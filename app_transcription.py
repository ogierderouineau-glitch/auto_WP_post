from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY


DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"


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
