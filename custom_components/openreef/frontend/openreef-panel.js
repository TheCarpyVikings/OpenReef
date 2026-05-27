class OpenReefPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._sensorMeta = {};
    this._validation = null;
    this._activeTab = "mission";
    this._setupOpen = false;
    this._setupStep = 0;
    this._searchResults = {};
    this._message = "";
    this._error = "";
    this._busy = false;
    this._eventsAttached = false;
    this._lastRenderedSetupOpen = false;
    this._lastRenderedSetupStep = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config) {
      if (!this._setupOpen) {
        this._render();
      }
      return;
    }

    this._renderLoading();
    this._loadConfig();
  }

  connectedCallback() {
    this._attachEvents();
    this._renderLoading();
    this._loadConfig();
  }

  async _callWS(payload) {
    if (!this._hass) throw new Error("Home Assistant is not ready yet");
    if (typeof this._hass.callWS === "function") return this._hass.callWS(payload);
    if (this._hass.connection?.sendMessagePromise) {
      return this._hass.connection.sendMessagePromise(payload);
    }
    throw new Error("Home Assistant WebSocket helper is unavailable");
  }

  async _loadConfig() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    try {
      const result = await this._callWS({ type: "openreef/get_config" });
      this._config = result.config || result.settings;
      this._sensorMeta = result.sensor_meta || {};
      this._validation = result.validation || null;
      this._setupOpen = !this._config?.display?.setupComplete;
      this._error = "";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not load OpenReef";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _saveConfig(nextConfig = this._config) {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      const result = await this._callWS({
        type: "openreef/save_config",
        config: nextConfig,
      });
      this._config = result.config || nextConfig;
      this._validation = result.validation || null;
      this._message = "Saved";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not save OpenReef";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _validateConfig() {
    try {
      this._validation = await this._callWS({ type: "openreef/validate_config" });
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not validate OpenReef";
    }
    this._render();
  }

  async _searchEntities(key, target) {
    this._searchResults[key] = { loading: true, candidates: [] };
    this._render();
    try {
      const result = await this._callWS({
        type: "openreef/search_entities",
        target,
        limit: 10,
      });
      this._searchResults[key] = {
        loading: false,
        candidates: result.candidates || [],
      };
    } catch (err) {
      this._searchResults[key] = {
        loading: false,
        error: err instanceof Error ? err.message : "Search failed",
        candidates: [],
      };
    }
    this._render();
  }

  async _toggleEquipment(equipmentId) {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      await this._callWS({ type: "openreef/toggle_equipment", equipment_id: equipmentId });
      this._message = "Command sent";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not toggle equipment";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _attachEvents() {
    if (this._eventsAttached) return;
    this._eventsAttached = true;

    this.shadowRoot.addEventListener("click", (event) => {
      const target = event.target.closest("[data-action]");
      if (!target) return;
      const action = target.dataset.action;
      const id = target.dataset.id;
      const field = target.dataset.field;

      if (action === "tab") {
        this._activeTab = id;
        this._setupOpen = false;
        this._render();
      }
      if (action === "setup") {
        this._setupOpen = true;
        this._setupStep = 0;
        this._render();
      }
      if (action === "close-setup") {
        this._setupOpen = false;
        this._render();
      }
      if (action === "next-step") {
        this._setupStep = Math.min(this._setupStep + 1, 3);
        this._render();
      }
      if (action === "prev-step") {
        this._setupStep = Math.max(this._setupStep - 1, 0);
        this._render();
      }
      if (action === "finish-setup") {
        this._config.display.setupComplete = true;
        this._setupOpen = false;
        this._saveConfig();
      }
      if (action === "save") this._saveConfig();
      if (action === "validate") this._validateConfig();
      if (action === "search-sensor") {
        const meta = this._sensorMeta[id] || {};
        this._searchEntities(`sensor:${id}`, {
          id,
          label: this._config.sensors[id]?.label || meta.label || id,
          ...(meta.target || {}),
        });
      }
      if (action === "search-equipment") {
        const equipment = this._config.equipment[id] || {};
        this._searchEntities(`equipment:${id}:${field}`, this._equipmentTarget(id, equipment, field));
      }
      if (action === "choose-sensor") {
        this._config.sensors[id].entity_id = target.dataset.entity;
        this._render();
      }
      if (action === "choose-equipment") {
        this._config.equipment[id][field] = target.dataset.entity;
        this._render();
      }
      if (action === "add-equipment") this._addEquipment(target.dataset.label);
      if (action === "remove-equipment") {
        delete this._config.equipment[id];
        this._render();
      }
      if (action === "toggle-armed") {
        const equipment = this._config.equipment[id];
        equipment.armed = !equipment.armed;
        this._saveConfig();
      }
      if (action === "toggle-equipment") this._toggleEquipment(id);
    });

    this.shadowRoot.addEventListener("input", (event) => {
      const target = event.target;
      if (!target.dataset) return;
      const scope = target.dataset.scope;
      const id = target.dataset.id;
      const field = target.dataset.field;
      const value = target.type === "number" ? Number(target.value) : target.value;

      if (scope === "tank") this._config.tank[field] = value;
      if (scope === "display") this._config.display[field] = value;
      if (scope === "sensor") this._config.sensors[id][field] = value;
      if (scope === "equipment") this._config.equipment[id][field] = value;
      if (scope === "energy") this._config.energy[field] = value;
    });
  }

  _addEquipment(label) {
    const base = this._slug(label || "Equipment");
    let id = base;
    let suffix = 2;
    while (this._config.equipment[id]) {
      id = `${base}_${suffix}`;
      suffix += 1;
    }
    this._config.equipment[id] = {
      label: label || "Equipment",
      switch_entity_id: "",
      power_entity_id: "",
      energy_entity_id: "",
      cost_entity_id: "",
      armed: false,
    };
    this._render();
  }

  _equipmentTarget(id, equipment, field) {
    const label = equipment.label || id;
    const base = {
      id: `${id}_${field}`,
      label,
      prefer: ["reef", "tank", "aquarium", label],
      avoid: [],
    };
    if (field === "switch_entity_id") {
      return {
        ...base,
        domains: ["switch"],
        keywords: [label, "plug", "switch", "socket", "outlet"],
      };
    }
    if (field === "power_entity_id") {
      return {
        ...base,
        domains: ["sensor"],
        keywords: [label, "power", "watts"],
        device_classes: ["power"],
        units: ["W", "w"],
      };
    }
    if (field === "energy_entity_id") {
      return {
        ...base,
        domains: ["sensor"],
        keywords: [label, "energy", "kwh"],
        device_classes: ["energy"],
        units: ["kWh", "Wh"],
      };
    }
    return {
      ...base,
      domains: ["sensor"],
      keywords: [label, "cost", "money"],
      device_classes: ["monetary"],
      units: ["GBP", "£"],
    };
  }

  _state(entityId) {
    if (!entityId || !this._hass?.states) return null;
    return this._hass.states[entityId] || null;
  }

  _stateValue(entityId) {
    return this._state(entityId)?.state ?? "--";
  }

  _number(entityId) {
    const value = Number.parseFloat(this._stateValue(entityId));
    return Number.isFinite(value) ? value : null;
  }

  _sensorStatus(sensor) {
    const value = this._number(sensor.entity_id);
    if (value === null) return "unknown";
    if (value < Number(sensor.min) || value > Number(sensor.max)) return "critical";
    const buffer = (Number(sensor.max) - Number(sensor.min)) * 0.1;
    if (value < Number(sensor.min) + buffer || value > Number(sensor.max) - buffer) return "warning";
    return "ok";
  }

  _format(value, digits = 1) {
    return Number.isFinite(value) ? Number(value).toFixed(digits) : "--";
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _slug(value) {
    return String(value || "equipment")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "equipment";
  }

  _renderLoading() {
    this._lastRenderedSetupOpen = false;
    this._lastRenderedSetupStep = null;
    this.shadowRoot.innerHTML = `${this._styles()}<main class="page"><div class="center-card"><div class="spinner"></div><p>Loading OpenReef...</p></div></main>`;
  }

  _captureScrollState() {
    const wizard = this.shadowRoot.querySelector(".wizard");
    return {
      wizard: wizard ? wizard.scrollTop : 0,
    };
  }

  _restoreScrollState(scrollState) {
    if (!scrollState) return;
    requestAnimationFrame(() => {
      const wizard = this.shadowRoot.querySelector(".wizard");
      if (wizard) wizard.scrollTop = scrollState.wizard;
    });
  }

  _render() {
    if (!this._config) {
      this._renderLoading();
      return;
    }

    const scrollState = this._captureScrollState();
    const preserveSetupScroll =
      this._setupOpen &&
      this._lastRenderedSetupOpen &&
      this._setupStep === this._lastRenderedSetupStep;

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <main class="page">
        <header class="topbar">
          <div>
            <p class="eyebrow">OpenReef Core</p>
            <h1>${this._escape(this._config.tank.name || "OpenReef")}</h1>
            <p>${this._escape(this._config.tank.owner || "Home Assistant native reef controller")}</p>
          </div>
          <div class="actions">
            <button class="secondary" data-action="setup">Setup</button>
            <button class="secondary" data-action="validate">Check</button>
          </div>
        </header>

        ${this._messages()}
        ${this._tabs()}
        ${this._activeContent()}
        ${this._setupOpen ? this._setupWizard() : ""}
      </main>
    `;

    this._lastRenderedSetupOpen = this._setupOpen;
    this._lastRenderedSetupStep = this._setupOpen ? this._setupStep : null;
    if (preserveSetupScroll) this._restoreScrollState(scrollState);
  }

  _messages() {
    return `
      ${this._error ? `<div class="notice error">${this._escape(this._error)}</div>` : ""}
      ${this._message ? `<div class="notice success">${this._escape(this._message)}</div>` : ""}
      ${this._busy ? `<div class="notice">Working...</div>` : ""}
    `;
  }

  _tabs() {
    const tabs = [
      ["mission", "Mission Control"],
      ["live", "Live Stats"],
      ["controls", "Controls"],
      ["energy", "Energy"],
      ["settings", "Settings"],
    ];
    return `
      <nav class="tabs">
        ${tabs.map(([id, label]) => `
          <button class="${this._activeTab === id ? "active" : ""}" data-action="tab" data-id="${id}">
            ${label}
          </button>
        `).join("")}
      </nav>
    `;
  }

  _activeContent() {
    if (this._activeTab === "live") return this._liveStats();
    if (this._activeTab === "controls") return this._controls();
    if (this._activeTab === "energy") return this._energy();
    if (this._activeTab === "settings") return this._settings();
    return this._mission();
  }

  _mission() {
    const sensors = Object.entries(this._config.sensors || {});
    const critical = sensors.filter(([, sensor]) => this._sensorStatus(sensor) === "critical");
    const warnings = sensors.filter(([, sensor]) => this._sensorStatus(sensor) === "warning");
    const missing = this._validation?.missing_entities || [];
    const armedUnavailable = this._validation?.armed_unavailable || [];
    const status = critical.length || armedUnavailable.length ? "Action needed" : warnings.length || missing.length ? "Watch closely" : "All systems nominal";

    return `
      <section class="stack">
        <div class="hero ${critical.length || armedUnavailable.length ? "danger-border" : warnings.length || missing.length ? "warning-border" : "ok-border"}">
          <div>
            <p class="eyebrow">Mission Control</p>
            <h2>${status}</h2>
            <p>${critical.length} critical sensor issue(s), ${missing.length} missing mapping(s), ${armedUnavailable.length} armed device issue(s).</p>
          </div>
          <button class="secondary" data-action="validate">Refresh checks</button>
        </div>
        <div class="grid two">
          <article class="panel">
            <h3>Core Sensors</h3>
            ${sensors.map(([id, sensor]) => this._sensorRow(id, sensor)).join("")}
          </article>
          <article class="panel">
            <h3>Armed Equipment</h3>
            ${this._armedEquipmentRows()}
          </article>
        </div>
      </section>
    `;
  }

  _sensorRow(id, sensor) {
    const status = this._sensorStatus(sensor);
    const value = this._number(sensor.entity_id);
    const display = id === "ph" ? this._format(value, 2) : this._format(value, 1);
    return `
      <div class="row">
        <div>
          <strong>${this._escape(sensor.label)}</strong>
          <span>${this._escape(sensor.entity_id || "Not mapped")}</span>
        </div>
        <div class="pill ${status}">${display} ${this._escape(sensor.unit || "")}</div>
      </div>
    `;
  }

  _armedEquipmentRows() {
    const armed = Object.entries(this._config.equipment || {}).filter(([, item]) => item.armed);
    if (!armed.length) return `<p class="muted">No equipment has been armed yet.</p>`;
    return armed.map(([id, item]) => `
      <div class="row">
        <div>
          <strong>${this._escape(item.label || id)}</strong>
          <span>${this._escape(item.switch_entity_id || "No switch mapped")}</span>
        </div>
        <div class="pill">${this._escape(this._stateValue(item.switch_entity_id))}</div>
      </div>
    `).join("");
  }

  _liveStats() {
    return `
      <section class="stack">
        <h2>Live Stats</h2>
        <div class="grid three">
          ${Object.entries(this._config.sensors || {}).map(([id, sensor]) => {
            const value = this._number(sensor.entity_id);
            const display = id === "ph" ? this._format(value, 2) : this._format(value, 1);
            return `
              <article class="stat">
                <p>${this._escape(sensor.label)}</p>
                <strong>${display}</strong>
                <span>${this._escape(sensor.unit || "")}</span>
                <small>${this._escape(sensor.entity_id || "Not mapped")}</small>
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `;
  }

  _controls() {
    const rows = Object.entries(this._config.equipment || {});
    return `
      <section class="stack">
        <div class="section-head">
          <h2>Controls</h2>
          <p>Controls stay locked until each device is explicitly armed.</p>
        </div>
        <div class="grid two">
          ${rows.length ? rows.map(([id, item]) => this._controlCard(id, item)).join("") : `<article class="panel"><p class="muted">No equipment mapped yet.</p></article>`}
        </div>
      </section>
    `;
  }

  _controlCard(id, item) {
    const state = this._stateValue(item.switch_entity_id);
    return `
      <article class="panel">
        <div class="card-head">
          <div>
            <h3>${this._escape(item.label || id)}</h3>
            <p>${this._escape(item.switch_entity_id || "No switch mapped")}</p>
          </div>
          <span class="pill">${this._escape(state)}</span>
        </div>
        <div class="button-row">
          <button class="${item.armed ? "warning" : "secondary"}" data-action="toggle-armed" data-id="${this._escape(id)}">
            ${item.armed ? "Disarm" : "Arm control"}
          </button>
          <button class="primary" ${item.armed && item.switch_entity_id ? "" : "disabled"} data-action="toggle-equipment" data-id="${this._escape(id)}">
            Toggle
          </button>
        </div>
      </article>
    `;
  }

  _energy() {
    const tariff = Number(this._config.energy.tariff || 0);
    const totals = [
      ["Daily", "daily_energy_entity_id", "daily_cost_entity_id"],
      ["Weekly", "weekly_energy_entity_id", "weekly_cost_entity_id"],
      ["Monthly", "monthly_energy_entity_id", "monthly_cost_entity_id"],
    ];
    return `
      <section class="stack">
        <div class="section-head">
          <h2>Energy</h2>
          <p>${this._escape(this._config.energy.currency || "GBP")} ${tariff.toFixed(2)} per kWh</p>
        </div>
        <div class="grid three">
          ${totals.map(([label, energyKey, costKey]) => {
            const energy = this._number(this._config.energy[energyKey]);
            const mappedCost = this._number(this._config.energy[costKey]);
            const cost = mappedCost ?? (energy === null ? null : energy * tariff);
            return `
              <article class="stat">
                <p>${label}</p>
                <strong>${this._format(energy, 2)} kWh</strong>
                <span>${cost === null ? "--" : cost.toFixed(2)} ${this._escape(this._config.energy.currency || "GBP")}</span>
                <small>${this._escape(this._config.energy[energyKey] || "Optional mapping missing")}</small>
              </article>
            `;
          }).join("")}
        </div>
        <div class="grid two">
          ${Object.entries(this._config.equipment || {}).map(([id, item]) => {
            const power = this._number(item.power_entity_id);
            const energy = this._number(item.energy_entity_id);
            return `
              <article class="panel">
                <h3>${this._escape(item.label || id)}</h3>
                <div class="row"><span>Power</span><strong>${this._format(power, 1)} W</strong></div>
                <div class="row"><span>Energy</span><strong>${this._format(energy, 2)} kWh</strong></div>
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `;
  }

  _settings() {
    return `
      <section class="stack">
        <div class="section-head">
          <h2>Settings</h2>
          <button class="primary" data-action="save">Save settings</button>
        </div>
        ${this._profileSettings()}
        <article class="panel">
          <h3>Sensors</h3>
          <div class="grid two compact">${Object.entries(this._config.sensors || {}).map(([id, sensor]) => this._sensorPicker(id, sensor)).join("")}</div>
        </article>
        ${this._equipmentSettings()}
        ${this._energySettings()}
      </section>
    `;
  }

  _profileSettings() {
    return `
      <article class="panel">
        <h3>Profile</h3>
        <div class="grid two compact">
          <label>Tank name<input data-scope="tank" data-field="name" value="${this._escape(this._config.tank.name)}"></label>
          <label>Owner<input data-scope="tank" data-field="owner" value="${this._escape(this._config.tank.owner)}"></label>
          <label>Theme<input data-scope="display" data-field="themeColor" value="${this._escape(this._config.display.themeColor)}"></label>
          <label>Tariff<input type="number" step="0.01" data-scope="energy" data-field="tariff" value="${this._escape(this._config.energy.tariff)}"></label>
        </div>
      </article>
    `;
  }

  _sensorPicker(id, sensor) {
    const key = `sensor:${id}`;
    const result = this._searchResults[key];
    return `
      <div class="picker">
        <label>${this._escape(sensor.label)}<input data-scope="sensor" data-id="${this._escape(id)}" data-field="entity_id" value="${this._escape(sensor.entity_id)}" placeholder="sensor.example"></label>
        <div class="mini-grid">
          <label>Min<input type="number" step="0.01" data-scope="sensor" data-id="${this._escape(id)}" data-field="min" value="${this._escape(sensor.min)}"></label>
          <label>Max<input type="number" step="0.01" data-scope="sensor" data-id="${this._escape(id)}" data-field="max" value="${this._escape(sensor.max)}"></label>
        </div>
        <button class="secondary" data-action="search-sensor" data-id="${this._escape(id)}">${result?.loading ? "Finding..." : "Find matches"}</button>
        ${this._candidateList(key, "choose-sensor", id)}
      </div>
    `;
  }

  _equipmentSettings() {
    const quick = ["Return Pump", "Heater", "Skimmer", "ATO", "Wave Maker", "Lights"];
    return `
      <article class="panel">
        <div class="section-head">
          <h3>Equipment</h3>
          <div class="quick-add">${quick.map((label) => `<button class="secondary" data-action="add-equipment" data-label="${this._escape(label)}">+ ${this._escape(label)}</button>`).join("")}</div>
        </div>
        <div class="stack tight">
          ${Object.entries(this._config.equipment || {}).map(([id, item]) => this._equipmentEditor(id, item)).join("") || `<p class="muted">Add equipment to enable safe controls and energy tracking.</p>`}
        </div>
      </article>
    `;
  }

  _equipmentEditor(id, item) {
    const fields = [
      ["switch_entity_id", "Switch", "switch.example"],
      ["power_entity_id", "Power", "sensor.example_power"],
      ["energy_entity_id", "Energy", "sensor.example_energy"],
      ["cost_entity_id", "Cost", "sensor.example_cost"],
    ];
    return `
      <div class="equipment-editor">
        <div class="card-head">
          <label>Name<input data-scope="equipment" data-id="${this._escape(id)}" data-field="label" value="${this._escape(item.label || id)}"></label>
          <button class="danger-text" data-action="remove-equipment" data-id="${this._escape(id)}">Remove</button>
        </div>
        <div class="grid two compact">
          ${fields.map(([field, label, placeholder]) => `
            <div class="picker">
              <label>${label}<input data-scope="equipment" data-id="${this._escape(id)}" data-field="${field}" value="${this._escape(item[field])}" placeholder="${placeholder}"></label>
              <button class="secondary" data-action="search-equipment" data-id="${this._escape(id)}" data-field="${field}">Find matches</button>
              ${this._candidateList(`equipment:${id}:${field}`, "choose-equipment", id, field)}
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  _energySettings() {
    const fields = [
      ["daily_energy_entity_id", "Daily energy"],
      ["weekly_energy_entity_id", "Weekly energy"],
      ["monthly_energy_entity_id", "Monthly energy"],
      ["daily_cost_entity_id", "Daily cost"],
      ["weekly_cost_entity_id", "Weekly cost"],
      ["monthly_cost_entity_id", "Monthly cost"],
    ];
    return `
      <article class="panel">
        <h3>Energy Totals</h3>
        <div class="grid two compact">
          ${fields.map(([field, label]) => `
            <label>${label}<input data-scope="energy" data-field="${field}" value="${this._escape(this._config.energy[field])}" placeholder="sensor.optional"></label>
          `).join("")}
        </div>
      </article>
    `;
  }

  _candidateList(key, action, id, field = "") {
    const result = this._searchResults[key];
    if (!result) return `<p class="hint">Paste an entity ID or find matches.</p>`;
    if (result.error) return `<p class="hint error-text">${this._escape(result.error)}</p>`;
    if (result.loading) return `<p class="hint">Searching Home Assistant...</p>`;
    if (!result.candidates?.length) return `<p class="hint">No matches found. Manual entry still works.</p>`;
    return `
      <div class="candidates">
        ${result.candidates.map((candidate) => `
          <button class="candidate" data-action="${action}" data-id="${this._escape(id)}" data-field="${this._escape(field)}" data-entity="${this._escape(candidate.entity_id)}">
            <strong>${this._escape(candidate.name || candidate.entity_id)}</strong>
            <span>${this._escape(candidate.entity_id)}${candidate.area ? ` · ${this._escape(candidate.area)}` : ""}</span>
          </button>
        `).join("")}
      </div>
    `;
  }

  _setupWizard() {
    const steps = ["Profile", "Sensors", "Equipment", "Finish"];
    return `
      <div class="modal">
        <section class="wizard">
          <button class="close" data-action="close-setup">x</button>
          <div class="stepper">${steps.map((step, index) => `<span class="${index <= this._setupStep ? "on" : ""}">${index + 1}</span>`).join("")}</div>
          ${this._setupStep === 0 ? `<h2>Welcome to OpenReef</h2><p class="muted">Start with your tank name, then map the reef sensors Home Assistant already knows about.</p>${this._profileSettings()}` : ""}
          ${this._setupStep === 1 ? `<h2>Map Sensors</h2><p class="muted">Use the Find matches buttons for clickable suggestions, or paste an entity ID.</p><div class="grid two compact">${Object.entries(this._config.sensors || {}).map(([id, sensor]) => this._sensorPicker(id, sensor)).join("")}</div>` : ""}
          ${this._setupStep === 2 ? `<h2>Map Equipment</h2><p class="muted">Equipment controls remain locked until you arm each device.</p>${this._equipmentSettings()}` : ""}
          ${this._setupStep === 3 ? `<h2>You are ready</h2><p class="muted">Save the setup, then use Mission Control to check mappings before arming controls.</p>${this._mission()}` : ""}
          <footer class="wizard-actions">
            <button class="secondary" data-action="prev-step" ${this._setupStep === 0 ? "disabled" : ""}>Back</button>
            ${this._setupStep < 3 ? `<button class="primary" data-action="next-step">Next</button>` : `<button class="primary" data-action="finish-setup">Finish</button>`}
          </footer>
        </section>
      </div>
    `;
  }

  _styles() {
    return `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          background: #07111a;
          color: #e5edf5;
          font-family: var(--ha-font-family-body, Arial, sans-serif);
        }
        * { box-sizing: border-box; }
        button, input { font: inherit; }
        button { cursor: pointer; }
        button:disabled { cursor: not-allowed; opacity: .45; }
        .page { min-height: 100vh; padding: 24px; background: radial-gradient(circle at 20% 0%, rgba(14, 165, 233, .12), transparent 28%), #07111a; }
        .topbar, .hero, .panel, .stat, .wizard { border: 1px solid #24364a; background: #121f2f; border-radius: 8px; }
        .topbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 22px; margin-bottom: 18px; }
        h1, h2, h3, p { margin: 0; }
        h1 { font-size: clamp(26px, 3vw, 42px); color: #15c8e8; }
        h2 { font-size: 24px; margin-bottom: 8px; }
        h3 { font-size: 17px; margin-bottom: 14px; }
        .eyebrow, .muted, .hint, small, .topbar p, .section-head p, .row span { color: #8da2ba; }
        .eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: 12px; font-weight: 700; margin-bottom: 6px; }
        .actions, .button-row, .quick-add, .wizard-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
        .tabs { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 8px; margin-bottom: 18px; }
        .tabs button, .primary, .secondary, .warning, .candidate, .danger-text { border: 1px solid #294055; border-radius: 8px; padding: 11px 14px; color: #dcecff; background: #172536; }
        .tabs button.active, .primary { background: #10b8d7; border-color: #10b8d7; color: #041019; font-weight: 800; }
        .secondary:hover, .tabs button:hover { border-color: #14b8d4; }
        .warning { background: #47351a; color: #fde68a; border-color: #a16207; }
        .danger-text { color: #fecaca; background: transparent; border-color: #7f1d1d; }
        .notice { padding: 12px 14px; border-radius: 8px; margin-bottom: 12px; background: #0f2c3d; border: 1px solid #075985; }
        .notice.error, .error-text { color: #fecaca; border-color: #7f1d1d; }
        .notice.success { color: #bbf7d0; border-color: #166534; }
        .stack { display: grid; gap: 16px; }
        .stack.tight { gap: 10px; }
        .grid { display: grid; gap: 16px; }
        .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .grid.compact { gap: 12px; }
        .hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 22px; }
        .ok-border { border-color: #22c55e; background: #0b2b24; }
        .warning-border { border-color: #f59e0b; background: #2f2614; }
        .danger-border { border-color: #ef4444; background: #2b171c; }
        .panel, .stat { padding: 18px; }
        .section-head, .card-head, .row { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .row { padding: 12px 0; border-top: 1px solid #223447; align-items: center; }
        .row:first-of-type { border-top: 0; }
        .row div { display: grid; gap: 4px; }
        .pill { display: inline-flex; align-items: center; justify-content: center; min-width: 74px; min-height: 30px; padding: 5px 10px; border-radius: 999px; background: #203247; color: #dbeafe; font-weight: 800; }
        .pill.ok { background: #14532d; color: #bbf7d0; }
        .pill.warning { background: #713f12; color: #fde68a; }
        .pill.critical { background: #7f1d1d; color: #fecaca; }
        .pill.unknown { background: #334155; color: #cbd5e1; }
        .stat { display: grid; gap: 8px; min-height: 150px; }
        .stat strong { font-size: 34px; color: #67e8f9; }
        label { display: grid; gap: 7px; color: #a7b7ca; font-size: 13px; font-weight: 700; }
        input { width: 100%; min-width: 0; border: 1px solid #2b4056; border-radius: 8px; background: #0b1724; color: #f8fafc; padding: 11px 12px; min-height: 42px; }
        .picker { display: grid; gap: 9px; align-content: start; }
        .mini-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .candidates { display: grid; gap: 7px; }
        .candidate { display: grid; gap: 3px; min-width: 0; text-align: left; }
        .candidate strong, .candidate span, small { min-width: 0; overflow-wrap: anywhere; }
        .candidate span { color: #93a4b8; font-size: 12px; }
        .equipment-editor { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0e1a28; }
        .modal { position: fixed; inset: 0; display: grid; place-items: center; padding: 18px; background: rgba(0,0,0,.72); z-index: 10; overflow: hidden; }
        .wizard { position: relative; width: min(1100px, 100%); max-height: min(900px, 92vh); overflow: auto; overscroll-behavior: contain; padding: 28px; display: grid; gap: 18px; box-shadow: 0 24px 80px rgba(0,0,0,.45); }
        .close { position: absolute; top: 14px; right: 14px; width: 38px; height: 38px; border-radius: 50%; border: 1px solid #294055; background: #172536; color: #dcecff; }
        .stepper { display: flex; gap: 10px; justify-content: center; }
        .stepper span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: #203247; color: #94a3b8; font-weight: 800; }
        .stepper span.on { background: #10b8d7; color: #041019; }
        .wizard-actions { justify-content: space-between; padding-top: 8px; }
        .center-card { min-height: 60vh; display: grid; place-items: center; gap: 16px; color: #8da2ba; }
        .spinner { width: 36px; height: 36px; border: 3px solid #203247; border-top-color: #10b8d7; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 900px) {
          .page { padding: 12px; }
          .topbar, .hero, .section-head, .card-head { flex-direction: column; align-items: stretch; }
          .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .grid.two, .grid.three { grid-template-columns: 1fr; }
        }
      </style>
    `;
  }
}

customElements.define("openreef-panel", OpenReefPanel);
