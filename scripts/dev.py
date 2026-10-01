"""Run backend and frontend dev servers together (cross-platform). Ctrl+C stops both."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found on PATH", file=sys.stderr)
        return 1
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
            cwd=ROOT / "backend",
        ),
        subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend"),
    ]
    print("backend  http://localhost:8000/health\nfrontend http://localhost:5173/m  /ops")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
