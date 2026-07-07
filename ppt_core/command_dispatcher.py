"""Central command dispatcher for parsed WebSocket messages.

Routes incoming command dicts (already decoded by ``ppt_core.ws_messages.parse``)
to the appropriate subsystem: mouse controller, PPT executor, or callback
hooks for downloads / spotlight / timer overlays / window minimize-restore /
client settings. The dispatcher is thread-safe so it can be called from the
websocket reader thread and any other worker concurrently.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from .ws_messages import is_laser_delta, is_mouse_click, parse


# kasi.txt [1]:LASER/MOUSE_CLICK 是 hot path(60fps),必须走同步路径;
# PPT_CMDS 调 COM 可能阻塞 100-200ms,放线程池。
# 拆开后:
#   - LASER/MOUSE_CLICK: 同步,无锁,无队列 → 激光不卡
#   - 其他命令: 锁内选 cmd,线程池异步执行 → PPT 不阻塞 WS 接收
_FAST_PATH_CMDS = {"LASER", "MOUSE_CLICK"}


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
        # kasi.txt [1]:max_workers 从 2 提到 8,避免 COM 长任务占满 worker
        # 导致 LASER 队列堆积(虽然现在 LASER 不进池了,其他命令并发上限也放宽)
        self._executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="dispatch"
        )

    # ------------------------------------------------------------------ public

    def dispatch(self, d: dict) -> None:
        """Dispatch one parsed command dict to the appropriate handler.

        kasi.txt [1]:拆 fast path。
        - LASER / MOUSE_CLICK 走同步路径,无锁无队列,60fps 激光无延迟
        - 其他命令锁内选 cmd,锁外 submit 到线程池,WS 接收不被 COM 阻塞
        """
        if not isinstance(d, dict):
            return
        cmd = d.get("cmd")
        # Fast path: 鼠标类命令同步执行,无锁无队列
        if cmd in _FAST_PATH_CMDS:
            self._dispatch_mouse(d, cmd)
            return
        # 慢路径:线程池异步执行
        if cmd:
            self._executor.submit(self._dispatch_slow, d)

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

    def shutdown(self, wait: bool = True) -> None:
        """停掉线程池(测试 / 退出时用)"""
        self._executor.shutdown(wait=wait)

    # ----------------------------------------------------------------- private

    def _dispatch_mouse(self, d: dict, cmd: str) -> None:
        """同步执行 mouse 命令,无锁。

        kasi.txt [1]: hot path,被 60fps 激光调用,要最快。
        """
        if is_laser_delta(d):
            try:
                dx = float(d["dx"])
                dy = float(d["dy"])
                self._mouse.apply_delta(dx, dy)
            except Exception:
                pass
            return
        if cmd == "LASER":
            # 绝对定位(没有 dx/dy,但有 x/y)
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

    def _dispatch_slow(self, d: dict) -> None:
        """线程池内执行的慢命令(COM / IO / callbacks)"""
        cmd = d.get("cmd")

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
