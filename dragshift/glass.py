"""Apple-style look shared by the radial menu, notifications and every window: the system
font (SF Pro on macOS), SF Symbols, Apple's system colours, and a glass surface painter."""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)

IS_MAC = sys.platform == "darwin"


def font(px: float, weight: QFont.Weight = QFont.Normal) -> QFont:
    """The system UI font as the OS hands it out (SF Pro on macOS, with Apple's optical sizes;
    Segoe UI on Windows) at a pixel size."""
    f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    return f


# ---------------------------------------------------------------- colours
@dataclass(frozen=True)
class Theme:
    """Light frosted glass with dark text; your system accent colour for anything selected
    or primary."""
    label: QColor          # primary text
    label2: QColor         # secondary text
    label3: QColor         # tertiary text, disabled
    fill: QColor           # secondary buttons, segmented-control track
    fill2: QColor          # hovered secondary button
    separator: QColor
    field: QColor          # text fields
    card: QColor           # grouped-form card on a window
    popup: QColor          # menus, combo lists, tooltips
    glass: QColor          # tint over refracted glass (notifications, the menu's disc)
    panel: QColor          # tint over refracted glass for windows (denser, for reading)
    solid: QColor          # glass stand-in when there's no backdrop to refract
    segment: QColor        # the menu's buttons and centre capsule
    accent: QColor
    green: QColor
    orange: QColor
    red: QColor


def accent() -> QColor:
    """The accent colour chosen in System Settings (macOS), else Apple's system blue."""
    if IS_MAC:
        from . import platform_mac
        rgb = platform_mac.accent_rgb()
        if rgb:
            return QColor(*rgb)
    return QColor(0, 122, 255)


def theme() -> Theme:
    return Theme(QColor(29, 29, 31), QColor(60, 60, 67, 170), QColor(60, 60, 67, 95),
                 QColor(255, 255, 255, 160), QColor(255, 255, 255, 220), QColor(0, 0, 0, 26),
                 QColor(255, 255, 255, 225), QColor(255, 255, 255, 120), QColor(250, 250, 252, 252),
                 QColor(255, 255, 255, 105), QColor(255, 255, 255, 150), QColor(246, 244, 242, 246),
                 QColor(255, 255, 255, 170), accent(),
                 QColor(52, 199, 89), QColor(255, 149, 0), QColor(255, 59, 48))


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.3f})"


# ---------------------------------------------------------------- SF Symbols
_SYMBOLS: dict = {}


def symbol(name: str, px: int, color: QColor, weight: str = "regular") -> QPixmap | None:
    """An SF Symbol as a tinted pixmap (macOS), or None elsewhere (callers draw a glyph)."""
    key = (name, px, color.rgba(), weight)
    if key in _SYMBOLS:
        return _SYMBOLS[key]
    pm = None
    if IS_MAC:
        from . import platform_mac
        data = platform_mac.symbol_png(name, px, weight)
        if data:
            img = QImage.fromData(data).convertToFormat(QImage.Format_ARGB32_Premultiplied)
            p = QPainter(img)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(img.rect(), color)
            p.end()
            img.setDevicePixelRatio(2.0)
            pm = QPixmap.fromImage(img)
    _SYMBOLS[key] = pm
    return pm


def draw_symbol(p: QPainter, name: str, center: QPointF, px: int, color: QColor,
                fallback: str = "", weight: str = "regular") -> None:
    """Draw an SF Symbol centred on `center`; without SF Symbols, draw `fallback` text."""
    pm = symbol(name, px, color, weight)
    if pm is not None:
        w, h = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
        p.drawPixmap(QRectF(center.x() - w / 2, center.y() - h / 2, w, h), pm, QRectF(pm.rect()))
    elif fallback:
        p.save()
        p.setFont(font(px * 1.1, QFont.DemiBold if weight in ("semibold", "bold") else QFont.Normal))
        p.setPen(color)
        p.drawText(QRectF(center.x() - px, center.y() - px, 2 * px, 2 * px), Qt.AlignCenter, fallback)
        p.restore()


def set_symbol(button, name: str, text: str = "", fallback: str = "", px: int = 14) -> None:
    """Give a button an SF Symbol icon (macOS) next to `text`; elsewhere show `fallback`."""
    pm = symbol(name, px, theme().label, "medium")
    if pm is None:
        button.setText(fallback or text)
        return
    button.setIcon(QIcon(pm))
    button.setIconSize(QSize(int(pm.width() / pm.devicePixelRatio()), int(pm.height() / pm.devicePixelRatio())))
    button.setText(text)


