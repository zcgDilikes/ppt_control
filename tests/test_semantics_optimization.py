"""Regression tests for info.txt-driven semantics.py optimizations.

Each test covers one finding from info.txt:
  - 一.3 dual pairing slot
  - 三.1 hand leave clears cooldown + last_static_gesture
  - 三.2 reload_config resets pairing
  - 三.3 palm_hold fields removed
  - 五.4 hand_size upper bound
  - 六.3 laser_smoothing exception guard
  - 五.3 debug_log gate
"""

import time
import pytest

from pc_gesture.config import load_gesture_config, DEFAULT_GESTURE_CONFIG
from pc_gesture.semantics import GestureSemantics, HandState


# ---- 一.3: dual pairing slot ----

def test_pairing_accepts_pointing_up_from_either_slot():
    """之前只看 slot A;现在 A 或 B 任一 slot pointing_up 1s 都能确认配对。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem.start_pairing(window_ms=5000)
    # 直接调 PairingService.update() 喂状态
    sem._pairing.update(
        {"A": "NONE", "B": sem.G_POINTING_UP},
        sem.G_POINTING_UP,
    )
    # B 槽还没 1s,不确认
    assert sem._pairing.confirmed is False
    # 时间跳到 1.5s 后再 update
    sem._pairing.update(
        {"A": "NONE", "B": sem.G_POINTING_UP},
        sem.G_POINTING_UP,
    )
    # 等等,倒退时间会让 elapsed_ms 变负,PairingService 用 now - started,
    # 倒退不实际生效。改用 mock approach:
    # 让 slot_pointing_up_start 直接设为 1.5s 前
    sem._pairing._slot_pointing_up_start["B"] = time.monotonic() - 1.5
    sem._pairing.update({"A": "NONE", "B": sem.G_POINTING_UP}, sem.G_POINTING_UP)
    assert sem._pairing.confirmed is True


def test_pairing_does_not_confirm_when_no_pointing():
    """所有 slot 都没 pointing_up,即使窗口已过大半也不确认。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem.start_pairing(window_ms=5000)
    sem._update_pairing_called_explicitly = True  # B-17:不再用 _update_pairing
    sem._pairing.update(
        {slot: st.last_static_gesture for slot, st in sem._slots.items()},
        sem.G_POINTING_UP,
    )
    assert sem._pairing.confirmed is False
    assert sem._pairing.active is True


# ---- 三.1: hand leave clears cooldown + last_static_gesture ----

def test_hand_leave_clears_cooldown_and_last_gesture():
    """手部消失 > 0.5s 后,last_static_gesture + static_cooldown_until 都应清空。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    st = sem._slots["A"]
    st.last_static_gesture = sem.G_OK
    st.static_cooldown_until = time.monotonic() + 5.0
    st.last_seen_monotonic = time.monotonic() - 1.0  # 1s 前见过
    # process 没手传入 → active_slots 空 → 走 hand-leave cleanup
    sem.process([], [])
    assert st.last_static_gesture == sem.G_NONE
    assert st.static_cooldown_until == 0.0
    assert st.last_static_at == 0.0


# ---- 三.2: reload_config resets pairing ----

def test_reload_config_resets_pairing_state():
    """reload_config 后,PairingService 状态都应被重置。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem.start_pairing(window_ms=5000)
    sem._pairing._confirmed = True
    # 现在 reload
    sem.reload_config(load_gesture_config())
    assert sem._pairing.active is False
    assert sem._pairing.confirmed is False
    assert sem._pairing._started == 0.0


# ---- 三.3: palm_hold fields removed ----

def test_handstate_has_no_palm_hold_fields():
    """palm_hold_start / palm_hold_fired 已删除,不应该再出现在 HandState。"""
    st = HandState(slot="A")
    assert not hasattr(st, "palm_hold_start")
    assert not hasattr(st, "palm_hold_fired")


# ---- 五.4: hand_size upper bound ----

def test_hand_size_lower_bound():
    """极端近距离(手贴镜头)时 size 不会爆炸,夹紧到 0.05。"""
    from pc_gesture.semantics import WRIST, MIDDLE_MCP
    # 构造 wrist 和 middle_mcp 几乎重叠的 21 个关键点
    class _P:
        def __init__(self, x, y): self.x, self.y = x, y
    lm = [_P(0.5, 0.5) for _ in range(21)]
    lm[WRIST] = _P(0.50001, 0.50001)
    lm[MIDDLE_MCP] = _P(0.5, 0.5)
    size = GestureSemantics._hand_size(lm)
    assert size == pytest.approx(0.05, abs=0.001), f"size should be clamped to 0.05, got {size}"


