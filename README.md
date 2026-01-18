# help-me-post

A small Flask + SQLite web app to help creators generate platform-specific posting plans from uploaded media and a short intent.

## Goals
- Upload images/videos
- Provide a short intent
- Generate platform-specific post plans (no auto-posting)

## Quickstart (Linux)
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set required env vars (at least OPENAI_API_KEY) via your shell or Apache SetEnv.
export FLASK_APP=wsgi.py
export FLASK_ENV=development
flask run
```

Then open `http://127.0.0.1:5000`.

## Notes
- No auth/OAuth.
- AI calls are isolated behind `app/ai/client.py`.
- Platform logic lives in `app/planners/`.
