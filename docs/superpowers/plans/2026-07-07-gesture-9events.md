# 9-Event 手势控制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 7 个 gesture 基础上,新增 9 个事件(4 指尖触碰 × 2 手 + 1 双手十指相扣),保持旧 gesture 行为不变,UI 加 9 行 combo box,dual 模式才生效。

**Architecture:** 在 `GestureSemantics` 加 `_detect_tip_touches()` + `_detect_interlock()` 两个独立分类函数。9 事件作为新事件流输出,event dict 用 `type: "tip_touch"|"interlock"` 区分;`_process_one_hand` 新增 step 4;`process()` 末尾加 cross-slot interlock 检测。`gesture_bridge` 据 `type` 路由到 `tip_bindings` dict。UI 加 9 行 combo + dual mode disable。

**Tech Stack:** Python 3.12 / PySide6 / Pytest / MediaPipe Tasks HandLandmarker

## Global Constraints

- 现有 191 测试不破(只增不改)
- dual mode off 时 9 事件不触发(graceful no-op,不发空事件)
- 9 事件与 7 旧 gesture 共享 rising-edge + cooldown 机制,但冷却槽独立(`static_cooldown_until` vs `tip_cooldown_until` vs `interlock_cooldown_until`)
- 所有距离归一化用现有 `_hand_size()`(夹紧 [0.05, 0.5])
- 阈值抽到 `cfg.sensitivity`(用户可调)
- 中文注释风格沿用现有代码

---

## File Structure

### Modified files
- `pc_gesture/config.py` — 加 `TIP_GESTURES`、`DEFAULT_TIP_BINDINGS`、4 个 sensitivity 字段、`tip_bindings` 顶层字段
- `pc_gesture/semantics.py` — `HandState` 增 4 字段、新增 `_detect_tip_touches` / `_detect_interlock` / `_interlock_start` 状态、`_process_one_hand` 增 step 4、`process()` 增 slot_lms 收集 + interlock 检测
- `ppt_core/gesture_bridge.py` — `_on_gesture_event` 据 `type` 路由
- `ppt_qt/pages/gesture_page.py` — `_TIP_GESTURE_META`、`_build_gesture_tab` 加 9 行 combo + dual mode disable

### New files
- `tests/test_tip_touch_gestures.py` — 16 个新测试

---

### Task 1: Add new config fields and bindings

**Files:**
- Modify: `pc_gesture/config.py:22-105` (加 `TIP_GESTURES`、`DEFAULT_TIP_BINDINGS`、sensitivity 4 字段、`tip_bindings` 顶层字段)
- Modify: `pc_gesture/config.py:117-258` (GestureConfig 加 `tip_bindings` 属性 + `get_tip_binding`/`set_tip_binding` 方法)
- Test: `tests/test_tip_touch_gestures.py`(新建)

**Interfaces:**
- Consumes: 现有 `DEFAULT_GESTURE_CONFIG` 结构
- Produces:
  - `TIP_GESTURES`: tuple of 9 str (新事件名)
  - `DEFAULT_TIP_BINDINGS: Dict[str, Optional[str]]` (9 个默认绑定)
  - `cfg.sensitivity.tip_touch_ratio: float` (默认 0.55)
  - `cfg.sensitivity.interlock_max_wrist_dist: float` (默认 0.20)
  - `cfg.sensitivity.interlock_max_tip_dist: float` (默认 0.40)
  - `cfg.sensitivity.interlock_min_dwell_s: float` (默认 0.3)
  - `cfg.tip_bindings: Dict[str, Optional[str]]` (运行时绑定,可改)
  - `cfg.get_tip_binding(gesture: str) -> Optional[str]`
  - `cfg.set_tip_binding(gesture: str, action: Optional[str]) -> None`

- [ ] **Step 1: Write the failing test for new config fields**

Create `tests/test_tip_touch_gestures.py` with these imports at the top:

```python
"""Tests for 9-event gesture system (info.txt 9-events design)."""
from pc_gesture.config import (
    DEFAULT_GESTURE_CONFIG,
    DEFAULT_TIP_BINDINGS,
    TIP_GESTURES,
    GestureConfig,
)
```

Add test at the end of the file:

```python
def test_tip_gestures_enum_has_nine():
    """9 个事件: 4 × 2 + 1 interlock"""
    assert len(TIP_GESTURES) == 9
    assert "L_HAND_INDEX" in TIP_GESTURES
    assert "L_HAND_MIDDLE" in TIP_GESTURES
    assert "L_HAND_RING" in TIP_GESTURES
    assert "L_HAND_PINKY" in TIP_GESTURES
    assert "R_HAND_INDEX" in TIP_GESTURES
    assert "R_HAND_MIDDLE" in TIP_GESTURES
    assert "R_HAND_RING" in TIP_GESTURES
    assert "R_HAND_PINKY" in TIP_GESTURES
    assert "HANDS_INTERLOCK" in TIP_GESTURES


def test_default_tip_bindings_have_all_nine():
    """每个 tip 事件都有默认 binding(可能 None)"""
    assert len(DEFAULT_TIP_BINDINGS) == 9
    for g in TIP_GESTURES:
        assert g in DEFAULT_TIP_BINDINGS
        v = DEFAULT_TIP_BINDINGS[g]
        assert v is None or isinstance(v, str)


def test_sensitivity_has_new_fields():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    s = cfg.sensitivity
    assert s["tip_touch_ratio"] == 0.55
    assert s["interlock_max_wrist_dist"] == 0.20
    assert s["interlock_max_tip_dist"] == 0.40
    assert s["interlock_min_dwell_s"] == 0.3


def test_tip_bindings_attribute_round_trip():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    # 读默认
    assert cfg.tip_bindings["L_HAND_INDEX"] == "NEXT_PAGE"
    # 改
    cfg.set_tip_binding("L_HAND_INDEX", "BLACK_SCREEN")
    assert cfg.get_tip_binding("L_HAND_INDEX") == "BLACK_SCREEN"
    # 写盘
    cfg.set_tip_binding("L_HAND_MIDDLE", None)
    assert cfg.get_tip_binding("L_HAND_MIDDLE") is None


def test_set_tip_binding_rejects_unknown_gesture():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("UNKNOWN_GESTURE", "NEXT_PAGE")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")


def test_set_tip_binding_rejects_unknown_action():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("L_HAND_INDEX", "FAKE_ACTION")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -v`

Expected: ImportError on `TIP_GESTURES`/`DEFAULT_TIP_BINDINGS` (FAIL)

- [ ] **Step 3: Add new constants to config.py**

Modify `pc_gesture/config.py` to add after line 39 (after `DEFAULT_BINDINGS`):

