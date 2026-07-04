"""Central command dispatcher for parsed WebSocket messages.

Routes incoming command dicts (already decoded by ``ppt_core.ws_messages.parse``)
to the appropriate subsystem: mouse controller, PPT executor, or callback
hooks for downloads / spotlight / timer overlays / window minimize-restore /
client settings. The dispatcher is thread-safe so it can be called from the
websocket reader thread and any other worker concurrently.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from .ws_messages import is_laser_delta, is_mouse_click, parse


class CommandDispatcher:
    """Route parsed WS command dicts to mouse / PPT / callbacks.

    All callbacks (``status_cb``, ``on_download``, ``on_spotlight``,
    ``on_timer_overlay``, ``on_minimize``, ``on_restore``,
    ``on_client_settings``) are wrapped in try/except so that an exception
    raised in user-supplied code never propagates out of ``dispatch`` —
    dispatch must remain total.
    """

    PPT_CMDS = {
        "NEXT_PAGE", "PREV_PAGE", "FULL_SCREEN", "FROM_CURRENT",
        "BLACK_SCREEN", "WHITE_SCREEN", "EXIT",
        "SEND_TEXT", "SELECT_ALL", "COPY", "PASTE", "DELETE",
        "SCREENSHOT", "OPEN_PPT",
    }

    TIMER_CMDS = {
        "TIMER_OVERLAY_SHOW", "TIMER_OVERLAY_HIDE",
        "TIMER_OVERLAY_PAUSE", "TIMER_OVERLAY_RESUME",
        "TIMER_OVERLAY_RESET",
    }

    def __init__(
        self,
        mouse: Any,
        ppt_executor: Any,
        *,
        status_cb: Optional[Callable[[str], None]] = None,
        on_download: Optional[Callable[[str], None]] = None,
        on_spotlight: Optional[Callable[[Optional[dict]], None]] = None,
        on_timer_overlay: Optional[Callable[[str, dict], None]] = None,
        on_minimize: Optional[Callable[[], None]] = None,
        on_restore: Optional[Callable[[], None]] = None,
        on_client_settings: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._mouse = mouse
        self._ppt_executor = ppt_executor
        self._status_cb = status_cb
        self._on_download = on_download
        self._on_spotlight = on_spotlight
        self._on_timer_overlay = on_timer_overlay
        self._on_minimize = on_minimize
        self._on_restore = on_restore
        self._on_client_settings = on_client_settings
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def dispatch(self, d: dict) -> None:
        """Dispatch one parsed command dict to the appropriate handler.

        Acquires the internal lock so concurrent calls from multiple
        threads are serialized. Unknown commands are silently ignored.
        """
        with self._lock:
            self._dispatch_locked(d)

    def dispatch_many(self, raw_messages: list[str]) -> int:
        """Parse and dispatch a list of raw JSON strings.

        Returns the count of successfully dispatched messages (i.e. raw
        strings that parsed to a valid command dict).
        """
        n = 0
        for raw in raw_messages:
            d = parse(raw)
            if d is None:
                continue
            self.dispatch(d)
            n += 1
        return n

    # ----------------------------------------------------------------- private

    def _dispatch_locked(self, d: dict) -> None:
        cmd = d.get("cmd")

        # LASER — delta vs absolute distinguished by presence of dx/dy.
        if is_laser_delta(d):
            try:
                dx = float(d["dx"])
                dy = float(d["dy"])
                self._mouse.apply_delta(dx, dy)
            except Exception:
                pass
            return

        if cmd == "LASER":
            try:
                x = float(d["x"])
                y = float(d["y"])
                self._mouse.set_absolute(x, y)
            except Exception:
                pass
            return

        if is_mouse_click(d):
            count = d.get("count", 1)
            try:
                count = int(count)
            except Exception:
                count = 1
            self._mouse.click(count)
            return

        if cmd in self.PPT_CMDS:
            self._ppt_executor.execute(d)
            return

        if cmd == "FILE_ARRIVED":
            if self._on_download is not None:
                try:
                    self._on_download(d.get("url", ""))
                except Exception:
                    pass
            return

        if cmd == "CLIENT_SETTINGS":
            if self._on_client_settings is not None:
                try:
                    self._on_client_settings(d)
                except Exception:
                    pass
            return

        if cmd == "PC_WINDOW_MINIMIZE":
            if self._on_minimize is not None:
                try:
                    self._on_minimize()
                except Exception:
                    pass
            return

        if cmd == "PC_WINDOW_RESTORE":
            if self._on_restore is not None:
                try:
                    self._on_restore()
                except Exception:
                    pass
            return

        if cmd in ("SPOTLIGHT_SHOW", "SPOTLIGHT_UPDATE"):
            if self._on_spotlight is not None:
                try:
                    self._on_spotlight(d)
                except Exception:
                    pass
            return

        if cmd == "SPOTLIGHT_HIDE":
            if self._on_spotlight is not None:
                try:
                    self._on_spotlight(None)
                except Exception:
                    pass
            return

        if cmd in self.TIMER_CMDS:
            if self._on_timer_overlay is not None:
                try:
                    payload = {k: v for k, v in d.items() if k != "cmd"}
                    self._on_timer_overlay(cmd, payload)
                except Exception:
                    pass
            return

        # Unknown cmd — ignored silently.