# pc_gesture 模块补齐 — 设计

日期：2026-07-04
状态：已确认关键决策，待用户最终确认设计

## 背景

`ppt_pc_client.py` 在「手势控制」选项卡中已经按完整模块调用了 `pc_gesture`：

- `from pc_gesture.config import load_gesture_config, save_gesture_config`
- `from pc_gesture.engine import GestureEngine`
- `eng.cfg.raw["preview_only"] / "mirror" / "operator_mode" / "dual_roles_swapped" / "enabled"`
- `GestureEngine(dispatch_fn, on_status, on_fps, on_send_text)`
- `eng.running`, `eng.start() -> Optional[str]`, `eng.stop()`
- `eng.start_pairing()`, `eng.reset_pairing()`, `eng.save_config()`
- `eng._semantics.reload_config(cfg)`

仓库中目前**不存在** `pc_gesture/` 包。本设计补齐此包，并使其能在 UI 控制下端到端运行。

## 决策摘要（已与用户对齐）

| 项 | 选择 |
|---|---|
| 实现完整度 | 完整可运行 |
| MediaPipe 路线 | MediaPipe Tasks 0.10+（HandLandmarker） |
| 手势识别策略 | HandLandmarker 21 关键点 + 全自研分类（不依赖预训练手势模型） |
| 双人协作 A/B 判定 | 双手 x 位置划分 + 1 秒食指确认（可交换） |
| 启动/预览 | 后台线程读摄像头 + OpenCV 独立预览窗口 |
| 包结构 | `pc_gesture/` 含 `__init__.py` / `config.py` / `semantics.py` / `engine.py` |

## 包结构

```
pc_gesture/
├── __init__.py            # 包标记 + re-export GestureEngine / load_gesture_config
├── config.py              # GestureConfig dataclass, load_gesture_config, save_gesture_config
├── semantics.py           # GestureSemantics（每帧分类 + 状态机 + 双人配对）
└── engine.py              # GestureEngine（编排 + 摄像头 + MediaPipe 线程）
```

约束：

- 仅 4 个文件，每个职责单一；
- `config.py` 必须提供 `load_gesture_config() -> GestureConfig` 与 `save_gesture_config(cfg)`；
- `engine.py` 必须导出 `GestureEngine`，构造签名 `(dispatch_fn, on_status, on_fps, on_send_text)`；
- `engine.GestureEngine._semantics` 必须是 `GestureSemantics` 实例，提供 `reload_config(cfg)`；
- 命令格式必须与 `ppt_pc_client.dispatch_remote_command` 兼容。

## 模块职责

### config.py

```python
@dataclass
class GestureConfig:
    preview_only: bool
    operator_mode: str        # "single" | "dual"
    dual_roles_swapped: bool
    raw: dict                 # 透传全部 JSON 字段，含阈值、camera_index 等

DEFAULT_GESTURE_CONFIG = {
    "preview_only": False,
    "mirror": True,
    "operator_mode": "single",
    "dual_roles_swapped": False,
    "enabled": False,
    "camera_index": 0,
    "show_preview_window": True,
    "sensitivity": {
        "pinch_threshold": 0.07,        # 拇指尖到食指尖距离 / 手掌宽度
        "swipe_min_velocity": 0.35,     # 每帧 x 归一化位移
        "swipe_history_ms": 220,        # 滑动判定窗口
        "swipe_cooldown_ms": 700,       # 滑动后冷却
        "gesture_cooldown_ms": 800,     # 一次性手势冷却
        "palm_hold_ms": 1800,           # 张掌持续触发 on_send_text
        "laser_smoothing": 0.5,         # 0=不滤波，1=全上一帧
        "pointing_index_min_extend": 0.04,  # 食指指尖到 PIP 的归一化位移
        "thumb_extension_min": 0.05,    # 拇指尖到 MCP 的归一化位移
    },
}
```

文件位置：`ppt_pc_client_gesture.json`（同 `ppt_pc_client.py` 所在目录）。

`load_gesture_config()`：读取 JSON，缺失字段从默认值补齐，返回 `GestureConfig`。`raw` 始终是完整 JSON dict。

