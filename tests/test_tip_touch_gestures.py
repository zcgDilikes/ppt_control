"""Tests for 9-event gesture system (info.txt 9-events design)."""
from pc_gesture.config import (
    DEFAULT_GESTURE_CONFIG,
    DEFAULT_TIP_BINDINGS,
    TIP_GESTURES,
    GestureConfig,
)


def test_tip_gestures_enum_has_nine():
    """9 个事件: 4 × 2 + 1 interlock"""
    assert len(TIP_GESTURES) == 9
    assert "L_HAND_INDEX" in TIP_GESTURES
    assert "L_HAND_MIDDLE" in TIP_GESTURES
    assert "L_HAND_RING" in TIP_GESTURES
    assert "L_HAND_PINKY" in TIP_GESTURES
    assert "R_HAND_INDEX" in TIP_GESTURES
    assert "R_HAND_MIDDLE" in TIP_GESTURES
    assert "R_HAND_RING" in TIP_GESTURES
    assert "R_HAND_PINKY" in TIP_GESTURES
    assert "HANDS_INTERLOCK" in TIP_GESTURES


def test_default_tip_bindings_have_all_nine():
    """每个 tip 事件都有默认 binding(可能 None)"""
    assert len(DEFAULT_TIP_BINDINGS) == 9
    for g in TIP_GESTURES:
        assert g in DEFAULT_TIP_BINDINGS
        v = DEFAULT_TIP_BINDINGS[g]
        assert v is None or isinstance(v, str)


def test_sensitivity_has_new_fields():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    s = cfg.sensitivity
    assert s["tip_touch_ratio"] == 0.55
    assert s["interlock_max_wrist_dist"] == 0.20
    assert s["interlock_max_tip_dist"] == 0.40
    assert s["interlock_min_dwell_s"] == 0.3


def test_tip_bindings_attribute_round_trip():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    # 读默认
    assert cfg.tip_bindings["L_HAND_INDEX"] == "NEXT_PAGE"
    # 改
    cfg.set_tip_binding("L_HAND_INDEX", "BLACK_SCREEN")
    assert cfg.get_tip_binding("L_HAND_INDEX") == "BLACK_SCREEN"
    # 写盘
    cfg.set_tip_binding("L_HAND_MIDDLE", None)
    assert cfg.get_tip_binding("L_HAND_MIDDLE") is None


def test_set_tip_binding_rejects_unknown_gesture():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("UNKNOWN_GESTURE", "NEXT_PAGE")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")


def test_set_tip_binding_rejects_unknown_action():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("L_HAND_INDEX", "FAKE_ACTION")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")


def test_handstate_has_new_tip_fields():
    """9 事件需要新的 last_gesture 和 cooldown 字段"""
    from pc_gesture.semantics import HandState
    st = HandState(slot="A")
    assert st.last_tip_gesture == "NONE"
    assert st.tip_cooldown_until == 0.0
    assert st.last_interlock_gesture == "NONE"
    assert st.interlock_cooldown_until == 0.0


# ---------------------------------------------------------------------------
# Task 3: _detect_tip_touches (single-hand)
# ---------------------------------------------------------------------------
class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _make_tip_hand(thumb_xy, target_tip_xy, wrist_xy=(0.3, 0.7)):
    """构造拇指尖与 target_tip 接近的手(其他手指位置随意)。

    wrist=(0.3, 0.7), MCP=(0.3, 0.5): hand_size = 0.2
    thumb_xy 与 target_tip_xy 距离 ≈ 0 → 触到
    """
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[0] = _P(*wrist_xy)  # WRIST
    for idx in (5, 9, 13, 17):  # MCP 全部相同
        lm[idx] = _P(0.3, 0.5)
    # 4 个指尖位置
    lm[8] = _P(0.5, 0.2)   # INDEX_TIP
    lm[12] = _P(0.6, 0.2)  # MIDDLE_TIP
    lm[16] = _P(0.7, 0.2)  # RING_TIP
    lm[20] = _P(0.8, 0.2)  # PINKY_TIP
    # 4 个 PIP(无影响)
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        lm[pip_idx] = _P(0.5, 0.3)
    # 拇指尖
    lm[4] = _P(*thumb_xy)
    return lm