```python
# 9 个 tip-touch 事件(单手 × 4 指尖 × 2 + 双手 interlock)
# 见 docs/superpowers/specs/2026-07-07-gesture-9events-design.md
TIP_GESTURES = (
    "L_HAND_INDEX", "L_HAND_MIDDLE", "L_HAND_RING", "L_HAND_PINKY",
    "R_HAND_INDEX", "R_HAND_MIDDLE", "R_HAND_RING", "R_HAND_PINKY",
    "HANDS_INTERLOCK",
)

DEFAULT_TIP_BINDINGS: Dict[str, Optional[str]] = {
    "L_HAND_INDEX":     "NEXT_PAGE",
    "L_HAND_MIDDLE":    "PREV_PAGE",
    "L_HAND_RING":      "FULL_SCREEN",
    "L_HAND_PINKY":     "FROM_CURRENT",
    "R_HAND_INDEX":     "BLACK_SCREEN",
    "R_HAND_MIDDLE":    "WHITE_SCREEN",
    "R_HAND_RING":      "EXIT",
    "R_HAND_PINKY":     "SCREENSHOT",
    "HANDS_INTERLOCK":  "OPEN_PPT",
}
```

Modify `pc_gesture/config.py` `DEFAULT_GESTURE_CONFIG["sensitivity"]` to add 4 new fields before the closing brace (around line 97):

```python
        # 配对判定:某 slot pointing_up 持续此秒数即认为配对成功
        "pairing_pointing_up_s": 1.0,
        # 配对窗口:从 start_pairing 算起,此秒数内未确认则超时
        "pairing_window_ms": 3000,
        # info.txt 9-events: 9 个新事件阈值
        # 拇指尖到目标指尖的归一化距离阈值(单手 tip_touch)
        "tip_touch_ratio": 0.55,
        # 双手 interlock 检测:两 wrist 归一化距离上限
        "interlock_max_wrist_dist": 0.20,
        # 双手 interlock:10 指尖两两均值距离上限(归一化)
        "interlock_max_tip_dist": 0.40,
        # 双手 interlock:最小持续秒数(防误触)
        "interlock_min_dwell_s": 0.3,
```

Modify `pc_gesture/config.py` `DEFAULT_GESTURE_CONFIG` to add a top-level `tip_bindings` key after `"bindings"` (line 59):

```python
    "bindings": dict(DEFAULT_BINDINGS),
    "tip_bindings": dict(DEFAULT_TIP_BINDINGS),  # 9 个 tip 事件独立绑定
    "sensitivity": {
```

- [ ] **Step 4: Add tip_bindings property + getter/setter to GestureConfig**

Modify `pc_gesture/config.py` GestureConfig class. Add to `__post_init__` (after the `self.raw["bindings"] = out` block, around line 141):

```python
        # tip_bindings 同步(类似 bindings,缺失键用默认填)
        raw_tip = self.raw.get("tip_bindings") if isinstance(self.raw, dict) else None
        merged_tip: Dict[str, Optional[str]] = dict(DEFAULT_TIP_BINDINGS)
        if isinstance(raw_tip, dict):
            for g in TIP_GESTURES:
                if g in raw_tip:
                    v = raw_tip[g]
                    merged_tip[g] = v if (v is None or v in ACTIONS) else None
        self.tip_bindings = merged_tip
        if isinstance(self.raw, dict):
            self.raw["tip_bindings"] = dict(self.tip_bindings)
```

Add new methods after `set_binding` / `get_binding` (around line 211):

```python
    # ----- tip_bindings (9-event) -----
    def set_tip_binding(self, gesture: str, action: Optional[str]) -> None:
        if gesture not in TIP_GESTURES:
            raise ValueError(f"unknown tip gesture: {gesture!r}")
        if action is not None and action not in ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
        self.tip_bindings[gesture] = action
        if isinstance(self.raw, dict):
            self.raw["tip_bindings"] = dict(self.tip_bindings)

    def get_tip_binding(self, gesture: str) -> Optional[str]:
        return self.tip_bindings.get(gesture)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -v`

Expected: 6 tests pass

- [ ] **Step 6: Run full test suite to ensure no regression**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 191 + 6 = 197 tests pass

- [ ] **Step 7: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(config): add 9-event tip_bindings schema and 4 sensitivity fields

- TIP_GESTURES: 9 enum (4 L/R single-hand + interlock)
- DEFAULT_TIP_BINDINGS: default mapping
- 4 new cfg.sensitivity fields: tip_touch_ratio=0.55, interlock_max_*=0.20/0.40, interlock_min_dwell_s=0.3
- GestureConfig.tip_bindings property + get/set_tip_binding methods
- 6 new tests cover schema + round-trip + validation

Tests: 197 passed (191 existing + 6 new)"
```

---

### Task 2: Extend HandState with new fields

**Files:**
- Modify: `pc_gesture/semantics.py:66-79` (HandState 加 4 字段)
- Test: 追加测试到 `tests/test_tip_touch_gestures.py`

**Interfaces:**
- Consumes: 现有 `HandState` dataclass
- Produces: 新字段
  - `HandState.last_tip_gesture: str` 默认 `"NONE"`
  - `HandState.tip_cooldown_until: float` 默认 `0.0`
  - `HandState.last_interlock_gesture: str` 默认 `"NONE"`
  - `HandState.interlock_cooldown_until: float` 默认 `0.0`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
def test_handstate_has_new_tip_fields():
    """9 事件需要新的 last_gesture 和 cooldown 字段"""
    from pc_gesture.semantics import HandState
    st = HandState(slot="A")
    assert st.last_tip_gesture == "NONE"
    assert st.tip_cooldown_until == 0.0
    assert st.last_interlock_gesture == "NONE"
    assert st.interlock_cooldown_until == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py::test_handstate_has_new_tip_fields -v`

Expected: AttributeError on `last_tip_gesture`

- [ ] **Step 3: Add fields to HandState**

Modify `pc_gesture/semantics.py` HandState class (lines 66-79), add 4 fields before the closing of the class body:

