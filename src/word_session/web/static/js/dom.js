// Small DOM helpers. Text is only ever inserted as text nodes or attributes,
// never parsed as markup, so untrusted paths and names cannot inject HTML.

// Build an element: h("button", {class: "primary", onclick: fn}, "Save").
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on") && typeof value === "function") {
      el.addEventListener(name.slice(2), value);
    } else if (name === "class") {
      el.className = value;
    } else if (value === true) {
      el.setAttribute(name, "");
    } else {
      el.setAttribute(name, String(value));
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

let counter = 0;
// A labelled form control; returns {field, input}.
export function labelled(text, input) {
  counter += 1;
  const id = `field-${counter}`;
  input.id = id;
  return { field: h("div", { class: "field" }, h("label", { for: id }, text), input), input };
}

export function formatDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString();
}

export function formatPosition(position) {
  if (!position || position.page === null || position.page === undefined) return "";
  const line = position.line !== null && position.line !== undefined ? `, l. ${position.line}` : "";
  return `p. ${position.page}${line}`;
}

// Turn an ApiError into the sentence shown to the user, with a hint if useful.
export function describeError(error) {
  if (error && error.status === 503) {
    return { message: "Word is not running", hint: "Start Word and try again." };
  }
  if (error && error.status === 504) {
    return { message: "Word is not responding — it may be showing a dialog.", hint: "" };
  }
  if (error && error.status === 0) {
    return { message: "Word Session is not running — reopen it from the tray", hint: "" };
  }
  return { message: (error && error.message) || "Something went wrong", hint: "" };
}

export function errorBox(error) {
  const { message, hint } = describeError(error);
  return h("div", { class: "error-box", role: "alert" }, message, hint ? ` ${hint}` : "");
}

export function badge(text, extraClass = "") {
  return h("span", { class: `badge ${extraClass}`.trim() }, text);
}

// Show a short message in the toast area.
export function toast(message, kind = "info") {
  const area = document.getElementById("toasts");
  const el = h("div", { class: kind === "error" ? "toast toast-error" : "toast" }, message);
  area.append(el);
  setTimeout(() => el.remove(), 6000);
}

export function toastError(error) {
  if (error && error.status === 0) return;
  toast(describeError(error).message, "error");
}

// Ask a question in a modal dialog; resolves to true when confirmed.
export function confirmDialog(title, message, confirmLabel) {
  return new Promise((resolve) => {
    const confirm = h("button", { type: "submit", class: "danger", value: "yes" }, confirmLabel);
    const cancel = h("button", { type: "submit", value: "no", formnovalidate: true }, "Cancel");
    const dialog = h(
      "dialog",
      { "aria-label": title },
      h("form", { method: "dialog" }, h("h3", {}, title), h("p", {}, message), h("menu", {}, cancel, confirm)),
    );
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "yes");
      dialog.remove();
    });
    document.body.append(dialog);
    dialog.showModal();
    cancel.focus();
  });
}

// Ask for one line of text in a modal dialog; resolves to the text or null.
export function promptDialog(title, label, confirmLabel) {
  return new Promise((resolve) => {
    const { field, input } = labelled(label, h("input", { type: "text", autocomplete: "off" }));
    const ok = h("button", { type: "submit", class: "primary", value: "yes" }, confirmLabel);
    const cancel = h("button", { type: "submit", value: "no", formnovalidate: true }, "Cancel");
    const dialog = h(
      "dialog",
      { "aria-label": title },
      h("form", { method: "dialog" }, h("h3", {}, title), field, h("menu", {}, cancel, ok)),
    );
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "yes" ? input.value.trim() : null);
      dialog.remove();
    });
    document.body.append(dialog);
    dialog.showModal();
    input.focus();
  });
}

// Run an async action with a button disabled meanwhile.
export async function withBusy(button, action) {
  button.disabled = true;
  try {
    return await action();
  } finally {
    button.disabled = false;
  }
}
