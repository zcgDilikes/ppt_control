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

from pc_gesture.engine import GestureEngine


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

    # --------------------------------------------------------------- internal

    def _ensure(self) -> GestureEngine:
        if self._engine is None:
            self._engine = GestureEngine(
                dispatch_fn=self._dispatcher.dispatch,
                on_status=self._on_status,
                on_fps=self._on_fps,
                on_send_text=self._on_send_text,
            )
        return self._engine

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
