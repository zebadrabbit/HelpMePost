import sqlite3

from app import create_app


def test_startup_migrates_legacy_media_db(tmp_path, monkeypatch):
    # Create a legacy DB: media table exists, no projects/plans, no media.project_id.
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO media (original_name, stored_name, content_type, size_bytes, created_at)
            VALUES ('old.png', 'old.png', 'image/png', 123, '2020-01-01T00:00:00+00:00');
            """
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    create_app()

    # Trigger init_db/migrations (runs during create_app). Now verify.
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    try:
        projects = conn2.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
        assert len(projects) >= 1
        assert projects[0]["title"] == "Imported Workspace"

        media_rows = conn2.execute("SELECT * FROM media").fetchall()
        assert len(media_rows) == 1
        assert media_rows[0]["project_id"] is not None
        assert int(media_rows[0]["project_id"]) == int(projects[0]["id"])

        # plans table exists even if empty.
        conn2.execute("SELECT * FROM plans").fetchall()
    finally:
        conn2.close()
