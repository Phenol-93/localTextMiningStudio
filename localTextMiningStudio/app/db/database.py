"""SQLite connection and project database initialization helpers."""

from __future__ import annotations

import re
import sqlite3
import sys
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator

from app.utils.paths import get_projects_dir


PROJECT_DATABASE_NAME = "project.sqlite"
_PROJECT_DIR_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def get_schema_sql() -> str:
    """Read the database schema SQL."""
    try:
        return resources.files("app.db").joinpath("schema.sql").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError):
        candidates = [
            Path(getattr(sys, "_MEIPASS", "")) / "app" / "db" / "schema.sql",
            Path(sys.executable).resolve().parent
            / "_internal"
            / "app"
            / "db"
            / "schema.sql",
            Path(__file__).with_name("schema.sql"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with app defaults."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def connection_scope(database_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Yield a connection and commit or roll back around the block."""
    connection = connect(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path: Path | str) -> Path:
    """Create all tables for a project database."""
    path = Path(database_path)
    with connection_scope(path) as connection:
        connection.executescript(get_schema_sql())
        _apply_migrations(connection)
    return path


def create_project_database(project_name: str, base_dir: Path | None = None) -> Path:
    """Create and initialize a project database under the projects directory."""
    project_dir = _next_available_project_dir(project_name, base_dir or get_projects_dir())
    project_dir.mkdir(parents=True, exist_ok=False)
    return initialize_database(project_dir / PROJECT_DATABASE_NAME)


def get_project_database_path(project_dir: Path | str) -> Path:
    """Return the SQLite database path for a project directory."""
    return Path(project_dir) / PROJECT_DATABASE_NAME


def _next_available_project_dir(project_name: str, base_dir: Path) -> Path:
    safe_name = _safe_project_dir_name(project_name)
    candidate = base_dir / safe_name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = base_dir / f"{safe_name}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _safe_project_dir_name(project_name: str) -> str:
    normalized = _PROJECT_DIR_PATTERN.sub("-", project_name.strip()).strip(".-_")
    return normalized or "project"


def _apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply small additive migrations for existing project databases."""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(documents)").fetchall()
    }
    if "filename" not in columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN filename TEXT NOT NULL DEFAULT ''"
        )
    if "raw_text" not in columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN raw_text TEXT NOT NULL DEFAULT ''"
        )
    if "cleaned_text" not in columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN cleaned_text TEXT NOT NULL DEFAULT ''"
        )
    if "preprocessing_params_json" not in columns:
        connection.execute(
            "ALTER TABLE documents ADD COLUMN preprocessing_params_json TEXT NOT NULL DEFAULT '{}'"
        )

    triple_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(triples)").fetchall()
    }
    if "created_by" not in triple_columns:
        connection.execute(
            "ALTER TABLE triples ADD COLUMN created_by TEXT NOT NULL DEFAULT 'ai'"
        )
