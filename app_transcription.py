from pathlib import Path
import re

from openai import OpenAI

from config import OPENAI_API_KEY


DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"

_DOMAIN_KEYWORDS = {
    "event",
    "hochzeit",
    "jubilaeum",
    "jubiläum",
    "messe",
    "catering",
    "cocktail",
    "cocktails",
    "bar",
    "gaeste",
    "gäste",
    "kunden",
    "promotion",
    "service",
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\wÄÖÜäöüß-]+\b", value or ""))


def _is_low_signal_sentence(sentence: str) -> bool:
    text = _normalize_text(sentence)
    if not text:
        return True

    lowered = text.lower()
    words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", lowered)
    if not words:
        return True

    if len(words) <= 2 and all(word in {"ja", "nein", "okay", "ok", "hm", "hmm", "ah", "äh", "also"} for word in words):
        return True

    has_domain_signal = any(word in _DOMAIN_KEYWORDS for word in words)
    has_intro = any(phrase in lowered for phrase in ("hallo", "hi", "hier ist", "ich bin", "ich hei", "guten tag", "moin"))
    has_recording_meta = any(
        phrase in lowered
        for phrase in (
            "test",
            "mikrofon",
            "aufnahme",
            "probe",
            "h\u00f6rst du mich",
            "hoerst du mich",
            "kannst du mich h\u00f6ren",
            "kannst du mich hoeren",
        )
    )

    if has_recording_meta and not has_domain_signal and len(words) <= 20:
        return True
    if has_intro and not has_domain_signal and len(words) <= 18:
        return True
    return False


def sanitize_transcript_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    chunks = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", raw) if part.strip()]
    cleaned: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        normalized = _normalize_text(chunk)
        fingerprint = re.sub(r"[^a-z0-9äöüß]+", "", normalized.lower())
        if not fingerprint or fingerprint in seen:
            continue
        if _is_low_signal_sentence(normalized):
            continue
        cleaned.append(normalized)
        seen.add(fingerprint)

    merged = _normalize_text(" ".join(cleaned))
    # Keep original transcript if rules remove too much content.
    if _word_count(merged) < 8 and _word_count(raw) >= 8:
        return _normalize_text(raw)
    return merged or _normalize_text(raw)


def transcribe_audio_file(
    audio_path: str | Path,
    model: str = DEFAULT_TRANSCRIPTION_MODEL,
) -> str:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    with path.open("rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )

    return transcription.text
