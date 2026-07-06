"""
pc_gesture.semantics
====================

每帧把手部关键点（21 个 NormalizedLandmark）分类为「事件」，供 GestureEngine 派发。

主要分类：
    OK / L / 三指 / 食指（激光）/ 剪刀 / 拳头 / 张掌 / 捏合（点击）

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
    # 上一次识别的手势类别(用于防抖/冷却)
    last_static_gesture: str = "NONE"                # OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM / NONE
    last_static_at: float = 0.0                      # 上一次识别到非 NONE 手势的 wall-clock,用于 auto-reset
    static_cooldown_until: float = 0.0
    # 捏合迟滞
    pinching: bool = False
    # 激光上一帧坐标(用于 EMA)
    laser_last_xy: Optional[Tuple[float, float]] = None
    # 配对确认累计:某 slot 在 pointing_up 上稳定了多久
    pointing_up_start: Optional[float] = None


# ---------------------------------------------------------------------------
# GestureSemantics
# ---------------------------------------------------------------------------
class GestureSemantics:
    """状态机 + 分类器。"""

    # 静态手势类别(机器友好 enum,UI 通过 _GESTURE_META 映射到中文 + emoji)
    G_NONE = "NONE"
    G_OK = "OK"                          # 拇指+食指圈,中/无名/小指伸
    G_L_SIGN = "L_SIGN"                  # 拇+食指伸(分开),其它卷
    G_THREE_FINGERS = "THREE_FINGERS"    # 拇+食+中伸,无名+小卷
    G_POINTING_UP = "POINTING_UP"        # 仅食指伸
    G_SCISSORS = "SCISSORS"              # 食+中伸,其它卷
    G_FIST = "FIST"                      # 全卷
    G_PALM = "PALM"                      # 全伸

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
        try:
            self._pairing_window_ms: int = int(
                self.cfg.sensitivity.get("pairing_window_ms", 3000)
            )
        except (TypeError, ValueError):
            self._pairing_window_ms = 3000

    # ------------------------------------------------------------------
    # 配置热更新
    # ------------------------------------------------------------------
    def reload_config(self, cfg: GestureConfig) -> None:
        self.cfg = cfg
        # 清空运行时状态，避免旧阈值下的历史造成误判
        for slot in self._slots.values():
            slot.last_static_gesture = self.G_NONE
            slot.last_static_at = 0.0
            slot.static_cooldown_until = 0.0
            slot.pinching = False
            slot.laser_last_xy = None
            slot.pointing_up_start = None
        # info.txt 三.2:热更新配置时也重置配对状态,避免新旧阈值冲突
        self._pairing_active = False
        self._pairing_confirmed = False
        self._pairing_started = 0.0

    # ------------------------------------------------------------------
    # 配对（仅在 dual 模式下生效）
    # ------------------------------------------------------------------
    def start_pairing(self, window_ms: Optional[int] = None) -> None:
        if window_ms is None:
            window_ms = self._pairing_window_ms
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
        """以 wrist→middle MCP 距离作为手掌参考长度(归一化坐标下通常 0.15~0.35)。

        双向夹紧:极端近距离手部时 size 趋近 0 会除以极小值造成距离归一化爆炸;
        极端远距离时 size 超过 0.5 也是异常(超过真人手部比例)。
        """
        raw = _dist(lm[WRIST].x, lm[WRIST].y, lm[MIDDLE_MCP].x, lm[MIDDLE_MCP].y)
        return min(max(raw, 0.05), 0.5)

    def _classify_static(self, lm) -> str:
        """返回 7 个新 enum 之一(NONE / OK / L_SIGN / THREE_FINGERS / POINTING_UP / SCISSORS / FIST / PALM)。

        优先级(从最特异到最普通):
          1. OK          — 拇-食指尖接触 + 中/无名/小指 >= 2 指伸(软阈值)
          2. L_SIGN      — 拇横向伸 + 食指伸 + 中/无名/小指卷 + 拇-食指分开
          3. THREE_FINGERS — 拇横向伸 + 食+中伸 + 无名+小指卷
          4. SCISSORS    — 拇卷 + 食+中伸 + 无名+小指卷
          5. POINTING_UP — 拇卷 + 仅食指伸 + 中/无名/小指卷
          6. FIST        — 拇卷 + 食指卷 + 中/无名/小指卷
          7. PALM        — 拇横向伸 + 4 指都伸

        info.txt 五.1:阈值从 cfg.sensitivity 读,默认值见 config.py。
        """
        sens = self.cfg.sensitivity
        size = self._hand_size(lm)
        # 异常配置 fallback 到默认值
        try:
            thumb_touch_thr = float(sens.get("thumb_touch_ratio", 0.08))
        except (TypeError, ValueError):
            thumb_touch_thr = 0.08
        try:
            thumb_extend_thr = float(sens.get("thumb_extend_ratio", 0.18))
        except (TypeError, ValueError):
            thumb_extend_thr = 0.18
        try:
            ext_strict_y = float(sens.get("ext_strict_y", 0.025))
        except (TypeError, ValueError):
            ext_strict_y = 0.025
        try:
            ext_relaxed_y = float(sens.get("ext_relaxed_y", 0.015))
        except (TypeError, ValueError):
            ext_relaxed_y = 0.015
        try:
            curl_y = float(sens.get("curl_y", 0.005))
        except (TypeError, ValueError):
            curl_y = 0.005

        # 拇指状态
        thumb_index_tip_dist = _dist(
            lm[THUMB_TIP].x, lm[THUMB_TIP].y,
            lm[INDEX_TIP].x, lm[INDEX_TIP].y,
        )
        thumb_index_mcp_dist = _dist(
            lm[THUMB_TIP].x, lm[THUMB_TIP].y,
            lm[INDEX_MCP].x, lm[INDEX_MCP].y,
        )
        thumb_touching = thumb_index_tip_dist < thumb_touch_thr * size
        thumb_extended = thumb_index_mcp_dist > thumb_extend_thr * size

        # 4 指状态(OK 软阈值用 ext_relaxed_y,其它严守 ext_strict_y)
        def ext_strict(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y - ext_strict_y
        def ext_relaxed(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y - ext_relaxed_y
        def curled(tip_idx, pip_idx):
            return lm[tip_idx].y > lm[pip_idx].y + curl_y

        index_ext = ext_strict(INDEX_TIP, INDEX_PIP)
        middle_ext = ext_strict(MIDDLE_TIP, MIDDLE_PIP)
        ring_ext = ext_strict(RING_TIP, RING_PIP)
        pinky_ext = ext_strict(PINKY_TIP, PINKY_PIP)

        middle_curled = curled(MIDDLE_TIP, MIDDLE_PIP)
        ring_curled = curled(RING_TIP, RING_PIP)
        pinky_curled = curled(PINKY_TIP, PINKY_PIP)

        # OK 软阈值:中/无名/小指 >= 2 指 soft-extended
        other_3_extended_relaxed_count = sum([
            ext_relaxed(MIDDLE_TIP, MIDDLE_PIP),
            ext_relaxed(RING_TIP, RING_PIP),
            ext_relaxed(PINKY_TIP, PINKY_PIP),
        ])

        # 1) OK — 最优先:空间距离 + 数量
        if thumb_touching and other_3_extended_relaxed_count >= 2:
            return self.G_OK

        # 2) L_SIGN — 拇横向 + 食指伸 + 其它卷 + 拇-食指分开
        if thumb_extended and index_ext and middle_curled and ring_curled and pinky_curled and not thumb_touching:
            return self.G_L_SIGN

        # 3) THREE_FINGERS — 拇横向 + 食+中伸 + 无名+小卷
        if thumb_extended and index_ext and middle_ext and ring_curled and pinky_curled:
            return self.G_THREE_FINGERS

        # 4) SCISSORS — 拇卷 + 食+中伸 + 无名+小卷
        if not thumb_extended and index_ext and middle_ext and ring_curled and pinky_curled:
            return self.G_SCISSORS

        # 5) POINTING_UP — 拇卷 + 仅食指伸
        if not thumb_extended and index_ext and middle_curled and ring_curled and pinky_curled:
            return self.G_POINTING_UP

        # 6) FIST — 拇卷 + 食指卷 + 中/无名/小卷
        if not thumb_extended and not index_ext and middle_curled and ring_curled and pinky_curled:
            return self.G_FIST

        # 7) PALM — 拇横向 + 4 指都伸(info.txt 二.4:用 relaxed 阈值,自然摊开手不再 NONE)
        palm_index_ext = ext_relaxed(INDEX_TIP, INDEX_PIP)
        palm_middle_ext = ext_relaxed(MIDDLE_TIP, MIDDLE_PIP)
        palm_ring_ext = ext_relaxed(RING_TIP, RING_PIP)
        palm_pinky_ext = ext_relaxed(PINKY_TIP, PINKY_PIP)
        if thumb_extended and palm_index_ext and palm_middle_ext and palm_ring_ext and palm_pinky_ext:
            return self.G_PALM

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
    ) -> List[Dict[str, Any]]:
        """输入 MediaPipe Tasks HandLandmarker.detect 的结果；返回要派发的事件列表。"""
        sens = self.cfg.sensitivity
        now = time.monotonic()
        events: List[Dict[str, Any]] = []
        # 当前帧活跃的槽位集合
        active_slots = set()
        # info.txt 五.2:低置信度手部(遮挡、远距离)仍走完整分类,造成算力浪费 + 误触。
        # 用 MediaPipe handedness.score 过滤。低于阈值的手部跳过分类。
        try:
            min_confidence = float(sens.get("low_confidence_threshold", 0.6))
        except (TypeError, ValueError):
            min_confidence = 0.6

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
                    # 跳过此手,但不让手部消失清理逻辑误清
                    # active_slots 不加 → 走 hand-leave 清理路径
                    continue
                slot = self._assign_slot(lm_list, self.cfg.dual_roles_swapped)
                st = self._slots[slot]
                st.last_seen_monotonic = now
                active_slots.add(slot)
                events.extend(self._process_one_hand(lm_list, slot, st, sens, now))

        # 配对窗口中：A 槽（屏幕左）持续 pointing_up 满 1 秒 → 确认
        self._update_pairing(now)

        # 没出现在本帧的槽位:清理与该手相关的瞬时状态
        # info.txt 三.1:手部消失 hand_lost_cleanup_s 后,也要清空 last_static_gesture + 冷却,
        # 否则手重新入画面会等冷却走完才能再次触发。
        try:
            hand_lost_s = float(sens.get("hand_lost_cleanup_s", 0.5))
        except (TypeError, ValueError):
            hand_lost_s = 0.5
        for slot, st in self._slots.items():
            if slot not in active_slots:
                if now - st.last_seen_monotonic > hand_lost_s:
                    st.pinching = False
                    st.laser_last_xy = None
                    st.pointing_up_start = None
                    # 重置手势状态,让手重新入画面能立即响应
                    st.last_static_gesture = self.G_NONE
                    st.last_static_at = 0.0
                    st.static_cooldown_until = 0.0

        return events

    # ------------------------------------------------------------------
    # 单只手处理
    # ------------------------------------------------------------------
    def _process_one_hand(self, lm, slot: str, st: HandState,
                          sens: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        operator_mode = self.cfg.operator_mode
        is_single = operator_mode == "single"

        # 静态手势分类
        gesture = self._classify_static(lm)

        # 在单人模式下，仅 A 槽产生指令；B 槽只用于预览
        # 在双人模式下，A 负责导航（挥页），B 负责指控（其余）
        # 注意：单/双人 角色映射由调用方（GestureEngine）决定；
        # 这里只负责「单只手能产生哪些事件」，由 slot 在合适时跳过。

        # 统一时间戳字段(info.txt 四.1):所有事件带 ts (秒, monotonic) 和
        # ts_ms (毫秒, int),上层能时序对齐、做防抖。
        ts = now
        ts_ms = int(now * 1000)

        # ----- 1) 激光（食指上指） -----
        # 单人：仅 A 槽产生激光；双人：B 槽产生激光
        # NOTE: laser emits a per-frame ``cmd:LASER`` payload so the cursor
        # follows the fingertip smoothly. The bridge / dispatcher uses
        # ``cmd`` payloads for laser motion and ``type=gesture`` payloads for
        # one-shot rising-edge bindings. These two channels are kept distinct.
        produce_laser = (is_single and slot == "A") or (not is_single and slot == "B")
        if produce_laser and gesture == self.G_POINTING_UP:
            tx = float(lm[INDEX_TIP].x)
            ty = float(lm[INDEX_TIP].y)
            # info.txt 六.3:异常兜底。配置可能传字符串/None/负数,不再直接报错。
            try:
                smoothing = float(sens.get("laser_smoothing", 0.55))
            except (TypeError, ValueError):
                smoothing = 0.55
            smoothing = max(0.0, min(0.95, smoothing))
            if st.laser_last_xy is not None:
                tx = smoothing * st.laser_last_xy[0] + (1.0 - smoothing) * tx
                ty = smoothing * st.laser_last_xy[1] + (1.0 - smoothing) * ty
            st.laser_last_xy = (tx, ty)
            # Per-frame cmd payload — kept distinct from the rising-edge
            # ``type=gesture`` event below so the bridge can route bindings
            # on transitions only, while laser motion streams every frame.
            events.append({
                "cmd": "LASER", "x": tx, "y": ty,
                "ts": ts, "ts_ms": ts_ms,
                "source": f"gesture:{slot}",
            })
        else:
            # 非 pointing_up → 停止激光平滑(下次重新起步)
            st.laser_last_xy = None

        # ----- 2) 一次性静态手势（带冷却） -----
        # 单人模式：仅 A 槽触发（用户操作的主手）。
        # 双人模式：A 和 B 两槽都能触发全部 7 个手势（slot 仅用于诊断/UI）。
        # 这样所有 7 个新手势在任何模式下都能用。
        produce_static = (
            (is_single and slot == "A") or
            (not is_single and slot in ("A", "B"))
        )

        # 自动重置 last_static_gesture:当用户把手放下回到 NONE 持续 static_reset_idle_s 秒,
        # 允许同一手势再次触发(不强制用户先切到别的再切回来)。这是「连点 OK」灵敏度的关键。
        try:
            reset_idle_s = float(sens.get("static_reset_idle_s", 0.3))
        except (TypeError, ValueError):
            reset_idle_s = 0.3
        if gesture != self.G_NONE:
            st.last_static_at = now
        elif st.last_static_gesture != self.G_NONE and (now - st.last_static_at) > reset_idle_s:
            st.last_static_gesture = self.G_NONE  # auto-reset

        if produce_static and gesture in (
            self.G_OK, self.G_L_SIGN, self.G_THREE_FINGERS,
            self.G_POINTING_UP, self.G_SCISSORS,
            self.G_FIST, self.G_PALM,
        ) and gesture != st.last_static_gesture:
            cooldown_ms = int(sens.get("gesture_cooldown_ms", 400))  # 默认 400ms(原 800ms 太慢)
            # 修复:now 是 time.monotonic() 秒,static_cooldown_until 也是秒。直接比较,不要乘 1000。
            # 旧逻辑 now * 1000.0 >= static_cooldown_until 单位不匹配,冷却形同虚设。
            debug_log = sens.get("debug_log", False)
            if now >= st.static_cooldown_until and cooldown_ms > 0:
                if debug_log:
                    print(f"[semantics] 🎯 识别 {gesture} (slot={slot}) → 派发 type=gesture")
                events.append({
                    "type": "gesture",
                    "gesture": gesture,
                    "slot": slot,
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
                st.static_cooldown_until = now + cooldown_ms / 1000.0
            else:
                if debug_log:
                    print(f"[semantics] ⏸️  {gesture} 被冷却挡住 ({now - st.static_cooldown_until:.2f}s 剩余)")
        # info.txt 四.2:手势结束事件。上一帧有手势 + 本帧 NONE → 发 gesture_end。
        # 这让上层能实现「长按手势持续触发、抬手取消」等逻辑。
        elif st.last_static_gesture != self.G_NONE and gesture == self.G_NONE:
            events.append({
                "type": "gesture_end",
                "gesture": st.last_static_gesture,
                "slot": slot,
                "ts": ts, "ts_ms": ts_ms,
                "source": f"gesture:{slot}",
            })
        st.last_static_gesture = gesture

        # ----- 3) 捏合 → 点击（迟滞防抖） -----
        produce_pinch = (is_single and slot == "A") or (not is_single and slot == "B")
        if produce_pinch:
            pinch_th = float(sens.get("pinch_threshold", 0.32))
            pinch_rel = float(sens.get("pinch_release", 0.45))
            if not st.pinching and self._is_pinching(lm, pinch_th, pinch_rel):
                st.pinching = True
                events.append({
                    "cmd": "MOUSE_CLICK", "count": 1,
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
                # info.txt 一.2:同步发 MOUSE_DOWN,支持长按拖拽
                events.append({
                    "cmd": "MOUSE_DOWN",
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
            elif st.pinching and self._is_pinch_released(lm, pinch_rel):
                st.pinching = False
                # info.txt 一.2:捏合松开发 MOUSE_UP,告诉上层「拖拽已结束」
                events.append({
                    "cmd": "MOUSE_UP",
                    "ts": ts, "ts_ms": ts_ms,
                    "source": f"gesture:{slot}",
                })
        else:
            # 不允许该槽位产生捏合 → 重置
            st.pinching = False

        return events

    # ------------------------------------------------------------------
    # 配对判定:任意槽 pointing_up 持续 ≥ 1 秒 → 确认
    # info.txt 一.3:之前硬编码只看 slot A,dual_roles_swapped=True 时配对失效。
    # 修复:扫描所有 slot,任意一个正在做 pointing_up 都开始累计;任一达到 1s 即可确认。
    # ------------------------------------------------------------------
    def _update_pairing(self, now: float) -> None:
        if not self._pairing_active or self._pairing_confirmed:
            return
        elapsed_ms = (now - self._pairing_started) * 1000.0
        if elapsed_ms > self._pairing_window_ms:
            # 超时:本次配对失败
            self._pairing_active = False
            return

        # 任一 slot 正在 pointing_up,各自独立累计
        # 配对成功所需 pointing_up 持续秒数(从 sens 读,fallback 1.0)
        try:
            pointing_up_s = float(self.cfg.sensitivity.get("pairing_pointing_up_s", 1.0))
        except (TypeError, ValueError):
            pointing_up_s = 1.0
        for slot in self._slots.values():
            if slot.last_static_gesture == self.G_POINTING_UP:
                if slot.pointing_up_start is None:
                    slot.pointing_up_start = now
                elif (now - slot.pointing_up_start) >= pointing_up_s:
                    self._pairing_confirmed = True
                    return
            else:
                slot.pointing_up_start = None