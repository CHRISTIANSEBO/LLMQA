// LLMQA dashboard — vanilla JS, no build step.
const $ = (sel) => document.querySelector(sel);
const api = (path, opts) => fetch(path, opts).then(async (r) => {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
});

let METRIC_ORDER = [];
let CASE_MAP = {}; // case_id → {input, expected, context}

async function init() {
  const cfg = await api("/api/config");
  METRIC_ORDER = cfg.metrics;
  (cfg.cases || []).forEach(c => { CASE_MAP[c.id] = c; });

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

  $("#runBtn").addEventListener("click", runEval);
  initCompare(cfg.all_providers);
  await loadHistory();
  await loadLatestRun();
}

// On first load, show the most recent stored run so the page isn't empty.
async function loadLatestRun() {
  try {
    const { runs } = await api("/api/history?limit=1");
    if (!runs.length) return;
    const full = await api(`/api/runs/${runs[0].id}`);
    if (full.detail) {
      const run = full.detail;
      // The stored detail lacks computed aggregates; take them from the summary.
      run.provider = full.provider;
      run.model = full.model;
      run.pass_rate = full.pass_rate;
      run.avg_score = full.avg_score;
      run.total_cost_usd = full.cost_usd;
      renderRun(run);
      $("#status").textContent = `Showing saved run #${full.id}`;
    }
  } catch (_) { /* non-fatal */ }
}

function selectedMetrics() {
  return [...document.querySelectorAll('#metrics input:checked')].map((i) => i.value);
}

async function runEval() {
  const btn = $("#runBtn");
  const status = $("#status");
  btn.disabled = true;

  // Reset UI for a fresh streaming run
  $("#summary").hidden = true;
  $("#resultsPanel").hidden = false;
  $("#results tbody").innerHTML = "";
  const tagFilterBar = document.getElementById("tagFilter");
  if (tagFilterBar) tagFilterBar.innerHTML = "";

  const tags = $("#tags").value.trim().split(/\s+/).filter(Boolean);
  const body = {
    provider: $("#provider").value,
    metrics: selectedMetrics(),
    tags: tags.length ? tags : null,
    store: $("#store").checked,
  };

  const streamedResults = [];
  let caseCount = 0;

  try {
    const resp = await fetch("/api/run/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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

        if (event.type === "case") {
          caseCount++;
          status.textContent = `Evaluating case ${caseCount}…`;
          streamedResults.push(event.result);
          appendCaseRow(event.result);
        } else if (event.type === "done") {
          $("#summary").hidden = false;
          const pct = Math.round(event.pass_rate * 100);
          $("#s-pass").textContent = `${pct}%`;
          $("#s-score").textContent = event.avg_score.toFixed(2);
          $("#s-model").textContent = `${event.provider}/${event.model}`;
          $("#s-cost").textContent = "$" + (event.total_cost_usd || 0).toFixed(4);
          status.textContent = `Done — ${caseCount} cases`;
          renderTagFilter(streamedResults);
          await loadHistory();
        }
      }
    }
  } catch (e) {
    status.textContent = "⚠ " + e.message;
  } finally {
    btn.disabled = false;
  }
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
  tr.title = "Click to expand";
  tr.innerHTML = `<td><strong class="expand-toggle">\u25b8 ${r.case_id}</strong></td>
    <td><span class="badge ${badge ? "pass" : "fail"}"><span class="glyph">${bGlyph}</span>${badge ? "PASS" : "FAIL"}</span></td>
    <td>${tagSpans}</td>
    <td class="latency">${ms}</td>
    <td><div class="mgrid">${metricCells}</div></td>`;
  tr.addEventListener("click", toggleDetail);
  return tr;
}

function appendCaseRow(r) {
  $("#results tbody").appendChild(buildResultRow(r));
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
  document.querySelectorAll("#results tbody tr").forEach(tr => {
    if (tr.classList.contains("detail-row")) return; // handled with parent
    const tags = (tr.dataset.tags ? JSON.parse(tr.dataset.tags) : []);
    const show = !_activeTagFilters.size || tags.some(t => _activeTagFilters.has(t));
    tr.hidden = !show;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("detail-row")) next.hidden = !show;
  });
}
// ------------------------------------------------------------------------

async function loadHistory() {
  const { runs } = await api("/api/history?limit=30");
  const tbody = $("#history tbody");
  tbody.innerHTML = "";
  runs.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.id}</td>
      <td>${(r.timestamp || "").replace("T", " ").replace("+00:00", "")}</td>
      <td>${r.provider}/${r.model}</td>
      <td>${Math.round(r.pass_rate * 100)}%</td>
      <td>${r.avg_score.toFixed(2)}</td>
      <td>$${(r.cost_usd || 0).toFixed(4)}</td>`;
    tbody.appendChild(tr);
  });
  renderTrend(runs);
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
  const gridY = [0, 0.5, 1].map((v) =>
    `<line x1="${padX}" y1="${y(v).toFixed(1)}" x2="${W - padX}" y2="${y(v).toFixed(1)}" stroke="${gridColor}" stroke-width="1"/>` +
    `<text x="2" y="${(y(v) + 3).toFixed(1)}" fill="${mutedColor}" font-size="9">${v}</text>`).join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="quality trend">
      ${gridY}
      <path d="${path("avg_score")}" fill="none" stroke="${inkColor2}" stroke-width="2" stroke-dasharray="5 4"/>
      <path d="${path("pass_rate")}" fill="none" stroke="${inkColor}" stroke-width="2.5"/>
      ${dots("avg_score", inkColor2)}${dots("pass_rate", inkColor)}
    </svg>
    <div style="font-size:12px;color:var(--muted);font-family:var(--mono)">
      ―― pass rate (solid) &nbsp;&nbsp; –– avg score (dashed) &nbsp; (oldest → newest, ${n} runs)
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
      body: JSON.stringify({ providers: [provA, provB] }),
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

  // Table
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
      <td><strong>${cid}</strong></td>
      <td>${badgeHtml(passA)} <span class="cmp-score">${scoreA.toFixed(2)}</span></td>
      <td>${badgeHtml(passB)} <span class="cmp-score">${scoreB.toFixed(2)}</span></td>
      <td class="cmp-delta ${delta > 0 ? 'pos' : delta < 0 ? 'neg' : 'neu'}">${delta >= 0 ? '+' : ''}${delta.toFixed(2)}</td>`;
    body.appendChild(tr);
  });

  document.getElementById("cmp-results").hidden = false;
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
  const ctx = c.has_context ? `<div class="detail-field"><span class="dl">Context</span><pre class="dv ctx">${esc(c.context || "—")}</pre></div>` : "";
  detail.innerHTML = `<td colspan="4" class="detail-cell">
    <div class="detail-grid">
      <div class="detail-field"><span class="dl">Input</span><pre class="dv">${esc(c.input || "—")}</pre></div>
      ${ctx}
      <div class="detail-field"><span class="dl">Model output</span><pre class="dv out">${esc(output || "—")}</pre></div>
      <div class="detail-field"><span class="dl">Expected</span><pre class="dv exp">${esc(c.expected || "—")}</pre></div>
    </div>
  </td>`;
  tr.after(detail);
  tr.classList.add("expanded");
  if (toggle) toggle.innerHTML = `\u25be ${caseId}`;
}

init().catch((e) => { $("#status").textContent = "Init error: " + e.message; });