def symbol_file(name: str, px: int, color: QColor, weight: str = "semibold") -> str | None:
    """An SF Symbol saved as a PNG, for style sheets (`image: url(...)`)."""
    pm = symbol(name, px, color, weight)
    if pm is None:
        return None
    d = Path(tempfile.gettempdir()) / "dragshift-symbols"
    d.mkdir(exist_ok=True)
    f = d / f"{name}-{px}-{weight}-{color.rgba():08x}.png"
    if not f.exists():
        pm.save(str(f))
    return f.as_posix()


# ---------------------------------------------------------------- glass surfaces
def blur_pixmap(pm: QPixmap, radius: int = 18) -> QPixmap:
    """Fast frosted blur: downscale, light box blur via repeated scaling, upscale."""
    if pm.isNull():
        return pm
    w, h = pm.width(), pm.height()
    f = max(2, radius // 3)
    small = pm.scaled(max(1, w // f), max(1, h // f), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.scaled(max(1, w // (f * 2)), max(1, h // (f * 2)), Qt.IgnoreAspectRatio,
                         Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def paint_glass(p: QPainter, path: QPainterPath, tint: QColor, backdrop: QPixmap | None = None,
                highlight: float = 1.0) -> None:
    """A glass surface filling `path`: optional frosted backdrop, a neutral tint, a soft top
    sheen and a thin specular rim that's brightest on the edges facing the light (top-left),
    like Apple's Liquid Glass. A hairline keeps light glass visible on light backgrounds."""
    rect = path.boundingRect()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setClipPath(path)
    if backdrop is not None and not backdrop.isNull():
        p.drawPixmap(QPointF(0, 0), backdrop)
    p.fillPath(path, tint)
    sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + min(rect.height(), 120) * 0.6))
    sheen.setColorAt(0.0, QColor(255, 255, 255, int(26 * highlight)))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.setClipping(False)
    if tint.lightness() > 160:
        p.setPen(QPen(QColor(0, 0, 0, 34), 1.0))
        p.drawPath(path)
    rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
    rim.setColorAt(0.0, QColor(255, 255, 255, int(170 * highlight)))
    rim.setColorAt(0.35, QColor(255, 255, 255, int(40 * highlight)))
    rim.setColorAt(0.65, QColor(255, 255, 255, int(28 * highlight)))
    rim.setColorAt(1.0, QColor(255, 255, 255, int(100 * highlight)))
    p.setPen(QPen(QBrush(rim), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.restore()


# ---------------------------------------------------------------- Qt style sheet
def qss(t: Theme | None = None) -> str:
    """Controls in the style of macOS 26: capsule buttons, accent for the primary action and
    selections, quiet fields. The font is the application font (the system font, see app.py)."""
    t = t or theme()
    a = t.accent
    hover, pressed = a.lighter(112), a.darker(112)
    chevron = symbol_file("chevron.up.chevron.down", 9, t.label2)
    check = symbol_file("checkmark", 9, QColor(255, 255, 255), "bold")
    up = symbol_file("chevron.up", 8, t.label2)
    down = symbol_file("chevron.down", 8, t.label2)
    img = lambda f, w, h: f"image: url({f}); width: {w}px; height: {h}px;" if f else ""
    return f"""
* {{ color: {css(t.label)}; font-size: 13px; }}
QWidget#glassRoot {{ background: transparent; }}
QLabel#title {{ font-size: 13px; font-weight: 600; }}
QLabel#heading {{ font-size: 22px; font-weight: 700; }}
QLabel#dim, QLabel.dim {{ color: {css(t.label2)}; font-size: 12px; }}
QLabel#section {{ color: {css(t.label2)}; font-size: 12px; font-weight: 500; }}
QLabel#big {{ font-size: 26px; font-weight: 700; }}
QLabel#good {{ color: {css(t.green)}; font-weight: 600; }}
QLabel#warn {{ color: {css(t.orange)}; font-weight: 600; }}
QPushButton {{
  background: {css(t.fill)}; border: 1px solid rgba(0,0,0,0.06); border-radius: 13px;
  padding: 4px 16px; min-height: 16px; font-weight: 500;
}}
QPushButton:hover {{ background: {css(t.fill2)}; }}
QPushButton:pressed {{ background: rgba(255,255,255,0.4); }}
QPushButton:checked {{ background: {css(a)}; border-color: {css(a)}; color: white; }}
QPushButton:disabled {{ color: {css(t.label3)}; }}
QPushButton#primary {{ background: {css(a)}; border-color: {css(a)}; color: white; font-weight: 600; padding: 4px 18px; }}
QPushButton#primary:hover {{ background: {css(hover)}; }}
QPushButton#primary:pressed {{ background: {css(pressed)}; }}
QPushButton#primary:disabled {{ background: {css(t.fill)}; color: {css(t.label3)}; }}
QFrame#segmented {{ background: {css(t.fill)}; border: 1px solid rgba(0,0,0,0.06); border-radius: 14px; }}
QFrame#segmented QPushButton {{ background: transparent; border: none; border-radius: 11px; padding: 3px 13px; }}
QFrame#segmented QPushButton:hover {{ background: rgba(255,255,255,0.7); }}
QFrame#segmented QPushButton:checked {{ background: {css(a)}; color: white; font-weight: 600; }}
QPushButton#swatch {{
  border-radius: 7px; padding: 0; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
  border: 1px solid {css(t.separator)};
}}
QPushButton#swatch:checked {{ border: 2px solid {css(a)}; }}
QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: rgba(0,0,0,0.10); border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {css(a)}; border-radius: 2px; }}
QSlider::handle:horizontal {{
  background: #ffffff; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px;
  border: 1px solid rgba(0,0,0,0.14);
}}
QSpinBox, QLineEdit, QComboBox {{
  background: {css(t.field)}; border: 1px solid rgba(0,0,0,0.10); border-radius: 7px;
  padding: 3px 8px; min-height: 18px; selection-background-color: {css(a)}; selection-color: white;
}}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {css(a)}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ {img(chevron, 9, 11)} }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent; width: 16px; }}
QSpinBox::up-arrow {{ {img(up, 8, 5)} }}
QSpinBox::down-arrow {{ {img(down, 8, 5)} }}
QComboBox QAbstractItemView {{
  background: {css(t.popup)}; border: 1px solid {css(t.separator)}; border-radius: 8px; padding: 4px;
  selection-background-color: {css(a)}; selection-color: white; outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
  width: 14px; height: 14px; border-radius: 4px; border: 1px solid {css(t.label3)}; background: {css(t.field)};
}}
QCheckBox::indicator:checked {{ background: {css(a)}; border: 1px solid {css(a)}; {img(check, 10, 10)} }}
QFrame#card {{ background: {css(t.card)}; border: none; border-radius: 12px; }}
QFrame#hairline {{ background: {css(t.separator)}; border: none; min-height: 1px; max-height: 1px; }}
QTableWidget {{
  background: transparent; border: none; gridline-color: transparent;
  alternate-background-color: {css(t.card)}; selection-background-color: {css(a)};
}}
QTableWidget::item {{ padding: 3px 6px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
  background: transparent; border: none; border-bottom: 1px solid {css(t.separator)};
  padding: 4px 6px; color: {css(t.label2)}; font-size: 11px; font-weight: 600;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {css(t.label3)}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{
  background: {css(t.popup)}; color: {css(t.label)}; border: 1px solid {css(t.separator)};
  border-radius: 6px; padding: 4px 8px; font-size: 12px;
}}
QMenu {{ background: {css(t.popup)}; border: 1px solid {css(t.separator)}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 4px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {css(a)}; color: white; }}
QMenu::separator {{ height: 1px; background: {css(t.separator)}; margin: 4px 8px; }}
"""


# ---------------------------------------------------------------- Windows acrylic
class _ACCENT(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


def enable_acrylic(hwnd: int, tint_abgr: int = 0x40281E28) -> bool:
    """Real blur-behind for a frameless translucent window (Windows 10/11).
    Returns False elsewhere so callers can fall back to a painted frost."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        accent = _ACCENT(4, 2, tint_abgr, 0)  # 4 = ACCENT_ENABLE_ACRYLICBLURBEHIND
        data = _WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        ok = bool(user32.SetWindowCompositionAttribute(ctypes.c_void_p(hwnd), ctypes.byref(data)))
        try:  # rounded corners on Windows 11
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33,
                                                       ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass
        return ok
    except Exception:
        return False


def qimage_from_pil(im) -> QImage:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qi = QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888)
    return qi.copy()  # detach from the Python buffer


def pil_from_qimage(qi: QImage):
    from PIL import Image
    qi = qi.convertToFormat(QImage.Format_RGBA8888)
    ptr = qi.constBits()
    return Image.frombuffer("RGBA", (qi.width(), qi.height()), bytes(ptr), "raw", "RGBA",
                            qi.bytesPerLine(), 1).copy()


def rounded_rect_path(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


# ---------------------------------------------------------------- live liquid backing
def exclude_from_capture(hwnd: int) -> bool:
    """Hide a window from screen capture (Windows 10 2004+), so we can re-capture what's
    behind it while it's visible. Skipped while recording demos (it would hide us)."""
    import os
    if sys.platform == "darwin":
        from . import platform_mac
        return platform_mac.OK      # macOS: we capture "below our window" instead
    if sys.platform != "win32" or os.environ.get("DRAGSHIFT_RECORDING"):
        return False
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), 0x11))
    except Exception:
        return False


from PySide6.QtCore import QObject, QRect, QRunnable, QThreadPool, QTimer, Signal  # noqa: E402


class _LiquidSig(QObject):
    done = Signal(int, QImage, bool)


class _LiquidJob(QRunnable):
    def __init__(self, serial, backdrop, w, h, radius, style, dark):
        super().__init__()
        self.args = (serial, backdrop, w, h, radius, style, dark)
        self.sig = _LiquidSig()

    def run(self):
        serial, backdrop, w, h, radius, style, dark = self.args
        try:
            from . import liquid
            sdf = liquid.sdf_rounded_rect(w, h, 0.5, 0.5, w - 0.5, h - 0.5, radius)
            img, light = liquid.render(backdrop, sdf, style, dark=dark)
            try:
                self.sig.done.emit(serial, qimage_from_pil(img), light)
            except RuntimeError:
                pass  # window closed before the render finished
        except Exception:
            import traceback
            traceback.print_exc()


def grab_screen(x: int, y: int, w: int, h: int, below_window: int = 0):
    """Screen pixels under a rect (logical coords) as a PIL image of size w×h, or None.
    macOS: only if Screen Recording is already allowed, so DragShift never makes macOS ask
    (without it the glass is drawn frosted, with nothing behind it to bend); the capture
    leaves out the drag picture (and `below_window` and above)."""
    if sys.platform == "darwin":
        from . import platform_mac
        if not platform_mac.has_screen_recording():
            return None
        return platform_mac.capture(x, y, w, h, below_window)
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    scr = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2)) or QGuiApplication.primaryScreen()
    g = scr.geometry()
    try:
        shot = scr.grabWindow(0, x - g.x(), y - g.y(), w, h)
    except Exception:
        return None
    if shot.isNull():
        return None
    return pil_from_qimage(shot.toImage().scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))


