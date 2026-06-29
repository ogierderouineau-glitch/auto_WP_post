from __future__ import annotations

# Workbook step keys resolve only to reviewed application-service method names.
# No function name is read or executed dynamically from workbook text.
WORKFLOW_HANDLER_METHODS: dict[str, str] = {
    "create_session": "create",
    "upload_photos": "attach_upload",
    "upload_voice_messages": "attach_upload",
    "transcribe_voice": "analyze",
    "extract_facts": "analyze",
    "analyze_photos": "analyze",
    "clarify_missing": "analyze",
    "save_user_corrections": "answer",
    "build_context": "generate",
    "generate_shared_fields": "generate",
    "generate_acf_fields": "generate",
    "select_internal_links": "generate",
    "build_related_links_html": "generate",
    "process_images": "generate",
    "generate_image_metadata": "generate",
    "build_payload": "generate",
    "validate_draft": "generate",
    "review_draft": "approve",
    "publish_wordpress": "publish",
}
