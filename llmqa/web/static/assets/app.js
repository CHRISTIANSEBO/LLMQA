// LLMQA dashboard — vanilla JS, no build step.
const $ = (sel) => document.querySelector(sel);
const api = (path, opts) => fetch(path, opts).then(async (r) => {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
});

let METRIC_ORDER = [];
let CASE_MAP = {}; // case_id → {input, expected, context, tags, gate_metrics}
let RESULT_MAP = {}; // case_id → full CaseResult (metrics[].detail, cost, latency, error)
let CURRENT_DATASET = null; // selected dataset file name
let LAST_RUN = null; // {summary, results} of the most recent single-provider run
let RUN_SUMMARY = {}; // run_id → history summary row (for the diff slots)

async function init() {
  // Wire tabs first so a #hash deep link applies before any async work.
  initTabs();
  const cfg = await api("/api/config");
  METRIC_ORDER = cfg.metrics;
  CURRENT_DATASET = cfg.default_dataset || cfg.dataset;
  applyCases(cfg.cases);

  const dsSel = $("#dataset");
  if (dsSel) {
    (cfg.datasets || [cfg.dataset]).forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name.replace(/\.ya?ml$/i, "");
      dsSel.appendChild(opt);
    });
    dsSel.value = CURRENT_DATASET;
    dsSel.addEventListener("change", onDatasetChange);
  }

  const provSel = $("#provider");
  cfg.all_providers.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p;
    const usable = cfg.providers.includes(p);
    opt.textContent = usable ? p : `${p} (no API key on server)`;
    if (!usable && p !== "mock") opt.disabled = true;
    provSel.appendChild(opt);
  });

  const metricsBox = $("#metrics");
  cfg.metrics.forEach((m) => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${m}" checked /> ${m}`;
    metricsBox.appendChild(label);
  });

  // Restore the last-used run config, then persist it on every change so a
  // reload doesn't reset your setup.
  restoreFormState();
  wireFormPersistence();

  $("#runBtn").addEventListener("click", runEval);
  const cancelBtn = $("#cancelBtn");
  if (cancelBtn) cancelBtn.addEventListener("click", cancelRun);
  const failedOnly = $("#failedOnly");
  if (failedOnly) failedOnly.addEventListener("change", applyResultView);
  const sortSel = $("#resultSort");
  if (sortSel) sortSel.addEventListener("change", applyResultView);
  const searchEl = $("#resultSearch");
  if (searchEl) searchEl.addEventListener("input", applyResultView);
  const metricSel = $("#metricFilter");
  if (metricSel) {
    cfg.metrics.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = `${m} failed`;
      metricSel.appendChild(opt);
    });
    metricSel.addEventListener("change", applyResultView);
  }
  const historySearch = $("#historySearch");
  if (historySearch) historySearch.addEventListener("input", applyHistoryFilter);
  initShortcuts();
  initCompare(cfg.all_providers);
  initDatasetValidator();
  initDownloads();
  initDatasetPeek();
  initHistoryDiff();
  initChartZoom();
  initTour();
  await loadHistory();
  // Deep link: /dashboard?run=<id> loads and shows that stored run so results
  // are shareable/bookmarkable. Otherwise start fresh with the empty state.
  const wantRun = new URLSearchParams(window.location.search).get("run");
  if (wantRun) {
    const ok = await loadRunById(wantRun);
    if (!ok) showEmptyState();
  } else {
    showEmptyState();
  }
}

// Load a stored run by id and render it into the results panel (used by the
// ?run= deep link and clicking a history row's id).
async function loadRunById(runId) {
  try {
    const raw = await api(`/api/runs/${encodeURIComponent(runId)}`);
    // /api/runs/{id} returns summary fields plus the full run under `detail`.
    // Per-case `passed` is a server-side property (not serialized), so compute
    // it here from gate_metrics + metric.passed (matches the backend).
    const det = raw.detail || {};
    const results = (det.results || []).map((r) => ({
      ...r,
      passed: casePassed(r),
    }));
    const run = {
      id: raw.id,
      provider: raw.provider, model: raw.model,
      pass_rate: raw.pass_rate, avg_score: raw.avg_score,
      total_cost_usd: raw.cost_usd != null ? raw.cost_usd : det.total_cost_usd,
      results,
    };
    const emptyState = $("#resultsEmpty");
    if (emptyState) emptyState.hidden = true;
    renderRun(run);
    switchTab("results");
    renderLoadedBanner(run);
    LAST_RUN = {
      summary: {
        provider: run.provider, model: run.model,
        pass_rate: run.pass_rate, avg_score: run.avg_score,
        total_cost_usd: run.total_cost_usd, run_id: run.id,
      },
      results,
    };
    renderVerdict(LAST_RUN.summary, results);
    setDownloadsEnabled(true);
    $("#status").textContent = `Loaded run #${run.id}`;
    return true;
  } catch (e) {
    $("#status").textContent = "\u26a0 " + e.message;
    return false;
  }
}

// Friendly "nothing here yet" prompt shown before the first run so the page
// never looks broken or blank on arrival.
function showEmptyState() {
  const panel = $("#resultsPanel");
  const empty = $("#resultsEmpty");
  if (empty) empty.hidden = false;
  if (panel) panel.hidden = true;
  $("#summary").hidden = true;
}

function selectedMetrics() {
  return [...document.querySelectorAll('#metrics input:checked')].map((i) => i.value);
}

// Rebuild the case lookup (used by row detail, dataset peek, and the progress
// denominator) from a /api/config cases array.
function applyCases(cases) {
  CASE_MAP = {};
  (cases || []).forEach((c) => { CASE_MAP[c.id] = c; });
}

// Switching datasets refetches that dataset's cases and resets the results.
async function onDatasetChange(e) {
  CURRENT_DATASET = e.target.value;
  try {
    const cfg = await api(`/api/config?dataset=${encodeURIComponent(CURRENT_DATASET)}`);
    applyCases(cfg.cases);
    initDatasetPeek();
    $("#results tbody").innerHTML = "";
    const verdictEl = $("#verdict"); if (verdictEl) verdictEl.hidden = true;
    setDownloadsEnabled(false);
    LAST_RUN = null;
    showEmptyState();
    $("#status").textContent = `Dataset: ${CURRENT_DATASET.replace(/\.ya?ml$/i, "")}`;
  } catch (err) {
    $("#status").textContent = "\u26a0 " + err.message;
  }
}

// Holds the AbortController for the in-flight streaming run so the Cancel
// button (and a dataset switch) can stop it mid-flight.
let _runAbort = null;

async function runEval() {
  const btn = $("#runBtn");
  const cancelBtn = $("#cancelBtn");
  const status = $("#status");
  // If a run is already streaming, this same handler shouldn't re-enter.
  btn.disabled = true;
  _runAbort = new AbortController();
  if (cancelBtn) cancelBtn.hidden = false;

  // Reset UI for a fresh streaming run; jump to Results so rows are visible.
  switchTab("results");
  const emptyState = $("#resultsEmpty");
  if (emptyState) emptyState.hidden = true;
  $("#summary").hidden = true;
  $("#resultsPanel").hidden = false;
  $("#results tbody").innerHTML = "";
  const tagFilterBar = document.getElementById("tagFilter");
  if (tagFilterBar) tagFilterBar.innerHTML = "";

  const verdictEl = $("#verdict");
  if (verdictEl) verdictEl.hidden = true;

  // Tell assistive tech the results region is actively updating.
  const tableWrap = document.querySelector("#resultsPanel .table-wrap");
  if (tableWrap) tableWrap.setAttribute("aria-busy", "true");

  const tags = $("#tags").value.trim().split(/\s+/).filter(Boolean);
  const tagList = tags.length ? tags : null;
  const concEl = $("#concurrency");
  const costEl = $("#maxCost");
  const conc = concEl ? Math.max(1, Math.min(16, parseInt(concEl.value, 10) || 1)) : 1;
  const maxCost = costEl && costEl.value !== "" ? parseFloat(costEl.value) : null;
  const body = {
    provider: $("#provider").value,
    metrics: selectedMetrics(),
    tags: tagList,
    dataset: CURRENT_DATASET,
    store: $("#store").checked,
    concurrency: conc,
    max_cost_usd: Number.isFinite(maxCost) ? maxCost : null,
  };

  const total = expectedCaseCount(tagList);
  const streamedResults = [];
  let caseCount = 0, passCount = 0, failCount = 0, costSoFar = 0;
  updateProgress(0, total, 0, 0);
  const costMeterEl = $("#rp-cost");
  if (costMeterEl) costMeterEl.textContent = "$0.0000";

  try {
    await streamRun(
      body,
      (result) => {
        caseCount++;
        if (result.passed) passCount++; else failCount++;
        costSoFar += result.cost_usd || 0;
        status.textContent = `Evaluating case ${caseCount}…`;
        streamedResults.push(result);
        appendCaseRow(result);
        updateProgress(caseCount, total, passCount, failCount);
        // Live cost meter (matters on real providers; $0 on the mock).
        if (costMeterEl) costMeterEl.textContent = "$" + costSoFar.toFixed(4);
      },
      async (event) => {
        $("#summary").hidden = false;
        const pct = Math.round(event.pass_rate * 100);
        $("#s-pass").textContent = `${pct}%`;
        $("#s-score").textContent = event.avg_score.toFixed(2);
        $("#s-model").textContent = `${event.provider}/${event.model}`;
        $("#s-cost").textContent = "$" + (event.total_cost_usd || 0).toFixed(4);
        renderLatency(streamedResults);
        renderMetricBreakdown(streamedResults);
        const stopped = event.stopped_early ? ` — stopped early (${event.stopped_reason})` : "";
        status.textContent = `Done — ${caseCount} cases${stopped}`;
        updateProgress(caseCount, caseCount, passCount, failCount);
        renderTagFilter(streamedResults);
        LAST_RUN = { summary: event, results: streamedResults };
        renderVerdict(event, streamedResults);
        setDownloadsEnabled(true);
        renderLoadedBanner({ id: event.run_id, provider: event.provider, model: event.model });
        // Make the stored run shareable/bookmarkable without a reload.
        if (event.run_id != null) {
          const url = new URL(window.location.href);
          url.searchParams.set("run", event.run_id);
          history.replaceState(null, "", url);
        }
        await loadHistory();
      },
      _runAbort.signal
    );
  } catch (e) {
    if (e.name === "AbortError") status.textContent = "Run cancelled.";
    else status.textContent = "⚠ " + e.message;
  } finally {
    btn.disabled = false;
    _runAbort = null;
    if (cancelBtn) cancelBtn.hidden = true;
    if (tableWrap) tableWrap.setAttribute("aria-busy", "false");
  }
}

