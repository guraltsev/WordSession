// #/diagnostics — doctor checks, log tail and a copyable report.
import { api } from "../api.js";
import { badge, errorBox, h, toast } from "../dom.js";

export function mount(root) {
  const checksBox = h("div", {});
  const logBox = h("pre", { class: "log", tabindex: "0", "aria-label": "Log tail" });
  let alive = true;
  let checks = [];
  let lines = [];

  const copy = h("button", { type: "button", class: "primary" }, "Copy report");
  copy.addEventListener("click", async () => {
    const text = [
      "Word Session diagnostics",
      ...checks.map((c) => `${c.status.toUpperCase().padEnd(4)} ${c.name}: ${c.detail}`),
      "",
      "Last log lines",
      ...lines,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast("Report copied to the clipboard.");
    } catch {
      toast("Could not copy; select the log text and copy it manually.", "error");
    }
  });

  root.append(h("h2", {}, "Diagnostics"), h("p", {}, copy), checksBox, h("h3", {}, "Log"), logBox);

  async function load() {
    // Checks and log are independent; show whichever succeeds.
    const [checkResult, logResult] = await Promise.allSettled([api.doctor(), api.logs(200)]);
    if (!alive) return;
    if (checkResult.status === "fulfilled") {
      checks = checkResult.value;
      checksBox.replaceChildren(table(checks));
    } else {
      checksBox.replaceChildren(errorBox(checkResult.reason));
    }
    if (logResult.status === "fulfilled") {
      lines = logResult.value;
      logBox.textContent = lines.length ? lines.join("\n") : "(the log is empty)";
    } else {
      logBox.textContent = "(the log could not be read)";
    }
  }

  function table(items) {
    if (items.length === 0) return h("p", { class: "empty" }, "No checks available.");
    const kinds = { ok: "badge-ok", warn: "badge-warn", fail: "badge-fail" };
    const head = h("tr", {}, ...["Status", "Check", "Detail"].map((t) => h("th", { scope: "col" }, t)));
    const rows = items.map((c) =>
      h("tr", {}, h("td", {}, badge(c.status, kinds[c.status] || "")), h("td", {}, c.name), h("td", { class: "path" }, c.detail)),
    );
    return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, ...rows)));
  }

  load();
  return {
    refresh: load,
    destroy() {
      alive = false;
    },
  };
}
