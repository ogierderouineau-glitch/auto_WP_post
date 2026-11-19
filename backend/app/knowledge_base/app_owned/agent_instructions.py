from __future__ import annotations

from backend.app.knowledge_base.step_01_models import AgentInstruction


# Import app-level instructions here from a temporary `agent_instructions_app` sheet export.
# Keep this as the source of truth, then remove that workbook tab.
APP_OWNED_AGENT_INSTRUCTIONS: tuple[AgentInstruction, ...] = (
    AgentInstruction(
        sheet_row=1,
        instruction_id="core_002",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="analysis",
        applies_to="facts",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="Nur ausdrucklich genannte oder eindeutig bestatigte Fakten verwenden. Fehlende Fakten niemals erfinden.",
        expected_behavior="Unbekannte Werte bleiben leer oder missing und fuhren bei Bedarf zu Ruckfragen.",
        conflict_policy="confirmed_user_input_wins",
        source_reference="client_guidelines",
        notes_de="Gilt fur Faktenextraktion und Generierung.",
    ),
    AgentInstruction(
        sheet_row=2,
        instruction_id="core_003",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="all",
        applies_to="schema",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="Nur die im bereitgestellten Schema enthaltenen Feldschlussel zuruckgeben.",
        expected_behavior="Keine zusatzlichen WordPress-, Yoast- oder ACF-Felder erzeugen.",
        conflict_policy="schema_wins",
        source_reference="client_guidelines",
        notes_de="Payload-Mapping erfolgt spater in Python.",
    ),
    AgentInstruction(
        sheet_row=3,
        instruction_id="core_004",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="context_loading",
        applies_to="post_type_isolation",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="Nur Regeln, Beispiele und Felder des ausgewahlten Post-Typs verwenden.",
        expected_behavior="Keine Beispiele oder Besonderheiten anderer Post-Typen vermischen.",
        conflict_policy="specific_over_global",
        source_reference="client_guidelines",
        notes_de="Globale Regeln gelten zusatzlich.",
    ),
    AgentInstruction(
        sheet_row=4,
        instruction_id="core_005",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="all",
        applies_to="user_corrections",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="Bestatigte Nutzerkorrekturen haben Vorrang vor Transkript, Bildanalyse und Beispielen.",
        expected_behavior="Spatere bestatigte Werte uberschreiben fruhere Extraktionen.",
        conflict_policy="confirmed_user_input_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=5,
        instruction_id="core_006",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="clarification",
        applies_to="questions",
        owner="language_model",
        priority="high",
        condition="missing_required_or_contradictory",
        instruction_de="Nur notwendige Ruckfragen stellen und zusammengehorige Fragen bundeln.",
        expected_behavior="Kurze priorisierte Ruckfragen statt vieler einzelner Nachrichten.",
        conflict_policy="higher_priority_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=6,
        instruction_id="core_007",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="generation",
        applies_to="partial_task",
        owner="language_model",
        priority="high",
        condition="user_requests_partial_task",
        instruction_de="Bei einer ausdrucklich verlangten Teilaufgabe nur die angeforderten Felder erzeugen.",
        expected_behavior="Keine ungefragte Vollgenerierung.",
        conflict_policy="user_request_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=7,
        instruction_id="core_008",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="generation",
        applies_to="examples",
        owner="language_model",
        priority="medium",
        condition="approved_examples_available",
        instruction_de="Freigegebene Beispiele als Stilreferenz verwenden, aber keine Formulierungen oder Fakten kopieren.",
        expected_behavior="Ton und Struktur orientieren sich an relevanten Beispielen.",
        conflict_policy="facts_override_examples",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=8,
        instruction_id="core_010",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="internal_links",
        applies_to="urls",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de=(
            "Related links are mandatory.\n\n"
            "For every related-link candidate provided, you must insert it naturally into the article body or CTA text as a linked phrase. Do not skip candidates unless there is truly no grammatical way to use them.\n\n"
            "Rules:\n"
            "- Use every candidate exactly once when possible.\n"
            "- The anchor text should match or closely resemble the candidate phrase.\n"
            "- Prefer natural in-sentence placement over a separate link list.\n"
            "- If a candidate does not fit the main article body, place it in the CTA, closing paragraph, or a short recommendation sentence.\n"
            "- Do not use an ACF field for related links.\n"
            "- Do not output unused related-link candidates silently.\n"
            "- If a candidate cannot be used naturally, report it under Unused related links with a short reason.\n\n"
            "When internal link candidates are available, write their anchor phrases naturally into article body, FAQ, or CTA text so they can be linked in context. Never in titles. Prefer CTA text for commercial/service anchors that do not fit the story body.\n"
            "Do not create a separate related-links list as the primary solution. Don't invent URLs, only use selected candidates.\n\n"
            "Examples:\n"
            "Candidate: mobile Cocktailbar\n"
            "Good: Wer eine mobile Cocktailbar fuer Events sucht, findet hier passende Konzepte...\n"
            "Bad: Adding the link only in metadata or ignoring it.\n\n"
            "Candidate: Showbarkeeper Berlin\n"
            "Good CTA: Jetzt Showbarkeeper in Berlin fuer Ihr Event anfragen."
        ),
        expected_behavior="Wenn kein Link passt, keinen Link vorschlagen.",
        conflict_policy="database_only",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=9,
        instruction_id="core_011",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="image_metadata",
        applies_to="visible_content",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="Bildmetadaten nur aus sichtbarem Bildinhalt und bestatigten Fakten erzeugen.",
        expected_behavior="Keine Personen, Marken, Orte oder Drinks ohne Bestatigung identifizieren.",
        conflict_policy="image_analysis_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=10,
        instruction_id="core_012",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="generation",
        applies_to="content_quality",
        owner="language_model",
        priority="medium",
        condition="always",
        instruction_de=(
            "post_title and hero_h1 must not repeat the same wording.\n"
            "post_title should be SEO/search-result oriented and concise.\n"
            "hero_h1 should be page-hero oriented, natural, and visually engaging.\n"
            "If both fields mention the same event/service/location, vary the sentence structure and avoid copying more than 3 consecutive meaningful words."
        ),
        expected_behavior="Keine Wiederholungen im Beitrag",
        conflict_policy="higher_priority_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=11,
        instruction_id="analysis_003",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="clarification",
        applies_to="required_facts",
        owner="language_model",
        priority="high",
        condition="missing_required_for_analysis_or_required_output_source",
        instruction_de="Wenn ein Feld mit required_for_analysis=TRUE fehlt oder ein Pflicht-Ausgabefeld ohne ausreichende bestatigte Quellfakten nicht sicher erzeugt werden kann, eine gebundelte konkrete Ruckfrage stellen.",
        expected_behavior="Optionale Fakten werden nicht erzwungen. Pflichtfakten werden vor der Inhaltsgenerierung geklart; fehlende Werte werden niemals erfunden.",
        conflict_policy="schema_wins",
        source_reference="workbook_contract",
        notes_de="Python bestimmt anhand der Schemata, welche Fakten fehlen; das Modell formuliert nur die Ruckfragen.",
    ),
    AgentInstruction(
        sheet_row=12,
        instruction_id="analysis_004",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="clarification",
        applies_to="source_fact_keys",
        owner="language_model",
        priority="high",
        condition="required_output_dependency_missing",
        instruction_de="Fur Pflicht-Ausgabefelder ausschlieslich die von Python bereitgestellten source_fact_keys als Faktenabhangigkeiten verwenden. Fehlende erforderliche Quellfakten als gebundelte Ruckfragen formulieren.",
        expected_behavior="Keine Abhangigkeiten aus Feldnamen, Beispielen oder guidance_de ableiten. Optionale Ausgabefelder ohne Quellfakten uberspringen.",
        conflict_policy="schema_wins",
        source_reference="workbook_contract",
        notes_de="Python ermittelt die fehlenden Abhangigkeiten deterministisch; das Modell formuliert nur verstandliche Ruckfragen.",
    ),
    AgentInstruction(
        sheet_row=13,
        instruction_id="analysis_005",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="ai_image_edit",
        applies_to="visible_content",
        owner="language_model",
        priority="high",
        condition="ai_edit_requested",
        instruction_de="Alle Gesichter und Umgebungsdetails wie vorgegeben beibehalten, sofern nicht ausdrucklich anders angegeben",
        expected_behavior="Die Authentizitat der Bilder wird nicht beeintrachtigt; es sind lediglich gezielte Anderungen zulassig.",
        conflict_policy="higher_priority_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
    AgentInstruction(
        sheet_row=14,
        instruction_id="core_013",
        enabled=True,
        scope="global",
        post_type_key="*",
        workflow_stage="generation",
        applies_to="urls",
        owner="language_model",
        priority="high",
        condition="always",
        instruction_de="During draft revision, always keep the existing links in the revised version",
        expected_behavior="Links previously inserted are not wiped out after revision",
        conflict_policy="higher_priority_wins",
        source_reference="client_guidelines",
        notes_de=None,
    ),
)


_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_OWNER_RANK = {"application": 0, "language_model": 1, "vision_model": 2, "speech_to_text": 3, "user": 4}


def merge_agent_instructions(
    app_rules: tuple[AgentInstruction, ...],
    client_rules: tuple[AgentInstruction, ...],
) -> tuple[AgentInstruction, ...]:
    """Merge app and client instructions with deterministic conflict handling.

    Rule policy:
    1. Client can extend app rules by adding new instruction IDs.
    2. When instruction_id conflicts, higher priority wins.
    3. If priority ties, owner rank decides.
    4. If still tied, app rule wins (base safety default).
    """

    selected: dict[str, AgentInstruction] = {
        row.instruction_id: row for row in app_rules
    }
    for candidate in client_rules:
        existing = selected.get(candidate.instruction_id)
        if existing is None or _is_preferred(candidate, existing):
            selected[candidate.instruction_id] = candidate

    merged = list(selected.values())
    merged.sort(key=_sort_key)
    return tuple(merged)


def _is_preferred(candidate: AgentInstruction, existing: AgentInstruction) -> bool:
    candidate_rank = (_priority(candidate.priority), _owner(candidate.owner))
    existing_rank = (_priority(existing.priority), _owner(existing.owner))
    return candidate_rank < existing_rank


def _sort_key(row: AgentInstruction) -> tuple[int, int, str]:
    return (_priority(row.priority), _owner(row.owner), row.instruction_id)


def _priority(value: str) -> int:
    return _PRIORITY_RANK.get(str(value or "").strip().lower(), 99)


def _owner(value: str) -> int:
    return _OWNER_RANK.get(str(value or "").strip().lower(), 99)