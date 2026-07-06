"""Tests for GestureBridge frame_signal + latest_snapshot() API."""

import pytest


def test_bridge_has_latest_snapshot_field():
    """latest_snapshot exists and starts as None."""
    import sys
    monkeypatch = pytest.MonkeyPatch()
    try:
        # Drop cached bridge module so our monkeypatched GestureEngine is
        # picked up by the bridge's ``from pc_gesture.engine import GestureEngine``.
        monkeypatch.delitem(sys.modules, "ppt_core.gesture_bridge", raising=False)
        from ppt_core.gesture_bridge import GestureBridge
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _FakeEngine)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        assert hasattr(bridge, "latest_snapshot")
        assert bridge.latest_snapshot() is None
    finally:
        monkeypatch.undo()


def test_bridge_on_frame_callback_caches_snapshot():
    """The on_frame closure that bridge passes to engine stores into _latest_snapshot."""
    import sys
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.delitem(sys.modules, "ppt_core.gesture_bridge", raising=False)
        from ppt_core.gesture_bridge import GestureBridge
        captured = []
        class _Cap:
            def __init__(self, **kw): captured.append(kw)
            def start(self): return None
            def stop(self): pass
            def start_pairing(self): pass
            def reset_pairing(self): pass
            def save_config(self): pass
            cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
            _semantics = None
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _Cap)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        bridge.start()  # triggers _ensure → _Cap(**kw) captured
        assert "on_frame" in captured[0]
        cb = captured[0]["on_frame"]
        from pc_gesture.types import FrameSnapshot
        snap = FrameSnapshot(timestamp_ms=1, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
        cb(snap)
        assert bridge.latest_snapshot() is snap
    finally:
        monkeypatch.undo()


def test_bridge_frame_signal_emit_on_callback():
    """on_frame callback also emits frame_signal (Qt)."""
    import sys
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    captured_signal = []
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.delitem(sys.modules, "ppt_core.gesture_bridge", raising=False)
        from ppt_core.gesture_bridge import GestureBridge
        class _Cap:
            def __init__(self, **kw): pass
            def start(self): return None
            def stop(self): pass
            def start_pairing(self): pass
            def reset_pairing(self): pass
            def save_config(self): pass
            cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
            _semantics = None
        monkeypatch.setattr("ppt_core.gesture_bridge.GestureEngine", _Cap)
        bridge = GestureBridge(
            dispatcher=_FakeDispatcher(),
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda: None,
        )
        bridge.frame_signal.connect(lambda s: captured_signal.append(s))
        from pc_gesture.types import FrameSnapshot
        snap = FrameSnapshot(timestamp_ms=99, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
        bridge._on_frame(snap)
        assert captured_signal == [snap]
    finally:
        monkeypatch.undo()


# ---- helpers ----

class _FakeDispatcher:
    def __init__(self): self.calls = []
    def dispatch(self, d): self.calls.append(d)


class _FakeEngine:
    """Minimal stand-in for GestureEngine; captures kwargs."""
    instances = []

    def __init__(self, **kw):
        self.kwargs = kw
        self.start_called = False
        self.stop_called = False
        self.start_pairing_called = False
        self.reset_pairing_called = False
        self.save_config_called = 0
        self.cfg = type("C", (), {"dual_roles_swapped": False, "raw": {}})()
        self._semantics = None
        _FakeEngine.instances.append(self)

    def start(self): self.start_called = True; return None
    def stop(self): self.stop_called = True
    def start_pairing(self): self.start_pairing_called = True
    def reset_pairing(self): self.reset_pairing_called = True
    def save_config(self): self.save_config_called += 1
