# 手势控制 教学功能 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `ppt_qt/pages/gesture_page.py` 加一套"手势教学"系统——静态图卡、首次启动自动弹向导、教学模式开关、识别实况高亮——让用户能学会并确认每个手势。

**Architecture:** 单页面扩展。所有 UI 加在现有 `GesturePage`(顶部开关 + 新图卡段 + 「重看教学」按钮);新增独立 `GestureTutorialDialog`(模态 QDialog, 7 步状态机);`GestureBridge` 加 `teaching_mode` 状态控制派发;`GestureConfig.raw` 加 `tutorial_done` 持久化。

**Tech Stack:** PySide6 (Qt for Python) + 现有 `pc_gesture` / `ppt_core` / `ppt_qt` 模块。测试用 pytest + monkeypatch(沿用现有 gesture_bridge / gesture_config 测试模式)。

---

## Global Constraints

- 中文注释、英文代码,与现有 `ppt_qt/pages/gesture_page.py` 风格保持一致
- 不引入新依赖(无 pytest-qt、无 PIL/动画库)
- Qt UI 控件对象名沿用 `PrimaryButton` / `SecondaryButton` / `GlassCard` 命名规范
- 新增代码必须不破坏现有 61 个测试(`pytest` 全绿)
- 配置文件向后兼容:`_merge_defaults` 必须能兜住旧的 `ppt_pc_client_gesture.json`(没有 `tutorial_done` 字段)
- 教学模式 / 教学向导均不持久化开关状态(默认 False);仅 `tutorial_done` 持久化

## File Structure

| 文件 | 类型 | 职责 |
|------|------|------|
| `pc_gesture/config.py` | 改 | `DEFAULT_GESTURE_CONFIG` 加 `tutorial_done: False`;`GestureConfig` 加同名属性 |
| `ppt_core/gesture_bridge.py` | 改 | `__init__` 加 `self._teaching_mode = False`;`set_teaching_mode(bool)` 公开方法;`_on_gesture_event` 在 `teaching_mode` 下跳过 dispatcher |
| `ppt_qt/pages/gesture_tutorial_dialog.py` | **新** | `GestureTutorialDialog(QDialog)` — 7 步状态机,倒计时,识别检测,完成/跳过写 `tutorial_done=True` |
| `ppt_qt/pages/gesture_page.py` | 改 | 顶部加「教学模式」QCheckBox;段 0 加静态图卡(7 行 emoji+名+动作+说明);试用面板加高亮;加「重看教学」按钮;`showEvent` 加自动弹 |
| `tests/test_gesture_config_tutorial_done.py` | **新** | 默认值/缺字段/读写回环 |
| `tests/test_gesture_bridge_teaching_mode.py` | **新** | 教学模式压住 dispatcher、关闭后恢复派发、仍写 `recent_gestures` |

---

## Task 1: GestureConfig 增加 `tutorial_done`

**Files:**
- Modify: `pc_gesture/config.py:46-70`(`DEFAULT_GESTURE_CONFIG`)和 `__post_init__` 区域
- Test: `tests/test_gesture_config_tutorial_done.py` (new)

**Interfaces:**
- Consumes: 无
- Produces: `GestureConfig.raw["tutorial_done"]: bool`(默认 False);`cfg.tutorial_done` 属性可读可写

- [ ] **Step 1: 写失败测试**

`tests/test_gesture_config_tutorial_done.py`:

```python
import json
import os
import tempfile

from pc_gesture.config import load_gesture_config, save_gesture_config


def test_tutorial_done_defaults_false():
    cfg = load_gesture_config()
    assert cfg.tutorial_done is False


def test_tutorial_done_round_trips(tmp_path):
    cfg = load_gesture_config()
    cfg.tutorial_done = True
    p = tmp_path / "gesture_cfg.json"
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert cfg2.tutorial_done is True


def test_tutorial_done_missing_in_old_config_is_backfilled(tmp_path):
    """旧配置文件没有 tutorial_done 字段时,_merge_defaults 必须补默认值 False。"""
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({"operator_mode": "single"}), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    assert cfg.tutorial_done is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gesture_config_tutorial_done.py -v`
Expected: 全部 FAIL,`AttributeError: 'GestureConfig' object has no attribute 'tutorial_done'`

