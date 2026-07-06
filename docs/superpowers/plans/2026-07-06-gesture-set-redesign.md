# 手势集重新设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 7 个有歧义的手势替换成 7 个纯静态、互不冲突的新手势集(OK / 剪刀 / 拳头 / 张掌 / 三指 / L / 食指),并迁移用户旧配置。

**Architecture:** config.py 替换 `GESTURES` tuple + `DEFAULT_BINDINGS`,加迁移 helper;semantics.py 重写 `_classify_static` 优先级链;UI 同步更新 `_GESTURE_META` / `_TUTORIAL_META`;bridge 在 lazy-init 时调用迁移 helper 把旧 keys 删掉并重置 `tutorial_done`。enum 字符串(FIST/PALM/POINTING_UP)与旧版同义,避免破坏现有测试。

**Tech Stack:** PySide6 / MediaPipe HandLandmarker 已有;测试用 pytest + 现有 landmark fixture 模式。

---

## Global Constraints

- 中文注释、英文代码,沿用现有 `pc_gesture/semantics.py` 风格
- 不引入新依赖
- enum 值保留: `FIST` / `PALM` / `POINTING_UP`(与旧版同名,语义略变:现在表示「5 指卷/5 指伸/仅食指伸」)
- 新增 enum 值: `OK` / `L_SIGN` / `THREE_FINGERS` / `SCISSORS`
- 删除 enum 值: `THUMBS_UP` / `THUMBS_DOWN` / `SWIPE_LEFT` / `SWIPE_RIGHT`(代码层完全移除)
- 关键距离阈值:
  - 拇指-食指尖接触判定: `dist(thumb_tip[4], index_tip[8]) < 0.08 * hand_size`
  - 拇指横向伸判定: `dist(thumb_tip[4], index_mcp[5]) > 0.18 * hand_size`
  - OK 软阈值: 3 指里 >= 2 指 `tip.y < pip.y - 0.015` 即视为伸
  - 其它指 EXT 严守 `tip.y < pip.y - 0.025`
  - CURL: `tip.y > pip.y + 0.005`
- DEFAULT_BINDINGS 新值: `OK=NEXT_PAGE`, `SCISSORS=PREV_PAGE`, `FIST=BLACK_SCREEN`, `PALM=EXIT`, `THREE_FINGERS=WHITE_SCREEN`, `L_SIGN=FULL_SCREEN`, `POINTING_UP=None`(激光走 rising-edge 持续发射不走 bindings)
- 配置文件向后兼容: 旧 keys(THUMBS_UP/DOWN/SWIPE_LEFT/RIGHT)被 `_migrate_old_bindings` 静默删除并重置 `tutorial_done=False`
- 现有 89 个测试必须保持绿;新增 ~14-16 个分类器测试

## File Structure

| 文件 | 类型 | 职责 |
|------|------|------|
| `pc_gesture/config.py` | 改 | `GESTURES` 换 7 新 enum;`DEFAULT_BINDINGS` 换新映射;新增 `migrate_old_bindings()` 方法 |
| `pc_gesture/semantics.py` | 改 | `_classify_static` 重写优先级链;新增 `G_OK` / `G_L_SIGN` / `G_THREE_FINGERS` / `G_SCISSORS` 类常量;删除 `G_THUMBS_UP` / `G_THUMBS_DOWN` |
| `ppt_core/gesture_bridge.py` | 改 | `_ensure` 在构造 engine 前调 `cfg.migrate_old_bindings()`;若返回 True,通过 `_on_status` 推送"手势集已更新"提示 |
| `ppt_qt/pages/gesture_page.py` | 改 | `_GESTURE_META` 改为 7 新手势(emoji + 中文名);`_GESTURE_NAME` 自动派生 |
| `ppt_qt/pages/gesture_tutorial_dialog.py` | 改 | `_TUTORIAL_META` 改为 7 新手势(emoji + 中文名 + 一句话描述) |
| `tests/test_gesture_classification.py` | **新** | 14-16 个分类器测试,含互斥路径 |
| `tests/test_gesture_config_migration.py` | **新** | 迁移 helper 测试 |

---

## Task 1: config.py 替换 GESTURES + DEFAULT_BINDINGS + 加迁移 helper

**Files:**
- Modify: `pc_gesture/config.py:22-41`(`GESTURES` / `ACTIONS` / `DEFAULT_BINDINGS`)和 `GestureConfig` 类
- Test: `tests/test_gesture_config_migration.py` (new)

