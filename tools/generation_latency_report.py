#!/usr/bin/env python3
"""Report and diagnose slow generation operations.

Scans local file-backed sessions in data/v2_sessions and highlights operation log
entries whose duration is above a threshold (default: 45s).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_SESSIONS_ROOT = Path("data/v2_sessions")
DEFAULT_OPERATION = "content_generation"


@dataclass
class SlowOperation:
    session_id: str
    operation_id: str
    operation: str
    status: str
    started_at: str
    finished_at: str
    duration_seconds: float
    total_tokens: int
    estimated_cost_usd: float | None
    model: str | None
    reasoning_effort: str | None
    generation_mode: str | None
    model_calls: list[dict[str, Any]]
    model_call_count: int
    model_time_seconds: float
    non_model_time_seconds: float
    image_count: int
    processed_image_count: int
    diagnosis: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose slow generation operations.")
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_SESSIONS_ROOT,
        help="Root directory containing session folders with state.json files.",
    )
    parser.add_argument(
        "--operation",
        default=DEFAULT_OPERATION,
        help="Operation name to inspect (default: content_generation).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=45.0,
        help="Flag operations with duration >= threshold seconds (default: 45).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum flagged rows to print (default: 25).",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="If set, only inspect this session id.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print flagged entries as JSON.",
    )
    return parser.parse_args()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _diagnose(
    *,
    duration: float,
    model_time: float,
    image_count: int,
    processed_image_count: int,
    model_calls: list[dict[str, Any]],
) -> str:
    non_model = max(0.0, duration - model_time)
    if model_time >= 45 and non_model <= 10:
        return "model_latency"
    if non_model >= 45 and image_count and processed_image_count < image_count:
        return "image_processing_or_vision_before_generation"
    if non_model >= 45 and image_count:
        return "pre_or_post_model_pipeline_overhead_with_images"
    if non_model >= 45 and not image_count:
        return "pipeline_or_worker_overhead"
    if duration >= 45 and len(model_calls) > 1:
        return "multi_call_generation"
    if duration >= 45:
        return "mixed_latency"
    return "ok"


def _finished_sort_key(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


def _load_flagged_operations(
    sessions_root: Path,
    *,
    operation: str,
    threshold_seconds: float,
    session_id_filter: str,
) -> tuple[list[SlowOperation], int, int]:
    state_files = sorted(sessions_root.glob("*/state.json"))
    if session_id_filter:
        state_files = [path for path in state_files if path.parent.name == session_id_filter]

    scanned_sessions = 0
    total_matching_operations = 0
    flagged: list[SlowOperation] = []

    for state_file in state_files:
        if not state_file.is_file():
            continue
        scanned_sessions += 1
        try:
            session = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        session_id = str(session.get("session_id") or state_file.parent.name)
        operation_log = session.get("operation_log") or []
        image_refs = session.get("image_refs") or []
        processed_images = session.get("processed_images") or []

        for entry in operation_log:
            if str(entry.get("operation") or "") != operation:
                continue
            if str(entry.get("status") or "") != "success":
                continue
            total_matching_operations += 1

            duration = _safe_float(entry.get("duration_seconds"))
            details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
            model_calls = details.get("model_calls") if isinstance(details.get("model_calls"), list) else []
            model_time = sum(_safe_float(call.get("duration_seconds")) for call in model_calls)
            non_model_time = max(0.0, duration - model_time)

            if duration < threshold_seconds:
                continue

            diagnosis = _diagnose(
                duration=duration,
                model_time=model_time,
                image_count=len(image_refs),
                processed_image_count=len(processed_images),
                model_calls=model_calls,
            )
            flagged.append(
                SlowOperation(
                    session_id=session_id,
                    operation_id=str(entry.get("operation_id") or ""),
                    operation=operation,
                    status="success",
                    started_at=str(entry.get("started_at") or ""),
                    finished_at=str(entry.get("finished_at") or ""),
                    duration_seconds=duration,
                    total_tokens=_safe_int(entry.get("total_tokens")),
                    estimated_cost_usd=(
                        float(entry.get("estimated_cost_usd"))
                        if entry.get("estimated_cost_usd") is not None
                        else None
                    ),
                    model=str(details.get("model")) if details.get("model") is not None else None,
                    reasoning_effort=(
                        str(details.get("reasoning_effort"))
                        if details.get("reasoning_effort") is not None
                        else None
                    ),
                    generation_mode=(
                        str(details.get("generation_mode"))
                        if details.get("generation_mode") is not None
                        else None
                    ),
                    model_calls=model_calls,
                    model_call_count=len(model_calls),
                    model_time_seconds=round(model_time, 3),
                    non_model_time_seconds=round(non_model_time, 3),
                    image_count=len(image_refs),
                    processed_image_count=len(processed_images),
                    diagnosis=diagnosis,
                )
            )

    flagged.sort(key=lambda row: (_finished_sort_key(row.finished_at), row.duration_seconds), reverse=True)
    return flagged, scanned_sessions, total_matching_operations


def _print_human(
    flagged: list[SlowOperation],
    *,
    scanned_sessions: int,
    total_matching_operations: int,
    threshold_seconds: float,
    limit: int,
) -> None:
    print(
        f"Scanned {scanned_sessions} sessions | "
        f"{total_matching_operations} matching successful operations | "
        f"{len(flagged)} flagged (>= {threshold_seconds:.1f}s)"
    )

    if not flagged:
        return

    print()
    print("Flagged operations:")
    for row in flagged[:limit]:
        print(
            "- "
            f"{row.finished_at} "
            f"session={row.session_id} "
            f"duration={row.duration_seconds:.1f}s "
            f"model_time={row.model_time_seconds:.1f}s "
            f"non_model={row.non_model_time_seconds:.1f}s "
            f"tokens={row.total_tokens:,} "
            f"calls={row.model_call_count} "
            f"model={row.model or '-'} "
            f"reasoning={row.reasoning_effort or '-'} "
            f"mode={row.generation_mode or '-'} "
            f"images={row.image_count}/{row.processed_image_count} "
            f"diagnosis={row.diagnosis}"
        )


def _to_jsonable(rows: list[SlowOperation]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        payload.append(
            {
                "session_id": row.session_id,
                "operation_id": row.operation_id,
                "operation": row.operation,
                "status": row.status,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "duration_seconds": row.duration_seconds,
                "model_time_seconds": row.model_time_seconds,
                "non_model_time_seconds": row.non_model_time_seconds,
                "total_tokens": row.total_tokens,
                "estimated_cost_usd": row.estimated_cost_usd,
                "model": row.model,
                "reasoning_effort": row.reasoning_effort,
                "generation_mode": row.generation_mode,
                "model_call_count": row.model_call_count,
                "image_count": row.image_count,
                "processed_image_count": row.processed_image_count,
                "diagnosis": row.diagnosis,
            }
        )
    return payload


def main() -> int:
    args = _parse_args()
    flagged, scanned_sessions, total_matching_operations = _load_flagged_operations(
        args.sessions_root,
        operation=args.operation,
        threshold_seconds=args.threshold,
        session_id_filter=args.session_id,
    )
    if args.json:
        print(json.dumps(_to_jsonable(flagged[: args.limit]), indent=2))
    else:
        _print_human(
            flagged,
            scanned_sessions=scanned_sessions,
            total_matching_operations=total_matching_operations,
            threshold_seconds=args.threshold,
            limit=args.limit,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
