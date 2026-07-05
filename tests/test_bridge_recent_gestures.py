"""Tests for GestureBridge: recent-gesture ring buffer + dispatch signature.

Covers I-3 (recent_gestures buffer) and the dispatch signature used by
GestureEngine._safe_dispatch (event, source).
"""
from __future__ import annotations

import os
import tempfile
import pytest

from pc_gesture.config import load_gesture_config
from ppt_core.gesture_bridge import GestureBridge


class _FakeDispatcher:
    def __init__(self):
        self.calls = []

    def dispatch(self, d):
        self.calls.append(d)


class _FakeEngine:
    instances = []

    def __init__(self, *, dispatch_fn, on_status, on_fps, on_send_text):
        self.kwargs = {
            "dispatch_fn": dispatch_fn,
            "on_status": on_status,
            "on_fps": on_fps,
            "on_send_text": on_send_text,
        }
        self.start_called = False
        self.stop_called = False
        self.start_pairing_called = False
        self.reset_pairing_called = False
        self.save_config_called = 0
        self.cfg = load_gesture_config()
        self._semantics = None
        _FakeEngine.instances.append(self)

    def start(self):
        self.start_called = True
        return None

    def stop(self):
        self.stop_called = True

    def start_pairing(self):
        self.start_pairing_called = True

    def reset_pairing(self):
        self.reset_pairing_called = True

    def save_config(self):
        self.save_config_called += 1
        # Mirror the real engine: actually persist the config so disk
        # round-trip tests work.
        from pc_gesture.config import save_gesture_config
        save_gesture_config(self.cfg)


def _make_bridge(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, "ppt_core.gesture_bridge", raising=False)
    monkeypatch.delitem(sys.modules, "pc_gesture.engine", raising=False)
    monkeypatch.delitem(sys.modules, "pc_gesture", raising=False)
    import ppt_core.gesture_bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "GestureEngine", _FakeEngine)
    bridge = bridge_mod.GestureBridge(
        dispatcher=_FakeDispatcher(),
        on_status=lambda s: None,
        on_fps=lambda f: None,
        on_send_text=lambda t: None,
    )
    return bridge_mod, bridge


def test_on_gesture_event_accepts_source_arg(monkeypatch):
    """C-1: _on_gesture_event must accept (ev, source) — engine calls with 2 args."""
    _mod, bridge = _make_bridge(monkeypatch)
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    # Engine actually calls with positional 2nd arg "gesture"
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"},
        "gesture",
    )
    assert bridge._dispatcher.calls == [{"cmd": "BLACK_SCREEN"}]


def test_recent_gestures_records_recognized_gesture(monkeypatch):
    """I-3: bridge records every recognized gesture (bound or unbound) for UI."""
    _mod, bridge = _make_bridge(monkeypatch)
    # Reset to defaults — the bridge loads the user's real config from disk,
    # so PALM's binding may not be None if the user has customized it.
    bridge.cfg.reset_bindings()
    bridge.cfg.set_binding("FIST", "BLACK_SCREEN")
    # Bound: records action
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "A", "source": "gesture:A"},
        "gesture",
    )
    # Unbound: still recorded (action=None)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "PALM", "slot": "A", "source": "gesture:A"},
        "gesture",
    )
    # Non-A slot: not recorded (skipped earlier)
    bridge._on_gesture_event(
        {"type": "gesture", "gesture": "FIST", "slot": "B", "source": "gesture:B"},
        "gesture",
    )

    recent = bridge.recent_gestures()
    gestures = [r["gesture"] for r in recent]
    actions = [r["action"] for r in recent]
    assert gestures == ["FIST", "PALM"]
    assert actions == ["BLACK_SCREEN", None]


def test_save_persists_bridge_bindings_to_disk(monkeypatch, tmp_path):
    """C-2: bridge.save() persists UI-set binding via disk reload round-trip.

    Uses a temporary config file patched into both the bridge and engine so
    the test does not pollute the user's real config.
    """
    _mod, bridge = _make_bridge(monkeypatch)
    # Override the default path in BOTH the bridge and the engine to a temp
    # file. The engine's save_config() calls save_gesture_config(cfg) which
    # defaults to GESTURE_CONFIG_PATH; we must rewrite that global so the
    # engine writes to the temp file too.
    import pc_gesture.config as cfg_mod
    cfg_path = tmp_path / "g.json"
    orig_path = cfg_mod.GESTURE_CONFIG_PATH
    cfg_mod.GESTURE_CONFIG_PATH = str(cfg_path)
    try:
        # Fresh config objects tied to the temp path.
        bridge._cfg = load_gesture_config(path=str(cfg_path))
        bridge.cfg.set_binding("FIST", "NEXT_PAGE")
        # Force engine creation so save() syncs into engine.cfg + writes file.
        bridge._engine = _FakeEngine(
            dispatch_fn=lambda *a, **k: None,
            on_status=lambda t: None,
            on_fps=lambda f: None,
            on_send_text=lambda t: None,
        )
        bridge._engine.cfg = load_gesture_config(path=str(cfg_path))
        bridge.save()

        # Round-trip: reload from disk and verify the UI change persisted.
        reloaded = load_gesture_config(path=str(cfg_path))
        assert reloaded.get_binding("FIST") == "NEXT_PAGE"
    finally:
        cfg_mod.GESTURE_CONFIG_PATH = orig_path


def test_trial_mode_removed(monkeypatch):
    """I-1: trial_mode is dead code — attribute should not exist."""
    _mod, bridge = _make_bridge(monkeypatch)
    assert not hasattr(bridge, "_trial_mode")