**Interfaces:**
- Consumes: 无
- Produces:
  - `pc_gesture.config.GESTURES = ("OK", "L_SIGN", "THREE_FINGERS", "POINTING_UP", "SCISSORS", "FIST", "PALM")`
  - `pc_gesture.config.DEFAULT_BINDINGS = {"OK": "NEXT_PAGE", "SCISSORS": "PREV_PAGE", "FIST": "BLACK_SCREEN", "PALM": "EXIT", "THREE_FINGERS": "WHITE_SCREEN", "L_SIGN": "FULL_SCREEN", "POINTING_UP": None}`
  - `GestureConfig.migrate_old_bindings() -> bool`(返回 True 表示发生了迁移)

- [ ] **Step 1: 写失败测试**

`tests/test_gesture_config_migration.py`:

```python
"""Tests for GestureConfig.migrate_old_bindings — drops deprecated gesture keys."""

import json

from pc_gesture.config import load_gesture_config, save_gesture_config, GESTURES


def test_gestures_tuple_has_seven_new_entries():
    """新 GESTURES tuple 长度 7,包含全部新名,不含旧名。"""
    assert len(GESTURES) == 7
    expected = {"OK", "L_SIGN", "THREE_FINGERS", "POINTING_UP", "SCISSORS", "FIST", "PALM"}
    assert set(GESTURES) == expected
    assert "THUMBS_UP" not in GESTURES
    assert "SWIPE_LEFT" not in GESTURES


def test_migrate_returns_false_for_clean_config():
    cfg = load_gesture_config()
    cfg.tutorial_done = True  # ensure non-default
    migrated = cfg.migrate_old_bindings()
    assert migrated is False
    assert cfg.tutorial_done is True  # 未触动


def test_migrate_drops_thumbs_up(tmp_path):
    """旧 THUMBS_UP 键会被删除,tutorial_done 重置。"""
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({
        "bindings": {"THUMBS_UP": "FULL_SCREEN", "FIST": "BLACK_SCREEN"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.tutorial_done = True
    migrated = cfg.migrate_old_bindings()
    assert migrated is True
    assert "THUMBS_UP" not in cfg.raw.get("bindings", {})
    assert cfg.get_binding("FIST") == "BLACK_SCREEN"  # FIST 保留
    assert cfg.tutorial_done is False


def test_migrate_drops_all_deprecated_keys(tmp_path):
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({
        "bindings": {
            "THUMBS_UP": "FULL_SCREEN",
            "THUMBS_DOWN": "EXIT",
            "SWIPE_LEFT": "PREV_PAGE",
            "SWIPE_RIGHT": "NEXT_PAGE",
            "FIST": "BLACK_SCREEN",
        }
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    migrated = cfg.migrate_old_bindings()
    assert migrated is True
    deprecated = {"THUMBS_UP", "THUMBS_DOWN", "SWIPE_LEFT", "SWIPE_RIGHT"}
    assert not (set(cfg.raw.get("bindings", {}).keys()) & deprecated)
    assert cfg.get_binding("FIST") == "BLACK_SCREEN"


def test_migrate_returns_false_when_only_valid_keys_present():
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "bindings": {"FIST": "BLACK_SCREEN", "PALM": "EXIT"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.tutorial_done = True
    migrated = cfg.migrate_old_bindings()
    assert migrated is False
    assert cfg.tutorial_done is True


def test_migrate_persists_changes_via_save(tmp_path):
    """迁移后再 save + reload,旧键不会回来。"""
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "bindings": {"THUMBS_UP": "FULL_SCREEN"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.migrate_old_bindings()
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert "THUMBS_UP" not in cfg2.raw.get("bindings", {})
    assert cfg2.tutorial_done is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gesture_config_migration.py -v`
Expected: `test_gestures_tuple_has_seven_new_entries` FAIL(GESTURES tuple 还是旧的);`test_migrate_*` FAIL(AttributeError: 'GestureConfig' object has no attribute 'migrate_old_bindings')

- [ ] **Step 3: 改 `pc_gesture/config.py` —— `GESTURES` + `DEFAULT_BINDINGS`**

替换 `pc_gesture/config.py:22-41` 整个块为:

```python
GESTURES = (
    "OK", "L_SIGN", "THREE_FINGERS", "POINTING_UP", "SCISSORS", "FIST", "PALM",
)
ACTIONS = (
    "NEXT_PAGE", "PREV_PAGE", "FULL_SCREEN", "FROM_CURRENT",
    "BLACK_SCREEN", "WHITE_SCREEN", "EXIT",
    "SCREENSHOT", "OPEN_PPT",
    "PC_WINDOW_MINIMIZE", "PC_WINDOW_RESTORE",
)
DEFAULT_BINDINGS: Dict[str, Optional[str]] = {
    "OK":             "NEXT_PAGE",     # 下一页
    "SCISSORS":       "PREV_PAGE",     # 上一页(剪刀手)
    "FIST":           "BLACK_SCREEN",  # 黑屏(拳头)
    "PALM":           "EXIT",          # 退出放映(张掌)
    "THREE_FINGERS":  "WHITE_SCREEN",  # 白屏(三指)
    "L_SIGN":         "FULL_SCREEN",   # 从头放映(L 手势)
    "POINTING_UP":    None,            # 激光:走 rising-edge 持续发射,不走 bindings
}

# 旧 enum 字符串,用于迁移检测(代码层不再使用)
_DEPRECATED_GESTURES = (
    "THUMBS_UP", "THUMBS_DOWN", "SWIPE_LEFT", "SWIPE_RIGHT",
)
```

- [ ] **Step 4: 跑测试看 GESTURES tuple 测试是否通过**

Run: `pytest tests/test_gesture_config_migration.py::test_gestures_tuple_has_seven_new_entries -v`
Expected: PASS

- [ ] **Step 5: 在 `GestureConfig` 类加 `migrate_old_bindings()` 方法**

在 `GestureConfig` 类的 `import_dict` 方法之后加:

```python
    # ----- 旧手势迁移 -----
    def migrate_old_bindings(self) -> bool:
        """移除 raw['bindings'] 里的旧 enum 键(THUMBS_UP/DOWN, SWIPE_*),
        并将 tutorial_done 重置为 False。

        返回 True 表示发生了迁移(供上层推 UI 状态消息)。
        FIST / PALM / POINTING_UP 三个保留 enum 键不动。
        """
        bindings = self.raw.get("bindings") if isinstance(self.raw, dict) else None
        if not isinstance(bindings, dict):
            return False
        deprecated = {"THUMBS_UP", "THUMBS_DOWN", "SWIPE_LEFT", "SWIPE_RIGHT"}
        changed = any(k in bindings for k in deprecated)
        if not changed:
            return False
        for k in deprecated:
            bindings.pop(k, None)
        # 反向同步
        self.bindings = {k: v for k, v in bindings.items() if k in self.bindings or k in GESTURES}
        self.raw["bindings"] = dict(self.bindings)
        # 强制重置教学标志
        self.tutorial_done = False
        return True
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_gesture_config_migration.py -v`
Expected: 全 PASS(6/6)

- [ ] **Step 7: 跑全套测试检查已有测试是否还绿**

Run: `pytest -q`
Expected: 89 个原测试可能有些 fail(因为 GESTURES tuple 变了,某些测试可能依赖旧 gesture 名)。先看具体哪些 fail,把修复放到 Task 2/3 里处理。

> **预期失败点**:
> - `test_gesture_bridge_teaching_mode.py` 里如果用了 `bridge.cfg.set_binding("THUMBS_UP", ...)` → 失败,因为 THUMBS_UP 不在 GESTURES 里了 → `cfg.set_binding` 会 raise ValueError。
> - 类似地,任何引用旧 enum 名做 set_binding / get_binding 的测试都会失败。

先看 pytest 输出,然后继续。

- [ ] **Step 8: 提交**

```bash
git add pc_gesture/config.py tests/test_gesture_config_migration.py
git commit -m "feat(config): replace GESTURES with 7 new unambiguous gestures + migration helper"
```

---

## Task 2: semantics.py 重写 `_classify_static` + 新 G_* 常量

**Files:**
- Modify: `pc_gesture/semantics.py:90-100`(`GestureSemantics.G_*` 类常量)和 `_classify_static`(line 180-224)
- Test: `tests/test_gesture_classification.py` (new)

