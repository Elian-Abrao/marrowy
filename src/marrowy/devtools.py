from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine
from sqlalchemy import text

from marrowy.core.settings import Settings
from marrowy.db.session import SessionLocal
from marrowy.services.projects import ProjectService


@dataclass(slots=True)
class BridgeProcess:
    process: subprocess.Popen[bytes]
    log_path: Path
    log_file: object

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log_file.close()


def ensure_env_file(project_root: Path) -> bool:
    env_path = project_root / ".env"
    example_path = project_root / ".env.example"
    if env_path.exists() or not example_path.exists():
        return False
    shutil.copy2(example_path, env_path)
    return True


def ensure_postgres_container(project_root: Path) -> None:
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], cwd=project_root, check=True)


def wait_for_database(database_url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("select 1"))
            return
        except Exception as exc:  # pragma: no cover - timing-dependent path
            last_error = exc
            time.sleep(0.5)
        finally:
            engine.dispose()
    detail = str(last_error).strip() if last_error is not None else "unknown database error"
    raise RuntimeError(f"Database did not become ready in time: {detail}")


def run_migrations(project_root: Path) -> None:
    subprocess.run(["alembic", "upgrade", "head"], cwd=project_root, check=True)


def seed_default_project() -> str:
    db = SessionLocal()
    try:
        project = ProjectService(db).seed_default_project()
        db.commit()
        return project.slug
    finally:
        db.close()


def bridge_ready(bridge_url: str, *, timeout_seconds: float = 1.5) -> bool:
    try:
        response = httpx.get(f"{bridge_url.rstrip('/')}/readyz", timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return bool(payload.get("ok"))
    except Exception:
        return False


def start_local_bridge(settings: Settings, *, log_dir: Path | None = None) -> BridgeProcess:
    bridge_dir = settings.codex_runtime_bridge_dir
    python_bin = bridge_dir / ".venv" / "bin" / "python"
    if not bridge_dir.exists():
        raise RuntimeError(
            f"Could not find codex-runtime-bridge at {bridge_dir}. "
            "Set MARROWY_CODEX_RUNTIME_BRIDGE_DIR or start the bridge manually."
        )
    if not python_bin.exists():
        raise RuntimeError(
            f"Could not find the bridge Python interpreter at {python_bin}. "
            "Create the bridge virtualenv first or start the bridge manually."
        )

    parsed = urlparse(settings.codex_bridge_url)
    port = parsed.port or 8787
    log_directory = log_dir or settings.base_dir / ".state"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "codex-runtime-bridge.log"
    log_file = open(log_path, "ab")
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    process = subprocess.Popen(
        [str(python_bin), "-m", "codex_runtime_bridge", "serve", "--port", str(port)],
        cwd=bridge_dir,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return BridgeProcess(process=process, log_path=log_path, log_file=log_file)


def wait_for_bridge(bridge_url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if bridge_ready(bridge_url):
            return
        time.sleep(0.5)
    raise RuntimeError(f"Codex bridge at {bridge_url} did not become ready in time.")