class LiquidBacking(QObject):
    """Keeps a refracted snapshot of whatever is behind a rounded-rect window."""
    changed = Signal()

    def __init__(self, widget, radius: float, style=None):
        super().__init__(widget)
        from .liquid import GlassStyle
        self.w = widget
        self.radius = radius
        self.style = style or GlassStyle(blur=16, strength=14, bezel=20)
        self.image: QImage | None = None
        self.is_light = False
        self.excluded = False
        self._serial = 0
        self._debounce = QTimer(self, singleShot=True, interval=140, timeout=self.refresh)

    def capture_at(self, rect: QRect):
        """Grab the screen under `rect` (call before the window is shown, or when excluded)."""
        below = 0
        if sys.platform == "darwin" and self.w.isVisible():
            from . import platform_mac
            below = platform_mac.window_number(self.w)
        pil = grab_screen(rect.x(), rect.y(), rect.width(), rect.height(), below)
        if pil is None:
            return
        self._serial += 1
        job = _LiquidJob(self._serial, pil, rect.width(), rect.height(), self.radius, self.style, False)
        from .util import keep, release
        job.sig.done.connect(lambda *a, j=job: (release(j), self._done(*a)))
        QThreadPool.globalInstance().start(keep(job))

    def _done(self, serial, img, light):
        if serial == self._serial:
            self.image, self.is_light = img, light
            self.changed.emit()

    def moved(self):
        """Window moved/resized: refresh once it settles (only possible when excluded)."""
        if self.excluded:
            self.image = None if self.image is not None and self.image.size() != self.w.size() else self.image
            self._debounce.start()

    def refresh(self):
        if self.excluded and self.w.isVisible():
            self.capture_at(self.w.frameGeometry())


