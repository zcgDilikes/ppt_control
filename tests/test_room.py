"""Tests for ppt_core.room."""

import json
import re
from pathlib import Path

from ppt_core.room import load_or_create_room_id, save_room_id

ROOM_ID_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


def test_first_call_creates_and_persists(tmp_path: Path):
    """First call returns a 6-char uppercase alphanumeric id and writes the file."""
    room_path = tmp_path / "room.json"
    assert not room_path.exists()

    rid = load_or_create_room_id(path=room_path)

    assert isinstance(rid, str)
    assert ROOM_ID_PATTERN.match(rid), f"id {rid!r} does not match [A-Z0-9]{{6}}"
    assert room_path.exists()
    # Persisted payload is a JSON object with the same id
    saved = json.loads(room_path.read_text(encoding="utf-8"))
    assert saved.get("room_id") == rid


def test_subsequent_call_returns_same_id(tmp_path: Path):
    """A second call against the existing file returns the same id."""
    room_path = tmp_path / "room.json"

    first = load_or_create_room_id(path=room_path)
    second = load_or_create_room_id(path=room_path)

    assert first == second
    assert ROOM_ID_PATTERN.match(second)


def test_save_room_id_overwrites(tmp_path: Path):
    """save_room_id then load_or_create returns the saved value."""
    room_path = tmp_path / "room.json"

    save_room_id("ABC123", path=room_path)
    assert room_path.exists()

    loaded = load_or_create_room_id(path=room_path)

    assert loaded == "ABC123"