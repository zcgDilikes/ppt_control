# PPT 遥控 PC 端 · PySide6 重构 + Glassmorphism UI 设计

日期：2026-07-04
状态：4 节设计稿已获用户通过；本文件为正式 spec，待用户复核

## 背景

`ppt_pc_client.py` 单文件 2803 行，类 `PptDesktopApp` 一个类吞了 1307 行（60+ 个方法）。同文件混了 10+ 个不相关子系统：WebSocket / 房间配置 / 设置持久化 / PPT 备注 COM / PPT 指令 / 文件下载 / 鼠标控制 / 聚光灯（Win32 GDI）/ 计时器浮窗 / 系统托盘 / GUI 主体。

`pc_gesture/` 已经模块化（4 文件 1041 行），是良好参照。上一轮已经把它补齐为可运行的完整模块。

本次目标：**一刀切重写整个 PC 客户端为 PySide6 / Qt**，同时把 UI 从 Tkinter 改为 Glassmorphism 风格。旧 `ppt_pc_client.py` 保留作回退。

## 决策摘要（已与用户对齐）

| 项 | 决定 |
|---|---|
| 范围 | 一刀切重写，旧 `ppt_pc_client.py` 留作回退 |
| 框架 | PySide6 / Qt 6 |
| 视觉风格 | Glassmorphism（毛玻璃 + 渐变背景） |
| 导航模式 | 左侧导航栏（图标 + 主区内容） |
| 配色 | 日落渐变（珊瑚粉 #ff6e7f → #ffd3d3 → 浅蓝 #bfe9ff） |
| 主题模式 | 仅深色 |
| 项目结构 | 颗粒拆解（~10 个子包，分层 ppt_core / ppt_qt） |
| Win32 集成 | 全面替换为 Qt 原生（聚光灯改 QPainter；计时器改 QWidget；PPT 备注保留 win32com） |
| 迁移策略 | 一刀切 |
| 新功能 | 不加（仅重写现有能力） |

## §1 · 仓库结构与分层

### 目录树（最终态）

```
PyCharmMiscProject/
├── ppt_pc_client.py            # 旧 Tkinter 实现（保留作回退，不动）
├── ppt_qt.py                   # 新入口；5 行启动 QApplication + PptQtApp.run()
├── pc_gesture/                 # 已完成，不动
│   ├── __init__.py / config.py / engine.py / semantics.py
│
├── ppt_qt/                     # 新 Qt 主体（仅 UI 与 Qt 集成）
│   ├── __init__.py
│   ├── app.py                  # PptQtApp：组合根 + 生命周期
│   ├── theme.py                # QPalette / QSS / 渐变背景绘制
│   ├── widgets/                # 复用控件
│   │   ├── glass_card.py       # 半透明圆角容器
│   │   ├── primary_button.py   # 主操作按钮
│   │   ├── sidebar.py          # 左侧导航
│   │   └── status_pill.py      # 顶部状态条
│   ├── pages/                  # 4 个页面（侧栏每项对应一页）
│   │   ├── connect_page.py     # 配对码 + 二维码 + 启动服务
│   │   ├── behavior_page.py    # 行为开关
│   │   ├── transfers_page.py   # 文件传输记录
│   │   └── gesture_page.py     # 手势控制（包装现有 pc_gesture）
│   └── overlays/               # 全屏/浮层
│       ├── spotlight.py        # 聚光灯（QWidget + QPainter）
│       └── timer_overlay.py    # 计时器浮窗（QWidget + QTimer）
│
├── ppt_core/                   # 纯逻辑（无 Qt 依赖，可单测）
│   ├── __init__.py
│   ├── settings.py             # 配置读写（替换原 load_settings_from_disk 等）
│   ├── room.py                 # 房间号生成/读写
│   ├── ws_client.py            # WebSocket 客户端（asyncio + websockets）
│   ├── ws_messages.py          # 消息类型 / 命令字面量
│   ├── command_dispatcher.py   # dispatch_remote_command 重写版
│   ├── mouse_controller.py     # 鼠标绝对/增量移动（pynput）
│   ├── ppt_notes.py            # PPT 备注 COM 读取
│   ├── ppt_executor.py         # execute_command 重写版（pyautogui）
│   ├── downloads.py            # 文件下载（requests 流式）
│   └── gesture_bridge.py       # 把 pc_gesture.GestureEngine 接入 dispatch
│
└── docs/superpowers/specs/2026-07-04-qt-redesign-design.md
```

### 分层原则

- **`ppt_core/`** 纯业务逻辑，零 Qt 依赖。可独立单元测试。
- **`ppt_qt/`** 仅 UI 与 Qt 集成。订阅 ppt_core 事件、调用 ppt_core 方法。
- **`pc_gesture/`** 维持现状。新增 `ppt_core/gesture_bridge.py` 做薄包装，让 `GestureEngine` 与 `ppt_core.command_dispatcher` 对接。
- **入口 `ppt_qt.py`** 极薄，5 行代码：构造 QApplication → 实例化 PptQtApp → app.run()。

