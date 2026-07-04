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

from typing import Callable, Optional

from pc_gesture.config import load_gesture_config
from pc_gesture.engine import GestureEngine


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
        trial_mode: bool = False,
    ) -> None:
        self._dispatcher = dispatcher
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        self._trial_mode = bool(trial_mode)
        self._engine: Optional[GestureEngine] = None
        # Bridge-owned GestureConfig so UI calls (set_binding / get_binding /
        # reset_bindings) work before any engine.start(). The engine itself
        # also loads the same JSON file when it boots, so values stay in sync.
        self._cfg = load_gesture_config()

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

    def _on_gesture_event(self, ev: dict) -> None:
        """Engine raw gesture event entry: filter + binding lookup + dispatch."""
        if not isinstance(ev, dict):
            return
        if ev.get("type") != "gesture":
            return
        gesture = ev.get("gesture")
        slot = ev.get("slot", "A")
        if slot != "A":
            return
        action = self._cfg.get_binding(gesture)
        if not action and not self._trial_mode:
            return
        if not action:
            return
        payload = _action_to_cmd(action, default_open_ppt_path="")
        if payload:
            try:
                self._dispatcher.dispatch(payload)
            except Exception:
                pass

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
        if self._engine is not None:
            self._engine.save_config()

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
