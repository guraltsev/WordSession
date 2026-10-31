// #/sessions — save the current session, search, filter and list sessions.
import { api } from "../api.js";
import {
  addFieldHelp,
  badge,
  errorBox,
  formatDate,
  h,
  helpHeading,
  helpLink,
  labelled,
  toast,
  toastError,
  withBusy,
  withHelp,
} from "../dom.js";

const KIND_TIPS = {
  manual:
    "Show only sessions you saved yourself with Save current session. Manual sessions are never removed by automatic clean-up. " +
    "Click again to show all sessions.",
  auto:
    "Show only sessions that autosave created in the background. Only the newest ones are kept, according to the Settings page, " +
    "unless you pin them. Click again to show all sessions.",
};

export function mount(root) {
  const state = { q: "", kind: null, pinned: false };
  const body = h("div", {});
  let alive = true;
  let loadId = 0;

  // ---- toolbar: save, search, filters ----
  const nameInput = h("input", {
    type: "text",
    autocomplete: "off",
    title:
      "The name given to the session you are about to save. If you leave it empty, the session is named after the current date and time. " +
      "You can rename any session later from its detail page.",
  });
  const nameField = labelled("Session name (optional)", nameInput);
  const saveButton = h(
    "button",
    {
      type: "button",
      class: "primary",
      title:
        "Records every document that is open in Word right now, together with where the cursor is in each one. " +
        "The result appears in the list below as a manual session. Nothing in Word is changed or closed.",
    },
    "Save current session",
  );
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

  const searchInput = h("input", {
    type: "search",
    autocomplete: "off",
    title:
      "Type part of a session name, id or document path to narrow the list. Capital letters do not matter. " +
      "The list updates a moment after you stop typing; clear the box to see every session.",
  });
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
  function chip(label, tip, isOn, toggle) {
    const button = h("button", { type: "button", class: "chip", "aria-pressed": "false", title: tip }, label);
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
      KIND_TIPS[kind],
      () => state.kind === kind,
      () => {
        state.kind = state.kind === kind ? null : kind;
      },
    );
  const filters = h(
    "div",
    { class: "field" },
    h(
      "span",
      { class: "with-help" },
      h(
        "span",
        {
          class: "field-label",
          id: "filters-label",
          title:
            "Narrow the list by how a session was created or whether it is pinned. Click a button to turn that filter on, click it again to turn it off. " +
            "Several filters can be on at once and all of them must match.",
        },
        "Filter",
      ),
      helpLink("filters", "filters"),
    ),
    h(
      "div",
      { role: "group", "aria-labelledby": "filters-label", class: "inline" },
      kindChip("manual"),
      kindChip("auto"),
      chip(
        "pinned",
        "Show only sessions you pinned. Pinned sessions are protected from automatic clean-up, so they stay until you delete them. " +
          "Click again to show all sessions.",
        () => state.pinned,
        () => {
          state.pinned = !state.pinned;
        },
      ),
    ),
  );

  root.append(
    helpHeading(
      "h2",
      "Sessions",
      "sessions-page",
      "Sessions page",
      "A session is a saved list of the documents that were open in Word, with the cursor position of each. " +
        "On this page you can save the current state, find older sessions, pin the ones you want to keep and reopen them in Word. " +
        "Click a session name to see its documents and notes.",
    ),
    h(
      "div",
      { class: "toolbar" },
      nameField.field,
      withHelp(saveButton, "save-session", "saving a session"),
      addFieldHelp(searchField.field, "search", "search"),
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
    // Columns whose header carries a "?" link: [help anchor, topic].
    const columnTips = {
      Name: "The session's name. Click it to open the detail page with its documents, notes and restore options.",
      Created: "When the session was saved, in your local time. The list is sorted with the newest session first.",
      Kind:
        "How the session came to be: manual means you saved it, auto means autosave saved it in the background. " +
        "Only auto sessions are removed by automatic clean-up.",
      Documents: "How many documents the session contains. Restoring the session tries to reopen all of them.",
      Missing:
        "How many of the session's documents no longer exist at their saved location, for example because they were moved or deleted. " +
        "Restoring reports these instead of opening them.",
      Pinned:
        "Pinned sessions are protected from automatic clean-up of old autosaves. " +
        "Use the button in the row to pin or unpin the session.",
      Restore:
        "Reopens every document of the session in Word and moves the cursor back to its saved position. " +
        "Documents that are already open are not opened twice.",
    };
    const columnHelp = {
      Kind: ["kinds", "session kinds"],
      Missing: ["session-list", "missing documents"],
      Pinned: ["pin", "pinning"],
      Restore: ["restore-button", "restoring a session"],
    };
    const head = h(
      "tr",
      {},
      ...["Name", "Created", "Kind", "Documents", "Missing", "Pinned", "Restore"].map((text, i) =>
        h(
          "th",
          { scope: "col", class: i === 3 || i === 4 ? "num" : "", title: columnTips[text] },
          columnHelp[text] ? withHelp(text, ...columnHelp[text]) : text,
        ),
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
        title: session.pinned
          ? "This session is pinned, so automatic clean-up never removes it. Click to unpin it; it can then be removed like any other automatic session."
          : "Protects this session from automatic clean-up, which otherwise removes old autosaved sessions. Click again later to unpin it.",
      },
      session.pinned ? "Pinned" : "Pin",
    );
    pin.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePin(session, pin);
    });
    const restore = h(
      "button",
      {
        type: "button",
        "aria-label": `Restore ${session.name}`,
        title:
          "Reopens every document of this session in Word and puts the cursor back where it was. " +
          "Word is started first if the settings allow it. A report shows which documents could not be opened.",
      },
      "Restore",
    );
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
