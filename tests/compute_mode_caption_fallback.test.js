const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const test = require("node:test");
const vm = require("vm");

const uiPath = path.resolve(__dirname, "..", "src", "radcast", "static", "ui.js");
const source = fs.readFileSync(uiPath, "utf8");

class FakeHTMLElement {}
class FakeHTMLButtonElement extends FakeHTMLElement {}

function buildContext() {
  const nodes = new Map();

  function makeNode(id) {
    if (!nodes.has(id)) {
      nodes.set(id, {
        id,
        hidden: false,
        classList: { toggle() {}, add() {}, remove() {} },
        style: {},
        textContent: "",
        value: "",
        disabled: false,
        checked: false,
        dataset: {},
        children: [],
        parentNode: null,
        attributes: new Map(),
        addEventListener() {},
        setAttribute(name, value) {
          this.attributes.set(name, String(value));
        },
        getAttribute(name) {
          return this.attributes.get(name) ?? null;
        },
        removeAttribute(name) {
          this.attributes.delete(name);
        },
        appendChild(child) {
          child.parentNode = this;
          this.children.push(child);
          return child;
        },
        pause() {},
        load() {},
        focus() {},
        closest() {
          return null;
        },
        querySelector() {
          return null;
        },
        querySelectorAll() {
          return [];
        },
      });
    }
    return nodes.get(id);
  }

  const document = {
    getElementById(id) {
      return makeNode(id);
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    body: {
      classList: {
        toggle() {},
      },
    },
    activeElement: null,
  };

  const context = {
    window: null,
    document,
    localStorage: {
      getItem() {
        return null;
      },
      setItem() {},
    },
    fetch() {
      throw new Error("fetch should not be called");
    },
    navigator: {
      clipboard: {
        writeText() {},
      },
    },
    URL: {
      revokeObjectURL() {},
      createObjectURL() {
        return "blob:";
      },
    },
    setTimeout,
    clearTimeout,
    setInterval() {
      return 1;
    },
    clearInterval() {},
    console,
    HTMLElement: FakeHTMLElement,
    HTMLButtonElement: FakeHTMLButtonElement,
    Element: FakeHTMLElement,
    AbortController: class {},
    FormData: class {},
    Blob: class {},
    Headers: class {},
    Response: class {},
    Request: class {},
    Intl,
    Math,
    Date,
    JSON,
    Number,
    String,
    Boolean,
    Array,
    Set,
    Object,
    RegExp,
    Error,
    URLSearchParams,
    encodeURIComponent,
    decodeURIComponent,
    performance: {
      now() {
        return 0;
      },
    },
  };

  context.window = context;
  context.window.__RADCAST_DISABLE_AUTOINIT__ = true;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "ui.js" });
  return context;
}

test("caption stage keeps local helper mode for claimed worker jobs", () => {
  const context = buildContext();

  context.startJobTracking({
    job_id: "job_worker_caption",
    stage: "queued_remote",
    worker_mode: true,
    worker_fallback_timeout_seconds: 40,
    worker_online_count: 1,
    worker_total_count: 1,
    worker_live_count: 1,
    worker_registered_count: 1,
    worker_stale_count: 0,
    worker_last_live_seen_at: "2026-03-31T03:41:12.745319+00:00",
    worker_online_window_seconds: 60,
  });

  context.updateFromJob({
    stage: "captions",
    logs: ["Transcribing speech for captions. Window 1 of 9."],
    progress: 0.25,
    eta_seconds: 840,
    status: "running",
  });

  assert.equal(context.computeLabelForMode(), "Processing on: local helper device");
  assert.equal(
    context.runningStatusText(),
    "Helper connected. Generating captions on your local helper device."
  );
});

test("caption stage still shows server when server fallback is explicit", () => {
  const context = buildContext();

  context.startJobTracking({
    job_id: "job_server_caption",
    stage: "queued_remote",
    worker_mode: true,
    worker_fallback_timeout_seconds: 40,
    worker_online_count: 1,
    worker_total_count: 1,
    worker_live_count: 1,
    worker_registered_count: 1,
    worker_stale_count: 0,
    worker_last_live_seen_at: "2026-03-31T03:41:12.745319+00:00",
    worker_online_window_seconds: 60,
  });

  context.updateFromJob({
    stage: "captions",
    logs: ["Helper enhancement is done. Generating captions on the RADcast server."],
    progress: 0.25,
    eta_seconds: 840,
    status: "running",
  });

  assert.equal(context.computeLabelForMode(), "Processing on: RADcast server (Mac mini)");
  assert.equal(
    context.runningStatusText(),
    "Audio processing is done. Generating captions on the RADcast server (Mac mini)."
  );
});
