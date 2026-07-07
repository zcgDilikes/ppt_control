# 9-Event 手势控制设计 spec

**Date:** 2026-07-07
**Status:** 设计已批,待 writing-plans
**Author:** brainstorming session

## 1. 背景

当前 `pc_gesture` 用 7 个静态手势(OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM)。OK 手势要求"拇-食指尖接触"且"其他 ≥ 2 指伸(relaxed 阈值)",实战中:
- 自然 OK 经常其他手指微弯,relaxed 阈值仍过严,误判 NONE
- 用户做 OK 时拇指伸出方向有偏差,接触判定阈值过死

新设计:9 个事件改为基于"拇指尖到目标指尖的距离"这个**单一定量信号**,阈值用归一化距离(对手掌参考长度)。每帧只出一个最接近指尖的事件,互斥无冲突。同时加一个双手十指相扣的特殊事件(用于触发不常用的 action)。

## 2. 目标

- 单手 8 个事件(4 指尖触碰 × 左/右手),每帧每手最多出 1 个事件
- 双手 1 个 interlock 事件,需两手都可见且十指交叉近距
- 旧 7 个 gesture 继续保留,UI 总 16 行
- 191 个现有测试不破

## 3. 事件定义

| Enum | 中文名 | 触发条件 | 模式 |
|---|---|---|---|
| `L_HAND_INDEX` | 左手拇指触食指 | slot A 拇指尖到 INDEX_TIP 归一化距离 < `tip_touch_ratio` | dual |
| `L_HAND_MIDDLE` | 左手拇指触中指 | slot A 拇指尖到 MIDDLE_TIP 距离 < 阈值 | dual |
| `L_HAND_RING` | 左手拇指触无名指 | slot A 拇指尖到 RING_TIP 距离 < 阈值 | dual |
| `L_HAND_PINKY` | 左手拇指触小拇指 | slot A 拇指尖到 PINKY_TIP 距离 < 阈值 | dual |
| `R_HAND_INDEX` | 右手拇指触食指 | slot B 拇指尖到 INDEX_TIP 距离 < 阈值 | dual |
| `R_HAND_MIDDLE` | 右手拇指触中指 | slot B 拇指尖到 MIDDLE_TIP 距离 < 阈值 | dual |
| `R_HAND_RING` | 右手拇指触无名指 | slot B 拇指尖到 RING_TIP 距离 < 阈值 | dual |
| `R_HAND_PINKY` | 右手拇指触小拇指 | slot B 拇指尖到 PINKY_TIP 距离 < 阈值 | dual |
| `HANDS_INTERLOCK` | 双手十指相扣 | slot A + slot B 都做某 tip_touch,两 wrist 距离 < `interlock_max_wrist_dist`,10 指尖两两均值距离 < `interlock_max_tip_dist`,持续 ≥ `interlock_min_dwell_s` 秒 | dual |

(旧 7 gesture 保留,行为不变)

## 4. 架构

```
每帧:
  MediaPipe HandLandmarker → hand_landmarks, handedness
           ↓
  GestureSemantics.process(landmarks, handedness)
    ├─ _classify_static()          → 7 旧 gesture(rising-edge)
    └─ _detect_tip_touches(per slot) + _detect_interlock(cross slot)
                                     → 9 新事件(rising-edge)
           ↓
  返回 events list,每条 dict:
    { type: "gesture" | "tip_touch" | "interlock" | "gesture_end",
      gesture: <enum>,
      slot: "A" | "B" | "BOTH",
      ts, ts_ms, source }
           ↓
  GestureEngine._loop → dispatch_fn(event)
           ↓
  GestureBridge._on_gesture_event(event)
    ├─ type == "gesture"   → self._cfg.get_binding(gesture)         → _action_to_cmd
    ├─ type == "tip_touch" → self._cfg.get_tip_binding(gesture)     → _action_to_cmd
    ├─ type == "interlock" → self._cfg.get_tip_binding("HANDS_INTERLOCK") → _action_to_cmd
    └─ type == "gesture_end" → 仅做记录,不入 dispatch
           ↓
  CommandDispatcher.dispatch(payload)
```

