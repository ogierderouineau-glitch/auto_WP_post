from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".webm", ".mp4"}
IMAGE_MIME_PREFIX = "image/"
AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "video/mp4",
}


def safe_upload_name(filename: str, fallback_extension: str) -> str:
    name = Path(filename or "").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-._")
    suffix = Path(name).suffix.lower() or fallback_extension
    return f"{stem or 'upload'}-{uuid.uuid4().hex[:12]}{suffix}"


def validate_upload(
    path: Path,
    *,
    kind: str,
    declared_content_type: str | None,
    max_bytes: int,
) -> str:
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise ValueError(f"{kind} upload size must be between 1 and {max_bytes} bytes.")
    suffix = path.suffix.lower()
    detected = (declared_content_type or mimetypes.guess_type(path.name)[0] or "").split(";", 1)[0].strip().lower()
    if kind == "image":
        if suffix not in IMAGE_EXTENSIONS or not detected.startswith(IMAGE_MIME_PREFIX):
            raise ValueError("Unsupported image extension or MIME type.")
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("Uploaded image is not decodable.") from exc
    elif kind == "audio":
        if suffix not in AUDIO_EXTENSIONS or detected not in AUDIO_MIME_TYPES:
            raise ValueError("Unsupported audio extension or MIME type.")
    else:
        raise ValueError(f"Unsupported upload kind: {kind}")
    return detected
