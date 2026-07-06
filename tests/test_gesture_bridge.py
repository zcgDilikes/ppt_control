"""Tests for ppt_core.gesture_bridge — bridge between pc_gesture.GestureEngine and CommandDispatcher."""

from __future__ import annotations

from types import SimpleNamespace


class FakeDispatcher:
    """Records every command dict dispatched through it."""

    def __init__(self):
        self.calls = []

    def dispatch(self, d):
        self.calls.append(d)


class FakeSemantics:
    """Stands in for GestureEngine._semantics — records reload_config calls."""

    def __init__(self):
        self.reloaded = []

    def reload_config(self, cfg):
        self.reloaded.append(cfg)


class FakeEngine:
    """Stand-in for pc_gesture.engine.GestureEngine."""

    instances = []  # type: ignore[type-arg]

    def __init__(self, *, dispatch_fn, on_status, on_fps, on_send_text, on_frame=None):
        self.kwargs = {
            "dispatch_fn": dispatch_fn,
            "on_status": on_status,
            "on_fps": on_fps,
            "on_send_text": on_send_text,
            "on_frame": on_frame,
        }
        self.start_called = False
        self.stop_called = False
        self.start_pairing_called = False
        self.reset_pairing_called = False
        self.save_config_called = 0
        # cfg: simple namespace with attributes dual_roles_swapped and a .raw dict
        self.cfg = SimpleNamespace(dual_roles_swapped=False, raw={})
        self._semantics = FakeSemantics()
        FakeEngine.instances.append(self)

    def start(self):
        self.start_called = True
        return None  # or "fake error"

    def stop(self):
        self.stop_called = True

    def start_pairing(self):
        self.start_pairing_called = True

    def reset_pairing(self):
        self.reset_pairing_called = True

    def save_config(self):
        self.save_config_called += 1


def _make_bridge(monkeypatch):
    """Reload ppt_core.gesture_bridge under a monkeypatched GestureEngine.

    The bridge does ``from pc_gesture.engine import GestureEngine``, so we
    must (a) register the fake at the bridge module's namespace BEFORE the
    bridge's import resolves, then (b) reload the bridge module so that the
    ``from ... import`` line picks up our fake. ``monkeypatch.setattr`` runs
    eagerly, but the bridge module is typically already imported by an earlier
    test or sibling test file, so we additionally force a reload.
    """
    import sys
    import importlib
    # Make sure any previously-loaded bridge module is dropped so the
    # monkeypatched name is picked up by ``from ... import ...``.
    monkeypatch.delitem(sys.modules, "ppt_core.gesture_bridge", raising=False)
    monkeypatch.delitem(sys.modules, "pc_gesture.engine", raising=False)
    monkeypatch.delitem(sys.modules, "pc_gesture", raising=False)
    # Now import the bridge module fresh and patch the GestureEngine binding.
    import ppt_core.gesture_bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "GestureEngine", FakeEngine)
    dispatcher = FakeDispatcher()
    status_calls, fps_calls, send_text_calls = [], [], []
    bridge = bridge_mod.GestureBridge(
        dispatcher=dispatcher,
        on_status=lambda s: status_calls.append(s),
        on_fps=lambda f: fps_calls.append(f),
        on_send_text=lambda t: send_text_calls.append(t),
    )
    return bridge_mod, bridge, dispatcher, (status_calls, fps_calls, send_text_calls)


def test_bridge_start_calls_engine_start(monkeypatch):
    _bridge_mod, bridge, _dispatcher, _cb = _make_bridge(monkeypatch)
    result = bridge.start()
    assert result is None
    assert bridge.engine is not None
    assert bridge.engine.start_called is True
    # Engine should be instantiated exactly once (lazily) on first start()
    assert len(FakeEngine.instances) == 1
    # dispatch_fn passed to engine should now be the bridge's gesture-event
    # router (bridge owns binding lookup + dispatch).
    assert bridge.engine.kwargs["dispatch_fn"] == _bridge_mod.GestureBridge._on_gesture_event.__get__(bridge)


def test_bridge_dispatch_passes_dispatcher(monkeypatch):
    _bridge_mod, bridge, dispatcher, _cb = _make_bridge(monkeypatch)
    bridge.start()  # forces engine creation
    # Pull out the dispatch_fn the engine received and invoke it with a
    # gesture event (not a raw cmd dict — the bridge filters + binding-lookups
    # first, then dispatches).
    dispatch_fn = bridge.engine.kwargs["dispatch_fn"]
    bridge.cfg.set_binding("POINTING_UP", "FULL_SCREEN")
    dispatch_fn({"type": "gesture", "gesture": "POINTING_UP", "slot": "A", "source": "gesture:A"})
    assert dispatcher.calls == [{"cmd": "FULL_SCREEN"}]


