"""Persistent settings + the Settings and Welcome windows."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from . import __version__, glass
from .util import CONFIG
from .window import GlassWindow, Switch, form_card

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
APP = "DragShift"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULTS = {
    "output": "next",
    "jpg_quality": 90,
    "pdf_dpi": 200,
    "trigger": "shift",
    "welcomed": False,
}


class Settings:
    def __init__(self):
        self.q = QSettings(APP, APP)

    def get(self, key):
        v = self.q.value(key, DEFAULTS[key])
        d = DEFAULTS[key]
        if isinstance(d, bool):
            return v in (True, "true", "1", 1)
        if isinstance(d, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d
        return v

    def set(self, key, value):
        self.q.setValue(key, value)
        self.apply()

    def apply(self):
        for k in ("output", "jpg_quality", "pdf_dpi"):
            CONFIG[k] = self.get(k)


# ---------------------------------------------------------------- autostart (Windows)
def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --quiet'
    return f'"{sys.executable}" -m dragshift --quiet'


def autostart_enabled() -> bool:
    if IS_MAC:
        from . import platform_mac
        return platform_mac.autostart_enabled()
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    if IS_MAC:
        from . import platform_mac
        platform_mac.set_autostart(on)
        return
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


TRIGGERS = ([("shift", "Shift ⇧"), ("ctrl", "Control ⌃"), ("alt", "Option ⌥")] if IS_MAC
            else [("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")])
OUTPUTS = [("next", "Next to the original"), ("folder", "In a “DragShift” subfolder")]
DPIS = [(150, "150 dpi · small"), (200, "200 dpi · balanced"), (300, "300 dpi · print")]


class SettingsWindow(GlassWindow):
    changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__("Settings", size=(500, 440))
        self.s = settings

        def combo(options, current):
            c = QComboBox()
            for v, label in options:
                c.addItem(label, v)
            values = [v for v, _ in options]
            c.setCurrentIndex(values.index(current) if current in values else 0)
            return c

        self.trigger = combo(TRIGGERS, self.s.get("trigger"))
        self.trigger.currentIndexChanged.connect(lambda _: self._save("trigger", self.trigger.currentData()))
        self.output = combo(OUTPUTS, self.s.get("output"))
        self.output.currentIndexChanged.connect(lambda _: self._save("output", self.output.currentData()))
        q_row = QHBoxLayout()
        self.q = QSlider(Qt.Horizontal)
        self.q.setRange(60, 100)
        self.q.setValue(self.s.get("jpg_quality"))
        self.q.setFixedWidth(150)
        self.qv = QLabel(str(self.q.value()))
        self.qv.setObjectName("dim")
        self.qv.setFixedWidth(26)
        self.qv.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.q.valueChanged.connect(lambda v: (self.qv.setText(str(v)), self._save("jpg_quality", v)))
        q_row.addWidget(self.q)
        q_row.addWidget(self.qv)
        self.dpi = combo(DPIS, self.s.get("pdf_dpi"))
        self.dpi.currentIndexChanged.connect(lambda _: self._save("pdf_dpi", self.dpi.currentData()))
        self.body.addWidget(form_card([
            ("Open the menu with", "Press it while you’re dragging a file", self.trigger),
            ("Save results", "", self.output),
            ("JPG and WebP quality", "", q_row),
            ("PDF to image resolution", "", self.dpi),
        ]))

        rows = []
        if IS_WIN or IS_MAC:
            self.auto = Switch(autostart_enabled())
            self.auto.toggled.connect(set_autostart)
            rows.append(("Start with Windows" if IS_WIN else "Open at login", "", self.auto))
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                allow = QPushButton("Allow…")
                allow.clicked.connect(platform_mac.request_screen_recording)
                rows.append(("Show windows through the glass",
                             "Needs Screen Recording. Without it the glass shows your wallpaper.", allow))
        if rows:
            self.body.addWidget(form_card(rows))
        self.body.addStretch(1)
        about = QLabel(f"DragShift {__version__}  ·  originals are never changed")
        about.setObjectName("dim")
        foot = QHBoxLayout()
        foot.addWidget(about)
        foot.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        foot.addWidget(done)
        self.body.addLayout(foot)

    def _save(self, key, value):
        self.s.set(key, value)
        self.changed.emit()


class SymbolBadge(QWidget):
    """An SF Symbol in a soft accent-tinted circle."""

    def __init__(self, name: str, fallback: str, parent=None):
        super().__init__(parent)
        self.name, self.fallback = name, fallback
        self.setFixedSize(32, 32)

    def paintEvent(self, e):
        a = glass.accent()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(a)
        bg.setAlpha(46)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(QRectF(0, 0, 32, 32))
        glass.draw_symbol(p, self.name, QPointF(16, 16), 15, a, self.fallback, "medium")


class WelcomeWindow(GlassWindow):
    def __init__(self, settings: Settings, trigger_label: str = "Shift"):
        super().__init__("", size=(500, 510))
        self.s = settings
        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        pm = QPixmap(str(Path(__file__).with_name("assets") / "dragshift.png"))
        if not pm.isNull():
            pm = pm.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2.0)
            icon.setPixmap(pm)
        self.body.addWidget(icon)
        head = QLabel("Welcome to DragShift")
        head.setObjectName("heading")
        head.setAlignment(Qt.AlignCenter)
        self.body.addWidget(head)
        sub = QLabel("Convert and edit any file, right from a drag.")
        sub.setObjectName("dim")
        sub.setAlignment(Qt.AlignCenter)
        self.body.addWidget(sub)
        self.body.addSpacing(6)

        where = "in Finder or on the desktop" if IS_MAC else "in File Explorer or on the desktop"
        steps = [
            ("hand.draw", "1", "Start dragging any file", where),
            ("shift", "⇧", f"Press {trigger_label}", "The menu opens right under your cursor"),
            ("tray.and.arrow.down", "↓", "Drop it on a button", "The result is saved next to the original"),
            ("arrow.left.arrow.right", "⇄", f"Tap {trigger_label} again", "To switch between Convert and Tools"),
        ]
        rows = QVBoxLayout()
        rows.setSpacing(12)
        for sym, fb, title, desc in steps:
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(SymbolBadge(sym, fb), 0, Qt.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(1)
            h = QLabel(title)
            h.setStyleSheet("font-weight: 600;")
            d = QLabel(desc)
            d.setObjectName("dim")
            text.addWidget(h)
            text.addWidget(d)
            row.addLayout(text, 1)
            rows.addLayout(row)
        box = QHBoxLayout()
        box.addSpacing(36)
        box.addLayout(rows, 1)
        box.addSpacing(20)
        self.body.addLayout(box)
        self.body.addStretch(1)
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                note = QHBoxLayout()
                t = QLabel("Optional: allow Screen Recording so the glass can show the windows behind "
                           "it. DragShift never saves or sends it.")
                t.setObjectName("dim")
                t.setWordWrap(True)
                note.addWidget(t, 1)
                b = QPushButton("Allow…")
                b.clicked.connect(platform_mac.request_screen_recording)
                note.addWidget(b, 0, Qt.AlignVCenter)
                self.body.addLayout(note)
        foot = QHBoxLayout()
        if IS_WIN or IS_MAC:
            self.auto = Switch(True)
            foot.addWidget(self.auto)
            foot.addSpacing(4)
            foot.addWidget(QLabel("Start with Windows" if IS_WIN else "Open at login"))
        foot.addStretch(1)
        ok = QPushButton("Get Started")
        ok.setObjectName("primary")
        ok.clicked.connect(self._done)
        foot.addWidget(ok)
        self.body.addLayout(foot)

    def _done(self):
        self.s.set("welcomed", True)
        if IS_WIN or IS_MAC:
            set_autostart(self.auto.isChecked())
        self.close()
