# 商业化产品级手势体验 spec

**Date:** 2026-07-08
**Status:** 4 节设计稿已获用户通过;本文件为正式 spec,待用户复核

## 1. 背景

`pc_gesture` 已演化为 9-event tip-touch + interlock 系统,`ppt_qt` 视频预览已重做,
`ppt_core` 派发走 COM-first + ThreadPoolExecutor。

但与商业化产品(Kare, Logitech Spotlight, Apple Vision Pro 手势控制)对比,仍缺:
- **首启速度**:从点图标到能控制 1-2 秒,差 0.5-1.5 秒
- **多手多人**:MediaPipe 实际只能稳定跟踪 2 手,3 人会议场景不支持
- **个人习惯**:用户重复 1 个动作时仍要选 8 个 combo,无记忆
- **扩展生态**:无 API/插件机制,SDK 不完整

本次 spec 集中提升 **质量(P0)+ 智能能力(双手多手 + 个人习惯)**。

## 2. 决策摘要(已与用户对齐)

| 项 | 决定 |
|---|---|
| 范围 | 一次性做:启动速度 + 多手 + 个人习惯,3 块打包单 spec |
| 启动速度子集 | 插件式:库预加载 + 快速打开(<200ms 主窗口) + 首启动画 |
| 3 人多手实现 | MediaPipe 单 model 跟踪 ≤ 2 手(稳定) + 第 3 人用第 2 帧轮圈 |
| 个人习惯存储 | 本地 JSON(`user_data/habits.json`) |
| 多 MediaPipe 实例 | **不做**(本期) — 留接口待 Phase 2(2x 模型开销大) |
| 个人习惯 UI | 顶栏 Smart Tray dropdown,top-3 常用动作 |
| 习惯数据保留 | 最近 100 条,RingBuffer 限 |
| 习惯时间窗 | 30 天(过期不入 top-3) |
| 不压 SDK/插件 | 本期不做(留后) |

## §1 · 架构总览

```
[主入口] app.py 启动(< 500ms 出主窗口)
   │
   ├─ 第 1 阶段(200ms):画主窗口 + 占位 toolbar
   │
   ├─ 第 2 阶段(后台):
   │   ├─ 插件式 import:cv2、mediapipe、bridge
   │   ├─ lazy load 9-event classifier(config on first access)
   │   └─ 进度信号 emit 给首启页
   │
   ├─ GesturePage:
   │   ├─ [NEW] 多手面板:3 个手 slot (A, B, C 颜色区分)
   │   ├─ 9-event tip-touch + interlock(已修)
   │   ├─ [NEW] Smart Tray:顶栏 dropdown 显示 top-3 习惯
   │   └─ [NEW] 首启画:进度环 + 加载文案
   │
   └─ Persistence:
       ├─ user_data/habits.json(个人习惯)
       └─ 已有:config.json(bindings/sensitivity)
```

## §2 · 启动速度 + 首启体验(0-1s 主窗口)

### 2.1 阶段化启动(200ms / 800ms / lazy)

```
t=0    main() 进入
t<200  QApplication 创建 + 加载 main window + show()
       UI 用 stub 占位:GesturePage 显示骨架
t=200  emit `core_ready` → 显示 1 帧"加载中"圈 + 进度 0%
t=200-800  后台线程加载:
         ├─ import cv2(~80ms)
         ├─ import mediapipe(~200ms,核心)
         ├─ load 9-event 模块(~10ms)
         └─ 启动 engine init camera
t=800  加载完成 → 进度 100% → 隐藏 loading → 显示真实 UI
```

### 2.2 关键实现点

```python
# app.py
class PptQtApp:
    def __init__(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyleSheet(GLOBAL_QSS)
        # 1. 先 build window(< 200ms)
        self._build_main_window()  # 占位 skeleton
        # 2. 立即 show 让用户看到
        self._win.show()
        # 3. async 加载 heavy 模块
        QTimer.singleShot(0, self._async_load_core)

    def _async_load_core(self):
        # 后台 import heavy 模块
        global cv2, mediapipe_tasks
        import cv2
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        # 启动 engine
        self._bridge = ...
        # 隐藏 loading
```

### 2.3 首启画组件(SplashPage)

- 全屏毛玻璃,中央进度环 + 加载文案(`加载手部模型…`、`初始化摄像头…`)
- 进度由后台任务逐个 emit `progress(stage, percent)` 更新
- < 800ms 看到主窗口 UI(已是 skeleton)> 看 splash
- > 1.5s 仍未完成,进度条超过 80% → 切换"继续等待"按钮

### 2.4 缓存策略

- 模型文件 → app 启动后首次 `load_model()` 缓存到 `__pycache__`
- user_data/ 目录首次访问 lazy create
- QSS 静态资源 → 编译期 buildozer(Android)嵌入

### 2.5 进度条 4 阶段

| 阶段 | 进度 | 状态文本 |
|------|------|----------|
| `importing` | 0-25% | 加载核心库… |
| `loading_model` | 25-50% | 加载手部模型(5MB)… |
| `init_camera` | 50-75% | 初始化摄像头… |
| `ready` | 100% | 完成 |

## §3 · 多手跟踪(2 人稳定 + 3 人接口预留)

### 3.1 现状(9-event 单手/双手模式)

- MediaPipe `HandLandmarker(num_hands=2)` → 最多同时检测 2 手
- 当前 Slot A/B 由 wrist.x 决定,9 个事件在 dual mode 下覆盖双手 4 指

### 3.2 多手 3 人方案折中

