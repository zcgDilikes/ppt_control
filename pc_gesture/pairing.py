"""PairingService — business logic for confirming which hand is the controller.

info.txt 六.2: 配对属于业务交互逻辑,不应和手部几何分类(semantics)耦合。
独立成 PairingService,semantics 通过 update() 喂 slot 状态,得到 confirmed
状态。

Pairing semantics:
  1. start_pairing() 后开始窗口(window_ms 默认 3s)
  2. 任一 slot 的 pointing_up 持续 >= pointing_up_s(默认 1s)→ 确认
  3. 窗口结束前未确认 → 失败
  4. 确认后 pairing_state = "CONFIRMED",配对回调触发
"""
from __future__ import annotations

import time
from typing import Dict, Optional


class PairingService:
    """配对状态机。配对逻辑(业务)与手势分类(几何)解耦。"""

    PAIRING_IDLE = "IDLE"
    PAIRING_WAITING = "WAITING"
    PAIRING_CONFIRMED = "CONFIRMED"
    PAIRING_EXPIRED = "EXPIRED"

    def __init__(self, sensitivity: Dict[str, float]):
        self._sensitivity = sensitivity
        self._active: bool = False
        self._started: float = 0.0
        self._confirmed: bool = False
        # A-2:窗口过期标志,保留 _active 让 state 仍能返回 EXPIRED(而非 IDLE)
        self._expired: bool = False
        self._active_window_ms: int = 0
        self._slot_pointing_up_start: Dict[str, Optional[float]] = {"A": None, "B": None}

    def start(self, window_ms: Optional[int] = None) -> None:
        """启动配对窗口。window_ms=None 用 cfg 默认值。"""
        if window_ms is None:
            try:
                window_ms = int(self._sensitivity.get("pairing_window_ms", 3000))
            except (TypeError, ValueError):
                window_ms = 3000
        self._active_window_ms = max(500, int(window_ms))
        self._active = True
        self._expired = False
        self._started = time.monotonic()
        self._confirmed = False
        for slot in self._slot_pointing_up_start:
            self._slot_pointing_up_start[slot] = None

    def reset(self) -> None:
        """取消配对,清空所有状态。"""
        self._active = False
        self._confirmed = False
        self._expired = False
        self._started = 0.0
        for slot in self._slot_pointing_up_start:
            self._slot_pointing_up_start[slot] = None

    def update(self, slot_gestures: Dict[str, str], pointing_up_enum: str) -> bool:
        """每帧调用一次,喂 slot → 当前 gesture 状态。

        Returns True iff this update triggered confirmation。
        A-3:update 内部用 time.monotonic() 单一时间源,跟 state 一致。
        """
        if not self._active or self._confirmed:
            return False
        now = time.monotonic()
        elapsed_ms = (now - self._started) * 1000.0
        if elapsed_ms > self._active_window_ms:
            # A-2:超时设 _expired=True 保留 _active,state 可返 EXPIRED
            self._expired = True
            return False

        try:
            pointing_up_s = float(self._sensitivity.get("pairing_pointing_up_s", 1.0))
        except (TypeError, ValueError):
            pointing_up_s = 1.0

        # 任一 slot 正在 pointing_up,各自独立累计
        for slot, gesture in slot_gestures.items():
            if gesture == pointing_up_enum:
                if self._slot_pointing_up_start[slot] is None:
                    self._slot_pointing_up_start[slot] = now
                elif (now - self._slot_pointing_up_start[slot]) >= pointing_up_s:
                    self._confirmed = True
                    return True
            else:
                self._slot_pointing_up_start[slot] = None
        return False

    @property
    def state(self) -> str:
        """IDLE / WAITING / CONFIRMED / EXPIRED。"""
        if self._confirmed:
            return self.PAIRING_CONFIRMED
        if self._expired:
            return self.PAIRING_EXPIRED
        if not self._active:
            return self.PAIRING_IDLE
        elapsed_ms = (time.monotonic() - self._started) * 1000.0
        if elapsed_ms > self._active_window_ms:
            return self.PAIRING_EXPIRED
        return self.PAIRING_WAITING

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def active(self) -> bool:
        return self._active
