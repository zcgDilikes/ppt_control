"""Settings persistence for the PPT client.

Zero Qt dependencies. Loads/saves a JSON settings file at the project root
(`ppt_pc_client_settings.json`) by default, with the path overridable for
testing and alternate deployments.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Union

DEFAULT_SETTINGS: dict = {
    "screenshot_open_folder": True,
    "transfer_open_folder": True,
    "transfer_open_ppt": True,
    "ppt_notes_enabled": False,
    "open_ppt_path": "",
}

DEFAULT_SETTINGS_FILENAME = "ppt_pc_client_settings.json"


def _resolve_path(path: Union[str, os.PathLike, None]) -> Path:
    """Return an absolute Path for the given input, or the project-root default."""
    if path is None:
        return Path(__file__).resolve().parent.parent / DEFAULT_SETTINGS_FILENAME
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    return p


def _merge_defaults(loaded: Mapping[str, Any]) -> dict:
    """Return a new dict containing DEFAULT_SETTINGS values filled in for missing keys."""
    merged: dict = dict(DEFAULT_SETTINGS)
    for key, value in loaded.items():
        if key in merged:
            merged[key] = value
    return merged


def load_settings(path: Union[str, os.PathLike, None] = None) -> dict:
    """Load settings from disk, falling back to defaults on any error.

    Returns a fresh copy of DEFAULT_SETTINGS merged with any keys present in
    the on-disk file. Any I/O, JSON, or permission error → defaults.
    """
    target = _resolve_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)
    return _merge_defaults(data)


def save_settings(
    data: Mapping[str, Any],
    path: Union[str, os.PathLike, None] = None,
) -> None:
    """Atomically write settings to disk.

    Creates parent directories as needed. Writes to a temp file in the same
    directory then `os.replace`s it into place so the file is never partial.
    """
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Merge into defaults so on-disk file always carries the full schema.
    payload = _merge_defaults(data)

    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise