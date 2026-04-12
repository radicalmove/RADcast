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

function makeNode(id) {
  return {
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
    addEventListener() {},
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
  };
}

function buildContext(fetchHandler) {
  const nodes = new Map();

  function getNode(id) {
    if (!nodes.has(id)) {
      const node = makeNode(id);
      if (id === "output-list") {
        node.tagName = "UL";
      } else if (id.endsWith("-btn")) {
        node.tagName = "BUTTON";
        node.tabIndex = 0;
      } else {
        node.tagName = "DIV";
      }
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
      const el = makeNode(tagName.toLowerCase());
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

test("completed versions expose glossary review action when artifacts exist", async () => {
  const fetchCalls = [];
  const { context, nodes } = buildContext(async (url) => {
    fetchCalls.push(String(url));
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
                output_path: "projects/demo/assets/enhanced_audio/sample.mp3",
                folder_path: "projects/demo/assets/enhanced_audio",
                created_at: "2026-04-12T00:00:00.000Z",
                duration_seconds: 5,
                runtime_seconds: 10,
                caption_format: "vtt",
                caption_review_required: true,
                caption_review_warning_segments: 0,
                caption_review_failure_segments: 1,
                has_review_artifacts: true,
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
    throw new Error(`unexpected request: ${url}`);
  });

  context.window.__radcastTestState.activeProjectRef = "demo";
  await context.loadOutputs();

  const outputListNode = nodes.get("output-list");
  assert.match(outputListNode.innerHTML, /Review glossary candidates/);
  assert.equal(fetchCalls.length, 1);
});

test("glossary review modal renders candidate context from the API", async () => {
  const payload = {
    project_id: "demo",
    output_path: "projects/demo/assets/enhanced_audio/sample.mp3",
    caption_path: "projects/demo/assets/enhanced_audio/sample.vtt",
    review_path: "projects/demo/assets/enhanced_audio/sample.vtt.review.txt",
    has_review_artifacts: true,
    has_candidates: true,
    candidate_count: 2,
    candidates: [
      {
        candidate_id: "tikanga:1000:2000",
        term: "tikanga",
        normalized_term: "tikanga",
        reason: "probable critical term miss: tikanga",
        previous_context: "Welcome everyone",
        flagged_context: "Aitikanga Māori space",
        next_context: "And then we discuss transgression",
        already_known: false,
      },
      {
        candidate_id: "transgression:2000:3000",
        term: "transgression",
        normalized_term: "transgression",
        reason: "probable critical term miss: transgression",
        previous_context: "Aitikanga Māori space",
        flagged_context: "And then we discuss transgression",
        next_context: "",
        already_known: true,
      },
    ],
  };

  const fetchCalls = [];
  const { context, nodes } = buildContext(async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    if (String(url).includes("/glossary-review-candidates") && String(options.method || "GET") === "GET") {
      return {
        ok: true,
        status: 200,
        async json() {
          return payload;
        },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });

  context.window.__radcastTestState.activeProjectRef = "demo";
  await context.loadGlossaryReviewCandidates(payload.output_path);

  const statusNode = nodes.get("glossary-review-status");
  const listNode = nodes.get("glossary-review-list");
  const summaryNode = nodes.get("glossary-review-summary");

  assert.match(statusNode.textContent, /2 glossary candidates loaded/);
  assert.match(summaryNode.innerHTML, /2 candidates/);
  assert.match(listNode.innerHTML, /Approve for shared glossary/);
  assert.match(listNode.innerHTML, /Already in glossary/);
  assert.match(listNode.innerHTML, /Aitikanga Māori space/);
  assert.equal(fetchCalls[0].url, `/projects/demo/outputs/glossary-review-candidates?path=${encodeURIComponent(payload.output_path)}`);
  assert.equal(fetchCalls[0].options.method, "GET");
});
