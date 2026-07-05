"""Tests for GestureBridge teaching_mode flag.

Teaching mode = recognize but don't dispatch. The UI's top toggle and
tutorial dialog both flip this state; the bridge must suppress dispatcher
calls while still populating ``recent_gestures`` so the trial panel and
the dialog can see what was recognized.
"""


def _make_bridge():
    import ppt_core.gesture_bridge as gb
    from ppt_core.gesture_bridge import GestureBridge

    captured = []

    class FakeDispatcher:
        def dispatch(self, d):
            captured.append(d)

    class FakeEngine:
        def __init__(self, **kwargs):
            pass
        def start(self):
            return None
        def stop(self):
            pass
        def start_pairing(self):
            pass
        def reset_pairing(self):
            pass
        def save_config(self):
            pass
        cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
        _semantics = None

    orig_engine = gb.GestureEngine
    gb.GestureEngine = FakeEngine
    try:
        bridge = GestureBridge(
            dispatcher=FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
    finally:
        gb.GestureEngine = orig_engine
    return bridge, captured


def test_teaching_mode_defaults_false():
    bridge, _ = _make_bridge()
    assert bridge.teaching_mode is False


def test_set_teaching_mode_updates_flag():
    bridge, _ = _make_bridge()
    bridge.set_teaching_mode(True)
    assert bridge.teaching_mode is True
    bridge.set_teaching_mode(False)
    assert bridge.teaching_mode is False


def test_teaching_mode_blocks_dispatcher_but_records_gesture():
    bridge, captured = _make_bridge()
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    bridge.set_teaching_mode(True)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"}
    )
    # Dispatcher was NOT called.
    assert captured == []
    # But recent_gestures() did get the recognition so UI / tutorial can see it.
    recent = bridge.recent_gestures()
    assert len(recent) == 1
    assert recent[0]["gesture"] == "FIST"


def test_teaching_mode_off_lets_dispatch_through():
    bridge, captured = _make_bridge()
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    bridge.set_teaching_mode(False)  # explicit
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"}
    )
    assert captured == [{"cmd": "BLACK_SCREEN"}]


def test_teaching_mode_does_not_swallow_unbound_gesture():
    """PALM is unbound by default — teaching_mode should not cause any side effect."""
    bridge, captured = _make_bridge()
    bridge.set_teaching_mode(True)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "PALM", "slot": "A", "source": "gesture:A"}
    )
    assert captured == []
    assert len(bridge.recent_gestures()) == 1
