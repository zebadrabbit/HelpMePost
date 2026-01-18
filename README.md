# HelpMePost

HelpMePost is a small web app that helps you turn one idea + a few uploads (images/videos) into a ready-to-post draft.

If you want a plain-language walkthrough, start with [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

You can use it two ways:
- **Template Draft (no AI)**: works offline and doesn’t need an API key.
- **AI Draft**: uses an OpenAI key to generate more tailored copy.

It also supports posting to **Bluesky** (images only) if you provide your handle + an App Password.

## How to use (in the browser)

1. Open the app in your browser.
2. Upload your images/videos.
3. Fill in **Focus** (what the post is about).
4. (Optional) Add **Audience**, **Tone**, and **Tags/hashtags**.
5. Choose options:
	- **Template Draft (no AI)** if you don’t want to use an API key.
	- **Add emojis** (light touch)
	- **Call-to-action** (CTA): if enabled, you must provide a link or @handle.
6. Click **Generate**.
7. Copy the draft text.

### Bluesky posting (optional)

If you want HelpMePost to post the result to Bluesky:
- Select **1–4 images** (videos aren’t supported for posting).
- Enter your Bluesky handle and an **App Password** (recommended by Bluesky).
- Click **Post to Bluesky**.

Notes:
- The app does **not** use your main Bluesky password.
- If an image is too large for Bluesky’s upload limits, the app will try to compress it.

## “Why are there hashtags I didn’t pick?”

When generating a draft, the app may suggest extra hashtags/keywords to improve reach based on your focus text.

If you prefer strict control, you can later add a “lock hashtags” mode (only the tags you typed/clicked).

## Install & run (simple local setup)

You only need Python.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Load variables from .env into your shell (this repo does not auto-load .env)
set -a
. ./.env
set +a

export FLASK_APP=wsgi.py
flask run
```

Then open `http://127.0.0.1:5000`.

### Template Draft mode (no API key)

If you don’t set `OPENAI_API_KEY`, you can still use the app by enabling **Template Draft (no AI)** in the UI.

## Configuration (optional)

These are optional environment variables that customize the landing page (suggestions + default switches):

- `HMP_AUDIENCE_SUGGESTIONS` — comma-separated list (or JSON list)
- `HMP_TAG_SUGGESTIONS` — comma-separated list (or JSON list)
- `HMP_TONE_SUGGESTIONS` — comma-separated list (or JSON list)
- `HMP_DEFAULT_TEMPLATE_MODE` — `0` or `1`
- `HMP_DEFAULT_ADD_EMOJIS` — `0` or `1`
- `HMP_DEFAULT_INCLUDE_CTA` — `0` or `1`
- `HMP_DEFAULT_CTA_TARGET` — default CTA destination (e.g. `@your-handle`)

## Privacy & safety notes

- This app is intended for personal/small-team use.
- Uploaded files and the SQLite database are stored on the machine running the app (under `instance/`).
- Never commit secrets. Keep `.env` out of git (this repo already ignores it).

## Production deployment

If you want to deploy this on a Linux server behind Apache, see [docs/APACHE.md](docs/APACHE.md).
