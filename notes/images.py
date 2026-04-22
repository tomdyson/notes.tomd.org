"""Image upload validation and Pillow pipeline."""

import io

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image as PImage
from PIL import UnidentifiedImageError

from .models import Image


class ImageError(Exception):
    """Raised when an uploaded file fails validation."""


_ALLOWED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "HEIC", "HEIF"}


def process_upload(upload) -> Image:
    """Validate, re-encode, and persist an uploaded image.

    Returns a saved Image. Raises ImageError on any validation failure.
    """
    max_bytes = settings.IMAGE_MAX_UPLOAD_BYTES
    if upload.size is not None and upload.size > max_bytes:
        raise ImageError(f"File too large (max {max_bytes // (1024 * 1024)}MB).")

    data = upload.read()
    if len(data) > max_bytes:
        raise ImageError(f"File too large (max {max_bytes // (1024 * 1024)}MB).")

    head = data[:64].lstrip()
    if head.startswith(b"<?xml") or head.lower().startswith(b"<svg"):
        raise ImageError("SVG uploads are not allowed.")

    try:
        src = PImage.open(io.BytesIO(data))
        src.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageError("File is not a recognised image.")

    fmt = (src.format or "").upper()
    if fmt not in _ALLOWED_FORMATS:
        raise ImageError(f"Unsupported image format: {fmt or 'unknown'}.")

    if src.mode in ("P", "RGBA", "LA"):
        src = src.convert("RGBA")
    else:
        src = src.convert("RGB")

    max_dim = settings.IMAGE_MAX_DIMENSION
    if src.width > max_dim or src.height > max_dim:
        src.thumbnail((max_dim, max_dim), PImage.Resampling.LANCZOS)

    buf = io.BytesIO()
    save_kwargs = {"format": "WEBP", "quality": settings.IMAGE_WEBP_QUALITY, "method": 6}
    src.save(buf, **save_kwargs)
    buf.seek(0)

    image = Image(
        original_name=(upload.name or "")[:255],
        width=src.width,
        height=src.height,
    )
    image.assign_short_id()
    image.file.save(f"{image.short_id}.webp", ContentFile(buf.getvalue()), save=False)
    image.save()
    return image
