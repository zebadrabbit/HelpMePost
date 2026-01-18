from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YouTubePlan:
    title: str
    description: str
    tags: list[str]
    category: str


def from_canonical(plan: dict[str, Any]) -> YouTubePlan:
    y = plan["youtube"]
    return YouTubePlan(
        title=str(y["title"]),
        description=str(y["description"]),
        tags=[str(x) for x in y["tags"]],
        category=str(y["category"]),
    )