- [ ] **Step 3: 加默认值 + 属性**

修改 `pc_gesture/config.py:46-70`,`DEFAULT_GESTURE_CONFIG` 字典内增加一行(放在 `"bindings": dict(DEFAULT_BINDINGS),` 之前):

```python
    "tutorial_done": False,
```

并在 `GestureConfig` 类内(mirror 与 `show_preview_window` 之后)增加:

```python
    # ----- tutorial_done -----
    @property
    def tutorial_done(self) -> bool:
        return bool(self.raw.get("tutorial_done", False))

    @tutorial_done.setter
    def tutorial_done(self, v: bool) -> None:
        self.raw["tutorial_done"] = bool(v)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_gesture_config_tutorial_done.py -v`
Expected: 全部 PASS(3/3)

- [ ] **Step 5: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿(包括原 61 个 + 新增 3 个 = 64/64)

- [ ] **Step 6: 提交**

```bash
git add pc_gesture/config.py tests/test_gesture_config_tutorial_done.py
git commit -m "feat(config): tutorial_done flag persisted in raw config"
```

---

## Task 2: GestureBridge 增加 `teaching_mode` 状态

**Files:**
- Modify: `ppt_core/gesture_bridge.py`(`__init__`、`_on_gesture_event`)
- Test: `tests/test_gesture_bridge_teaching_mode.py` (new)

**Interfaces:**
- Consumes: 无
- Produces: `bridge.teaching_mode` 属性(默认 False);`bridge.set_teaching_mode(bool)` 方法;`bridge._on_gesture_event` 在 `teaching_mode=True` 时**跳过 dispatcher.dispatch 但仍调用 `_record_recognized_gesture`**

- [ ] **Step 1: 写失败测试**

`tests/test_gesture_bridge_teaching_mode.py`:

```python
"""Tests for GestureBridge teaching_mode flag.

Teaching mode = recognize but don't dispatch. The UI's top toggle and
tutorial dialog both flip this state; the bridge must suppress dispatcher
calls while still populating ``recent_gestures`` so the trial panel and
the dialog can see what was recognized.
"""


def _make_bridge():
    import ppt_core.gesture_bridge as gb
    from ppt_core.gesture_bridge import GestureBridge

    captured = []

    class FakeDispatcher:
        def dispatch(self, d):
            captured.append(d)

    class FakeEngine:
        def __init__(self, **kwargs):
            pass
        def start(self):
            return None
        def stop(self):
            pass
        def start_pairing(self):
            pass
        def reset_pairing(self):
            pass
        def save_config(self):
            pass
        cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
        _semantics = None

    orig_engine = gb.GestureEngine
    gb.GestureEngine = FakeEngine
    try:
        bridge = GestureBridge(
            dispatcher=FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
    finally:
        gb.GestureEngine = orig_engine
    return bridge, captured


def test_teaching_mode_defaults_false():
    bridge, _ = _make_bridge()
    assert bridge.teaching_mode is False


def test_set_teaching_mode_updates_flag():
    bridge, _ = _make_bridge()
    bridge.set_teaching_mode(True)
    assert bridge.teaching_mode is True
    bridge.set_teaching_mode(False)
    assert bridge.teaching_mode is False


def test_teaching_mode_blocks_dispatcher_but_records_gesture():
    bridge, captured = _make_bridge()
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    bridge.set_teaching_mode(True)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"}
    )
    # Dispatcher was NOT called.
    assert captured == []
    # But recent_gestures() did get the recognition so UI / tutorial can see it.
    recent = bridge.recent_gestures()
    assert len(recent) == 1
    assert recent[0]["gesture"] == "FIST"


def test_teaching_mode_off_lets_dispatch_through():
    bridge, captured = _make_bridge()
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    bridge.set_teaching_mode(False)  # explicit
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"}
    )
    assert captured == [{"cmd": "BLACK_SCREEN"}]


def test_teaching_mode_does_not_swallow_unbound_gesture():
    """PALM is unbound by default — teaching_mode should not cause any side effect."""
    bridge, captured = _make_bridge()
    bridge.set_teaching_mode(True)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "PALM", "slot": "A", "source": "gesture:A"}
    )
    assert captured == []
    assert len(bridge.recent_gestures()) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_gesture_bridge_teaching_mode.py -v`
