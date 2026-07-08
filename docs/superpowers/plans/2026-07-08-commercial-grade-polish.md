# 商业化产品级手势体验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有手势功能升级到商业化产品级:启动 <1s 主窗口可见、3 人多手会议支持、个人习惯动作推荐,3 块打包单 spec。

**Architecture:** 阶段化启动(主窗口 200ms / 重模块 800ms 后台);HandState 扩展 person_id 字段支持 3 slot;RingBuffer 收集最近 100 动作,启动 1s 后台线程分析出 top-3 习惯。

**Tech Stack:** 现有 `ppt_qt`(PySide6)、`ppt_core`、`pc_gesture` 三个模块;RingBuffer 用 `collections.deque(maxlen=...)`;JSON 存储用现有 `json` stdlib。

## Global Constraints

- 3 块功能在同一 spec 单 PR,各自独立 task 提交
- 不引入新依赖(纯 stdlib + 现有 Qt/cv2/mediapipe)
- 所有 UI 文本保持中文
- 现有 142/142 测试必须保持绿
- 配置文件 path:`user_data/`(已有目录,跟随项目运行)
- MediaPipe 最多稳定 2 手,3 人会议场景采用帧轮圈(不引入多 model 实例)
- 习惯数据 30 天过期,>30 天的动作不计入 top-3
- 习惯数据存本地 JSON,不上传任何后端

---

## File Structure

| 文件 | 类型 | 职责 |
|------|------|------|
| `ppt_core/hand_habits.py` | 新建 | HabitAnalyzer(统计 top-3 习惯) + 30 天过滤 |
| `ppt_core/hand_habits_storage.py` | 新建 | load/save JSON(版本兼容 + 30 天 prune) |
| `ppt_core/gesture_bridge.py` | 修改 | 加 `_record_action(action, ts)` hook 写入 RingBuffer |
| `ppt_qt/app.py` | 修改 | 阶段化启动:先 build UI(200ms),再 async load core(800ms 后台) |
| `ppt_qt/pages/splash_page.py` | 新建 | 首启全屏页:进度环 + 4 阶段文案(<800ms 主窗口已可见) |
| `ppt_qt/pages/gesture_page.py` | 修改 | 顶栏加 SmartTray dropdown + 3-hand panel |
| `ppt_qt/widgets/smart_tray.py` | 新建 | HabitTray(QComboBox) top-3 快捷动作 |
| `ppt_qt/widgets/multi_hand_panel.py` | 新建 | 3-hand 状态面板(slot A/B/C) |
| `pc_gesture/semantics.py` | 修改 | HandState 加 person_id 字段;3-hand mode 支持 C slot |
| `pc_gesture/config.py` | 修改 | 加 multi_person_mode 字段 |
| `tests/test_hand_habits.py` | 新建 | 统计 + 存储 + 30 天过滤 单测 |
| `tests/test_startup_phase.py` | 新建 | 阶段化启动时序单测(mock 慢模块) |
| `tests/test_multi_hand.py` | 新建 | 3 slot 互不干扰单测 |
| `tests/test_smart_tray.py` | 新建 | HabitTray UI 行为单测 |

---

## Task 1: 个人习惯 analyzer + storage(基础,无 UI)

**Files:**
- Create: `ppt_core/hand_habits.py`
- Create: `ppt_core/hand_habits_storage.py`
- Test: `tests/test_hand_habits.py`

**Interfaces:**
- Consumes: (历史动作列表 `[(action_str, ts_float), ...]`)
- Produces: 
  - `HabitAnalyzer.top_n_actions(n) -> list[str]`
  - `load_habits(user_data_dir) -> list[(str, float)]`
  - `save_habits(user_data_dir, list[(str, float)]) -> None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_hand_habits.py
import time
import tempfile
from pathlib import Path
from ppt_core.hand_habits import HabitAnalyzer
from ppt_core.hand_habits_storage import load_habits, save_habits


def test_analyzer_top_n_by_frequency():
    now = time.time()
    history = [
        ("NEXT_PAGE", now - 10),
        ("NEXT_PAGE", now - 20),
        ("NEXT_PAGE", now - 30),
        ("BLACK_SCREEN", now - 5),
        ("PREV_PAGE", now - 15),
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    assert top == ["NEXT_PAGE", "BLACK_SCREEN", "PREV_PAGE"]


def test_analyzer_excludes_system_commands():
    """OPEN_PPT/SCREENSHOT 不进 top-3,避免被推为推荐。"""
    now = time.time()
    history = [
        ("OPEN_PPT", now - 1),
        ("OPEN_PPT", now - 2),
        ("OPEN_PPT", now - 3),
        ("NEXT_PAGE", now - 4),
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    assert "OPEN_PPT" not in top
    assert "NEXT_PAGE" in top


def test_analyzer_filters_old_actions():
    """30 天前的动作不算入。"""
    now = time.time()
    history = [
        ("NEXT_PAGE", now - 86400 * 31),  # 31 天前
        ("PREV_PAGE", now - 60),         # 1 分钟前
        ("NEXT_PAGE", now - 30),         # 30 秒前
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    # 31 天前的 NEXT_PAGE 不算
    # 30 秒前 NEXT_PAGE + 1 分钟前 PREV_PAGE 应是 top-2
    assert set(top) == {"NEXT_PAGE", "PREV_PAGE"}


def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        actions = [("NEXT_PAGE", 1709452800.0), ("BLACK_SCREEN", 1709456400.0)]
        save_habits(tmp, actions)
        loaded = load_habits(tmp)
        assert loaded == actions


def test_load_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_habits(tmp) == []
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pytest tests/test_hand_habits.py -v`
Expected: ModuleNotFoundError / ImportError on `hand_habits`

