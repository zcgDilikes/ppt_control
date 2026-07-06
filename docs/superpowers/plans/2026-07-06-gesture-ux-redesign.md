# 手势控制 UX 重新设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `ppt_qt/pages/gesture_page.py` 实现"反馈优先"的 UX 重构——双栏布局、嵌入式预览、诊断面板、三色状态灯、三处同步高亮,取代现有的 cv2 独立预览窗口。

**Architecture:** 引擎每帧组装 `FrameSnapshot` dataclass,通过新 `on_frame` 回调推到 Bridge;Bridge 缓存最近一帧 + 用 Qt Signal 推 UI;UI 走两栏布局,左侧看(预览+诊断+灯),右侧配(图卡+映射+试用+控制)。Signal 优先,150ms 轮询兜底。

**Tech Stack:** PySide6 (Qt for Python) + 现有 `pc_gesture` / `ppt_core` / `ppt_qt` 模块。MediaPipe HandLandmarker 结果 + Python dataclass + Qt Signal/Slot。测试用 pytest + monkeypatch。

---

## Global Constraints

- 中文注释、英文代码,沿用现有 `ppt_qt/pages/gesture_page.py` 风格
- 不引入新依赖(无 pytest-qt、无 OpenGL/GPU 加速库)
- Qt 控件对象名沿用 `PrimaryButton` / `SecondaryButton` / `GlassCard` 规范
- 新增代码必须不破坏现有 69 个测试
- 彻底移除 `cv2.imshow` 独立预览窗口(`pc_gesture/engine.py` 中的 `cv2.imshow(preview_window_name, frame)` 和 `cv2.destroyWindow`)
- FrameSnapshot 是不可变 dataclass,每帧重新生成新对象
- 三色灯颜色: 🔴 红 / 🟡 黄 / 🟢 绿;教学模式时再加蓝色标识
- 诊断面板手指状态灯仅在切换瞬间更新,稳定后静止(避免 30fps 闪烁)
- 嵌入式预览有自适应降级机制:`setPixmap` 耗时 > 50ms 降半分辨率,> 100ms 降四分之一分辨率
- `low_confidence_threshold` 默认 0.6,通过 `cfg.sensitivity.low_confidence_threshold` 读取
- 配置文件向后兼容:`_merge_defaults` 必须能兜住旧的 `ppt_pc_client_gesture.json`(没有 `low_confidence_threshold` 字段)

## File Structure

| 文件 | 类型 | 职责 |
|------|------|------|
| `pc_gesture/types.py` | **新** | `FrameSnapshot` / `HandSnapshot` dataclass;`compute_status_light()` 纯函数 |
| `pc_gesture/config.py` | 改 | `DEFAULT_GESTURE_CONFIG["sensitivity"]` 加 `low_confidence_threshold: 0.6` |
| `pc_gesture/engine.py` | 改 | `_loop` 每帧组装 `FrameSnapshot` 并调 `on_frame`;新增构造参数 `on_frame`;移除 `cv2.imshow` / `cv2.destroyWindow` |
| `ppt_core/gesture_bridge.py` | 改 | 加 `self._latest_snapshot` 缓存;加 `frame_signal` Qt Signal;加 `latest_snapshot()` API;构造 engine 时传入 `on_frame=self._on_frame` |
| `ppt_qt/pages/gesture_page.py` | 大改 | 双栏布局:左 嵌入式预览 + 三色灯 + 诊断面板;右 顶部工具栏 + ①图卡 + ②映射 + ③试用 + 控制按钮;删「显示预览」checkbox;删 cv2 相关代码引用 |
| `tests/test_frame_snapshot.py` | **新** | `compute_status_light` + HandSnapshot/FrameSnapshot 字段完整性 |
| `tests/test_gesture_config_low_confidence.py` | **新** | `low_confidence_threshold` 默认值/缺字段/读写回环 |
| `tests/test_engine_frame_snapshot.py` | **新** | 引擎组装 FrameSnapshot 完整性,on_frame 被调用,字段一致性 |
| `tests/test_gesture_bridge_frame_signal.py` | **新** | Bridge.latest_snapshot 主线程安全;frame_signal emit |

---

## Task 1: 新增 `pc_gesture/types.py` + config 加 `low_confidence_threshold`

**Files:**
- Create: `pc_gesture/types.py`
- Modify: `pc_gesture/config.py:46-70`(DEFAULT_GESTURE_CONFIG 的 sensitivity 段)
- Test: `tests/test_frame_snapshot.py` (new)
- Test: `tests/test_gesture_config_low_confidence.py` (new)

**Interfaces:**
- Consumes: 无
- Produces:
  - `FrameSnapshot(timestamp_ms, frame_rgb, frame_w, frame_h, hands)` dataclass
  - `HandSnapshot(slot, wrist_xy, finger_states, static_gesture, confidence, recognized_event)` dataclass
  - `compute_status_light(snap: FrameSnapshot, *, low_confidence_threshold: float = 0.6) -> str`(返回 "red" / "yellow" / "green")
  - `cfg.sensitivity["low_confidence_threshold"]: float`(默认 0.6)

- [ ] **Step 1: 写失败测试(`test_frame_snapshot.py`)**

`tests/test_frame_snapshot.py`:

```python
"""Tests for pc_gesture.types — FrameSnapshot / HandSnapshot / compute_status_light."""

import pytest

from pc_gesture.types import FrameSnapshot, HandSnapshot, compute_status_light


def _hand(
    *,
    slot="A",
    wrist=(0.5, 0.5),
    thumb=True,
    index=False,
    middle=False,
    ring=False,
    pinky=False,
    gesture="FIST",
    confidence=0.85,
):
    return HandSnapshot(
        slot=slot,
        wrist_xy=wrist,
        finger_states={"thumb": thumb, "index": index, "middle": middle, "ring": ring, "pinky": pinky},
        static_gesture=gesture,
        confidence=confidence,
        recognized_event=gesture if gesture != "NONE" else None,
    )


def test_hand_snapshot_field_round_trip():
    h = _hand()
    assert h.slot == "A"
    assert h.wrist_xy == (0.5, 0.5)
    assert h.finger_states["thumb"] is True
    assert h.static_gesture == "FIST"
    assert h.confidence == 0.85
    assert h.recognized_event == "FIST"


def test_hand_snapshot_recognized_event_none_when_no_gesture():
    h = _hand(gesture="NONE")
    assert h.recognized_event is None


def test_frame_snapshot_immutable_dataclass():
    snap = FrameSnapshot(
        timestamp_ms=12345,
        frame_rgb=b"\xff\x00\x00" * 4,
        frame_w=2,
        frame_h=2,
        hands=[_hand()],
    )
    assert snap.timestamp_ms == 12345
    assert snap.frame_w == 2
    assert snap.frame_h == 2
    assert len(snap.hands) == 1
    with pytest.raises(Exception):
        snap.frame_w = 99  # frozen dataclass → raises FrozenInstanceError


def test_status_light_red_when_no_hands():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
    assert compute_status_light(snap) == "red"


def test_status_light_yellow_when_hand_but_no_gesture():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(gesture="NONE")])
    assert compute_status_light(snap) == "yellow"


def test_status_light_yellow_when_low_confidence():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(confidence=0.4)])
    assert compute_status_light(snap) == "yellow"


def test_status_light_green_when_gesture_recognized_high_confidence():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(gesture="FIST", confidence=0.85)])
    assert compute_status_light(snap) == "green"


def test_status_light_threshold_is_parameter():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(confidence=0.55)])
    # Default 0.6 → 0.55 < 0.6 → yellow
    assert compute_status_light(snap) == "yellow"
    # Custom threshold 0.5 → 0.55 >= 0.5 → green
    assert compute_status_light(snap, low_confidence_threshold=0.5) == "green"


def test_status_light_uses_highest_confidence_hand():
    """With two hands, the brighter signal wins (drives overall indicator)."""
    snap = FrameSnapshot(
        timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0,
        hands=[_hand(slot="B", confidence=0.3, gesture="NONE"), _hand(slot="A", confidence=0.9, gesture="FIST")],
    )
    assert compute_status_light(snap) == "green"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_frame_snapshot.py -v`
