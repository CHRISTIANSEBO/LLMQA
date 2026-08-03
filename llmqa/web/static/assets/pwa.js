/* LLMQA PWA install helper.
 *
 * - Registers the service worker (required for installability).
 * - Exposes a discoverable "Install app" control in the masthead nav
 *   (#pwaInstallNav) plus a first-visit floating nudge, both of which open a
 *   single install POPUP.
 * - The popup adapts to the platform:
 *     * Chrome/Edge/Android: a live "Install" button backed by the captured
 *       `beforeinstallprompt` event.
 *     * iOS Safari (no such event): Share > Add to Home Screen steps.
 *     * Desktop without a captured prompt yet: the browser's address-bar
 *       install-icon / menu instructions (button enables itself once the
 *       prompt becomes available).
 * - Everything hides once the app is installed / running standalone.
 */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    });
  }

  const isStandalone = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  const ua = window.navigator.userAgent || "";
  const isIOS = /iphone|ipad|ipod/i.test(ua) ||
    (/(macintosh)/i.test(ua) && "ontouchend" in document); // iPadOS ~ Mac UA
  const isMobile = isIOS || /android/i.test(ua);
  const installVerb = isMobile ? "Add to Home Screen" : "Install app";

  let deferredPrompt = null;
  let popup = null;

  const NUDGE_KEY = "llmqa-…udged";
  const nudged = () => {
    try { return localStorage.getItem(NUDGE_KEY) === "1"; } catch { return false; }
  };
  const markNudged = () => {
    try { localStorage.setItem(NUDGE_KEY, "1"); } catch { /* private mode */ }
  };

  // ---- Build the popup once, lazily ------------------------------------
  function buildPopup() {
    if (popup) return popup;
    popup = document.createElement("div");
    popup.className = "pwa-modal";
    popup.hidden = true;
    popup.innerHTML =
      '<div class="pwa-modal-backdrop"></div>' +
      '<div class="pwa-modal-card" role="dialog" aria-modal="true" aria-labelledby="pwa-modal-title">' +
        '<button type="button" class="pwa-modal-x" aria-label="Close">\u2715</button>' +
        '<div class="pwa-modal-mark" aria-hidden="true">' +
          '<img class="brand-logo brand-logo--light" src="/assets/logo-light.svg" alt="" width="44" height="44" />' +
          '<img class="brand-logo brand-logo--dark" src="/assets/logo-dark.svg" alt="" width="44" height="44" />' +
        '</div>' +
        '<h3 id="pwa-modal-title">Install LLMQA</h3>' +
        '<p class="pwa-modal-lead">Add LLMQA to your ' +
          (isMobile ? "home screen" : "desktop") +
          ' for a full-screen, app-like experience \u2014 one tap to your evaluations, works offline for the shell.</p>' +
        '<div class="pwa-modal-body"></div>' +
        '<div class="pwa-modal-actions">' +
          '<button type="button" class="run pwa-do-install">' + installVerb + '</button>' +
          '<button type="button" class="link-btn pwa-modal-later">Maybe later</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(popup);

    const close = () => { popup.hidden = true; document.body.style.overflow = ""; };
    popup.querySelector(".pwa-modal-backdrop").addEventListener("click", close);
    popup.querySelector(".pwa-modal-x").addEventListener("click", close);
    popup.querySelector(".pwa-modal-later").addEventListener("click", () => { close(); markNudged(); });
    popup.querySelector(".pwa-do-install").addEventListener("click", doInstall);
    window.addEventListener("keydown", (e) => {
      if (!popup.hidden && e.key === "Escape") close();
    });
    return popup;
  }

  // Platform-specific guidance shown inside the popup body.
  function renderPopupBody() {
    const body = popup.querySelector(".pwa-modal-body");
    const doBtn = popup.querySelector(".pwa-do-install");
    if (isIOS) {
      doBtn.hidden = true;
      body.innerHTML =
        '<ol class="pwa-steps">' +
        '<li>Tap the <strong>Share</strong> button ' +
        '<span class="pwa-glyph" aria-hidden="true">\u2191\uFE0E</span> in the Safari toolbar.</li>' +
        '<li>Choose <strong>Add to Home Screen</strong> ' +
        '<span class="pwa-glyph" aria-hidden="true">\u2795</span>.</li>' +
        '<li>Tap <strong>Add</strong> \u2014 LLMQA opens full-screen like an app.</li>' +
        '</ol>';
    } else if (deferredPrompt) {
      doBtn.hidden = false;
      doBtn.disabled = false;
      body.innerHTML = '<p class="pwa-hint">Click <strong>' + installVerb +
        '</strong> and confirm in your browser\u2019s prompt.</p>';
    } else {
      // Chromium may not have fired the prompt yet (engagement heuristics),
      // or this is a browser without programmatic install. Rather than show a
      // dead/disabled CTA, hide it and give the manual path.
      doBtn.hidden = true;
      body.innerHTML = '<p class="pwa-hint">Look for the <strong>install icon</strong> ' +
        '<span class="pwa-glyph" aria-hidden="true">\u2913</span> in your browser\u2019s address bar, ' +
        'or open the browser menu and choose <strong>Install LLMQA</strong>.</p>';
    }
  }

  function openPopup() {
    buildPopup();
    renderPopupBody();
    popup.hidden = false;
    document.body.style.overflow = "hidden";
  }

  async function doInstall() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      try {
        const { outcome } = await deferredPrompt.userChoice;
        if (outcome === "accepted") { if (popup) popup.hidden = true; hideEntryPoints(); }
      } catch { /* ignore */ }
      deferredPrompt = null;
    }
  }

  // ---- Entry points: nav button + floating first-visit nudge -----------
  function navButtons() {
    return Array.prototype.slice.call(document.querySelectorAll("#pwaInstallNav"));
  }

  function showEntryPoints() {
    if (isStandalone()) return;
    navButtons().forEach((b) => { b.hidden = false; b.addEventListener("click", openPopup); });
    // First-visit floating nudge (once), mobile only — on desktop the nav
    // button is enough, so we avoid a redundant floating pill.
    if (isMobile && !nudged() && !document.getElementById("pwa-nudge")) {
      const nudge = document.createElement("button");
      nudge.id = "pwa-nudge";
      nudge.type = "button";
      nudge.className = "pwa-nudge";
      nudge.innerHTML = '<span class="pwa-nav-ic" aria-hidden="true">\u2913</span> ' + installVerb;
      nudge.setAttribute("aria-label", installVerb);
      nudge.addEventListener("click", () => { openPopup(); nudge.remove(); markNudged(); });
      document.body.appendChild(nudge);
    }
  }

  function hideEntryPoints() {
    navButtons().forEach((b) => { b.hidden = true; });
    const n = document.getElementById("pwa-nudge");
    if (n) n.remove();
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (popup && !popup.hidden) renderPopupBody(); // upgrade an open popup live
  });

  window.addEventListener("appinstalled", () => {
    if (popup) popup.hidden = true;
    hideEntryPoints();
    markNudged();
    deferredPrompt = null;
  });

  document.addEventListener("DOMContentLoaded", () => {
    if (isStandalone()) { hideEntryPoints(); return; }
    showEntryPoints();
  });
})();
