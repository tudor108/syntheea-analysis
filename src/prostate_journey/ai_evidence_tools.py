"""Deterministic, path-free evidence tools for Ask the Evidence."""

from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ai_artifact_catalog import ArtifactCatalogue, ArtifactRecord, ArtifactStore

STOP_WORDS = {
    "about",
    "after",
    "again",
    "among",
    "and",
    "are",
    "care",
    "current",
    "data",
    "does",
    "evidence",
    "for",
    "from",
    "have",
    "how",
    "into",
    "patient",
    "project",
    "show",
    "synthetic",
    "that",
    "the",
    "this",
    "what",
    "when",
    "which",
    "with",
}
BLOCK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential_access",
        re.compile(r"(?i)(api\s*key|openai[_ -]?api[_ -]?key|secret|credential|\.env|token value)"),
    ),
    (
        "patient_level_access",
        re.compile(
            r"(?i)(patient[- ]level|individual patient|patient identifiers?|list patients|"
            r"row[- ]level|raw patients?|reconstruct.*patient)"
        ),
    ),
    (
        "instruction_override",
        re.compile(
            r"(?i)(ignore (all |the )?(previous|developer|system) instructions|"
            r"reveal (the )?(system|developer) prompt|act as system)"
        ),
    ),
    (
        "arbitrary_execution",
        re.compile(
            r"(?i)(run (a )?(shell|sql|python)|execute (this )?(command|code)|"
            r"drop table|select \* from|\.\./|powershell|cmd\.exe)"
        ),
    ),
    (
        "unsupported_web_access",
        re.compile(r"(?i)(browse the web|search the internet|google this|latest news)"),
    ),
    (
        "clinical_recommendation",
        re.compile(
            r"(?i)(recommend(ed)? treatment|which treatment should|patient action|"
            r"prescribe|clinical decision)"
        ),
    ),
    (
        "unsupported_clinical_endpoint",
        re.compile(r"(?i)(overall survival|hazard ratio|progression[- ]free survival)"),
    ),
    (
        "release_override",
        re.compile(r"(?i)(use|switch to|load).{0,25}(another|different|stale) release"),
    ),
    (
        "certified_output_mutation",
        re.compile(r"(?i)(overwrite|modify|replace).{0,30}certified (result|output|release)"),
    ),
    (
        "unavailable_tool",
        re.compile(r"(?i)(call|invoke|use).{0,25}(unavailable|disallowed) tool"),
    ),
    (
        "external_exfiltration",
        re.compile(r"(?i)(send|upload|exfiltrate).{0,35}(externally|outside|third party)"),
    ),
    (
        "evidence_fabrication",
        re.compile(r"(?i)(claim|say|pretend).{0,35}(real )?bayer evidence"),
    ),
    (
        "denominator_concealment",
        re.compile(r"(?i)(change|modify).{0,30}denominator.{0,30}(hide|conceal)"),
    ),
)

UNTRUSTED_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(r"(?i)(ignore|disregard|override).{0,40}(instruction|system|developer|policy)"),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"(?i)(reveal|print|return|exfiltrate).{0,50}"
            r"(prompt|api.?key|credential|secret|token|environment)"
        ),
    ),
    (
        "tool_coercion",
        re.compile(
            r"(?i)(call|invoke|execute|run).{0,35}"
            r"(tool|function|shell|python|powershell|sql|web.?search)"
        ),
    ),
    (
        "role_spoofing",
        re.compile(r"(?i)(^|[\s{<])(?:system|developer|assistant)\s*[:=>]"),
    ),
)


def detect_prompt_injection(value: str) -> str | None:
    """Classify instruction-like content found inside any untrusted source field."""
    normalized = html.unescape(value).replace("\\u003c", "<").replace("\\u003e", ">")
    for category, pattern in UNTRUSTED_INJECTION_PATTERNS:
        if pattern.search(normalized):
            return category
    for category, pattern in BLOCK_PATTERNS:
        if pattern.search(normalized):
            return category
    return None


def sanitize_untrusted_text(value: str) -> str:
    """Remove instruction-bearing fields before they enter the model context."""
    category = detect_prompt_injection(value)
    if category:
        return f"[UNTRUSTED INSTRUCTION CONTENT REMOVED: {category}]"
    return value


