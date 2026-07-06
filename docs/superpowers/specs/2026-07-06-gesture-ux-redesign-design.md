# 手势控制 UX 重新设计

日期：2026-07-06
状态：4 节设计稿已获用户通过；本文件为正式 spec，待用户复核

## 背景

`ppt_qt/pages/gesture_page.py` 自 2026-07-04 重映射 + 2026-07-05 教学功能两轮迭代后，页面堆叠了 4 段内容（示图卡 / 映射 / 试用 / 控制）+ 顶部工具栏 + 试用面板的历史记录。但用户反馈「不好用」——核心痛点是 **反馈弱**：不知道摄像头里发生什么，不知道识别状态，不知道为什么某个手势没生效。

现有方案是把 OpenCV 独立预览窗口 (`cv2.imshow`) 当作"看见发生了什么"的主要手段，但这要求用户扭头看另一个窗口，且窗口生命周期独立、关闭时机不对会造成泄漏。

目标：从 PM 视角重做 UX，以「实时反馈」为主线，把可视化、诊断、操作三件事压在一个屏幕里。

## 决策摘要（已与用户对齐）

| 项 | 决定 |
|---|---|
| 主攻方向 | 反馈弱（实时反馈 + 诊断信息） |
| 反馈落点 | 嵌入式预览 + 诊断面板 + 三处同步高亮 + 三色状态灯（四合一） |
| 信息架构 | 两栏布局：左侧「看得见」，右侧「配置」 |
| 既有 cv2 独立预览窗口 | 彻底移除，由主窗口嵌入式预览取代 |
| 数据上行架构 | 引擎组装 FrameSnapshot → Bridge 转发 → UI 150ms 轮询 + Qt Signal 兜底 |
| 嵌入式预览刷新率 | 跟随相机帧率（~30fps），自适应降级避免卡顿 |
| 诊断面板手指状态 | 仅在切换瞬间更新，稳定后静止（避免 30fps 闪烁） |
| 单/双人模式 / A/B 槽位 | 沿用现有语义，仅在诊断面板显式显示当前 slot |

## §1 · 架构

两栏布局，左侧是「看得见发生了什么」，右侧是「配置」。

```
┌────────────────────────┬─────────────────────────┐
│ LEFT (≈ 50% width)     │ RIGHT (≈ 50% width)     │
│                        │                         │
│ ┌──────────────────┐   │ 顶部工具栏：              │
│ │ [摄像头预览]      │   │  ● 三色灯 [教学模式]       │
│ │  16:9 QLabel     │   │  [重看教学] [查找]         │
│ │  cv2 → QImage    │   │                         │
│ │  150ms 刷新       │   │ ① 手势示图卡（7 行）       │
│ └──────────────────┘   │                         │
│                        │ ② 手势映射（7 行下拉）     │
│ 三色状态灯：             │                         │
│ 🟢 手 + 识别正常         │ ③ 实时试用              │
│ 🟡 手 + 识别不准         │   当前：✊ 握拳            │
│ 🔴 没看到手              │   历史（5 条）            │
│                        │                         │
│ 诊断面板：               │ 控制按钮：               │
│ FIST   未识别 | 识别中   │ [启动] [停止]            │
│ PALM   未识别 | 识别中   │ [恢复默认] [导出] [导入]   │
│ 食指     ●伸直 ●卷曲    │                         │
│ 中指     ●伸直 ●卷曲    │                         │
│ 无名指   ●伸直 ●卷曲    │                         │
│ 小指     ●伸直 ●卷曲    │                         │
│ 拇指     ●伸直 ●卷曲    │                         │
│ 手位置   (0.32, 0.61)  │                         │
│ 置信度   0.87           │                         │
│ Slot    A | B           │                         │
└────────────────────────┴─────────────────────────┘
```

### 文件改动

