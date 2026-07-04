# PPT 遥控 PC 端 · PySide6 重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `ppt_pc_client.py`（2803 行 Tkinter 单文件）一刀切重写为 PySide6 + Glassmorphism 风格，旧文件保留作回退。

**Architecture:** 严格分层 —— `ppt_core/` 纯业务逻辑（零 Qt 依赖，可单测），`ppt_qt/` 仅 UI 与 Qt 集成，`pc_gesture/` 维持现状不变。Qt 主线程 + asyncio 事件循环线程 + 手势引擎线程 + PPT 备注线程 4 路并行，通过 `Signal/Slot` 与 `asyncio.run_coroutine_threadsafe` 通信。

**Tech Stack:** Python 3.12 · PySide6 (Qt 6) · pynput · pyautogui · pyperclip · pywin32 · websockets · requests · pillow · qrcode · pytest

---

## Global Constraints

- **保留** `ppt_pc_client.py` 旧文件不动；`python ppt_pc_client.py` 仍可启动旧 Tk 客户端。
- **入口**：新文件 `ppt_qt.py`（5 行），`python ppt_qt.py` 启动新客户端。
- **不动** `pc_gesture/` 子包（4 文件 1041 行已完工）。
- **配色**：日落渐变 `#ff6e7f → #ffd3d3 → #bfe9ff`；玻璃面 `rgba(20,20,30,0.55)` + `blur(20px)`。
- **侧栏 4 项**：⌂连接 / ⚙行为 / ↥传输 / ✋手势。
- **页面 4 个**：对应 4 个侧栏项。
- **Win32**：聚光灯改 `QPainter`；计时器改 `QWidget`；PPT 备注仍用 `win32com`。
- **依赖缺失**：启动时 `import` 检测，缺 PySide6 / mediapipe / opencv-python 时弹窗给 `pip install` 链接。
- **WS 重连**：指数退避 1/2/4/8/16 秒，封顶 30 秒。
- **commit 风格**：每任务一次 commit；message 用 `feat:` / `test:` / `chore:` 前缀。
- **Git**：当前不是 git 仓库，Task 1 包含 `git init`。

---

## 文件结构（最终态）

```
PyCharmMiscProject/
├── ppt_pc_client.py            # 旧，不动
├── ppt_qt.py                   # 新入口
├── pc_gesture/                 # 不动
├── ppt_qt/
│   ├── __init__.py
│   ├── app.py                  # PptQtApp
│   ├── theme.py                # 调色板/渐变/QSS
│   ├── widgets/{__init__,glass_card,primary_button,sidebar,status_pill}.py
│   ├── pages/{__init__,connect_page,behavior_page,transfers_page,gesture_page}.py
│   └── overlays/{__init__,spotlight,timer_overlay}.py
├── ppt_core/
│   ├── __init__.py
│   ├── settings.py             # 配置读写
│   ├── room.py                 # 房间号生成/读写
│   ├── ws_messages.py          # 消息类型 + parse/serialize
│   ├── command_dispatcher.py   # cmd 路由（线程安全）
│   ├── mouse_controller.py     # 鼠标绝对/增量移动（pynput）
│   ├── ppt_executor.py         # pyautogui 封装
│   ├── ppt_notes.py            # PPT 备注 COM 读取
│   ├── downloads.py            # HTTP 流式下载
│   ├── ws_client.py            # asyncio + websockets（QThread 持有 loop）
│   └── gesture_bridge.py       # 包装 pc_gesture 接入 dispatcher
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_room.py
│   ├── test_ws_messages.py
│   ├── test_command_dispatcher.py
│   └── test_gesture_bridge.py
├── pytest.ini
├── docs/superpowers/specs/2026-07-04-qt-redesign-design.md
└── docs/superpowers/plans/2026-07-04-qt-redesign.md
```

---


## Task 1: 初始化仓库、依赖、测试骨架

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

**Interfaces:** none

- [ ] **Step 1: 安装 PySide6 到 .venv**

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
.venv/Scripts/python.exe -m pip install PySide6 --quiet 2>&1 | tail -5
.venv/Scripts/python.exe -c "import PySide6; print(PySide6.__version__)"
```

Expected: `6.x.y` 打印出来。

- [ ] **Step 2: 初始化 git 仓库**

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
git init
git add ppt_pc_client.py pc_gesture/ ppt_files/ 2>&1 | head -5
git -c user.email=plan@local -c user.name=plan commit -m "chore: baseline before Qt rewrite"
```

Expected: 仓库初始化成功，commit 完成。

- [ ] **Step 3: 写 .gitignore**

创建文件 `C:/Users/admin_gmail/PyCharmMiscProject/.gitignore`：