Expected: 全部 FAIL(`AttributeError: 'GestureBridge' object has no attribute 'teaching_mode'`)

- [ ] **Step 3: 改 GestureBridge**

在 `ppt_core/gesture_bridge.py` 的 `__init__` 里(`self._recent_gestures` 初始化之后)插入:

```python
        # Teaching mode: when True, the bridge still recognizes gestures and
        # records them in ``_recent_gestures`` for UI/trial observation, but
        # does NOT call ``dispatcher.dispatch``. The UI's top toggle and the
        # tutorial dialog control this. Default off — normal dispatch.
        self._teaching_mode: bool = False
```

并在 `__init__` 后面、lifecycle 区之前,加公开 API:

```python
    # --------------------------------------------------------------- teaching

    @property
    def teaching_mode(self) -> bool:
        return self._teaching_mode

    def set_teaching_mode(self, on: bool) -> None:
        self._teaching_mode = bool(on)
```

然后改 `_on_gesture_event` 的派发分支,变成:

```python
    def _on_gesture_event(self, ev: dict, source: str = "gesture") -> None:
        """Engine raw gesture event entry: filter + binding lookup + dispatch.

        The engine always invokes ``dispatch_fn(event, source)`` (see
        :meth:`pc_gesture.engine.GestureEngine._safe_dispatch`), so the second
        positional ``source`` argument must be accepted even though we only
        use the event payload here.
        """
        if not isinstance(ev, dict):
            return
        if ev.get("type") != "gesture":
            return
        gesture = ev.get("gesture")
        slot = ev.get("slot", "A")
        if slot != "A":
            return
        action = self._cfg.get_binding(gesture)
        # Always record what we recognized, regardless of teaching_mode —
        # the UI's trial panel and the tutorial dialog both poll
        # recent_gestures() and need to see recognition events.
        self._record_recognized_gesture(gesture, action, ev, source)
        # Teaching mode: skip the actual cmd dispatch but keep the recording.
        if self._teaching_mode:
            return
        if action:
            payload = _action_to_cmd(action, default_open_ppt_path="")
            if payload:
                try:
                    self._dispatcher.dispatch(payload)
                except Exception:
                    pass
```

注意:**`_record_recognized_gesture` 现在无条件调用**——这是从原代码的"先 record 再 dispatch"顺序中,把 record 提到条件外。这是行为变化,需要复核是否破坏 `test_gesture_bridge.py` 现有用例。看现有断言:

- `test_bridge_dispatch_passes_dispatcher` — 只断言 `dispatcher.calls == [{"cmd": "FULL_SCREEN"}]`,不查 recent_gestures。✅
- `test_bridge_skips_unbound_gesture` — 只断言 `captured == []`,不查 recent_gestures。✅
- `test_bridge_skips_non_a_slot` — 只断言 `captured == []`,不查 recent_gestures。但现在 `_record_recognized_gesture` 会调用,但 slot==B,ev 被吞掉所以还是不进 ring buffer。✅

- [ ] **Step 4: 跑新测试确认通过**