def sanitize_untrusted_value(value: Any) -> Any:
    """Recursively sanitize every string-bearing field from an untrusted artifact."""
    if isinstance(value, str):
        return sanitize_untrusted_text(value)
    if isinstance(value, list):
        return [sanitize_untrusted_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_untrusted_value(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_untrusted_text(str(key)): sanitize_untrusted_value(item)
            for key, item in value.items()
        }
    return value


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArtifactsInput(StrictInput):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class ArtifactSectionInput(StrictInput):
    artifact_id: str = Field(pattern=r"^artifact_[A-Za-z0-9]+$")
    section: str | None = Field(default=None, max_length=120)


class MetricDefinitionInput(StrictInput):
    metric_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_]+$")


class CertifiedMetricInput(StrictInput):
    metric_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_]+$")
    market: str = Field(default="ALL", min_length=2, max_length=8)

    @field_validator("market")
    @classmethod
    def _market_code(cls, value: str) -> str:
        normalized = value.upper()
        if normalized != "ALL" and not re.fullmatch(r"[A-Z]{2}", normalized):
            raise ValueError("market must be ALL or one configured two-letter scenario code")
        return normalized


class DenominatorDefinitionInput(StrictInput):
    tactic_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_]+$")


class TacticCardInput(StrictInput):
    tactic_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_]+$")


class TacticResultInput(TacticCardInput):
    market: str = Field(default="ALL", min_length=2, max_length=8)


class ReleaseManifestInput(StrictInput):
    pass


class CompareMetricsInput(StrictInput):
    metric_ids: list[str] = Field(min_length=2, max_length=5)
    market: str = Field(default="ALL", min_length=2, max_length=8)

    @model_validator(mode="after")
    def _unique_metrics(self) -> CompareMetricsInput:
        if len(self.metric_ids) != len(set(self.metric_ids)):
            raise ValueError("metric_ids must be unique")
        return self


class ListTacticsInput(StrictInput):
    category: str | None = Field(default=None, max_length=60)


class MetricEvidence(BaseModel):
    """Exact aggregate metric and denominator returned by deterministic code."""

    model_config = ConfigDict(extra="forbid")

    metric_id: str
    label: str
    value: float
    unit: Literal["percent", "count", "days"]
    numerator: int | float
    denominator: int | float
    rate: float | None
    population: str
    time_window: str
    market: str
    method: str
    analysis_id: str
    tactic_id: str
    source_artifact_id: str
    source_file: str
    evidence_status: Literal["directly evidenced", "derived deterministically"]


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_name: str
    artifact_type: str
    score: float
    excerpt: str
    certification_status: str
    permitted_use: str


class GroundingPacket(BaseModel):
    """Small bounded context sent to the model."""

    model_config = ConfigDict(extra="forbid")

    question: str
    release_id: str
    metrics: list[MetricEvidence]
    tactics: list[dict[str, Any]]
    narrative_results: list[SearchResult]
    model_evidence_available: bool
    evidence_sufficient: bool
    suggested_tactic_ids: list[str]
    allowed_numbers: list[str]


def guard_question(question: str) -> str | None:
    """Return a refusal category for requests outside read-only aggregate evidence Q&A."""
    normalized = question.strip()
    injection = detect_prompt_injection(normalized)
    if injection:
        return injection
    for category, pattern in BLOCK_PATTERNS:
        if pattern.search(normalized):
            return category
    return None


def _tokens(value: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9_]{2,}", value.casefold()) if token not in STOP_WORDS
    ]


def _strip_markup(value: str) -> str:
    no_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    no_tags = re.sub(r"(?s)<[^>]+>", " ", no_scripts)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


