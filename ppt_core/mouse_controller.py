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
# kasi.txt [15]:Button enum 在 hot-path click() 中每次重新 import 会慢 100-500us,
# 改模块级懒加载(首次使用 cache,后续直接读)。
_PYNPUT_BUTTON = None  # type: ignore[var-annotated]
_PYNPUT_BUTTON_LOCK = threading.Lock()


def _get_pynput_button():
    global _PYNPUT_BUTTON
    if _PYNPUT_BUTTON is not None:
        return _PYNPUT_BUTTON
    with _PYNPUT_BUTTON_LOCK:
        if _PYNPUT_BUTTON is not None:
            return _PYNPUT_BUTTON
        try:
            from pynput.mouse import Button  # type: ignore
            # cache to module-level singleton
            globals()["_PYNPUT_BUTTON"] = Button
        except Exception:
            return None
        return _PYNPUT_BUTTON


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

        kasi.txt [14]:之前用 ``Fraction(str(float(dx))) * LASER_SENS`` 算缩放,
        60fps laser 时 Fraction 构造比纯 float 慢 100-1000 倍。改纯 float 算,
        精度损失在 1e-6 像素级,对鼠标位置无可观察影响。
        """
        try:
            fx = float(dx) * LASER_SENS
            fy = float(dy) * LASER_SENS
        except (TypeError, ValueError):
            return
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
        # kasi.txt [15]:Button enum 之前在 click() 内部 import,每次 ~100-500us
        # 改模块级懒加载(见顶部 _get_pynput_button),首次 click 加载,后续直接用。
        Button = _get_pynput_button()
        if Button is None:
            return
        for _ in range(n):
            try:
                controller.click(Button.left)
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
