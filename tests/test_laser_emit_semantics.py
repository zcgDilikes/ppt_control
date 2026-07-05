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
    sem.process([lm], [], on_send_text=None)
    # Second frame: should now emit a per-frame LASER cmd.
    events = sem.process([lm], [], on_send_text=None)
    laser_cmds = [e for e in events if e.get("cmd") == "LASER"]
    assert len(laser_cmds) >= 1, f"expected per-frame LASER cmd, got {events}"
    assert "x" in laser_cmds[0] and "y" in laser_cmds[0]


def test_pointing_up_rising_edge_emits_type_gesture(monkeypatch):
    """I-2: rising edge from NONE to POINTING_UP emits type=gesture once."""
    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    lm = _make_hand_pointing_up()
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_POINTING_UP)
    events = sem.process([lm], [], on_send_text=None)
    gesture_events = [e for e in events if e.get("type") == "gesture"]
    assert any(e.get("gesture") == "POINTING_UP" for e in gesture_events), events


def test_fist_rising_edge_emits_type_gesture_no_laser(monkeypatch):
    """I-2: FIST rising edge emits type=gesture, no per-frame LASER cmd."""
    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    lm = _make_hand_pointing_up()
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_FIST)
    events = sem.process([lm], [], on_send_text=None)
    gesture_events = [e for e in events if e.get("type") == "gesture"]
    assert any(e.get("gesture") == "FIST" for e in gesture_events), events
    laser_cmds = [e for e in events if e.get("cmd") == "LASER"]
    assert laser_cmds == []


def test_swipe_right_emits_with_correct_slot(monkeypatch):
    """Swipe detection must tag the event with the originating slot (A).

    Regression: ``_update_swipe`` referenced an undefined ``slot`` local,
    which would raise NameError when a swipe velocity was reached. The
    fix routes the slot through ``HandState.slot`` instead.
    """
    import time as _time

    cfg = _single_mode_cfg()
    sem = GestureSemantics(cfg)
    # Force classifier to PALM so swipe logic activates for the A-slot hand.
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_PALM)

    # Hand at left side of frame (x=0.2 → slot A).
    lm = _make_hand_pointing_up(x=0.2)
    # Pre-warm: drop a frame so wrist_history has a starting point.
    sem.process([lm], [], on_send_text=None)

    # Pre-populate A-slot wrist_history with stationary samples so the
    # velocity check has a baseline that pre-dates the swipe window.
    st_a = sem._slots["A"]
    base_t = _time.monotonic() - 0.2  # ~200 ms ago
    st_a.wrist_history = [
        (base_t, 0.2),
        (base_t + 0.05, 0.2),
        (base_t + 0.10, 0.2),
    ]
    st_a.last_swire_at = 0.0

    # Jump wrist x to the right but stay inside slot A (x < 0.5).
    # This produces positive wrist velocity → SWIPE_RIGHT.
    lm_fast = _make_hand_pointing_up(x=0.2)
    lm_fast[0] = _P(0.45, 0.6)
    events = sem.process([lm_fast], [], on_send_text=None)

    swipe_events = [e for e in events
                    if e.get("type") == "gesture"
                    and e.get("gesture") in ("SWIPE_LEFT", "SWIPE_RIGHT")]
    assert swipe_events, f"expected a swipe event, got {events}"
    assert swipe_events[0]["slot"] == "A", swipe_events[0]