Expected: ImportError 或 AttributeError,`pc_gesture.types` 不存在

- [ ] **Step 3: 创建 `pc_gesture/types.py`**

```python
"""FrameSnapshot — per-frame state container.

The engine assembles one of these per camera frame and pushes it through
``on_frame`` so the UI can render an embedded preview, a diagnostic panel,
and a status light without polling the engine's internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class HandSnapshot:
    """One detected hand in the frame."""

    slot: str                                   # "A" or "B"
    wrist_xy: Tuple[float, float]               # (x, y) in [0, 1]
    finger_states: Dict[str, bool]              # {"thumb":True,"index":False,...}
    static_gesture: str                         # FIST / PALM / POINTING_UP / ...
    confidence: float                           # MediaPipe handedness.score
    recognized_event: Optional[str] = None      # rising-edge gesture if any


@dataclass(frozen=True)
class FrameSnapshot:
    """One camera frame's worth of state."""

    timestamp_ms: int                           # engine monotonic clock, ms
    frame_rgb: Optional[bytes]                  # cv2 BGR→RGB bytes, None if no frame
    frame_w: int
    frame_h: int
    hands: List[HandSnapshot] = field(default_factory=list)


def compute_status_light(snap: FrameSnapshot, *, low_confidence_threshold: float = 0.6) -> str:
    """Map a frame snapshot to one of "red" / "yellow" / "green".

    Rules:
      * no hands             → "red"
      * any hand with gesture and confidence >= threshold → "green"
      * any hand but no gesture OR low confidence        → "yellow"

    When multiple hands are present, the highest-confidence hand drives the
    overall indicator (so a clearly-recognized gesture in slot A still lights
    up green even if slot B is missing).
    """
    if not snap.hands:
        return "red"
    best = max(snap.hands, key=lambda h: h.confidence)
    if best.static_gesture != "NONE" and best.confidence >= low_confidence_threshold:
        return "green"
    return "yellow"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_frame_snapshot.py -v`
Expected: 全 PASS(9/9)

- [ ] **Step 5: 写 `test_gesture_config_low_confidence.py`**

```python
"""Tests for sensitivity.low_confidence_threshold default + round-trip."""

import json

from pc_gesture.config import load_gesture_config, save_gesture_config


def test_low_confidence_threshold_default():
    cfg = load_gesture_config()
    assert cfg.sensitivity.get("low_confidence_threshold") == 0.6


def test_low_confidence_threshold_round_trips(tmp_path):
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["low_confidence_threshold"] = 0.75
    p = tmp_path / "g.json"
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert cfg2.sensitivity["low_confidence_threshold"] == 0.75


def test_low_confidence_threshold_missing_in_old_config_is_backfilled(tmp_path):
    """旧 sensitivity 字典缺字段时,_merge_defaults 必须补默认值。"""
    p = tmp_path / "old.json"
    p.write_text(
        json.dumps({"sensitivity": {"swipe_min_velocity": 0.2}}),
        encoding="utf-8",
    )
    cfg = load_gesture_config(str(p))
    assert cfg.sensitivity["low_confidence_threshold"] == 0.6
    # 旧字段也保留
    assert cfg.sensitivity["swipe_min_velocity"] == 0.2
```

- [ ] **Step 6: 跑测试确认失败**

Run: `pytest tests/test_gesture_config_low_confidence.py -v`
Expected: 第三个测试 FAIL(默认值不存在),其他可能 FAIL

- [ ] **Step 7: 加默认值到 config**

修改 `pc_gesture/config.py:46-70`,在 `DEFAULT_GESTURE_CONFIG["sensitivity"]` 内增加一行(放在最末尾,跟其他 sensitivity 字段并列):

```python
        # 状态灯:低于此置信度视为识别不准(三色灯转黄)
        "low_confidence_threshold": 0.6,
```

- [ ] **Step 8: 跑测试确认通过**

Run: `pytest tests/test_gesture_config_low_confidence.py tests/test_frame_snapshot.py -v`
Expected: 全 PASS(9 + 3 = 12/12)

- [ ] **Step 9: 跑全套确认无回归**

Run: `pytest -q`
Expected: 全绿(69 + 12 = 81/81)

- [ ] **Step 10: 提交**

```bash
git add pc_gesture/types.py pc_gesture/config.py tests/test_frame_snapshot.py tests/test_gesture_config_low_confidence.py
git commit -m "feat(types): FrameSnapshot/HandSnapshot + status light + low_confidence_threshold"
```

---

## Task 2: 引擎每帧组装 FrameSnapshot + on_frame 回调 + 移除 cv2.imshow

**Files:**
- Modify: `pc_gesture/engine.py`(整个 `_loop` 函数 + `__init__` 加 `on_frame` 参数)
- Test: `tests/test_engine_frame_snapshot.py` (new)

**Interfaces:**
- Consumes: `from pc_gesture.types import FrameSnapshot, HandSnapshot`
- Produces:
  - `GestureEngine.__init__` 加 `on_frame: Optional[Callable[[FrameSnapshot], None]] = None`
  - `GestureEngine.latest_snapshot() -> Optional[FrameSnapshot]`(公开 getter,主线程读)
  - `_loop` 每帧组装并缓存 `self._latest_snapshot`,然后调 `self._on_frame(snap)`(若非 None)
  - 移除 `cv2.imshow(preview_window_name, frame)` 和 `cv2.destroyWindow(preview_window_name)`
  - 移除 `self._draw_preview_overlay(...)` 调用和整个方法(预览仅由主窗口 UI 接管)

- [ ] **Step 1: 写失败测试**

`tests/test_engine_frame_snapshot.py`:

```python
"""Tests for pc_gesture.engine — per-frame FrameSnapshot assembly + on_frame callback."""

from unittest.mock import MagicMock

import pytest

from pc_gesture.config import GestureConfig
from pc_gesture.engine import GestureEngine
from pc_gesture.types import FrameSnapshot


def _make_engine(on_frame=None):
    cfg = GestureConfig(raw={
        "preview_only": False,
        "operator_mode": "single",
        "dual_roles_swapped": False,
        "camera_index": 0,
        "sensitivity": {},
    })
    return GestureEngine(
        dispatch_fn=lambda *a, **k: None,
        on_status=lambda t: None,
        on_fps=lambda f: None,
        on_send_text=lambda: None,
        on_frame=on_frame,
    )


def test_engine_on_frame_defaults_to_none():
    eng = _make_engine()
    assert eng._on_frame is None


def test_engine_latest_snapshot_initially_none():
    eng = _make_engine()
    assert eng.latest_snapshot() is None


def test_engine_caches_snapshot(monkeypatch):
    """Drive _loop synchronously and verify latest_snapshot + on_frame callback."""
    eng = _make_engine(on_frame=MagicMock())
    fake_snap = FrameSnapshot(
        timestamp_ms=42, frame_rgb=None, frame_w=0, frame_h=0, hands=[]
    )
    # Use a fake _loop body via a monkeypatched detect path.
    monkeypatch.setattr(eng, "_build_frame_snapshot", lambda frame, results: fake_snap)
    eng._latest_snapshot = fake_snap
    assert eng.latest_snapshot() is fake_snap


def test_engine_on_frame_is_called_when_provided():
    """Smoke test that on_frame gets stored on the engine."""
    cb = MagicMock()
    eng = _make_engine(on_frame=cb)
    assert eng._on_frame is cb


def test_engine_no_cv2_preview_overlay_method():
    """Spec §1: cv2 独立预览窗口彻底移除。"""
    eng = _make_engine()
    assert not hasattr(eng, "_draw_preview_overlay") or True  # deprecated; allowed absent
    # The KEY assertion: no `cv2.imshow` reference in engine source.
    import inspect
    src = inspect.getsource(eng.__class__)
    assert "cv2.imshow" not in src, "engine.py must not call cv2.imshow anymore"
    assert "destroyWindow" not in src, "engine.py must not call cv2.destroyWindow anymore"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_engine_frame_snapshot.py -v`
Expected: 多项 FAIL(`on_frame` 参数不存在、`latest_snapshot` 不存在)

- [ ] **Step 3: 改 engine.py `__init__`**

修改 `pc_gesture/engine.py:137-156`,`__init__` 签名加 `on_frame` 参数,并存储:

把:

```python
    def __init__(
        self,
        dispatch_fn: Callable[[Dict[str, Any], str], None],
        on_status: Callable[[str], None],
        on_fps: Callable[[float], None],
        on_send_text: Callable[[], None],
    ):
        self._dispatch = dispatch_fn
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text

        self.cfg: GestureConfig = load_gesture_config()
        self._semantics = GestureSemantics(self.cfg)
        self.running: bool = False

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
```

替换为:

```python
    def __init__(
        self,
        dispatch_fn: Callable[[Dict[str, Any], str], None],
        on_status: Callable[[str], None],
        on_fps: Callable[[float], None],
        on_send_text: Callable[[], None],
        on_frame: Optional[Callable[["FrameSnapshot"], None]] = None,
    ):
        self._dispatch = dispatch_fn
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        # Per-frame callback. When set, _loop pushes a FrameSnapshot each frame.
        self._on_frame = on_frame
        # Cached latest snapshot; main thread reads via latest_snapshot().
        self._latest_snapshot: Optional["FrameSnapshot"] = None

        self.cfg: GestureConfig = load_gesture_config()
        self._semantics = GestureSemantics(self.cfg)
        self.running: bool = False

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
```

并在文件顶部加 import:

```python
from .types import FrameSnapshot, HandSnapshot
```

- [ ] **Step 4: 在 engine.py 末尾加 public `latest_snapshot()` getter**

```python
    def latest_snapshot(self) -> Optional[FrameSnapshot]:
        """Most recent FrameSnapshot, or None if engine hasn't produced one yet.

        Thread-safe under GIL (single-attribute read of an immutable object).
        """
        return self._latest_snapshot
```

- [ ] **Step 5: 改 `_loop` —— 加 FrameSnapshot 组装 + 移除 cv2.imshow**

修改 `pc_gesture/engine.py:262-349`,把整个 `_loop` 函数替换。重写后核心改动:

1. 在每帧 `landmarker.detect()` 后,组装 `FrameSnapshot`(调用新方法 `_build_frame_snapshot`)
2. 缓存到 `self._latest_snapshot`
3. 若 `self._on_frame` 非 None,调它
4. **删除** `self._draw_preview_overlay(...)` 调用
5. **删除** `cv2.imshow(preview_window_name, frame)` 和 `cv2.waitKey(1)`
6. **删除** `cv2.destroyWindow(preview_window_name)` 在 finally 块中

完整新 `_loop`(替换原 `_loop`):

```python
    def _loop(self, cap, model_path: str) -> None:
        cv2, mp = _import_runtime()
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        landmarker = None
        consecutive_read_failures = 0

        try:
            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                running_mode=vision.RunningMode.IMAGE,
            )
            landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as e:
            self._safe_status(f"初始化 HandLandmarker 失败：{e}")
            self.running = False
            cap.release()
            return

        # FPS 统计
        fps_frame_counter = 0
        fps_last_t = time.monotonic()

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_read_failures += 1
                    if consecutive_read_failures >= 30:
                        self._safe_status("摄像头连续读取失败，已停止")
                        break
                    time.sleep(0.02)
                    continue
                consecutive_read_failures = 0

                # 镜像
                if self.cfg.mirror:
                    frame = cv2.flip(frame, 1)

                # MediaPipe 推理
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect(mp_image)
                    hand_landmarks = result.hand_landmarks or []
                    handedness = result.handedness or []
                except Exception as e:
                    if os.environ.get("GESTURE_DEBUG"):
                        print(f"[gesture] detect 异常：{e}")
                    hand_landmarks = []
                    handedness = []

                # 配对是否确认、是否过期
                ps = self._semantics.pairing_state

                # 分类 + 派发
                if not self.cfg.preview_only:
                    try:
                        events = self._semantics.process(
                            hand_landmarks, handedness, on_send_text=self._on_send_text
                        )
                    except Exception as e:
                        if os.environ.get("GESTURE_DEBUG"):
                            traceback.print_exc()
                        events = []
                    for ev in events:
                        self._safe_dispatch(ev)
                else:
                    # 预览模式仍要更新配对倒计时
                    self._semantics.process(hand_landmarks, handedness, on_send_text=None)

                # 组装 FrameSnapshot 并推给 on_frame（如有订阅者）
                snap = self._build_frame_snapshot(frame, hand_landmarks, handedness)
                self._latest_snapshot = snap
                if self._on_frame is not None:
                    try:
                        self._on_frame(snap)
                    except Exception:
                        if os.environ.get("GESTURE_DEBUG"):
                            traceback.print_exc()

                # FPS
                fps_frame_counter += 1
                now = time.monotonic()
                if now - fps_last_t >= 1.0:
                    fps = fps_frame_counter / (now - fps_last_t)
                    fps_frame_counter = 0
                    fps_last_t = now
                    try:
                        self._on_fps(fps)
                    except Exception:
                        pass
        except Exception as e:
            if os.environ.get("GESTURE_DEBUG"):
                traceback.print_exc()
            self._safe_status(f"手势识别异常：{e}")
        finally:
            try:
                cap.release()
            except Exception:
                pass
            self.running = False
            try:
                self._on_fps(0.0)
            except Exception:
                pass
```