function cancelRun() {
  if (_runAbort) _runAbort.abort();
}

/** Read a POST /api/run/stream Server-Sent-Events response, invoking
 *  onCase(result) for each completed case and onDone(summary) at the end.
 *  Kept as a small shared helper so SSE parsing lives in one place. */
async function streamRun(body, onCase, onDone, signal) {
  const resp = await fetch("/api/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      let event;
      try { event = JSON.parse(line.slice(6)); } catch { continue; }
      if (event.type === "case") onCase(event.result);
      else if (event.type === "done") onDone(event);
    }
  }
}

// Expected number of cases for a given tag filter (drives the progress bar's
// denominator before any case has streamed back).
function expectedCaseCount(tags) {
  const all = Object.values(CASE_MAP);
  if (!tags || !tags.length) return all.length;
  const want = new Set(tags);
  return all.filter((c) => (c.tags || []).some((t) => want.has(t))).length;
}

function updateProgress(done, total, pass, fail) {
  const wrap = $("#runProgress");
  if (!wrap) return;
  wrap.hidden = false;
  wrap.setAttribute("aria-hidden", "false");
  $("#rp-count").textContent = `${done} / ${total || "?"}`;
  $("#rp-pass").textContent = `\u2713 ${pass}`;
  $("#rp-fail").textContent = `\u2715 ${fail}`;
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  $("#rp-fill").style.width = pct + "%";
}

// One-line human verdict shown above the results table once a run completes.
function renderVerdict(summary, results) {
  const el = $("#verdict");
  if (!el) return;
  const total = results.length;
  const passed = results.filter((r) => r.passed).length;
  const failed = total - passed;
  const pct = Math.round((summary.pass_rate || 0) * 100);
  const failing = results.filter((r) => !r.passed).map((r) => r.case_id);
  let tail = "";
  if (failed) {
    const shown = failing.slice(0, 4).join(", ");
    const more = failing.length > 4 ? ` +${failing.length - 4} more` : "";
    tail = ` \u2014 review <span class="v-fail">${shown}${more}</span>`;
  } else {
    tail = " \u2014 clean sweep.";
  }
  el.className = "verdict " + (failed === 0 ? "ok" : "warn");
  el.innerHTML = `<strong>${passed}/${total}</strong> cases passed (${pct}%) \u00b7 avg score `
    + `<strong>${(summary.avg_score || 0).toFixed(2)}</strong> \u00b7 `
    + `${summary.provider}/${summary.model}${tail}`;
  el.hidden = false;
}

// Shows which stored run the Results view currently reflects, so the KPI cards
// and table are never ambiguous about what you're looking at.
function renderLoadedBanner(run) {
  const el = document.getElementById("loadedBanner");
  if (!el) return;
  if (!run || run.id == null) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `Showing <strong>run #${run.id}</strong> · ${esc(run.provider || "")}/${esc(run.model || "")}`;
}

// ---- Form state persistence ----------------------------------------------
const FORM_STATE_KEY = "llmqa-run-form";

function saveFormState() {
  try {
    const state = {
      provider: $("#provider")?.value,
      dataset: $("#dataset")?.value,
      tags: $("#tags")?.value,
      concurrency: $("#concurrency")?.value,
      maxCost: $("#maxCost")?.value,
      store: $("#store")?.checked,
      metrics: selectedMetrics(),
    };
    localStorage.setItem(FORM_STATE_KEY, JSON.stringify(state));
  } catch (e) { /* private mode: no-op */ }
}

function restoreFormState() {
  let s;
  try { s = JSON.parse(localStorage.getItem(FORM_STATE_KEY) || "null"); } catch { return; }
  if (!s) return;
  const set = (sel, v) => { const el = $(sel); if (el != null && v != null) el.value = v; };
  // Only restore a provider/dataset that still exists as an enabled option.
  const prov = $("#provider");
  if (prov && s.provider && [...prov.options].some((o) => o.value === s.provider && !o.disabled)) {
    prov.value = s.provider;
  }
  const ds = $("#dataset");
  if (ds && s.dataset && [...ds.options].some((o) => o.value === s.dataset)) {
    ds.value = s.dataset;
    CURRENT_DATASET = s.dataset;
  }
  set("#tags", s.tags);
  set("#concurrency", s.concurrency);
  set("#maxCost", s.maxCost);
  if ($("#store") && typeof s.store === "boolean") $("#store").checked = s.store;
  if (Array.isArray(s.metrics)) {
    document.querySelectorAll("#metrics input").forEach((i) => {
      i.checked = s.metrics.includes(i.value);
    });
  }
}

function wireFormPersistence() {
  ["#provider", "#dataset", "#tags", "#concurrency", "#maxCost", "#store"].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener("change", saveFormState);
  });
  document.querySelectorAll("#metrics input").forEach((i) => i.addEventListener("change", saveFormState));
}

// ---- Keyboard shortcuts ---------------------------------------------------
function initShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ignore when a modal/tour is open or when typing in a text field (except
    // the documented combos).
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    // Cmd/Ctrl+Enter: run an evaluation from anywhere.
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      const btn = $("#runBtn");
      if (btn && !btn.disabled) { switchTab("results"); runEval(); }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") {
      // Focus the results search (switch to Results if needed).
      e.preventDefault();
      switchTab("results");
      $("#resultSearch")?.focus();
    } else if (e.key === "f") {
      const cb = $("#failedOnly");
      if (cb) { switchTab("results"); cb.checked = !cb.checked; applyResultView(); }
    } else if (e.key === "r") {
      const btn = $("#runBtn");
      if (btn && !btn.disabled) { switchTab("results"); runEval(); }
    }
  });
}

// ---- Tabs: Run / Results / History & trend / Compare / Validate ----------
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) => {
    const on = b.dataset.tab === name;
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.classList.toggle("active", on);
  });
  document.querySelectorAll(".tabpanel").forEach((p) => {
    p.hidden = p.id !== `tab-${name}`;
  });
  try { history.replaceState(null, "", updateHashTab(name)); } catch (e) {}
}

function updateHashTab(name) {
  const url = new URL(window.location.href);
  url.hash = name;
  return url;
}

function initTabs() {
  const bar = document.getElementById("tabbar");
  if (!bar) return;
  bar.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) switchTab(btn.dataset.tab);
  });
  // Arrow-key navigation across the tablist (a11y).
  bar.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = [...bar.querySelectorAll(".tab")];
    const i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
    const next = e.key === "ArrowRight" ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length;
    tabs[next].focus();
    switchTab(tabs[next].dataset.tab);
  });
  // Open the tab from the URL hash (deep link), else default to Run.
  const fromHash = (window.location.hash || "").replace("#", "");
  const valid = ["run", "results", "history", "compare", "validate"];
  switchTab(valid.includes(fromHash) ? fromHash : "run");
}

// p50/p95 latency across the run, shown in a KPI card. Real signal once you
// run a live provider; stays 0ms on the deterministic mock.
function renderLatency(results) {
  const el = $("#s-latency");
  if (!el) return;
  const lats = (results || []).map((r) => r.latency_ms || 0).sort((a, b) => a - b);
  if (!lats.length) { el.textContent = "—"; return; }
  const pct = (p) => lats[Math.min(lats.length - 1, Math.round((p / 100) * (lats.length - 1)))];
  el.textContent = `${Math.round(pct(50))} / ${Math.round(pct(95))} ms`;
}

// Per-metric pass-rate bars: which metric is dragging quality down.
function renderMetricBreakdown(results) {
  const panel = $("#metricBreakdown");
  const bars = $("#mb-bars");
  if (!panel || !bars) return;
  const agg = {};
  (results || []).forEach((r) => {
    (r.metrics || []).forEach((m) => {
      const a = (agg[m.metric] = agg[m.metric] || { pass: 0, total: 0, score: 0 });
      a.total++; a.score += m.score; if (m.passed) a.pass++;
    });
  });
  const names = METRIC_ORDER.filter((n) => agg[n]);
  if (!names.length) { panel.hidden = true; return; }
  panel.hidden = false;
  bars.innerHTML = names.map((n) => {
    const a = agg[n];
    const rate = a.total ? a.pass / a.total : 0;
    const pct = Math.round(rate * 100);
    const avg = a.total ? (a.score / a.total) : 0;
    const cls = rate >= 0.8 ? "ok" : rate >= 0.5 ? "mid" : "bad";
    return `<div class="mb-row">`
      + `<span class="mb-name">${esc(n)}</span>`
      + `<span class="mb-track"><span class="mb-fill ${cls}" style="width:${pct}%"></span></span>`
      + `<span class="mb-val">${pct}% <span class="mb-avg">avg ${avg.toFixed(2)}</span></span></div>`;
  }).join("");
}

