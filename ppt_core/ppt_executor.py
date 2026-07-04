"""PPT command executor — thin ``pyautogui`` / ``pyperclip`` wrapper.

Routes incoming command dicts (already decoded by ``ppt_core.ws_messages``
and routed via ``ppt_core.command_dispatcher.CommandDispatcher``) to the
appropriate OS-level keyboard / clipboard / file open action.

Supported commands (also enumerated in
``ppt_core.command_dispatcher.CommandDispatcher.PPT_CMDS``):

* ``NEXT_PAGE``         — ``pagedown``
* ``PREV_PAGE``         — ``pageup``
* ``FULL_SCREEN``       — ``f5``
* ``FROM_CURRENT``      — ``shift + f5``
* ``BLACK_SCREEN``      — ``b``
* ``WHITE_SCREEN``      — ``w``
* ``EXIT``              — ``esc``
* ``SEND_TEXT``         — copies ``text`` to the clipboard then ``Ctrl+V``
* ``SELECT_ALL``        — ``Ctrl+A``
* ``COPY``              — ``Ctrl+C``
* ``PASTE``             — ``Ctrl+V``
* ``DELETE``            — ``backspace``
* ``SCREENSHOT``        — saves a screenshot to ``save_dir/screen_<ts>.png``
* ``OPEN_PPT``          — opens an existing ``.pptx``/``...`` file or creates
                          a new empty ``.pptx`` in the system temp dir

All ``pyautogui`` / ``pyperclip`` imports are wrapped in try/except so the
module imports cleanly even when those packages are not installed — every
action that requires them is also guarded with try/except so the executor
fails silently rather than raising into the dispatcher's lock.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Callable, Optional

# ``pyautogui`` is the keyboard / mouse / screenshot driver.  It is the
# heaviest third-party dependency in the stack; we import it defensively so
# that a missing installation doesn't prevent the executor module from
# being imported at all (e.g. during ``python -c "import ..."`` smoke tests
# on a CI box without GUI libraries).
try:
    import pyautogui as _pyautogui  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - exercised only without pyautogui
    _pyautogui = None  # type: ignore[assignment]

# ``pyperclip`` is used to push text into the clipboard for ``SEND_TEXT``.
# It is optional for the rest of the executor — only ``SEND_TEXT`` needs
# it, and that path is wrapped in try/except.
try:
    import pyperclip as _pyperclip  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - exercised only without pyperclip
    _pyperclip = None  # type: ignore[assignment]


# PowerPoint file extensions accepted by ``OPEN_PPT``.  Provided as a module
# constant so callers (e.g. file upload validators) can import it without
# instantiating the executor.
PPT_EXTS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".pot", ".potx"}


class PptExecutor:
    """Execute PPT / slideshow commands via ``pyautogui`` and ``pyperclip``.

    The executor holds no per-instance state beyond ``save_dir`` and the
    optional ``on_screenshot`` callback.  Each ``execute`` call is fire-and-
    forget — there is no queue, no async dispatch, and no return value.

    Parameters
    ----------
    save_dir
        Directory in which to write screenshots produced by the
        ``SCREENSHOT`` command.  Created lazily on first screenshot.
    on_screenshot
        Optional callable invoked with the absolute path of each saved
        screenshot after a successful save.  Failures inside the callback
        are swallowed so that executor never raises into the dispatcher.
    """

    def __init__(
        self,
        *,
        save_dir: str = "./ppt_files/",
        on_screenshot: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._save_dir = save_dir
        self._on_screenshot = on_screenshot

    # ------------------------------------------------------------------ public

    def execute(self, d: dict) -> None:  # noqa: C901 - dispatch table is clearer linear
        """Dispatch one command dict to the matching OS-level action.

        Unknown commands are silently ignored.  Every action is guarded
        against ``pyautogui`` / ``pyperclip`` being unavailable (those
        imports may have failed at module load) and against the underlying
        call itself raising; the executor must never propagate exceptions
        into ``CommandDispatcher.dispatch``'s lock.
        """
        cmd = d.get("cmd")

        if cmd == "NEXT_PAGE":
            self._press("pagedown")
            return

        if cmd == "PREV_PAGE":
            self._press("pageup")
            return

        if cmd == "FULL_SCREEN":
            self._press("f5")
            return

        if cmd == "FROM_CURRENT":
            self._hotkey("shift", "f5")
            return

        if cmd == "BLACK_SCREEN":
            self._press("b")
            return

        if cmd == "WHITE_SCREEN":
            self._press("w")
            return

        if cmd == "EXIT":
            self._press("esc")
            return

        if cmd == "SEND_TEXT":
            self._send_text(d.get("text", ""))
            return

        if cmd == "SELECT_ALL":
            self._hotkey("ctrl", "a")
            return

        if cmd == "COPY":
            self._hotkey("ctrl", "c")
            return

        if cmd == "PASTE":
            self._hotkey("ctrl", "v")
            return

        if cmd == "DELETE":
            # The brief calls for try/except around DELETE explicitly.
            try:
                self._press("backspace")
            except Exception:
                pass
            return

        if cmd == "SCREENSHOT":
            self._screenshot()
            return

        if cmd == "OPEN_PPT":
            self._open_ppt(d.get("path", ""))
            return

        # Unknown cmd — ignored silently, per dispatcher contract.

    # ----------------------------------------------------------------- private

    def _press(self, key: str) -> None:
        if _pyautogui is None:
            return
        try:
            _pyautogui.press(key)
        except Exception:
            pass

    def _hotkey(self, *keys: str) -> None:
        if _pyautogui is None:
            return
        try:
            _pyautogui.hotkey(*keys)
        except Exception:
            pass

    def _send_text(self, text: str) -> None:
        """Push ``text`` into the clipboard then trigger ``Ctrl+V``.

        Both the clipboard write and the paste hotkey are guarded so the
        executor still works (silently doing nothing) when ``pyperclip``
        or ``pyautogui`` are unavailable.
        """
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return
        if _pyperclip is not None:
            try:
                _pyperclip.copy(text)
            except Exception:
                # No clipboard available — fall through and try the paste
                # anyway; on most systems that is a no-op rather than an
                # error, and we have nothing else to do here.
                pass
        self._hotkey("ctrl", "v")

    def _screenshot(self) -> None:
        """Capture the screen, save it, and notify ``on_screenshot``.

        The filename embeds ``int(time.time())`` so successive screenshots
        in the same second collide — that matches the brief and is fine
        for the typical "one screenshot per gesture" workload.  The
        directory is created lazily; ``on_screenshot`` failures are
        swallowed so the executor remains total.
        """
        if _pyautogui is None:
            return
        out_path = os.path.join(self._save_dir, f"screen_{int(time.time())}.png")
        abs_path: Optional[str] = None
        try:
            try:
                os.makedirs(self._save_dir, exist_ok=True)
            except Exception:
                # If we cannot create the directory, bail — there is no
                # useful recovery for a screenshot that cannot be written.
                return
            try:
                _pyautogui.screenshot(out_path)
            except Exception:
                return
            abs_path = os.path.abspath(out_path)
        except Exception:
            return
        if abs_path is not None and self._on_screenshot is not None:
            try:
                self._on_screenshot(abs_path)
            except Exception:
                pass

    def _open_ppt(self, path: str) -> None:
        """Open ``path`` if it exists, else launch a fresh empty ``.pptx``.

        Resolution order:

        1. If ``path`` is a non-empty string that points to an existing
           file with a known PPT extension (or any extension, since the
           caller already validated it), ``os.startfile`` is invoked.
        2. Otherwise create an empty ``.pptx`` in the system temp dir
           (``os.environ['TEMP']`` on Windows, falling back to
           ``tempfile.gettempdir()``) and open that.
        3. ``os.startfile`` is Windows-only; on other platforms this
           silently does nothing because the project as a whole is
           Windows-only (``ppt_pc_client`` is a desktop app for Windows).
        """
        target: Optional[str] = None

        if isinstance(path, str) and path:
            try:
                if os.path.isfile(path):
                    target = path
            except Exception:
                target = None

        if target is None:
            try:
                temp_root = os.environ.get("TEMP") or tempfile.gettempdir()
                # ``mkstemp`` returns ``(fd, name)``; close the fd
                # immediately — we only need the path.  An empty file is
                # created on disk; PowerPoint will treat it as a blank
                # document when launched via ``os.startfile``.
                fd, name = tempfile.mkstemp(suffix=".pptx", dir=temp_root)
                try:
                    os.close(fd)
                except Exception:
                    pass
                target = name
            except Exception:
                # If we cannot even create a temp file, there is nothing
                # useful we can do here.
                return

        try:
            os.startfile(target)  # type: ignore[attr-defined]  # Windows-only
        except Exception:
            # ``os.startfile`` may fail for a number of reasons (no file
            # association, no PowerPoint installed, etc).  Swallow —
            # caller cannot meaningfully react, and the executor's
            # contract is total.
            pass
