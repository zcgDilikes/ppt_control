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
ACTIONS = (
    "NEXT_PAGE", "PREV_PAGE", "FULL_SCREEN", "FROM_CURRENT",
    "BLACK_SCREEN", "WHITE_SCREEN", "EXIT",
    "SCREENSHOT", "OPEN_PPT",
    "PC_WINDOW_MINIMIZE", "PC_WINDOW_RESTORE",
)

# 9 个事件(单手 × 4 指尖 × 2 + 双手 interlock)
# 7 旧 gesture(OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM)已全删
TIP_GESTURES = (
    "L_HAND_INDEX", "L_HAND_MIDDLE", "L_HAND_RING", "L_HAND_PINKY",
    "R_HAND_INDEX", "R_HAND_MIDDLE", "R_HAND_RING", "R_HAND_PINKY",
    "HANDS_INTERLOCK",
)

DEFAULT_TIP_BINDINGS: Dict[str, Optional[str]] = {
    "L_HAND_INDEX":     "NEXT_PAGE",
    "L_HAND_MIDDLE":    "PREV_PAGE",
    "L_HAND_RING":      "FULL_SCREEN",
    "L_HAND_PINKY":     "FROM_CURRENT",
    "R_HAND_INDEX":     "BLACK_SCREEN",
    "R_HAND_MIDDLE":    "WHITE_SCREEN",
    "R_HAND_RING":      "EXIT",
    "R_HAND_PINKY":     "SCREENSHOT",
    "HANDS_INTERLOCK":  "OPEN_PPT",
}

# Backward-compat shims: 7 旧 gesture 路径已删,但部分测试 / 旧代码可能仍引用
# 这些符号。给个空 stub 让 import 不报错。
GESTURES = ()
DEFAULT_BINDINGS: Dict[str, Optional[str]] = {}


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
    "tip_bindings": dict(DEFAULT_TIP_BINDINGS),  # 9 个 tip 事件独立绑定
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
        # 激光平滑：0 = 不滤波（直接抖动），1 = 上一帧权重 100%（不响应）
        "laser_smoothing": 0.55,
        # 调试日志开关:True 时 [semantics]/[bridge] 在终端打日志,默认关(生产环境无 IO 损耗)
        "debug_log": False,
        # 状态灯:低于此置信度视为识别不准(三色灯转黄)
        "low_confidence_threshold": 0.6,
        # info.txt 五.1:硬编码魔法数字抽出到配置
        # 拇-食指尖距离 / 手掌参考长度 < 此值 视为接触(OK 手势前提)
        "thumb_touch_ratio": 0.08,
        # 拇-食指距离 / 手掌参考长度 > 此值 视为伸直(L / 三指前提)
        "thumb_extend_ratio": 0.18,
        # 手指伸直 Y 偏移(归一化)。tip.y < pip.y - 此值 视为严格伸直
        "ext_strict_y": 0.025,
        # 手指伸直 Y 偏移(归一化,放松版)。tip.y < pip.y - 此值 视为伸直
        # (OK 软阈值、PALM 用)
        "ext_relaxed_y": 0.015,
        # 手指卷曲 Y 偏移(归一化)。tip.y > pip.y + 此值 视为卷曲
        "curl_y": 0.005,
        # 手部消失超过此秒数,清理 slot 瞬时状态(冷却、最后手势、激光历史)
        "hand_lost_cleanup_s": 0.5,
        # 配对判定:某 slot pointing_up 持续此秒数即认为配对成功
        "pairing_pointing_up_s": 1.0,
        # 配对窗口:从 start_pairing 算起,此秒数内未确认则超时
        "pairing_window_ms": 3000,
        # info.txt 9-events: 9 个新事件阈值
        # 拇指尖到目标指尖的归一化距离阈值(单手 tip_touch)
        "tip_touch_ratio": 0.55,
        # 双手 interlock 检测:两 wrist 归一化距离上限
        "interlock_max_wrist_dist": 0.20,
        # 双手 interlock:10 指尖两两均值距离上限(归一化)
        "interlock_max_tip_dist": 0.40,
        # 双手 interlock:最小持续秒数(P0.2 调高到 2s,防误触高风险动作)
        "interlock_min_dwell_s": 2.0,
        # info.txt 二.1:Y 模糊时(hand sideways),2D 距离作为伸直兜底。
        # 模糊判定:|tip.y - pip.y| < 此值 视为手侧放,启用 2D 距离判伸直。
        "ambiguous_y_tolerance": 0.005,
        # 2D 距离占手掌参考长度比例(伸直阈值,模糊时用)
        "ext_2d_ratio": 0.5,  # 方案 C:tip-to-MCP 距离阈值(占 size 比),< 此值 视为弯曲
        # 方案 C:2D 关节角阈值(弧度)< 此值 视为伸直;卷曲时约 π/2 ≈ 1.57
        "ext_joint_angle_rad": 1.57,
        # info.txt 二.3:L_SIGN 需要拇指明显横向伸出,不能只是「微伸」
        "l_sign_thumb_extend_ratio": 0.30,
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
    """顶层属性与 raw['...'] 双向同步；UI 既可 ``gcfg.preview_only`` 也可 ``cfg.raw['preview_only']``。

    7 旧 gesture 全删,只保留 9 个新事件的 tip_bindings。
    """

    raw: Dict[str, Any] = field(default_factory=dict)
    tip_bindings: Dict[str, Optional[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # tip_bindings 同步(缺失键用默认填)
        raw_tip = self.raw.get("tip_bindings") if isinstance(self.raw, dict) else None
        merged_tip: Dict[str, Optional[str]] = dict(DEFAULT_TIP_BINDINGS)
        if isinstance(raw_tip, dict):
            for g in TIP_GESTURES:
                if g in raw_tip:
                    v = raw_tip[g]
                    merged_tip[g] = v if (v is None or v in ACTIONS) else None
        self.tip_bindings = merged_tip
        if isinstance(self.raw, dict):
            self.raw["tip_bindings"] = dict(self.tip_bindings)
        # 兼容旧 config:丢弃旧 bindings 字段(7 gesture 已删)
        if isinstance(self.raw, dict) and "bindings" in self.raw:
            self.raw.pop("bindings", None)

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

    # ----- tip_bindings (9-event) -----
    def set_tip_binding(self, gesture: str, action: Optional[str]) -> None:
        if gesture not in TIP_GESTURES:
            raise ValueError(f"unknown tip gesture: {gesture!r}")
        if action is not None and action not in ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
        self.tip_bindings[gesture] = action
        if isinstance(self.raw, dict):
            self.raw["tip_bindings"] = dict(self.tip_bindings)

    def get_tip_binding(self, gesture: str) -> Optional[str]:
        return self.tip_bindings.get(gesture)

    def reset_bindings(self) -> None:
        """重置 tip_bindings 为默认(7 旧 gesture 的 reset_bindings 已删)"""
        self.tip_bindings = dict(DEFAULT_TIP_BINDINGS)
        if isinstance(self.raw, dict):
            self.raw["tip_bindings"] = dict(self.tip_bindings)


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