MediaPipe **单模型硬限 4 手**(实测 2 手是稳定上限,3 手 FPS 暴跌)。**3 人会议场景需要**:
- 单 MediaPipe 跟踪 2 手(稳定 FPS)
- 第 3 个手:MediaPipe 跟踪 1 个手 + 第 2 个手在「轮圈」(多人在同一桌前依次发言)
- 实际交互:演讲场景 A 持续操作, 第 3 个用户用主控外的"附加窗口"介入

### 3.3 实现策略

```python
# config: 多人多手模式
multi_person_mode: str = "off"  # off | 2_hand | 3_hand_round_robin

# semantics:扩展 HandState 支持多人
@dataclass
class HandState:
    slot: str = ""
    person_id: int = 0  # 0=主手,1=副手,2=第三手
    ...
```

主控 (`person_id=0`) 用 single MediaPipe 实例,占 slot A/B。第三人(`person_id=2`)另开 MediaPipe 实例,占 slot C(新加)。

### 3.4 9 事件扩展到 3 人

| 单人 | 2 人 | 3 人(扩展) |
|------|------|-------------|
| L_HAND_xxx | L_HAND_xxx | L_HAND_xxx(主) |
| R_HAND_xxx | R_HAND_xxx | R_HAND_xxx(主) |
| - | HANDS_INTERLOCK | C_HAND_xxx(第三手) |
| - | - | HANDS_INTERLOCK(主手×第三手) |

C_HAND 与 L/R_HAND 类似,但 prefix 为 "C"。

### 3.5 误触防护(3 人场景)

- 单人模式:MediaPipe 仍只跟踪 1 手
- 2 人模式:MediaPipe 跟踪 2 手,slot 互不干扰
- 3 人模式:MediaPipe × 2 并行(2 个 HandLandmarker 实例)
- 配置新增 `multi_person_mode: str`,UI 加切换 widget

### 3.6 测试覆盖

- 单 model 跟踪 ≤ 2 手:FPS ≥ 25
- 双 model 跟踪 3 手:FPS ≥ 20(2 帧 + 第 3 模型 1 帧交错)
- Slot C 错位 0 容忍(必须只读自己的 HandState)
- 3 人同时 interlock:语义层独立判断每两人对

## §4 · 个人习惯(动作推荐)

### 4.1 数据收集(被动)

- 启动 hook:在 `_process_one_hand` 现有 path 增加 `record_action(action, ts)` 调用
- 不打日志、不阻塞:动作入库用 `RingBuffer(maxlen=100)` (最近 100 次)
- 不分 user/duration:只关心"哪几个动作最近用过"

```python
# gesture_bridge.py
class GestureBridge:
    def __init__(...):
        self._habits = RingBuffer(maxlen=100)  # FIFO 100

    def _record_action(self, action: str, ts: float):
        self._habits.append((action, ts))
```

### 4.2 启动时分析(主动)

- 启动后 1 秒(等数据稳定)在后台线程跑分析
- 统计:每个 action 的最近 30 天调用频次
- 输出:top-3 actions(频次降序)

```python
# habits_analyzer.py(独立小模块)
class HabitAnalyzer:
    def __init__(self, actions_history: list[tuple[str, float]]):
        self._history = actions_history

    def top_n_actions(self, n: int = 3) -> list[str]:
        # 排除高频系统命令(避免误推)
        freq = Counter(a for a, _ in self._history)
        return [a for a, _ in freq.most_common(n)
                if a not in {"OPEN_PPT", "SCREENSHOT"}]
```

### 4.3 推荐 UI(Smart Tray)

- 顶栏 toolbar 加 dropdown"⭐ 常用":[下一页, 上一步, 黑屏]
- 用户点击 → 立即派发对应 action(同正常 binding)
- 推荐列表 30 天过期(自动隐藏空槽)

```python
# toolbar widget
class HabitTray(QComboBox):
    def __init__(self, habit_analyzer, dispatcher):
        ...
        self._analyzer = habit_analyzer
        self.refresh()  # 启动时调一次

    def refresh(self):
        self.clear()
        for action in self._analyzer.top_n_actions(3):
            self.addItem(action_labels[action], userData=action)
```

### 4.4 数据存储(user_data/habits.json)

```json
{
    "version": 1,
    "actions": [
        ["NEXT_PAGE", 1709452800.0],
        ["NEXT_PAGE", 1709456400.0],
        ["BLACK_SCREEN", 1709460000.0]
    ],
    "last_updated": 1709460000.0
}
```

```python
# habits_storage.py
def load_habits(user_data_dir: str) -> list[tuple[str, float]]:
    path = os.path.join(user_data_dir, "habits.json")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return [(a, t) for a, t in data.get("actions", [])]

def save_habits(user_data_dir: str, actions: list[tuple[str, float]]):
    path = os.path.join(user_data_dir, "habits.json")
    os.makedirs(user_data_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "version": 1,
            "actions": list(actions),
            "last_updated": time.time(),
        }, f)
```

### 4.5 隐私 / 性能

- 全部本地,不上传
- RingBuffer 限 100 条,内存 < 10KB
- 启动分析 1 秒后台线程,不阻塞 UI
- 用户可"清除数据"按钮(在设置页)
- 旧动作 (>30 天)在分析时被忽略,不入 top-3

### 4.6 测试覆盖

- 100 次动作 ring buffer 满了之后丢最旧
- Top-3 排序按频次降序
- 0 历史时 tray 显示空
- save/load JSON round-trip
- 关闭 GUI 不丢数据(flush)
- 30 天过滤:旧动作不计入
