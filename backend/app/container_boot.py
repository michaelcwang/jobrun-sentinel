from __future__ import annotations

import os
import time

from sqlalchemy import text


def main() -> None:
    """Container entrypoint: wait for dependencies, then start the API server."""
    _wait_for_database()
    if _truthy(os.getenv("JOBRUN_RUN_MIGRATIONS", "false")):
        _run_migrations()
    _run_uvicorn()


def _wait_for_database() -> None:
    from app.core.database import engine

    wait_seconds = int(os.getenv("JOBRUN_DB_WAIT_SECONDS", "60"))
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while time.monotonic() <= deadline:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # pragma: no cover - exercised in container runtime
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Database was not ready after {wait_seconds}s: {last_error}") from last_error


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.upgrade(config, "head")


def _run_uvicorn() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "*"),
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
