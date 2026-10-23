"""macOS integration (only imported on darwin).

* Trigger: NSEvent.pressedMouseButtons / modifierFlags give the *global* mouse and
  modifier state, with no Accessibility or Input Monitoring permission needed.
* Capture: CGWindowListCreateImage can capture "everything below window N", which keeps
  Finder's drag picture and our own windows out of the glass (live refresh like Windows'
  capture exclusion). It needs the Screen Recording permission, so it's only used once you've
  allowed that in Settings; otherwise the glass is drawn without a backdrop and macOS is
  never asked.
* Start at login: a LaunchAgent plist.
"""
from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

try:
    import AppKit  # pyobjc-framework-Cocoa
    import Quartz  # pyobjc-framework-Quartz
    OK = True
except Exception:  # pragma: no cover
    OK = False

# NSEventModifierFlags
SHIFT, CONTROL, OPTION, COMMAND = 1 << 17, 1 << 18, 1 << 19, 1 << 20
KEY_FLAGS = {"shift": SHIFT, "ctrl": CONTROL, "alt": OPTION}


# ---------------------------------------------------------------- input state
def left_button_down() -> bool:
    return bool(OK and AppKit.NSEvent.pressedMouseButtons() & 1)


def key_down(name: str) -> bool:
    return bool(OK and AppKit.NSEvent.modifierFlags() & KEY_FLAGS.get(name, SHIFT))


FILE_TYPES = {"public.file-url", "NSFilenamesPboardType"}


def drag_pasteboard() -> tuple[int, bool]:
    """(change count, holds files) of the system drag pasteboard. Finder writes it when a file
    drag starts; moving a window or selecting text doesn't, and dragging text writes no file
    type. Only the list of types is read, never the contents."""
    if not OK:
        return 0, False
    try:
        pb = AppKit.NSPasteboard.pasteboardWithName_(AppKit.NSPasteboardNameDrag)
        return int(pb.changeCount()), any(str(t) in FILE_TYPES for t in (pb.types() or []))
    except Exception:
        return 0, False


def escape_down() -> bool:
    if not OK:
        return False
    try:
        return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateCombinedSessionState, 53))
    except Exception:
        return False


# ---------------------------------------------------------------- app behaviour
def become_accessory():
    """Menu-bar app: no Dock icon (the bundle also sets LSUIElement)."""
    if OK:
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)


def activate():
    """Bring our windows to the front (accessory apps aren't activated automatically)."""
    if OK:
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def window_number(widget) -> int:
    """CGWindowID of a Qt top-level widget (winId() is an NSView*)."""
    if not OK:
        return 0
    try:
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        win = view.window()
        return int(win.windowNumber()) if win is not None else 0
    except Exception:
        return 0


# ---------------------------------------------------------------- screen capture
LAST_SWEEP: list[str] = []


def drag_window_ids(cursor: tuple[int, int] | None = None) -> list[int]:
    """The drag picture under the cursor: windows at the dragging level, or any small
    window of another app sitting right on the cursor above normal windows."""
    LAST_SWEEP.clear()
    if not OK:
        return []
    try:
        level = Quartz.CGWindowLevelForKey(Quartz.kCGDraggingWindowLevelKey)
        infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
        me = os.getpid()
        ids = []
        for i in infos:
            layer = int(i.get("kCGWindowLayer", 0))
            b = i.get("kCGWindowBounds", {}) or {}
            x, y, w, h = (float(b.get(k, 0)) for k in ("X", "Y", "Width", "Height"))
            near = cursor is not None and x - 40 <= cursor[0] <= x + w + 40 and y - 40 <= cursor[1] <= y + h + 40
            if near:
                LAST_SWEEP.append(f"{i.get('kCGWindowOwnerName')} layer={layer} {int(w)}x{int(h)}")
            if int(i.get("kCGWindowOwnerPID", 0)) == me:
                continue
            if layer >= level or (near and layer > 0 and w < 700 and h < 700):
                ids.append(int(i["kCGWindowNumber"]))
        return ids
    except Exception as e:
        LAST_SWEEP.append(f"error {e}")
        return []


def capture(x: int, y: int, w: int, h: int, below_window: int = 0):
    """Capture a screen rect (global points, top-left origin) as a PIL RGB image.
    below_window: capture only what is beneath that window (excludes it and anything above)."""
    if not OK:
        return None
    from PIL import Image
    rect = Quartz.CGRectMake(x, y, w, h)
    if below_window:
        opt, wid = Quartz.kCGWindowListOptionOnScreenBelowWindow, below_window
    else:
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        drags = drag_window_ids((int(loc.x), int(loc.y)))
        if drags:
            # everything below the lowest drag window = no drag picture in the glass
            opt, wid = Quartz.kCGWindowListOptionOnScreenBelowWindow, min(drags)
        else:
            opt, wid = Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    try:
        img = Quartz.CGWindowListCreateImage(rect, opt, wid, Quartz.kCGWindowImageBestResolution)
    except Exception:
        return None
    if img is None:
        return None
    width, height = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    im = Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA", bpr, 1)
    return im.convert("RGB").resize((w, h), Image.LANCZOS)