class EvidenceTools:
    """Strict deterministic API over the active aggregate catalogue."""

    def __init__(
        self,
        project_root: str | Path,
        catalogue: ArtifactCatalogue,
    ) -> None:
        self.root = Path(project_root).resolve()
        self.catalogue = catalogue
        self.store = ArtifactStore(self.root, catalogue)
        self.records_by_name: dict[str, list[ArtifactRecord]] = {}
        for record in catalogue.artifacts:
            self.records_by_name.setdefault(record.artifact_name, []).append(record)
        self.registry = self._json_artifact("tactic_registry.json")
        self.tactics = {str(item["tactic_id"]): item for item in self.registry.get("tactics", [])}
        self.aggregate_rows = self._csv_artifact("aggregate_export.csv")
        self.aggregate_metrics = {
            str(row["metric_id"]): row for row in self.aggregate_rows if row.get("metric_id")
        }
        self.dashboard_data = self._dashboard_payload()

    def _preferred_record(self, name: str) -> ArtifactRecord:
        matches = self.records_by_name.get(name, [])
        if not matches:
            raise KeyError(f"approved artifact is unavailable: {name}")
        return sorted(
            matches,
            key=lambda item: (
                item.source_scope != "presentation",
                item.source_scope != "release",
            ),
        )[0]

    def _json_artifact(self, name: str) -> dict[str, Any]:
        record = self._preferred_record(name)
        payload = json.loads(self.store.read(record.artifact_id, max_characters=2_000_000))
        if not isinstance(payload, dict):
            raise ValueError(f"approved JSON artifact must be an object: {name}")
        return payload

    def _csv_artifact(self, name: str) -> list[dict[str, str]]:
        record = self._preferred_record(name)
        return list(csv.DictReader(self.store.read(record.artifact_id).splitlines()))

    def _dashboard_payload(self) -> dict[str, Any]:
        record = self._preferred_record("executive_story.html")
        document = self.store.read(record.artifact_id, max_characters=2_000_000)
        match = re.search(
            r'<script id="dashboardData" type="application/json">(.*?)</script>',
            document,
            re.DOTALL,
        )
        if not match:
            raise ValueError("certified dashboard payload is unavailable")
        payload = json.loads(match.group(1))
        if payload.get("provenance", {}).get("release_id") != self.catalogue.release_id:
            raise ValueError("dashboard payload release does not match active catalogue")
        if payload.get("synthetic_only") is not True:
            raise ValueError("dashboard payload is not marked synthetic-only")
        return payload

    def _source_id(self, name: str) -> str:
        return self._preferred_record(name).artifact_id

    def list_available_tactics(self, category: str | None = None) -> list[dict[str, Any]]:
        values = list(self.tactics.values())
        if category:
            normalized = category.casefold()
            values = [
                item
                for item in values
                if str(item.get("category", "")).casefold() == normalized
                or normalized in {str(tag).casefold() for tag in item.get("tags", [])}
            ]
        return [
            {
                "tactic_id": item["tactic_id"],
                "title": item["title"],
                "category": item["category"],
                "question": item["question"],
                "reviewer_status": item["reviewer_status"],
                "synthetic_only": item["synthetic_only"],
            }
            for item in values
        ]

    def get_tactic_card(self, tactic_id: str) -> dict[str, Any]:
        try:
            item = self.tactics[tactic_id]
        except KeyError as error:
            raise KeyError("tactic_id is not available in the active registry") from error
        return dict(item)

    def get_denominator_definition(self, tactic_id: str) -> dict[str, Any]:
        tactic = self.get_tactic_card(tactic_id)
        return {
            "tactic_id": tactic_id,
            "target_population": tactic["target_population"],
            "numerator_definition": tactic["numerator_definition"],
            "denominator_definition": tactic["denominator_definition"],
            "index_date": tactic["index_date"],
            "time_horizon": tactic["time_horizon"],
            "method": tactic["method"],
            "release_id": self.catalogue.release_id,
        }

    def get_metric_definition(self, metric_id: str) -> dict[str, Any]:
        if metric_id in self.aggregate_metrics:
            row = self.aggregate_metrics[metric_id]
            return {
                "metric_id": metric_id,
                "population": row["population"],
                "time_window": row["time_window"],
                "method": row["method"],
                "release_id": row["release_id"],
                "source_file": "aggregate_export.csv",
            }
        aliases = self._market_metric_aliases("ALL")
        if metric_id in aliases:
            return {
                "metric_id": metric_id,
                **{key: aliases[metric_id][key] for key in ("population", "time_window", "method")},
                "release_id": self.catalogue.release_id,
                "source_file": "executive_story.html",
            }
        raise KeyError("metric_id is not available in certified aggregate outputs")

    def _from_aggregate(self, metric_id: str) -> MetricEvidence:
        row = self.aggregate_metrics[metric_id]
        numerator = float(row["numerator"])
        denominator = float(row["denominator"])
        rate = float(row["rate"]) if row.get("rate") else None
        tactic_id = {
            "eligible": "cohort_definition",
            "initiated_30d": "initiation_landmarks",
            "not_initiated_30d_evaluable": "initiation_landmarks",
            "initiated_60d": "initiation_landmarks",
            "not_initiated_60d_evaluable": "initiation_landmarks",
            "initiated_90d": "initiation_landmarks",
            "not_initiated_90d_evaluable": "initiation_landmarks",
            "persistent_12m_gap_30d": "persistence_sensitivity",
            "persistent_12m_gap_60d": "persistence_sensitivity",
            "persistent_12m_gap_90d": "persistence_sensitivity",
        }[metric_id]
        return MetricEvidence(
            metric_id=metric_id,
            label=metric_id.replace("_", " "),
            value=round(rate * 100, 4) if rate is not None else numerator,
            unit="percent" if rate is not None else "count",
            numerator=int(numerator),
            denominator=int(denominator),
            rate=rate,
            population=row["population"],
            time_window=row["time_window"],
            market="ALL",
            method=row["method"],
            analysis_id=str(self.tactics[tactic_id]["analysis_id"]),
            tactic_id=tactic_id,
            source_artifact_id=self._source_id("aggregate_export.csv"),
            source_file="aggregate_export.csv",
            evidence_status="directly evidenced",
        )

    def _market_metric_aliases(self, market: str) -> dict[str, dict[str, Any]]:
        segments = self.dashboard_data["segments"]
        if market not in segments:
            raise KeyError("market is not a configured synthetic scenario")
        segment = segments[market]
        result: dict[str, dict[str, Any]] = {
            "total": {
                "numerator": segment["total"],
                "denominator": segment["total"],
                "population": "All generated records in the selected synthetic scenario.",
                "time_window": "Release cohort",
                "method": "Distinct generated-record count.",
                "analysis_id": "cohort_definition",
                "tactic_id": "cohort_definition",
            },
            "eligible": {
                "numerator": segment["eligible"],
                "denominator": segment["total"],
                "population": "Generated records in the selected synthetic scenario.",
                "time_window": "Eligibility at index",
                "method": "Configured synthetic eligibility rule.",
                "analysis_id": "cohort_definition",
                "tactic_id": "cohort_definition",
            },
            "censored_12m": {
                "numerator": segment["censored12"],
                "denominator": segment["initiated90"],
                "population": "Eligible day-90 initiators in the selected scenario.",
                "time_window": "12 months after treatment start",
                "method": "Explicit month-12 evaluability reconciliation.",
                "analysis_id": "censoring_audit",
                "tactic_id": "censoring_evaluability",
            },
            "referral_completion": {
                "numerator": segment["referrals"]["completed"],
                "denominator": segment["referrals"]["total"],
                "population": "Generated referrals in the selected synthetic scenario.",
                "time_window": "Referral to governed observation boundary",
                "method": "Completed referral proportion.",
                "analysis_id": "referral_pathway",
                "tactic_id": "referral_pathway",
            },
        }
        for item in segment["initiation_windows"]:
            result[f"initiated_{item['days']}d"] = {
                "numerator": item["value"],
                "denominator": segment["eligible"],
                "population": "Eligible generated records in the selected scenario.",
                "time_window": f"{item['days']} days after eligibility",
                "method": "Censor-aware cumulative landmark proportion.",
                "analysis_id": "initiation_funnel",
                "tactic_id": "initiation_landmarks",
            }
            result[f"not_initiated_{item['days']}d_evaluable"] = {
                "numerator": item["gap"],
                "denominator": item["evaluable"],
                "population": "Eligible records evaluable through the selected landmark.",
                "time_window": f"{item['days']} days after eligibility",
                "method": "Evaluable landmark complement.",
                "analysis_id": "initiation_funnel",
                "tactic_id": "initiation_landmarks",
            }
        for item in segment["persistence_sensitivity"]:
            result[f"persistent_12m_gap_{item['gap_days']}d"] = {
                "numerator": item["persistent"],
                "denominator": item["evaluable"],
                "population": "Evaluable eligible day-90 initiators.",
                "time_window": f"365 days; {item['gap_days']}-day permissible gap",
                "method": "Operational persistence landmark sensitivity.",
                "analysis_id": "persistence_landmark",
                "tactic_id": "persistence_sensitivity",
            }
        return result

    def get_certified_metric(self, metric_id: str, market: str = "ALL") -> MetricEvidence:
        normalized_market = market.upper()
        if normalized_market == "ALL" and metric_id in self.aggregate_metrics:
            return self._from_aggregate(metric_id)
        aliases = self._market_metric_aliases(normalized_market)
        if metric_id not in aliases:
            raise KeyError("metric_id is not available for the selected synthetic scenario")
        item = aliases[metric_id]
        numerator = float(item["numerator"])
        denominator = float(item["denominator"])
        rate = numerator / denominator if denominator else None
        return MetricEvidence(
            metric_id=metric_id,
            label=metric_id.replace("_", " "),
            value=round(rate * 100, 4) if rate is not None else numerator,
            unit="percent" if rate is not None else "count",
            numerator=int(numerator),
            denominator=int(denominator),
            rate=rate,
            population=item["population"],
            time_window=item["time_window"],
            market=normalized_market,
            method=item["method"],
            analysis_id=item["analysis_id"],
            tactic_id=item["tactic_id"],
            source_artifact_id=self._source_id("executive_story.html"),
            source_file="executive_story.html",
            evidence_status="derived deterministically",
        )

    def compare_certified_metrics(
        self, metric_ids: list[str], market: str = "ALL"
    ) -> list[MetricEvidence]:
        return [self.get_certified_metric(metric_id, market) for metric_id in metric_ids]

    def get_tactic_result(self, tactic_id: str, market: str = "ALL") -> list[MetricEvidence]:
        self.get_tactic_card(tactic_id)
        metric_map = {
            "cohort_definition": ["eligible"],
            "initiation_landmarks": ["initiated_30d", "initiated_60d", "initiated_90d"],
            "censoring_evaluability": ["censored_12m"],
            "persistence_sensitivity": [
                "persistent_12m_gap_30d",
                "persistent_12m_gap_60d",
                "persistent_12m_gap_90d",
            ],
            "time_to_initiation": ["initiated_30d", "initiated_60d", "initiated_90d"],
            "referral_pathway": ["referral_completion"],
            "segmented_treatment_gap": ["not_initiated_90d_evaluable"],
        }
        return [
            self.get_certified_metric(metric_id, market)
            for metric_id in metric_map.get(tactic_id, [])
        ]

    def get_release_manifest(self) -> dict[str, Any]:
        release = self._json_artifact("release_manifest.json")
        return {
            "release_id": self.catalogue.release_id,
            "created_at": release.get("created_at"),
            "decision": release.get("decision"),
            "immutable": release.get("immutable"),
            "synthetic_data_only": release.get("synthetic_data_only", True),
            "source_commit": release.get("git", {}).get("git_commit"),
            "catalogued_artifacts": len(self.catalogue.artifacts),
            "indexable_artifacts": sum(item.indexable for item in self.catalogue.artifacts),
            "warning": (
                "Historical internal release wording is not Bayer, clinical, RWE, or "
                "production approval."
            ),
        }

    def get_artifact_section(self, artifact_id: str, section: str | None = None) -> dict[str, Any]:
        record = self.store.record(artifact_id)
        content = _strip_markup(self.store.read(artifact_id, max_characters=30000))
        if section:
            folded = content.casefold()
            start = folded.find(section.casefold())
            if start < 0:
                excerpt = ""
            else:
                excerpt = content[start : start + 5000]
        else:
            excerpt = content[:5000]
        return {
            "artifact": record.model_dump(mode="json"),
            "section": section,
            "content": excerpt,
            "content_is_untrusted_evidence": True,
        }

    def search_certified_artifacts(self, query: str, top_k: int = 5) -> list[SearchResult]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, ArtifactRecord, str]] = []
        for record in self.catalogue.artifacts:
            if not record.indexable:
                continue
            raw = self.store.read(record.artifact_id, max_characters=24000)
            text = _strip_markup(raw)
            searchable = (
                f"{record.artifact_name} {record.artifact_type} "
                f"{record.analysis_id or ''} {' '.join(record.tactic_ids)} {text}"
            ).casefold()
            counts = Counter(_tokens(searchable))
            score = sum(min(counts[token], 8) for token in query_tokens)
            score += sum(3 for token in query_tokens if token in record.artifact_name.casefold())
            if score <= 0:
                continue
            first_positions = [searchable.find(token) for token in query_tokens]
            valid_positions = [position for position in first_positions if position >= 0]
            position = min(valid_positions) if valid_positions else 0
            excerpt_start = max(0, position - 180)
            excerpt = sanitize_untrusted_text(text[excerpt_start : excerpt_start + 900])
            scored.append((float(score), record, excerpt))
        scored.sort(key=lambda item: (-item[0], item[1].artifact_name))
        return [
            SearchResult(
                artifact_id=record.artifact_id,
                artifact_name=record.artifact_name,
                artifact_type=record.artifact_type,
                score=score,
                excerpt=excerpt,
                certification_status=record.certification_status,
                permitted_use=record.permitted_use,
            )
            for score, record, excerpt in scored[:top_k]
        ]

    def _suggest_tactics(self, question: str) -> list[str]:
        query_tokens = set(_tokens(question))
        scored: list[tuple[int, str]] = []
        for tactic_id, tactic in self.tactics.items():
            text = " ".join(
                [
                    tactic_id,
                    str(tactic.get("title", "")),
                    str(tactic.get("question", "")),
                    str(tactic.get("category", "")),
                    " ".join(map(str, tactic.get("tags", []))),
                ]
            )
            score = len(query_tokens.intersection(_tokens(text)))
            if score:
                scored.append((score, tactic_id))
        return [item[1] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[:3]]

    def _question_metrics(self, question: str, market: str) -> list[MetricEvidence]:
        folded = question.casefold()
        metric_ids: list[str] = []
        for explicit in self.aggregate_metrics:
            if explicit in folded:
                metric_ids.append(explicit)
        if "eligible" in folded or "cohort" in folded:
            metric_ids.append("eligible")
        if any(word in folded for word in ("initiat", "treatment gap", "neini")):
            days = next((value for value in (30, 60, 90) if str(value) in folded), 90)
            metric_ids.append(f"initiated_{days}d")
            if "gap" in folded or "not initi" in folded or "neini" in folded:
                metric_ids.append(f"not_initiated_{days}d_evaluable")
        if "persist" in folded:
            gap = next((value for value in (30, 60, 90) if str(value) in folded), 60)
            metric_ids.append(f"persistent_12m_gap_{gap}d")
        if "censor" in folded or "evaluab" in folded:
            metric_ids.append("censored_12m")
        if "referral" in folded or "trimit" in folded:
            metric_ids.append("referral_completion")
        unique: list[str] = []
        for metric_id in metric_ids:
            if metric_id not in unique:
                unique.append(metric_id)
        metrics: list[MetricEvidence] = []
        for metric_id in unique[:5]:
            try:
                metrics.append(self.get_certified_metric(metric_id, market))
            except KeyError:
                continue
        return metrics

    def build_grounding(
        self,
        question: str,
        *,
        market: str = "ALL",
        top_k: int = 4,
    ) -> GroundingPacket:
        if top_k < 1 or top_k > 5:
            raise ValueError("grounding top_k must remain between one and five")
        metrics = self._question_metrics(question, market)
        tactic_ids = list(
            dict.fromkeys([item.tactic_id for item in metrics] + self._suggest_tactics(question))
        )[:3]
        results = self.search_certified_artifacts(question, top_k=top_k)
        tactic_fields = (
            "tactic_id",
            "title",
            "question",
            "target_population",
            "numerator_definition",
            "denominator_definition",
            "time_horizon",
            "method",
            "limitation",
            "reviewer_status",
            "synthetic_only",
            "prohibited_interpretations",
        )
        tactics = [
            {field: card[field] for field in tactic_fields if field in card}
            for tactic_id in tactic_ids
            for card in [self.get_tactic_card(tactic_id)]
        ]
        model_available = bool(self.dashboard_data.get("models", {}).get("available"))
        sufficient = bool(metrics or tactics or (results and results[0].score >= 2))
        # Quantitative answer validation is intentionally stricter than narrative
        # retrieval. Only deterministic metric tools can authorize a number in a
        # generated answer; prose, user text, and retrieved snippets cannot.
        serialized = json.dumps(
            {
                "metrics": [
                    {
                        "metric_id": item.metric_id,
                        "value": item.value,
                        "numerator": item.numerator,
                        "denominator": item.denominator,
                        "rate": item.rate,
                        "time_window": item.time_window,
                    }
                    for item in metrics
                ]
            },
            ensure_ascii=False,
        )
        allowed_numbers = sorted(set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", serialized)))
        return GroundingPacket(
            question=question,
            release_id=self.catalogue.release_id,
            metrics=metrics,
            tactics=tactics,
            narrative_results=results,
            model_evidence_available=model_available,
            evidence_sufficient=sufficient,
            suggested_tactic_ids=tactic_ids,
            allowed_numbers=allowed_numbers,
        )

    def tool_contracts(self) -> list[dict[str, Any]]:
        contracts: dict[str, type[StrictInput]] = {
            "search_certified_artifacts": SearchArtifactsInput,
            "get_artifact_section": ArtifactSectionInput,
            "get_metric_definition": MetricDefinitionInput,
            "get_certified_metric": CertifiedMetricInput,
            "get_denominator_definition": DenominatorDefinitionInput,
            "get_tactic_card": TacticCardInput,
            "get_tactic_result": TacticResultInput,
            "get_release_manifest": ReleaseManifestInput,
            "compare_certified_metrics": CompareMetricsInput,
            "list_available_tactics": ListTacticsInput,
        }
        return [
            {
                "name": name,
                "strict": True,
                "parameters": model.model_json_schema(),
            }
            for name, model in contracts.items()
        ]

    def dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute one named tool after strict schema validation."""
        if name == "search_certified_artifacts":
            search_args = SearchArtifactsInput.model_validate(arguments)
            return self.search_certified_artifacts(search_args.query, search_args.top_k)
        if name == "get_artifact_section":
            section_args = ArtifactSectionInput.model_validate(arguments)
            return self.get_artifact_section(section_args.artifact_id, section_args.section)
        if name == "get_metric_definition":
            definition_args = MetricDefinitionInput.model_validate(arguments)
            return self.get_metric_definition(definition_args.metric_id)
        if name == "get_certified_metric":
            metric_args = CertifiedMetricInput.model_validate(arguments)
            return self.get_certified_metric(metric_args.metric_id, metric_args.market)
        if name == "get_denominator_definition":
            denominator_args = DenominatorDefinitionInput.model_validate(arguments)
            return self.get_denominator_definition(denominator_args.tactic_id)
        if name == "get_tactic_card":
            tactic_args = TacticCardInput.model_validate(arguments)
            return self.get_tactic_card(tactic_args.tactic_id)
        if name == "get_tactic_result":
            result_args = TacticResultInput.model_validate(arguments)
            return self.get_tactic_result(result_args.tactic_id, result_args.market)
        if name == "get_release_manifest":
            ReleaseManifestInput.model_validate(arguments)
            return self.get_release_manifest()
        if name == "compare_certified_metrics":
            comparison_args = CompareMetricsInput.model_validate(arguments)
            return self.compare_certified_metrics(
                comparison_args.metric_ids, comparison_args.market
            )
        if name == "list_available_tactics":
            list_args = ListTacticsInput.model_validate(arguments)
            return self.list_available_tactics(list_args.category)
        raise KeyError("unknown or prohibited evidence tool")
