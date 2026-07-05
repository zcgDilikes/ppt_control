# 手势控制 教学功能 设计

日期：2026-07-05
状态：4 节设计稿已获用户通过；本文件为正式 spec，待用户复核

## 背景

`ppt_qt/pages/gesture_page.py` 目前能让用户看到实时识别结果（试用面板）和改绑定，但没有告诉用户**每个手势长什么样**、**触发什么**、**首次启动该怎么用**。用户反馈"骨架能识别，但具体事件有没有也不知道 / 应该一直不能用 / 或者我不会用"——可识别 ≠ 可用，缺一层引导。

目标：加一个教学系统，**简单、有效、直观**地把"这个手势长什么样 → 会触发什么 → 实际做一次确认能做对"完整跑通。

## 决策摘要（已与用户对齐）

| 项 | 决定 |
|---|---|
| 教学形态 | 四合一：静态图卡 + 交互向导 + 预览实况高亮 + 教学模式开关 |
| 向导触发 | 首次进入「手势」页且引擎已启动过 → 自动弹；用户点「重看教学」可手动重走 |
| 教学内容 | 默认 7 手势全教（FIST/PALM/POINTING_UP/THUMBS_UP/THUMBS_DOWN/SWIPE_LEFT/SWIPE_RIGHT） |
| 单步超时 | 15 秒未识别 → 自动跳下一步（标 SKIPPED） |
| 「已教学过」持久化 | `ppt_pc_client_gesture.json` 加 `tutorial_done: bool`，默认 False |
| 教学模式开关位置 | 「手势」页顶部 checkbox，随时切换；不持久化（重启默认 False） |
| 教学模式语义 | 只识别不派发；试用面板/向导仍可见 |
| 向导与教学模式耦合 | 向导开始时自动开教学模式，向导结束恢复原值 |

## §1 · 架构

四个层都寄生在 `GesturePage` 上，互不抢 UI 焦点：

```
GesturePage
├── (top) 顶部开关： ▢ 教学模式（只识别不派发）
├── ① 手势示图卡            ← 静态参考，常驻
├── ② 实时试用面板          ← 现有 + 新增：每次识别把图卡对应行高亮
├── ③ 手势映射              ← 现有不动
└── [重看教学] 按钮          ← 手动触发向导
        ↓ 点击
GestureTutorialDialog (模态 QDialog)
├── 7 步：FIST / PALM / POINTING_UP / THUMBS_UP / THUMBS_DOWN / SWIPE_LEFT / SWIPE_RIGHT
├── 每步：大图卡 + 「请做 XXX」 + 倒计时进度条
├── 15 秒未识别 → 自动跳下一步（标 SKIPPED）
└─ 完成 / 全跳过 → 写 tutorial_done=True → 关闭

GestureBridge（扩展）
├── teaching_mode: bool          ← 由顶部开关控制
├── _on_gesture_event            ← 教学模式下跳过 dispatcher.dispatch
└── record_recognized_gesture    ← 教学模式仍写入（让试用面板/向导能看见）

GestureConfig（扩展 raw）
└── tutorial_done: bool          ← 持久化"已教学过"
```

文件布局：

| 文件 | 改动 |
|---|---|
| `ppt_qt/pages/gesture_page.py` | 加图卡 + 顶开关 + 「重看教学」按钮 |
| `ppt_qt/pages/gesture_tutorial_dialog.py` | 新文件，模态向导 |
| `ppt_core/gesture_bridge.py` | 加 `teaching_mode` 状态、`set_teaching_mode()` |
| `pc_gesture/config.py` | `DEFAULT_GESTURE_CONFIG` 加 `tutorial_done: False` |

## §2 · 数据流

### 2.1 启动 / 首次进入流程

```
App boot
  └─ load GestureConfig（含 tutorial_done）
  └─ GestureBridge.__init__ (teaching_mode=False 默认)
  └─ 用户切换到「手势」页
       └─ GesturePage._maybe_show_tutorial()
            ├─ if not cfg.tutorial_done AND bridge.engine 已启动过:
            │     └─ 自动弹 GestureTutorialDialog（模态）
            │           └─ 完成后 cfg.tutorial_done = True; bridge.save()
            └─ else: 静默
```

**为什么「首次进入 + 引擎启动过」才弹**：预览窗口要开着才能教学，否则用户对着黑屏做手势，识别不到会更困惑。

### 2.2 向导单步流程

```
GestureTutorialDialog.step = i (0..6)
  显示 gesture_i 的卡片（emoji + 中文名 + 触发动作）
  ├─ bridge.recent_gestures() 轮询（150ms）
  │     └─ 识别到 gesture_i → 标 DONE，1.5s 后 auto-advance
  ├─ 15s 倒计时（QTimer）耗尽 → 标 SKIPPED，立刻 next
  └─ 用户点「跳过」→ SKIPPED，立刻 next

  step 推进：
    ├─ 7 步全 DONE → status "全部完成！" → 0.8s 后关闭
    ├─ 任意 SKIPPED → 关闭时 status "已跳过 N 个，可点「重看教学」再来"
    └─ 用户点「结束」 → 立即关闭
```

