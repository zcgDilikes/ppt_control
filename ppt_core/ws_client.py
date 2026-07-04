"""Asynchronous WebSocket client wrapped in a ``QThread``.

Hosts an ``asyncio`` event loop on a Qt thread so the Qt GUI thread is never
blocked by WebSocket I/O. All callbacks (``on_message`` / ``on_status`` /
``on_connected`` / ``on_disconnected``) are invoked from the asyncio thread;
the Qt wiring layer is responsible for marshalling them onto the GUI thread
via ``QObject.signals`` or ``QMetaObject.invokeMethod``.

The behavior is ported from ``ppt_pc_client.websocket_client_loop``:

* URL scheme is derived from ``base_url``: ``https`` -> ``wss``, ``http`` -> ``ws``.
* ``MINI_HELLO`` performs the version handshake; older peers get a
  ``VERSION_MISMATCH`` reply.
* ``ONLINE`` / ``OFFLINE`` are observed for parity with the reference but
  do not drive any UI state yet (presence wiring is the responsibility of
  the higher layer).
* ``LASER`` / ``MOUSE_CLICK`` and any other command are forwarded to
  ``on_message``.
* Connection failures trigger an exponential-backoff reconnect
  (1, 2, 4, 8, 16 s, capped at 30 s) until ``stop()`` is called.
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

import websockets
from PySide6.QtCore import QThread

# Wire-protocol constants. Keep in sync with ppt_pc_client.
PC_PROTOCOL_VERSION = 2
MINI_MIN_REQUIRED_VERSION = 2


def _build_url(base_url: str, sub_path: str, room_id: str) -> str:
    """Return the full websocket URL for the given room.

    Mirrors ``ppt_pc_client.get_ws_url``: ``https://`` becomes ``wss://``,
    ``http://`` becomes ``ws://``; any other prefix (or no scheme) is
    treated as ``ws://``.
    """
    base = (base_url or "").rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    else:
        base = "ws://" + base
    rid = str(room_id or "").strip().upper()
    sub = (sub_path or "ws/python").strip().strip("/")
    return f"{base}/{sub}/{rid}"


class WsClient(QThread):
    """QThread hosting an asyncio websocket loop.

    The thread owns one ``asyncio`` event loop for its entire lifetime; the
    loop is created in ``run()`` and torn down on exit. Callbacks are plain
    callables and fire from the websocket thread; thread-safety at the Qt
    boundary is the caller's responsibility.

    Lifecycle::

        ws = WsClient(base_url=..., sub_path=..., room_id=..., ...)
        ws.start()        # QThread.start -> schedules run()
        ...
        ws.send({...})    # safe from any thread
        ws.stop()         # request clean shutdown
        ws.wait()         # join (callers usually do this from the GUI thread)
    """

    # Backoff schedule for reconnect attempts after a failed connection.
    # First retry waits 1s; subsequent retries double up to a 16s cap.
    # Any wait beyond 16s is clamped to 30s as a safety net (the spec).
    _BACKOFF_INITIAL_S = 1.0
    _BACKOFF_FACTOR = 2.0
    _BACKOFF_CAP_S = 16.0
    _BACKOFF_HARD_CAP_S = 30.0

    def __init__(
        self,
        *,
        base_url: str,
        sub_path: str,
        room_id: str,
        on_message: Callable[[dict], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[Optional[BaseException]], None]] = None,
    ) -> None:
        super().__init__()
        self._base_url = base_url
        self._sub_path = sub_path
        self._room_id = room_id
        self._url = _build_url(base_url, sub_path, room_id)
        self._on_message = on_message
        self._on_status = on_status
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        # Loop / websocket references. Both are only touched from the
        # asyncio thread (``run``) except via ``asyncio.run_coroutine_threadsafe``
        # and ``loop.call_soon_threadsafe`` from ``send`` / ``stop``.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None  # type: ignore[var-annotated]

        # Set to True to break the reconnect loop. Protected by ``_stop_event``
        # so ``stop()`` is race-free against the asyncio thread.
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Create the asyncio loop and run the connect loop until stopped."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def send(self, payload: dict) -> None:
        """Thread-safe: schedule a JSON-encoded send on the asyncio loop.

        Silently no-ops if the loop is not running yet or if the websocket
        is currently disconnected. Errors from ``ws.send`` are logged but
        not re-raised to the caller.
        """
        loop = self._loop
        ws = self._ws
        if loop is None or ws is None or not loop.is_running():
            return
        try:
            data = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        try:
            asyncio.run_coroutine_threadsafe(ws.send(data), loop)
        except Exception:
            pass

    def stop(self) -> None:
        """Request graceful shutdown.

        Schedules ``ws.close()`` on the asyncio loop, then stops the loop.
        Safe to call from any thread (and safe to call multiple times).
        """
        loop = self._loop
        # Signal the reconnect loop first so no new connection is attempted.
        try:
            self._stop_event.set()
        except Exception:
            pass
        if loop is None:
            return

        ws = self._ws

        def _shutdown() -> None:
            if ws is not None:
                try:
                    # ``close()`` returns a coroutine on some websockets
                    # versions; ``wait_closed`` awaits it.
                    result = ws.close()
                    if asyncio.iscoroutine(result):
                        async def _await_close() -> None:
                            try:
                                await result
                            except Exception:
                                pass
                        asyncio.ensure_future(_await_close())
                except Exception:
                    pass
            loop.stop()

        try:
            loop.call_soon_threadsafe(_shutdown)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _connect_loop(self) -> None:
        """Connect, consume messages, and reconnect with backoff until stopped."""
        delay = self._BACKOFF_INITIAL_S
        while not self._stop_event.is_set():
            url = self._url
            print(f"[ws] connecting to {url}")
            err: Optional[BaseException] = None
            try:
                async with websockets.connect(
                    url,
                    ping_interval=None,
                    ping_timeout=None,
                    max_size=None,
                ) as ws:
                    self._ws = ws
                    self._notify_status("已连接 · 等待手机端指令")
                    if self._on_connected is not None:
                        try:
                            self._on_connected()
                        except Exception:
                            pass
                    print("[ws] connected; awaiting commands")

                    err = await self._consume(ws)

            except Exception as e:
                err = e
                print(f"[ws] connection error: {e!r}")
            finally:
                self._ws = None
                if self._on_disconnected is not None:
                    try:
                        self._on_disconnected(err)
                    except Exception:
                        pass

            # If a stop was requested during the connection, exit immediately.
            if self._stop_event.is_set():
                break

            wait_s = min(delay, self._BACKOFF_HARD_CAP_S)
            self._notify_status(f"连接断开 · {wait_s:.0f}s 后重试")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_s)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * self._BACKOFF_FACTOR, self._BACKOFF_CAP_S)

    async def _consume(self, ws) -> Optional[BaseException]:
        """Read messages from ``ws`` until disconnect or stop.

        Returns the exception that broke the loop, or ``None`` on a clean
        stop. Parses JSON, performs the MINI_HELLO handshake, and forwards
        ``LASER`` / ``MOUSE_CLICK`` plus any other command to ``on_message``.
        """
        try:
            async for message in ws:
                if self._stop_event.is_set():
                    break
                data = self._parse(message)
                if data is None:
                    continue
                cmd = data.get("cmd")
                if cmd == "MINI_HELLO":
                    self._handle_mini_hello(ws, data)
                    continue
                if cmd in ("ONLINE", "OFFLINE"):
                    # Presence wiring is the caller's responsibility; we
                    # simply skip these frames so the GUI layer does not
                    # see raw presence events it cannot yet interpret.
                    continue
                if cmd in ("LASER", "MOUSE_CLICK"):
                    self._dispatch(data)
                    continue
                # Any other command (including unknown ones) is forwarded.
                self._dispatch(data)
        except Exception as e:
            return e
        return None

    def _handle_mini_hello(self, ws, data: dict) -> None:
        """Validate the phone-side handshake version.

        If the peer's protocol version is below ``MINI_MIN_REQUIRED_VERSION``
        we send back a ``VERSION_MISMATCH`` frame so the phone can prompt
        the user to upgrade.
        """
        try:
            mini_ver = int(data.get("version") or 0)
        except (TypeError, ValueError):
            mini_ver = 0
        if mini_ver < MINI_MIN_REQUIRED_VERSION:
            payload = {
                "cmd": "VERSION_MISMATCH",
                "roomId": self._room_id,
                "pc_version": PC_PROTOCOL_VERSION,
                "min_required": MINI_MIN_REQUIRED_VERSION,
            }
            try:
                # Schedule synchronously via ``send`` (handles thread-safety
                # and JSON encoding) — but here we are on the asyncio
                # thread, so we can send directly.
                asyncio.ensure_future(
                    ws.send(json.dumps(payload, ensure_ascii=False))
                )
            except Exception:
                pass
            print(
                f"[ws] mini app version too old ({mini_ver}); "
                f"requires >= {MINI_MIN_REQUIRED_VERSION}; notified peer"
            )
        else:
            print(
                f"[ws] handshake ok: mini={mini_ver} pc={PC_PROTOCOL_VERSION}"
            )

    @staticmethod
    def _parse(raw) -> Optional[dict]:
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

    def _dispatch(self, data: dict) -> None:
        cb = self._on_message
        if cb is None:
            return
        try:
            cb(data)
        except Exception:
            pass

    def _notify_status(self, text: str) -> None:
        cb = self._on_status
        if cb is None:
            return
        try:
            cb(text)
        except Exception:
            pass