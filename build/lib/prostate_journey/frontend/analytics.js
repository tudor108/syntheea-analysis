"use strict";

const dashboardData = JSON.parse(document.getElementById("dashboardData").textContent);
const numberFormat = new Intl.NumberFormat("en-US");
const validWindows = [30, 60, 90];
const validGaps = [30, 60, 90];
const viewNames = ["executive", "analyst", "methodology", "governance"];
const syntheticWarning =
  "SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA";
const prohibitedUse =
  "Not for clinical decisions, treatment recommendations, patient action, market ranking, causal claims, or production AI.";

const state = {
  market: "ALL",
  initiationWindow: 90,
  persistenceGap: 60,
  view: "executive",
  tacticFilter: "All",
  presentationMode: false,
  presentationStep: 0,
};

let lastFocus = null;

function byId(id) {
  return document.getElementById(id);
}

function formatCount(value) {
  return value === null || value === undefined ? "Not available" : numberFormat.format(value);
}

function formatPercent(value) {
  return value === null || value === undefined ? "Not evaluable" : `${Number(value).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function announce(message) {
  byId("liveStatus").textContent = message;
}

function selectedSegment() {
  return dashboardData.segments[state.market];
}

function initiationFor(segment = selectedSegment()) {
  return segment.initiation_windows.find((item) => item.days === state.initiationWindow);
}

function persistenceFor(segment = selectedSegment()) {
  return segment.persistence_sensitivity.find((item) => item.gap_days === state.persistenceGap);
}

function selectedMarketLabel() {
  return state.market === "ALL" ? "All configured scenarios" : state.market;
}

function activeDenominatorContext() {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  return {
    label: `${formatCount(segment.eligible)} eligible synthetic records`,
    count: segment.eligible,
    population: `${selectedMarketLabel()} — configured synthetic eligibility cohort`,
    included: "Meets the versioned eligibility rule and has a valid eligibility date.",
    excluded: `${formatCount(segment.total - segment.eligible)} selected records do not enter this eligibility cohort.`,
    timeZero: "eligibility_date",
    evaluability: `${formatCount(initiation.evaluable)} are evaluable through day ${state.initiationWindow}; ${formatCount(initiation.censored)} are censored before that landmark.`,
    censoring: "Death, loss to follow-up, or administrative end before the required landmark remains separate from non-initiation.",
  };
}

function evidenceContext(tacticId, resultOverride = null) {
  const tactic = dashboardData.tactics.find((item) => item.tactic_id === tacticId);
  const result = resultOverride || tacticResult(tacticId);
  return {
    title: tactic ? tactic.title : "Certified aggregate result",
    releaseId: dashboardData.provenance.release_id,
    sourceCommit: dashboardData.provenance.source_commit,
    configHash: dashboardData.provenance.configuration_hash,
    inputRelease: dashboardData.provenance.release_id,
    analysisId: tactic ? tactic.analysis_id : "not_recorded",
    tacticId: tactic ? tactic.tactic_id : "not_recorded",
    numerator: result.numeratorDefinition || tactic?.numerator_definition || "Not applicable",
    denominator: result.denominatorDefinition || tactic?.denominator_definition || "Not applicable",
    evidenceFile: result.evidence || tactic?.aggregate_result_source || "evidence_manifest.json",
    generatedTime: dashboardData.provenance.generated_at,
    qaStatus: dashboardData.provenance.qa_status,
    limitation: tactic?.limitation || dashboardData.provenance.primary_limitation,
    syntheticStatus: syntheticWarning,
    currentResult: result.headline,
    currentFraction: result.fraction || "Not applicable",
  };
}

function renderTrustBar() {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  const persistence = persistenceFor(segment);
  byId("trustRelease").textContent = dashboardData.provenance.release_id;
  byId("trustScenario").textContent = selectedMarketLabel();
  byId("trustCohort").textContent = "Synthetic mHSPC eligibility cohort";
  byId("trustDenominator").textContent = `${formatCount(segment.eligible)} eligible`;
  byId("trustWindow").textContent = `${state.initiationWindow} days`;
  byId("trustGap").textContent = `${state.persistenceGap} days`;
  byId("trustStatus").textContent = dashboardData.provenance.analytical_status;
  byId("trustDetail").title =
    `${formatCount(initiation.value)}/${formatCount(segment.eligible)} initiate by day ${state.initiationWindow}; ` +
    `${formatCount(persistence.persistent)}/${formatCount(persistence.evaluable)} meet the ${state.persistenceGap}-day persistence definition.`;
}

function kpiCard(label, value, fraction, population, window, tacticId) {
  return `<article class="kpi-card">
    <span class="status-label">${escapeHtml(label)}</span>
    <div class="value">${escapeHtml(value)}</div>
    <div class="fraction">${escapeHtml(fraction)}</div>
    <div class="metric-contract">
      <span><strong>Population:</strong> ${escapeHtml(population)}</span>
      <span><strong>Window:</strong> ${escapeHtml(window)}</span>
      <span><strong>Release:</strong> ${escapeHtml(dashboardData.provenance.release_short)}</span>
    </div>
    <button class="evidence-button" type="button" data-evidence="${escapeHtml(tacticId)}">Evidence &amp; provenance</button>
  </article>`;
}

function renderExecutiveKpis() {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  const persistence = persistenceFor(segment);
  byId("executiveKpis").innerHTML = [
    kpiCard(
      "Eligible",
      formatCount(segment.eligible),
      `${formatCount(segment.eligible)} / ${formatCount(segment.total)} (${formatPercent(segment.eligible_rate)})`,
      selectedMarketLabel(),
      "At eligibility index",
      "cohort_definition",
    ),
    kpiCard(
      `Initiated by day ${state.initiationWindow}`,
      formatCount(initiation.value),
      `${formatCount(initiation.value)} / ${formatCount(segment.eligible)} (${formatPercent(initiation.rate)})`,
      "Eligible synthetic records",
      `${state.initiationWindow} days after eligibility`,
      "initiation_landmarks",
    ),
    kpiCard(
      `Not initiated by day ${state.initiationWindow}`,
      formatCount(initiation.gap),
      `${formatCount(initiation.gap)} / ${formatCount(initiation.evaluable)} (${formatPercent(initiation.gap_rate_evaluable)})`,
      "Eligible and evaluable at the landmark",
      `${state.initiationWindow} days after eligibility`,
      "segmented_treatment_gap",
    ),
    kpiCard(
      "Persistent at month 12",
      formatCount(persistence.persistent),
      `${formatCount(persistence.persistent)} / ${formatCount(persistence.evaluable)} (${formatPercent(persistence.rate)})`,
      "Evaluable eligible day-90 initiators",
      `365 days; ${state.persistenceGap}-day permissible gap`,
      "persistence_sensitivity",
    ),
  ].join("");
}

function renderLedger() {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  const persistence = persistenceFor(segment);
  const notEligible = segment.total - segment.eligible;
  const persistenceOther = persistence.evaluable - persistence.persistent;
  byId("cohortLedger").innerHTML = `
    <div class="ledger-row"><span class="ledger-count">${formatCount(segment.total)}</span><span class="ledger-label">Total selected synthetic cohort</span><span class="ledger-reason">Configured scenario records</span><span class="ledger-denominator">Starting population</span></div>
    <div class="ledger-row excluded"><span class="ledger-count">${formatCount(notEligible)}</span><span class="ledger-label">Excluded from eligibility cohort</span><span class="ledger-reason">Does not meet the versioned analytical rule</span><span class="ledger-denominator">Shown separately</span></div>
    <div class="ledger-row"><span class="ledger-count">${formatCount(segment.eligible)}</span><span class="ledger-label">Eligible</span><span class="ledger-reason">Active initiation denominator</span><span class="ledger-denominator">N = ${formatCount(segment.eligible)}</span></div>
    <div class="ledger-row"><span class="ledger-count">${formatCount(initiation.value)}</span><span class="ledger-label">Initiated by day ${state.initiationWindow}</span><span class="ledger-reason">Observed treatment start on or before landmark</span><span class="ledger-denominator">n/N = ${formatCount(initiation.value)}/${formatCount(segment.eligible)}</span></div>
    <div class="ledger-row excluded"><span class="ledger-count">${formatCount(initiation.gap)}</span><span class="ledger-label">Evaluable, not initiated by day ${state.initiationWindow}</span><span class="ledger-reason">Separate outcome branch; not a clinical judgment</span><span class="ledger-denominator">n/N = ${formatCount(initiation.gap)}/${formatCount(initiation.evaluable)}</span></div>
    <div class="ledger-row censored"><span class="ledger-count">${formatCount(initiation.censored)}</span><span class="ledger-label">Censored before initiation landmark</span><span class="ledger-reason">Insufficient follow-up; never classified as non-initiation</span><span class="ledger-denominator">Excluded from evaluable branch</span></div>
    <div class="ledger-row"><span class="ledger-count">${formatCount(segment.initiated90)}</span><span class="ledger-label">Day-90 initiators entering persistence assessment</span><span class="ledger-reason">Persistence target population</span><span class="ledger-denominator">N = ${formatCount(segment.initiated90)}</span></div>
    <div class="ledger-row"><span class="ledger-count">${formatCount(persistence.evaluable)}</span><span class="ledger-label">Evaluable at month 12</span><span class="ledger-reason">Official persistence denominator</span><span class="ledger-denominator">N = ${formatCount(persistence.evaluable)}</span></div>
    <div class="ledger-row"><span class="ledger-count">${formatCount(persistence.persistent)}</span><span class="ledger-label">Meets ${state.persistenceGap}-day persistence definition</span><span class="ledger-reason">Operational dispensing-continuity definition</span><span class="ledger-denominator">n/N = ${formatCount(persistence.persistent)}/${formatCount(persistence.evaluable)}</span></div>
    <div class="ledger-row excluded"><span class="ledger-count">${formatCount(persistenceOther)}</span><span class="ledger-label">Other evaluable persistence states</span><span class="ledger-reason">Discontinued or switched under the selected rule</span><span class="ledger-denominator">Part of official denominator</span></div>
    <div class="ledger-row censored"><span class="ledger-count">${formatCount(persistence.censored)}</span><span class="ledger-label">Censored before month 12</span><span class="ledger-reason">Shown separately from the persistence denominator</span><span class="ledger-denominator">Not in N = ${formatCount(persistence.evaluable)}</span></div>`;
  byId("ledgerSummary").textContent =
    `${formatCount(persistence.persistent)} of ${formatCount(persistence.evaluable)} evaluable records meet the ` +
    `${state.persistenceGap}-day operational persistence definition. The ${formatCount(persistence.censored)} censored records are not in that denominator.`;
}

function renderInitiationChart() {
  const segment = selectedSegment();
  const maximum = Math.max(...segment.initiation_windows.map((item) => item.rate || 0), 1);
  byId("initiationPlot").innerHTML = segment.initiation_windows
    .map(
      (item) => `<div class="dot-row">
        <span><strong>Day ${item.days}</strong><br><span class="subtle">Cumulative initiation</span></span>
        <span class="plot-track" aria-hidden="true"><span class="plot-fill" style="width:${(item.rate / maximum) * 100}%"></span></span>
        <span class="plot-value">${formatCount(item.value)} / ${formatCount(segment.eligible)} · ${formatPercent(item.rate)}</span>
      </div>`,
    )
    .join("");
  byId("initiationSummary").textContent =
    `${formatCount(initiationFor(segment).value)} of ${formatCount(segment.eligible)} eligible synthetic records initiate by day ` +
    `${state.initiationWindow}. ${formatCount(initiationFor(segment).censored)} records are censored before this landmark.`;
}

function renderPersistenceChart() {
  const segment = selectedSegment();
  const maximum = Math.max(...segment.persistence_sensitivity.map((item) => item.rate || 0), 1);
  byId("persistencePlot").innerHTML = segment.persistence_sensitivity
    .map(
      (item) => `<div class="dot-row">
        <span><strong>${item.gap_days}-day gap</strong><br><span class="subtle">Definition sensitivity</span></span>
        <span class="plot-track" aria-hidden="true"><span class="plot-dot" style="left:${(item.rate / maximum) * 100}%"></span></span>
        <span class="plot-value">${formatCount(item.persistent)} / ${formatCount(item.evaluable)} · ${formatPercent(item.rate)}</span>
      </div>`,
    )
    .join("");
  const selected = persistenceFor(segment);
  byId("persistenceSummary").textContent =
    `Under the selected ${state.persistenceGap}-day permissible-gap rule, ${formatCount(selected.persistent)} of ` +
    `${formatCount(selected.evaluable)} evaluable day-90 initiators meet the operational persistence definition; ` +
    `${formatCount(selected.censored)} are censored separately.`;
}

function renderMarketComparison() {
  const rows = dashboardData.markets.map((market) => ({ market, ...dashboardData.segments[market] }));
  const maximum = Math.max(...rows.map((row) => initiationFor(row).rate || 0), 1);
  byId("marketPlot").innerHTML = rows
    .map((row) => {
      const item = initiationFor(row);
      return `<div class="dot-row">
        <span><strong>${escapeHtml(row.market)}</strong><br><span class="subtle">Configured scenario</span></span>
        <span class="plot-track" aria-hidden="true"><span class="plot-dot" style="left:${(item.rate / maximum) * 100}%"></span></span>
        <span class="plot-value">${formatCount(item.value)} / ${formatCount(row.eligible)} · ${formatPercent(item.rate)}</span>
      </div>`;
    })
    .join("");
  byId("marketTableBody").innerHTML = rows
    .map((row) => {
      const initiation = initiationFor(row);
      const persistence = persistenceFor(row);
      return `<tr data-market="${escapeHtml(row.market)}" tabindex="0" aria-label="Focus all views on configured scenario ${escapeHtml(row.market)}" class="${state.market === row.market ? "active" : ""}">
        <th scope="row">${escapeHtml(row.market)}</th>
        <td>${formatCount(row.total)}</td>
        <td>${formatCount(row.eligible)}</td>
        <td>${formatCount(initiation.value)} / ${formatCount(row.eligible)}</td>
        <td>${formatPercent(initiation.rate)}</td>
        <td>${formatCount(initiation.gap)} / ${formatCount(initiation.evaluable)}</td>
        <td>${formatCount(persistence.persistent)} / ${formatCount(persistence.evaluable)}</td>
      </tr>`;
    })
    .join("");
  document.querySelectorAll("#marketTableBody tr").forEach((row) => {
    row.addEventListener("click", () => changeMarket(row.dataset.market));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        changeMarket(row.dataset.market);
      }
    });
  });
  const rates = rows.map((row) => initiationFor(row).rate).filter((value) => value !== null);
  byId("scenarioRange").textContent = rates.length
    ? `${formatPercent(Math.min(...rates))} to ${formatPercent(Math.max(...rates))} across configured scenarios at day ${state.initiationWindow}. This is a scenario assumption range, not a confidence interval or market ranking.`
    : "Scenario range is not evaluable.";
}

function renderMissingness() {
  const fields = dashboardData.segments.ALL.missingness.map((item) => item.field);
  const header = `<span class="heat-cell heat-label">Field</span>${dashboardData.markets
    .map((market) => `<span class="heat-cell"><strong>${escapeHtml(market)}</strong></span>`)
    .join("")}`;
  const cells = fields
    .map((field) => {
      const row = dashboardData.markets
        .map((market) => dashboardData.segments[market].missingness.find((item) => item.field === field))
        .map((item) => {
          const rate = item?.rate || 0;
          const band = rate >= 20 ? "high" : rate >= 8 ? "medium" : "low";
          return `<span class="heat-cell" data-band="${band}" aria-label="${escapeHtml(field)}, ${formatPercent(rate)} missing">${formatPercent(rate)}<br><span class="subtle">n=${formatCount(item?.missing)}</span></span>`;
        })
        .join("");
      return `<span class="heat-cell heat-label">${escapeHtml(field)}</span>${row}`;
    })
    .join("");
  byId("missingnessHeatmap").innerHTML = header + cells;
  byId("missingnessSummary").textContent =
    "Cell labels provide exact rates and counts. Background bands support scanning but do not encode a quality judgment or real-data mechanism.";
}

function renderPathway() {
  const segment = selectedSegment();
  const referral = segment.referrals;
  byId("referralSummary").innerHTML = `
    <div class="inspector-item"><span>Referral rows</span><strong>${formatCount(referral.total)}</strong></div>
    <div class="inspector-item"><span>Completed</span><strong>${formatCount(referral.completed)} / ${formatCount(referral.total)} (${formatPercent(referral.completion_rate)})</strong></div>
    <div class="inspector-item"><span>Median observed delay</span><strong>${referral.median_delay === null ? "Not evaluable" : `${referral.median_delay} days`}</strong></div>`;
  byId("transitionSummary").innerHTML = segment.transitions
    .map(
      (item) => `<div class="inspector-item"><span>${escapeHtml(item.label)}</span><strong>${formatCount(item.value)} / ${formatCount(item.denominator)}</strong><small>${escapeHtml(item.definition)}</small></div>`,
    )
    .join("");
}

function renderDenominatorInspector() {
  const context = activeDenominatorContext();
  const selectedAnalysis = byId("denominatorAnalysis")?.value || "initiation";
  let detail = context;
  if (selectedAnalysis === "persistence") {
    const segment = selectedSegment();
    const persistence = persistenceFor(segment);
    detail = {
      label: `${formatCount(persistence.evaluable)} evaluable day-90 initiators`,
      count: persistence.evaluable,
      population: `${selectedMarketLabel()} — eligible records initiated by day 90 with a classifiable month-12 status`,
      included: "PERSISTENT, DISCONTINUED, or SWITCHED at month 12 under the selected gap rule.",
      excluded: `${formatCount(persistence.censored)} month-12 censored records and non-applicable records are outside this denominator.`,
      timeZero: "treatment_start_date",
      evaluability: `Observed through day 365 or an earlier qualifying classified event; ${formatCount(persistence.evaluable)} evaluable.`,
      censoring: "Loss to follow-up or administrative end before classification remains separate.",
    };
  }
  if (selectedAnalysis === "referral") {
    const referral = selectedSegment().referrals;
    detail = {
      label: `${formatCount(referral.total)} generated referral rows`,
      count: referral.total,
      population: `${selectedMarketLabel()} — referrals with valid referral dates`,
      included: "Referral rows entering the completion and delay summary.",
      excluded: "Records without an observed referral do not enter this analysis.",
      timeZero: "referral_date",
      evaluability: "Completion date and status determine completed-referral timing.",
      censoring: "Observation boundary limits follow-up; absence of completion is not interpreted as care quality.",
    };
  }
  byId("inspectorTitle").textContent = detail.label;
  byId("inspectorGrid").innerHTML = [
    ["Population", detail.population],
    ["Included", detail.included],
    ["Excluded", detail.excluded],
    ["Time zero", detail.timeZero],
    ["Evaluability", detail.evaluability],
    ["Censoring", detail.censoring],
  ]
    .map(([label, value]) => `<div class="inspector-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

function tacticResult(tacticId) {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  const persistence = persistenceFor(segment);
  const maximumMissing = [...segment.missingness].sort((a, b) => (b.rate || 0) - (a.rate || 0))[0];
  const results = {
    cohort_definition: {
      headline: `${formatCount(segment.eligible)} of ${formatCount(segment.total)} selected synthetic records enter the eligible cohort`,
      fraction: `${formatCount(segment.eligible)} / ${formatCount(segment.total)} (${formatPercent(segment.eligible_rate)})`,
      numerator: segment.eligible,
      denominator: segment.total,
      evidence: "presentation_kpis.csv",
    },
    initiation_landmarks: {
      headline: `${formatCount(initiation.value)} eligible records initiate by day ${state.initiationWindow}`,
      fraction: `${formatCount(initiation.value)} / ${formatCount(segment.eligible)} (${formatPercent(initiation.rate)})`,
      numerator: initiation.value,
      denominator: segment.eligible,
      evidence: "healthcare_initiation_funnel.csv",
    },
    censoring_evaluability: {
      headline: `${formatCount(initiation.censored)} eligible records are censored before day ${state.initiationWindow}`,
      fraction: `${formatCount(initiation.censored)} / ${formatCount(segment.eligible)}`,
      numerator: initiation.censored,
      denominator: segment.eligible,
      evidence: "healthcare_initiation_funnel.csv",
    },
    persistence_sensitivity: {
      headline: `${formatCount(persistence.persistent)} records meet the ${state.persistenceGap}-day month-12 persistence definition`,
      fraction: `${formatCount(persistence.persistent)} / ${formatCount(persistence.evaluable)} (${formatPercent(persistence.rate)})`,
      numerator: persistence.persistent,
      denominator: persistence.evaluable,
      evidence: "healthcare_persistence_summary.csv",
    },
    time_to_initiation: {
      headline: segment.median_days_to_initiation === null
        ? "Median observed time to initiation is not evaluable"
        : `Median observed time among day-90 initiators is ${segment.median_days_to_initiation} days`,
      fraction: `${formatCount(initiation.value)} observed initiations by day ${state.initiationWindow}`,
      numerator: initiation.value,
      denominator: segment.eligible,
      evidence: "cohort_summary.md",
    },
    referral_pathway: {
      headline: `${formatCount(segment.referrals.completed)} of ${formatCount(segment.referrals.total)} generated referrals are completed`,
      fraction: `${formatCount(segment.referrals.completed)} / ${formatCount(segment.referrals.total)} (${formatPercent(segment.referrals.completion_rate)})`,
      numerator: segment.referrals.completed,
      denominator: segment.referrals.total,
      evidence: "healthcare_referral_summary.csv",
    },
    segmented_treatment_gap: {
      headline: `${formatCount(initiation.gap)} evaluable eligible records are not initiated by day ${state.initiationWindow}`,
      fraction: `${formatCount(initiation.gap)} / ${formatCount(initiation.evaluable)} (${formatPercent(initiation.gap_rate_evaluable)})`,
      numerator: initiation.gap,
      denominator: initiation.evaluable,
      evidence: "cohort_dashboard.html",
    },
    missingness_profile: {
      headline: maximumMissing
        ? `${maximumMissing.field}: ${formatCount(maximumMissing.missing)} of ${formatCount(segment.total)} records missing`
        : "No configured missingness fields are available",
      fraction: maximumMissing ? `${formatPercent(maximumMissing.rate)} in selected synthetic scenario` : "Not evaluable",
      numerator: maximumMissing?.missing ?? null,
      denominator: segment.total,
      evidence: "healthcare_missingness_by_market.csv",
    },
    model_disposition: dashboardData.models.available
      ? {
          headline: `${dashboardData.models.research_count} RESEARCH ONLY and ${dashboardData.models.rejected_count} REJECTED; zero deployable models`,
          fraction: `${dashboardData.models.items.length} release-matched model targets reviewed`,
          numerator: 0,
          denominator: dashboardData.models.items.length,
          evidence: "model_disposition.csv",
        }
      : {
          headline: "Release-matched predictive evidence is unavailable for this selected release",
          fraction: "No model metric or disposition is inferred",
          numerator: null,
          denominator: null,
          evidence: "evidence_manifest.json",
        },
    evidence_governance: {
      headline: `One certified release powers every displayed aggregate; QA status ${dashboardData.provenance.qa_status}`,
      fraction: `Release ${dashboardData.provenance.release_short}`,
      numerator: dashboardData.provenance.verified_artifacts,
      denominator: dashboardData.provenance.verified_artifacts,
      evidence: "evidence_manifest.json",
    },
  };
  const tactic = dashboardData.tactics.find((item) => item.tactic_id === tacticId);
  const result = results[tacticId] || {
    headline: "This analytical method is not valid under the selected configuration.",
    fraction: "Not evaluable",
    numerator: null,
    denominator: null,
    evidence: "evidence_manifest.json",
  };
  return {
    ...result,
    numeratorDefinition: tactic?.numerator_definition,
    denominatorDefinition: tactic?.denominator_definition,
  };
}

function renderTactics() {
  const term = byId("tacticSearch").value.trim().toLowerCase();
  const tactics = dashboardData.tactics.filter((tactic) => {
    const categoryMatch = state.tacticFilter === "All" || tactic.tags.includes(state.tacticFilter);
    const searchText = `${tactic.title} ${tactic.question} ${tactic.method} ${tactic.tags.join(" ")}`.toLowerCase();
    return categoryMatch && (!term || searchText.includes(term));
  });
  byId("tacticGrid").innerHTML = tactics.length
    ? tactics
        .map((tactic) => {
          const result = tacticResult(tactic.tactic_id);
          return `<article class="tactic-card">
            <span class="tactic-category">${escapeHtml(tactic.category)} · ${escapeHtml(tactic.tactic_id)}</span>
            <h3>${escapeHtml(tactic.title)}</h3>
            <p>${escapeHtml(tactic.question)}</p>
            <div class="tactic-result">${escapeHtml(result.headline)}<br><span class="subtle">${escapeHtml(result.fraction)}</span></div>
            <div class="tactic-tags">${tactic.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
            <button class="button secondary" type="button" data-tactic="${escapeHtml(tactic.tactic_id)}">Open tactic — Levels 1–3</button>
          </article>`;
        })
        .join("")
    : '<div class="empty-state">No synthetic records meet the current analytical definition.</div>';
  document.querySelectorAll("[data-tactic]").forEach((button) => {
    button.addEventListener("click", () => openTactic(button.dataset.tactic));
  });
}

function openTactic(tacticId) {
  const tactic = dashboardData.tactics.find((item) => item.tactic_id === tacticId);
  if (!tactic) return;
  const result = tacticResult(tacticId);
  lastFocus = document.activeElement;
  byId("tacticTitle").textContent = tactic.title;
  byId("tacticCategory").textContent = `${tactic.category} · ${tactic.tactic_id} · v${tactic.version}`;
  byId("tacticLevel1").innerHTML = `
    <p><strong>Question:</strong> ${escapeHtml(tactic.question)}</p>
    <p><strong>Why this exists:</strong> ${escapeHtml(tactic.why)}</p>
    <div class="tactic-result">${escapeHtml(result.headline)}<br>${escapeHtml(result.fraction)}</div>
    <p><strong>Interpretation:</strong> ${escapeHtml(tactic.interpretation)}</p>
    <p><strong>Limitation:</strong> ${escapeHtml(tactic.limitation)}</p>`;
  byId("tacticLevel2").innerHTML = `
    <div class="method-contract">
      ${[
        ["Target population", tactic.target_population],
        ["Numerator", tactic.numerator_definition],
        ["Denominator", tactic.denominator_definition],
        ["Index / time zero", tactic.index_date],
        ["Horizon", tactic.time_horizon],
        ["Method", tactic.method],
        ["Parameters", JSON.stringify(tactic.parameters)],
        ["Defaults", JSON.stringify(tactic.default_parameters)],
      ]
        .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
        .join("")}
    </div>`;
  byId("tacticLevel3").innerHTML = `
    <div class="method-contract">
      ${[
        ["Analysis ID", tactic.analysis_id],
        ["Aggregate result source", tactic.aggregate_result_source],
        ["Methodology source", tactic.methodology_source],
        ["Limitation source", tactic.limitation_source],
        ["Evidence files", tactic.evidence_files.join(", ")],
        ["Release compatibility", tactic.release_compatibility],
        ["Reviewer status", tactic.reviewer_status],
        ["Required real-data fields", tactic.required_real_data_fields.join(", ")],
        ["Prohibited interpretations", tactic.prohibited_interpretations.join("; ")],
        ["Certified release", dashboardData.provenance.release_id],
      ]
        .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
        .join("")}
    </div>`;
  byId("tacticEvidence").dataset.evidence = tacticId;
  byId("tacticEvidence").onclick = () => {
    closeLayer("tacticModalBackdrop", "tacticModal");
    openEvidence(tacticId);
  };
  byId("tacticModalBackdrop").hidden = false;
  byId("tacticModal").hidden = false;
  byId("closeTactic").focus();
}

function renderModels() {
  if (!dashboardData.models.available) {
    byId("modelExperience").innerHTML = `
      <div class="empty-state">
        <strong>Release-matched model evidence is unavailable.</strong><br>
        This historical certified release contains no verified Prompt-3 predictive package. No AUC, calibration, sample size, event rate, or model disposition is inferred from another release.
        <div style="margin-top:10px"><span class="status-chip unavailable">METHOD UNAVAILABLE FOR SELECTED RELEASE</span></div>
      </div>`;
    return;
  }
  byId("modelExperience").innerHTML = dashboardData.models.items
    .map((model) => {
      const statusClass = model.disposition === "REJECTED" ? "rejected" : "research";
      return `<article class="model-card">
        <span class="status-chip ${statusClass}">${escapeHtml(model.disposition)}</span>
        <h3>${escapeHtml(model.target_name || model.model_id)}</h3>
        <dl>
          <dt>Population</dt><dd>${escapeHtml(model.population || "See model card")}</dd>
          <dt>Prediction time</dt><dd>${escapeHtml(model.prediction_time || "See target contract")}</dd>
          <dt>Horizon</dt><dd>${model.prediction_horizon_days == null ? "See target contract" : `${formatCount(model.prediction_horizon_days)} days`}</dd>
          <dt>Validation n</dt><dd>${formatCount(model.validation_n)}</dd>
          <dt>Event rate</dt><dd>${formatPercent(model.event_prevalence === null ? null : model.event_prevalence * 100)}</dd>
          <dt>ROC AUC</dt><dd>${model.roc_auc === null ? "Not evaluable" : Number(model.roc_auc).toFixed(3)}</dd>
          <dt>PR AUC</dt><dd>${model.pr_auc === null ? "Not evaluable" : Number(model.pr_auc).toFixed(3)}</dd>
          <dt>Calibration</dt><dd>${model.calibration_intercept === null ? "Not evaluable" : `intercept ${Number(model.calibration_intercept).toFixed(3)}; slope ${Number(model.calibration_slope).toFixed(3)}`}</dd>
          <dt>Validation</dt><dd>Release-matched final temporal holdout plus governed robustness evidence.</dd>
          <dt>Limitation</dt><dd>${escapeHtml(model.reason || "Synthetic internal validation is non-operational.")}</dd>
          <dt>Prohibited use</dt><dd>Patient ranking, treatment decision, outreach, provider/market assessment, or deployment.</dd>
        </dl>
        <button class="evidence-button" type="button" data-evidence="model_disposition">Evidence &amp; provenance</button>
      </article>`;
    })
    .join("");
}

function renderMethodology() {
  byId("methodologyContracts").innerHTML = dashboardData.tactics
    .filter((tactic) => tactic.tactic_id !== "model_disposition")
    .map(
      (tactic) => `<details>
        <summary>${escapeHtml(tactic.title)} — ${escapeHtml(tactic.analysis_id)}</summary>
        <div class="method-contract">
          ${[
            ["Research question", tactic.question],
            ["Target population", tactic.target_population],
            ["Numerator", tactic.numerator_definition],
            ["Denominator", tactic.denominator_definition],
            ["Index / time zero", tactic.index_date],
            ["Outcome / method", tactic.method],
            ["Horizon", tactic.time_horizon],
            ["Assumptions", "Synthetic scenario and versioned analytical contract; descriptive results are not causal."],
            ["Sensitivity", JSON.stringify(tactic.parameters)],
            ["Limitation", tactic.limitation],
          ]
            .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
            .join("")}
        </div>
      </details>`,
    )
    .join("");
}

function renderGovernance() {
  const provenance = dashboardData.provenance;
  byId("governanceProvenance").innerHTML = [
    ["Certified release", provenance.release_id],
    ["Source commit", provenance.source_commit],
    ["Analysis commit", provenance.analysis_commit],
    ["Configuration hash", provenance.configuration_hash],
    ["Release selection", provenance.selection_method],
    ["QA status", provenance.qa_status],
    ["Lineage", "Release → aggregate presentation → manifest-listed frontend assets"],
    ["Claim/evidence register", "docs/CLAIM_EVIDENCE_REGISTER.md"],
    ["Model disposition", dashboardData.models.available ? "See release-matched model cards" : "Unavailable for selected release"],
    ["Reviewer status", "Independent clinical/RWE/statistical/accessibility review pending"],
    ["Stage-4 readiness", provenance.analytical_status],
  ]
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

function openEvidence(tacticId) {
  const context = evidenceContext(tacticId);
  lastFocus = document.activeElement;
  byId("evidenceTitle").textContent = context.title;
  byId("evidenceBody").innerHTML = `<dl class="provenance-list">
    ${[
      ["Current result", context.currentResult],
      ["Current n/N", context.currentFraction],
      ["Release ID", context.releaseId],
      ["Source commit", context.sourceCommit],
      ["Configuration hash", context.configHash],
      ["Input release", context.inputRelease],
      ["Analysis ID", context.analysisId],
      ["Tactic ID", context.tacticId],
      ["Numerator definition", context.numerator],
      ["Denominator definition", context.denominator],
      ["Evidence file", context.evidenceFile],
      ["Generated time", context.generatedTime],
      ["QA status", context.qaStatus],
      ["Limitation", context.limitation],
      ["Synthetic status", context.syntheticStatus],
    ]
      .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
      .join("")}
  </dl>`;
  byId("evidenceFileLink").href = context.evidenceFile;
  byId("evidenceBackdrop").hidden = false;
  byId("evidenceDrawer").hidden = false;
  byId("closeEvidence").focus();
}

function closeLayer(backdropId, layerId) {
  byId(backdropId).hidden = true;
  byId(layerId).hidden = true;
  if (lastFocus?.focus) lastFocus.focus();
}

function attachEvidenceButtons() {
  document.querySelectorAll("[data-evidence]").forEach((button) => {
    if (button.dataset.evidenceBound === "true") return;
    button.dataset.evidenceBound = "true";
    button.addEventListener("click", () => openEvidence(button.dataset.evidence));
  });
}

function showDenominatorChange(previous, current, reason) {
  const notice = byId("denominatorChange");
  notice.innerHTML = `<strong>DENOMINATOR CHANGED</strong>
    <span><b>Previous:</b> ${escapeHtml(previous)}</span><br>
    <span><b>Current:</b> ${escapeHtml(current)}</span><br>
    <span><b>Reason:</b> ${escapeHtml(reason)}</span>`;
  notice.hidden = false;
  announce(`Denominator changed. Previous: ${previous}. Current: ${current}. Reason: ${reason}`);
}

function changeMarket(market, silent = false) {
  if (!dashboardData.segments[market] || state.presentationMode && !silent) return;
  const previous = activeDenominatorContext().label;
  state.market = market;
  byId("marketSelect").value = market;
  const current = activeDenominatorContext().label;
  if (!silent && previous !== current) {
    showDenominatorChange(previous, current, `The selected configured scenario changed to ${selectedMarketLabel()}.`);
  }
  renderAll();
  updateUrl();
}

function changeWindow(days, silent = false) {
  const numeric = Number(days);
  if (!validWindows.includes(numeric) || state.presentationMode && !silent) return;
  const previous = state.initiationWindow;
  state.initiationWindow = numeric;
  byId("windowSelect").value = String(numeric);
  if (!silent && previous !== numeric) {
    const initiation = initiationFor();
    announce(
      `Analytical window changed from ${previous} to ${numeric} days. The eligible denominator remains ${formatCount(selectedSegment().eligible)}. ` +
        `${formatCount(initiation.censored)} are censored before day ${numeric}.`,
    );
    byId("windowChange").textContent =
      `ANALYTICAL WINDOW CHANGED — ${previous} to ${numeric} days. The eligible denominator remains ${formatCount(selectedSegment().eligible)}; event, gap, and evaluability counts have been recomputed.`;
    byId("windowChange").hidden = false;
  }
  renderAll();
  updateUrl();
}

function changeGap(days, silent = false) {
  const numeric = Number(days);
  if (!validGaps.includes(numeric) || state.presentationMode && !silent) return;
  const previousContext = `${formatCount(persistenceFor().evaluable)} evaluable records under ${state.persistenceGap}-day gap`;
  state.persistenceGap = numeric;
  byId("gapSelect").value = String(numeric);
  const currentContext = `${formatCount(persistenceFor().evaluable)} evaluable records under ${numeric}-day gap`;
  if (!silent && previousContext !== currentContext) {
    showDenominatorChange(
      previousContext,
      currentContext,
      "The operational persistence definition changed; censored and evaluable status can change.",
    );
  }
  renderAll();
  updateUrl();
}

function setView(view, { focus = true } = {}) {
  if (!viewNames.includes(view)) return;
  state.view = view;
  document.querySelectorAll(".view").forEach((panel) => {
    panel.hidden = panel.dataset.view !== view;
  });
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.viewTarget === view;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  if (focus) byId(`${view}Heading`)?.focus();
  updateUrl();
}

function updateUrl() {
  if (state.presentationMode) return;
  const params = new URLSearchParams();
  params.set("view", state.view);
  params.set("market", state.market);
  params.set("window", String(state.initiationWindow));
  params.set("gap", String(state.persistenceGap));
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
}

function resetCertifiedView({ announceReset = true } = {}) {
  state.market = "ALL";
  state.initiationWindow = 90;
  state.persistenceGap = 60;
  state.tacticFilter = "All";
  state.presentationMode = false;
  state.presentationStep = 0;
  document.body.classList.remove("presentation-mode");
  byId("presentationControls").hidden = true;
  byId("marketSelect").disabled = false;
  byId("windowSelect").disabled = false;
  byId("gapSelect").disabled = false;
  byId("marketSelect").value = "ALL";
  byId("windowSelect").value = "90";
  byId("gapSelect").value = "60";
  byId("denominatorChange").hidden = true;
  byId("windowChange").hidden = true;
  document.querySelectorAll(".filter-button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.filter === "All"));
  });
  renderAll();
  setView("executive", { focus: false });
  if (announceReset) announce("Reset to the certified view: all scenarios, 90-day initiation, 60-day persistence gap.");
}

function renderAll() {
  renderTrustBar();
  renderExecutiveKpis();
  renderLedger();
  renderInitiationChart();
  renderPersistenceChart();
  renderMarketComparison();
  renderMissingness();
  renderPathway();
  renderDenominatorInspector();
  renderTactics();
  renderModels();
  renderGovernance();
  attachEvidenceButtons();
  byId("loadingState").hidden = true;
}

function openPilotHypothesis() {
  lastFocus = document.activeElement;
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  byId("pilotObservation").value =
    `${formatCount(initiation.gap)} of ${formatCount(initiation.evaluable)} eligible/evaluable synthetic records are not initiated by day ${state.initiationWindow} in ${selectedMarketLabel()}.`;
  byId("pilotPopulation").value = `${selectedMarketLabel()} — eligible and evaluable synthetic records`;
  byId("pilotQuestion").value = "Could a governed source-data study test which measured workflow steps are associated with initiation timing?";
  byId("pilotOwner").value = "TO BE AGREED";
  byId("pilotApproval").value = "Clinical/RWE, statistics, privacy, data owner, and workflow owner approval required";
  byId("pilotBackdrop").hidden = false;
  byId("pilotModal").hidden = false;
  byId("closePilot").focus();
}

function downloadPilotHypothesis() {
  const fields = [
    "pilotObservation",
    "pilotPopulation",
    "pilotMechanism",
    "pilotWorkflow",
    "pilotQuestion",
    "pilotFields",
    "pilotMethod",
    "pilotValidation",
    "pilotHarm",
    "pilotOwner",
    "pilotApproval",
    "pilotStop",
  ];
  const payload = Object.fromEntries(fields.map((id) => [id, byId(id).value]));
  payload.synthetic_only = true;
  payload.release_id = dashboardData.provenance.release_id;
  payload.prohibited_use = prohibitedUse;
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "synthetic_pilot_hypothesis.json";
  link.click();
  URL.revokeObjectURL(link.href);
  announce("Synthetic pilot hypothesis downloaded. It is not an operational recommendation.");
}

function copyShareableState() {
  updateUrl();
  navigator.clipboard
    .writeText(location.href)
    .then(() => announce("Shareable aggregate filter state copied."))
    .catch(() => announce("Copy unavailable. The current URL still contains the aggregate filter state."));
}

function xmlEscape(value) {
  return escapeHtml(value).replaceAll("&#039;", "&apos;");
}

function downloadPng() {
  const segment = selectedSegment();
  const initiation = initiationFor(segment);
  const persistence = persistenceFor(segment);
  const lines = [
    syntheticWarning,
    `Release: ${dashboardData.provenance.release_id}`,
    `Source: ${dashboardData.provenance.source_commit}`,
    `Filters: ${selectedMarketLabel()} | initiation ${state.initiationWindow}d | persistence gap ${state.persistenceGap}d`,
    `Initiation: ${formatCount(initiation.value)} / ${formatCount(segment.eligible)} (${formatPercent(initiation.rate)})`,
    `Persistence: ${formatCount(persistence.persistent)} / ${formatCount(persistence.evaluable)} (${formatPercent(persistence.rate)})`,
    "Method: governed aggregate landmark summaries with explicit censoring.",
    `Generated: ${dashboardData.provenance.generated_at}`,
    prohibitedUse,
  ];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">
    <rect width="1600" height="900" fill="#f3f6f8"/>
    <rect x="70" y="70" width="1460" height="760" rx="24" fill="#ffffff" stroke="#cad5df"/>
    <rect x="70" y="70" width="1460" height="90" rx="24" fill="#102a43"/>
    <text x="110" y="126" fill="#ffffff" font-family="Arial" font-size="34" font-weight="700">Certified Analytics — Presentation Export</text>
    ${lines
      .map(
        (line, index) => `<text x="110" y="${210 + index * 67}" fill="${index === 0 ? "#7a4600" : "#152536"}" font-family="Arial" font-size="${index === 0 ? 25 : 28}" font-weight="${index === 0 ? 700 : 400}">${xmlEscape(line)}</text>`,
      )
      .join("")}
  </svg>`;
  const image = new Image();
  const canvas = document.createElement("canvas");
  canvas.width = 1600;
  canvas.height = 900;
  image.onload = () => {
    canvas.getContext("2d").drawImage(image, 0, 0);
    canvas.toBlob((blob) => {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `certified-analytics-${state.market}-${state.initiationWindow}d.png`;
      link.click();
      URL.revokeObjectURL(link.href);
      announce("PNG presentation export created with release and denominator context.");
    }, "image/png");
  };
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const presentationSteps = [
  { label: "1 · Executive overview", view: "executive", market: "ALL", window: 90, gap: 60, target: "executiveHeading" },
  { label: "2 · Trust and denominator", view: "executive", market: "ALL", window: 90, gap: 60, target: "denominatorLedger" },
  { label: "3 · 60-day initiation", view: "executive", market: "ALL", window: 60, gap: 60, target: "initiationSection" },
  { label: "4 · Scenario comparison", view: "analyst", market: "ALL", window: 90, gap: 60, target: "scenarioSection" },
  { label: "5 · Tactic method", view: "analyst", market: "ALL", window: 90, gap: 60, target: "tacticSection" },
  { label: "6 · Evidence provenance", view: "governance", market: "ALL", window: 90, gap: 60, target: "governanceHeading" },
  { label: "7 · Honest model status", view: "governance", market: "ALL", window: 90, gap: 60, target: "modelSection" },
  { label: "8 · Governed pilot", view: "executive", market: "ALL", window: 90, gap: 60, target: "pilotSection" },
];

function applyPresentationStep(index) {
  state.presentationStep = Math.max(0, Math.min(index, presentationSteps.length - 1));
  const step = presentationSteps[state.presentationStep];
  state.market = step.market;
  state.initiationWindow = step.window;
  state.persistenceGap = step.gap;
  byId("marketSelect").value = step.market;
  byId("windowSelect").value = String(step.window);
  byId("gapSelect").value = String(step.gap);
  renderAll();
  setView(step.view, { focus: false });
  byId("presentationStep").textContent = `${step.label} (${state.presentationStep + 1}/${presentationSteps.length})`;
  byId("previousStep").disabled = state.presentationStep === 0;
  byId("nextStep").disabled = state.presentationStep === presentationSteps.length - 1;
  byId(step.target)?.scrollIntoView({ block: "start" });
  byId(step.target)?.focus({ preventScroll: true });
  announce(`Presentation step ${state.presentationStep + 1}: ${step.label}`);
}

function startPresentationMode() {
  resetCertifiedView({ announceReset: false });
  state.presentationMode = true;
  document.body.classList.add("presentation-mode");
  byId("presentationControls").hidden = false;
  byId("marketSelect").disabled = true;
  byId("windowSelect").disabled = true;
  byId("gapSelect").disabled = true;
  applyPresentationStep(0);
}

function loadUrlState() {
  const params = new URLSearchParams(location.search);
  const market = params.get("market");
  const windowDays = Number(params.get("window"));
  const gapDays = Number(params.get("gap"));
  const view = params.get("view");
  if (market && dashboardData.segments[market]) state.market = market;
  if (validWindows.includes(windowDays)) state.initiationWindow = windowDays;
  if (validGaps.includes(gapDays)) state.persistenceGap = gapDays;
  if (viewNames.includes(view)) state.view = view;
}

function trapDialogFocus(event, container) {
  if (event.key !== "Tab") return;
  const controls = [...container.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(
    (item) => !item.disabled,
  );
  if (!controls.length) return;
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function initialize() {
  loadUrlState();
  dashboardData.markets.forEach((market) => byId("marketSelect").add(new Option(market, market)));
  byId("marketSelect").value = state.market;
  byId("windowSelect").value = String(state.initiationWindow);
  byId("gapSelect").value = String(state.persistenceGap);
  renderMethodology();
  renderAll();
  setView(state.view, { focus: false });

  byId("marketSelect").addEventListener("change", (event) => changeMarket(event.target.value));
  byId("windowSelect").addEventListener("change", (event) => changeWindow(event.target.value));
  byId("gapSelect").addEventListener("change", (event) => changeGap(event.target.value));
  byId("denominatorAnalysis").addEventListener("change", () => {
    const previous = byId("inspectorTitle").textContent;
    renderDenominatorInspector();
    showDenominatorChange(previous, byId("inspectorTitle").textContent, "The selected analysis requires a different evaluable population.");
  });
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.viewTarget));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const current = viewNames.indexOf(state.view);
      const change = event.key === "ArrowRight" ? 1 : -1;
      const next = (current + change + viewNames.length) % viewNames.length;
      document.querySelector(`[data-view-target="${viewNames[next]}"]`).focus();
      setView(viewNames[next]);
    });
  });
  document.querySelectorAll(".filter-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.tacticFilter = button.dataset.filter;
      document.querySelectorAll(".filter-button").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      renderTactics();
    });
  });
  byId("tacticSearch").addEventListener("input", renderTactics);
  document.querySelectorAll("[data-reset]").forEach((button) => button.addEventListener("click", () => resetCertifiedView()));
  byId("presentationMode").addEventListener("click", startPresentationMode);
  byId("previousStep").addEventListener("click", () => applyPresentationStep(state.presentationStep - 1));
  byId("nextStep").addEventListener("click", () => applyPresentationStep(state.presentationStep + 1));
  byId("exitPresentation").addEventListener("click", () => resetCertifiedView());
  byId("createPilot").addEventListener("click", openPilotHypothesis);
  byId("downloadPilot").addEventListener("click", downloadPilotHypothesis);
  byId("copyState").addEventListener("click", copyShareableState);
  byId("downloadPng").addEventListener("click", downloadPng);
  byId("printReport").addEventListener("click", () => window.print());
  byId("closeEvidence").addEventListener("click", () => closeLayer("evidenceBackdrop", "evidenceDrawer"));
  byId("evidenceBackdrop").addEventListener("click", () => closeLayer("evidenceBackdrop", "evidenceDrawer"));
  byId("closeTactic").addEventListener("click", () => closeLayer("tacticModalBackdrop", "tacticModal"));
  byId("tacticModalBackdrop").addEventListener("click", () => closeLayer("tacticModalBackdrop", "tacticModal"));
  byId("closePilot").addEventListener("click", () => closeLayer("pilotBackdrop", "pilotModal"));
  byId("pilotBackdrop").addEventListener("click", () => closeLayer("pilotBackdrop", "pilotModal"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!byId("evidenceDrawer").hidden) closeLayer("evidenceBackdrop", "evidenceDrawer");
      if (!byId("tacticModal").hidden) closeLayer("tacticModalBackdrop", "tacticModal");
      if (!byId("pilotModal").hidden) closeLayer("pilotBackdrop", "pilotModal");
    }
    if (!byId("evidenceDrawer").hidden) trapDialogFocus(event, byId("evidenceDrawer"));
    if (!byId("tacticModal").hidden) trapDialogFocus(event, byId("tacticModal"));
    if (!byId("pilotModal").hidden) trapDialogFocus(event, byId("pilotModal"));
  });
}

try {
  initialize();
} catch (error) {
  byId("loadingState").hidden = true;
  byId("fatalState").hidden = false;
  byId("fatalState").textContent =
    "The selected certified release could not be resolved. No fallback dataset has been loaded.";
  console.error("Certified analytics initialization failed", error);
}
