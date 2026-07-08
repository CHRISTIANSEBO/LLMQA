// LLMQA dashboard — vanilla JS, no build step.
const $ = (sel) => document.querySelector(sel);
const api = (path, opts) => fetch(path, opts).then(async (r) => {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
});

let METRIC_ORDER = [];

async function init() {
  const cfg = await api("/api/config");
  METRIC_ORDER = cfg.metrics;

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
  status.textContent = "Running… (live providers can take a few seconds)";
  try {
    const tags = $("#tags").value.trim().split(/\s+/).filter(Boolean);
    const body = {
      provider: $("#provider").value,
      metrics: selectedMetrics(),
      tags: tags.length ? tags : null,
      store: $("#store").checked,
    };
    const run = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderRun(run);
    status.textContent = `Done in ${totalLatency(run)} ms`;
    await loadHistory();
  } catch (e) {
    status.textContent = "⚠ " + e.message;
  } finally {
    btn.disabled = false;
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

function scoreClass(score, isGate) {
  let cls = "mscore" + (isGate ? " gate" : "");
  if (score < 0.5) cls += " low";
  else if (score < 0.8) cls += " mid";
  return cls;
}

function renderRun(run) {
  $("#summary").hidden = false;
  $("#resultsPanel").hidden = false;
  const pct = Math.round(run.pass_rate * 100);
  $("#s-pass").textContent = `${pct}%`;
  $("#s-pass").style.color = pct >= 80 ? "var(--accent-2)" : pct >= 50 ? "var(--warn)" : "var(--fail)";
  $("#s-score").textContent = run.avg_score.toFixed(2);
  $("#s-model").textContent = `${run.provider}/${run.model}`;
  $("#s-cost").textContent = "$" + (run.total_cost_usd || 0).toFixed(4);

  const tbody = $("#results tbody");
  tbody.innerHTML = "";
  (run.results || []).forEach((r) => {
    const gate = new Set(r.gate_metrics || []);
    const metricCells = METRIC_ORDER.map((name) => {
      const m = (r.metrics || []).find((x) => x.metric === name);
      if (!m) return `<span class="mname">${name}: —</span>`;
      const isGate = gate.size === 0 || gate.has(name);
      return `<span class="${scoreClass(m.score, isGate)}" title="${name}${isGate ? " (gates pass/fail)" : " (informational)"}">${name}=${m.score.toFixed(2)}</span>`;
    }).join("  ");
    const tags = (r.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
    const badge = r.passed !== undefined ? r.passed : computePassed(r, gate);
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${r.case_id}</strong></td>
      <td><span class="badge ${badge ? "pass" : "fail"}">${badge ? "PASS" : "FAIL"}</span></td>
      <td>${tags}</td>
      <td>${metricCells}</td>`;
    tbody.appendChild(tr);
  });
}

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
  const gridY = [0, 0.5, 1].map((v) =>
    `<line x1="${padX}" y1="${y(v).toFixed(1)}" x2="${W - padX}" y2="${y(v).toFixed(1)}" stroke="#2a3340" stroke-width="1"/>` +
    `<text x="2" y="${(y(v) + 3).toFixed(1)}" fill="#8b949e" font-size="9">${v}</text>`).join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="quality trend">
      ${gridY}
      <path d="${path("avg_score")}" fill="none" stroke="#4f9cf9" stroke-width="2.5" stroke-dasharray="5 4"/>
      <path d="${path("pass_rate")}" fill="none" stroke="#3fb950" stroke-width="2.5"/>
      ${dots("avg_score", "#4f9cf9")}${dots("pass_rate", "#3fb950")}
    </svg>
    <div style="font-size:12px;color:var(--muted)">
      <span style="color:#3fb950">■</span> pass rate &nbsp;
      <span style="color:#4f9cf9">▬</span> avg score &nbsp; (oldest → newest, ${n} runs)
    </div>`;
}

init().catch((e) => { $("#status").textContent = "Init error: " + e.message; });
