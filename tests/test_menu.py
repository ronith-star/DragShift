"""The radial menu's ring switching."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from dragshift.radial import SIZE, Item, RadialMenu  # noqa: E402


def test_crossing_the_hub_keeps_the_ring_and_pausing_switches_it():
    m = RadialMenu(lambda p: {"Convert": [Item("PNG"), Item("JPG")], "Tools": [Item("Crop", symbol="crop")]})
    m._load(["/tmp/x.jpg"])
    c = SIZE / 2
    m._set_hover(m.hit(QPointF(c + 90, c)), QPointF(c + 90, c))   # a segment: arms the hub
    for k in range(40):                                            # glide across the hub
        x = c + 40 - k * 2
        m._set_hover(m.hit(QPointF(x, c)), QPointF(x, c))
        QTest.qWait(20)
    assert m.ring_names[m.ring_idx] == "Convert"
    QTest.qWait(600)                                               # rest on it
    assert m.ring_names[m.ring_idx] == "Tools"
