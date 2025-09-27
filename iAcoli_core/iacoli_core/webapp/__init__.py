# iacoli_core/webapp/__init__.py
"""Módulo webapp do iAcoli Core - Interface web e API REST."""

from .app import create_app, app

__all__ = ["create_app", "app"]