Run: `pytest tests/test_gesture_bridge_teaching_mode.py -v`
Expected: 全部 PASS(5/5)

- [ ] **Step 5: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿(64 + 5 = 69/69)

- [ ] **Step 6: 提交**

```bash
git add ppt_core/gesture_bridge.py tests/test_gesture_bridge_teaching_mode.py
git commit -m "feat(bridge): teaching_mode flag suppresses dispatch, keeps recognition"
```

---

## Task 3: 新建 `GestureTutorialDialog`

**Files:**
- Create: `ppt_qt/pages/gesture_tutorial_dialog.py`

**Interfaces:**
- Consumes: `bridge: GestureBridge`(用 `bridge.recent_gestures()` 读识别事件;`bridge.set_teaching_mode(bool)` 切换;`bridge.cfg` 读绑定 + 写 `tutorial_done`;`bridge.save()` 持久化);`parent: QWidget`(对话框父窗口)
- Produces: 模态对话框,内部使用 `QDialog.exec()` 阻塞;用户关闭后,若 step 数 == 7 且之前是 False,自动写 `cfg.tutorial_done = True; bridge.save()`

> **测试说明:** 纯 Qt 控件,本任务不写 pytest 自动测试,UI 验收清单见 Task 5。但必须在文件顶部 import 自检能跑通(见 Step 4)。

- [ ] **Step 1: 写文件骨架**

`ppt_qt/pages/gesture_tutorial_dialog.py`:

