# 手势控制重映射 设计

日期：2026-07-04
状态：4 节设计稿已获用户通过；本文件为正式 spec，待用户复核

## 背景

`pc_gesture/semantics.py` 当前**硬编码**手势到 cmd 的映射（FIST→BLACK_SCREEN, THUMBS_UP→FULL_SCREEN 等），用户无法自定义；`ppt_qt/pages/gesture_page.py` 是 355 行的设置面板但没有映射编辑能力。

用户要"从 UI、到功能、到设置"重梳理。功能要好用、设置要方便、预览显示/不显示可选但只要启动就完整可用。

## 决策摘要（已与用户对齐）

| 项 | 决定 |
|---|---|
| 「翻页」语义 | = 下一页的别名（去重） |
| 有效动作数 | 9 个用户动作 + 2 个系统动作 = 11 候选 |
| 手势槽位 | 5 静态（FIST/PALM/POINTING_UP/THUMBS_UP/THUMBS_DOWN）+ 2 挥页（SWIPE_LEFT/SWIPE_RIGHT） = 7 槽 |
| 每槽映射 | 多选一（11 动作 + "无"=禁用） |
| 旧"持续 LASER" | 改离散触发（一次识别=一次 cmd）。"激光持续" 留作未来扩展 |
| 旧"托掌→文本输入" | 本次删除（YAGNI），如需可加 "发文本" 动作项 |
| 双人模式 | 仅 A 槽响应命令；B 槽识别但不派发 |
| 持久化 | 扩 `ppt_pc_client_gesture.json` 加 `bindings` 字段 |
| 视频预览 | 显示/不显示切换不影响功能；调试面板始终显示识别结果 |

## §1 · 动作清单

11 个候选动作（用户在 UI 下拉里看到的）：

| 动作名 (UI) | WS cmd | 底层实现 |
|---|---|---|
| 下一页 | `NEXT_PAGE` | `pyautogui.press("pagedown")` |
| 上一页 | `PREV_PAGE` | `pyautogui.press("pageup")` |
| 从头放映 | `FULL_SCREEN` | `pyautogui.press("f5")` |
| 从当前放映 | `FROM_CURRENT` | `pyautogui.hotkey("shift","f5")` |
| 黑屏 | `BLACK_SCREEN` | `pyautogui.press("b")` |
| 白屏 | `WHITE_SCREEN` | `pyautogui.press("w")` |
| 退出放映 | `EXIT` | `pyautogui.press("esc")` |
| 截屏 | `SCREENSHOT` | `pyautogui.screenshot()` + 回调 |
| 启动PPT | `OPEN_PPT` | `os.startfile(默认路径或临时空白)` |
| PC端最小化 | `PC_WINDOW_MINIMIZE` | `self._win.showMinimized()` |
| PC端恢复 | `PC_WINDOW_RESTORE` | `self._win.showNormal()` |

> 旧版已有 7 个 cmd 路由（PptExecutor + dispatcher 已有），新增 4 个（SCREENSHOT 实际已有，OPEN_PPT/MINIMIZE/RESTORE 已有）—— 本次不增加 dispatcher 路由项，仅在 GestureBridge 内组装 dict。

## §2 · 手势识别层解耦

### 改动 1：`pc_gesture/semantics.py`

**之前**：硬编码 cmd 字面量
```python
if produce_static and gesture == G_FIST:
    events.append({"cmd": "BLACK_SCREEN", "source": f"gesture:{slot}"})
elif gesture == G_PALM:
    events.append({"cmd": "WHITE_SCREEN", ...})
elif gesture == G_THUMBS_UP:
    events.append({"cmd": "FULL_SCREEN", ...})
elif gesture == G_THUMBS_DOWN:
    events.append({"cmd": "EXIT", ...})
```

**之后**：emit 原始 gesture 事件
```python
if produce_static and gesture in (G_FIST, G_PALM, G_POINTING_UP, G_THUMBS_UP, G_THUMBS_DOWN):
    events.append({
        "type": "gesture",
        "gesture": gesture,
        "slot": slot,
        "source": f"gesture:{slot}",
    })
```

