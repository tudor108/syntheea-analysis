(function () {
  "use strict";

  var state = {
    sessionId: null,
    csrfToken: null,
    specialistBlocked: false,
    activeTacticId: null,
    context: null,
    specialistContext: null,
    tactics: [],
    runs: [],
    activePreview: null,
    activeRun: null,
    busy: false,
    presentationMode: false,
    demoStep: 0,
    demoMetric: null,
    focusBeforeDrawer: null
  };

  var ERROR_COPY = {
    no_evidence: "No certified aggregate evidence supports this question.",
    unsupported_question: "This request is outside the approved analytical scope.",
    invalid_request: "One or more parameters are incompatible with the registered method.",
    no_denominator: "No evaluable denominator is available under the selected definition.",
    budget_exhausted: "The estimated maximum cost exceeds the remaining session budget.",
    provider_unavailable: "AI evidence is temporarily unavailable. Certified Analytics remains available.",
    execution_pending: "Execution is waiting for explicit RUN THIS ANALYSIS confirmation.",
    execution_failed: "The isolated analysis did not complete. No certified output changed.",
    qa_failed: "Post-run QA failed. Interpretation and export are suppressed.",
    session_expired: "This session expired. Start a new workspace to continue.",
    not_found: "The requested interactive run could not be found.",
    run_expired: "This interactive run is no longer available for action.",
    rate_limited: "The request-rate limit was reached. Wait briefly before trying again."
  };

  var byId = function (id) { return document.getElementById(id); };

  function create(tag, className, textValue) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (textValue !== undefined && textValue !== null) { node.textContent = textValue; }
    return node;
  }

  function announce(message) { byId("announcer").textContent = message; }

  function setStatus(label, kind) {
    byId("service-status").textContent = label;
    byId("service-status").className = "status-chip " + kind;
  }

  async function jsonRequest(url, options) {
    var requestOptions = options || {};
    requestOptions.headers = Object.assign({}, requestOptions.headers || {});
    if (state.csrfToken && requestOptions.method && requestOptions.method !== "GET") {
      requestOptions.headers["X-CSRF-Token"] = state.csrfToken;
    }
    var response = await fetch(url, requestOptions);
    var payload = await response.json();
    if (!response.ok) {
      var error = new Error(ERROR_COPY[payload.status] || payload.message || payload.status || "Request failed safely.");
      error.status = payload.status || "request_failed";
      throw error;
    }
    return payload;
  }

  function post(url, payload) {
    return jsonRequest(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
  }

  function releaseLabel(value) {
    if (!value) { return "Unavailable"; }
    return value.length <= 30 ? value : value.slice(0, 16) + "…" + value.slice(-10);
  }

  async function initialize() {
    try {
      var values = await Promise.all([
        jsonRequest("/api/context"),
        jsonRequest("/api/tactics"),
        post("/api/session", {})
      ]);
      state.context = values[0];
      state.sessionId = values[2].session_id;
      state.csrfToken = values[2].csrf_token;
      renderContext(values[0], values[2]);
      renderTactics(values[1].tactics || []);
      if (values[0].specialist_analysis_enabled) {
        state.specialistContext = await jsonRequest("/api/specialist/context");
        renderSpecialistContext(state.specialistContext);
        await loadCareSettings();
        await loadRuns();
      } else {
        byId("tab-specialist").disabled = true;
        byId("tab-history").disabled = true;
        byId("preview-status").textContent = "Specialist configuration is unavailable.";
      }
      setStatus(values[0].openai_configured ? "Ready" : "Evidence only", "ready");
    } catch (error) {
      setStatus("Unavailable", "error");
      addError(ERROR_COPY.provider_unavailable);
    }
  }

  function renderContext(context, session) {
    byId("release-context").textContent = "Certified parent release: " + context.release_id;
    byId("release-short").textContent = releaseLabel(context.release_id);
    byId("release-short").title = context.release_id;
    byId("model-value").textContent = context.model + " · bounded";
    byId("evidence-count").textContent = String(context.catalogued_artifacts) + " approved artifacts";
    byId("analytics-link").href = context.analytics_url;
    [byId("market-select"), byId("run-market")].forEach(function (select) {
      (context.markets || []).forEach(function (value) {
        if (value === "ALL" || select.querySelector('option[value="' + value + '"]')) { return; }
        var option = create("option", "", value + " · synthetic scenario");
        option.value = value;
        select.appendChild(option);
      });
    });
    renderSession(session);
  }

  function renderSession(session) {
    var used = Number(session.cost_used_usd || 0);
    var reserved = Number(session.reserved_usd || 0);
    var remaining = Number(session.remaining_budget_usd || 0);
    var hardStop = Number(session.hard_stop_usd || 2);
    state.specialistBlocked = Boolean(session.specialist_soft_stop_active);
    byId("session-cost").textContent = "$" + used.toFixed(4) + " + $" + reserved.toFixed(4) + " reserved / $" + hardStop.toFixed(2);
    byId("session-cost").title = "$" + remaining.toFixed(6) + " available";
    byId("session-cost").classList.toggle("budget-warning", Boolean(session.warning_active));
    byId("preview-analysis").disabled = state.specialistBlocked;
    if (state.specialistBlocked) {
      byId("preview-status").textContent = "Specialist soft stop reached; evidence questions remain available until the hard stop.";
    }
    if (state.sessionId) { loadCostDashboard(); }
  }

  async function loadCostDashboard() {
    try {
      var payload = await jsonRequest("/api/cost?session_id=" + encodeURIComponent(state.sessionId));
      var content = byId("cost-content");
      content.replaceChildren();
      var session = payload.session;
      var summary = create("div", "cost-summary-grid");
      [["Metered/charged", "$" + Number(session.cost_used_usd).toFixed(6)], ["Reserved", "$" + Number(session.reserved_usd).toFixed(6)], ["Available", "$" + Number(session.remaining_budget_usd).toFixed(6)], ["Hard stop", "$" + Number(session.hard_stop_usd).toFixed(2)]].forEach(function (item) {
        var card = create("div", "metric-card"); card.appendChild(create("span", "", item[0])); card.appendChild(create("strong", "", item[1])); summary.appendChild(card);
      });
      content.appendChild(summary);
      content.appendChild(create("p", "field-help", "Pricing effective " + payload.pricing_effective_date + ". Warning $" + Number(session.warning_usd).toFixed(2) + "; specialist soft stop $" + Number(session.specialist_soft_stop_usd).toFixed(2) + "."));
      var models = create("div", "cost-models");
      Object.keys(payload.by_model || {}).forEach(function (model) {
        var usage = payload.by_model[model];
        var details = create("details");
        details.appendChild(create("summary", "", model + " · " + usage.requests + " requests · $" + Number(usage.cost_usd).toFixed(6)));
        details.appendChild(create("pre", "source-excerpt", JSON.stringify(usage, null, 2)));
        models.appendChild(details);
      });
      if (!models.childNodes.length) { models.appendChild(create("p", "empty-state", "No provider-backed request has been charged in this session.")); }
      content.appendChild(models);
      var events = payload.recent_requests || [];
      if (events.length) {
        content.appendChild(create("h3", "", "Recent requests"));
        content.appendChild(create("pre", "source-excerpt", JSON.stringify(events, null, 2)));
      }
    } catch (error) {
      byId("cost-content").textContent = "Cost telemetry is unavailable for this session.";
    }
  }

  function renderSpecialistContext(context) {
    var lens = byId("expert-lens");
    lens.replaceChildren();
    (context.lenses || []).forEach(function (item) {
      var option = create("option", "", item.title);
      option.value = item.lens_id;
      option.dataset.purpose = item.purpose;
      lens.appendChild(option);
    });
    updateLensPurpose();
  }

  async function loadCareSettings() {
    try {
      var contract = await jsonRequest("/api/specialist/tactics/segmented_treatment_gap");
      var settings = contract.allowed_parameters.executable_parameters.care_setting || [];
      settings.forEach(function (value) {
        var option = create("option", "", value.replaceAll("_", " "));
        option.value = value;
        byId("care-setting").appendChild(option);
      });
    } catch (error) {
      byId("care-setting").disabled = true;
    }
  }

  function renderTactics(tactics) {
    state.tactics = tactics;
    byId("ask-tactic-count").textContent = String(tactics.length);
    byId("tactic-count").textContent = String(tactics.length) + " tactics";
    var tacticSelect = byId("specialist-tactic");
    tactics.forEach(function (tactic) {
      var option = create("option", "", tactic.title + (tactic.run_supported ? "" : " · browse only"));
      option.value = tactic.tactic_id;
      option.disabled = !tactic.run_supported;
      tacticSelect.appendChild(option);
    });
    [
      ["analysis-type-filter", "analysis_type"],
      ["journey-stage-filter", "journey_stage"],
      ["methodology-filter", "methodology_group"],
      ["market-filter", "market_applicability"],
      ["temporal-filter", "temporal_design"],
      ["evidence-type-filter", "evidence_type"]
    ].forEach(function (definition) {
      var select = byId(definition[0]);
      Array.from(new Set(tactics.map(function (item) { return item[definition[1]]; }).filter(Boolean))).sort().forEach(function (value) {
        var option = create("option", "", String(value).replaceAll("_", " "));
        option.value = value;
        select.appendChild(option);
      });
    });
    renderAskTactics();
    renderCatalogue();
  }

  function renderAskTactics() {
    var list = byId("ask-tactic-list");
    list.replaceChildren();
    state.tactics.forEach(function (tactic) {
      var card = create("article", "tactic-mini");
      card.appendChild(create("h3", "", tactic.title));
      card.appendChild(create("p", "", tactic.question));
      var button = create("button", "tactic-action ask", "Pin tactic");
      button.type = "button";
      button.addEventListener("click", function () {
        state.activeTacticId = tactic.tactic_id;
        byId("active-tactic").textContent = "Pinned: " + tactic.title;
        byId("question").value = tactic.question;
        updateCharacterCount();
        byId("question").focus();
        announce(tactic.title + " pinned.");
      });
      card.appendChild(button);
      list.appendChild(card);
    });
  }

  function renderCatalogue() {
    var query = byId("tactic-search").value.trim().toLowerCase();
    var filters = {
      analysis_type: byId("analysis-type-filter").value,
      journey_stage: byId("journey-stage-filter").value,
      methodology_group: byId("methodology-filter").value,
      market_applicability: byId("market-filter").value,
      temporal_design: byId("temporal-filter").value,
      evidence_type: byId("evidence-type-filter").value
    };
    var review = byId("review-filter").value;
    var filtered = state.tactics.filter(function (tactic) {
      var text = [tactic.title, tactic.question, tactic.why, tactic.method, tactic.category, tactic.target_population, tactic.denominator_definition].join(" ").toLowerCase();
      var matchesFilters = Object.keys(filters).every(function (key) { return filters[key] === "ALL" || tactic[key] === filters[key]; });
      var matchesReview = review === "ALL" || (review === "REQUIRED" && tactic.sme_review_required) || (review === "NOT_REQUIRED" && !tactic.sme_review_required);
      return (!query || text.indexOf(query) >= 0) && matchesFilters && matchesReview;
    });
    var catalogue = byId("tactic-catalogue");
    catalogue.replaceChildren();
    filtered.forEach(function (tactic) {
      var card = create("article", "tactic-card");
      card.dataset.tacticId = tactic.tactic_id;
      var meta = create("div", "tactic-meta");
      meta.appendChild(create("span", "", tactic.category));
      meta.appendChild(create("span", "", tactic.reviewer_status));
      card.appendChild(meta);
      card.appendChild(create("h3", "", tactic.title));
      card.appendChild(create("p", "", tactic.question));
      card.appendChild(create("p", "", tactic.why || "Registered analytical contract."));
      var result = tactic.current_results && tactic.current_results[0];
      card.appendChild(create("p", "tactic-result", result
        ? "Current certified synthetic result: " + (result.unit === "percent" ? Number(result.value).toFixed(1) + "%" : result.value) + " · numerator " + result.numerator + " / denominator " + result.denominator + "."
        : "Current certified synthetic result: no release-matched headline metric is displayed for this governance tactic."));
      var facts = create("dl", "tactic-facts");
      [
        ["Target population", tactic.target_population],
        ["Denominator", tactic.denominator_definition],
        ["Time window", tactic.time_window],
        ["Method", tactic.method],
        ["Limitation", tactic.limitation],
        ["Evidence source", tactic.evidence_source],
        ["Supported parameters", formatValue(tactic.supported_parameters)],
        ["Reviewer status", tactic.reviewer_status]
      ].forEach(function (entry) { facts.appendChild(create("dt", "", entry[0])); facts.appendChild(create("dd", "", entry[1] || "Not available in this release.")); });
      card.appendChild(facts);
      var levelTwo = create("details");
      levelTwo.appendChild(create("summary", "", "Level 2 · method and denominator"));
      levelTwo.appendChild(create("p", "", "Method: " + (tactic.method || "Open the governed contract.")));
      levelTwo.appendChild(create("p", "", "Denominator: " + (tactic.denominator_definition || "Open the governed contract.")));
      card.appendChild(levelTwo);
      var actions = create("div", "tactic-actions");
      [
        ["ask", "Ask about this"],
        ["method", "Open method"],
        ["evidence", "View evidence"],
        ["parameters", "Change parameters"],
        ["compare", "Compare"],
        ["specialist", "Start specialist analysis"]
      ].forEach(function (entry) {
        var button = create("button", "tactic-action" + (entry[0] === "ask" ? " ask" : ""), entry[1]);
        button.type = "button";
        if ((entry[0] === "parameters" || entry[0] === "compare") && !tactic.run_supported) { button.disabled = true; }
        if (state.presentationMode) {
          button.dataset.presentationWasDisabled = button.disabled ? "true" : "false";
          button.disabled = true;
        }
        button.addEventListener("click", function () { handleTacticAction(entry[0], tactic); });
        actions.appendChild(button);
      });
      card.appendChild(actions);
      catalogue.appendChild(card);
    });
    if (!filtered.length) { catalogue.appendChild(create("p", "empty-state", "No registered tactic matches this filter.")); }
  }

  async function handleTacticAction(action, tactic) {
    if (action === "method") { await openTacticContract(tactic.tactic_id); return; }
    if (action === "evidence") { await openTacticEvidence(tactic); return; }
    if (action === "ask") {
      switchMode("evidence");
      state.activeTacticId = tactic.tactic_id;
      byId("active-tactic").textContent = "Pinned: " + tactic.title;
      byId("question").value = "For the " + tactic.title + " tactic: " + tactic.question;
      updateCharacterCount();
      byId("question").focus();
      return;
    }
    switchMode("specialist");
    byId("specialist-tactic").value = tactic.run_supported ? tactic.tactic_id : "";
    byId("analysis-request").value = !tactic.run_supported
      ? "Propose new analysis related to " + tactic.title + ". Keep the method synthetic, aggregate-only, and subject to SME review."
      : action === "compare"
      ? "Compare this tactic with another approved interactive run while keeping denominators and methods separate: " + tactic.title
      : "Re-run " + tactic.title + " using the selected permitted parameters and show the exact denominator change.";
    updateParameterVisibility();
    updateFormStateSummary();
    byId("analysis-request").focus();
  }

  async function openTacticContract(tacticId) {
    try {
      var payload = await jsonRequest("/api/specialist/tactics/" + encodeURIComponent(tacticId));
      openToolDetail("Level 3 · evidence and implementation contract", payload);
    } catch (error) { addError("The tactic contract could not be resolved."); }
  }

  async function openTacticEvidence(tactic) {
    try {
      var payload = await post("/api/tools/search_certified_artifacts", {session_id: state.sessionId, arguments: {query: tactic.title + " " + tactic.question, top_k: 3}});
      if (!payload.result || !payload.result.length) { throw new Error("No source"); }
      await openSource(payload.result[0].artifact_id);
    } catch (error) { addError("No approved release-scoped evidence resolved for this tactic."); }
  }

  function switchMode(view) {
    var descriptions = {
      evidence: ["ASK THE EVIDENCE · READ ONLY", "Read-only answers grounded in one certified aggregate evidence release."],
      tactics: ["EXPLORE TACTICS · GOVERNED CATALOGUE", "Browse plain-language questions, exact methods, denominators, evidence, and permitted parameters."],
      specialist: ["SPECIALIST ANALYSIS · ISOLATED WORKSPACE", "Preview, explicitly confirm, execute, and QA synthetic experiments without changing the certified release."],
      history: ["RUN HISTORY · EXPERIMENT LINEAGE", "Inspect successful, proposed, failed, submitted, and expired runs outside certified Analytics."]
    };
    document.querySelectorAll(".mode-view").forEach(function (panel) { panel.hidden = panel.id !== "view-" + view; });
    document.querySelectorAll(".mode-tab").forEach(function (tab) {
      var active = tab.dataset.view === view;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    byId("trust-mode").textContent = descriptions[view][0];
    byId("mode-description").textContent = descriptions[view][1];
    var activeTab = document.querySelector('.mode-tab[data-view="' + view + '"]');
    if (activeTab) { activeTab.setAttribute("tabindex", "0"); }
    document.querySelectorAll('.mode-tab:not([data-view="' + view + '"])').forEach(function (tab) { tab.setAttribute("tabindex", "-1"); });
    announce(descriptions[view][0]);
  }

  function answerStatusLabel(value) {
    return {
      "directly evidenced": "CERTIFIED EVIDENCE",
      "derived deterministically": "DETERMINISTIC DERIVATION",
      "expert proposal": "PROPOSED ANALYSIS",
      "blocked pending SME or real data": "REQUIRES SME REVIEW",
      "not found": "NOT FOUND"
    }[value] || "EXPERT EXPLANATION";
  }

  function addUserMessage(textValue) {
    var article = create("article", "message user");
    article.appendChild(create("div", "message-label", "You · " + byId("market-select").value + " · " + byId("source-filter").selectedOptions[0].textContent));
    article.appendChild(create("p", "", textValue));
    byId("messages").appendChild(article);
    scrollMessages();
  }

  function addProgress() {
    var article = create("article", "message assistant");
    article.appendChild(create("div", "message-label", "Evidence Studio"));
    article.appendChild(create("p", "loading-state", "Searching the active certified evidence catalogue…"));
    byId("messages").appendChild(article);
    byId("messages").setAttribute("aria-busy", "true");
    announce("Retrieving evidence from the active certified aggregate catalogue.");
    scrollMessages();
    return article;
  }

  function addError(message) {
    var article = create("article", "message error");
    article.appendChild(create("div", "message-label", "Request unavailable"));
    article.appendChild(create("p", "", message));
    byId("messages").appendChild(article);
    byId("messages").setAttribute("aria-busy", "false");
    scrollMessages();
    announce(message);
  }

  function appendList(parent, title, values) {
    if (!values || !values.length) { return; }
    parent.appendChild(create("h3", "", title));
    var list = create("ul");
    values.forEach(function (value) { list.appendChild(create("li", "", value)); });
    parent.appendChild(list);
  }

  function renderMetrics(parent, metrics) {
    if (!metrics || !metrics.length) { return; }
    var strip = create("div", "metric-strip");
    metrics.forEach(function (metric) {
      var card = create("div", "metric-card");
      var display = metric.unit === "percent" ? Number(metric.value).toFixed(1) + "%" : String(metric.value);
      card.appendChild(create("strong", "", display));
      card.appendChild(create("span", "", metric.label));
      card.appendChild(create("span", "", "Numerator " + metric.numerator + " / denominator " + metric.denominator));
      card.appendChild(create("span", "", metric.time_window + " · " + metric.market));
      card.appendChild(create("span", "", metric.population));
      card.appendChild(create("span", "", "Method: " + metric.method));
      strip.appendChild(card);
    });
    parent.appendChild(strip);
  }

  function renderAnswer(payload, progressNode) {
    var answer = payload.answer;
    var article = create("article", "message assistant");
    article.appendChild(create("div", "message-label", "Evidence Studio · " + answer.active_market));
    article.appendChild(create("span", "answer-status", answerStatusLabel(answer.evidence_status)));
    article.appendChild(create("p", "", answer.direct_answer));
    renderMetrics(article, answer.quantitative_evidence);
    appendList(article, "Certified evidence", answer.certified_evidence);
    appendList(article, "Explanation", answer.explanation);
    appendList(article, "Limitations", answer.limitation);
    appendList(article, "Proposed next analysis", answer.proposed_next_analysis);
    appendList(article, "Not found in current artifacts", answer.not_found_in_current_artifacts);
    if (answer.evidence_sources && answer.evidence_sources.length) {
      article.appendChild(create("h3", "", "Evidence sources"));
      var sources = create("div");
      answer.evidence_sources.forEach(function (source) {
        var button = create("button", "citation-button", source.artifact_name);
        button.type = "button";
        button.addEventListener("click", function () { openSource(source.artifact_id); });
        sources.appendChild(button);
      });
      article.appendChild(sources);
    }
    var copy = create("button", "citation-button", "Copy answer");
    copy.type = "button";
    copy.addEventListener("click", async function () {
      var text = [answer.direct_answer, "CERTIFIED EVIDENCE: " + answer.certified_evidence.join(" "), "LIMITATION: " + answer.limitation.join(" "), "ACTIVE RELEASE: " + answer.active_release, answer.prohibited_use].join("\n\n");
      try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; announce("Validated answer copied."); }
      catch (error) { announce("Copy is unavailable in this browser."); }
    });
    article.appendChild(copy);
    progressNode.replaceWith(article);
    byId("messages").setAttribute("aria-busy", "false");
    renderSession(payload.session);
    scrollMessages();
  }

  function parseSseBlock(block) {
    var eventName = "message";
    var dataLines = [];
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) { eventName = line.slice(6).trim(); }
      else if (line.indexOf("data:") === 0) { dataLines.push(line.slice(5).trim()); }
    });
    return dataLines.length ? {event: eventName, data: JSON.parse(dataLines.join("\n"))} : null;
  }

  async function ask(question) {
    if (state.busy || !state.sessionId) { return; }
    state.busy = true;
    byId("send-question").disabled = true;
    setStatus("Searching", "waiting");
    addUserMessage(question);
    var progress = addProgress();
    try {
      var response = await fetch("/api/chat", {
        method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": state.csrfToken},
        body: JSON.stringify({session_id: state.sessionId, question: question, market: byId("market-select").value, tactic_id: state.activeTacticId, source_filter: byId("source-filter").value, idempotency_key: crypto.randomUUID()})
      });
      if (!response.ok || !response.body) { throw new Error("The AI evidence endpoint did not return a stream."); }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var complete = false;
      while (true) {
        var read = await reader.read();
        buffer += decoder.decode(read.value || new Uint8Array(), {stream: !read.done});
        var boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          var parsed = parseSseBlock(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (parsed && parsed.event === "status") { progress.querySelector("p").textContent = parsed.data.message; announce(parsed.data.message); }
          else if (parsed && parsed.event === "error") { throw new Error(parsed.data.message); }
          else if (parsed && parsed.event === "answer") { renderAnswer(parsed.data, progress); complete = true; }
          boundary = buffer.indexOf("\n\n");
        }
        if (read.done) { break; }
      }
      if (!complete) { throw new Error("The response ended before validation completed."); }
      setStatus("Ready", "ready");
    } catch (error) {
      progress.remove(); byId("messages").setAttribute("aria-busy", "false"); addError((ERROR_COPY[error.status] || error.message) + " Deterministic Analytics remains unaffected."); setStatus("AI unavailable", "error");
    } finally {
      state.busy = false; byId("send-question").disabled = false; state.activeTacticId = null; byId("active-tactic").textContent = "No tactic pinned";
    }
  }

  function updateParameterVisibility() {
    var tactic = byId("specialist-tactic").value;
    byId("initiation-window").closest("label").hidden = ["initiation_landmarks", "time_to_initiation", "segmented_treatment_gap"].indexOf(tactic) < 0;
    byId("persistence-gap").closest("label").hidden = tactic !== "persistence_sensitivity";
    byId("segment-mode").closest("label").hidden = tactic !== "segmented_treatment_gap";
    byId("care-setting").closest("label").hidden = tactic !== "segmented_treatment_gap" || byId("segment-mode").value !== "care_setting";
    byId("proposed-method-warning").hidden = Boolean(tactic);
  }

  function selectedMarkets() {
    var selected = Array.from(byId("run-market").selectedOptions).map(function (option) { return option.value; });
    if (selected.length > 1 && selected.indexOf("ALL") >= 0) { selected = selected.filter(function (value) { return value !== "ALL"; }); }
    return selected.length ? selected : ["ALL"];
  }

  function setSelectedMarkets(markets) {
    var normalized = markets && markets.length ? markets : ["ALL"];
    Array.from(byId("run-market").options).forEach(function (option) { option.selected = normalized.indexOf(option.value) >= 0; });
  }

  function updateFormStateSummary() {
    var tactic = byId("specialist-tactic").value || "proposed method";
    var parts = ["Tactic: " + tactic, "lens: " + byId("expert-lens").value, "markets: " + selectedMarkets().join(", "), "scenario: certified synthetic only"];
    if (!byId("initiation-window").closest("label").hidden) { parts.push("initiation: " + byId("initiation-window").value + " days"); }
    if (!byId("persistence-gap").closest("label").hidden) { parts.push("persistence gap: " + byId("persistence-gap").value + " days"); }
    if (!byId("segment-mode").closest("label").hidden) { parts.push("segmentation: " + byId("segment-mode").value); }
    byId("form-state-summary").textContent = "Form state — " + parts.join(" · ") + ".";
  }

  function addSpecialistTranscript(label, textValue) {
    var entry = create("p", "");
    entry.appendChild(create("strong", "", label + ": "));
    entry.appendChild(document.createTextNode(textValue));
    byId("specialist-transcript").appendChild(entry);
  }

  function synchronizeFormFromPreview(preview) {
    var spec = preview.spec;
    byId("expert-lens").value = spec.expert_lens;
    byId("specialist-tactic").value = spec.existing_tactic_id || "";
    setSelectedMarkets(spec.markets);
    if (spec.initiation_window_days) { byId("initiation-window").value = String(spec.initiation_window_days); }
    if (spec.persistence_gap_days) { byId("persistence-gap").value = String(spec.persistence_gap_days); }
    if (spec.parameters.segment) { byId("segment-mode").value = spec.parameters.segment; }
    if (spec.parameters.care_setting) { byId("care-setting").value = spec.parameters.care_setting; }
    updateParameterVisibility();
    updateLensPurpose();
    updateFormStateSummary();
    var changed = preview.parameter_diff.filter(function (item) { return item.changed; }).map(function (item) { return item.parameter + ": " + formatValue(item.certified_value) + " → " + formatValue(item.proposed_value); });
    addSpecialistTranscript("Studio interpretation", "Lens " + spec.expert_lens + "; tactic " + (spec.existing_tactic_id || "proposed method") + "; markets " + spec.markets.join(", ") + ". " + (changed.length ? "Typed changes: " + changed.join("; ") + "." : "No parameter changed from the registered defaults."));
  }

  function analysisParameters(tactic) {
    var markets = selectedMarkets();
    var parameters = markets.length > 1 ? {markets: markets} : {market: markets[0]};
    if (["initiation_landmarks", "time_to_initiation", "segmented_treatment_gap"].indexOf(tactic) >= 0) { parameters.initiation_window_days = Number(byId("initiation-window").value); }
    if (tactic === "persistence_sensitivity") { parameters.persistence_gap_days = Number(byId("persistence-gap").value); }
    if (tactic === "segmented_treatment_gap") {
      parameters.segment = byId("segment-mode").value;
      if (parameters.segment === "care_setting" && byId("care-setting").value) { parameters.care_setting = byId("care-setting").value; }
    }
    return parameters;
  }

  async function prepareAnalysis(event) {
    event.preventDefault();
    if (state.busy || state.specialistBlocked) { return; }
    var tactic = byId("specialist-tactic").value || null;
    var question = byId("analysis-request").value.trim();
    if (!tactic && question.toLowerCase().indexOf("propose") < 0) { question = "Propose new analysis: " + question; }
    state.busy = true;
    addSpecialistTranscript("You", question);
    byId("preview-analysis").disabled = true;
    byId("preview-status").textContent = "Classifying, validating, and calculating denominator preview…";
    try {
      var payload = await post("/api/specialist/preview", {
        session_id: state.sessionId,
        question: question,
        expert_lens: byId("expert-lens").value,
        tactic_id: tactic,
        parameters: analysisParameters(tactic),
        specialist_mode: true,
        use_model_router: byId("use-model-router").checked,
        idempotency_key: crypto.randomUUID()
      });
      state.activePreview = payload.preview;
      renderSession(payload.session);
      synchronizeFormFromPreview(payload.preview);
      renderPreview(payload.preview);
      byId("preview-status").textContent = "Preview complete. No analysis has run yet.";
    } catch (error) {
      byId("preview-status").textContent = error.message;
      announce("Analysis preview failed: " + error.message);
    } finally { state.busy = false; byId("preview-analysis").disabled = state.specialistBlocked; }
  }

  function formatValue(value) {
    if (value === null || value === undefined) { return "Not set"; }
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }

  function renderBadges(container, badges) {
    container.replaceChildren();
    (badges || []).forEach(function (value) {
      var kind = value.indexOf("FAILED") >= 0 ? " failed" : value.indexOf("SUBMITTED") >= 0 ? " submitted" : " proposed";
      container.appendChild(create("span", "badge" + kind, value));
    });
  }

  function renderPreview(preview) {
    byId("preview-empty").hidden = true;
    byId("preview-content").hidden = false;
    renderBadges(byId("preview-badges"), preview.badges);
    var timeline = byId("workflow-timeline");
    timeline.replaceChildren();
    preview.workflow.forEach(function (event) {
      var step = create("div", "workflow-step " + event.status.toLowerCase(), event.state);
      step.title = event.detail;
      timeline.appendChild(step);
    });
    var specSummary = byId("spec-summary");
    specSummary.replaceChildren();
    [
      ["Question", preview.spec.research_question],
      ["Recommended expert lens", preview.spec.expert_lens],
      ["Recommended/selected tactic", preview.spec.existing_tactic_id || "PROPOSED METHOD"],
      ["Population", preview.spec.target_population],
      ["Denominator", preview.spec.denominator_definition],
      ["Expected output", preview.spec.expected_outputs.join(", ")]
    ].forEach(function (entry) { var box = create("div"); box.appendChild(create("span", "", entry[0])); box.appendChild(create("strong", "", entry[1])); specSummary.appendChild(box); });
    var validation = byId("validation-summary");
    validation.replaceChildren();
    var summary = create("div", preview.validation.valid ? "validation-pass" : "validation-fail", preview.validation.valid ? "VALIDATION PASSED · all required contracts and parameter checks passed." : "VALIDATION FAILED · " + preview.validation.errors.join(" "));
    validation.appendChild(summary);
    var checks = create("details");
    checks.appendChild(create("summary", "", "Inspect validation checks"));
    var list = create("ul");
    preview.validation.checks.forEach(function (check) { list.appendChild(create("li", "", check.status + " · " + check.check_id + " · " + check.detail)); });
    checks.appendChild(list);
    validation.appendChild(checks);
    var diffBody = byId("diff-body");
    diffBody.replaceChildren();
    preview.parameter_diff.forEach(function (item) {
      var row = create("tr");
      [item.parameter, formatValue(item.certified_value), formatValue(item.proposed_value), (item.changed ? "CHANGED · " : "UNCHANGED · ") + item.impact].forEach(function (value) { row.appendChild(create("td", "", value)); });
      diffBody.appendChild(row);
    });
    var population = preview.population_preview;
    var alert = byId("denominator-change");
    alert.className = "denominator-alert" + (population.denominator_changed ? " changed" : "");
    alert.textContent = (population.denominator_changed ? "DENOMINATOR CHANGED · Previous " + formatValue(population.previous_denominator) + " · Current " + population.current_denominator + ". " : "DENOMINATOR UNCHANGED · " + population.current_denominator + ". ") + population.reason;
    var denominatorBody = byId("denominator-body");
    denominatorBody.replaceChildren();
    population.slices.forEach(function (item) {
      var row = create("tr");
      [item.market, item.population, item.numerator, item.denominator, item.excluded, item.censored, item.evaluability].forEach(function (value) { row.appendChild(create("td", "", String(value))); });
      denominatorBody.appendChild(row);
    });
    var cost = preview.cost_estimate;
    byId("cost-card").textContent = "ENGINE: " + cost.execution_engine + " · EXPECTED " + cost.expected_runtime_seconds + "s · HARD TIMEOUT " + cost.maximum_runtime_seconds + "s · PLANNING MODEL " + (cost.planning_model || "none") + " · PLAN CEILING $" + Number(cost.maximum_planning_cost_usd).toFixed(4) + " · LUNA SUMMARY CEILING $" + Number(cost.maximum_summary_cost_usd).toFixed(4) + " · MAX TOTAL $" + Number(cost.maximum_total_provider_cost_usd).toFixed(4) + " · " + (cost.within_budget ? "WITHIN BUDGET" : "BUDGET FAILED");
    byId("spec-json").textContent = JSON.stringify(preview.spec, null, 2);
    var assumptionPanel = byId("assumptions-limitations");
    assumptionPanel.replaceChildren();
    [["Assumptions", preview.spec.assumptions], ["Prohibited interpretations", preview.spec.prohibited_interpretations], ["Required SME review", preview.spec.sme_review_requirements]].forEach(function (group) {
      var section = create("section"); section.appendChild(create("h4", "", group[0])); var list = create("ul"); group[1].forEach(function (value) { list.appendChild(create("li", "", value)); }); section.appendChild(list); assumptionPanel.appendChild(section);
    });
    byId("plan-specialist").hidden = !preview.requires_specialist_plan;
    byId("run-analysis").disabled = !preview.confirmation_token;
    byId("confirmation-help").textContent = preview.warning;
    announce("Analysis preview complete. Validation " + (preview.validation.valid ? "passed" : "failed") + ". Denominator " + population.current_denominator + ". Maximum provider cost " + Number(cost.maximum_total_provider_cost_usd).toFixed(4) + " dollars.");
  }

  async function planSpecialist() {
    if (!state.activePreview || state.busy) { return; }
    state.busy = true;
    byId("plan-specialist").disabled = true;
    byId("preview-status").textContent = "Developing a bounded methodology plan with gpt-5.6-terra…";
    try {
      var payload = await post("/api/specialist/plan", {session_id: state.sessionId, request_id: state.activePreview.request_id, accept_estimated_cost: true});
      state.activePreview = payload.preview;
      renderSession(payload.session);
      renderPreview(payload.preview);
      byId("preview-status").textContent = "Specialist method plan complete; inspect before execution.";
    } catch (error) { byId("preview-status").textContent = error.message; announce(error.message); }
    finally { state.busy = false; byId("plan-specialist").disabled = false; }
  }

  async function executeAnalysis() {
    if (!state.activePreview || !state.activePreview.confirmation_token || state.busy) { return; }
    state.busy = true;
    byId("run-analysis").disabled = true;
    byId("preview-status").textContent = "Executing isolated aggregate analysis and post-run QA…";
    try {
      var payload = await post("/api/specialist/execute", {
        session_id: state.sessionId,
        request_id: state.activePreview.request_id,
        confirmation_token: state.activePreview.confirmation_token,
        confirmation: "RUN THIS ANALYSIS",
        use_model_summary: byId("use-model-summary").checked
      });
      state.activeRun = payload.run;
      if (payload.session) { renderSession(payload.session); }
      renderRun(payload.run);
      byId("preview-status").textContent = payload.run.manifest.status;
      await loadRuns();
      if (state.presentationMode && state.demoStep === 5) {
        byId("demo-next").disabled = false;
        byId("demo-step-copy").textContent = "The isolated run completed after explicit confirmation. Continue to inspect result, method, limitations, QA, provenance, and cost.";
      }
    } catch (error) { byId("preview-status").textContent = error.message; announce(error.message); }
    finally { state.busy = false; }
  }

  function renderRun(run) {
    byId("result-empty").hidden = true;
    byId("result-content").hidden = false;
    renderBadges(byId("result-badges"), run.manifest.badges);
    var content = byId("result-content");
    content.replaceChildren();
    var intro = create("p", run.qa.status === "PASS" ? "validation-pass" : "validation-fail", run.manifest.status + " · QA " + run.qa.status + " · parent release " + run.manifest.parent_release_id + " · provider cost $" + Number(run.manifest.actual_provider_cost_usd).toFixed(6));
    content.appendChild(intro);
    if (run.qa.status === "PASS") {
      var grid = create("div", "result-grid");
      run.results.forEach(function (row) {
        var card = create("article", "result-card");
        card.appendChild(create("strong", "", row.rate === null ? "N/A" : (Number(row.rate) * 100).toFixed(1) + "%"));
        card.appendChild(create("span", "", row.label + " · " + row.market + " · " + row.subgroup));
        card.appendChild(create("span", "", "Numerator " + row.numerator + " / denominator " + row.denominator));
        card.appendChild(create("span", "", row.time_window));
        card.appendChild(create("span", "", "Method: " + row.method));
        grid.appendChild(card);
      });
      content.appendChild(grid);
      appendList(content, "Interpretation boundary", run.interpretation);
      appendList(content, "Limitations", run.manifest.limitations);
      var actions = create("div", "run-actions");
      var exportButton = create("button", "button secondary", "Export aggregate CSV");
      exportButton.type = "button";
      exportButton.addEventListener("click", function () { exportAggregate(run.manifest.run_id); });
      actions.appendChild(exportButton);
      var manifestButton = create("button", "button secondary", "View run manifest");
      manifestButton.type = "button";
      manifestButton.addEventListener("click", function () { openToolDetail("Interactive run manifest", run.manifest); });
      actions.appendChild(manifestButton);
      var submit = create("button", "button primary", "Submit for review");
      submit.type = "button";
      submit.addEventListener("click", function () { submitRun(run.manifest.run_id); });
      actions.appendChild(submit);
      content.appendChild(actions);
    } else {
      content.appendChild(create("p", "", "ANALYSIS FAILED VALIDATION. Interpretation and export are suppressed."));
    }
    var qaDetails = create("details");
    qaDetails.appendChild(create("summary", "", "Post-run QA and provenance"));
    qaDetails.appendChild(create("pre", "source-excerpt", JSON.stringify({qa: run.qa, manifest: run.manifest}, null, 2)));
    content.appendChild(qaDetails);
    announce("Interactive analysis completed with QA " + run.qa.status + ".");
  }

  async function exportAggregate(runId) {
    try {
      var response = await fetch("/api/specialist/runs/" + encodeURIComponent(runId) + "/export");
      if (!response.ok) { throw new Error("Aggregate export failed."); }
      var blob = await response.blob();
      var url = URL.createObjectURL(blob);
      var link = create("a");
      link.href = url;
      link.download = runId + "_aggregate.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      announce("Aggregate-only export downloaded.");
    } catch (error) { announce(error.message); }
  }

  async function submitRun(runId) {
    var note = window.prompt("Optional note for the human review queue:", "Review denominator, method, limitations, and release lineage.");
    if (note === null) { return; }
    try {
      var submission = await post("/api/specialist/submit", {session_id: state.sessionId, run_id: runId, reviewer_note: note});
      openToolDetail("Review submission", submission);
      await loadRuns();
      announce("Run submitted for human review. Certification has not changed.");
    } catch (error) { announce(error.message); }
  }

  async function loadRuns() {
    try {
      var payload = await jsonRequest("/api/specialist/runs");
      state.runs = payload.runs || [];
      renderRunHistory();
      var active = state.runs.filter(function (run) { return !run.expired && run.qa_status === "PASS"; });
      [byId("left-run"), byId("right-run")].forEach(function (select) { select.replaceChildren(); });
      active.forEach(function (run, index) {
        [byId("left-run"), byId("right-run")].forEach(function (select, selectIndex) {
          var option = create("option", "", run.run_id + " · " + (run.tactic_id || "proposed"));
          option.value = run.run_id;
          if (index === selectIndex) { option.selected = true; }
          select.appendChild(option);
        });
      });
    } catch (error) { byId("run-history").textContent = ERROR_COPY[error.status] || "Run history is unavailable; certified Analytics remains unaffected."; }
  }

  function renderRunHistory() {
    var history = byId("run-history");
    history.replaceChildren();
    var selectedCategory = byId("history-filter").value;
    var categories = [
      ["successful_interactive_rerun", "Successful interactive re-runs"],
      ["proposed_custom_analysis", "Proposed custom analyses"],
      ["failed_validation", "Failed validation"],
      ["submitted_for_review", "Submitted for review"],
      ["expired", "Expired runs"]
    ];
    var visibleCount = 0;
    categories.forEach(function (definition) {
      if (selectedCategory !== "ALL" && selectedCategory !== definition[0]) { return; }
      var runs = state.runs.filter(function (run) { return run.category === definition[0]; });
      if (!runs.length) { return; }
      visibleCount += runs.length;
      var group = create("section", "run-group");
      group.appendChild(create("h3", "", definition[1] + " · " + runs.length));
      runs.forEach(function (run) {
        var card = create("article", "run-card");
        var header = create("div", "run-card-header");
        header.appendChild(create("h4", "", run.run_id));
        header.appendChild(create("span", "badge" + (run.qa_status === "FAIL" ? " failed" : run.submitted_for_review ? " submitted" : " proposed"), run.status + " · QA " + run.qa_status));
        card.appendChild(header);
        card.appendChild(create("p", "", run.user_question));
        var facts = create("div", "run-facts");
        [["Parent release", run.parent_release_id], ["Expert lens", run.expert_lens], ["Tactic", run.tactic_id || "PROPOSED METHOD"], ["Parameters", formatValue(run.parameters)], ["Provider cost", "$" + Number(run.actual_provider_cost_usd).toFixed(6)], ["Created", run.created_at], ["Expires", run.expires_at], ["Outputs", (run.output_files || []).join(", ")]].forEach(function (entry) { var fact = create("div"); fact.appendChild(create("span", "", entry[0])); fact.appendChild(create("strong", "", entry[1])); facts.appendChild(fact); });
        card.appendChild(facts);
        var actions = create("div", "run-actions");
        var manifest = create("button", "button secondary", "Open manifest and output");
        manifest.type = "button";
        manifest.addEventListener("click", async function () {
          try { var detail = await jsonRequest("/api/specialist/runs/" + encodeURIComponent(run.run_id)); openToolDetail("Interactive run evidence", detail); }
          catch (error) { announce(ERROR_COPY[error.status] || error.message); }
        });
        actions.appendChild(manifest);
        if (!run.expired && run.qa_status === "PASS") {
          var exportButton = create("button", "button secondary", "Export aggregate CSV");
          exportButton.type = "button";
          exportButton.addEventListener("click", function () { exportAggregate(run.run_id); });
          actions.appendChild(exportButton);
        }
        card.appendChild(actions);
        group.appendChild(card);
      });
      history.appendChild(group);
    });
    if (!visibleCount) { history.appendChild(create("p", "empty-state", state.runs.length ? "No interactive runs match the selected status." : "No isolated runs yet. Prepare and explicitly confirm an analysis to create one.")); }
    announce(visibleCount + " interactive runs displayed.");
  }

  async function compareRuns() {
    var left = byId("left-run").value;
    var right = byId("right-run").value;
    if (!left || !right || left === right) { byId("comparison-result").textContent = "Select two different runs."; return; }
    try {
      var payload = await post("/api/specialist/compare", {session_id: state.sessionId, left_run_id: left, right_run_id: right});
      byId("comparison-result").replaceChildren(create("pre", "source-excerpt", JSON.stringify(payload, null, 2)));
    } catch (error) { byId("comparison-result").textContent = error.message; }
  }

  function openToolDetail(title, payload) {
    var content = byId("source-content");
    content.replaceChildren();
    content.appendChild(create("h3", "", title));
    content.appendChild(create("pre", "source-excerpt", JSON.stringify(payload, null, 2)));
    openDrawer("source-drawer", "close-source");
  }

  async function openSource(artifactId) {
    try {
      var payload = await jsonRequest("/api/artifacts/" + encodeURIComponent(artifactId));
      var artifact = payload.artifact;
      var content = byId("source-content");
      content.replaceChildren();
      var list = create("dl", "source-grid");
      [["Artifact", artifact.artifact_name], ["Release", artifact.release_id], ["Certification", artifact.certification_status], ["Scope", artifact.source_scope], ["Approved use", artifact.permitted_use], ["SHA-256", artifact.sha256]].forEach(function (entry) {
        list.appendChild(create("dt", "", entry[0])); list.appendChild(create("dd", "", entry[1]));
      });
      content.appendChild(list);
      content.appendChild(create("h3", "", "Bounded source excerpt"));
      content.appendChild(create("pre", "source-excerpt", payload.content || "No displayable bounded text."));
      openDrawer("source-drawer", "close-source");
    } catch (error) { addError("The cited artifact could not be resolved from the active catalogue."); }
  }

  function openDrawer(drawerId, closeId) {
    state.focusBeforeDrawer = document.activeElement;
    ["source-drawer", "cost-drawer"].forEach(function (id) {
      if (id !== drawerId) { byId(id).classList.remove("open"); byId(id).setAttribute("aria-hidden", "true"); }
    });
    byId("drawer-backdrop").hidden = false;
    byId(drawerId).classList.add("open");
    byId(drawerId).setAttribute("aria-hidden", "false");
    byId(closeId).focus();
    announce(byId(drawerId).querySelector("h2").textContent + " opened.");
  }

  function closeDrawers() {
    ["source-drawer", "cost-drawer"].forEach(function (id) { byId(id).classList.remove("open"); byId(id).setAttribute("aria-hidden", "true"); });
    byId("drawer-backdrop").hidden = true;
    if (state.focusBeforeDrawer && typeof state.focusBeforeDrawer.focus === "function") { state.focusBeforeDrawer.focus(); }
    state.focusBeforeDrawer = null;
  }

  var DEMO_STEPS = [
    {view: "evidence", title: "Certified initiation answer", copy: "A deterministic tool displays the current synthetic 90-day initiation result and denominator without using the model."},
    {view: "evidence", title: "Cited evidence and provenance", copy: "Open the release-scoped artifact, SHA-256, certification scope, and bounded source excerpt."},
    {view: "tactics", title: "Initiation tactic contract", copy: "The tactic card exposes population, denominator, horizon, method, result, limitation, evidence, parameters, and review state."},
    {view: "specialist", title: "Natural-language parameter change", copy: "The request selects DE and FR, changes initiation from 90 to 60 days, and keeps deterministic routing for this demo."},
    {view: "specialist", title: "Typed diff and denominator preview", copy: "The validated AnalysisSpec, exact parameter diff, denominator slices, assumptions, warnings, and maximum cost appear before execution."},
    {view: "specialist", title: "Explicit controlled execution", copy: "Use RUN THIS ANALYSIS. The Next button remains locked until an isolated run completes and QA returns."},
    {view: "specialist", title: "Result, QA, provenance, and cost", copy: "Inspect aggregate n/N results, method, limitations, QA, parent release, manifest, and provider cost."},
    {view: "evidence", title: "Certified Analytics remains unchanged", copy: "Open deterministic Analytics in the other tab and verify the same parent release and certified values remain unchanged."},
    {view: "tactics", title: "Weak model evidence is not deployable", copy: "The model-disposition tactic remains browse-only and explicitly prohibits deployment claims or AI confidence scores."},
    {view: "history", title: "Narrow governed pilot message", copy: "Pilot one approved analytical question. Interactive outputs require human review and never become certified through this workspace."}
  ];

  function setPresentationLocks(locked) {
    var selectors = [
      ".mode-tab", ".starter", ".tactic-action", "#reset-session", "#market-select", "#source-filter",
      "#question", "#send-question", "#tactic-search", "#analysis-type-filter",
      "#journey-stage-filter", "#methodology-filter", "#market-filter", "#temporal-filter",
      "#evidence-type-filter", "#review-filter", "#expert-lens", "#specialist-tactic",
      "#analysis-request", "#run-market", "#initiation-window", "#persistence-gap",
      "#segment-mode", "#care-setting", "#scenario-scope", "#use-model-router", "#use-model-summary",
      "#preview-analysis", "#plan-specialist", "#refresh-runs", "#history-filter",
      "#left-run", "#right-run", "#compare-runs"
    ];
    document.querySelectorAll(selectors.join(",")).forEach(function (control) {
      if (locked) {
        control.dataset.presentationWasDisabled = control.disabled ? "true" : "false";
        control.disabled = true;
      } else {
        control.disabled = control.dataset.presentationWasDisabled === "true";
        delete control.dataset.presentationWasDisabled;
      }
    });
  }

  function resetPresentationState() {
    state.activePreview = null;
    state.activeRun = null;
    state.demoMetric = null;
    byId("tactic-search").value = "";
    ["analysis-type-filter", "journey-stage-filter", "methodology-filter", "market-filter", "temporal-filter", "evidence-type-filter", "review-filter"].forEach(function (id) { byId(id).value = "ALL"; });
    byId("market-select").value = "ALL";
    byId("source-filter").value = "ALL";
    byId("scenario-value").textContent = "ALL · certified view";
    byId("preview-empty").hidden = false;
    byId("preview-content").hidden = true;
    byId("result-empty").hidden = false;
    byId("result-content").hidden = true;
    byId("run-analysis").disabled = true;
    renderCatalogue();
  }

  async function renderDeterministicDemoAnswer() {
    var existing = byId("demo-evidence-answer");
    if (existing) { existing.remove(); }
    var payload = await post("/api/tools/get_certified_metric", {session_id: state.sessionId, arguments: {metric_id: "initiated_90d", market: "ALL"}});
    state.demoMetric = payload.result;
    var metric = payload.result;
    var article = create("article", "message assistant");
    article.id = "demo-evidence-answer";
    article.appendChild(create("div", "message-label", "Deterministic presentation fallback"));
    article.appendChild(create("span", "answer-status", "DETERMINISTIC DERIVATION"));
    article.appendChild(create("p", "", "The current certified synthetic 90-day initiation result is " + Number(metric.value).toFixed(1) + "%: numerator " + metric.numerator + " / denominator " + metric.denominator + "."));
    renderMetrics(article, [metric]);
    var citation = create("button", "citation-button", "Open cited evidence · " + metric.source_file);
    citation.type = "button";
    citation.addEventListener("click", function () { openSource(metric.source_artifact_id); });
    article.appendChild(citation);
    byId("messages").appendChild(article);
    scrollMessages();
  }

  function highlightDemoTarget(selector) {
    document.querySelectorAll(".demo-step-target").forEach(function (node) { node.classList.remove("demo-step-target"); });
    var target = selector ? document.querySelector(selector) : null;
    if (target) { target.classList.add("demo-step-target"); target.scrollIntoView({block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); }
  }

  async function applyDemoStep(index) {
    state.demoStep = Math.max(0, Math.min(DEMO_STEPS.length - 1, index));
    var step = DEMO_STEPS[state.demoStep];
    closeDrawers();
    switchMode(step.view);
    byId("demo-step-title").textContent = "Step " + (state.demoStep + 1) + " of " + DEMO_STEPS.length + " · " + step.title;
    byId("demo-step-copy").textContent = step.copy;
    byId("demo-previous").disabled = state.demoStep === 0;
    byId("demo-next").disabled = state.demoStep === DEMO_STEPS.length - 1;
    highlightDemoTarget(null);
    if (state.demoStep === 0) { await renderDeterministicDemoAnswer(); highlightDemoTarget("#demo-evidence-answer"); }
    if (state.demoStep === 1 && state.demoMetric) { await openSource(state.demoMetric.source_artifact_id); }
    if (state.demoStep === 2) { byId("tactic-search").value = "initiation"; renderCatalogue(); highlightDemoTarget('[data-tactic-id="initiation_landmarks"]'); }
    if (state.demoStep === 3) {
      byId("specialist-tactic").value = "initiation_landmarks";
      byId("expert-lens").value = "rwe_epidemiology";
      byId("analysis-request").value = "Compare DE and FR using a 60-day initiation window. Keep market denominators separate.";
      setSelectedMarkets(["DE", "FR"]);
      byId("initiation-window").value = "60";
      byId("use-model-router").checked = false;
      byId("use-model-summary").checked = false;
      updateParameterVisibility(); updateLensPurpose(); updateFormStateSummary();
      highlightDemoTarget("#specialist-form");
    }
    if (state.demoStep === 4) {
      if (!state.activePreview) { await prepareAnalysis({preventDefault: function () { return null; }}); }
      highlightDemoTarget("#analysis-preview");
    }
    if (state.demoStep === 5) { byId("demo-next").disabled = !state.activeRun; highlightDemoTarget("#run-analysis"); }
    if (state.demoStep === 6) { highlightDemoTarget(".run-panel"); }
    if (state.demoStep === 7) { highlightDemoTarget("#analytics-link"); }
    if (state.demoStep === 8) { byId("tactic-search").value = "model disposition"; renderCatalogue(); highlightDemoTarget('[data-tactic-id="model_disposition"]'); }
    if (state.demoStep === 9) { highlightDemoTarget("#history-title"); }
    if (state.demoStep !== 1) { byId("demo-step-title").focus(); }
    announce(byId("demo-step-title").textContent + ". " + step.copy);
  }

  function enterPresentationMode() {
    state.presentationMode = true;
    resetPresentationState();
    setPresentationLocks(true);
    document.body.classList.add("presentation-mode");
    byId("presentation-mode").setAttribute("aria-pressed", "true");
    byId("demo-controls").hidden = false;
    applyDemoStep(0);
  }

  function exitPresentationMode() {
    state.presentationMode = false;
    setPresentationLocks(false);
    document.body.classList.remove("presentation-mode");
    byId("presentation-mode").setAttribute("aria-pressed", "false");
    byId("demo-controls").hidden = true;
    highlightDemoTarget(null);
    byId("presentation-mode").focus();
    announce("Presentation mode closed.");
  }

  function updateCharacterCount() { byId("character-count").textContent = String(byId("question").value.length) + " / 2400"; }
  function updateLensPurpose() { var option = byId("expert-lens").selectedOptions[0]; byId("lens-purpose").textContent = option ? option.dataset.purpose : ""; }
  function scrollMessages() { var messages = byId("messages"); messages.scrollTop = messages.scrollHeight; }

  document.querySelectorAll(".mode-tab").forEach(function (button) {
    button.addEventListener("click", function () { switchMode(button.dataset.view); });
    button.addEventListener("keydown", function (event) {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(event.key) < 0) { return; }
      var tabs = Array.from(document.querySelectorAll(".mode-tab:not(:disabled)"));
      var current = tabs.indexOf(button);
      var next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      event.preventDefault(); tabs[next].focus(); tabs[next].click();
    });
  });
  byId("tactic-search").addEventListener("input", renderCatalogue);
  ["analysis-type-filter", "journey-stage-filter", "methodology-filter", "market-filter", "temporal-filter", "evidence-type-filter", "review-filter"].forEach(function (id) { byId(id).addEventListener("change", renderCatalogue); });
  byId("specialist-tactic").addEventListener("change", function () { updateParameterVisibility(); updateFormStateSummary(); });
  byId("segment-mode").addEventListener("change", function () { updateParameterVisibility(); updateFormStateSummary(); });
  byId("expert-lens").addEventListener("change", function () { updateLensPurpose(); updateFormStateSummary(); });
  ["run-market", "initiation-window", "persistence-gap", "care-setting", "use-model-router", "use-model-summary"].forEach(function (id) { byId(id).addEventListener("change", updateFormStateSummary); });
  byId("specialist-form").addEventListener("submit", prepareAnalysis);
  byId("plan-specialist").addEventListener("click", planSpecialist);
  byId("run-analysis").addEventListener("click", executeAnalysis);
  byId("refresh-runs").addEventListener("click", loadRuns);
  byId("history-filter").addEventListener("change", renderRunHistory);
  byId("compare-runs").addEventListener("click", compareRuns);
  byId("ask-form").addEventListener("submit", function (event) {
    event.preventDefault(); var question = byId("question").value.trim(); if (!question) { return; }
    byId("question").value = ""; updateCharacterCount(); ask(question);
  });
  byId("question").addEventListener("input", updateCharacterCount);
  byId("market-select").addEventListener("change", function () { byId("scenario-value").textContent = byId("market-select").value + " · synthetic scenario"; announce("Active synthetic scenario changed."); });
  document.querySelectorAll(".starter").forEach(function (button) { button.addEventListener("click", function () { byId("question").value = button.dataset.question; updateCharacterCount(); byId("question").focus(); }); });
  byId("reset-session").addEventListener("click", async function () {
    if (!state.sessionId || state.busy) { return; }
    try {
      var session = await post("/api/reset", {session_id: state.sessionId});
      state.sessionId = session.session_id; state.csrfToken = session.csrf_token;
      renderSession(session); state.activePreview = null; state.activeRun = null;
      byId("preview-empty").hidden = false; byId("preview-content").hidden = true;
      byId("result-empty").hidden = false; byId("result-content").hidden = true;
      byId("messages").replaceChildren(create("article", "message assistant welcome", "Workspace reset. Ask a release-grounded evidence question."));
      byId("specialist-transcript").replaceChildren(create("p", "", "Workspace reset. Describe a permitted analysis to synchronize chat, controls, and AnalysisSpec."));
      updateFormStateSummary();
      announce("Workspace and session budget reset.");
    } catch (error) { addError("Workspace reset failed."); }
  });
  byId("close-source").addEventListener("click", closeDrawers);
  byId("open-cost").addEventListener("click", function () { loadCostDashboard(); openDrawer("cost-drawer", "close-cost"); });
  byId("close-cost").addEventListener("click", closeDrawers);
  byId("drawer-backdrop").addEventListener("click", closeDrawers);
  byId("presentation-mode").addEventListener("click", function () { if (state.presentationMode) { exitPresentationMode(); } else { enterPresentationMode(); } });
  byId("demo-exit").addEventListener("click", exitPresentationMode);
  byId("demo-reset").addEventListener("click", function () { resetPresentationState(); applyDemoStep(0); });
  byId("demo-previous").addEventListener("click", function () { applyDemoStep(state.demoStep - 1); });
  byId("demo-next").addEventListener("click", function () { applyDemoStep(state.demoStep + 1); });
  document.addEventListener("keydown", function (event) {
    var drawer = document.querySelector(".source-panel.open");
    if (event.key === "Escape" && drawer) { event.preventDefault(); closeDrawers(); return; }
    if (event.key !== "Tab" || !drawer) { return; }
    var focusable = Array.from(drawer.querySelectorAll('button:not(:disabled), a[href], select:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex="0"]'));
    if (!focusable.length) { return; }
    var first = focusable[0]; var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  updateParameterVisibility();
  updateFormStateSummary();
  switchMode("evidence");
  initialize();
}());