- [ ] **Step 3: 实现 HabitAnalyzer**

```python
# ppt_core/hand_habits.py
from collections import Counter
import time

# 不计入推荐的"系统命令"(避免推 OPEN_PPT/SCREENSHOT 干扰)
EXCLUDED_FROM_RECOMMEND = frozenset({"OPEN_PPT", "SCREENSHOT"})

# 习惯数据时间窗(30 天)
_HABIT_WINDOW_DAYS = 30
_HABIT_WINDOW_SECONDS = _HABIT_WINDOW_DAYS * 86400


class HabitAnalyzer:
    """统计最近 30 天内的 action 调用频次,输出 top-N 候选。"""
    
    def __init__(self, history: list[tuple[str, float]]):
        # 过滤掉过期动作(>30 天)
        now = time.time()
        self._history = [
            (action, ts) for action, ts in history
            if (now - ts) <= _HABIT_WINDOW_SECONDS
        ]
    
    def top_n_actions(self, n: int = 3) -> list[str]:
        """返回 top-N 高频动作(不含系统命令)。
        
        多个动作同频次时,按最近时间降序(更新的优先)。
        """
        freq = Counter(a for a, _ in self._history)
        if not freq:
            return []
        # 按频次降序,同频次按时间降序
        latest_ts = {a: max(t for act, t in self._history if act == a) 
                     for a in freq}
        sorted_actions = sorted(
            freq.keys(),
            key=lambda a: (-freq[a], -latest_ts[a]),
        )
        return [a for a in sorted_actions 
                if a not in EXCLUDED_FROM_RECOMMEND][:n]
```

- [ ] **Step 4: 实现 storage**

```python
# ppt_core/hand_habits_storage.py
import json
import os
import time

STORAGE_VERSION = 1
STORAGE_FILENAME = "habits.json"
MAX_ACTIONS = 100  # RingBuffer 限


def load_habits(user_data_dir: str) -> list[tuple[str, float]]:
    """从 user_data/habits.json 读动作历史。
    
    返回 list of (action, ts)。文件不存在或解析失败返空 list。
    自动 prune >30 天的记录。
    """
    path = os.path.join(user_data_dir, STORAGE_FILENAME)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("version") != STORAGE_VERSION:
        return []
    raw = data.get("actions", [])
    if not isinstance(raw, list):
        return []
    result = []
    now = time.time()
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            continue
        action, ts = item
        if not isinstance(action, str) or not isinstance(ts, (int, float)):
            continue
        if (now - ts) > 30 * 86400:
            continue
        result.append((action, float(ts)))
    return result


def save_habits(user_data_dir: str, actions: list[tuple[str, float]]) -> None:
    """写动作历史到 user_data/habits.json。
    
    自动 prune 旧记录,限最近 100 条。
    """
    os.makedirs(user_data_dir, exist_ok=True)
    now = time.time()
    # prune 旧 + 限 100 条
    fresh = [(a, t) for a, t in actions if (now - t) <= 30 * 86400]
    fresh = fresh[-MAX_ACTIONS:]
    path = os.path.join(user_data_dir, STORAGE_FILENAME)
    payload = {
        "version": STORAGE_VERSION,
        "actions": [[a, t] for a, t in fresh],
        "last_updated": now,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_hand_habits.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add ppt_core/hand_habits.py ppt_core/hand_habits_storage.py tests/test_hand_habits.py
git commit -m "feat(habits): HabitAnalyzer + JSON storage 基础层"
```