`SWIPE_LEFT` / `SWIPE_RIGHT` 已经在 `process()` 里 emit `{"cmd":"NEXT_PAGE"/"PREV_PAGE"}`，改为同样 emit `{"type":"gesture","gesture":"SWIPE_LEFT/RIGHT","slot":slot}`。

> 现有 `pc_gesture.semantics` 测试中假 landmarks 已覆盖 5 静态手势分类；测试不需要改写，只调整断言（如果有针对 cmd 的断言需要改成针对 gesture 字段）。

### 改动 2：`ppt_core/gesture_bridge.py`

新增 `_handle_gesture_event(ev)`：
```python
def _handle_gesture_event(self, ev: dict) -> None:
    if ev.get("type") != "gesture":
        return
    gesture = ev.get("gesture")
    slot = ev.get("slot", "A")
    if slot != "A":       # 双人模式：仅 A 槽响应
        return
    binding = self._cfg.bindings.get(gesture)   # 例 "FIST" -> "BLACK_SCREEN"
    if not binding:
        return
    payload = _action_to_cmd(binding)            # 查表
    self._dispatcher.dispatch(payload)
```

`_action_to_cmd(action: str) -> dict`：纯函数查表（11 动作 → cmd dict）。OPEN_PPT 需要从 settings 读默认路径：

```python
def _action_to_cmd(action: str) -> dict:
    if action == "OPEN_PPT":
        return {"cmd": "OPEN_PPT", "path": ""}   # dispatcher 已支持 path 字段
    if action in ("NEXT_PAGE","PREV_PAGE","FULL_SCREEN","FROM_CURRENT",
                  "BLACK_SCREEN","WHITE_SCREEN","EXIT","SCREENSHOT"):
        return {"cmd": action}
    if action in ("PC_WINDOW_MINIMIZE","PC_WINDOW_RESTORE"):
        return {"cmd": action}
    return {}
```

## §3 · UI / 设置 / 便利能力

### 3.1 GesturePage 整体结构（保留在侧栏"✋ 手势"页）

三段布局：

1. **① 手势映射（7 槽 × 12 项下拉）**
2. **② 实时试用**（识别文字 + 触发历史 + 显示/试用勾选）
3. **③ 控制**（启动/停止/恢复默认/导出/导入 + 状态行）

### 3.2 一键恢复默认

```python
DEFAULT_BINDINGS = {
    "FIST":         "BLACK_SCREEN",
    "PALM":         None,            # 禁用
    "POINTING_UP":  "NEXT_PAGE",
    "THUMBS_UP":    "FULL_SCREEN",   # 从头放映
    "THUMBS_DOWN":  "EXIT",          # 退出放映
    "SWIPE_LEFT":   "PREV_PAGE",
    "SWIPE_RIGHT":  "NEXT_PAGE",
}
```

`None` = 该手势槽禁用。"启动PPT/截屏/最小化/恢复"等次要动作不绑默认手势，需要时用户自己加。

### 3.3 双向反查

GesturePage 顶部加反查框：
```
[查找: 下一页 ▼]   当前绑定: POINTING_UP, SWIPE_RIGHT
```

选动作 → 列出绑定该动作的手势；选"全部" → 列出所有"未绑定"的手势。

### 3.4 实时试用

- 摄像头帧 + 21 关键点骨架 + slot A/B 标签
- 当前识别手势名（大字，珊瑚色）
- 触发历史（最近 5 条：`14:32:01 握拳 → 黑屏`）
- 「试用」勾选框：勾上后立即派发真实 cmd；不勾时仅记录识别（用于安静调阈值）

### 3.5 导入/导出

- 导出：把 `cfg.raw` 全部字段写到 JSON（用户选文件位置）
- 导入：从 JSON 读，覆盖当前 cfg
- 与"恢复默认"并排

### 3.6 视频预览策略（用户硬性要求）

| 状态 | 摄像头 | 识别 | 命令 | 试用面板 | OpenCV 窗 |
|---|---|---|---|---|---|
| 启动，显示 | 读 | 是 | 派 | 显示 | 显示 |
| 启动，不显示 | 读 | 是 | 派 | 显示 | 不显示 |
| 停止 | 不读 | 否 | 否 | 不显示 | 不显示 |

