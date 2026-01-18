from __future__ import annotations

import os
from pathlib import Path
from flask import Flask

from .db import init_db
from .web.routes import web


def create_app() -> Flask:
    # Make local development reliable: load `.env` if present.
    # Flask CLI can also load this via python-dotenv, but that does not apply to
    # other entrypoints (e.g., mod_wsgi, gunicorn, `python wsgi.py`, tests).
    try:
        from dotenv import load_dotenv  # type: ignore

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:
        pass

    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "help_me_post.sqlite3")),
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", os.path.join(app.instance_path, "uploads")),
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", str(1024 * 1024 * 512))),  # 512MB
    )

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    init_db(app)

    app.register_blueprint(web)

    return app
