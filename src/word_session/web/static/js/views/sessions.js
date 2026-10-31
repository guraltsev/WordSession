// #/sessions — save the current session, search, filter and list sessions.
import { api } from "../api.js";
import { badge, errorBox, formatDate, h, labelled, toast, toastError, withBusy } from "../dom.js";

export function mount(root) {
  const state = { q: "", kind: null, pinned: false };
  const body = h("div", {});
  let alive = true;
  let loadId = 0;

  // ---- toolbar: save, search, filters ----
  const nameInput = h("input", { type: "text", autocomplete: "off" });
  const nameField = labelled("Session name (optional)", nameInput);
  const saveButton = h("button", { type: "button", class: "primary" }, "Save current session");
  saveButton.addEventListener("click", () =>
    withBusy(saveButton, async () => {
      try {
        const result = await api.capture(nameInput.value.trim());
        if (result.saved) {
          nameInput.value = "";
          const count = result.session.documents.length;
          toast(`Saved "${result.session.name}" (${count} documents)`);
          for (const warning of result.warnings) toast(warning);
        } else {
          toast("Word has no open documents; nothing saved.");
        }
        await load();
      } catch (error) {
        toastError(error);
      }
    }),
  );

  const searchInput = h("input", { type: "search", autocomplete: "off" });
  const searchField = labelled("Search", searchInput);
  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = searchInput.value.trim();
      load();
    }, 250);
  });

  const chips = [];
  function chip(label, isOn, toggle) {
    const button = h("button", { type: "button", class: "chip", "aria-pressed": "false" }, label);
    button.addEventListener("click", () => {
      toggle();
      for (const entry of chips) entry.button.setAttribute("aria-pressed", String(entry.isOn()));
      load();
    });
    chips.push({ button, isOn });
    return button;
  }
  const kindChip = (kind) =>
    chip(
      kind,
      () => state.kind === kind,
      () => {
        state.kind = state.kind === kind ? null : kind;
      },
    );
  const filters = h(
    "div",
    { class: "field" },
    h("span", { class: "field-label", id: "filters-label" }, "Filter"),
    h(
      "div",
      { role: "group", "aria-labelledby": "filters-label", class: "inline" },
      kindChip("manual"),
      kindChip("auto"),
      kindChip("imported"),
      chip(
        "pinned",
        () => state.pinned,
        () => {
          state.pinned = !state.pinned;
        },
      ),
    ),
  );

  root.append(
    h("h2", {}, "Sessions"),
    h(
      "div",
      { class: "toolbar" },
      nameField.field,
      saveButton,
      searchField.field,
      filters,
    ),
    body,
  );

  // ---- list ----
  async function load() {
    loadId += 1;
    const mine = loadId;
    let sessions;
    try {
      sessions = await api.listSessions(state);
    } catch (error) {
      if (alive && mine === loadId) body.replaceChildren(errorBox(error));
      return;
    }
    if (!alive || mine !== loadId) return;
    body.replaceChildren(sessions.length === 0 ? emptyMessage() : table(sessions));
  }

  const hasFilter = () => state.q || state.kind || state.pinned;
  const emptyMessage = () =>
    h(
      "p",
      { class: "empty" },
      hasFilter() ? "No sessions match the filters." : "No sessions yet. Save the current session to create one.",
    );

  function table(sessions) {
    const head = h(
      "tr",
      {},
      ...["Name", "Created", "Kind", "Documents", "Missing", "Pinned", "Restore"].map((text, i) =>
        h("th", { scope: "col", class: i === 3 || i === 4 ? "num" : "" }, text),
      ),
    );
    const rows = sessions.map(row);
    return h(
      "div",
      { class: "table-wrap" },
      h("table", {}, h("thead", {}, head), h("tbody", {}, ...rows)),
    );
  }

  function row(session) {
    const pin = h(
      "button",
      {
        type: "button",
        "aria-pressed": String(session.pinned),
        "aria-label": `Pin ${session.name}`,
      },
      session.pinned ? "Pinned" : "Pin",
    );
    pin.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePin(session, pin);
    });
    const restore = h("button", { type: "button", "aria-label": `Restore ${session.name}` }, "Restore");
    restore.addEventListener("click", (event) => {
      event.stopPropagation();
      location.hash = `#/sessions/${encodeURIComponent(session.id)}?restore=all`;
    });
    const tr = h(
      "tr",
      { class: "clickable" },
      h(
        "td",
        {},
        h("a", { href: `#/sessions/${encodeURIComponent(session.id)}` }, session.name),
      ),
      h("td", {}, formatDate(session.created_at)),
      h("td", {}, badge(session.kind)),
      h("td", { class: "num" }, session.document_count),
      h(
        "td",
        { class: session.missing_count > 0 ? "num missing" : "num" },
        session.missing_count,
      ),
      h("td", {}, pin),
      h("td", {}, restore),
    );
    tr.addEventListener("click", () => {
      location.hash = `#/sessions/${encodeURIComponent(session.id)}`;
    });
    return tr;
  }

  // Read the latest revision, then flip the pinned flag against it.
  async function togglePin(session, button) {
    await withBusy(button, async () => {
      try {
        const { revision } = await api.getSession(session.id);
        await api.patchSession(session.id, revision, { pinned: !session.pinned });
        await load();
      } catch (error) {
        toastError(error);
      }
    });
  }

  load();
  return {
    refresh: load,
    destroy() {
      alive = false;
      clearTimeout(searchTimer);
    },
  };
}
