# 手势集重新设计 — 无歧义 7 手势

日期：2026-07-06
状态：4 节设计稿已获用户通过；本文件为正式 spec，待用户复核

## 背景

`pc_gesture/semantics.py:_classify_static` 当前 7 手势（FIST/PALM/POINTING_UP/THUMBS_UP/THUMBS_DOWN/SWIPE_LEFT/SWIPE_RIGHT）存在歧义：

- **PALM ↔ SWIPE_LEFT/RIGHT**：SWIPE 在 `_update_swipe` 里是 "PALM + 手腕 x 速度"，静态姿势完全一样，仅靠运动区分。
- **FIST ↔ THUMBS_UP/DOWN**：4 指卷曲状态一样，仅靠 thumb tip 与 wrist 的 y 差 ±0.08~0.10 区分，容易误判。
- **POINTING_UP ↔ V 字**：要求"仅食指伸"，但用户自然做 V 字时经常食指+中指一起伸，被判 NONE。

PPT 控制要求每个手势都不能产生歧义和错误。本 spec 用一组**纯静态**手势替换，每对手势在手指状态或空间关系上至少差 2 个维度，误识别概率极低。

## 决策摘要（已与用户对齐）

| 项 | 决定 |
|---|---|
| 手势数量 | 7（保留同样数量） |
| 选集 | 方案 A — 7 个静态手势（OK / 剪刀 / 拳头 / 张掌 / 三指 / L / 食指） |
| 实施策略 | 方案 B — 就地替换 + 智能默认（DEFAULT_BINDINGS 重写，旧 keys 自然失效） |
| enum 值 | 保留机器友好字符串（FIST/PALM/POINTING_UP/OK/SCISSORS/THREE_FINGERS/L_SIGN），UI 通过 _GESTURE_META 映射到中文 + emoji |
| 旧配置兼容 | 旧 bindings（`FIST: BLACK_SCREEN` 等）自动失效，UI 显示「未绑定」，状态栏提示重新绑定 |
| tutorial_done | 检测到旧 keys 时自动重置为 False，提示「手势集已更新，请重看教学」 |

## §1 · 新手势集与分类规则

### 7 手势（按优先级排列）

| # | 中文名 | enum | 手指状态 | 默认动作 |
|---|--------|------|---------|---------|
| 1 | OK | `OK` | T=OPPOSED, M+R+P 都 EXT，拇指与食指尖接触 | 下一页 |
| 2 | L 手势 | `L_SIGN` | T=EXT(横向), I=EXT, M=R=P=CURL，拇-食指远 | 从头放映 |
| 3 | 三指 | `THREE_FINGERS` | T=EXT, I=EXT, M=EXT, R=P=CURL | 白屏 |
| 4 | 食指 | `POINTING_UP` | T=CURL, I=EXT, M=R=P=CURL | 激光 |
| 5 | 剪刀手 | `SCISSORS` | T=CURL, I=EXT, M=EXT, R=P=CURL | 上一页 |
| 6 | 拳头 | `FIST` | T=CURL, I=M=R=P=CURL | 黑屏 |
| 7 | 张掌 | `PALM` | T=EXT, I=M=R=P=EXT | 退出放映 |

### 关键距离阈值

- **OPPOSED 判定**（拇指-食指尖接触）：`dist(thumb_tip[4], index_tip[8]) < 0.08 * hand_size`
- **EXT 判定（拇指）**：`dist(thumb_tip[4], index_mcp[5]) > 0.18 * hand_size`
- **EXT 判定（其他指）**：`tip.y < pip.y - 0.015`（OK 时放宽到 `-0.015`；其它手势 `-0.025`）
- **CURL 判定**：`tip.y > pip.y + 0.005`（沿用现有）

### 优先级消除歧义

每个静态 pose 应该**只命中一条规则**。如果某个 pose 同时满足多条（比如 OK 与三指都有 3 指伸），优先级把空间关系最强的路径排在最前（OK 的 thumb-index 接触 > L 的横向 > 三指的拇-食分开 > 单指）。

### 与旧 7 手的映射

| 旧 | 新 | 备注 |
|----|----|------|
| `FIST` | `FIST`（拳头） | enum 保留，只改 UI 显示 |
| `PALM` | `PALM`（张掌） | 同上 |
| `POINTING_UP` | `POINTING_UP`（食指） | 同上 |
| `THUMBS_UP` | (丢弃) | 旧绑定 → None |
| `THUMBS_DOWN` | (丢弃) | 旧绑定 → None |
| `SWIPE_LEFT` | (丢弃) | — |
| `SWIPE_RIGHT` | (丢弃) | — |

