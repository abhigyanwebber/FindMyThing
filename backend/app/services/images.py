"""Image validation and metadata-stripping re-encode (contract §9, §21).

Output format follows the *decoded* format (JPEG->JPEG, PNG->PNG, WebP->WebP) per §21 - see N-003.
Never trusts the client's MIME type, filename or extension. Raw unprocessed bytes are never stored.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

MAX_BYTES = 5_000_000
MAX_PIXELS = 40_000_000  # decompression-bomb guard
ALLOWED = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    extension: str


def _invalid(message: str) -> AppError:
    return AppError(422, "INVALID_IMAGE", message)


def process_image(raw: bytes) -> ProcessedImage:
    if len(raw) == 0:
        raise _invalid("The file is empty.")
    if len(raw) > MAX_BYTES:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Images must be 5,000,000 bytes or smaller.")
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = (probe.format or "").upper()
        if fmt not in ALLOWED:
            raise _invalid("Only JPEG, PNG and WebP images are accepted.")
        if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) > 1:
            raise _invalid("Animated images are not accepted.")
        probe.verify()  # structural check; image must be reopened afterwards
        img = Image.open(io.BytesIO(raw))
        img.load()
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, SyntaxError,
            EOFError):
        raise _invalid("The file is not a valid image.") from None

    img = ImageOps.exif_transpose(img)  # apply orientation into the pixels before dropping metadata
    content_type, ext = ALLOWED[fmt]
    out = io.BytesIO()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=88, optimize=True)  # no exif/icc/comment passed -> stripped
    elif fmt == "PNG":
        if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            img = img.convert("RGBA")
        img.save(out, "PNG", optimize=True)
    else:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode or "transparency" in img.info else "RGB")
        img.save(out, "WEBP", quality=88, method=4)
    data = out.getvalue()
    if len(data) > MAX_BYTES:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "The processed image exceeds 5,000,000 bytes.")
    return ProcessedImage(data=data, content_type=content_type, extension=ext)


_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def safe_original_filename(name: str | None) -> str:
    """Stored for provenance only; never used in keys, headers or API responses."""
    base = (name or "upload").replace("\\", "/").split("/")[-1]
    base = _CTRL.sub("", unicodedata.normalize("NFC", base)).strip()
    return (base or "upload")[:255]
