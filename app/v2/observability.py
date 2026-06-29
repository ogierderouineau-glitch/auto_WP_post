from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class V2RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request logs without credentials or request bodies."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/content-sessions"):
            return await call_next(request)
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        session_id = None
        parts = request.url.path.strip("/").split("/")
        if len(parts) >= 3 and parts[2] not in {"_workbook"}:
            session_id = parts[2]
        logger = logging.getLogger("flairlab.v2")
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "session_id": session_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
            )
