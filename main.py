"""Readable application entry point.

The production app is hosted by ``app_main``. The current structured
content workflow is mounted there through a narrow router while its business
logic lives under ``app.v2``.
"""

from app_main import app

__all__ = ["app"]
