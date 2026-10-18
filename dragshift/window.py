"""Frameless liquid-glass window + an image view used by all editors."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizeGrip,
                               QVBoxLayout, QWidget)

from . import glass

IS_WIN = sys.platform == "win32"


class CloseButton(QAbstractButton):
    """The red macOS close button; shows its × on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("Close (Esc)")

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, 12, 12)
        p.setPen(QPen(QColor(224, 68, 62), 0.6))
        p.setBrush(QColor(255, 95, 87) if not self.isDown() else QColor(191, 64, 57))
        p.drawEllipse(r)
        if self.underMouse():
            p.setPen(QPen(QColor(77, 0, 0, 200), 1.2, Qt.SolidLine, Qt.RoundCap))
            c = r.center()
            d = 2.6
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))


class Switch(QAbstractButton):
    """macOS-style toggle switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._move)
        self.toggled.connect(lambda on: (self._anim.setStartValue(self._pos),
                                         self._anim.setEndValue(1.0 if on else 0.0), self._anim.start()))

    def _move(self, v):
        self._pos = float(v)
        self.update()

    def paintEvent(self, e):
        t = glass.theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(t.fill2)
        on = QColor(t.accent)
        mix = lambda a, b, k: QColor(int(a.red() + (b.red() - a.red()) * k), int(a.green() + (b.green() - a.green()) * k),
                                     int(a.blue() + (b.blue() - a.blue()) * k), int(a.alpha() + (b.alpha() - a.alpha()) * k))
        p.setPen(Qt.NoPen)
        p.setBrush(mix(track, on, self._pos))
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        x = 2 + self._pos * 16
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, 2.6, 18, 18))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, 2, 18, 18))


def form_card(rows: list) -> QFrame:
    """Apple's grouped form: rows of (title, subtitle or "", control widget or layout) in a
    rounded card, separated by hairlines."""
    card = QFrame()
    card.setObjectName("card")
    col = QVBoxLayout(card)
    col.setContentsMargins(14, 4, 14, 4)
    col.setSpacing(0)
    for i, (title, sub, control) in enumerate(rows):
        if i:
            line = QFrame()
            line.setObjectName("hairline")
            col.addWidget(line)
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(QLabel(title))
        if sub:
            d = QLabel(sub)
            d.setObjectName("dim")
            d.setWordWrap(True)
            text.addWidget(d)
        row.addLayout(text, 1)
        if isinstance(control, QWidget):
            row.addWidget(control, 0, Qt.AlignVCenter)
        elif control is not None:
            row.addLayout(control)
        col.addLayout(row)
    return card


class GlassWindow(QWidget):
    """Top-level glass window with its own title bar. Put content in `self.body`."""

    def __init__(self, title: str, parent=None, size=(760, 640)):
        super().__init__(parent)
        self.setWindowTitle(f"{title} · DragShift" if title else "DragShift")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("glassRoot")
        self.theme = glass.theme()
        self.setStyleSheet(glass.qss(self.theme))
        self.resize(*size)
        self._drag: QPoint | None = None
        self._acrylic = False
        self.radius = 24
        self.liquid = glass.LiquidBacking(self, self.radius)
        self.liquid.changed.connect(self.update)
        self._fade = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(0)
        close = CloseButton(self)
        close.clicked.connect(self.close)
        bar.addWidget(close)
        bar.addStretch(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        bar.addWidget(self.title_label)
        bar.addStretch(1)
        bar.addSpacing(close.width())
        outer.addLayout(bar)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip = QSizeGrip(self)
        grip.setFixedSize(12, 12)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        grip_row.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(grip_row)

    # ---- window behaviour
    def present(self):
        """Centre on the cursor's screen, capture what's behind, then show."""
        from PySide6.QtGui import QCursor, QGuiApplication
        scr = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(min(self.width(), scr.width() - 40), min(self.height(), scr.height() - 40))
        self.move(scr.center() - self.rect().center())
        self._placed = True
        self.liquid.capture_at(self.frameGeometry())
        self.show()
        if sys.platform == "darwin":
            from . import platform_mac
            platform_mac.activate()   # menu-bar apps aren't brought forward automatically
        self.raise_()
        self.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_placed", False):
            scr = self.screen().availableGeometry()
            self.move(scr.center() - self.rect().center())
            self._placed = True
            self.liquid.capture_at(self.frameGeometry())
        self.liquid.excluded = glass.exclude_from_capture(int(self.winId()))

    def moveEvent(self, e):
        super().moveEvent(e)
        self._stale()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._stale()

    def _stale(self):
        if not self.isVisible():
            return
        if self.liquid.excluded:
            self.liquid.moved()
        elif self.liquid.image is not None:
            # can't re-capture behind ourselves: switch to the system blur instead
            self.liquid.image = None
            if IS_WIN and not self._acrylic:
                self._acrylic = glass.enable_acrylic(int(self.winId()))
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 44:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                return  # native move: snapping etc.
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = glass.rounded_rect_path(r, self.radius)
        t = self.theme
        img = self.liquid.image
        if img is not None and not img.isNull() and img.size() == self.size():
            p.drawImage(0, 0, img)
            glass.paint_glass(p, path, t.panel)   # windows are for reading: denser than a menu
        else:
            tint = QColor(t.panel) if self._acrylic else t.solid
            glass.paint_glass(p, path, tint)


class ImageView(QWidget):
    """Shows an image scaled to fit, with helpers to map between widget and image coords.
    Subclasses override `paint_overlay` and the mouse hooks."""

    changed = Signal()

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.set_image(image)

    def set_image(self, image: QImage):
        self.image = image
        self.pix = QPixmap.fromImage(image)
        self.update()

    # geometry
    def target_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        avail = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        s = min(avail.width() / self.image.width(), avail.height() / self.image.height())
        w, h = self.image.width() * s, self.image.height() * s
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def scale(self) -> float:
        t = self.target_rect()
        return t.width() / max(1, self.image.width())

    def to_image(self, pt: QPointF) -> QPointF:
        t = self.target_rect()
        s = self.scale() or 1
        return QPointF((pt.x() - t.left()) / s, (pt.y() - t.top()) / s)

    def to_widget(self, pt: QPointF) -> QPointF:
        t = self.target_rect()
        s = self.scale()
        return QPointF(t.left() + pt.x() * s, t.top() + pt.y() * s)

    def rect_to_widget(self, r: QRectF) -> QRectF:
        a = self.to_widget(r.topLeft())
        b = self.to_widget(r.bottomRight())
        return QRectF(a, b)

    def clamp_image(self, pt: QPointF) -> QPointF:
        return QPointF(min(max(pt.x(), 0), self.image.width()), min(max(pt.y(), 0), self.image.height()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.target_rect()
        clip = QPainterPath()
        clip.addRoundedRect(t, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(t, QColor(128, 128, 128, 40))   # so transparent areas are visible
        p.drawPixmap(t, self.pix, QRectF(self.pix.rect()))
        p.restore()
        self.paint_overlay(p, t)

    def paint_overlay(self, p: QPainter, t: QRectF):
        pass
