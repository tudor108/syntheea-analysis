"""Structural accessibility checks for the optional AI Analysis Studio."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "src/prostate_journey/frontend/ai_studio.html"
CSS = ROOT / "src/prostate_journey/frontend/ai_studio.css"


class StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.labels: set[str] = set()
        self.controls: list[tuple[str, dict[str, str]]] = []
        self.landmarks: set[str] = set()
        self.inline_scripts = 0
        self.inline_styles = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "label" and values.get("for"):
            self.labels.add(values["for"])
        if tag in {"button", "input", "select", "textarea", "a"}:
            self.controls.append((tag, values))
        if tag in {"main", "header", "aside", "nav", "footer"}:
            self.landmarks.add(tag)
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        if tag == "style":
            self.inline_styles += 1


def main() -> int:
    parser = StructureParser()
    document = HTML.read_text(encoding="utf-8")
    stylesheet = CSS.read_text(encoding="utf-8")
    parser.feed(document)
    failures: list[str] = []
    for required in {"main", "header", "aside"}:
        if required not in parser.landmarks:
            failures.append(f"missing semantic landmark: {required}")
    if 'class="skip-link"' not in document:
        failures.append("missing skip link")
    if 'aria-live="assertive"' not in document or 'aria-live="polite"' not in document:
        failures.append("missing accessible live-region announcements")
    for required_text in (
        "Ask the Evidence",
        "Explore Tactics",
        "Specialist Analysis",
        "Run History",
        "Presentation mode",
        "INTERACTIVE SYNTHETIC ANALYSIS",
        "RUN THIS ANALYSIS",
        "Denominator preview",
    ):
        if required_text not in document:
            failures.append(f"missing specialist UX contract: {required_text}")
    if 'role="tablist"' not in document or 'role="tabpanel"' not in document:
        failures.append("missing semantic mode tabs")
    if document.count('role="tabpanel"') != 4:
        failures.append("AI Studio must expose exactly four top-level tab panels")
    if 'role="log"' not in document or 'role="dialog"' not in document:
        failures.append("missing accessible transcript or drawer semantics")
    if parser.inline_scripts or parser.inline_styles:
        failures.append("inline script/style conflicts with strict CSP")
    for tag, attrs in parser.controls:
        if tag in {"select", "textarea", "input"}:
            control_id = attrs.get("id", "")
            if not control_id or control_id not in parser.labels:
                failures.append(f"unlabelled form control: {tag}#{control_id}")
        if tag == "button" and not (
            attrs.get("aria-label") or attrs.get("id") or attrs.get("class")
        ):
            failures.append("button lacks a stable accessible naming hook")
    for required_css in (":focus-visible", "prefers-reduced-motion", "@media (max-width"):
        if required_css not in stylesheet:
            failures.append(f"missing CSS accessibility behavior: {required_css}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("AI Studio structural accessibility check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
