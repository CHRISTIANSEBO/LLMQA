/* Warm the cache for the dashboard's critical resources so it opens fast from
   the home page. Fire-and-forget on idle; failures are harmless. Externalized
   (not inline) so the page CSP doesn't need script-src 'unsafe-inline'. */
(function () {
  var warm = function () {
    try {
      fetch("/api/config", { headers: { "X-Prefetch": "1" } }).catch(function () {});
      ["/assets/app.js", "/dashboard"].forEach(function (href) {
        var l = document.createElement("link");
        l.rel = "prefetch";
        l.href = href;
        document.head.appendChild(l);
      });
    } catch (e) {}
  };
  if ("requestIdleCallback" in window) requestIdleCallback(warm, { timeout: 2000 });
  else setTimeout(warm, 1200);
})();