| 文件 | 改动 |
|---|---|
| `pc_gesture/types.py`（**新**） | 定义 `FrameSnapshot` / `HandSnapshot` dataclass |
| `pc_gesture/engine.py` | `_loop` 每帧组装并缓存 `FrameSnapshot`；新增 `on_frame` 回调参数 |
| `ppt_core/gesture_bridge.py` | 缓存 `latest_snapshot`；新增 `frame_signal` Qt Signal；新增 `latest_snapshot()` API |
| `ppt_qt/pages/gesture_page.py` | 大改：拆两栏；新增嵌入式预览 QLabel、诊断面板、三色灯；删除「显示预览」checkbox（cv2 预览已废）；三处同步高亮 |
| `pc_gesture/config.py` | `sensitivity` 新增 `low_confidence_threshold`（默认 0.6） |
| `tests/test_engine_frame_snapshot.py`（**新**） | FrameSnapshot 组装与字段完整性 |
| `tests/test_gesture_bridge_frame_signal.py`（**新**） | Bridge Signal emit + latest_snapshot 主线程安全 |
| `tests/test_status_light.py`（**新**） | 纯函数 `compute_status_light(snap) → "red"/"yellow"/"green"` |

## §2 · 数据流

### 2.1 新增 `FrameSnapshot`（每帧状态包）

引擎在每帧 MediaPipe 推理后，除了派发 `gesture` 事件，还**顺便**组装一个 `FrameSnapshot` 并缓存到 `self._latest_snapshot`，同时通过新的 `on_frame` 回调推给 Bridge。

```python
# 新增类型（pc_gesture/types.py）
@dataclass
class FrameSnapshot:
    timestamp_ms: int            # 引擎单调钟，毫秒
    frame_rgb: Optional[bytes]   # cv2 BGR → RGB bytes，None if 无帧
    frame_w: int
    frame_h: int
    hands: List[HandSnapshot]    # 0~2 个

@dataclass
class HandSnapshot:
    slot: str                    # "A" / "B"
    wrist_xy: Tuple[float,float] # (x, y) in [0,1]
    finger_states: Dict[str,bool] # {"thumb":True,"index":False,...} 伸直=True
    static_gesture: str          # FIST/PALM/POINTING_UP/THUMBS_UP/THUMBS_DOWN/NONE
    confidence: float            # 来自 MediaPipe handedness.score
    recognized_event: Optional[str]  # 最近一次识别的 gesture（rising-edge）
```

**关键点**：`finger_states` 直接来自 `_classify_static` 内部已有的 `index_ext` / `middle_ext` 等（`engine.py` 已有这些变量），只需暴露出来，不引入新分类器。

### 2.2 数据上行路径

```
引擎后台线程：
  cap.read() → landmarker.detect() → 组装 FrameSnapshot
                                    → cache self._latest_snapshot
                                    → 调 on_frame(snap)  (新回调)

Bridge（主线程 + 后台线程安全）：
  def _on_frame(snap):
      self._latest_snapshot = snap              # 主存最近一帧（原子赋值）
      self._frame_signal.emit(snap)             # Qt Signal，QueuedConnection

GesturePage（主线程，槽函数）：
  @Slot(object)
  def _on_frame(snap: FrameSnapshot):
      self._update_preview(snap)                # QLabel setPixmap
      self._update_status_light(snap)           # 三色灯
      self._update_diagnostics(snap)            # 诊断面板
      self._update_sync_highlight(snap)         # 三处高亮
```

**150ms 兜底**：Signal 是首选，但若 Signal 出问题（例如 Qt loop 阻塞），UI 用 150ms 轮询 `bridge.latest_snapshot()` 兜底。两条路并存，Signal 优先。

### 2.3 嵌入式预览刷新策略

`QLabel.setPixmap()` + 缩放到左栏宽度。**缩放后尺寸缓存**，避免每帧重算。Frame 比例不匹配时按比例 letterbox（黑色填充），不裁剪。

性能开销：30fps 1920×1080 → RGB bytes ≈ 6.2MB/帧 ≈ 186MB/s。GPU 直送 Qt QImage 用 `QImage(rgb_bytes, w, h, QImage.Format_RGB888)`，然后 `scaled()` 一次到目标尺寸缓存。CPU 占用应 < 5%（待实测）。

