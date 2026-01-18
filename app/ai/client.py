from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .plan_validation import ValidationResult, validate_plan


@dataclass(frozen=True)
class AIError:
    error_type: str
    human_message: str
    details: str | None = None


@dataclass(frozen=True)
class PlanGenerationResult:
    ok: bool
    plan: dict[str, Any] | None
    warnings: list[str]
    error: AIError | None


class AIClient:
    """All AI calls in one place.

    For now this uses OpenAI's HTTP API directly via stdlib (no extra deps).
    If OPENAI_API_KEY is not set, returns a structured error (no silent stubs).
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def generate_plan(
        self,
        *,
        focus: str,
        audience: str | None,
        tone: str | None,
        media_summary: list[dict[str, Any]],
        add_emojis: bool = False,
        include_cta: bool = False,
        cta_target: str | None = None,
        generate_targets: list[str] | None = None,
    ) -> PlanGenerationResult:
        """Generate a canonical plan object.

        Returns a strict, validated plan JSON matching the schema documented in
        `app/ai/plan_validation.py`. No silent fallbacks.
        """

        if not self.api_key:
            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=[],
                error=AIError(
                    error_type="missing_api_key",
                    human_message="AI generation is unavailable: OPENAI_API_KEY is not configured.",
                ),
            )

        system = (
            "You are a helpful assistant that outputs ONLY valid JSON. "
            "No markdown, no code fences, no extra keys, no trailing text."
        )

        targets_norm: list[str] = []
        for t in (generate_targets or ["bluesky", "youtube"]):
            if isinstance(t, str):
                tl = t.strip().lower()
                if tl in ("bluesky", "youtube") and tl not in targets_norm:
                    targets_norm.append(tl)
        if not targets_norm:
            targets_norm = ["bluesky", "youtube"]

        want_bluesky = "bluesky" in targets_norm
        want_youtube = "youtube" in targets_norm

        # Canonical schema reminder for the model (target-scoped).
        schema: dict[str, Any] = {}
        if want_bluesky:
            schema["bluesky"] = {
                "text": "string (<= 300 chars, includes hashtags inline at end)",
                "hashtags": "array of strings (2-5 items, no '#')",
                "alt_text": "array of strings (one per media item; can be empty strings if unknown)",
            }
        if want_youtube:
            schema["youtube"] = {
                "title": "string (<= 100 chars)",
                "description": "string (2-5 short paragraphs)",
                "tags": "array of strings (8-20 items)",
                "category": "string (human-readable)",
            }

        rules = [
            "Return ONLY a single JSON object matching required schema.",
            "Prefer specific nouns from the focus and media.",
            "Bluesky: the opening line should be a concrete hook that restates the focus in plain English.",
            "Avoid opening with salesy questions like 'Are you looking to…'.",
            "Keep tone consistent with the selected tone (Cozy should feel warm, not salesy).",
            "If a section is not requested, OMIT its key entirely (do not include empty placeholders).",
        ]

        if want_bluesky:
            rules.extend(
                [
                    "Bluesky voice: default to first-person ('I', 'my') unless the user focus clearly implies otherwise.",
                    "Avoid marketing phrases like 'Help your posts…', 'Discover…', 'Boost…'.",
                    "Bluesky.hashtags must NOT include '#'; Bluesky.text should include hashtags inline at the end.",
                    "Bluesky.alt_text must be an array with the same length and order as media_summary.",
                    "Bluesky.hashtags: 2-5 items (max 5).",
                    "Bluesky.hashtags: at least 2 should be specific to the focus when possible.",
                    "Bluesky.hashtags: prefer specific project/platform/tech tags when relevant (e.g. HelpMePost, Bluesky, ATProto, Flask, OpenSource, IndieDev).",
                    "Avoid generic tags like 'creators', 'content', 'producers' unless the focus explicitly relates to music/video production.",
                    "Tags like 'makers'/'artists' are allowed but should not dominate the set.",
                    "Hashtags must be consistent casing across the list (all lowercase or all CamelCase), and must not include '#'.",
                ]
            )

        # Optional emojis.
        if add_emojis:
            rules.extend(
                [
                    "Emojis are allowed but must be used sparingly.",
                    "YouTube.title: max 2 emojis total, placed only at the start or end (not mid-word).",
                    "Bluesky.text: max 3 emojis total.",
                ]
            )
        else:
            rules.append("Do not use emojis.")

        # Optional CTA.
        if include_cta:
            rules.append(
                "Include a short call-to-action. Bluesky: add a short CTA line near the end; keep hashtags as the final line. "
                "YouTube.description: include a short CTA near the top or bottom (but do not spam)."
            )
            if cta_target:
                rules.append(f"The CTA MUST include this exact string verbatim: {cta_target}")
                tl = cta_target.lower()
                if "youtu.be" not in tl and "youtube.com" not in tl:
                    rules.append("If the provided CTA target is just a link/handle, do NOT call it a video; refer to it as a link or handle.")
            else:
                rules.append("If no link/handle is provided, use a generic CTA like 'link in post/description'.")
        else:
            rules.append("Do not include any call-to-action.")

        user = {
            "task": "Generate a posting plan for Bluesky and YouTube.",
            "focus": focus,
            "audience": audience or "",
            "tone": tone or "",
            "media_summary": media_summary,
            "generate_targets": targets_norm,
            "add_emojis": bool(add_emojis),
            "include_cta": bool(include_cta),
            "cta_target": cta_target or "",
            "required_schema": schema,
            "rules": rules,
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user)},
            ],
            "temperature": 0.5,
        }

        req = urllib.request.Request(
            url="https://api.openai.com/v1/chat/completions",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # OpenAI uses 429 both for rate limits and quota exhaustion.
            details = f"HTTP {getattr(e, 'code', '?')}: {getattr(e, 'reason', '')}".strip()
            try:
                raw = e.read().decode("utf-8")
                if raw:
                    # Best-effort parse. If it isn't JSON, keep raw.
                    try:
                        j = json.loads(raw)
                        details = (details + " | " + json.dumps(j, ensure_ascii=False)) if details else json.dumps(j, ensure_ascii=False)
                    except Exception:
                        details = (details + " | " + raw) if details else raw
            except Exception:
                pass

            retry_after = None
            try:
                retry_after = e.headers.get("Retry-After")
            except Exception:
                retry_after = None

            if getattr(e, "code", None) == 429:
                hint = " Try again shortly."
                if retry_after:
                    hint = f" Try again in ~{retry_after} seconds."
                return PlanGenerationResult(
                    ok=False,
                    plan=None,
                    warnings=[],
                    error=AIError(
                        error_type="rate_limited",
                        human_message=(
                            "OpenAI is rate-limiting this request (HTTP 429)." + hint + " "
                            "You can also use 'Template Draft (no AI)' as a fallback."
                        ).strip(),
                        details=details,
                    ),
                )

            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=[],
                error=AIError(
                    error_type="api_error",
                    human_message=f"AI generation failed: HTTP {getattr(e, 'code', '?')}.",
                    details=details,
                ),
            )
        except Exception as e:
            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=[],
                error=AIError(
                    error_type="api_error",
                    human_message="AI generation failed due to an API/network error.",
                    details=str(e),
                ),
            )

        try:
            content = body["choices"][0]["message"]["content"]
        except Exception:
            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=[],
                error=AIError(
                    error_type="api_error",
                    human_message="AI generation failed: unexpected API response format.",
                ),
            )

        try:
            plan = json.loads(content)
        except Exception as e:
            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=[],
                error=AIError(
                    error_type="invalid_json",
                    human_message="AI generation failed: response was not valid JSON.",
                    details=str(e),
                ),
            )

        validation: ValidationResult = validate_plan(plan, targets=targets_norm)
        if not validation.ok:
            return PlanGenerationResult(
                ok=False,
                plan=None,
                warnings=validation.warnings,
                error=AIError(
                    error_type="schema_invalid",
                    human_message="AI generation returned an invalid plan format.",
                    details="; ".join(validation.errors),
                ),
            )

        return PlanGenerationResult(ok=True, plan=plan, warnings=validation.warnings, error=None)