def test_hand_size_upper_bound():
    """手远离镜头时 size 不会超过 0.5。"""
    from pc_gesture.semantics import WRIST, MIDDLE_MCP
    class _P:
        def __init__(self, x, y): self.x, self.y = x, y
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.0, 0.0)
    lm[MIDDLE_MCP] = _P(0.0, 1.0)  # wrist→middle_mcp 距离 1.0(超过 0.5)
    size = GestureSemantics._hand_size(lm)
    assert size == pytest.approx(0.5, abs=0.001), f"size should be clamped to 0.5, got {size}"


# ---- 六.3: laser_smoothing exception guard ----

def test_laser_smoothing_handles_string_config(monkeypatch):
    """配置里 smoothing 是字符串时,不应崩,应 fallback 到默认值。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["laser_smoothing"] = "not a number"  # 异常输入
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_POINTING_UP
    # 不应该抛异常
    events = sem.process([_make_hand()], [])
    laser_events = [e for e in events if e.get("cmd") == "LASER"]
    assert laser_events, "laser should still emit despite bad config"


def _make_hand():
    """造一个能被 classifier 判为 POINTING_UP 的 21-landmark hand。

    wrist.x=0.3 → slot A (single mode 时 laser 在 A 槽产生)。
    """
    from pc_gesture.semantics import WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP, INDEX_PIP, INDEX_TIP, MIDDLE_PIP, MIDDLE_TIP, RING_PIP, RING_TIP, PINKY_PIP, PINKY_TIP, THUMB_TIP

    class _P:
        def __init__(self, x, y): self.x, self.y = x, y
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.3, 0.7)  # wrist.x < 0.5 → slot A
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(0.3, 0.5)
    lm[INDEX_PIP] = _P(0.4, 0.22)
    lm[INDEX_TIP] = _P(0.4, 0.2)  # 伸
    lm[MIDDLE_PIP] = _P(0.45, 0.22)
    lm[MIDDLE_TIP] = _P(0.45, 0.5)  # 卷
    lm[RING_PIP] = _P(0.48, 0.22)
    lm[RING_TIP] = _P(0.48, 0.5)  # 卷
    lm[PINKY_PIP] = _P(0.5, 0.22)
    lm[PINKY_TIP] = _P(0.5, 0.5)  # 卷
    lm[THUMB_TIP] = _P(0.35, 0.55)  # 拇贴近 mcp,卷
    return lm


# ---- 五.3: debug_log gate ----

def test_default_debug_log_is_false():
    """默认 debug_log = False,生产环境不打印。"""
    assert DEFAULT_GESTURE_CONFIG["sensitivity"]["debug_log"] is False


def test_print_suppressed_when_debug_log_false(capsys, monkeypatch):
    """debug_log=False 时,识别手势不打印 [semantics] 日志。"""
    from pc_gesture.semantics import WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP, INDEX_PIP, INDEX_TIP, MIDDLE_PIP, MIDDLE_TIP, RING_PIP, RING_TIP, PINKY_PIP, PINKY_TIP, THUMB_TIP

    class _P:
        def __init__(self, x, y): self.x, self.y = x, y

    def mk():
        lm = [_P(0.0, 0.0) for _ in range(21)]
        lm[WRIST] = _P(0.3, 0.7)
        for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
            lm[idx] = _P(0.3, 0.5)
        lm[INDEX_PIP] = _P(0.4, 0.22)
        lm[INDEX_TIP] = _P(0.4, 0.2)
        lm[MIDDLE_PIP] = _P(0.45, 0.22)
        lm[MIDDLE_TIP] = _P(0.45, 0.5)
        lm[RING_PIP] = _P(0.48, 0.22)
        lm[RING_TIP] = _P(0.48, 0.5)
        lm[PINKY_PIP] = _P(0.5, 0.22)
        lm[PINKY_TIP] = _P(0.5, 0.5)
        lm[THUMB_TIP] = _P(0.35, 0.55)
        return lm

    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["debug_log"] = False
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_OK
    sem.process([mk()], [])
    captured = capsys.readouterr()
    assert "[semantics] 🎯" not in captured.out, "debug_log=False should suppress prints"