"""指尖与坐标平滑。"""

from __future__ import annotations


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = None
        self._dx = 0.0
        self._last_t = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * 3.141592653589793 * cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def __call__(self, x: float, t: float) -> float:
        if self._last_t is None:
            self._x = float(x)
            self._last_t = float(t)
            return self._x
        dt = max(float(t) - self._last_t, 1e-6)
        self._last_t = float(t)
        dx = (float(x) - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1.0 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x = a * float(x) + (1.0 - a) * self._x
        return self._x


class Point2DFilter:
    def __init__(self):
        self._fx = OneEuroFilter()
        self._fy = OneEuroFilter()

    def filter(self, x: float, y: float, t: float) -> tuple:
        return self._fx(x, t), self._fy(y, t)

    def reset(self) -> None:
        self._fx = OneEuroFilter()
        self._fy = OneEuroFilter()
