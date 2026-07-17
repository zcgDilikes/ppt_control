#!/usr/bin/env python3
"""下载 MediaPipe gesture_recognizer.task 到 pc_gesture/models/"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pc_gesture.config import MODEL_PATH, ensure_model_file

if __name__ == "__main__":
    print("下载模型到:", MODEL_PATH)

    def prog(done, total):
        if total > 0:
            pct = 100.0 * done / total
            print(f"\r{pct:.1f}%", end="", flush=True)

    path = ensure_model_file(progress_cb=prog)
    print("\n完成:", path)