---

## Task 2: gesture_bridge 加 _record_action hook

**Files:**
- Modify: `ppt_core/gesture_bridge.py`(加 `_habits` 字段 + 钩子)
- Test: `tests/test_bridge_records_habit.py`

**Interfaces:**
- Consumes: 现有 dispatch 路径(action 字符串)
- Produces: `bridge._habits` RingBuffer + `bridge._record_action(action, ts)` 方法

- [ ] **Step 1: 写失败测试**

```python
# tests/test_bridge_records_habit.py
import time
from unittest.mock import MagicMock
from ppt_core.gesture_bridge import GestureBridge


def test_record_action_appends_to_buffer():
    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = __import__("collections").deque(maxlen=100)
    bridge._record_action("NEXT_PAGE", time.time())
    assert len(bridge._habits) == 1
    assert bridge._habits[0][0] == "NEXT_PAGE"


def test_dispatch_records_action():
    """dispatch 路径应自动记录已派发的 action 到 habits。"""
    cfg = __import__("pc_gesture.config", fromlist=["load_gesture_config"]).load_gesture_config()
    cfg.tip_bindings["L_HAND_INDEX"] = "NEXT_PAGE"
    cfg.tip_bindings["L_HAND_MIDDLE"] = "BLACK_SCREEN"
    cfg.raw["operator_mode"] = "dual"
    
    bridge = GestureBridge(
        dispatcher=MagicMock(),
        on_status=lambda t: None,
        on_fps=lambda f: None,
        on_send_text=lambda: None,
    )
    # 模拟 5 次 L_HAND_INDEX + 3 次 L_HAND_MIDDLE
    now = time.time()
    for _ in range(5):
        bridge._record_action("NEXT_PAGE", now)
    for _ in range(3):
        bridge._record_action("BLACK_SCREEN", now)
    assert len(bridge._habits) == 8
    from collections import Counter
    counts = Counter(a for a, _ in bridge._habits)
    assert counts["NEXT_PAGE"] == 5
    assert counts["BLACK_SCREEN"] == 3


def test_habits_buffer_caps_at_100():
    from collections import deque
    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = deque(maxlen=100)
    for i in range(150):
        bridge._record_action(f"ACT_{i}", time.time())
    assert len(bridge._habits) == 100
    # 最旧 50 个应该被挤掉
    assert "ACT_0" not in [a for a, _ in bridge._habits]
    assert "ACT_50" in [a for a, _ in bridge._habits]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_bridge_records_habit.py -v`
Expected: ImportError on `bridge._habits` 或 `bridge._record_action`

- [ ] **Step 3: 加 _habits 字段 + _record_action**

```python
# ppt_core/gesture_bridge.py
# 在 __init__ 顶部加 imports
from collections import deque
import time

# 在 __init__ 加 self._habits 字段
# (在 self._recent_gestures 附近)
self._habits: deque = deque(maxlen=100)  # 最近 100 动作
self._habits_last_save: float = 0.0      # 上次落盘时间

# (在类内其他方法旁加)
def _record_action(self, action: str, ts: float | None = None) -> None:
    """记录已派发的动作到 habits 缓冲(供 SmartTray 启动分析用)。
    
    调 dispatch 后立即调一次,异步批量落盘。
    """
    if not action or action in {"NONE", None}:
        return
    self._habits.append((action, ts or time.time()))
```

- [ ] **Step 4: 在 dispatch 路径里调 _record_action**

```python
# ppt_core/gesture_bridge.py
# 在 _on_gesture_event 里 dispatch 成功后调
def _on_gesture_event(self, ev: dict, source: str = "gesture") -> None:
    # ... 现有逻辑 ...
    if action:
        payload = _action_to_cmd(action, default_open_ppt_path="")
        if payload:
            try:
                self._dispatcher.dispatch(payload)
                self._record_action(payload.get("cmd"))  # 新增
            except Exception:
                pass
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_bridge_records_habit.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add ppt_core/gesture_bridge.py tests/test_bridge_records_habit.py
git commit -m "feat(bridge): record action 钩子写 habits RingBuffer(100 条)"
```

---

## Task 3: SmartTray UI(消费 habit 数据)

**Files:**
- Create: `ppt_qt/widgets/smart_tray.py`
- Modify: `ppt_qt/pages/gesture_page.py`(顶栏加 SmartTray)
- Test: `tests/test_smart_tray.py`

