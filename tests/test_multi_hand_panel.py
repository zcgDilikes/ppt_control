# tests/test_multi_hand_panel.py
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ppt_qt.widgets.multi_hand_panel import MultiHandPanel
from pc_gesture.types import HandSnapshot


def _make_hand(slot, person_id):
    return HandSnapshot(
        slot=slot,
        wrist_xy=(0.5, 0.5),
        finger_states={"thumb": True, "index": False, "middle": False, "ring": False, "pinky": False},
        static_gesture="PALM",
        confidence=0.9,
        person_id=person_id,
    )


def test_panel_shows_3_slots():
    panel = MultiHandPanel()
    # 3 个 slot 都应该存在
    assert hasattr(panel, "_slot_a")
    assert hasattr(panel, "_slot_b")
    assert hasattr(panel, "_slot_c")


def test_panel_updates_with_3_hand_snapshot():
    panel = MultiHandPanel()
    # 模拟 3-hand snapshot
    snapshot = type("Snap", (), {})()
    snapshot.hands = [
        _make_hand("A", 0),
        _make_hand("B", 1),
        _make_hand("C", 2),
    ]
    panel.update_from_snapshot(snapshot)
    # 3 个 slot 都应该显示
    assert panel._slot_a.isVisible() or panel._slot_a.isVisibleTo(panel)
    assert panel._slot_b.isVisible() or panel._slot_b.isVisibleTo(panel)
    assert panel._slot_c.isVisible() or panel._slot_c.isVisibleTo(panel)


def test_panel_color_coding():
    """slot A 蓝, slot B 橙, slot C 紫(第三手新色)。"""
    panel = MultiHandPanel()
    assert "60a5fa" in panel._slot_a.styleSheet() or "60" in panel._slot_a.styleSheet()
    assert "fb923c" in panel._slot_b.styleSheet()
    # slot C 紫
    assert "a855f7" in panel._slot_c.styleSheet() or "purple" in panel._slot_c.styleSheet().lower()