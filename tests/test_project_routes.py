import io
import json
import re
import sqlite3
import importlib

from app import create_app


_HASHTAG_RE = re.compile(r"(?<!\\w)#([A-Za-z0-9_]+)")


def _extract_hashtags_from_text(text: str) -> list[str]:
    if not text:
        return []
    return _HASHTAG_RE.findall(text)


def _good_plan():
    return {
        "bluesky": {
            "text": "Hello world #petdefender #petsafety",
            "hashtags": ["petdefender", "petsafety"],
            "alt_text": ["A close-up of a chair wheel guard."],
        },
        "youtube": {
            "title": "Pet Defender demo",
            "description": "Short intro paragraph.\n\nSecond paragraph with details.",
            "tags": ["pet defender", "pets", "safety", "chair", "wheels", "3d printing", "prototype", "maker"],
            "category": "Pets & Animals",
        },
    }


class _FakeAIClient:
    def __init__(self, *, model=None, api_key=None):
        self.model = model or "gpt-4o-mini"

    def generate_plan(self, **_kwargs):
        from app.ai.client import PlanGenerationResult

        return PlanGenerationResult(ok=True, plan=_good_plan(), warnings=[], error=None)


class _FakeAIClientInvalidJson:
    def __init__(self, *, model=None, api_key=None):
        self.model = model or "gpt-4o-mini"

    def generate_plan(self, **_kwargs):
        from app.ai.client import AIError, PlanGenerationResult

        return PlanGenerationResult(
            ok=False,
            plan=None,
            warnings=[],
            error=AIError(error_type="invalid_json", human_message="AI generation failed: response was not valid JSON."),
        )


class _FakeAIClientWithBannedHashtags:
    def __init__(self, *, model=None, api_key=None):
        self.model = model or "fake"

    def generate_plan(self, **_kwargs):
        from app.ai.client import PlanGenerationResult

        plan = {
            "bluesky": {
                "text": "Shipping a Flask + Bluesky update.\n\n#creators #content",
                "hashtags": ["creators", "content"],
                "alt_text": ["File: a.txt"],
            },
        }
        return PlanGenerationResult(ok=True, plan=plan, warnings=[], error=None)


def _make_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    # Tests should not depend on external AI.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    routes_mod = importlib.import_module("app.web.routes")
    monkeypatch.setattr(routes_mod, "AIClient", _FakeAIClient)

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), db_path


def test_create_project(tmp_path, monkeypatch):
    client, _db_path = _make_client(tmp_path, monkeypatch)

    resp = client.post(
        "/api/projects",
        json={"title": "", "intent_text": "Make a post about my clip"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["project"]["id"]
    assert data["project"]["intent_text"] == "Make a post about my clip"


def test_upload_media_assigned_to_project_and_scoped_listing(tmp_path, monkeypatch):
    client, db_path = _make_client(tmp_path, monkeypatch)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]
    p2 = client.post("/api/projects", json={"title": "P2", "intent_text": "Intent"}).get_json()["project"]

    file_data = {"file": (io.BytesIO(b"abc"), "a.txt")}
    resp = client.post(f"/api/projects/{p['id']}/upload", data=file_data, content_type="multipart/form-data")
    assert resp.status_code == 200
    uploaded = resp.get_json()
    assert uploaded["project_id"] == p["id"]

    # Listing is project-scoped.
    resp_list = client.get(f"/api/projects/{p['id']}/media")
    assert resp_list.status_code == 200
    items = resp_list.get_json()["items"]
    assert len(items) == 1
    assert items[0]["project_id"] == p["id"]

    resp_list2 = client.get(f"/api/projects/{p2['id']}/media")
    assert resp_list2.status_code == 200
    assert resp_list2.get_json()["items"] == []

    # DB check: media row has matching project_id.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT project_id FROM media WHERE id = ?", (uploaded["id"],)).fetchone()
        assert row is not None
        assert int(row["project_id"]) == int(p["id"])
    finally:
        conn.close()


def test_generate_requires_selected_media_ids_and_stores_plan(tmp_path, monkeypatch):
    client, db_path = _make_client(tmp_path, monkeypatch)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]

    # Upload one media.
    file_data = {"file": (io.BytesIO(b"abc"), "a.txt")}
    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data=file_data,
        content_type="multipart/form-data",
    ).get_json()

    # Missing selected_media_ids -> 400
    bad = client.post(f"/api/projects/{p['id']}/generate", json={"intent_text": "x"})
    assert bad.status_code == 400

    # Empty selected_media_ids -> 400
    bad2 = client.post(f"/api/projects/{p['id']}/generate", json={"intent_text": "x", "selected_media_ids": []})
    assert bad2.status_code == 400

    # Success
    ok = client.post(
        f"/api/projects/{p['id']}/generate",
        json={"intent_text": "x", "selected_media_ids": [uploaded["id"]]},
    )
    assert ok.status_code == 200
    plan = ok.get_json()
    assert plan["project_id"] == p["id"]
    assert plan["id"]

    # DB check: plan stored.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan["id"],)).fetchone()
        assert row is not None
        assert int(row["project_id"]) == int(p["id"])
        assert row["model"]
        stored = json.loads(row["plan_json"])
        assert "bluesky" in stored and "youtube" in stored
    finally:
        conn.close()