## §2 · 文件改动与数据流

### 改动文件

| 文件 | 改动 |
|------|------|
| `pc_gesture/config.py` | `GESTURES` tuple 整个换（7 新 enum）；`DEFAULT_BINDINGS` 整个换；常量同步 |
| `pc_gesture/semantics.py` | `_classify_static` 重写（按 §1 优先级链）；`G_*` 类常量加 OK/SCISSORS/THREE_FINGERS/L_SIGN；删除 SWIPE 类常量 |
| `pc_gesture/engine.py` | 无改动（语义层变了它自动跟着变） |
| `ppt_qt/pages/gesture_page.py` | `_GESTURE_META` dict 改（7 个新 emoji + 中文名）；删除 SWIPE 元数据 |
| `ppt_qt/pages/gesture_tutorial_dialog.py` | `_TUTORIAL_META` 改（7 新手势展示元数据） |
| `tests/test_gesture_classification.py` | 新增：14-16 个分类器测试（含互斥测试） |
| `tests/test_gesture_config.py` | 扩展：`GESTURES` 长度 == 7，包含全部新名 |
| `tests/test_gesture_bridge.py` | 检查现有手势字符串，改 FIST→FIST 仍兼容 |
| `tests/test_bridge_recent_gestures.py` | 检查旧 gesture 名引用 |

### 配置文件回退策略

- 用户的 `bindings: {"FIST": "BLACK_SCREEN", ...}` 在新版变成"野键"
- 行为：`cfg.get_binding("FIST")` 返回 None（FIST 不在新 GESTURES — **等等，FIST 仍在新 GESTURES**，所以会查得到；但 FIST 的默认绑定从 BLACK_SCREEN 保留 BLACK_SCREEN）
- 实际效果：
  - `FIST` / `PALM` / `POINTING_UP` 三个保留的 enum：用户旧绑定仍生效（因为 enum 字符串不变）
  - `THUMBS_UP` / `THUMBS_DOWN` / `SWIPE_LEFT` / `SWIPE_RIGHT` 四个丢弃的 enum：`cfg.get_binding` 不会查它们，因为新 GESTURES 不含
- **首次启动时**：检测到用户的旧 `bindings` 里有 `THUMBS_UP` 等旧键时，状态栏显示「检测到旧版本配置，请重新绑定」+ 自动 `tutorial_done=False`

### 数据流（无变化）

手势分类 → engine 缓存到 `_latest_snapshot` → bridge Signal → UI 渲染。**数据驱动**，手势名变了不影响。

## §3 · 错误与边界

按发生概率从高到低：

### 边界 1：用户做 OK 时后三指没完全伸直

真人做 OK 时，后三指往往微卷（肌肉紧张）。

**处理**：`EXT` 判定放宽到 `tip.y < pip.y - 0.015`（从 0.025 降到 0.015）。同时新增**软阈值**：3 指里只要 2 指 EXT，1 指 CURL 也允许通过 OK 检测。**这是唯一放宽阈值的地方**，其它手势严守规则。

### 边界 2：拇指 OP 接触距离阈值（OK vs L）

`0.06 * hand_size` 太严漏，`0.10 * hand_size` 太松误把 L 当 OK。

**处理**：`0.08 * hand_size`（略放宽）。配合规则 2（L 手势的 thumb-index 远），只要 L 的中/无名/小指卷着，L 不会进 OK 路径。

### 边界 3：「三指」与 OK 视觉接近

三指：拇+食+中伸。OK：拇+食指圈 + 中+无名+小伸。

如果用户做 OK 时三指没全伸，**视觉上**接近"三指"。但分类器看到 thumb-index 接触（OK 路径），所以判定 OK。**这正是设计想要的**：空间距离 > 手指计数。

### 边界 4：用户做食指时手小/远

距离镜头太远时，食指可能看起来微卷。

**处理**：沿用现有的 `min_hand_detection_confidence=0.5` + UI 端的"手位置 (x, y) 实时显示"。无需额外处理。

### 边界 5：用户手部动作很快（A→B 切换）

rising-edge 机制已用——只有从 NONE 切换到新 gesture 才触发。**800ms 冷却**（沿用 `gesture_cooldown_ms`）防止快速重复触发。

### 边界 6：用户已经存在旧 bindings 配置

