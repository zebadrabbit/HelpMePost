from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, g, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from app.ai.client import AIClient
from app.ai.plan_validation import validate_plan
from app.db import (
    ensure_default_project,
    get_media,
    get_project,
    insert_media,
    insert_plan,
    insert_project,
    list_media,
    list_projects,
    list_plans_for_project,
    get_plan_for_project,
)
from app.planners.bluesky import from_canonical as bluesky_from_canonical
from app.planners.youtube import from_canonical as youtube_from_canonical
from app.integrations.bluesky import BlueskyAPIError, build_link_facets, create_post_with_images, create_session, upload_blob
from app.core.image_optimize import BSKY_MAX_IMAGE_BYTES, ImageOptimizationError, optimize_for_bluesky


web = Blueprint("web", __name__)


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@web.get("/")
def index() -> str:
    return render_template("index.html")


@web.get("/projects")
def projects_page() -> str:
    return render_template("projects.html")


@web.get("/projects/<int:project_id>")
def project_page(project_id: int):
    project = get_project(g._db, project_id)
    if project is None:
        return ("Not found", 404)
    return render_template("project.html", project=project)


def _project_or_404(project_id: int):
    project = get_project(g._db, project_id)
    if project is None:
        return None
    return project


@web.post("/api/projects")
def api_create_project() -> Response:
    data = request.get_json(silent=True) or {}

    title = str(data.get("title") or "").strip()
    intent_text = str(data.get("intent_text") or "").strip()
    if not intent_text:
        return jsonify({"ok": False, "error": "intent_text is required"}), 400

    if not title:
        title = "Untitled Project"

    project_id = insert_project(g._db, title=title, intent_text=intent_text)
    project = get_project(g._db, project_id)
    assert project is not None

    return jsonify(
        {
            "ok": True,
            "project": {
                "id": project.id,
                "title": project.title,
                "intent_text": project.intent_text,
                "created_at": project.created_at,
            },
        }
    )


@web.get("/api/projects")
def api_list_projects() -> Response:
    projects = list_projects(g._db)
    return jsonify(
        {
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "intent_text": p.intent_text,
                    "created_at": p.created_at,
                }
                for p in projects
            ]
        }
    )


@web.get("/api/projects/<int:project_id>")
def api_get_project(project_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "id": project.id,
            "title": project.title,
            "intent_text": project.intent_text,
            "created_at": project.created_at,
        }
    )


@web.get("/api/projects/<int:project_id>/media")
def api_project_media(project_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    items = list_media(g._db, project_id=project_id)
    return jsonify(
        {
            "items": [
                {
                    "id": m.id,
                    "project_id": m.project_id,
                    "original_name": m.original_name,
                    "content_type": m.content_type,
                    "size_bytes": m.size_bytes,
                    "created_at": m.created_at,
                    "url": f"/media/{m.id}",
                }
                for m in items
            ]
        }
    )


@web.post("/api/projects/<int:project_id>/upload")
def api_project_upload(project_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    # Dropzone defaults to field name "file".
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "missing file"}), 400

    original_name = f.filename or "upload"
    safe_name = secure_filename(original_name) or "upload"

    ext = Path(safe_name).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"

    upload_dir = current_app.config["UPLOAD_DIR"]
    dst = os.path.join(upload_dir, stored_name)
    f.save(dst)

    size_bytes = os.path.getsize(dst)
    content_type = f.mimetype

    media_id = insert_media(
        g._db,
        project_id=project_id,
        original_name=original_name,
        stored_name=stored_name,
        content_type=content_type,
        size_bytes=size_bytes,
    )

    return jsonify(
        {
            "id": media_id,
            "project_id": project_id,
            "original_name": original_name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "created_at": list_media(g._db, project_id=project_id)[0].created_at,
            "url": f"/media/{media_id}",
        }
    )


