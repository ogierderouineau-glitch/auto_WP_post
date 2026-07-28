from pathlib import Path
from types import SimpleNamespace

import pytest

from app.v2.models.step_01_session import ContentSession, MediaReference
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_02_uploads import validate_upload
from app.v2.errors import VideoProcessingError
from app.v2.storage.step_01_local import LocalObjectStorageProvider
from app.v2.sessions.step_01_repository import FileSessionRepository


def test_video_upload_validation_accepts_only_mp4(tmp_path: Path) -> None:
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"test-video")
    assert validate_upload(
        mp4,
        kind="video",
        declared_content_type="video/mp4",
        max_bytes=100,
    ) == "video/mp4"

    mov = tmp_path / "clip.mov"
    mov.write_bytes(b"test-video")
    with pytest.raises(ValueError, match="Only MP4"):
        validate_upload(
            mov,
            kind="video",
            declared_content_type="video/quicktime",
            max_bytes=100,
        )


def test_first_video_uses_shared_acf_destinations_with_unique_field_keys() -> None:
    first = MediaReference(
        media_id="first",
        filename="first.mp4",
        storage_uri="/stored/first.mp4",
        content_type="video/mp4",
        size_bytes=10,
    )
    second = first.model_copy(update={
        "media_id": "second",
        "filename": "second.mp4",
        "storage_uri": "/stored/second.mp4",
    })
    session = ContentSession(
        session_id="session",
        user_id="client",
        post_type_key="event",
        state="uploading",
        workbook_hash="hash",
        language="de",
        video_refs=[first, second],
        processed_videos=[{
            "media_id": "first",
            "path": "/stored/first.mp4",
            "poster_path": "/stored/first-poster.jpg",
        }],
    )
    snapshot = SimpleNamespace(acf_fields=[
        SimpleNamespace(
            enabled=True,
            include_in_payload=True,
            post_type_key="event",
            field_role="direct_acf",
            field_key="event_video_upload",
            acf_field_name="video_url",
        ),
        SimpleNamespace(
            enabled=True,
            include_in_payload=True,
            post_type_key="event",
            field_role="direct_acf",
            field_key="event_video_preview",
            acf_field_name="video_poster",
        ),
    ])

    media = ContentSessionService._video_publication_media(snapshot, session)

    assert [item["acf_field_name"] for item in media] == [
        "video_url",
        "video_poster",
    ]
    assert {item["source_video_media_id"] for item in media} == {"first"}


def test_publication_payload_rebuild_keeps_images_video_and_poster() -> None:
    reference = MediaReference(
        media_id="video",
        filename="clip.mp4",
        storage_uri="/stored/clip.mp4",
        content_type="video/mp4",
        size_bytes=10,
    )
    session = ContentSession(
        session_id="session",
        user_id="client",
        post_type_key="bartender",
        state="published",
        workbook_hash="hash",
        language="de",
        video_refs=[reference],
        processed_videos=[{
            "media_id": "video",
            "path": "/stored/clip.mp4",
            "poster_path": "/stored/clip-poster.jpg",
        }],
        image_metadata=[{"media_id": "image", "path": "/stored/image.webp"}],
    )
    snapshot = SimpleNamespace(acf_fields=[
        SimpleNamespace(
            enabled=True,
            include_in_payload=True,
            post_type_key="bartender",
            field_role="direct_acf",
            acf_field_name="video_url",
        ),
        SimpleNamespace(
            enabled=True,
            include_in_payload=True,
            post_type_key="bartender",
            field_role="direct_acf",
            acf_field_name="video_poster",
        ),
    ])

    media = ContentSessionService._publication_media(snapshot, session)

    assert [item.get("media_kind", "image") for item in media] == [
        "image",
        "video",
        "video_poster",
    ]


def test_missing_ffmpeg_becomes_actionable_service_error(tmp_path: Path) -> None:
    class MissingProcessor:
        def process(self, *_args, **_kwargs):
            raise RuntimeError("Video processing requires ffmpeg.")

    session = ContentSession(
        session_id="session",
        user_id="client",
        post_type_key="event",
        state="uploading",
        workbook_hash="hash",
        language="de",
    )
    repository = FileSessionRepository(tmp_path / "sessions")
    repository.create(session)
    service = ContentSessionService(
        knowledge=SimpleNamespace(),
        repository=repository,
        object_storage=LocalObjectStorageProvider(tmp_path / "storage"),
        video_processor=MissingProcessor(),
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")

    with pytest.raises(VideoProcessingError, match="requires ffmpeg"):
        service.attach_upload(
            "session",
            source=source,
            kind="video",
            filename="clip.mp4",
            content_type="video/mp4",
            expected_version=1,
        )