```
.venv/
__pycache__/
*.pyc
.superpowers/
ppt_pc_client_gesture.json
ppt_pc_client_settings.json
ppt_pc_client_downloads.json
pc_gesture_models/
.idea/
```

- [ ] **Step 4: 写 pytest.ini**

创建文件 `C:/Users/admin_gmail/PyCharmMiscProject/pytest.ini`：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 5: 写 tests 包与 conftest**

创建文件 `C:/Users/admin_gmail/PyCharmMiscProject/tests/__init__.py`：空文件。

创建文件 `C:/Users/admin_gmail/PyCharmMiscProject/tests/conftest.py`：

```python
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

- [ ] **Step 6: 验证 pytest 能跑空套件**

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
.venv/Scripts/python.exe -m pytest --collect-only 2>&1 | tail -5
```

Expected: `no tests ran` 或 `0 items collected`，无 import 错误。

- [ ] **Step 7: 提交**

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
git add pytest.ini tests/ .gitignore
git -c user.email=plan@local -c user.name=plan commit -m "chore: bootstrap pytest scaffolding"
```

---

## Task 2: ppt_core/settings.py 与 room.py

**Files:**
- Create: `ppt_core/__init__.py` (空)
- Create: `ppt_core/settings.py`
- Create: `ppt_core/room.py`
- Create: `tests/test_settings.py`
- Create: `tests/test_room.py`

**Interfaces:**
- `ppt_core.settings.DEFAULT_SETTINGS: dict`
- `ppt_core.settings.load_settings(path=None) -> dict`
- `ppt_core.settings.save_settings(data, path=None) -> None`
- `ppt_core.room.load_or_create_room_id(path=None) -> str`
- `ppt_core.room.save_room_id(rid, path=None) -> None`

**Default settings:**

```python
DEFAULT_SETTINGS = {
    "screenshot_open_folder": True,
    "transfer_open_folder": True,
    "transfer_open_ppt": True,
    "ppt_notes_enabled": False,
    "open_ppt_path": "",
}
```

- [ ] **Step 1: 写 settings 测试** — 写入 `tests/test_settings.py`，5 个测试：
  - `test_load_missing_returns_defaults`：文件不存在 → 返回 DEFAULT_SETTINGS
  - `test_save_then_load_roundtrip`：写入后读出等于原 dict
  - `test_load_partial_merges_defaults`：用户文件只有部分键时，未提供的键回落到默认
  - `test_load_corrupt_returns_defaults`：JSON 损坏 → 返回默认
  - `test_save_creates_dirs`：save 时自动 mkdir -p

- [ ] **Step 2: 跑测试失败** — `pytest tests/test_settings.py` 期望 `ModuleNotFoundError: No module named 'ppt_core.settings'`

- [ ] **Step 3: 写 settings 实现** — 写入 `ppt_core/settings.py`：定义 `DEFAULT_SETTINGS` 常量；`load_settings(path)` 用 `_merge_defaults` 把读到的 dict 与默认合并；`save_settings(data, path)` 用 `tempfile.mkstemp` + `os.replace` 原子写。

- [ ] **Step 4: 跑测试通过** — 期望 `5 passed`

- [ ] **Step 5: 写 room 测试** — 写入 `tests/test_room.py`，3 个测试：
  - `test_first_call_creates_and_persists`：首次调用返回 6 位大写字母+数字，且文件已写入
  - `test_subsequent_call_returns_same_id`：再次调用返回相同 id
  - `test_save_room_id_overwrites`：save 后 load 返回新值

- [ ] **Step 6: 写 room 实现** — 写入 `ppt_core/room.py`：内部 `_generate()` 用 `random.choices(string.ascii_uppercase + string.digits, k=6)`；`load_or_create_room_id(path)` 读 JSON 校验 6 位大写字母+数字，缺失或格式不对时重新生成；`save_room_id(rid, path)` 写入。

- [ ] **Step 7: 跑全部测试通过** — `pytest tests/test_room.py tests/test_settings.py` 期望 `8 passed`

- [ ] **Step 8: 提交** — `git add ppt_core/ tests/ && git commit -m "feat(ppt_core): settings and room modules"`

---

## Task 3: ppt_core/ws_messages.py

**Files:**
- Create: `ppt_core/ws_messages.py`
- Create: `tests/test_ws_messages.py`

**Interfaces:**
- `parse(raw: str) -> dict | None`
- `serialize(d: dict) -> str`
- `is_laser_delta(d: dict) -> bool`
- `is_mouse_click(d: dict) -> bool`

- [ ] **Step 1: 写测试** — 写入 `tests/test_ws_messages.py`，9 个测试覆盖：parse 有效/无效 JSON/缺 cmd/非 dict；serialize 往返；is_laser_delta 增量与绝对；is_mouse_click 正反。

- [ ] **Step 2: 跑测试失败** — 期望 `ModuleNotFoundError`

- [ ] **Step 3: 写实现** — 写入 `ppt_core/ws_messages.py`：parse 用 `json.loads` + `isinstance(d, dict)` + 校验 `cmd` 是非空 str；`is_laser_delta` 判 `cmd=="LASER" and dx is not None and dy is not None`。

- [ ] **Step 4: 跑测试通过** — 期望 `9 passed`

- [ ] **Step 5: 提交** — `git add ppt_core/ws_messages.py tests/test_ws_messages.py && git commit -m "feat(ppt_core): ws_messages module"`

---

## Task 4: ppt_core/command_dispatcher.py

**Files:**
- Create: `ppt_core/command_dispatcher.py`
- Create: `tests/test_command_dispatcher.py`

**Interfaces:**
- `class CommandDispatcher`:
  - `__init__(self, mouse, ppt_executor, *, status_cb=None, on_download=None, on_spotlight=None, on_timer_overlay=None, on_minimize=None, on_restore=None, on_client_settings=None)`
  - `dispatch(d: dict) -> None`
  - `dispatch_many(raw_messages: list[str]) -> int`

**Routing table (cmd → action):**
- LASER (dx/dy) → `mouse.apply_delta(dx, dy)`
- LASER (x/y) → `mouse.set_absolute(x, y)`
- MOUSE_CLICK → `mouse.click(count)`
- NEXT_PAGE / PREV_PAGE / FULL_SCREEN / FROM_CURRENT / BLACK_SCREEN / WHITE_SCREEN / EXIT / SEND_TEXT / SELECT_ALL / COPY / PASTE / DELETE / SCREENSHOT / OPEN_PPT → `ppt_executor.execute(d)`
- FILE_ARRIVED → `on_download(url)`
- CLIENT_SETTINGS → `on_client_settings(d)`
- PC_WINDOW_MINIMIZE → `on_minimize()`
- PC_WINDOW_RESTORE → `on_restore()`
- SPOTLIGHT_SHOW / SPOTLIGHT_UPDATE → `on_spotlight(d)`
- SPOTLIGHT_HIDE → `on_spotlight(None)`
- TIMER_OVERLAY_* → `on_timer_overlay(cmd, d)`

- [ ] **Step 1: 写测试** — 写入 `tests/test_command_dispatcher.py`，12 个测试覆盖：LASER 增量/绝对、MOUSE_CLICK 默认 count=1 / count=2、NEXT_PAGE 路由到 ppt、FILE_ARRIVED 调 on_download、SPOTLIGHT_SHOW 调 on_spotlight(d)、SPOTLIGHT_HIDE 调 on_spotlight(None)、TIMER_OVERLAY_SHOW 调 on_timer_overlay、MINIMIZE 回调、未知 cmd 忽略、dispatch_many 处理 raw 列表、4 线程并发 dispatch 不抛。

- [ ] **Step 2: 跑测试失败** — 期望 `ModuleNotFoundError`

- [ ] **Step 3: 写实现** — 写入 `ppt_core/command_dispatcher.py`：内部 `threading.Lock`；`dispatch` 加锁后调私有 `_dispatch_locked`；按 cmd 字段分支路由到 mouse / ppt / 回调；所有回调包 try/except；`dispatch_many` 走 `ws_messages.parse` 后调 `dispatch`。

- [ ] **Step 4: 跑测试通过** — 期望 `12 passed`

- [ ] **Step 5: 提交** — `git add ppt_core/command_dispatcher.py tests/test_command_dispatcher.py && git commit -m "feat(ppt_core): command_dispatcher with thread-safe routing"`

---



## Task 5: ppt_core/mouse_controller.py

**Files:**
- Create: `ppt_core/mouse_controller.py`
- Create: `tests/test_mouse_controller.py`

**Interfaces:**
- `class MouseController`:
  - `__init__(self, *, screen_size=None)`
  - `apply_delta(dx, dy) -> None`
  - `set_absolute(x, y) -> None`
  - `click(count=1) -> None`
  - `flush_deltas() -> list[tuple[float,float]]`
  - `pending_clicks() -> list[int]`
  - `render_loop(stop_event) -> None`  # 独立线程消费

- [ ] **Step 1: 写测试** — 写入 `tests/test_mouse_controller.py`：用 `monkeypatch` 把 `ppt_core.mouse_controller.pyautogui` 替换为 `FakePyautogui`，断言 (a) `apply_delta(0.1, -0.2)` 经 `LASER_SENS=6` 缩放后入队，`flush_deltas()` 返回并清空；(b) `set_absolute(0.5, 0.25)` 调用 `Controller.position` 写 `(960, 270)`；(c) `click(2)` 入队；(d) 4 线程并发 500 次共 2000 条 delta 不丢。

- [ ] **Step 2: 跑测试失败** — `pytest tests/test_mouse_controller.py` 期望 `ModuleNotFoundError`。

- [ ] **Step 3: 写实现** — 写入 `ppt_core/mouse_controller.py`：内部 `threading.Lock` 保护 `_pending_deltas` / `_pending_clicks`；`_ensure_screen` 在首次 `set_absolute` 时通过 `pyautogui.size()` 探测（测试中已 monkeypatch 替换为 FakePyautogui）；`flush_deltas` / `pending_clicks` 原子返回并清空；`LASER_SENS = 6` 常量；额外 `render_loop(stop_event)` 方法供独立线程消费（每 8ms 取出 delta/click 调 `pynput.Controller.move` / `.click`）。

- [ ] **Step 4: 跑测试通过** — `pytest tests/test_mouse_controller.py` 期望 `5 passed`。

- [ ] **Step 5: 提交** — `git add ppt_core/mouse_controller.py tests/test_mouse_controller.py && git commit -m "feat(ppt_core): mouse controller with delta/click queue"`

---

## Task 6: ppt_core/ppt_executor.py

**Files:**
- Create: `ppt_core/ppt_executor.py`

**Interfaces:**
- `class PptExecutor`:
  - `__init__(self, *, save_dir="./ppt_files/", on_screenshot=None)`
  - `execute(d: dict) -> None`

**支持的 cmd：** NEXT_PAGE / PREV_PAGE / FULL_SCREEN / FROM_CURRENT / BLACK_SCREEN / WHITE_SCREEN / EXIT / SEND_TEXT / SELECT_ALL / COPY / PASTE / DELETE / SCREENSHOT / OPEN_PPT

- [ ] **Step 1: 写实现** — 写入 `ppt_core/ppt_executor.py`：所有 pyautogui/pyperclip import 用 try/except 容错；SCREENSHOT 调 `pyautogui.screenshot(save_path)` 后调 `on_screenshot(abs_path)`；OPEN_PPT 优先用传入的 `d.get("path")`，否则用 `tempfile.mkstemp(suffix=".pptx")` 启动空文档；SEND_TEXT 走 `pyperclip.copy + hotkey("ctrl","v")`。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_core.ppt_executor import PptExecutor, PPT_EXTS; print(len(PPT_EXTS))"` 期望 `7`。