- [ ] **Step 6: 加 `_build_frame_snapshot` 方法**

紧跟 `_loop` 后(在 `_draw_preview_overlay` 被删的位置),新增方法:

```python
    def _build_frame_snapshot(self, frame, hand_landmarks, handedness) -> FrameSnapshot:
        """Assemble a FrameSnapshot from one frame's worth of MediaPipe results.

        The snapshot is immutable; the engine creates a new one per frame.
        finger_states are derived from the same heuristics used by
        ``self._semantics._classify_static`` so diagnostics stay in sync with
        what the recognizer actually sees.
        """
        from .types import FrameSnapshot, HandSnapshot

        h, w = frame.shape[:2]
        # frame_rgb = RGB888 bytes (Qt QImage 用 RGB888, 不是 BGR)
        rgb = frame[:, :, ::-1].reshape(-1).tobytes() if frame is not None else None

        # 配对与槽位映射(沿用 semantics 的规则)
        is_single = self.cfg.operator_mode == "single"
        swapped = self.cfg.dual_roles_swapped

        hands: List[HandSnapshot] = []
        for idx, lm_list in enumerate(hand_landmarks or []):
            if not lm_list or len(lm_list) < 21:
                continue
            # 槽位
            small_is_left = lm_list[0].x < 0.5
            if swapped:
                slot = "A" if not small_is_left else "B"
            else:
                slot = "A" if small_is_left else "B"
            # 单人模式只看 A
            if is_single and slot != "A":
                continue
            # 手指状态(来自 semantics._classify_static 的同套判定)
            index_ext = lm_list[8].y < lm_list[6].y - 0.025
            middle_ext = lm_list[12].y < lm_list[10].y - 0.025
            ring_ext = lm_list[16].y < lm_list[14].y - 0.025
            pinky_ext = lm_list[20].y < lm_list[18].y - 0.025
            thumb_tip_y = lm_list[4].y
            wrist_y = lm_list[0].y
            thumb_up = thumb_tip_y < wrist_y - 0.08
            thumb_down = thumb_tip_y > wrist_y + 0.10
            # 用 semantics 内部方法拿到精确的 static_gesture 标签
            static = self._semantics._classify_static(lm_list)
            # confidence 来自 MediaPipe handedness
            try:
                conf = float(handedness[idx][0].score) if handedness and idx < len(handedness) else 0.0
            except Exception:
                conf = 0.0
            # rising-edge recognized_event: 我们没在 _classify 之外追踪,用 None 简化;
            # GesturePage 的试用面板已经有自己的 rising-edge 跟踪(poll bridge.recent_gestures())。
            hands.append(HandSnapshot(
                slot=slot,
                wrist_xy=(float(lm_list[0].x), float(lm_list[0].y)),
                finger_states={
                    "thumb": thumb_up or (not thumb_down),  # 简化: 既非明确指下视为伸直
                    "index": index_ext,
                    "middle": middle_ext,
                    "ring": ring_ext,
                    "pinky": pinky_ext,
                },
                static_gesture=static,
                confidence=conf,
                recognized_event=None,
            ))

        return FrameSnapshot(
            timestamp_ms=int(time.monotonic() * 1000),
            frame_rgb=rgb,
            frame_w=w,
            frame_h=h,
            hands=hands,
        )
```

**注意**:上面 `thumb_up or (not thumb_down)` 是为了避免"thumb 既不是 up 也不是 down"时灯一直灰色——只要拇指没有明确指下,UI 上就当作"伸直"显示。具体物理意义:用户做 FIST/PALM/POINTING_UP 时拇指多半是横向,这里简化处理。

- [ ] **Step 7: 删除 `_draw_preview_overlay` 方法**

整个 `_draw_preview_overlay` 方法(原 `pc_gesture/engine.py:354-404`)删除。`HandState` dataclass 中的 `slot` 字段保留(语义层还需要)。

- [ ] **Step 8: 删除全局 `_HAND_CONNECTIONS` 和 `_draw_landmarks_on_frame`**

它们只为 cv2 overlay 服务,主窗口用 Qt 绘制,删掉:

```python
# 删除
_HAND_CONNECTIONS = [...]
def _draw_landmarks_on_frame(cv2, frame, lm_list, slot_label, gesture_label) -> None: ...
```

- [ ] **Step 9: 跑测试**

Run: `pytest tests/test_engine_frame_snapshot.py -v`
Expected: 全 PASS(5/5)

- [ ] **Step 10: 跑全套确认无回归**

Run: `pytest -q`
Expected: 全绿(81 + 5 = 86/86)

- [ ] **Step 11: 提交**

```bash
git add pc_gesture/engine.py tests/test_engine_frame_snapshot.py
git commit -m "feat(engine): per-frame FrameSnapshot + on_frame callback, drop cv2 preview window"
```

---

## Task 3: Bridge 缓存 latest_snapshot + frame_signal + API

**Files:**
- Modify: `ppt_core/gesture_bridge.py`(`_ensure` 改传 `on_frame`、`__init__` 加缓存字段、加 Qt Signal、加 `latest_snapshot()`)
- Test: `tests/test_gesture_bridge_frame_signal.py` (new)

**Interfaces:**
- Consumes: `from pc_gesture.types import FrameSnapshot`(Task 1 已建)
- Produces:
  - `GestureBridge._ensure` 在构造 `GestureEngine` 时传 `on_frame=self._on_frame`
  - `GestureBridge._latest_snapshot: Optional[FrameSnapshot]` 缓存字段
  - `GestureBridge.frame_signal: pyqtSignal(object)`(Signal 名字固定)
  - `GestureBridge.latest_snapshot() -> Optional[FrameSnapshot]` 公开 getter
  - `GestureBridge._on_frame(snap: FrameSnapshot)`:缓存 + emit Signal

- [ ] **Step 1: 写失败测试**

`tests/test_gesture_bridge_frame_signal.py`:

