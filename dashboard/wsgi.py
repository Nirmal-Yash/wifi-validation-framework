"""Canonical WSGI entrypoint for NetForge.

All deployment modes must import this module so the dashboard and enterprise
control plane are guaranteed to share the same Flask application instance.
"""

from dashboard.app import app

__all__ = ["app"]
