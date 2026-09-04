# External Evidence HTML Scraping Feasibility Spike

## Objective

This experiment evaluated whether a small real-world mHSPC/mCSPC external benchmark could be collected automatically from public article HTML using `requests` and `BeautifulSoup`. The target was five relevant studies with sample size and at least one meaningful treatment-pattern or treatment-intensification benchmark.

## Why this was explored

The synthetic project contains treatment-initiation and treatment-intensification analyses. External real-world studies could provide useful contextual benchmarks. They were intended for contextualization, not direct validation of synthetic rates.

## Approach

The spike uses a bounded candidate pool and a simple workflow:

`candidate pool -> HTML accessibility check -> article-content validation -> relevance gate -> evidence-quality gate -> extraction attempt`

Fifteen distinct candidate pages were evaluated. The script uses ordinary HTTP requests, BeautifulSoup parsing, short timeouts, a clear user agent, and a polite delay. It rejects challenge, login, paywall, landing, JavaScript-shell, and error pages. It does not crawl indefinitely.

## Success criteria

A selected study needed:

- mHSPC/mCSPC relevance;
- real-world or observational treatment-pattern relevance;
- accessible article HTML;
- sample size;
- at least one meaningful treatment benchmark;
- defensible source provenance.

Target: five usable studies.

## Results

Final observed assessment:

- candidates evaluated: 15
- inaccessible/unusable HTML: 13
- failed quality gate: 1
- studies meeting the full criteria: 1

The one successful study demonstrated that the technical extraction pattern works, but this was insufficient for the intended five-study benchmark. Results can vary with publisher availability; the spike records the observed feasibility outcome rather than creating benchmark datasets.

## Decision

**NO-GO / STOP**

Automated HTML scraping using `requests` and `BeautifulSoup` was not sufficiently reliable for this specific external-evidence use case. The benchmark was not promoted into the project because doing so would require weakening evidence-quality requirements, manually inventing or filling missing data, or substantially increasing scraping complexity. None of those options were justified for a five-study contextual benchmark.

## What worked

HTTP retrieval, BeautifulSoup parsing, article-content validation, challenge/landing/error-page rejection, relevance and quality gates, source provenance, and bounded candidate assessment all worked as a feasibility demonstration.

## What did not work

Stable access to enough publisher, PMC, or PubMed article HTML was not available. Five studies with useful treatment metrics could not be extracted reliably.

## Recommendation

If external benchmarking is required later, prefer a small manually curated and source-validated evidence dataset or an approved structured literature/data source. Do not extend this spike with Selenium or increasingly complex scraping.

## Guardrails

There was no paywall, access, CAPTCHA, or anti-bot bypass; no Selenium or browser automation; no fabricated benchmark values; and no claim that external studies validate synthetic project results.

`requests` and `beautifulsoup4` are required only to reproduce this experiment. They were not added to `pyproject.toml` or `requirements.txt`.
