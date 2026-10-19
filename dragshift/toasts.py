"""Notifications in the style of macOS banners: top-right on macOS (bottom-right on Windows),
stacked. Icon or thumbnail, a bold title, one line, and "now"; while the pointer is over a
result, Open and Undo appear (Undo moves the new files to the Trash/Recycle Bin), and a click
anywhere else shows the file in Finder/Explorer.

A card appears immediately while work runs (spinner), then turns into the result."""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QFile, QPointF, QRect, QRectF, Qt, QTimer, QUrl,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QFont, QFontMetrics,
                           QGuiApplication, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from . import glass
from .report import Result

W = 344
H_SHORT, H_TALL = 64, 80   # one line / an error that needs two
GAP = 8
MARGIN = 12
RADIUS = 20
PAD = 13
LEAD = 38                 # thumbnail / app icon size
TX = PAD + LEAD + 11      # text column
TOP_RIGHT = sys.platform == "darwin"   # where macOS shows notifications
_APP_ICON: QPixmap | None = None


def app_icon() -> QPixmap:
    global _APP_ICON
    if _APP_ICON is None:
        pm = QPixmap(str(Path(__file__).with_name("assets") / "dragshift.png"))
        if not pm.isNull():
            pm = pm.scaled(2 * LEAD, 2 * LEAD, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2.0)
        _APP_ICON = pm
    return _APP_ICON