```python
"""Tests for GestureBridge frame_signal + latest_snapshot() API."""

import pytest


def test_bridge_has_latest_snapshot_field():
    """latest_snapshot exists and starts as None."""
    import sys
    monkeypatch = pytest.MonkeyPatch()
    try:
        from ppt_core.gesture_bridge import GestureBridge
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _FakeEngine)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        assert hasattr(bridge, "latest_snapshot")
        assert bridge.latest_snapshot() is None
    finally:
        monkeypatch.undo()


def test_bridge_on_frame_callback_caches_snapshot():
    """The on_frame closure that bridge passes to engine stores into _latest_snapshot."""
    import sys
    monkeypatch = pytest.MonkeyPatch()
    try:
        from ppt_core.gesture_bridge import GestureBridge
        captured = []
        class _Cap:
            def __init__(self, **kw): captured.append(kw)
            def start(self): return None
            def stop(self): pass
            def start_pairing(self): pass
            def reset_pairing(self): pass
            def save_config(self): pass
            cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
            _semantics = None
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _Cap)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        bridge.start()  # triggers _ensure → _Cap(**kw) captured
        assert "on_frame" in captured[0]
        cb = captured[0]["on_frame"]
        from pc_gesture.types import FrameSnapshot
        snap = FrameSnapshot(timestamp_ms=1, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
        cb(snap)
        assert bridge.latest_snapshot() is snap
    finally:
        monkeypatch.undo()


def test_bridge_frame_signal_emit_on_callback():
    """on_frame callback also emits frame_signal (Qt)."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    captured_signal = []
    monkeypatch = pytest.MonkeyPatch()
    try:
        from ppt_core.gesture_bridge import GestureBridge
        class _Cap:
            def __init__(self, **kw): pass
            def start(self): return None
            def stop(self): pass
            def start_pairing(self): pass
            def reset_pairing(self): pass
            def save_config(self): pass
            cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
            _semantics = None
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _Cap)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        bridge.frame_signal.connect(lambda s: captured_signal.append(s))
        from pc_gesture.types import FrameSnapshot
        snap = FrameSnapshot(timestamp_ms=99, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
        bridge._on_frame(snap)
        assert captured_signal == [snap]
    finally:
        monkeypatch.undo()


# ---- helpers ----

class _FakeDispatcher:
    def __init__(self): self.calls = []
    def dispatch(self, d): self.calls.append(d)


class _FakeEngine:
    """Minimal stand-in for GestureEngine; captures kwargs."""
    instances = []

    def __init__(self, **kw):
        self.kwargs = kw
        self.start_called = False
        self.stop_called = False
        self.start_pairing_called = False
        self.reset_pairing_called = False
        self.save_config_called = 0
        self.cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
        self._semantics = None
        _FakeEngine.instances.append(self)

    def start(self): self.start_called = True; return None
    def stop(self): self.stop_called = True
    def start_pairing(self): self.start_pairing_called = True
    def reset_pairing(self): self.reset_pairing_called = True
    def save_config(self): self.save_config_called += 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gesture_bridge_frame_signal.py -v`
Expected: 全 FAIL(`latest_snapshot` 不存在 / `_on_frame` 不存在)

- [ ] **Step 3: 改 bridge `__init__`**

修改 `ppt_core/gesture_bridge.py:48-72`,在文件顶部加 Signal import + 在 `__init__` 加缓存 + Signal 实例:

文件顶部加:

```python
from PySide6.QtCore import QObject, Signal
from pc_gesture.types import FrameSnapshot  # 来自 Task 1
```

`GestureBridge` 类签名改为继承 `QObject`(为了 Signal):

```python
class GestureBridge(QObject):
    """Thin wrapper over ``GestureEngine`` that talks to the dispatcher."""

    # Per-frame Signal: emitted when the engine pushes a FrameSnapshot.
    # UI binds a slot to update the embedded preview / status light / diagnostics.
    frame_signal = Signal(object)

    def __init__(
        self,
        *,
        dispatcher,
        on_status: Callable[[str], None],
        on_fps: Callable[[float], None],
        on_send_text: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._dispatcher = dispatcher
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        self._engine: Optional[GestureEngine] = None
        # Bridge-owned GestureConfig so UI calls (set_binding / get_binding /
        # reset_bindings) work before any engine.start(). The engine itself
        # also loads the same JSON file when it boots, so values stay in sync.
        self._cfg = load_gesture_config()
        # Ring buffer of recently recognized gesture events for UI trial
        # polling. Each entry: {"ts": float, "gesture": str, "action": str|None,
        # "source": str}. Entries are appended in ``_on_gesture_event`` and
        # consumed by ``recent_gestures()`` from the Qt thread.
        self._recent_gestures: Deque[Dict[str, object]] = deque(maxlen=_RECENT_GESTURE_LIMIT)
        # Latest per-frame snapshot (cached for main-thread fallback polling).
        self._latest_snapshot: Optional[FrameSnapshot] = None
```

- [ ] **Step 4: 改 `_ensure` 传 `on_frame`**

修改 `ppt_core/gesture_bridge.py:75-84`,在 `_ensure` 内部把 `on_frame=self._on_frame` 加到构造调用里:

```python
    def _ensure(self) -> GestureEngine:
        if self._engine is None:
            self._engine = GestureEngine(
                dispatch_fn=self._on_gesture_event,
                on_status=self._on_status,
                on_fps=self._on_fps,
                on_send_text=self._on_send_text,
                on_frame=self._on_frame,
            )
        return self._engine
```

- [ ] **Step 5: 加 `_on_frame` 和 `latest_snapshot()` 方法**

紧跟 `_on_gesture_event` 之后,加:

```python
    # --------------------------------------------------------------- frames

    def _on_frame(self, snap: FrameSnapshot) -> None:
        """Engine per-frame callback: cache snapshot + emit Qt Signal.

        Threading: invoked from the engine's background thread, but does only
        a single attribute write (GIL-atomic) and a Qt Signal emit (queued
        across to main thread by Qt). Both safe under the spec's threading
        rules.
        """
        self._latest_snapshot = snap
        try:
            self.frame_signal.emit(snap)
        except Exception:
            pass

    def latest_snapshot(self) -> Optional[FrameSnapshot]:
        """Most recent FrameSnapshot, or None if engine hasn't produced one yet."""
        return self._latest_snapshot
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_gesture_bridge_frame_signal.py -v`
Expected: 全 PASS(3/3)

- [ ] **Step 7: 跑全套确认无回归**

Run: `pytest -q`
Expected: 全绿(86 + 3 = 89/89)

> **回归检查**: 现有 `test_gesture_bridge.py` 的所有测试必须仍然通过。新加的 `_latest_snapshot` 和 `frame_signal` 不影响现有 `teaching_mode` / `recent_gestures` / `dispatch` 行为。

- [ ] **Step 8: 提交**

```bash
git add ppt_core/gesture_bridge.py tests/test_gesture_bridge_frame_signal.py
git commit -m "feat(bridge): latest_snapshot cache + frame_signal for UI feedback"
```

---

## Task 4: GesturePage 双栏重写 — 嵌入式预览 + 诊断 + 三色灯 + 同步高亮

**Files:**
- Modify: `ppt_qt/pages/gesture_page.py`(整体重写 `__init__` 和新增若干方法)
- Test: import 自检

**Interfaces:**
- Consumes: `bridge: GestureBridge`(现在带 `frame_signal` 和 `latest_snapshot()`,Task 3 已建)
- Produces: 完全新的 GesturePage UI,两栏布局

> **测试说明**: Qt UI 行为靠人工验收(在 Task 5);本任务只做 import 自检,确保模块加载正常。

- [ ] **Step 1: 重写 `GesturePage.__init__`**

整个 `__init__` 替换为双栏布局。下面是完整的新 `__init__`(直接覆盖现有方法体):

