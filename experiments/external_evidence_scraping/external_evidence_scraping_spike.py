"""Feasibility spike for bounded mHSPC/mCSPC HTML evidence collection."""

from __future__ import annotations

import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "prostate-patient-journey-external-evidence-spike/1.0"}
TIMEOUT_SECONDS = 8
REQUEST_DELAY_SECONDS = 0.5
TARGET_STUDIES = 5

# Fifteen bounded article/publisher/repository pages; this is not a crawler.
CANDIDATE_SOURCES = [
    ("cancerlinq", "https://linkinghub.elsevier.com/retrieve/pii/S1078143924005428"),
    ("alberta", "https://www.tandfonline.com/doi/full/10.1080/14796694.2025.2479374"),
    ("us_eu5_japan", "https://link.springer.com/article/10.1186/s12894-022-00979-9"),
    ("contemporary_mhspc", "https://www.tandfonline.com/doi/full/10.1080/14796694.2025.2481024"),
    ("international_trends", "https://academic.oup.com/oncolo/article/28/9/780/7103238"),
    ("pmc_8915525", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8915525/"),
    ("pmc_10485292", "https://pmc.ncbi.nlm.nih.gov/articles/PMC10485292/"),
    ("pmc_11573622", "https://pmc.ncbi.nlm.nih.gov/articles/PMC11573622/"),
    ("pmc_11988207", "https://pmc.ncbi.nlm.nih.gov/articles/PMC11988207/"),
    ("pmc_12051548", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12051548/"),
    ("pmc_10485288", "https://pmc.ncbi.nlm.nih.gov/articles/PMC10485288/"),
    ("cmar_candidate", "https://www.tandfonline.com/doi/full/10.2147/CMAR.S506423"),
    ("fon_candidate", "https://www.tandfonline.com/doi/full/10.2217/fon-2023-0814"),
    ("euo_candidate", "https://www.europeanurology.com/article/S2588-9311(25)00228-7/fulltext"),
    ("annals_candidate", "https://www.annalsofoncology.org/article/S0923-7534(21)03365-2/fulltext"),
]

METRICS = ("intensification_rate", "adt_monotherapy_rate", "arpi_or_nha_rate", "chemotherapy_rate", "triplet_rate")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def discover_candidates() -> list[dict[str, str]]:
    return [{"candidate_id": candidate_id, "url": url} for candidate_id, url in CANDIDATE_SOURCES]


def check_html_accessibility(url: str) -> tuple[BeautifulSoup | None, str, bool, str]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, "", False, exc.__class__.__name__

    soup = BeautifulSoup(response.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    lower = text.lower()
    blocked = any(marker in lower for marker in (
        "captcha", "recaptcha", "checking your browser", "cookies must be enabled",
        "enable javascript and cookies", "just a moment", "access denied",
    ))
    has_article = bool(soup.select_one('meta[name="citation_title"]') or soup.select_one("article h1, main h1"))
    has_content = bool(soup.select_one(".abstract, section#Abs1, .c-article-section__content, table"))
    usable = not blocked and has_article and has_content
    status = f"HTTP {response.status_code}; {'usable article HTML' if usable else 'unusable article HTML'}"
    return soup, text, usable, status


def assess_relevance(text: str) -> bool:
    lower = text.lower()
    population = any(term in lower for term in ("mhspc", "mcspc", "metastatic hormone-sensitive", "metastatic castration-sensitive"))
    endpoint = any(term in lower for term in ("treatment intensification", "treatment pattern", "adt alone", "novel hormonal", "nha", "chemotherapy", "triplet", "treatment uptake"))
    return population and endpoint


def support_fragment(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return ""
    return clean(text[max(0, match.start() - 80):match.end() + 160])[:240]


def extract_study(soup: BeautifulSoup, text: str, candidate_id: str) -> tuple[dict[str, Any], list[tuple[str, Any, str]]]:
    values: dict[str, Any] = {}
    evidence: list[tuple[str, Any, str]] = []

    title = soup.select_one('meta[name="citation_title"]')
    date = soup.select_one('meta[name="citation_publication_date"], meta[name="citation_date"]')
    if title:
        values["study_title"] = clean(title.get("content", ""))
        evidence.append(("study_title", values["study_title"], values["study_title"][:240]))
    if date and date.get("content", "")[:4].isdigit():
        values["publication_year"] = int(date["content"][:4])
        evidence.append(("publication_year", values["publication_year"], date["content"]))

    if candidate_id == "us_eu5_japan":
        abstract = clean((soup.select_one(".c-article-section__content") or soup).get_text(" ", strip=True))
        sample = re.search(r"provided data on (\d+) mHSPC patients", abstract, re.IGNORECASE)
        if sample:
            values["sample_size"] = int(sample.group(1))
            values["population"] = "mHSPC patients"
            evidence.extend([
                ("sample_size", values["sample_size"], support_fragment(abstract, r"provided data on \d+ mHSPC patients")),
                ("population", values["population"], support_fragment(abstract, r"mHSPC patients")),
            ])
        for field, pattern in (("adt_monotherapy_rate", r"ADT alone \((\d+)%\)"), ("arpi_or_nha_rate", r"NHAs? \([^)]*\) \((\d+)%"), ("chemotherapy_rate", r"chemotherapy \([^)]*\) \((\d+)%\)")):
            match = re.search(pattern, abstract, re.IGNORECASE)
            if match:
                values[field] = float(match.group(1))
                evidence.append((field, values[field], support_fragment(abstract, pattern)))
    elif candidate_id == "international_trends":
        abstract = clean((soup.select_one(".abstract") or soup).get_text(" ", strip=True))
        values["population"] = "adult patients with mCSPC"
        evidence.append(("population", values["population"], support_fragment(abstract, r"adult patients with mCSPC")))
        if "2016-2018" in abstract and "2019-2020" in abstract:
            values["time_window"] = "2016-2018 versus 2019-2020"
            evidence.append(("time_window", values["time_window"], support_fragment(abstract, r"2016-2018 and in 2019-2020")))
        values["main_finding"] = "Most patients did not receive intensification; NHT use increased in 2019-2020."
        evidence.append(("main_finding", values["main_finding"], support_fragment(abstract, r"most patients with mCSPC do not receive treatment intensification")))
    return values, evidence


def validate_study(record: dict[str, Any]) -> tuple[bool, str]:
    required = ("study_title", "publication_year", "population", "sample_size", "source_url")
    if any(record.get(field) is None for field in required):
        return False, "missing title/year/population/sample/source"
    if not any(record.get(field) is not None for field in METRICS):
        return False, "no meaningful treatment benchmark"
    if record["sample_size"] <= 0 or any(record.get(field) is not None and not 0 <= record[field] <= 100 for field in METRICS):
        return False, "invalid sample size or percentage"
    return True, "quality gate passed"


def select_best_five(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [record for record in records if record["quality_gate"]]
    eligible.sort(key=lambda record: sum(record.get(field) is not None for field in METRICS), reverse=True)
    return eligible[:TARGET_STUDIES]


def main() -> None:
    candidates = discover_candidates()
    records: list[dict[str, Any]] = []
    rejected_access = rejected_relevance = rejected_quality = 0

    for candidate in candidates:
        soup, text, usable, status = check_html_accessibility(candidate["url"])
        if not usable:
            rejected_access += 1
            print(f"REJECT {candidate['candidate_id']}: {status}")
            continue
        if not assess_relevance(text):
            rejected_relevance += 1
            print(f"REJECT {candidate['candidate_id']}: relevance gate")
            continue
        values, evidence = extract_study(soup, text, candidate["candidate_id"])
        record = {"study_id": candidate["candidate_id"], "source_url": candidate["url"], **values}
        record["quality_gate"], reason = validate_study(record)
        if not record["quality_gate"]:
            rejected_quality += 1
        records.append(record)
        print(f"CANDIDATE {candidate['candidate_id']}: {reason}")
        for field, value, support in evidence:
            print(f"EVIDENCE {candidate['candidate_id']} | {field} | {value} | {support}")
        time.sleep(REQUEST_DELAY_SECONDS)

    selected = select_best_five(records)
    if len(selected) == TARGET_STUDIES:
        decision = "KEEP"
    else:
        decision = "NO-GO"
    print(f"Candidates evaluated: {len(candidates)}")
    print(f"Usable studies: {len(selected)}")
    print(f"Rejected for relevance: {rejected_relevance}")
    print(f"Rejected for inaccessible/unusable HTML: {rejected_access}")
    print(f"Failed quality gate: {rejected_quality}")
    print(f"Target studies: {TARGET_STUDIES}")
    print(f"Decision: {decision}")


if __name__ == "__main__":
    main()