- [ ] **Step 3: 提交** — `git add ppt_core/ppt_executor.py && git commit -m "feat(ppt_core): ppt_executor (pyautogui wrapper)"`

---

## Task 7: ppt_core/ppt_notes.py

**Files:**
- Create: `ppt_core/ppt_notes.py`

**Interfaces:**
- `class PptNotesWorker`:
  - `__init__(self, *, send_fn, get_settings, debug=False)`
  - `start() -> None`：守护线程；200ms 轮询当前幻灯片备注。
  - `stop() -> None`
  - `request_refresh() -> None`

- [ ] **Step 1: 写实现** — 写入 `ppt_core/ppt_notes.py`：照搬旧 `ppt_pc_client.py` 中可移植的 COM 读取部分（`_ppt_notes_shape_text` / `_ppt_notes_table_text` / `_ppt_notes_walk_shapes` / `_ppt_notes_try_read_once`），但 `send_fn` 接收构造好的 dict；保留 `_notes_last_sent` 去重；保留 `get_settings().get("ppt_notes_enabled")` 守门；缺 `pywin32` 时打印提示并 return。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_core.ppt_notes import PptNotesWorker; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_core/ppt_notes.py && git commit -m "feat(ppt_core): ppt_notes COM worker"`

---

## Task 8: ppt_core/downloads.py

**Files:**
- Create: `ppt_core/downloads.py`

**Interfaces:**
- `class DownloadManager`:
  - `__init__(self, *, base_url, save_dir, on_record_added=None, on_complete=None)`
  - `enqueue(uri: str) -> None`：后台下载
  - `records() -> list[dict]`
  - `reveal(path: str) -> None`
  - `open_folder() -> None`

- [ ] **Step 1: 写实现** — 写入 `ppt_core/downloads.py`：内部 `threading.Lock` 保护 `_records`；`enqueue` 启 `Thread(daemon=True)` 调 `requests.get(stream=True)` 流式写盘；完成后 `_records.insert(0, ...)` + 截断 50 + 调回调；`reveal` / `open_folder` 用 `subprocess.run(["explorer", ...])` 容错。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_core.downloads import DownloadManager; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_core/downloads.py && git commit -m "feat(ppt_core): download manager"`