`save_gesture_config(cfg)`：把 `cfg.raw` 原子写回（临时文件 + os.replace）。

### semantics.py

`GestureSemantics` 负责「关键点 → 手势事件」。

#### 手势分类（基于 21 关键点的几何规则）

| 手势 | 判定条件（归一化坐标系） | 输出事件 |
|---|---|---|
| 食指移动（激光） | index TIP.y < index PIP.y - ext，middle/ring/pinky TIP.y > PIP.y | 每帧 `{"cmd":"LASER","x":tip.x,"y":tip.y}` |
| 捏合 | thumb TIP 与 index TIP 距离 < pinch_threshold × 手宽 | 一次性 `{"cmd":"MOUSE_CLICK","count":1}` |
| 左右挥 | wrist x 在 swipe_history_ms 内位移 > swipe_min_velocity；方向按位移正负 | 一次性 `{"cmd":"NEXT_PAGE"}` / `{"cmd":"PREV_PAGE"}` |
| 握拳 | 4 指 TIP 均在 PIP 下方（y 更大） | 一次性 `{"cmd":"BLACK_SCREEN"}` |
| 张掌 | 4 指 TIP 均在 PIP 上方 | 一次性 `{"cmd":"WHITE_SCREEN"}`；持续 palm_hold_ms 调 on_send_text |
| 竖拇指 | thumb 远离 index MCP 且 4 指卷曲 | 一次性 `{"cmd":"FULL_SCREEN"}` |
| 拇指向下 | thumb TIP.y > wrist.y + 0.05 且其他指卷曲 | 一次性 `{"cmd":"EXIT"}` |

「一次性」靠状态机：`IDLE → DETECTED → COOLDOWN`；`gesture_cooldown_ms` 内不重复。

#### 双人模式

- dual 模式下，hand_landmarks 按 x 坐标分为 left / right 两槽；
- 默认 `A = left = 导航（挥页）`、`B = right = 指控（激光/捏合/F5/退出/托掌）`；
- `dual_roles_swapped = True` 时左右对调；
- 单人模式下，若同时识别到 2 只手，只取 `A` 槽（左侧那只）的关键点；
- 摄像头坐标轴：`x` 0→1 从左到右；`y` 0→1 从上到下（MediaPipe 默认）。

#### 配对流程

`start_pairing()` 进入 `pairing_state`，3 秒超时窗口：

- 用户点击「开始双人配对」→ engine 设置 `pairing_until = now + 3s`、`pairing_target = "A"`；
- 在窗口内，若左侧手进入「Pointing_Up」并稳定 1 秒，记录 `pairing_confirmed = True`，恢复常规手势识别；
- 超时未确认 → 自动回到 `pairing_confirmed = False`；
- `reset_pairing()` 立即取消配对状态。

#### reload_config

清空所有 hand state 机；阈值从 `cfg.raw["sensitivity"]` 重新读取；不影响摄像头线程。

### engine.py

```python
class GestureEngine:
    def __init__(self, dispatch_fn, on_status, on_fps, on_send_text): ...
    @property
    def cfg(self) -> GestureConfig
    @property
    def running(self) -> bool
    def start(self) -> Optional[str]: ...      # 缺依赖 / 无摄像头时返回错误字符串
    def stop(self) -> None: ...
    def start_pairing(self) -> None: ...
    def reset_pairing(self) -> None: ...
    def save_config(self) -> None: ...
    # 私有：
    #   self._semantics: GestureSemantics
    #   self._thread: Optional[Thread]
    #   self._stop_event: Event
    #   self._pairing: bool
    #   self._pairing_lock: Lock
```

`start()` 顺序：

1. 延迟 `import cv2`、`mediapipe.tasks.python`、`mediapipe.tasks.python.vision`；
2. 检查 `mediapipe` 与 `opencv-python` 是否就绪，缺则返回 `f"缺少依赖：{e}（请 pip install opencv-python mediapipe）"`；
3. 检查 `HandLandmarker` 模型文件（`hand_landmarker.task`），缺失则从 `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task` 下载到 `pc_gesture_models/`；
4. 打开 `cv2.VideoCapture(cfg.raw["camera_index"])`，不可用则返回错误；
5. 启动后台 `_loop` 线程。