def test_delete_media_removes_db_row_and_file(tmp_path, monkeypatch):
    client, db_path = _make_client(tmp_path, monkeypatch)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]

    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    # Lookup stored_name so we can verify the file is deleted.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT stored_name FROM media WHERE id = ?", (uploaded["id"],)).fetchone()
        assert row is not None
        stored_name = str(row["stored_name"])
    finally:
        conn.close()

    upload_path = tmp_path / "uploads" / stored_name
    assert upload_path.exists()

    resp = client.delete(f"/api/projects/{p['id']}/media/{uploaded['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Gone from listing.
    items = client.get(f"/api/projects/{p['id']}/media").get_json()["items"]
    assert items == []

    # Gone from file serving endpoint.
    gone = client.get(f"/media/{uploaded['id']}")
    assert gone.status_code == 404

    # File removed from disk.
    assert not upload_path.exists()


def test_generate_bluesky_only_omits_youtube_in_response_and_storage(tmp_path, monkeypatch):
    client, db_path = _make_client(tmp_path, monkeypatch)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]

    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    ok = client.post(
        f"/api/projects/{p['id']}/generate",
        json={
            "intent_text": "x",
            "selected_media_ids": [uploaded["id"]],
            "generate_targets": ["bluesky"],
        },
    )
    assert ok.status_code == 200
    data = ok.get_json()

    assert data["ok"] is True
    assert data.get("meta", {}).get("targets") == ["bluesky"]
    assert "bluesky" in data
    assert "youtube" not in data

    # DB check: stored plan_json should only include requested sections.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT plan_json FROM plans WHERE id = ?", (data["id"],)).fetchone()
        assert row is not None
        stored = json.loads(row["plan_json"])
        assert "bluesky" in stored
        assert "youtube" not in stored
        assert stored.get("meta", {}).get("targets") == ["bluesky"]
    finally:
        conn.close()


def test_plan_history_is_project_scoped(tmp_path, monkeypatch):
    client, _db_path = _make_client(tmp_path, monkeypatch)

    p1 = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]
    p2 = client.post("/api/projects", json={"title": "P2", "intent_text": "Intent"}).get_json()["project"]

    up1 = client.post(
        f"/api/projects/{p1['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    up2 = client.post(
        f"/api/projects/{p2['id']}/upload",
        data={"file": (io.BytesIO(b"def"), "b.txt")},
        content_type="multipart/form-data",
    ).get_json()

    plan1 = client.post(
        f"/api/projects/{p1['id']}/generate",
        json={"intent_text": "x", "selected_media_ids": [up1["id"]]},
    ).get_json()

    plan2 = client.post(
        f"/api/projects/{p2['id']}/generate",
        json={"intent_text": "y", "selected_media_ids": [up2["id"]]},
    ).get_json()

    # List scoped.
    l1 = client.get(f"/api/projects/{p1['id']}/plans").get_json()["items"]
    assert all(item["id"] != plan2["id"] for item in l1)

    l2 = client.get(f"/api/projects/{p2['id']}/plans").get_json()["items"]
    assert all(item["id"] != plan1["id"] for item in l2)

    # Cannot fetch across projects.
    cross = client.get(f"/api/projects/{p1['id']}/plans/{plan2['id']}")
    assert cross.status_code == 404


def test_generate_returns_ok_false_on_invalid_json(tmp_path, monkeypatch):
    client, _db_path = _make_client(tmp_path, monkeypatch)

    # Override AIClient for this test to simulate invalid_json.
    routes_mod = importlib.import_module("app.web.routes")
    monkeypatch.setattr(routes_mod, "AIClient", _FakeAIClientInvalidJson)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Intent"}).get_json()["project"]
    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.post(
        f"/api/projects/{p['id']}/generate",
        json={"intent_text": "x", "selected_media_ids": [uploaded["id"]]},
    )
    assert resp.status_code == 502
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"]["error_type"] == "invalid_json"


