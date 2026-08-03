/* Light/dark theme toggle, shared by every page.
 *
 * A tiny inline snippet in each page's <head> sets data-theme before paint (so
 * there's no flash). This wires the masthead toggle button: it flips the theme,
 * persists an explicit choice, and keeps the glyph/labels in sync. When the
 * user has NOT made an explicit choice, the page follows the OS preference and
 * updates live if the OS theme changes.
 */
(function () {
  var KEY = "llmqa-theme";
  var root = document.documentElement;
  var mq = window.matchMedia("(prefers-color-scheme: dark)");

  function stored() {
    try {
      var t = localStorage.getItem(KEY);
      return t === "light" || t === "dark" ? t : null;
    } catch (e) {
      return null;
    }
  }

  function current() {
    var explicit = stored();
    if (explicit) return explicit;
    var attr = root.getAttribute("data-theme");
    if (attr === "light" || attr === "dark") return attr;
    return mq.matches ? "dark" : "light";
  }

  function apply(theme, btn) {
    root.setAttribute("data-theme", theme);
    if (!btn) return;
    var dark = theme === "dark";
    btn.setAttribute("aria-pressed", String(dark));
    btn.setAttribute(
      "aria-label",
      dark ? "Switch to light theme" : "Switch to dark theme"
    );
    btn.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
    var glyph = btn.querySelector(".tt-glyph");
    if (glyph) glyph.textContent = dark ? "\u263E" : "\u2600"; // moon / sun
  }

  function init() {
    var btn = document.getElementById("theme-toggle");
    apply(current(), btn);
    if (btn) {
      btn.addEventListener("click", function () {
        var next = current() === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(KEY, next);
        } catch (e) {}
        apply(next, btn);
      });
    }
    // Follow OS changes only while the user hasn't chosen explicitly.
    var onChange = function () {
      if (!stored()) apply(mq.matches ? "dark" : "light", btn);
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  /* Mobile masthead menu: the hamburger toggles the nav dropdown. Closes on
   * link click, Escape, or an outside click so it behaves like a native menu. */
  function initMenu() {
    var btn = document.getElementById("nav-toggle");
    var nav = document.getElementById("topnav");
    if (!btn || !nav) return;

    function setOpen(open) {
      nav.classList.toggle("is-open", open);
      btn.setAttribute("aria-expanded", String(open));
      btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setOpen(btn.getAttribute("aria-expanded") !== "true");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.closest("a")) setOpen(false);
    });
    document.addEventListener("click", function (e) {
      if (
        btn.getAttribute("aria-expanded") === "true" &&
        !nav.contains(e.target) &&
        !btn.contains(e.target)
      )
        setOpen(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && btn.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        btn.focus();
      }
    });
  }

  function boot() {
    init();
    initMenu();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