### 2.4 三色状态灯逻辑

| 颜色 | 条件 |
|------|------|
| 🔴 灰/红 | 没有手（`len(snap.hands) == 0` 或手位置 NaN） |
| 🟡 黄 | 有手但 `static_gesture == NONE` 或 `confidence < 0.6` |
| 🟢 绿 | 有手 + `static_gesture != NONE` + `confidence >= 0.6` |

`confidence < 0.6` 阈值由 `settings.sensitivity.low_confidence_threshold` 控制（默认 0.6）。

### 2.5 同步高亮（三处同步）

识别到手势时（`FrameSnapshot.recognized_event` 变化时）：

- 图卡对应行：`setStyleSheet("background:rgba(34,197,94,0.4)")` + 2s reset（已实现，保留）
- **映射下拉行**：`setStyleSheet("...")` 同步高亮（**新增**）
- **试用面板当前识别**：`setStyleSheet("...")` 同步高亮（**新增**）
- 三处共享同一个 `gesture_name`，用 `QTimer.singleShot(2000, ...)` 统一 reset

## §3 · 错误与边界

按发生概率从高到低：

### 边界 1：camera 没启动就进 GesturePage

诊断面板显示「等待摄像头…」，三色灯全灰。预览区显示「未启动」placeholder（`QLabel.setText("未启动")`）。不弹错误，等用户点「启动手势」。

### 边界 2：摄像头被占用 / 权限拒绝

引擎 `start()` 返回错误字符串（已有逻辑）。Bridge 在 `_on_bridge_status` 推送错误，UI 状态栏变红 + 「启动手势」按钮置灰（已经在 running 时）。预览区显示错误提示文字。

### 边界 3：手暂时离开画面

手位置在 `frame_h > 0` 但 `len(hands) == 0` 持续 > 1.5 秒 → 状态灯转灰，诊断面板的「手位置」显示「—」，**而不是直接消失**——保留历史信息让用户知道刚才有手。3 秒没手 → 完全清空诊断面板。

### 边界 4：MediaPipe 推理异常

引擎已有 `try/except` 包裹 `landmarker.detect()`（`engine.py:285-289`），失败时推空 `hand_landmarks`。FrameSnapshot 仍然生成，但 `hands=[]`，走边界 3 的逻辑。诊断面板显示「推理异常（已跳过）」。`GESTURE_DEBUG=1` 时打印 traceback。

### 边界 5：嵌入式预览 frame 太大，UI 卡顿

加**自适应降级**：

- 启动时测一次单帧 `setPixmap` 耗时
- 耗时 > 50ms → 自动降到**半分辨率**（`scale 0.5x`）
- 耗时 > 100ms → 降到**四分之一分辨率**（`scale 0.25x`）
- 状态栏提示「预览降级中：分辨率 X」
- 降级状态不持久化，重启恢复

### 边界 6：诊断面板的手指灯闪烁

每帧都重置手指状态时，用户视觉上看到的就是「稳定伸直/稳定卷曲」。**只在状态切换瞬间闪一下，稳定后静止**——避免 30fps 高频闪烁造成视觉疲劳。

具体：只有当 `finger_states[某指]` 与上一帧不同时，才更新该指的圆点颜色（`●伸直` / `○卷曲`）。不变就不重绘。

### 边界 7：Qt 主线程被阻塞（Signal 不来）

兜底 150ms 轮询 `bridge.latest_snapshot()`。如果 Signal 和轮询同时更新同一个 widget，会有竞态。但 Qt 主线程同一时刻只有一个更新入口，所以**实际不会冲突**——Signal 在主线程执行，轮询 QTimer.timeout 也在主线程执行，二者是串行的。Signal 优先，轮询仅在 Signal 没来时兜底。

判断 Signal 没来：用 `frame_signal_count` 计数器，如果 200ms 内计数没增加，标记 Signal 失效，UI 改纯轮询模式（状态栏提示）。

### 边界 8：cv2 帧格式不匹配

