"""Apple Vision actions (macOS only): Remove BG and Copy Text."""
import sys

import pytest
from PIL import Image, ImageDraw

from dragshift import convert, imaging

mac = pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision is macOS only")


def scan(tmp_path):
    from PIL import ImageFont
    im = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 44)
    d.text((40, 60), "Quarterly report 2026", fill="black", font=f)
    d.text((40, 150), "Revenue grew 12% year over year.", fill="black", font=f)
    p = tmp_path / "Scan.png"
    im.save(p)
    return p


@mac
def test_read_text_from_picture_and_scanned_pdf(tmp_path):
    p = scan(tmp_path)
    assert "Revenue grew 12%" in imaging.read_text(p)
    pdf = convert.convert(p, "image", "PDF")[0]      # a PDF with no text layer
    assert "Quarterly report" in imaging.read_text(pdf)


@mac
def test_read_text_finds_nothing(tmp_path):
    p = tmp_path / "Blank.png"
    Image.new("RGB", (400, 300), "white").save(p)
    with pytest.raises(Exception, match="No text"):
        imaging.read_text(p)


@mac
def test_remove_background(tmp_path):
    from dragshift import platform_mac
    if not platform_mac.can_lift_subject():
        pytest.skip("needs macOS 14")
    im = Image.new("RGB", (800, 600), (235, 235, 230))
    d = ImageDraw.Draw(im)
    d.ellipse((250, 120, 550, 420), fill=(200, 40, 50))
    d.rectangle((380, 400, 420, 560), fill=(90, 60, 30))
    p = tmp_path / "Subject.jpg"
    im.save(p, quality=92)
    out = imaging.remove_background(p)
    assert out.name == "Subject No Background.png"
    with Image.open(out) as o:
        a = o.getchannel("A")
        assert a.getpixel((10, 10)) < 30 and a.getpixel((400, 270)) > 220
