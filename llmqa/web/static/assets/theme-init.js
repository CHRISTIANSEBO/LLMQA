/* Set the theme before paint to avoid a flash of the wrong palette.
   Loaded synchronously in <head> so it runs before first paint. Only an
   explicit stored choice is applied here; otherwise CSS follows the OS via
   prefers-color-scheme. Externalized (not inline) so the page CSP doesn't need
   script-src 'unsafe-inline'. */
(function () {
  try {
    var t = localStorage.getItem("llmqa-theme");
    if (t === "light" || t === "dark")
      document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();
