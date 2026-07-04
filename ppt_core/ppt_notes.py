"""PPT slideshow notes reader (COM, pywin32).

Polls the active PowerPoint/WPS slideshow for the current slide's notes and
forwards any changes via a user-supplied ``send_fn`` callback.

Ported from ``ppt_pc_client.py`` so the rest of the codebase no longer needs
to import that monolithic script. Zero Qt dependencies; only requires
``pywin32`` (``win32com.client`` + ``pythoncom``) on Windows.

Usage:

    worker = PptNotesWorker(send_fn=safe_send, get_settings=get_settings)
    worker.start()
    ...
    worker.stop()

The worker runs on a daemon thread. If ``pywin32`` is unavailable the worker
prints a one-time notice and ``start()`` becomes a no-op.
"""

from __future__ import annotations

import os
import threading
import time
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, Optional, Tuple

# Lazy imports of pywin32 — see _ensure_pywin32().
_wc = None  # type: ignore[var-annotated]
_pythoncom = None  # type: ignore[var-annotated]


# MsoShapeType constants — same numeric values across Office and WPS.
_MSO_GROUP = 6
_MSO_TABLE = 19

# Programmatic identifiers to try in order when locating an active slideshow.
_WPS_PROGIDS = ("Kwpp.Application", "wps.Application", "Kingsoft.WPP.Application")

SendFn = Callable[[Dict[str, Any]], None]
GetSettingsFn = Callable[[], Dict[str, Any]]


def _ensure_pywin32() -> bool:
    """Lazily import ``win32com.client`` and ``pythoncom``.

    Returns True on success; on ImportError prints a one-time notice and
    returns False so the caller can abort cleanly without killing the host
    process.
    """
    global _wc, _pythoncom
    if _wc is not None and _pythoncom is not None:
        return True
    try:
        import win32com.client as wc  # type: ignore[import-not-found]
        import pythoncom as pc  # type: ignore[import-not-found]
    except ImportError:
        if not getattr(_ensure_pywin32, "_warned", False):
            setattr(_ensure_pywin32, "_warned", True)
            print("ℹ️ 未安装 pywin32，演讲者模式不可用（pip install pywin32）")
        return False
    _wc = wc
    _pythoncom = pc
    return True


def _ppt_notes_shape_text(sh) -> str:
    """Read text from a single shape on the notes page.

    Tries ``TextFrame2`` first (richer), then falls back to ``TextFrame`` if
    the shape doesn't expose it. Some placeholder shapes lack a reliable
    ``HasTextFrame`` flag, so both paths are wrapped in try/except.
    """
    seen_local = set()
    chunks = []
    for use_tf2 in (True, False):
        try:
            if use_tf2:
                tf = sh.TextFrame2
            else:
                if not getattr(sh, "HasTextFrame", False):
                    continue
                tf = sh.TextFrame
            tr = tf.TextRange
            t = (tr.Text or "").replace("\r", "\n").strip()
            if t and t not in seen_local:
                seen_local.add(t)
                chunks.append(t)
        except Exception:
            continue
    return "\n".join(chunks).strip() if chunks else ""


def _ppt_notes_table_text(sh) -> str:
    """Read text from every cell of a table shape on the notes page."""
    parts = []
    seen = set()
    try:
        tbl = sh.Table
        rows = int(tbl.Rows.Count)
        cols = int(tbl.Columns.Count)
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                try:
                    cell = tbl.Cell(r, c)
                    inner = cell.Shape
                    t = _ppt_notes_shape_text(inner)
                    if t and t not in seen:
                        seen.add(t)
                        parts.append(t)
                except Exception:
                    continue
    except Exception:
        return ""
    return "\n".join(parts).strip()


def _ppt_notes_walk_shapes(shapes, parts: list, seen: set, depth: int = 0) -> None:
    """Recursively walk the notes page's shapes (groups, tables, text boxes)."""
    if depth > 32:
        return
    try:
        cnt = int(shapes.Count)
    except Exception:
        return
    for i in range(1, cnt + 1):
        try:
            sh = shapes.Item(i)
        except Exception:
            continue
        try:
            st = int(sh.Type)
        except Exception:
            st = -1
        if st == _MSO_GROUP:
            try:
                _ppt_notes_walk_shapes(sh.GroupItems, parts, seen, depth + 1)
            except Exception:
                pass
            continue
        if st == _MSO_TABLE:
            tt = _ppt_notes_table_text(sh)
            if tt and tt not in seen:
                seen.add(tt)
                parts.append(tt)
            continue
        t = _ppt_notes_shape_text(sh)
        if t and t not in seen:
            seen.add(t)
            parts.append(t)