def has_screen_recording() -> bool:
    """Whether Screen Recording is already allowed. Only checks: never makes macOS ask."""
    try:
        return OK and bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return False


def request_screen_recording() -> bool:
    try:
        return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception:
        return False


# ---------------------------------------------------------------- Apple's look
def accent_rgb() -> tuple[int, int, int] | None:
    """The accent colour picked in System Settings → Appearance."""
    if not OK:
        return None
    try:
        c = AppKit.NSColor.controlAccentColor().colorUsingColorSpace_(AppKit.NSColorSpace.sRGBColorSpace())
        return int(c.redComponent() * 255), int(c.greenComponent() * 255), int(c.blueComponent() * 255)
    except Exception:
        return None


def symbol_png(name: str, px: int, weight: str = "regular") -> bytes | None:
    """An SF Symbol rendered (monochrome, as a template) at 2x as PNG, or None if unknown."""
    if not OK:
        return None
    try:
        img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if img is None:
            return None
        weights = {"light": AppKit.NSFontWeightLight, "regular": AppKit.NSFontWeightRegular,
                   "medium": AppKit.NSFontWeightMedium, "semibold": AppKit.NSFontWeightSemibold,
                   "bold": AppKit.NSFontWeightBold}
        cfg = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(px, weights.get(weight, 0.0))
        img = img.imageWithSymbolConfiguration_(cfg)
        w, h = img.size().width, img.size().height
        rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, int(round(w * 2)), int(round(h * 2)), 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
        rep.setSize_((w, h))
        AppKit.NSGraphicsContext.saveGraphicsState()
        AppKit.NSGraphicsContext.setCurrentContext_(AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
        img.drawInRect_(((0, 0), (w, h)))
        AppKit.NSGraphicsContext.restoreGraphicsState()
        data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
        return bytes(data)
    except Exception:
        return None


# ---------------------------------------------------------------- on-device Vision
def _cgimage(im):
    """A PIL image as an sRGB CGImage for Vision, straight from its pixels (no encoding)."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes()
    provider = Quartz.CGDataProviderCreateWithCFData(AppKit.NSData.dataWithBytes_length_(data, len(data)))
    return Quartz.CGImageCreate(w, h, 8, 24, w * 3, Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB),
                                Quartz.kCGImageAlphaNone, provider, None, False, Quartz.kCGRenderingIntentDefault)


def _mask_image(buf):
    """Vision's one-channel float mask (a CVPixelBuffer) as a PIL "L" image, read directly."""
    import numpy as np
    from PIL import Image
    Quartz.CVPixelBufferLockBaseAddress(buf, Quartz.kCVPixelBufferLock_ReadOnly)
    try:
        w, h = Quartz.CVPixelBufferGetWidth(buf), Quartz.CVPixelBufferGetHeight(buf)
        row = Quartz.CVPixelBufferGetBytesPerRow(buf)
        raw = Quartz.CVPixelBufferGetBaseAddress(buf).as_buffer(row * h)
        a = np.frombuffer(raw, dtype=np.float32).reshape(h, row // 4)[:, :w]
        return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), "L")
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(buf, Quartz.kCVPixelBufferLock_ReadOnly)


def _vision(name: str):
    try:
        import Vision
        return getattr(Vision, name, None)
    except Exception:
        return None


def can_lift_subject() -> bool:
    """Subject cut-out needs macOS 14 or later."""
    return OK and _vision("VNGenerateForegroundInstanceMaskRequest") is not None


def can_read_text() -> bool:
    return OK and _vision("VNRecognizeTextRequest") is not None


def subject_mask(im):
    """Mask (PIL "L", same size as `im`) of the picture's subject, found by Apple's on-device
    Vision, as in Photos' "lift subject"; None if there's no clear subject."""
    import Vision
    from PIL import Image
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(_cgimage(im), {})
    req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision couldn't analyse the picture: {err}")
    results = req.results() or []
    if not results:
        return None
    obs = results[0]
    buf, err = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(obs.allInstances(), handler, None)
    if buf is None:
        raise RuntimeError(f"Vision couldn't make the mask: {err}")
    mask = _mask_image(buf)
    return mask if mask.size == im.size else mask.resize(im.size, Image.LANCZOS)


def recognize_text(im) -> str:
    """Text in a picture, read by Apple's on-device Vision (Live Text), in reading order."""
    import Vision
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(_cgimage(im), {})
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    if req.respondsToSelector_("setAutomaticallyDetectsLanguage:"):
        req.setAutomaticallyDetectsLanguage_(True)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision couldn't read the picture: {err}")
    lines = []
    for obs in req.results() or []:
        top = obs.topCandidates_(1)
        if top:
            lines.append(str(top[0].string()))
    return "\n".join(lines)


# ---------------------------------------------------------------- start at login
AGENT_LABEL = "io.github.ronith-star.orbit"
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def _program() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--quiet"]
    return [sys.executable, "-m", "dragshift", "--quiet"]


def autostart_enabled() -> bool:
    return AGENT.exists()


def set_autostart(on: bool):
    if on:
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        with open(AGENT, "wb") as f:
            plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": _program(),
                           "RunAtLoad": True, "ProcessType": "Interactive"}, f)
    elif AGENT.exists():
        AGENT.unlink()