## 5. 算法

### 5.1 单手指尖触碰(per slot)

```python
def _detect_tip_touches(self, lm, slot: str) -> str:
    """返回 8 个单手事件之一,或 'NONE'"""
    if not lm or len(lm) < 21:
        return "NONE"
    size = self._hand_size(lm)  # 现有方法,夹紧 [0.05, 0.5]
    thumb_tip = lm[THUMB_TIP]
    threshold = float(self.cfg.sensitivity.get("tip_touch_ratio", 0.55))
    prefix = "L_HAND" if slot == "A" else "R_HAND"
    candidates = [
        (f"{prefix}_INDEX",  lm[INDEX_TIP]),
        (f"{prefix}_MIDDLE", lm[MIDDLE_TIP]),
        (f"{prefix}_RING",   lm[RING_TIP]),
        (f"{prefix}_PINKY",  lm[PINKY_TIP]),
    ]
    dists = [
        (name, _dist(thumb_tip.x, thumb_tip.y, tip.x, tip.y) / size)
        for name, tip in candidates
    ]
    name, d = min(dists, key=lambda x: x[1])
    if d < threshold:
        return name
    return "NONE"
```

**关键点**:
- 单标签(每帧每手至多 1 个事件,出最接近的)
- 距离归一化用 `_hand_size()`,与 OK 路径一致
- 默认 `tip_touch_ratio=0.55` 比 OK 的 0.08 宽松,实测"指尖接近"比"指尖接触"容易识别

### 5.2 双手十指相扣(cross slot)

```python
def _detect_interlock(self, lm_a, lm_b, now: float) -> bool:
    if not lm_a or not lm_b or len(lm_a) < 21 or len(lm_b) < 21:
        return False
    wrist_d = _dist(lm_a[WRIST], lm_b[WRIST])
    if wrist_d > float(self.cfg.sensitivity.get("interlock_max_wrist_dist", 0.20)):
        return False
    tips_a = [lm_a[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
    tips_b = [lm_b[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
    size = self._hand_size(lm_a)  # 归一化用主手 size
    cross = [
        _dist(a.x, a.y, b.x, b.y) / size
        for a in tips_a for b in tips_b
    ]
    if sum(cross) / len(cross) > float(self.cfg.sensitivity.get("interlock_max_tip_dist", 0.40)):
        return False
    # dwell: 持续 min_dwell_s 才确认
    dwell = float(self.cfg.sensitivity.get("interlock_min_dwell_s", 0.3))
    if not hasattr(self, "_interlock_start") or self._interlock_start is None:
        self._interlock_start = now
        return False
    if now - self._interlock_start < dwell:
        return False
    return True
```

**3 个条件**(任一不满足 → False):
1. 两 wrist 归一化距离 < 0.20
2. 10 指尖两两距离均值 < 0.40(归一化)
3. 上述条件持续 ≥ 0.3s(dwell 防误触)

## 6. 状态机集成

在 `GestureSemantics._process_one_hand` 内,**step 1 (laser) 之后、step 2 (静态 gesture) 之后**,新增 **step 4 (tip_touch 9 事件)**:

```python
# step 4: 9 事件(独立通道)
if operator_mode == "dual":
    tip = self._detect_tip_touches(lm, slot)
    if tip and tip != st.last_tip_gesture:
        cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))
        if now >= st.tip_cooldown_until and cooldown_ms > 0:
            events.append({
                "event_class": "tip_touch",
                "type": "tip_touch",
                "gesture": tip,
                "slot": slot,
                "ts": ts, "ts_ms": ts_ms,
                "source": f"gesture:{slot}",
            })
            st.tip_cooldown_until = now + cooldown_ms / 1000.0
    st.last_tip_gesture = tip
```

