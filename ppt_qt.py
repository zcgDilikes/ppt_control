"""Entry point for the PySide6 PPT client.

Surfaces a friendly dialog if a required dependency is missing instead of
crashing with a ``ModuleNotFoundError`` that the user cannot act on.
"""

from __future__ import annotations

import sys

_REQUIRED_MODULES = (
    ("PySide6", "PySide6"),
    ("qrcode", "qrcode[pil]"),
    ("pynput", "pynput"),
    ("pyautogui", "pyautogui"),
    ("cv2", "opencv-python"),
    ("mediapipe", "mediapipe"),
)


def _check_dependencies() -> str | None:
    """Return the pip-install hint for the first missing module, else None."""
    import importlib

    for module_name, pip_name in _REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception:
            return pip_name
    return None


def main() -> int:
    missing = _check_dependencies()
    if missing is not None:
        # Defer PySide6 import so we can show a Qt dialog if it's the
        # missing dependency itself.
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
        except Exception:
            print(
                "缺少依赖：请运行：pip install PySide6 mediapipe opencv-python "
                "qrcode[pil] pynput pyautogui",
                file=sys.stderr,
            )
            return 1
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "缺少依赖",
            f"请运行：pip install PySide6 mediapipe opencv-python qrcode[pil] pynput pyautogui",
        )
        return 1
    from ppt_qt.app import PptQtApp
    return PptQtApp().run()


if __name__ == "__main__":
    sys.exit(main())