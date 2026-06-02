import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

class HarnessHTMLElement {
  attachShadow() {
    this.shadowRoot = {
      activeElement: null,
      addEventListener() {},
      appendChild() {},
      querySelector() {
        return null;
      },
      querySelectorAll() {
        return [];
      },
    };
    return this.shadowRoot;
  }
}

let cachedPanelCtor = null;

function installBrowserStubs() {
  const storage = new Map();
  globalThis.HTMLElement = HarnessHTMLElement;
  globalThis.window = {
    clearInterval() {},
    setInterval() {
      return 0;
    },
    setTimeout,
    localStorage: {
      getItem(key) {
        return storage.has(key) ? storage.get(key) : null;
      },
      setItem(key, value) {
        storage.set(key, String(value));
      },
      removeItem(key) {
        storage.delete(key);
      },
    },
  };
  globalThis.document = {
    createElement() {
      return {
        click() {},
        remove() {},
        set download(value) {
          this._download = value;
        },
        set href(value) {
          this._href = value;
        },
      };
    },
  };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        async writeText() {},
      },
    },
  });
  globalThis.customElements = {
    registry: new Map(),
    define(name, ctor) {
      this.registry.set(name, ctor);
    },
    get(name) {
      return this.registry.get(name);
    },
  };
}

export function loadOpenReefPanel(repoRoot) {
  installBrowserStubs();
  if (cachedPanelCtor) return new cachedPanelCtor();
  const panelPath = path.join(repoRoot, "custom_components/openreef/frontend/openreef-panel.js");
  const source = fs.readFileSync(panelPath, "utf8");
  vm.runInThisContext(source, { filename: panelPath });
  const PanelCtor = globalThis.customElements.get("openreef-panel");
  if (!PanelCtor) throw new Error("openreef-panel custom element was not registered.");
  cachedPanelCtor = PanelCtor;
  return new PanelCtor();
}
