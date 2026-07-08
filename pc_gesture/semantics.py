"""
pc_gesture.semantics
====================

每帧把手部关键点（21 个 NormalizedLandmark）分类为「事件」，供 GestureEngine 派发。

主要事件:
    9 个 tip-touch 事件(单手 4 指尖 × 2 手 + 双手 interlock)
    + 激光(per-frame cursor 位置)
    + 捏合(MOUSE_CLICK/DOWN/UP)

注:7 旧 gesture(OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM)
   全部删除,只保留 9 个新事件,9 事件支持单/双人模式。

双人模式:
    按 ``hand_landmarks[WRIST].x`` 把每只手分配到 A 槽或 B 槽:
        默认:A = 屏幕左侧(小 x) = L_HAND_*
              B = 屏幕右侧(大 x) = R_HAND_*
        勾选 ``dual_roles_swapped`` 时左右对调。
    单人模式:slot 由 x 决定(A 左 / B 右),产 L_HAND_* 或 R_HAND_*;
              没有 interlock(需要两手)。

坐标说明:
    MediaPipe 归一化坐标 ``x ∈ [0,1]`` 从左到右,``y ∈ [0,1]`` 从上到下。
    ``cv2.flip(frame, 1)`` 镜像后用户「自己的右手」出现在画面左侧(小 x),
    用户「自己的左手」出现在画面右侧(大 x)。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import GestureConfig


# ---------------------------------------------------------------------------
# MediaPipe HandLandmarker 21 关键点索引
# ---------------------------------------------------------------------------
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


# ---------------------------------------------------------------------------
# Per-hand state
# ---------------------------------------------------------------------------
@dataclass
class HandState:
    slot: str = ""                                   # "A" or "B"
    last_seen_monotonic: float = 0.0
    # 9-event 字段
    last_tip_gesture: str = "NONE"                   # L/R_HAND_INDEX|MIDDLE|RING|PINKY|NONE
    tip_cooldown_until: float = 0.0                  # 9 事件独立冷却
    last_interlock_gesture: str = "NONE"             # slot A 上的 interlock 状态(单一)
    interlock_cooldown_until: float = 0.0            # interlock 独立冷却
    # 捏合迟滞
    pinching: bool = False
    # 激光上一帧坐标(用于 EMA)
    laser_last_xy: Optional[Tuple[float, float]] = None
    # 注:7 旧 gesture 字段(last_static_gesture / last_static_at / static_cooldown_until)已删


# ---------------------------------------------------------------------------
# GestureSemantics
# ---------------------------------------------------------------------------
class GestureSemantics:
    """状态机 + 分类器。只产 9 个 tip-touch 事件 + 激光 + 捏合。"""

    G_NONE = "NONE"  # 占位(向后兼容,7 旧 enum 已删)

    def __init__(self, cfg: GestureConfig):
        self.cfg = cfg
        self._slots: Dict[str, HandState] = {
            "A": HandState(slot="A"),
            "B": HandState(slot="B"),
        }
        # interlock cross-slot dwell timer(_detect_interlock 维护)
        self._interlock_start: Optional[float] = None
        # interlock 当前帧状态(NONE / HANDS_INTERLOCK),用于 rising-edge
        self._interlock_state: str = "NONE"
        # 注:PairingService 已删(7 旧 gesture 路径不再需要 pairing POINTING_UP)

    # ------------------------------------------------------------------
    # 配置热更新
    # ------------------------------------------------------------------
    def reload_config(self, cfg: GestureConfig) -> None:
        self.cfg = cfg
        # 清空运行时状态
        for slot in self._slots.values():
            slot.last_tip_gesture = "NONE"
            slot.tip_cooldown_until = 0.0
            slot.last_interlock_gesture = "NONE"
            slot.interlock_cooldown_until = 0.0
            slot.pinching = False
            slot.laser_last_xy = None
        # interlock cross-slot 状态也清
        self._interlock_start = None
        self._interlock_state = "NONE"

    # ------------------------------------------------------------------
    # 关键点 → 几何特征
    # ------------------------------------------------------------------
    @staticmethod
    def _hand_size(lm) -> float:
        """以 wrist→middle MCP 距离作为手掌参考长度(归一化坐标下通常 0.15~0.35)。

        双向夹紧:极端近距离手部时 size 趋近 0 会除以极小值造成距离归一化爆炸;
        极端远距离时 size 超过 0.5 也是异常(超过真人手部比例)。
        """
        raw = _dist(lm[WRIST].x, lm[WRIST].y, lm[MIDDLE_MCP].x, lm[MIDDLE_MCP].y)
        return min(max(raw, 0.05), 0.5)

    def _detect_tip_touches(self, lm, slot: str) -> str:
        """9-events design spec 2026-07-07: 单手指尖触碰检测。

        拇指尖到 4 个指尖的归一化距离,选最近;距离 < tip_touch_ratio 触发。
        返回 8 个 L/R_HAND_* 事件之一或 "NONE"。
        9 事件支持单/双人模式:slot 由 x 决定,产 L_* 或 R_*。
        """
        if not lm or len(lm) < 21:
            return "NONE"
        try:
            size = self._hand_size(lm)
            threshold = float(self.cfg.sensitivity.get("tip_touch_ratio", 0.55))
        except (TypeError, ValueError):
            return "NONE"
        thumb_tip = lm[THUMB_TIP]
        prefix = "L_HAND" if slot == "A" else "R_HAND"
        candidates = [
            (f"{prefix}_INDEX",  lm[INDEX_TIP]),
            (f"{prefix}_MIDDLE", lm[MIDDLE_TIP]),
            (f"{prefix}_RING",   lm[RING_TIP]),
            (f"{prefix}_PINKY",  lm[PINKY_TIP]),
        ]
        try:
            dists = [
                (name, _dist(thumb_tip.x, thumb_tip.y, tip.x, tip.y) / size)
                for name, tip in candidates
            ]
        except (TypeError, AttributeError):
            return "NONE"
        name, d = min(dists, key=lambda x: x[1])
        if d < threshold:
            return name
        return "NONE"

    def _detect_interlock(self, lm_a, lm_b, now: float) -> bool:
        """9-events design spec 2026-07-07: 双手十指相扣检测(仅 dual 模式)。

        3 个条件(任一不满足返回 False):
        1. 两 wrist 距离 < interlock_max_wrist_dist(默认 0.20,归一化坐标)
        2. 10 指尖两两均值距离 < interlock_max_tip_dist(默认 0.40,归一化坐标)
        3. 上述条件持续 ≥ interlock_min_dwell_s(默认 0.3s)

        维护 self._interlock_start 实例属性(条件首次同时满足的时间)。
        """
        if not lm_a or not lm_b or len(lm_a) < 21 or len(lm_b) < 21:
            self._interlock_start = None
            return False
        try:
            sens = self.cfg.sensitivity
            max_wrist = float(sens.get("interlock_max_wrist_dist", 0.20))
            max_tip = float(sens.get("interlock_max_tip_dist", 0.40))
            dwell = float(sens.get("interlock_min_dwell_s", 0.3))
        except (TypeError, ValueError):
            return False
        wrist_d = _dist(lm_a[WRIST].x, lm_a[WRIST].y, lm_b[WRIST].x, lm_b[WRIST].y)
        if wrist_d > max_wrist:
            self._interlock_start = None
            return False
        tips_a = [lm_a[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        tips_b = [lm_b[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        cross = [
            _dist(a.x, a.y, b.x, b.y)
            for a in tips_a for b in tips_b
        ]
        if sum(cross) / len(cross) > max_tip:
            self._interlock_start = None
            return False
        if self._interlock_start is None:
            self._interlock_start = now
            return False
        return (now - self._interlock_start) >= dwell

    # ------------------------------------------------------------------
    # 槽位分配(基于 wrist x)
    # ------------------------------------------------------------------
    def _assign_slot(self, lm, swapped: bool) -> str:
        """默认 A=小 x(屏幕左),B=大 x(屏幕右);swapped 时对调。"""
        small_is_left = lm[WRIST].x < 0.5
        if swapped:
            return "A" if not small_is_left else "B"
        return "A" if small_is_left else "B"

    # ------------------------------------------------------------------
    # 角色映射(7 旧 gesture 删除后,只剩 laser/pinch/tip-touch)
    # ------------------------------------------------------------------
    def _resolve_role_flags(self, is_single: bool, slot: str) -> tuple:
        """返回 (produce_laser, produce_pinch):
          - laser:  single + A | dual + B  (9-event 设计:指控手 B 槽)
          - pinch:  single + A | dual + B  (同样指控手 B 槽)
          - tip-touch 路径无条件(每槽都产,无论 mode)
        """
        produce_laser = (is_single and slot == "A") or (not is_single and slot == "B")
        produce_pinch = (is_single and slot == "A") or (not is_single and slot == "B")
        return produce_laser, produce_pinch

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def process(
        self,
        hand_landmarks_list,
        handedness_list,
    ) -> List[Dict[str, Any]]:
        """输入 MediaPipe Tasks HandLandmarker.detect 的结果;返回要派发的事件列表。

        9-event 设计:每只手(slot A/B)产 tip_touch 事件;
        两手在画面 + 持续 0.3s 满足条件 → 产 interlock 事件。
        """
        sens = self.cfg.sensitivity
        now = time.monotonic()
        events: List[Dict[str, Any]] = []
        # 当前帧活跃的槽位集合
        active_slots = set()
        # info.txt 五.2:低置信度手部(遮挡、远距离)仍走完整分类,造成算力浪费 + 误触。
        try:
            min_confidence = float(sens.get("low_confidence_threshold", 0.6))
        except (TypeError, ValueError):
            min_confidence = 0.6

        slot_lms: Dict[str, list] = {}  # 9-events: 收集 per-slot 关键点给 interlock 用
        if hand_landmarks_list:
            for idx, lm_list in enumerate(hand_landmarks_list):
                if not lm_list or len(lm_list) < 21:
                    continue
                # 过滤低置信度
                confidence = 1.0
                if handedness_list and idx < len(handedness_list):
                    h = handedness_list[idx]
                    if h:
                        try:
                            confidence = float(h[0].score)
                        except (AttributeError, IndexError, TypeError, ValueError):
                            confidence = 1.0
                if confidence < min_confidence:
                    continue
                slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
                st = self._slots[slot]
                st.last_seen_monotonic = now
                active_slots.add(slot)
                slot_lms[slot] = lm_list
                events.extend(self._process_one_hand(lm_list, slot, st, sens, now))

        # 没出现在本帧的槽位:清理与该手相关的瞬时状态
        try:
            hand_lost_s = float(sens.get("hand_lost_cleanup_s", 0.5))
        except (TypeError, ValueError):
            hand_lost_s = 0.5
        for slot, st in self._slots.items():
            if slot not in active_slots:
                if now - st.last_seen_monotonic > hand_lost_s:
                    st.pinching = False
                    st.laser_last_xy = None
                    st.last_tip_gesture = "NONE"
                    st.tip_cooldown_until = 0.0
                    st.last_interlock_gesture = "NONE"
                    st.interlock_cooldown_until = 0.0

        # 9-events: cross-slot interlock 检测(仅 dual,两手可见)
        operator_mode = self.cfg.operator_mode
        if operator_mode == "dual":
            try:
                cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))
            except (TypeError, ValueError):
                cooldown_ms = 400
            lm_a = slot_lms.get("A")
            lm_b = slot_lms.get("B")
            interlock_hit = self._detect_interlock(lm_a, lm_b, now)
            st_a = self._slots["A"]
            new_state = "HANDS_INTERLOCK" if interlock_hit else "NONE"
            if new_state != self._interlock_state:
                # rising edge:只在状态从 NONE 跳到 HANDS_INTERLOCK 时派发
                self._interlock_state = new_state
                if interlock_hit and now >= st_a.interlock_cooldown_until and cooldown_ms > 0:
                    events.append({
                        "event_class": "interlock",
                        "type": "interlock",
                        "gesture": "HANDS_INTERLOCK",
                        "slot": "BOTH",
                        "ts": now, "ts_ms": int(now * 1000),
                        "source": "gesture:interlock",
                    })
                    st_a.interlock_cooldown_until = now + cooldown_ms / 1000.0
            else:
                # 状态未变化,但 interlock_hit=True 时持续记 _interlock_start
                # 让 _detect_interlock 自己更新它(已实现)
                pass

        return events

    # ------------------------------------------------------------------
    # 单只手处理:激光(per-frame) + 捏合(rising) + 9-event tip-touch
    # ------------------------------------------------------------------
    def _process_one_hand(self, lm, slot: str, st: HandState,
                          sens: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        operator_mode = self.cfg.operator_mode
        is_single = operator_mode == "single"

        # 角色映射(只剩 laser + pinch;tip-touch 路径无条件)
        produce_laser, produce_pinch = self._resolve_role_flags(is_single, slot)

        # 统一时间戳字段
        ts = now
        ts_ms = int(now * 1000)

        # ----- 1) 激光(per-frame cursor 位置) -----
        # 7 旧 gesture 删除后,无 POINTING_UP 触发条件;改为"该槽位 produce_laser 且
        # 手可见就持续发 laser"(用户用任何手势都能动光标)。
        if produce_laser:
            tx = float(lm[INDEX_TIP].x)
            ty = float(lm[INDEX_TIP].y)
            try:
                smoothing = float(sens.get("laser_smoothing", 0.55))
            except (TypeError, ValueError):
                smoothing = 0.55
            smoothing = max(0.0, min(0.95, smoothing))
            if st.laser_last_xy is not None:
                tx = smoothing * st.laser_last_xy[0] + (1.0 - smoothing) * tx
                ty = smoothing * st.laser_last_xy[1] + (1.0 - smoothing) * ty
            st.laser_last_xy = (tx, ty)
            events.append({
                "cmd": "LASER", "x": tx, "y": ty,
                "ts": ts, "ts_ms": ts_ms,
                "source": f"gesture:{slot}",
            })
        else:
            st.laser_last_xy = None

        # ----- 2) 捏合 → 点击(迟滞防抖) -----
        if produce_pinch:
            try:
                pinch_th = float(sens.get("pinch_threshold", 0.32))
                pinch_rel = float(sens.get("pinch_release", 0.45))
            except (TypeError, ValueError):
                pinch_th = 0.32
                pinch_rel = 0.45
            if not st.pinching and self._is_pinching(lm, pinch_th, pinch_rel):
                st.pinching = True
                events.append({
                    "cmd": "MOUSE_CLICK", "count": 1,
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
                events.append({
                    "cmd": "MOUSE_DOWN",
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
            elif st.pinching and self._is_pinch_released(lm, pinch_rel):
                st.pinching = False
                events.append({
                    "cmd": "MOUSE_UP",
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
        else:
            st.pinching = False

        # ----- 3) 9-event tip_touch 通道(单/双人模式都产) -----
        # 9-event 设计:无条件产 tip_touch,slot 由 x 决定 L_* 或 R_*
        try:
            cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))
        except (TypeError, ValueError):
            cooldown_ms = 400
        tip = self._detect_tip_touches(lm, slot)
        if tip and tip != st.last_tip_gesture:
            if now >= st.tip_cooldown_until and cooldown_ms > 0:
                events.append({
                    "event_class": "tip_touch",
                    "type": "tip_touch",
                    "gesture": tip,
                    "slot": slot,
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
                st.tip_cooldown_until = now + cooldown_ms / 1000.0
        st.last_tip_gesture = tip

        return events

    def _is_pinching(self, lm, pinch_th: float, pinch_rel: float) -> bool:
        """拇指尖与食指尖的距离 / 手掌参考长度。"""
        size = self._hand_size(lm)
        d = _dist(lm[THUMB_TIP].x, lm[THUMB_TIP].y, lm[INDEX_TIP].x, lm[INDEX_TIP].y)
        return (d / size) < pinch_th

    def _is_pinch_released(self, lm, pinch_rel: float) -> bool:
        size = self._hand_size(lm)
        d = _dist(lm[THUMB_TIP].x, lm[THUMB_TIP].y, lm[INDEX_TIP].x, lm[INDEX_TIP].y)
        return (d / size) > pinch_rel
