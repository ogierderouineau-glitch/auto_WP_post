from __future__ import annotations

import ipaddress
import mimetypes
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from pypdf import PdfReader
from PIL import Image

from backend.app.errors import explain, size_label

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


LINK_HELP = (
    "Use a direct link to the file itself: a picture (JPG, PNG, WebP, GIF) or an MP4 video that "
    "downloads or opens on its own, usually a link ending in .jpg, .png, .webp, .gif or .mp4. "
    "Share pages of Google Drive, Dropbox, WeTransfer, YouTube or Instagram usually do not work."
)


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
    if size <= 0:
        raise ValueError("The file is empty. Choose the file again.")
    if size > max_bytes:
        raise ValueError(f"This {kind} file is larger than the {size_label(max_bytes)} limit. Use a smaller or compressed file.")
    suffix = path.suffix.lower()
    detected = (declared_content_type or mimetypes.guess_type(path.name)[0] or "").split(";", 1)[0].strip().lower()
    if kind == "image":
        if suffix not in IMAGE_EXTENSIONS or not detected.startswith(IMAGE_MIME_PREFIX):
            raise ValueError("This file type is not supported. Allowed pictures: JPG, PNG, WebP, GIF.")
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(
                explain("This picture file seems damaged. Export it again as JPG or PNG and upload that file.", exc)
            ) from exc
    elif kind == "audio":
        if suffix not in AUDIO_EXTENSIONS or detected not in AUDIO_MIME_TYPES:
            raise ValueError("This file type is not supported. Allowed audio: MP3, M4A, OGG, OPUS, WAV, WEBM, MP4.")
    elif kind == "video":
        if suffix not in VIDEO_EXTENSIONS or detected not in VIDEO_MIME_TYPES:
            raise ValueError("Only MP4 video files are supported. Convert the video to MP4 and upload that file.")
    else:
        raise ValueError(f"Unsupported upload kind: {kind}")
    return detected


MAX_DOCUMENT_PAGES = 30
MAX_DOCUMENT_CHARS = 30_000


# Contact details with a recognisable shape. Street addresses and names have none, so they stay.
# Phone numbers must start with +, 00, ( or 0, so year ranges like "2015 - 2020" are kept.
_PERSONAL_DATA_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in (
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",  # email
    r"(?:https?://|www\.)\S+|(?:linkedin|xing|instagram|facebook)\.com/\S+",  # web and profile links
    r"(?<![\w.])@\w[\w.]{2,}",  # social handle such as @name
    r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b",  # IBAN
    # labelled birth date, month + year or year alone (the year would reveal the age too)
    r"\b(?:born|geboren(?: am)?|geburtsdatum|geburtsjahr|date of birth|dob|(?-i:n[éÉ]e?)(?: le| en)?|nacido(?: el| en)?)"
    r"\W{0,3}(?:\d{1,2}(?:st|nd|rd|th)?[./\s-]\s?)?(?:\d{1,2}[./-]|[a-zäéû]{3,9}\.?\s)?\d{4}\b|"
    r"\b(?:born|geboren(?: am)?|date of birth|dob)\W{0,3}\d{1,2}[./-]\d{1,2}[./-]\d{2}\b",
    r"\b(?:age|alter)\W{0,3}\d{2}\b|\b\d{2}\s*(?:years old|jahre alt|ans\b|años)",  # stated age
    r"(?<![\w])(?:\+|00|\(|0)\d[\d\s().\-/]{6,}\d",  # phone number
)]


def remove_personal_data(text: str) -> str:
    """Replace emails, links, IBANs, labelled birth dates and phone numbers with [removed]."""
    for pattern in _PERSONAL_DATA_PATTERNS:
        text = pattern.sub("[removed]", text)
    return text


def extract_pdf_text(path: Path) -> str:
    """Read the text of a PDF (max 30 pages, 30 000 characters) so the AI can use it as context.

    Contact details are removed here, before the text is stored or sent to any AI.

    Only text PDFs work: scanned pages have no text layer and are reported as empty.
    """
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected. Remove the password and upload it again.")
        if len(reader.pages) > MAX_DOCUMENT_PAGES:
            raise ValueError(
                f"This PDF has {len(reader.pages)} pages; the limit is {MAX_DOCUMENT_PAGES}. "
                "Upload only the pages that matter."
            )
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            explain("This PDF could not be read. Check that it opens normally and upload it again.", exc)
        ) from exc
    if not text:
        raise ValueError(
            "No text was found in this PDF. It is probably a scan or a picture of a document; "
            "only PDFs with selectable text are supported."
        )
    return remove_personal_data(text)[:MAX_DOCUMENT_CHARS]


def _require_public_host(url: str) -> None:
    """Refuse non-HTTP(S) links and hosts that resolve to private/internal addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{LINK_HELP} The link must start with http:// or https://.")
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
            raise ValueError(explain("The link could not be reached. Check that it is spelled correctly and opens in your browser.", exc)) from exc
        with response:
            if response.is_redirect:
                current = urljoin(current, response.headers.get("Location", ""))
                continue
            if not response.ok:
                hint = (
                    "The website refused the download: the link may need a login or has expired."
                    if response.status_code in (401, 403)
                    else "The file was not found: check the link."
                    if response.status_code == 404
                    else "The website had a problem: try again later."
                )
                raise ValueError(f"{hint} (HTTP {response.status_code})")
            name = Path(unquote(urlparse(current).path)).name
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type in ("", "application/octet-stream"):
                content_type = mimetypes.guess_type(name)[0] or content_type
            if not content_type.startswith(("image/", "video/")):
                raise ValueError(f"This link opens a web page, not a file. {LINK_HELP}")
            if not Path(name).suffix:
                name += mimetypes.guess_extension(content_type) or ""
            size = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"The linked file is larger than the {size_label(max_bytes)} limit.")
                    handle.write(chunk)
            return content_type, name or "download"
    raise ValueError("The link redirects too many times.")
