"""MediaPipe GestureRecognizer 封装。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import numpy as np

from .config import MODEL_PATH, ensure_model_file

_HAS_MP = False
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    _HAS_MP = True
except ImportError:
    mp = None


@dataclass
class HandObservation:
    index: int
    handedness: str
    landmarks: List[tuple]  # 21 x (x,y,z) normalized image coords
    gesture_name: str
    gesture_score: float
    wrist: tuple
    bbox_area: float

    @property
    def index_tip(self) -> tuple:
        if len(self.landmarks) > 8:
            p = self.landmarks[8]
            return (p[0], p[1])
        return self.wrist


@dataclass
class FrameResult:
    hands: List[HandObservation] = field(default_factory=list)
    timestamp_ms: int = 0
    error: Optional[str] = None


def mediapipe_available() -> bool:
    return _HAS_MP


class GestureRecognizerWrapper:
    """LIVE_STREAM 模式；结果通过 poll_latest 读取。"""

    def __init__(
        self,
        model_path: str = MODEL_PATH,
        num_hands: int = 2,
        min_detection: float = 0.5,
        min_presence: float = 0.5,
        min_tracking: float = 0.5,
    ):
        if not _HAS_MP:
            raise RuntimeError("未安装 mediapipe，请执行: pip install mediapipe")
        ensure_model_file()
        self._lock = __import__("threading").Lock()
        self._latest: Optional[FrameResult] = None
        self._recognizer = None
        self._num_hands = num_hands
        self._closed = False
        base = mp_python.BaseOptions(model_asset_path=model_path)
        opts = vision.GestureRecognizerOptions(
            base_options=base,
            running_mode=vision.RunningMode.LIVE_STREAM,
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection,
            min_hand_presence_confidence=min_presence,
            min_tracking_confidence=min_tracking,
            result_callback=self._on_result,
        )
        self._recognizer = vision.GestureRecognizer.create_from_options(opts)

    def _on_result(self, result, output_image, timestamp_ms: int) -> None:
        hands: List[HandObservation] = []
        try:
            if result.gestures and result.hand_landmarks:
                for i, lm_list in enumerate(result.hand_landmarks):
                    g_name = "None"
                    g_score = 0.0
                    if i < len(result.gestures) and result.gestures[i]:
                        top = result.gestures[i][0]
                        g_name = top.category_name or "None"
                        g_score = float(top.score or 0.0)
                    handed = "Unknown"
                    if result.handedness and i < len(result.handedness) and result.handedness[i]:
                        handed = result.handedness[i][0].category_name or "Unknown"
                    pts = [(float(p.x), float(p.y), float(p.z)) for p in lm_list]
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs and ys else 0.0
                    wrist = pts[0] if pts else (0.5, 0.5, 0.0)
                    hands.append(
                        HandObservation(
                            index=i,
                            handedness=handed,
                            landmarks=pts,
                            gesture_name=g_name,
                            gesture_score=g_score,
                            wrist=(wrist[0], wrist[1]),
                            bbox_area=area,
                        )
                    )
        except Exception as e:
            fr = FrameResult(hands=[], timestamp_ms=int(timestamp_ms), error=str(e))
            with self._lock:
                self._latest = fr
            return
        fr = FrameResult(hands=hands, timestamp_ms=int(timestamp_ms))
        with self._lock:
            self._latest = fr

    def detect_async(self, bgr_frame: np.ndarray, timestamp_ms: Optional[int] = None) -> None:
        if self._closed or self._recognizer is None:
            return
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        rgb = bgr_frame[:, :, ::-1].copy()
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._recognizer.recognize_async(mp_image, ts)

    def poll_latest(self) -> FrameResult:
        with self._lock:
            if self._latest is None:
                return FrameResult()
            return self._latest

    def close(self) -> None:
        self._closed = True
        if self._recognizer is not None:
            try:
                self._recognizer.close()
            except Exception:
                pass
            self._recognizer = None
