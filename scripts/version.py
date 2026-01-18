#!/usr/bin/env python3
"""Version helper.

Usage:
  python scripts/version.py           # prints current version
  python scripts/version.py bump patch
  python scripts/version.py bump minor
  python scripts/version.py bump major
  python scripts/version.py set 1.2.3

This repo isn't packaged (no pyproject), so VERSION is the single source of truth.
Optionally creates a dated section in CHANGELOG.md when bumping.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"


_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, s: str) -> "SemVer":
        m = _SEMVER_RE.match(s.strip())
        if not m:
            raise ValueError(f"Invalid semver: {s!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def bump(self, part: str) -> "SemVer":
        if part == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        if part == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if part == "major":
            return SemVer(self.major + 1, 0, 0)
        raise ValueError("part must be one of: patch, minor, major")


def read_version() -> SemVer:
    if not VERSION_FILE.exists():
        raise SystemExit(f"Missing {VERSION_FILE}")
    return SemVer.parse(VERSION_FILE.read_text(encoding="utf-8").strip())


def write_version(v: SemVer) -> None:
    VERSION_FILE.write_text(f"{v}\n", encoding="utf-8")


def ensure_changelog_section(version: SemVer) -> None:
    if not CHANGELOG_FILE.exists():
        return

    text = CHANGELOG_FILE.read_text(encoding="utf-8")
    header = f"## [{version}] - {date.today().isoformat()}"
    if header in text:
        return

    # Insert right after "Unreleased" header.
    marker = "## [Unreleased]"
    idx = text.find(marker)
    if idx == -1:
        return

    insert_at = idx + len(marker)
    insertion = (
        "\n\n"
        + header
        + "\n"
        + "### Added\n"
        + "- \n"
    )
    CHANGELOG_FILE.write_text(text[:insert_at] + insertion + text[insert_at:], encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    bump = sub.add_parser("bump", help="bump semantic version")
    bump.add_argument("part", choices=["patch", "minor", "major"])
    bump.add_argument("--changelog", action="store_true", help="add a new dated section to CHANGELOG.md")

    setp = sub.add_parser("set", help="set an explicit version")
    setp.add_argument("version")
    setp.add_argument("--changelog", action="store_true", help="add a new dated section to CHANGELOG.md")

    args = p.parse_args()

    if not args.cmd:
        print(read_version())
        return

    if args.cmd == "bump":
        v = read_version().bump(args.part)
        write_version(v)
        if args.changelog:
            ensure_changelog_section(v)
        print(v)
        return

    if args.cmd == "set":
        v = SemVer.parse(args.version)
        write_version(v)
        if args.changelog:
            ensure_changelog_section(v)
        print(v)
        return

    raise SystemExit(2)


if __name__ == "__main__":
    main()
