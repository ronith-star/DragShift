"""Glass notifications in the style of Apple's banners: top-right on macOS (bottom-right on
Windows), stacked.

A card appears immediately while work runs (spinner), then turns into the result:
thumbnail, what changed (e.g. "2.4 MB → 610 KB · 75% smaller") and actions:
Open · Show in Finder/folder · Undo (moves the new files to the Trash/Recycle Bin)."""
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

W, H = 360, 100
GAP = 8
MARGIN = 12
RADIUS = 22
PAD = 14
LEAD = 40                 # thumbnail / icon size
TX = PAD + LEAD + 12      # text column
TOP_RIGHT = sys.platform == "darwin"   # where macOS shows notifications


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
        self.resize(W, H)
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
    def working(self, title: str, detail: str = ""):
        self.state, self.title, self.detail = "working", title, detail
        self.spinner.start()
        self.update()

    def done(self, r: Result):
        self.spinner.stop()
        self.state, self.result = "done", r
        self.title, self.detail, self.good = r.title, r.detail, r.good
        self.thumb = None
        if r.thumb is not None:
            pm = QPixmap(str(r.thumb))
            if not pm.isNull():
                self.thumb = pm.scaled(2 * LEAD, 2 * LEAD, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.life.start(6500)
        self.update()

    def error(self, title: str, detail: str):
        self.spinner.stop()
        self.state, self.title, self.detail = "error", title, detail
        self.life.start(9000)
        self.update()

    def info(self, title: str, detail: str, ms: int = 4500):
        self.spinner.stop()
        self.state, self.title, self.detail = "info", title, detail
        self.life.start(ms)
        self.update()

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
        elif name == "Show":
            reveal(r.outs[0])
            self.dismiss()
        elif name == "Undo":
            n = trash(r.outs)
            self.result = None
            self.thumb = None
            self.good = ""
            bin_name = "Trash" if sys.platform == "darwin" else "Recycle Bin"
            self.info("Undone", f"Moved {n} file{'s' if n != 1 else ''} to the {bin_name}", 2500)

    # ------------------------------------------------------------ paint
    def _close_rect(self) -> QRectF:
        return QRectF(W - 30, 8, 22, 22)

    def _spinner(self, p: QPainter, c: QPointF, col: QColor):
        """Apple's activity indicator: eight spokes, fading behind the leading one."""
        step = int(self.spin / 45) % 8
        p.save()
        for i in range(8):
            a = math.radians(90 - i * 45)
            fade = ((i - step) % 8) / 8
            q = QColor(col)
            q.setAlphaF(col.alphaF() * (1 - 0.8 * fade))
            p.setPen(QPen(q, 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + 5.5 * math.cos(a), c.y() - 5.5 * math.sin(a)),
                       QPointF(c.x() + 10.5 * math.cos(a), c.y() - 10.5 * math.sin(a)))
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

        has_buttons = self.state == "done" and bool(self.result and self.result.outs)
        top = PAD if has_buttons else (H - LEAD) / 2
        lead = QRectF(PAD, top, LEAD, LEAD)

        # leading visual: spinner / thumbnail / symbol
        if self.state == "working":
            self._spinner(p, lead.center(), t.label2)
        elif self.thumb is not None:
            clip = QPainterPath()
            clip.addRoundedRect(lead, 9, 9)
            p.save()
            p.setClipPath(clip)
            sw, sh = self.thumb.width(), self.thumb.height()
            side = min(sw, sh)
            p.drawPixmap(lead, self.thumb, QRectF((sw - side) / 2, (sh - side) / 2, side, side))
            p.restore()
            p.setPen(QPen(t.separator, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(lead, 9, 9)
        else:
            name, col, glyph = {
                "done": ("checkmark.circle.fill", t.green, "✓"),
                "error": ("exclamationmark.triangle.fill", t.orange, "!"),
            }.get(self.state, ("info.circle.fill", t.accent, "i"))
            if self.title == "Undone":
                name, glyph = "arrow.uturn.backward.circle.fill", "↺"
            glass.draw_symbol(p, name, lead.center(), 30, col, glyph)

        tw = W - TX - 34
        tf = glass.font(13, QFont.DemiBold)
        fm = QFontMetrics(tf)
        p.setFont(tf)
        title = fm.elidedText(self.title, Qt.ElideRight, int(tw))
        ty = top - 1 if has_buttons else top + 1
        p.setPen(t.label)
        p.drawText(QRectF(TX, ty, tw, 18), Qt.AlignLeft | Qt.AlignVCenter, title)
        # highlighted figure (e.g. "75% smaller")
        if self.good:
            gf = glass.font(11, QFont.DemiBold)
            gw = QFontMetrics(gf).horizontalAdvance(self.good) + 12
            gx = TX + fm.horizontalAdvance(title) + 7
            if gx + gw < W - 34:
                chip = QRectF(gx, ty + 1, gw, 16)
                bg = QColor(t.green)
                bg.setAlpha(46)
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(chip, 8, 8)
                p.setFont(gf)
                p.setPen(t.green)
                p.drawText(chip, Qt.AlignCenter, self.good)
        df = glass.font(12)
        p.setFont(df)
        p.setPen(t.label2)
        p.drawText(QRectF(TX, ty + 19, tw + 18, 34), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   QFontMetrics(df).elidedText(self.detail, Qt.ElideMiddle, int(tw * 1.9)))

        # close button, shown while the pointer is over the card
        if self.hovered:
            cr = self._close_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(t.fill2)
            p.drawEllipse(cr)
            glass.draw_symbol(p, "xmark", cr.center(), 9, t.label2, "✕", "bold")

        # action buttons
        self.buttons = []
        if has_buttons:
            labels = {"Open": "Open", "Show": "Show in Finder" if sys.platform == "darwin" else "Show in folder",
                      "Undo": "Undo"}
            bf = glass.font(12, QFont.Medium)
            p.setFont(bf)
            bfm = QFontMetrics(bf)
            bx = TX
            for i, nme in enumerate(("Open", "Show", "Undo")):
                bw = bfm.horizontalAdvance(labels[nme]) + 22
                br = QRectF(bx, H - PAD - 24, bw, 24)
                self.buttons.append((nme, br))
                p.setPen(Qt.NoPen)
                p.setBrush(t.fill2 if self.hover_btn == i else t.fill)
                p.drawRoundedRect(br, 12, 12)
                p.setPen(t.label)
                p.drawText(br, Qt.AlignCenter, labels[nme])
                bx += bw + 6


class ToastStack:
    """Owns the cards and keeps them stacked in the corner of the active screen."""

    def __init__(self):
        self.cards: list[ToastCard] = []

    def _screen_rect(self) -> QRect:
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _slot(self, i: int) -> QRect:
        g = self._screen_rect()
        x = g.right() - W - MARGIN
        if TOP_RIGHT:
            y = g.top() + MARGIN + i * (H + GAP)
        else:
            y = g.bottom() - MARGIN - H - i * (H + GAP)
        return QRect(x, y, W, H)

    def new(self) -> ToastCard:
        c = ToastCard(self)
        c.closed.connect(self._closed)
        while len(self.cards) >= 4:
            self.cards[0].dismiss()
        self.cards.append(c)
        c.appear(self._slot(len(self.cards) - 1))
        return c

    def _closed(self, card):
        if card in self.cards:
            self.cards.remove(card)
        for i, c in enumerate(self.cards):
            c.relocate(self._slot(i))

    # conveniences
    def info(self, title: str, detail: str, ms: int = 4500) -> ToastCard:
        c = self.new()
        c.info(title, detail, ms)
        return c

    def error(self, title: str, detail: str) -> ToastCard:
        c = self.new()
        c.error(title, detail)
        return c
