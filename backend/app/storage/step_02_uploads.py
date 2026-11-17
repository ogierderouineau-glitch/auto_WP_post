from __future__ import annotations

import ipaddress
import mimetypes
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
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
VIDEO_EXTENSIONS = {".mp4"}
VIDEO_MIME_TYPES = {"video/mp4", "application/mp4"}


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
    elif kind == "video":
        if suffix not in VIDEO_EXTENSIONS or detected not in VIDEO_MIME_TYPES:
            raise ValueError("Only MP4 video uploads are supported.")
    else:
        raise ValueError(f"Unsupported upload kind: {kind}")
    return detected


def _require_public_host(url: str) -> None:
    """Refuse non-HTTP(S) links and hosts that resolve to private/internal addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a full http(s) link to a picture or MP4 video.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("The link's host could not be found.") from exc
    if not all(ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Links to private or internal addresses are not allowed.")


def download_media_url(url: str, destination: Path, max_bytes: int) -> tuple[str, str]:
    """Download a public media link into `destination`; returns (content_type, filename).

    Redirects are followed by hand so every hop is checked against private addresses
    (otherwise a public link could redirect the server to an internal one).
    """
    current = url.strip()
    for _ in range(4):
        _require_public_host(current)
        try:
            response = requests.get(current, stream=True, timeout=(5, 30), allow_redirects=False)
        except requests.RequestException as exc:
            raise ValueError("The link could not be downloaded.") from exc
        with response:
            if response.is_redirect:
                current = urljoin(current, response.headers.get("Location", ""))
                continue
            if not response.ok:
                raise ValueError(f"The link returned HTTP {response.status_code}.")
            name = Path(unquote(urlparse(current).path)).name
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type in ("", "application/octet-stream"):
                content_type = mimetypes.guess_type(name)[0] or content_type
            if not content_type.startswith(("image/", "video/")):
                raise ValueError("The link does not lead directly to a picture or MP4 video file.")
            if not Path(name).suffix:
                name += mimetypes.guess_extension(content_type) or ""
            size = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"The file exceeds the {max_bytes}-byte limit.")
                    handle.write(chunk)
            return content_type, name or "download"
    raise ValueError("The link redirects too many times.")