### 依赖图（单向，无环）

```
ppt_qt.py → ppt_qt.app → ppt_qt.pages/* → ppt_core.* ← pc_gesture.engine
```

## §2 · UI 布局与视觉规范

### 主窗口（780×780，最小尺寸 620×620）

三段式纵向：72px 侧栏（左）+ 主区（中部，自适应宽度）+ 顶部状态条 + 底部信息条。

### 视觉规范

| 项 | 取值 |
|---|---|
| 背景 | 日落渐变 `#ff6e7f → #ffd3d3 → #bfe9ff`（QPainter 绘制，首版静态） |
| 玻璃面 | `rgba(20,20,30,0.55)` + `blur(20px)` + 1px 白色 10% 边 |

> **实现备注**：QtWidgets 不支持 `backdrop-filter`；视觉上以 `rgba(20,20,30,0.55)` 透明叠加 + 1px 白色描边模拟玻璃面（参见 `ppt_qt/theme.py` 中 `GLASS_BG = "rgba(20, 20, 30, 140)"`）。原 spec 中 `blur(20px)` 的承诺在 PySide6 路径下不实现。
| 圆角 | 卡片 16px / 按钮 10px / 侧栏图标 10px |
| 字体 | Segoe UI Variable（Win11 默认）；配对码用 Segoe UI Mono 字宽 |
| 主色 | 珊瑚粉 `#ff6e7f`（操作按钮 / 状态点） |
| 辅色 | 浅蓝 `#bfe9ff`（次按钮 / 链接） |
| 状态色 | 绿 `#34d399`（在线）/ 红 `#f87171`（离线）/ 灰（未启动） |

### 侧栏 4 项

| 图标 | 名称 | 职责 |
|---|---|---|
| ⌂ | 连接 | 配对码 + 二维码 + 启动/停止服务 + 移动端状态 |
| ⚙ | 行为 | 4 个开关（截图打开文件夹 / 文件传输打开文件夹 / 演示文稿自动打开 / 演讲者模式）+ 默认 PPT 路径输入框 |
| ↥ | 传输 | 最近 50 条文件下载记录，可一键在资源管理器中显示 |
| ✋ | 手势 | pc_gesture 控制台（启动/停止/单人/双人/镜像/交换 A/B/配对） |

底部一个 ⌬ 图标作为托盘退出按钮（pystray 替换为 QSystemTrayIcon）。

### 4 个 Page 内容映射

| Page | 主体组件 |
|---|---|
| connect_page | 大号配对码（36px 字宽 6px）+ 二维码（白底）+ 移动端状态 pill + 启动/停止主按钮 |
| behavior_page | 5 个 Checkbox + 1 个 Entry（默认 PPT 路径）+ 浏览/清除按钮 |
| transfers_page | Listbox + 在文件夹中显示按钮 + 打开保存目录按钮 |
| gesture_page | 启动/停止按钮 + 1 个 checkbox（仅预览）+ 2 个 radiobutton（单人/双人）+ 2 个 checkbox（镜像 / 交换 A/B）+ 双人配对按钮 + 状态文本 + FPS |

## §3 · 线程模型与数据流

### 线程拓扑

```
Qt Main Thread（GUI）
  QApplication · PptQtApp · 4 Page · SpotlightOverlay · TimerOverlay
      ▲ signal/slot (Qt.QueuedConnection)
      │
      │ ┌────────────────────────────┐   ┌──────────────────────────┐
      │ │ Asyncio Loop Thread        │   │ Gesture Engine Thread    │
      │ │ (QThread 子类 + inner loop) │   │ (pc_gesture.engine._loop)│
      │ │                            │   │                          │
      │ │  • ws_client.py            │   │  • cv2.VideoCapture      │
      │ │  • ON/OFF/CMD 接收         │   │  • MediaPipe HandLandmark│
      │ │  • asyncio.Lock 共享 ws    │   │  • cv2.imshow 预览窗     │
      │ └────────┬───────────────────┘   └──────────┬───────────────┘
               │ QMetaObject.invokeMethod / asyncio.run_coroutine_threadsafe
               ▼                                       ▼
      ┌─────────────────────────────────────────────────────────────┐
      │ ppt_core.command_dispatcher（线程安全队列 + 锁）              │
      │   in: dict(cmd=...)                                          │
      │   out: enqueue → ppt_executor / mouse_controller / GUI slot  │
      └────────────┬─────────────────────────────────────────────────┘
                   ▼
      ┌────────────────────────────┐  ┌────────────────────────────┐
      │ ppt_executor (pyautogui)   │  │ mouse_controller (pynput)  │
      └────────────────────────────┘  └────────────────────────────┘

      ┌────────────────────────────┐
      │ ppt_notes.py (独立线程)    │  pywin32 CoInitialize
      │   • 监听设置变更 + 触发    │  → 每 200ms 轮询当前幻灯片
      │   • 通过 ws 发 PPT_NOTES   │  → send to mini
      └────────────────────────────┘
```

