from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "app/v2/api/legacy_ui_adapter.js"
APP_MAIN = ROOT / "app_main.py"
README = ROOT / "README.md"


class LegacyUiAdapterTests(unittest.TestCase):
    def test_old_ui_loads_the_v2_adapter_only_in_v2_mode(self) -> None:
        source = APP_MAIN.read_text(encoding="utf-8")
        self.assertIn('window.FLAIRLAB_PIPELINE_VERSION !== "v2"', source)
        self.assertIn('adapter = \'<script src="/v2/legacy-ui-adapter.js"></script>\'', source)
        self.assertIn('html.rsplit("</body>", 1)', source)
        self.assertIn('if CONTENT_PIPELINE_VERSION == "v2":', source)
        self.assertIn("v2UseVisionOnUpload", source)
        self.assertIn("Metadata mit Vision nach dem ersten Entwurf generieren lassen", source)
        self.assertIn('id="startRecordingButton"', source)
        self.assertIn('title="Aufnahme starten"', source)
        self.assertIn('id="voiceInstructions"', source)
        self.assertNotIn("Empfohlene Struktur fuer Sprachnachrichten", source)
        self.assertIn("function formatElapsedDuration(ms)", source)
        self.assertIn("function appendElapsedDuration(text, startedAt)", source)
        self.assertIn("promptTraceModal", source)
        self.assertIn("function openPromptTrace(field)", source)
        self.assertIn("Prompt-Regeln für dieses Feld anzeigen", source)
        self.assertIn("Kontext kopieren", source)

    def test_readme_documents_new_post_type_setup(self) -> None:
        source = README.read_text(encoding="utf-8")
        self.assertIn("`post_type_key` is the beacon", source)
        self.assertIn("ACF_fields_schema", source)
        self.assertIn("post_blueprint", source)
        self.assertIn("agent_instructions", source)
        self.assertIn("seo_rules", source)
        self.assertIn("V2_MILESTONE_LOGS", source)

    def test_adapter_routes_core_old_ui_actions_to_v2(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        for endpoint in (
            "/api/content-sessions",
            "/inputs",
            "/uploads",
            "/analyze",
            "/answers",
            "/generate",
            "/approve",
            "/publish",
        ):
            self.assertIn(endpoint, source)
        for action in (
            "createSession =",
            "uploadFiles =",
            "transcribe =",
            "saveTranscript =",
            "generateDraft =",
            "saveDraft =",
            "createWordPressPost =",
        ):
            self.assertIn(action, source)
        self.assertIn("function formatV2ApiError(data)", source)

    def test_adapter_keeps_explicit_fact_confirmation(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn('panel = document.createElement("details")', source)
        self.assertIn("Fakten anzeigen / bearbeiten", source)
        self.assertIn('document.querySelector("#panelTranscript .panel-body")', source)
        self.assertIn("Fakten speichern & erneut analysieren", source)
        self.assertIn("clarification_questions", source)
        self.assertIn("v2FactsTableBody", source)
        self.assertIn("function factsFromTable()", source)
        self.assertIn("hasKnownFacts", source)
        self.assertIn("hasTranscript", source)
        self.assertIn("window.confirmV2Facts = confirmV2Facts;", source)

    def test_recorded_voice_and_image_metadata_use_v2_routes(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("uploadRecordedVoiceAndRetranscribe = async function", source)
        recorded = source.split(
            "uploadRecordedVoiceAndRetranscribe = async function", 1
        )[1].split(
            "transcribe = async function transcribe()", 1
        )[0]
        self.assertIn('await uploadV2File(voice, "audio");', recorded)
        self.assertNotIn("await transcribe();", recorded)
        self.assertNotIn("await saveDraft();", recorded)
        self.assertIn("Klicke „Sprache transkribieren“", recorded)
        self.assertIn("queuedRecordedVoiceFiles", source)
        self.assertIn("v2RecordedVoiceQueue.push", source)
        self.assertIn("clearQueuedRecordings", source)
        self.assertIn("baseRenderVoiceList", source)
        self.assertIn("...queuedRecordedVoiceFiles()", source)
        self.assertIn("baseRemoveLocalVoice", source)
        self.assertIn("startRecording = async function startRecording()", source)
        recorder = source.split(
            "startRecording = async function startRecording()", 1
        )[1].split(
            "transcribeDraftChatVoice = async function transcribeDraftChatVoice()", 1
        )[0]
        self.assertNotIn("uploadRecordedVoiceAndRetranscribe", recorder)
        self.assertIn("updateButtons();", recorder)
        self.assertNotIn("/app/sessions", recorded)
        self.assertIn("/draft-chat/transcribe", source)
        self.assertIn("/draft-chat", source)
        self.assertIn("await saveDraft();", source)
        self.assertIn("message,", source)
        self.assertIn("Entwurf wurde mit dem Agenten aktualisiert.", source)
        self.assertNotIn("Der V2-Agenten-Chat ist noch nicht", source)
        self.assertIn("/image-metadata", source)
        self.assertIn("Bildmetadaten gespeichert", source)
        self.assertIn("setFeaturedImage = async function setFeaturedImage", source)
        self.assertIn("/featured-image", source)
        self.assertIn("Titelbild gespeichert", source)
        self.assertIn("/images/optimize", source)
        self.assertIn("/images/restore-original", source)
        self.assertNotIn("Wiederherstellungsroute", source)
        self.assertNotIn("Bildbearbeitungsroute", source)
        self.assertNotIn('"imageOptimizePrompt"', source.split("document.querySelector(\"header p\")", 1)[1])

    def test_expected_fact_review_state_is_not_a_browser_error(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        generate_draft = source.split("generateDraft = async function generateDraft()", 1)[1]
        needs_input_branch = generate_draft.split('if (v2Session.state === "needs_input")', 1)[1].split(
            'if (v2Session.state !== "ready_to_generate")', 1
        )[0]
        self.assertIn("renderV2Clarifications(v2Session);", needs_input_branch)
        self.assertIn("status(", needs_input_branch)
        self.assertIn("return;", needs_input_branch)
        self.assertNotIn("throw new Error", needs_input_branch)

    def test_workbook_status_waits_for_api_key(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        workbook_loader = source.split(
            "loadKnowledgeStatus = async function loadKnowledgeStatus()", 1
        )[1].split(
            "uploadKnowledgeWorkbook = async function uploadKnowledgeWorkbook()", 1
        )[0]
        self.assertLess(
            workbook_loader.index("if (!key())"),
            workbook_loader.index("v2Api(`/api/content-sessions/_workbook${suffix}`"),
        )

    def test_workbook_status_feeds_old_ui_acf_field_map(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        workbook_loader = source.split(
            "loadKnowledgeStatus = async function loadKnowledgeStatus()", 1
        )[1].split(
            "uploadKnowledgeWorkbook = async function uploadKnowledgeWorkbook()", 1
        )[0]
        self.assertIn("flairlab_knowledge_status", workbook_loader)
        self.assertIn("JSON.stringify(version)", workbook_loader)
        self.assertIn("version.storage_mode", workbook_loader)
        self.assertIn("version.gcs_uri", workbook_loader)
        self.assertIn("renderPostTypeOptions(version)", workbook_loader)

    def test_post_type_selection_is_workbook_driven(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        create_session = source.split("createSession = async function createSession", 1)[1].split(
            "restoreSession = async function restoreSession()", 1
        )[0]
        self.assertIn("selectedPostTypeKey()", create_session)
        self.assertNotIn('selected !== "event"', create_session)
        self.assertNotIn("unterstützt derzeit den Beitragstyp Event", create_session)
        self.assertNotIn('option.disabled = option.textContent.trim().toLowerCase() !== "event"', source)
        self.assertIn("function renderPostTypeOptions(version)", source)
        self.assertIn("function renderVoiceInstructionsForSelectedPostType()", source)
        self.assertIn("option.dataset.voiceInstructions = postType.voice_instructions || \"\";", source)
        self.assertIn("target.innerHTML = html.trim()", source)

    def test_workbook_upload_remains_available_in_v2_adapter(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        uploader = source.split(
            "uploadKnowledgeWorkbook = async function uploadKnowledgeWorkbook()", 1
        )[1].split(
            "autoUploadSelectedImages = async function autoUploadSelectedImages()", 1
        )[0]
        self.assertIn('api("/app/knowledge/workbook"', uploader)
        self.assertIn('v2Api("/api/content-sessions/_workbook/reload"', uploader)
        self.assertIn('document.getElementById("uploadKnowledgeButton").disabled = false', source)
        self.assertNotIn("während eines Tests nicht ersetzt", uploader)

    def test_wordpress_buttons_create_new_or_update_linked_post(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        app = APP_MAIN.read_text(encoding="utf-8")
        self.assertIn("Neuen WordPress-Beitrag erstellen", app)
        self.assertIn("Verknüpften Beitrag aktualisieren", app)
        self.assertIn("async function publishV2ToWordPress", adapter)
        self.assertIn("force_create_new: forceCreateNew", adapter)
        self.assertIn("target_post_id: targetPostId", adapter)
        self.assertIn("shared_fields: edits.shared", adapter)
        self.assertIn("acf_source_fields: edits.acf", adapter)
        create_post = adapter.split("createWordPressPost = async function createWordPressPost()", 1)[1].split(
            "updateExistingWordPressPost = async function updateExistingWordPressPost()", 1
        )[0]
        update_post = adapter.split("updateExistingWordPressPost = async function updateExistingWordPressPost()", 1)[1].split(
            "uploadWordPressMediaLibrary = async function uploadWordPressMediaLibrary()", 1
        )[0]
        self.assertIn("forceCreateNew: true", create_post)
        self.assertIn("targetPostId: Number(post.post_id)", update_post)
        self.assertNotIn("window.open(post.edit_url", update_post)

    def test_manual_draft_save_is_available_after_publication(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        save_draft = source.split("saveDraft = async function saveDraft()", 1)[1].split(
            "sendDraftChat = async function sendDraftChat()", 1
        )[0]
        self.assertIn("!hasV2DraftReadyForWordPress()", save_draft)
        self.assertIn("/draft-fields", save_draft)
        self.assertIn('method: "PUT"', save_draft)
        self.assertNotIn('v2Session.state !== "needs_review"', save_draft)
        update_buttons = source.split(
            "updateButtons = function updateButtons()", 1
        )[1].split(
            'document.querySelector("header p").textContent', 1
        )[0]
        self.assertIn('document.getElementById("saveDraftButton").disabled = !hasDraft;', update_buttons)

    def test_transcribe_recovers_from_stale_session_version(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        transcribe = source.split("transcribe = async function transcribe()", 1)[1].split(
            "saveTranscript = async function saveTranscript()", 1
        )[0]
        self.assertLess(
            transcribe.index("await refreshV2Session();"),
            transcribe.index("/analyze"),
        )
        self.assertIn("if (error.status !== 409) throw error;", transcribe)
        self.assertIn("await refreshV2Session();", transcribe)
        self.assertIn('v2Session.state === "needs_input"', transcribe)

    def test_image_upload_after_review_triggers_v2_regeneration(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("v2ImageUploadInFlight", source)
        self.assertIn("appendPendingV2ImageCards", source)
        self.assertIn("markLocalImageCardsProcessing", source)
        self.assertIn("v2UseVisionOnUpload", source)
        self.assertIn("checkbox.checked", source)
        self.assertNotIn("checkbox.unchecked", source)
        self.assertNotIn("unchecked>", APP_MAIN.read_text(encoding="utf-8"))
        self.assertIn('form.append("use_vision", "0")', source)
        self.assertIn("use_vision_for_image_metadata: useVisionOnUpload()", source)
        upload_v2_file = source.split(
            "async function uploadV2File(file, kind)", 1
        )[1].split(
            "function v2ImageUrl", 1
        )[0]
        self.assertIn("Number.isInteger(Number(v2Session.version))", upload_v2_file)
        self.assertIn("await loadActiveV2Session();", upload_v2_file)
        self.assertIn('form.append("expected_version", String(Number(v2Session.version)))', upload_v2_file)
        self.assertIn("v2LocalImagePreviewUrls", source)
        self.assertIn("rememberLocalImagePreview(file)", source)
        self.assertIn("imageUploadActionLabel", source)
        self.assertIn("Wird optimiert", source)
        self.assertIn("status: imageProcessingStatus", source)
        self.assertIn("hasOriginal: true", source)
        self.assertIn("isProcessed: !!processed", source)
        self.assertIn("metadataByMedia", source)
        self.assertIn("wp_metadata", source)
        self.assertIn("metadata.image_description || metadata.description || metadata.image_description_wp", source)
        self.assertIn("ai_usage: session.ai_usage || {}", source)
        self.assertIn("schedulePillowStatusPoll = function schedulePillowStatusPoll()", source)
        self.assertIn("/api/content-sessions/${v2Session.session_id}", source)
        auto_upload = source.split(
            "autoUploadSelectedImages = async function autoUploadSelectedImages()", 1
        )[1].split(
            "uploadPendingMediaFiles = async function uploadPendingMediaFiles()", 1
        )[0]
        self.assertIn("v2UploadQueue", auto_upload)
        self.assertIn("await uploadPendingMediaFiles();", auto_upload)
        self.assertIn("imageUploadActionLabel()", auto_upload)
        self.assertNotIn(
            "await renderV2(v2Session",
            auto_upload.split("await uploadPendingMediaFiles();", 1)[0],
        )

        uploader = source.split(
            "uploadPendingMediaFiles = async function uploadPendingMediaFiles()", 1
        )[1].split(
            "uploadFiles = async function uploadFiles()", 1
        )[0]
        self.assertIn('v2Session.state === "needs_review"', uploader)
        self.assertIn("await saveDraft();", uploader)
        self.assertLess(
            uploader.index("await renderV2(v2Session"),
            uploader.index("clearUploadInputs({images: true, videos: true})"),
        )

        upload_files = source.split(
            "uploadFiles = async function uploadFiles()", 1
        )[1].split(
            "transcribe = async function transcribe()", 1
        )[0]
        self.assertIn('v2Session.state === "needs_review"', upload_files)
        self.assertIn("await saveDraft();", upload_files)
        self.assertNotIn("if (voices.length) await transcribe();", upload_files)
        self.assertIn("Klicke „Sprache transkribieren“", upload_files)

    def test_new_v2_session_clears_local_media_but_upload_creation_preserves_it(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("function clearV2LocalMediaUi()", source)
        create_session = source.split(
            "createSession = async function createSession(options = {})", 1
        )[1].split(
            "restoreSession = async function restoreSession()", 1
        )[0]
        self.assertIn("clearV2LocalMediaUi();", create_session)
        self.assertIn("!options.preservePendingUploads", create_session)
        self.assertIn("v2LocalImagePreviewUrls.clear();", source)
        self.assertIn('document.getElementById("imagePreviews")', source)
        self.assertIn("createSession({preservePendingUploads: true})", source)

        transcribe = source.split(
            "transcribe = async function transcribe()", 1
        )[1].split(
            "saveTranscript = async function saveTranscript()", 1
        )[0]
        self.assertIn('await uploadV2File(voice, "audio");', transcribe)
        self.assertIn("clearQueuedRecordings();", transcribe)
        self.assertIn("hasPendingVoice", source)

    def test_archive_and_long_running_actions_use_v2_endpoints(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("/api/content-sessions/recent", source)
        self.assertIn("/api/content-sessions/delete", source)
        self.assertIn("renderRecentSessions(data)", source)
        self.assertIn("openSessionLogsById = async function", source)
        self.assertIn("loadSessionById = async function", source)
        self.assertIn("Session geladen.", source)
        self.assertIn("generate-job", source)
        self.assertIn("publish-job", source)
        self.assertIn("waitForV2Job", source)
        self.assertIn("formatElapsedDuration(Date.now() - startedAt)", source)
        self.assertIn("navigator.wakeLock.request", source)

    def test_publish_button_accepts_already_approved_v2_draft(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("function hasV2DraftReadyForWordPress()", source)
        self.assertIn('"ready_to_publish"', source)
        publish_helper = source.split(
            "async function publishV2ToWordPress", 1
        )[1].split(
            "updateExistingWordPressPost = async function updateExistingWordPressPost()", 1
        )[0]
        self.assertIn("if (!v2Session) await loadActiveV2Session();", publish_helper)
        self.assertIn("const edits = editedFieldMaps();", publish_helper)
        self.assertIn('v2Session.state === "needs_review"', publish_helper)
        self.assertIn("await saveDraft();", publish_helper)
        self.assertIn("await approveV2SessionIfNeeded();", publish_helper)
        self.assertIn("publish-job", publish_helper)
        self.assertIn("target_post_id: targetPostId", publish_helper)
        self.assertIn("force_create_new: forceCreateNew", publish_helper)
        update_buttons = source.split(
            "updateButtons = function updateButtons()", 1
        )[1].split(
            'document.querySelector("header p").textContent', 1
        )[0]
        self.assertIn("hasV2DraftReadyForWordPress()", update_buttons)
        self.assertIn("createPostButton", update_buttons)


if __name__ == "__main__":
    unittest.main()