---

## Task 9: ppt_core/ws_client.py

**Files:**
- Create: `ppt_core/ws_client.py`

**Interfaces:**
- `class WsClient(QThread)`:
  - `__init__(self, *, base_url, sub_path, room_id, on_message, on_status, on_connected, on_disconnected)`
  - `run() -> None`：QThread 入口；内 `asyncio.new_event_loop()` + `run_until_complete(connect_loop())`
  - `send(payload: dict) -> None`
  - `stop() -> None`

- [ ] **Step 1: 写实现** — 写入 `ppt_core/ws_client.py`：从 `ppt_pc_client.websocket_client_loop` 移植：URL 拼装（https→wss、http→ws）、MINI_HELLO 握手、VERSION_MISMATCH、ONLINE/OFFLINE 旁路、LASER/MOUSE_CLICK 直进 `on_message`、指数退避重连（1/2/4/8/16s 封顶 30s）。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_core.ws_client import WsClient; print('ok')"` 期望 `ok`（首次 import PySide6，可能拉 5s；超时则跳过）。

- [ ] **Step 3: 提交** — `git add ppt_core/ws_client.py && git commit -m "feat(ppt_core): async ws client (QThread host)"`

---

## Task 10: ppt_core/gesture_bridge.py

**Files:**
- Create: `ppt_core/gesture_bridge.py`
- Create: `tests/test_gesture_bridge.py`

