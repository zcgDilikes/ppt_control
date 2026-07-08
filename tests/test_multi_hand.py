"""Tests for multi-hand (3-person meeting scenario) feature.

Task 6: HandState.person_id + slot C + multi_person_mode config.

Brief verbatim: tests assert HandState has person_id, multi_person_mode config
exists, slot C is created in 3-hand mode, and tip_touch dispatches C_HAND_*
gesture prefix for person_id=2.
"""
from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


def _make_tip_hand(thumb_xy, target_tip_xy, wrist_xy=(0.3, 0.7)):
    """构造拇指尖与 target_tip 接近的手(其他手指位置随意)。"""
    class _P:
        def __init__(self, x, y):
            self.x = x
            self.y = y
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[0] = _P(*wrist_xy)  # WRIST
    for idx, mcp_x in zip((5, 9, 13, 17), (0.3, 0.4, 0.5, 0.6)):
        lm[idx] = _P(mcp_x, 0.5)
    lm[8] = _P(0.5, 0.2)   # INDEX_TIP
    lm[12] = _P(0.6, 0.2)  # MIDDLE_TIP
    lm[16] = _P(0.7, 0.2)  # RING_TIP
    lm[20] = _P(0.8, 0.2)  # PINKY_TIP
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        lm[pip_idx] = _P(0.5, 0.3)
    lm[4] = _P(*thumb_xy)
    thumb_x = thumb_xy[0]
    lm[1] = _P(thumb_x - 0.1, 0.55)
    lm[2] = _P(thumb_x - 0.05, 0.5)
    lm[3] = _P(thumb_x, 0.3)
    return lm


def test_2_hand_mode_assigns_a_b():
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "2_hand"
    sem = GestureSemantics(cfg)

    # 构造两只手:拇指触食指,且满足 3 特征投票。
    # 手 1 wrist.x=0.3 → slot A → L_HAND_INDEX
    # 手 2 wrist.x=0.7 → slot B → R_HAND_INDEX
    lm_a = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.3, 0.7))
    lm_b = _make_tip_hand((0.5, 0.2), (0.5, 0.2), wrist_xy=(0.7, 0.7))
    events = sem.process([lm_a, lm_b], [[], []])
    # 应有 L_HAND_* 和 R_HAND_* 各一个(互不干扰)
    tip_events = [e for e in events if e.get("type") == "tip_touch"]
    gestures = {e["gesture"] for e in tip_events}
    assert any(g.startswith("L_HAND") for g in gestures)
    assert any(g.startswith("R_HAND") for g in gestures)


def test_handstate_has_person_id():
    """HandState must have person_id field (default 0)."""
    from pc_gesture.semantics import HandState
    st = HandState(slot="A")
    assert hasattr(st, "person_id")
    assert st.person_id == 0
    st2 = HandState(slot="C", person_id=2)
    assert st2.person_id == 2


def test_config_has_multi_person_mode():
    """GestureConfig must have multi_person_mode field (default off)."""
    cfg = load_gesture_config()
    # multi_person_mode may be exposed via raw or a property
    mode = cfg.raw.get("multi_person_mode", None)
    assert mode is not None, "multi_person_mode must be in raw config"
    assert mode in ("off", "2_hand", "3_hand_round_robin")


def test_3_hand_mode_creates_slot_c():
    """When multi_person_mode=3_hand_round_robin, slot C HandState is created."""
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "3_hand_round_robin"
    sem = GestureSemantics(cfg)
    assert "C" in sem._slots, "slot C must be created in 3-hand mode"
    assert sem._slots["C"].slot == "C"
    assert sem._slots["C"].person_id == 2


def test_off_mode_no_slot_c():
    """When multi_person_mode=off (default), no slot C."""
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "off"
    sem = GestureSemantics(cfg)
    assert "C" not in sem._slots


def test_detect_tip_touch_slot_c_uses_c_prefix():
    """_detect_tip_touches with slot C produces C_HAND_* gesture prefix."""
    from pc_gesture.semantics import GestureSemantics
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)

    # Build hand where thumb touches INDEX tip (closest)
    class _P:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[0] = _P(0.3, 0.7)  # WRIST
    for idx, mcp_x in zip((5, 9, 13, 17), (0.3, 0.4, 0.5, 0.6)):
        lm[idx] = _P(mcp_x, 0.5)
    lm[8] = _P(0.5, 0.2)   # INDEX_TIP
    lm[12] = _P(0.6, 0.2)  # MIDDLE_TIP
    lm[16] = _P(0.7, 0.2)  # RING_TIP
    lm[20] = _P(0.8, 0.2)  # PINKY_TIP
    for tip_idx, pip_idx in ((8, 6), (12, 10), (16, 14), (20, 18)):
        lm[pip_idx] = _P(0.5, 0.3)
    lm[4] = _P(0.5, 0.2)   # THUMB_TIP touches INDEX_TIP
    lm[1] = _P(0.4, 0.55)
    lm[2] = _P(0.45, 0.5)
    lm[3] = _P(0.5, 0.3)

    # Slot A → L_HAND_INDEX
    assert sem._detect_tip_touches(lm, "A") == "L_HAND_INDEX"
    # Slot B → R_HAND_INDEX
    assert sem._detect_tip_touches(lm, "B") == "R_HAND_INDEX"
    # Slot C → C_HAND_INDEX
    assert sem._detect_tip_touches(lm, "C") == "C_HAND_INDEX"


def test_slot_isolation_3_hand():
    """3 个手不互相污染各自 HandState。"""
    cfg = load_gesture_config()
    cfg.raw["multi_person_mode"] = "3_hand_round_robin"
    sem = GestureSemantics(cfg)
    # 模拟 slot A、B、C 各自的 interlock 进度
    sem._interlock_start = 100.0
    # 3 个手各自分配,验证 HandState 独立
    assert sem._slots["A"].slot == "A"
    assert sem._slots["B"].slot == "B"
    assert sem._slots["C"].slot == "C"
    # 修改 A 的字段不影响 B/C
    sem._slots["A"].last_tip_gesture = "L_HAND_INDEX"
    assert sem._slots["B"].last_tip_gesture == "NONE"
    assert sem._slots["C"].last_tip_gesture == "NONE"