// #/diagnostics — doctor checks, log tail and a copyable report.
import { api } from "../api.js";
import { badge, errorBox, h, helpHeading, toast, withHelp } from "../dom.js";

export function mount(root) {
  const checksBox = h("div", {});
  const logBox = h("pre", { class: "log", tabindex: "0", "aria-label": "Log tail",
    title:
      "The newest lines of the Word Session log file, oldest first. The log records what the program did and any errors. " +
      "Select text here to copy part of it.",
  });
  let alive = true;
  let checks = [];
  let lines = [];

  const copy = h(
    "button",
    {
      type: "button",
      class: "primary",
      title:
        "Copies the results of all checks and the most recent log lines to the clipboard as plain text. " +
        "Paste it into an e-mail or a message when you ask for help. It contains file paths but no document contents.",
    },
    "Copy report",
  );
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

  root.append(
    helpHeading(
      "h2",
      "Diagnostics",
      "diagnostics",
      "Diagnostics page",
      "Runs a set of checks on Python, Word, your folders and your settings, and shows the end of the log. " +
        "Use it when saving or restoring does not work. Each check says ok, warn or fail with a short explanation.",
    ),
    h("p", {}, withHelp(copy, "copy-report", "copying the report")),
    checksBox,
    helpHeading(
      "h3",
      "Log",
      "log",
      "Log",
      "The log is a text file in which Word Session notes what it does and what goes wrong. " +
        "The last 200 lines are shown here. The same file is useful when reporting a problem.",
    ),
    logBox,
  );

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
    const tips = {
      Status: "ok means the check passed, warn means something may cause trouble, fail means a feature will not work until it is fixed.",
      Check: "The name of the thing that was tested, for example Python, Word or the sessions folder.",
      Detail: "What the check found, such as a version number, a folder path or the reason it failed.",
    };
    const head = h(
      "tr",
      {},
      ...["Status", "Check", "Detail"].map((t) => h("th", { scope: "col", title: tips[t] }, t)),
    );
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