**Interfaces:**
- `class GestureBridge`:
  - `__init__(self, *, dispatcher, on_status, on_fps, on_send_text)`
  - `start() -> Optional[str]`
  - `stop() / start_pairing() / reset_pairing() / swap_roles(bool) / save() -> None`
  - `engine` 属性

- [ ] **Step 1: 写测试** — 写入 `tests/test_gesture_bridge.py`：`monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", FakeEngine)`；FakeEngine 记录 `start/stop/start_pairing` 调用；FakeDispatcher 记录 `dispatch(event)` 调用；断言 `bridge.start()` 调用 FakeEngine.start() 且 `engine.dispatch_fn(fake_dispatcher.dispatch)`；FakeEngine 模拟发出 `{"cmd":"LASER","x":0.5,"y":0.3}` → FakeDispatcher 收到。

- [ ] **Step 2: 跑测试失败** — `pytest tests/test_gesture_bridge.py` 期望 `ModuleNotFoundError`。

- [ ] **Step 3: 写实现** — 写入 `ppt_core/gesture_bridge.py`：

```python
from typing import Callable, Optional
from pc_gesture.engine import GestureEngine

class GestureBridge:
    def __init__(self, *, dispatcher, on_status, on_fps, on_send_text):
        self._dispatcher = dispatcher
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        self._engine: Optional[GestureEngine] = None

    def _ensure(self) -> GestureEngine:
        if self._engine is None:
            self._engine = GestureEngine(
                dispatch_fn=self._dispatcher.dispatch,
                on_status=self._on_status,
                on_fps=self._on_fps,
                on_send_text=self._on_send_text,
            )
        return self._engine

    def start(self) -> Optional[str]:
        return self._ensure().start()

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    def start_pairing(self) -> None:
        self._ensure().start_pairing()

    def reset_pairing(self) -> None:
        self._ensure().reset_pairing()

    def swap_roles(self, swapped: bool) -> None:
        eng = self._ensure()
        eng.cfg.dual_roles_swapped = bool(swapped)
        eng.save_config()
        if eng._semantics is not None:
            eng._semantics.reload_config(eng.cfg)

    def save(self) -> None:
        if self._engine is not None:
            self._engine.save_config()

    @property
    def engine(self):
        return self._engine
```

- [ ] **Step 4: 跑测试通过** — `pytest tests/test_gesture_bridge.py` 期望至少 `3 passed`。

- [ ] **Step 5: 提交** — `git add ppt_core/gesture_bridge.py tests/test_gesture_bridge.py && git commit -m "feat(ppt_core): gesture bridge to dispatcher"`

---


## Task 11: ppt_qt/theme.py

**Files:**
- Create: `ppt_qt/__init__.py`
- Create: `ppt_qt/theme.py`

**Interfaces:**
- 常量：`SUNSET_TOP`, `SUNSET_MID`, `SUNSET_BOT`
- 常量：`GLASS_BG`, `GLASS_BORDER`
- 常量：`CORAL_PRIMARY`, `BLUE_LINK`, `GREEN_OK`, `RED_ERR`
- `paint_sunset_background(painter, rect)`：QPainter 绘日落渐变
- `GLOBAL_QSS: str`：全局 QSS

