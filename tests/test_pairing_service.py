"""Unit tests for pc_gesture.pairing.PairingService (info.txt 六.2 SRP extraction).

PairingService 是独立的业务逻辑类,只依赖 sensitivity dict。
不依赖 GestureSemantics,可以直接 unit test。
"""

import time

from pc_gesture.pairing import PairingService


def _sens(window_ms=3000, pointing_up_s=1.0):
    return {"pairing_window_ms": window_ms, "pairing_pointing_up_s": pointing_up_s}


def test_state_idle_initially():
    ps = PairingService(_sens())
    assert ps.state == PairingService.PAIRING_IDLE
    assert ps.confirmed is False
    assert ps.active is False


def test_start_transitions_to_waiting():
    ps = PairingService(_sens())
    ps.start()
    assert ps.state == PairingService.PAIRING_WAITING
    assert ps.active is True
    assert ps.confirmed is False


def test_reset_returns_to_idle():
    ps = PairingService(_sens())
    ps.start()
    ps.reset()
    assert ps.state == PairingService.PAIRING_IDLE
    assert ps.active is False
    assert ps.confirmed is False


def test_update_with_no_pointing_stays_waiting():
    ps = PairingService(_sens(window_ms=5000))
    ps.start()
    now = time.monotonic()
    confirmed = ps.update({"A": "NONE", "B": "NONE"}, "POINTING_UP")
    assert confirmed is False
    assert ps.confirmed is False
    assert ps.state == PairingService.PAIRING_WAITING


def test_update_with_pointing_increments_timer():
    ps = PairingService(_sens(window_ms=5000, pointing_up_s=0.5))
    ps.start()
    # 第一次 update: 设 pointing_up_start
    now = time.monotonic()
    confirmed = ps.update({"A": "POINTING_UP", "B": "NONE"}, "POINTING_UP")
    assert confirmed is False
    assert ps._slot_pointing_up_start["A"] == now


def test_update_triggers_confirmation_after_duration():
    ps = PairingService(_sens(window_ms=5000, pointing_up_s=0.5))
    ps.start()
    now = time.monotonic()
    # 设 pointing_up_start 为 0.6s 前(> 0.5s 阈值)
    ps._slot_pointing_up_start["A"] = now - 0.6
    confirmed = ps.update({"A": "POINTING_UP", "B": "NONE"}, "POINTING_UP")
    assert confirmed is True
    assert ps.confirmed is True
    assert ps.state == PairingService.PAIRING_CONFIRMED


def test_either_slot_can_confirm():
    ps = PairingService(_sens(window_ms=5000, pointing_up_s=0.5))
    ps.start()
    now = time.monotonic()
    # B 槽 doing pointing up
    ps._slot_pointing_up_start["B"] = now - 0.6
    confirmed = ps.update({"A": "NONE", "B": "POINTING_UP"}, "POINTING_UP")
    assert confirmed is True
    assert ps.confirmed is True


def test_update_after_window_expires_sets_expired_state():
    """fixed.txt A-2:窗口超时后,update 设 _expired=True(保留 _active),
    state 仍能返回 EXPIRED(而非 IDLE)。"""
    ps = PairingService(_sens(window_ms=500, pointing_up_s=0.5))
    ps.start()
    # 把 _started 设为 1s 前(模拟窗口已过)
    ps._started = time.monotonic() - 1.0
    # update 时 elapsed_ms = 1000 > 500,触发 expire
    confirmed = ps.update({"A": "POINTING_UP", "B": "NONE"}, "POINTING_UP")
    assert confirmed is False
    # A-2:_active 仍为 True,_expired=True → state 返 EXPIRED
    assert ps.active is True
    assert ps.state == PairingService.PAIRING_EXPIRED
    # reset() 后回到 IDLE
    ps.reset()
    assert ps.state == PairingService.PAIRING_IDLE


def test_inactive_update_does_nothing():
    ps = PairingService(_sens())
    # 不 start,直接 update
    confirmed = ps.update({"A": "POINTING_UP"}, "POINTING_UP")
    assert confirmed is False
    assert ps.confirmed is False


def test_explicit_window_overrides_config():
    """start(window_ms=500) 锁定窗口,不读 cfg。"""
    ps = PairingService(_sens(window_ms=99999))  # cfg 默认超长
    ps.start(window_ms=500)
    # 600ms 后 state 应是 EXPIRED(用锁定窗口,不是 cfg 的 99999)
    time.sleep(0.6)
    assert ps.state == PairingService.PAIRING_EXPIRED


def test_invalid_sensitivity_falls_back_to_default():
    """sensitivity 给字符串/None,fallback 到默认值,不要崩。"""
    bad_sens = {"pairing_window_ms": "not a number", "pairing_pointing_up_s": None}
    ps = PairingService(bad_sens)
    ps.start()
    # 不会崩,state 正常
    assert ps.state == PairingService.PAIRING_WAITING


def test_reset_clears_slot_timers():
    ps = PairingService(_sens())
    ps.start()
    ps._slot_pointing_up_start["A"] = time.monotonic()
    ps.reset()
    assert ps._slot_pointing_up_start["A"] is None
    assert ps._slot_pointing_up_start["B"] is None