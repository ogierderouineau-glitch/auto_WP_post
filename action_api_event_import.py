import argparse
import json
import logging
import os
import shutil
import traceback
import uuid
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from config import get_client_config
from run_event_import import run_import
from step_10_event_payload import DEFAULT_OUTPUT_ROOT, safe_name
from pydantic import BaseModel, ConfigDict, Field

API_UPLOAD_ROOT = Path("data/api_uploads")
API_LOG_ROOT = Path("data/api_logs")
API_LOG_FILE = API_LOG_ROOT / "api_event_import.log"
IMPORT_API_KEY = os.getenv("IMPORT_API_KEY", "")

API_LOG_ROOT.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=API_LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("flairlab_event_import_api")


class OpenAIFileRef(BaseModel):
    name: str | None = None
    id: str | None = None
    mime_type: str | None = None
    download_link: str


class EventPostParams(BaseModel):
    openaiFileIdRefs: list[OpenAIFileRef] = Field(
        ...,
        min_length=1,
        max_length=1,
    )
    event_name: str | None = None
    status: str = "publish"
    row: int = 0
    required_category: str = "auto event post"
    existing_post_mode: str = "update"
    existing_post_id: int | None = None
    client_id: str = "flairlab"


class EventPostActionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: str | None = None
    method: str | None = None
    path: str | None = None
    operation: str | None = None
    operation_hash: str | None = None
    is_consequential: bool | None = None
    params: EventPostParams


class EventPostFromZipRequest(BaseModel):
    openaiFileIdRefs: list[OpenAIFileRef] = Field(
        ...,
        min_length=1,
        max_length=1,
    )
    event_name: str | None = None
    status: str = "publish"
    row: int = 0
    required_category: str = "auto event post"
    existing_post_mode: str = "update"
    existing_post_id: int | None = None
    client_id: str = "flairlab"


app = FastAPI(
    title="FLAIRLAB Event Post Import API",
    version="1.0.0",
    description=(
        "Receives a chatbot-generated event zip, imports its CSV and pictures into "
        "WordPress, and returns the generated post links."
    ),
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    logger.info("request_start id=%s method=%s path=%s", request_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_crashed id=%s method=%s path=%s", request_id, request.method, request.url.path)
        raise
    logger.info(
        "request_end id=%s method=%s path=%s status=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = uuid.uuid4().hex[:12]
    logger.error(
        "unhandled_exception id=%s method=%s path=%s error=%s\n%s",
        request_id,
        request.method,
        request.url.path,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "request_id": request_id,
            "error": str(exc),
        },
    )


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if IMPORT_API_KEY and x_api_key != IMPORT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def save_downloaded_zip(file_ref: dict[str, Any]) -> Path:
    download_link = file_ref.get("download_link")
    if not download_link:
        raise HTTPException(status_code=400, detail="Missing download_link in openaiFileIdRefs[0].")

    filename = safe_name(Path(file_ref.get("name") or "event.zip").name)
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="The generated file must be a .zip file.")

    upload_dir = API_UPLOAD_ROOT / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / filename

    response = requests.get(download_link, timeout=120)
    if not response.ok:
        logger.error("openai_file_download_failed status=%s body=%s", response.status_code, response.text[:500])
        raise HTTPException(status_code=400, detail="Could not download ZIP from openaiFileIdRefs download_link.")

    with destination.open("wb") as output:
        output.write(response.content)
    logger.info("zip_downloaded filename=%s path=%s size=%s", filename, destination, destination.stat().st_size)
    return destination


def build_import_args(
    zip_path: Path,
    event_name: str | None,
    status: str,
    row: int,
    required_category: str,
    existing_post_mode: str,
    existing_post_id: int | None,
    client_id: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        zip_path=zip_path,
        event_dir=None,
        input_csv=None,
        event_name=event_name,
        client_id=client_id,
        batch_root=None,
        sync_source=None,
        rclone_source=None,
        rclone_root_folder_id=None,
        allow_rclone_root=False,
        processed_dir_name="processed",
        move_after_dry_run=False,
        output_root=DEFAULT_OUTPUT_ROOT,
        row=row,
        status=status,
        media_mode="post-attachments",
        existing_post_mode=existing_post_mode,
        existing_post_id=existing_post_id,
        acf_mode="post-acf",
        acf_placement="both",
        strict_acf=False,
        required_category=required_category,
        skip_missing_categories=True,
        create_missing_tags=True,
        strict_featured_image=False,
        strict_preflight=True,
        reuse_existing_uploads=True,
        compress_images=True,
        compression_target_kb=50,
        compression_min_quality=25,
        compression_start_quality=90,
        compression_min_width=300,
        live=True,
    )


def post_response_from_output(output_dir: Path, client_id: str) -> dict[str, Any]:
    post_path = output_dir / "created_post.json"
    if not post_path.exists():
        raise RuntimeError(f"Import completed but no created_post.json was written: {post_path}")

    post = json.loads(post_path.read_text(encoding="utf-8"))
    technical_log_path = output_dir / "technical_log.json"
    technical_log = (
        json.loads(technical_log_path.read_text(encoding="utf-8"))
        if technical_log_path.exists()
        else {}
    )

    post_id = post["id"]
    client_config = get_client_config(client_id)
    return {
        "success": True,
        "post_id": post_id,
        "status": post.get("status"),
        "view_url": post.get("link"),
        "edit_url": f"{client_config.wp_base_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit",
        "post_write_mode": technical_log.get("post_write_mode"),
        "output_dir": str(output_dir),
        "warnings": json.loads((output_dir / "warnings.json").read_text(encoding="utf-8"))
        if (output_dir / "warnings.json").exists()
        else [],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/last-import")
def last_import_debug(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    import_dirs = [path for path in DEFAULT_OUTPUT_ROOT.iterdir() if path.is_dir()] if DEFAULT_OUTPUT_ROOT.exists() else []
    upload_dirs = [path for path in API_UPLOAD_ROOT.iterdir() if path.is_dir()] if API_UPLOAD_ROOT.exists() else []
    latest_import = max(import_dirs, key=lambda path: path.stat().st_mtime, default=None)
    latest_upload = max(upload_dirs, key=lambda path: path.stat().st_mtime, default=None)

    return {
        "latest_import_dir": str(latest_import) if latest_import else None,
        "latest_upload_dir": str(latest_upload) if latest_upload else None,
        "log_file": str(API_LOG_FILE),
    }


@app.post("/event-posts/from-zip")
async def import_event_post_from_zip(
    payload: EventPostActionRequest,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    params = payload.params
    file_ref = params.openaiFileIdRefs[0]

    zip_path = save_downloaded_zip(file_ref.model_dump())

    args = build_import_args(
        zip_path=zip_path,
        event_name=params.event_name,
        status=params.status,
        row=params.row,
        required_category=params.required_category,
        existing_post_mode=params.existing_post_mode,
        existing_post_id=params.existing_post_id,
        client_id=params.client_id,
    )

    try:
        logger.info(
            "import_start zip=%s event_name=%s status=%s",
            zip_path,
            params.event_name,
            params.status,
        )

        output_dir = await run_in_threadpool(run_import, args)
        response = post_response_from_output(output_dir, params.client_id)

        logger.info(
            "import_success zip=%s output_dir=%s post_id=%s",
            zip_path,
            output_dir,
            response.get("post_id"),
        )

        return response

    except Exception as exc:
        logger.error(
            "import_failed zip=%s error=%s\n%s",
            zip_path,
            exc,
            traceback.format_exc(),
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error": str(exc),
                "uploaded_zip": str(zip_path),
            },
        ) from exc
