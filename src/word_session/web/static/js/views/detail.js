// #/sessions/<id> — one session: rename, notes, documents, restore, delete.
import { api } from "../api.js";
import {
  badge,
  confirmDialog,
  errorBox,
  formatDate,
  formatPosition,
  h,
  labelled,
  toast,
  toastError,
  withBusy,
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
      h("h3", {}, "Documents"),
      documentsTable(session),
      actions(session),
    );
  }

  function titleRow(session) {
    if (nameEditing) {
      const { field, input } = labelled("Session name", h("input", { type: "text", value: session.name }));
      const save = h("button", { type: "button", class: "primary" }, "Save name");
      const cancel = h("button", { type: "button" }, "Cancel");
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
    const rename = h("button", { type: "button" }, "Rename");
    rename.addEventListener("click", () => {
      nameEditing = true;
      render();
    });
    const pin = h("button", { type: "button", "aria-pressed": String(session.pinned) }, session.pinned ? "Pinned" : "Pin");
    pin.addEventListener("click", () =>
      withBusy(pin, () => edit(() => patch({ pinned: !session.pinned }))),
    );
    return h(
      "div",
      { class: "title-row" },
      h("a", { href: "#/sessions" }, "Sessions"),
      h("h2", {}, session.name),
      badge(session.kind),
      rename,
      pin,
    );
  }

  function metaPanel(session) {
    return h(
      "div",
      { class: "panel" },
      h(
        "dl",
        { class: "meta" },
        h("dt", {}, "Id"),
        h("dd", {}, session.id),
        h("dt", {}, "Created"),
        h("dd", {}, formatDate(session.created_at)),
        h("dt", {}, "Host"),
        h("dd", {}, session.host),
        h("dt", {}, "Word version"),
        h("dd", {}, session.word_version || "unknown"),
      ),
    );
  }

  function notesPanel(session) {
    const area = h("textarea", { rows: "4" });
    area.value = notesDraft !== null ? notesDraft : session.notes;
    area.addEventListener("input", () => {
      notesDraft = area.value;
    });
    const { field } = labelled("Notes", area);
    const save = h("button", { type: "button" }, "Save notes");
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
    return h("div", { class: "panel" }, field, h("p", {}, save));
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
    const all = h("input", { type: "checkbox", "aria-label": "Select all documents" });
    all.checked = selected.size === session.documents.length;
    all.addEventListener("change", () => {
      selected = all.checked ? new Set(session.documents.map((d) => d.path)) : new Set();
      render();
    });
    const head = h(
      "tr",
      {},
      h("th", { scope: "col" }, all),
      ...["Document", "Location", "File", "Position"].map((text) => h("th", { scope: "col" }, text)),
    );
    const rows = session.documents.map((doc) => {
      const box = h("input", { type: "checkbox", "aria-label": `Select ${doc.path}` });
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
    const restoreButton = h("button", { type: "button", class: "primary", disabled: none }, "Restore selected");
    restoreButton.addEventListener("click", () => startRestore([...selected]));
    const removeButton = h("button", { type: "button", disabled: none }, "Remove selected from session");
    removeButton.addEventListener("click", async () => {
      const ok = await confirmDialog(
        "Remove documents",
        `Remove ${selected.size} selected document(s) from this session? The files themselves are not touched.`,
        "Remove",
      );
      if (!ok) return;
      const paths = [...selected];
      await edit(async () => {
        await patch({ remove_paths: paths });
        toast("Documents removed from the session.");
      });
    });
    const deleteButton = h("button", { type: "button", class: "danger" }, "Delete session");
    deleteButton.addEventListener("click", async () => {
      const ok = await confirmDialog(
        "Delete session",
        `Delete "${session.name}"? It is moved to the trash folder.`,
        "Delete",
      );
      if (!ok) return;
      await edit(async () => {
        await api.deleteSession(sessionId, current.revision);
        toast("Session deleted.");
        location.hash = "#/sessions";
      });
    });
    return h("div", { class: "actions" }, restoreButton, removeButton, deleteButton);
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
    const children = [h("h3", {}, "Restore")];
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
        h("progress", { max: total, value: done, "aria-label": "Restore progress" }),
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