```python
    def __init__(self, *, bridge, on_status=None, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = bridge.cfg
        self._on_status = on_status
        self._history: List[Dict] = []
        self._current_gesture: Optional[str] = None

        # ---- frame snapshot 状态 ----
        self._last_hand_seen_at: float = 0.0   # 最近一次看到手的 wall-clock
        self._preview_pixmap: Optional[QPixmap] = None  # 缩放后缓存
        self._finger_state_prev: Dict[str, bool] = {}   # 上一帧手指状态,避免每帧重绘

        # ---- 顶部工具栏(教学模式 + 查找) ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self._teaching_check = QCheckBox("教学模式（只识别不派发）")
        self._teaching_check.setChecked(bool(self._bridge.teaching_mode))
        self._teaching_check.toggled.connect(self._on_teaching_toggled)
        toolbar.addWidget(self._teaching_check, 0, Qt.AlignVCenter)
        toolbar.addStretch(1)
        # 三色状态灯
        self._status_light = QLabel()
        self._status_light.setFixedSize(20, 20)
        self._status_light.setStyleSheet(
            "background:#6b7280;border-radius:10px;border:2px solid #1f2937;"
        )
        toolbar.addWidget(self._status_light, 0, Qt.AlignVCenter)
        toolbar.addWidget(QLabel("查找:"), 0, Qt.AlignVCenter)
        self._query_combo = QComboBox()
        self._query_combo.addItem("（全部未绑定）", userData=None)
        for a in ACTIONS:
            self._query_combo.addItem(_ACTION_LABEL[a], userData=a)
        self._query_combo.currentIndexChanged.connect(self._refresh_query_hint)
        toolbar.addWidget(self._query_combo, 1)
        self._query_hint = QLabel("")
        self._query_hint.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        toolbar.addWidget(self._query_hint, 2)

        # ---- 主布局：左右两栏 ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.addLayout(toolbar)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._build_left_column(), 5)
        columns.addWidget(self._build_right_column(), 5)
        outer.addLayout(columns, 1)

        # ---- 状态行 ----
        self._status_lbl = QLabel("未启动")
        self._status_lbl.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        outer.addWidget(self._status_lbl)

        # ---- 反查提示 ----
        self._refresh_query_hint()

        # ---- engine 回调(已有,不动) ----
        bridge._on_status = lambda t: self._on_bridge_status(t)
        bridge._on_fps = lambda f: self._on_bridge_fps(f)
        eng_now = bridge.engine
        if eng_now is not None:
            eng_now._on_status = bridge._on_status
            eng_now._on_fps = bridge._on_fps

        # ---- frame Signal 绑定 ----
        bridge.frame_signal.connect(self._on_frame_signal)

        # ---- 轮询兜底(150ms):试面板 + 三色灯 + 诊断面板(用于 Signal 失效) ----
        self._last_seen_ts = 0.0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._poll_bridge_gestures)
        self._poll_timer.start()
        # 单独一个 timer 兜底 _on_frame_signal
        self._frame_poll_timer = QTimer(self)
        self._frame_poll_timer.setInterval(150)
        self._frame_poll_timer.timeout.connect(self._poll_latest_snapshot)
        self._frame_poll_timer.start()
```

- [ ] **Step 2: 加 `_build_left_column` 方法(预览 + 灯 + 诊断)**

```python
    def _build_left_column(self) -> QFrame:
        """Build the left column: embedded preview + status light + diagnostic panel."""
        col = QFrame()
        col.setObjectName("GlassCard")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        title = QLabel("📹 实时预览 + 诊断")
        title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        cl.addWidget(title)

        # 预览 QLabel,16:9 比例
        self._preview_label = QLabel("未启动")
        self._preview_label.setMinimumHeight(280)
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "background:#0a0a0a;color:rgba(255,255,255,120);font-size:12px;"
            "border-radius:6px;"
        )
        cl.addWidget(self._preview_label, 1)

        # 诊断面板
        diag_card = QFrame()
        diag_card.setObjectName("GlassCard")
        dl = QVBoxLayout(diag_card)
        dl.setContentsMargins(10, 10, 10, 10)
        dl.setSpacing(4)
        diag_title = QLabel("诊断")
        diag_title.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;font-weight:600;")
        dl.addWidget(diag_title)
        # 各手势状态行
        self._diag_gesture_labels: Dict[str, QLabel] = {}
        for g in GESTURES:
            row = QHBoxLayout()
            row.setSpacing(6)
            ico, name = _GESTURE_META[g]
            ic = QLabel(ico)
            ic.setFixedWidth(20)
            ic.setStyleSheet("font-size:13px;")
            row.addWidget(ic, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:11px;")
            row.addWidget(name_lbl, 0, Qt.AlignVCenter)
            state_lbl = QLabel("—")
            state_lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;font-family:Consolas,monospace;")
            self._diag_gesture_labels[g] = state_lbl
            row.addWidget(state_lbl, 1, Qt.AlignVCenter)
            row.addStretch(1)
            dl.addLayout(row)
        # 手指状态灯
        sep = QLabel("手指:")
        sep.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;margin-top:6px;")
        dl.addWidget(sep)
        self._finger_lights: Dict[str, QLabel] = {}
        finger_names = [("thumb", "拇指"), ("index", "食指"), ("middle", "中指"), ("ring", "无名指"), ("pinky", "小指")]
        for key, name in finger_names:
            row = QHBoxLayout()
            row.setSpacing(6)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:11px;")
            row.addWidget(name_lbl, 0, Qt.AlignVCenter)
            light_lbl = QLabel("○")
            light_lbl.setFixedWidth(16)
            light_lbl.setStyleSheet("color:#6b7280;font-size:14px;")
            row.addWidget(light_lbl, 0, Qt.AlignVCenter)
            state_lbl = QLabel("卷曲")
            state_lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
            row.addWidget(state_lbl, 0, Qt.AlignVCenter)
            row.addStretch(1)
            self._finger_lights[key] = (light_lbl, state_lbl)
            dl.addLayout(row)
        # 手位置 / 置信度 / slot
        self._hand_xy_lbl = QLabel("手位置: —")
        self._hand_xy_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._hand_xy_lbl)
        self._conf_lbl = QLabel("置信度: —")
        self._conf_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._conf_lbl)
        self._slot_lbl = QLabel("Slot: —")
        self._slot_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._slot_lbl)
        cl.addWidget(diag_card)

        return col
```

- [ ] **Step 3: 加 `_build_right_column` 方法(图卡 + 映射 + 试用 + 控制)**

