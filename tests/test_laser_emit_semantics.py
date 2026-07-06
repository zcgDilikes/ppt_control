"""Tests for GestureSemantics laser + rising-edge emit semantics (I-2).

Verifies that:
  * Per-frame POINTING_UP emits ``cmd:LASER`` with x/y (smooth cursor)
  * Rising-edge transition into a static gesture emits ``type=gesture`` once
  * Other static gestures emit rising-edge ``type=gesture`` without laser

Rather than constructing full 21-landmark synthetic hands (which requires
matching MediaPipe's heuristic exactly), we drive ``_process_one_hand``
directly with a hand-crafted HandState and monkeypatched classifier to
isolate the emit logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics, HandState


@dataclass
class _P:
    x: float
    y: float


def _make_hand_pointing_up(x: float = 0.3) -> List[_P]:
    lm: List[_P] = [_P(0.0, 0.0) for _ in range(21)]
    lm[0] = _P(x, 0.6)
    # index tip + other landmarks at known positions (semantics only uses
    # INDEX_TIP + WRIST + sens for the laser block)
    lm[8] = _P(x, 0.2)  # INDEX_TIP (high)
    return lm


def _single_mode_cfg():
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "single"
    cfg.raw["dual_roles_swapped"] = False
    return cfg


def test_laser_emits_per_frame_cmd_laser(monkeypatch):
    """I-2: per-frame POINTING_UP emits cmd:LASER (not type=gesture)."""
    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    lm = _make_hand_pointing_up()

    # Force classifier to return POINTING_UP for both frames.
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_POINTING_UP)
    # First frame: warm up state (rising-edge fires here).
    sem.process([lm], [])
    # Second frame: should now emit a per-frame LASER cmd.
    events = sem.process([lm], [])
    laser_cmds = [e for e in events if e.get("cmd") == "LASER"]
    assert len(laser_cmds) >= 1, f"expected per-frame LASER cmd, got {events}"
    assert "x" in laser_cmds[0] and "y" in laser_cmds[0]


def test_pointing_up_rising_edge_emits_type_gesture(monkeypatch):
    """I-2: rising edge from NONE to POINTING_UP emits type=gesture once."""
    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    lm = _make_hand_pointing_up()
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_POINTING_UP)
    events = sem.process([lm], [])
    gesture_events = [e for e in events if e.get("type") == "gesture"]
    assert any(e.get("gesture") == "POINTING_UP" for e in gesture_events), events


def test_fist_rising_edge_emits_type_gesture_no_laser(monkeypatch):
    """I-2: FIST rising edge emits type=gesture, no per-frame LASER cmd."""
    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    lm = _make_hand_pointing_up()
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_FIST)
    events = sem.process([lm], [])
    gesture_events = [e for e in events if e.get("type") == "gesture"]
    assert any(e.get("gesture") == "FIST" for e in gesture_events), events
    laser_cmds = [e for e in events if e.get("cmd") == "LASER"]
    assert laser_cmds == []