def reveal(path: str | Path):
    path = str(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


def open_file(path: str | Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def trash(paths: list[Path]) -> int:
    n = 0
    for p in paths:
        p = Path(p)
        if p.is_file():
            if QFile.moveToTrash(str(p)):
                n += 1
            else:
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
    # remove now-empty output folders we created (e.g. "x images/")
    for d in {Path(p).parent for p in paths}:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    return n


class ToastCard(QWidget):
    closed = Signal(object)

    def __init__(self, stack: "ToastStack"):
        super().__init__(None)
        self.stack = stack
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint |
                            Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.h = H_SHORT
        self.resize(W, self.h)
        self.state = "working"     # working | done | error | info
        self.title = ""
        self.detail = ""
        self.good = ""
        self.result: Result | None = None
        self.thumb: QPixmap | None = None
        self.spin = 0.0
        self.hover_btn = -1
        self.buttons: list[tuple[str, QRectF]] = []
        self._fade = 0.0
        from .liquid import GlassStyle
        self.liquid = glass.LiquidBacking(self, RADIUS, GlassStyle(blur=8, strength=12, bezel=16))
        self.theme = glass.theme()
        self.hovered = False
        self.liquid.changed.connect(self.update)
        self.fade = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=200,
                                      easingCurve=QEasingCurve.OutCubic)
        self.fade.valueChanged.connect(self._set_fade)
        self.spinner = QTimer(self, interval=16, timeout=self._spin)
        self.life = QTimer(self, singleShot=True, timeout=self.dismiss)

    # ------------------------------------------------------------ state
    def _fit(self):
        """Taller only for an error that needs two lines; the stack re-flows when this changes."""
        h = H_TALL if self.state == "error" and self.detail else H_SHORT
        if h != self.h:
            self.h = h
            if self.isVisible():
                self.stack.reflow()
        self.update()

    def working(self, title: str, detail: str = ""):
        self.state, self.title, self.detail = "working", title, detail
        self.spinner.start()
        self._fit()

    def done(self, r: Result):
        self.spinner.stop()
        self.state, self.result = "done", r
        outs = r.outs or []
        self.title, self.good = r.title, r.good
        if any(ch.isdigit() for ch in r.good):     # a figure, like "75% smaller"
            self.detail = r.good[0].upper() + r.good[1:]
        else:
            self.detail = Path(outs[0]).name if len(outs) == 1 else f"{len(outs)} files" if outs else ""
        self.thumb = None
        if r.thumb is not None:
            pm = QPixmap(str(r.thumb))
            if not pm.isNull():
                self.thumb = pm.scaled(2 * LEAD, 2 * LEAD, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.life.start(6500)
        self._fit()

    def error(self, title: str, detail: str):
        self.spinner.stop()
        self.state, self.title, self.detail = "error", title, detail
        self.life.start(9000)
        self._fit()

    def info(self, title: str, detail: str, ms: int = 4500):
        self.spinner.stop()
        self.state, self.title, self.detail = "info", title, detail
        self.thumb = None
        self.life.start(ms)
        self._fit()

    def _spin(self):
        self.spin = (self.spin + 6) % 360
        self.update()

    def _set_fade(self, v):
        self._fade = float(v)
        self.setWindowOpacity(self._fade)
        self.update()

    def appear(self, rect: QRect):
        self.setGeometry(rect)
        self.liquid.capture_at(rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.liquid.excluded = glass.exclude_from_capture(int(self.winId()))
        self.fade.start()

    def relocate(self, rect: QRect):
        if rect == self.geometry():
            return
        self.setGeometry(rect)
        if self.liquid.excluded:
            self.liquid.refresh()
        else:
            self.liquid.image = None
            self.update()

    def dismiss(self):
        self.spinner.stop()
        self.life.stop()
        self.hide()
        self.closed.emit(self)
        self.deleteLater()

    # ------------------------------------------------------------ input
    def enterEvent(self, e):
        self.life.stop()
        self.hovered = True
        self.update()

    def leaveEvent(self, e):
        self.hover_btn = -1
        self.hovered = False
        if self.state in ("done", "info"):
            self.life.start(2500)
        elif self.state == "error":
            self.life.start(4000)
        self.update()

    def mouseMoveEvent(self, e):
        hb = -1
        for i, (_, r) in enumerate(self.buttons):
            if r.contains(e.position()):
                hb = i
        if hb != self.hover_btn:
            self.hover_btn = hb
            self.setCursor(Qt.PointingHandCursor if hb >= 0 else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._close_rect().contains(e.position()):
            self.dismiss()
            return
        for name, r in self.buttons:
            if r.contains(e.position()):
                self._act(name)
                return
        if self.state == "done" and self.result and self.result.outs:
            reveal(self.result.outs[0])
            self.dismiss()

    def _act(self, name: str):
        r = self.result
        if not r:
            return
        if name == "Open":
            open_file(r.outs[0])
            self.dismiss()
        elif name == "Undo":
            trash(r.outs)
            self.result = None
            self.good = ""
            bin_name = "Trash" if sys.platform == "darwin" else "Recycle Bin"
            self.info(f"Moved to {bin_name}", "", 2500)

    # ------------------------------------------------------------ paint
    def _close_rect(self) -> QRectF:
        return QRectF(4, 4, 18, 18) if self.hovered else QRectF()

    def _spinner(self, p: QPainter, c: QPointF, col: QColor):
        """Apple's activity indicator: eight spokes, fading behind the leading one."""
        step = int(self.spin / 45) % 8
        p.save()
        for i in range(8):
            a = math.radians(90 - i * 45)
            fade = ((i - step) % 8) / 8
            q = QColor(col)
            q.setAlphaF(col.alphaF() * (1 - 0.8 * fade))
            p.setPen(QPen(q, 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + 3.8 * math.cos(a), c.y() - 3.8 * math.sin(a)),
                       QPointF(c.x() + 7.5 * math.cos(a), c.y() - 7.5 * math.sin(a)))
        p.restore()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = self.theme
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = glass.rounded_rect_path(r, RADIUS)
        img = self.liquid.image
        if img is not None and not img.isNull() and img.size() == self.size():
            p.drawImage(0, 0, img)
            glass.paint_glass(p, path, t.glass)
        else:
            glass.paint_glass(p, path, t.solid)

        # leading picture: the result's thumbnail, else the app icon
        lead = QRectF(PAD, (self.h - LEAD) / 2 if self.h == H_SHORT else PAD, LEAD, LEAD)
        if self.thumb is not None:
            clip = QPainterPath()
            clip.addRoundedRect(lead, 8, 8)
            p.save()
            p.setClipPath(clip)
            sw, sh = self.thumb.width(), self.thumb.height()
            side = min(sw, sh)
            p.drawPixmap(lead, self.thumb, QRectF((sw - side) / 2, (sh - side) / 2, side, side))
            p.restore()
            p.setPen(QPen(t.separator, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(lead, 8, 8)
        else:
            icon = app_icon()
            if not icon.isNull():
                p.drawPixmap(lead, icon, QRectF(icon.rect()))

        # right side: "now", a spinner while working, or Open / Undo while hovered
        self.buttons = []
        right = W - PAD
        actions = self.hovered and self.state == "done" and bool(self.result and self.result.outs)
        if actions:
            bf = glass.font(12, QFont.Medium)
            bfm = QFontMetrics(bf)
            p.setFont(bf)
            x = right
            for i, name in reversed(list(enumerate(("Open", "Undo")))):
                bw = bfm.horizontalAdvance(name) + 20
                br = QRectF(x - bw, (self.h - 24) / 2, bw, 24)
                self.buttons.insert(0, (name, br))
                p.setPen(Qt.NoPen)
                p.setBrush(t.fill2 if self.hover_btn == i else t.fill)
                p.drawRoundedRect(br, 12, 12)
                p.setPen(t.label)
                p.drawText(br, Qt.AlignCenter, name)
                x -= bw + 6
            right = x - 4
        elif self.state == "working":
            self._spinner(p, QPointF(right - 8, self.h / 2), t.label2)
            right -= 24
        else:
            nf = glass.font(11)
            p.setFont(nf)
            p.setPen(t.label2)
            nw = QFontMetrics(nf).horizontalAdvance("now")
            p.drawText(QRectF(right - nw, PAD - 1, nw, 18), Qt.AlignRight | Qt.AlignVCenter, "now")
            right -= nw + 8

        # title and one line
        tw = right - TX
        tf = glass.font(13, QFont.DemiBold)
        df = glass.font(13)
        lines = 2 if self.state == "error" and self.h == H_TALL else 1
        block = 17 + (17 * lines if self.detail else 0)
        ty = (self.h - block) / 2
        p.setFont(tf)
        p.setPen(t.label)
        p.drawText(QRectF(TX, ty, tw, 17), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(tf).elidedText(self.title, Qt.ElideRight, int(tw)))
        if self.detail:
            p.setFont(df)
            p.setPen(t.label2)
            dw = (W - PAD - TX) if lines == 2 else tw
            if lines == 2:
                p.drawText(QRectF(TX, ty + 17, dw, 34), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                           self.detail)
            else:
                p.drawText(QRectF(TX, ty + 17, dw, 17), Qt.AlignLeft | Qt.AlignVCenter,
                           QFontMetrics(df).elidedText(self.detail, Qt.ElideMiddle, int(dw)))

        # close button on hover, top-left like macOS
        if self.hovered:
            cr = self._close_rect()
            p.setPen(QPen(t.separator, 1))
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(cr)
            glass.draw_symbol(p, "xmark", cr.center(), 8, t.label2, "✕", "bold")


class ToastStack:
    """Owns the cards and keeps them stacked in the corner of the active screen."""

    def __init__(self):
        self.cards: list[ToastCard] = []

    def _screen_rect(self) -> QRect:
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _rects(self) -> list[QRect]:
        """Each card's place, newest last, stacked away from the corner by their heights."""
        g = self._screen_rect()
        x = g.right() - W - MARGIN
        rects, off = [], MARGIN
        for c in self.cards:
            y = g.top() + off if TOP_RIGHT else g.bottom() - off - c.h
            rects.append(QRect(x, y, W, c.h))
            off += c.h + GAP
        return rects

    def reflow(self):
        for c, r in zip(self.cards, self._rects()):
            c.relocate(r)

    def new(self) -> ToastCard:
        c = ToastCard(self)
        c.closed.connect(self._closed)
        while len(self.cards) >= 4:
            self.cards[0].dismiss()
        self.cards.append(c)
        c.appear(self._rects()[-1])
        return c

    def _closed(self, card):
        if card in self.cards:
            self.cards.remove(card)
        self.reflow()

    # conveniences
    def info(self, title: str, detail: str, ms: int = 4500) -> ToastCard:
        c = self.new()
        c.info(title, detail, ms)
        return c

    def error(self, title: str, detail: str) -> ToastCard:
        c = self.new()
        c.error(title, detail)
        return c
