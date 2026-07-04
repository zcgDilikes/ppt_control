"""HTTP download manager for files received from the mobile peer.

Ports the streaming-download behavior of ``ppt_pc_client.download_file`` /
``start_download_file_async`` into a self-contained class so the rest of the
codebase no longer needs to import the monolithic script.

The manager owns:

* an in-memory ring of the last ``MAX_RECORDS`` completed downloads
  (newest first, thread-safe via an internal ``Lock``);
* a daemon-thread pool that streams HTTP responses to disk without blocking
  the caller (e.g. a WebSocket receive loop);
* Windows shell helpers that reveal a downloaded file in Explorer or open
  the save folder.

The manager does not auto-open PowerPoint files — that policy is decided by
the wiring layer (a separate ``on_ppt_open`` callback may be supplied, but
the manager itself only fires ``on_complete``).

Usage:

    mgr = DownloadManager(
        base_url="https://example.com",
        save_dir="./downloads",
        on_record_added=lambda rec: refresh_gui(),
        on_complete=lambda path, ext: print(path, ext),
    )
    mgr.enqueue("/files/foo.pptx")
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from threading import Lock, Thread
from typing import Callable, Dict, List, Optional

import requests

# Extensions we treat as PowerPoint-compatible documents. Ported verbatim
# from ``ppt_pc_client.PPT_EXTS``.
PPT_EXTS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".pot", ".potx"}

# Maximum number of recent-download records retained in memory.
MAX_RECORDS = 50

# Default HTTP timeout (seconds) for the streaming GET.
_DEFAULT_TIMEOUT = 30.0

# Stream chunk size (bytes) — matches the legacy implementation.
_CHUNK_SIZE = 8192

RecordDict = Dict[str, object]
RecordCallback = Callable[[RecordDict], None]
CompleteCallback = Callable[[str, str], None]
PptOpenCallback = Callable[[str], None]


def _safe_filename_from_uri(uri: str) -> str:
    """Extract a filesystem-safe filename from a URL/URI path component.

    Strips any query string, takes the basename, and falls back to a
    timestamped placeholder if the URI does not yield a usable name.
    """
    try:
        cleaned = str(uri or "").strip()
    except Exception:
        cleaned = ""
    # Strip query string before basename extraction.
    cleaned = cleaned.split("?", 1)[0].split("#", 1)[0]
    name = os.path.basename(cleaned)
    if not name or name in ("/", "\\"):
        name = f"download_{int(time.time() * 1000)}"
    return name


class DownloadManager:
    """Background HTTP download manager.

    Parameters
    ----------
    base_url:
        Server origin that ``enqueue``'d URIs are appended to. The trailing
        slash is normalized so ``"https://x" + "/a"`` and ``"https://x/" + "a"``
        both work.
    save_dir:
        Directory where downloaded files are written. Created if missing.
    on_record_added:
        Optional callback fired (on the download thread) with each new
        ``{name, path, ts}`` record immediately after the file is written.
    on_complete:
        Optional callback fired with ``(abs_path, lowercased_extension)``
        after a successful download.
    on_ppt_open:
        Optional callback fired with ``abs_path`` for downloads whose
        extension is in :data:`PPT_EXTS`. The manager does not invoke
        ``os.startfile`` itself — that policy lives in the caller.
    """

    def __init__(
        self,
        *,
        base_url: str,
        save_dir: str,
        on_record_added: Optional[RecordCallback] = None,
        on_complete: Optional[CompleteCallback] = None,
        on_ppt_open: Optional[PptOpenCallback] = None,
    ) -> None:
        self._base_url = str(base_url or "").rstrip("/")
        self._save_dir = str(save_dir or "").strip() or "."
        self._on_record_added = on_record_added
        self._on_complete = on_complete
        self._on_ppt_open = on_ppt_open

        # Create the save directory eagerly so enqueue() never races with
        # filesystem creation on the first call.
        try:
            os.makedirs(self._save_dir, exist_ok=True)
        except Exception:
            # Best-effort; the worker will retry on its own thread.
            pass

        self._records: List[RecordDict] = []
        self._lock: Lock = Lock()

    # -- public API -------------------------------------------------------

    def enqueue(self, uri: str) -> None:
        """Schedule a background download of ``uri``.

        Returns immediately; the actual HTTP request runs on a daemon
        thread. Empty/blank URIs are ignored. All exceptions raised by
        the worker thread are swallowed.
        """
        if not uri or not str(uri).strip():
            return
        u = str(uri).strip()

        def _run() -> None:
            try:
                self._download_one(u)
            except Exception:
                # Belt-and-braces: _download_one already swallows, but
                # defend against bugs in the plumbing.
                pass

        Thread(target=_run, name="ppt-download", daemon=True).start()

    def records(self) -> List[dict]:
        """Return a snapshot of recent download records (newest first, max 50)."""
        with self._lock:
            # Return shallow copies so callers cannot mutate internal state.
            return [dict(r) for r in self._records[:MAX_RECORDS]]

    def reveal(self, path: str) -> None:
        """Open Explorer with ``path`` selected. Errors are swallowed."""
        try:
            normalized = os.path.normpath(str(path or ""))
            if not normalized:
                return
            subprocess.run(
                ["explorer", "/select,", normalized],
                check=False,
            )
        except Exception:
            pass

    def open_folder(self) -> None:
        """Open Explorer pointing at ``save_dir``. Errors are swallowed."""
        try:
            normalized = os.path.normpath(self._save_dir)
            subprocess.run(
                ["explorer", normalized],
                check=False,
            )
        except Exception:
            pass

    # -- internals --------------------------------------------------------

    def _full_url(self, uri: str) -> str:
        return f"{self._base_url}{uri}"

    def _abs_path_for(self, uri: str) -> str:
        filename = _safe_filename_from_uri(uri)
        return os.path.abspath(os.path.join(self._save_dir, filename))

    def _download_one(self, uri: str) -> None:
        """Worker: perform the streaming GET and persist the result."""
        try:
            url = self._full_url(uri)
            abs_path = self._abs_path_for(uri)
            name = os.path.basename(abs_path)

            resp = requests.get(url, stream=True, timeout=_DEFAULT_TIMEOUT)
            resp.raise_for_status()

            try:
                with open(abs_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
            except Exception:
                # Best-effort cleanup if the write failed mid-stream.
                try:
                    if os.path.isfile(abs_path):
                        os.unlink(abs_path)
                except OSError:
                    pass
                return

            record: RecordDict = {
                "name": name,
                "path": abs_path,
                "ts": time.time(),
            }

            with self._lock:
                self._records.insert(0, record)
                # Bound the list so it never grows past MAX_RECORDS.
                if len(self._records) > MAX_RECORDS:
                    del self._records[MAX_RECORDS:]

            ext = os.path.splitext(abs_path)[1].lower()

            cb = self._on_record_added
            if cb is not None:
                try:
                    cb(record)
                except Exception:
                    pass

            ccb = self._on_complete
            if ccb is not None:
                try:
                    ccb(abs_path, ext)
                except Exception:
                    pass

            if ext in PPT_EXTS:
                popen = self._on_ppt_open
                if popen is not None:
                    try:
                        popen(abs_path)
                    except Exception:
                        pass
        except Exception:
            # Network errors, HTTP errors, permission errors — none of them
            # should ever propagate out of the worker thread.
            pass


__all__ = ["DownloadManager", "PPT_EXTS", "MAX_RECORDS"]