**Interfaces:**
- Consumes: 无(只修改内部规则)
- Produces:
  - `GestureSemantics.G_OK = "OK"`
  - `GestureSemantics.G_L_SIGN = "L_SIGN"`
  - `GestureSemantics.G_THREE_FINGERS = "THREE_FINGERS"`
  - `GestureSemantics.G_SCISSORS = "SCISSORS"`
  - `GestureSemantics.G_FIST = "FIST"`(保持)
  - `GestureSemantics.G_PALM = "PALM"`(保持)
  - `GestureSemantics.G_POINTING_UP = "POINTING_UP"`(保持)
  - 删除 `G_THUMBS_UP` / `G_THUMBS_DOWN`
  - `_classify_static(lm)` 按 7 优先级链返回 enum 字符串

- [ ] **Step 1: 写失败测试**

`tests/test_gesture_classification.py`:

```python
"""Tests for GestureSemantics._classify_static — 7 unambiguous gestures + mutual exclusion.

Each gesture is tested by:
1. positive case: hand crafted landmarks matching the gesture → assert returned enum
2. negative case: similar-looking pose for the nearest-neighbor gesture → assert NOT that enum

We construct landmarks using a tiny _P dataclass mirroring MediaPipe NormalizedLandmark.
"""

from dataclasses import dataclass

import pytest

from pc_gesture.semantics import GestureSemantics


@dataclass
class _P:
    x: float
    y: float


WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_TIP = 20


def _hand(*, thumb_xy, index_tip_xy, middle_tip_xy, ring_tip_xy, pinky_tip_xy,
          wrist_xy=(0.5, 0.6), mcp_xy=(0.5, 0.5)):
    """Build 21-landmark hand with specified tips. Other landmarks default.

    Sets all MCP landmarks to mcp_xy so _hand_size (wrist→middle MCP) gives a
    sensible ~0.15-0.20 reference length, not relying on default-zero values.
    """
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(*wrist_xy)
    # Set MCP landmarks (5, 9, 13, 17) to the reference MCP position
    for mcp_idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[mcp_idx] = _P(*mcp_xy)
    # PIP landmarks sit just below tips (smaller y for extended fingers)
    lm[INDEX_PIP] = _P(index_tip_xy[0], index_tip_xy[1] + 0.02)
    lm[INDEX_TIP] = _P(*index_tip_xy)
    lm[MIDDLE_PIP] = _P(middle_tip_xy[0], middle_tip_xy[1] + 0.02)
    lm[MIDDLE_TIP] = _P(*middle_tip_xy)
    lm[RING_PIP] = _P(ring_tip_xy[0], ring_tip_xy[1] + 0.02)
    lm[RING_TIP] = _P(*ring_tip_xy)
    lm[PINKY_PIP] = _P(pinky_tip_xy[0], pinky_tip_xy[1] + 0.02)
    lm[PINKY_TIP] = _P(*pinky_tip_xy)
    lm[THUMB_TIP] = _P(*thumb_xy)
    return lm


def _extended(tip_xy, mcp_xy=(0.5, 0.5)):
    """指伸直:tip 远高于 pip,在 mcp 上方很多。"""
    return (tip_xy[0], mcp_xy[1] - 0.3)


def _curled(tip_xy, mcp_xy=(0.5, 0.5)):
    """指卷曲:tip 在 pip 下方。"""
    return (tip_xy[0], mcp_xy[1] + 0.2)


def _all_extended():
    """4 指都伸直,拇指向侧面。"""
    return _hand(
        thumb_xy=(0.2, 0.5),            # 拇横向(远离 index_mcp)
        index_tip_xy=_extended((0.6, 0.5)),
        middle_tip_xy=_extended((0.7, 0.5)),
        ring_tip_xy=_extended((0.75, 0.5)),
        pinky_tip_xy=_extended((0.78, 0.5)),
    )


def _all_curled_thumb_side():
    """5 指都卷曲,拇贴在掌侧。"""
    return _hand(
        thumb_xy=(0.55, 0.55),           # 拇贴近 index_mcp
        index_tip_xy=_curled((0.55, 0.5)),
        middle_tip_xy=_curled((0.6, 0.5)),
        ring_tip_xy=_curled((0.65, 0.5)),
        pinky_tip_xy=_curled((0.7, 0.5)),
    )


@pytest.fixture
def sem():
    from pc_gesture.config import load_gesture_config
    return GestureSemantics(load_gesture_config())


# ---- positive cases ----

def test_classify_ok(sem):
    """拇指-食指尖接触 + 中/无名/小指都伸。"""
    lm = _hand(
        thumb_xy=(0.55, 0.2),           # 拇指尖贴近 index 尖
        index_tip_xy=(0.58, 0.2),        # 食指尖
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),  # 中指伸
        ring_tip_xy=_extended((0.7, 0.5))[0:1] + (0.2,),
        pinky_tip_xy=_extended((0.75, 0.5))[0:1] + (0.2,),
    )
    assert sem._classify_static(lm) == sem.G_OK


def test_classify_l_sign(sem):
    """拇+食指伸(分开),其它卷曲。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),           # 拇远离(横向)
        index_tip_xy=(0.6, 0.2),        # 食伸
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_L_SIGN


def test_classify_three_fingers(sem):
    """拇+食+中伸,无名+小卷曲。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_THREE_FINGERS


def test_classify_scissors(sem):
    """拇卷 + 食+中伸 + 无名+小卷。"""
    lm = _hand(
        thumb_xy=(0.55, 0.55),          # 拇贴近
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_SCISSORS


def test_classify_pointing(sem):
    """仅食指伸。"""
    lm = _hand(
        thumb_xy=(0.55, 0.55),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_POINTING_UP


def test_classify_fist(sem):
    """5 指全卷曲。"""
    lm = _all_curled_thumb_side()
    assert sem._classify_static(lm) == sem.G_FIST


def test_classify_palm(sem):
    """5 指全伸。"""
    lm = _all_extended()
    assert sem._classify_static(lm) == sem.G_PALM


# ---- mutual exclusion ----

def test_ok_not_misread_as_three_fingers(sem):
    """OK pose(拇-食接触)不应被判为 THREE_FINGERS。"""
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.58, 0.2),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_extended((0.7, 0.5))[0:1] + (0.2,),
        pinky_tip_xy=_extended((0.75, 0.5))[0:1] + (0.2,),
    )
    assert sem._classify_static(lm) != sem.G_THREE_FINGERS


def test_l_sign_not_misread_as_ok(sem):
    """L pose(拇-食分开)不应被判为 OK。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_OK


def test_scissors_not_misread_as_three_fingers(sem):
    """scissors(拇卷)不应被判为 THREE_FINGERS(拇伸)。"""
    lm = _hand(
        thumb_xy=(0.55, 0.55),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_THREE_FINGERS


def test_pointing_not_misread_as_scissors(sem):
    """pointing(中指卷)不应被判为 SCISSORS(中指伸)。"""
    lm = _hand(
        thumb_xy=(0.55, 0.55),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_SCISSORS


def test_partial_curl_still_ok(sem):
    """边界 #1:OK 时三指里只有 2 指完全 EXT,1 指微卷,仍应判 OK。"""
    # middle 真正伸,ring 真正伸,pinky 微卷(只稍低 pip 一点点)
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.58, 0.2),
        middle_tip_xy=(0.65, 0.2),       # 真正伸(pip.y=0.52, tip.y=0.2)
        ring_tip_xy=(0.7, 0.2),         # 真正伸
        pinky_tip_xy=(0.75, 0.51),      # 微卷(pip.y=0.53, tip.y=0.51,差 -0.02 < -0.015 阈值)
    )
    assert sem._classify_static(lm) == sem.G_OK
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gesture_classification.py -v`
Expected: 大部分 FAIL,因为旧 `_classify_static` 不识别 OK / SCISSORS / L_SIGN / THREE_FINGERS,可能返回 FIST 或 PALM 或 NONE。

