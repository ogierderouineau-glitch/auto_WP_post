from __future__ import annotations

import base64
import mimetypes
import json
import os
import tempfile
from time import perf_counter
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from app.v2.providers.image_pricing import image_output_price_usd

from openai import APIStatusError, OpenAI

try:
    from PIL import Image
except Exception:
    Image = None

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
    def __init__(self, *, api_key: str, model: str, reasoning_effort: str | None = None) -> None:
        self.api_key = api_key
        self.client = OpenAI(
            api_key=api_key,
            timeout=float(os.getenv("V2_TEXT_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("V2_TEXT_MAX_RETRIES", "2")),
        )
        self.model = model
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else os.getenv("V2_TEXT_REASONING_EFFORT", "low").strip()
        )
        self.last_usage: dict[str, Any] | None = None

    def with_settings(self, *, model: str, reasoning_effort: str) -> "OpenAILanguageModelProvider":
        return OpenAILanguageModelProvider(
            api_key=self.api_key,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        request_options: dict[str, Any] = {}
        if self.reasoning_effort:
            request_options["reasoning"] = {"effort": self.reasoning_effort}
        started = perf_counter()
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=context["messages"],
                text_format=schema,
                **request_options,
            )
        except APIStatusError as exc:
            if exc.status_code >= 500:
                body = exc.body if isinstance(exc.body, dict) else {}
                retry_after = body.get("retry_after")
                retry_hint = (
                    f" Wait at least {retry_after} seconds, then try again."
                    if retry_after
                    else " Wait briefly, then try again."
                )
                request_id = getattr(exc, "request_id", None)
                request_hint = f" Request ID: {request_id}." if request_id else ""
                raise RuntimeError(
                    f"OpenAI is temporarily unavailable (HTTP {exc.status_code})."
                    f"{retry_hint}{request_hint}"
                ) from exc
            raise
        self.last_usage = {
            **_usage_event(response, model=self.model, service="openai_text", call_name=task),
            "duration_seconds": round(perf_counter() - started, 3),
        }
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
                            "detail": "high",
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
    def __init__(self, *, api_key: str, model: str = "gpt-image-2", quality: str = "medium") -> None:
        if quality not in {"low", "medium", "high"}:
            raise ValueError("Image edit quality must be low, medium, or high.")
        self.client = OpenAI(
            api_key=api_key,
            timeout=float(os.getenv("V2_IMAGE_EDIT_TIMEOUT_SECONDS", "150")),
            max_retries=int(os.getenv("V2_IMAGE_EDIT_MAX_RETRIES", "1")),
        )
        self.model = model
        self.quality = quality
        self.last_usage: dict[str, Any] | None = None

    def edit(self, source: Path, destination: Path, instructions: dict[str, Any]) -> Path:
        prompt = str(instructions.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Image edit prompt is required.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        edit_input = source
        temporary_input: Path | None = None
        if Image is not None:
            try:
                with Image.open(source) as opened:
                    source_image = opened.convert("RGB") if opened.mode != "RGB" else opened.copy()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temporary:
                    temporary_input = Path(temporary.name)
                source_image.save(temporary_input, format="JPEG", quality=95)
                edit_input = temporary_input
            except Exception:
                edit_input = source
        try:
            if Image is not None:
                with Image.open(edit_input) as opened:
                    request_size = (
                        "1024x1536"
                        if opened.height > opened.width
                        else "1536x1024"
                        if opened.width > opened.height
                        else "1024x1024"
                    )
            else:
                request_size = "1024x1024"
            with edit_input.open("rb") as image_file:
                try:
                    response = self.client.images.edit(
                        model=self.model,
                        image=image_file,
                        prompt=prompt,
                        quality=self.quality,
                        size=request_size,
                    )
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        request_id = getattr(exc, "request_id", None)
                        request_hint = f" Request ID: {request_id}." if request_id else ""
                        raise RuntimeError(
                            "OpenAI's image service is temporarily unavailable after automatic retries "
                            f"(HTTP {exc.status_code}).{request_hint} Wait a minute, then try again."
                        ) from exc
                    raise
        finally:
            if temporary_input and temporary_input.exists():
                try:
                    temporary_input.unlink()
                except Exception:
                    pass
        self.last_usage = _usage_event(
            response,
            model=self.model,
            service="openai_images",
            call_name="image_optimization",
            estimated_cost_usd=image_output_price_usd(self.model, self.quality, request_size),
            extra={"quality": self.quality, "size": request_size, "pricing_unit": "per_output_image"},
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
            _write_image_bytes(destination, base64.b64decode(b64_data))
            return destination
        if image_url:
            with urlopen(str(image_url), timeout=60) as response_stream:
                _write_image_bytes(destination, response_stream.read())
            return destination
        raise ValueError("OpenAI image edit response did not include image content.")


def _write_image_bytes(destination: Path, image_bytes: bytes) -> None:
    if Image is None:
        destination.write_bytes(image_bytes)
        return
    image = Image.open(BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    suffix = destination.suffix.lower()
    if suffix == ".webp":
        image.save(destination, format="WEBP", quality=90, method=6)
    elif suffix in {".jpg", ".jpeg"}:
        image.save(destination, format="JPEG", quality=92, optimize=True, progressive=True)
    elif suffix == ".png":
        image.save(destination, format="PNG", optimize=True)
    else:
        image.save(destination, format="WEBP", quality=90, method=6)


def _usage_event(
    response: Any,
    *,
    model: str,
    service: str,
    call_name: str,
    estimated_cost_usd: float | None = None,
    extra: dict[str, Any] | None = None,
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
            "estimated_cost_usd": estimated_cost_usd,
            **(extra or {}),
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
    estimated_cost = estimated_cost_usd
    if estimated_cost is None:
        estimated_cost = _estimate_cost_usd(model, prompt_tokens, completion_tokens)
    return {
        "service": service,
        "call_name": call_name,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens),
        "estimated_cost_usd": estimated_cost,
        **(extra or {}),
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
