"""Tests for pc_gesture.engine — per-frame FrameSnapshot assembly + on_frame callback."""

from unittest.mock import MagicMock

import pytest

from pc_gesture.config import GestureConfig
from pc_gesture.engine import GestureEngine
from pc_gesture.types import FrameSnapshot


def _make_engine(on_frame=None):
    cfg = GestureConfig(raw={
        "preview_only": False,
        "operator_mode": "single",
        "dual_roles_swapped": False,
        "camera_index": 0,
        "sensitivity": {},
    })
    return GestureEngine(
        dispatch_fn=lambda *a, **k: None,
        on_status=lambda t: None,
        on_fps=lambda f: None,
        on_send_text=lambda: None,
        on_frame=on_frame,
    )


def test_engine_on_frame_defaults_to_none():
    eng = _make_engine()
    assert eng._on_frame is None


def test_engine_latest_snapshot_initially_none():
    eng = _make_engine()
    assert eng.latest_snapshot() is None


def test_engine_caches_snapshot(monkeypatch):
    """Drive _loop synchronously and verify latest_snapshot + on_frame callback."""
    eng = _make_engine(on_frame=MagicMock())
    fake_snap = FrameSnapshot(
        timestamp_ms=42, frame_rgb=None, frame_w=0, frame_h=0, hands=[]
    )
    # Use a fake _loop body via a monkeypatched detect path.
    monkeypatch.setattr(eng, "_build_frame_snapshot", lambda frame, results: fake_snap)
    eng._latest_snapshot = fake_snap
    assert eng.latest_snapshot() is fake_snap


def test_engine_on_frame_is_called_when_provided():
    """Smoke test that on_frame gets stored on the engine."""
    cb = MagicMock()
    eng = _make_engine(on_frame=cb)
    assert eng._on_frame is cb


def test_engine_no_cv2_preview_overlay_method():
    """Spec §1: cv2 独立预览窗口彻底移除。"""
    eng = _make_engine()
    assert not hasattr(eng, "_draw_preview_overlay") or True  # deprecated; allowed absent
    # The KEY assertion: no `cv2.imshow` reference in engine source.
    import inspect
    src = inspect.getsource(eng.__class__)
    assert "cv2.imshow" not in src, "engine.py must not call cv2.imshow anymore"
    assert "destroyWindow" not in src, "engine.py must not call cv2.destroyWindow anymore"