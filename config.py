import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()


@dataclass(frozen=True)
class WordPressClientConfig:
    client_id: str
    wp_base_url: str
    wp_username: str
    wp_app_password: str


def env_prefix_for_client(client_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", client_id).strip("_").upper()
    return cleaned or "FLAIRLAB"


def get_client_config(client_id: str = "flairlab") -> WordPressClientConfig:
    prefix = env_prefix_for_client(client_id)
    return WordPressClientConfig(
        client_id=client_id,
        wp_base_url=os.getenv(f"{prefix}_WP_BASE_URL") or os.getenv("WP_BASE_URL", "https://staging.flairlab.de"),
        wp_username=os.getenv(f"{prefix}_WP_USERNAME") or os.getenv("WP_USERNAME", ""),
        wp_app_password=os.getenv(f"{prefix}_WP_APP_PASSWORD") or os.getenv("WP_APP_PASSWORD", ""),
    )


_active_client_id: ContextVar[str] = ContextVar("active_client_id", default="flairlab")


def set_active_client(client_id: str) -> None:
    _active_client_id.set(client_id or "flairlab")


def get_active_client_id() -> str:
    return _active_client_id.get()


def get_active_client_config() -> WordPressClientConfig:
    return get_client_config(get_active_client_id())


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
KNOWLEDGE_WORKBOOK_PATH = os.getenv("KNOWLEDGE_WORKBOOK_PATH", "")
KNOWLEDGE_WORKBOOK_GCS_URI = os.getenv("KNOWLEDGE_WORKBOOK_GCS_URI", "")
KNOWLEDGE_SOURCE_POLICY = os.getenv("KNOWLEDGE_SOURCE_POLICY", "").strip().lower()
KNOWLEDGE_WORKBOOK_SHEET = os.getenv("KNOWLEDGE_WORKBOOK_SHEET", "")
SESSION_STATE_GCS_PREFIX = os.getenv("SESSION_STATE_GCS_PREFIX", "")
CONTENT_PIPELINE_VERSION = os.getenv("CONTENT_PIPELINE_VERSION", "v2").strip().lower()
V2_KNOWLEDGE_WORKBOOK_PATH = os.getenv("V2_KNOWLEDGE_WORKBOOK_PATH", "")
V2_SESSION_ROOT = os.getenv("V2_SESSION_ROOT", "data/v2_sessions")
V2_SESSION_GCS_PREFIX = os.getenv("V2_SESSION_GCS_PREFIX", "")
V2_LANGUAGE_MODEL = os.getenv("V2_LANGUAGE_MODEL", "gpt-5.5")
V2_VISION_MODEL = os.getenv("V2_VISION_MODEL", "gpt-5.5")
V2_TRANSCRIPTION_MODEL = os.getenv("V2_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
V2_IMAGE_EDIT_MODEL = os.getenv("V2_IMAGE_EDIT_MODEL", "gpt-image-1")
V2_MAX_IMAGE_BYTES = int(os.getenv("V2_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
V2_MAX_AUDIO_BYTES = int(os.getenv("V2_MAX_AUDIO_BYTES", str(50 * 1024 * 1024)))
WP_BASE_URL = get_client_config().wp_base_url
WP_USERNAME = get_client_config().wp_username
WP_APP_PASSWORD = get_client_config().wp_app_password