def test_generate_template_mode_succeeds_without_api_key(tmp_path, monkeypatch):
    # Do not patch AIClient to a success stub: we want to ensure template_mode skips AI entirely.
    db_path = tmp_path / "test.sqlite3"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    routes_mod = importlib.import_module("app.web.routes")

    class _ExplodingAIClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("AIClient should not be constructed in template_mode")

    monkeypatch.setattr(routes_mod, "AIClient", _ExplodingAIClient)

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Demo"}).get_json()["project"]
    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.post(
        f"/api/projects/{p['id']}/generate",
        json={
            "intent_text": "Focus: Demo",
            "selected_media_ids": [uploaded["id"]],
            "template_mode": True,
            "add_emojis": True,
            "include_cta": True,
            "cta_target": "@firetailfab.com",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("meta", {}).get("is_template") is True

    # CTA should be present when enabled.
    assert "Follow" in (data.get("bluesky", {}).get("text") or "")
    assert "@firetailfab.com" in (data.get("bluesky", {}).get("text") or "")
    assert "Follow" in (data.get("youtube", {}).get("description") or "")
    assert "@firetailfab.com" in (data.get("youtube", {}).get("description") or "")

    # Emoji toggle is allowed to add light emojis in template mode.
    yt_title = (data.get("youtube", {}).get("title") or "")
    assert "🎬" in yt_title

    # Hashtag single source of truth: inline hashtags must match array exactly.
    bsky = data.get("bluesky", {})
    inline = _extract_hashtags_from_text(bsky.get("text") or "")
    assert inline == (bsky.get("hashtags") or [])

    from app.ai.plan_validation import validate_plan

    assert validate_plan(data).ok is True


def test_generate_ai_mode_drops_banned_generic_hashtags_when_not_production_related(tmp_path, monkeypatch):
    client, _db_path = _make_client(tmp_path, monkeypatch)

    routes_mod = importlib.import_module("app.web.routes")
    monkeypatch.setattr(routes_mod, "AIClient", _FakeAIClientWithBannedHashtags)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Flask + Bluesky post builder"}).get_json()["project"]
    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.post(
        f"/api/projects/{p['id']}/generate",
        json={"intent_text": "Focus: Flask + Bluesky post builder", "selected_media_ids": [uploaded["id"]], "generate_targets": ["bluesky"]},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    tags = data.get("bluesky", {}).get("hashtags")
    assert isinstance(tags, list)
    assert 2 <= len(tags) <= 5
    assert all(isinstance(t, str) and t and "#" not in t for t in tags)
    assert "creators" not in [t.lower() for t in tags]
    assert "content" not in [t.lower() for t in tags]

    # Hashtag single source of truth: inline hashtags must match array exactly.
    bsky = data.get("bluesky", {})
    inline = _extract_hashtags_from_text(bsky.get("text") or "")
    assert inline == (bsky.get("hashtags") or [])


def test_generate_ai_mode_injects_cta_target_when_ai_omits_it(tmp_path, monkeypatch):
    client, _db_path = _make_client(tmp_path, monkeypatch)

    # Override AIClient for this test to simulate an AI plan that forgets to include the CTA target.
    routes_mod = importlib.import_module("app.web.routes")

    from app.ai.client import PlanGenerationResult

    class _FakeAIClientMissingCta:
        def __init__(self, *args, **kwargs):
            self.model = "fake"

        def generate_plan(self, **_kwargs):
            plan = {
                "bluesky": {
                    "text": "A short post.\n\n#demo #update",
                    "hashtags": ["demo", "update"],
                    "alt_text": ["File: a.txt"],
                },
                "youtube": {
                    "title": "Demo",
                    "description": "Paragraph one.\n\nParagraph two.",
                    "tags": ["demo"] * 8,
                    "category": "People & Blogs",
                },
            }
            return PlanGenerationResult(ok=True, plan=plan, warnings=[], error=None)

    monkeypatch.setattr(routes_mod, "AIClient", _FakeAIClientMissingCta)

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Demo"}).get_json()["project"]
    uploaded = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    ).get_json()

    target = "@firetailfab.com"
    resp = client.post(
        f"/api/projects/{p['id']}/generate",
        json={
            "intent_text": "Focus: Demo",
            "selected_media_ids": [uploaded["id"]],
            "include_cta": True,
            "cta_target": target,
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True

    # Backend should guarantee the exact target string appears even if AI forgot.
    assert target in (data.get("bluesky", {}).get("text") or "")
    assert target in (data.get("youtube", {}).get("description") or "")
