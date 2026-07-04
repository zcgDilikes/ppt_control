"""Bridge between pc_gesture.GestureEngine and the command dispatcher.

Wraps ``pc_gesture.engine.GestureEngine`` so the rest of the application can
hold a single object that:
  * lazily constructs the engine (only when a feature actually needs it),
  * routes engine-emitted command dicts through ``CommandDispatcher.dispatch``,
  * exposes a small lifecycle surface (``start/stop/start_pairing/reset_pairing/save``),
  * and offers ``swap_roles(bool)`` to toggle dual-hand role assignment at
    runtime, persisting the choice via ``engine.save_config()`` and refreshing
    the active ``_semantics`` instance.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

from pc_gesture.config import load_gesture_config
from pc_gesture.engine import GestureEngine

# Maximum number of recently recognized gestures kept for UI trial polling.
# 32 is enough for ~5 seconds at 150 ms poll cadence with comfortable slack.
_RECENT_GESTURE_LIMIT = 32


# ---------------------------------------------------------------------------
# Action → cmd dict mapping (11 actions → dispatcher payload)
# ---------------------------------------------------------------------------
def _action_to_cmd(action: str, *, default_open_ppt_path: str = "") -> dict:
    """Map a bound action name to the cmd dict the dispatcher expects.

    9 actions are simple ``{cmd: <name>}`` payloads; ``OPEN_PPT`` carries a
    ``path`` field. Unknown / non-string actions return an empty dict so the
    caller can no-op.
    """
    if not isinstance(action, str) or not action:
        return {}
    if action in ("NEXT_PAGE", "PREV_PAGE", "FULL_SCREEN", "FROM_CURRENT",
                  "BLACK_SCREEN", "WHITE_SCREEN", "EXIT", "SCREENSHOT",
                  "PC_WINDOW_MINIMIZE", "PC_WINDOW_RESTORE"):
        return {"cmd": action}
    if action == "OPEN_PPT":
        return {"cmd": "OPEN_PPT", "path": default_open_ppt_path}
    return {}


class GestureBridge:
    """Thin wrapper over ``GestureEngine`` that talks to the dispatcher."""

    def __init__(
        self,
        *,
        dispatcher,
        on_status: Callable[[str], None],
        on_fps: Callable[[float], None],
        on_send_text: Callable[[str], None],
    ) -> None:
        self._dispatcher = dispatcher
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        self._engine: Optional[GestureEngine] = None
        # Bridge-owned GestureConfig so UI calls (set_binding / get_binding /
        # reset_bindings) work before any engine.start(). The engine itself
        # also loads the same JSON file when it boots, so values stay in sync.
        self._cfg = load_gesture_config()
        # Ring buffer of recently recognized gesture events for UI trial
        # polling. Each entry: {"ts": float, "gesture": str, "action": str|None,
        # "source": str}. Entries are appended in ``_on_gesture_event`` and
        # consumed by ``recent_gestures()`` from the Qt thread.
        self._recent_gestures: Deque[Dict[str, object]] = deque(maxlen=_RECENT_GESTURE_LIMIT)

    # --------------------------------------------------------------- internal

    def _ensure(self) -> GestureEngine:
        if self._engine is None:
            self._engine = GestureEngine(
                dispatch_fn=self._on_gesture_event,
                on_status=self._on_status,
                on_fps=self._on_fps,
                on_send_text=self._on_send_text,
            )
        return self._engine

    def _on_gesture_event(self, ev: dict, source: str = "gesture") -> None:
        """Engine raw gesture event entry: filter + binding lookup + dispatch.

        The engine always invokes ``dispatch_fn(event, source)`` (see
        :meth:`pc_gesture.engine.GestureEngine._safe_dispatch`), so the second
        positional ``source`` argument must be accepted even though we only
        use the event payload here.
        """
        if not isinstance(ev, dict):
            return
        if ev.get("type") != "gesture":
            return
        gesture = ev.get("gesture")
        slot = ev.get("slot", "A")
        if slot != "A":
            return
        action = self._cfg.get_binding(gesture)
        if action:
            payload = _action_to_cmd(action, default_open_ppt_path="")
            if payload:
                try:
                    self._dispatcher.dispatch(payload)
                except Exception:
                    pass
        # Always emit a recognized-gesture record so UI / trial polling can
        # observe what the bridge just saw (regardless of whether the binding
        # produced a payload). Unbound gestures are still "recognized" — just
        # no cmd fired.
        self._record_recognized_gesture(gesture, action, ev, source)

    # --------------------------------------------------------------- lifecycle

    def start(self) -> Optional[str]:
        """Start the engine; returns ``None`` on success, error string otherwise."""
        return self._ensure().start()

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    def start_pairing(self) -> None:
        self._ensure().start_pairing()

    def reset_pairing(self) -> None:
        self._ensure().reset_pairing()

    def save(self) -> None:
        """Persist the bridge-owned config to disk.

        The bridge is the source of truth for ``bindings`` (UI mutates
        ``self._cfg``). When the engine exists we mirror our bindings into
        ``engine.cfg`` BEFORE ``engine.save_config()`` runs so the on-disk
        file reflects UI changes. When the engine has not yet been
        constructed, we save our own cfg directly so UI mutations made
        before the user clicks "Start gesture" still persist.
        """
        # Ensure the in-memory cfg's raw view matches our bindings.
        if isinstance(self._cfg.raw, dict):
            self._cfg.raw["bindings"] = dict(self._cfg.bindings)
        if self._engine is not None:
            # Sync bridge-owned bindings into the engine's config object
            # so engine.save_config() writes the latest values.
            try:
                self._engine.cfg.bindings = dict(self._cfg.bindings)
            except Exception:
                pass
            if isinstance(getattr(self._engine.cfg, "raw", None), dict):
                self._engine.cfg.raw["bindings"] = dict(self._cfg.bindings)
            self._engine.save_config()
            return
        # No engine yet — persist the bridge's cfg directly.
        from pc_gesture.config import save_gesture_config
        try:
            save_gesture_config(self._cfg)
        except Exception:
            pass

    # --------------------------------------------------------------- roles

    def swap_roles(self, swapped: bool) -> None:
        """Toggle the dual-hand role assignment at runtime.

        Writes the new value to ``engine.cfg.dual_roles_swapped``, persists it
        via ``engine.save_config()``, and asks the live semantics module to
        reload so the change takes effect immediately.
        """
        eng = self._ensure()
        eng.cfg.dual_roles_swapped = bool(swapped)
        eng.save_config()
        if eng._semantics is not None:
            eng._semantics.reload_config(eng.cfg)

    # --------------------------------------------------------------- access

    @property
    def engine(self) -> Optional[GestureEngine]:
        """The underlying ``GestureEngine`` (None until first use)."""
        return self._engine

    @property
    def cfg(self):
        """Bridge-owned ``GestureConfig`` (bindings live here)."""
        return self._cfg

    # --------------------------------------------------------------- UI hooks

    def _record_recognized_gesture(
        self,
        gesture: Optional[str],
        action: Optional[str],
        ev: dict,
        source: str,
    ) -> None:
        """Append a recognized-gesture record to the bridge's ring buffer.

        Called by :meth:`_on_gesture_event` so the UI's trial panel can
        observe what was recognized, even for unbound gestures (where
        ``action`` is ``None`` and no cmd fires).
        """
        if not gesture:
            return
        try:
            ts = float(ev.get("ts") or 0.0) or time.time()
        except Exception:
            ts = 0.0
        self._recent_gestures.append({
            "ts": ts,
            "gesture": str(gesture),
            "action": action,
            "source": str(source),
        })

    def recent_gestures(self) -> list:
        """Snapshot of recently recognized gestures (oldest → newest)."""
        return list(self._recent_gestures)