@web.post("/api/projects/<int:project_id>/generate")
def api_project_generate(project_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    intent_text = str(data.get("intent_text", "")).strip()
    model = str(data.get("model") or "").strip() or None
    template_mode = bool(data.get("template_mode") or False)
    generate_targets = data.get("generate_targets")
    add_emojis = bool(data.get("add_emojis") or False)
    include_cta = bool(data.get("include_cta") or False)
    cta_target = str(data.get("cta_target") or "").strip() or None
    # UX hardening: if the user provided a link/handle, treat that as explicit intent
    # to include a CTA even if the checkbox/payload got out of sync (cached JS, etc.).
    if cta_target:
        include_cta = True
    selected_media_ids = data.get("selected_media_ids")

    # Target platforms to generate. Backward compatible default is both.
    if generate_targets is None:
        targets = ["bluesky", "youtube"]
    elif isinstance(generate_targets, list) and all(isinstance(x, str) for x in generate_targets):
        targets = []
        for t in generate_targets:
            tl = t.strip().lower()
            if tl in ("bluesky", "youtube") and tl not in targets:
                targets.append(tl)
        if not targets:
            targets = ["bluesky", "youtube"]
    else:
        return jsonify({"error": "generate_targets must be an array of strings"}), 400

    want_bluesky = "bluesky" in targets
    want_youtube = "youtube" in targets

    if not isinstance(selected_media_ids, list):
        return jsonify({"error": "selected_media_ids is required"}), 400
    if len(selected_media_ids) == 0:
        return jsonify({"error": "selected_media_ids must not be empty"}), 400

    # Validate selected_media_ids are ints.
    try:
        selected_media_ids_int = [int(x) for x in selected_media_ids]
    except Exception:
        return jsonify({"error": "selected_media_ids must be an array of integers"}), 400

    # Ensure selected media belong to this project.
    media_items = {m.id: m for m in list_media(g._db, project_id=project_id)}
    selected_items = []
    for mid in selected_media_ids_int:
        if mid not in media_items:
            return jsonify({"error": f"media_id {mid} not found in this project"}), 400
        selected_items.append(media_items[mid])

    def _parse_builder_fields(text: str) -> tuple[str, str | None, str | None]:
        focus = ""
        audience = None
        tone = None
        for line in (x.strip() for x in text.splitlines()):
            if line.lower().startswith("focus:"):
                focus = line.split(":", 1)[1].strip()
            elif line.lower().startswith("audience:"):
                audience = line.split(":", 1)[1].strip() or None
            elif line.lower().startswith("tone:"):
                tone = line.split(":", 1)[1].strip() or None
        if not focus:
            focus = (project.title or "").strip() or "(untitled)"
        return focus, audience, tone

    effective_intent = intent_text or (project.intent_text or "")
    focus, audience, tone = _parse_builder_fields(effective_intent)

    media_summary = [
        {
            "filename": m.original_name,
            "content_type": m.content_type or "",
            "size_bytes": m.size_bytes,
        }
        for m in selected_items
    ]

    def _simple_keywords(text: str) -> list[str]:
        # Very light keyword extraction: split on non-alnum, keep unique tokens.
        tokens: list[str] = []
        cur = ""
        for ch in text.lower():
            if ch.isalnum():
                cur += ch
            else:
                if cur:
                    tokens.append(cur)
                cur = ""
        if cur:
            tokens.append(cur)

        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "for",
            "of",
            "in",
            "on",
            "with",
            "my",
            "your",
            "our",
            "this",
            "that",
            "is",
            "are",
            "it",
            "as",
        }

        seen: set[str] = set()
        out: list[str] = []
        for t in tokens:
            if len(t) < 3:
                continue
            if t in stop:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    def _normalize_hashtag_token(tag: str) -> str:
        t = (tag or "").strip()
        if t.startswith("#"):
            t = t[1:]
        return t.strip()

    def _is_production_related_focus(text: str) -> bool:
        tl = (text or "").lower()
        keywords = [
            "video production",
            "music production",
            "producer",
            "production",
            "editing",
            "video editing",
            "filming",
            "cinematography",
            "recording",
            "mixing",
            "mastering",
            "sound design",
            "beat",
            "studio",
        ]
        return any(k in tl for k in keywords)

    def _suggest_specific_hashtags_for_focus(text: str) -> list[str]:
        tl = (text or "").lower()
        out: list[str] = []
        # Keep these stable and project-relevant.
        if "help" in tl and "post" in tl:
            out.append("helpmepost")
        if "bluesky" in tl:
            out.append("bluesky")
        if "atproto" in tl or "at proto" in tl or "at-proto" in tl:
            out.append("atproto")
        if "flask" in tl:
            out.append("flask")
        if "open source" in tl or "opensource" in tl or "open-source" in tl:
            out.append("opensource")
        if "indiedev" in tl or ("indie" in tl and "dev" in tl):
            out.append("indiedev")
        return out

    def _pick_bluesky_hashtags(*, focus: str, audience: str | None, tone: str | None) -> list[str]:
        banned = {"creators", "content", "producers"}

        # Prefer focus-specific tags first.
        focus_specific = _suggest_specific_hashtags_for_focus(focus)

        # Then use keywords, but bias toward the focus line (avoid super generic filler).
        kw_focus = _simple_keywords(focus)
        kw_other = _simple_keywords(" ".join([audience or "", tone or ""]))

        allow_generic = {"makers", "artists"}
        discouraged = {"update", "project", "demo", "behindthescenes", "build", "new"}

        candidates: list[str] = []
        candidates.extend(focus_specific)
        candidates.extend([k for k in kw_focus if k not in discouraged])
        candidates.extend([k for k in kw_other if k not in discouraged])
        candidates.extend([k for k in kw_focus if k in allow_generic])

        out: list[str] = []
        for c in candidates:
            t = _normalize_hashtag_token(c)
            if not t:
                continue
            if t in banned:
                continue
            if "#" in t:
                continue
            if t not in out:
                out.append(t)
            if len(out) >= 5:
                break

        # Ensure at least 2 tags when possible.
        allowlist_fallback = ["bluesky", "flask", "opensource", "atproto", "helpmepost"]
        for t in allowlist_fallback:
            if len(out) >= 2:
                break
            if t not in out:
                out.append(t)

        return out[:5]

    def _bluesky_hook_line(*, focus: str, tone: str | None) -> str:
        base = (focus or "").strip() or "Update"
        t = (tone or "").strip().lower()
        if t == "cozy":
            return f"I've been working on {base}.".strip()
        if t == "informative":
            return f"I built a small thing: {base}.".strip()
        if t == "excited":
            return f"I just shipped {base}!".strip()
        if t == "funny":
            return f"I got tired of overthinking posts, so I made {base}.".strip()
        if t == "serious":
            return f"I built {base}.".strip()
        return f"I built {base}.".strip()

    _HASHTAG_RE = re.compile(r"(?<!\\w)#([A-Za-z0-9_]+)")

    def _render_bluesky_text_from_hashtags(text: str, hashtags: list[str]) -> str:
        # Single source of truth: the hashtags array.
        tags: list[str] = []
        for h in (hashtags or []):
            if not isinstance(h, str):
                continue
            t = _normalize_hashtag_token(h)
            if not t:
                continue
            if "#" in t:
                t = t.replace("#", "")
            if t and t not in tags:
                tags.append(t)
            if len(tags) >= 5:
                break

        raw = (text or "").strip()
        # Remove any existing hashtags anywhere in the text to prevent drift/banned tag reappearance.
        body = _HASHTAG_RE.sub("", raw)
        # Clean up whitespace artifacts from removals.
        body = re.sub(r"[ \t]{2,}", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = body.strip()

        hashtags_line = " ".join([f"#{t}" for t in tags])
        if hashtags_line:
            composed = (body + "\n\n" + hashtags_line).strip() if body else hashtags_line
        else:
            composed = body

        # Enforce Bluesky 300-char cap while preserving the hashtag line.
        if len(composed) > 300:
            if hashtags_line:
                suffix = "\n\n" + hashtags_line
                max_body = 300 - len(suffix)
                if max_body <= 1:
                    body_trim = "…"
                else:
                    body_trim = (body[: max_body - 1].rstrip() + "…") if body else ""
                if body_trim:
                    composed = (body_trim + suffix).strip()
                else:
                    composed = suffix.strip()
            else:
                composed = composed[:297].rstrip() + "…"

        return composed

    def _cta_line_for_target(target: str | None) -> str:
        t = (target or "").strip()
        if not t:
            return "Link in post"

        # Heuristics: keep wording accurate.
        # - If it's a handle, prompt a follow.
        # - If it looks like a YouTube link, "Watch" is reasonable.
        # - Otherwise, treat it as a generic link/resource.
        tl = t.lower()
        if t.startswith("@"):  # handle
            return f"Follow: {t}"
        if "youtu.be" in tl or "youtube.com" in tl:
            return f"Watch here: {t}"
        return f"Link: {t}"

    def _template_plan() -> dict:
        # Keep it simple and deterministic.
        base = focus.strip() or "Update"

        hashtags = _pick_bluesky_hashtags(focus=focus, audience=audience, tone=tone)

        # Optional emoji support (very light, deterministic).
        # Constraints:
        # - YouTube title: max 2 emojis, start or end only
        # - Bluesky text: max 3 emojis total
        b_emoji_prefix = "✨ " if add_emojis else ""
        y_emoji_suffix = " 🎬" if add_emojis else ""

        out: dict = {"meta": {"is_template": True, "targets": targets}}

        if want_bluesky:
            # Bluesky text: short + hashtags inline at end.
            hook = _bluesky_hook_line(focus=base, tone=tone)
            b_lines = [f"{b_emoji_prefix}{hook}".strip()]
            if audience:
                b_lines.append(f"For: {audience}.")
            if selected_items:
                b_lines.append(f"Media: {len(selected_items)} file(s).")

            b_text = " ".join(b_lines).strip()

            # CTA: add a short CTA line near the end (before hashtags).
            cta_line = ""
            if include_cta:
                cta_line = _cta_line_for_target(cta_target)

            if cta_line:
                b_text = (b_text + "\n" + cta_line).strip()

            # Single source of truth: render inline hashtags from the array.
            b_text = _render_bluesky_text_from_hashtags(b_text, hashtags[:5])

            # Alt text: one per selected media, by filename/type.
            alt_text: list[str] = []
            for m in selected_items:
                ct = (m.content_type or "").lower()
                if ct.startswith("image/"):
                    alt_text.append(f"Image: {m.original_name}")
                elif ct.startswith("video/"):
                    alt_text.append(f"Video: {m.original_name}")
                else:
                    alt_text.append(f"File: {m.original_name}")

            out["bluesky"] = {"text": b_text, "hashtags": hashtags[:5], "alt_text": alt_text}

        if want_youtube:
            # YouTube fields
            y_title = base
            if len(y_title) > 100:
                y_title = y_title[:97].rstrip() + "…"
            if y_emoji_suffix:
                # Emoji at end only (not mid-word).
                y_title = (y_title + y_emoji_suffix)
                if len(y_title) > 100:
                    y_title = y_title[:100].rstrip()

            para1 = f"In this update: {base}."
            if tone:
                para1 += f" Tone: {tone}."
            if audience:
                para1 += f" Made for {audience}."

            media_names = ", ".join([m.original_name for m in selected_items[:5]])
            para2 = ""
            if media_names:
                para2 = f"Included media: {media_names}."
                if len(selected_items) > 5:
                    para2 += f" (+{len(selected_items) - 5} more)"
            else:
                para2 = "Included media: (none)"

            y_desc = (para1.strip() + "\n\n" + para2.strip()).strip()
            if include_cta:
                y_desc = (y_desc + "\n\n" + _cta_line_for_target(cta_target)).strip()

            kw = _simple_keywords(" ".join([focus or "", audience or "", tone or ""]))
            tags = kw[:20]
            # Ensure minimum tags without heavy NLP.
            fallback_tags = ["update", "project", "tutorial", "demo", "behind the scenes", "tips", "how to", "short"]
            for t in fallback_tags:
                if len(tags) >= 8:
                    break
                if t not in tags:
                    tags.append(t)
            tags = tags[:20]

            out["youtube"] = {"title": y_title, "description": y_desc, "tags": tags, "category": "People & Blogs"}

        return out

    if template_mode:
        plan = _template_plan()
        validation = validate_plan(plan, targets=targets)
        if not validation.ok:
            current_app.logger.error("Template plan failed validation: %s", "; ".join(validation.errors))
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "error_type": "schema_invalid",
                            "human_message": "Template draft generation failed due to an internal schema error.",
                        },
                    }
                ),
                500,
            )
        # Contextual alt_text validation (same rule as AI path).
        if want_bluesky:
            alt_text = plan.get("bluesky", {}).get("alt_text", [])
            if not isinstance(alt_text, list) or len(alt_text) != len(selected_items):
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": {
                                "error_type": "schema_invalid",
                                "human_message": "Template draft generation failed due to an internal schema error.",
                            },
                        }
                    ),
                    500,
                )

        plan_id = insert_plan(g._db, project_id=project_id, model="template", plan_json=json.dumps(plan))

        resp: dict = {
            "ok": True,
            "id": plan_id,
            "project_id": project_id,
            "selected_media_ids": selected_media_ids_int,
            "meta": {"is_template": True, "targets": targets},
            "warnings": [],
        }
        if want_bluesky and "bluesky" in plan:
            bluesky = bluesky_from_canonical(plan)
            resp["bluesky"] = {"text": bluesky.text, "hashtags": bluesky.hashtags, "alt_text": bluesky.alt_text}
        if want_youtube and "youtube" in plan:
            youtube = youtube_from_canonical(plan)
            resp["youtube"] = {
                "title": youtube.title,
                "description": youtube.description,
                "tags": youtube.tags,
                "category": youtube.category,
            }
        return jsonify(resp)

    ai = AIClient(model=model)

    result = ai.generate_plan(
        focus=focus,
        audience=audience,
        tone=tone,
        media_summary=media_summary,
        add_emojis=add_emojis,
        include_cta=include_cta,
        cta_target=cta_target,
        generate_targets=targets,
    )

    if not result.ok or result.plan is None:
        err = result.error
        details = err.details if err else None
        if details:
            current_app.logger.error("AI generation failed (%s): %s", err.error_type if err else "unknown", details)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "error_type": err.error_type if err else "unknown",
                        "human_message": err.human_message if err else "AI generation failed.",
                    },
                }
            ),
            502,
        )

    # Store meta about what was generated.
    if isinstance(result.plan, dict):
        meta = result.plan.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            result.plan["meta"] = meta
        meta["targets"] = targets

    # Validate again at the route boundary (defense in depth).
    validation = validate_plan(result.plan, targets=targets)
    if not validation.ok:
        current_app.logger.error("AI plan schema invalid after generation: %s", "; ".join(validation.errors))
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "error_type": "schema_invalid",
                        "human_message": "AI generation returned an invalid plan format.",
                    },
                }
            ),
            502,
        )

    # Contextual validation: alt_text must align 1:1 with selected media.
    try:
        if want_bluesky:
            alt_text = result.plan.get("bluesky", {}).get("alt_text", [])
            if not isinstance(alt_text, list) or len(alt_text) != len(selected_items):
                current_app.logger.error(
                    "AI plan schema invalid: bluesky.alt_text length %s does not match selected media count %s",
                    len(alt_text) if isinstance(alt_text, list) else "(not a list)",
                    len(selected_items),
                )
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": {
                                "error_type": "schema_invalid",
                                "human_message": "AI generation returned an invalid plan format.",
                            },
                        }
                    ),
                    502,
                )
    except Exception:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "error_type": "schema_invalid",
                        "human_message": "AI generation returned an invalid plan format.",
                    },
                }
            ),
            502,
        )

    def _inject_cta_into_bluesky_text(text: str, target: str) -> str:
        cta_line = _cta_line_for_target(target).strip()

        raw = (text or "").strip()
        if not raw:
            raw = ""

        lines = raw.splitlines() if raw else []
        hashtags_line = ""
        body_lines = lines

        # Heuristic: if the last non-empty line contains hashtags, keep it as the final line.
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                if "#" in lines[i]:
                    hashtags_line = lines[i].strip()
                    body_lines = lines[:i]
                break

        body = "\n".join(body_lines).strip()
        if body:
            composed = body + "\n" + cta_line
        else:
            composed = cta_line

        if hashtags_line:
            composed = (composed + "\n\n" + hashtags_line).strip()

        # Enforce Bluesky text length cap while preserving CTA + hashtags line.
        if len(composed) > 300:
            suffix = "\n" + cta_line
            if hashtags_line:
                suffix = "\n" + cta_line + "\n\n" + hashtags_line

            # Trim the body to fit.
            max_body = 300 - len(suffix)
            if max_body <= 1:
                body_trim = "…"
            else:
                body_trim = body[: max_body - 1].rstrip() + "…" if body else ""

            if body_trim:
                composed = (body_trim + suffix).strip()
            else:
                # Worst case: no room for body; keep CTA + hashtags.
                composed = suffix.strip()
                if len(composed) > 300:
                    composed = composed[:297].rstrip() + "…"

        return composed

    def _postprocess_bluesky_hashtags(plan: dict, *, focus: str) -> None:
        b = plan.get("bluesky")
        if not isinstance(b, dict):
            return
        raw = b.get("hashtags")
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            return

        banned = {"creators", "content", "producers"}
        allowlist_lower = ["bluesky", "flask", "opensource", "atproto", "helpmepost"]
        allowlist_camel = {
            "bluesky": "Bluesky",
            "flask": "Flask",
            "opensource": "OpenSource",
            "atproto": "ATProto",
            "helpmepost": "HelpMePost",
        }

        keep_style_camel = any(any(ch.isupper() for ch in t) for t in raw)
        allowlist = [allowlist_camel[t] for t in allowlist_lower] if keep_style_camel else allowlist_lower

        focus_is_prod = _is_production_related_focus(focus)

        cleaned: list[str] = []
        removed_any = False
        for t in raw:
            tt = _normalize_hashtag_token(t)
            if not tt:
                continue
            # Treat case-insensitively for banned checks.
            tl = tt.lower()
            if (tl in banned) and not focus_is_prod:
                removed_any = True
                continue
            if "#" in tt:
                # Never allow '#'.
                removed_any = True
                tt = tt.replace("#", "")
                if not tt:
                    continue
            if tt not in cleaned:
                cleaned.append(tt)
            if len(cleaned) >= 5:
                break

        # If we removed banned generic tags, replace with stable specific allowlist tags.
        if removed_any and not focus_is_prod:
            for t in allowlist:
                if len(cleaned) >= 5:
                    break
                if t not in cleaned:
                    cleaned.append(t)

        # Ensure minimum of 2 hashtags if possible.
        for t in allowlist:
            if len(cleaned) >= 2:
                break
            if t not in cleaned:
                cleaned.append(t)

        b["hashtags"] = cleaned[:5]

    def _ensure_cta_verbatim(plan: dict, target: str, *, want_bluesky: bool, want_youtube: bool) -> None:
        target = (target or "").strip()
        if not target:
            return

        if want_bluesky:
            b = plan.get("bluesky")
            if isinstance(b, dict):
                b_text = str(b.get("text") or "")
                if target not in b_text:
                    b["text"] = _inject_cta_into_bluesky_text(b_text, target)

        if want_youtube:
            y = plan.get("youtube")
            if isinstance(y, dict):
                y_desc = str(y.get("description") or "")
                if target not in y_desc:
                    y["description"] = (y_desc.rstrip() + "\n\n" + _cta_line_for_target(target)).strip()

    # Safety net: even if the AI ignores the instruction, guarantee the link/handle is present.
    if include_cta and cta_target and isinstance(result.plan, dict):
        _ensure_cta_verbatim(result.plan, cta_target, want_bluesky=want_bluesky, want_youtube=want_youtube)

    # Optional minimal hardening: drop banned generic Bluesky hashtags if focus isn't production-related.
    if want_bluesky and isinstance(result.plan, dict):
        _postprocess_bluesky_hashtags(result.plan, focus=focus)

    # Hashtag single source of truth (Bluesky): ensure inline hashtags in text are rendered
    # directly from bluesky.hashtags (no drift, consistent casing, max 5).
    if want_bluesky and isinstance(result.plan, dict):
        b = result.plan.get("bluesky")
        if isinstance(b, dict):
            text = str(b.get("text") or "")
            tags = b.get("hashtags")
            if isinstance(tags, list) and all(isinstance(x, str) for x in tags):
                b["text"] = _render_bluesky_text_from_hashtags(text, tags)

    # Enforce target-scoped storage: do not persist unrequested sections.
    if isinstance(result.plan, dict):
        if not want_bluesky:
            result.plan.pop("bluesky", None)
        if not want_youtube:
            result.plan.pop("youtube", None)

    # Keep stored plan_json as the canonical schema only (single source of truth).
    plan_id = insert_plan(g._db, project_id=project_id, model=ai.model, plan_json=json.dumps(result.plan))

    resp: dict = {
        "ok": True,
        "id": plan_id,
        "project_id": project_id,
        "selected_media_ids": selected_media_ids_int,
        "meta": {"targets": targets},
        "warnings": result.warnings,
    }

    if want_bluesky and isinstance(result.plan, dict) and "bluesky" in result.plan:
        bluesky = bluesky_from_canonical(result.plan)
        resp["bluesky"] = {
            "text": bluesky.text,
            "hashtags": bluesky.hashtags,
            "alt_text": bluesky.alt_text,
        }
    if want_youtube and isinstance(result.plan, dict) and "youtube" in result.plan:
        youtube = youtube_from_canonical(result.plan)
        resp["youtube"] = {
            "title": youtube.title,
            "description": youtube.description,
            "tags": youtube.tags,
            "category": youtube.category,
        }

    return jsonify(resp)


