// The only module that talks to the server. Every call carries the
// X-Word-Session header and the session cookie, and every failure becomes an
// ApiError (status 0 means the server could not be reached at all).

export class ApiError extends Error {
  constructor(status, type, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
  }
}

const hooks = { onUnauthorized: () => {}, onNetworkError: () => {} };

// Let the app react globally to "not signed in" and "server unreachable".
export function configure(newHooks) {
  Object.assign(hooks, newHooks);
}

const baseHeaders = { "X-Word-Session": "1" };

// Turn a failed response into an ApiError, whatever shape its body has.
async function errorFrom(response) {
  let type = "HTTPError";
  let message = `${response.status} ${response.statusText}`.trim();
  try {
    const body = await response.json();
    if (body && body.error) {
      type = body.error.type || type;
      message = body.error.message || message;
    } else if (body && Array.isArray(body.detail)) {
      type = "ValidationError";
      message = body.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    }
  } catch {
    // The body was not JSON; keep the status line.
  }
  return new ApiError(response.status, type, message);
}

// Send one request and return {data, etag, status}.
export async function request(method, path, { body, headers, signal } = {}) {
  const init = {
    method,
    credentials: "same-origin",
    headers: { ...baseHeaders, ...(headers || {}) },
    signal,
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    if (cause && cause.name === "AbortError") throw cause;
    hooks.onNetworkError();
    throw new ApiError(0, "NetworkError", "Cannot reach Word Session");
  }
  if (!response.ok) {
    const error = await errorFrom(response);
    if (response.status === 401) hooks.onUnauthorized();
    throw error;
  }
  const etag = response.headers.get("ETag");
  const data = response.status === 204 ? null : await response.json();
  return { data, etag: etag ? etag.replaceAll('"', "") : null, status: response.status };
}

const ifMatch = (revision) => ({ "If-Match": `"${revision}"` });

export const api = {
  health: () => request("GET", "/api/health").then((r) => r.data),
  word: () => request("GET", "/api/word").then((r) => r.data),
  wordDocuments: () => request("GET", "/api/word/documents").then((r) => r.data),

  listSessions({ q, kind, pinned } = {}) {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (kind) params.set("kind", kind);
    if (pinned) params.set("pinned", "true");
    const query = params.toString();
    return request("GET", `/api/sessions${query ? `?${query}` : ""}`).then((r) => r.data);
  },
  // Returns {session, revision}.
  getSession: (id) =>
    request("GET", `/api/sessions/${encodeURIComponent(id)}`).then((r) => ({
      session: r.data,
      revision: r.etag,
    })),
  capture: (name) => request("POST", "/api/sessions", { body: { name: name || null } }).then((r) => r.data),
  // Returns {session, revision}.
  patchSession: (id, revision, patch) =>
    request("PATCH", `/api/sessions/${encodeURIComponent(id)}`, {
      body: patch,
      headers: ifMatch(revision),
    }).then((r) => ({ session: r.data, revision: r.etag })),
  deleteSession: (id, revision) =>
    request("DELETE", `/api/sessions/${encodeURIComponent(id)}`, { headers: ifMatch(revision) }),
  restore: (id, body) =>
    request("POST", `/api/sessions/${encodeURIComponent(id)}/restore`, { body }).then(
      (r) => r.data.job_id,
    ),
  job: (jobId) => request("GET", `/api/jobs/${encodeURIComponent(jobId)}`).then((r) => r.data),

  getSettings: () => request("GET", "/api/settings").then((r) => r.data),
  putSettings: (settings) => request("PUT", "/api/settings", { body: settings }).then((r) => r.data),
  importLegacy: () => request("POST", "/api/import-legacy").then((r) => r.data),
  doctor: () => request("GET", "/api/doctor").then((r) => r.data),
  logs: (tail = 200) => request("GET", `/api/logs?tail=${tail}`).then((r) => r.data.lines),
};

// Read the server-sent event stream with fetch so the required header can be
// sent. Calls onEvent({type, ...data}) per event and onState("open"|"error")
// as the connection changes; reconnects with backoff until `signal` aborts.
export async function streamEvents({ onEvent, onState, signal }) {
  let delay = 1000;
  while (!signal.aborted) {
    try {
      const response = await fetch("/api/events", {
        headers: { ...baseHeaders, Accept: "text/event-stream" },
        credentials: "same-origin",
        signal,
      });
      if (response.status === 401) {
        hooks.onUnauthorized();
        return;
      }
      if (!response.ok || !response.body) throw new Error(`event stream: ${response.status}`);
      delay = 1000;
      onState("open");
      await readFrames(response.body, onEvent, signal);
    } catch (cause) {
      if (signal.aborted) return;
      void cause;
    }
    // The stream ended or failed: tell the app, then wait before retrying.
    onState("error");
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 2, 15000);
  }
}

// Split the byte stream into SSE frames and dispatch each one.
async function readFrames(stream, onEvent, signal) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  signal.addEventListener("abort", () => reader.cancel().catch(() => {}), { once: true });
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      dispatchFrame(frame, onEvent);
      end = buffer.indexOf("\n\n");
    }
  }
}

function dispatchFrame(frame, onEvent) {
  let type = "message";
  const dataLines = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0 && type === "message") return;
  let payload = {};
  try {
    payload = JSON.parse(dataLines.join("\n") || "{}");
  } catch {
    // Ignore a malformed payload but still deliver the event type.
  }
  onEvent({ ...payload, type });
}
