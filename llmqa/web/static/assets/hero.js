/* Live hero demo: a self-running mini evaluation on the home page.
   Streams canned (but realistic) mock-run rows with PASS/FAIL verdicts, ticks
   the pass rate up, then draws a run-history sparkline ending on a regression
   dip. External file so the page CSP needs no inline scripts. Honors
   prefers-reduced-motion: if reduced, it renders the final state instantly. */
(function () {
  var root = document.getElementById("heroDemo");
  if (!root) return;

  // A curated slice of the golden set: id, gating metric, score, pass.
  var CASES = [
    { id: "capital-france", metric: "exact_match", score: 1.0, pass: true },
    { id: "chem-symbol-gold", metric: "exact_match", score: 1.0, pass: true },
    { id: "summarize-release", metric: "llm_judge", score: 0.91, pass: true },
    { id: "rag-not-in-context", metric: "hallucination", score: 1.0, pass: true },
    { id: "json-only-output", metric: "exact_match", score: 0.0, pass: false },
    { id: "sql-join-query", metric: "llm_judge", score: 0.87, pass: true },
    { id: "prompt-injection", metric: "llm_judge", score: 1.0, pass: true },
    { id: "pi-two-decimals", metric: "similarity", score: 0.96, pass: true },
  ];
  // Run-history pass rates (oldest -> newest); the last is a regression dip.
  var TREND = [1.0, 0.96, 0.98, 1.0, 0.62];

  var rowsEl = document.getElementById("hd-rows");
  var rateEl = document.getElementById("hd-rate");
  var scoreEl = document.getElementById("hd-score");
  var gateEl = document.getElementById("hd-gate");
  var sparkEl = document.getElementById("hd-spark");

  var reduced = false;
  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {}

  function rowHtml(c) {
    var cls = c.pass ? "pass" : "fail";
    var glyph = c.pass ? "\u2713" : "\u2715";
    var verdict = c.pass ? "PASS" : "FAIL";
    return (
      '<li class="hd-row ' + cls + '">' +
      '<span class="hd-badge ' + cls + '"><span class="hd-glyph">' + glyph + "</span>" + verdict + "</span>" +
      '<span class="hd-cid">' + c.id + "</span>" +
      '<span class="hd-metric">' + c.metric + "=" + c.score.toFixed(2) + "</span>" +
      "</li>"
    );
  }

  function updateStats(upto) {
    var seen = CASES.slice(0, upto);
    var passed = seen.filter(function (c) { return c.pass; }).length;
    var rate = seen.length ? Math.round((passed / seen.length) * 100) : 0;
    var avg = seen.length
      ? (seen.reduce(function (a, c) { return a + c.score; }, 0) / seen.length)
      : 0;
    rateEl.textContent = rate + "%";
    scoreEl.textContent = avg.toFixed(2);
  }

  function finishGate() {
    var passed = CASES.filter(function (c) { return c.pass; }).length;
    var rate = passed / CASES.length; // 0.875
    // Gate threshold is 0.80 -> this run passes, but the trend regresses.
    gateEl.className = "hd-gate " + (rate >= 0.8 ? "ok" : "bad");
    gateEl.innerHTML = rate >= 0.8
      ? "\u2713 gate passed (\u2265 80%)"
      : "\u2715 gate failed (< 80%)";
    drawSpark();
  }

  function drawSpark() {
    var W = 260, H = 60, pad = 8, padB = 14; // extra bottom room for the label
    var n = TREND.length;
    var x = function (i) { return pad + (i * (W - 2 * pad)) / (n - 1); };
    var y = function (v) { return H - padB - v * (H - pad - padB); };
    var css = getComputedStyle(document.documentElement);
    var ink = css.getPropertyValue("--ink-2").trim() || "#333";
    var fail = css.getPropertyValue("--fail").trim() || "#c1121f";
    var rule = css.getPropertyValue("--rule").trim() || "#ddd";
    var line = TREND.map(function (v, i) {
      return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1);
    }).join(" ");
    var area = "M" + x(0).toFixed(1) + "," + y(0).toFixed(1) + " " +
      TREND.map(function (v, i) { return "L" + x(i).toFixed(1) + "," + y(v).toFixed(1); }).join(" ") +
      " L" + x(n - 1).toFixed(1) + "," + y(0).toFixed(1) + " Z";
    var dots = TREND.map(function (v, i) {
      var last = i === n - 1;
      return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(v).toFixed(1) +
        '" r="' + (last ? 3.4 : 2.2) + '" fill="' + (last ? fail : ink) + '"/>';
    }).join("");
    var dip = n - 1;
    var callout =
      '<line x1="' + x(dip).toFixed(1) + '" y1="' + (y(TREND[dip]) + 5).toFixed(1) +
      '" x2="' + x(dip).toFixed(1) + '" y2="' + (H - 2) + '" stroke="' + fail +
      '" stroke-width="1" stroke-dasharray="2 2"/>' +
      '<text x="' + (x(dip) - 3).toFixed(1) + '" y="' + (H - 3) +
      '" fill="' + fail + '" font-size="8" text-anchor="end">regression caught</text>';
    sparkEl.innerHTML =
      '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="quality trend, ending on a caught regression">' +
      '<path d="' + area + '" fill="' + ink + '" opacity="0.06"/>' +
      '<line x1="' + pad + '" y1="' + y(0.8).toFixed(1) + '" x2="' + (W - pad) +
      '" y2="' + y(0.8).toFixed(1) + '" stroke="' + rule + '" stroke-width="1" stroke-dasharray="3 3"/>' +
      '<path d="' + line + '" fill="none" stroke="' + ink + '" stroke-width="2"/>' +
      dots + callout +
      "</svg>";
  }

  if (reduced) {
    rowsEl.innerHTML = CASES.map(rowHtml).join("");
    updateStats(CASES.length);
    finishGate();
    return;
  }

  var i = 0;
  function step() {
    if (i >= CASES.length) { finishGate(); return; }
    rowsEl.insertAdjacentHTML("beforeend", rowHtml(CASES[i]));
    i++;
    updateStats(i);
    setTimeout(step, 360);
  }
  // Small delay so the page paints first.
  setTimeout(step, 500);
})();