@web.get("/api/projects/<int:project_id>/plans")
def api_project_plans(project_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    plans = list_plans_for_project(g._db, project_id=project_id)
    return jsonify(
        {
            "items": [
                {
                    "id": p.id,
                    "created_at": p.created_at,
                    "model": p.model,
                    "is_template": bool(
                        (json.loads(p.plan_json).get("meta") or {}).get("is_template")
                    )
                    if p.plan_json
                    else False,
                }
                for p in plans
            ]
        }
    )


@web.post("/api/projects/<int:project_id>/bluesky_post")
def api_project_bluesky_post(project_id: int) -> Response:
    """Post to Bluesky using app-password auth.

    Scope: images only (no video/GIF) and 1-4 images max.
    We do not store credentials or tokens.
    """

    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    identifier = str(data.get("identifier") or "").strip()
    app_password = str(data.get("app_password") or "").strip()
    text = str(data.get("text") or "").strip()
    selected_media_ids = data.get("selected_media_ids")
    alt_text = data.get("alt_text")

    if not identifier:
        return jsonify({"error": "identifier is required"}), 400
    if not app_password:
        return jsonify({"error": "app_password is required"}), 400
    if not text:
        return jsonify({"error": "text is required"}), 400
    if not isinstance(selected_media_ids, list):
        return jsonify({"error": "selected_media_ids is required"}), 400

    try:
        selected_ids = [int(x) for x in selected_media_ids]
    except Exception:
        return jsonify({"error": "selected_media_ids must be an array of integers"}), 400

    if len(selected_ids) == 0:
        return jsonify({"error": "Select at least one image."}), 400

    # Validate + load media items; ensure they belong to this project.
    media_items = {m.id: m for m in list_media(g._db, project_id=project_id)}
    selected_items = []
    for mid in selected_ids:
        if mid not in media_items:
            return jsonify({"error": f"media_id {mid} not found in this project"}), 400
        selected_items.append(media_items[mid])

    # Images only: 1-4 images, no GIF.
    images = []
    for m in selected_items:
        ct = (m.content_type or "").lower()
        if not ct.startswith("image/"):
            return jsonify({"error": "Only images are supported for Bluesky posting (no video yet)."}), 400
        if ct == "image/gif":
            return jsonify({"error": "GIF is not supported for Bluesky posting in this phase."}), 400
        images.append(m)

    if len(images) == 0:
        return jsonify({"error": "No images selected."}), 400
    if len(images) > 4:
        return jsonify({"error": "Bluesky supports up to 4 images per post."}), 400

    if alt_text is not None:
        if not isinstance(alt_text, list) or not all(isinstance(x, str) for x in alt_text):
            return jsonify({"error": "alt_text must be an array of strings"}), 400
        if len(alt_text) != len(images):
            return jsonify({"error": "alt_text length must match selected image count"}), 400

    # Authenticate and post (do not persist tokens).
    try:
        access_jwt, did = create_session(identifier=identifier, app_password=app_password)

        uploaded_images = []
        optimization_details: list[dict[str, int | str | bool]] = []
        compressed_count = 0
        upload_dir = current_app.config["UPLOAD_DIR"]

        for idx, m in enumerate(images):
            path = os.path.join(upload_dir, m.stored_name)
            original_size = int(m.size_bytes or 0)
            content_type = (m.content_type or "application/octet-stream").lower()

            # Bluesky's images embed enforces 1,000,000 bytes per image.
            # If the file is oversized, compress deterministically to JPEG.
            if original_size > BSKY_MAX_IMAGE_BYTES:
                try:
                    optimized = optimize_for_bluesky(path, content_type)
                except ImageOptimizationError:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": {
                                    "human_message": "Image could not be compressed under Bluesky’s 1MB limit.",
                                },
                            }
                        ),
                        400,
                    )

                blob = upload_blob(access_jwt=access_jwt, content_type=str(optimized["out_mime"]), data=optimized["bytes"])
                compressed_count += 1
                optimization_details.append(
                    {
                        "index": int(idx),
                        "original_size_bytes": int(original_size),
                        "optimized_size_bytes": int(optimized["size_bytes"]),
                        "width": int(optimized["width"]),
                        "height": int(optimized["height"]),
                        "quality": int(optimized["quality"]),
                        "changed": bool(optimized["changed"]),
                        "out_mime": str(optimized["out_mime"]),
                    }
                )
            else:
                with open(path, "rb") as f:
                    raw = f.read()
                blob = upload_blob(access_jwt=access_jwt, content_type=content_type, data=raw)

            alt = ""
            if isinstance(alt_text, list):
                alt = alt_text[idx]

            uploaded_images.append({"alt": alt, "image": blob})

        facets = build_link_facets(text)
        result = create_post_with_images(access_jwt=access_jwt, did=did, text=text, images=uploaded_images, facets=facets)
        payload: dict[str, object] = {"ok": True, "uri": result.uri, "cid": result.cid}
        if compressed_count > 0:
            payload["optimization"] = {
                "compressed_images": int(compressed_count),
                "max_bytes": int(BSKY_MAX_IMAGE_BYTES),
                "details": optimization_details,
            }
        return jsonify(payload)
    except BlueskyAPIError as e:
        # No stack traces and never include passwords.
        msg = str(e)
        # Surface a clearer status code for bad credentials.
        status = 401 if msg.lower().startswith("bluesky login failed") else 502
        current_app.logger.warning("Bluesky post failed: %s", msg)
        return jsonify({"ok": False, "error": {"human_message": msg}}), status
    except Exception:
        current_app.logger.exception("Bluesky post failed due to an internal error")
        return jsonify({"ok": False, "error": {"human_message": "Bluesky post failed due to an internal error."}}), 502