```python
"""GestureTutorialDialog — 7-step modal walkthrough.

Pops the first time the user enters the gesture page after starting the
engine (or manually via the "重看教学" button). Each step shows one of
the seven default gestures and waits up to 15s for the user to perform it.
Recognized → mark DONE → 1.5s auto-advance. Timeout → mark SKIPPED → next.

Side effects:
  * On open: saves bridge.teaching_mode, sets it to True.
  * On close: restores teaching_mode; if user reached step 7, sets
    cfg.tutorial_done=True and calls bridge.save().
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QFrame,
)

from pc_gesture.config import GESTURES


# Per-gesture display metadata (icon + Chinese name + one-line description).
# Mirrors the dict already used in gesture_page.py but kept local so the
# dialog can be moved/imported independently.
_TUTORIAL_META = {
    "FIST":         ("✊", "握拳",    "四指卷起，拇指压在食指外侧"),
    "PALM":         ("🖐", "张掌",    "五指全部伸直，掌心朝镜头"),
    "POINTING_UP":  ("☝", "食指上",  "只伸食指，其它四指卷起"),
    "THUMBS_UP":    ("👍", "竖拇指",  "拇指指向上方，其它四指卷起"),
    "THUMBS_DOWN":  ("👎", "拇指向下","拇指指向下方，其它四指卷起"),
    "SWIPE_LEFT":   ("◀", "挥左",    "张掌，手腕快速向左移"),
    "SWIPE_RIGHT":  ("▶", "挥右",    "张掌，手腕快速向右移"),
}

_STEP_TIMEOUT_MS = 15000        # 15s per step
_AUTO_ADVANCE_MS = 1500         # recognized → wait 1.5s before next step
_FINAL_CLOSE_MS = 800           # all DONE → 0.8s before dialog closes
_POLL_INTERVAL_MS = 150         # bridge.recent_gestures() poll cadence


class GestureTutorialDialog(QDialog):
    def __init__(self, *, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = bridge.cfg

        # ---- save & flip teaching_mode (auto-restore on close) ----
        self._prev_teaching_mode = bool(bridge.teaching_mode)
        bridge.set_teaching_mode(True)

        # ---- state ----
        self._step = 0                         # 0..len(GESTURES)-1
        self._step_results: list[str] = []     # "DONE" or "SKIPPED" per step
        self._last_seen_ts: float = 0.0        # for polling new recognitions
        self._step_started_at: float = time.monotonic()

        # ---- window ----
        self.setWindowTitle("手势教学")
        self.setModal(True)
        self.resize(420, 360)
        self.setStyleSheet("background:#0f172a;color:#ffffff;")

        # ---- layout ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        self._header = QLabel()
        self._header.setStyleSheet("color:rgba(255,255,255,200);font-size:12px;")
        outer.addWidget(self._header)

        # Gesture card
        self._card = QFrame()
        self._card.setObjectName("GlassCard")
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(8)
        self._card_icon = QLabel()
        self._card_icon.setStyleSheet("font-size:64px;")
        self._card_icon.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_icon)
        self._card_name = QLabel()
        self._card_name.setStyleSheet("font-size:20px;font-weight:600;")
        self._card_name.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_name)
        self._card_action = QLabel()
        self._card_action.setStyleSheet("color:rgba(255,255,255,180);font-size:12px;")
        self._card_action.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_action)
        self._card_desc = QLabel()
        self._card_desc.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        self._card_desc.setAlignment(Qt.AlignCenter)
        self._card_desc.setWordWrap(True)
        cl.addWidget(self._card_desc)
        outer.addWidget(self._card)

        # Progress bar (15s countdown for current step)
        self._progress = QProgressBar()
        self._progress.setRange(0, _STEP_TIMEOUT_MS)
        self._progress.setValue(_STEP_TIMEOUT_MS)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet("QProgressBar{background:rgba(255,255,255,40);border:none;} QProgressBar::chunk{background:#22c55e;}")
        outer.addWidget(self._progress)

        self._status = QLabel("请做出手势")
        self._status.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        self._status.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_skip = QPushButton("跳过本步")
        self._btn_skip.clicked.connect(lambda: self._finish_step("SKIPPED"))
        btn_row.addWidget(self._btn_skip)
        self._btn_end = QPushButton("结束")
        self._btn_end.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_end)
        outer.addLayout(btn_row)

        # ---- timers ----
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_recognition)
        self._poll_timer.start()

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(lambda: self._finish_step("SKIPPED"))
        self._step_timer.start(_STEP_TIMEOUT_MS)

        # ---- render step 0 ----
        self._render_step()

    # ------------------------------------------------------------ step logic

    def _current_gesture(self) -> str:
        return GESTURES[self._step]

    def _render_step(self) -> None:
        g = self._current_gesture()
        icon, name, desc = _TUTORIAL_META[g]
        action = self._cfg.get_binding(g) or "（未绑定）"
        self._header.setText(f"第 {self._step + 1} / {len(GESTURES)} 步")
        self._card_icon.setText(icon)
        self._card_name.setText(name)
        self._card_action.setText(f"→ {action}")
        self._card_desc.setText(desc)
        self._status.setText("请做出手势（15 秒内）")
        self._step_started_at = time.monotonic()
        self._progress.setValue(_STEP_TIMEOUT_MS)
        self._step_timer.start(_STEP_TIMEOUT_MS)

    def _poll_recognition(self) -> None:
        """Watch bridge.recent_gestures() for the target gesture."""
        target = self._current_gesture()
        recent = self._bridge.recent_gestures()
        new = [r for r in recent if float(r.get("ts") or 0.0) > self._last_seen_ts]
        if not new:
            # tick down the countdown bar
            elapsed_ms = (time.monotonic() - self._step_started_at) * 1000.0
            remaining = max(0, int(_STEP_TIMEOUT_MS - elapsed_ms))
            self._progress.setValue(remaining)
            return
        # Mark last_seen_ts to newest entry
        self._last_seen_ts = max(float(r.get("ts") or 0.0) for r in new)
        if any(str(r.get("gesture") or "") == target for r in new):
            self._finish_step("DONE")

    def _finish_step(self, result: str) -> None:
        """Mark the current step result and advance / close."""
        self._step_results.append(result)
        self._step += 1
        if self._step >= len(GESTURES):
            # Final step done. Compute summary and accept.
            done = sum(1 for r in self._step_results if r == "DONE")
            skipped = len(GESTURES) - done
            if skipped == 0:
                self._status.setText("全部完成！🎉")
            else:
                self._status.setText(f"已跳过 {skipped} 个，可点「重看教学」再来")
            self._poll_timer.stop()
            self._step_timer.stop()
            # Mark tutorial_done only if user reached step 7 (regardless of
            # DONE/SKIPPED mix). User closing early (reject path) bypasses
            # this and doesn't write — boundary #5 of the spec.
            try:
                self._cfg.tutorial_done = True
                self._bridge.save()
            except Exception:
                pass
            QTimer.singleShot(_FINAL_CLOSE_MS, self.accept)
            return
        self._render_step()

    # ------------------------------------------------------------ cleanup

    def closeEvent(self, ev):
        # Restore teaching_mode on any close path (X button, reject, accept).
        try:
            self._bridge.set_teaching_mode(self._prev_teaching_mode)
        except Exception:
            pass
        try:
            self._poll_timer.stop()
            self._step_timer.stop()
        except Exception:
            pass
        super().closeEvent(ev)
```

