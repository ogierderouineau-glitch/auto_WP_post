import json
import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

APP_NAME = os.getenv("APP_NAME", "Speech2Post")
CLIENT_CONFIG_PATHS = (Path("/etc/secrets/clients.json"), Path("clients.json"))


@dataclass(frozen=True)
class WordPressClientConfig:
    client_id: str
    name: str
    country: str
    language: str
    import_api_key: str
    wp_base_url: str
    wp_username: str
    wp_app_password: str
    session_prefix: str
    knowledge_workbook: str


def _required_string(record: dict[str, Any], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{context}.{key} must be a non-empty string.")
    return value.strip()


def _load_clients() -> tuple[dict[str, WordPressClientConfig], Path | None]:
    path = next((candidate for candidate in CLIENT_CONFIG_PATHS if candidate.is_file()), None)
    if path is None:
        if os.getenv("RENDER"):
            raise RuntimeError("Missing Render secret file: /etc/secrets/clients.json")
        # Allows isolated unit tests and tooling to import configuration without
        # possessing deployment secrets. Auth remains unavailable.
        return {
            "default": WordPressClientConfig(
                client_id="default",
                name="Default client",
                country="DE",
                language="de-DE",
                import_api_key="",
                wp_base_url="",
                wp_username="",
                wp_app_password="",
                session_prefix="clients/default/v2-sessions",
                knowledge_workbook="clients/default/knowledge/current.xlsm",
            )
        }, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load client configuration from {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError(f"{path} must contain a non-empty JSON object.")

    clients: dict[str, WordPressClientConfig] = {}
    import_keys: set[str] = set()
    for client_id, value in raw.items():
        if (
            not isinstance(client_id, str)
            or not client_id
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in client_id)
        ):
            raise RuntimeError(f"Invalid client ID in {path}: {client_id!r}")
        if not isinstance(value, dict):
            raise RuntimeError(f"Client {client_id!r} in {path} must be an object.")
        wordpress = value.get("wordpress")
        storage = value.get("storage")
        if not isinstance(wordpress, dict):
            raise RuntimeError(f"clients.{client_id}.wordpress must be an object.")

        storage_config: dict[str, Any] = {}
        if isinstance(storage, dict):
            storage_config = storage
        else:
            storage_config = {
                "session_prefix": value.get("session_prefix"),
                "knowledge_workbook": value.get("knowledge_workbook"),
            }

        import_key = _required_string(value, "import_api_key", f"clients.{client_id}")
        if import_key in import_keys:
            raise RuntimeError(f"Duplicate import_api_key in {path}.")
        import_keys.add(import_key)
        clients[client_id] = WordPressClientConfig(
            client_id=client_id,
            name=_required_string(value, "name", f"clients.{client_id}"),
            country=_required_string(value, "country", f"clients.{client_id}"),
            language=_required_string(value, "language", f"clients.{client_id}"),
            import_api_key=import_key,
            wp_base_url=_required_string(wordpress, "base_url", f"clients.{client_id}.wordpress"),
            wp_username=_required_string(wordpress, "username", f"clients.{client_id}.wordpress"),
            wp_app_password=_required_string(wordpress, "app_password", f"clients.{client_id}.wordpress"),
            session_prefix=_required_string(storage_config, "session_prefix", f"clients.{client_id}.storage").strip("/"),
            knowledge_workbook=_required_string(
                storage_config, "knowledge_workbook", f"clients.{client_id}.storage"
            ).strip("/"),
        )
    return clients, path


CLIENTS, CLIENT_CONFIG_PATH = _load_clients()
DEFAULT_CLIENT_ID = next(iter(CLIENTS))


def get_client_config(client_id: str | None = None) -> WordPressClientConfig:
    resolved_client_id = str(client_id or DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID
    client = CLIENTS.get(resolved_client_id)
    if client is None:
        raise KeyError(f"Unknown client: {resolved_client_id}")
    return client


def import_key_for_client(client: WordPressClientConfig) -> str:
    return client.import_api_key


def client_from_import_key(import_key: str | None) -> WordPressClientConfig | None:
    if not import_key:
        return None
    for client_id in CLIENTS:
        client = get_client_config(client_id)
        expected = import_key_for_client(client)
        if expected and secrets.compare_digest(import_key, expected):
            return client
    return None


def configured_import_keys() -> bool:
    return any(import_key_for_client(get_client_config(client_id)) for client_id in CLIENTS)


_active_client_id: ContextVar[str] = ContextVar(
    "active_client_id",
    default=DEFAULT_CLIENT_ID,
)


def set_active_client(client_id: str) -> None:
    _active_client_id.set(client_id or DEFAULT_CLIENT_ID)


def get_active_client_id() -> str:
    return _active_client_id.get()


def get_active_client_config() -> WordPressClientConfig:
    return get_client_config(get_active_client_id())


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()


def _gcs_bucket_name(env_name: str, default_suffix: str) -> str:
    explicit = os.getenv(env_name, "").strip()
    if explicit:
        return explicit
    if GOOGLE_CLOUD_PROJECT:
        return f"{GOOGLE_CLOUD_PROJECT}{default_suffix}"
    return ""


GCS_DATA_BUCKET = _gcs_bucket_name("GCS_DATA_BUCKET", "-speech2post-data")
GCS_KNOWLEDGE_BUCKET = _gcs_bucket_name("GCS_KNOWLEDGE_BUCKET", "-speech2post-knowledge")
if os.getenv("RENDER"):
    missing_cloud_settings = [
        name
        for name, value in (
            ("GOOGLE_CLOUD_PROJECT", GOOGLE_CLOUD_PROJECT),
            ("GCS_DATA_BUCKET", GCS_DATA_BUCKET),
            ("GCS_KNOWLEDGE_BUCKET", GCS_KNOWLEDGE_BUCKET),
        )
        if not value
    ]
    if missing_cloud_settings:
        raise RuntimeError(
            "Missing required Render configuration: "
            + ", ".join(missing_cloud_settings)
        )
for bucket_setting, bucket_name in (
    ("GCS_DATA_BUCKET", GCS_DATA_BUCKET),
    ("GCS_KNOWLEDGE_BUCKET", GCS_KNOWLEDGE_BUCKET),
):
    if bucket_name and (bucket_name.startswith("gs://") or "/" in bucket_name):
        raise RuntimeError(f"{bucket_setting} must contain only a GCS bucket name.")
V2_SESSION_ROOT = os.getenv("V2_SESSION_ROOT", "data/v2_sessions")
V2_LANGUAGE_MODEL = os.getenv("V2_LANGUAGE_MODEL", "gpt-5.6")
V2_VISION_MODEL = os.getenv("V2_VISION_MODEL", "gpt-5-mini")
V2_TRANSCRIPTION_MODEL = os.getenv("V2_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
V2_IMAGE_EDIT_MODEL = os.getenv("V2_IMAGE_EDIT_MODEL", "gpt-image-2")
V2_IMAGE_EDIT_QUALITY = os.getenv("V2_IMAGE_EDIT_QUALITY", "medium").strip().lower()
V2_MAX_IMAGE_BYTES = int(os.getenv("V2_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
V2_MAX_AUDIO_BYTES = int(os.getenv("V2_MAX_AUDIO_BYTES", str(25 * 1024 * 1024)))