/** Build a result <tr> for one case — shared by renderRun and appendCaseRow. */
function buildResultRow(r) {
  const gate = new Set(r.gate_metrics || []);
  const metricCells = METRIC_ORDER.map((name) => {
    const m = (r.metrics || []).find((x) => x.metric === name);
    if (!m) return `<span class="mname">${name}: —</span>`;
    const isGate = gate.size === 0 || gate.has(name);
    const st = scoreState(m);
    const gateCls = "mscore " + st.cls + (isGate ? " gate" : "");
    const title = `${name}: ${st.label}${isGate ? " (gates pass/fail)" : " (informational)"}`;
    return `<span class="${gateCls}" title="${title}"><span class="sglyph">${st.glyph}</span>${name}=${m.score.toFixed(2)}</span>`;
  }).join("");
  const tagSpans = (r.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
  const badge = r.passed !== undefined ? r.passed : computePassed(r, gate);
  const bGlyph = badge ? "\u2713" : "\u2715";
  const ms = r.latency_ms != null ? `${r.latency_ms} ms` : "\u2014";
  const tr = document.createElement("tr");
  tr.className = "result-row";
  tr.dataset.tags = JSON.stringify(r.tags || []);
  tr.dataset.caseId = r.case_id;
  tr.dataset.output = r.output || "";
  tr.dataset.input = (CASE_MAP[r.case_id] && CASE_MAP[r.case_id].input) || "";
  // Stash the full result so the drill-down can show per-metric rationale,
  // per-case cost/latency, and the expected-vs-actual diff.
  RESULT_MAP[r.case_id] = r;
  // Extra filter keys.
  tr.dataset.gates = JSON.stringify(r.gate_metrics || []);
  tr.dataset.metricsPassed = JSON.stringify(
    (r.metrics || []).filter((m) => m.passed).map((m) => m.metric)
  );
  // Sort/filter keys (used by applyResultView).
  tr.dataset.passed = badge ? "1" : "0";
  tr.dataset.avgScore = String(avgScore(r));
  tr.dataset.latency = String(r.latency_ms || 0);
  tr.title = "Click to expand";
  tr.innerHTML = `<td data-label="Case"><strong class="expand-toggle">\u25b8 ${r.case_id}</strong></td>
    <td data-label="Result"><span class="badge ${badge ? "pass" : "fail"}"><span class="glyph">${bGlyph}</span>${badge ? "PASS" : "FAIL"}</span></td>
    <td data-label="Tags">${tagSpans}</td>
    <td data-label="Latency" class="latency">${ms}</td>
    <td data-label="Metrics"><div class="mgrid">${metricCells}</div></td>`;
  tr.addEventListener("click", toggleDetail);
  return tr;
}

function appendCaseRow(r) {
  $("#results tbody").appendChild(buildResultRow(r));
}

// Fetch a single case's full detail (incl. context) once and cache it into
// CASE_MAP so re-expanding is instant. /api/config omits context to keep its
// payload small; this fills it in on demand.
async function ensureContext(caseId) {
  const c = CASE_MAP[caseId];
  if (c && c.context != null) return c;
  try {
    const full = await api(
      `/api/cases/${encodeURIComponent(caseId)}?dataset=${encodeURIComponent(CURRENT_DATASET || "")}`
    );
    CASE_MAP[caseId] = { ...(CASE_MAP[caseId] || {}), ...full };
    return CASE_MAP[caseId];
  } catch {
    return null;
  }
}

function totalLatency(run) {
  return Math.round((run.results || []).reduce((a, r) => a + (r.latency_ms || 0), 0));
}

// Fallback pass/fail honoring gate_metrics (matches the backend CaseResult.passed).
function computePassed(r, gate) {
  const metrics = r.metrics || [];
  if (!metrics.length) return false;
  let gating = gate.size ? metrics.filter((m) => gate.has(m.metric)) : metrics;
  if (!gating.length) gating = metrics;
  return gating.every((m) => m.passed);
}

// Map a metric result to a visual state. The pass/fail glyph + label are
// driven by the server's authoritative `m.passed` (each metric has its own
// threshold — similarity passes at 0.30, not 0.50), so the UI can never label
// a passing metric as "fail" or vice-versa. The score magnitude only picks a
// color nuance: a passing-but-modest score gets a "partial" tint, never a
// contradicting glyph. Color is always paired with a glyph + label so the UI
// stays readable in grayscale and for red-green colorblindness.
function scoreState(m) {
  if (m.passed) {
    // Strong pass vs. squeaked-by pass — both show ✓, differ only in tint.
    const cls = m.score >= 0.8 ? "high" : "mid";
    return { cls, glyph: "\u2713", label: cls === "high" ? "pass" : "pass (marginal)" };
  }
  return { cls: "low", glyph: "\u2715", label: "fail" }; // ✕
}

function renderRun(run) {
  $("#summary").hidden = false;
  $("#resultsPanel").hidden = false;
  const pct = Math.round(run.pass_rate * 100);
  // Summary cards stay pure ink by design — no state color here.
  $("#s-pass").textContent = `${pct}%`;
  $("#s-score").textContent = run.avg_score.toFixed(2);
  $("#s-model").textContent = `${run.provider}/${run.model}`;
  $("#s-cost").textContent = "$" + (run.total_cost_usd || 0).toFixed(4);
  renderLatency(run.results);
  renderMetricBreakdown(run.results);

  const tbody = $("#results tbody");
  tbody.innerHTML = "";
  renderTagFilter(run.results);
  (run.results || []).forEach((r) => tbody.appendChild(buildResultRow(r)));
}

// ---- Tag filter -------------------------------------------------------
let _activeTagFilters = new Set();

function renderTagFilter(results) {
  const bar = document.getElementById("tagFilter");
  if (!bar) return;
  const allTags = new Set();
  (results || []).forEach(r => (r.tags || []).forEach(t => allTags.add(t)));
  bar.innerHTML = "";
  _activeTagFilters.clear();
  if (!allTags.size) return;

  const label = document.createElement("span");
  label.className = "tf-label";
  label.textContent = "Filter:";
  bar.appendChild(label);

  allTags.forEach(tag => {
    const btn = document.createElement("button");
    btn.className = "tag tf-btn";
    btn.textContent = tag;
    btn.dataset.tag = tag;
    btn.addEventListener("click", () => {
      if (_activeTagFilters.has(tag)) _activeTagFilters.delete(tag);
      else _activeTagFilters.add(tag);
      btn.classList.toggle("active", _activeTagFilters.has(tag));
      applyTagFilter();
    });
    bar.appendChild(btn);
  });

  const clearBtn = document.createElement("button");
  clearBtn.className = "tf-clear";
  clearBtn.textContent = "clear";
  clearBtn.addEventListener("click", () => {
    _activeTagFilters.clear();
    bar.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
    applyTagFilter();
  });
  bar.appendChild(clearBtn);
}

function applyTagFilter() {
  applyResultView();
}

// Combined view controls for the results table: tag filter + "failed only" +
// sort. Runs over the current rows (works during streaming and after).
function applyResultView() {
  const tbody = document.querySelector("#results tbody");
  if (!tbody) return;
  const failedOnly = document.getElementById("failedOnly");
  const sortSel = document.getElementById("resultSort");
  const searchEl = document.getElementById("resultSearch");
  const metricSel = document.getElementById("metricFilter");
  const onlyFail = failedOnly && failedOnly.checked;
  const mode = sortSel ? sortSel.value : "default";
  const q = searchEl ? searchEl.value.trim().toLowerCase() : "";
  const metricWant = metricSel ? metricSel.value : "";

  // Collapse any expanded detail rows first so sorting only moves result rows.
  tbody.querySelectorAll("tr.detail-row").forEach((d) => {
    const parent = d.previousElementSibling;
    if (parent) {
      parent.classList.remove("expanded");
      const t = parent.querySelector(".expand-toggle");
      if (t) t.innerHTML = `\u25b8 ${parent.dataset.caseId}`;
    }
    d.remove();
  });

  const rows = [...tbody.querySelectorAll("tr.result-row")];
  // Filter (tags + failed-only + text search + metric).
  let shown = 0;
  rows.forEach((tr) => {
    const tags = tr.dataset.tags ? JSON.parse(tr.dataset.tags) : [];
    const tagOk = !_activeTagFilters.size || tags.some((t) => _activeTagFilters.has(t));
    const failOk = !onlyFail || tr.dataset.passed === "0";
    const hay = (tr.dataset.caseId + " " + (tr.dataset.input || "")).toLowerCase();
    const searchOk = !q || hay.includes(q);
    // Metric filter: show cases where the selected metric FAILED (the debugging
    // case) — i.e. the metric ran and is not in metricsPassed.
    let metricOk = true;
    if (metricWant) {
      const passedM = tr.dataset.metricsPassed ? JSON.parse(tr.dataset.metricsPassed) : [];
      const ran = (RESULT_MAP[tr.dataset.caseId]?.metrics || []).some((m) => m.metric === metricWant);
      metricOk = ran && !passedM.includes(metricWant);
    }
    const vis = tagOk && failOk && searchOk && metricOk;
    tr.hidden = !vis;
    if (vis) shown++;
  });
  const countEl = document.getElementById("resultCount");
  if (countEl) countEl.textContent = shown === rows.length ? `${rows.length} cases` : `${shown} / ${rows.length} cases`;

  // Sort (reorder the DOM rows; stable via index tiebreak).
  if (mode !== "default") {
    const num = (v) => (Number.isFinite(+v) ? +v : 0);
    const cmp = {
      "fail-first": (a, b) => num(a.dataset.passed) - num(b.dataset.passed),
      "score-asc": (a, b) => num(a.dataset.avgScore) - num(b.dataset.avgScore),
      "score-desc": (a, b) => num(b.dataset.avgScore) - num(a.dataset.avgScore),
      "latency-desc": (a, b) => num(b.dataset.latency) - num(a.dataset.latency),
    }[mode];
    if (cmp) rows.sort(cmp).forEach((tr) => tbody.appendChild(tr));
  }
}
// ------------------------------------------------------------------------

async function loadHistory() {
  const { runs } = await api("/api/history?limit=30");
  RUN_SUMMARY = {};
  const tbody = $("#history tbody");
  tbody.innerHTML = "";
  runs.forEach((r) => {
    RUN_SUMMARY[r.id] = r;
    const tr = document.createElement("tr");
    tr.className = "hist-row";
    tr.draggable = true;
    tr.dataset.runId = r.id;
    tr.title = "Drag into a slot above — or click to add to the diff";
    // Show just the dataset name (the stored value is a full path).
    const ds = ((r.dataset || "").split(/[/\\]/).pop() || "").replace(/\.ya?ml$/i, "") || "—";
    const label = r.label ? esc(r.label) : "—";
    // Searchable haystack for the history filter.
    tr.dataset.hay = `${r.provider} ${r.model} ${ds} ${r.label || ""}`.toLowerCase();
    tr.innerHTML = `<td><a class="link-btn run-link" data-run-id="${r.id}" title="Open this run">#${r.id}</a></td>
      <td title="${esc(r.timestamp || "")}">${relTime(r.timestamp)}</td>
      <td>${esc(r.provider)}/${esc(r.model)}</td>
      <td>${esc(ds)}</td>
      <td>${label}</td>
      <td>${Math.round(r.pass_rate * 100)}%</td>
      <td>${r.avg_score.toFixed(2)}</td>
      <td>$${(r.cost_usd || 0).toFixed(4)}</td>
      <td><button class="mini-btn diff-add" type="button" data-run-id="${r.id}" title="Add this run to the A/B diff">⇄ diff</button></td>`;
    tr.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", String(r.id));
      e.dataTransfer.effectAllowed = "copy";
      tr.classList.add("dragging");
    });
    tr.addEventListener("dragend", () => tr.classList.remove("dragging"));
    tr.addEventListener("click", (e) => {
      // The #id link opens the run; the '⇄ diff' button adds it to the A/B
      // slots; clicking elsewhere in the row also adds to the diff.
      const link = e.target.closest(".run-link");
      const diffBtn = e.target.closest(".diff-add");
      if (link) {
        e.stopPropagation();
        const id = link.dataset.runId;
        const url = new URL(window.location.href);
        url.searchParams.set("run", id);
        history.replaceState(null, "", url);
        loadRunById(id);
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else if (diffBtn) {
        e.stopPropagation();
        assignRunToNextSlot(r.id);
        document.getElementById("slotA")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else {
        assignRunToNextSlot(r.id);
      }
    });
    tbody.appendChild(tr);
  });
  refreshSlots();
  renderTrend(runs);
  applyHistoryFilter();
}

// Relative timestamp ("2m ago", "3h ago", "5d ago") from an ISO string, so the
// history reads at a glance instead of a wall of identical wall-clock stamps.
function relTime(iso) {
  if (!iso) return "—";
  const t = Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Filter the history table by the search box (provider / dataset / label).
function applyHistoryFilter() {
  const q = (document.getElementById("historySearch")?.value || "").trim().toLowerCase();
  const rows = [...document.querySelectorAll("#history tbody tr")];
  let shown = 0;
  rows.forEach((tr) => {
    const vis = !q || (tr.dataset.hay || "").includes(q);
    tr.hidden = !vis;
    if (vis) shown++;
  });
  const c = document.getElementById("historyCount");
  if (c) c.textContent = shown === rows.length ? `${rows.length} runs` : `${shown} / ${rows.length} runs`;
}

function renderTrend(runs) {
  const el = $("#trend");
  if (!runs || runs.length < 2) {
    el.innerHTML = runs && runs.length === 1
      ? "One run so far — trend appears after the second run."
      : "No history yet — run an evaluation.";
    return;
  }
  const series = [...runs].reverse(); // oldest -> newest
  const W = 900, H = 130, padX = 26, padY = 22;
  const n = series.length;
  const x = (i) => padX + (i * (W - 2 * padX)) / (n - 1);
  const y = (v) => H - padY - v * (H - 2 * padY); // 0..1 mapped with headroom
  const path = (key) =>
    series.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`).join(" ");
  const dots = (key, color) =>
    series.map((r, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(r[key]).toFixed(1)}" r="3" fill="${color}"/>`).join("");
  // Pure ink by design: pass rate = solid line, avg score = dashed line.
  // The two series are distinguished by line style, not color.
  const css = getComputedStyle(document.documentElement);
  const inkColor = css.getPropertyValue("--ink").trim() || "#111111";
  const inkColor2 = css.getPropertyValue("--ink-2").trim() || "#333333";
  const gridColor = css.getPropertyValue("--rule").trim() || "#dddad2";
  const mutedColor = css.getPropertyValue("--muted").trim() || "#6b6b6b";
  const failColor = css.getPropertyValue("--fail").trim() || "#c1121f";
  // Subtle area fill under the pass-rate line for presence.
  const areaPath = `M${x(0).toFixed(1)},${y(0).toFixed(1)} `
    + series.map((r, i) => `L${x(i).toFixed(1)},${y(r.pass_rate).toFixed(1)}`).join(" ")
    + ` L${x(n - 1).toFixed(1)},${y(0).toFixed(1)} Z`;
  // Flag the largest run-over-run pass-rate DROP as a caught regression.
  let worstIdx = -1, worstDrop = 0;
  for (let i = 1; i < n; i++) {
    const drop = series[i - 1].pass_rate - series[i].pass_rate;
    if (drop > worstDrop) { worstDrop = drop; worstIdx = i; }
  }
  const regressionMark = (worstIdx >= 0 && worstDrop >= 0.1)
    ? `<circle cx="${x(worstIdx).toFixed(1)}" cy="${y(series[worstIdx].pass_rate).toFixed(1)}" r="4.5" fill="${failColor}"/>`
      + `<line x1="${x(worstIdx).toFixed(1)}" y1="${(y(series[worstIdx].pass_rate) + 6).toFixed(1)}" x2="${x(worstIdx).toFixed(1)}" y2="${H - 6}" stroke="${failColor}" stroke-width="1" stroke-dasharray="2 2"/>`
      + `<text x="${x(worstIdx).toFixed(1)}" y="${H - 1}" fill="${failColor}" font-size="9" text-anchor="middle">regression caught</text>`
    : "";
  const gridY = [0, 0.5, 1].map((v) =>
    `<line x1="${padX}" y1="${y(v).toFixed(1)}" x2="${W - padX}" y2="${y(v).toFixed(1)}" stroke="${gridColor}" stroke-width="1"/>` +
    `<text x="2" y="${(y(v) + 3).toFixed(1)}" fill="${mutedColor}" font-size="9">${v}</text>`).join("");
  // Mark where the dataset changed between consecutive runs: a score jump then
  // isn't apples-to-apples. Dashed vertical rule + a small 'dataset changed' tag.
  let datasetChanged = false;
  const marks = series.map((r, i) => {
    if (i === 0) return "";
    const prev = series[i - 1];
    if (r.dataset_hash && prev.dataset_hash && r.dataset_hash !== prev.dataset_hash) {
      datasetChanged = true;
      const mx = x(i).toFixed(1);
      return `<line x1="${mx}" y1="${padY}" x2="${mx}" y2="${H - padY}" stroke="${mutedColor}" stroke-width="1" stroke-dasharray="2 3"/>`
        + `<text x="${mx}" y="${padY - 4}" fill="${mutedColor}" font-size="8" text-anchor="middle">dataset Δ</text>`;
    }
    return "";
  }).join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="quality trend">
      ${gridY}${marks}
      <path d="${areaPath}" fill="${inkColor}" opacity="0.05"/>
      <path d="${path("avg_score")}" fill="none" stroke="${inkColor2}" stroke-width="2" stroke-dasharray="5 4"/>
      <path d="${path("pass_rate")}" fill="none" stroke="${inkColor}" stroke-width="2.5"/>
      ${dots("avg_score", inkColor2)}${dots("pass_rate", inkColor)}
      ${regressionMark}
    </svg>
    <div class="chart-cap">
      ―― pass rate (solid) &nbsp;&nbsp; –– avg score (dashed) &nbsp; (oldest → newest, ${n} runs)
      ${datasetChanged ? '&nbsp;&nbsp;¦ dataset Δ = golden set changed (not apples-to-apples)' : ''}
      <span class="zoom-hint">⤢ tap to enlarge / download</span>
    </div>`;
}

// ---- Provider comparison -----------------------------------------------
function initCompare(allProviders) {
  const selA = document.getElementById("cmp-a");
  const selB = document.getElementById("cmp-b");
  if (!selA || !selB) return;

  allProviders.forEach((p, i) => {
    [selA, selB].forEach((sel) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    });
  });
  // Default: strong vs lite for an instant meaningful comparison.
  selA.value = allProviders.includes("mock-strong") ? "mock-strong" : allProviders[0];
  selB.value = allProviders.includes("mock-lite")   ? "mock-lite"   : allProviders[1] || allProviders[0];

  document.getElementById("cmpBtn").addEventListener("click", runCompare);
}

async function runCompare() {
  const btn = document.getElementById("cmpBtn");
  const status = document.getElementById("cmp-status");
  const provA = document.getElementById("cmp-a").value;
  const provB = document.getElementById("cmp-b").value;
  btn.disabled = true;
  status.textContent = "Running both providers…";

  try {
    const data = await api("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ providers: [provA, provB], dataset: CURRENT_DATASET }),
    });
    renderComparison(data);
    status.textContent = "";
  } catch (e) {
    status.textContent = "\u26a0 " + e.message;
  } finally {
    btn.disabled = false;
  }
}

function renderComparison({ runs, providers }) {
  const [pA, pB] = providers;
  const runA = runs[pA], runB = runs[pB];
  const allCases = (runA.results || []).map(r => r.case_id);

  // Summary bar
  const sumEl = document.getElementById("cmp-summary");
  const fmt = (r, p) => `<span class="cmp-pill"><strong>${p}</strong> &nbsp; pass ${Math.round(r.pass_rate*100)}% &nbsp; avg ${r.avg_score.toFixed(2)}</span>`;
  sumEl.innerHTML = fmt(runA, pA) + "<span class='cmp-vs'>vs</span>" + fmt(runB, pB);

  // Per-case grouped bar chart
  renderCmpChart(allCases, runA, runB, pA, pB);

  // Diff table
  const head = document.getElementById("cmp-head");
  head.innerHTML = `<th>Case</th><th>${pA}</th><th>${pB}</th><th>Delta</th>`;

  const body = document.getElementById("cmp-body");
  body.innerHTML = "";
  allCases.forEach(cid => {
    const rA = (runA.results || []).find(r => r.case_id === cid);
    const rB = (runB.results || []).find(r => r.case_id === cid);
    if (!rA || !rB) return;

    const scoreA = avgScore(rA), scoreB = avgScore(rB);
    const delta = scoreB - scoreA;
    const passA = rA.passed, passB = rB.passed;
    const flip = passA !== passB;

    const tr = document.createElement("tr");
    if (flip) tr.className = "cmp-flip";
    tr.innerHTML = `
      <td data-label="Case"><strong>${cid}</strong></td>
      <td data-label="${esc(pA)}">${badgeHtml(passA)} <span class="cmp-score">${scoreA.toFixed(2)}</span></td>
      <td data-label="${esc(pB)}">${badgeHtml(passB)} <span class="cmp-score">${scoreB.toFixed(2)}</span></td>
      <td data-label="Delta" class="cmp-delta ${delta > 0 ? 'pos' : delta < 0 ? 'neg' : 'neu'}">${delta >= 0 ? '+' : ''}${delta.toFixed(2)}</td>`;
    body.appendChild(tr);
  });

  document.getElementById("cmp-results").hidden = false;
}

function renderCmpChart(cases, runA, runB, labelA, labelB) {
  const el = document.getElementById("cmp-chart");
  if (!el || !cases.length) return;

  const BAR = 18, GAP = 4, GROUP = BAR * 2 + GAP, GUTTER = 6;
  const W = Math.max(600, cases.length * (GROUP + GUTTER) + 120);
  const H = 140;
  const padL = 110, padR = 16, padT = 28, padB = 24;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const barX = (i, slot) => padL + i * (GROUP + GUTTER) + slot * (BAR + GAP);
  const barH = (score) => Math.round(score * chartH);
  const barY = (score) => padT + chartH - barH(score);

  const css = getComputedStyle(document.documentElement);
  const passCol  = css.getPropertyValue("--pass").trim()  || "#1a7f37";
  const failCol  = css.getPropertyValue("--fail").trim()  || "#c1121f";
  const ruleCol  = css.getPropertyValue("--rule").trim()  || "#dddad2";
  const mutedCol = css.getPropertyValue("--muted").trim() || "#6b6b6b";
  const inkCol   = css.getPropertyValue("--ink").trim()   || "#111111";

  // horizontal grid lines at 0, 0.5, 1.0
  const gridLines = [0, 0.5, 1].map(v => {
    const y = barY(v);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="${ruleCol}" stroke-width="1"/>`
      + `<text x="${padL - 4}" y="${y + 4}" fill="${mutedCol}" font-size="9" text-anchor="end">${v}</text>`;
  }).join("");

  // bars
  const bars = cases.map((cid, i) => {
    const rA = (runA.results || []).find(r => r.case_id === cid);
    const rB = (runB.results || []).find(r => r.case_id === cid);
    const sA = rA ? avgScore(rA) : 0, sB = rB ? avgScore(rB) : 0;
    const pA2 = rA?.passed, pB2 = rB?.passed;
    const colA = pA2 ? passCol : failCol;
    const colB = pB2 ? passCol : failCol;
    const xA = barX(i, 0), xB = barX(i, 1);
    const label = cid.length > 14 ? cid.slice(0, 13) + "\u2026" : cid;
    return [
      `<rect x="${xA}" y="${barY(sA)}" width="${BAR}" height="${barH(sA)}" fill="${colA}" opacity="0.85"/>`,
      `<rect x="${xB}" y="${barY(sB)}" width="${BAR}" height="${barH(sB)}" fill="${colB}" opacity="0.5"/>`,
      `<text x="${xA + BAR}" y="${H - 4}" fill="${mutedCol}" font-size="8" text-anchor="middle"
        transform="rotate(-35 ${xA + BAR} ${H - 4})">${label}</text>`,
    ].join("");
  }).join("");

  // legend
  const legY = padT - 14;
  const legend = [
    `<rect x="${padL}" y="${legY}" width="10" height="10" fill="${inkCol}" opacity="0.85"/>`,
    `<text x="${padL + 13}" y="${legY + 9}" fill="${inkCol}" font-size="10">${labelA}</text>`,
    `<rect x="${padL + 80}" y="${legY}" width="10" height="10" fill="${inkCol}" opacity="0.5"/>`,
    `<text x="${padL + 93}" y="${legY + 9}" fill="${inkCol}" font-size="10">${labelB}</text>`,
    `<rect x="${padL + 160}" y="${legY}" width="10" height="10" fill="${passCol}"/>`,
    `<text x="${padL + 173}" y="${legY + 9}" fill="${mutedCol}" font-size="10">pass</text>`,
    `<rect x="${padL + 205}" y="${legY}" width="10" height="10" fill="${failCol}"/>`,
    `<text x="${padL + 218}" y="${legY + 9}" fill="${mutedCol}" font-size="10">fail</text>`,
  ].join("");

  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="per-case score comparison">
    ${gridLines}${bars}${legend}
  </svg>
  <div class="chart-cap"><span class="zoom-hint">⤢ tap to enlarge / download</span></div>`;
}

function avgScore(r) {
  const scores = (r.metrics || []).map(m => m.score);
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
}

function badgeHtml(passed) {
  const g = passed ? "\u2713" : "\u2715";
  return `<span class="badge ${passed ? 'pass' : 'fail'}"><span class="glyph">${g}</span>${passed ? 'PASS' : 'FAIL'}</span>`;
}
// -------------------------------------------------------------------------


function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function toggleDetail(e) {
  const tr = e.currentTarget;
  const caseId = tr.dataset.caseId;
  const output = tr.dataset.output;
  const c = CASE_MAP[caseId] || {};
  const toggle = tr.querySelector(".expand-toggle");

  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail-row")) {
    next.remove();
    tr.classList.remove("expanded");
    if (toggle) toggle.innerHTML = `\u25b8 ${caseId}`;
    return;
  }

  const detail = document.createElement("tr");
  detail.className = "detail-row";
  const r = RESULT_MAP[caseId] || {};
  // Context is fetched lazily (it can be large, so /api/config omits it). Show
  // a placeholder that fills in once /api/cases/{id} resolves.
  const ctx = c.has_context
    ? `<div class="detail-field"><span class="dl">Context</span><pre class="dv ctx">${c.context != null ? esc(c.context) : "loading\u2026"}</pre></div>`
    : "";
  const expected = c.expected || "";
  // Per-metric breakdown: score, gate vs informational, pass/fail, rationale.
  const gate = new Set(r.gate_metrics || []);
  const metricRows = (r.metrics || []).map((m) => {
    const isGate = gate.size === 0 || gate.has(m.metric);
    const st = scoreState(m);
    return `<tr class="mrow ${st.cls}">`
      + `<td class="mrow-name">${esc(m.metric)}${isGate ? ' <span class="mrow-gate">gate</span>' : ""}</td>`
      + `<td class="mrow-score"><span class="sglyph">${st.glyph}</span> ${m.score.toFixed(2)}</td>`
      + `<td class="mrow-detail">${esc(m.detail || "—")}</td></tr>`;
  }).join("");
  const metricTable = metricRows
    ? `<div class="detail-field detail-metrics"><span class="dl">Metric breakdown</span>`
      + `<table class="mrow-table"><tbody>${metricRows}</tbody></table></div>`
    : "";
  // Per-case cost / latency / error.
  const lat = r.latency_ms != null ? `${r.latency_ms} ms` : "—";
  const cost = r.cost_usd != null ? `$${(r.cost_usd || 0).toFixed(4)}` : "—";
  const meta = `<div class="detail-meta">`
    + `<span class="dmeta"><span class="dmeta-k">latency</span> ${lat}</span>`
    + `<span class="dmeta"><span class="dmeta-k">cost</span> ${cost}</span>`
    + (r.error ? `<span class="dmeta dmeta-err"><span class="dmeta-k">error</span> ${esc(r.error)}</span>` : "")
    + `</div>`;
  // Expected-vs-actual word diff (only meaningful when there's an expected).
  const diffBlock = expected
    ? `<div class="detail-field"><span class="dl">Expected vs. output <button class="mini-btn diff-toggle" type="button">diff</button></span>`
      + `<pre class="dv exp">${esc(expected)}</pre>`
      + `<pre class="dv out">${esc(output || "—")}</pre>`
      + `<pre class="dv worddiff" hidden></pre></div>`
    : `<div class="detail-field"><span class="dl">Model output</span><pre class="dv out">${esc(output || "—")}</pre></div>`;
  detail.innerHTML = `<td colspan="5" class="detail-cell">
    ${meta}
    <div class="detail-grid">
      <div class="detail-field"><span class="dl">Input</span><pre class="dv">${esc(c.input || "—")}</pre></div>
      ${ctx}
      ${diffBlock}
      ${metricTable}
    </div>
    <div class="detail-actions">
      <button class="mini-btn rerun-btn" type="button">\u21bb Re-run just this case</button>
      <span class="rerun-status" aria-live="polite"></span>
    </div>
  </td>`;
  tr.after(detail);
  tr.classList.add("expanded");
  if (toggle) toggle.innerHTML = `\u25be ${caseId}`;
  // Lazily load context if we don't have it yet and the case has one.
  if (c.has_context && c.context == null) {
    ensureContext(caseId).then((full) => {
      if (!full) return;
      const pre = detail.querySelector(".dv.ctx");
      if (pre) pre.textContent = full.context || "\u2014";
    });
  }
  const rerunBtn = detail.querySelector(".rerun-btn");
  if (rerunBtn) rerunBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    rerunCase(caseId, tr, detail);
  });
  // Expected-vs-output word diff toggle.
  const diffBtn = detail.querySelector(".diff-toggle");
  if (diffBtn) diffBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const field = diffBtn.closest(".detail-field");
    const expPre = field.querySelector(".dv.exp");
    const outPre = field.querySelector(".dv.out");
    const diffPre = field.querySelector(".dv.worddiff");
    const showingDiff = !diffPre.hidden;
    if (showingDiff) {
      diffPre.hidden = true;
      expPre.hidden = false; outPre.hidden = false;
      diffBtn.textContent = "diff";
    } else {
      diffPre.innerHTML = wordDiff(expected, output || "");
      diffPre.hidden = false;
      expPre.hidden = true; outPre.hidden = true;
      diffBtn.textContent = "show raw";
    }
  });
}

// Tiny word-level diff: highlights tokens present in output-but-not-expected
// (added) and expected-but-not-output (missing). Not a full LCS diff — a
// readable, dependency-free approximation that makes a mismatch obvious.
function wordDiff(expected, output) {
  const tok = (s) => s.split(/(\s+)/);
  const norm = (w) => w.toLowerCase().replace(/[^a-z0-9]/g, "");
  const expSet = new Set(tok(expected).map(norm).filter(Boolean));
  const outSet = new Set(tok(output).map(norm).filter(Boolean));
  const expHtml = tok(expected).map((w) => {
    const n = norm(w);
    return n && !outSet.has(n) ? `<span class="wd-miss">${esc(w)}</span>` : esc(w);
  }).join("");
  const outHtml = tok(output).map((w) => {
    const n = norm(w);
    return n && !expSet.has(n) ? `<span class="wd-add">${esc(w)}</span>` : esc(w);
  }).join("");
  return `<span class="wd-label">expected</span>${expHtml}\n<span class="wd-label">output</span>${outHtml}`;
}

// Re-run a single case through the currently selected provider/metrics using
// the backend's case_ids filter. Result is not stored (store:false) so the
// history stays a log of full runs. The row is refreshed in place.
async function rerunCase(caseId, row, detailRow) {
  const statusEl = detailRow.querySelector(".rerun-status");
  const btn = detailRow.querySelector(".rerun-btn");
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = "running\u2026";
  try {
    const data = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: $("#provider").value,
        metrics: selectedMetrics(),
        case_ids: [caseId],
        dataset: CURRENT_DATASET,
        store: false,
      }),
    });
    const r = (data.results || []).find((x) => x.case_id === caseId) || (data.results || [])[0];
    if (!r) throw new Error("case not found in response");
    const fresh = buildResultRow(r);
    fresh.classList.add("flash");
    detailRow.remove();
    row.replaceWith(fresh);
  } catch (e) {
    if (statusEl) statusEl.textContent = "\u26a0 " + e.message;
    if (btn) btn.disabled = false;
  }
}

// =====================================================================
// Report downloads (Markdown / JSON) for the most recent run
// =====================================================================
function setDownloadsEnabled(on) {
  ["#dl-md", "#dl-json", "#dl-junit"].forEach((sel) => {
    const b = document.querySelector(sel);
    if (b) b.disabled = !on;
  });
}

function initDownloads() {
  setDownloadsEnabled(false);
  const md = $("#dl-md"), js = $("#dl-json"), ju = $("#dl-junit");
  if (md) md.addEventListener("click", () => {
    if (!LAST_RUN) return;
    downloadFile(reportFilename("md"), buildReportMarkdown(), "text/markdown");
  });
  if (js) js.addEventListener("click", () => {
    if (!LAST_RUN) return;
    downloadFile(reportFilename("json"), buildReportJSON(), "application/json");
  });
  if (ju) ju.addEventListener("click", () => {
    if (!LAST_RUN) return;
    downloadFile(reportFilename("xml"), buildReportJUnit(), "application/xml");
  });
}

// Client-side JUnit XML, mirroring report.to_junit so a dashboard run produces
// the same CI-consumable artifact as the CLI: one <testcase> per case, a
// <failure> when it didn't pass, gated metrics in the message.
function buildReportJUnit() {
  const s = LAST_RUN.summary || {};
  const rows = LAST_RUN.results || [];
  const failures = rows.filter((r) => !r.passed).length;
  const suite = `llmqa.${(s.provider || "run")}`;
  const xesc = (v) => String(v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>'];
  lines.push(`<testsuite name="${xesc(suite)}" tests="${rows.length}" failures="${failures}">`);
  rows.forEach((r) => {
    const time = ((r.latency_ms || 0) / 1000).toFixed(3);
    if (r.passed) {
      lines.push(`  <testcase classname="${xesc(suite)}" name="${xesc(r.case_id)}" time="${time}"/>`);
    } else {
      const gated = (r.gate_metrics && r.gate_metrics.length)
        ? r.gate_metrics.join(", ") : "all metrics";
      const scores = (r.metrics || []).map((m) => `${m.metric}=${m.score.toFixed(2)}`).join(" ");
      lines.push(`  <testcase classname="${xesc(suite)}" name="${xesc(r.case_id)}" time="${time}">`);
      lines.push(`    <failure message="${xesc(`gated on ${gated}`)}">${xesc(scores)}</failure>`);
      lines.push(`  </testcase>`);
    }
  });
  lines.push(`</testsuite>`);
  return lines.join("\n");
}

function reportFilename(ext) {
  const s = LAST_RUN.summary || {};
  const prov = (s.provider || "run").replace(/[^a-z0-9-]/gi, "-");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
  return `llmqa-${prov}-${stamp}.${ext}`;
}

function buildReportJSON() {
  return JSON.stringify(
    { summary: LAST_RUN.summary, results: LAST_RUN.results }, null, 2
  );
}

function buildReportMarkdown() {
  const s = LAST_RUN.summary || {};
  const rows = LAST_RUN.results || [];
  const total = rows.length;
  const passed = rows.filter((r) => r.passed).length;
  const lines = [];
  lines.push(`# LLMQA evaluation report`);
  lines.push("");
  lines.push(`- **Provider/model:** ${s.provider}/${s.model}`);
  lines.push(`- **Pass rate:** ${passed}/${total} (${Math.round((s.pass_rate || 0) * 100)}%)`);
  lines.push(`- **Avg score:** ${(s.avg_score || 0).toFixed(2)}`);
  lines.push(`- **Total cost:** $${(s.total_cost_usd || 0).toFixed(4)}`);
  lines.push(`- **Generated:** ${new Date().toISOString()}`);
  lines.push("");
  lines.push(`| Case | Result | Latency | ${METRIC_ORDER.join(" | ")} |`);
  lines.push(`|---|---|---|${METRIC_ORDER.map(() => "---").join("|")}|`);
  rows.forEach((r) => {
    const cells = METRIC_ORDER.map((name) => {
      const m = (r.metrics || []).find((x) => x.metric === name);
      return m ? m.score.toFixed(2) : "\u2014";
    });
    const ms = r.latency_ms != null ? `${r.latency_ms} ms` : "\u2014";
    lines.push(`| ${r.case_id} | ${r.passed ? "PASS" : "FAIL"} | ${ms} | ${cells.join(" | ")} |`);
  });
  lines.push("");
  return lines.join("\n");
}