def test_bridge_swap_roles_writes_cfg(monkeypatch):
    _bridge_mod, bridge, _dispatcher, _cb = _make_bridge(monkeypatch)
    bridge.start()
    bridge.swap_roles(True)
    assert bridge.engine.cfg.dual_roles_swapped is True
    assert bridge.engine.save_config_called >= 1
    assert bridge.engine._semantics.reloaded == [bridge.engine.cfg]

    bridge.swap_roles(False)
    assert bridge.engine.cfg.dual_roles_swapped is False


def test_bridge_start_pairing_resets_engine(monkeypatch):
    _bridge_mod, bridge, _dispatcher, _cb = _make_bridge(monkeypatch)
    bridge.start_pairing()
    bridge.reset_pairing()
    bridge.save()
    assert bridge.engine is not None
    assert bridge.engine.start_pairing_called is True
    assert bridge.engine.reset_pairing_called is True
    assert bridge.engine.save_config_called >= 1


def test_bridge_engine_property_none_before_start(monkeypatch):
    _bridge_mod, bridge, _dispatcher, _cb = _make_bridge(monkeypatch)
    assert bridge.engine is None


def test_action_to_cmd_known_actions():
    from ppt_core.gesture_bridge import _action_to_cmd
    assert _action_to_cmd("NEXT_PAGE") == {"cmd": "NEXT_PAGE"}
    assert _action_to_cmd("EXIT") == {"cmd": "EXIT"}
    assert _action_to_cmd("OPEN_PPT") == {"cmd": "OPEN_PPT", "path": ""}
    assert _action_to_cmd("PC_WINDOW_MINIMIZE") == {"cmd": "PC_WINDOW_MINIMIZE"}


def test_action_to_cmd_unknown_action_returns_empty():
    from ppt_core.gesture_bridge import _action_to_cmd
    assert _action_to_cmd("BOGUS") == {}


def test_bridge_routes_gesture_event_to_dispatcher():
    import sys; sys.path.insert(0, '.')
    from ppt_core.gesture_bridge import GestureBridge

    captured = []
    class FakeDispatcher:
        def dispatch(self, d): captured.append(d)

    class FakeEngine:
        def __init__(self, **kwargs): self.kwargs = kwargs
        def start(self): return None
        def stop(self): pass
        def start_pairing(self): pass
        def reset_pairing(self): pass
        def save_config(self): pass
        cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
        _semantics = None

    import ppt_core.gesture_bridge as gb
    orig_engine = gb.GestureEngine
    gb.GestureEngine = FakeEngine
    try:
        bridge = GestureBridge(
            dispatcher=FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
        bridge._on_gesture_event({"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"})
        assert captured == [{"cmd": "BLACK_SCREEN"}]
    finally:
        gb.GestureEngine = orig_engine


def test_bridge_skips_unbound_gesture():
    import ppt_core.gesture_bridge as gb
    from ppt_core.gesture_bridge import GestureBridge
    captured = []
    class FakeDispatcher:
        def dispatch(self, d): captured.append(d)
    class FakeEngine:
        def __init__(self, **kwargs): pass
        def start(self): return None
        def stop(self): pass
        def start_pairing(self): pass
        def reset_pairing(self): pass
        def save_config(self): pass
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
        bridge.cfg.reset_bindings()
        bridge._on_gesture_event({"type": "gesture", "gesture": "PALM", "slot": "A", "source": "gesture:A"})
        assert captured == []
    finally:
        gb.GestureEngine = orig_engine


def test_bridge_skips_non_a_slot():
    import ppt_core.gesture_bridge as gb
    from ppt_core.gesture_bridge import GestureBridge
    captured = []
    class FakeDispatcher:
        def dispatch(self, d): captured.append(d)
    class FakeEngine:
        def __init__(self, **kwargs): pass
        def start(self): return None
        def stop(self): pass
        def start_pairing(self): pass
        def reset_pairing(self): pass
        def save_config(self): pass
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
        bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
        bridge._on_gesture_event({"type": "gesture", "gesture": "FIST", "slot": "B", "source": "gesture:B"})
        assert captured == []
    finally:
        gb.GestureEngine = orig_engine