### 2.3 实时试用面板（现有 + 增强）

`_poll_bridge_gestures` 已经在 150ms 轮询 `bridge.recent_gestures()`。新增：

- 收到新识别 → 找出图卡里对应行，设 `setStyleSheet("background:rgba(34,197,94,0.4);")`
- 2 秒后还原（`QTimer.singleShot(2000, lambda: clear())`）
- 同手势重复识别 → clear + 重新设绿色 + 重置 2s 定时器

### 2.4 教学模式开关

```
GesturePage 顶部 checkbox toggled → bridge.set_teaching_mode(bool)
  └─ GestureBridge.teaching_mode = bool

bridge._on_gesture_event(ev, src):
  if ev.type == "gesture":
    if self.teaching_mode:
      # 仍写环形缓冲（试用面板/向导需要看见），但跳过 dispatcher
      self._record_recognized_gesture(gesture, action, ev, src)
      return
    self._record_recognized_gesture(...)         # 现有
    if action: dispatch(...)                      # 现有
```

**关键点**：教学模式**只压住 dispatcher**，不压住识别，所以试用面板和向导都能正常看到结果。这就是"只识别不派发"的实现。

## §3 · 错误与边界

| # | 边界 | 处理 |
|---|------|------|
| 1 | 引擎未启动时进入手势页 | 不弹向导；图卡常驻；用户必须先点「启动手势」才能进教学 |
| 2 | 教学进行中用户点「停止」 | 向导对话框不依赖 engine 生命周期；后续步骤识别不到东西，15s 后全部 SKIPPED 正常关闭 |
| 3 | 教学进行中用户改绑定 | 每步显示的动作标签随 `cfg.get_binding(g)` 现读现显示，立刻反映 |
| 4 | config 损坏 / 缺 `tutorial_done` | `_merge_defaults()` 补默认值；旧配置文件向后兼容 |
| 5 | 用户中途关闭对话框 / 强杀 | `tutorial_done` 只在完整跑完（或全部跳过）才写，下次进入手势页会再弹 |
| 6 | Qt 线程安全 | 所有轮询/高亮/倒计时均在 Qt 主线程（`QTimer` 默认主线程）；`deque.append()` 线程安全；`recent_gestures()` 返回新 list |
| 7 | 试用面板高亮叠加 | 每次新识别都 `clearStyleSheet()` + 重新设绿色 + 重置 2s 定时器 |
| 8 | 教学模式 + 教学向导 | 向导开始时若教学模式为关，自动开；向导结束恢复原值。避免向导过程中误派发 BLACK_SCREEN |

## §4 · 测试

### 4.1 单元测试（写到 `tests/`）

| 测试 | 验证什么 |
|------|---------|
| `test_teaching_mode_blocks_dispatch` | 教学模式下识别手势，**不**调 dispatcher；但 `bridge.recent_gestures()` 里有 FIST |
| `test_teaching_mode_allows_dispatch_when_off` | 关闭教学模式时，正常派发 |
| `test_tutorial_done_persists_in_default_config` | `tutorial_done` 默认 False；缺字段不报错（`_merge_defaults` 兜底） |
| `test_tutorial_done_round_trips` | 写入 → 重读，值保留 |
| `test_record_recognized_gesture_in_teaching_mode` | 教学模式下 `_record_recognized_gesture` 仍被调用 |
| `test_teaching_mode_does_not_swallow_unbound_gestures` | 教学模式下未绑定手势也不派发（本来就没绑定可派发） |

### 4.2 Qt UI 验收清单（手测，不写 pytest）

- [ ] 首次启动引擎后切到「手势」页，自动弹出向导
- [ ] 向导 7 步依次显示，识别到 FIST 后自动跳下一步
- [ ] 故意做出非目标手势（比如目标是 FIST，做 POINTING_UP），15 秒后自动跳过
- [ ] 7 步走完后 `tutorial_done=True`，重新进入手势页不弹向导
- [ ] 「重看教学」按钮可触发向导
- [ ] 顶部开关打开后，做 FIST → 试用面板出现「握拳」，PPT 没黑屏
- [ ] 关闭顶部开关后，做 FIST → 试用面板出现「握拳」，PPT 黑屏
- [ ] 向导进行中开/关引擎，对话框不崩
- [ ] 向导进行中修改 FIST 绑定，下一步卡片「动作」标签立刻反映
- [ ] 修改 PPT 绑定 → 重启 → 顶部开关默认 False，`tutorial_done` 仍是 True

### 4.3 不能回归

- `tests/test_gesture_bridge.py`（bridge 派发逻辑）— 加 teaching_mode 不能破坏现有用例
- `tests/test_laser_emit_semantics.py`（semantics 分类）— 完全无关
- `tests/test_bridge_recent_gestures.py`（`recent_gestures()` API）— 必须保持接口稳定，因为向导和试用面板都靠它