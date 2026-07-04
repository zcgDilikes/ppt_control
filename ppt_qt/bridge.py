"""Qt signal bridge for marshalling events from worker threads to the GUI.

Asyncio callbacks (WebSocket receive loop), DownloadManager workers, and the
gesture engine all run off the Qt main thread. Directly mutating Qt widgets
from those threads is unsafe: it can race the event loop, corrupt internal
state, or trigger Qt's "QObject: Cannot create children for a parent that is
in a different thread" assertions.

This module exposes a ``QtBridge(QObject)`` whose ``Signal`` members are
``emit``ted from any thread. Qt automatically delivers ``Signal`` emissions to
slots connected on the GUI thread using a ``QueuedConnection``, so consumers
simply connect slots in the composition root and the bridge is the single
object that worker threads call.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal


class QtBridge(QObject):
    """Thread-safe bridge between worker threads and the Qt main thread."""

    # Status text updates (websocket / gesture / etc.)
    ws_status = Signal(str)
    # Connection state transitions.
    ws_connected = Signal()
    ws_disconnected = Signal(object)  # err: Optional[BaseException]
    ws_fatal_disconnect = Signal(str, int)  # err_msg, attempts
    # Downloads.
    file_arrived = Signal(str)
    record_added = Signal(object)  # dict
    # PPT notes
    notes_send = Signal(object)  # dict payload
    # Spotlight: payload is dict on show/update, None on hide.
    spotlight = Signal(object)  # dict | None

    def emit_ws_status(self, text: str) -> None:
        self.ws_status.emit(str(text))

    def emit_ws_connected(self) -> None:
        self.ws_connected.emit()

    def emit_ws_disconnected(self, err: Optional[BaseException]) -> None:
        self.ws_disconnected.emit(err)

    def emit_ws_fatal(self, err: Optional[BaseException], attempts: int) -> None:
        msg = ""
        if err is not None:
            try:
                msg = str(err)
            except Exception:
                msg = repr(err)
        self.ws_fatal_disconnect.emit(msg, int(attempts))

    def emit_file_arrived(self, url: str) -> None:
        self.file_arrived.emit(str(url))

    def emit_record_added(self, record: dict) -> None:
        self.record_added.emit(record)

    def emit_notes_send(self, payload: dict) -> None:
        self.notes_send.emit(dict(payload))

    def emit_spotlight(self, payload: Optional[dict]) -> None:
        """payload None means hide; non-None dict means show/update."""
        self.spotlight.emit(payload)