```python
@dataclass
class HandState:
    slot: str = ""                                   # "A" or "B"
    last_seen_monotonic: float = 0.0
    # 上一次识别的手势类别(用于防抖/冷却)
    last_static_gesture: str = "NONE"                # OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM / NONE
    last_static_at: float = 0.0                      # 上一次识别到非 NONE 手势的 wall-clock,用于 auto-reset
    static_cooldown_until: float = 0.0
    # 9-event 字段(9-events design spec 2026-07-07)
    last_tip_gesture: str = "NONE"                   # L/R_HAND_INDEX|MIDDLE|RING|PINKY|NONE
    tip_cooldown_until: float = 0.0                  # 9 事件独立冷却
    last_interlock_gesture: str = "NONE"             # slot A 上的 interlock 状态(单一)
    interlock_cooldown_until: float = 0.0            # interlock 独立冷却
    # 捏合迟滞
    pinching: bool = False
    # 激光上一帧坐标(用于 EMA)
    laser_last_xy: Optional[Tuple[float, float]] = None
    # 配对确认累计:某 slot 在 pointing_up 上稳定了多久
    pointing_up_start: Optional[float] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py::test_handstate_has_new_tip_fields -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 198 tests pass (191 + 7 new)

- [ ] **Step 6: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(semantics): extend HandState with 9-event tip/interlock fields

- last_tip_gesture / tip_cooldown_until: 8 single-hand tip_touch events
- last_interlock_gesture / interlock_cooldown_until: cross-slot interlock

Tests: 198 passed (191 + 7 new)"
```

---

### Task 3: Implement _detect_tip_touches (single-hand)

**Files:**
- Modify: `pc_gesture/semantics.py:170-318` (after `_classify_static`, add `_detect_tip_touches`)
- Test: 追加到 `tests/test_tip_touch_gestures.py`

**Interfaces:**
- Consumes: `lm` (21 关键点) + `slot: str`
- Produces: `str` 9 个事件名之一或 `"NONE"`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _make_tip_hand(thumb_xy, target_tip_xy, wrist_xy=(0.3, 0.7)):
    """构造拇指尖与 target_tip 接近的手(其他手指位置随意)。

    wrist=(0.3, 0.7), MCP=(0.3, 0.5): hand_size = 0.2
    thumb_xy 与 target_tip_xy 距离 ≈ 0 → 触到
    """
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[0] = _P(*wrist_xy)  # WRIST
    for idx in (5, 9, 13, 17):  # MCP 全部相同
        lm[idx] = _P(0.3, 0.5)
    # 4 个指尖位置
    lm[8] = _P(0.5, 0.2)   # INDEX_TIP
    lm[12] = _P(0.6, 0.2)  # MIDDLE_TIP
    lm[16] = _P(0.7, 0.2)  # RING_TIP
    lm[20] = _P(0.8, 0.2)  # PINKY_TIP
    # 4 个 PIP(无影响)
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        lm[pip_idx] = _P(0.5, 0.3)
    # 拇指尖
    lm[4] = _P(*thumb_xy)
    return lm


def test_detect_tip_touch_index():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖 = INDEX_TIP = (0.5, 0.2),hand_size=0.2 → dist 归一化=0
    lm = _make_tip_hand((0.5, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_INDEX"


def test_detect_tip_touch_middle():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.6, 0.2), (0.6, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_MIDDLE"


def test_detect_tip_touch_ring():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.7, 0.2), (0.7, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_RING"


def test_detect_tip_touch_pinky():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.8, 0.2), (0.8, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_PINKY"


def test_detect_tip_touch_no_contact_returns_none():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖在 (0.1, 0.2),离最近 INDEX_TIP=(0.5, 0.2) 距离 0.4
    # hand_size = 0.2,归一化 0.4/0.2 = 2.0,远超 0.55 阈值
    lm = _make_tip_hand((0.1, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "NONE"


def test_detect_tip_touch_slot_b_uses_r_prefix():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # slot B 的同名触食指应该返回 R_HAND_INDEX
    lm = _make_tip_hand((0.5, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "B") == "R_HAND_INDEX"


def test_detect_tip_touch_threshold_via_config():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    # 调小阈值,让边缘接触也能识别
    cfg.raw["sensitivity"]["tip_touch_ratio"] = 1.0
    sem = GestureSemantics(cfg)
    # 拇指尖 (0.55, 0.2), INDEX_TIP (0.5, 0.2),归一化距离 0.05/0.2 = 0.25
    # 默认 0.55 阈值 → 不触发;调 1.0 → 触发
    lm = _make_tip_hand((0.55, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_INDEX"


def test_detect_tip_touch_chooses_nearest():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖 (0.6, 0.2),离 MIDDLE_TIP (0.6, 0.2) 最近(0 距离)
    # 与 INDEX_TIP (0.5, 0.2) 距离 0.1,归一化 0.5(超过 0.55 阈值);
    # 与 RING/PINKY 更远。所以应选 MIDDLE
    lm = _make_tip_hand((0.6, 0.2), (0.6, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_MIDDLE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "detect_tip_touch" -v`

Expected: AttributeError on `_detect_tip_touches` (8 FAIL)

- [ ] **Step 3: Implement _detect_tip_touches**

Modify `pc_gesture/semantics.py`, add after `_classify_static` (line 318, before `_is_pinching` at line 320):

```python
    def _detect_tip_touches(self, lm, slot: str) -> str:
        """9-events design spec 2026-07-07: 单手指尖触碰检测。

        拇指尖到 4 个指尖的归一化距离,选最近;距离 < tip_touch_ratio 触发。
        返回 8 个 L/R_HAND_* 事件之一或 "NONE"。
        """
        if not lm or len(lm) < 21:
            return "NONE"
        try:
            size = self._hand_size(lm)
            threshold = float(self.cfg.sensitivity.get("tip_touch_ratio", 0.55))
        except (TypeError, ValueError):
            return "NONE"
        thumb_tip = lm[THUMB_TIP]
        prefix = "L_HAND" if slot == "A" else "R_HAND"
        candidates = [
            (f"{prefix}_INDEX",  lm[INDEX_TIP]),
            (f"{prefix}_MIDDLE", lm[MIDDLE_TIP]),
            (f"{prefix}_RING",   lm[RING_TIP]),
            (f"{prefix}_PINKY",  lm[PINKY_TIP]),
        ]
        try:
            dists = [
                (name, _dist(thumb_tip.x, thumb_tip.y, tip.x, tip.y) / size)
                for name, tip in candidates
            ]
        except (TypeError, AttributeError):
            return "NONE"
        name, d = min(dists, key=lambda x: x[1])
        if d < threshold:
            return name
        return "NONE"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "detect_tip_touch" -v`

Expected: 8 tests pass

- [ ] **Step 5: Run full test suite to ensure no regression**

Run: `cd C:/Users/gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 198 + 8 = 206 tests pass

(Note: the path here is wrong, use the actual project path)

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q
```

Expected: 206 tests pass

- [ ] **Step 6: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(semantics): add _detect_tip_touches for 8 single-hand events

8 new events: L/R_HAND_{INDEX,MIDDLE,RING,PINKY}
- thumb_tip 到目标指尖归一化距离,选最近
- 距离 < cfg.sensitivity.tip_touch_ratio(默认 0.55) 触发
- slot A 产 L_*,slot B 产 R_*

8 new tests cover all 4 fingers × 2 slots + threshold + no-contact

Tests: 206 passed (191 + 15 new)"
```

---

### Task 4: Implement _detect_interlock (cross-slot)

**Files:**
- Modify: `pc_gesture/semantics.py` (after `_detect_tip_touches`, add `_detect_interlock` and `_interlock_start` state)
- Test: 追加到 `tests/test_tip_touch_gestures.py`

**Interfaces:**
- Consumes: `lm_a`, `lm_b` (两手 landmarks, 可能 None) + `now: float` (monotonic)
- Produces: `bool` 是否持续 interlock 状态
- Side effect: 维护 `self._interlock_start` 实例属性

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
def _make_two_hands_close():
    """构造两手相距近 + 10 指尖两两距离近 → 满足 interlock 条件。"""
    a = [_P(0.0, 0.0) for _ in range(21)]
    a[0] = _P(0.3, 0.5)  # WRIST
    a[5] = a[9] = a[13] = a[17] = _P(0.35, 0.4)  # MCP
    a[8] = _P(0.4, 0.3)  # INDEX_TIP
    a[12] = _P(0.42, 0.32)  # MIDDLE_TIP
    a[16] = _P(0.44, 0.34)  # RING_TIP
    a[20] = _P(0.46, 0.36)  # PINKY_TIP
    a[4] = _P(0.38, 0.35)  # THUMB_TIP
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        a[pip_idx] = _P(0.4, 0.4)

    b = [_P(0.0, 0.0) for _ in range(21)]
    b[0] = _P(0.5, 0.5)  # WRIST(距 a 的 wrist 0.2)
    b[5] = b[9] = b[13] = b[17] = _P(0.45, 0.4)
    b[8] = _P(0.4, 0.3)
    b[12] = _P(0.42, 0.32)
    b[16] = _P(0.44, 0.34)
    b[20] = _P(0.46, 0.36)
    b[4] = _P(0.42, 0.35)
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        b[pip_idx] = _P(0.4, 0.4)
    return a, b


def test_detect_interlock_two_hands_close():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 第一次调用,设 _interlock_start
    assert sem._detect_interlock(a, b, time.monotonic()) is False
    # 持续 0.3s 后再调 → True
    time.sleep(0.35)
    assert sem._detect_interlock(a, b, time.monotonic()) is True


def test_detect_interlock_requires_both_hands():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, _ = _make_two_hands_close()
    assert sem._detect_interlock(a, None, time.monotonic()) is False
    assert sem._detect_interlock(None, a, time.monotonic()) is False


def test_detect_interlock_dwell_time():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 第一次调用,设 start;0.1s 内调,dwell 未到 → False
    t0 = time.monotonic()
    sem._detect_interlock(a, b, t0)
    assert sem._detect_interlock(a, b, t0 + 0.1) is False
    # 0.3s 后 → True
    assert sem._detect_interlock(a, b, t0 + 0.35) is True


def test_detect_interlock_wrist_too_far():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 把 b 的 wrist 拉到远处
    b[0] = _P(0.9, 0.9)
    t0 = time.monotonic()
    sem._detect_interlock(a, b, t0)
    time.sleep(0.4)
    assert sem._detect_interlock(a, b, time.monotonic()) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "interlock" -v`

Expected: AttributeError on `_detect_interlock` (4 FAIL)

- [ ] **Step 3: Implement _detect_interlock**

Modify `pc_gesture/semantics.py`, add after `_detect_tip_touches`:

```python
    def _detect_interlock(self, lm_a, lm_b, now: float) -> bool:
        """9-events design spec 2026-07-07: 双手十指相扣检测。

        3 个条件(任一不满足返回 False):
        1. 两 wrist 距离 < interlock_max_wrist_dist(默认 0.20,归一化坐标)
        2. 10 指尖两两均值距离 < interlock_max_tip_dist(默认 0.40,归一化坐标)
        3. 上述条件持续 ≥ interlock_min_dwell_s(默认 0.3s)

        维护 self._interlock_start 实例属性(条件首次同时满足的时间)。
        """
        if not lm_a or not lm_b or len(lm_a) < 21 or len(lm_b) < 21:
            self._interlock_start = None
            return False
        try:
            sens = self.cfg.sensitivity
            max_wrist = float(sens.get("interlock_max_wrist_dist", 0.20))
            max_tip = float(sens.get("interlock_max_tip_dist", 0.40))
            dwell = float(sens.get("interlock_min_dwell_s", 0.3))
        except (TypeError, ValueError):
            return False
        wrist_d = _dist(lm_a[WRIST], lm_b[WRIST])
        if wrist_d > max_wrist:
            self._interlock_start = None
            return False
        tips_a = [lm_a[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        tips_b = [lm_b[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        cross = [
            _dist(a.x, a.y, b.x, b.y)
            for a in tips_a for b in tips_b
        ]
        if sum(cross) / len(cross) > max_tip:
            self._interlock_start = None
            return False
        # 两条件满足,dwell 检查
        if self._interlock_start is None:
            self._interlock_start = now
            return False
        return (now - self._interlock_start) >= dwell
```

Note: thresholds are absolute (归一化坐标直接比较),not divided by hand_size.
`WRIST`, `THUMB_TIP`, `INDEX_TIP`, `MIDDLE_TIP`, `RING_TIP`, `PINKY_TIP` are already defined as module-level constants at top of `semantics.py` (lines 35-56).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "interlock" -v`

Expected: 4 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 210 tests pass (191 + 19 new)

- [ ] **Step 6: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(semantics): add _detect_interlock for HANDS_INTERLOCK

3 conditions for interlock:
1. 两 wrist 归一化距离 < interlock_max_wrist_dist(默认 0.20)
2. 10 指尖两两均值距离 < interlock_max_tip_dist(默认 0.40)
3. 持续 ≥ interlock_min_dwell_s(默认 0.3s,防误触)

self._interlock_start 维护 dwell 计时起点。

4 new tests cover happy path / 缺手 / dwell 不足 / wrist 太远

Tests: 210 passed (191 + 19 new)"
```

---

### Task 5: Wire 9 events into process() with rising-edge + cooldown

**Files:**
- Modify: `pc_gesture/semantics.py` (在 `process()` 收集 `slot_lms`,在 `_process_one_hand` 加 step 4,在 `process()` 末尾加 interlock 检测)
- Test: 追加到 `tests/test_tip_touch_gestures.py`

**Interfaces:**
- Consumes: 现有 `process()` / `_process_one_hand` 流程
- Produces: 新事件 dict `{"event_class": "tip_touch"|"interlock", "type": ..., "gesture": <enum>, "slot": <slot>, "ts", "ts_ms", "source"}`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
def test_process_emits_tip_touch_in_dual_mode():
    """dual 模式 + 拇指触食指 → L_HAND_INDEX 事件"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    sem = GestureSemantics(cfg)
    # 模拟 slot A 手(wrist 在画面左侧)
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))
    lm_b = [_P(0.0, 0.0) for _ in range(21)]  # 另一只手不可见
    events = sem.process([lm_a, lm_b], [[], []])
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    assert len(tip_events) == 1
    assert tip_events[0]["gesture"] == "L_HAND_INDEX"
    assert tip_events[0]["slot"] == "A"


def test_process_no_tip_touch_in_single_mode_for_R_prefix():
    """single 模式只产 L_*(slot A),即使给两手 landmarks 也只识别 A 槽"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "single"
    sem = GestureSemantics(cfg)
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))  # 左侧
    lm_b = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.7, 0.7))  # 右侧
    events = sem.process([lm_a, lm_b], [[], []])
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    # single 模式 _process_one_hand 只调 A 槽,所以即使有两手也只产 L_*
    for e in tip_events:
        assert e["gesture"].startswith("L_HAND_")


def test_process_tip_touch_cooldown_independent_from_static():
    """tip 事件冷却独立于 7 旧 gesture 冷却"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    import time
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    cfg.raw["sensitivity"]["gesture_cooldown_ms"] = 400
    sem = GestureSemantics(cfg)
    # 第 1 帧:slot A 触食指
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))
    lm_b = [_P(0.0, 0.0) for _ in range(21)]
    events1 = sem.process([lm_a, lm_b], [[], []])
    assert any(e.get("type") == "tip_touch" for e in events1)
    # 第 2 帧(立刻,小于 400ms 冷却):tip 应该被挡
    events2 = sem.process([lm_a, lm_b], [[], []])
    assert not any(e.get("type") == "tip_touch" for e in events2)


def test_process_emits_interlock_event():
    """双手 interlock 触发 HANDS_INTERLOCK"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    import time
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    sem = GestureSemantics(cfg)
    a, b = _make_two_hands_close()
    # 第 1 帧:初始化 dwell
    sem.process([a, b], [[], []])
    # 0.4s 后:interlock 触发
    time.sleep(0.4)
    events = sem.process([a, b], [[], []])
    interlock_events = [e for e in events if e.get("type") == "interlock"]
    assert len(interlock_events) == 1
    assert interlock_events[0]["gesture"] == "HANDS_INTERLOCK"
    assert interlock_events[0]["slot"] == "BOTH"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "process_emits or process_no_tip or process_tip_touch_cooldown" -v`

Expected: 4 tests FAIL (no events with type=tip_touch/interlock)

- [ ] **Step 3: Modify process() to collect slot_lms**

Modify `pc_gesture/semantics.py` `process()` (around line 364), in the iteration loop, add `slot_lms` dict:

Find the loop:
```python
        if hand_landmarks_list:
            for idx, lm_list in enumerate(hand_landmarks_list):
                if not lm_list or len(lm_list) < 21:
                    continue
                # 过滤低置信度
                confidence = 1.0
                if handedness_list and idx < len(handedness_list):
                    h = handedness_list[idx]
                    if h:
                        try:
                            confidence = float(h[0].score)
                        except (AttributeError, IndexError, TypeError, ValueError):
                            confidence = 1.0
                if confidence < min_confidence:
                    # 跳过此手,但不让手部消失清理逻辑误清
                    # active_slots 不加 → 走 hand-leave 清理路径
                    continue
                slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
                st = self._slots[slot]
                st.last_seen_monotonic = now
                active_slots.add(slot)
                events.extend(self._process_one_hand(lm_list, slot, st, sens, now))
```

Replace with:
```python
        slot_lms: Dict[str, list] = {}  # 9-events: 收集 per-slot 关键点给 interlock 用
        if hand_landmarks_list:
            for idx, lm_list in enumerate(hand_landmarks_list):
                if not lm_list or len(lm_list) < 21:
                    continue
                # 过滤低置信度
                confidence = 1.0
                if handedness_list and idx < len(handedness_list):
                    h = handedness_list[idx]
                    if h:
                        try:
                            confidence = float(h[0].score)
                        except (AttributeError, IndexError, TypeError, ValueError):
                            confidence = 1.0
                if confidence < min_confidence:
                    # 跳过此手,但不让手部消失清理逻辑误清
                    # active_slots 不加 → 走 hand-leave 清理路径
                    continue
                slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
                st = self._slots[slot]
                st.last_seen_monotonic = now
                active_slots.add(slot)
                slot_lms[slot] = lm_list  # 9-events: 保存
                events.extend(self._process_one_hand(lm_list, slot, st, sens, now))
```

- [ ] **Step 4: Add step 4 to _process_one_hand**

Modify `pc_gesture/semantics.py` `_process_one_hand`. Find the end of step 3 (捏合, around line 553, before `return events`):

```python
        else:
            # 不允许该槽位产生捏合 → 重置
            st.pinching = False

        return events
```

Replace with:
```python
        else:
            # 不允许该槽位产生捏合 → 重置
            st.pinching = False

        # ----- 4) 9-event tip_touch 通道(独立于 7 旧 gesture) -----
        # spec 2026-07-07:仅 dual 模式生效;冷却与 static 独立
        if operator_mode == "dual":
            try:
                cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))
            except (TypeError, ValueError):
                cooldown_ms = 400
            tip = self._detect_tip_touches(lm, slot)
            if tip and tip != st.last_tip_gesture:
                if now >= st.tip_cooldown_until and cooldown_ms > 0:
                    events.append({
                        "event_class": "tip_touch",
                        "type": "tip_touch",
                        "gesture": tip,
                        "slot": slot,
                        "ts": ts, "ts_ms": ts_ms,
                        "source": f"gesture:{slot}",
                    })
                    st.tip_cooldown_until = now + cooldown_ms / 1000.0
            st.last_tip_gesture = tip

        return events
```

- [ ] **Step 5: Add cross-slot interlock detection to process()**

Modify `pc_gesture/semantics.py` `process()`. Find the cleanup loop:

```python
        for slot, st in self._slots.items():
            if slot not in active_slots:
                if now - st.last_seen_monotonic > hand_lost_s:
                    st.pinching = False
                    st.laser_last_xy = None
                    st.pointing_up_start = None
                    # 重置手势状态,让手重新入画面能立即响应
                    st.last_static_gesture = self.G_NONE
                    st.last_static_at = 0.0
                    st.static_cooldown_until = 0.0

        return events
```

Replace with:
```python
        for slot, st in self._slots.items():
            if slot not in active_slots:
                if now - st.last_seen_monotonic > hand_lost_s:
                    st.pinching = False
                    st.laser_last_xy = None
                    st.pointing_up_start = None
                    # 重置手势状态,让手重新入画面能立即响应
                    st.last_static_gesture = self.G_NONE
                    st.last_static_at = 0.0
                    st.static_cooldown_until = 0.0
                    # 9-events:重置 tip/interlock 冷却
                    st.last_tip_gesture = self.G_NONE
                    st.tip_cooldown_until = 0.0
                    st.last_interlock_gesture = self.G_NONE
                    st.interlock_cooldown_until = 0.0

        # 9-events: cross-slot interlock 检测(仅 dual)
        operator_mode = self.cfg.operator_mode
        if operator_mode == "dual":
            try:
                cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))
            except (TypeError, ValueError):
                cooldown_ms = 400
            lm_a = slot_lms.get("A")
            lm_b = slot_lms.get("B")
            interlock_hit = self._detect_interlock(lm_a, lm_b, now)
            st_a = self._slots["A"]
            self._interlock_state = "HANDS_INTERLOCK" if interlock_hit else "NONE"
            if interlock_hit and self._interlock_state != st_a.last_interlock_gesture:
                if now >= st_a.interlock_cooldown_until and cooldown_ms > 0:
                    events.append({
                        "event_class": "interlock",
                        "type": "interlock",
                        "gesture": "HANDS_INTERLOCK",
                        "slot": "BOTH",
                        "ts": now, "ts_ms": int(now * 1000),
                        "source": "gesture:interlock",
                    })
                    st_a.interlock_cooldown_until = now + cooldown_ms / 1000.0
            st_a.last_interlock_gesture = self._interlock_state

        return events
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "process" -v`

Expected: 4 tests pass

- [ ] **Step 7: Run full test suite to ensure no regression**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 214 tests pass (191 + 23 new)

- [ ] **Step 8: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(semantics): wire 9 events into process() with rising-edge + cooldown

- slot_lms dict 收集 per-slot 关键点(cross-slot interlock 用)
- _process_one_hand step 4:dual 模式产 8 个 L/R_HAND_* tip_touch 事件
- process() 末尾:cross-slot HANDS_INTERLOCK 事件
- 冷却独立:tip_cooldown_until / interlock_cooldown_until 与 static_cooldown_until 不共享
- hand-leave cleanup 重置 4 个新字段

4 new tests cover dual 模式 / single 模式限制 / 冷却独立 / interlock 触发

Tests: 214 passed (191 + 23 new)"
```

---

### Task 6: Update gesture_bridge to route tip_bindings

**Files:**
- Modify: `ppt_core/gesture_bridge.py:_on_gesture_event` (据 `type` 字段路由)
- Test: 追加到 `tests/test_tip_touch_gestures.py`

**Interfaces:**
- Consumes: 现有 `_on_gesture_event` 接收 event dict
- Produces: 据 `type`:
  - `gesture` → `cfg.get_binding(gesture)`(已有)
  - `tip_touch` / `interlock` → `cfg.get_tip_binding(gesture)`
  - `gesture_end` → 仅记录,不派发

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
class _FakeDispatcher:
    def __init__(self):
        self.calls = []
    def dispatch(self, payload):
        self.calls.append(payload)


def test_bridge_routes_tip_touch_to_tip_binding():
    """tip_touch 事件路由到 tip_bindings,不是 bindings"""
    from ppt_core.gesture_bridge import GestureBridge
    dispatcher = _FakeDispatcher()
    bridge = GestureBridge(dispatcher=dispatcher, on_status=lambda t: None, on_fps=lambda f: None)
    # 改 tip binding
    bridge.cfg.set_tip_binding("L_HAND_INDEX", "BLACK_SCREEN")
    # 触发 tip_touch 事件
    bridge._on_gesture_event({
        "type": "tip_touch",
        "gesture": "L_HAND_INDEX",
        "slot": "A",
        "ts": 0.0, "ts_ms": 0,
    })
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["cmd"] == "BLACK_SCREEN"


def test_bridge_routes_interlock_to_tip_binding():
    """interlock 事件路由到 tip_bindings"""
    from ppt_core.gesture_bridge import GestureBridge
    dispatcher = _FakeDispatcher()
    bridge = GestureBridge(dispatcher=dispatcher, on_status=lambda t: None, on_fps=lambda f: None)
    bridge.cfg.set_tip_binding("HANDS_INTERLOCK", "EXIT")
    bridge._on_gesture_event({
        "type": "interlock",
        "gesture": "HANDS_INTERLOCK",
        "slot": "BOTH",
        "ts": 0.0, "ts_ms": 0,
    })
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["cmd"] == "EXIT"


def test_bridge_routes_old_gesture_to_binding():
    """7 旧 gesture 继续走 bindings(回归测试)"""
    from ppt_core.gesture_bridge import GestureBridge
    dispatcher = _FakeDispatcher()
    bridge = GestureBridge(dispatcher=dispatcher, on_status=lambda t: None, on_fps=lambda f: None)
    # 默认 OK 绑 NEXT_PAGE
    bridge._on_gesture_event({
        "type": "gesture",
        "gesture": "OK",
        "slot": "A",
        "ts": 0.0, "ts_ms": 0,
    })
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["cmd"] == "NEXT_PAGE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "bridge_routes" -v`

Expected: 3 tests FAIL (gesture_bridge 不识别 type=tip_touch/interlock)

- [ ] **Step 3: Update _on_gesture_event to dispatch by type**

Modify `ppt_core/gesture_bridge.py:_on_gesture_event` (around line 117). Find:

```python
    def _on_gesture_event(self, ev: dict, source: str = "gesture") -> None:
        """Engine raw gesture event entry: filter + binding lookup + dispatch.

        The engine always invokes ``dispatch_fn(event, source)`` (see
        :meth:`pc_gesture.engine.GestureEngine._safe_dispatch`), so the second
        positional ``source`` argument must be accepted even though we only
        use the event payload here.

        kasi.txt [36]:之前 7 个 print 在热路径(每次 gesture event 都打),
        双人模式 slot B 每次识别都打,持续几百次/秒 print + I/O。
        加 debug_log 门控,默认关。
        """
        if not isinstance(ev, dict):
            return
        if ev.get("type") != "gesture":
            return
        gesture = ev.get("gesture")
        slot = ev.get("slot", "A")
        # kasi.txt [36]:debug_log 默认 False,热路径只读一次
        debug = bool(self._cfg.sensitivity.get("debug_log", False))
        if slot != "A":
            if debug:
                print(f"[bridge] ignored slot={slot} gesture={gesture} (only slot A fires)")
            return
        action = self._cfg.get_binding(gesture)
        # Always record what we recognized, regardless of teaching_mode —
        # the UI's trial panel and the tutorial dialog both poll
        # recent_gestures() and need to see recognition events.
        self._record_recognized_gesture(gesture, action, ev, source)
        # Teaching mode: skip the actual cmd dispatch but keep the recording.
        if self._teaching_mode:
            if debug:
                print(f"[bridge] 🎓 教学模式 → 识别 {gesture} 但跳过 dispatch")
            return
        if action:
            payload = _action_to_cmd(action, default_open_ppt_path="")
            if payload:
                if debug:
                    print(f"[bridge] ✅ {gesture} → {action} → dispatch {payload}")
                try:
                    self._dispatcher.dispatch(payload)
                except Exception as e:
                    # dispatch 失败应该始终打(罕见,可能是 bug)
                    print(f"[bridge] ❌ dispatch 失败: {e}")
        else:
            if debug:
                print(f"[bridge] ⚠️  {gesture} 识别成功但未绑定 action,跳过 dispatch")
```

Replace with:

```python
    def _on_gesture_event(self, ev: dict, source: str = "gesture") -> None:
        """Engine raw gesture event entry: filter + binding lookup + dispatch.

        9-events spec 2026-07-07:
          type="gesture"   → 7 旧 gesture 走 cfg.bindings
          type="tip_touch" → 8 单手事件走 cfg.tip_bindings
          type="interlock" → HANDS_INTERLOCK 走 cfg.tip_bindings
          type="gesture_end" → 仅记录,不入 dispatch
        """
        if not isinstance(ev, dict):
            return
        ev_type = ev.get("type")
        # gesture_end 不入 dispatch
        if ev_type == "gesture_end":
            return
        # type 不在已知集合 → 忽略
        if ev_type not in ("gesture", "tip_touch", "interlock"):
            return
        gesture = ev.get("gesture")
        slot = ev.get("slot", "A")
        debug = bool(self._cfg.sensitivity.get("debug_log", False))
        # 9-events: tip_touch / interlock 不受 slot=="A" 限制(双槽都可触发)
        if ev_type == "gesture" and slot != "A":
            if debug:
                print(f"[bridge] ignored slot={slot} gesture={gesture} (only slot A fires)")
            return
        # 9-events: 选 binding 来源
        if ev_type in ("tip_touch", "interlock"):
            action = self._cfg.get_tip_binding(gesture)
        else:
            action = self._cfg.get_binding(gesture)
        # Always record
        self._record_recognized_gesture(gesture, action, ev, source)
        if self._teaching_mode:
            if debug:
                print(f"[bridge] 🎓 教学模式 → 识别 {gesture} 但跳过 dispatch")
            return
        if action:
            payload = _action_to_cmd(action, default_open_ppt_path="")
            if payload:
                if debug:
                    print(f"[bridge] ✅ {gesture} → {action} → dispatch {payload}")
                try:
                    self._dispatcher.dispatch(payload)
                except Exception as e:
                    print(f"[bridge] ❌ dispatch 失败: {e}")
        else:
            if debug:
                print(f"[bridge] ⚠️  {gesture} 识别成功但未绑定 action,跳过 dispatch")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "bridge_routes" -v`

Expected: 3 tests pass

- [ ] **Step 5: Run full test suite**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 217 tests pass (191 + 26 new)

- [ ] **Step 6: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(bridge): route 9 events to tip_bindings

- type=gesture → cfg.bindings(7 旧)
- type=tip_touch / interlock → cfg.tip_bindings(9 新)
- type=gesture_end → 仅记录,不入 dispatch
- tip_touch/interlock 不受 slot==A 限制(双槽都可触发)

3 new tests cover 9-event routing + 7 旧 gesture 回归

Tests: 217 passed (191 + 26 new)"
```

---

### Task 7: Update UI to show 16 combo boxes + dual mode disable

**Files:**
- Modify: `ppt_qt/pages/gesture_page.py` (加 `_TIP_GESTURE_META`、`_build_gesture_tab` 加 9 行 combo)
- Test: 追加到 `tests/test_tip_touch_gestures.py`(需要 mock QApplication)

**Interfaces:**
- Consumes: 现有 `_build_gesture_tab` 流程
- Produces: 9 个新 combo box widget,挂在 `self._tip_combos` list,dual mode off 时 disable

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tip_touch_gestures.py`:

```python
def test_gesture_page_has_16_combos():
    """UI 应该有 7 旧 combo + 9 新 combo = 16 个"""
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ppt_qt.pages.gesture_page import GesturePage
    app = QApplication.instance() or QApplication([])
    from ppt_qt.bridge import QtBridge
    from ppt_core.gesture_bridge import GestureBridge
    bridge = GestureBridge(dispatcher=None, on_status=lambda t: None, on_fps=lambda f: None)
    page = GesturePage(bridge=bridge)
    # 7 旧 + 9 新
    assert len(page._binding_combos) == 7
    assert len(page._tip_combos) == 9
    # 默认 9 个新 combo 都 enable(operator_mode 默认为 single 时仍 enable,只不出事件)
    for combo in page._tip_combos:
        assert combo.isEnabled()


def test_gesture_page_disables_tip_combos_in_single_mode():
    """single 模式时 9 个新 combo 应该 disable(并 tooltip 提示)"""
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ppt_qt.pages.gesture_page import GesturePage
    from ppt_core.gesture_bridge import GestureBridge
    app = QApplication.instance() or QApplication([])
    bridge = GestureBridge(dispatcher=None, on_status=lambda t: None, on_fps=lambda f: None)
    bridge.cfg.raw["operator_mode"] = "single"
    page = GesturePage(bridge=bridge)
    for combo in page._tip_combos:
        assert not combo.isEnabled()
        assert "双人模式" in combo.toolTip()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "gesture_page" -v`

Expected: AttributeError on `_tip_combos` (2 FAIL)

- [ ] **Step 3: Add _TIP_GESTURE_META constant**

Modify `ppt_qt/pages/gesture_page.py` at top (after `_ACTION_LABEL` definition, around line 43):

```python
# 9-event 提示(emoji + 中文名)
_TIP_GESTURE_META = {
    "L_HAND_INDEX":    ("👆", "左手拇指触食指"),
    "L_HAND_MIDDLE":   ("🖕", "左手拇指触中指"),
    "L_HAND_RING":     ("💍", "左手拇指触无名指"),
    "L_HAND_PINKY":    ("🤙", "左手拇指触小拇指"),
    "R_HAND_INDEX":    ("👆", "右手拇指触食指"),
    "R_HAND_MIDDLE":   ("🖕", "右手拇指触中指"),
    "R_HAND_RING":     ("💍", "右手拇指触无名指"),
    "R_HAND_PINKY":    ("🤙", "右手拇指触小拇指"),
    "HANDS_INTERLOCK": ("🤝", "双手十指相扣"),
}
```

- [ ] **Step 4: Add _tip_combos list and build 9 new rows in _build_gesture_tab**

Modify `ppt_qt/pages/gesture_page.py` `__init__` (around line 55), add `self._tip_combos = []` after `self._binding_combos = ...` line.

Modify `ppt_qt/pages/gesture_page.py` `_build_gesture_tab` (find the section that builds combo boxes for the 7 old gestures, around line 250-280 in your file).

The current code (assumed pattern) creates 7 rows with `populate_combo` and adds to `self._binding_combos`. After that block, add:

```python
        # ---- 9-event: 9 个新 combo box(仅 dual 模式有效) ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color:rgba(255,255,255,80);margin:8px 0;")
        cl.addWidget(sep)
        tip_label = QLabel("新 9-事件(需双人模式)")
        tip_label.setStyleSheet("color:rgba(255,255,255,200);font-size:12px;font-weight:600;margin-top:4px;")
        cl.addWidget(tip_label)
        for g in TIP_GESTURES:
            row = QHBoxLayout()
            emoji, name = _TIP_GESTURE_META.get(g, ("", g))
            lbl = QLabel(f"{emoji}  {name}")
            lbl.setMinimumWidth(180)
            row.addWidget(lbl)
            cb = QComboBox()
            cb.addItem("无", None)
            for a in ACTIONS:
                cb.addItem(_ACTION_LABEL[a], a)
            # set current from cfg.tip_bindings
            cur = self._cfg.get_tip_binding(g)
            for i in range(cb.count()):
                if cb.itemData(i) == cur:
                    cb.setCurrentIndex(i)
                    break
            cb.currentIndexChanged.connect(
                lambda v, gg=g: self._on_tip_binding_changed(gg, v)
            )
            self._tip_combos.append(cb)
            row.addWidget(cb, 1)
            cl.addLayout(row)
```

- [ ] **Step 5: Add _on_tip_binding_changed method**

Modify `ppt_qt/pages/gesture_page.py`, add after `_on_sens_changed` or similar method:

```python
    def _on_tip_binding_changed(self, gesture: str, idx: int) -> None:
        """9-event combo box 变化时写回 cfg,持久化"""
        cb = self.sender()
        if cb is None:
            return
        action = cb.itemData(idx)
        try:
            self._cfg.set_tip_binding(gesture, action)
        except ValueError:
            return
        self._bridge.save()
```

- [ ] **Step 6: Add dual mode watcher to disable 9 combos**

Modify `ppt_qt/pages/gesture_page.py`, find the spot where operator_mode changes are saved (search for `operator_mode`), and add:

```python
    def _refresh_tip_combos_enabled(self) -> None:
        """dual mode off → 9 个 tip combo 禁用 + tooltip 提示"""
        enabled = (self._cfg.operator_mode == "dual")
        tip = "需切到「双人模式」才能使用" if not enabled else ""
        for cb in self._tip_combos:
            cb.setEnabled(enabled)
            cb.setToolTip(tip)
```

Find the existing `_gesture_save_options` method (or wherever operator_mode is saved) and add at the end:

```python
        # 9-event:刷新 combo enable 状态
        if hasattr(self, "_tip_combos"):
            self._refresh_tip_combos_enabled()
```

- [ ] **Step 7: Update reset_bindings to clear tip_bindings too**

Modify `ppt_qt/pages/gesture_page.py`, find the existing "重置默认" button handler (search for `_on_sens_reset` or "重置默认"). After that block, find the bindings reset handler and modify to also reset tip_bindings.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -k "gesture_page" -v`

Expected: 2 tests pass

- [ ] **Step 9: Run full test suite**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 219 tests pass (191 + 28 new)

- [ ] **Step 10: Commit**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "feat(qt): UI 9 个新 combo box + dual mode disable

- _TIP_GESTURE_META:9 个 emoji + 中文名
- _tip_combos:9 个 QComboBox,跟随 cfg.tip_bindings
- _on_tip_binding_changed:combobox 变化写 cfg + 持久化
- _refresh_tip_combos_enabled:dual mode off → 9 个 combo 禁用 + tooltip
- operator_mode 切换时实时刷新 enable 状态

2 new tests cover 16 combo 构建 + dual mode 禁用

Tests: 219 passed (191 + 28 new)"
```

---

### Task 8: Run full test suite + final verification

**Files:** (no code changes)

**Interfaces:** (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest -q`

Expected: 219 tests pass (191 existing + 28 new for 9-event system)

- [ ] **Step 2: Verify no regression in old gesture detection**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_gesture_classification.py tests/test_semantics_optimization.py tests/test_semantics_v2_events.py -v`

Expected: All existing gesture tests pass

- [ ] **Step 3: Verify new tip_touch + interlock tests**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_tip_touch_gestures.py -v`

Expected: 28 new tests pass

- [ ] **Step 4: Verify engine integration tests still pass**

Run: `cd C:/Users/admin_gmail/PyCharmMiscProject && python -m pytest tests/test_engine_frame_snapshot.py tests/test_gesture_bridge.py -v`

Expected: All pass

- [ ] **Step 5: Final commit if any pending changes**

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git status
```

If clean, no commit needed. If changes pending:

```bash
cd C:/Users/admin_gmail/PyCharmMiscProject && git add -A && git commit -m "chore: 9-event system final verification - 219 tests pass"
```

---

## Plan Summary

| Task | 描述 | 测试数 | 累计测试 |
|---|---|---|---|
| 1 | 配置 schema + bindings | 6 | 197 |
| 2 | HandState 新字段 | 1 | 198 |
| 3 | _detect_tip_touches | 8 | 206 |
| 4 | _detect_interlock | 4 | 210 |
| 5 | process() 接线 + cooldown | 4 | 214 |
| 6 | bridge 路由 | 3 | 217 |
| 7 | UI 9 combo + dual disable | 2 | 219 |
| 8 | 验证 | 0 | 219 |

**最终验收**: 219 测试全过,9 事件与 7 旧 gesture 共存,dual mode 切换正常,无破坏性改动。
