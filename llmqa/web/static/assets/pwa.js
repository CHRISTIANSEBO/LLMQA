/* LLMQA PWA install helper.
 *
 * - Registers the service worker (required for installability).
 * - Shows an "Install app" (desktop) / "Add to Home Screen" (mobile) pill:
 *     * Chrome/Edge/Android: uses the captured `beforeinstallprompt` event.
 *     * iOS Safari (no such event): shows Share > Add to Home Screen steps.
 * - Hides itself once the app is installed / running standalone.
 */
(function () {
  "use strict";

  // Register the service worker (root scope so it controls the whole site).
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    });
  }

  const isStandalone = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  if (isStandalone()) return; // already installed — nothing to offer

  const ua = window.navigator.userAgent || "";
  const isIOS = /iphone|ipad|ipod/i.test(ua) ||
    (/(macintosh)/i.test(ua) && "ontouchend" in document); // iPadOS masquerades as Mac
  const isMobile = isIOS || /android/i.test(ua);

  let deferredPrompt = null;

  // ---- UI: a small ink-on-paper install pill + iOS instruction sheet ----
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pwa-install";
  btn.hidden = true;
  btn.innerHTML =
    '<span class="pwa-ic" aria-hidden="true">\u2913</span>' +
    '<span class="pwa-tx">' +
    (isMobile ? "Add to Home Screen" : "Install app") +
    "</span>";
  btn.setAttribute(
    "aria-label",
    isMobile ? "Add LLMQA to your home screen" : "Install the LLMQA app"
  );

  const dismissBtn = document.createElement("button");
  dismissBtn.type = "button";
  dismissBtn.className = "pwa-dismiss";
  dismissBtn.setAttribute("aria-label", "Dismiss install prompt");
  dismissBtn.textContent = "\u2715";

  const wrap = document.createElement("div");
  wrap.className = "pwa-wrap";
  wrap.hidden = true;
  wrap.appendChild(btn);
  wrap.appendChild(dismissBtn);

  const DISMISS_KEY = "llmqa-pwa-dismissed";
  const dismissed = () => {
    try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; }
  };
  const markDismissed = () => {
    try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* private mode */ }
  };

  function show() {
    if (dismissed()) return;
    wrap.hidden = false;
    btn.hidden = false;
  }
  function hide() {
    wrap.hidden = true;
  }

  dismissBtn.addEventListener("click", () => {
    hide();
    markDismissed();
  });

  // ---- iOS instruction sheet (Safari can't trigger the native prompt) ----
  function showIosSheet() {
    let sheet = document.getElementById("pwa-ios");
    if (sheet) { sheet.hidden = false; return; }
    sheet = document.createElement("div");
    sheet.id = "pwa-ios";
    sheet.className = "pwa-ios";
    sheet.innerHTML =
      '<div class="pwa-ios-backdrop"></div>' +
      '<div class="pwa-ios-card" role="dialog" aria-modal="true" aria-label="Add to Home Screen">' +
      '<h3>Add LLMQA to your Home Screen</h3>' +
      '<ol>' +
      '<li>Tap the <strong>Share</strong> button ' +
      '<span class="pwa-ios-glyph" aria-hidden="true">\u2191\uFE0E</span> in the Safari toolbar.</li>' +
      '<li>Scroll and choose <strong>Add to Home Screen</strong> ' +
      '<span class="pwa-ios-glyph" aria-hidden="true">\u2795</span>.</li>' +
      '<li>Tap <strong>Add</strong>. LLMQA opens full-screen like an app.</li>' +
      '</ol>' +
      '<button type="button" class="mini-btn pwa-ios-close">Got it</button>' +
      '</div>';
    document.body.appendChild(sheet);
    const close = () => { sheet.hidden = true; };
    sheet.querySelector(".pwa-ios-backdrop").addEventListener("click", close);
    sheet.querySelector(".pwa-ios-close").addEventListener("click", close);
  }

  btn.addEventListener("click", async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      try {
        const { outcome } = await deferredPrompt.userChoice;
        if (outcome === "accepted") { hide(); markDismissed(); }
      } catch { /* ignore */ }
      deferredPrompt = null;
      return;
    }
    if (isIOS) { showIosSheet(); return; }
    // No prompt available and not iOS: nothing we can do — hide quietly.
    hide();
  });

  // Chromium fires this when the app meets installability criteria.
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    show();
  });

  window.addEventListener("appinstalled", () => {
    hide();
    markDismissed();
    deferredPrompt = null;
  });

  // iOS never fires beforeinstallprompt, so offer the manual path directly.
  if (isIOS) {
    window.addEventListener("load", () => setTimeout(show, 1200));
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.body.appendChild(wrap);
  });
})();
