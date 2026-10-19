"""The radial drop menu that pops up under the cursor while you Shift+drag a file: a small
frosted glass disc of rounded segments around a hub; the hub's capsule names the action you're on.

Rendering: the moment the menu opens we snapshot the screen behind it; a worker thread then
refracts that snapshot through the disc (see liquid.py). Until that's ready (~60 ms) a cheap
frosted version is drawn, so the menu still appears instantly."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QRectF, QRunnable, Qt,
                            QThreadPool, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage,
                           QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from . import glass


@dataclass
class Item:
    label: str
    glyph: str = ""          # text fallback for the symbol (no SF Symbols outside macOS)
    run: Callable[[list[str]], None] | None = None
    key: str = ""
    symbol: str = ""         # SF Symbol name; formats have none, tools do


SIZE = 340          # window size (room for the shadow)
R_DISC = 128        # the glass disc
R_OUT = 117         # segments' outer edge
R_IN = 56           # segments' inner edge
R_HUB = 46          # hub ring
GAP = 7             # even gap between segments, px
CORNER = 11         # segment corner radius
CAP_H = 30          # centre capsule height


def span(n: int, i: int) -> tuple[float, float]:
    """Angles (degrees, 0 = 3 o'clock, CCW) of segment i of n: the first at 12 o'clock,
    then clockwise."""
    mid = 90 - i * 360.0 / n
    return mid - 180.0 / n, mid + 180.0 / n


def circle_path(c: QPointF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(c, r, r)
    return path


def _wedge(c: QPointF, r0: float, r1: float, a0: float, a1: float, gap: float) -> QPainterPath:
    """Sharp annular wedge a0..a1 whose straight sides are set back by gap/2, so neighbouring
    wedges are separated by a gap of even width."""
    do = math.degrees(math.asin(min(1.0, gap / 2 / r1)))
    di = math.degrees(math.asin(min(1.0, gap / 2 / r0)))
    outer = QRectF(c.x() - r1, c.y() - r1, 2 * r1, 2 * r1)
    inner = QRectF(c.x() - r0, c.y() - r0, 2 * r0, 2 * r0)
    path = QPainterPath()
    path.arcMoveTo(outer, a0 + do)
    path.arcTo(outer, a0 + do, (a1 - do) - (a0 + do))
    path.arcTo(inner, a1 - di, -((a1 - di) - (a0 + di)))
    path.closeSubpath()
    return path


def segment_path(c: QPointF, n: int, i: int) -> QPainterPath:
    """Segment i of n with rounded corners: the wedge shrunk by CORNER, then grown back with
    round joins."""
    a0, a1 = span(n, i)
    core = _wedge(c, R_IN + CORNER, R_OUT - CORNER, a0, a1, GAP + 2 * CORNER)
    st = QPainterPathStroker()
    st.setWidth(2 * CORNER)
    st.setJoinStyle(Qt.RoundJoin)
    st.setCapStyle(Qt.RoundCap)
    return core.united(st.createStroke(core)).simplified()


# ---------------------------------------------------------------- background render
class _RenderSig(QObject):
    done = Signal(int, QImage)   # serial, image


class _RenderJob(QRunnable):
    def __init__(self, serial: int, backdrop):
        super().__init__()
        self.serial, self.backdrop = serial, backdrop
        self.sig = _RenderSig()

    def run(self):
        try:
            from . import liquid
            c = SIZE / 2
            sdf = liquid.sdf_circle(SIZE, SIZE, c, c, R_DISC)
            img, _ = liquid.render(self.backdrop, sdf, liquid.GlassStyle(bezel=16, strength=11, blur=12),
                                   tint=(255, 255, 255, 0.16))
            sh = liquid.shadow(sdf, spread=20, opacity=0.22, offset=(0, 6))
            sh.alpha_composite(img)
            try:
                self.sig.done.emit(self.serial, glass.qimage_from_pil(sh))
            except RuntimeError:
                pass
        except Exception:  # pragma: no cover - fall back to the painted glass
            import traceback
            traceback.print_exc()


class RadialMenu(QWidget):
    activated = Signal(object, list)     # Item, paths
    dismissed = Signal()

    def __init__(self, build_rings: Callable[[list[str]], dict[str, list[Item]]]):
        super().__init__(None)
        self.build_rings = build_rings
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint |
                            Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.resize(SIZE, SIZE)

        self.paths: list[str] = []
        self.rings: dict[str, list[Item]] = {}
        self.ring_names: list[str] = []
        self.ring_idx = 0
        self.hover = -1          # segment index, -2 = hub, -1 = none
        self.cursor_pos = QPointF(SIZE / 2, SIZE / 2)
        self.backdrop: QPixmap | None = None     # blurred, for the instant fallback
        self._raw_backdrop = None                 # PIL image for the liquid renderer
        self.disc: QImage | None = None           # rendered glass disc
        self._segments: dict[int, list[QPainterPath]] = {}
        self._serial = 0
        self.got_drag = False
        self.hub_armed = False
        self.click_mode = False  # opened from tray/menu instead of a drag
        self._t = 1.0            # pop-in animation 0..1
        self._swap = 1.0         # ring-swap animation 0..1
        self.spring: list[float] = []   # per-segment hover amount 0..1 (eased every frame)
        self.hub_spring = 0.0
        self.theme = glass.theme()

        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=190,
                                      easingCurve=QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._set_t)
        self.swap_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=220,
                                           easingCurve=QEasingCurve.OutCubic)
        self.swap_anim.valueChanged.connect(self._set_swap)
        self.hub_timer = QTimer(self, singleShot=True, interval=420, timeout=self.next_ring)
        self.frame = QTimer(self, interval=16, timeout=self._tick)   # 60 fps springs

    # ------------------------------------------------------------ show / hide
    def popup(self, pos: QPoint | None = None, paths: list[str] | None = None):
        pos = pos or QCursor.pos()
        tl = pos - QPoint(SIZE // 2, SIZE // 2)
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        tl.setX(min(max(tl.x(), g.left()), g.right() - SIZE))
        tl.setY(min(max(tl.y(), g.top()), g.bottom() - SIZE))
        # snapshot what's underneath *before* we appear
        self.theme = glass.theme()
        self._serial += 1
        self.disc = None
        try:
            if sys.platform == "darwin":
                # macOS captures "below the drag window": the drag picture never gets in
                raw = glass.grab_screen(tl.x(), tl.y(), SIZE, SIZE)
                if raw is None:
                    raise RuntimeError("capture failed")
                from . import platform_mac
                print("menu: mac windows at cursor:", "; ".join(platform_mac.LAST_SWEEP), flush=True)
                if self.got_drag or paths is None:
                    # belt and braces: Finder's drag picture (icon + name label) sits on the
                    # cursor; erase that area — it ends up under the hub, blurred anyway
                    cx, cy = pos.x() - tl.x(), pos.y() - tl.y()
                    raw = glass.inpaint_rects(raw, [(cx - 70, cy - 64, cx + 70, cy + 64)])
                shot = QPixmap.fromImage(glass.qimage_from_pil(raw))
            else:
                with glass.hidden_drag_images() as hid:
                    shot = scr.grabWindow(0, tl.x() - g.left(), tl.y() - g.top(), SIZE, SIZE)
                if hid.hwnds:
                    print(f"menu: hid {len(hid.hwnds)} drag image(s) during capture: {'; '.join(hid.info)}", flush=True)
                elif hid.info:
                    print(f"menu: drag-image sweep: {'; '.join(hid.info)}", flush=True)
                raw = glass.pil_from_qimage(
                    shot.toImage().scaled(SIZE, SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                if hid.rects:
                    # belt and braces: erase where the drag picture was, in case it was captured anyway
                    k = SIZE / max(1, shot.width())
                    local = [(int((x0 - tl.x()) * k), int((y0 - tl.y()) * k), int((x1 - tl.x()) * k), int((y1 - tl.y()) * k))
                             for (x0, y0, x1, y1) in hid.rects]
                    raw = glass.inpaint_rects(raw, local)
                    shot = QPixmap.fromImage(glass.qimage_from_pil(raw))
            self._raw_backdrop = raw
            self.backdrop = glass.blur_pixmap(shot, 24)
        except Exception:
            self.backdrop = None
            self._raw_backdrop = None
        self.move(tl)
        self.hover = -1
        self.got_drag = False
        self.hub_armed = False  # drags start on the hub; don't flip until they leave it
        self.click_mode = paths is not None
        self._render()
        if paths is not None:
            self._load(paths)
        else:
            self.paths, self.rings, self.ring_names = [], {}, []
        self._t = 0.0
        self.show()
        self.raise_()
        self.anim.start()
        self.frame.start()
        if self.click_mode:
            # behave like a popup: a click anywhere outside dismisses it
            QTimer.singleShot(0, self.grabMouse)

    def close_menu(self):
        if self.isVisible():
            self.hide()
            self.frame.stop()
            self.hub_timer.stop()
            self.dismissed.emit()

    def hideEvent(self, e):
        self.frame.stop()
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        super().hideEvent(e)

    def _render(self):
        if self._raw_backdrop is None:
            return
        job = _RenderJob(self._serial, self._raw_backdrop)
        from .util import keep, release
        job.sig.done.connect(lambda *a, j=job: (release(j), self._rendered(*a)))
        QThreadPool.globalInstance().start(keep(job))

    def _rendered(self, serial: int, img: QImage):
        if serial == self._serial:
            self.disc = img
            self.update()

    def _load(self, paths: list[str]):
        self.paths = paths
        self.rings = {k: v for k, v in self.build_rings(paths).items() if v}
        self.ring_names = list(self.rings)
        self.ring_idx = 0
        self.spring = [0.0] * len(self.items)
        self.update()

    def next_ring(self):
        if len(self.ring_names) > 1:
            self.ring_idx = (self.ring_idx + 1) % len(self.ring_names)
            self.hover = -1
            self.spring = [0.0] * len(self.items)
            self._swap = 0.0
            self.swap_anim.start()
            self.update()

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _set_swap(self, v):
        self._swap = float(v)
        self.update()

    def _tick(self):
        moved = False
        for i in range(len(self.spring)):
            target = 1.0 if i == self.hover else 0.0
            v = self.spring[i]
            nv = v + (target - v) * 0.32
            if abs(nv - target) < 0.003:
                nv = target
            if nv != v:
                self.spring[i] = nv
                moved = True
        ht = 1.0 if self.hover == -2 else 0.0
        nh = self.hub_spring + (ht - self.hub_spring) * 0.3
        if abs(nh - ht) < 0.003:
            nh = ht
        if nh != self.hub_spring:
            self.hub_spring = nh
            moved = True
        if moved:
            self.update()

    # ------------------------------------------------------------ geometry
    @property
    def items(self) -> list[Item]:
        if not self.ring_names:
            return []
        return self.rings[self.ring_names[self.ring_idx]]

    def hit(self, pos: QPointF) -> int:
        c = QPointF(SIZE / 2, SIZE / 2)
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        d = math.hypot(dx, dy)
        if d <= R_HUB:
            return -2
        if d > R_DISC + 24 or not self.items:
            return -1
        ang = math.degrees(math.atan2(dy, dx)) % 360
        n = len(self.items)
        rel = (90 + 180.0 / n - ang) % 360
        return int(rel // (360.0 / n)) % n

    def _set_hover(self, h: int, pos: QPointF | None = None):
        if pos is not None:
            self.cursor_pos = QPointF(pos)
        if h != self.hover:
            self.hover = h
            if h >= 0:
                self.hub_armed = True  # visited a petal: hovering the hub may now flip rings
            if h == -2 and self.hub_armed and len(self.ring_names) > 1:
                self.hub_timer.start()
            else:
                self.hub_timer.stop()
        self.update()

    # ------------------------------------------------------------ drag & drop
    @staticmethod
    def _local_paths(md) -> list[str]:
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and u.toLocalFile()]

    def dragEnterEvent(self, e):
        paths = self._local_paths(e.mimeData())
        if not paths:
            e.ignore()
            return
        self.got_drag = True
        if paths != self.paths:
            self._load(paths)
        e.setDropAction(Qt.CopyAction)  # never let a Shift(=move) drop delete the source
        e.accept()

    def dragMoveEvent(self, e):
        self._set_hover(self.hit(e.position()), e.position())
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def dragLeaveEvent(self, e):
        self._set_hover(-1)

    def dropEvent(self, e):
        idx = self.hit(e.position())
        items = self.items
        if 0 <= idx < len(items):
            e.setDropAction(Qt.CopyAction)
            e.accept()
            item, paths = items[idx], list(self.paths)
            self.hide()
            # return to Explorer's drag loop immediately; do the work after
            QTimer.singleShot(0, lambda: self.activated.emit(item, paths))
        else:
            e.ignore()
            self.close_menu()

    # ------------------------------------------------------------ click mode
    def mouseMoveEvent(self, e):
        if self.click_mode:
            self._set_hover(self.hit(e.position()), e.position())

    def mouseReleaseEvent(self, e):
        if not self.click_mode:
            return
        if e.button() == Qt.RightButton:
            self.close_menu()
            return
        idx = self.hit(e.position())
        if idx == -2:
            self.next_ring()
        elif 0 <= idx < len(self.items):
            item, paths = self.items[idx], list(self.paths)
            self.hide()
            QTimer.singleShot(0, lambda: self.activated.emit(item, paths))
        else:
            self.close_menu()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_menu()
        elif e.key() in (Qt.Key_Tab, Qt.Key_Shift):
            self.next_ring()

    def leaveEvent(self, e):
        if self.click_mode:
            self._set_hover(-1)

    # ------------------------------------------------------------ painting
    def _paths(self, n: int) -> list[QPainterPath]:
        if n not in self._segments:
            c = QPointF(SIZE / 2, SIZE / 2)
            self._segments[n] = [segment_path(c, n, i) for i in range(n)]
        return self._segments[n]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        th = self.theme
        c = QPointF(SIZE / 2, SIZE / 2)
        t = self._t
        p.setOpacity(min(1.0, max(0.0, t * 1.5)))
        p.translate(c)
        s = 0.80 + 0.20 * t
        p.scale(s, s)
        p.translate(-c)
        # catch drops anywhere on the menu, also in the gaps (never on what's below)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 2))
        p.drawEllipse(c, R_DISC + 24, R_DISC + 24)

        # the glass disc
        if self.disc is not None and not self.disc.isNull():
            p.drawImage(0, 0, self.disc)
            glass.paint_glass(p, circle_path(c, R_DISC), QColor(255, 255, 255, 30))
        else:
            glass.paint_glass(p, circle_path(c, R_DISC),
                              th.glass if self.backdrop is not None else th.solid, self.backdrop)
        # frosted rim band and hub ring
        band = circle_path(c, R_DISC - 1).subtracted(circle_path(c, R_OUT + 4))
        p.fillPath(band, QColor(255, 255, 255, 46))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
        p.setBrush(QColor(255, 255, 255, 34 + int(30 * self.hub_spring)))
        p.drawEllipse(c, R_HUB, R_HUB)

        items = self.items
        n = len(items) or 7
        paths = self._paths(n)
        rot = (1 - self._swap) * -22
        for i, path in enumerate(paths):
            h = self.spring[i] if i < len(self.spring) else 0.0
            a0, a1 = span(n, i)
            mid = math.radians((a0 + a1) / 2)
            push = QPointF(3 * h * math.cos(mid), -3 * h * math.sin(mid))
            seg = path.translated(push)
            p.fillPath(seg, th.segment)
            if h > 0.001:
                a = QColor(th.accent)
                a.setAlphaF(min(1.0, h))
                p.fillPath(seg, a)
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(seg)
            if i < len(items):
                lm = math.radians((a0 + a1) / 2 + rot)
                rc = (R_IN + R_OUT) / 2 + 1
                at = QPointF(c.x() + rc * math.cos(lm), c.y() - rc * math.sin(lm)) + push
                self._label(p, at, items[i], h)
        self._capsule(p, c)

    def _label(self, p: QPainter, at: QPointF, it: Item, h: float):
        """The action's name, with its symbol above it for tools; the group is centred on `at`
        by its visible height (cap height for the text)."""
        p.save()
        p.setOpacity(p.opacity() * (0.25 + 0.75 * self._swap))
        col = QColor(255, 255, 255) if h > 0.5 else QColor(self.theme.label)
        if it.symbol or it.glyph:
            f = glass.font(10, QFont.Medium)
            fm = QFontMetricsF(f)
            pm = glass.symbol(it.symbol, 15, col, "medium") if it.symbol else None
            sym_h = pm.height() / pm.devicePixelRatio() if pm is not None else 16
            gap = 5
            top = at.y() - (sym_h + gap + fm.capHeight()) / 2
            glass.draw_symbol(p, it.symbol, QPointF(at.x(), top + sym_h / 2), 15, col, it.glyph, "medium")
            base = top + sym_h + gap + fm.capHeight()
        else:
            f = glass.font(12, QFont.DemiBold)
            fm = QFontMetricsF(f)
            base = at.y() + fm.capHeight() / 2
        p.setFont(f)
        p.setPen(col)
        p.drawText(QPointF(at.x() - fm.horizontalAdvance(it.label) / 2, base), it.label)
        p.restore()

    def _capsule(self, p: QPainter, c: QPointF):
        """The hub's capsule names the action under the pointer (or the ring)."""
        items = self.items
        hov = items[self.hover] if 0 <= self.hover < len(items) else None
        if hov is not None:
            text = hov.label
        elif self.ring_names:
            text = self.ring_names[self.ring_idx]
        else:
            text = "Drop here"
        f = glass.font(12, QFont.DemiBold)
        fm = QFontMetricsF(f)
        text = fm.elidedText(text, Qt.ElideRight, 2 * R_HUB - 30)
        w = min(2 * R_HUB - 12, max(62.0, fm.horizontalAdvance(text) + 24))
        r = QRectF(c.x() - w / 2, c.y() - CAP_H / 2, w, CAP_H)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.0))
        p.setBrush(self.theme.segment)
        p.drawRoundedRect(r, CAP_H / 2, CAP_H / 2)
        p.setFont(f)
        p.setPen(self.theme.label)
        p.drawText(QPointF(c.x() - fm.horizontalAdvance(text) / 2, c.y() + fm.capHeight() / 2), text)
