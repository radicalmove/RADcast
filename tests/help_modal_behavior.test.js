const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const uiPath = path.resolve(__dirname, "..", "src", "radcast", "static", "ui.js");
const source = fs.readFileSync(uiPath, "utf8");

class FakeHTMLElement {}
class FakeHTMLButtonElement extends FakeHTMLElement {}

function makeButton(tab) {
  return Object.assign(new FakeHTMLButtonElement(), {
    dataset: { helpTab: tab },
    classList: {
      toggle() {},
      add() {},
      remove() {},
    },
    style: {},
    hidden: false,
    tabIndex: -1,
    textContent: "",
    disabled: false,
    focused: false,
    addEventListener() {},
    setAttribute() {},
    focus() {
      this.focused = true;
    },
    closest(selector) {
      return selector === "[data-help-tab]" ? this : null;
    },
  });
}

function makePanel(tab) {
  return Object.assign(new FakeHTMLElement(), {
    dataset: { helpPanel: tab },
    hidden: false,
  });
}

const helpTabs = [
  "overview",
  "process-audio",
  "cleanup-pauses",
  "generate-captions",
  "trim-clip",
  "helper-processing",
  "troubleshooting",
].map(makeButton);
const helpPanels = helpTabs.map((button) => makePanel(button.dataset.helpTab));
const nodes = new Map();

function makeNode(id) {
  if (id === "help-modal-tabs") return { addEventListener() {} };
  if (!nodes.has(id)) {
    nodes.set(
      id,
      Object.assign(new FakeHTMLElement(), {
        id,
        hidden: false,
        classList: {
          toggle() {},
          add() {},
          remove() {},
        },
        style: {},
        textContent: "",
        value: "",
        disabled: false,
        checked: false,
        dataset: {},
        addEventListener() {},
        setAttribute() {},
        removeAttribute() {},
        appendChild() {},
        pause() {},
        load() {},
        focus() {},
        closest() {
          return null;
        },
        querySelector() {
          return null;
        },
      })
    );
  }
  return nodes.get(id);
}

const document = {
  getElementById(id) {
    return makeNode(id);
  },
  querySelectorAll(selector) {
    if (selector === "[data-help-tab]") return helpTabs;
    if (selector === "[data-help-panel]") return helpPanels;
    return [];
  },
  addEventListener() {},
  body: {
    classList: {
      toggle() {},
    },
  },
  activeElement: helpTabs[2],
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

const helper = context.window.__radcastHelp;

helper.setHelpTab("cleanup-pauses", { persist: false });
helper.handleHelpTabKeydown({
  key: "Home",
  preventDefault() {},
  target: helpTabs[2],
});

assert.equal(helpTabs[0].tabIndex, 0);
assert.equal(helpTabs[0].focused, true);
assert.equal(helpTabs[2].tabIndex, -1);
assert.equal(helpPanels[0].hidden, false);
assert.equal(helpPanels[2].hidden, true);

helpTabs.forEach((button) => {
  button.focused = false;
});

helper.handleHelpTabKeydown({
  key: "End",
  preventDefault() {},
  target: helpTabs[0],
});

assert.equal(helpTabs[6].tabIndex, 0);
assert.equal(helpTabs[6].focused, true);
assert.equal(helpTabs[0].tabIndex, -1);
assert.equal(helpPanels[6].hidden, false);
assert.equal(helpPanels[0].hidden, true);
