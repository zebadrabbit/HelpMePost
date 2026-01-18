from app import create_app


def test_home_returns_200(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "smoke.sqlite3"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    app = create_app()
    app.config.update(TESTING=True)

    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert 'name="builder-platform"' in html
    assert 'id="builder-platform-bluesky"' in html
    assert 'id="builder-platform-youtube"' in html
    assert 'id="gen-bluesky"' in html
    assert 'id="gen-both"' in html
    assert 'id="gen-youtube"' not in html