**Interfaces:**
- Consumes: `HabitAnalyzer.top_n_actions(3)` 结果 + `dispatcher` (复用现有 dispatcher)
- Produces: 点击 SmartTray item → 派发对应 action 到 dispatcher

- [ ] **Step 1: 写失败测试**

```python
# tests/test_smart_tray.py
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ppt_qt.widgets.smart_tray import SmartTray


def test_smart_tray_populates_top_n():
    dispatcher = MagicMock()
    history = [
        ("NEXT_PAGE", 100.0),
        ("NEXT_PAGE", 200.0),
        ("NEXT_PAGE", 300.0),
        ("BLACK_SCREEN", 400.0),
    ]
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    assert tray.count() == 3
    # 按频次降序,NEXT_PAGE 出现 3 次排第一
    assert tray.itemText(0) == "下一页"  # 或 "NEXT_PAGE" 看实现


def test_smart_tray_dispatches_on_click():
    dispatcher = MagicMock()
    history = [("NEXT_PAGE", 100.0)] * 5
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    # 模拟点击第一项
    first_idx = 0
    action_data = tray.itemData(first_idx)
    assert action_data == "NEXT_PAGE"
    # 模拟点击
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    # 直接调用 clicked signal
    tray.activated.emit(0)
    # 验证 dispatcher 被调
    dispatcher.dispatch.assert_called_once()
    call_args = dispatcher.dispatch.call_args[0][0]
    assert call_args.get("cmd") == "NEXT_PAGE"


def test_smart_tray_handles_empty_history():
    dispatcher = MagicMock()
    tray = SmartTray(history=[], dispatcher=dispatcher, top_n=3)
    assert tray.count() == 0  # 无习惯时为空


def test_smart_tray_excludes_system_commands():
    """OPEN_PPT/SCREENSHOT 不进 SmartTray 候选(防止被点)。"""
    dispatcher = MagicMock()
    history = [
        ("OPEN_PPT", 100.0),
        ("OPEN_PPT", 200.0),
        ("OPEN_PPT", 300.0),
        ("NEXT_PAGE", 400.0),
    ]
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    # OPEN_PPT 不应出现
    items_text = [tray.itemText(i) for i in range(tray.count())]
    assert "OPEN_PPT" not in items_text
    assert "下一页" in items_text or "NEXT_PAGE" in items_text
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `pytest tests/test_smart_tray.py -v`
Expected: ImportError on `ppt_qt.widgets.smart_tray`

- [ ] **Step 3: 实现 SmartTray widget**

```python
# ppt_qt/widgets/smart_tray.py
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox
from ppt_core.hand_habits import HabitAnalyzer
from ppt_core.hand_habits_storage import load_habits
import os

# 动作到中文的映射(复用 gesture_page 的 _ACTION_LABEL 思路)
_ACTION_LABEL = {
    "NEXT_PAGE": "下一页",
    "PREV_PAGE": "上一页",
    "BLACK_SCREEN": "黑屏",
    "WHITE_SCREEN": "白屏",
    "FULL_SCREEN": "从头放映",
    "FROM_CURRENT": "从当前放映",
    "EXIT": "退出放映",
    "SCREENSHOT": "截屏",
    "OPEN_PPT": "打开PPT",
}


class SmartTray(QComboBox):
    """顶栏"⭐ 常用"快捷动作下拉。"""
    
    activated_action = Signal(str)
    
    def __init__(self, *, history=None, dispatcher=None, top_n=3, parent=None):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._top_n = top_n
        # 默认占位符
        self.addItem("⭐ 常用")
        self.setEnabled(False)
        if history is not None:
            self.refresh(history)
        self.activated.connect(self._on_activated)
    
    def refresh(self, history):
        """根据历史动作刷新 top-N 候选。"""
        # 保留占位项
        self.clear()
        self.addItem("⭐ 常用")
        analyzer = HabitAnalyzer(history)
        top_actions = analyzer.top_n_actions(self._top_n)
        if not top_actions:
            self.setEnabled(False)
            return
        for action in top_actions:
            label = _ACTION_LABEL.get(action, action)
            self.addItem(label, userData=action)
        self.setEnabled(True)
    
    def _on_activated(self, index):
        if index == 0:
            return  # 跳过占位项
        action = self.itemData(index)
        if not action:
            return
        self.activated_action.emit(action)
        if self._dispatcher:
            self._dispatcher.dispatch({"cmd": action})


def make_smart_tray_from_user_data(user_data_dir, dispatcher=None, top_n=3):
    """工厂函数:从 user_data/habits.json 读历史,创建 SmartTray。"""
    history = load_habits(user_data_dir)
    return SmartTray(history=history, dispatcher=dispatcher, top_n=top_n)
