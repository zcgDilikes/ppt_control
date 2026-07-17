"""指令轮盘 FSM。"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WheelState(Enum):
    OFF = "off"
    ARMING = "arming"
    OPEN = "open"
    ADJUST = "adjust"


@dataclass
class WheelStatus:
    state: WheelState = WheelState.OFF
    sector: int = -1
    hold_progress: float = 0.0


class CommandWheelFSM:
    def __init__(self, hold_ms: float = 800, num_sectors: int = 12):
        self.hold_ms = hold_ms
        self.num_sectors = num_sectors
        self.state = WheelState.OFF
        self._hold_start: Optional[float] = None
        self.selected_sector = -1
        self._tray_pose = False

    def reset(self) -> None:
        self.state = WheelState.OFF
        self._hold_start = None
        self.selected_sector = -1
        self._tray_pose = False

    def update_tray_pose(self, active: bool) -> WheelStatus:
        now = time.monotonic()
        if active:
            if self._hold_start is None:
                self._hold_start = now
            prog = min(1.0, (now - self._hold_start) * 1000.0 / max(self.hold_ms, 1))
            if prog >= 1.0 and self.state == WheelState.OFF:
                self.state = WheelState.OPEN
            return WheelStatus(
                state=WheelState.ARMING if self.state == WheelState.OFF else self.state,
                hold_progress=prog,
            )
        self._hold_start = None
        if self.state in (WheelState.ARMING,):
            self.state = WheelState.OFF
        return WheelStatus(state=self.state)

    def update_point(self, nx: float, ny: float) -> int:
        if self.state != WheelState.OPEN:
            return -1
        dx = nx - 0.5
        dy = 0.5 - ny
        ang = math.atan2(dy, dx)
        sector = int(((ang + math.pi) / (2 * math.pi)) * self.num_sectors) % self.num_sectors
        self.selected_sector = sector
        return sector

    def confirm_pinch(self) -> int:
        if self.state == WheelState.OPEN and self.selected_sector >= 0:
            s = self.selected_sector
            self.reset()
            return s
        return -1

    def cancel_fist(self) -> None:
        self.reset()
