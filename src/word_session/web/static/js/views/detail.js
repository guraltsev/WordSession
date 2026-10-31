// #/sessions/<id> — one session: rename, notes, documents, restore, delete.
import { api } from "../api.js";
import {
  badge,
  confirmDialog,
  errorBox,
  formatDate,
  formatPosition,
  h,
  helpHeading,
  labelled,
  toast,
  toastError,
  withBusy,
  withHelp,
} from "../dom.js";

// Make a path match itself literally when used as a glob pattern.
function globEscape(path) {
  return path.replace(/[*?[]/g, (ch) => `[${ch}]`);
}

function statusBadge(status) {
  const good = status === "opened" || status === "already_open";
  const bad = status === "missing" || status === "locked" || status === "failed";
  return badge(status, good ? "badge-ok" : bad ? "badge-fail" : "");
}

export function mount(root, params) {
  const sessionId = params.id;
  const main = h("div", {});
  const progressPanel = h("div", {});
  root.append(main, progressPanel);

  let alive = true;
  let current = null; // {session, revision}
  let selected = null; // Set of document paths ticked for restore/remove
  let nameEditing = false;
  let notesDraft = null; // unsaved text typed into the notes box
  let restore = null; // progress of the restore started from this view
  let fallbackTimer = null;
  let known = new Set(); // document paths seen on the previous load

  // ---- loading ----
  async function load() {
    try {
      current = await api.getSession(sessionId);
    } catch (error) {
      if (!alive) return;
      if (error.status === 404) {
        main.replaceChildren(
          errorBox(error),
          h("p", {}, h("a", { href: "#/sessions" }, "Back to sessions")),
        );
      } else {
        main.replaceChildren(errorBox(error));
      }
      return;
    }
    if (!alive) return;

    // Keep the user's ticks across reloads; new documents start ticked.
    const paths = current.session.documents.map((d) => d.path);
    selected =
      selected === null ? new Set(paths) : new Set(paths.filter((p) => selected.has(p) || !known.has(p)));
    known = new Set(paths);
    render();
  }

  // Run an edit; on a stale revision reload and tell the user.
  async function edit(action) {
    try {
      await action();
    } catch (error) {
      if (error.status === 412) {
        notesDraft = null;
        toast("This session was changed in another tab; showing the latest version.");
        await load();
      } else {
        toastError(error);
      }
    }
  }

  async function patch(changes) {
    const result = await api.patchSession(sessionId, current.revision, changes);
    current = result;
    await load();
  }

  // ---- rendering ----
  function render() {
    const { session } = current;
    main.replaceChildren(
      titleRow(session),
      metaPanel(session),
      notesPanel(session),
      helpHeading(
        "h3",
        "Documents",
        "documents",
        "Documents",
        "The documents stored in this session. Tick the ones you want to act on, then use Restore selected or Remove selected from session below. " +
          "Nothing here changes the files on disk.",
      ),
      documentsTable(session),
      actions(session),
    );
  }

  function titleRow(session) {
    if (nameEditing) {
      const { field, input } = labelled("Session name", h("input", { type: "text", value: session.name }));
      const save = h("button", { type: "button", class: "primary", title: "Saves the new name for this session and leaves the editing mode. You can also press Enter in the name box. The documents inside the session are not affected." }, "Save name");
      const cancel = h("button", { type: "button", title: "Leaves the editing mode without changing anything; the session keeps its old name. You can also press Esc in the name box." }, "Cancel");
      cancel.addEventListener("click", () => {
        nameEditing = false;
        render();
      });
      save.addEventListener("click", () =>
        withBusy(save, () =>
          edit(async () => {
            nameEditing = false;
            await patch({ name: input.value.trim() });
          }),
        ),
      );
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") save.click();
        if (event.key === "Escape") cancel.click();
      });
      queueMicrotask(() => input.focus());
      return h("div", { class: "title-row" }, field, save, cancel);
    }
    const rename = h("button", { type: "button", title: "Lets you type a new name for this session. The name only helps you recognise the session; it does not change any file. Press Enter to keep the new name." }, "Rename");
    rename.addEventListener("click", () => {
      nameEditing = true;
      render();
    });
    const pin = h(
      "button",
      {
        type: "button",
        "aria-pressed": String(session.pinned),
        title: session.pinned
          ? "This session is pinned, so automatic clean-up never removes it. Click to unpin it; it can then be removed like any other automatic session."
          : "Protects this session from automatic clean-up, which otherwise removes old autosaved sessions. Click again later to unpin it.",
      },
      session.pinned ? "Pinned" : "Pin",
    );
    pin.addEventListener("click", () =>
      withBusy(pin, () => edit(() => patch({ pinned: !session.pinned }))),
    );
    return h(
      "div",
      { class: "title-row" },
      h("a", { href: "#/sessions", title: "Goes back to the list of all saved sessions. Nothing is changed by leaving this page. Unsaved text in the notes box is kept while you stay on this session." }, "Sessions"),
      h("h2", {}, session.name),
      withHelp(
        h(
          "span",
          {
            title:
              "How this session was created: manual means you saved it yourself, auto means autosave saved it in the background. " +
              "Only auto sessions are removed by automatic clean-up, and pinning protects even those.",
          },
          badge(session.kind),
        ),
        "kinds",
        "session kinds",
      ),
      withHelp(rename, "rename", "renaming"),
      withHelp(pin, "detail-pin", "pinning"),
    );
  }

  function metaPanel(session) {
    return h(
      "div",
      { class: "panel" },
      helpHeading(
        "h3",
        "Details",
        "session-info",
        "session details",
        "Facts recorded when the session was saved: its unique id, the time, the computer and the Word version. " +
          "They are read-only and help you tell sessions apart or find the session file on disk.",
      ),
      h(
        "dl",
        { class: "meta" },
        h("dt", { title: "The unique identifier of this session. It is also the name of the session file, and you can use it on the command line." }, "Id"),
        h("dd", {}, session.id),
        h("dt", { title: "The date and time at which the session was saved, shown in your local time. It does not change when you rename the session." }, "Created"),
        h("dd", {}, formatDate(session.created_at)),
        h("dt", { title: "The name of the computer the session was saved on. This matters if you share a sessions folder between computers, because paths may differ." }, "Host"),
        h("dd", {}, session.host),
        h("dt", { title: "The version of Word that was running when the session was saved. It is only for your information and does not affect restoring." }, "Word version"),
        h("dd", {}, session.word_version || "unknown"),
      ),
    );
  }

  function notesPanel(session) {
    const area = h("textarea", {
      rows: "4",
      title:
        "Free text stored together with this session, for example what you were working on. " +
        "It is only saved when you press Save notes. Notes never affect restoring.",
    });
    area.value = notesDraft !== null ? notesDraft : session.notes;
    area.addEventListener("input", () => {
      notesDraft = area.value;
    });
    const { field } = labelled("Notes", area);
    const save = h("button", { type: "button", title: "Stores the text of the notes box in this session, replacing the earlier notes. Until you press it, the text only exists in this browser page. Notes can be changed again at any time." }, "Save notes");
    save.addEventListener("click", () =>
      withBusy(save, () =>
        edit(async () => {
          const text = area.value;
          notesDraft = null;
          await patch({ notes: text });
          toast("Notes saved.");
        }),
      ),
    );
    return h("div", { class: "panel" }, field, h("p", {}, withHelp(save, "notes", "notes")));
  }

  function locationBadge(doc) {
    return badge(doc.location);
  }

  function existsCell(doc) {
    if (doc.exists === true) return badge("exists", "badge-ok");
    if (doc.exists === false) return badge("missing", "badge-warn");
    return h("span", { class: "hint" }, "n/a");
  }

  function documentsTable(session) {
    if (session.documents.length === 0) {
      return h("p", { class: "empty" }, "This session has no documents.");
    }
    const all = h("input", { type: "checkbox", "aria-label": "Select all documents", title: "Ticks or clears the box of every document in the list at once. The ticked documents are used by Restore selected and Remove selected from session. Nothing happens until you press one of those buttons." });
    all.checked = selected.size === session.documents.length;
    all.addEventListener("change", () => {
      selected = all.checked ? new Set(session.documents.map((d) => d.path)) : new Set();
      render();
    });
    const columnTips = {
      Document: "The full path of the saved document. The one marked active was the document in front when the session was saved.",
      Location:
        "Where the file is stored: on a local disk, on a network share, or in a cloud folder. " +
        "Network and cloud files can be slow to open or unavailable when you are offline.",
      File:
        "Whether the file still exists at its saved path right now. Missing means it was moved, renamed or deleted, " +
        "and restoring will report it instead of opening it.",
      Position:
        "The page and line of the cursor when the session was saved. Restoring puts the cursor back there " +
        "when Restore cursor positions is on in Settings.",
    };
    const head = h(
      "tr",
      {},
      h("th", { scope: "col", title: "Tick boxes to choose documents for the buttons below. The box here selects or clears all of them." }, all),
      ...["Document", "Location", "File", "Position"].map((text) =>
        h("th", { scope: "col", title: columnTips[text] }, text),
      ),
    );
    const rows = session.documents.map((doc) => {
      const box = h("input", {
        type: "checkbox",
        "aria-label": `Select ${doc.path}`,
        title: "Ticks this document so that Restore selected reopens it, or Remove selected from session drops it from the session. The file on disk is never touched by ticking. Untick it to leave it out.",
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
        h("td", {}, locationBadge(doc)),
        h("td", {}, existsCell(doc)),
        h("td", {}, formatPosition(doc.position)),
      );
    });
    return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, ...rows)));
  }

  function actions(session) {
    const none = selected.size === 0;
    const restoreButton = h(
      "button",
      {
        type: "button",
        class: "primary",
        disabled: none,
        title: none
          ? "Tick at least one document in the table first. Then this button reopens exactly those documents in Word. The others are left alone."
          : "Reopens the ticked documents in Word and puts the cursor back where it was. Documents that are already open are not opened twice. A report shows which ones succeeded.",
      },
      "Restore selected",
    );
    restoreButton.addEventListener("click", () => startRestore([...selected]));
    const removeButton = h(
      "button",
      {
        type: "button",
        disabled: none,
        title: none
          ? "Tick at least one document in the table first. Then this button removes exactly those documents from the session."
          : "Removes the ticked documents from this session's list after asking you to confirm. The files on disk are not touched or deleted. This cannot be undone, but you can save a new session again.",
      },
      "Remove selected from session",
    );
    removeButton.addEventListener("click", async () => {
      const ok = await confirmDialog(
        "Remove documents",
        `Remove ${selected.size} selected document(s) from this session? The files themselves are not touched.`,
        "Remove",
        "Remove the documents from the session",
      );
      if (!ok) return;
      const paths = [...selected];
      await edit(async () => {
        await patch({ remove_paths: paths });
        toast("Documents removed from the session.");
      });
    });
    const deleteButton = h(
      "button",
      {
        type: "button",
        class: "danger",
        title:
          "Moves this whole session to the trash folder after asking you to confirm. Your documents are not touched. " +
          "Because the session file is only moved, it can still be recovered by hand from the trash folder.",
      },
      "Delete session",
    );
    deleteButton.addEventListener("click", async () => {
      const ok = await confirmDialog(
        "Delete session",
        `Delete "${session.name}"? It is moved to the trash folder.`,
        "Delete",
        "Move the session to the trash folder",
      );
      if (!ok) return;
      await edit(async () => {
        await api.deleteSession(sessionId, current.revision);
        toast("Session deleted.");
        location.hash = "#/sessions";
      });
    });
    return h(
      "div",
      { class: "actions" },
      withHelp(restoreButton, "restore-selected", "restoring selected documents"),
      withHelp(removeButton, "remove-documents", "removing documents"),
      withHelp(deleteButton, "delete-session", "deleting a session"),
    );
  }

  // ---- restore with progress ----
  async function startRestore(paths) {
    const total = paths ? paths.length : current.session.documents.length;
    restore = { jobId: null, total, results: [], report: null, error: null, started: false };
    renderProgress();
    try {
      const body = paths === null ? {} : { only: paths.map(globEscape) };
      restore.jobId = await api.restore(sessionId, body);
    } catch (error) {
      restore = null;
      renderProgress();
      toastError(error);
      return;
    }
    // Events normally report everything; check the job once now, and once more
    // shortly after in case it failed before publishing any event.
    await checkJob();
    fallbackTimer = setTimeout(() => {
      if (restore && !restore.started && !restore.report && !restore.error) checkJob();
    }, 1500);
  }

  async function checkJob() {
    if (!restore || !restore.jobId) return;
    try {
      const job = await api.job(restore.jobId);
      if (!restore || !alive) return;
      if (job.state === "failed") restore.error = job.error;
      if (job.state === "done" && job.report) restore.report = job.report;
      if (job.results.length > restore.results.length) restore.results = job.results;
      renderProgress();
    } catch (error) {
      void error;
    }
  }

  function onEvent(event) {
    if (!restore || event.session_id !== sessionId) return;
    if (event.type === "restore_started") {
      restore.started = true;
      restore.total = event.total;
    } else if (event.type === "restore_progress") {
      restore.started = true;
      restore.total = event.total;
      restore.results[event.index] = event.result;
    } else if (event.type === "restore_finished") {
      restore.report = event.report;
    } else {
      return;
    }
    renderProgress();
  }

  function renderProgress() {
    if (!restore) {
      progressPanel.replaceChildren();
      return;
    }
    const children = [helpHeading(
        "h3",
        "Restore",
        "restore-progress",
        "restore results",
        "Shows how reopening the documents is going and the result for each one: opened, already open, missing, locked or failed. " +
          "Closing this page does not stop the restore. Problems are listed with a short reason.",
      )];
    const done = restore.results.filter(Boolean).length;
    if (restore.error) {
      children.push(
        h("div", { class: "error-box", role: "alert" }, `Restore failed: ${restore.error.message}`),
      );
    } else if (restore.report) {
      const ok = restore.report.results.every((r) => !["missing", "locked", "failed"].includes(r.status));
      children.push(
        h(
          "p",
          { role: "status" },
          ok ? "Restore finished." : "Restore finished with problems.",
        ),
      );
    } else {
      const total = restore.total || 1;
      children.push(
        h("progress", { max: total, value: done, "aria-label": "Restore progress", title: "How many documents have been handled so far out of the total. Each document is opened one after another in Word." }),
        h("p", { role: "status" }, `Restoring: ${done} of ${restore.total || "?"} documents`),
      );
    }
    const results = restore.report ? restore.report.results : restore.results.filter(Boolean);
    if (results.length > 0) {
      const rows = results.map((r) =>
        h("tr", {}, h("td", {}, statusBadge(r.status)), h("td", { class: "path" }, r.path), h("td", {}, r.message || "")),
      );
      children.push(
        h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            {},
            h("thead", {}, h("tr", {}, ...["Status", "Document", "Message"].map((t) => h("th", { scope: "col" }, t)))),
            h("tbody", {}, ...rows),
          ),
        ),
      );
    }
    progressPanel.replaceChildren(h("div", { class: "panel" }, ...children));
  }

  // Auto-start from the list's "Restore" button.
  load().then(() => {
    if (params.query.get("restore") === "all" && current) {
      history.replaceState(null, "", `#/sessions/${encodeURIComponent(sessionId)}`);
      startRestore(null);
    }
  });

  return {
    refresh: load,
    onEvent,
    destroy() {
      alive = false;
      clearTimeout(fallbackTimer);
    },
  };
}