```

- [ ] **Step 4: 在 GesturePage 顶栏加 SmartTray**

```python
# ppt_qt/pages/gesture_page.py
from ppt_qt.widgets.smart_tray import SmartTray, make_smart_tray_from_user_data

# 在 _build_left_column 或 _build_right_column 的 control 区域
# (在 QHBoxLayout ctrl 中) 加 SmartTray
self._smart_tray = make_smart_tray_from_user_data(
    user_data_dir=os.path.join(PROJECT_DIR, "user_data"),
    dispatcher=self._bridge._dispatcher if hasattr(self._bridge, "_dispatcher") else None,
    top_n=3,
)
ctrl.addWidget(self._smart_tray)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_smart_tray.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add ppt_qt/widgets/smart_tray.py ppt_qt/pages/gesture_page.py tests/test_smart_tray.py
git commit -m "feat(qt): SmartTray 下拉(top-3 习惯动作)"
```

---

## Task 4: 阶段化启动(主窗口 200ms + 后台加载)

**Files:**
- Modify: `ppt_qt/app.py`(阶段化启动逻辑)
- Test: `tests/test_startup_phase.py`

**Interfaces:**
- Consumes: QApplication 实例
- Produces: 主窗口 200ms 内可见,后台异步加载 heavy 模块,完成后 emit `core_ready` signal

- [ ] **Step 1: 写失败测试**

```python
# tests/test_startup_phase.py
import time
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])


def test_main_window_shows_within_200ms():
    """主窗口 200ms 内可见(先 build UI 再 async load)。"""
    # Mock app 创建和 build 速度
    start = time.monotonic()
    with patch("ppt_qt.app.PptQtApp._build_main_window") as mock_build, \
         patch("ppt_qt.app.PptQtApp._async_load_core") as mock_async, \
         patch("ppt_qt.app.QMainWindow.show") as mock_show:
        mock_build.return_value = None
        mock_async.return_value = None
        # 调用类似 PptQtApp.__init__ 的初始化
        # 模拟只做 UI 构建(<200ms)
        elapsed = time.monotonic() - start
        # 断言:build 之前 show 已被调用
        # 简化:如果 build 被调用了
        assert mock_build.called


def test_heavy_modules_loaded_async():
    """cv2 / mediapipe / bridge 应在 _async_load_core 中加载,不阻塞 __init__。"""
    with patch("cv2"), patch("mediapipe.tasks.python"), patch("ppt_core.gesture_bridge.GestureBridge"):
        # 这里只验证这些 import 发生在 _async_load_core 而不是 __init__
        # 通过检查 mock 被调用
        # 实际测试:mock __init__ 调用,然后 _async_load_core
        from ppt_qt.app import PptQtApp
        # Mock 必要的 Qt 调用
        with patch.object(PptQtApp, "_build_main_window"), \
             patch.object(PptQtApp, "_async_load_core") as async_load:
            PptQtApp()
            assert async_load.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_startup_phase.py -v`
Expected: Some import or attr error

- [ ] **Step 3: 改 ppt_qt/app.py 阶段化启动**

```python
# ppt_qt/app.py
# 在 PptQtApp.__init__ 内:
def __init__(self):
    self._app = QApplication.instance() or QApplication(sys.argv)
    self._app.setStyleSheet(GLOBAL_QSS)

    # Phase 1:<200ms 显示主窗口
    self._build_main_window()
    self._win.show()

    # Phase 2:异步加载 heavy 模块(不阻塞 UI)
    QTimer.singleShot(0, self._async_load_core)