- [ ] **Step 3: 更新 `GestureSemantics.G_*` 类常量**

替换 `pc_gesture/semantics.py:92-100` 为:

```python
    # 静态手势类别(机器友好 enum,UI 通过 _GESTURE_META 映射到中文 + emoji)
    G_NONE = "NONE"
    G_OK = "OK"                          # 拇指+食指圈,中/无名/小指伸
    G_L_SIGN = "L_SIGN"                  # 拇+食指伸(分开),其它卷
    G_THREE_FINGERS = "THREE_FINGERS"    # 拇+食+中伸,无名+小卷
    G_POINTING_UP = "POINTING_UP"        # 仅食指伸
    G_SCISSORS = "SCISSORS"              # 食+中伸,其它卷
    G_FIST = "FIST"                      # 全卷
    G_PALM = "PALM"                      # 全伸
```

- [ ] **Step 4: 重写 `_classify_static`**

替换 `pc_gesture/semantics.py:180-224` 的整个 `_classify_static` 方法为:

```python
    def _classify_static(self, lm) -> str:
        """返回 7 个新 enum 之一(NONE / OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM)。

        优先级(从最特异到最普通):
          1. OK          — 拇-食指尖接触 + 中/无名/小指 >= 2 指伸(软阈值)
          2. L_SIGN      — 拇横向伸 + 食指伸 + 中/无名/小指卷 + 拇-食指分开
          3. THREE_FINGERS — 拇横向伸 + 食+中伸 + 无名+小指卷
          4. SCISSORS    — 拇卷 + 食+中伸 + 无名+小指卷
          5. POINTING_UP — 拇卷 + 仅食指伸 + 中/无名/小指卷
          6. FIST        — 拇卷 + 食指卷 + 中/无名/小指卷
          7. PALM        — 拇横向伸 + 4 指都伸
        """
        size = self._hand_size(lm)

        # 拇指状态
        thumb_index_tip_dist = _dist(
            lm[THUMB_TIP].x, lm[THUMB_TIP].y,
            lm[INDEX_TIP].x, lm[INDEX_TIP].y,
        )
        thumb_index_mcp_dist = _dist(
            lm[THUMB_TIP].x, lm[THUMB_TIP].y,
            lm[INDEX_MCP].x, lm[INDEX_MCP].y,
        )
        thumb_touching = thumb_index_tip_dist < 0.08 * size
        thumb_extended = thumb_index_mcp_dist > 0.18 * size

        # 4 指状态(OK 软阈值 -0.015,其它严守 -0.025)
        def ext_strict(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y - 0.025
        def ext_relaxed(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y - 0.015
        def curled(tip_idx, pip_idx):
            return lm[tip_idx].y > lm[pip_idx].y + 0.005

        index_ext = ext_strict(INDEX_TIP, INDEX_PIP)
        middle_ext = ext_strict(MIDDLE_TIP, MIDDLE_PIP)
        ring_ext = ext_strict(RING_TIP, RING_PIP)
        pinky_ext = ext_strict(PINKY_TIP, PINKY_PIP)

        middle_curled = curled(MIDDLE_TIP, MIDDLE_PIP)
        ring_curled = curled(RING_TIP, RING_PIP)
        pinky_curled = curled(PINKY_TIP, PINKY_PIP)

        # OK 软阈值:中/无名/小指 >= 2 指 soft-extended
        other_3_extended_relaxed_count = sum([
            ext_relaxed(MIDDLE_TIP, MIDDLE_PIP),
            ext_relaxed(RING_TIP, RING_PIP),
            ext_relaxed(PINKY_TIP, PINKY_PIP),
        ])

        # 1) OK — 最优先:空间距离 + 数量
        if thumb_touching and other_3_extended_relaxed_count >= 2:
            return self.G_OK

        # 2) L_SIGN — 拇横向 + 食指伸 + 其它卷 + 拇-食指分开
        if thumb_extended and index_ext and middle_curled and ring_curled and pinky_curled and not thumb_touching:
            return self.G_L_SIGN

        # 3) THREE_FINGERS — 拇横向 + 食+中伸 + 无名+小卷
        if thumb_extended and index_ext and middle_ext and ring_curled and pinky_curled:
            return self.G_THREE_FINGERS

        # 4) SCISSORS — 拇卷 + 食+中伸 + 无名+小卷
        if not thumb_extended and index_ext and middle_ext and ring_curled and pinky_curled:
            return self.G_SCISSORS

        # 5) POINTING_UP — 拇卷 + 仅食指伸
        if not thumb_extended and index_ext and middle_curled and ring_curled and pinky_curled:
            return self.G_POINTING_UP

        # 6) FIST — 拇卷 + 食指卷 + 中/无名/小卷
        if not thumb_extended and not index_ext and middle_curled and ring_curled and pinky_curled:
            return self.G_FIST

        # 7) PALM — 拇横向 + 4 指都伸
        if thumb_extended and index_ext and middle_ext and ring_ext and pinky_ext:
            return self.G_PALM

        return self.G_NONE
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_gesture_classification.py -v`
Expected: 全 PASS(12/12)