@web.get("/api/projects/<int:project_id>/plans/<int:plan_id>")
def api_project_plan_detail(project_id: int, plan_id: int) -> Response:
    project = _project_or_404(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404

    plan = get_plan_for_project(g._db, project_id=project_id, plan_id=plan_id)
    if plan is None:
        return jsonify({"error": "not found"}), 404

    try:
        payload = json.loads(plan.plan_json)
    except Exception:
        payload = {"raw": plan.plan_json}
    return jsonify(payload)


@web.get("/api/media")
def api_media_list() -> Response:
    # legacy endpoint; will be removed after project UI is stable.
    default_project_id = ensure_default_project(g._db)
    items = list_media(g._db, project_id=default_project_id)
    return jsonify(
        {
            "items": [
                {
                    "id": m.id,
                    "project_id": m.project_id,
                    "original_name": m.original_name,
                    "content_type": m.content_type,
                    "size_bytes": m.size_bytes,
                    "created_at": m.created_at,
                    "url": f"/media/{m.id}",
                }
                for m in items
            ]
        }
    )


@web.post("/api/upload")
def api_upload() -> Response:
    # legacy endpoint; will be removed after project UI is stable.
    # Dropzone defaults to field name "file".
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "missing file"}), 400

    project_id = ensure_default_project(g._db)

    original_name = f.filename or "upload"
    safe_name = secure_filename(original_name) or "upload"

    ext = Path(safe_name).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"

    upload_dir = current_app.config["UPLOAD_DIR"]
    dst = os.path.join(upload_dir, stored_name)
    f.save(dst)

    size_bytes = os.path.getsize(dst)
    content_type = f.mimetype

    media_id = insert_media(
        g._db,
        project_id=project_id,
        original_name=original_name,
        stored_name=stored_name,
        content_type=content_type,
        size_bytes=size_bytes,
    )

    return jsonify(
        {
            "id": media_id,
            "project_id": project_id,
            "original_name": original_name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "created_at": list_media(g._db, project_id=project_id)[0].created_at,
            "url": f"/media/{media_id}",
        }
    )


