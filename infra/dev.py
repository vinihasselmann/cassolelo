"""Sobe backend (uvicorn --reload, :8000) e frontend (vite, :5173) juntos.

Usado por `make dev` (funciona em Windows, macOS e Linux). Ctrl+C encerra os dois.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _exe(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        sys.exit(f"'{name}' não encontrado no PATH.")
    return path


def main() -> int:
    procs = {
        "backend": subprocess.Popen(  # noqa: S603
            [
                _exe("uv"), "run", "uvicorn", "app.main:create_app", "--factory",
                "--reload", "--host", "127.0.0.1", "--port", "8000",
            ],
            cwd=ROOT / "backend",
        ),
        "frontend": subprocess.Popen([_exe("npm"), "run", "dev"], cwd=ROOT / "frontend"),  # noqa: S603
    }
    print("\n  Backend:  http://localhost:8000/api/health\n  Frontend: http://localhost:5173\n")
    try:
        while True:
            for name, proc in procs.items():
                code = proc.poll()
                if code is not None:
                    print(f"{name} terminou (código {code}); encerrando o outro.")
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                if sys.platform == "win32":
                    # npm roda via cmd: encerra a árvore inteira (senão o vite fica órfão)
                    subprocess.run(  # noqa: S603
                        [_exe("taskkill"), "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    proc.send_signal(signal.SIGINT)
        for proc in procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
