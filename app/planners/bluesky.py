from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BlueskyPlan:
    text: str
    hashtags: list[str]
    alt_text: list[str]


def from_canonical(plan: dict[str, Any]) -> BlueskyPlan:
    b = plan["bluesky"]
    return BlueskyPlan(
        text=str(b["text"]),
        hashtags=[str(x) for x in b["hashtags"]],
        alt_text=[str(x) for x in b["alt_text"]],
    )