@web.get("/media/<int:media_id>")
def media_file(media_id: int):
    item = get_media(g._db, media_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(current_app.config["UPLOAD_DIR"], item.stored_name, as_attachment=False)


@web.post("/api/generate")
def api_generate() -> Response:
    data = request.get_json(silent=True) or {}
    intent_text = str(data.get("intent_text", "")).strip()

    # Keep this for now for compatibility with the old UI.
    project_id = ensure_default_project(g._db)

    ai = AIClient()

    def _parse_builder_fields(text: str) -> tuple[str, str | None, str | None]:
        focus = ""
        audience = None
        tone = None
        for line in (x.strip() for x in (text or "").splitlines()):
            if line.lower().startswith("focus:"):
                focus = line.split(":", 1)[1].strip()
            elif line.lower().startswith("audience:"):
                audience = line.split(":", 1)[1].strip() or None
            elif line.lower().startswith("tone:"):
                tone = line.split(":", 1)[1].strip() or None
        if not focus:
            focus = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else "(untitled)"
        return focus, audience, tone

    focus, audience, tone = _parse_builder_fields(intent_text)

    # Legacy endpoint: no media context. Generate a best-effort plan with empty media.
    result = ai.generate_plan(
        focus=focus,
        audience=audience,
        tone=tone,
        media_summary=[],
        add_emojis=False,
        include_cta=False,
        cta_target=None,
        generate_targets=["bluesky", "youtube"],
    )

    if not result.ok or result.plan is None:
        err = result.error
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "error_type": err.error_type if err else "unknown",
                        "human_message": err.human_message if err else "AI generation failed.",
                    },
                }
            ),
            502,
        )

    validation = validate_plan(result.plan, targets=["bluesky", "youtube"])
    if not validation.ok:
        current_app.logger.error("Legacy /api/generate returned invalid plan: %s", "; ".join(validation.errors))
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "error_type": "schema_invalid",
                        "human_message": "AI generation returned an invalid plan format.",
                    },
                }
            ),
            502,
        )

    # Store canonical schema (single source of truth) but return legacy-shaped payload.
    plan_id = insert_plan(g._db, project_id=project_id, model=ai.model, plan_json=json.dumps(result.plan))

    resp: dict = {"id": plan_id, "project_id": project_id}

    if isinstance(result.plan, dict) and "bluesky" in result.plan:
        b = bluesky_from_canonical(result.plan)
        resp["bluesky"] = {
            "title": focus,
            "post_text": b.text,
            "alt_text": b.alt_text,
            "hashtags": b.hashtags,
        }
    if isinstance(result.plan, dict) and "youtube" in result.plan:
        y = youtube_from_canonical(result.plan)
        resp["youtube"] = {
            "title": y.title,
            "description": y.description,
            "keywords": y.tags,
            "category": y.category,
        }

    return jsonify(resp)