切换显示/不显示无需重启手势（勾选框即时生效）。

## §4 · 测试 / 错误处理 / 未做事项

### 4.1 测试

| 层 | 覆盖 | 方法 |
|---|---|---|
| action_to_cmd 查表 | 11 动作名 → cmd dict 映射正确 | pytest 纯函数 |
| GestureBridge 路由 | raw gesture 事件 → 查 binding → 派 cmd；缺 binding 跳过；非 A 槽跳过 | monkeypatch 替换 GestureEngine 与 Dispatcher |
| binding 持久化 | save / load / 恢复默认 / 导入 / 导出 / 与 sensitivity 共存 | pytest 用 tempfile |
| semantics 改动 | 现有 5+2 手势分类仍正确；emit 字段为 type/gesture/slot | 沿用现有假 landmarks 测试 |
| GesturePage UI | 下拉 12 项；试用模式勾选；导出按钮触达文件 API | 手工冒烟（offscreen QPA） |

### 4.2 错误处理

- **binding 加载失败**（文件损坏 / 字段缺失）→ 用 DEFAULT_BINDINGS 兜底；不抛
- **动作名无效**（用户编辑 JSON 写入）→ save 校验降级为 None；load 丢弃
- **摄像头启动失败** → 状态栏弹"无法打开摄像头"，手势不启动
- **mediapipe 缺失** → GestureBridge.start() 返回错误字符串；UI 弹 pip 提示
- **试用中 cmd 派发失败** → 历史区显示"派发失败: ..."，红色字
- **导入 JSON 损坏** → 弹 QMessageBox，配置不变

### 4.3 持久化格式

`ppt_pc_client_gesture.json` 扩字段：

```json
{
  "preview_only": false,
  "mirror": true,
  "operator_mode": "single",
  "dual_roles_swapped": false,
  "enabled": false,
  "camera_index": 0,
  "show_preview_window": true,
  "sensitivity": { ... },
  "bindings": {
    "FIST":         "BLACK_SCREEN",
    "PALM":         null,
    "POINTING_UP":  "NEXT_PAGE",
    "THUMBS_UP":    "FULL_SCREEN",
    "THUMBS_DOWN":  "EXIT",
    "SWIPE_LEFT":   "PREV_PAGE",
    "SWIPE_RIGHT":  "NEXT_PAGE"
  }
}
```

旧字段保留；缺失 `bindings` 时全部填 `None`（全部禁用，等用户显式启用）。

### 4.4 未做事项（YAGNI）

- 「激光 (持续)」动作项：旧版 POINTING_UP 持续派 LASER；本次改离散。需要时加 1 个动作项即可
- 「托掌 → 文本输入」：本次删除。需要时加 1 个动作项
- 双人手 B 槽独立控制：本次仅 A 槽响应
- 云端同步 / 多设备配置共享：导入/导出走本地文件
- 录制 / 回放手势：调试只到"实时识别 + 历史"
- 同一动作被多手势绑定：支持（不冲突），但每手势只能绑 1 个

### 4.5 文件改动清单

| 状态 | 文件 | 改动 |
|---|---|---|
| 改 | `pc_gesture/semantics.py` | ~60 行；删除 cmd 字面量，emit 原始 gesture 事件 |
| 改 | `pc_gesture/config.py` | +20 行；加 DEFAULT_BINDINGS / load_save bindings / set/get_binding / reset_bindings / import_export |
| 改 | `ppt_core/gesture_bridge.py` | +30 行；_handle_gesture_event 路由；订阅 cfg.bindings |
| 改 | `ppt_qt/pages/gesture_page.py` | ~250 行重写；映射 + 反查 + 试用 + 导入导出 |
| 改 | `tests/test_gesture_bridge.py` | +5 个测试 |
| 新 | `tests/test_gesture_config.py` | 5 个测试 |
| 不动 | `pc_gesture/engine.py`（低层识别 OK） | — |
| 不动 | `pc_gesture/__init__.py` | — |

## 后续（写完 spec 后）

→ 调用 `superpowers:writing-plans` 把本 spec 转写为可执行的实施计划（带文件级任务列表）。