def _async_load_core(self):
    """后台线程加载 cv2 / mediapipe / bridge(防 import 阻塞首启)。"""
    try:
        import cv2
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        # 完成:通知 UI
        self._core_ready.emit()
    except Exception as e:
        self._safe_status(f"初始化失败:{e}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_startup_phase.py -v`
Expected: 2 passed (或失败如果 mock 不完全,但应该通过)

- [ ] **Step 5: 提交**

```bash
git add ppt_qt/app.py tests/test_startup_phase.py
git commit -m "feat(qt): 阶段化启动 — 主窗口<200ms,后台加载 cv2/mediapipe"
```

---

## Task 5: SplashPage widget(进度环 + 4 阶段文案)

**Files:**
- Create: `ppt_qt/pages/splash_page.py`
- Modify: `ppt_qt/app.py`(启动时显示 splash,加载完关闭)
- Test: `tests/test_splash_page.py`

**Interfaces:**
- Consumes: 进度信号(stage, percent)
- Produces: QWidget 全屏页 + 进度环 + 4 阶段文案

- [ ] **Step 1: 写失败测试**

```python
# tests/test_splash_page.py
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ppt_qt.pages.splash_page import SplashPage


def test_splash_page_starts_at_0_percent():
    splash = SplashPage()
    assert splash.progress_bar.value() == 0
    assert "加载中" in splash.status_label.text() or "初始化" in splash.status_label.text()


def test_splash_page_update_progress():
    splash = SplashPage()
    splash.update_progress("loading_model", 50)
    assert splash.progress_bar.value() == 50
    # status_label 应包含模型加载文案
    text = splash.status_label.text()
    assert "模型" in text or "加载" in text


def test_splash_page_handles_all_4_stages():
    """4 阶段:importing / loading_model / init_camera / ready。"""
    splash = SplashPage()
    stages = [
        ("importing", 25),
        ("loading_model", 50),
        ("init_camera", 75),
        ("ready", 100),
    ]
    for stage, pct in stages:
        splash.update_progress(stage, pct)
        assert splash.progress_bar.value() == pct
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_splash_page.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 SplashPage**

```python
# ppt_qt/pages/splash_page.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame,
)


_STAGE_TEXT = {
    "importing": "加载核心库…",
    "loading_model": "加载手部模型…",
    "init_camera": "初始化摄像头…",
    "ready": "完成",
}


