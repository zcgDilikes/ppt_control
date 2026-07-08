"""FrameSnapshot — per-frame state container.

The engine assembles one of these per camera frame and pushes it through
``on_frame`` so the UI can render an embedded preview, a diagnostic panel,
and a status light without polling the engine's internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class HandSnapshot:
    """One detected hand in the frame."""

    slot: str                                   # "A" / "B" / "C"
    wrist_xy: Tuple[float, float]               # (x, y) in [0, 1]
    finger_states: Dict[str, bool]              # {"thumb":True,"index":False,...}
    static_gesture: str                         # FIST / PALM / POINTING_UP / ...
    confidence: float                           # MediaPipe handedness.score
    person_id: int = 0                          # 0=主手,1=副手,2=第三手(3-hand mode)
    recognized_event: Optional[str] = None      # rising-edge gesture if any


@dataclass(frozen=True)
class FrameSnapshot:
    """One camera frame's worth of state."""

    timestamp_ms: int                           # engine monotonic clock, ms
    frame_rgb: Optional[bytes]                  # cv2 BGR→RGB bytes, None if no frame
    frame_w: int
    frame_h: int
    hands: List[HandSnapshot] = field(default_factory=list)


def compute_status_light(snap: FrameSnapshot, *, low_confidence_threshold: float = 0.6) -> str:
    """Map a frame snapshot to one of "red" / "yellow" / "green".

    Rules:
      * no hands             → "red"
      * any hand with gesture and confidence >= threshold → "green"
      * any hand but no gesture OR low confidence        → "yellow"

    When multiple hands are present, the highest-confidence hand drives the
    overall indicator (so a clearly-recognized gesture in slot A still lights
    up green even if slot B is missing).
    """
    if not snap.hands:
        return "red"
    best = max(snap.hands, key=lambda h: h.confidence)
    if best.static_gesture != "NONE" and best.confidence >= low_confidence_threshold:
        return "green"
    return "yellow"