def test_detect_tip_touch_index():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖 = INDEX_TIP = (0.5, 0.2),hand_size=0.2 → dist 归一化=0
    lm = _make_tip_hand((0.5, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_INDEX"


def test_detect_tip_touch_middle():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.6, 0.2), (0.6, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_MIDDLE"


def test_detect_tip_touch_ring():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.7, 0.2), (0.7, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_RING"


def test_detect_tip_touch_pinky():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    lm = _make_tip_hand((0.8, 0.2), (0.8, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_PINKY"


def test_detect_tip_touch_no_contact_returns_none():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖在 (0.1, 0.2),离最近 INDEX_TIP=(0.5, 0.2) 距离 0.4
    # hand_size = 0.2,归一化 0.4/0.2 = 2.0,远超 0.55 阈值
    lm = _make_tip_hand((0.1, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "NONE"


def test_detect_tip_touch_slot_b_uses_r_prefix():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # slot B 的同名触食指应该返回 R_HAND_INDEX
    lm = _make_tip_hand((0.5, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "B") == "R_HAND_INDEX"


def test_detect_tip_touch_threshold_via_config():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    # 调小阈值,让边缘接触也能识别
    cfg.raw["sensitivity"]["tip_touch_ratio"] = 1.0
    sem = GestureSemantics(cfg)
    # 拇指尖 (0.7, 0.2), INDEX_TIP (0.5, 0.2),归一化距离 0.2/0.2 = 1.0
    # 默认 0.55 阈值 → 不触发(1.0 >= 0.55);调 1.0 → 触发(1.0 < 1.0 失败 → 改用 RING)
    # 用 RING_TIP(0.7, 0.2):距离 0,阈值 1.0 时触发
    lm = _make_tip_hand((0.7, 0.2), (0.5, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_RING"


def test_detect_tip_touch_chooses_nearest():
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    # 拇指尖 (0.6, 0.2),离 MIDDLE_TIP (0.6, 0.2) 最近(0 距离)
    # 与 INDEX_TIP (0.5, 0.2) 距离 0.1,归一化 0.5(超过 0.55 阈值);
    # 与 RING/PINKY 更远。所以应选 MIDDLE
    lm = _make_tip_hand((0.6, 0.2), (0.6, 0.2))
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_MIDDLE"


# ---------------------------------------------------------------------------
# Task 4: _detect_interlock (cross-slot)
# ---------------------------------------------------------------------------
def _make_two_hands_close():
    """构造两手相距近 + 10 指尖两两距离近 → 满足 interlock 条件。"""
    a = [_P(0.0, 0.0) for _ in range(21)]
    a[0] = _P(0.3, 0.5)  # WRIST
    a[5] = a[9] = a[13] = a[17] = _P(0.35, 0.4)  # MCP
    a[8] = _P(0.4, 0.3)  # INDEX_TIP
    a[12] = _P(0.42, 0.32)  # MIDDLE_TIP
    a[16] = _P(0.44, 0.34)  # RING_TIP
    a[20] = _P(0.46, 0.36)  # PINKY_TIP
    a[4] = _P(0.38, 0.35)  # THUMB_TIP
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        a[pip_idx] = _P(0.4, 0.4)

    b = [_P(0.0, 0.0) for _ in range(21)]
    b[0] = _P(0.5, 0.5)  # WRIST(距 a 的 wrist 0.2)
    b[5] = b[9] = b[13] = b[17] = _P(0.45, 0.4)
    b[8] = _P(0.4, 0.3)
    b[12] = _P(0.42, 0.32)
    b[16] = _P(0.44, 0.34)
    b[20] = _P(0.46, 0.36)
    b[4] = _P(0.42, 0.35)
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        b[pip_idx] = _P(0.4, 0.4)
    return a, b


def test_detect_interlock_two_hands_close():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 第一次调用,设 _interlock_start
    assert sem._detect_interlock(a, b, time.monotonic()) is False
    # 持续 0.3s 后再调 → True
    time.sleep(0.35)
    assert sem._detect_interlock(a, b, time.monotonic()) is True


def test_detect_interlock_requires_both_hands():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, _ = _make_two_hands_close()
    assert sem._detect_interlock(a, None, time.monotonic()) is False
    assert sem._detect_interlock(None, a, time.monotonic()) is False


def test_detect_interlock_dwell_time():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 第一次调用,设 start;0.1s 内调,dwell 未到 → False
    t0 = time.monotonic()
    sem._detect_interlock(a, b, t0)
    assert sem._detect_interlock(a, b, t0 + 0.1) is False
    # 0.3s 后 → True
    assert sem._detect_interlock(a, b, t0 + 0.35) is True


def test_detect_interlock_wrist_too_far():
    import time
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    sem = GestureSemantics(load_gesture_config())
    a, b = _make_two_hands_close()
    # 把 b 的 wrist 拉到远处
    b[0] = _P(0.9, 0.9)
    t0 = time.monotonic()
    sem._detect_interlock(a, b, t0)
    time.sleep(0.4)
    assert sem._detect_interlock(a, b, time.monotonic()) is False


# ---------------------------------------------------------------------------
# Task 5: process() 集成 9 事件
# ---------------------------------------------------------------------------
def test_process_emits_tip_touch_in_dual_mode():
    """dual 模式 + 拇指触食指 → L_HAND_INDEX 事件"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    cfg.raw["dual_roles_swapped"] = False  # 测试要确认 slot A,需把互换关掉
    sem = GestureSemantics(cfg)
    # 模拟 slot A 手(wrist 在画面左侧)
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))
    lm_b = [_P(0.0, 0.0) for _ in range(21)]  # 另一只手不可见
    events = sem.process([lm_a, lm_b], [[], []])
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    assert len(tip_events) == 1
    assert tip_events[0]["gesture"] == "L_HAND_INDEX"
    assert tip_events[0]["slot"] == "A"


def test_process_no_tip_touch_in_single_mode_for_R_prefix():
    """single 模式只产 L_*(slot A),即使给两手 landmarks 也只识别 A 槽"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "single"
    sem = GestureSemantics(cfg)
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))  # 左侧
    lm_b = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.7, 0.7))  # 右侧
    events = sem.process([lm_a, lm_b], [[], []])
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    # single 模式 _process_one_hand 只调 A 槽,所以即使有两手也只产 L_*
    for e in tip_events:
        assert e["gesture"].startswith("L_HAND_")


def test_process_tip_touch_cooldown_independent_from_static():
    """tip 事件冷却独立于 7 旧 gesture 冷却"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    import time
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    cfg.raw["dual_roles_swapped"] = False  # 测试要确认 slot A,需把互换关掉
    cfg.raw["sensitivity"]["gesture_cooldown_ms"] = 400
    sem = GestureSemantics(cfg)
    # 第 1 帧:slot A 触食指
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))
    lm_b = [_P(0.0, 0.0) for _ in range(21)]
    events1 = sem.process([lm_a, lm_b], [[], []])
    assert any(e.get("type") == "tip_touch" for e in events1)
    # 第 2 帧(立刻,小于 400ms 冷却):tip 应该被挡
    events2 = sem.process([lm_a, lm_b], [[], []])
    assert not any(e.get("type") == "tip_touch" for e in events2)


def test_process_emits_interlock_event():
    """双手 interlock 触发 HANDS_INTERLOCK"""
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.config import load_gesture_config
    import time
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    cfg.raw["dual_roles_swapped"] = False  # 测试要确认 slot A,需把互换关掉
    sem = GestureSemantics(cfg)
    a, b = _make_two_hands_close()
    # 第 1 帧:初始化 dwell
    sem.process([a, b], [[], []])
    # 0.4s 后:interlock 触发
    time.sleep(0.4)
    events = sem.process([a, b], [[], []])
    interlock_events = [e for e in events if e.get("type") == "interlock"]
    assert len(interlock_events) == 1
    assert interlock_events[0]["gesture"] == "HANDS_INTERLOCK"
    assert interlock_events[0]["slot"] == "BOTH"