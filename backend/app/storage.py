"""Receipt image storage.

Uploads are never trusted: the file is decoded by Pillow, re-encoded from raw
pixels, and written under a server-generated name. That drops EXIF (including GPS
coordinates from phone cameras) and neutralises anything hiding in the container.
"""

from __future__ import annotations

import io
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
# Guard against decompression bombs -- a 100MP "receipt" is not a receipt.
Image.MAX_IMAGE_PIXELS = 80_000_000


class ReceiptError(ValueError):
    """Upload rejected for a reason worth showing the user."""


def _relative_dir(expense_id: uuid.UUID) -> Path:
    today = datetime.now(UTC)
    return Path(f"{today:%Y/%m}") / str(expense_id)


def _fit(image: Image.Image, max_edge: int) -> Image.Image:
    if max(image.size) <= max_edge:
        return image
    ratio = max_edge / max(image.size)
    new_size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(new_size, Image.LANCZOS)


def store_receipt(raw: bytes, expense_id: uuid.UUID) -> tuple[str, str, int]:
    """Validate and persist an upload.

    Returns (file_path, thumb_path, stored_size_bytes), both paths relative to the
    upload directory.
    """
    if not raw:
        raise ReceiptError("Die Datei ist leer.")
    if len(raw) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise ReceiptError(f"Das Bild ist zu groß (max. {limit_mb} MB).")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            # Phone photos carry rotation in EXIF; bake it into the pixels.
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            full = _fit(image, settings.image_max_edge)
            thumb = _fit(full.copy(), settings.thumbnail_max_edge)

            full_buffer = io.BytesIO()
            full.save(full_buffer, format="JPEG", quality=settings.jpeg_quality, optimize=True)
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="JPEG", quality=70, optimize=True)
    except UnidentifiedImageError as exc:
        raise ReceiptError("Das ist kein lesbares Bild.") from exc
    except Image.DecompressionBombError as exc:
        raise ReceiptError("Das Bild hat zu viele Pixel.") from exc
    except OSError as exc:
        raise ReceiptError("Das Bild konnte nicht verarbeitet werden.") from exc

    rel_dir = _relative_dir(expense_id)
    target_dir = settings.upload_dir / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = secrets.token_urlsafe(12)
    file_rel = rel_dir / f"{stem}.jpg"
    thumb_rel = rel_dir / f"{stem}_thumb.jpg"

    full_bytes = full_buffer.getvalue()
    (settings.upload_dir / file_rel).write_bytes(full_bytes)
    (settings.upload_dir / thumb_rel).write_bytes(thumb_buffer.getvalue())

    return str(file_rel), str(thumb_rel), len(full_bytes)


def resolve_path(relative_path: str) -> Path:
    """Turn a stored relative path into an absolute one, refusing escapes."""
    base = settings.upload_dir.resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_relative_to(base):
        raise ReceiptError("Ungültiger Pfad.")
    return candidate


def delete_receipt_files(*relative_paths: str) -> None:
    for relative_path in relative_paths:
        try:
            resolve_path(relative_path).unlink(missing_ok=True)
        except (ReceiptError, OSError):
            # A missing or unreachable file must not block deleting the database row.
            continue
