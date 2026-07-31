"""FastAPI composition root for the current content-session application."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from google.cloud import storage as gcs_storage

from backend import config
from backend.app.api.step_02_routes import create_router, v2_error_handler
from backend.app.api.step_03_container import (
    client_knowledge_gcs_uri,
    configured_workbook_path,
    get_v2_service,
    reload_v2_knowledge_if_initialized,
    v2_readiness,
)
from backend.app.errors import V2Error
from backend.app.knowledge_base.step_02_loader import WorkbookLoader
from backend.app.knowledge_base.step_03_validator import WorkbookValidator
from backend.app.observability import V2RequestLoggingMiddleware


async def verify_api_key(
    x_api_key: str | None = Header(default=None),
) -> config.WordPressClientConfig:
    """Authenticate the request and derive its client from the key."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if not config.CLIENTS:
        raise HTTPException(status_code=503, detail="API key is not configured.")

    client = config.client_from_import_key(x_api_key)
    if client is None and not os.getenv("RENDER"):
        # Development accepts any non-empty API key and uses the configured default client.
        client = config.get_client_config()
    elif client is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    config.set_active_client(client.client_id)
    return client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Defer workbook initialization until the authenticated client actually needs it.
    yield


app = FastAPI(
    title=config.APP_NAME,
    version="2.0.0",
    description="Structured content-session API for the Speech2Post frontend.",
    lifespan=lifespan,
)
app.add_exception_handler(V2Error, v2_error_handler)
app.add_middleware(V2RequestLoggingMiddleware)
app.include_router(create_router(get_v2_service, verify_api_key, v2_readiness))


@app.get("/clients")
def clients(client: config.WordPressClientConfig = Depends(verify_api_key)) -> dict[str, object]:
    return {
        "clients": [
            {
                "client_id": client.client_id,
                "name": client.name,
                "country": client.country,
                "language": client.language,
                "wp_base_url": client.wp_base_url,
                "status": (
                    "configured"
                    if client.wp_username and client.wp_app_password
                    else "missing_credentials"
                ),
            }
        ]
    }


@app.get("/app/knowledge/workbook")
def download_knowledge_workbook(
    _: None = Depends(verify_api_key),
) -> FileResponse:
    path = configured_workbook_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Knowledge workbook not found.")
    return FileResponse(
        path,
        media_type="application/vnd.ms-excel.sheet.macroEnabled.12",
        filename=path.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/app/knowledge/workbook")
async def upload_knowledge_workbook(
    workbook: UploadFile = File(...),
    post_type: str | None = Form(default=None),
    _: None = Depends(verify_api_key),
) -> dict[str, object]:
    del post_type  # The complete workbook is validated for every post type.
    suffix = Path(workbook.filename or "").suffix.lower()
    if suffix not in {".xlsm", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Upload an .xlsm or .xlsx workbook.")

    destination = configured_workbook_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}.uploading{suffix}")
    try:
        with temporary.open("wb") as output:
            while chunk := await workbook.read(1024 * 1024):
                output.write(chunk)
        WorkbookValidator().validate(WorkbookLoader().load(temporary))

        gcs_uri = client_knowledge_gcs_uri()
        if gcs_uri:
            bucket_name, separator, blob_name = gcs_uri[5:].partition("/")
            if not gcs_uri.startswith("gs://") or not separator or not bucket_name or not blob_name:
                raise HTTPException(
                    status_code=500,
                    detail="The configured client knowledge workbook URI is invalid.",
                )
            gcs_storage.Client().bucket(bucket_name).blob(blob_name).upload_from_filename(
                str(temporary)
            )

        os.replace(temporary, destination)
        reload_v2_knowledge_if_initialized()
        return {"success": True, "message": "Database Datei aktualisiert."}
    except V2Error as exc:
        raise HTTPException(status_code=400, detail=exc.as_dict()) from exc
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