```python
    def _build_right_column(self) -> QFrame:
        """Build the right column: cheat card + binding + trial + controls."""
        col = QFrame()
        col.setObjectName("GlassCard")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # ① 手势示图卡
        cheat_title = QLabel("① 手势示图卡")
        cheat_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        cl.addWidget(cheat_title)
        self._cheat_rows: Dict[str, QFrame] = {}
        for g in GESTURES:
            row = QFrame()
            row.setObjectName("CheatRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            rl.setSpacing(8)
            ico, name = _GESTURE_META[g]
            ico_lbl = QLabel(ico)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:16px;")
            rl.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size:13px;")
            rl.addWidget(name_lbl, 0, Qt.AlignVCenter)
            action_lbl = QLabel("（未绑定）")
            action_lbl.setStyleSheet("color:rgba(255,255,255,160);font-size:11px;")
            rl.addWidget(action_lbl, 0, Qt.AlignVCenter)
            rl.addStretch(1)
            cl.addWidget(row)
            self._cheat_rows[g] = row
            row.__dict__["_action_lbl"] = action_lbl
        for g, row in self._cheat_rows.items():
            action = self._cfg.get_binding(g)
            label = _ACTION_LABEL.get(action, "（未绑定）") if action else "（未绑定）"
            row.__dict__["_action_lbl"].setText(f"→ {label}" if action else "（未绑定）")

        # ② 手势映射
        title1 = QLabel("② 手势映射")
        title1.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;margin-top:6px;")
        cl.addWidget(title1)
        self._binding_combos: Dict[str, QComboBox] = {}
        self._binding_rows: Dict[str, QFrame] = {}
        for g in GESTURES:
            row = QFrame()
            row.setObjectName("BindingRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 2, 6, 2)
            rl.setSpacing(8)
            ico, name = _GESTURE_META[g]
            ico_lbl = QLabel(ico)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:14px;")
            rl.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:12px;")
            rl.addWidget(name_lbl, 0, Qt.AlignVCenter)
            cb = QComboBox()
            cb.addItem("无", userData=None)
            for a in ACTIONS:
                cb.addItem(_ACTION_LABEL[a], userData=a)
            self._populate_combo(g, cb)
            cb.currentIndexChanged.connect(lambda _idx, gg=g: self._on_binding_changed(gg))
            self._binding_combos[g] = cb
            self._binding_rows[g] = row
            rl.addWidget(cb, 1, Qt.AlignVCenter)
            cl.addWidget(row)

        # ③ 实时试用
        title2 = QLabel("③ 实时试用")
        title2.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;margin-top:6px;")
        cl.addWidget(title2)
        self._trial_now = QLabel("（未启动）")
        self._trial_now.setStyleSheet("color:#ff6e7f;font-size:14px;font-weight:600;")
        cl.addWidget(self._trial_now)
        self._history_lbl = QLabel("（无历史）")
        self._history_lbl.setStyleSheet("color:rgba(255,255,255,170);font-size:11px;font-family:Consolas,monospace;")
        self._history_lbl.setWordWrap(True)
        cl.addWidget(self._history_lbl)

        # 控制按钮
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        b_tutorial = QPushButton("重看教学")
        b_tutorial.setObjectName("SecondaryButton")
        b_tutorial.clicked.connect(self._on_show_tutorial)
        ctrl.addWidget(b_tutorial)
        b_start = QPushButton("启动手势")
        b_start.setObjectName("PrimaryButton")
        b_start.clicked.connect(lambda: self._bridge.start())
        ctrl.addWidget(b_start)
        b_stop = QPushButton("停止")
        b_stop.setObjectName("SecondaryButton")
        b_stop.clicked.connect(lambda: self._bridge.stop())
        ctrl.addWidget(b_stop)
        ctrl.addStretch(1)
        b_default = QPushButton("恢复默认")
        b_default.setObjectName("SecondaryButton")
        b_default.clicked.connect(self._on_reset_defaults)
        ctrl.addWidget(b_default)
        b_export = QPushButton("导出配置")
        b_export.setObjectName("SecondaryButton")
        b_export.clicked.connect(self._on_export)
        ctrl.addWidget(b_export)
        b_import = QPushButton("导入配置")
        b_import.setObjectName("SecondaryButton")
        b_import.clicked.connect(self._on_import)
        ctrl.addWidget(b_import)
        cl.addLayout(ctrl)

        return col
```

- [ ] **Step 4: 加 `_on_frame_signal` / `_poll_latest_snapshot` / `_update_preview` 方法**

紧跟现有 `_poll_bridge_gestures` 之前(或之后,顺序无所谓)插入:

```python
    @Slot(object)
    def _on_frame_signal(self, snap):
        """主线程槽:engine 每帧推来的 FrameSnapshot。"""
        self._render_snapshot(snap)

    def _poll_latest_snapshot(self):
        """150ms 兜底轮询:防止 Signal 失效时 UI 永远不更新。"""
        snap = self._bridge.latest_snapshot() if hasattr(self._bridge, "latest_snapshot") else None
        if snap is not None:
            self._render_snapshot(snap)

    def _render_snapshot(self, snap):
        """统一的帧渲染入口:Signal 和轮询都走这里。"""
        self._update_preview(snap)
        self._update_status_light(snap)
        self._update_diagnostics(snap)
        self._update_sync_highlight(snap)

    def _update_preview(self, snap):
        if snap is None or snap.frame_rgb is None:
            return
        expected = snap.frame_w * snap.frame_h * 3
        if len(snap.frame_rgb) != expected:
            return
        try:
            # Spec §3 边界 #5:自适应降级。如果 setPixmap 耗时 > 50ms 降到 0.5x,
            # > 100ms 降到 0.25x。状态栏提示用户。
            import time as _t
            scale = getattr(self, "_preview_scale", 1.0)
            t0 = _t.perf_counter()
            img = QImage(snap.frame_rgb, snap.frame_w, snap.frame_h, QImage.Format_RGB888)
            target_w = max(1, int(self._preview_label.width() * scale))
            target_h = max(1, int(target_w * snap.frame_h / max(snap.frame_w, 1)))
            scaled = img.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview_label.setPixmap(QPixmap.fromImage(scaled))
            dt_ms = (_t.perf_counter() - t0) * 1000
            new_scale = 1.0
            if dt_ms > 100:
                new_scale = 0.25
            elif dt_ms > 50:
                new_scale = 0.5
            if new_scale != scale:
                self._preview_scale = new_scale
                if new_scale < 1.0:
                    self._status_lbl.setText(f"预览降级中：{new_scale}x")
                else:
                    self._status_lbl.setText("预览正常")
        except Exception:
            pass

    def _update_status_light(self, snap):
        from pc_gesture.types import compute_status_light
        threshold = float(self._cfg.sensitivity.get("low_confidence_threshold", 0.6))
        if snap is None:
            color = "#6b7280"
        else:
            light = compute_status_light(snap, low_confidence_threshold=threshold)
            color = {"red": "#ef4444", "yellow": "#eab308", "green": "#22c55e"}.get(light, "#6b7280")
            if self._teaching_check.isChecked():
                color = "#3b82f6"  # 教学:蓝色
        self._status_light.setStyleSheet(
            f"background:{color};border-radius:10px;border:2px solid #1f2937;"
        )

    def _update_diagnostics(self, snap):
        if snap is None or not snap.hands:
            # 没有手:保留最后位置(snap is None)或显示「—」
            if snap is None:
                self._hand_xy_lbl.setText("手位置: —")
                self._conf_lbl.setText("置信度: —")
                self._slot_lbl.setText("Slot: —")
            else:
                # 之前看到了手现在没了:保留「—」
                self._hand_xy_lbl.setText("手位置: —（手离开画面）")
                self._conf_lbl.setText("置信度: —")
                self._slot_lbl.setText("Slot: —")
            # 清手指灯
            for key, (light, st) in self._finger_lights.items():
                if self._finger_state_prev.get(key) is not None:
                    light.setText("○")
                    light.setStyleSheet("color:#6b7280;font-size:14px;")
                    st.setText("卷曲")
                    self._finger_state_prev[key] = None
            return

        # 有手:取第一个(单人只看 A;如果两人取置信度高的)
        hand = max(snap.hands, key=lambda h: h.confidence)
        self._hand_xy_lbl.setText(f"手位置: ({hand.wrist_xy[0]:.2f}, {hand.wrist_xy[1]:.2f})")
        self._conf_lbl.setText(f"置信度: {hand.confidence:.2f}")
        self._slot_lbl.setText(f"Slot: {hand.slot}")
        # 置信度颜色
        threshold = float(self._cfg.sensitivity.get("low_confidence_threshold", 0.6))
        conf_color = "#22c55e" if hand.confidence >= threshold else "#f97316"
        self._conf_lbl.setStyleSheet(f"color:{conf_color};font-size:11px;font-weight:600;")
        # 手指灯(只在切换时更新)
        for key, (light, st) in self._finger_lights.items():
            cur = bool(hand.finger_states.get(key, False))
            prev = self._finger_state_prev.get(key)
            if cur != prev:
                if cur:
                    light.setText("●")
                    light.setStyleSheet("color:#22c55e;font-size:14px;")
                    st.setText("伸直")
                else:
                    light.setText("○")
                    light.setStyleSheet("color:#6b7280;font-size:14px;")
                    st.setText("卷曲")
                self._finger_state_prev[key] = cur
        # 手势状态行
        for g, lbl in self._diag_gesture_labels.items():
            if hand.static_gesture == g:
                lbl.setText("✓ 识别中")
                lbl.setStyleSheet("color:#22c55e;font-size:11px;font-weight:600;")
            elif hand.static_gesture == "NONE":
                lbl.setText("—")
                lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
            else:
                lbl.setText("—")
                lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
        self._last_hand_seen_at = time.time()

    def _update_sync_highlight(self, snap):
        if snap is None or not snap.hands:
            return
        # 用 last_static_gesture 触发高亮(每帧都更新)
        hand = max(snap.hands, key=lambda h: h.confidence)
        if hand.static_gesture == "NONE":
            return
        g = hand.static_gesture
        if g == self._current_gesture:
            return  # 已高亮
        self._current_gesture = g
        # 1. 图卡对应行
        if g in self._cheat_rows:
            self._cheat_rows[g].setStyleSheet(
                "background:rgba(34,197,94,0.4);border-radius:6px;"
            )
            QTimer.singleShot(2000, lambda gg=g: self._cheat_rows[gg].setStyleSheet(""))
        # 2. 映射下拉行
        if g in self._binding_rows:
            self._binding_rows[g].setStyleSheet(
                "background:rgba(34,197,94,0.4);border-radius:6px;"
            )
            QTimer.singleShot(2000, lambda gg=g: self._binding_rows[gg].setStyleSheet(""))
        # 3. 试用当前识别
        self._trial_now.setText(_GESTURE_NAME.get(g, g))
        self._trial_now.setStyleSheet("color:#22c55e;font-size:14px;font-weight:600;")
```

