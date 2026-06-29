from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.providers.step_02_openai import OpenAILanguageModelProvider
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService
from config import OPENAI_API_KEY, V2_LANGUAGE_MODEL

SYNTHETIC_EVENT = """
FLAIRLAB betreut am 24.06.2026 ein Firmen-Sommerfest für 120 Gäste bei
Beispielkunde GmbH in der Musterlocation Berlin. Der Kundentyp ist company.
Gebucht ist Cocktailcatering mit einer mobilen Cocktailbar. Das Event findet
in Berlin statt. Bitte verwenden Sie ausschließlich diese ausdrücklich
bestätigten Testfakten; alle Namen sind synthetische Testdaten.
""".strip()

CONFIRMED_FACTS = {
    "event_year": 2026,
    "event_month": "Juni",
    "event_date": "24.06.2026",
    "city": "Berlin",
    "venue": "Musterlocation Berlin",
    "event_type": "Firmen-Sommerfest",
    "client_type": "company",
    "client_name": "Beispielkunde GmbH",
    "guest_count": 120,
    "service_type": "Cocktailcatering",
    "bar_type": "mobile Cocktailbar",
}

FORBIDDEN_OPTIONAL_FIELDS = {
    "event_challenge",
    "event_solution",
    "fact_bartender",
    "fact_challenge",
    "fact_focus",
    "fact_speciality",
}


def generation_invariant_errors(report: dict) -> list[str]:
    errors: list[str] = []
    payload = report.get("payload") or {}
    acf = payload.get("acf") or {}
    generated_fields = set(report.get("acf_source_field_keys") or [])
    leaked = sorted(FORBIDDEN_OPTIONAL_FIELDS.intersection(generated_fields))
    if leaked:
        errors.append(f"Unconfirmed optional fields were generated: {', '.join(leaked)}")

    facts_html = str(acf.get("fakten") or "")
    if CONFIRMED_FACTS["event_date"] not in facts_html:
        errors.append("The confirmed event date is missing from the facts HTML.")
    if "&lt;li" in facts_html or "\\u003cli" in facts_html:
        errors.append("The facts HTML contains escaped list markup.")
    for forbidden_label in ("Barkeeper:", "Fokus:", "Herausforderung:"):
        if forbidden_label in facts_html:
            errors.append(
                f"The facts HTML contains an unconfirmed optional label: {forbidden_label}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a live OpenAI V2 generation smoke test without WordPress publication."
    )
    parser.add_argument(
        "--workbook",
        type=Path,
        default=Path("data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/audits/v2_live_generation_smoke.json"),
    )
    args = parser.parse_args()
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is not configured.")
    with tempfile.TemporaryDirectory() as temporary:
        knowledge = KnowledgeBaseService(args.workbook)
        service = ContentSessionService(
            knowledge=knowledge,
            repository=FileSessionRepository(temporary),
            language_model=OpenAILanguageModelProvider(
                api_key=OPENAI_API_KEY,
                model=V2_LANGUAGE_MODEL,
            ),
        )
        session = service.create(user_id="synthetic-smoke", post_type_key="event")
        session = service.add_inputs(
            session.session_id,
            manual_text=SYNTHETIC_EVENT,
            confirmed_facts=CONFIRMED_FACTS,
            expected_version=session.version,
        )
        session = service.analyze(
            session.session_id,
            expected_version=session.version,
        )
        if session.state != "ready_to_generate":
            report = {
                "passed": False,
                "stage": "analysis",
                "state": session.state,
                "questions": session.clarification_questions,
                "confirmed_fact_keys": sorted(session.confirmed_facts),
            }
        else:
            session = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            report = {
                "passed": session.state == "needs_review",
                "stage": "generation",
                "state": session.state,
                "workbook_hash": session.workbook_hash,
                "model": V2_LANGUAGE_MODEL,
                "confirmed_fact_keys": sorted(session.confirmed_facts),
                "shared_field_keys": sorted(session.shared_fields),
                "acf_source_field_keys": sorted(session.acf_source_fields),
                "selected_link_ids": [
                    row.get("link_id") for row in session.selected_links
                ],
                "payload": session.wordpress_payload,
                "validation_report": session.validation_report,
                "published": False,
            }
            invariant_errors = generation_invariant_errors(report)
            report["invariant_errors"] = invariant_errors
            report["passed"] = report["passed"] and not invariant_errors
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