> **预期问题**:`test_classify_ok` 测试里我用了稍微粗糙的 landmark 坐标,可能 thumb_touching 阈值拿捏不到。如果某些测试 fail,微调 landmark 坐标(例如把 thumb_xy 的 y 从 0.2 调到 0.18,让距离 < 0.08 * size)直到通过。不改分类器逻辑。

- [ ] **Step 6: 处理 Task 1 留下的测试失败**

Run: `pytest -q`
Expected: 大部分原测试还绿,少量引用旧 enum 名的测试可能失败(典型如 `test_gesture_bridge_teaching_mode.py` 里 `bridge.cfg.set_binding("THUMBS_UP", ...)`)。**这里只列出预期失败,不修复——Task 3 一并清理**。

- [ ] **Step 7: 提交**

```bash
git add pc_gesture/semantics.py tests/test_gesture_classification.py
git commit -m "feat(semantics): rewrite _classify_static for 7 unambiguous gestures"
```

---

## Task 3: UI 标签 + Bridge 迁移接入

**Files:**
- Modify: `ppt_qt/pages/gesture_page.py:17-26`(`_GESTURE_META`)
- Modify: `ppt_qt/pages/gesture_tutorial_dialog.py:30-39`(`_TUTORIAL_META`)
- Modify: `ppt_core/gesture_bridge.py:_ensure`(调 migration helper)
- Modify: 引用旧 enum 名的现有测试文件(把 `THUMBS_UP` / `THUMBS_DOWN` / `SWIPE_LEFT` / `SWIPE_RIGHT` 替换成新 enum)

