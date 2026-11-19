"""Compatibility ASGI entry point for ``uvicorn main:app``."""

from backend.main import app

__all__ = ["app"]
