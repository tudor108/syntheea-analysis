"""Run structural accessibility checks on a generated presentation package."""

from __future__ import annotations

import argparse
from pathlib import Path

from prostate_journey.frontend_validation import validate_frontend_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    failures = validate_frontend_package(args.package)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Frontend structural accessibility check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
