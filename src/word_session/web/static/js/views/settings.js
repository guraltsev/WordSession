// #/settings — edit the application settings and import old sessions.
import { api } from "../api.js";
import { errorBox, h, labelled, toast, toastError, withBusy } from "../dom.js";

export function mount(root) {
  const holder = h("div", {});
  const importResult = h("p", { role: "status", class: "hint" });
  let alive = true;

  const importButton = h("button", { type: "button" }, "Import sessions from old tools");
  importButton.addEventListener("click", () =>
    withBusy(importButton, async () => {
      try {
        const summary = await api.importLegacy();
        importResult.textContent =
          `Imported ${summary.imported.length} session(s), skipped ${summary.skipped.length}, ` +
          `${summary.errors.length} error(s).`;
      } catch (error) {
        toastError(error);
      }
    }),
  );

  root.append(
    h("h2", {}, "Settings"),
    holder,
    h("h3", {}, "Old tools"),
    h("p", {}, importButton),
    importResult,
  );

  async function load() {
    let settings;
    try {
      settings = await api.getSettings();
    } catch (error) {
      if (alive) holder.replaceChildren(errorBox(error));
      return;
    }
    if (alive) holder.replaceChildren(form(settings));
  }

  function checkbox(text, value) {
    const input = h("input", { type: "checkbox" });
    input.checked = value;
    const { field } = labelled(text, input);
    field.className = "inline";
    // Show the box before its label for checkboxes.
    field.prepend(input);
    return { field, input };
  }

  function number(text, value, attrs) {
    const input = h("input", { type: "number", ...attrs });
    input.value = String(value);
    return labelled(text, input);
  }

  function form(settings) {
    const enabled = checkbox("Autosave enabled", settings.autosave.enabled);
    const interval = number("Autosave interval (minutes)", settings.autosave.interval_minutes, { min: "1", max: "1440", step: "1" });
    const keep = number("Automatic sessions to keep", settings.autosave.keep, { min: "0", max: "10000", step: "1" });
    const onlyChange = checkbox("Autosave only when something changed", settings.autosave.only_on_change);
    const startWord = checkbox("Start Word when restoring", settings.restore.start_word);
    const position = checkbox("Restore cursor positions", settings.restore.restore_position);
    const timeout = number("Open timeout (seconds)", settings.restore.open_timeout_s, { min: "1", max: "3600", step: "1" });
    const dirInput = h("input", { type: "text", autocomplete: "off" });
    dirInput.value = settings.sessions_dir || "";
    const dir = labelled("Sessions folder (empty for the default)", dirInput);
    const login = checkbox("Start at login", settings.ui.start_at_login);

    const save = h("button", { type: "submit", class: "primary" }, "Save settings");
    const element = h(
      "form",
      {},
      h("fieldset", {}, h("legend", {}, "Autosave"), h("div", { class: "form-grid" }, enabled.field, interval.field, keep.field, onlyChange.field)),
      h("fieldset", {}, h("legend", {}, "Restore"), h("div", { class: "form-grid" }, startWord.field, position.field, timeout.field)),
      h("fieldset", {}, h("legend", {}, "General"), h("div", { class: "form-grid" }, dir.field, login.field)),
      save,
    );
    element.addEventListener("submit", (event) => {
      event.preventDefault();
      const updated = {
        sessions_dir: dirInput.value.trim() || null,
        autosave: {
          enabled: enabled.input.checked,
          interval_minutes: Number(interval.input.value),
          keep: Number(keep.input.value),
          only_on_change: onlyChange.input.checked,
        },
        restore: {
          start_word: startWord.input.checked,
          restore_position: position.input.checked,
          open_timeout_s: Number(timeout.input.value),
        },
        ui: { start_at_login: login.input.checked },
      };
      withBusy(save, async () => {
        try {
          await api.putSettings(updated);
          toast("Settings saved.");
        } catch (error) {
          toastError(error);
        }
      });
    });
    return element;
  }

  load();
  return {
    refresh() {},
    destroy() {
      alive = false;
    },
  };
}