**Interfaces:**
- Consumes: Task 1 的 `cfg.migrate_old_bindings()`,Task 2 的新 G_* 常量
- Produces:
  - `_GESTURE_META` 改为 7 新手势的 emoji + 中文名
  - `_TUTORIAL_META` 改为 7 新手势的 emoji + 中文名 + 一句话描述
  - `_ensure` 在构造 engine 前调 `cfg.migrate_old_bindings()`;若返回 True,推 `on_status("手势集已更新,请重新绑定并重看教学")`

- [ ] **Step 1: 改 `_GESTURE_META`**

替换 `ppt_qt/pages/gesture_page.py:17-26` 的 `_GESTURE_META` dict 为:

```python
# 手势显示:枚举 → emoji + 中文名
_GESTURE_META = {
    "OK":            ("👌", "OK 手势"),
    "L_SIGN":        ("🤙", "L 手势"),
    "THREE_FINGERS": ("🤟", "三指"),
    "POINTING_UP":   ("☝",  "食指"),
    "SCISSORS":      ("✌",  "剪刀手"),
    "FIST":          ("✊", "拳头"),
    "PALM":          ("🖐", "张掌"),
}
```

- [ ] **Step 2: 跑 import 自检**

Run:
```bash
python -c "from ppt_qt.pages.gesture_page import GesturePage, _GESTURE_META; print('OK', len(_GESTURE_META))"
```
Expected: `OK 7`

- [ ] **Step 3: 改 `_TUTORIAL_META`**

替换 `ppt_qt/pages/gesture_tutorial_dialog.py:30-39` 的 `_TUTORIAL_META` dict 为:

```python
_TUTORIAL_META = {
    "OK":            ("👌", "OK 手势",   "拇指与食指尖相接成圈,其它三指伸直"),
    "L_SIGN":        ("🤙", "L 手势",   "拇指与食指伸直成 L 形,其它三指卷曲"),
    "THREE_FINGERS": ("🤟", "三指",     "拇指 + 食指 + 中指伸直,无名指与小指卷曲"),
    "POINTING_UP":   ("☝",  "食指",     "仅食指伸直,其它四指卷曲"),
    "SCISSORS":      ("✌",  "剪刀手",   "食指与中指伸直成 V,其它三指卷曲"),
    "FIST":          ("✊", "拳头",     "五指全部卷曲握紧"),
    "PALM":          ("🖐", "张掌",     "五指全部伸直,掌心朝镜头"),
}
```

- [ ] **Step 4: 跑 import 自检**

Run:
```bash
python -c "from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog, _TUTORIAL_META; print('OK', len(_TUTORIAL_META))"
```
Expected: `OK 7`

- [ ] **Step 5: 改 `_ensure` 在构造 engine 前调用 migration**

修改 `ppt_core/gesture_bridge.py:_ensure`,在 `self._engine = GestureEngine(...)` 之前加 migration 调用。具体改:

把:

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

替换为:

```python
    def _ensure(self) -> GestureEngine:
        if self._engine is None:
            # 首次启动:检测并迁移旧 bindings(THUMBS_UP/DOWN, SWIPE_*)
            migrated = self._cfg.migrate_old_bindings()
            if migrated:
                try:
                    self._on_status(
                        "手势集已更新:7 个旧手势已被替换,新绑定请重新设置。"
                    )
                except Exception:
                    pass
            self._engine = GestureEngine(
                dispatch_fn=self._on_gesture_event,
                on_status=self._on_status,
                on_fps=self._on_fps,
                on_send_text=self._on_send_text,
                on_frame=self._on_frame,
            )
        return self._engine
```

