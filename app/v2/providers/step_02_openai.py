from __future__ import annotations

import base64
import mimetypes
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from openai import OpenAI

from app.v2.providers.step_01_interfaces import (
    ImageEditingProvider,
    LanguageModelProvider,
    SpeechToTextProvider,
    VisionProvider,
)

MODEL_PRICES_PER_MILLION_TOKENS_USD: dict[str, tuple[float, float]] = {
    "gpt-5.5": (1.25, 10.0),
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.4),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}


class OpenAILanguageModelProvider(LanguageModelProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.last_usage: dict[str, Any] | None = None

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        response = self.client.responses.parse(
            model=self.model,
            input=context["messages"],
            text_format=schema,
        )
        self.last_usage = _usage_event(response, model=self.model, service="openai_text", call_name=task)
        if response.output_parsed is None:
            raise ValueError(f"OpenAI returned no parsed output for task {task!r}.")
        return response.output_parsed


class OpenAISpeechToTextProvider(SpeechToTextProvider):
    def __init__(self, *, api_key: str, model: str = "gpt-4o-transcribe") -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.last_usage: dict[str, Any] | None = None

    def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
            )
        self.last_usage = _usage_event(response, model=self.model, service="openai_transcription", call_name="transcription")
        return str(response.text or "").strip()


class OpenAIVisionProvider(VisionProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.last_usage: dict[str, Any] | None = None

    def analyze(
        self,
        image_path: Path,
        schema: type[Any],
        context: dict[str, Any],
    ) -> Any:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(context, ensure_ascii=False),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded}",
                        },
                    ],
                }
            ],
            text_format=schema,
        )
        self.last_usage = _usage_event(response, model=self.model, service="openai_vision", call_name="image_analysis")
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no parsed image-analysis output.")
        return response.output_parsed


class OpenAIImageEditingProvider(ImageEditingProvider):
    def __init__(self, *, api_key: str, model: str = "gpt-image-1") -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.last_usage: dict[str, Any] | None = None

    def edit(self, source: Path, destination: Path, instructions: dict[str, Any]) -> Path:
        prompt = str(instructions.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Image edit prompt is required.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as image_file:
            response = self.client.images.edit(
                model=self.model,
                image=image_file,
                prompt=prompt,
            )
        self.last_usage = _usage_event(
            response,
            model=self.model,
            service="openai_images",
            call_name="image_optimization",
        )
        data_items = getattr(response, "data", None) or []
        if not data_items:
            raise ValueError("OpenAI image edit returned no image data.")
        first_item = data_items[0]
        b64_data = getattr(first_item, "b64_json", None)
        if not b64_data and isinstance(first_item, dict):
            b64_data = first_item.get("b64_json")
        image_url = getattr(first_item, "url", None)
        if not image_url and isinstance(first_item, dict):
            image_url = first_item.get("url")
        if b64_data:
            destination.write_bytes(base64.b64decode(b64_data))
            return destination
        if image_url:
            with urlopen(str(image_url), timeout=60) as response_stream:
                destination.write_bytes(response_stream.read())
            return destination
        raise ValueError("OpenAI image edit response did not include image content.")


def _usage_event(
    response: Any,
    *,
    model: str,
    service: str,
    call_name: str,
) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "service": service,
            "call_name": call_name,
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": None,
        }
    prompt_tokens = int(
        getattr(usage, "prompt_tokens", None)
        or getattr(usage, "input_tokens", 0)
        or 0
    )
    completion_tokens = int(
        getattr(usage, "completion_tokens", None)
        or getattr(usage, "output_tokens", 0)
        or 0
    )
    estimated_cost = _estimate_cost_usd(model, prompt_tokens, completion_tokens)
    return {
        "service": service,
        "call_name": call_name,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens),
        "estimated_cost_usd": estimated_cost,
    }


def _estimate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    normalized = model.lower()
    prices = next(
        (
            value
            for prefix, value in MODEL_PRICES_PER_MILLION_TOKENS_USD.items()
            if normalized.startswith(prefix)
        ),
        None,
    )
    if prices is None:
        return None
    input_price, output_price = prices
    return round(
        (prompt_tokens / 1_000_000 * input_price)
        + (completion_tokens / 1_000_000 * output_price),
        8,
    )