- [ ] **Step 1: 写实现** — 写入 `ppt_qt/theme.py` 与 `ppt_qt/__init__.py`（空）。theme.py 用 PySide6 导入：QColor、QLinearGradient、QPainter、QRect；定义上述常量；`paint_sunset_background` 在 rect 上 setColorAt 0/0.5/1 → 三色渐变 fillRect；GLOBAL_QSS 至少 1000 字符覆盖 QMainWindow 透明 / QPushButton 圆角 / QCheckBox 选中色 / QRadioButton / QLineEdit / QListWidget / QStatusBar。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.theme import GLOBAL_QSS, paint_sunset_background; print(len(GLOBAL_QSS))"` 期望 > 1000。

- [ ] **Step 3: 提交** — `git add ppt_qt/ && git commit -m "feat(ppt_qt): theme (sunset gradient + QSS)"`

---

## Task 12: ppt_qt/widgets/* (4 控件)

**Files:**
- Create: `ppt_qt/widgets/__init__.py` (空)
- Create: `ppt_qt/widgets/glass_card.py`
- Create: `ppt_qt/widgets/primary_button.py`
- Create: `ppt_qt/widgets/sidebar.py`
- Create: `ppt_qt/widgets/status_pill.py`

**Interfaces:**
- `GlassCard(QWidget)`：objectName="GlassCard"
- `PrimaryButton(QPushButton)`：objectName="PrimaryButton"
- `SecondaryButton(QPushButton)`：objectName="SecondaryButton"
- `Sidebar(QWidget)`：
  - `__init__(self, *, items: list[tuple[str, str]], current: int = 0, on_change=None, on_exit=None, parent=None)`
  - `currentChanged = Signal(int)`
  - 固定宽度 72px；顶部 logo P；中间导航按钮；底部 ⌬ 退出
- `StatusPill(QWidget)`：
  - `__init__(self, *, status_text="", button_text="", on_button=None, parent=None)`
  - `set_status(text) / set_ok(bool|None) / set_button_text(text)`

- [ ] **Step 1: 写 glass_card.py** — 继承 QWidget，setObjectName("GlassCard")，setAttribute(Qt.WA_StyledBackground, True)，无 paintEvent。

- [ ] **Step 2: 写 primary_button.py** — 两个类 PrimaryButton/SecondaryButton 仅在 __init__ 里 setObjectName。

- [ ] **Step 3: 写 sidebar.py** — 实现 Sidebar 类（代码见 §设计 §2 描述），emit currentChanged；底部 ⌬ 按钮 on_exit 回调无则不显示。

- [ ] **Step 4: 写 status_pill.py** — 实现 StatusPill 类；set_ok(True) 绿 + box-shadow glow；set_ok(False) 红；set_ok(None) 灰。

- [ ] **Step 5: 冒烟** — `python -c "from ppt_qt.widgets import Sidebar, StatusPill, GlassCard, PrimaryButton, SecondaryButton; print('ok')"` 期望 `ok`。

- [ ] **Step 6: 提交** — `git add ppt_qt/widgets/ && git commit -m "feat(ppt_qt): glass_card, buttons, sidebar, status_pill widgets"`

---

## Task 13: ppt_qt/overlays/spotlight.py

**Files:**
- Create: `ppt_qt/overlays/__init__.py` (空)
- Create: `ppt_qt/overlays/spotlight.py`

**Interfaces:**
- `SpotlightOverlay(QWidget)`：
  - `__init__(self, parent=None)`
  - `apply(cx, cy, hw, hh)`：节流 36ms 后 update()
  - `hide_overlay()`

- [ ] **Step 1: 写实现** — WindowFlags = FramelessWindowHint | WindowStaysOnTopHint | Tool；WA_TranslucentBackground；paintEvent 中 fillRect(black 168) → setCompositionMode(Clear) → fillPath(rect.subtracted(ellipse))；节流用 QTimer.singleShot。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.overlays.spotlight import SpotlightOverlay; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/overlays/spotlight.py && git commit -m "feat(ppt_qt): spotlight overlay (QPainter)"`

---

## Task 14: ppt_qt/overlays/timer_overlay.py

**Files:**
- Create: `ppt_qt/overlays/timer_overlay.py`

**Interfaces:**
- `TimerOverlay(QWidget)`：
  - `__init__(self, parent=None)`
  - `show_countdown(seconds)` / `show_stopwatch(start_seconds=0)` / `hide_overlay()`
  - `pause() / resume() / reset(seconds=None)`

- [ ] **Step 1: 写实现** — 移植旧 `_gui_timer_overlay_*` 方法为 QWidget 子类；QTimer 1000ms tick；format_timer_label 工具函数抽到类内；`update_label` 触发 `self.label.setText(...)`；剩余秒 = 0 时停 tick。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.overlays.timer_overlay import TimerOverlay; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/overlays/timer_overlay.py && git commit -m "feat(ppt_qt): timer overlay (QWidget)"`