### 跨线程通信统一约定

- **任何线程 → Qt 主线程**：`QMetaObject.invokeMethod(target, "slot_name", Qt.QueuedConnection, ...)` 或 `Signal.emit`（自动 Queued）。
- **Qt 主线程 → Asyncio 循环**：`asyncio.run_coroutine_threadsafe(coro, loop)`。loop 由 `ppt_core.ws_client` 内部 `QThread` 持有。
- **任何线程 → 后台工作线程（gesture）**：通过 Qt 信号送进 GestureEngine 的入站方法（stop/start_pairing 等）；gesture 出站事件通过 dispatch_fn 回流。
- **共享状态**：房间号、设置、下载记录。统一存盘到 `ppt_core.*` 模块级 + `threading.Lock` 保护。

### 关键数据流

1. **WS 收包**：asyncio 线程 → `ws_messages.parse(raw)` → `command_dispatcher.dispatch(msg)`
2. **激光 / 点击（高频）**：走 `mouse_controller` 内部双端队列（沿用旧实现）
3. **PPT 指令（低频）**：`ppt_executor.execute(cmd_dict)`，主线程调用 `pyautogui`
4. **聚光灯**：`SpotlightOverlay.show(cx,cy,hw,hh)` → 主线程 throttle 36ms 后 `update()` 重绘
5. **PPT 备注**：独立线程轮询 → 差异比较 → 通过 ws 发 `PPT_NOTES` 帧
6. **文件下载**：触发时 `threading.Thread(daemon=True)` 启动，下载完成追加记录

## §4 · 测试、错误处理、风险

### 测试策略

| 层 | 覆盖 | 方法 |
|---|---|---|
| `ppt_core/` | 命令解析、调度、消息序列化、设置往返 | pytest，纯函数测试，无 Qt |
| `pc_gesture/` | 手势分类、状态机、配对窗口 | pytest + 假 landmarks |
| `ppt_qt/` | GUI 组件渲染、信号槽连通 | `offscreen` QPA 平台跑 `QApplication` + 截图对比；不强制 |
| 端到端 | 启动 → 启动服务 → 模拟 ws 帧 → 指令生效 | 手工冒烟 |

### 错误处理约定

- **不吞异常**：所有回调包 try/except，错误打到 logger + 调 `on_status(msg)` 显示在顶部状态条。
- **致命错误**（Qt 主线程崩、WS 重连失败 5 次）：弹 QMessageBox，主窗口保持可见，不静默退出。
- **依赖缺失**（PySide6 / mediapipe / opencv-python）：启动时 `import` 检测，缺则弹窗 + 给出 pip 安装指令链接。
- **摄像头失败**：手势启动时弹窗「无法打开摄像头，请检查权限」。
- **WS 断开**：自动重连（指数退避 1/2/4/8/16 秒，封顶 30 秒），状态条转红。

### 已识别风险

1. Qt 打包后体积 100-150 MB（旧方案约 80 MB）。
2. QPainter 聚光灯 30fps（旧 GDI 60fps）；可接受。
3. `blur(20px)` 在低端 GPU 上掉帧；可加阈值检测自动降到 `blur(8px)`。
4. 深色玻璃主题长时间观看是否刺眼 — 由用户反馈。

### 不做事项

- 不改协议 / 服务端 / 手机端
- 不引入国际化（保留中文）
- 不打包成 exe（仍以 `python ppt_qt.py` 启动）
- 不动 `pc_gesture/` 子包（已完工）
- 不实现窗口拖动时的渐变跟随动画（首版静态）
- 无障碍（屏幕阅读器、键盘焦点环）首版不专门优化

## 文件清单（预计）

### 新增

- `ppt_qt.py`（入口）
- `ppt_qt/__init__.py`
- `ppt_qt/app.py`
- `ppt_qt/theme.py`
- `ppt_qt/widgets/{__init__,glass_card,primary_button,sidebar,status_pill}.py`
- `ppt_qt/pages/{__init__,connect_page,behavior_page,transfers_page,gesture_page}.py`
- `ppt_qt/overlays/{__init__,spotlight,timer_overlay}.py`
- `ppt_core/__init__.py`
- `ppt_core/{settings,room,ws_client,ws_messages,command_dispatcher,mouse_controller,ppt_notes,ppt_executor,downloads,gesture_bridge}.py`
- `tests/test_ppt_core/`（pytest）

### 不动

- `ppt_pc_client.py`（保留作回退）
- `pc_gesture/`（已完工）

## 后续（写完 spec 后）

→ 调用 `superpowers:writing-plans` 把本 spec 转写为可执行的实施计划（带文件级任务列表）。