const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const test = require("node:test");
const vm = require("vm");

const uiPath = path.resolve(__dirname, "..", "src", "radcast", "static", "ui.js");
const source = fs.readFileSync(uiPath, "utf8");

class FakeHTMLElement {}
class FakeHTMLButtonElement extends FakeHTMLElement {}
class FakeHTMLInputElement extends FakeHTMLElement {}

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
      if (id === "output-list") {
        Kind = FakeHTMLElement;
      } else if (id.endsWith("-btn")) {
        Kind = FakeHTMLButtonElement;
      }
      const node = makeNode(id, Kind);
      node.tagName = id === "output-list" ? "UL" : id.endsWith("-btn") ? "BUTTON" : "DIV";
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
      const Kind =
        normalized === "button"
          ? FakeHTMLButtonElement
          : normalized === "input"
            ? FakeHTMLInputElement
            : FakeHTMLElement;
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
    HTMLInputElement: FakeHTMLInputElement,
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

function makePendingResponse(outputPath) {
  return {
    project_id: "demo",
    output_path: outputPath,
    status: "pending",
    automated_blocking_items: 1,
    blocking_items_remaining: 1,
    needs_review: [
      {
        item_id: "flag-1",
        cue_index: 0,
        reason_category: "terminology",
        reason_label: "Term likely misheard",
        term: "muru",
        normalized_term: "muru",
        cue_start_seconds: 1.0,
        cue_end_seconds: 2.2,
        previous_context: "Welcome back",
        flagged_context: "This lecture covers Murray as collective remedy",
        next_context: "The lecturer discusses reciprocity",
        already_in_glossary: false,
        can_add_to_glossary: true,
        absolute_start_seconds: 1.0,
        absolute_end_seconds: 2.2,
      },
    ],
    already_in_glossary: [],
    resolved_items: [],
  };
}

function makeResolvedResponse(outputPath) {
  return {
    project_id: "demo",
    output_path: outputPath,
    status: "passed_after_human_review",
    automated_blocking_items: 1,
    blocking_items_remaining: 0,
    needs_review: [],
    already_in_glossary: [],
    resolved_items: [
      {
        item_id: "flag-1",
        cue_index: 0,
        reason_category: "terminology",
        reason_label: "Term likely misheard",
        term: "muru",
        normalized_term: "muru",
        cue_start_seconds: 1.0,
        cue_end_seconds: 2.2,
        previous_context: "Welcome back",
        flagged_context: "muru as collective remedy",
        next_context: "The lecturer discusses reciprocity",
        already_in_glossary: false,
        can_add_to_glossary: false,
        absolute_start_seconds: 1.0,
        absolute_end_seconds: 2.2,
      },
    ],
  };
}

test("saving a correction updates the row state immediately", async () => {
  const outputPath = "projects/demo/assets/enhanced_audio/sample.mp3";
  const fetchCalls = [];
  const { context, nodes } = buildContext(async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    if (String(url).includes("/review-items") && String(options.method || "GET") === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          return makePendingResponse(outputPath);
        },
      };
    }
    if (String(url).includes("/review-items/correct") && String(options.method || "POST") === "POST") {
      return {
        ok: true,
        status: 200,
        async json() {
          return makeResolvedResponse(outputPath);
        },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });

  context.window.__radcastTestState.activeProjectRef = "demo";
  await context.window.__radcastGlossaryReview.loadReviewItems(outputPath);
  await context.window.__radcastGlossaryReview.submitReviewItemCorrection({
    itemId: "flag-1",
    correctedText: "muru as collective remedy",
    correctedStartSeconds: 1.1,
    correctedEndSeconds: 2.3,
  });

  const statusNode = nodes.get("glossary-review-status");
  const summaryNode = nodes.get("glossary-review-summary");
  const listNode = nodes.get("glossary-review-list");

  assert.equal(fetchCalls[1].url, `/projects/demo/outputs/review-items/correct?path=${encodeURIComponent(outputPath)}`);
  assert.equal(fetchCalls[1].options.method, "POST");
  assert.match(String(fetchCalls[1].options.body || ""), /muru as collective remedy/);
  assert.match(statusNode.textContent, /Saved correction/);
  assert.match(statusNode.textContent, /passes after human review/i);
  assert.match(summaryNode.innerHTML, /0 still need review/);
  assert.match(listNode.innerHTML, /Resolved in this review/);
});

test("approving an item marks it resolved and updates remaining failure count", async () => {
  const outputPath = "projects/demo/assets/enhanced_audio/sample.mp3";
  const fetchCalls = [];
  const { context, nodes } = buildContext(async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    if (String(url).includes("/review-items") && String(options.method || "GET") === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          return makePendingResponse(outputPath);
        },
      };
    }
    if (String(url).includes("/review-items/approve") && String(options.method || "POST") === "POST") {
      return {
        ok: true,
        status: 200,
        async json() {
          return makeResolvedResponse(outputPath);
        },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });

  context.window.__radcastTestState.activeProjectRef = "demo";
  await context.window.__radcastGlossaryReview.loadReviewItems(outputPath);
  await context.window.__radcastGlossaryReview.submitReviewItemApproval({ itemId: "flag-1" });

  const statusNode = nodes.get("glossary-review-status");
  const summaryNode = nodes.get("glossary-review-summary");
  const listNode = nodes.get("glossary-review-list");

  assert.equal(fetchCalls[1].url, `/projects/demo/outputs/review-items/approve?path=${encodeURIComponent(outputPath)}`);
  assert.equal(fetchCalls[1].options.method, "POST");
  assert.match(String(fetchCalls[1].options.body || ""), /flag-1/);
  assert.match(statusNode.textContent, /Approved as correct/);
  assert.match(summaryNode.innerHTML, /0 still need review/);
  assert.match(listNode.innerHTML, /Resolved in this review/);
});