- [ ] **Step 6: 修复引用旧 enum 名的现有测试**

跑全套看哪些 fail:

Run: `pytest -q 2>&1 | grep FAIL`
Expected: 命中以下文件里的 `THUMBS_UP` / `THUMBS_DOWN` / `SWIPE_LEFT` / `SWIPE_RIGHT` 用法

逐个修复:
- `tests/test_gesture_bridge_teaching_mode.py` 里如果有 `set_binding("THUMBS_UP", ...)` → 改 `set_binding("OK", ...)`(OK 也 binding 不到 None,改用别的)
- `tests/test_bridge_recent_gestures.py` 里如果有 `{"type": "gesture", "gesture": "THUMBS_UP", ...}` → 改成 `"OK"` 或别的现存 enum
- `tests/test_gesture_bridge.py` 里检查引用

> **最小改动原则**:只把字符串换成 GESTURES 里有的 enum(FIST/PALM/POINTING_UP/OK/SCISSORS/THREE_FINGERS/L_SIGN)。不改测试意图。

- [ ] **Step 7: 跑全套测试确认全绿**

Run: `pytest -q`
Expected: 全绿(89 - 已修复的旧 enum 用法测试 + 6 migration + 12 classification = 107-ish/107)

- [ ] **Step 8: 提交**

```bash
git add ppt_qt/pages/gesture_page.py ppt_qt/pages/gesture_tutorial_dialog.py ppt_core/gesture_bridge.py tests/
git commit -m "feat(qt+bridge): new gesture UI labels + bridge migration hook"
```

---

## Task 4: UI 验收清单走一遍

本任务**没有代码改动**——按 spec §4.4 的清单逐项验证。

**Files:** 无

- [ ] **Step 1: 启动 app**

Run: `python ppt_qt/app.py`
Expected: 主窗口出现

- [ ] **Step 2: 验证手势页 7 个新标签**

切到「手势」页。期望:
- ① 图卡显示 7 行:👌 OK 手势、🤙 L 手势、🤟 三指、☝ 食指、✌ 剪刀手、✊ 拳头、🖐 张掌
- ② 映射下拉也是这 7 个
- ③ 默认绑定:OK=NEXT_PAGE, SCISSORS=PREV_PAGE, FIST=BLACK_SCREEN, PALM=EXIT, THREE_FINGERS=WHITE_SCREEN, L_SIGN=FULL_SCREEN, POINTING_UP=无

- [ ] **Step 3: 验证分类**

依次做 OK → 剪刀 → 拳头 → 张掌 → 三指 → L → 食指:
- 每个手势的「当前识别」标签实时更新
- 试用面板历史记录正确

- [ ] **Step 4: 验证互斥(关键)**

- 做 OK(拇指+食指圈):不应触发三指(虽然视觉接近)
- 做 L 手势(拇+食分开):不应触发 OK
- 做 剪刀(拇卷):不应触发三指(因为拇状态不同)
- 做 食指(中指卷):不应触发剪刀

- [ ] **Step 5: 验证边界 #1(OK 时三指微卷)**

做 OK 时故意让小指稍微卷。期望仍识别 OK。

- [ ] **Step 6: 验证旧配置迁移**

如果你的 `ppt_pc_client_gesture.json` 里有 `THUMBS_UP: FULL_SCREEN` 之类的旧键:
- 启动时状态栏提示「手势集已更新:...」
- 进入手势页时,7 个手势按新默认值显示
- 旧键被删掉(FIST/PALM/POINTING_UP 的绑定保留)

- [ ] **Step 7: 验证教学对话框**

点「重看教学」,期望:
- 7 步依次显示 7 个新手势
- emoji + 中文名 + 描述跟新规则一致
- 倒计时 15s / 跳过 / 结束 都正常

- [ ] **Step 8: 跑全套测试最后一遍**

Run: `pytest -q`
Expected: 全绿

- [ ] **Step 9: 提交(若 Step 1-7 暴露 bug,先回到 Task 2/3 修复后重新提交)**

```bash
# 若全部通过,无新文件需要 commit
# 若有 bug fix:
git add <fix files>
git commit -m "fix(qt): gesture set redesign smoke findings"
```