"""双人协作：槽位职责与 cmd 白名单。"""

from __future__ import annotations

from typing import Optional

from .config import GestureConfig


def navigator_slot(cfg: GestureConfig) -> str:
    return "A" if cfg.dual_roles_swapped else "B"


def pointer_slot(cfg: GestureConfig) -> str:
    return "B" if cfg.dual_roles_swapped else "A"


def slot_allows_cmd(cfg: GestureConfig, slot: Optional[str], cmd: str) -> bool:
    if cfg.operator_mode != "dual":
        return True
    if not slot:
        return False
    return cmd in cfg.effective_cmds_for_slot(slot)


def wheel_allowed(cfg: GestureConfig, slot: Optional[str]) -> bool:
    if cfg.operator_mode != "dual":
        return True
    return slot == navigator_slot(cfg)