引擎统一 `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)`。FrameSnapshot.frame_rgb 是 bytes，长度 = `w * h * 3`。Qt 端检查 `len(bytes) == w * h * 3`，不匹配就跳过本帧 + 状态栏提示。

### 边界 9：用户切到别的页再切回来

`showEvent` 已经在做（`gesture_page.py:263`），加一行：切回来时重置三色灯为「等待中」，等下一帧 snapshot 进来再更新。避免旧数据误导。

## §4 · 测试

### 4.1 单元测试（写到 `tests/`）

| 测试 | 验证什么 |
|------|---------|
| `test_engine_emits_frame_snapshot_per_loop` | 引擎 `_loop` 每帧都更新 `self._latest_snapshot`，不会跳过 |
| `test_engine_frame_snapshot_has_finger_states` | FrameSnapshot.finger_states 包含 5 指 boolean，且与 `_classify_static` 结果一致（FIST 时 4 指卷曲） |
| `test_bridge_latest_snapshot_returns_engine_snapshot` | Bridge.latest_snapshot() 返回最近一帧（主线程拿值，后台线程安全） |
| `test_bridge_frame_signal_emitted_per_frame` | Bridge 收到 engine 的 frame callback 后，Qt Signal 被 emit，带相同 snapshot |
| `test_status_light_thresholds` | 纯函数：`compute_status_light(snap) → "red"/"yellow"/"green"`（无 Qt 依赖，易测） |
| `test_frame_snapshot_to_qimage_pixels` | FrameSnapshot.frame_rgb 长度 = w*h*3；坐标 (x,y) 处的 RGB 值在 [0,255] |
| `test_bridge_drops_old_snapshot_when_engine_quiet` | 引擎停转后 `latest_snapshot()` 仍返回最后一帧（不是 None），UI 显示「最后画面」 |

### 4.2 Qt UI 验收清单（手测，文档化，不写 pytest）

写在 spec 里作为验收清单：

- [ ] 启动后左栏出现嵌入式预览，~30fps 流畅，镜像正确
- [ ] 不开「显示预览」checkbox 也照样在主窗口内显示（本版本废除 cv2 预览）
- [ ] 三色灯：无手→灰，有手但 NONE→黄，识别→绿
- [ ] 诊断面板：每指状态灯在手势切换时跳变，稳定后静止
- [ ] 诊断面板：手位置坐标 (x, y) 实时更新，移动手能看到坐标变
- [ ] 诊断面板：置信度数字 > 0.6 时是绿色，< 0.6 时变橙
- [ ] 三处同步高亮：做 FIST → 图卡行 + 映射下拉行 + 试用当前识别 三处同时绿
- [ ] 手离开画面 > 1.5s：三色灯转灰，但诊断面板保留「最后位置」
- [ ] 手离开画面 > 3s：诊断面板清空
- [ ] 故意遮挡摄像头：三色灯立刻转红，状态栏「检测不到手」
- [ ] 摄像头被外部占用：启动按钮报错，状态栏红字，预览区显示错误文字
- [ ] 高负载下预览自动降级：状态栏提示「预览降级中：0.5x」
- [ ] 切到别的页再回来：三色灯短暂「等待中」，下一帧立刻恢复
- [ ] 单/双人模式切换：A/B 槽位标签正确（单人只看 A）
- [ ] 教学模式开/关：右上灯变「教学」标识（跟普通状态灯颜色不同，例如蓝色）

### 4.3 不能回归

- `tests/test_laser_emit_semantics.py`（semantics 分类）— 完全无关，但 `_classify_static` 不能改
- `tests/test_gesture_bridge.py`（bridge 派发）— 加 snapshot 不能破坏 teaching_mode / tutorial_done / recent_gestures 现有行为
- `tests/test_bridge_recent_gestures.py` — `recent_gestures()` API 必须保持稳定
- `tests/test_gesture_config_*.py` — config 改动要向后兼容
- 上次 spec 的 8 个单元测试（`test_gesture_config_tutorial_done`、`test_gesture_bridge_teaching_mode`）