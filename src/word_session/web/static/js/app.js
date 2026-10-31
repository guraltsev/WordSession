// Entry point: hash routing, the live event stream, Word status and the
// global "not signed in" / "not running" states.
import { ApiError, api, configure, streamEvents } from "./api.js";
import { h } from "./dom.js";
import * as detail from "./views/detail.js";
import * as diagnostics from "./views/diagnostics.js";
import * as now from "./views/now.js";
import * as sessions from "./views/sessions.js";
import * as settings from "./views/settings.js";

const app = document.getElementById("app");
const banner = document.getElementById("banner");
const wordDot = document.getElementById("word-dot");
const wordText = document.getElementById("word-status-text");
const streamAbort = new AbortController();

let current = null; // the mounted view: {refresh, onEvent, destroy}
let signedOut = false;
let offline = false;
let wordTimer = null;

// ---- routing ----

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { parts, query: new URLSearchParams(query || "") };
}

function route() {
  if (signedOut) return;
  const { parts, query } = parseHash();
  if (current) current.destroy();
  app.replaceChildren();

  let name = parts[0] || "sessions";
  if (name === "sessions" && parts[1]) {
    current = detail.mount(app, { id: parts[1], query });
    name = "sessions";
  } else if (name === "now") {
    current = now.mount(app, {});
  } else if (name === "settings") {
    current = settings.mount(app, {});
  } else if (name === "diagnostics") {
    current = diagnostics.mount(app, {});
  } else {
    name = "sessions";
    current = sessions.mount(app, {});
  }

  // Mark the active navigation link for keyboard and screen-reader users.
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

window.addEventListener("hashchange", route);

// ---- global states ----

function showSignedOut() {
  if (signedOut) return;
  signedOut = true;
  streamAbort.abort();
  clearInterval(wordTimer);
  if (current) current.destroy();
  current = null;
  banner.hidden = true;
  app.replaceChildren(
    h(
      "div",
      { class: "signed-out", role: "alert" },
      h("h2", {}, "Not signed in"),
      h(
        "p",
        {},
        "Not signed in. Open the manager from the tray icon or run ",
        h("code", {}, "word-session open"),
        ".",
      ),
    ),
  );
}

function setOffline(value) {
  offline = value;
  banner.hidden = !value || signedOut;
  if (value) setWordStatus(null);
}

// After the stream is back, confirm the server answers and we are still signed in.
async function recover() {
  try {
    await api.health();
    await api.word();
  } catch (error) {
    // 401 already switched to the signed-out page; a network error keeps the banner.
    if (!(error instanceof ApiError) || error.status === 0) return;
  }
  if (signedOut) return;
  setOffline(false);
  if (current) current.refresh();
}

configure({ onUnauthorized: showSignedOut, onNetworkError: () => setOffline(true) });

// ---- Word status ----

function setWordStatus(info) {
  wordDot.className = "dot";
  if (info === null) {
    wordText.textContent = "Word: unknown";
  } else if (info.running) {
    wordDot.classList.add("dot-ok");
    wordText.textContent = `Word ${info.version} running`;
  } else {
    wordDot.classList.add("dot-off");
    wordText.textContent = "Word not running";
  }
}

async function pollWord() {
  if (signedOut || document.visibilityState !== "visible") return;
  try {
    setWordStatus(await api.word());
  } catch {
    setWordStatus(null);
  }
}

document.addEventListener("visibilitychange", pollWord);

// ---- live events ----

let refreshTimer = null;

function onEvent(event) {
  if (!current) return;
  // Restore progress goes straight to the view that started the restore.
  if (current.onEvent) current.onEvent(event);
  if (["session_saved", "session_updated", "session_deleted"].includes(event.type)) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => current && current.refresh(), 300);
  }
}

function onStreamState(state) {
  if (state === "error") {
    setOffline(true);
  } else if (offline) {
    recover();
  }
}

// ---- start ----

route();
pollWord();
wordTimer = setInterval(pollWord, 10000);
streamEvents({ onEvent, onState: onStreamState, signal: streamAbort.signal });