`HandState` 新增:
- `last_tip_gesture: str`  — 单手最近 tip_touch 事件
- `tip_cooldown_until: float`  — 独立于 `static_cooldown_until`,不共享冷却
- `last_interlock_gesture: str`  — slot A 上的 interlock 标记(单一,因 interlock 是 cross-slot 共享)
- `interlock_cooldown_until: float`  — interlock 独立冷却

`GestureSemantics` 实例属性新增:
- `_interlock_start: Optional[float]`  — interlock dwell 计时起点(两条件首次同时满足时设置)
- `self._interlock_state: str`  — 上一帧 interlock 检测结果(NONE / HANDS_INTERLOCK)

**冷却独立**:9 事件不消耗 7 旧 gesture 的冷却槽,反之亦然(用户连点 OK + 拇指触食指,两个事件都能触发)。

**hand-leave 清理**:`process()` 末尾的 cleanup 路径增加:
```python
st.last_tip_gesture = "NONE"
st.tip_cooldown_until = 0.0
```

### 6.1 双手 interlock 检测

在 `GestureSemantics.process` 末尾、配对更新之后,需要先收集每个 slot 的 landmarks:

```python
# process() 内:
slot_lms: Dict[str, list] = {}  # 收集 per-slot 关键点
for idx, lm_list in enumerate(hand_landmarks_list):
    ...
    slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
    slot_lms[slot] = lm_list
    events.extend(self._process_one_hand(lm_list, slot, st, sens, now))

# 配对更新之后:
if operator_mode == "dual":
    lm_a = slot_lms.get("A")
    lm_b = slot_lms.get("B")
    if self._detect_interlock(lm_a, lm_b, now):
        st_inter = self._slots["A"]
        if (self._interlock_state != "HANDS_INTERLOCK"
            and now >= st_inter.interlock_cooldown_until
            and cooldown_ms > 0):
            events.append({
                "event_class": "interlock",
                "type": "interlock",
                "gesture": "HANDS_INTERLOCK",
                "slot": "BOTH",
                "ts": ts, "ts_ms": ts_ms,
                "source": "gesture:interlock",
            })
            st_inter.interlock_cooldown_until = now + cooldown_ms / 1000.0
        self._interlock_state = "HANDS_INTERLOCK"
    else:
        # 拆掉 dwell
        self._interlock_start = None
        self._interlock_state = "NONE"
```

## 7. 配置 schema

### 7.1 `pc_gesture/config.py`

```python
TIP_GESTURES = (
    "L_HAND_INDEX", "L_HAND_MIDDLE", "L_HAND_RING", "L_HAND_PINKY",
    "R_HAND_INDEX", "R_HAND_MIDDLE", "R_HAND_RING", "R_HAND_PINKY",
    "HANDS_INTERLOCK",
)

DEFAULT_TIP_BINDINGS: Dict[str, Optional[str]] = {
    "L_HAND_INDEX":     "NEXT_PAGE",
    "L_HAND_MIDDLE":    "PREV_PAGE",
    "L_HAND_RING":      "FULL_SCREEN",
    "L_HAND_PINKY":     "FROM_CURRENT",
    "R_HAND_INDEX":     "BLACK_SCREEN",
    "R_HAND_MIDDLE":    "WHITE_SCREEN",
    "R_HAND_RING":      "EXIT",
    "R_HAND_PINKY":     "SCREENSHOT",
    "HANDS_INTERLOCK":  "OPEN_PPT",
}

# DEFAULT_GESTURE_CONFIG["sensitivity"] 新增:
"tip_touch_ratio": 0.55,           # 拇-目标指尖归一化距离阈值
"interlock_max_wrist_dist": 0.20, # 两 wrist 归一化距离上限
"interlock_max_tip_dist": 0.40,   # 10 指尖两两均值距离上限(归一化)
"interlock_min_dwell_s": 0.3,     # interlock 最小持续秒数

# DEFAULT_GESTURE_CONFIG 新增字段:
"tip_bindings": dict(DEFAULT_TIP_BINDINGS),
```

