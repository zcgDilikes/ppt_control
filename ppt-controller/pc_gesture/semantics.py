"""混合语义：分类器离散手势 + landmark 连续规则。"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from .config import GestureConfig
from .gestures_wheel import CommandWheelFSM
from .mapper import tool_id_to_payload
from .operator import OperatorContext, OperatorManager, PairState
from .recognizer import FrameResult, HandObservation
from .roles import slot_allows_cmd, wheel_allowed
from .smoothing import Point2DFilter


@dataclass
class SemanticOutput:
    commands: List[Dict[str, Any]] = field(default_factory=list)
    status: str = ""
    armed: bool = False
    wheel_sector: int = -1


def _pinch(h: HandObservation) -> bool:
    if len(h.landmarks) < 9:
        return False
    t = h.landmarks[4]
    i = h.landmarks[8]
    d = math.hypot(t[0] - i[0], t[1] - i[1])
    return d < 0.06


def _palm_open(h: HandObservation) -> bool:
    return h.gesture_name == "Open_Palm" and h.gesture_score >= 0.5


def _is_pointing(h: HandObservation) -> bool:
    return h.gesture_name in ("Pointing_Up", "None") and len(h.landmarks) >= 9


class GestureSemantics:
    def __init__(self, cfg: GestureConfig, on_send_text: Optional[Callable[[], None]] = None):
        self.cfg = cfg
        self.on_send_text = on_send_text
        self.operator_mgr = OperatorManager(cfg)
        self.wheel = CommandWheelFSM(hold_ms=float(cfg.raw.get("wheel_hold_ms") or 800))
        self._laser_filter = Point2DFilter()
        self._vote: Dict[str, Deque[bool]] = {}
        self._cooldown: Dict[str, float] = {}
        self._armed_slots: Dict[str, bool] = {"primary": False, "A": False, "B": False}
        self._wrist_hist: Deque[tuple] = deque(maxlen=8)
        self._last_pinch = False
        self._pinch_count = 0
        self._last_pinch_time = 0.0
        self._gesture_hold: Dict[str, float] = {}

    def reload_config(self, cfg: GestureConfig) -> None:
        self.cfg = cfg
        self.operator_mgr.cfg = cfg

    def _cooldown_ok(self, key: str, cmd: str) -> bool:
        cd = (self.cfg.raw.get("cooldown_ms") or {}).get(cmd, 500)
        now = time.monotonic()
        full = f"{key}:{cmd}"
        last = self._cooldown.get(full, 0)
        if (now - last) * 1000 < cd:
            return False
        self._cooldown[full] = now
        return True

    def _vote_ok(self, name: str, active: bool) -> bool:
        n = int(self.cfg.raw.get("vote_frames") or 3)
        if name not in self._vote:
            self._vote[name] = deque(maxlen=max(n, 5))
        self._vote[name].append(active)
        if len(self._vote[name]) < n:
            return False
        return sum(self._vote[name]) >= n

    def _classifier_active(self, h: HandObservation, name: str) -> bool:
        th = float(self.cfg.raw.get("score_threshold") or 0.72)
        return h.gesture_name == name and h.gesture_score >= th

    def _pick_primary_hand(self, hands: List[HandObservation]) -> Optional[HandObservation]:
        if not hands:
            return None
        pointing = [h for h in hands if _is_pointing(h)]
        return pointing[0] if pointing else hands[0]

    def process_frame(self, frame: FrameResult) -> SemanticOutput:
        out = SemanticOutput()
        hands = frame.hands
        primary_hand = self._pick_primary_hand(hands)
        pointing_up = any(
            h.gesture_name == "Pointing_Up" and h.gesture_score >= 0.5 for h in hands
        )
        ctx = self.operator_mgr.update(hands, pointing_up)
        out.status = ctx.message
        ctrl_hands = self.operator_mgr.hands_for_control(ctx)
        if not ctrl_hands:
            self._laser_filter.reset()
            return out

        ph = self._pick_primary_hand(ctrl_hands)
        if not ph:
            return out

        slot = self.operator_mgr.slot_for_hands(ctx, ph) or "primary"
        mode = ctx.mode

        if pointing_up:
            self._armed_slots[slot] = True
        out.armed = self._armed_slots.get(slot, False)

        if mode == "strict":
            allowed_laser = slot_allows_cmd(self.cfg, slot, "LASER")
            if allowed_laser and (out.armed or self.cfg.raw.get("laser_without_armed", True)):
                self._emit_laser(ph, out)
            return out

        if mode == "cautious":
            if slot_allows_cmd(self.cfg, slot, "LASER"):
                self._emit_laser(ph, out)
            if _pinch(ph) and slot_allows_cmd(self.cfg, slot, "MOUSE_CLICK"):
                self._emit_click(ph, slot, out)
            return out

        self._process_wheel(ctx, ph, slot, hands, out)
        if self.wheel.state.value != "off" and self.wheel.state.value != "arming":
            return out

        if self.cfg.raw.get("laser_without_armed", True) or out.armed:
            if slot_allows_cmd(self.cfg, slot, "LASER"):
                self._emit_laser(ph, out)

        self._emit_pinch(ph, slot, out)
        if out.armed or not self.cfg.raw.get("armed_required", True):
            self._emit_swipe(hands, slot, out)
            self._emit_discrete(hands, slot, out)

        return out

    def _emit_laser(self, h: HandObservation, out: SemanticOutput) -> None:
        t = time.monotonic()
        x, y = h.index_tip
        fx, fy = self._laser_filter.filter(x, y, t)
        out.commands.append({"cmd": "LASER", "x": fx, "y": fy})

    def _emit_click(self, h: HandObservation, slot: str, out: SemanticOutput) -> None:
        p = _pinch(h)
        now = time.monotonic()
        if p and not self._last_pinch:
            if now - self._last_pinch_time < 0.35:
                self._pinch_count += 1
            else:
                self._pinch_count = 1
            self._last_pinch_time = now
            cnt = 2 if self._pinch_count >= 2 else 1
            key = f"{slot}:MOUSE_CLICK"
            if self._cooldown_ok(key, "MOUSE_CLICK"):
                out.commands.append({"cmd": "MOUSE_CLICK", "count": cnt})
                self._pinch_count = 0
        self._last_pinch = p

    def _emit_pinch(self, h: HandObservation, slot: str, out: SemanticOutput) -> None:
        if slot_allows_cmd(self.cfg, slot, "MOUSE_CLICK"):
            self._emit_click(h, slot, out)

    def _emit_swipe(self, hands: List[HandObservation], slot: str, out: SemanticOutput) -> None:
        if not hands:
            return
        h = hands[0]
        self._wrist_hist.append((time.monotonic(), h.wrist[0], h.wrist[1]))
        if len(self._wrist_hist) < 5:
            return
        t0, x0, y0 = self._wrist_hist[0]
        t1, x1, y1 = self._wrist_hist[-1]
        dt = t1 - t0
        if dt < 0.12:
            return
        vx = (x1 - x0) / dt
        if abs(vx) < 0.8:
            return
        if vx > 0 and slot_allows_cmd(self.cfg, slot, "NEXT_PAGE"):
            if self._vote_ok(f"{slot}:swipe_r", True) and self._cooldown_ok(slot, "NEXT_PAGE"):
                out.commands.append({"cmd": "NEXT_PAGE"})
        elif vx < 0 and slot_allows_cmd(self.cfg, slot, "PREV_PAGE"):
            if self._vote_ok(f"{slot}:swipe_l", True) and self._cooldown_ok(slot, "PREV_PAGE"):
                out.commands.append({"cmd": "PREV_PAGE"})

    def _emit_discrete(self, hands: List[HandObservation], slot: str, out: SemanticOutput) -> None:
        for h in hands:
            now = time.monotonic()
            if self._classifier_active(h, "Thumb_Up"):
                if self._vote_ok(f"{slot}:thumb_up", True) and self._cooldown_ok(slot, "FULL_SCREEN"):
                    out.commands.append({"cmd": "FULL_SCREEN"})
            if self._classifier_active(h, "Closed_Fist"):
                key = f"{slot}:fist"
                if key not in self._gesture_hold:
                    self._gesture_hold[key] = now
                elif (now - self._gesture_hold[key]) >= 0.6:
                    if self._cooldown_ok(slot, "BLACK_SCREEN"):
                        out.commands.append({"cmd": "BLACK_SCREEN"})
            else:
                self._gesture_hold.pop(f"{slot}:fist", None)

            if self._classifier_active(h, "Open_Palm"):
                key = f"{slot}:palm"
                if key not in self._gesture_hold:
                    self._gesture_hold[key] = now
                elif (now - self._gesture_hold[key]) >= 0.6:
                    if self._cooldown_ok(slot, "WHITE_SCREEN"):
                        out.commands.append({"cmd": "WHITE_SCREEN"})
            else:
                self._gesture_hold.pop(f"{slot}:palm", None)

            if self._classifier_active(h, "Thumb_Down"):
                if self._vote_ok(f"{slot}:thumb_down", True) and self._cooldown_ok(slot, "EXIT"):
                    out.commands.append({"cmd": "EXIT"})

    def _process_wheel(
        self,
        ctx: OperatorContext,
        ph: HandObservation,
        slot: str,
        hands: List[HandObservation],
        out: SemanticOutput,
    ) -> None:
        if not wheel_allowed(self.cfg, slot):
            return
        tray = sum(1 for h in hands if _palm_open(h)) >= 1 and len(hands) >= 1
        st = self.wheel.update_tray_pose(tray)
        if st.state.value == "open":
            sec = self.wheel.update_point(ph.index_tip[0], ph.index_tip[1])
            out.wheel_sector = sec
            sectors = self.cfg.raw.get("wheel_sectors") or []
            if _pinch(ph):
                confirmed = self.wheel.confirm_pinch()
                if 0 <= confirmed < len(sectors):
                    tid = sectors[confirmed]
                    payload = tool_id_to_payload(tid)
                    if payload:
                        if payload.get("_needs_dialog"):
                            if self.on_send_text:
                                self.on_send_text()
                        elif slot_allows_cmd(self.cfg, slot, payload["cmd"]):
                            out.commands.append(payload)
        if any(self._classifier_active(h, "Closed_Fist") for h in hands):
            self.wheel.cancel_fist()
