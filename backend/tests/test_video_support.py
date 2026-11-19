from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models.step_01_session import ContentSession, MediaReference
from backend.app.sessions.step_03_service import ContentSessionService
from backend.app.storage.step_02_uploads import validate_upload
from backend.app.errors import VideoProcessingError
from backend.app.storage.step_01_local import LocalObjectStorageProvider
from backend.app.sessions.step_01_repository import FileSessionRepository


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


def test_replace_video_cover_overwrites_poster(tmp_path):
    from PIL import Image

    class FakeProcessor:
        def process(self, source, destination_dir, stem):
            video, poster = destination_dir / f"{stem}.mp4", destination_dir / f"{stem}-poster.jpg"
            video.write_bytes(b"video")
            Image.new("RGB", (10, 10), "red").save(poster)
            return SimpleNamespace(video=video, poster=poster, operations=())

    repository = FileSessionRepository(tmp_path / "sessions")
    repository.create(ContentSession(
        session_id="session", user_id="client", post_type_key="event",
        state="uploading", workbook_hash="hash", language="de",
    ))
    service = ContentSessionService(
        knowledge=SimpleNamespace(), repository=repository,
        object_storage=LocalObjectStorageProvider(tmp_path / "storage"),
        video_processor=FakeProcessor(),
    )
    source, cover = tmp_path / "clip.mp4", tmp_path / "cover.png"
    source.write_bytes(b"video")
    Image.new("RGB", (2000, 1000), "blue").save(cover)
    session = service.attach_upload(
        "session", source=source, kind="video", filename="clip.mp4",
        content_type="video/mp4", expected_version=1,
    )
    session = service.replace_video_cover(
        "session", filename=session.processed_videos[0]["filename"], cover=cover,
        expected_version=session.version,
    )
    with Image.open(session.processed_videos[0]["poster_path"].removeprefix("file://")) as poster:
        assert poster.size == (1280, 640) and poster.getpixel((5, 5))[2] > 200


def test_video_fields_with_prefixed_names_are_found() -> None:
    """Workbooks may name the ACF fields freely (here a real-estate style prefix)."""
    reference = MediaReference(
        media_id="v", filename="tour.mp4", storage_uri="/s/tour.mp4",
        content_type="video/mp4", size_bytes=1,
    )
    session = ContentSession(
        session_id="s", user_id="c", post_type_key="listing", state="published",
        workbook_hash="h", language="de", video_refs=[reference],
        processed_videos=[{"media_id": "v", "path": "/s/tour.mp4", "poster_path": "/s/tour.jpg"}],
    )
    rows = [
        SimpleNamespace(enabled=True, include_in_payload=True, post_type_key="listing",
                        field_role="direct_acf", acf_field_name=name)
        for name in ("tour_video_url", "tour_video_poster", "price")
    ]
    media = ContentSessionService._video_publication_media(SimpleNamespace(acf_fields=rows), session)
    assert [m["acf_field_name"] for m in media] == ["tour_video_url", "tour_video_poster"]


def _wp_video_service(tmp_path, found):
    class FakeWordPress:
        def find_media(self, url):
            return found

    repository = FileSessionRepository(tmp_path / "sessions")
    repository.create(ContentSession(
        session_id="s", user_id="c", post_type_key="listing", state="uploading",
        workbook_hash="h", language="de",
    ))
    return ContentSessionService(
        knowledge=SimpleNamespace(), repository=repository, wordpress=FakeWordPress(),
        wordpress_site_url="https://client.example",
    )


WP_VIDEO = {
    "id": 77, "mime_type": "video/mp4",
    "source_url": "https://client.example/wp-content/uploads/tour.mp4",
    "title": {"raw": "Tour"}, "caption": {"raw": "<p>Walk</p>"}, "description": {"raw": ""},
}


def test_wordpress_library_video_is_linked_not_copied(tmp_path) -> None:
    service = _wp_video_service(tmp_path, WP_VIDEO)
    session = service.attach_wordpress_video("s", url=WP_VIDEO["source_url"], expected_version=1)
    assert session.processed_videos[0]["wp_media_id"] == 77
    assert session.video_metadata[0] | {"media_id": ""} == {
        "media_id": "", "video_title": "Tour", "video_caption": "Walk",
        "video_description": "", "keep_existing_metadata": True,
    }
    rows = [
        SimpleNamespace(enabled=True, include_in_payload=True, post_type_key="listing",
                        field_role="direct_acf", acf_field_name=name)
        for name in ("tour_video_url", "tour_video_poster")
    ]
    media = ContentSessionService._video_publication_media(SimpleNamespace(acf_fields=rows), session)
    assert [(m["media_kind"], m.get("wp_media_id")) for m in media] == [("video", 77)]


def test_other_links_are_not_registered(tmp_path) -> None:
    service = _wp_video_service(tmp_path, WP_VIDEO)
    assert service.attach_wordpress_video("s", url="https://other.example/a.mp4", expected_version=1) is None
    image = _wp_video_service(tmp_path / "i", {**WP_VIDEO, "mime_type": "image/jpeg"})
    assert image.attach_wordpress_video("s", url=WP_VIDEO["source_url"], expected_version=1) is None


def test_video_can_be_featured_only_with_a_cover_and_demotes_pictures(tmp_path) -> None:
    from backend.app.errors import InvalidUploadError

    service = _wp_video_service(tmp_path, WP_VIDEO)
    session = service.attach_wordpress_video("s", url=WP_VIDEO["source_url"], expected_version=1)
    with pytest.raises(InvalidUploadError, match="cover"):
        service.set_featured_video("s", filename="tour.mp4", expected_version=session.version)

    row = {**session.processed_videos[0], "poster_path": "/s/tour-poster.jpg"}
    session = service.repository.save(
        session.model_copy(update={
            "processed_videos": [row],
            "image_metadata": [{"media_id": "i", "image_usage": "featured", "image_number": 1}],
        }),
        expected_version=session.version,
    )
    session = service.set_featured_video("s", filename="tour.mp4", expected_version=session.version)
    assert session.processed_videos[0]["is_featured"] is True
    assert session.image_metadata[0]["image_usage"] == "gallery"

    rows = [SimpleNamespace(enabled=True, include_in_payload=True, post_type_key="listing",
                            field_role="direct_acf", acf_field_name=n) for n in ("a_video_url", "a_video_poster")]
    media = ContentSessionService._video_publication_media(SimpleNamespace(acf_fields=rows), session)
    assert [m.get("image_usage") for m in media] == [None, "featured"]