启动时旧 `bindings: {THUMBS_UP: ...}` 会被 `_merge_defaults` 透传到 `cfg.raw["bindings"]`，但 `cfg.get_binding("THUMBS_UP")` 永远返回 None（新 GESTURES 不含）。

**处理**：启动时检测 `cfg.raw["bindings"]` 是否含旧 keys（含任何一个 `THUMBS_UP/THUMBS_DOWN/SWIPE_LEFT/SWIPE_RIGHT` 即认为旧配置），则：
1. 删除这些 keys（写回 cfg.raw）
2. `cfg.tutorial_done = False`
3. 状态栏显示「手势集已更新，请重新绑定 + 重看教学」
4. 下次进手势页自动弹 tutorial

### 边界 7：MediaPipe 丢手/低置信度

沿用现有的 FrameSnapshot 流程——`compute_status_light` 看 confidence，UI 三色灯变黄。

### 边界 8：双人协作模式两个手不同手势

当前语义层只看 slot A / A 和 B 分别触发。新版依然沿用——只是动作名变了。

### 边界 9：用户已经跑过旧 tutorial（tutorial_done=true）

旧 tutorial 教的是旧手势（握拳/张掌/食指/竖拇/拇下/挥左/挥右）。

**处理**：通过边界 #6 的检测自动重置。

## §4 · 测试

### 4.1 单元测试（写到 `tests/test_gesture_classification.py`）

| 测试 | 验证什么 |
|------|---------|
| `test_classify_ok_*` | 拇指+食指尖接触 + 中/无名/小指伸 → OK |
| `test_classify_scissors_*` | 拇卷 + 食/中伸 + 无名/小卷 → SCISSORS |
| `test_classify_fist_*` | 全 5 卷 → FIST |
| `test_classify_palm_*` | 全 5 伸 → PALM |
| `test_classify_three_fingers_*` | 拇+食+中伸 + 无名/小卷 → THREE_FINGERS |
| `test_classify_l_sign_*` | 拇+食指伸（分开）+ 中/无名/小卷 → L_SIGN |
| `test_classify_pointing_*` | 仅食指伸 → POINTING_UP |
| **互斥测试（关键）** | |
| `test_ok_not_misread_as_three_fingers` | OK pose 不会命中 THREE_FINGERS |
| `test_l_sign_not_misread_as_ok` | L pose（thumb-index 远）不会命中 OK |
| `test_scissors_not_misread_as_three_fingers` | scissors（拇卷）不会命中 THREE_FINGERS（拇伸） |
| `test_pointing_not_misread_as_scissors` | 单指不会命中 scissors（双指） |
| `test_partial_curl_still_ok` | 边界 #1：OK 时三指微卷（2 of 3 EXT）仍判 OK |

总计 14-16 个测试。

### 4.2 集成测试（扩展现有）

- `test_gesture_config.py`：测试 `GESTURES` tuple 长度 == 7，且包含全部新名。
- `test_gesture_bridge.py` / `test_bridge_recent_gestures.py`：现有用例用了 `FIST` / `POINTING_UP` 等 enum 值——这些 enum 值在新 GESTURES 中保留，所以现有测试无需改动。
- `test_gesture_bridge_teaching_mode.py`：枚举手势的字符串可以保留/更新。
- `test_gesture_bridge_frame_signal.py`：无直接手势名依赖。
- `test_gesture_config_tutorial_done.py`：逻辑层独立。
- `test_gesture_config_low_confidence.py`：逻辑层独立。
- `test_laser_emit_semantics.py`：检查所有手势字符串引用。
- `test_frame_snapshot.py`：沿用。

### 4.3 不能回归

- 现有 89 个测试必须保持绿
- 新增 ~14-16 个手势分类测试，总数约 103-105

### 4.4 Qt UI 验收清单（手测，文档化）

写在 spec 里作为验收清单：

- [ ] 启动后 7 个手势图卡都是新名字（OK/剪刀/拳头/张掌/三指/L/食指）
- [ ] 做 OK → 翻下一页；做剪刀 → 翻上一页
- [ ] 做 OK 时后三指微卷仍正确识别（边界 #1）
- [ ] 做 L 手势时不会被误判为 OK（边界 #2）
- [ ] 做剪刀时不会被误判为三指（因为拇状态不同）
- [ ] 做食指时不会被误判为剪刀（因为中指状态不同）
- [ ] 教学对话框显示新 7 手势的图标 + 中文名
- [ ] 旧配置用户首次启动时状态栏提示「手势集已更新，请重新绑定」
- [ ] 旧配置用户首次进入手势页时自动弹教学向导