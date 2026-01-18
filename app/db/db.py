from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import Flask, g


DEFAULT_IMPORTED_PROJECT_TITLE = "Imported Workspace"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    # Enforce FK constraints for this connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r["name"] == column_name for r in rows)


def migrate(conn: sqlite3.Connection) -> None:
    """Pragmatic, idempotent migrations.

    Rules:
    - If `projects` table doesn't exist, create it.
    - If `plans` table doesn't exist, create it.
    - If `media` lacks `project_id`, add it (nullable), then backfill with a default project.

    We keep the DB column nullable to avoid SQLite ALTER TABLE limitations, but enforce
    NOT NULL by application logic.
    """

    # Base table (for brand-new installs or very old installs).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            content_type TEXT,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    if not table_exists(conn, "projects"):
        conn.execute(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                intent_text TEXT
            )
            """
        )

    if not table_exists(conn, "plans"):
        conn.execute(
            """
            CREATE TABLE plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                model TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
            """
        )

    # Add project_id to media if missing.
    if not column_exists(conn, "media", "project_id"):
        conn.execute("ALTER TABLE media ADD COLUMN project_id INTEGER NULL")

        default_project_id = ensure_default_project(conn)
        conn.execute(
            "UPDATE media SET project_id = ? WHERE project_id IS NULL",
            (default_project_id,),
        )

    # On already-migrated DBs, still ensure there's at least one project.
    if table_exists(conn, "projects"):
        ensure_default_project(conn)

    conn.commit()


def init_db(app: Flask) -> None:
    # Run migrations once on startup.
    conn = _connect(app.config["DATABASE_PATH"])
    try:
        migrate(conn)
    finally:
        conn.close()

    @app.before_request
    def _open_db() -> None:
        g._db = _connect(app.config["DATABASE_PATH"])

    @app.teardown_request
    def _close_db(_: Exception | None = None) -> None:
        conn2 = getattr(g, "_db", None)
        if conn2 is not None:
            conn2.close()
            g._db = None


def get_db(app: Flask | None = None) -> sqlite3.Connection:
    if hasattr(g, "_db"):
        return g._db  # type: ignore[attr-defined]
    if app is None:
        raise RuntimeError("get_db requires app outside request context")
    return _connect(app.config["DATABASE_PATH"])


@dataclass(frozen=True)
class ProjectItem:
    id: int
    created_at: str
    title: str
    intent_text: str | None


@dataclass(frozen=True)
class MediaItem:
    id: int
    project_id: int
    original_name: str
    stored_name: str
    content_type: str | None
    size_bytes: int
    created_at: str


@dataclass(frozen=True)
class PlanItem:
    id: int
    project_id: int
    created_at: str
    model: str
    plan_json: str


def ensure_default_project(conn: sqlite3.Connection) -> int:
    """Ensure a stable default project exists and return its id."""
    row = conn.execute(
        "SELECT id FROM projects WHERE title = ? ORDER BY id ASC LIMIT 1",
        (DEFAULT_IMPORTED_PROJECT_TITLE,),
    ).fetchone()
    if row is not None:
        return int(row["id"])

    created_at = _utc_now_iso()
    cur = conn.execute(
        "INSERT INTO projects (created_at, title, intent_text) VALUES (?, ?, ?)",
        (created_at, DEFAULT_IMPORTED_PROJECT_TITLE, None),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_project(conn: sqlite3.Connection, *, title: str, intent_text: str) -> int:
    created_at = _utc_now_iso()
    cur = conn.execute(
        "INSERT INTO projects (created_at, title, intent_text) VALUES (?, ?, ?)",
        (created_at, title, intent_text),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_projects(conn: sqlite3.Connection) -> list[ProjectItem]:
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [
        ProjectItem(
            id=int(r["id"]),
            created_at=str(r["created_at"]),
            title=str(r["title"]),
            intent_text=r["intent_text"],
        )
        for r in rows
    ]


def get_project(conn: sqlite3.Connection, project_id: int) -> ProjectItem | None:
    r = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if r is None:
        return None
    return ProjectItem(
        id=int(r["id"]),
        created_at=str(r["created_at"]),
        title=str(r["title"]),
        intent_text=r["intent_text"],
    )


def insert_media(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    original_name: str,
    stored_name: str,
    content_type: str | None,
    size_bytes: int,
) -> int:
    created_at = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO media (project_id, original_name, stored_name, content_type, size_bytes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, original_name, stored_name, content_type, size_bytes, created_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_media(conn: sqlite3.Connection, *, project_id: int | None = None) -> list[MediaItem]:
    if project_id is None:
        rows = conn.execute("SELECT * FROM media ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM media WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall()

    items: list[MediaItem] = []
    for r in rows:
        pid = r["project_id"]
        if pid is None:
            # Legacy data should have been migrated, but keep this defensive.
            pid = ensure_default_project(conn)
        items.append(
            MediaItem(
                id=int(r["id"]),
                project_id=int(pid),
                original_name=str(r["original_name"]),
                stored_name=str(r["stored_name"]),
                content_type=r["content_type"],
                size_bytes=int(r["size_bytes"]),
                created_at=str(r["created_at"]),
            )
        )
    return items


def get_media(conn: sqlite3.Connection, media_id: int) -> MediaItem | None:
    r = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if r is None:
        return None

    pid = r["project_id"]
    if pid is None:
        pid = ensure_default_project(conn)

    return MediaItem(
        id=int(r["id"]),
        project_id=int(pid),
        original_name=str(r["original_name"]),
        stored_name=str(r["stored_name"]),
        content_type=r["content_type"],
        size_bytes=int(r["size_bytes"]),
        created_at=str(r["created_at"]),
    )


def insert_plan(conn: sqlite3.Connection, *, project_id: int, model: str, plan_json: str) -> int:
    created_at = _utc_now_iso()
    cur = conn.execute(
        "INSERT INTO plans (project_id, created_at, model, plan_json) VALUES (?, ?, ?, ?)",
        (project_id, created_at, model, plan_json),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_plans_for_project(conn: sqlite3.Connection, *, project_id: int) -> list[PlanItem]:
    rows = conn.execute(
        "SELECT * FROM plans WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return [
        PlanItem(
            id=int(r["id"]),
            project_id=int(r["project_id"]),
            created_at=str(r["created_at"]),
            model=str(r["model"]),
            plan_json=str(r["plan_json"]),
        )
        for r in rows
    ]


def get_plan_for_project(conn: sqlite3.Connection, *, project_id: int, plan_id: int) -> PlanItem | None:
    r = conn.execute(
        "SELECT * FROM plans WHERE id = ? AND project_id = ?",
        (plan_id, project_id),
    ).fetchone()
    if r is None:
        return None
    return PlanItem(
        id=int(r["id"]),
        project_id=int(r["project_id"]),
        created_at=str(r["created_at"]),
        model=str(r["model"]),
        plan_json=str(r["plan_json"]),
    )


def list_plans_for_project(conn: sqlite3.Connection, *, project_id: int) -> list[PlanItem]:
    rows = conn.execute(
        "SELECT * FROM plans WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return [
        PlanItem(
            id=int(r["id"]),
            project_id=int(r["project_id"]),
            created_at=str(r["created_at"]),
            model=str(r["model"]),
            plan_json=str(r["plan_json"]),
        )
        for r in rows
    ]
