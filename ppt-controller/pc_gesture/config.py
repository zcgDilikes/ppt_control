"""手势配置加载与模型路径。"""

from __future__ import annotations

import json
import os
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GESTURE_CONFIG_PATH = os.path.join(SCRIPT_DIR, "ppt_pc_client_gesture.json")
MODEL_DIR = os.path.join(SCRIPT_DIR, "pc_gesture", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "gesture_recognizer.task")
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)

DEFAULT_ROI = {"x": 0.225, "y": 0.15, "w": 0.55, "h": 0.7}
DEFAULT_DUAL_ROI = {
    "a": {"x": 0.1, "y": 0.15, "w": 0.38, "h": 0.7},
    "b": {"x": 0.52, "y": 0.15, "w": 0.38, "h": 0.7},
}

POINTER_CMDS = [
    "LASER",
    "MOUSE_CLICK",
    "SPOTLIGHT_SHOW",
    "SPOTLIGHT_UPDATE",
    "SPOTLIGHT_HIDE",
    "TIMER_OVERLAY_SHOW",
    "TIMER_OVERLAY_PAUSE",
    "TIMER_OVERLAY_RESUME",
    "TIMER_OVERLAY_RESET",
    "TIMER_OVERLAY_HIDE",
]

NAVIGATOR_CMDS = [
    "PREV_PAGE",
    "NEXT_PAGE",
    "BLACK_SCREEN",
    "WHITE_SCREEN",
    "FULL_SCREEN",
    "FROM_CURRENT",
    "EXIT",
    "SCREENSHOT",
    "OPEN_PPT",
    "SELECT_ALL",
    "COPY",
    "PASTE",
    "DELETE",
    "PC_WINDOW_MINIMIZE",
    "PC_WINDOW_RESTORE",
    "SEND_TEXT",
]

DEFAULT_WHEEL_SECTORS = [
    "SCREENSHOT",
    "FROM_CURRENT",
    "OPEN_PPT",
    "SELECT_ALL",
    "COPY",
    "PASTE",
    "DELETE",
    "SPOTLIGHT",
    "TIMER",
    "PC_WINDOW_MINIMIZE",
    "PC_WINDOW_RESTORE",
    "SEND_TEXT",
]

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "preview_only": False,
    "camera_index": 0,
    "mirror": True,
    "operator_mode": "single",
    "dual_roles_swapped": False,
    "center_roi": dict(DEFAULT_ROI),
    "dual_roi": deepcopy(DEFAULT_DUAL_ROI),
    "max_hands_detect": 4,
    "num_hands_single": 2,
    "wrist_pair_max_dist": 0.35,
    "primary_switch_hold_ms": 1500,
    "primary_leave_unlock_ms": 2000,
    "score_threshold": 0.72,
    "vote_frames": 3,
    "laser_sens": 6,
    "armed_required": True,
    "laser_without_armed": True,
    "wheel_hold_ms": 800,
    "cooldown_ms": {
        "PREV_PAGE": 600,
        "NEXT_PAGE": 600,
        "FULL_SCREEN": 1500,
        "EXIT": 1200,
        "BLACK_SCREEN": 800,
        "WHITE_SCREEN": 800,
        "SCREENSHOT": 2000,
        "MOUSE_CLICK": 300,
    },
    "multi_person_policy": {"two": "cautious", "three_plus": "strict"},
    "dual_roles": {
        "pointer": {"label": "指控", "cmds": list(POINTER_CMDS)},
        "navigator": {"label": "导航", "cmds": list(NAVIGATOR_CMDS)},
    },
    "wheel_sectors": list(DEFAULT_WHEEL_SECTORS),
}


@dataclass
class GestureConfig:
    raw: Dict[str, Any] = field(default_factory=lambda: deepcopy(DEFAULTS))

    def get(self, key: str, default=None):
        return self.raw.get(key, default)

    @property
    def enabled(self) -> bool:
        return bool(self.raw.get("enabled"))

    @property
    def preview_only(self) -> bool:
        return bool(self.raw.get("preview_only"))

    @property
    def operator_mode(self) -> str:
        return str(self.raw.get("operator_mode") or "single")

    @property
    def dual_roles_swapped(self) -> bool:
        return bool(self.raw.get("dual_roles_swapped"))

    def num_hands(self) -> int:
        if self.operator_mode == "dual":
            return int(self.raw.get("max_hands_detect") or 4)
        return int(self.raw.get("num_hands_single") or 2)

    def effective_cmds_for_slot(self, slot: str) -> List[str]:
        roles = self.raw.get("dual_roles") or DEFAULTS["dual_roles"]
        pointer = list((roles.get("pointer") or {}).get("cmds") or POINTER_CMDS)
        navigator = list((roles.get("navigator") or {}).get("cmds") or NAVIGATOR_CMDS)
        swapped = self.dual_roles_swapped
        if slot == "A":
            return navigator if swapped else pointer
        return pointer if swapped else navigator

    def slot_role_label(self, slot: str) -> str:
        roles = self.raw.get("dual_roles") or DEFAULTS["dual_roles"]
        swapped = self.dual_roles_swapped
        if slot == "A":
            key = "navigator" if swapped else "pointer"
        else:
            key = "pointer" if swapped else "navigator"
        return str((roles.get(key) or {}).get("label") or key)


def _merge_defaults(data: Optional[Dict]) -> Dict[str, Any]:
    merged = deepcopy(DEFAULTS)
    if not data:
        return merged
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


def load_gesture_config() -> GestureConfig:
    if not os.path.isfile(GESTURE_CONFIG_PATH):
        return GestureConfig()
    try:
        with open(GESTURE_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return GestureConfig(_merge_defaults(data))
    except Exception:
        return GestureConfig()


def save_gesture_config(cfg: GestureConfig) -> None:
    try:
        with open(GESTURE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg.raw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def ensure_model_file(progress_cb=None) -> str:
    os.makedirs(MODEL_DIR, exist_ok=True)
    if os.path.isfile(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1000:
        return MODEL_PATH

    def _rep(block, block_size, total):
        if progress_cb and total > 0:
            progress_cb(block * block_size, total)

    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, _rep)
    return MODEL_PATH
