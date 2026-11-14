"""SEO check with a dental-clinic fixture and arbitrary field names (no client names)."""
from types import SimpleNamespace

from backend.app.models.step_01_session import ContentSession
from backend.app.validation.step_02_seo import SeoChecker, occurrences, plain_text

FOCUS = "Zahnersatz für Senioren"


def rule(key, action, value):
    return SimpleNamespace(enabled=True, post_type_key="*", target_type="field", target_key=key,
                           action_type=action, value=value)


def shared(key, dest_type, dest_key):
    return SimpleNamespace(enabled=True, field_key=key, destination_type=dest_type, destination_key=dest_key)


SNAPSHOT = SimpleNamespace(
    shared_fields=(
        shared("page_title", "wordpress", "title"), shared("url_part", "wordpress", "slug"),
        shared("kw", "yoast", "yoast_wpseo_focuskw"), shared("search_title", "yoast", "yoast_wpseo_title"),
        shared("search_blurb", "yoast", "yoast_wpseo_metadesc"),
    ),
    acf_fields=tuple(SimpleNamespace(post_type_key="dentistry_case", field_key=k)
                     for k in ("lead_h", "lead_text", "long_text")),
    seo_rules=(
        rule("lead_h", "check_role", "heading"), rule("lead_text", "check_role", "introduction"),
        rule("long_text", "check_role", "body"), rule("search_blurb", "check_length", "40;120"),
        rule("not_in_draft", "check_role", "heading"),  # fields missing from the draft are ignored
    ),
)

GOOD_SHARED = {
    "page_title": "Zahnersatz für Senioren in Köln", "url_part": "zahnersatz-fuer-senioren-koeln",
    "kw": FOCUS, "search_title": "Zahnersatz für Senioren | Praxis Lindenhof",
    "search_blurb": "Zahnersatz für Senioren: festsitzend oder herausnehmbar, mit Beratung und festem Kostenplan.",
}
GOOD_ACF = {
    "lead_h": "<h1>Mit {{Zahnersatz}} für Senioren zurück zum Lachen</h1>",
    "lead_text": "<p>Zahnersatz für Senioren braucht Zeit. Wir erklären jeden Schritt.</p>",
    "long_text": "<p>" + "Wir beraten ruhig und planen gemeinsam den Ablauf. " * 4 + "</p>",
}


def session(shared_fields=None, acf=None, **extra):
    return ContentSession(
        session_id="s", user_id="u", post_type_key="dentistry_case", state="needs_review",
        workbook_hash="h", language="de-DE", shared_fields=dict(GOOD_SHARED, **(shared_fields or {})),
        acf_source_fields=dict(GOOD_ACF, **(acf or {})), **extra,
    )


def run(**kwargs):
    findings = SeoChecker().check(session(**kwargs), SNAPSHOT)
    return {f.check_id: f for f in findings}


def test_good_draft_has_no_failures_and_ignores_missing_rule_fields():
    findings = run()
    assert [f.check_id for f in findings.values() if f.status == "fail"] == []
    assert "in_heading:not_in_draft" not in findings
    assert findings["in_introduction:lead_text"].status == "pass"
    assert findings["in_heading:lead_h"].status == "pass"  # {{ }} markers and HTML are ignored


def test_missing_keyphrase_in_introduction_points_at_the_acf_field():
    findings = run(acf={"lead_text": "<p>Wir erklären jeden Schritt in Ruhe. Fragen sind jederzeit willkommen. Zahnersatz für Senioren folgt später.</p>"})
    assert findings["in_introduction:lead_text"].status == "fail"
    assert findings["in_introduction:lead_text"].field_ids == ["acf:lead_text"]


def test_slug_matches_transliterated_umlauts_and_ignores_function_words():
    assert run()["in_slug"].status == "pass"  # "für" is written "fuer" in the slug
    assert run(shared_fields={"url_part": "zahnersatz-koeln"})["in_slug"].status == "fail"


def test_published_post_keeps_its_slug_out_of_the_revision_fields():
    findings = run(shared_fields={"url_part": "praxis-news"}, wordpress_result={"post_id": 7})
    assert findings["in_slug"].status == "fail" and findings["in_slug"].field_ids == []


def test_length_rule_and_title_checks():
    findings = run(shared_fields={"search_blurb": "Zahnersatz für Senioren."})
    assert findings["length:search_blurb"].status == "fail"
    findings = run(shared_fields={"search_title": "Praxis Lindenhof Köln"})
    assert findings["in_seo_title"].status == "fail"


def test_other_selected_keywords_must_appear_somewhere():
    findings = run(selected_keywords=[FOCUS, "Kostenplan", "Implantat Köln"])
    assert findings["other_keywords"].status == "fail"
    assert "Implantat Köln" in findings["other_keywords"].message and "Kostenplan" not in findings["other_keywords"].message


def test_focus_keyphrase_used_by_another_page_but_not_by_the_post_itself():
    taken = {"zahnersatz für senioren": ["https://clinic.example/old/"]}
    assert run(site_focus_keyphrases=taken)["focus_unique"].status == "fail"
    own = run(site_focus_keyphrases=taken, wordpress_result={"view_url": "https://clinic.example/old/"})
    assert own["focus_unique"].status == "pass"
    assert run()["focus_unique"].status == "skipped"  # no site scan available


def test_density_only_for_enough_text_and_flags_stuffing():
    assert "density" not in run()
    stuffed = "Zahnersatz für Senioren. " * 40
    assert run(acf={"long_text": stuffed})["density"].status == "fail"


def test_without_a_focus_keyphrase_only_that_finding_is_returned():
    findings = SeoChecker().check(session(shared_fields={"kw": ""}), SNAPSHOT)
    assert [f.check_id for f in findings] == ["focus_keyphrase"] and findings[0].status == "fail"


def test_a_workbook_without_check_rows_still_checks_the_standard_fields():
    bare = SimpleNamespace(shared_fields=SNAPSHOT.shared_fields, acf_fields=SNAPSHOT.acf_fields, seo_rules=())
    findings = {f.check_id: f for f in SeoChecker().check(session(), bare)}
    assert findings["in_post_title"].status == "pass"
    assert not any(key.startswith(("in_introduction", "in_heading", "length")) for key in findings)
    assert findings["role_missing:introduction"].status == "skipped"
    assert findings["role_missing:heading"].status == "skipped"
    assert "role_missing:introduction" not in run()  # configured post types get no such note


def test_revision_instruction_lists_only_failed_fixable_checks():
    findings = SeoChecker().check(session(shared_fields={"search_title": "Praxis Lindenhof"}), SNAPSHOT)
    text = SeoChecker.revision_instruction(session(), findings)
    assert "SEO title" in text and "meta description" not in text


def test_phrase_matching_allows_endings_and_compounds_but_not_substrings():
    assert occurrences("Mehrere Smoothies zum Mixen", "Smoothie") == 1
    assert occurrences("Das Kaffeecatering war gut", "Kaffee-Catering") == 1
    assert occurrences("Der Barkeeper kam", "Bar") == 0
    assert plain_text("<p>Hallo [gallery id=3] {{Welt}}</p>") == "Hallo Welt"
