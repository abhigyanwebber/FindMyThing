"""Generated, real image fixtures (no checked-in binaries). Every fixture carries identifiable metadata on purpose."""

from __future__ import annotations

import io
import os

from PIL import Image, PngImagePlugin

MARKER = "SECRET-CAMERA-9137"  # must never survive re-encoding
EXIF_ORIENTATION, EXIF_MAKE, EXIF_SOFTWARE, EXIF_GPS_IFD = 0x0112, 0x010F, 0x0131, 0x8825


def _pixels(size: tuple[int, int], mode: str = "RGB") -> Image.Image:
    img = Image.new(mode, size)
    img.putdata([((x * 7) % 256, (y * 13) % 256, (x + y) % 256) if mode == "RGB" else ((x * 7) % 256, (y * 13) % 256, (x + y) % 256, 200)
                 for y in range(size[1]) for x in range(size[0])])
    return img


def _exif(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = orientation
    exif[EXIF_MAKE] = MARKER
    exif[EXIF_SOFTWARE] = MARKER
    exif.get_ifd(EXIF_GPS_IFD)[1] = "N"  # a GPS IFD is present
    return exif


def jpeg_with_exif(size: tuple[int, int] = (40, 20), orientation: int = 1) -> bytes:
    out = io.BytesIO()
    _pixels(size).save(out, "JPEG", exif=_exif(orientation), comment=MARKER.encode(), quality=90)
    return out.getvalue()


def png_with_text(size: tuple[int, int] = (30, 30), alpha: bool = False) -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", MARKER)
    info.add_text("Comment", MARKER)
    out = io.BytesIO()
    _pixels(size, "RGBA" if alpha else "RGB").save(out, "PNG", pnginfo=info, exif=_exif())
    return out.getvalue()


def webp_with_exif(size: tuple[int, int] = (30, 30)) -> bytes:
    out = io.BytesIO()
    _pixels(size).save(out, "WEBP", exif=_exif(), quality=90)
    return out.getvalue()


def gif_static() -> bytes:
    out = io.BytesIO()
    Image.new("P", (10, 10), 3).save(out, "GIF")
    return out.getvalue()


def bmp() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (10, 10), (1, 2, 3)).save(out, "BMP")
    return out.getvalue()


def oversized_png() -> bytes:
    """A decodable PNG just over the 5,000,000-byte limit (random noise does not compress)."""
    out = io.BytesIO()
    Image.frombytes("RGB", (1300, 1300), os.urandom(1300 * 1300 * 3)).save(out, "PNG", compress_level=0)
    data = out.getvalue()
    assert len(data) > 5_000_000
    return data


def truncated_jpeg() -> bytes:
    return jpeg_with_exif((200, 200))[:120]


NOT_AN_IMAGE = b"%PDF-1.7 definitely not an image " + os.urandom(64)
