"""Room-id persistence for the PPT client.

A room id is a 6-character uppercase alphanumeric code used to identify the
PC client to phone controllers. Stored at `ppt_pc_client_room.json` at the
project root by default. Zero Qt dependencies.
"""

from __future__ import annotations

import json
import os
import random
import re
import string
import tempfile
from pathlib import Path
from typing import Union

ROOM_ID_LENGTH = 6
ROOM_ID_PATTERN = re.compile(r"^[A-Z0-9]{6}$")
ROOM_ID_ALPHABET = string.ascii_uppercase + string.digits

DEFAULT_ROOM_FILENAME = "ppt_pc_client_room.json"


def _resolve_path(path: Union[str, os.PathLike, None]) -> Path:
    """Return an absolute Path for the given input, or the project-root default."""
    if path is None:
        return Path(__file__).resolve().parent.parent / DEFAULT_ROOM_FILENAME
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    return p


def _generate() -> str:
    """Generate a fresh 6-char uppercase alphanumeric room id."""
    return "".join(random.choices(ROOM_ID_ALPHABET, k=ROOM_ID_LENGTH))


def _is_valid(rid: object) -> bool:
    return isinstance(rid, str) and bool(ROOM_ID_PATTERN.match(rid))


def load_or_create_room_id(path: Union[str, os.PathLike, None] = None) -> str:
    """Return the persisted room id, creating + persisting one if absent or invalid."""
    target = _resolve_path(path)
    rid: object = None
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                rid = payload.get("room_id")
        except Exception:
            rid = None

    if not _is_valid(rid):
        rid = _generate()
        save_room_id(rid, path=target)
        return rid

    return rid  # type: ignore[return-value]


def save_room_id(rid: str, path: Union[str, os.PathLike, None] = None) -> None:
    """Atomically write the given room id to disk.

    Creates parent directories as needed. Uses a temp-file + os.replace so the
    file is never partially written.
    """
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"room_id": rid}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