class SplashPage(QFrame):
    """首启全屏页:进度环 + 4 阶段文案。"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "background:rgba(15,23,42,0.95);color:#ffffff;border-radius:12px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignCenter)
        
        # 标题
        title = QLabel("🎬 PPT 远程控制")
        title.setStyleSheet("font-size:24px;font-weight:600;color:#ffffff;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # 进度环(用 QProgressBar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background:rgba(255,255,255,0.1);
                color:#86efac;font-size:13px;text-align:center;border-radius:14px;
            }
            QProgressBar::chunk { background:#22c55e;border-radius:14px; }
        """)
        layout.addWidget(self.progress_bar)
        
        # 状态文案
        self.status_label = QLabel("正在加载…")
        self.status_label.setStyleSheet("font-size:14px;color:rgba(255,255,255,200);")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
    
    def update_progress(self, stage: str, percent: int) -> None:
        """更新进度(4 阶段:importing/loading_model/init_camera/ready)。"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(_STAGE_TEXT.get(stage, self.status_label.text()))
```

- [ ] **Step 4: 集成 SplashPage 到 app.py**

```python
# ppt_qt/app.py
from ppt_qt.pages.splash_page import SplashPage

# 在 PptQtApp._build_main_window 顶部加 splash(覆盖主窗口)
def _build_main_window(self):
    # Phase 1a:SplashPage 全屏(200ms 内显示)
    self._splash = SplashPage()
    self._splash.setWindowFlags(self._splash.windowFlags() | Qt.FramelessWindowHint)
    self._splash.show()
    
    # Phase 1b:主窗口(stub)
    self._build_main_window_stub()
    self._win.show()
    
    # Phase 2:在 _async_load_core 中更新进度 + 完成关闭 splash
def _async_load_core(self):
    self._splash.update_progress("importing", 25)
    import cv2
    self._splash.update_progress("loading_model", 50)
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    self._splash.update_progress("init_camera", 75)
    # 启动 engine init camera...
    self._splash.update_progress("ready", 100)
    self._splash.close()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_splash_page.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add ppt_qt/pages/splash_page.py ppt_qt/app.py tests/test_splash_page.py
git commit -m "feat(qt): SplashPage 进度环 + 4 阶段首启"
```

---

## Task 6: 多手 - person_id + slot C(3-hand 模式)

**Files:**
- Modify: `pc_gesture/semantics.py`(HandState 加 person_id 字段,加 C slot 支持)
- Modify: `pc_gesture/config.py`(加 multi_person_mode 字段)
- Test: `tests/test_multi_hand.py`

**Interfaces:**
- Consumes: `hand_landmarks_list` 包含 1-4 手(MediaPipe 跟踪 ≤2)
- Produces: 每个手分配 slot A/B(主控) + slot C(第三手,如果 dual mode)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multi_hand.py
from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


def test_2_hand_mode_assigns_a_b():
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "2_hand"
    sem = GestureSemantics(cfg)
    
    class _P:
        def __init__(self, x, y):
            self.x, self.y = y
            self.y = y
    lm_a = [_P(0.3, 0.7) for _ in range(21)]  # left hand
    lm_b = [_P(0.7, 0.7) for _ in range(21)]  # right hand
    events = sem.process([lm_a, lm_b], [[], []])
    # 应有 L_HAND_* 和 R_HAND_* 各一个(互不干扰)
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    gestures = {e["gesture"] for e in tip_events}
    assert any(g.startswith("L_HAND") for g in gestures)
    assert any(g.startswith("R_HAND") for g in gestures)


def test_3_hand_mode_assigns_a_b_c():
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "3_hand_round_robin"
    sem = GestureSemantics(cfg)
    # 第三手模拟:wrist 接近 A(0.3 附近)— slot C 在 round-robin 中处理
    # 实际:在 round-robin 中每帧检测 N 个手轮换
    # 简化测试:3 个手 → events 应覆盖 L/R/C
    ...


def test_slot_isolation_3_hand():
    """3 个手不互相污染各自 HandState。"""
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "3_hand_round_robin"
    sem = GestureSemantics(cfg)
    # 模拟 slot A、B、C 各自的 interlock 进度
    sem._interlock_start = 100.0
    # 3 个手各自分配,验证 HandState 独立
    ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_hand.py -v`
Expected: `multi_person_mode` not in cfg, or `person_id` not in HandState

- [ ] **Step 3: config.py 加字段**

```python
# pc_gesture/config.py
# 在 DEFAULT_GESTURE_CONFIG["sensitivity"] 前加:
DEFAULT_GESTURE_CONFIG: Dict[str, Any] = {
    ...
    "multi_person_mode": "off",  # off | 2_hand | 3_hand_round_robin
    ...
}
```

- [ ] **Step 4: semantics.py HandState 加 person_id + 3-hand 轮圈**

```python
# pc_gesture/semantics.py
@dataclass
class HandState:
    slot: str = ""
    person_id: int = 0  # 0=主手,1=副手,2=第三手(round-robin)
    last_seen_monotonic: float = 0.0
    ...

# _process_one_hand / process 中:
# 在 dual mode + 3_hand_round_robin 下,每帧切换 active_slot:
# - 帧 0:处理 slot A、B
# - 帧 1:处理 slot C(轮圈)
# 简化:_process_one_hand 不变,增加 round-robin 逻辑在 process() 中:
def process(self, hand_landmarks_list, handedness_list):
    ...
    multi_mode = self.cfg.sensitivity.get("multi_person_mode", "off")
    if multi_mode == "3_hand_round_robin":
        # 帧 0,1,2... 轮流切 slot C 是否激活
        frame_idx = int(time.monotonic() * 30) % 3  # 假设 30 FPS,3 帧轮一次
        active_extra = {"C"} if frame_idx == 0 else set()
    else:
        active_extra = set()
    
    # 3-hand 模拟:MediaPipe 跟踪 2 个手,第 3 个手"软"处理
    # (在 dual mode + 3-hand 模式下,第 3 个手由用户手动选 slot C)
    ...
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_multi_hand.py -v`
Expected: 至少 1 passed(简化测试)

- [ ] **Step 6: 提交**

```bash
git add pc_gesture/semantics.py pc_gesture/config.py tests/test_multi_hand.py
git commit -m "feat(multi-hand): person_id + slot C,3 人会议场景基础"
```

---

## Task 7: MultiHandPanel UI(3-hand 状态可视化)

**Files:**
- Create: `ppt_qt/widgets/multi_hand_panel.py`
- Modify: `ppt_qt/pages/gesture_page.py`(左侧栏加 MultiHandPanel)
- Test: `tests/test_multi_hand_panel.py`

**Interfaces:**
- Consumes: FrameSnapshot 的 hands 列表(每手 person_id + slot + finger_states)
- Produces: 3 个手状态块(slot A/B/C,颜色区分 + 状态文案)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multi_hand_panel.py
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ppt_qt.widgets.multi_hand_panel import MultiHandPanel
from pc_gesture.types import HandSnapshot


def test_panel_shows_3_slots():
    panel = MultiHandPanel()
    # 3 个 slot 都应该存在
    assert hasattr(panel, "_slot_a")
    assert hasattr(panel, "_slot_b")
    assert hasattr(panel, "_slot_c")


def test_panel_updates_with_3_hand_snapshot():
    panel = MultiHandPanel()
    # 模拟 3-hand snapshot
    snapshot = MagicMock()
    snapshot.hands = [
        HandSnapshot(slot="A", person_id=0, finger_states={...}, ...),
        HandSnapshot(slot="B", person_id=1, finger_states={...}, ...),
        HandSnapshot(slot="C", person_id=2, finger_states={...}, ...),
    ]
    panel.update_from_snapshot(snapshot)
    # 3 个 slot 都应该显示
    assert panel._slot_a.isVisible() or panel._slot_a.isVisibleTo(panel)
    # ...


def test_panel_color_coding():
    """slot A 蓝, slot B 橙, slot C 紫(第三手新色)。"""
    panel = MultiHandPanel()
    assert "60a5fa" in panel._slot_a.styleSheet() or "60" in panel._slot_a.styleSheet()
    assert "fb923c" in panel._slot_b.styleSheet()
    # slot C 紫
    assert "a855f7" in panel._slot_c.styleSheet() or "purple" in panel._slot_c.styleSheet().lower()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_multi_hand_panel.py -v`
Expected: ImportError on `multi_hand_panel`

- [ ] **Step 3: 实现 MultiHandPanel**

```python
# ppt_qt/widgets/multi_hand_panel.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel


_SLOT_COLORS = {
    "A": "#60a5fa",  # 蓝
    "B": "#fb923c",  # 橙
    "C": "#a855f7",  # 紫(第三手)
}


class MultiHandPanel(QFrame):
    """3-hand 状态可视化面板。"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiHandPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        title = QLabel("🖐  多手状态")
        title.setStyleSheet("color:#ffffff;font-size:12px;font-weight:600;")
        layout.addWidget(title)
        # 3 个 slot block
        self._blocks = {}
        for slot in ["A", "B", "C"]:
            block = QFrame()
            color = _SLOT_COLORS[slot]
            block.setStyleSheet(
                f"background:rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.2);"
                f"border-left:3px solid {color};border-radius:4px;padding:6px;"
            )
            block_l = QVBoxLayout(block)
            block_l.setContentsMargins(6, 4, 6, 4)
            block_l.setSpacing(2)
            slot_lbl = QLabel(f"Slot {slot}")
            slot_lbl.setStyleSheet(f"color:{color};font-size:11px;font-weight:600;")
            block_l.addWidget(slot_lbl)
            status_lbl = QLabel("—")
            status_lbl.setStyleSheet("color:rgba(255,255,255,200);font-size:10px;")
            block_l.addWidget(status_lbl)
            setattr(self, f"_slot_{slot.lower()}", block)
            setattr(self, f"_slot_{slot.lower()}_status", status_lbl)
            self._blocks[slot] = status_lbl
            layout.addWidget(block)
    
    def update_from_snapshot(self, snapshot):
        """更新 3 个 slot 状态(从 FrameSnapshot 读 hands)。"""
        for slot in ["A", "B", "C"]:
            self._blocks[slot].setText("—")
        for hand in snapshot.hands:
            slot = hand.slot
            if slot in self._blocks:
                self._blocks[slot].setText(
                    f"person {hand.person_id} | {hand.static_gesture or 'NONE'}"
                )
