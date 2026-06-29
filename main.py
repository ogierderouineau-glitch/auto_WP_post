"""Readable application entry point.

V1 remains hosted by ``app_main`` during migration. V2 is mounted there through
a narrow router while all V2 business logic lives under ``app.v2``.
"""

from app_main import app

__all__ = ["app"]
