from __future__ import annotations

import argparse
import json
import os
import socket
import time

from lib.platform import platform_adapter_for
from lib.repositories import SQLiteDatabase
from lib.services.credential_vault import CredentialVaultService
from lib.services.pipeline_runtime import build_pipeline_handlers
from lib.services.pipeline_service import PipelineService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run durable NetRegress pipeline steps.")
    parser.add_argument("--database", help="SQLite database path (defaults to the NetRegress database resolver)")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}:{os.getpid()}")
    parser.add_argument("--poll-interval", type=float, default=0.0, help="Poll interval in seconds; zero runs one step and exits")
    parser.add_argument("--once", action="store_true", help="Run at most one step and exit")
    args = parser.parse_args()
    if args.poll_interval < 0 or args.poll_interval > 300:
        parser.error("--poll-interval must be between 0 and 300 seconds")

    database = SQLiteDatabase(args.database) if args.database else SQLiteDatabase()
    database.initialize()
    adapter = platform_adapter_for()
    vault = CredentialVaultService(
        database, adapter.create_secret_store(),
        secret_provider=adapter.descriptor.family.value,
    )
    service = PipelineService(database)
    handlers = build_pipeline_handlers(database, vault)

    while True:
        result = service.run_once(args.worker_id, handlers)
        print(json.dumps(result or {"status": "IDLE"}, sort_keys=True, separators=(",", ":")))
        if args.poll_interval == 0 or args.once:
            return 0
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
