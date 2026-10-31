// #/now — the documents open in Word right now: tick some, save them as a
// session, close them.
import { api } from "../api.js";
import {
  badge,
  confirmDialog,
  errorBox,
  formatPosition,
  h,
  helpHeading,
  promptDialog,
  toast,
  toastError,
  withBusy,
  withHelp,
} from "../dom.js";

const TICK_FIRST = "Tick at least one document in the table first. ";

export function mount(root) {
  const status = h(
    "p",
    {
      role: "status",
      title:
        "Tells you whether Word is running, its version and how many documents it has open. " +
        "Checking never starts Word. The text refreshes when Word opens or closes a document.",
    },
    "Checking Word",
  );
  const body = h("div", {});
  let alive = true;
  let documents = [];
  // Ticked paths; kept after saving so the same documents can be closed next.
  let selected = new Set();

  const saveButton = h(
    "button",
    { type: "button", class: "primary" },
    "Save selected as session…",
  );
  const closeButton = h("button", { type: "button", class: "danger" }, "Close now");

  function updateButtons() {
    const none = selected.size === 0;
    saveButton.disabled = none;
    closeButton.disabled = none;
    saveButton.title = none
      ? `${TICK_FIRST}Then this button saves exactly the ticked documents as a new manual session and asks for a name.`
      : "Saves the ticked documents as a new manual session and asks you for a name first. " +
        "The cursor position of each document is stored too. The ticks stay in place afterwards, so you can close the same documents with Close now.";
    closeButton.title = none
      ? `${TICK_FIRST}Then this button closes exactly those documents in Word.`
      : "Closes the ticked documents in Word without saving them, after asking you to confirm. " +
        "Documents with unsaved changes are left open and reported. Save a session first if you want to reopen these documents later.";
  }

  saveButton.addEventListener("click", async () => {
    const name = await promptDialog(
      "Save selected as session",
      "Session name (optional)",
      "Save",
      "Save the ticked documents as a new session",
    );
    if (name === null) return;
    await withBusy(saveButton, async () => {
      try {
        const result = await api.capture(name, [...selected]);
        toast(result.saved ? `Saved "${result.session.name}".` : "None of the ticked documents are open; nothing saved.");
        for (const warning of result.warnings) toast(warning);
      } catch (error) {
        toastError(error);
      }
    });
  });

  closeButton.addEventListener("click", async () => {
    const paths = [...selected];
    const ok = await confirmDialog(
      "Close documents",
      `Close ${paths.length} document(s) in Word without saving? Documents with unsaved changes stay open.`,
      "Close now",
      "Close the ticked documents in Word",
    );
    if (!ok) return;
    await withBusy(closeButton, async () => {
      try {
        const results = await api.closeDocuments(paths);
        const closed = results.filter((r) => r.status === "closed").length;
        toast(`Closed ${closed} of ${results.length} document(s).`);
        for (const r of results) {
          if (r.status !== "closed") toast(`${r.path}: ${r.message || "was not open"}`, "error");
        }
      } catch (error) {
        toastError(error);
      }
      await load();
    });
  });

  root.append(
    helpHeading(
      "h2",
      "Open now",
      "open-now",
      "Open now page",
      "Shows the documents that are open in Word at this moment. " +
        "Tick some of them to save just those as a session, or to close them in Word. " +
        "The list refreshes by itself when Word changes.",
    ),
    status,
    h(
      "p",
      { class: "actions" },
      withHelp(saveButton, "save-session", "saving a session"),
      withHelp(closeButton, "close-now", "closing documents"),
    ),
    body,
  );
  updateButtons();

  async function load() {
    // Word status first; it never starts Word.
    try {
      const info = await api.word();
      if (!alive) return;
      status.textContent = info.running
        ? `Word ${info.version || ""} is running with ${info.document_count ?? documents.length} open document(s).`.replace("  ", " ")
        : "Word is not running.";
    } catch (error) {
      if (alive) status.textContent = "Word status unavailable.";
      void error;
    }

    // Then the document list; forget ticks of documents that are gone.
    try {
      documents = await api.wordDocuments();
      if (!alive) return;
      const open = new Set(documents.map((d) => d.path));
      selected = new Set([...selected].filter((p) => open.has(p)));
      render();
    } catch (error) {
      documents = [];
      selected = new Set();
      updateButtons();
      if (alive) body.replaceChildren(errorBox(error));
    }
  }

  function render() {
    updateButtons();
    body.replaceChildren(documents.length === 0 ? h("p", { class: "empty" }, "No documents are open.") : table());
  }

  function table() {
    const tips = {
      Document: "The full path of the document in Word. The one marked active is the document you are currently working in.",
      Location:
        "Where the file is stored: on a local disk, on a network share, or in a cloud folder such as OneDrive or SharePoint. " +
        "Network and cloud files may be slow to reopen.",
      Position:
        "The page and line where the cursor is in that document. A session stores this so that restoring can put the cursor back. " +
        "It is empty when Word cannot report a position.",
    };
    const all = h("input", {
      type: "checkbox",
      "aria-label": "Select all documents",
      title: "Ticks or clears every document in the list at once. The ticked documents are used by the two buttons above the table.",
    });
    all.checked = selected.size === documents.length;
    all.addEventListener("change", () => {
      selected = all.checked ? new Set(documents.map((d) => d.path)) : new Set();
      render();
    });
    const head = h(
      "tr",
      {},
      h("th", { scope: "col", title: "Tick documents to save them as a session or to close them." }, all),
      ...["Document", "Location", "Position"].map((t) => h("th", { scope: "col", title: tips[t] }, t)),
    );
    const rows = documents.map((doc) => {
      const box = h("input", {
        type: "checkbox",
        "aria-label": `Select ${doc.path}`,
        title:
          "Ticks this document for Save selected as session and Close now. " +
          "Ticking changes nothing in Word by itself. Untick it to leave it out.",
      });
      box.checked = selected.has(doc.path);
      box.addEventListener("change", () => {
        if (box.checked) selected.add(doc.path);
        else selected.delete(doc.path);
        render();
      });
      return h(
        "tr",
        {},
        h("td", {}, box),
        h("td", { class: "path" }, doc.path, doc.active ? " " : "", doc.active ? badge("active") : ""),
        h("td", {}, badge(doc.location)),
        h("td", {}, formatPosition(doc.position)),
      );
    });
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
