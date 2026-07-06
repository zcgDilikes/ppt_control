"""Tests for pc_gesture.types — FrameSnapshot / HandSnapshot / compute_status_light."""

import pytest

from pc_gesture.types import FrameSnapshot, HandSnapshot, compute_status_light


def _hand(
    *,
    slot="A",
    wrist=(0.5, 0.5),
    thumb=True,
    index=False,
    middle=False,
    ring=False,
    pinky=False,
    gesture="FIST",
    confidence=0.85,
):
    return HandSnapshot(
        slot=slot,
        wrist_xy=wrist,
        finger_states={"thumb": thumb, "index": index, "middle": middle, "ring": ring, "pinky": pinky},
        static_gesture=gesture,
        confidence=confidence,
        recognized_event=gesture if gesture != "NONE" else None,
    )


def test_hand_snapshot_field_round_trip():
    h = _hand()
    assert h.slot == "A"
    assert h.wrist_xy == (0.5, 0.5)
    assert h.finger_states["thumb"] is True
    assert h.static_gesture == "FIST"
    assert h.confidence == 0.85
    assert h.recognized_event == "FIST"


def test_hand_snapshot_recognized_event_none_when_no_gesture():
    h = _hand(gesture="NONE")
    assert h.recognized_event is None


def test_frame_snapshot_immutable_dataclass():
    snap = FrameSnapshot(
        timestamp_ms=12345,
        frame_rgb=b"\xff\x00\x00" * 4,
        frame_w=2,
        frame_h=2,
        hands=[_hand()],
    )
    assert snap.timestamp_ms == 12345
    assert snap.frame_w == 2
    assert snap.frame_h == 2
    assert len(snap.hands) == 1
    with pytest.raises(Exception):
        snap.frame_w = 99  # frozen dataclass → raises FrozenInstanceError


def test_status_light_red_when_no_hands():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[])
    assert compute_status_light(snap) == "red"


def test_status_light_yellow_when_hand_but_no_gesture():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(gesture="NONE")])
    assert compute_status_light(snap) == "yellow"


def test_status_light_yellow_when_low_confidence():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(confidence=0.4)])
    assert compute_status_light(snap) == "yellow"


def test_status_light_green_when_gesture_recognized_high_confidence():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(gesture="FIST", confidence=0.85)])
    assert compute_status_light(snap) == "green"


def test_status_light_threshold_is_parameter():
    snap = FrameSnapshot(timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0, hands=[_hand(confidence=0.55)])
    # Default 0.6 → 0.55 < 0.6 → yellow
    assert compute_status_light(snap) == "yellow"
    # Custom threshold 0.5 → 0.55 >= 0.5 → green
    assert compute_status_light(snap, low_confidence_threshold=0.5) == "green"


def test_status_light_uses_highest_confidence_hand():
    """With two hands, the brighter signal wins (drives overall indicator)."""
    snap = FrameSnapshot(
        timestamp_ms=0, frame_rgb=None, frame_w=0, frame_h=0,
        hands=[_hand(slot="B", confidence=0.3, gesture="NONE"), _hand(slot="A", confidence=0.9, gesture="FIST")],
    )
    assert compute_status_light(snap) == "green"