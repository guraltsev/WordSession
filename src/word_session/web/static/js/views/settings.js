// #/settings — edit the application settings and manage the Start menu shortcut.
import { api } from "../api.js";
import { errorBox, h, helpHeading, labelled, toast, toastError, withBusy, withHelp } from "../dom.js";

export function mount(root) {
  const holder = h("div", {});
  let alive = true;

  // ---- Start menu shortcut (per user) ----
  const shortcutBox = h("div", {});

  function renderShortcut(state) {
    if (!state.supported) {
      shortcutBox.replaceChildren(h("p", { class: "hint" }, "Start menu shortcuts are only available on Windows."));
      return;
    }
    const status = h(
      "p",
      { role: "status" },
      state.exists ? "Word Session is in your Start menu: " : "Word Session is not in your Start menu yet. It will be created at ",
      h("code", {}, state.path),
    );
    const create = h(
      "button",
      {
        type: "button",
        class: state.exists ? "" : "primary",
        title: state.exists
          ? "Writes the Start menu shortcut again. Use this if the shortcut stopped working, for example after you moved or reinstalled Word Session. " +
            "Your sessions and settings are not affected."
          : "Adds Word Session to your own Start menu so you can find it by typing its name. " +
            "The shortcut is only for your account and needs no administrator rights. You can remove it again here at any time.",
      },
      state.exists ? "Recreate Start menu shortcut" : "Create Start menu shortcut",
    );
    create.addEventListener("click", () =>
      withBusy(create, async () => {
        try {
          renderShortcut(await api.createShortcut());
          toast("Start menu shortcut created.");
        } catch (error) {
          toastError(error);
        }
      }),
    );
    const buttons = [withHelp(create, "start-menu", "Start menu shortcut")];
    if (state.exists) {
      const remove = h(
        "button",
        {
          type: "button",
          title:
            "Takes Word Session out of your Start menu. The program, your sessions and your settings stay exactly as they are. " +
            "You can create the shortcut again at any time.",
        },
        "Remove Start menu shortcut",
      );
      remove.addEventListener("click", () =>
        withBusy(remove, async () => {
          try {
            renderShortcut(await api.removeShortcut());
            toast("Start menu shortcut removed.");
          } catch (error) {
            toastError(error);
          }
        }),
      );
      buttons.push(remove);
    }
    shortcutBox.replaceChildren(status, h("div", { class: "actions" }, ...buttons));
  }

  async function loadShortcut() {
    try {
      const state = await api.shortcut();
      if (alive) renderShortcut(state);
    } catch (error) {
      if (alive) shortcutBox.replaceChildren(errorBox(error));
    }
  }

  root.append(
    helpHeading(
      "h2",
      "Settings",
      "settings",
      "Settings page",
      "Controls how Word Session saves and restores your documents and how it starts. " +
        "Changes take effect as soon as you press Save settings. They are stored in your own user profile and affect only you.",
    ),
    holder,
    helpHeading(
      "h3",
      "Start menu",
      "start-menu",
      "Start menu shortcut",
      "Adds Word Session to your Windows Start menu so you can open it like any other program. " +
        "The shortcut belongs to your account only and needs no administrator rights. Removing it does not delete any sessions.",
    ),
    shortcutBox,
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

  function checkbox(text, value, tip) {
    const input = h("input", { type: "checkbox", title: tip });
    input.checked = value;
    const { field } = labelled(text, input);
    field.className = "inline";
    // Show the box before its label for checkboxes.
    field.prepend(input);
    return { field, input };
  }

  function number(text, value, attrs, tip) {
    const input = h("input", { type: "number", ...attrs, title: tip });
    input.value = String(value);
    return labelled(text, input);
  }

  function form(settings) {
    const enabled = checkbox(
      "Autosave enabled",
      settings.autosave.enabled,
      "Lets Word Session save the documents open in Word by itself, at the interval below, without you doing anything. " +
        "Automatic sessions are marked auto in the session list. Turn this off if you only want sessions you save yourself.",
    );
    const interval = number(
      "Autosave interval (minutes)",
      settings.autosave.interval_minutes,
      { min: "1", max: "1440", step: "1" },
      "How many minutes pass between two autosave checks, from 1 to 1440 (one day). " +
        "A short interval gives a more recent session after a crash but creates more sessions. " +
        "Old automatic sessions are removed according to the next setting.",
    );
    const keep = number(
      "Automatic sessions to keep",
      settings.autosave.keep,
      { min: "0", max: "10000", step: "1" },
      "How many automatic sessions to keep; 0 removes them all after each autosave. " +
        "Older ones are moved to the trash folder, so they can still be recovered by hand. " +
        "Pinned sessions and sessions you saved manually are never removed.",
    );
    const onlyChange = checkbox(
      "Autosave only when something changed",
      settings.autosave.only_on_change,
      "Skips an autosave when the same documents are open with the cursors in the same places as in the previous autosave. " +
        "This stops the list from filling up with identical sessions while you are away. " +
        "Turn it off if you want a session at every interval no matter what.",
    );
    const startWord = checkbox(
      "Start Word when restoring",
      settings.restore.start_word,
      "If Word is not running when you restore a session, Word Session starts it first. " +
        "When this is off, restoring fails with a message and Word stays closed. " +
        "Documents are then opened in the new Word window.",
    );
    const position = checkbox(
      "Restore cursor positions",
      settings.restore.restore_position,
      "After a document is reopened, the cursor is moved to the place it had when the session was saved. " +
        "If the document has changed since then, the closest page and line are used. " +
        "Turn this off to leave every document at its start.",
    );
    const timeout = number(
      "Open timeout (seconds)",
      settings.restore.open_timeout_s,
      { min: "1", max: "3600", step: "1" },
      "How many seconds to wait for Word to open one document, from 1 to 3600. " +
        "If Word takes longer, for example because it shows a dialog, that document is reported as failed and the next one is tried. " +
        "Raise the value for very large files or slow network drives.",
    );
    const dirInput = h("input", {
      type: "text",
      autocomplete: "off",
      title: "The folder where session files are stored. Leave it empty to use the default folder in your user profile. " +
        "Existing sessions are not moved when you change it, so copy them over yourself if you want to keep them listed.",
    });
    dirInput.value = settings.sessions_dir || "";
    const dir = labelled("Sessions folder (empty for the default)", dirInput);
    const login = checkbox(
      "Start at login",
      settings.ui.start_at_login,
      "Starts Word Session in the background whenever you sign in to Windows, so autosave works without you opening it. " +
        "It appears as an icon in the system tray. Turn this off if you prefer to start it yourself.",
    );

    const legend = (text, anchor, tip) =>
      h("legend", { title: tip }, withHelp(text, anchor, `${text} settings`));
    const save = h(
      "button",
      {
        type: "submit",
        class: "primary",
        title:
          "Stores all the settings on this page and applies them immediately. Nothing is changed until you press this button. " +
          "If a value is out of range you are told which one.",
      },
      "Save settings",
    );
    const element = h(
      "form",
      {},
      h("fieldset", {}, legend("Autosave", "settings-autosave", "Settings for the automatic background saving of your open documents. They let you recover your work set-up after a crash or restart. Each autosave creates an automatic session."), h("div", { class: "form-grid" }, enabled.field, interval.field, keep.field, onlyChange.field)),
      h("fieldset", {}, legend("Restore", "settings-restore", "Settings for reopening a saved session in Word. They decide whether Word is started for you, whether cursors are put back, and how long to wait for each document."), h("div", { class: "form-grid" }, startWord.field, position.field, timeout.field)),
      h("fieldset", {}, legend("General", "settings-general", "Settings that are not about saving or restoring: where session files live and whether Word Session starts with Windows. Both affect only your own account."), h("div", { class: "form-grid" }, dir.field, login.field)),
      withHelp(save, "settings", "settings"),
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
  loadShortcut();
  return {
    refresh() {},
    destroy() {
      alive = false;
    },
  };
}