### 7.2 持久化

`_merge_defaults` 已支持 nested dict 合并,新增字段自动透传。现有 `bindings` 字段不动,`tip_bindings` 独立 key。

## 8. UI 集成(`ppt_qt/pages/gesture_page.py`)

### 8.1 Combo box 排布

`_build_gesture_tab` 在 7 行旧 gesture combo 之后,加分隔线 + 9 行新事件 combo:

```
──────────────── 旧版手势(7 个)───────────────
[OK]              [下一页   ▼]
[L_SIGN]          [上一页   ▼]
[THREE_FINGERS]   [黑屏     ▼]
[POINTING_UP]     [None     ▼]   # 走 laser
[SCISSORS]        [...]
[FIST]            [...]
[PALM]            [...]

─────────── 新 9-事件(需双人模式) ──────────
[左手拇指触食指]  [下一页   ▼]
[左手拇指触中指]  [上一页   ▼]
[左手拇指触无名指][从头放映 ▼]
[左手拇指触小拇指][从当前放映▼]
[右手拇指触食指]  [黑屏     ▼]
[右手拇指触中指]  [白屏     ▼]
[右手拇指触无名指][退出     ▼]
[右手拇指触小拇指][截屏     ▼]
[双手十指相扣]    [启动PPT  ▼]
```

### 8.2 dual mode off 时 disable

```python
if self._cfg.operator_mode != "dual":
    for combo in self._tip_combos:
        combo.setEnabled(False)
        combo.setToolTip("需切到「双人模式」才能使用")
else:
    for combo in self._tip_combos:
        combo.setEnabled(True)
        combo.setToolTip("")
```

监听 `self._var_gesture_operator` 变化,实时更新 enable 状态。

### 8.3 `_GESTURE_META` 增 9 项

```python
_TIP_GESTURE_META = {
    "L_HAND_INDEX":    ("👆", "左手拇指触食指"),
    "L_HAND_MIDDLE":   ("🖕", "左手拇指触中指"),
    "L_HAND_RING":     ("💍", "左手拇指触无名指"),
    "L_HAND_PINKY":    ("🤙", "左手拇指触小拇指"),
    "R_HAND_INDEX":    ("👆", "右手拇指触食指"),
    "R_HAND_MIDDLE":   ("🖕", "右手拇指触中指"),
    "R_HAND_RING":     ("💍", "右手拇指触无名指"),
    "R_HAND_PINKY":    ("🤙", "右手拇指触小拇指"),
    "HANDS_INTERLOCK": ("🤝", "双手十指相扣"),
}
```

## 9. 迁移策略

- **绑定兼容**: 现有 `ppt_pc_client_gesture.json` 的 `bindings` 字段保留。新增 `tip_bindings` 字段。`_merge_defaults` 把 `DEFAULT_TIP_BINDINGS` 灌进 `tip_bindings` 缺失键,用户已有 `bindings` 不动。
- **教学流**: 现有 `gesture_tutorial_dialog` 保持原 7 步教学,**不**加 9 步(教学负担太重)。试用面板天然进同一 ring buffer,在面板上加列"事件类型"区分 gesture / tip_touch / interlock。
- **回退**: 9 事件检测失败不影响 7 旧 gesture 派发;反之亦然。两条通道完全独立。

## 10. 测试计划

新增 `tests/test_tip_touch_gestures.py`(估计 ~150 行):

