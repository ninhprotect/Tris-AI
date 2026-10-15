"""Start the bundled PostgreSQL cluster when the local desktop app needs it."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from config.settings import POSTGRES_DSN, PROJECT_ROOT


def ensure_local_postgres() -> bool:
    """Start only the project-owned cluster; never touch another PostgreSQL."""
    if not POSTGRES_DSN:
        return False
    parsed = urlparse(POSTGRES_DSN)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    runtime = PROJECT_ROOT / "runtime" / "postgresql-17.11" / "pgsql" / "bin"
    cluster = PROJECT_ROOT / "data" / "postgres-account-db"
    # A copied project can carry an un-administrable account cluster whose
    # superuser secret never travelled with it. Once setup_postgres_fresh.ps1
    # has produced the replacement beside it, prefer the fresh cluster — the
    # original one may not even start (its files refuse rename/unlink).
    if (PROJECT_ROOT / "data" / "postgres-account-db-fresh" / "PG_VERSION").exists():
        cluster = PROJECT_ROOT / "data" / "postgres-account-db-fresh"
    pg_isready = runtime / "pg_isready.exe"
    pg_ctl = runtime / "pg_ctl.exe"
    if not pg_isready.exists() or not (cluster / "PG_VERSION").exists():
        return False
    readiness = subprocess.run(
        [str(pg_isready), "-h", "127.0.0.1", "-p", str(parsed.port or 5432)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if readiness.returncode == 0:
        return True
    log_path = PROJECT_ROOT / "data" / "postgres-account-db.log"
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW
    # The started server inherits pg_ctl's handles, so captured pipes would
    # never see EOF and this call would block until the server exits. Give
    # pg_ctl a null console (its own -l log keeps the messages) and re-probe.
    subprocess.run(
        [
            str(pg_ctl),
            "-D",
            str(cluster),
            "-l",
            str(log_path),
            "-o",
            f'"-p {parsed.port or 5432}"',
            "start",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        creationflags=creation_flags,
    )
    for _ in range(20):
        readiness = subprocess.run(
            [str(pg_isready), "-h", "127.0.0.1", "-p", str(parsed.port or 5432)],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if readiness.returncode == 0:
            return True
        time.sleep(0.5)
    return False

