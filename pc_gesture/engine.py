"""
pc_gesture.engine
=================

编排摄像头 + MediaPipe Tasks HandLandmarker + GestureSemantics 的后台线程。

生命周期::

    eng = GestureEngine(dispatch_fn, on_status, on_fps, on_send_text)
    err = eng.start()                  # None = 成功；str = 错误信息（缺依赖 / 无摄像头）
    ...
    eng.stop()

线程模型：
    start() 拉起一个守护线程；线程内做 ``cap.read()`` → ``landmarker.detect()`` →
    ``semantics.process()`` → ``dispatch_fn(event)`` → ``on_frame(snapshot)``。
    stop() 通过 ``_stop_event`` 让线程在下一次循环开头退出（≤2s 超时 join）。

依赖：
    pip install opencv-python mediapipe
首次运行自动从 Google Storage 下载 hand_landmarker.task（约 5MB）；
若离线请自行放置到 ``<project>/pc_gesture_models/hand_landmarker.task``。
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from .config import GestureConfig, load_gesture_config, save_gesture_config
from .semantics import GestureSemantics
from .types import FrameSnapshot, HandSnapshot


# ---------------------------------------------------------------------------
# MediaPipe Tasks 模型路径
# ---------------------------------------------------------------------------
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_DIR, "pc_gesture_models")
MODEL_PATH = os.path.join(MODEL_DIR, "hand_landmarker.task")


def _download_model(progress_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """下载 hand_landmarker.task 到本地；返回路径或 None。"""
    if os.path.isfile(MODEL_PATH):
        return MODEL_PATH
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        if progress_cb:
            progress_cb("首次启动：下载 MediaPipe Hand 模型（约 5MB）…")
        import urllib.request
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        if os.path.isfile(MODEL_PATH):
            if progress_cb:
                progress_cb("模型下载完成")
            return MODEL_PATH
        return None
    except Exception as ex:
        if progress_cb:
            progress_cb(f"模型下载失败：{ex}")
        return None


# ---------------------------------------------------------------------------
# MediaPipe / OpenCV 延迟导入（避免启动时强依赖）
# ---------------------------------------------------------------------------
def _import_runtime():
    """延迟导入 cv2 与 mediapipe；任一失败时抛 RuntimeError。"""
    try:
        import cv2  # type: ignore
    except Exception as e:
        raise RuntimeError(
            f"缺少依赖 opencv-python：{e}（请 pip install opencv-python）"
        ) from e
    try:
        from mediapipe.tasks import python  # type: ignore  # noqa: F401
        from mediapipe.tasks.python import vision  # type: ignore  # noqa: F401
        import mediapipe as mp  # type: ignore
    except Exception as e:
        raise RuntimeError(
            f"缺少依赖 mediapipe：{e}（请 pip install mediapipe）"
        ) from e
    return cv2, mp


# ---------------------------------------------------------------------------
# GestureEngine
# ---------------------------------------------------------------------------
class GestureEngine:
    def __init__(
        self,
        dispatch_fn: Callable[[Dict[str, Any], str], None],
        on_status: Callable[[str], None],
        on_fps: Callable[[float], None],
        on_send_text: Callable[[], None],
        on_frame: Optional[Callable[["FrameSnapshot"], None]] = None,
    ):
        self._dispatch = dispatch_fn
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        # Per-frame callback. When set, _loop pushes a FrameSnapshot each frame.
        self._on_frame = on_frame
        # Cached latest snapshot; main thread reads via latest_snapshot().
        self._latest_snapshot: Optional["FrameSnapshot"] = None

        self.cfg: GestureConfig = load_gesture_config()
        self._semantics = GestureSemantics(self.cfg)
        self.running: bool = False

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def save_config(self) -> None:
        save_gesture_config(self.cfg)

    def start(self) -> Optional[str]:
        """启动后台线程。返回 ``None`` 表示成功，错误信息字符串表示启动失败。"""
        with self._lock:
            if self.running:
                return None

            try:
                cv2, _ = _import_runtime()
            except RuntimeError as e:
                return str(e)

            camera_index = self.cfg.camera_index
            cap = cv2.VideoCapture(camera_index)
            if not cap.isOpened():
                cap.release()
                return f"无法打开摄像头（index={camera_index}）。请检查权限或更换摄像头。"

            model_path = _download_model(self._on_status)
            if not model_path:
                cap.release()
                return "MediaPipe Hand 模型下载失败，请检查网络或手动放置 hand_landmarker.task"

            # 同步 cfg.raw["enabled"]
            self.cfg.raw["enabled"] = not bool(self.cfg.preview_only)

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                args=(cap, model_path),
                daemon=True,
                name="gesture-engine",
            )
            self.running = True
            self._thread.start()
            self._on_status("手势识别运行中")
            return None

    def stop(self) -> None:
        with self._lock:
            if not self.running and self._thread is None:
                return
            self._stop_event.set()
            th = self._thread
            self._thread = None
        if th is not None and th.is_alive():
            th.join(timeout=2.5)
        self.running = False
        try:
            self._on_fps(0.0)
        except Exception:
            pass

    def start_pairing(self) -> None:
        self._semantics.start_pairing()
        try:
            self._on_status("双人配对：请屏幕左侧协作者竖食指 1 秒")
        except Exception:
            pass

    def reset_pairing(self) -> None:
        self._semantics.reset_pairing()
        try:
            self._on_status("已重置配对")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 后台线程主循环
    # ------------------------------------------------------------------
    def _loop(self, cap, model_path: str) -> None:
        cv2, mp = _import_runtime()
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        landmarker = None
        consecutive_read_failures = 0

        try:
            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                running_mode=vision.RunningMode.IMAGE,
            )
            landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as e:
            self._safe_status(f"初始化 HandLandmarker 失败：{e}")
            self.running = False
            cap.release()
            return

        # FPS 统计
        fps_frame_counter = 0
        fps_last_t = time.monotonic()

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_read_failures += 1
                    if consecutive_read_failures >= 30:
                        self._safe_status("摄像头连续读取失败，已停止")
                        break
                    time.sleep(0.02)
                    continue
                consecutive_read_failures = 0

                # 镜像
                if self.cfg.mirror:
                    frame = cv2.flip(frame, 1)

                # MediaPipe 推理
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect(mp_image)
                    hand_landmarks = result.hand_landmarks or []
                    handedness = result.handedness or []
                except Exception as e:
                    if os.environ.get("GESTURE_DEBUG"):
                        print(f"[gesture] detect 异常：{e}")
                    hand_landmarks = []
                    handedness = []

                # 配对是否确认、是否过期
                ps = self._semantics.pairing_state

                # 分类 + 派发
                if not self.cfg.preview_only:
                    try:
                        events = self._semantics.process(
                            hand_landmarks, handedness, on_send_text=self._on_send_text
                        )
                    except Exception as e:
                        if os.environ.get("GESTURE_DEBUG"):
                            traceback.print_exc()
                        events = []
                    for ev in events:
                        self._safe_dispatch(ev)
                else:
                    # 预览模式仍要更新配对倒计时
                    self._semantics.process(hand_landmarks, handedness, on_send_text=None)

                # 组装 FrameSnapshot 并推给 on_frame（如有订阅者）
                snap = self._build_frame_snapshot(frame, hand_landmarks, handedness)
                self._latest_snapshot = snap
                if self._on_frame is not None:
                    try:
                        self._on_frame(snap)
                    except Exception:
                        if os.environ.get("GESTURE_DEBUG"):
                            traceback.print_exc()

                # FPS
                fps_frame_counter += 1
                now = time.monotonic()
                if now - fps_last_t >= 1.0:
                    fps = fps_frame_counter / (now - fps_last_t)
                    fps_frame_counter = 0
                    fps_last_t = now
                    try:
                        self._on_fps(fps)
                    except Exception:
                        pass
        except Exception as e:
            if os.environ.get("GESTURE_DEBUG"):
                traceback.print_exc()
            self._safe_status(f"手势识别异常：{e}")
        finally:
            try:
                cap.release()
            except Exception:
                pass
            self.running = False
            try:
                self._on_fps(0.0)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 每帧 FrameSnapshot 组装
    # ------------------------------------------------------------------
    def _build_frame_snapshot(self, frame, hand_landmarks, handedness) -> FrameSnapshot:
        """Assemble a FrameSnapshot from one frame's worth of MediaPipe results.

        The snapshot is immutable; the engine creates a new one per frame.
        finger_states are derived from the same heuristics used by
        ``self._semantics._classify_static`` so diagnostics stay in sync with
        what the recognizer actually sees.
        """
        from .types import FrameSnapshot, HandSnapshot

        h, w = frame.shape[:2]
        # frame_rgb = RGB888 bytes (Qt QImage 用 RGB888, 不是 BGR)
        rgb = frame[:, :, ::-1].reshape(-1).tobytes() if frame is not None else None

        # 配对与槽位映射(沿用 semantics 的规则)
        is_single = self.cfg.operator_mode == "single"
        swapped = self.cfg.dual_roles_swapped

        hands: List[HandSnapshot] = []
        for idx, lm_list in enumerate(hand_landmarks or []):
            if not lm_list or len(lm_list) < 21:
                continue
            # 槽位
            small_is_left = lm_list[0].x < 0.5
            if swapped:
                slot = "A" if not small_is_left else "B"
            else:
                slot = "A" if small_is_left else "B"
            # 单人模式只看 A
            if is_single and slot != "A":
                continue
            # 手指状态(来自 semantics._classify_static 的同套判定)
            index_ext = lm_list[8].y < lm_list[6].y - 0.025
            middle_ext = lm_list[12].y < lm_list[10].y - 0.025
            ring_ext = lm_list[16].y < lm_list[14].y - 0.025
            pinky_ext = lm_list[20].y < lm_list[18].y - 0.025
            thumb_tip_y = lm_list[4].y
            wrist_y = lm_list[0].y
            thumb_up = thumb_tip_y < wrist_y - 0.08
            thumb_down = thumb_tip_y > wrist_y + 0.10
            # 用 semantics 内部方法拿到精确的 static_gesture 标签
            static = self._semantics._classify_static(lm_list)
            # confidence 来自 MediaPipe handedness
            try:
                conf = float(handedness[idx][0].score) if handedness and idx < len(handedness) else 0.0
            except Exception:
                conf = 0.0
            # rising-edge recognized_event: 我们没在 _classify 之外追踪,用 None 简化;
            # GesturePage 的试用面板已经有自己的 rising-edge 跟踪(poll bridge.recent_gestures())。
            hands.append(HandSnapshot(
                slot=slot,
                wrist_xy=(float(lm_list[0].x), float(lm_list[0].y)),
                finger_states={
                    "thumb": thumb_up or (not thumb_down),  # 简化: 既非明确指下视为伸直
                    "index": index_ext,
                    "middle": middle_ext,
                    "ring": ring_ext,
                    "pinky": pinky_ext,
                },
                static_gesture=static,
                confidence=conf,
                recognized_event=None,
            ))

        return FrameSnapshot(
            timestamp_ms=int(time.monotonic() * 1000),
            frame_rgb=rgb,
            frame_w=w,
            frame_h=h,
            hands=hands,
        )

    def latest_snapshot(self) -> Optional[FrameSnapshot]:
        """Most recent FrameSnapshot, or None if engine hasn't produced one yet.

        Thread-safe under GIL (single-attribute read of an immutable object).
        """
        return self._latest_snapshot

    # ------------------------------------------------------------------
    # 回调安全封装（线程切换期间 UI 已退出也不应抛）
    # ------------------------------------------------------------------
    def _safe_status(self, msg: str) -> None:
        try:
            self._on_status(msg)
        except Exception:
            pass

    def _safe_dispatch(self, event: Dict[str, Any]) -> None:
        try:
            self._dispatch(event, "gesture")
        except Exception:
            pass