---

## Task 15: ppt_qt/pages/connect_page.py

**Files:**
- Create: `ppt_qt/pages/__init__.py` (空)
- Create: `ppt_qt/pages/connect_page.py`

**Interfaces:**
- `ConnectPage(QWidget)`：
  - `__init__(self, *, room_id, on_toggle_service, parent=None)`
  - `set_status(text)` / `set_running(bool)` / `set_mobile_online(bool)`

- [ ] **Step 1: 写实现** — 左侧 GlassCard 装大号配对码 (36px) + 二维码 (PIL Image → QPixmap) + 移动端状态 pill；右侧主按钮 "启动服务" / "停止服务"；按钮按 set_running 切换 label。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.pages.connect_page import ConnectPage; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/pages/connect_page.py && git commit -m "feat(ppt_qt): connect page"`

---

## Task 16: ppt_qt/pages/behavior_page.py

**Files:**
- Create: `ppt_qt/pages/behavior_page.py`

**Interfaces:**
- `BehaviorPage(QWidget)`：
  - `__init__(self, *, settings: dict, on_change: Callable[[dict], None], parent=None)`
  - `reload_from_model()`

- [ ] **Step 1: 写实现** — 4 个 QCheckBox + 1 个 QLineEdit (默认 PPT 路径) + 浏览/清除按钮；任何 widget 变化构造新 settings dict 调 on_change。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.pages.behavior_page import BehaviorPage; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/pages/behavior_page.py && git commit -m "feat(ppt_qt): behavior page"`

---

## Task 17: ppt_qt/pages/transfers_page.py

**Files:**
- Create: `ppt_qt/pages/transfers_page.py`

**Interfaces:**
- `TransfersPage(QWidget)`：
  - `__init__(self, *, on_reveal, on_open_dir, parent=None)`
  - `set_records(records: list[dict])`

- [ ] **Step 1: 写实现** — QListWidget + 两个按钮 (在文件夹中显示 / 打开保存目录)；records 元素 {name, path, ts} 转 "MM-DD HH:MM  filename" 显示；on_reveal(idx) 回调。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.pages.transfers_page import TransfersPage; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/pages/transfers_page.py && git commit -m "feat(ppt_qt): transfers page"`

---


## Task 18: ppt_qt/pages/gesture_page.py

**Files:**
- Create: `ppt_qt/pages/gesture_page.py`

**Interfaces:**
- `GesturePage(QWidget)`：
  - `__init__(self, *, bridge, parent=None)`
  - `set_status(text) / set_fps(fps)`
  - 内置 5 个控件：1 checkbox (仅预览) / 2 radio (单人/双人) / 2 checkbox (镜像 / 交换 A/B) / 启动 + 停止 + 配对 + 重新配对 4 个按钮
  - 与 `bridge.engine.cfg.raw` 直接交互；`bridge.save()` 落盘

- [ ] **Step 1: 写实现** — 与 `bridge` 协作；按钮 click → 调 `bridge.start() / stop() / start_pairing() / reset_pairing() / swap_roles(bool)`；`bridge.engine.cfg.raw["..."]` 写回；任何状态变化调 `bridge.save()`。

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.pages.gesture_page import GesturePage; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt/pages/gesture_page.py && git commit -m "feat(ppt_qt): gesture page"`

---

## Task 19: ppt_qt/app.py (PptQtApp 组合根)

**Files:**
- Create: `ppt_qt/app.py`

**Interfaces:**
- `class PptQtApp`：
  - `__init__(self)`
  - `run() -> int`
  - 内部组装: settings / room / mouse / ppt / dispatcher / downloads / ws_client / bridge / spotlight / timer / 4 page
  - 信号路由: `_on_toggle_service / _on_ws_status / _on_file_arrived / _on_settings_changed / _broadcast_settings / _on_client_settings / _on_spotlight / _on_timer_overlay / _on_window_minimize / _on_window_restore / _on_reveal_selected / _on_open_save_dir / _on_gesture_status / _on_gesture_fps / _on_gesture_send_text / _quit_app`

