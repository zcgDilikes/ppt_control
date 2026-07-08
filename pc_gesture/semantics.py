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
import threading
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
    slot: str = ""                                   # "A" | "B" | "C"
    person_id: int = 0                               # 0=主手,1=副手,2=第三手(round-robin)
    last_seen_monotonic: float = 0.0
    # 9-event 字段
    last_tip_gesture: str = "NONE"                   # L/R/C_HAND_INDEX|MIDDLE|RING|PINKY|NONE
    tip_cooldown_until: float = 0.0                  # 9 事件独立冷却
    last_tip_ts: float = 0.0                          # Bug3:tip_touch 触发时刻(用于防误触 pinch)
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
            "A": HandState(slot="A", person_id=0),
            "B": HandState(slot="B", person_id=1),
        }
        # 多手 / 3 人会议:当 multi_person_mode=3_hand_round_robin 时,
        # 额外创建 slot C,person_id=2(MediaPipe 跟踪 ≤2,第 3 手由
        # round-robin 帧切换由用户手动选 slot C 软处理)。
        try:
            multi_mode = str(cfg.raw.get("multi_person_mode", "off")).strip().lower()
        except (AttributeError, TypeError):
            multi_mode = "off"
        if multi_mode == "3_hand_round_robin":
            self._slots["C"] = HandState(slot="C", person_id=2)
        # Bug7:interlock 状态用 Lock 保护,避免 engine 线程 + 同步读 interlock_progress
        # 的多线程场景下 race condition
        self._interlock_lock = threading.Lock()
        # interlock cross-slot dwell timer(_detect_interlock 维护)
        self._interlock_start: Optional[float] = None
        # interlock 当前帧状态(NONE / HANDS_INTERLOCK),用于 rising-edge
        self._interlock_state: str = "NONE"
        # round-robin 帧计数器:3 帧切换一次,active_extra slot C
        self._rr_frame_counter: int = 0
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

    @staticmethod
    def _finger_joint_angle_2d(lm, mcp_idx, pip_idx, tip_idx) -> float:
        """方案 C:2D 关节角度(MCP→PIP→TIP 弯折角)。

        完全伸直:~180°(π rad)
        弯曲中:~135°(3π/4 rad)
        完全卷曲:~90°(π/2 rad)

        2D 角度对镜头方向仍敏感(手在 2D 图像里的弯折角可能与 3D 不同),
        但与 Y 轴 / 2D 距离互为补充:3 特征投票时显著提升角度鲁棒性。
        """
        v1 = (lm[pip_idx].x - lm[mcp_idx].x, lm[pip_idx].y - lm[mcp_idx].y)
        v2 = (lm[tip_idx].x - lm[pip_idx].x, lm[tip_idx].y - lm[pip_idx].y)
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cos_a = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (n1 * n2)))
        return math.acos(cos_a)  # 弧度,0~π

    @staticmethod
    def _is_finger_extended_vote(lm, tip_idx, pip_idx, mcp_idx, dip_idx, size,
                                 sens) -> bool:
        """方案 C:多特征投票识别手指是否伸直。

        3 个独立特征,各投 1 票,至少 2/3 通过才算伸直:
        1. Y:tip.y < pip.y - 0.025(标准 Y 检查)
        2. 2D:dist(tip, mcp) > 0.85*size(2D 距离兜底)
        3. Joint:MCP→PIP→TIP 向量夹角 < π/2 ≈ 1.57 rad(伸直时接近 0°,卷曲接近 90°)

        单手侧放/倾斜时,Y 通常误判,2D/关节角仍准;手腕在画面上方/下方时,
        关节角仍准。3 特征互相补,跨角度鲁棒。
        """
        # vote 1: Y
        y_pass = lm[tip_idx].y < lm[pip_idx].y - 0.025
        # vote 2: 2D distance
        try:
            d_thr = float(sens.get("ext_2d_ratio", 0.5))
        except (TypeError, ValueError):
            d_thr = 0.85
        d_pass = _dist(lm[tip_idx].x, lm[tip_idx].y, lm[mcp_idx].x, lm[mcp_idx].y) > d_thr * size
        # vote 3: 2D joint angle(< π/2 ≈ 1.57 = extended;卷曲接近 90° = 1.57,完全折近 π=3.14)
        try:
            angle_thr = float(sens.get("ext_joint_angle_rad", 1.57))
        except (TypeError, ValueError):
            angle_thr = 1.57
        angle = GestureSemantics._finger_joint_angle_2d(lm, mcp_idx, pip_idx, tip_idx)
        angle_pass = angle < angle_thr
        # 至少 2 票通过
        return sum([y_pass, d_pass, angle_pass]) >= 2

    def _detect_tip_touches(self, lm, slot: str) -> str:
        """9-events design spec 2026-07-07: 单手指尖触碰检测 + 方案 C 3 特征投票。

        步骤:
        1. 拇指尖到 4 个指尖的归一化距离,选最近
        2. 距离 < tip_touch_ratio 触发
        3. 方案 C:目标手指必须「伸直」(3 特征投票 ≥2/3),防止:
           - 手倾斜时拇指相对位置变化导致误触
           - 弯曲手指尖偶然在视觉上接近拇指根

        任意特征判弯曲则返回 NONE(就算距离够近也忽略)。
        返回 L/R/C_HAND_* 事件之一或 "NONE"。
        """
        if not lm or len(lm) < 21:
            return "NONE"
        try:
            size = self._hand_size(lm)
            threshold = float(self.cfg.sensitivity.get("tip_touch_ratio", 0.55))
            sens = self.cfg.sensitivity
        except (TypeError, ValueError):
            return "NONE"
        thumb_tip = lm[THUMB_TIP]
        # 槽位 → gesture 前缀映射:
        #   A → L_HAND_*(主手/左)
        #   B → R_HAND_*(副手/右)
        #   C → C_HAND_*(第三手,3-hand 模式下)
        if slot == "A":
            prefix = "L_HAND"
        elif slot == "B":
            prefix = "R_HAND"
        else:
            prefix = "C_HAND"
        # 候选(目标 name / tip_idx / pip_idx / mcp_idx / dip_idx)
        candidates = [
            (f"{prefix}_INDEX",  INDEX_TIP,  INDEX_PIP,  INDEX_MCP,  INDEX_DIP),
            (f"{prefix}_MIDDLE", MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP, MIDDLE_DIP),
            (f"{prefix}_RING",   RING_TIP,   RING_PIP,   RING_MCP,   RING_DIP),
            (f"{prefix}_PINKY",  PINKY_TIP,  PINKY_PIP,  PINKY_MCP,  PINKY_DIP),
        ]
        try:
            dists = [
                (name, tip_idx, pip_idx, mcp_idx, dip_idx,
                 _dist(thumb_tip.x, thumb_tip.y, lm[tip_idx].x, lm[tip_idx].y) / size)
                for name, tip_idx, pip_idx, mcp_idx, dip_idx in candidates
            ]
        except (TypeError, AttributeError):
            return "NONE"
        name, tip_idx, pip_idx, mcp_idx, dip_idx, d = min(dists, key=lambda x: x[5])
        if d >= threshold:
            return "NONE"
        # 方案 C:3 特征投票验证目标手指「伸直」
        # 拇指本身也算伸直(否则不算有效 9-event)
        thumb_extended = self._is_finger_extended_vote(
            lm, THUMB_TIP, THUMB_IP, THUMB_CMC, THUMB_MCP, size, sens,
        )
        target_extended = self._is_finger_extended_vote(
            lm, tip_idx, pip_idx, mcp_idx, dip_idx, size, sens,
        )
        if not (thumb_extended and target_extended):
            return "NONE"
        return name

    def _detect_interlock(self, lm_a, lm_b, now: float) -> bool:
        """9-events design spec 2026-07-07: 双手十指相扣检测(仅 dual 模式)。

        3 个条件(任一不满足返回 False):
        1. 两 wrist 距离 < interlock_max_wrist_dist(默认 0.20,归一化坐标)
        2. 10 指尖两两均值距离 < interlock_max_tip_dist(默认 0.40,归一化坐标)
        3. 上述条件持续 ≥ interlock_min_dwell_s(默认 0.3s)

        维护 self._interlock_start 实例属性(条件首次同时满足的时间)。
        """
        if not lm_a or not lm_b or len(lm_a) < 21 or len(lm_b) < 21:
            with self._interlock_lock:
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
            with self._interlock_lock:
                self._interlock_start = None
            return False
        tips_a = [lm_a[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        tips_b = [lm_b[i] for i in (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)]
        cross = [
            _dist(a.x, a.y, b.x, b.y)
            for a in tips_a for b in tips_b
        ]
        if sum(cross) / len(cross) > max_tip:
            with self._interlock_lock:
                self._interlock_start = None
            return False
        with self._interlock_lock:
            if self._interlock_start is None:
                self._interlock_start = now
            elapsed = now - self._interlock_start
        return elapsed >= dwell

    def interlock_progress(self, now: float) -> float:
        """P0.2:返回当前 interlock 进度 0-1(用于 UI 进度条)。

        - 0 表示刚刚开始,双手还没进入互锁距离
        - < 1 表示在 dwell 中(UI 应显示进度条)
        - 1 表示完成,UI 可触发确认
        """
        with self._interlock_lock:
            if self._interlock_start is None:
                return 0.0
            start = self._interlock_start
        try:
            dwell = float(self.cfg.sensitivity.get("interlock_min_dwell_s", 2.0))
        except (TypeError, ValueError):
            dwell = 2.0
        elapsed = now - start
        return min(1.0, max(0.0, elapsed / dwell))

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
    # 角色映射(7 旧 gesture 删除后,只剩 laser/pinch;tip-touch 路径无条件产)
    # ------------------------------------------------------------------
    def _laser_pinch_slot_flags(self, is_single: bool, slot: str) -> tuple:
        """Bug4 改名:返回 (produce_laser, produce_pinch):
          - laser:  single + A | dual + B  (9-event 设计:指控手 B 槽)
          - pinch:  single + A | dual + B  (同样指控手 B 槽)
          - tip-touch 路径无条件产(每槽都产,无论 mode)
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
        # 多手模式:round-robin 帧计数(每 3 帧轮一次,slot C 在 1/3 帧上活跃)
        try:
            multi_mode = str(self.cfg.raw.get("multi_person_mode", "off")).strip().lower()
        except (AttributeError, TypeError):
            multi_mode = "off"
        if multi_mode == "3_hand_round_robin":
            self._rr_frame_counter = (self._rr_frame_counter + 1) % 3
        else:
            self._rr_frame_counter = 0
        # info.txt 五.2:低置信度手部(遮挡、远距离)仍走完整分类,造成算力浪费 + 误触。
        try:
            min_confidence = float(sens.get("low_confidence_threshold", 0.6))
        except (TypeError, ValueError):
            min_confidence = 0.6

        slot_lms: Dict[str, list] = {}  # 9-events: 收集 per-slot 关键点给 interlock 用
        # 多手模式:round-robin gating — slot C only "active" every 3rd frame.
        # Per spec §3.4.4 (3-hand round-robin): on counter==0 slot C is
        # allowed to dispatch; on counter!=0 it's collected for interlock
        # only and tip_touch/laser/pinch are skipped.
        if multi_mode == "3_hand_round_robin":
            # counter is incremented above; spec says C active when 0.
            active_extra = {"C"} if self._rr_frame_counter == 0 else set()
        else:
            active_extra = set()
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
                # 多手模式:person_id 跟随 slot(A=0,B=1,C=2)
                st.person_id = 0 if slot == "A" else (1 if slot == "B" else 2)
                # Round-robin gating: skip dispatch for slot C when its
                # frame is not the active one. We still update
                # ``last_seen_monotonic`` + ``active_slots`` so cleanup
                # logic doesn't immediately evict the slot — the user's
                # third hand is still visible, we just chose not to fire.
                if slot not in ("A", "B") and slot not in active_extra:
                    continue
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
        produce_laser, produce_pinch = self._laser_pinch_slot_flags(is_single, slot)

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
        # Bug3 fixed.txt B-4 回归:tip_touch 刚触发(200ms 内)不接 pinch,
        # 防止翻页(拇指尖碰食指)同时误触发 MOUSE_CLICK。
        try:
            tip_grace_s = 0.2
        except (TypeError, ValueError):
            tip_grace_s = 0.2
        in_tip_grace = (now - st.last_tip_ts) < tip_grace_s
        if produce_pinch and not in_tip_grace:
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
        # Bug8:仅在 cooldown 真正放行时(条件全满足)才更新 last_tip_gesture。
        # 否则 cooldown 期内同一手势重复触发会被认作「没变化」而漏报;
        # 改成 cooldown 内的同 gesture 视作上次的(被 last_tip_gesture 卡住)。
        if tip and tip != st.last_tip_gesture:
            if now >= st.tip_cooldown_until and cooldown_ms > 0:
                events.append({
                    "event_class": "tip_touch",
                    "type": "tip_touch",
                    "gesture": tip,
                    "slot": slot,
                    "person_id": st.person_id,
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
                st.tip_cooldown_until = now + cooldown_ms / 1000.0
                st.last_tip_ts = now  # Bug3:记录 tip 时刻,防误触 pinch
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