# ---------------------------------------------------------------- drag-image hiding
class hidden_drag_images:
    """While dragging, Windows draws a translucent picture of the file under the cursor.
    Hide it for the instant we capture the screen behind the menu, so it doesn't get frozen
    into the glass, then show it again. We hide every visible top-level window of another
    process that sits under the cursor and is layered + click-through (that is what drag
    images are), plus the known drag-image classes."""

    CLASSES = ("SysDragImage", "DragImageWindow", "DragWindow")
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020

    def __init__(self, point=None):
        self.point = point
        self.hwnds: list[int] = []
        self.info: list[str] = []
        self.rects: list[tuple[int, int, int, int]] = []   # screen px, for inpainting

    def __enter__(self):
        if sys.platform != "win32":
            return self
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            mypid = os.getpid()
            found = []
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def cb(hwnd, _):
                h = ctypes.c_void_p(hwnd)
                if not user32.IsWindowVisible(h):
                    return True
                r = wintypes.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                near = r.left - 40 <= pt.x <= r.right + 40 and r.top - 40 <= pt.y <= r.bottom + 40
                if not near or (r.right - r.left) > 900 or (r.bottom - r.top) > 900:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if pid.value == mypid:
                    return True
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(h, buf, 64)
                ex = user32.GetWindowLongW(h, -20)  # GWL_EXSTYLE
                drag_like = (ex & self.WS_EX_LAYERED) and (ex & self.WS_EX_TRANSPARENT)
                if buf.value in self.CLASSES or drag_like:
                    found.append(hwnd)
                    self.rects.append((r.left, r.top, r.right, r.bottom))
                    self.info.append(f"{buf.value} ex=0x{ex & 0xffffffff:08x} {r.right - r.left}x{r.bottom - r.top}")
                return True
            user32.EnumWindows(WNDENUMPROC(cb), 0)
            for h in found:
                user32.ShowWindow(ctypes.c_void_p(h), 0)  # SW_HIDE
            self.hwnds = found
            if found:
                ctypes.windll.gdi32.GdiFlush()
                ctypes.windll.dwmapi.DwmFlush()  # wait for the compositor to drop them
                ctypes.windll.dwmapi.DwmFlush()
        except Exception as e:
            self.info.append(f"error: {e}")
        return self

    def __exit__(self, *exc):
        if self.hwnds:
            try:
                for h in self.hwnds:
                    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(h), 8)  # SW_SHOWNA
            except Exception:
                pass
        return False


