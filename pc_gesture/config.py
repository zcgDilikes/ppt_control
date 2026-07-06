"""
pc_gesture.config
=================

* ``GestureConfig``：对 UI 友好的属性访问 + 透传 ``raw`` JSON dict（保存时直接序列化）。
* ``load_gesture_config`` / ``save_gesture_config``：JSON 文件读写（原子写）。

配置文件路径：与 ``ppt_pc_client.py`` 同目录的 ``ppt_pc_client_gesture.json``。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# 手势/动作枚举 + 默认映射
# ---------------------------------------------------------------------------
GESTURES = (
    "OK", "L_SIGN", "THREE_FINGERS", "POINTING_UP", "SCISSORS", "FIST", "PALM",
)
ACTIONS = (
    "NEXT_PAGE", "PREV_PAGE", "FULL_SCREEN", "FROM_CURRENT",
    "BLACK_SCREEN", "WHITE_SCREEN", "EXIT",
    "SCREENSHOT", "OPEN_PPT",
    "PC_WINDOW_MINIMIZE", "PC_WINDOW_RESTORE",
)
DEFAULT_BINDINGS: Dict[str, Optional[str]] = {
    "OK":             "NEXT_PAGE",     # 下一页
    "SCISSORS":       "PREV_PAGE",     # 上一页(剪刀手)
    "FIST":           "BLACK_SCREEN",  # 黑屏(拳头)
    "PALM":           "EXIT",          # 退出放映(张掌)
    "THREE_FINGERS":  "WHITE_SCREEN",  # 白屏(三指)
    "L_SIGN":         "FULL_SCREEN",   # 从头放映(L 手势)
    "POINTING_UP":    None,            # 激光:走 rising-edge 持续发射,不走 bindings
}

# 旧 enum 字符串,用于迁移检测(代码层不再使用)
_DEPRECATED_GESTURES = (
    "THUMBS_UP", "THUMBS_DOWN", "SWIPE_LEFT", "SWIPE_RIGHT",
)


# ---------------------------------------------------------------------------
# 默认配置（新增字段时在此追加，并确保 _merge_defaults 透传用户已有字段）
# ---------------------------------------------------------------------------
DEFAULT_GESTURE_CONFIG: Dict[str, Any] = {
    "preview_only": False,
    "mirror": True,
    "operator_mode": "single",          # "single" | "dual"
    "dual_roles_swapped": False,
    "enabled": False,
    "camera_index": 0,
    "show_preview_window": True,
    "tutorial_done": False,
    "bindings": dict(DEFAULT_BINDINGS),
    "sensitivity": {
        # 捏合：拇指尖到食指尖的距离 / 手掌参考长度；越小越严格
        "pinch_threshold": 0.32,
        "pinch_release": 0.45,          # 迟滞松开阈值（> pinch_threshold）
        # 挥页：单位时间 wrist x 的归一化位移；越大越迟钝
        "swipe_min_velocity": 0.18,
        "swipe_history_ms": 240,
        "swipe_cooldown_ms": 700,
        # 一次性手势冷却:握拳/张掌/竖拇指/拇指向下 触发后多久内不重复(默认 400ms,老 800ms 太慢)
        "gesture_cooldown_ms": 400,
        # 托掌：open palm 持续多久后调起 on_send_text
        "palm_hold_ms": 1800,
        # 激光平滑：0 = 不滤波（直接抖动），1 = 上一帧权重 100%（不响应）
        "laser_smoothing": 0.55,
        # 状态灯:低于此置信度视为识别不准(三色灯转黄)
        "low_confidence_threshold": 0.6,
    },
}


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../pc_gesture/
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)                    # 项目根
GESTURE_CONFIG_PATH = os.path.join(PROJECT_DIR, "ppt_pc_client_gesture.json")


# ---------------------------------------------------------------------------
# GestureConfig
# ---------------------------------------------------------------------------
@dataclass
class GestureConfig:
    """顶层属性与 raw['...'] 双向同步；UI 既可 ``gcfg.preview_only`` 也可 ``cfg.raw['preview_only']``。"""

    raw: Dict[str, Any] = field(default_factory=dict)
    bindings: Dict[str, Optional[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 从 raw['bindings'] 同步到实例属性（_merge_defaults 已合并默认值）
        # 注意：保留 raw 中未知 key（如旧 enum 字符串），由 migrate_old_bindings 清理
        raw_bindings = self.raw.get("bindings") if isinstance(self.raw, dict) else None
        merged: Dict[str, Optional[str]] = dict(DEFAULT_BINDINGS)
        if isinstance(raw_bindings, dict):
            for g in GESTURES:
                if g in raw_bindings:
                    v = raw_bindings[g]
                    merged[g] = v if (v is None or v in ACTIONS) else None
        self.bindings = merged
        # 反向同步到 raw：保留未知键（旧 enum）以供 migrate_old_bindings 检测
        if isinstance(self.raw, dict):
            out = dict(self.bindings)
            if isinstance(raw_bindings, dict):
                for k, v in raw_bindings.items():
                    if k not in out:
                        out[k] = v
            self.raw["bindings"] = out

    # ----- preview_only -----
    @property
    def preview_only(self) -> bool:
        return bool(self.raw.get("preview_only", False))

    @preview_only.setter
    def preview_only(self, v: bool) -> None:
        self.raw["preview_only"] = bool(v)

    # ----- operator_mode -----
    @property
    def operator_mode(self) -> str:
        m = str(self.raw.get("operator_mode", "single")).strip().lower()
        return "dual" if m == "dual" else "single"

    @operator_mode.setter
    def operator_mode(self, v: str) -> None:
        self.raw["operator_mode"] = "dual" if str(v).strip().lower() == "dual" else "single"

    # ----- dual_roles_swapped -----
    @property
    def dual_roles_swapped(self) -> bool:
        return bool(self.raw.get("dual_roles_swapped", False))

    @dual_roles_swapped.setter
    def dual_roles_swapped(self, v: bool) -> None:
        self.raw["dual_roles_swapped"] = bool(v)

    # ----- sensitivity（嵌套字典，不强制同步） -----
    @property
    def sensitivity(self) -> Dict[str, Any]:
        s = self.raw.get("sensitivity")
        return s if isinstance(s, dict) else {}

    @property
    def camera_index(self) -> int:
        try:
            return int(self.raw.get("camera_index", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def mirror(self) -> bool:
        return bool(self.raw.get("mirror", True))

    @property
    def show_preview_window(self) -> bool:
        return bool(self.raw.get("show_preview_window", True))

    # ----- tutorial_done -----
    @property
    def tutorial_done(self) -> bool:
        return bool(self.raw.get("tutorial_done", False))

    @tutorial_done.setter
    def tutorial_done(self, v: bool) -> None:
        self.raw["tutorial_done"] = bool(v)

    # ----- bindings（手势 → 动作 或 None）-----
    def set_binding(self, gesture: str, action: Optional[str]) -> None:
        if gesture not in GESTURES:
            raise ValueError(f"unknown gesture: {gesture!r}")
        if action is not None and action not in ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
        self.bindings[gesture] = action
        if isinstance(self.raw, dict):
            self.raw["bindings"] = dict(self.bindings)

    def get_binding(self, gesture: str) -> Optional[str]:
        return self.bindings.get(gesture)

    def reset_bindings(self) -> None:
        self.bindings = dict(DEFAULT_BINDINGS)
        if isinstance(self.raw, dict):
            self.raw["bindings"] = dict(self.bindings)

    def export_dict(self) -> dict:
        return dict(self.bindings)

    def import_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        new_bindings: Dict[str, Optional[str]] = {}
        for g in GESTURES:
            if g in data:
                v = data[g]
                new_bindings[g] = v if (v is None or v in ACTIONS) else None
            else:
                new_bindings[g] = DEFAULT_BINDINGS.get(g)
        self.bindings = new_bindings
        if isinstance(self.raw, dict):
            self.raw["bindings"] = dict(self.bindings)

    # ----- 旧手势迁移 -----
    def migrate_old_bindings(self) -> bool:
        """移除 raw['bindings'] 里的旧 enum 键(THUMBS_UP/DOWN, SWIPE_*),
        并将 tutorial_done 重置为 False。

        返回 True 表示发生了迁移(供上层推 UI 状态消息)。
        FIST / PALM / POINTING_UP 三个保留 enum 键不动。
        """
        bindings = self.raw.get("bindings") if isinstance(self.raw, dict) else None
        if not isinstance(bindings, dict):
            return False
        deprecated = set(_DEPRECATED_GESTURES)
        changed = any(k in bindings for k in deprecated)
        if not changed:
            return False
        for k in deprecated:
            bindings.pop(k, None)
        # 反向同步
        self.bindings = {k: v for k, v in bindings.items() if k in self.bindings or k in GESTURES}
        self.raw["bindings"] = dict(self.bindings)
        # 强制重置教学标志
        self.tutorial_done = False
        return True


def _merge_defaults(raw: dict) -> dict:
    """递归补齐 DEFAULT_GESTURE_CONFIG 缺失字段，但不覆盖用户已有键。"""
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, Any] = {}
    for k, v in DEFAULT_GESTURE_CONFIG.items():
        if isinstance(v, dict):
            sub = raw.get(k)
            if isinstance(sub, dict):
                out[k] = {**v, **sub}
            else:
                out[k] = dict(v)
        else:
            out[k] = raw[k] if k in raw else v
    # 透传未列入默认值的字段
    for k, v in raw.items():
        if k not in out:
            out[k] = v
    return out


def load_gesture_config(path: Optional[str] = None) -> GestureConfig:
    """读取 JSON 配置；不存在或解析失败时返回全默认值。"""
    p = path or GESTURE_CONFIG_PATH
    raw: Dict[str, Any] = {}
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                raw = data
        except Exception:
            raw = {}
    return GestureConfig(raw=_merge_defaults(raw))


def save_gesture_config(cfg: GestureConfig, path: Optional[str] = None) -> None:
    """把 cfg.raw 原子写到磁盘（临时文件 + os.replace）。失败静默。"""
    p = path or GESTURE_CONFIG_PATH
    if not isinstance(cfg, GestureConfig):
        return
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="gesture_cfg_", suffix=".json",
                                   dir=os.path.dirname(p) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg.raw, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    except Exception:
        pass