| 测试名 | 验证 |
|---|---|
| `test_tip_touch_index_close_to_thumb` | 拇指触食指 → L_HAND_INDEX |
| `test_tip_touch_middle` | 拇指触中指 → L_HAND_MIDDLE |
| `test_tip_touch_ring` | 拇指触无名指 → L_HAND_RING |
| `test_tip_touch_pinky` | 拇指触小拇指 → L_HAND_PINKY |
| `test_tip_touch_no_contact_returns_none` | 拇指张开离所有指尖 > 阈值 → NONE |
| `test_tip_touch_threshold_via_config` | 调小 tip_touch_ratio 让更宽松接触也能识别 |
| `test_tip_touch_slot_b_uses_R_prefix` | slot B 的同名触食指 → R_HAND_INDEX |
| `test_tip_touch_only_in_dual_mode` | single 模式只产 L_* 不产 R_* |
| `test_interlock_two_hands_close` | 两手距离近 + 10 指尖近 → HANDS_INTERLOCK |
| `test_interlock_requires_both_hands` | 只有一个手 → False |
| `test_interlock_dwell_time` | 持续 < min_dwell_s → 不触发 |
| `test_interlock_wrist_too_far` | 两 wrist 距离 > 阈值 → False |
| `test_tip_bindings_persist_via_save_load` | 9 binding 写盘 + 读回一致 |
| `test_dispatch_independence` | 7 gesture 触发不消耗 9 event 的 cooldown |
| `test_16_combos_in_ui` | `_build_gesture_tab` 构建 16 行 combo box |
| `test_tip_touch_cooldown_independent` | 9 event 冷却与 7 gesture 冷却独立计时 |

## 11. 验收标准

- 191 现有测试 + 16 新测试 = 207 个测试全过
- `kasi.txt` 中已有的"OK 误触"问题在新模型下消失(用户实测)
- 教学流不破,试用面板能区分 16 个事件
- 旧 `bindings.json` 不丢,新 `tip_bindings` 字段自动写入
- dual mode off 时 UI 9 行 disable,on 时 enable
- interlock dwell 0.3s 可通过 cfg 调整

## 12. 不做(YAGNI)

- 教学 9 步模式(教学负担重,试用面板够用)
- 9 事件自定义 emoji(用 `_TIP_GESTURE_META` 默认即可)
- interlock 单/双手 L/R 区分(双手事件就一种)
- "握手"其他姿态变种(双掌合十、五指交叉等)
- 持久化 9 事件的灵敏度调节 UI(走 cfg.sensitivity,暂不暴露 UI)

## 13. 风险

| 风险 | 缓解 |
|---|---|
| MediaPipe 在双手 interlock 时 landmark 检测质量下降 | 9 事件是 best-effort,失败不影响 7 旧 gesture |
| 用户做 OK 时也触发 L_HAND_INDEX(因为 OK 包含拇指触食指) | 9 事件 channel 与 7 gesture channel 独立,UI 上两个 combo 都能绑不同 action(用户可自选) |
| dual mode off 时 9 事件不触发,UI 显示 disable | 已设计 |
| 现有 191 测试中可能 mock `_classify_static` 而 `_detect_tip_touches` 没 mock | 新增 tip_touch 测试用独立 mock |

## 14. 文件改动清单

- `pc_gesture/config.py` — 加 TIP_GESTURES / DEFAULT_TIP_BINDINGS / 4 个 sensitivity 字段
- `pc_gesture/semantics.py` — 加 `_detect_tip_touches` / `_detect_interlock` / step 4 派发 / HandState 增字段
- `pc_gesture/types.py` — HandSnapshot `static_gesture` 不变(7 旧),新增 `tip_touch` 字段
- `pc_gesture/gesture_bridge.py`(在 ppt_core/) — `_on_gesture_event` 据 `event_class` 路由到 `bindings` 或 `tip_bindings`
- `pc_gesture/config.py`  — `GestureConfig` 增 `tip_bindings` 属性
- `ppt_qt/pages/gesture_page.py` — `_TIP_GESTURE_META` / `_build_gesture_tab` 加 9 行 combo / `dual mode off` 禁用
- `tests/test_tip_touch_gestures.py`(新文件) — 16 个新测试
