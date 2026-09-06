"""Dependency-free structural accessibility and export-boundary checks."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


class _ProductHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: Counter[str] = Counter()
        self.ids: list[str] = []
        self.controls: list[str] = []
        self.labelled_controls: set[str] = set()
        self.label_for: set[str] = set()
        self.hrefs: list[str] = []
        self.buttons_without_type = 0
        self.dialogs_without_name = 0
        self.aria_live_regions = 0
        self.data_evidence_controls = 0
        self.table_depth = 0
        self.tables = 0
        self.table_captions = 0
        self.label_depth = 0
        self.html_lang: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags[tag] += 1
        element_id = attributes.get("id")
        if element_id:
            self.ids.append(element_id)
        if tag == "html":
            self.html_lang = attributes.get("lang")
        if tag == "label":
            self.label_depth += 1
            if attributes.get("for"):
                self.label_for.add(str(attributes["for"]))
        if tag in {"input", "select", "textarea"} and element_id:
            self.controls.append(element_id)
            if self.label_depth:
                self.labelled_controls.add(element_id)
        if tag == "button" and not attributes.get("type"):
            self.buttons_without_type += 1
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(str(attributes["href"]))
        if attributes.get("role") == "dialog" and not (
            attributes.get("aria-label") or attributes.get("aria-labelledby")
        ):
            self.dialogs_without_name += 1
        if attributes.get("aria-live"):
            self.aria_live_regions += 1
        if "data-evidence" in attributes:
            self.data_evidence_controls += 1
        if tag == "table":
            self.tables += 1
            self.table_depth += 1
        if tag == "caption" and self.table_depth:
            self.table_captions += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self.label_depth = max(0, self.label_depth - 1)
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)


def validate_frontend_package(package_dir: str | Path) -> list[str]:
    """Return structural accessibility or export-boundary failures for a generated package."""
    root = Path(package_dir)
    frontend = root / "executive_story.html"
    css_path = root / "assets" / "analytics.css"
    javascript_path = root / "assets" / "analytics.js"
    failures: list[str] = []
    for path in (frontend, css_path, javascript_path):
        if not path.is_file():
            failures.append(f"missing required frontend artifact: {path.name}")
    if failures:
        return failures

    markup = frontend.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")
    javascript = javascript_path.read_text(encoding="utf-8")
    parser = _ProductHTMLParser()
    parser.feed(markup)

    if parser.html_lang != "en":
        failures.append("html language must be declared as English")
    for landmark in ("header", "nav", "main", "footer"):
        if not parser.tags[landmark]:
            failures.append(f"missing {landmark} landmark")
    if 'class="skip-link" href="#main-content"' not in markup:
        failures.append("missing skip link to main content")
    duplicate_ids = sorted(key for key, count in Counter(parser.ids).items() if count > 1)
    if duplicate_ids:
        failures.append(f"duplicate element IDs: {duplicate_ids}")
    labelled = parser.labelled_controls | parser.label_for
    unlabelled = sorted(set(parser.controls) - labelled)
    if unlabelled:
        failures.append(f"unlabelled form controls: {unlabelled}")
    if parser.buttons_without_type:
        failures.append(f"buttons without an explicit type: {parser.buttons_without_type}")
    if parser.dialogs_without_name:
        failures.append(f"dialogs without an accessible name: {parser.dialogs_without_name}")
    if parser.aria_live_regions < 2:
        failures.append("denominator/filter changes require aria-live announcements")
    if parser.data_evidence_controls < 6:
        failures.append("material results do not expose enough evidence controls")
    if parser.tables != parser.table_captions:
        failures.append("every data table must include a caption")
    if any(href.lower().endswith((".parquet", ".duckdb")) for href in parser.hrefs):
        failures.append("patient-level or analytical-dataset export link found")
    if "SYNTHETIC SCENARIO — NOT REAL PATIENT" not in markup:
        failures.append("persistent synthetic-data warning is missing")
    if ":focus-visible" not in css:
        failures.append("visible keyboard focus style is missing")
    if "prefers-reduced-motion" not in css:
        failures.append("reduced-motion style is missing")
    if "@media (max-width: 760px)" not in css:
        failures.append("mobile reflow breakpoint is missing")
    if "DENOMINATOR CHANGED" not in javascript:
        failures.append("denominator-change announcement is missing")
    if "presentationSteps" not in javascript:
        failures.append("deterministic presentation sequence is missing")
    return failures