def _norm_pair(slide_idx, text: str) -> Tuple[int, str]:
    """Build a hashable (slide_index, text) pair used for de-duplication."""
    if slide_idx is None:
        return (-1, "")
    return (int(slide_idx), text or "")


class PptNotesWorker:
    """Background COM poller that emits slide notes via ``send_fn``.

    The constructor stores its dependencies but does not start any threads;
    call :meth:`start` to spawn the daemon thread. ``stop()`` is idempotent.
    """

    def __init__(
        self,
        *,
        send_fn: SendFn,
        get_settings: GetSettingsFn,
        debug: bool = False,
    ) -> None:
        self._send_fn = send_fn
        self._get_settings = get_settings
        self._debug = bool(debug) or os.environ.get("PPT_NOTES_DEBUG", "").strip().lower() in ("1", "true", "yes")

        self._stop_event: Event = Event()
        self._wake_q: "Queue[bool]" = Queue(maxsize=1)
        self._lock: Lock = Lock()
        self._thread: Optional[Thread] = None

        # (slide_idx, text) or None
        self._last_sent: Optional[Tuple[int, str]] = None
        # One-shot warning flags
        self._warned_slideshow = False
        self._announced_read_ok = False

    # -- public API -------------------------------------------------------

    def start(self) -> None:
        """Spawn the daemon thread. No-op if pywin32 is missing."""
        if not _ensure_pywin32():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            t = Thread(target=self._run, name="ppt-notes", daemon=True)
            self._thread = t
            t.start()

    def stop(self) -> None:
        """Signal the worker to exit and wait briefly for the thread."""
        self._stop_event.set()
        # Wake any blocked _wake_q.get() so the loop notices the stop flag.
        try:
            self._wake_q.put_nowait(True)
        except Exception:
            pass
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=1.5)
        self._thread = None

    def request_refresh(self) -> None:
        """Wake the worker immediately for a fresh poll (no-op if disabled)."""
        try:
            if not (self._get_settings() or {}).get("ppt_notes_enabled", False):
                return
        except Exception:
            # If get_settings blows up, allow the wake anyway; the worker
            # itself will re-check the flag.
            pass
        try:
            self._wake_q.put_nowait(True)
        except Exception:
            # Queue full → a wake is already pending, which is fine.
            pass

    # -- internals --------------------------------------------------------

    def _warn_slideshow_once(self) -> None:
        if self._warned_slideshow:
            return
        try:
            if not (self._get_settings() or {}).get("ppt_notes_enabled", False):
                return
        except Exception:
            return
        self._warned_slideshow = True
        print(
            "ℹ️ 演讲者模式已开启：请在 PowerPoint / WPS 中按 F5（从头）或 Shift+F5（从当前页）进入幻灯片放映；"
            "仅在编辑窗口打开时无法同步备注。"
        )

    def _try_read_once(self):
        """Run one COM read attempt. Returns (slide_index_or_None, text)."""
        assert _wc is not None, "pywin32 must be ensured before _try_read_once"
        app = None
        for progid in ("PowerPoint.Application",) + _WPS_PROGIDS:
            try:
                app = _wc.GetActiveObject(progid)
                if app is not None:
                    break
            except Exception:
                continue
        if app is None:
            if self._debug:
                print("ℹ️ [PPT_NOTES] GetActiveObject 未找到 PowerPoint/WPS，请先打开演示软件并进入放映")
            return None, ""

        try:
            windows = app.SlideShowWindows
            n = int(windows.Count)
        except Exception as ex:
            if self._debug:
                print(f"ℹ️ [PPT_NOTES] 无法访问 SlideShowWindows: {ex!r}")
            return None, ""
        if n < 1:
            self._warn_slideshow_once()
            if self._debug:
                print("ℹ️ [PPT_NOTES] SlideShowWindows.Count=0，当前没有放映窗口")
            return None, ""

        if self._debug:
            print(f"ℹ️ [PPT_NOTES] SlideShowWindows.Count={n}，将依次尝试各窗口")

        slide = None
        idx = None
        for wi in range(1, n + 1):
            try:
                wnd = windows.Item(wi)
                view = wnd.View
                try:
                    idx = int(view.CurrentShowPosition)
                except Exception:
                    idx = None
                sl = None
                try:
                    sl = view.Slide
                except Exception:
                    sl = None
                if sl is None and idx is not None:
                    try:
                        sl = wnd.Presentation.Slides.Item(idx)
                    except Exception:
                        sl = None
                if sl is not None:
                    slide = sl
                    if idx is None:
                        try:
                            idx = int(sl.SlideIndex)
                        except Exception:
                            idx = -1
                    if self._debug:
                        try:
                            pos = view.CurrentShowPosition
                        except Exception:
                            pos = "?"
                        print(
                            f"ℹ️ [PPT_NOTES] 使用放映窗口 #{wi}，CurrentShowPosition={pos} SlideIndex={idx}"
                        )
                    break
            except Exception as ex:
                if self._debug:
                    print(f"ℹ️ [PPT_NOTES] 放映窗口 #{wi} 不可用: {ex!r}")
                continue

        if slide is None:
            if self._debug:
                print("ℹ️ [PPT_NOTES] 所有放映窗口均无法取得当前 Slide")
            return None, ""

        try:
            notes_page = slide.NotesPage
        except Exception as ex:
            if self._debug:
                print(f"ℹ️ [PPT_NOTES] 无法访问 NotesPage: {ex!r}")
            return None, ""

        parts = []
        seen = set()
        try:
            _ppt_notes_walk_shapes(notes_page.Shapes, parts, seen, 0)
        except Exception as ex:
            if self._debug:
                print(f"ℹ️ [PPT_NOTES] 遍历备注页形状失败: {ex!r}")
            return idx, ""

        text = "\n".join(parts).strip()
        if self._debug:
            print(f"ℹ️ [PPT_NOTES] slide={idx} 形状片段数={len(parts)} 备注长度={len(text)}")
            if not text:
                try:
                    sc = int(notes_page.Shapes.Count)
                    print(
                        f"ℹ️ [PPT_NOTES] 备注页共 {sc} 个形状但未解析出文字；"
                        "请确认在「普通视图」备注窗格中输入过内容（非仅默认占位提示）"
                    )
                except Exception:
                    pass
        return idx, text

    def _emit(self, text: str) -> None:
        """Invoke the user's send_fn with a PPT_NOTES payload.

        The room id is intentionally left as a placeholder; the caller wires
        the real value into the payload before dispatching it.
        """
        try:
            self._send_fn({
                "cmd": "PPT_NOTES",
                "roomId": "",
                "text": text or "",
            })
        except Exception as ex:
            if self._debug:
                print(f"ℹ️ [PPT_NOTES] send_fn 回调失败: {ex!r}")

    def _run(self) -> None:
        """Daemon-thread main loop. Owns the COM apartment for this thread."""
        assert _pythoncom is not None
        _pythoncom.CoInitialize()
        try:
            while not self._stop_event.is_set():
                # Gate on the user setting.
                try:
                    enabled = bool((self._get_settings() or {}).get("ppt_notes_enabled", False))
                except Exception:
                    enabled = False
                if not enabled:
                    time.sleep(0.25)
                    continue

                # Wait up to 200ms for an explicit refresh; fall through on timeout.
                try:
                    self._wake_q.get(timeout=0.2)
                    # Drain any extra wakes so we only do one read per burst.
                    while True:
                        try:
                            self._wake_q.get_nowait()
                        except Empty:
                            break
                except Empty:
                    pass

                if self._stop_event.is_set():
                    break

                try:
                    idx, text = self._try_read_once()
                except Exception as ex:
                    if self._debug:
                        print(f"ℹ️ [PPT_NOTES] 读取异常: {ex!r}")
                    continue
                if idx is None:
                    text = ""

                pair = _norm_pair(idx, text)
                should_send = False
                with self._lock:
                    if self._last_sent != pair:
                        self._last_sent = pair
                        should_send = True
                if not should_send:
                    continue

                self._emit(pair[1])

                # One-shot success announcement.
                if pair[1].strip() and not self._announced_read_ok:
                    self._announced_read_ok = True
                    print(
                        f"✅ 演讲者模式：本机已读到内容（{len(pair[1].strip())} 字），"
                        "已通过 send_fn 回调发出。"
                    )
        finally:
            try:
                _pythoncom.CoUninitialize()
            except Exception:
                pass


__all__ = ["PptNotesWorker"]