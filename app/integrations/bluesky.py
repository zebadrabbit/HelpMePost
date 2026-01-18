from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


BSKY_BASE = "https://bsky.social"


@dataclass(frozen=True)
class BlueskyPostResult:
    uri: str
    cid: str


class BlueskyAPIError(RuntimeError):
    pass


_URL_RE = re.compile(r"https?://[^\s]+")


def build_link_facets(text: str) -> list[dict[str, Any]]:
    """Build ATProto link facets for URLs in text.

    Bluesky clients will always make these clickable even if their auto-linking
    heuristics don't trigger.

    NOTE: facet byte offsets are UTF-8 byte indices.
    """

    if not text:
        return []

    facets: list[dict[str, Any]] = []
    for m in _URL_RE.finditer(text):
        url = m.group(0)
        # Trim common trailing punctuation that shouldn't be part of the URL.
        trimmed = url.rstrip(").,;:!?]\"'")
        if not trimmed:
            continue

        start = m.start(0)
        end = start + len(trimmed)

        byte_start = len(text[:start].encode("utf-8"))
        byte_end = len(text[:end].encode("utf-8"))

        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [
                    {
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": trimmed,
                    }
                ],
            }
        )

    return facets


def _utc_iso_z() -> str:
    # Example: 2026-01-17T18:03:12.123456Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_error_message(resp: requests.Response) -> str:
    """Best-effort extraction of a useful error message (no secrets)."""
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                # OpenAI-style wrapper isn't expected here, but keep generic.
                msg = err.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
            msg = payload.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        return json.dumps(payload)
    except Exception:
        text = (resp.text or "").strip()
        return text if text else f"HTTP {resp.status_code}"


def create_session(*, identifier: str, app_password: str) -> tuple[str, str]:
    """Create a temporary session.

    Returns (accessJwt, did). Caller must not persist them.
    """
    url = f"{BSKY_BASE}/xrpc/com.atproto.server.createSession"
    resp = requests.post(url, json={"identifier": identifier, "password": app_password}, timeout=30)
    if resp.status_code != 200:
        raise BlueskyAPIError(f"Bluesky login failed: {_clean_error_message(resp)}")

    data: Any = resp.json()
    try:
        access_jwt = str(data["accessJwt"])
        did = str(data["did"])
    except Exception as e:
        raise BlueskyAPIError("Bluesky login failed: unexpected response format") from e

    return access_jwt, did


def upload_blob(*, access_jwt: str, content_type: str, data: bytes) -> dict[str, Any]:
    url = f"{BSKY_BASE}/xrpc/com.atproto.repo.uploadBlob"
    headers = {
        "Authorization": f"Bearer {access_jwt}",
        "Content-Type": content_type,
    }
    resp = requests.post(url, headers=headers, data=data, timeout=60)
    if resp.status_code != 200:
        raise BlueskyAPIError(f"Bluesky upload failed: {_clean_error_message(resp)}")

    payload: Any = resp.json()
    blob = payload.get("blob") if isinstance(payload, dict) else None
    if not isinstance(blob, dict):
        raise BlueskyAPIError("Bluesky upload failed: missing blob in response")
    return blob


def create_post_with_images(
    *,
    access_jwt: str,
    did: str,
    text: str,
    images: list[dict[str, Any]],
    facets: list[dict[str, Any]] | None = None,
) -> BlueskyPostResult:
    url = f"{BSKY_BASE}/xrpc/com.atproto.repo.createRecord"
    headers = {
        "Authorization": f"Bearer {access_jwt}",
        "Content-Type": "application/json",
    }

    record = {
        "text": text,
        "createdAt": _utc_iso_z(),
        "embed": {
            "$type": "app.bsky.embed.images",
            "images": images,
        },
    }

    if facets:
        record["facets"] = facets

    payload = {
        "repo": did,
        "collection": "app.bsky.feed.post",
        "record": record,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise BlueskyAPIError(f"Bluesky post failed: {_clean_error_message(resp)}")

    data: Any = resp.json()
    try:
        uri = str(data["uri"])
        cid = str(data["cid"])
    except Exception as e:
        raise BlueskyAPIError("Bluesky post failed: unexpected response format") from e

    return BlueskyPostResult(uri=uri, cid=cid)