- [ ] **Step 2: 在 `pages/__init__.py` 里导出**

打开 `ppt_qt/pages/__init__.py`,在现有导出后面追加:

```python
from .gesture_tutorial_dialog import GestureTutorialDialog  # noqa: F401
```

(若 `__init__.py` 用 `__all__`,也加上 `'GestureTutorialDialog'`。)

- [ ] **Step 3: 跑 import 自检**

Run:
```bash
python -c "from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog; print('OK')"
```
Expected: 输出 `OK`,无异常

- [ ] **Step 4: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿(69/69)

- [ ] **Step 5: 提交**

```bash
git add ppt_qt/pages/gesture_tutorial_dialog.py ppt_qt/pages/__init__.py
git commit -m "feat(qt): GestureTutorialDialog 7-step walkthrough with countdown"
```

---

## Task 4: GesturePage 增加教学相关 UI

**Files:**
- Modify: `ppt_qt/pages/gesture_page.py`(顶部开关、新图卡段、试用面板高亮、「重看教学」按钮、`showEvent` 自动弹)

**Interfaces:**
- Consumes: `bridge: GestureBridge`(已有),`on_status: Optional[Callable]`
- Produces: 用户切到「手势」页时,**若 `bridge.engine is not None` 且 `cfg.tutorial_done is False`,自动弹 `GestureTutorialDialog`**

> **测试说明:** Qt 行为难自动化,本任务靠 UI 验收清单(Task 5)保证;静态行为(顶部 checkbox 切换 → bridge.set_teaching_mode)靠手测。

- [ ] **Step 1: 在顶部加「教学模式」QCheckBox**

修改 `ppt_qt/pages/gesture_page.py`,把第 56-72 行的"反查行"区域整体包进新的 top-level 容器。先在反查行顶部插入 QHBoxLayout 包含 QCheckBox,让"教学模式"在最显眼的位置。

具体:把现有:

```python
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("查找:"))
        self._query_combo = QComboBox()
        ...
```

替换为(在 `top` 之前先创建一个 toolbar 容器):

```python
        # ---- 顶部工具栏：教学模式 + 查找 ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self._teaching_check = QCheckBox("教学模式（只识别不派发）")
        self._teaching_check.setChecked(bool(self._bridge.teaching_mode))
        self._teaching_check.toggled.connect(self._on_teaching_toggled)
        toolbar.addWidget(self._teaching_check, 0, Qt.AlignVCenter)
        toolbar.addStretch(1)
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.addLayout(toolbar)
```

(注意:原代码把 `top` 直接 `outer.addLayout(top)`,现在改为 `outer.addLayout(toolbar)`,且不再在后面单独 `outer.addLayout(top)`,因为 toolbar 已经包含查找 UI。)

