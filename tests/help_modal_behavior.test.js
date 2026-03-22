const assert = require("assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const uiPath = path.resolve(__dirname, "..", "src", "radcast", "static", "ui.js");
const source = fs.readFileSync(uiPath, "utf8");

class FakeHTMLElement {}
class FakeHTMLButtonElement extends FakeHTMLElement {}

function attachChild(parent, child) {
  if (!parent.children) parent.children = [];
  child.parentNode = parent;
  parent.children.push(child);
  return child;
}

function makeButton(tab) {
  return Object.assign(new FakeHTMLButtonElement(), {
    tagName: "BUTTON",
    dataset: { helpTab: tab },
    children: [],
    parentNode: null,
    attributes: new Map(),
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
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name === "tabindex") this.tabIndex = Number(value);
    },
    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    },
    focus() {
      this.focused = true;
      document.activeElement = this;
    },
    closest(selector) {
      return selector === "[data-help-tab]" ? this : null;
    },
  });
}

function makePanel(tab) {
  return Object.assign(new FakeHTMLElement(), {
    tagName: "SECTION",
    dataset: { helpPanel: tab },
    children: [],
    parentNode: null,
    attributes: new Map(),
    hidden: false,
    addEventListener() {},
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
    },
    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    },
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
    const node = Object.assign(new FakeHTMLElement(), {
      id,
      tagName: id.endsWith("-btn") ? "BUTTON" : "DIV",
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
      children: [],
      parentNode: null,
      attributes: new Map(),
      tabIndex: id.endsWith("-btn") ? 0 : -1,
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
        return attachChild(this, child);
      },
      pause() {},
      load() {},
      focus() {
        document.activeElement = this;
      },
      closest() {
        return null;
      },
      querySelector() {
        return null;
      },
    });
    if (id === "help-modal") {
      const closeBtn = makeNode("help-close-btn");
      attachChild(node, closeBtn);
      for (const button of helpTabs) attachChild(node, button);
      for (const panel of helpPanels) attachChild(node, panel);
    }
    nodes.set(id, node);
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

const helpCloseBtn = document.getElementById("help-close-btn");
let prevented = false;

helpCloseBtn.focus();
helper.handleHelpModalKeydown({
  key: "Tab",
  shiftKey: true,
  preventDefault() {
    prevented = true;
  },
});

assert.equal(prevented, true);
assert.equal(document.activeElement, helpTabs[6]);

prevented = false;
helpTabs[6].focus();
helper.handleHelpModalKeydown({
  key: "Tab",
  shiftKey: false,
  preventDefault() {
    prevented = true;
  },
});

assert.equal(prevented, true);
assert.equal(document.activeElement, helpCloseBtn);