- [ ] **Step 1: 写实现** — 写入 `ppt_qt/app.py`，核心是：
  - 在 `__init__` 里依次实例化 ppt_core 模块
  - 用 QMainWindow + QHBoxLayout 装 Sidebar + QStackedWidget（4 个 page）
  - 用 QSystemTrayIcon 替换旧 pystray
  - 重写 `centralWidget().paintEvent` 调 `paint_sunset_background`
  - `_on_toggle_service` 控制 ws_client.start/stop 并切 StatusPill 按钮文字
  - `_on_spotlight(None)` 隐藏；非 None 时 showFullScreen + apply
  - `_on_gesture_send_text` 用 QInputDialog 替代旧 simpledialog
  - 全代码 ~250 行

- [ ] **Step 2: 冒烟** — `python -c "from ppt_qt.app import PptQtApp; print('ok')"` 期望 `ok`（首次 import PySide6，可能 5s）。

- [ ] **Step 3: 提交** — `git add ppt_qt/app.py && git commit -m "feat(ppt_qt): PptQtApp composition root"`

---

## Task 20: ppt_qt.py (入口)

**Files:**
- Create: `ppt_qt.py`

- [ ] **Step 1: 写实现** — 写入 `ppt_qt.py`（5 行）：

```python
import sys
from ppt_qt.app import PptQtApp

if __name__ == "__main__":
    sys.exit(PptQtApp().run())
```

- [ ] **Step 2: 冒烟** — `python -c "import ppt_qt; print('ok')"` 期望 `ok`。

- [ ] **Step 3: 提交** — `git add ppt_qt.py && git commit -m "feat: ppt_qt entry point"`

---

## Task 21: 端到端冒烟 (旧/新同跑对比)

**Files:** none

- [ ] **Step 1: 旧客户端冒烟** — `python ppt_pc_client.py` 跑 6 秒后自动退出，验证 4 个选项卡正常加载、手势引擎可启动、模型已下载。

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
import ppt_pc_client as m
app = m.PptDesktopApp()
def s():
    try: app._quit_app()
    except Exception: pass
app.root.after(6000, s)
app.run()
" 2>&1 | tail -10
```

- [ ] **Step 2: 新客户端冒烟** — `python ppt_qt.py` 同样跑 6 秒后自动退出，验证 PySide6 启动、4 个 page 加载、glass 渐变背景渲染：

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from PySide6.QtCore import QTimer
from ppt_qt.app import PptQtApp
app = PptQtApp()
QTimer.singleShot(6000, app._quit_app)
sys.exit(app.run())
" 2>&1 | tail -10
```

- [ ] **Step 3: 跑全部 pytest**

```bash
cd "C:/Users/admin_gmail/PyCharmMiscProject"
.venv/Scripts/python.exe -m pytest tests/ 2>&1 | tail -5
```

Expected: 全部 passed（≥ 30 tests）。

- [ ] **Step 4: 提交** — `git add -A && git commit -m "chore: e2e smoke verified - both clients boot" --allow-empty`

---

## 自审检查 (plan 完成后做)

- [ ] **Spec 覆盖**：每节 spec 都能指向至少一个 task 实施
  - §1 仓库结构 → Task 1 (mkdir / git init) + Task 19/20 (ppt_qt/app.py + ppt_qt.py)
  - §2 UI 布局 → Task 11 (theme) + Task 12 (widgets) + Task 15-18 (pages)
  - §3 线程 → Task 4 (dispatcher lock) + Task 5 (mouse lock) + Task 9 (ws_client QThread)
  - §4 测试 → Task 1 (pytest scaffolding) + 各 task 内的 TDD step
  - Win32 → Task 7 (ppt_notes 保留 win32com) + Task 13 (聚光灯改 QPainter) + Task 14 (计时器改 QWidget)

- [ ] **占位扫描**：无 TBD / TODO / "implement later" / "fill in details"

- [ ] **类型一致**：
  - `CommandDispatcher.dispatch(d: dict)` ←→ `GestureBridge._ensure()` 把 `self._dispatcher.dispatch` 作为 `dispatch_fn` 传入
  - `WsClient.send(payload: dict)` ←→ `_broadcast_settings` 调 `self._ws.send(payload)`
  - `MouseController.apply_delta(dx, dy)` / `set_absolute(x, y)` ←→ `CommandDispatcher._dispatch_locked` 调用

- [ ] **任务粒度**：21 个任务，每个含独立测试或冒烟 + commit 步骤

---

## 执行选项

1. **Subagent-Driven (推荐)** — 每任务派一个 fresh subagent，任务间 review；迭代快。
2. **Inline Execution** — 在当前会话中顺序执行任务，批量带 checkpoint。

请告知选哪个，然后调用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`。
