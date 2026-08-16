"""Canonical local development entrypoint.

Run with: python run.py
"""

from dashboard.app import app
from dashboard.db import ensure_schema


if __name__ == "__main__":
    ensure_schema()
    print("[*] NetForge Control Plane: http://127.0.0.1:5000")
    app.run(
        host="0.0.0.0",
        port=int(__import__("os").getenv("NETFORGE_PORT", "5000")),
        debug=__import__("os").getenv("NETFORGE_DEBUG", "0") == "1",
    )
