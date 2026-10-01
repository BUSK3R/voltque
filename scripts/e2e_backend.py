"""Backend for the Playwright E2E run: its own SQLite file, migrated and seeded from scratch.

Usage: python scripts/e2e_backend.py [port]   (default 8100; the dev database is never touched)
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
DB_FILE = "e2e.db"


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8100"
    for suffix in ("", "-journal", "-wal", "-shm"):
        (BACKEND / f"{DB_FILE}{suffix}").unlink(missing_ok=True)
    env = {**os.environ, "DATABASE_URL": f"sqlite:///./{DB_FILE}"}
    for cmd in ([sys.executable, "-m", "alembic", "upgrade", "head"], [sys.executable, "-m", "app.seed"]):
        subprocess.run(cmd, cwd=BACKEND, env=env, check=True)
    # no --reload: a single process, so the runner can stop it cleanly
    server = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", port]
    try:
        return subprocess.run(server, cwd=BACKEND, env=env, check=False).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
