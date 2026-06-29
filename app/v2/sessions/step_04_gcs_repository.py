from __future__ import annotations

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

from app.v2.errors import SessionNotFoundError, SessionVersionConflictError
from app.v2.models.step_01_session import ContentSession
from app.v2.sessions.step_01_repository import SessionRepository
from app.v2.storage.step_03_gcs import parse_gcs_uri


class GCSSessionRepository(SessionRepository):
    """GCS JSON repository with object-generation conflict protection."""

    def __init__(self, root_uri: str) -> None:
        bucket_name, self.prefix = parse_gcs_uri(root_uri)
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def create(self, session: ContentSession) -> ContentSession:
        blob = self._blob(session.session_id)
        try:
            blob.upload_from_string(
                session.model_dump_json(indent=2),
                content_type="application/json",
                if_generation_match=0,
            )
        except PreconditionFailed as exc:
            raise SessionVersionConflictError(
                f"Session already exists: {session.session_id}"
            ) from exc
        return session

    def get(self, session_id: str) -> ContentSession:
        blob = self._blob(session_id)
        if not blob.exists():
            raise SessionNotFoundError(f"V2 session not found: {session_id}")
        return ContentSession.model_validate_json(blob.download_as_text())

    def save(self, session: ContentSession, *, expected_version: int) -> ContentSession:
        blob = self._blob(session.session_id)
        try:
            blob.reload()
        except Exception as exc:
            raise SessionNotFoundError(f"V2 session not found: {session.session_id}") from exc
        current = ContentSession.model_validate_json(blob.download_as_text())
        if current.version != expected_version:
            raise SessionVersionConflictError(
                f"Session {session.session_id} changed from version "
                f"{expected_version} to {current.version}."
            )
        updated = session.model_copy(update={"version": expected_version + 1})
        try:
            blob.upload_from_string(
                updated.model_dump_json(indent=2),
                content_type="application/json",
                if_generation_match=blob.generation,
            )
        except PreconditionFailed as exc:
            raise SessionVersionConflictError(
                f"Concurrent update detected for session {session.session_id}."
            ) from exc
        return updated

    def list(self) -> list[ContentSession]:
        prefix = "/".join(part for part in (self.prefix, "") if part)
        sessions: list[ContentSession] = []
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            if not blob.name.endswith("/state.json"):
                continue
            try:
                sessions.append(ContentSession.model_validate_json(blob.download_as_text()))
            except Exception:
                continue
        return sessions

    def delete(self, session_id: str) -> bool:
        blob = self._blob(session_id)
        prefix = blob.name.removesuffix("state.json")
        deleted = False
        for item in self.client.list_blobs(self.bucket, prefix=prefix):
            item.delete()
            deleted = True
        return deleted

    def _blob(self, session_id: str):
        safe_id = session_id.strip()
        if not safe_id or "/" in safe_id or "\\" in safe_id:
            raise SessionNotFoundError("Invalid session identifier.")
        object_name = "/".join(
            part
            for part in (self.prefix, safe_id, "state.json")
            if part
        )
        return self.bucket.blob(object_name)
