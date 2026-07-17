"""单人主控选举与双人协作槽位。"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .config import GestureConfig
from .recognizer import HandObservation


class PairState(Enum):
    IDLE = "idle"
    WAIT_A = "wait_a"
    WAIT_B = "wait_b"
    READY = "ready"


@dataclass
class OperatorCluster:
    hands: List[HandObservation]
    wrist_center: Tuple[float, float]
    bbox_area: float
    in_center_roi: bool
    in_slot_a: bool
    in_slot_b: bool
    slot: Optional[str] = None  # A, B, or None


@dataclass
class OperatorContext:
    mode: str = "normal"
    primary_slot: Optional[str] = None
    pair_state: PairState = PairState.IDLE
    operator_count: int = 0
    message: str = ""
    profile_a: Optional[Tuple[float, float]] = None
    profile_b: Optional[Tuple[float, float]] = None
    clusters: List[OperatorCluster] = field(default_factory=list)


def _in_roi(wx: float, wy: float, roi: dict) -> bool:
    x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 1), roi.get("h", 1)
    return x <= wx <= x + w and y <= wy <= y + h


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def cluster_hands(hands: List[HandObservation], cfg: GestureConfig) -> List[OperatorCluster]:
    if not hands:
        return []
    used = set()
    clusters: List[OperatorCluster] = []
    center_roi = cfg.raw.get("center_roi") or {}
    dual = cfg.raw.get("dual_roi") or {}
    roi_a = dual.get("a") or {}
    roi_b = dual.get("b") or {}
    max_pair = float(cfg.raw.get("wrist_pair_max_dist") or 0.35)

    for i, h in enumerate(hands):
        if i in used:
            continue
        group = [h]
        used.add(i)
        for j, h2 in enumerate(hands):
            if j in used:
                continue
            if _dist(h.wrist, h2.wrist) < max_pair:
                group.append(h2)
                used.add(j)
        wx = sum(x.wrist[0] for x in group) / len(group)
        wy = sum(x.wrist[1] for x in group) / len(group)
        area = sum(x.bbox_area for x in group)
        clusters.append(
            OperatorCluster(
                hands=group,
                wrist_center=(wx, wy),
                bbox_area=area,
                in_center_roi=_in_roi(wx, wy, center_roi),
                in_slot_a=_in_roi(wx, wy, roi_a),
                in_slot_b=_in_roi(wx, wy, roi_b),
            )
        )
    return clusters


class OperatorManager:
    def __init__(self, cfg: GestureConfig):
        self.cfg = cfg
        self.locked_primary: Optional[int] = None
        self._primary_idx: Optional[int] = None
        self._primary_score_lead_since: Optional[float] = None
        self.pair_state = PairState.IDLE
        self.profile_a: Optional[Tuple[float, float]] = None
        self.profile_b: Optional[Tuple[float, float]] = None
        self._pair_hold_start: Optional[float] = None
        self._pair_slot: Optional[str] = None
        self.manual_lock_slot: Optional[str] = None

    def reset_pairing(self) -> None:
        self.pair_state = PairState.IDLE
        self.profile_a = None
        self.profile_b = None
        self._pair_hold_start = None
        self._pair_slot = None

    def start_pairing(self) -> None:
        self.reset_pairing()
        self.pair_state = PairState.WAIT_A

    def _score_cluster(self, c: OperatorCluster, idx: int) -> float:
        s = c.bbox_area * 100.0
        if c.in_center_roi:
            s += 50.0
        if self._primary_idx == idx:
            s += 20.0
        return s

    def _assign_dual_slots(self, clusters: List[OperatorCluster]) -> None:
        if not self.profile_a or not self.profile_b:
            return
        for c in clusters:
            da = _dist(c.wrist_center, self.profile_a)
            db = _dist(c.wrist_center, self.profile_b)
            c.slot = "A" if da <= db else "B"

    def _match_profile(self, wrist: Tuple[float, float], profile: Tuple[float, float]) -> bool:
        return _dist(wrist, profile) < 0.12

    def update(self, hands: List[HandObservation], pointing_up: bool) -> OperatorContext:
        cfg = self.cfg
        clusters = cluster_hands(hands, cfg)
        ctx = OperatorContext(
            mode="normal",
            pair_state=self.pair_state,
            operator_count=len([c for c in clusters if c.in_center_roi or c.in_slot_a or c.in_slot_b]),
            profile_a=self.profile_a,
            profile_b=self.profile_b,
            clusters=clusters,
        )

        if cfg.operator_mode == "dual":
            return self._update_dual(ctx, clusters, pointing_up)

        return self._update_single(ctx, clusters)

    def _update_dual(
        self,
        ctx: OperatorContext,
        clusters: List[OperatorCluster],
        pointing_up: bool,
    ) -> OperatorContext:
        now = time.monotonic()
        if self.pair_state == PairState.WAIT_A:
            ctx.message = "请在左侧举起食指 1 秒完成 A 槽位配对"
            for c in clusters:
                if c.in_slot_a and pointing_up:
                    if self._pair_hold_start is None:
                        self._pair_hold_start = now
                    elif now - self._pair_hold_start >= 1.0:
                        self.profile_a = c.wrist_center
                        self.pair_state = PairState.WAIT_B
                        self._pair_hold_start = None
                        ctx.message = "请在右侧举起食指 1 秒完成 B 槽位配对"
                    return ctx
            self._pair_hold_start = None
            return ctx

        if self.pair_state == PairState.WAIT_B:
            for c in clusters:
                if c.in_slot_b and pointing_up:
                    if self._pair_hold_start is None:
                        self._pair_hold_start = now
                    elif now - self._pair_hold_start >= 1.0:
                        if self.profile_a and _dist(c.wrist_center, self.profile_a) < 0.15:
                            ctx.message = "请与左侧协作者分开站立"
                            self._pair_hold_start = None
                            return ctx
                        self.profile_b = c.wrist_center
                        self.pair_state = PairState.READY
                        self._pair_hold_start = None
                        ctx.message = "双人协作已就绪"
                    return ctx
            self._pair_hold_start = None
            return ctx

        if self.pair_state != PairState.READY:
            ctx.message = "请点击「开始配对」"
            ctx.mode = "idle"
            return ctx

        self._assign_dual_slots(clusters)
        active = [c for c in clusters if c.slot in ("A", "B")]
        if len(active) >= 3:
            ctx.mode = "strict"
            ctx.message = "检测到多人，已忽略第三人"
        else:
            ctx.mode = "dual_active"
            ctx.message = "双人协作中"
        return ctx

    def _update_single(self, ctx: OperatorContext, clusters: List[OperatorCluster]) -> OperatorContext:
        candidates = [c for c in clusters if c.in_center_roi] or clusters
        if not candidates:
            ctx.mode = "idle"
            ctx.message = "未检测到手部"
            self._primary_idx = None
            return ctx

        scored = sorted(
            [(i, self._score_cluster(c, i)) for i, c in enumerate(candidates)],
            key=lambda x: -x[1],
        )
        best_i, best_s = scored[0]
        now = time.monotonic()

        if self._primary_idx is not None and self._primary_idx < len(candidates):
            if best_i != self._primary_idx:
                challenger = best_s
                current = self._score_cluster(candidates[self._primary_idx], self._primary_idx)
                if challenger > current * 1.15:
                    if self._primary_score_lead_since is None:
                        self._primary_score_lead_since = now
                    elif (now - self._primary_score_lead_since) * 1000 >= float(
                        self.cfg.raw.get("primary_switch_hold_ms") or 1500
                    ):
                        self._primary_idx = best_i
                        self._primary_score_lead_since = None
                else:
                    self._primary_score_lead_since = None
            else:
                self._primary_score_lead_since = None
        else:
            self._primary_idx = best_i

        n = len(candidates)
        if n >= 3:
            ctx.mode = "strict"
            ctx.message = "多人同框，仅激光"
        elif n == 2:
            ctx.mode = "cautious"
            ctx.message = "检测到两人，仅主控激光/点击"
        else:
            ctx.mode = "normal"
            ctx.message = "主控就绪"

        primary = candidates[self._primary_idx]
        ctx.primary_slot = "primary"
        for i, c in enumerate(clusters):
            if c.wrist_center == primary.wrist_center:
                c.slot = "primary"
        return ctx

    def hands_for_control(self, ctx: OperatorContext) -> List[HandObservation]:
        if self.cfg.operator_mode == "dual":
            if self.pair_state != PairState.READY:
                return []
            out: List[HandObservation] = []
            for c in ctx.clusters:
                if c.slot in ("A", "B"):
                    out.extend(c.hands)
            return out
        for c in ctx.clusters:
            if c.slot == "primary":
                return list(c.hands)
        if ctx.clusters and self._primary_idx is not None:
            idx = min(self._primary_idx, len(ctx.clusters) - 1)
            return list(ctx.clusters[idx].hands)
        return []

    def slot_for_hands(self, ctx: OperatorContext, hand: HandObservation) -> Optional[str]:
        for c in ctx.clusters:
            if hand in c.hands:
                return c.slot
        return None
