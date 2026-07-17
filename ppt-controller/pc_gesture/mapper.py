"""手势扇区 / 工具 ID → WebSocket 兼容 cmd 载荷。"""

from __future__ import annotations

from typing import Any, Dict, Optional


def tool_id_to_payload(tool_id: str) -> Optional[Dict[str, Any]]:
    tid = (tool_id or "").strip().upper()
    if tid == "PREV_PAGE":
        return {"cmd": "PREV_PAGE"}
    if tid == "NEXT_PAGE":
        return {"cmd": "NEXT_PAGE"}
    if tid == "FULL_SCREEN":
        return {"cmd": "FULL_SCREEN"}
    if tid == "FROM_CURRENT":
        return {"cmd": "FROM_CURRENT"}
    if tid == "BLACK_SCREEN":
        return {"cmd": "BLACK_SCREEN"}
    if tid == "WHITE_SCREEN":
        return {"cmd": "WHITE_SCREEN"}
    if tid == "EXIT":
        return {"cmd": "EXIT"}
    if tid == "SCREENSHOT":
        return {"cmd": "SCREENSHOT"}
    if tid == "OPEN_PPT":
        return {"cmd": "OPEN_PPT"}
    if tid == "SELECT_ALL":
        return {"cmd": "SELECT_ALL"}
    if tid == "COPY":
        return {"cmd": "COPY"}
    if tid == "PASTE":
        return {"cmd": "PASTE"}
    if tid == "DELETE":
        return {"cmd": "DELETE"}
    if tid == "PC_WINDOW_MINIMIZE":
        return {"cmd": "PC_WINDOW_MINIMIZE"}
    if tid == "PC_WINDOW_RESTORE":
        return {"cmd": "PC_WINDOW_RESTORE"}
    if tid == "SPOTLIGHT":
        return {
            "cmd": "SPOTLIGHT_SHOW",
            "cx": 0.5,
            "cy": 0.5,
            "halfW": 0.075,
            "halfH": 0.06,
        }
    if tid == "TIMER":
        return {
            "cmd": "TIMER_OVERLAY_SHOW",
            "mode": "countdown",
            "seconds": 300,
        }
    if tid == "SEND_TEXT":
        return {"cmd": "SEND_TEXT", "_needs_dialog": True}
    return None
