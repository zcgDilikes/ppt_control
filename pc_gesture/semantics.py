"""
pc_gesture.semantics
====================

每帧把手部关键点（21 个 NormalizedLandmark）分类为「事件」，供 GestureEngine 派发。

主要分类：
    握拳 / 张掌 / 竖拇指 / 拇指向下 / 食指（激光）/ 捏合（点击）/ 左右挥（翻页）/ 托掌（on_send_text）

双人模式：
    按 ``hand_landmarks[WRIST].x`` 把每只手分配到 A 槽或 B 槽：
        默认：A = 屏幕左侧（小 x）= 导航（挥页）
              B = 屏幕右侧（大 x）= 指控（激光/点击/F5/退出/托掌）
        勾选 ``dual_roles_swapped`` 时左右对调。
    单人模式：取 A 槽（A 也即屏幕左侧）；若 A 槽为空则取 B 槽。

坐标说明：
    MediaPipe 归一化坐标 ``x ∈ [0,1]`` 从左到右，``y ∈ [0,1]`` 从上到下。
    ``cv2.flip(frame, 1)`` 镜像后用户「自己的右手」出现在画面左侧（小 x），
    用户「自己的左手」出现在画面右侧（大 x）。
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
    # 上一次识别的手势类别（用于防抖/冷却）
    last_static_gesture: str = "NONE"                # FIST/PALM/POINTING_UP/THUMBS_UP/THUMBS_DOWN/NONE
    static_cooldown_until: float = 0.0
    # 捏合迟滞
    pinching: bool = False
    # 托掌持续时长
    palm_hold_start: Optional[float] = None
    palm_hold_fired: bool = False
    # 激光上一帧坐标（用于 EMA）
    laser_last_xy: Optional[Tuple[float, float]] = None
    # 挥页 wrist x 历史（环形缓冲）
    wrist_history: List[Tuple[float, float]] = field(default_factory=list)
    last_swire_at: float = 0.0
    # 配对确认累计：slot A 在 pointing_up 上稳定了多久
    pointing_up_start: Optional[float] = None


# ---------------------------------------------------------------------------
# GestureSemantics
# ---------------------------------------------------------------------------
class GestureSemantics:
    """状态机 + 分类器。"""

    # 静态手势类别
    G_NONE = "NONE"
    G_FIST = "FIST"
    G_PALM = "PALM"
    G_POINTING_UP = "POINTING_UP"
    G_THUMBS_UP = "THUMBS_UP"
    G_THUMBS_DOWN = "THUMBS_DOWN"

    def __init__(self, cfg: GestureConfig):
        self.cfg = cfg
        self._slots: Dict[str, HandState] = {
            "A": HandState(slot="A"),
            "B": HandState(slot="B"),
        }
        # 配对
        self._pairing_active: bool = False
        self._pairing_started: float = 0.0
        self._pairing_confirmed: bool = False
        self._pairing_window_ms: int = 3000

    # ------------------------------------------------------------------
    # 配置热更新
    # ------------------------------------------------------------------
    def reload_config(self, cfg: GestureConfig) -> None:
        self.cfg = cfg
        # 清空运行时状态，避免旧阈值下的历史造成误判
        for slot in self._slots.values():
            slot.last_static_gesture = self.G_NONE
            slot.static_cooldown_until = 0.0
            slot.pinching = False
            slot.palm_hold_start = None
            slot.palm_hold_fired = False
            slot.laser_last_xy = None
            slot.wrist_history.clear()
            slot.last_swire_at = 0.0
            slot.pointing_up_start = None

    # ------------------------------------------------------------------
    # 配对（仅在 dual 模式下生效）
    # ------------------------------------------------------------------
    def start_pairing(self, window_ms: int = 3000) -> None:
        self._pairing_active = True
        self._pairing_started = time.monotonic()
        self._pairing_confirmed = False
        self._pairing_window_ms = max(500, int(window_ms))
        # 清除指向累计，从头开始计时
        for slot in self._slots.values():
            slot.pointing_up_start = None

    def reset_pairing(self) -> None:
        self._pairing_active = False
        self._pairing_confirmed = False
        self._pairing_started = 0.0
        for slot in self._slots.values():
            slot.pointing_up_start = None

    @property
    def pairing_state(self) -> str:
        if not self._pairing_active:
            return "IDLE"
        if self._pairing_confirmed:
            return "CONFIRMED"
        elapsed_ms = (time.monotonic() - self._pairing_started) * 1000.0
        if elapsed_ms > self._pairing_window_ms:
            return "EXPIRED"
        return "WAITING"

    @property
    def pairing_confirmed(self) -> bool:
        return self._pairing_confirmed

    # ------------------------------------------------------------------
    # 关键点 → 几何特征
    # ------------------------------------------------------------------
    @staticmethod
    def _hand_size(lm) -> float:
        """以 wrist→middle MCP 距离作为手掌参考长度（归一化坐标下通常 0.15~0.35）。"""
        return max(_dist(lm[WRIST].x, lm[WRIST].y, lm[MIDDLE_MCP].x, lm[MIDDLE_MCP].y), 1e-3)

    @staticmethod
    def _finger_curled(lm, tip_idx: int, pip_idx: int) -> bool:
        """TIP.y > PIP.y 表示指尖低于 PIP（卷曲）；margin 抗噪。"""
        return lm[tip_idx].y > lm[pip_idx].y + 0.005

    @staticmethod
    def _finger_extended(lm, tip_idx: int, pip_idx: int, margin: float = 0.025) -> bool:
        return lm[tip_idx].y < lm[pip_idx].y - margin

    def _classify_static(self, lm) -> str:
        """返回 FIST / PALM / POINTING_UP / THUMBS_UP / THUMBS_DOWN / NONE。

        优先级：PALM → THUMBS_UP/DOWN → FIST → POINTING_UP。
        拇指向手势优先于握拳（握拳的姿态同时满足 4 指卷曲，但拇指朝向有区分意义）。
        """
        size = self._hand_size(lm)

        index_ext = self._finger_extended(lm, INDEX_TIP, INDEX_PIP)
        middle_ext = self._finger_extended(lm, MIDDLE_TIP, MIDDLE_PIP)
        ring_ext = self._finger_extended(lm, RING_TIP, RING_PIP)
        pinky_ext = self._finger_extended(lm, PINKY_TIP, PINKY_PIP)

        index_curled = self._finger_curled(lm, INDEX_TIP, INDEX_PIP)
        middle_curled = self._finger_curled(lm, MIDDLE_TIP, MIDDLE_PIP)
        ring_curled = self._finger_curled(lm, RING_TIP, RING_PIP)
        pinky_curled = self._finger_curled(lm, PINKY_TIP, PINKY_PIP)
        all_curled = index_curled and middle_curled and ring_curled and pinky_curled

        # 1) 张掌：四指全部伸直
        if index_ext and middle_ext and ring_ext and pinky_ext:
            return self.G_PALM

        thumb_tip_y = lm[THUMB_TIP].y
        wrist_y = lm[WRIST].y

        # 2) 竖拇指：拇指尖明显高于 wrist；其他四指卷曲
        thumb_high = thumb_tip_y < wrist_y - 0.08
        if thumb_high and all_curled:
            return self.G_THUMBS_UP

        # 3) 拇指向下：拇指尖明显低于 wrist；其他四指卷曲
        thumb_low = thumb_tip_y > wrist_y + 0.10
        if thumb_low and all_curled:
            return self.G_THUMBS_DOWN

        # 4) 握拳：四指全部卷曲（且不满足竖/拇指向下）
        if all_curled:
            return self.G_FIST

        # 5) 食指上指：仅食指伸直，其余卷曲
        if index_ext and middle_curled and ring_curled and pinky_curled:
            return self.G_POINTING_UP

        return self.G_NONE

    def _is_pinching(self, lm, pinch_th: float, pinch_rel: float) -> bool:
        """拇指尖与食指尖的距离 / 手掌参考长度。"""
        size = self._hand_size(lm)
        d = _dist(lm[THUMB_TIP].x, lm[THUMB_TIP].y, lm[INDEX_TIP].x, lm[INDEX_TIP].y)
        return (d / size) < pinch_th

    def _is_pinch_released(self, lm, pinch_rel: float) -> bool:
        size = self._hand_size(lm)
        d = _dist(lm[THUMB_TIP].x, lm[THUMB_TIP].y, lm[INDEX_TIP].x, lm[INDEX_TIP].y)
        return (d / size) > pinch_rel

    # ------------------------------------------------------------------
    # 槽位分配（基于 wrist x）
    # ------------------------------------------------------------------
    def _assign_slot(self, lm, swapped: bool) -> str:
        """默认 A=小 x（屏幕左），B=大 x（屏幕右）；swapped 时对调。"""
        # 0.5 中线为分界；若用户启用了水平翻转（mirror），这一判定保持不变——
        # 图像坐标系始终 0..1，分界固定在画面中点。
        small_is_left = lm[WRIST].x < 0.5
        if swapped:
            return "A" if not small_is_left else "B"
        return "A" if small_is_left else "B"

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def process(
        self,
        hand_landmarks_list,
        handedness_list,
        on_send_text: Optional[Callable[[], None]] = None,
    ) -> List[Dict[str, Any]]:
        """输入 MediaPipe Tasks HandLandmarker.detect 的结果；返回要派发的事件列表。"""
        sens = self.cfg.sensitivity
        now = time.monotonic()
        events: List[Dict[str, Any]] = []
        # 当前帧活跃的槽位集合
        active_slots = set()

        if hand_landmarks_list:
            for lm_list in hand_landmarks_list:
                if not lm_list or len(lm_list) < 21:
                    continue
                slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
                st = self._slots[slot]
                st.last_seen_monotonic = now
                active_slots.add(slot)
                events.extend(self._process_one_hand(lm_list, slot, st, sens, now, on_send_text))

        # 配对窗口中：A 槽（屏幕左）持续 pointing_up 满 1 秒 → 确认
        self._update_pairing(now)

        # 没出现在本帧的槽位：清理与该手相关的瞬时状态（pinch/tap/wrist 历史）
        # 但保留静态手势冷却和 palm_hold 计时，避免画面外短暂消失就重置
        for slot, st in self._slots.items():
            if slot not in active_slots:
                # 失联超过 500ms，重置瞬时状态
                if now - st.last_seen_monotonic > 0.5:
                    st.pinching = False
                    st.palm_hold_start = None
                    st.palm_hold_fired = False
                    st.wrist_history.clear()
                    st.laser_last_xy = None
                    st.pointing_up_start = None

        return events

    # ------------------------------------------------------------------
    # 单只手处理
    # ------------------------------------------------------------------
    def _process_one_hand(self, lm, slot: str, st: HandState,
                          sens: Dict[str, Any], now: float,
                          on_send_text: Optional[Callable[[], None]]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        operator_mode = self.cfg.operator_mode
        is_single = operator_mode == "single"

        # 静态手势分类
        gesture = self._classify_static(lm)

        # 在单人模式下，仅 A 槽产生指令；B 槽只用于预览
        # 在双人模式下，A 负责导航（挥页），B 负责指控（其余）
        # 注意：单/双人 角色映射由调用方（GestureEngine）决定；
        # 这里只负责「单只手能产生哪些事件」，由 slot 在合适时跳过。

        # ----- 1) 激光（食指上指） -----
        # 单人：仅 A 槽产生激光；双人：B 槽产生激光
        produce_laser = (is_single and slot == "A") or (not is_single and slot == "B")
        if produce_laser and gesture == self.G_POINTING_UP:
            tx = float(lm[INDEX_TIP].x)
            ty = float(lm[INDEX_TIP].y)
            smoothing = float(sens.get("laser_smoothing", 0.55))
            smoothing = max(0.0, min(0.95, smoothing))
            if st.laser_last_xy is not None:
                tx = smoothing * st.laser_last_xy[0] + (1.0 - smoothing) * tx
                ty = smoothing * st.laser_last_xy[1] + (1.0 - smoothing) * ty
            st.laser_last_xy = (tx, ty)
            events.append({
                "type": "gesture",
                "gesture": gesture,
                "slot": slot,
                "x": tx,
                "y": ty,
                "source": f"gesture:{slot}",
            })
        else:
            # 非 pointing_up → 停止激光平滑（下次重新起步）
            st.laser_last_xy = None

        # ----- 2) 一次性静态手势（带冷却） -----
        # 单人：全部由 A 槽触发；双人：FIST/PALM 由 A 槽触发（导航/托掌），THUMBS_UP/DOWN 由 B 槽触发
        produce_static = (
            (is_single and slot == "A") or
            (not is_single and slot == "A" and gesture in (self.G_FIST, self.G_PALM)) or
            (not is_single and slot == "B" and gesture in (self.G_THUMBS_UP, self.G_THUMBS_DOWN))
        )
        if produce_static and gesture in (
            self.G_FIST, self.G_PALM, self.G_POINTING_UP, self.G_THUMBS_UP, self.G_THUMBS_DOWN
        ) and gesture != st.last_static_gesture:
            cooldown_ms = int(sens.get("gesture_cooldown_ms", 800))
            if now * 1000.0 >= st.static_cooldown_until and cooldown_ms > 0:
                events.append({
                    "type": "gesture",
                    "gesture": gesture,
                    "slot": slot,
                    "source": f"gesture:{slot}",
                })
                st.static_cooldown_until = now + cooldown_ms / 1000.0
        st.last_static_gesture = gesture

        # ----- 3) 张掌持续 → 托掌进轮盘（on_send_text） -----
        produce_palm_hold = (is_single and slot == "A") or (not is_single and slot == "A")
        if produce_palm_hold and gesture == self.G_PALM:
            if st.palm_hold_start is None:
                st.palm_hold_start = now
            elif not st.palm_hold_fired:
                held_ms = (now - st.palm_hold_start) * 1000.0
                if held_ms >= float(sens.get("palm_hold_ms", 1800)):
                    st.palm_hold_fired = True
                    if on_send_text is not None:
                        try:
                            on_send_text()
                        except Exception:
                            pass
        else:
            # 张掌中断或被其他手势替代 → 重置
            st.palm_hold_start = None
            st.palm_hold_fired = False

        # ----- 4) 捏合 → 点击（迟滞防抖） -----
        produce_pinch = (is_single and slot == "A") or (not is_single and slot == "B")
        if produce_pinch:
            pinch_th = float(sens.get("pinch_threshold", 0.32))
            pinch_rel = float(sens.get("pinch_release", 0.45))
            if not st.pinching and self._is_pinching(lm, pinch_th, pinch_rel):
                st.pinching = True
                events.append({"cmd": "MOUSE_CLICK", "count": 1, "source": f"gesture:{slot}"})
            elif st.pinching and self._is_pinch_released(lm, pinch_rel):
                st.pinching = False
        else:
            # 不允许该槽位产生捏合 → 重置
            st.pinching = False

        # ----- 5) 左右挥 → 翻页（仅 A 槽，单/双人都由 A 负责导航） -----
        if slot == "A":
            self._update_swipe(lm, st, sens, now, events)

        return events

    def _update_swipe(self, lm, st: HandState, sens: Dict[str, Any],
                      now: float, events: List[Dict[str, Any]]) -> None:
        """基于 wrist x 在时间窗内的位移判定左右挥。"""
        if self._classify_static(lm) != self.G_PALM:
            st.wrist_history.clear()
            return

        wx = float(lm[WRIST].x)
        history_ms = int(sens.get("swipe_history_ms", 240))
        cooldown_ms = int(sens.get("swipe_cooldown_ms", 700))
        min_velocity = float(sens.get("swipe_min_velocity", 0.18))
        if cooldown_ms > 0 and (now - st.last_swire_at) * 1000.0 < cooldown_ms:
            return

        st.wrist_history.append((now, wx))
        # 清理窗口外
        cutoff = now - history_ms / 1000.0
        st.wrist_history = [(t, x) for (t, x) in st.wrist_history if t >= cutoff]
        if len(st.wrist_history) < 3:
            return

        oldest_t, oldest_x = st.wrist_history[0]
        dt = now - oldest_t
        if dt <= 0:
            return
        dx = wx - oldest_x
        velocity = dx / dt
        if abs(velocity) < min_velocity:
            return

        if velocity > 0:
            events.append({
                "type": "gesture",
                "gesture": "SWIPE_RIGHT",
                "slot": slot,
                "source": "gesture:swipe",
            })
        else:
            events.append({
                "type": "gesture",
                "gesture": "SWIPE_LEFT",
                "slot": slot,
                "source": "gesture:swipe",
            })
        st.last_swire_at = now
        st.wrist_history.clear()

    # ------------------------------------------------------------------
    # 配对判定：A 槽 pointing_up 持续 ≥ 1 秒 → 确认
    # ------------------------------------------------------------------
    def _update_pairing(self, now: float) -> None:
        if not self._pairing_active or self._pairing_confirmed:
            return
        elapsed_ms = (now - self._pairing_started) * 1000.0
        if elapsed_ms > self._pairing_window_ms:
            # 超时：本次配对失败
            self._pairing_active = False
            return

        st_a = self._slots["A"]
        # A 槽 pointing_up 稳定时长
        if st_a.last_static_gesture == self.G_POINTING_UP:
            if st_a.pointing_up_start is None:
                st_a.pointing_up_start = now
            elif (now - st_a.pointing_up_start) >= 1.0:
                self._pairing_confirmed = True
        else:
            st_a.pointing_up_start = None