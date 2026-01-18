# Deploying on Linux with Apache + mod_wsgi (no Docker)

This guide describes a simple, production-style deployment of this Flask app behind Apache using mod_wsgi.

It aims to be copy/paste friendly and distro-agnostic. Adjust paths and service names for your OS.

## 1) Assumptions / prerequisites

- Linux server with Apache installed
  - Debian/Ubuntu: `apache2`
  - RHEL/Fedora/CentOS: `httpd`
- `mod_wsgi` installed **for the same Python you will run your app with**
  - Prefer the packaged `libapache2-mod-wsgi-py3` / `mod_wsgi` where possible.
  - If you compile/install `mod_wsgi` yourself, ensure it targets your Python version.
- Repo checked out to a stable path, e.g.:
  - `/var/www/help-me-post`
- A Python virtualenv created inside the repo:
  - `/var/www/help-me-post/.venv`

Example setup:

```bash
sudo mkdir -p /var/www/help-me-post
sudo chown -R $USER:$USER /var/www/help-me-post
cd /var/www/help-me-post
# (git clone your fork here)

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 2) Recommended directory layout + permissions

This app uses Flask’s `instance` directory for runtime state by default:

- `instance/` must be writable by the Apache user
- `instance/uploads/` must be writable (uploaded media)
- `instance/*.sqlite3` must be writable (SQLite DB file)

Recommended layout:

```
/var/www/help-me-post/
  app/
  docs/
  tests/
  wsgi.py
  requirements.txt
  instance/
    help_me_post.sqlite3
    uploads/
```

Create the directories:

```bash
sudo mkdir -p /var/www/help-me-post/instance/uploads
```

### Ownership and why it matters

Apache/mod_wsgi runs the app under the Apache service user (commonly `www-data` on Debian/Ubuntu, or `apache` on RHEL-derived distros). That process needs write access to `instance/` so it can:

- create or update the SQLite database
- write uploaded files to `instance/uploads/`

Set ownership to your Apache user:

Debian/Ubuntu:

```bash
sudo chown -R www-data:www-data /var/www/help-me-post/instance
sudo chmod -R u+rwX,g+rwX,o-rwx /var/www/help-me-post/instance
```

RHEL/Fedora/CentOS:

```bash
sudo chown -R apache:apache /var/www/help-me-post/instance
sudo chmod -R u+rwX,g+rwX,o-rwx /var/www/help-me-post/instance
```

Notes:
- Keep the rest of the repo readable by Apache, but **only** `instance/` needs to be writable.
- If you use SELinux (common on RHEL/Fedora), you may also need to set an appropriate context for write access to `instance/`.

## 3) Environment variables

The app reads configuration from environment variables (no Docker required). Common ones:

- `OPENAI_API_KEY` (required for real AI calls; if missing, the app returns stub results)
- `OPENAI_MODEL` (optional; default is set in the app)
- `SECRET_KEY` (recommended in production)
- `DATABASE_PATH` (optional; defaults to `<instance>/help_me_post.sqlite3`)
- `UPLOAD_DIR` (optional; defaults to `<instance>/uploads`)
- `MAX_CONTENT_LENGTH` (optional; default is 512MB)

### Using a `.env` file vs Apache `SetEnv`

Important: this repository does **not** include `python-dotenv`, so the app will **not automatically** load a `.env` file.

- A `.env` file can still be useful for **local development** (where you export variables in your shell).
- For Apache/mod_wsgi, the practical approach is to set environment variables in your Apache VirtualHost using `SetEnv` (or `PassEnv`).

Example `SetEnv` directives:

```apache
# Never commit secrets. Do not put real keys in git.
SetEnv OPENAI_API_KEY "YOUR_KEY_HERE"
SetEnv OPENAI_MODEL "gpt-4.1-mini"
SetEnv SECRET_KEY "a-long-random-secret"

# Optional explicit paths (recommended to avoid ambiguity)
SetEnv DATABASE_PATH "/var/www/help-me-post/instance/help_me_post.sqlite3"
SetEnv UPLOAD_DIR "/var/www/help-me-post/instance/uploads"

# Optional: allow larger uploads (bytes)
SetEnv MAX_CONTENT_LENGTH "536870912"
```

### `.env.example`

If your project workflow expects a `.env.example`, create one that documents the variables above and keep real secrets out of version control. Add `.env` to `.gitignore`.

## 4) WSGI entrypoint

This repo already includes a WSGI entrypoint at `wsgi.py`.

A minimal `wsgi.py` should look like:

```python
from app import create_app

app = create_app()
```

Apache/mod_wsgi will import `app` from this module.

## 5) Apache VirtualHost example

Below is a minimal, non-SSL VirtualHost example. SSL/TLS can be handled separately (e.g., with Let’s Encrypt + a TLS vhost).

Create a site config (path varies by distro):

- Debian/Ubuntu: `/etc/apache2/sites-available/help-me-post.conf`
- RHEL/Fedora: `/etc/httpd/conf.d/help-me-post.conf`

Example configuration:

```apache
<VirtualHost *:80>
    ServerName help-me-post.example.com

    # Point these to your repo + venv.
    # Ensure python-home matches the venv created with python3.
    WSGIDaemonProcess help-me-post \
        python-home=/var/www/help-me-post/.venv \
        python-path=/var/www/help-me-post \
        processes=2 threads=10

    WSGIProcessGroup help-me-post
    WSGIScriptAlias / /var/www/help-me-post/wsgi.py

    # Environment variables for the app
    SetEnv OPENAI_API_KEY "YOUR_KEY_HERE"
    SetEnv OPENAI_MODEL "gpt-4.1-mini"
    SetEnv SECRET_KEY "a-long-random-secret"
    SetEnv DATABASE_PATH "/var/www/help-me-post/instance/help_me_post.sqlite3"
    SetEnv UPLOAD_DIR "/var/www/help-me-post/instance/uploads"

    # Upload limits: Apache + Flask both matter.
    # Apache: limit request body (bytes). Adjust as needed.
    LimitRequestBody 536870912

    <Directory /var/www/help-me-post>
        Require all granted
    </Directory>

    # Optional: serve static files directly via Apache.
    # This is not required (Flask can serve /static), but is common in production.
    Alias /static/ /var/www/help-me-post/app/web/static/
    <Directory /var/www/help-me-post/app/web/static>
        Require all granted
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/help-me-post-error.log
    CustomLog ${APACHE_LOG_DIR}/help-me-post-access.log combined
</VirtualHost>
```

Enable and restart (Debian/Ubuntu example):

```bash
sudo a2enmod wsgi
sudo a2ensite help-me-post
sudo systemctl reload apache2
```

RHEL/Fedora example:

```bash
sudo systemctl restart httpd
```

## 6) Common failure modes / troubleshooting checklist

### Permissions errors (SQLite / uploads)

Symptoms:
- 500 errors
- logs show `OperationalError: unable to open database file`
- logs show `Permission denied` writing uploads

Checks:
- `instance/` is writable by the Apache user (`www-data` / `apache`)
- `instance/uploads/` exists and is writable
- `DATABASE_PATH` and `UPLOAD_DIR` point to real paths

### Python / mod_wsgi mismatch

Symptoms:
- import errors for packages installed in your venv
- mod_wsgi loads but can’t find Flask or your modules

Checks:
- `WSGIDaemonProcess ... python-home=/path/to/.venv` is correct
- `python-path=/var/www/help-me-post` points at the repo root (so `import app` works)
- mod_wsgi is installed for Python 3 and compatible with your Apache build

### Missing environment variables

Symptoms:
- AI generation returns stub results unexpectedly

Checks:
- `SetEnv OPENAI_API_KEY` is present and correct
- Avoid putting secrets in shell profiles and assuming Apache sees them; Apache runs as a service with its own environment

### Upload/request size limits

Symptoms:
- uploads fail with 413 Request Entity Too Large
- uploads hang or are cut off

Places to tune:
- Apache: `LimitRequestBody` (in bytes)
- Flask: `MAX_CONTENT_LENGTH` (in bytes; this app defaults to 512MB)

Also consider:
- Apache timeouts for slow uploads (distro defaults vary)

### Where to look for logs

- Debian/Ubuntu:
  - `/var/log/apache2/help-me-post-error.log`
- RHEL/Fedora:
  - `/var/log/httpd/help-me-post-error.log`

Start troubleshooting by checking the Apache error log immediately after reproducing a failure.
