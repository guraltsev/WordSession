// #/now — the documents open in Word right now.
import { api } from "../api.js";
import { badge, errorBox, formatPosition, h, promptDialog, toast, toastError, withBusy } from "../dom.js";

export function mount(root) {
  const status = h("p", { role: "status" }, "Checking Word");
  const body = h("div", {});
  let alive = true;

  const saveButton = h("button", { type: "button", class: "primary" }, "Save as session…");
  saveButton.addEventListener("click", async () => {
    const name = await promptDialog("Save as session", "Session name (optional)", "Save");
    if (name === null) return;
    await withBusy(saveButton, async () => {
      try {
        const result = await api.capture(name);
        toast(result.saved ? `Saved "${result.session.name}".` : "Word has no open documents; nothing saved.");
        for (const warning of result.warnings) toast(warning);
      } catch (error) {
        toastError(error);
      }
    });
  });

  root.append(h("h2", {}, "Open now"), status, h("p", {}, saveButton), body);

  async function load() {
    // Word status first; it never starts Word.
    try {
      const info = await api.word();
      if (!alive) return;
      status.textContent = info.running
        ? `Word ${info.version} is running with ${info.document_count} open document(s).`
        : "Word is not running.";
    } catch (error) {
      if (alive) status.textContent = "Word status unavailable.";
      void error;
    }

    // Then the document list.
    try {
      const documents = await api.wordDocuments();
      if (!alive) return;
      body.replaceChildren(documents.length === 0 ? h("p", { class: "empty" }, "No documents are open.") : table(documents));
    } catch (error) {
      if (alive) body.replaceChildren(errorBox(error));
    }
  }

  function table(documents) {
    const head = h("tr", {}, ...["Document", "Location", "Position"].map((t) => h("th", { scope: "col" }, t)));
    const rows = documents.map((doc) =>
      h(
        "tr",
        {},
        h("td", { class: "path" }, doc.path, doc.active ? " " : "", doc.active ? badge("active") : ""),
        h("td", {}, badge(doc.location)),
        h("td", {}, formatPosition(doc.position)),
      ),
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
