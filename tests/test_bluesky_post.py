import io
import importlib
import random

from PIL import Image


def _upload_image(client, project_id: int, name: str, content_type: str = "image/png"):
    return client.post(
        f"/api/projects/{project_id}/upload",
        data={"file": (io.BytesIO(b"img-bytes"), name, content_type)},
        content_type="multipart/form-data",
    ).get_json()


def test_bluesky_post_rejects_more_than_4_images(tmp_path, monkeypatch):
    from app import create_app

    db_path = tmp_path / "test.sqlite3"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Demo"}).get_json()["project"]

    ids = []
    for i in range(5):
        up = _upload_image(client, p["id"], f"{i}.png")
        ids.append(up["id"])

    resp = client.post(
        f"/api/projects/{p['id']}/bluesky_post",
        json={
            "identifier": "me.bsky.social",
            "app_password": "xxxx-xxxx-xxxx-xxxx",
            "text": "Hello",
            "selected_media_ids": ids,
        },
    )
    assert resp.status_code == 400
    assert "up to 4" in resp.get_json()["error"].lower()


def test_bluesky_post_happy_path_mocks_requests(tmp_path, monkeypatch):
    from app import create_app

    db_path = tmp_path / "test.sqlite3"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Demo"}).get_json()["project"]

    up1 = _upload_image(client, p["id"], "a.png")
    up2 = _upload_image(client, p["id"], "b.png")

    # Mock requests.post used by the Bluesky integration module.
    bluesky_mod = importlib.import_module("app.integrations.bluesky")

    calls = []

    class _Resp:
        def __init__(self, status_code, payload, headers=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/xrpc/com.atproto.server.createSession"):
            return _Resp(200, {"accessJwt": "jwt", "did": "did:plc:123"})
        if url.endswith("/xrpc/com.atproto.repo.uploadBlob"):
            return _Resp(200, {"blob": {"$type": "blob", "ref": {"$link": "abc"}}})
        if url.endswith("/xrpc/com.atproto.repo.createRecord"):
            return _Resp(200, {"uri": "at://did:plc:123/app.bsky.feed.post/xyz", "cid": "cid123"})
        return _Resp(500, {"error": "unexpected"}, text="unexpected")

    monkeypatch.setattr(bluesky_mod.requests, "post", fake_post)

    resp = client.post(
        f"/api/projects/{p['id']}/bluesky_post",
        json={
            "identifier": "me.bsky.social",
            "app_password": "xxxx-xxxx-xxxx-xxxx",
            "text": "Hello",
            "selected_media_ids": [up1["id"], up2["id"]],
            "alt_text": ["Alt A", "Alt B"],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["uri"]
    assert data["cid"]

    # Verify createRecord payload contains correct embed type and images length.
    create_calls = [c for c in calls if c[0].endswith("/xrpc/com.atproto.repo.createRecord")]
    assert len(create_calls) == 1
    payload = create_calls[0][1]["json"]
    assert payload["collection"] == "app.bsky.feed.post"
    record = payload["record"]
    assert record["embed"]["$type"] == "app.bsky.embed.images"
    assert len(record["embed"]["images"]) == 2


def test_bluesky_post_optimizes_large_image_before_upload(tmp_path, monkeypatch):
    from app import create_app

    db_path = tmp_path / "test.sqlite3"
    upload_dir = tmp_path / "uploads"

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    p = client.post("/api/projects", json={"title": "P1", "intent_text": "Focus: Demo"}).get_json()["project"]

    # Create a deterministic hard-to-compress PNG (>1MB) to trigger optimization.
    w, h = 1800, 1800
    rng = random.Random(0)
    raw = rng.randbytes(w * h * 3)
    im = Image.frombytes("RGB", (w, h), raw)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)

    up = client.post(
        f"/api/projects/{p['id']}/upload",
        data={"file": (buf, "big.png", "image/png")},
        content_type="multipart/form-data",
    ).get_json()

    assert up["size_bytes"] > 1_000_000

    # Mock requests.post used by the Bluesky integration module.
    bluesky_mod = importlib.import_module("app.integrations.bluesky")

    calls = []

    class _Resp:
        def __init__(self, status_code, payload, headers=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/xrpc/com.atproto.server.createSession"):
            return _Resp(200, {"accessJwt": "jwt", "did": "did:plc:123"})
        if url.endswith("/xrpc/com.atproto.repo.uploadBlob"):
            # Optimizer should have converted to JPEG and compressed under the limit.
            assert kwargs["headers"]["Content-Type"] == "image/jpeg"
            assert len(kwargs["data"]) <= 1_000_000
            return _Resp(200, {"blob": {"$type": "blob", "ref": {"$link": "abc"}}})
        if url.endswith("/xrpc/com.atproto.repo.createRecord"):
            return _Resp(200, {"uri": "at://did:plc:123/app.bsky.feed.post/xyz", "cid": "cid123"})
        return _Resp(500, {"error": "unexpected"}, text="unexpected")

    monkeypatch.setattr(bluesky_mod.requests, "post", fake_post)

    resp = client.post(
        f"/api/projects/{p['id']}/bluesky_post",
        json={
            "identifier": "me.bsky.social",
            "app_password": "xxxx-xxxx-xxxx-xxxx",
            "text": "Link: https://github.com/zebadrabbit/HelpMePost",
            "selected_media_ids": [up["id"]],
            "alt_text": ["Alt A"],
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("optimization", {}).get("compressed_images") == 1

    # Verify createRecord includes link facets so the URL is clickable.
    create_calls = [c for c in calls if c[0].endswith("/xrpc/com.atproto.repo.createRecord")]
    assert len(create_calls) == 1
    record = create_calls[0][1]["json"]["record"]
    assert "facets" in record
    assert isinstance(record["facets"], list) and len(record["facets"]) >= 1
