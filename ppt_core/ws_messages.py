"""WebSocket message parsing and routing helpers for the PPT client.

Defines a tiny JSON-message contract used by phone controllers to drive the
PC client. Each message is a JSON object carrying a `cmd` field plus
payload-specific keys (e.g. `x`/`y` for laser absolute, `dx`/`dy` for laser
delta, `roomId` for join, etc.). The helpers in this module intentionally
have zero I/O and zero Qt dependencies so they can be unit-tested in isolation
and reused by both the live websocket client and any mock harness.
"""

from __future__ import annotations

import json


def parse(raw: str) -> dict | None:
    """Parse a raw websocket JSON string into a command dict.

    Returns ``None`` for any failure mode: invalid JSON, non-dict top-level
    values, or messages missing a non-empty ``cmd`` string. The function
    swallows all exceptions so callers can treat it as a total predicate.
    """
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    cmd = d.get("cmd")
    if not isinstance(cmd, str) or not cmd:
        return None
    return d


def serialize(d: dict) -> str:
    """Serialize a command dict to a JSON string for sending over the wire.

    ``ensure_ascii=False`` so that Chinese room ids and any future CJK
    content in payload fields round-trip cleanly through the phone clients.
    """
    return json.dumps(d, ensure_ascii=False)


def is_laser_delta(d: dict) -> bool:
    """Return True iff ``d`` is a LASER message carrying ``dx``/``dy`` deltas.

    The presence of ``dx`` and ``dy`` (non-None) distinguishes a delta message
    from an absolute ``x``/``y`` laser message; both share the same ``cmd``.
    """
    return (
        d.get("cmd") == "LASER"
        and d.get("dx") is not None
        and d.get("dy") is not None
    )


def is_mouse_click(d: dict) -> bool:
    """Return True iff ``d`` is a MOUSE_CLICK command."""
    return d.get("cmd") == "MOUSE_CLICK"