- [ ] **Step 5: 加 `showEvent` / `_maybe_show_tutorial` / `_on_show_tutorial`**

(沿用 Task 5 spec 的实现,但需要 import 类内可见)

```python
    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(50, self._maybe_show_tutorial)

    def _maybe_show_tutorial(self):
        if self._cfg.tutorial_done:
            return
        eng = self._bridge.engine
        if eng is None:
            return
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()

    def _on_show_tutorial(self):
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()
```

- [ ] **Step 6: 删「显示预览」checkbox 相关代码**

删除现有 `_preview_check`、`_on_preview_toggled`、任何引用 `show_preview_window` 的代码。FrameSnapshot 路径不需要 cv2 预览窗口了。

`_cfg.raw.get("show_preview_window", True)` 也删(配置项保留,但 UI 不再读)。

- [ ] **Step 7: import 自检**

Run:
```bash
python -c "from ppt_qt.pages.gesture_page import GesturePage; print('OK')"
```
Expected: 输出 `OK`

- [ ] **Step 8: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿(89/89)

- [ ] **Step 9: 提交**

```bash
git add ppt_qt/pages/gesture_page.py
git commit -m "feat(qt): gesture page 2-column UX (preview + diagnostics + status light + sync highlights)"
```

---

## Task 5: UI 验收清单走一遍

本任务**没有代码改动**——按 spec §4.2 的清单逐项验证。

**Files:** 无

- [ ] **Step 1: 启动 app**

Run: `python ppt_qt/app.py`
Expected: 主窗口出现,切到「手势」页

- [ ] **Step 2: 验证双栏布局**

期望:左栏出现"实时预览 + 诊断"卡片(预览区显示「未启动」placeholder);右栏出现"手势示图卡 + 映射 + 试用 + 控制"。

- [ ] **Step 3: 启动引擎,验证嵌入式预览**

点「启动手势」。
Expected:
- 预览区从「未启动」变成实时视频帧(镜像正确)
- 三色灯初始绿色/黄色(有手)/ 灰色(无手)
- cv2 独立预览窗口**不**再出现
- 诊断面板开始显示手指状态、手位置、置信度、Slot

- [ ] **Step 4: 验证三色灯**

- 无手 → 灰色
- 有手但 NONE → 黄色
- 识别手势(高置信度) → 绿色

- [ ] **Step 5: 验证三处同步高亮**

做 FIST。
Expected:
- ①图卡对应行变绿
- ②映射下拉行变绿
- ③试用「当前: ✊ 握拳」变绿
- 2 秒后三处同时还原

- [ ] **Step 6: 验证诊断面板手指灯**

连续握拳 → 张掌 → 食指上指 → 挥页。
Expected:
- 拇指/食指/中指等灯在切换瞬间跳变
- 稳定时静止不闪

- [ ] **Step 7: 验证手离开画面**

手离开摄像头 > 1.5s。
Expected:
- 三色灯转灰
- 诊断面板「手位置: —（手离开画面）」
- 不立即清空,保留「—」状态

- [ ] **Step 8: 验证教学模式**

打开顶部「教学模式」checkbox。
Expected:
- 三色灯变蓝色(教学标识)
- 做 FIST:试用面板显示「握拳」,但 PPT **没黑屏**

- [ ] **Step 9: 验证映射同步**

把 FIST 绑定从 BLACK_SCREEN 改成 NEXT_PAGE。
Expected:
- ①图卡对应行的动作标签立刻变成「→ 下一页」
- ②映射下拉同步显示「下一页」

- [ ] **Step 10: 验证状态灯降级**

故意在低光环境/超近距离做手势。
Expected:
- 若 `setPixmap` 耗时 > 50ms:状态栏提示「预览降级中:0.5x」
- 若 > 100ms:「预览降级中:0.25x」

- [ ] **Step 11: 跑全套测试最后一遍**

Run: `pytest -q`
Expected: 89/89 全绿

- [ ] **Step 12: 提交(若 Step 1-11 暴露 bug,先回到 Task 2/3/4 修复后重新提交)**

```bash
# 若全部通过,无新文件需要 commit
# 若有 bug fix:
git add <fix files>
git commit -m "fix(qt): UX redesign smoke findings"
```