然后在 `_populate_combo` 上方附近(私有方法区)新增:

```python
    def _on_teaching_toggled(self, on: bool) -> None:
        self._bridge.set_teaching_mode(bool(on))
        self._status_lbl.setText(
            f"教学模式：{'开（只识别不派发）' if on else '关'}"
        )
```

- [ ] **Step 2: 加静态图卡段**

把图卡插入到现有"段 1 7 行映射"(代码中 `map_card`)之前。**注:图卡里的行也是 GESTURES 列表,需要为每行保存一个引用以便后续高亮。**

在 `outer.addWidget(map_card)` 之前插入:

```python
        # ---- 段 0 静态手势示图卡（常驻参考） ----
        cheat_card = QFrame()
        cheat_card.setObjectName("GlassCard")
        ccl = QVBoxLayout(cheat_card)
        ccl.setContentsMargins(12, 12, 12, 12)
        ccl.setSpacing(4)
        cheat_title = QLabel("① 手势示图卡")
        cheat_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        ccl.addWidget(cheat_title)
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
            ccl.addWidget(row)
            self._cheat_rows[g] = row
            self._cheat_rows[g].__dict__["_action_lbl"] = action_lbl
        # Initial binding labels
        for g, row in self._cheat_rows.items():
            action = self._cfg.get_binding(g)
            row.__dict__["_action_lbl"].setText(
                f"→ {_ACTION_LABEL.get(action, '（未绑定）')}" if action else "（未绑定）"
            )
        outer.addWidget(cheat_card)
```

然后改 `_on_binding_changed` 让图卡同步(在该函数末尾追加 1 行):

```python
    def _on_binding_changed(self, gesture: str) -> None:
        cb = self._binding_combos[gesture]
        action = cb.currentData()
        self._cfg.set_binding(gesture, action)
        self._bridge.save()
        self._refresh_query_hint()
        # Sync the cheat-card row label too.
        if gesture in self._cheat_rows:
            label = _ACTION_LABEL.get(action, "（未绑定）") if action else "（未绑定）"
            self._cheat_rows[gesture].__dict__["_action_lbl"].setText(
                f"→ {label}" if action else "（未绑定）"
            )
        self._status_lbl.setText(f"已更新 {gesture} -> {action or '禁用'}")
```

- [ ] **Step 3: 试用面板识别高亮**

改 `_poll_bridge_gestures` 的 for 循环(找到 `self._history.insert` 那行附近),在每次新识别时高亮图卡对应行。改为:

```python
        for entry in new_entries:
            ts = float(entry.get("ts") or 0.0)
            gesture = str(entry.get("gesture") or "")
            action = entry.get("action")
            if not gesture or gesture == self._current_gesture:
                continue
            self._current_gesture = gesture
            self._trial_now.setText(_GESTURE_NAME.get(gesture, gesture))
            self._history.insert(0, {"ts": ts or time.time(), "gesture": gesture, "action": action})
            self._history = self._history[:5]
            self._last_seen_ts = max(self._last_seen_ts, ts or time.time())
            # Highlight the matching row in the cheat card (green flash, 2s).
            if hasattr(self, "_cheat_rows") and gesture in self._cheat_rows:
                self._cheat_rows[gesture].setStyleSheet(
                    "background:rgba(34,197,94,0.4);border-radius:6px;"
                )
                QTimer.singleShot(
                    2000,
                    lambda g=gesture: self._cheat_rows[g].setStyleSheet("")
                )
```

- [ ] **Step 4: 加「重看教学」按钮 + 自动弹**

把现有控制按钮区(line 134 附近 `ctrl = QHBoxLayout()`)扩展,在「启动手势」**之前**加一个 QPushButton:

