"""Fail CI when a repository-local Markdown link points to a missing file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
SKIP_SCHEMES = {"http", "https", "mailto", "tel", "data"}
GENERATED_ROOTS = {"data", "outputs", "external"}


def local_link_target(document: Path, raw: str, root: Path) -> Path | None:
    value = raw.strip().strip("<>").split(maxsplit=1)[0]
    parsed = urlsplit(value)
    if parsed.scheme.lower() in SKIP_SCHEMES or not parsed.path or parsed.path.startswith("#"):
        return None
    if "{" in parsed.path or "<" in parsed.path:
        return None
    decoded = unquote(parsed.path)
    if re.match(r"^[A-Za-z]:[/\\]", decoded):
        return None
    if decoded.startswith("/"):
        return (root / decoded.lstrip("/")).resolve()
    return (document.parent / decoded).resolve()


def check_links(root: Path) -> list[str]:
    failures: list[str] = []
    for document in sorted(root.rglob("*.md")):
        relative_parts = document.relative_to(root).parts
        if relative_parts[0] in GENERATED_ROOTS or any(
            part.startswith(".") and part not in {"."} for part in relative_parts
        ):
            continue
        text = document.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in LINK.finditer(line):
                target = local_link_target(document, match.group(1), root)
                if target is not None and not target.exists():
                    failures.append(
                        f"{document.relative_to(root).as_posix()}:{line_number}: missing {target}"
                    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()
    failures = check_links(root)
    if failures:
        print("\n".join(failures))
        return 1
    print("Markdown local-link check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
