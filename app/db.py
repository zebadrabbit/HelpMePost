"""Compatibility shim.

The DB layer was moved to the `app.db` package (see `app/db/db.py`).
This module remains to avoid breakage for any early adopters importing `app.db`.
"""

from app.db.db import *  # noqa: F403