```python
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        b_tutorial = QPushButton("重看教学")
        b_tutorial.setObjectName("SecondaryButton")
        b_tutorial.clicked.connect(self._on_show_tutorial)
        ctrl.addWidget(b_tutorial)
        b_start = QPushButton("启动手势")
        b_start.setObjectName("PrimaryButton")
        b_start.clicked.connect(lambda: bridge.start())
        ctrl.addWidget(b_start)
        b_stop = QPushButton("停止")
        ...
        (其它按钮保持原样)
```

并在 `_on_teaching_toggled` 后面新增:

```python
    def _on_show_tutorial(self) -> None:
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()

    def _maybe_show_tutorial(self) -> None:
        """Called from showEvent: pop tutorial if first time and engine is up."""
        if self._cfg.tutorial_done:
            return
        eng = self._bridge.engine
        if eng is None:
            return  # user hasn't pressed Start yet; nothing to demo against
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()

    def showEvent(self, ev):
        super().showEvent(ev)
        # Defer to next tick so the page is fully laid out before the modal
        # appears (avoids focus/geometry glitches).
        QTimer.singleShot(50, self._maybe_show_tutorial)
```

> **注意**: `import GestureTutorialDialog` 写在函数体内,避免 `pages/__init__.py` 的循环 import 问题。

- [ ] **Step 5: 跑 import + 启动自检**

Run:
```bash
python -c "from ppt_qt.pages.gesture_page import GesturePage; print('OK')"
```
Expected: 输出 `OK`,无异常

- [ ] **Step 6: 跑全套测试确认无回归**

Run: `pytest -q`
Expected: 全绿(69/69)

- [ ] **Step 7: 提交**

```bash
git add ppt_qt/pages/gesture_page.py
git commit -m "feat(qt): gesture page tutorial card + teaching toggle + auto-pop dialog"
```

---

## Task 5: UI 验收清单走一遍

本任务**没有代码改动**——只是按 spec §4.2 的清单逐项验证。

**Files:** 无

- [ ] **Step 1: 启动 app**

Run: `python ppt_qt/app.py`
Expected: 主窗口出现,切到「手势」页(首次切)

- [ ] **Step 2: 验证自动弹**

期望:由于还没点过「启动手势」,引擎是 None,**不应弹**向导。
切到「连接」页启动后端(若无,手动进「手势」页),再点「启动手势」。再切走再切回「手势」页。
Expected: 自动弹出 `GestureTutorialDialog`

- [ ] **Step 3: 走 7 步**

做出每个手势(按向导提示),期望每识别一次就跳下一步;故意做出非目标手势 15 秒,期望自动跳过并跳到下一步。

- [ ] **Step 4: 完成 → 不再弹**

向导走完后关闭,期待 `tutorial_done=True`。再次切走切回「手势」页,**不再弹**。

- [ ] **Step 5: 「重看教学」按钮**

点「重看教学」,向导再次弹出。

- [ ] **Step 6: 教学模式开关**

打开顶部 checkbox,做出握拳。
Expected: 试用面板显示「握拳」,但 PPT **没黑屏**。

关闭 checkbox,做出握拳。
Expected: 试用面板显示「握拳」,PPT 黑屏。

- [ ] **Step 7: 修改绑定→图卡同步**

在段 3 「手势映射」段把 FIST 改成「下一页」。
Expected: 段 0 图卡里 FIST 行的动作标签立刻变成「→ 下一页」。

- [ ] **Step 8: 重启验证**

关闭 app,再启动,切到「手势」页。
Expected: 顶部 checkbox 默认 False(图卡、状态都正常),`tutorial_done` 仍是 True(不弹)。

- [ ] **Step 9: 跑全套测试最后一遍**

Run: `pytest -q`
Expected: 69/69 全绿

- [ ] **Step 10: 提交(若 Step 1-9 暴露 bug,先回到对应 Task 修复后重新提交)**

```bash
# 若全部通过,无新文件需要 commit
# 若有 bug fix:
git add <fix files>
git commit -m "fix(qt): tutorial UI smoke findings"
```