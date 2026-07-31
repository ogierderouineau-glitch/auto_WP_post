import tempfile

from backend.app.models.step_01_session import ContentSession
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService


def test_generation_settings_merge_into_latest_session_version() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        repository = FileSessionRepository(temporary)
        session = repository.create(ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="created",
            workbook_hash="hash",
            language="de",
        ))
        latest = repository.save(
            session.model_copy(update={"operation_log": []}),
            expected_version=session.version,
        )
        service = ContentSessionService(knowledge=object(), repository=repository)

        updated = service.update_generation_settings(
            session.session_id,
            language_model="gpt-5.6",
            reasoning_effort="low",
            generation_mode="single",
            expected_version=session.version,
        )

        assert updated.version == latest.version + 1
        assert updated.language_model == "gpt-5.6"
        assert updated.reasoning_effort == "low"
        assert updated.generation_mode == "single"