`_loop()` 主循环（每帧）：

1. `cap.read()` 拿 BGR；
2. 若 `cfg.raw["mirror"]`，`cv2.flip(frame, 1)`；
3. 转 `mp.Image(IMAGE_FORMAT_SRGB, cv2.cvtColor(frame, BGR2RGB))`；
4. `landmarker.detect(mp_image)` → 手数 ≤2；
5. 把 `hand_landmarks` + `handedness` 喂给 `self._semantics.process(...)`；
6. 返回的事件列表逐个 `self._dispatch(ev, "gesture")`；
7. FPS 统计，1 秒一次 `self._on_fps(fps)`；
8. 若 `cfg.raw["preview_only"]` 为 False 且 `cfg.raw["show_preview_window"]` 为 True，则 `cv2.imshow("Gesture Preview", frame_with_overlays)`；预览窗口上的覆盖层包括手势标签、角色标签、配对状态；
9. `cv2.waitKey(1)` 让 OpenCV 拿到事件；线程可通过 `_stop_event` 中止。

`stop()`：

1. 设置 `_stop_event`；
2. join 线程（≤2 秒）；
3. `cap.release()`；
4. `cv2.destroyWindow("Gesture Preview")`；
5. `self.running = False`。

#### 错误处理

- 所有 `import` 用 `try/except ImportError`，捕获后返回字符串而非抛异常；
- 模型下载失败 → 返回 `f"模型下载失败：{e}"`，不启动线程；
- `cap.read()` 失败 3 次以上 → 调 `self._on_status("摄像头读取失败，已停止")`，退出循环；
- MediaPipe 推理异常 → 仅当帧丢弃，不杀线程；
- 整个 `start()` 抛异常 → `self.running = False`、状态栏收到错误信息。

## UI 文案对齐

`ppt_pc_client._build_gesture_tab` 末尾的提示文案已写明 8 类手势，本设计 1:1 覆盖：

> 食指移动=激光 · 捏合=点击 · 左右挥=翻页 · 握拳/张掌=黑/白屏 · 竖拇指=F5 · 拇指向下=退出 · 托掌进轮盘

实现完毕即可生效。

## 测试策略

由于手势识别依赖摄像头，本次实现**不**包含自动测试覆盖（避免引入物理设备 mock）。改为：

1. `python -c "from pc_gesture.engine import GestureEngine; print('ok')"` 验证包导入；
2. 人工冒烟（在用户的 Windows 笔记本上）：
   - 安装 `pip install opencv-python mediapipe`；
   - 启动 GUI → 「手势控制」选项卡 → 启动手势 → 看到预览窗口；
   - 依次演示 8 类手势，确认对应 PPT 指令生效。

## 文件清单

- 新增：`pc_gesture/__init__.py`
- 新增：`pc_gesture/config.py`
- 新增：`pc_gesture/semantics.py`
- 新增：`pc_gesture/engine.py`
- 新增（首次运行自动生成）：`ppt_pc_client_gesture.json`
- 新增（首次运行自动下载）：`pc_gesture_models/hand_landmarker.task`

## 风险与已知限制

1. **MediaPipe 模型首次下载需联网**；离线环境需要预置模型文件；
2. **OpenCV 预览窗口可能与 Tk 主窗口争抢焦点**；Tk 最小化时预览仍可见；
3. **拇指向下 vs 食指**在某些角度可能混淆；通过「拇指尖相对 wrist 的位移」+「其他指是否卷曲」做联合判定；
4. **多线程帧丢失**在 720p 下 30fps 稳定；1080p 时 MediaPipe Tasks 推理会拖慢，必要时可降分辨率。

## 后续非目标（本次不做）

- 不实现「手势录制 + 自定义手势」（UI 无对应入口）；
- 不实现 WebRTC 推流到手机；
- 不实现多人 (>2) 协作；
- 不实现非手部姿态（头部、面部）控制。