from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Canonical Plan JSON schema (returned by AI, stored as plan_json):
# {
#   "bluesky": {
#     "text": "string (<= 300 chars, includes hashtags inline at end)",
#     "hashtags": ["string", ...] (2-6 items, no '#'),
#     "alt_text": ["string", ...] (one per media item; if none, empty list)
#   },
#   "youtube": {
#     "title": "string (<= 100 chars)",
#     "description": "string (2-5 short paragraphs; include keywords naturally)",
#     "tags": ["string", ...] (8-20 items),
#     "category": "string" (human-readable, e.g. 'Science & Technology')
#   }
# }


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    warnings: list[str]
    errors: list[str]


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _normalize_targets(targets: Any) -> list[str]:
    if targets is None:
        return ["bluesky", "youtube"]
    if not isinstance(targets, list) or not all(isinstance(x, str) for x in targets):
        return ["bluesky", "youtube"]
    out: list[str] = []
    for t in targets:
        tl = t.strip().lower()
        if tl in ("bluesky", "youtube") and tl not in out:
            out.append(tl)
    return out or ["bluesky", "youtube"]


def validate_plan(plan: Any, *, targets: list[str] | None = None) -> ValidationResult:
    warnings: list[str] = []
    errors: list[str] = []

    targets_norm = _normalize_targets(targets)
    want_bluesky = "bluesky" in targets_norm
    want_youtube = "youtube" in targets_norm

    if not isinstance(plan, dict):
        return ValidationResult(ok=False, warnings=[], errors=["plan must be an object"])

    bluesky = plan.get("bluesky")
    youtube = plan.get("youtube")

    if want_bluesky:
        if not isinstance(bluesky, dict):
            errors.append("missing or invalid 'bluesky' object")
            bluesky = {}
    else:
        bluesky = bluesky if isinstance(bluesky, dict) else None

    if want_youtube:
        if not isinstance(youtube, dict):
            errors.append("missing or invalid 'youtube' object")
            youtube = {}
    else:
        youtube = youtube if isinstance(youtube, dict) else None

    # Bluesky
    if want_bluesky and isinstance(bluesky, dict):
        b_text = bluesky.get("text")
        b_hashtags = bluesky.get("hashtags")
        b_alt = bluesky.get("alt_text")

        if not isinstance(b_text, str) or not b_text.strip():
            errors.append("bluesky.text must be a non-empty string")
        else:
            if len(b_text) > 300:
                warnings.append("bluesky.text is longer than 300 characters")

        if not _is_str_list(b_hashtags):
            errors.append("bluesky.hashtags must be an array of strings")
        else:
            if not (2 <= len(b_hashtags) <= 5):
                warnings.append("bluesky.hashtags should have 2-5 items")
            if any("#" in h for h in b_hashtags):
                errors.append("bluesky.hashtags must not include '#' characters")

        if not _is_str_list(b_alt):
            errors.append("bluesky.alt_text must be an array of strings")

    # YouTube
    if want_youtube and isinstance(youtube, dict):
        y_title = youtube.get("title")
        y_desc = youtube.get("description")
        y_tags = youtube.get("tags")
        y_cat = youtube.get("category")

        if not isinstance(y_title, str) or not y_title.strip():
            errors.append("youtube.title must be a non-empty string")
        else:
            if len(y_title) > 100:
                warnings.append("youtube.title is longer than 100 characters")

        if not isinstance(y_desc, str) or not y_desc.strip():
            errors.append("youtube.description must be a non-empty string")
        else:
            # Paragraph guidance: warn if it doesn't look like multiple paragraphs.
            paragraphs = [p for p in (x.strip() for x in y_desc.split("\n\n")) if p]
            if not (2 <= len(paragraphs) <= 5):
                warnings.append("youtube.description should be 2-5 short paragraphs")

        if not _is_str_list(y_tags):
            errors.append("youtube.tags must be an array of strings")
        else:
            if not (8 <= len(y_tags) <= 20):
                warnings.append("youtube.tags should have 8-20 items")

        if not isinstance(y_cat, str) or not y_cat.strip():
            errors.append("youtube.category must be a non-empty string")

    return ValidationResult(ok=len(errors) == 0, warnings=warnings, errors=errors)