def inpaint_rects(im, rects, pad: int = 6):
    """Fill rectangles of a PIL image from their surroundings (normalised convolution):
    a smooth, colour-matched patch — invisible once refracted and blurred by the glass."""
    import numpy as np
    from PIL import Image, ImageFilter
    if not rects:
        return im
    rgb = im.convert("RGB")
    w, h = rgb.size
    mask = Image.new("L", (w, h), 255)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    any_hit = False
    for (x0, y0, x1, y1) in rects:
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
        if x1 > x0 and y1 > y0:
            d.rectangle((x0, y0, x1, y1), fill=0)
            any_hit = True
    if not any_hit:
        return im
    a = np.asarray(rgb, np.float32)
    m = np.asarray(mask, np.float32)[..., None] / 255
    radius = 28
    num = np.asarray(Image.fromarray(np.clip(a * m, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius)), np.float32)
    den = np.asarray(mask.filter(ImageFilter.GaussianBlur(radius)), np.float32)[..., None] / 255
    fill = num / np.maximum(den, 1e-3)
    fill = np.asarray(Image.fromarray(np.clip(fill, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)), np.float32)
    # feather the seam: the glass bezel magnifies any hard edge into a visible line
    soft = np.asarray(mask.filter(ImageFilter.GaussianBlur(12)), np.float32)[..., None] / 255
    soft = np.minimum(soft, m)  # never let the drag picture bleed back in
    out = a * soft + fill * (1 - soft)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
