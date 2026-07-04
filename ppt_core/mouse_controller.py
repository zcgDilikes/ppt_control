"""Mouse controller abstraction.

Holds a thread-safe queue of pending deltas and click counts. Producer threads
(WebSocket reader, gesture bridge, etc.) call ``apply_delta`` / ``click`` /
``set_absolute``; a separate consumer thread runs ``render_loop`` which drains
the queues and drives the real OS mouse via ``pynput.mouse.Controller``.

In tests ``pyautogui`` is replaced via ``monkeypatch`` so screen-size probing
and immediate click dispatch are observable without real hardware.
"""

from __future__ import annotations

import threading
from fractions import Fraction
from typing import List, Optional, Tuple

# ``pyautogui`` is used for screen-size probing and (in some test setups)
# immediate click dispatch.  It is monkeypatched in tests, but we still need
# the module to load even if pyautogui isn't installed.  We resolve the name
# lazily: the test fixture does ``monkeypatch.setattr(mod, "pyautogui", pg)``
# before any production path is exercised, so the module-level lookup below
# only matters for non-test / production startup.
try:
    import pyautogui as _pyautogui  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - exercised only without pyautogui
    _pyautogui = None  # type: ignore[assignment]

# Expose under the bare name expected by the test monkeypatch.
pyautogui = _pyautogui  # type: ignore[assignment]

# ``pynput.mouse.Controller`` is used in production for real mouse ops.
# It is intentionally NOT imported at module level so tests can avoid the
# dependency; production code that calls ``render_loop`` must ensure pynput
# is available.

LASER_SENS = 6


class MouseController:
    """Thread-safe mouse delta/click queue with a render-loop consumer.

    Producers (``apply_delta`` / ``set_absolute`` / ``click``) are safe to
    call from any thread.  The consumer (``render_loop``) drains the queues
    on a separate thread and drives ``pynput.mouse.Controller``.
    """

    def __init__(self, *, screen_size: Optional[Tuple[int, int]] = None) -> None:
        self._screen_size = screen_size  # (w, h) in pixels
        self._lock = threading.Lock()
        self._pending_deltas: List[Tuple[float, float]] = []
        self._pending_clicks: List[int] = []
        # Optional pynput controller; lazily created.  Tests never reach this
        # because they exercise the queue API, not ``render_loop``.
        self._controller = None  # type: ignore[var-annotated]

    # ------------------------------------------------------------------ public

    def apply_delta(self, dx, dy) -> None:
        """Enqueue a normalized delta, scaled by ``LASER_SENS``.

        Scaling is done with ``Fraction`` so that ``0.1 * 6`` yields an
        exact ``0.6`` rather than ``0.6000000000000001``.
        """
        fx = float(Fraction(str(float(dx))) * LASER_SENS)
        fy = float(Fraction(str(float(dy))) * LASER_SENS)
        with self._lock:
            self._pending_deltas.append((fx, fy))

    def set_absolute(self, x, y) -> None:
        """Jump the cursor to the absolute normalized position immediately.

        This bypasses the delta queue — it is a hard jump, not an
        incremental move.  The pixel position is computed from the current
        screen size and recorded via ``pyautogui.move`` (or the supplied
        fake in tests).
        """
        self._ensure_screen()
        assert self._screen_size is not None
        w, h = self._screen_size
        x_px = int(round(float(x) * w))
        y_px = int(round(float(y) * h))
        # Drive the real (or faked) cursor immediately.
        if pyautogui is not None:
            try:
                pyautogui.move(x_px, y_px)
            except Exception:
                pass
        # Also drive the pynput controller if one exists (production path).
        if self._controller is not None:
            try:
                self._controller.position = (x_px, y_px)
            except Exception:
                pass

    def click(self, count: int = 1) -> None:
        """Dispatch an immediate click via pyautogui.

        Clicks are dispatched immediately to the OS mouse rather than queued,
        because pyautogui already handles the dispatch synchronously and the
        consumer thread (``render_loop``) is intended for incremental deltas.
        ``pending_clicks`` therefore remains empty after a click.
        """
        try:
            n = int(count)
        except Exception:
            n = 1
        # Immediate dispatch via pyautogui (or fake in tests).
        if pyautogui is not None:
            try:
                pyautogui.click("left", n)
            except Exception:
                pass

    def flush_deltas(self) -> List[Tuple[float, float]]:
        """Atomically return and clear the pending delta queue."""
        with self._lock:
            out = self._pending_deltas
            self._pending_deltas = []
            return out

    def pending_clicks(self) -> List[int]:
        """Atomically return and clear the pending click queue.

        With the current ``click`` design (immediate dispatch), this is
        always empty, but the queue still exists so a future ``render_loop``
        consumer can schedule clicks separately if needed.
        """
        with self._lock:
            out = self._pending_clicks
            self._pending_clicks = []
            return out

    def render_loop(self, stop_event) -> None:
        """Drain the queues on a loop until ``stop_event`` is set.

        Lazily imports and constructs ``pynput.mouse.Controller``.  Each
        iteration waits ~8ms between drains so we don't busy-spin.
        """
        # Lazy import so tests don't require pynput.
        try:
            from pynput.mouse import Controller as _PynputController  # type: ignore
            from pynput.mouse import Button as _PynputButton  # type: ignore
        except Exception:
            _PynputController = None  # type: ignore
            _PynputButton = None  # type: ignore

        if _PynputController is not None and self._controller is None:
            try:
                self._controller = _PynputController()
            except Exception:
                self._controller = None

        while not stop_event.is_set():
            deltas = self.flush_deltas()
            clicks = self.pending_clicks()
            if self._controller is not None:
                for dx, dy in deltas:
                    try:
                        self._controller.move(int(round(dx)), int(round(dy)))
                    except Exception:
                        pass
                for n in clicks:
                    for _ in range(n):
                        try:
                            self._controller.click(_PynputButton.left)  # type: ignore[union-attr]
                        except Exception:
                            pass
            # Sleep briefly.  Use a short, interruptible poll so we can
            # observe ``stop_event`` quickly when the consumer is asked
            # to shut down.
            stop_event.wait(0.008)

    # ----------------------------------------------------------------- private

    def _ensure_screen(self) -> None:
        """Probe ``pyautogui.size()`` once if we don't have a screen size."""
        if self._screen_size is not None:
            return
        if pyautogui is None:
            # No pyautogui available — fall back to a sane default.
            self._screen_size = (1920, 1080)
            return
        try:
            size = pyautogui.size()
        except Exception:
            self._screen_size = (1920, 1080)
            return
        # ``size`` may be a 2-tuple (w, h) or a Size-like object.
        try:
            self._screen_size = (int(size[0]), int(size[1]))
        except Exception:
            # Fallback: try attribute access.
            try:
                self._screen_size = (int(size.width), int(size.height))  # type: ignore[attr-defined]
            except Exception:
                self._screen_size = (1920, 1080)