function downloadFile(filename, text, mime) {
  const blob = new Blob([text], { type: mime + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// =====================================================================
// Dataset validator — paste/upload a dataset and check it against the schema
// via /api/validate-dataset. Nothing is stored server-side.
// =====================================================================
function initDatasetValidator() {
  const text = $("#ds-text");
  const file = $("#ds-file");
  const btn = $("#ds-validate");
  const clear = $("#ds-clear");
  const status = $("#ds-status");
  const result = $("#ds-result");
  if (!text || !btn) return;

  if (file) file.addEventListener("change", async () => {
    const f = file.files && file.files[0];
    if (!f) return;
    text.value = await f.text();
    status.textContent = `Loaded ${f.name}`;
  });

  if (clear) clear.addEventListener("click", () => {
    text.value = "";
    if (file) file.value = "";
    status.textContent = "";
    result.hidden = true;
    result.innerHTML = "";
  });

  btn.addEventListener("click", async () => {
    const content = text.value.trim();
    if (!content) { status.textContent = "Paste or upload a dataset first."; return; }
    btn.disabled = true;
    status.textContent = "Validating\u2026";
    try {
      const data = await api("/api/validate-dataset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      status.textContent = "";
      result.hidden = false;
      result.className = "ds-result ok";
      const rows = data.cases.map((c) => {
        const tags = (c.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
        const gates = (c.gate_metrics && c.gate_metrics.length)
          ? c.gate_metrics.map((g) => `<code>${esc(g)}</code>`).join(" ")
          : `<span class="peek-allgate">all metrics</span>`;
        return `<div class="peek-item"><div class="peek-head"><span class="peek-id">${esc(c.id)}</span>${tags}</div>`
          + `<div class="peek-in">${esc(c.input || "")}</div>`
          + `<div class="peek-gate">gated on: ${gates}${c.has_context ? ' \u00b7 <span class="peek-allgate">has context</span>' : ""}</div></div>`;
      }).join("");
      result.innerHTML = `<p class="ds-ok-head">\u2713 Valid \u2014 ${data.count} case${data.count === 1 ? "" : "s"}.</p>`
        + `<div class="peek-list">${rows}</div>`;
    } catch (e) {
      result.hidden = false;
      result.className = "ds-result err";
      result.innerHTML = `<p class="ds-err-head">\u2715 Invalid</p><pre class="dv">${esc(e.message)}</pre>`;
      status.textContent = "";
    } finally {
      btn.disabled = false;
    }
  });
}

// =====================================================================
// Dataset peek — what's actually being graded, and what gates each case
// =====================================================================
function initDatasetPeek() {
  const list = $("#peek-list");
  const count = $("#peek-count");
  if (!list) return;
  const cases = Object.values(CASE_MAP);
  if (count) count.textContent = `(${cases.length} cases)`;
  list.innerHTML = cases.map((c) => {
    const tags = (c.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
    const gates = (c.gate_metrics && c.gate_metrics.length)
      ? c.gate_metrics.map((g) => `<code>${g}</code>`).join(" ")
      : `<span class="peek-allgate">all metrics</span>`;
    return `<div class="peek-item">
      <div class="peek-head"><span class="peek-id">${c.id}</span>${tags}</div>
      <div class="peek-in">${esc(c.input || "")}</div>
      <div class="peek-gate">gated on: ${gates}</div>
    </div>`;
  }).join("");
}

// =====================================================================
// History diff — drag (or click) two runs into slots and diff them
// =====================================================================
const SLOTS = { A: null, B: null };

function initHistoryDiff() {
  ["A", "B"].forEach((which) => {
    const slot = document.querySelector(`#slot${which}`);
    if (!slot) return;
    slot.addEventListener("dragover", (e) => { e.preventDefault(); slot.classList.add("over"); });
    slot.addEventListener("dragleave", () => slot.classList.remove("over"));
    slot.addEventListener("drop", (e) => {
      e.preventDefault();
      slot.classList.remove("over");
      const id = parseInt(e.dataTransfer.getData("text/plain"), 10);
      if (!Number.isNaN(id)) { SLOTS[which] = id; refreshSlots(); maybeRenderDiff(); }
    });
  });
  const clearBtn = $("#slotClear");
  if (clearBtn) clearBtn.addEventListener("click", () => {
    SLOTS.A = null; SLOTS.B = null; refreshSlots(); maybeRenderDiff();
  });
}

function assignRunToNextSlot(id) {
  if (SLOTS.A === null || SLOTS.A === id) SLOTS.A = id;
  else if (SLOTS.B === null) SLOTS.B = id;
  else SLOTS.B = id; // replace B once both full
  refreshSlots();
  maybeRenderDiff();
}

function refreshSlots() {
  ["A", "B"].forEach((which) => {
    const slot = document.querySelector(`#slot${which}`);
    if (!slot) return;
    const id = SLOTS[which];
    const r = id != null ? RUN_SUMMARY[id] : null;
    slot.classList.toggle("filled", !!r);
    if (r) {
      slot.innerHTML = `<span class="slot-label">Run #${r.id}</span>`
        + `<span class="slot-meta">${r.provider}/${r.model}</span>`
        + `<span class="slot-meta">${Math.round(r.pass_rate * 100)}% \u00b7 avg ${r.avg_score.toFixed(2)}</span>`;
    } else {
      slot.innerHTML = `<span class="slot-label">Run ${which}</span><span class="slot-hint">drag a run here</span>`;
    }
  });
  const clearBtn = $("#slotClear");
  if (clearBtn) clearBtn.hidden = SLOTS.A === null && SLOTS.B === null;
  // reflect which history rows are selected
  document.querySelectorAll("#history .hist-row").forEach((tr) => {
    const id = parseInt(tr.dataset.runId, 10);
    tr.classList.toggle("selected", id === SLOTS.A || id === SLOTS.B);
  });
}

async function maybeRenderDiff() {
  const box = $("#histDiff");
  if (!box) return;
  if (SLOTS.A === null || SLOTS.B === null || SLOTS.A === SLOTS.B) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = `<p class="hint">Loading runs \u2026</p>`;
  try {
    const [runA, runB] = await Promise.all([
      api(`/api/runs/${SLOTS.A}`),
      api(`/api/runs/${SLOTS.B}`),
    ]);
    renderHistDiff(runA, runB);
  } catch (e) {
    box.innerHTML = `<p class="hint">\u26a0 ${e.message}</p>`;
  }
}

function renderHistDiff(runA, runB) {
  const box = $("#histDiff");
  const rateA = runA.pass_rate ?? passRate(runA), rateB = runB.pass_rate ?? passRate(runB);
  const avgA = runA.avg_score ?? 0, avgB = runB.avg_score ?? 0;
  const dRate = Math.round((rateB - rateA) * 100);
  const dAvg = avgB - avgA;
  const byId = (run) => {
    const m = {};
    (run.results || []).forEach((r) => { m[r.case_id] = r; });
    return m;
  };
  const mapA = byId(runA), mapB = byId(runB);
  const ids = [...new Set([...Object.keys(mapA), ...Object.keys(mapB)])];
  const flips = [];
  ids.forEach((id) => {
    const a = mapA[id], b = mapB[id];
    if (!a || !b) return;
    const pa = casePassed(a), pb = casePassed(b);
    if (pa !== pb) flips.push({ id, from: pa, to: pb });
  });
  const header = `<div class="diff-head">`
    + `<span class="diff-run">#${runA.id || "A"} \u2192 #${runB.id || "B"}</span>`
    + diffStat("pass rate", `${dRate >= 0 ? "+" : ""}${dRate} pts`, dRate)
    + diffStat("avg score", `${dAvg >= 0 ? "+" : ""}${dAvg.toFixed(2)}`, dAvg)
    + `</div>`;
  let flipHtml;
  if (!flips.length) {
    flipHtml = `<p class="hint">No cases flipped pass/fail between these two runs.</p>`;
  } else {
    flipHtml = `<div class="diff-flips">` + flips.map((f) =>
      `<div class="diff-flip ${f.to ? "gained" : "lost"}">`
      + `<span class="badge ${f.from ? "pass" : "fail"}"><span class="glyph">${f.from ? "\u2713" : "\u2715"}</span>${f.from ? "PASS" : "FAIL"}</span>`
      + `<span class="diff-arrow">\u2192</span>`
      + `<span class="badge ${f.to ? "pass" : "fail"}"><span class="glyph">${f.to ? "\u2713" : "\u2715"}</span>${f.to ? "PASS" : "FAIL"}</span>`
      + `<code class="diff-cid">${f.id}</code></div>`
    ).join("") + `</div>`;
  }
  box.innerHTML = header + flipHtml;
}

function diffStat(label, value, sign) {
  const cls = sign > 0 ? "pos" : sign < 0 ? "neg" : "neu";
  return `<span class="diff-stat"><span class="diff-label">${label}</span>`
    + `<span class="diff-val ${cls}">${value}</span></span>`;
}

function passRate(run) {
  const rs = run.results || [];
  if (!rs.length) return 0;
  return rs.filter(casePassed).length / rs.length;
}

function casePassed(r) {
  if (r.passed !== undefined) return r.passed;
  return computePassed(r, new Set(r.gate_metrics || []));
}

// =====================================================================
// Chart zoom + PNG export — tap any chart (trend / comparison) to enlarge it
// in a modal, then download it as a PNG. Helps a lot on mobile where the
// inline SVGs are small and the comparison chart otherwise scrolls sideways.
// =====================================================================
function initChartZoom() {
  const modal = $("#chartModal");
  if (!modal) return;
  let currentSvg = null;
  let currentName = "llmqa-chart";

  let _lastFocus = null;
  const open = (svg, title, name) => {
    currentSvg = svg;
    currentName = name;
    _lastFocus = document.activeElement;
    const body = $("#cm-body");
    body.innerHTML = "";
    const clone = svg.cloneNode(true);
    clone.removeAttribute("width");
    clone.removeAttribute("height");
    clone.style.width = "100%";
    clone.style.height = "auto";
    body.appendChild(clone);
    const t = $("#cm-title");
    if (t) t.textContent = title;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    // Move focus into the dialog for keyboard users.
    const closeBtn = $("#cm-close");
    if (closeBtn) closeBtn.focus();
  };
  const close = () => {
    modal.hidden = true;
    $("#cm-body").innerHTML = "";
    document.body.style.overflow = "";
    // Restore focus to whatever opened the modal.
    if (_lastFocus && _lastFocus.focus) _lastFocus.focus();
    _lastFocus = null;
  };

  // Trap Tab focus within the modal while it's open (accessibility).
  modal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const focusables = modal.querySelectorAll(
      'button, [href], input, select, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // Event delegation: charts are re-rendered via innerHTML, so bind on document.
  document.addEventListener("click", (e) => {
    const svg = e.target.closest && e.target.closest("#trend svg, #cmp-chart svg");
    if (!svg) return;
    const isTrend = !!svg.closest("#trend");
    open(
      svg,
      isTrend ? "Quality trend" : "Provider comparison",
      isTrend ? "llmqa-trend" : "llmqa-comparison"
    );
  });

  const closeBtn = $("#cm-close");
  if (closeBtn) closeBtn.addEventListener("click", close);
  const backdrop = modal.querySelector(".cm-backdrop");
  if (backdrop) backdrop.addEventListener("click", close);
  window.addEventListener("keydown", (e) => {
    if (!modal.hidden && e.key === "Escape") close();
  });
  const dl = $("#cm-download");
  if (dl) dl.addEventListener("click", () => {
    if (currentSvg) svgToPng(currentSvg, currentName + ".png");
  });
}

// Rasterize an inline SVG to a PNG download. Colors are already inlined at
// render time (computed from the CSS theme tokens), so the exported image
// matches the on-screen light/dark palette. A solid paper background is added
// so the PNG isn't transparent.
function svgToPng(svg, filename, scale = 2) {
  const vb = svg.viewBox && svg.viewBox.baseVal;
  const w = Math.round(vb && vb.width ? vb.width : (svg.clientWidth || 900));
  const h = Math.round(vb && vb.height ? vb.height : (svg.clientHeight || 140));
  const clone = svg.cloneNode(true);
  clone.setAttribute("width", w);
  clone.setAttribute("height", h);
  const css = getComputedStyle(document.documentElement);
  const bg = css.getPropertyValue("--paper-edge").trim() || "#ffffff";
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", 0); rect.setAttribute("y", 0);
  rect.setAttribute("width", w); rect.setAttribute("height", h);
  rect.setAttribute("fill", bg);
  clone.insertBefore(rect, clone.firstChild);
  const xml = new XMLSerializer().serializeToString(clone);
  const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = w * scale;
    canvas.height = h * scale;
    const ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  };
  img.src = svg64;
}

// =====================================================================
// 60-second guided tour
// =====================================================================
const TOUR = [
  { sel: "#provider", tab: "run", title: "Pick a provider", body: "Choose which model runs the golden dataset. This demo ships deterministic mock providers so results are free and reproducible \u2014 no API key." },
  { sel: "#metrics", tab: "run", title: "Choose your metrics", body: "Each metric scores an answer differently: exact match, similarity, an LLM judge, and a hallucination check. Toggle whichever you care about." },
  { sel: "#runBtn", tab: "run", title: "Run the evaluation", body: "Cases stream back one at a time. Watch the progress bar tally passes and fails live as the run completes." },
  { sel: "#resultsEmpty", tab: "results", title: "Read the results", body: "The bold metric is the one that gates a case's pass/fail. Click any row to see the input, model output, and expected answer \u2014 or re-run a single case." },
  { sel: "#comparePanel", tab: "compare", title: "Compare providers", body: "Run two providers over the same golden cases and see exactly where they diverge, case by case." },
  { sel: "#trend", tab: "history", title: "Track quality over time", body: "Every stored run feeds the trend chart. Drag any two runs into the diff slots to see exactly which cases flipped." },
];
let _tourIdx = 0;

const TOUR_SEEN_KEY = "llmqa.tourSeen";

function tourSeen() {
  try { return localStorage.getItem(TOUR_SEEN_KEY) === "1"; } catch { return false; }
}
function markTourSeen() {
  try { localStorage.setItem(TOUR_SEEN_KEY, "1"); } catch { /* private mode: no-op */ }
}

function initTour() {
  const btn = $("#tourBtn");
  if (btn) btn.addEventListener("click", () => startTour());
  const next = $("#tour-next"), prev = $("#tour-prev"), skip = $("#tour-skip");
  if (next) next.addEventListener("click", () => stepTour(1));
  if (prev) prev.addEventListener("click", () => stepTour(-1));
  if (skip) skip.addEventListener("click", endTour);
  window.addEventListener("scroll", onTourReflow, { passive: true });
  window.addEventListener("resize", onTourReflow);
  window.addEventListener("keydown", (e) => {
    if ($("#tour").hidden) return;
    if (e.key === "Escape") endTour();
    else if (e.key === "ArrowRight") stepTour(1);
    else if (e.key === "ArrowLeft") stepTour(-1);
  });
  // First-time visitors get the tour offered once, automatically. After they
  // finish or skip it we set a flag so it never auto-opens again (it stays
  // available on demand via the tour button).
  // Auto-open once for first-time visitors, but not when they deep-linked to a
  // specific tab or run (they came for that, not the tour).
  const deepLinked = !!(window.location.hash || new URLSearchParams(window.location.search).get("run"));
  if (!tourSeen() && !deepLinked) setTimeout(() => { if (!tourSeen()) startTour(); }, 900);
}

function startTour() {
  _tourIdx = 0;
  $("#tour").hidden = false;
  showTourStep();
}

function stepTour(dir) {
  const nextIdx = _tourIdx + dir;
  if (nextIdx < 0) return;
  if (nextIdx >= TOUR.length) { endTour(); return; }
  _tourIdx = nextIdx;
  showTourStep();
}

function showTourStep() {
  const step = TOUR[_tourIdx];
  if (step.tab) switchTab(step.tab);
  const target = document.querySelector(step.sel);
  $("#tour-step").textContent = `Step ${_tourIdx + 1} of ${TOUR.length}`;
  $("#tour-title").textContent = step.title;
  $("#tour-body").textContent = step.body;
  $("#tour-prev").disabled = _tourIdx === 0;
  $("#tour-next").textContent = _tourIdx === TOUR.length - 1 ? "Done" : "Next";
  const tip = $("#tip");
  if (target && tip) {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    // Position after the smooth scroll settles so the ring lands correctly.
    setTimeout(() => positionTour(target), 200);
  } else if (tip) {
    tip.hidden = true;
  }
}

// Place the spotlight ring over the target and move the bubble to whichever
// half of the viewport the target is NOT in, so on small screens the bubble
// never covers the control it's describing.
function positionTour(target) {
  const tip = $("#tip");
  const bubble = document.querySelector(".tour-bubble");
  if (!target || !tip) return;
  const rect = target.getBoundingClientRect();
  tip.hidden = false;
  tip.style.top = (window.scrollY + rect.top - 6) + "px";
  tip.style.left = (window.scrollX + rect.left - 6) + "px";
  tip.style.width = rect.width + 12 + "px";
  tip.style.height = rect.height + 12 + "px";
  if (bubble) {
    // If the target sits in the lower half of the viewport, dock the bubble to
    // the top; otherwise keep it at the bottom.
    const targetMid = rect.top + rect.height / 2;
    bubble.classList.toggle("bubble-top", targetMid > window.innerHeight * 0.55);
  }
}

// Keep the ring/bubble aligned if the user scrolls or rotates the device
// mid-tour (common on mobile).
function currentTourTarget() {
  const step = TOUR[_tourIdx];
  return step ? document.querySelector(step.sel) : null;
}
let _tourReflow = null;
function onTourReflow() {
  if ($("#tour").hidden) return;
  if (_tourReflow) cancelAnimationFrame(_tourReflow);
  _tourReflow = requestAnimationFrame(() => positionTour(currentTourTarget()));
}

function endTour() {
  $("#tour").hidden = true;
  const tip = $("#tip");
  if (tip) tip.hidden = true;
  markTourSeen();
}

init().catch((e) => { $("#status").textContent = "Init error: " + e.message; });