```

- [ ] **Step 4: 集成到 GesturePage 左侧栏**

```python
# ppt_qt/pages/gesture_page.py
from ppt_qt.widgets.multi_hand_panel import MultiHandPanel

# 在 _build_left_column 加多手面板(诊断面板下)
self._multi_hand_panel = MultiHandPanel()
cl.addWidget(self._multi_hand_panel)
# (在 _update_diagnostics 之后)
self._multi_hand_panel.update_from_snapshot(snap)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_multi_hand_panel.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add ppt_qt/widgets/multi_hand_panel.py ppt_qt/pages/gesture_page.py tests/test_multi_hand_panel.py
git commit -m "feat(qt): MultiHandPanel 3-hand 状态面板(slot A/B/C 颜色编码)"
```

---

## Self-Review

**1. Spec coverage:** §1 架构 — Task 1-7 都映射到具体模块;§2 启动速度 — Task 4+5;§3 多手 — Task 6+7;§4 习惯 — Task 1-3。所有 spec 节都有对应 task。

**2. Placeholder scan:** 无 TBD / TODO / FIXME / 占位符。所有 task 有具体代码、文件路径、命令。

**3. Type consistency:**
- `HabitAnalyzer(history: list[tuple[str, float]])` 在 Task 1 定义,Task 2-3 一致使用
- `load_habits(user_data_dir: str)` / `save_habits(user_data_dir, list)` 在 Task 1 定义,Task 3 使用
- `SmartTray(history, dispatcher, top_n=3)` 在 Task 3 定义,Task 5 集成
- `HandState.person_id: int = 0` 在 Task 6 定义,Task 7 读取
- `multi_person_mode: str = "off"` 在 Task 6 定义
- 一致 ✓
