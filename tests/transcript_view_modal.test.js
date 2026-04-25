const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const test = require("node:test");
const vm = require("vm");

const uiPath = path.resolve(__dirname, "..", "src", "radcast", "static", "ui.js");
const source = fs.readFileSync(uiPath, "utf8");

class FakeHTMLElement {}
class FakeHTMLButtonElement extends FakeHTMLElement {}

function makeNode(id, Kind = FakeHTMLElement) {
  const node = new Kind();
  Object.assign(node, {
    id,
    hidden: false,
    classList: { toggle() {}, add() {}, remove() {} },
    style: {},
    textContent: "",
    innerHTML: "",
    value: "",
    disabled: false,
    checked: false,
    dataset: {},
    children: [],
    parentNode: null,
    attributes: new Map(),
    listeners: new Map(),
    addEventListener(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(handler);
    },
    dispatch(type, event = {}) {
      const handlers = this.listeners.get(type) || [];
      for (const handler of handlers) handler(event);
    },
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name === "tabindex") this.tabIndex = Number(value);
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
  return node;
}

function buildContext(fetchHandler) {
  const nodes = new Map();

  function getNode(id) {
    if (!nodes.has(id)) {
      let Kind = FakeHTMLElement;
      if (id.endsWith("-btn")) {
        Kind = FakeHTMLButtonElement;
      }
      const node = makeNode(id, Kind);
      node.tagName = id.endsWith("-btn") ? "BUTTON" : "DIV";
      if (id.endsWith("-btn")) node.tabIndex = 0;
      nodes.set(id, node);
    }
    return nodes.get(id);
  }

  const document = {
    getElementById(id) {
      return getNode(id);
    },
    querySelectorAll() {
      return [];
    },
    createElement(tagName) {
      const normalized = String(tagName || "").toLowerCase();
      const Kind = normalized === "button" ? FakeHTMLButtonElement : FakeHTMLElement;
      const el = makeNode(normalized, Kind);
      el.tagName = String(tagName || "").toUpperCase();
      return el;
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
    fetch: fetchHandler,
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
  return { context, nodes };
}

test("clicking the view transcript action opens the transcript modal and loads cues", async () => {
  const outputPath = "projects/demo/assets/enhanced_audio/sample.mp3";
  const fetchCalls = [];
  const { context, nodes } = buildContext(async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    if (String(url).endsWith("/outputs")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            project_id: "demo",
            outputs: [
              {
                output_name: "sample.mp3",
                output_path: outputPath,
                folder_path: "projects/demo/assets/enhanced_audio",
                created_at: "2026-04-12T00:00:00.000Z",
                duration_seconds: 117,
                runtime_seconds: 89,
                caption_format: "vtt",
                caption_review_required: true,
                caption_review_warning_segments: 0,
                caption_review_failure_segments: 0,
                has_review_artifacts: false,
                caption_review_download_url: "download",
                caption_download_url: "caption",
                download_url: "audio",
                play_url: "play",
              },
            ],
          };
        },
      };
    }
    if (String(url).includes("/outputs/transcript") && String(options.method || "GET") === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            project_id: "demo",
            output_path: outputPath,
            caption_path: "projects/demo/assets/enhanced_audio/sample.vtt",
            caption_format: "vtt",
            cue_count: 2,
            cues: [
              {
                index: 0,
                start: 3.7,
                end: 5.574,
                text: "Hi! Replacing the lightbulb is one of the simple",
              },
              {
                index: 1,
                start: 5.574,
                end: 9.02,
                text: "things to do. The first thing you need to do is to remove the broken bulb.",
              },
            ],
          };
        },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });

  context.window.__radcastTestState.activeProjectRef = "demo";
  context.bindOutputActions();
  await context.loadOutputs();

  const outputListNode = nodes.get("output-list");
  assert.match(outputListNode.innerHTML, /View transcript/);

  const transcriptButton = makeNode("transcript-action", FakeHTMLButtonElement);
  transcriptButton.dataset.outputPath = outputPath;
  transcriptButton.closest = (selector) => (selector === ".transcript-view-btn" ? transcriptButton : null);

  outputListNode.dispatch("click", { target: transcriptButton });
  await new Promise((resolve) => setImmediate(resolve));

  const modalNode = nodes.get("transcript-view-modal");
  const statusNode = nodes.get("transcript-view-status");
  const metaNode = nodes.get("transcript-view-meta");
  const listNode = nodes.get("transcript-view-list");

  assert.equal(modalNode.hidden, false);
  assert.match(statusNode.textContent, /Loaded 2 cues/);
  assert.match(metaNode.textContent, /2 cues/);
  assert.match(metaNode.textContent, /sample\.vtt/);
  assert.match(listNode.innerHTML, /Cue 1/);
  assert.match(listNode.innerHTML, /00:00:03\.700 → 00:00:05\.574/);
  assert.match(listNode.innerHTML, /Replacing the lightbulb/);
  assert.equal(fetchCalls[1].url, `/projects/demo/outputs/transcript?path=${encodeURIComponent(outputPath)}`);
  assert.equal(fetchCalls[1].options.method, "GET");
});
