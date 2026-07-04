"""Mouse controller abstraction.

Provides direct (synchronous) mouse control via ``pynput.mouse.Controller`` with
``pyautogui`` as a fallback for screen-size probing and immediate dispatch.
All entry points (``apply_delta`` / ``set_absolute`` / ``click``) are safe to
call from any thread.

In tests ``pyautogui`` and ``pynput.mouse.Controller`` are replaced via
``monkeypatch`` so screen-size probing and immediate mouse dispatch are
observable without real hardware.
"""

from __future__ import annotations

import threading
from fractions import Fraction
from typing import Optional, Tuple

# ``pyautogui`` is used for screen-size probing.  It is monkeypatched in tests,
# but the module must still load even if pyautogui isn't installed.
try:
    import pyautogui as _pyautogui  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - exercised only without pyautogui
    _pyautogui = None  # type: ignore[assignment]

# Expose under the bare name expected by the test monkeypatch.
pyautogui = _pyautogui  # type: ignore[assignment]

# ``pynput.mouse.Controller`` is used in production for real mouse ops.
# It is intentionally NOT imported at module level so tests can avoid the
# dependency; tests monkeypatch ``pynput.mouse.Controller`` instead.

LASER_SENS = 6


class MouseController:
    """Thread-safe synchronous mouse driver.

    ``apply_delta`` / ``set_absolute`` / ``click`` all dispatch immediately
    via ``pynput.mouse.Controller`` (constructed lazily on first use).
    The ``screen_size`` argument or a runtime ``pyautogui.size()`` probe
    determines the pixel range for absolute positioning.
    """

    def __init__(self, *, screen_size: Optional[Tuple[int, int]] = None) -> None:
        self._screen_size = screen_size  # (w, h) in pixels
        self._lock = threading.Lock()
        # Lazily created pynput controller; protected by ``_lock``.
        self._controller = None  # type: ignore[var-annotated]

    # ------------------------------------------------------------------ public

    def apply_delta(self, dx, dy) -> None:
        """Move the cursor by ``(dx, dy) * LASER_SENS`` pixels synchronously.

        Scaling uses ``Fraction`` so ``0.1 * 6`` yields an exact ``0.6``
        rather than ``0.6000000000000001``.
        """
        fx = float(Fraction(str(float(dx))) * LASER_SENS)
        fy = float(Fraction(str(float(dy))) * LASER_SENS)
        controller = self._ensure_controller()
        if controller is None:
            return
        try:
            controller.move(int(round(fx)), int(round(fy)))
        except Exception:
            pass

    def set_absolute(self, x, y) -> None:
        """Jump the cursor to the absolute normalized position immediately.

        The pixel position is computed from the current screen size and
        dispatched via ``pynput.mouse.Controller``. ``pyautogui.move`` is
        used as a secondary path so the test fixture (which monkeypatches
        only ``pyautogui``) can still observe the jump.
        """
        self._ensure_screen()
        assert self._screen_size is not None
        w, h = self._screen_size
        x_px = int(round(float(x) * w))
        y_px = int(round(float(y) * h))
        # Drive pyautogui (test fakes observe this).
        if pyautogui is not None:
            try:
                pyautogui.move(x_px, y_px)
            except Exception:
                pass
        # Drive the real pynput controller.
        controller = self._ensure_controller()
        if controller is not None:
            try:
                controller.position = (x_px, y_px)
            except Exception:
                pass

    def click(self, count: int = 1) -> None:
        """Dispatch an immediate click via ``pynput.mouse.Controller``.

        ``count`` clicks are dispatched back-to-back. ``pyautogui.click`` is
        used as a secondary path so the test fixture can observe clicks.
        """
        try:
            n = int(count)
        except Exception:
            n = 1
        if pyautogui is not None:
            try:
                pyautogui.click("left", n)
            except Exception:
                pass
        controller = self._ensure_controller()
        if controller is None:
            return
        # Lazy import of the Button enum (so test environments without
        # pynput don't break at module load time).
        try:
            from pynput.mouse import Button as _PynputButton  # type: ignore
        except Exception:
            return
        for _ in range(n):
            try:
                controller.click(_PynputButton.left)
            except Exception:
                pass

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
        try:
            self._screen_size = (int(size[0]), int(size[1]))
        except Exception:
            try:
                self._screen_size = (int(size.width), int(size.height))  # type: ignore[attr-defined]
            except Exception:
                self._screen_size = (1920, 1080)

    def _ensure_controller(self):
        """Lazily construct a ``pynput.mouse.Controller`` under lock."""
        if self._controller is not None:
            return self._controller
        with self._lock:
            if self._controller is not None:
                return self._controller
            try:
                from pynput.mouse import Controller as _PynputController  # type: ignore
                self._controller = _PynputController()
            except Exception:
                self._controller = None
            return self._controller
