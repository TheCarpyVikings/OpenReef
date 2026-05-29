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
    this._trend = null;
    this._trendRequest = "";
    this._modeConfirm = null;
    this._controlConfirm = null;
    this._equipmentDetail = null;
    this._configDirty = false;
    this._modeCountdownTimer = null;
    this._lastModeAutoReturnRefresh = 0;
    this._equipmentEditors = {};
    this._equipmentEnergyEditors = {};
    this._settingsSections = {
      profile: false,
      mission: false,
      sensors: false,
      equipment: false,
      modes: false,
      alerts: false,
      interlocks: false,
      energy: false,
    };
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config) {
      if (this._shouldRenderForHassUpdate()) {
        this._render();
      }
      return;
    }

    this._renderLoading();
    this._loadConfig();
  }

  _isEditingFormControl() {
    const active = this.shadowRoot.activeElement;
    return Boolean(active?.matches?.("input, textarea, select"));
  }

  _shouldRenderForHassUpdate() {
    if (this._setupOpen || this._trend || this._activeTab === "settings") return false;
    if (this._isEditingFormControl()) return false;
    return true;
  }

  connectedCallback() {
    this._attachEvents();
    this._renderLoading();
    this._loadConfig();
    if (!this._modeCountdownTimer) {
      this._modeCountdownTimer = window.setInterval(() => {
        this._refreshAfterAutoReturnIfDue();
        this._updateModeCountdownElements();
      }, 10000);
    }
  }

  disconnectedCallback() {
    if (this._modeCountdownTimer) {
      window.clearInterval(this._modeCountdownTimer);
      this._modeCountdownTimer = null;
    }
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
      this._configDirty = false;
      this._error = "";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not load OpenReef";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _refreshConfigSilently(message = "") {
    if (!this._hass || this._busy) return false;
    this._busy = true;
    try {
      const result = await this._callWS({ type: "openreef/get_config" });
      this._config = result.config || result.settings || this._config;
      this._sensorMeta = result.sensor_meta || this._sensorMeta;
      this._validation = result.validation || this._validation;
      this._configDirty = false;
      if (message) this._message = message;
      this._error = "";
      return true;
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not refresh OpenReef";
      return false;
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
      this._configDirty = false;
      this._message = "Saved";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not save OpenReef";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _persistConfigSilently(nextConfig = this._config) {
    const result = await this._callWS({
      type: "openreef/save_config",
      config: nextConfig,
    });
    this._config = result.config || nextConfig;
    this._validation = result.validation || null;
    this._configDirty = false;
  }

  _setDirty(dirty = true) {
    this._configDirty = dirty;
    const saveButton = this.shadowRoot.querySelector("[data-action='save']");
    if (saveButton) saveButton.textContent = dirty ? "Save changes" : "Saved";
    const saveState = this.shadowRoot.querySelector(".save-state");
    if (saveState) {
      saveState.textContent = dirty ? "Unsaved changes" : "Saved";
      saveState.classList.toggle("dirty", dirty);
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
    const item = this._config.equipment?.[equipmentId] || {};
    const label = item.label || equipmentId;
    const current = this._stateValue(item.switch_entity_id);
    const desired = current === "on" ? "off" : "on";
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      await this._callWS({ type: "openreef/toggle_equipment", equipment_id: equipmentId });
      this._recordActivity(`${label} turned ${desired}`, "control");
      await this._persistConfigSilently();
      this._message = `${label} turned ${desired}`;
      this._controlConfirm = null;
    } catch (err) {
      const reason = err instanceof Error ? err.message : "Could not toggle equipment";
      this._recordActivity(`${label} toggle blocked: ${reason}`, "warning");
      try {
        await this._persistConfigSilently();
      } catch {
        // Keep the visible control error if activity persistence fails.
      }
      this._error = reason;
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _applyMode(modeId) {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      if (this._configDirty) {
        await this._persistConfigSilently();
      }
      const result = await this._callWS({ type: "openreef/apply_mode", mode_id: modeId });
      const refreshed = await this._callWS({ type: "openreef/get_config" });
      this._config = refreshed.config || this._config;
      this._validation = refreshed.validation || this._validation;
      this._configDirty = false;
      const applied = result.applied?.length || 0;
      const locked = result.skipped_locked?.length || 0;
      const unavailable = result.skipped_missing?.length || 0;
      const wavemakerBlocked = (result.skipped_locked || []).filter(
        (item) => item?.reason === "Display wavemaker automatic restart blocked",
      ).length;
      this._message = `Mode applied: ${applied} changed, ${locked} locked, ${unavailable} unavailable${wavemakerBlocked ? `, ${wavemakerBlocked} display wavemaker restart blocked` : ""}`;
      this._modeConfirm = null;
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not apply mode";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _muteAlert(sensorId, durationMinutes) {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      const result = await this._callWS({
        type: "openreef/mute_alert",
        sensor_id: sensorId,
        duration_minutes: durationMinutes,
      });
      this._config = result.config || this._config;
      this._validation = result.validation || this._validation;
      this._message = durationMinutes > 0 ? "Alert muted" : "Alert unmuted";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not update alert mute";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _clearAlertHistory() {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      const result = await this._callWS({ type: "openreef/clear_alert_history" });
      this._config = result.config || this._config;
      this._validation = result.validation || this._validation;
      this._message = "Alert history cleared";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not clear alert history";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _loadTrend(sensorId, range = this._trend?.range || "24h") {
    const sensor = this._config?.sensors?.[sensorId];
    const entityId = sensor?.entity_id || "";
    const requestId = `${sensorId}:${range}:${Date.now()}`;
    this._trendRequest = requestId;
    this._trend = {
      sensorId,
      entityId,
      range,
      loading: true,
      points: [],
      error: "",
    };
    this._render();

    if (!entityId) {
      if (this._trendRequest !== requestId) return;
      this._trend = {
        sensorId,
        entityId,
        range,
        loading: false,
        points: [],
        error: "Map this sensor before viewing a trend.",
      };
      this._render();
      return;
    }

    try {
      const points = await this._fetchTrendPoints(entityId, range);
      if (this._trendRequest !== requestId) return;
      this._trend = {
        sensorId,
        entityId,
        range,
        loading: false,
        points,
        error: points.length ? "" : this._trendEmptyMessage(range),
      };
    } catch (err) {
      if (this._trendRequest !== requestId) return;
      this._trend = {
        sensorId,
        entityId,
        range,
        loading: false,
        points: [],
        error: err instanceof Error ? err.message : "Could not load trend history.",
      };
    }
    this._render();
  }

  async _fetchTrendPoints(entityId, range) {
    const end = new Date();
    const start = new Date(end.getTime() - this._trendRangeMs(range));
    let statisticPoints = [];

    if (range === "7d" || range === "30d") {
      statisticPoints = await this._fetchStatisticTrendPoints(entityId, start, end, range);
      if (statisticPoints.length >= 2) return statisticPoints;
    }

    const historyPoints = await this._fetchHistoryTrendPoints(entityId, start, end);
    if (historyPoints.length >= 2) return historyPoints;

    return statisticPoints.length ? statisticPoints : historyPoints;
  }

  async _fetchHistoryTrendPoints(entityId, start, end) {
    if (typeof this._hass?.callApi === "function") {
      const params = new URLSearchParams({
        end_time: end.toISOString(),
        filter_entity_id: entityId,
        minimal_response: "1",
        no_attributes: "1",
        significant_changes_only: "0",
      });
      const raw = await this._hass.callApi(
        "GET",
        `history/period/${encodeURIComponent(start.toISOString())}?${params.toString()}`,
      );
      return this._historyPoints(raw, entityId);
    }

    const raw = await this._callWS({
      type: "history/history_during_period",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      entity_ids: [entityId],
      minimal_response: true,
      significant_changes_only: false,
    });
    return this._historyPoints(raw, entityId);
  }

  async _fetchStatisticTrendPoints(entityId, start, end, range) {
    try {
      const raw = await this._callWS({
        type: "recorder/statistics_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        statistic_ids: [entityId],
        period: range === "30d" ? "day" : "hour",
        types: ["mean", "state", "min", "max"],
      });
      return this._statisticsPoints(raw, entityId);
    } catch {
      return [];
    }
  }

  _historySeries(raw, entityId) {
    if (Array.isArray(raw)) {
      if (Array.isArray(raw[0])) return raw[0];
      return raw;
    }
    if (raw && typeof raw === "object") {
      if (Array.isArray(raw[entityId])) return raw[entityId];
      const series = Object.values(raw).find((value) => Array.isArray(value));
      return Array.isArray(series) ? series : [];
    }
    return [];
  }

  _historyTime(item, fallbackTime) {
    const raw =
      item?.start ??
      item?.end ??
      item?.last_updated ??
      item?.last_changed ??
      item?.last_reported ??
      item?.lu ??
      item?.lc ??
      item?.lr;

    if (typeof raw === "number") {
      return raw < 100000000000 ? raw * 1000 : raw;
    }
    if (typeof raw === "string" && raw.trim()) {
      const parsed = Number(raw);
      if (Number.isFinite(parsed)) return parsed < 100000000000 ? parsed * 1000 : parsed;
      const date = Date.parse(raw);
      if (Number.isFinite(date)) return date;
    }
    return fallbackTime;
  }

  _statisticsSeries(raw, entityId) {
    if (!raw || typeof raw !== "object") return [];
    if (Array.isArray(raw[entityId])) return raw[entityId];
    if (raw.statistics && Array.isArray(raw.statistics[entityId])) {
      return raw.statistics[entityId];
    }
    const series = Object.entries(raw)
      .filter(([key]) => key !== "metadata")
      .map(([, value]) => value)
      .find((value) => Array.isArray(value));
    return Array.isArray(series) ? series : [];
  }

  _statisticsPoints(raw, entityId) {
    const series = this._statisticsSeries(raw, entityId);
    const points = series
      .map((item, index) => {
        const rawValue = item?.mean ?? item?.state ?? item?.max ?? item?.min;
        const value = Number.parseFloat(rawValue);
        if (!Number.isFinite(value)) return null;
        return {
          time: this._historyTime(item, Date.now() - (series.length - index - 1) * 60000),
          value,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    return this._downsample(points, 220);
  }

  _historyPoints(raw, entityId) {
    const series = this._historySeries(raw, entityId);
    const now = Date.now();
    const points = series
      .map((item, index) => {
        const state = item?.state ?? item?.s ?? item?.value ?? item?.v;
        const value = Number.parseFloat(state);
        if (!Number.isFinite(value)) return null;
        return {
          time: this._historyTime(item, now - (series.length - index - 1) * 60000),
          value,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time - b.time);

    return this._downsample(points, 180);
  }

  _downsample(points, maxPoints) {
    if (points.length <= maxPoints) return points;
    const sampled = [];
    const step = (points.length - 1) / (maxPoints - 1);
    for (let index = 0; index < maxPoints; index += 1) {
      sampled.push(points[Math.round(index * step)]);
    }
    return sampled;
  }

  _trendRanges() {
    return [
      ["1h", "1 hour", 60 * 60 * 1000],
      ["6h", "6 hours", 6 * 60 * 60 * 1000],
      ["24h", "24 hours", 24 * 60 * 60 * 1000],
      ["7d", "7 days", 7 * 24 * 60 * 60 * 1000],
      ["30d", "30 days", 30 * 24 * 60 * 60 * 1000],
    ];
  }

  _trendRangeMs(range) {
    return this._trendRanges().find(([id]) => id === range)?.[2] || 24 * 60 * 60 * 1000;
  }

  _trendRangeLabel(range) {
    return this._trendRanges().find(([id]) => id === range)?.[1] || "24 hours";
  }

  _trendEmptyMessage(range) {
    if (range === "7d" || range === "30d") {
      return `No long-term statistics or recorder history is available for this ${this._trendRangeLabel(range)} range. Home Assistant may not have kept that much history for this entity yet.`;
    }
    return "No numeric history is available for this sensor yet.";
  }

  _trendCoverageMessage(points, range) {
    if (points.length < 2) return "";
    const requested = this._trendRangeMs(range);
    const first = points[0].time;
    const last = points[points.length - 1].time;
    const actual = last - first;
    if (actual >= requested * 0.65) return "";
    return `Showing ${this._formatTrendTime(first, range)} to ${this._formatTrendTime(last, range)} because Home Assistant only returned part of the requested ${this._trendRangeLabel(range)} range.`;
  }

  _formatTrendTime(timestamp, range = "24h") {
    const date = new Date(timestamp);
    if (range === "1h" || range === "6h" || range === "24h") {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
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
        this._equipmentDetail = null;
        this._controlConfirm = null;
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
      if (action === "setup-step") {
        this._setupStep = Math.max(0, Math.min(Number(target.dataset.step || 0), 3));
        this._render();
      }
      if (action === "finish-setup") {
        this._config.display.setupComplete = true;
        this._setupOpen = false;
        this._recordActivity("Setup completed");
        this._saveConfig();
      }
      if (action === "save") {
        this._recordActivity("Settings saved");
        this._saveConfig();
      }
      if (action === "validate") this._validateConfig();
      if (action === "mute-alert") this._muteAlert(id, Number(target.dataset.minutes || 60));
      if (action === "unmute-alert") this._muteAlert(id, 0);
      if (action === "clear-alert-history") this._clearAlertHistory();
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
      if (action === "search-energy") {
        this._searchEntities(`energy:${field}`, this._energyTarget(field, target.dataset.label));
      }
      if (action === "choose-sensor") {
        this._config.sensors[id].entity_id = target.dataset.entity;
        delete this._searchResults[`sensor:${id}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "choose-equipment") {
        this._config.equipment[id][field] = target.dataset.entity;
        this._equipmentEditors[id] = true;
        delete this._searchResults[`equipment:${id}:${field}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "choose-energy") {
        this._config.energy[field] = target.dataset.entity;
        delete this._searchResults[`energy:${field}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "hide-matches") {
        delete this._searchResults[target.dataset.key];
        this._render();
      }
      if (action === "toggle-sensor") {
        const sensor = this._config.sensors[id];
        sensor.enabled = !this._sensorEnabled(sensor);
        delete this._searchResults[`sensor:${id}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "setup-sensor-preset") {
        this._applySensorPreset(id);
        this._render();
      }
      if (action === "setup-add-starter-equipment") this._addStarterEquipment();
      if (action === "add-custom-mode") this._addCustomMode();
      if (action === "remove-custom-mode") this._removeCustomMode(target.dataset.mode);
      if (action === "add-mode-schedule") this._addModeSchedule();
      if (action === "remove-mode-schedule") this._removeModeSchedule(target.dataset.schedule);
      if (action === "toggle-schedule-day") {
        this._toggleScheduleDay(target.dataset.schedule, target.dataset.day);
        this._render();
      }
      if (action === "add-equipment") this._addEquipment(target.dataset.label);
      if (action === "remove-equipment") {
        const removed = this._config.equipment[id]?.label || id;
        delete this._config.equipment[id];
        Object.values(this._config.modePreviews || {}).forEach((preview) => delete preview[id]);
        this._recordActivity(`Removed equipment: ${removed}`);
        this._setDirty(true);
        this._render();
      }
      if (action === "toggle-armed") {
        const equipment = this._config.equipment[id];
        equipment.armed = !equipment.armed;
        this._recordActivity(`${equipment.label || id} ${equipment.armed ? "armed" : "disarmed"}`, "control");
        this._saveConfig();
      }
      if (action === "toggle-equipment") {
        const equipment = this._config.equipment[id] || {};
        if (this._requiresControlConfirm(id, equipment)) {
          this._controlConfirm = id;
          this._render();
        } else {
          this._toggleEquipment(id);
        }
      }
      if (action === "confirm-toggle-equipment") this._toggleEquipment(id);
      if (action === "close-control-confirm") {
        this._controlConfirm = null;
        this._render();
      }
      if (action === "toggle-equipment-editor") {
        this._equipmentEditors[id] = !this._equipmentEditorOpen(id);
        this._render();
      }
      if (action === "toggle-equipment-energy") {
        this._equipmentEnergyEditors[id] = !this._equipmentEnergyOpen(id);
        this._render();
      }
      if (action === "show-equipment-detail") {
        this._equipmentDetail = id;
        this._render();
      }
      if (action === "close-equipment-detail") {
        this._equipmentDetail = null;
        this._render();
      }
      if (action === "set-theme") {
        this._config.display.themeColor = target.dataset.color;
        this._setDirty(true);
        this._render();
      }
      if (action === "set-mode") {
        const modeId = target.dataset.mode || "running";
        const hasRestorePlan = this._modeActionRows("running").length > 0;
        if (modeId !== "running" || (this._activeMode() !== "running" && hasRestorePlan)) {
          this._modeConfirm = modeId;
          this._render();
          return;
        }
        if (this._activeMode() !== "running") this._applyMode("running");
      }
      if (action === "apply-mode") this._applyMode(target.dataset.mode);
      if (action === "apply-mode-preset") {
        this._applyModePreset(target.dataset.mode, target.dataset.preset);
        this._render();
      }
      if (action === "close-mode-confirm") {
        this._modeConfirm = null;
        this._render();
      }
      if (action === "toggle-settings-section") {
        this._settingsSections[id] = !this._settingsSectionOpen(id);
        this._render();
      }
      if (action === "clear-activity") {
        this._config.activity = [];
        this._saveConfig();
      }
      if (action === "show-trend") this._loadTrend(id);
      if (action === "trend-range") this._loadTrend(id, target.dataset.range);
      if (action === "close-trend") {
        this._trend = null;
        this._trendRequest = "";
        this._render();
      }
      if (action === "refresh-trend") this._loadTrend(id, this._trend?.range || "24h");
    });

    const handleFieldInput = (event) => {
      const target = event.target;
      if (!target.dataset) return;
      const scope = target.dataset.scope;
      const id = target.dataset.id;
      const field = target.dataset.field;
      const value = target.type === "checkbox" ? target.checked : target.type === "number" ? Number(target.value) : target.value;

      if (scope === "tank") this._config.tank[field] = value;
      if (scope === "display") this._config.display[field] = value;
      if (scope === "sensor") this._config.sensors[id][field] = value;
      if (scope === "equipment") {
        this._config.equipment[id][field] = value;
        if (field === "type") {
          const displayWavemaker = value === "display_wavemaker";
          this._config.equipment[id].displayWavemaker = displayWavemaker;
          this._config.equipment[id].allowAutoRestart = displayWavemaker ? false : true;
          this._config.equipment[id].wavemakerNotifications = displayWavemaker;
        }
      }
      if (scope === "energy") this._config.energy[field] = value;
      if (scope === "alerts") {
        this._config.alerts = this._config.alerts || {};
        this._config.alerts[field] = value;
      }
      if (scope === "interlocks") {
        this._config.interlocks = this._config.interlocks || {};
        this._config.interlocks[field] = value;
      }
      if (scope === "mode-preview") {
        const modeId = target.dataset.mode;
        const equipmentId = target.dataset.equipment;
        this._config.modePreviews = this._config.modePreviews || { feed: {}, maintenance: {} };
        this._config.modePreviews[modeId] = this._config.modePreviews[modeId] || {};
        this._config.modePreviews[modeId][equipmentId] = value;
      }
      if (scope === "mode-timer") {
        const modeId = target.dataset.mode;
        this._config.modeTimers = this._config.modeTimers || {};
        this._config.modeTimers[modeId] = this._config.modeTimers[modeId] || {};
        this._config.modeTimers[modeId][field] = field === "durationMinutes"
          ? Math.max(0, Math.min(Number(value), 720))
          : value;
      }
      if (scope === "mode-settings") {
        const modeId = target.dataset.mode;
        this._config.modeSettings = this._config.modeSettings || {};
        this._config.modeSettings[modeId] = this._config.modeSettings[modeId] || {};
        this._config.modeSettings[modeId][field] = value;
      }
      if (scope === "mode-schedule-global") {
        this._config.modeSchedule = this._modeSchedule();
        this._config.modeSchedule[field] = value;
      }
      if (scope === "mode-schedule") {
        const schedule = this._scheduleItem(id);
        if (schedule) schedule[field] = value;
      }
      if (scope === "mission-card") {
        this._config.display.missionCards = this._missionCards();
        this._config.display.missionCards[id] = value;
      }
      if (scope) this._setDirty(true);
      if (scope === "display" && field === "themeColor") this._render();
      if (
        (scope === "mode-schedule" || scope === "mode-schedule-global" || (scope === "equipment" && field === "type"))
        && event.type === "change"
      ) this._render();
    };

    this.shadowRoot.addEventListener("input", handleFieldInput);
    this.shadowRoot.addEventListener("change", handleFieldInput);
  }

  _addEquipment(label) {
    const base = this._slug(label || "Equipment");
    let id = base;
    let suffix = 2;
    while (this._config.equipment[id]) {
      id = `${base}_${suffix}`;
      suffix += 1;
    }
    const type = this._inferEquipmentProfile(label, id);
    const displayWavemaker = type === "display_wavemaker";
    this._config.equipment[id] = {
      label: label || "Equipment",
      type,
      switch_entity_id: "",
      power_entity_id: "",
      energy_entity_id: "",
      cost_entity_id: "",
      armed: false,
      displayWavemaker,
      allowAutoRestart: !displayWavemaker,
      wavemakerNotifications: displayWavemaker,
    };
    this._equipmentEditors[id] = true;
    this._recordActivity(`Added equipment: ${label || "Equipment"}`);
    this._setDirty(true);
    this._render();
  }

  _equipmentLabelExists(label) {
    const lower = String(label || "").toLowerCase();
    return Object.values(this._config.equipment || {}).some((item) => String(item.label || "").toLowerCase() === lower);
  }

  _looksLikeDisplayWavemaker(label, id = "") {
    const text = `${id} ${label || ""}`.toLowerCase();
    return text.includes("wave") || text.includes("wavemaker") || text.includes("powerhead") || text.includes("gyre");
  }

  _equipmentProfileChoices() {
    return [
      ["return_pump", "Return pump"],
      ["display_wavemaker", "Display wavemaker"],
      ["flow_pump", "Flow pump"],
      ["heater", "Heater / chiller"],
      ["skimmer", "Skimmer"],
      ["ato", "ATO / top-off"],
      ["lighting", "Lighting"],
      ["doser", "Doser"],
      ["filtration", "Filter / reactor"],
      ["other", "Other"],
    ];
  }

  _equipmentProfileLabel(profile) {
    return this._equipmentProfileChoices().find(([id]) => id === profile)?.[1] || "Other";
  }

  _inferEquipmentProfile(label, id = "") {
    const text = `${id} ${label || ""}`.toLowerCase();
    if (this._looksLikeDisplayWavemaker(label, id)) return "display_wavemaker";
    if (text.includes("return")) return "return_pump";
    if (text.includes("heater") || text.includes("chiller")) return "heater";
    if (text.includes("skimmer")) return "skimmer";
    if (text.includes("ato") || text.includes("top off") || text.includes("rodi")) return "ato";
    if (text.includes("light") || text.includes("kessil") || text.includes("hydra")) return "lighting";
    if (text.includes("doser") || text.includes("dosing")) return "doser";
    if (text.includes("filter") || text.includes("reactor")) return "filtration";
    if (text.includes("pump")) return "flow_pump";
    return "other";
  }

  _addStarterEquipment() {
    const starter = ["Return Pump", "Heater", "Lights", "Skimmer", "ATO"];
    let added = 0;
    starter.forEach((label) => {
      if (this._equipmentLabelExists(label)) return;
      const base = this._slug(label);
      let id = base;
      let suffix = 2;
      while (this._config.equipment[id]) {
        id = `${base}_${suffix}`;
        suffix += 1;
      }
      const type = this._inferEquipmentProfile(label, id);
      const displayWavemaker = type === "display_wavemaker";
      this._config.equipment[id] = {
        label,
        type,
        switch_entity_id: "",
        power_entity_id: "",
        energy_entity_id: "",
        cost_entity_id: "",
        armed: false,
        displayWavemaker,
        allowAutoRestart: !displayWavemaker,
        wavemakerNotifications: displayWavemaker,
      };
      this._equipmentEditors[id] = true;
      added += 1;
    });
    this._recordActivity(added ? `Added ${added} starter equipment item(s)` : "Starter equipment already exists");
    this._setDirty(true);
    this._render();
  }

  _customModes() {
    return Array.isArray(this._config?.customModes)
      ? this._config.customModes.filter((mode) => mode && typeof mode.id === "string")
      : [];
  }

  _editableModeIds() {
    return ["feed", "maintenance", ...this._customModes().map((mode) => mode.id)];
  }

  _isCustomMode(modeId) {
    return this._customModes().some((mode) => mode.id === modeId);
  }

  _modeSlug(label) {
    const slug = this._slug(label || "Custom Mode");
    return ["running", "feed", "maintenance"].includes(slug) ? `custom_${slug}` : slug;
  }

  _addCustomMode() {
    this._config.customModes = this._customModes();
    const existing = new Set(this._modeChoices().map(([modeId]) => modeId));
    let suffix = this._config.customModes.length + 1;
    let label = suffix > 1 ? `Custom Mode ${suffix}` : "Custom Mode";
    let modeId = this._modeSlug(label);
    while (existing.has(modeId)) {
      suffix += 1;
      label = `Custom Mode ${suffix}`;
      modeId = this._modeSlug(label);
    }
    this._config.customModes.push({ id: modeId });
    this._config.modeSettings = this._config.modeSettings || {};
    this._config.modeSettings[modeId] = {
      label,
      description: "Custom manual mode. Set the equipment plan before applying.",
    };
    this._config.modePreviews = this._config.modePreviews || {};
    this._config.modePreviews[modeId] = {};
    this._config.modeTimers = this._config.modeTimers || {};
    this._config.modeTimers[modeId] = { durationMinutes: 0, autoReturn: false };
    this._recordActivity(`Added custom mode: ${label}`);
    this._setDirty(true);
    this._render();
  }

  _removeCustomMode(modeId) {
    if (!this._isCustomMode(modeId) || this._activeMode() === modeId) return;
    const mode = this._modeConfig(modeId);
    this._config.customModes = this._customModes().filter((item) => item.id !== modeId);
    delete this._config.modeSettings?.[modeId];
    delete this._config.modePreviews?.[modeId];
    delete this._config.modeTimers?.[modeId];
    if (Array.isArray(this._config.modeSchedule?.items)) {
      this._config.modeSchedule.items = this._config.modeSchedule.items.filter((item) => item?.mode !== modeId);
    }
    this._recordActivity(`Removed custom mode: ${mode.label}`);
    this._setDirty(true);
    this._render();
  }

  _modeSchedule() {
    this._config.modeSchedule = this._config.modeSchedule || { enabled: false, items: [], lastRuns: {} };
    this._config.modeSchedule.items = Array.isArray(this._config.modeSchedule.items)
      ? this._config.modeSchedule.items
      : [];
    this._config.modeSchedule.lastRuns = this._config.modeSchedule.lastRuns || {};
    return this._config.modeSchedule;
  }

  _scheduleItem(scheduleId) {
    return this._modeSchedule().items.find((item) => item?.id === scheduleId);
  }

  _scheduleDays() {
    return [
      ["mon", "Mon"],
      ["tue", "Tue"],
      ["wed", "Wed"],
      ["thu", "Thu"],
      ["fri", "Fri"],
      ["sat", "Sat"],
      ["sun", "Sun"],
    ];
  }

  _addModeSchedule() {
    const schedule = this._modeSchedule();
    const modeId = this._editableModeIds()[0] || "feed";
    const id = `schedule_${Date.now().toString(36)}`;
    schedule.items.push({
      id,
      enabled: false,
      mode: modeId,
      time: "12:00",
      days: [],
      requireAutoReturn: true,
    });
    this._recordActivity("Added mode schedule");
    this._setDirty(true);
    this._render();
  }

  _removeModeSchedule(scheduleId) {
    const schedule = this._modeSchedule();
    schedule.items = schedule.items.filter((item) => item?.id !== scheduleId);
    delete schedule.lastRuns?.[scheduleId];
    this._recordActivity("Removed mode schedule");
    this._setDirty(true);
    this._render();
  }

  _toggleScheduleDay(scheduleId, day) {
    const item = this._scheduleItem(scheduleId);
    if (!item) return;
    if (day === "all") {
      item.days = [];
    } else {
      const days = Array.isArray(item.days) ? item.days : [];
      item.days = days.includes(day)
        ? days.filter((value) => value !== day)
        : [...days, day];
    }
    this._setDirty(true);
  }

  _applySensorPreset(preset) {
    const sensors = this._config.sensors || {};
    Object.entries(sensors).forEach(([id, sensor]) => {
      if (preset === "tank") sensor.enabled = sensor.group !== "room";
      if (preset === "all") sensor.enabled = true;
      if (preset === "minimal") sensor.enabled = id === "temp";
    });
    this._recordActivity(`Setup sensor preset selected: ${preset}`);
    this._setDirty(true);
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

  _energyTarget(field, label = "") {
    const words = String(label || field)
      .replaceAll("_", " ")
      .replaceAll("entity id", "")
      .trim();
    const lowerWords = words.toLowerCase();
    let period = "";
    if (lowerWords.includes("daily")) period = "daily";
    if (lowerWords.includes("weekly")) period = "weekly";
    if (lowerWords.includes("monthly")) period = "monthly";

    if (field.includes("cost")) {
      return {
        id: field,
        label: words,
        domains: ["sensor"],
        keywords: [words, period, "cost", "money", "price", "tariff"],
        prefer: ["reef", "tank", "aquarium", period, "cost", "energy"],
        avoid: [],
        device_classes: ["monetary"],
        units: ["GBP", "gbp", "£"],
      };
    }

    return {
      id: field,
      label: words,
      domains: ["sensor"],
      keywords: [words, period, "energy", "kwh", "consumption"],
      prefer: ["reef", "tank", "aquarium", period, "energy"],
      avoid: [],
      device_classes: ["energy"],
      units: ["kWh", "Wh"],
      state_classes: ["total", "total_increasing"],
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

  _entityStatus(entityId) {
    if (!entityId) return ["unknown", "Not mapped"];
    const state = this._state(entityId);
    if (!state) return ["critical", "Missing"];
    if (state.state === "unavailable") return ["critical", "Unavailable"];
    if (state.state === "unknown") return ["warning", "Unknown"];
    return ["ok", "Live"];
  }

  _bestEntityStatus(entityIds) {
    const mapped = entityIds.filter(Boolean);
    if (!mapped.length) return ["unknown", "Not mapped"];
    const statuses = mapped.map((entityId) => this._entityStatus(entityId));
    return statuses.find(([status]) => status === "ok") || statuses[0];
  }

  _lastChangedLabel(entityId) {
    const state = this._state(entityId);
    const raw = state?.last_changed || state?.last_updated || state?.last_reported;
    if (!raw) return "No timestamp";
    const date = new Date(raw);
    if (!Number.isFinite(date.getTime())) return "No timestamp";
    return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  _friendlyEntityName(entityId) {
    const state = this._state(entityId);
    return state?.attributes?.friendly_name || entityId || "Not mapped";
  }

  _alertMutedUntil(sensorId) {
    const value = this._config?.alerts?.muteUntil?.[sensorId];
    if (!value) return null;
    const mutedUntil = new Date(value);
    if (!Number.isFinite(mutedUntil.getTime()) || mutedUntil <= new Date()) return null;
    return mutedUntil;
  }

  _isAlertMuted(sensorId) {
    return Boolean(this._alertMutedUntil(sensorId));
  }

  _formatMutedUntil(sensorId) {
    const mutedUntil = this._alertMutedUntil(sensorId);
    if (!mutedUntil) return "";
    return mutedUntil.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  _sensorStatus(sensor, sensorId = "") {
    if (!this._sensorEnabled(sensor)) return "disabled";
    if (sensorId && this._isAlertMuted(sensorId)) return "muted";
    if (sensor.alertsEnabled === false) return "muted";
    const value = this._number(sensor.entity_id);
    if (value === null) return "unknown";
    if (value < Number(sensor.min) || value > Number(sensor.max)) return "critical";
    const bufferPercent = Math.max(0, Math.min(Number(sensor.warningBuffer ?? 10), 50)) / 100;
    const buffer = (Number(sensor.max) - Number(sensor.min)) * bufferPercent;
    if (value < Number(sensor.min) + buffer || value > Number(sensor.max) - buffer) return "warning";
    return "ok";
  }

  _sensorStatusLabel(status) {
    if (status === "muted") return "muted";
    if (status === "unknown") return "not reporting";
    if (status === "ok") return "resolved";
    return status;
  }

  _format(value, digits = 1) {
    return Number.isFinite(value) ? Number(value).toFixed(digits) : "--";
  }

  _energyWh(entityId) {
    const value = this._number(entityId);
    if (value === null) return null;
    const unit = String(this._state(entityId)?.attributes?.unit_of_measurement || "").toLowerCase();
    return unit === "kwh" ? value * 1000 : value;
  }

  _formatEnergyWh(entityId) {
    const value = this._energyWh(entityId);
    return value === null ? "-- Wh" : `${Number(value).toFixed(0)} Wh`;
  }

  _energyCost(energyEntityId, mappedCost) {
    if (mappedCost !== null) return mappedCost;
    const value = this._number(energyEntityId);
    if (value === null) return null;
    const unit = String(this._state(energyEntityId)?.attributes?.unit_of_measurement || "").toLowerCase();
    const energyKwh = unit === "kwh" ? value : value / 1000;
    return energyKwh * Number(this._config.energy.tariff || 0);
  }

  _formatMoney(value) {
    return value === null ? "--" : `${Number(value).toFixed(2)} ${this._config.energy.currency || "GBP"}`;
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

  _themeColor() {
    const color = this._config?.display?.themeColor || "#00b4d8";
    return /^#[0-9a-f]{6}$/i.test(color) ? color : "#00b4d8";
  }

  _themeChoices() {
    return [
      ["#00b4d8", "Reef Blue"],
      ["#14b8a6", "Lagoon Teal"],
      ["#22c55e", "Coral Green"],
      ["#f59e0b", "Sunset Amber"],
      ["#f97316", "Clownfish Orange"],
      ["#e879f9", "Coral Pink"],
      ["#8b5cf6", "Royal Violet"],
      ["#38bdf8", "Clear Sky"],
    ];
  }

  _modeBaseChoices() {
    return [
      ["running", "Running", "Returns from Feed or Maintenance by restoring captured armed equipment states."],
      ["feed", "Feed", "Temporarily changes selected armed equipment after confirmation."],
      ["maintenance", "Maintenance", "Applies a hands-in-tank equipment plan after confirmation."],
    ];
  }

  _modeConfig(modeId) {
    const base = this._modeBaseChoices().find(([id]) => id === modeId) || [modeId, modeId, ""];
    const settings = this._config?.modeSettings?.[modeId] || {};
    const label = typeof settings.label === "string" && settings.label.trim() ? settings.label.trim() : base[1];
    const description = typeof settings.description === "string" && settings.description.trim()
      ? settings.description.trim()
      : base[2];
    return { id: modeId, label, description };
  }

  _modeChoices() {
    return [
      ...this._modeBaseChoices().map(([id]) => id),
      ...this._customModes().map((mode) => mode.id),
    ].map((id) => {
      const mode = this._modeConfig(id);
      return [mode.id, mode.label, mode.description];
    });
  }

  _activeMode() {
    const active = this._config?.mode?.active || "running";
    return this._modeChoices().some(([id]) => id === active) ? active : "running";
  }

  _activeModeLabel() {
    return this._modeChoices().find(([id]) => id === this._activeMode())?.[1] || "Running";
  }

  _modeDurationLabel() {
    const raw = this._config?.mode?.startedAt;
    if (!raw) return "Not started yet";
    const started = new Date(raw);
    if (!Number.isFinite(started.getTime())) return "Not started yet";
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
    if (elapsedSeconds < 60) return "Less than 1 minute";
    const minutes = Math.floor(elapsedSeconds / 60);
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours < 24) {
      return remainingMinutes
        ? `${hours}h ${remainingMinutes}m`
        : `${hours} hour${hours === 1 ? "" : "s"}`;
    }
    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? "" : "s"}`;
  }

  _formatDurationMs(ms) {
    if (!Number.isFinite(ms) || ms <= 0) return "Expired";
    const totalSeconds = Math.ceil(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes < 1) return `${seconds}s`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours < 1) return `${minutes}m`;
    return `${hours}h ${remainingMinutes}m`;
  }

  _modeTimerConfig(modeId) {
    const defaults = modeId === "maintenance"
      ? { durationMinutes: 60, autoReturn: false }
      : modeId === "feed"
        ? { durationMinutes: 10, autoReturn: false }
        : { durationMinutes: 0, autoReturn: false };
    const timer = this._config?.modeTimers?.[modeId] || {};
    const duration = Number(timer.durationMinutes ?? defaults.durationMinutes);
    return {
      durationMinutes: Number.isFinite(duration) ? Math.max(0, Math.min(duration, 720)) : defaults.durationMinutes,
      autoReturn: Boolean(timer.autoReturn ?? defaults.autoReturn),
    };
  }

  _activeModeExpiresAt() {
    const raw = this._config?.mode?.expiresAt;
    if (!raw) return null;
    const expiresAt = new Date(raw);
    return Number.isFinite(expiresAt.getTime()) ? expiresAt : null;
  }

  _activeModeCountdownText() {
    const active = this._activeMode();
    if (active === "running") return "No timer active";
    const expiresAt = this._activeModeExpiresAt();
    if (!expiresAt) return "No timer set";
    const remaining = expiresAt.getTime() - Date.now();
    const autoReturn = Boolean(this._config?.mode?.autoReturn);
    return remaining > 0
      ? `${this._formatDurationMs(remaining)} left${autoReturn ? " - auto-return on" : ""}`
      : autoReturn
        ? "Auto-return due"
        : "Timer expired";
  }

  _modeTimerExpired() {
    const expiresAt = this._activeModeExpiresAt();
    return this._activeMode() !== "running" && Boolean(expiresAt) && expiresAt.getTime() <= Date.now();
  }

  _modeTimerSummary(modeId) {
    if (modeId === "running") return "No timer is used for Running.";
    const timer = this._modeTimerConfig(modeId);
    if (!timer.durationMinutes) return "No timer set.";
    return `${timer.durationMinutes} minute timer; auto-return ${timer.autoReturn ? "on" : "off"}.`;
  }

  _updateModeCountdownElements() {
    const text = this._activeModeCountdownText();
    this.shadowRoot.querySelectorAll("[data-mode-countdown]").forEach((element) => {
      element.textContent = text;
    });
  }

  _refreshAfterAutoReturnIfDue() {
    if (!this._config || this._configDirty || this._setupOpen || this._trend) return;
    if (this._isEditingFormControl()) return;
    const mode = this._config.mode || {};
    if (this._activeMode() === "running" || !mode.autoReturn) return;
    const expiresAt = this._activeModeExpiresAt();
    if (!expiresAt || expiresAt.getTime() > Date.now()) return;
    const now = Date.now();
    if (now - this._lastModeAutoReturnRefresh < 15000) return;
    this._lastModeAutoReturnRefresh = now;
    this._refreshConfigSilently("Auto-return status refreshed");
  }

  _modeStatusDetail() {
    const active = this._activeMode();
    if (active === "running") {
      return "Normal monitoring. No mode equipment plan is active.";
    }
    const restoreRows = this._modeActionRows("running");
    const timerText = this._activeModeCountdownText();
    const timerSuffix = this._modeTimerExpired() && !this._config?.mode?.autoReturn
      ? "Timer expired. Return to Running when ready."
      : `${timerText}.`;
    if (!restoreRows.length) return `No restore states were captured for Running yet. ${timerSuffix}`;
    const ready = restoreRows.filter((row) => row.status === "ready").length;
    return `${restoreRows.length} captured state${restoreRows.length === 1 ? "" : "s"} for Running. ${ready} ready to restore. ${timerSuffix}`;
  }

  _modePresetChoices(modeId) {
    if (modeId === "feed") {
      return [
        ["reef-feed", "Reef feed", "Turn off return pump, flow profiles, and skimmer."],
        ["flow-only", "Flow only", "Turn off flow devices, leave filtration unchanged."],
        ["clear", "Clear plan", "Leave all equipment unchanged."],
      ];
    }
    if (modeId === "maintenance") {
      return [
        ["hands-in-tank", "Hands in tank", "Turn off heater, ATO, skimmer, and display flow profiles."],
        ["waterline", "Waterline work", "Turn off top-off and skimmer profiles."],
        ["clear", "Clear plan", "Leave all equipment unchanged."],
      ];
    }
    return [];
  }

  _modePresetState(modeId, preset, equipmentId, item) {
    const profile = this._equipmentProfile(equipmentId, item);
    const isReturn = profile === "return_pump";
    const isWave = profile === "display_wavemaker" || profile === "flow_pump";
    const isSkimmer = profile === "skimmer";
    const isPump = isReturn || isWave;
    const isTopOff = profile === "ato";
    const isTemperature = profile === "heater";

    if (preset === "clear") return "unchanged";
    if (modeId === "feed" && preset === "reef-feed") {
      return isReturn || isWave || isSkimmer ? "off" : "unchanged";
    }
    if (modeId === "feed" && preset === "flow-only") {
      return isPump ? "off" : "unchanged";
    }
    if (modeId === "maintenance" && preset === "hands-in-tank") {
      return isTemperature || isTopOff || isSkimmer || isWave ? "off" : "unchanged";
    }
    if (modeId === "maintenance" && preset === "waterline") {
      return isTopOff || isSkimmer ? "off" : "unchanged";
    }
    return "unchanged";
  }

  _applyModePreset(modeId, preset) {
    const equipment = Object.entries(this._config.equipment || {});
    this._config.modePreviews = this._config.modePreviews || { feed: {}, maintenance: {} };
    this._config.modePreviews[modeId] = {};
    equipment.forEach(([equipmentId, item]) => {
      const state = this._modePresetState(modeId, preset, equipmentId, item);
      if (state === "on" || state === "off") {
        this._config.modePreviews[modeId][equipmentId] = state;
      }
    });
    const modeLabel = this._modeChoices().find(([id]) => id === modeId)?.[1] || modeId;
    const presetLabel = this._modePresetChoices(modeId).find(([id]) => id === preset)?.[1] || preset;
    this._recordActivity(`${modeLabel} preset selected: ${presetLabel}`);
    this._setDirty(true);
  }

  _sensorGroupLabel(sensor) {
    return sensor?.group === "room" ? "Room" : "Tank";
  }

  _sensorGroupClass(sensor) {
    return sensor?.group === "room" ? "room-card" : "tank-card";
  }

  _sensorEnabled(sensor) {
    return Boolean(sensor?.enabled);
  }

  _enabledSensors() {
    return Object.entries(this._config.sensors || {}).filter(([, sensor]) => this._sensorEnabled(sensor));
  }

  _sensorAlerts(sensors = this._enabledSensors()) {
    return sensors
      .filter(([, sensor]) => sensor.alertsEnabled !== false)
      .map(([id, sensor]) => {
        const status = this._sensorStatus(sensor, id);
        if (!["critical", "warning", "unknown"].includes(status)) return null;
        const value = this._number(sensor.entity_id);
        const display = id === "ph" ? this._format(value, 2) : this._format(value, 1);
        const range = `${sensor.min} - ${sensor.max} ${sensor.unit || ""}`.trim();
        const title = status === "unknown" ? `${sensor.label} is not reporting` : `${sensor.label} ${status === "critical" ? "outside range" : "near threshold"}`;
        const detail = status === "unknown" ? (sensor.entity_id || "No entity mapped") : `${display} ${sensor.unit || ""} · target ${range}`;
        return { id, sensor, status, title, detail };
      })
      .filter(Boolean);
  }

  _equipmentType(id, item) {
    return this._equipmentProfileLabel(this._equipmentProfile(id, item));
  }

  _equipmentProfile(id, item) {
    const explicit = this._equipmentProfileChoices().some(([profile]) => profile === item?.type)
      ? item.type
      : "";
    if (explicit) return explicit;
    if (item?.displayWavemaker) return "display_wavemaker";
    return this._inferEquipmentProfile(item?.label, id);
  }

  _equipmentGroups(rows = Object.entries(this._config.equipment || {})) {
    const order = this._equipmentProfileChoices().map(([, label]) => label);
    const groups = new Map(order.map((label) => [label, []]));
    rows.forEach(([id, item]) => {
      groups.get(this._equipmentType(id, item)).push([id, item]);
    });
    return order.map((label) => [label, groups.get(label)]).filter(([, items]) => items.length);
  }

  _isDisplayWavemaker(id, item) {
    return this._equipmentProfile(id, item) === "display_wavemaker";
  }

  _blocksDisplayWavemakerAutoRestart(item, desiredState = "on", id = "") {
    return desiredState === "on" && this._isDisplayWavemaker(id, item) && item.allowAutoRestart !== true;
  }

  _equipmentStateClass(item) {
    if (!item?.switch_entity_id) return "unknown";
    const state = this._stateValue(item.switch_entity_id);
    if (state === "on") return "ok";
    if (state === "off") return item.armed ? "unknown" : "disabled";
    return "critical";
  }

  _equipmentStateLabel(item) {
    if (!item?.switch_entity_id) return "Not mapped";
    const state = this._stateValue(item.switch_entity_id);
    if (state === "on") return "On";
    if (state === "off") return "Off";
    return state;
  }

  _equipmentRisk(id, item) {
    const profile = this._equipmentProfile(id, item);
    if (profile === "display_wavemaker") {
      return ["critical", "Display risk", "Display wavemakers can injure livestock if restarted while fish are inside. Inspect the tank before turning them on."];
    }
    if (profile === "ato") {
      return ["critical", "Critical", "Top-off equipment can change salinity if left running."];
    }
    if (profile === "return_pump") {
      return ["critical", "Critical", "Return pumps affect flow through the whole system."];
    }
    if (profile === "heater") {
      return ["critical", "Critical", "Temperature equipment can move the tank quickly."];
    }
    if (profile === "skimmer") {
      return ["warning", "Caution", "Skimmers can overflow if flow conditions change."];
    }
    if (profile === "doser") {
      return ["critical", "Critical", "Dosing equipment can change chemistry quickly."];
    }
    return ["ok", "Normal", "Standard manual control."];
  }

  _equipmentUseHint(id, item) {
    const profile = this._equipmentProfile(id, item);
    if (profile === "display_wavemaker") {
      return "Automatic restart is blocked by default. If a display wavemaker stays off, inspect the tank and restart manually because flow is critical for corals.";
    }
    if (profile === "heater") {
      return "Best kept armed only with a live tank temperature sensor and heater interlock warning enabled.";
    }
    if (profile === "ato") {
      return "Top-off control should stay deliberate. Use the ATO runtime interlock before unattended use.";
    }
    if (profile === "return_pump") {
      return "Main circulation device. Feed or maintenance plans should be reviewed before turning this off.";
    }
    if (profile === "skimmer") {
      return "Often paused during feeding or maintenance to avoid overflow after water level changes.";
    }
    if (profile === "flow_pump") {
      return "Flow equipment is a good candidate for Feed mode presets.";
    }
    if (profile === "lighting") {
      return "Lighting is usually left unchanged by Feed and Maintenance presets.";
    }
    if (profile === "doser") {
      return "Keep dosing controls deliberate and review chemistry before arming manual control.";
    }
    if (profile === "filtration") {
      return "Filtration and reactor controls can affect nutrient export and water clarity.";
    }
    return "Use manual control only when the mapped switch and reef impact are clear.";
  }

  _controlAvailable(item) {
    if (!item?.switch_entity_id) return false;
    if (!item.armed) return false;
    const state = this._stateValue(item.switch_entity_id);
    return state === "on" || state === "off";
  }

  _controlBlockReason(item) {
    if (!item?.switch_entity_id) return "Map a switch in Settings";
    if (!item.armed) return "Disarmed in Settings";
    const state = this._stateValue(item.switch_entity_id);
    if (state !== "on" && state !== "off") return `Switch is ${state}`;
    return "Manual control armed";
  }

  _controlActionLabel(item) {
    return this._stateValue(item?.switch_entity_id) === "on" ? "turn off" : "turn on";
  }

  _requiresControlConfirm(id, item) {
    const [risk] = this._equipmentRisk(id, item);
    return risk === "critical" || risk === "warning";
  }

  _equipmentEditorOpen(id) {
    const item = this._config.equipment?.[id];
    if (!item?.switch_entity_id) return true;
    return this._equipmentEditors[id] === true;
  }

  _equipmentEnergyOpen(id) {
    return this._equipmentEnergyEditors[id] === true;
  }

  _interlockWarnings() {
    const interlocks = this._config.interlocks || {};
    const equipment = Object.entries(this._config.equipment || {});
    const warnings = [];

    if (interlocks.heaterRequiresTankTemp !== false) {
      warnings.push(...this._heaterInterlocks(equipment));
    }
    if (interlocks.atoMaxRuntimeEnabled !== true) {
      const armedAto = equipment.filter(
        ([id, item]) => item.armed && this._equipmentProfile(id, item) === "ato",
      );
      if (armedAto.length) {
        warnings.push({
          title: "ATO runtime interlock is not enabled",
          detail: "An ATO/top-off device is armed. Configure the max-runtime guard before relying on unattended top-off control.",
        });
      }
    }
    if (interlocks.returnPumpSkimmerWarning !== false) {
      const armedSkimmers = equipment.filter(
        ([id, item]) => item.armed && this._equipmentProfile(id, item) === "skimmer",
      );
      const armedReturnPumps = equipment.filter(
        ([id, item]) => item.armed && this._equipmentProfile(id, item) === "return_pump",
      );
      if (armedSkimmers.length && !armedReturnPumps.length) {
        warnings.push({
          title: "Skimmer has no armed return pump relationship",
          detail: "Arm or map the return pump so future skimmer safety rules can prevent dry or overflow scenarios.",
        });
      }
      armedSkimmers.forEach(([skimmerId, skimmer]) => {
        const skimmerState = this._stateValue(skimmer.switch_entity_id);
        const returnOff = armedReturnPumps.some(([, pump]) => this._stateValue(pump.switch_entity_id) === "off");
        if (skimmerState === "on" && returnOff) {
          warnings.push({
            title: "Skimmer is on while an armed return pump is off",
            detail: `${skimmer.label || skimmerId} is running. Check return flow before leaving the system unattended.`,
          });
        }
      });
    }

    return warnings;
  }

  _heaterInterlocks(equipment = Object.entries(this._config.equipment || {})) {
    const tempSensor = this._config.sensors?.temp;
    const heaters = equipment.filter(
      ([id, item]) => item.armed && this._equipmentProfile(id, item) === "heater",
    );

    if (!heaters.length) return [];
    if (!this._sensorEnabled(tempSensor)) {
      return [{
        title: "Heater interlock cannot verify tank temperature",
        detail: "A heater is armed, but Tank Temperature is disabled.",
      }];
    }
    if (!tempSensor?.entity_id) {
      return [{
        title: "Heater interlock needs a tank temperature sensor",
        detail: "Map Tank Temperature before relying on armed heater controls.",
      }];
    }
    const state = this._state(tempSensor.entity_id);
    if (!state || ["unknown", "unavailable"].includes(state.state)) {
      return [{
        title: "Heater interlock has no live temperature reading",
        detail: `${tempSensor.entity_id} is ${state?.state || "not available"}.`,
      }];
    }
    return [];
  }

  _modePreview(modeId) {
    if (modeId === "running") return this._config.mode?.returnPlan || {};
    return this._config.modePreviews?.[modeId] || {};
  }

  _modePreviewSummary(modeId) {
    const preview = this._modePreview(modeId);
    const actions = Object.values(preview).filter((state) => state === "on" || state === "off");
    if (!actions.length) return modeId === "running" ? "No restore plan saved." : "Preview not configured.";
    if (modeId === "running") return `${actions.length} captured state${actions.length === 1 ? "" : "s"} to restore.`;
    const off = actions.filter((state) => state === "off").length;
    const on = actions.filter((state) => state === "on").length;
    return `${off} off, ${on} on when confirmed.`;
  }

  _modeActionRows(modeId) {
    const preview = this._modePreview(modeId);
    return Object.entries(preview)
      .filter(([, state]) => state === "on" || state === "off")
      .map(([equipmentId, desiredState]) => {
        const item = this._config.equipment?.[equipmentId] || {};
        const switchEntity = item.switch_entity_id || "";
        const autoRestartBlocked = this._blocksDisplayWavemakerAutoRestart(item, desiredState, equipmentId);
        let status = "ready";
        let detail = switchEntity || "No switch mapped";
        if (!switchEntity) {
          status = "missing";
          detail = "No switch mapped";
        } else if (!item.armed) {
          status = "locked";
          detail = "Skipped because this device is disarmed";
        } else {
          const current = this._stateValue(switchEntity);
          if (current === "unknown" || current === "unavailable" || current === "--") {
            status = "missing";
            detail = `${switchEntity} is ${current}`;
          } else if (autoRestartBlocked) {
            status = "locked";
            detail = "Automatic display wavemaker restart is blocked. Inspect livestock and restart manually.";
          } else {
            detail = modeId === "running"
              ? `${switchEntity} is currently ${current}; restore to ${desiredState}`
              : `${switchEntity} is currently ${current}`;
          }
        }
        return {
          equipmentId,
          label: item.label || equipmentId,
          desiredState,
          detail,
          status,
          armed: Boolean(item.armed),
          displayWavemaker: Boolean(item.displayWavemaker),
          autoRestartBlocked,
        };
      });
  }

  _modeActionCounts(modeId) {
    const rows = this._modeActionRows(modeId);
    return {
      rows,
      ready: rows.filter((row) => row.status === "ready").length,
      locked: rows.filter((row) => row.status === "locked").length,
      missing: rows.filter((row) => row.status === "missing").length,
    };
  }

  _recordActivity(message, type = "info") {
    this._config.activity = Array.isArray(this._config.activity) ? this._config.activity : [];
    this._config.activity.unshift({
      timestamp: new Date().toISOString(),
      message,
      type,
    });
    this._config.activity = this._config.activity.slice(0, 50);
  }

  _formatActivityTime(timestamp) {
    const date = new Date(timestamp);
    if (!Number.isFinite(date.getTime())) return "Unknown time";
    return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  _missionCards() {
    return {
      live: true,
      controls: true,
      energy: true,
      ...(this._config?.display?.missionCards || {}),
    };
  }

  _missionCardChoices() {
    return [
      ["live", "Live Stats", "Show mapped sensor readings in Mission Control."],
      ["controls", "Controls", "Show armed equipment status in Mission Control."],
      ["energy", "Energy", "Show energy and cost summaries in Mission Control."],
    ];
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
        ${this._trend ? this._trendModal() : ""}
        ${this._modeConfirm ? this._modeConfirmModal() : ""}
        ${this._equipmentDetail ? this._equipmentDetailModal() : ""}
        ${this._controlConfirm ? this._controlConfirmModal() : ""}
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
    const sensors = this._enabledSensors();
    const equipment = Object.entries(this._config.equipment || {});
    const sensorAlerts = this._sensorAlerts(sensors);
    const critical = sensorAlerts.filter((alert) => alert.status === "critical");
    const warnings = sensorAlerts.filter((alert) => alert.status === "warning");
    const missing = this._validation?.missing_entities || [];
    const armedUnavailable = this._validation?.armed_unavailable || [];
    const interlocks = this._interlockWarnings();
    const mappedSensors = sensors.filter(([, sensor]) => sensor.entity_id).length;
    const armedEquipment = equipment.filter(([, item]) => item.armed).length;
    const mappedEnergy = this._energyTotalMappings().filter(([, energyKey]) => this._config.energy[energyKey]).length;
    const noEnabledSensors = !sensors.length;
    const status = critical.length || armedUnavailable.length ? "Action needed" : warnings.length || missing.length || noEnabledSensors || interlocks.length ? "Watch closely" : "All systems nominal";
    const cards = this._missionCards();
    const summaryCards = [
      cards.live ? this._missionSummaryCard("Sensors", `${mappedSensors}/${sensors.length}`, `${critical.length} critical · ${warnings.length} warning`, critical.length ? "critical" : warnings.length || noEnabledSensors ? "warning" : "ok", "live") : "",
      cards.controls ? this._missionSummaryCard("Equipment", `${armedEquipment}/${equipment.length}`, equipment.length ? "armed devices" : "none mapped", armedUnavailable.length ? "critical" : armedEquipment ? "ok" : "unknown", "controls") : "",
      cards.energy ? this._missionSummaryCard("Energy", `${mappedEnergy}/3`, "daily, weekly, monthly totals", mappedEnergy ? "ok" : "unknown", "energy") : "",
    ].join("");

    return `
      <section class="stack">
        <div class="hero ${critical.length || armedUnavailable.length ? "danger-border" : warnings.length || missing.length || noEnabledSensors || interlocks.length ? "warning-border" : "ok-border"}">
          <div>
            <p class="eyebrow">Mission Control</p>
            <h2>${status}</h2>
            <p>${critical.length} critical alert(s), ${warnings.length} warning(s), ${interlocks.length} interlock warning(s), ${missing.length} missing mapping(s), ${armedUnavailable.length} armed device issue(s).</p>
          </div>
          <div class="actions">
            <button class="secondary" data-action="validate">Refresh checks</button>
            <button class="primary" data-action="tab" data-id="settings">Open settings</button>
          </div>
        </div>
        ${this._modePanel()}
        ${summaryCards ? `<div class="summary-grid">${summaryCards}</div>` : ""}
        <article class="panel">
          <div class="section-head">
            <h3>Attention</h3>
            <p>Only configured OpenReef entities are checked here.</p>
          </div>
          ${this._missionIssueList(sensors, equipment, sensorAlerts, missing, armedUnavailable, interlocks)}
        </article>
        ${this._activityPanel()}
        <div class="grid two">
          ${cards.live ? `<article class="panel">
            <h3>Core Sensors</h3>
            ${sensors.length ? sensors.map(([id, sensor]) => this._sensorRow(id, sensor)).join("") : this._emptyState("No sensors enabled", "Enable the sensor types you own in Settings. Disabled sensors stay out of Mission Control.", "settings", "Choose sensors")}
          </article>` : ""}
          ${cards.controls ? `<article class="panel">
            <h3>Armed Equipment</h3>
            ${this._armedEquipmentRows()}
          </article>` : ""}
          ${cards.energy ? `<article class="panel">
            <h3>Energy</h3>
            ${this._missionEnergyRows()}
          </article>` : ""}
        </div>
      </section>
    `;
  }

  _missionSummaryCard(label, value, detail, status, tab) {
    return `
      <button class="summary-card ${status}" data-action="tab" data-id="${this._escape(tab)}">
        <span>${this._escape(label)}</span>
        <strong>${this._escape(value)}</strong>
        <small>${this._escape(detail)}</small>
      </button>
    `;
  }

  _modePanel() {
    const active = this._activeMode();
    const started = this._config.mode?.startedAt ? new Date(this._config.mode.startedAt) : null;
    const startedLabel = started && Number.isFinite(started.getTime()) ? started.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Not started yet";
    const durationLabel = this._modeDurationLabel();
    const durationText = durationLabel === "Not started yet" ? durationLabel : `for ${durationLabel}`;
    const countdownText = this._activeModeCountdownText();
    const restoreRows = active === "running" ? [] : this._modeActionRows("running");
    return `
      <article class="panel mode-panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">Current Mode</p>
            <h3>${this._escape(this._activeModeLabel())}</h3>
            <p class="muted">${this._escape(this._modeStatusDetail())}</p>
          </div>
          <div class="pill-stack">
            <span class="pill">${this._escape(startedLabel)}</span>
            <span class="pill ${active === "running" ? "ok" : "warning"}">${this._escape(durationText)}</span>
            ${active !== "running" ? `<span class="pill warning" data-mode-countdown>${this._escape(countdownText)}</span>` : ""}
            ${active !== "running" ? `<button class="primary compact-button" data-action="set-mode" data-mode="running">${this._modeTimerExpired() ? "Return now" : "Return to Running"}</button>` : ""}
          </div>
        </div>
        <div class="mode-actions">
          ${this._modeChoices().map(([id, label, description]) => `
            <button class="mode-button ${active === id ? "active" : ""}" data-action="set-mode" data-mode="${this._escape(id)}">
              <strong>${this._escape(label)}</strong>
              <span>${this._escape(description)} ${id === "running" && active === "running" ? "" : this._escape(this._modePreviewSummary(id))}</span>
            </button>
          `).join("")}
        </div>
        ${restoreRows.length ? `
          <div class="mode-restore-panel">
            <div class="section-head">
              <div>
                <h4>Running restore plan</h4>
                <p class="muted">When you return to Running, OpenReef will ask for confirmation and restore only armed available equipment.</p>
              </div>
              <span class="pill warning">${restoreRows.length} captured</span>
            </div>
            <div class="mode-mini-list">
              ${restoreRows.slice(0, 5).map((row) => `
                <div class="mode-mini-row ${this._escape(row.status)}">
                  <strong>${this._escape(row.label)}</strong>
                  <span>${this._escape(row.desiredState)}</span>
                  <small>${this._escape(row.detail)}</small>
                </div>
              `).join("")}
            </div>
          </div>
        ` : ""}
      </article>
    `;
  }

  _modeBanner() {
    const active = this._activeMode();
    const isRunning = active === "running";
    return `
      <article class="panel mode-strip ${isRunning ? "running" : this._modeTimerExpired() ? "expired" : "active"}">
        <div>
          <p class="eyebrow">Active Mode</p>
          <h3>${this._escape(this._activeModeLabel())}</h3>
          <p>${this._escape(this._modeStatusDetail())}</p>
        </div>
        <div class="pill-stack">
          <span class="pill ${isRunning ? "ok" : "warning"}" ${isRunning ? "" : "data-mode-countdown"}>${this._escape(isRunning ? "Monitoring" : this._activeModeCountdownText())}</span>
          ${!isRunning ? `<button class="primary compact-button" data-action="set-mode" data-mode="running">${this._modeTimerExpired() ? "Return now" : "Return to Running"}</button>` : ""}
        </div>
      </article>
    `;
  }

  _activityPanel() {
    const activity = Array.isArray(this._config.activity) ? this._config.activity.slice(0, 12) : [];
    return `
      <article class="panel">
        <div class="section-head">
          <div>
            <h3>Activity</h3>
            <p>Recent OpenReef changes and manual actions.</p>
          </div>
          ${activity.length ? `<button class="secondary compact-button" data-action="clear-activity">Clear</button>` : ""}
        </div>
        ${activity.length ? `
          <div class="activity-list">
            ${activity.map((item) => `
              <div class="activity-item ${this._escape(item.type || "info")}">
                <span>${this._escape(this._formatActivityTime(item.timestamp))}</span>
                <strong>${this._escape(item.message)}</strong>
              </div>
            `).join("")}
          </div>
        ` : `<p class="muted">No OpenReef activity has been recorded yet.</p>`}
      </article>
    `;
  }

  _missionIssueList(sensors, equipment, sensorAlerts, missing, armedUnavailable, interlocks = []) {
    const issues = [];
    const unmappedSensors = sensors.filter(([, sensor]) => !sensor.entity_id);
    const disarmedMapped = equipment.filter(([, item]) => item.switch_entity_id && !item.armed);
    const displayWavemakersOff = this._activeMode() === "running"
      ? equipment.filter(([id, item]) => this._isDisplayWavemaker(id, item) && item.armed && item.switch_entity_id && this._stateValue(item.switch_entity_id) === "off")
      : [];

    sensorAlerts.filter((alert) => alert.status === "critical").forEach((alert) => {
      issues.push(["critical", alert.title, alert.detail, "live"]);
    });
    sensorAlerts.filter((alert) => alert.status === "warning").forEach((alert) => {
      issues.push(["warning", alert.title, alert.detail, "live"]);
    });
    sensorAlerts.filter((alert) => alert.status === "unknown").forEach((alert) => {
      issues.push(["warning", alert.title, alert.detail, "settings"]);
    });
    if (unmappedSensors.length) {
      issues.push(["warning", "Sensors still need mapping", unmappedSensors.map(([, sensor]) => sensor.label).join(", "), "settings"]);
    }
    if (!sensors.length) {
      issues.push(["warning", "No sensor types enabled", "Enable only the probes and room sensors you actually own.", "settings"]);
    }
    if (missing.length) {
      issues.push(["critical", "Mapped entity unavailable", missing.slice(0, 6).join(", "), "settings"]);
    }
    if (armedUnavailable.length) {
      issues.push(["critical", "Armed equipment unavailable", armedUnavailable.slice(0, 6).join(", "), "controls"]);
    }
    if (displayWavemakersOff.length) {
      issues.push([
        "critical",
        "Display wavemaker still off",
        `${displayWavemakersOff.map(([, item]) => item.label || item.switch_entity_id).join(", ")} need inspection before manual restart. Flow is critical for corals.`,
        "controls",
      ]);
    }
    interlocks.forEach((issue) => {
      issues.push(["warning", issue.title, issue.detail, "controls"]);
    });
    if (disarmedMapped.length) {
      issues.push(["info", "Mapped controls are still disarmed", `${disarmedMapped.length} device(s) need arming in Settings before they can be controlled.`, "settings"]);
    }
    if (!equipment.length) {
      issues.push(["info", "No equipment mapped yet", "Add pumps, heaters, skimmers, lights, or other switch-controlled devices when you are ready.", "settings"]);
    }

    if (!issues.length) {
      return this._emptyState("Nothing needs attention", "Mapped sensors are in range and armed equipment is available.", "live", "View live stats");
    }

    return `
      <div class="issue-list">
        ${issues.map(([severity, title, detail, tab]) => `
          <button class="issue-item ${severity}" data-action="tab" data-id="${this._escape(tab)}">
            <span class="pill ${severity === "info" ? "unknown" : severity}">${this._escape(severity)}</span>
            <strong>${this._escape(title)}</strong>
            <small>${this._escape(detail)}</small>
          </button>
        `).join("")}
      </div>
    `;
  }

  _sensorRow(id, sensor) {
    const status = this._sensorStatus(sensor, id);
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
        <div class="pill ${this._equipmentStateClass(item)}">${this._escape(this._equipmentStateLabel(item))}</div>
      </div>
    `).join("");
  }

  _missionEnergyRows() {
    const rows = this._energyTotalMappings().map(([label, energyKey, costKey]) => [
      label === "Daily" ? "Today" : label === "Weekly" ? "This week" : "This month",
      energyKey,
      costKey,
    ]);
    return rows.map(([label, energyKey, costKey]) => {
      const mappedCost = this._number(this._config.energy[costKey]);
      const cost = this._energyCost(this._config.energy[energyKey], mappedCost);
      return `
        <div class="row">
          <div>
            <strong>${label}</strong>
            <span>${this._escape(this._config.energy[energyKey] || "Energy entity not mapped")}</span>
          </div>
          <div class="pill">${this._formatEnergyWh(this._config.energy[energyKey])} / ${this._escape(this._formatMoney(cost))}</div>
        </div>
      `;
    }).join("");
  }

  _liveStats() {
    const sensors = this._enabledSensors();
    return `
      <section class="stack">
        <h2>Live Stats</h2>
        <div class="grid three">
          ${sensors.length ? sensors.map(([id, sensor]) => {
            const value = this._number(sensor.entity_id);
            const display = id === "ph" ? this._format(value, 2) : this._format(value, 1);
            return `
              <button class="stat stat-button ${this._sensorGroupClass(sensor)}" data-action="show-trend" data-id="${this._escape(id)}" aria-label="Open ${this._escape(sensor.label)} trend">
                <p>${this._escape(sensor.label)}</p>
                <strong>${display}</strong>
                <span>${this._escape(sensor.unit || "")}</span>
                <small>${this._escape(sensor.entity_id || "Not mapped")}</small>
                <span class="trend-hint">Trend</span>
              </button>
            `;
          }).join("") : this._emptyState("No live sensors enabled", "Enable the sensor types you own in Settings, then map them to Home Assistant entities.", "settings", "Choose sensors")}
        </div>
      </section>
    `;
  }

  _controls() {
    const rows = Object.entries(this._config.equipment || {});
    const groups = this._equipmentGroups(rows);
    return `
      <section class="stack">
        <div class="section-head">
          <h2>Controls</h2>
          <p>Controls stay locked until each device is explicitly armed.</p>
        </div>
        ${this._modeBanner()}
        ${rows.length ? groups.map(([label, items]) => `
          <section class="equipment-group">
            <div class="section-head">
              <h3>${this._escape(label)}</h3>
              <p>${items.length} device${items.length === 1 ? "" : "s"}</p>
            </div>
            <div class="grid two">${items.map(([id, item]) => this._controlCard(id, item)).join("")}</div>
          </section>
        `).join("") : this._emptyState("No equipment mapped", "Add equipment in Settings, choose a switch entity, then arm it before control is allowed.", "settings", "Add equipment")}
      </section>
    `;
  }

  _controlCard(id, item) {
    const state = this._stateValue(item.switch_entity_id);
    const isOn = state === "on";
    const enabled = this._controlAvailable(item);
    const stateClass = this._equipmentStateClass(item);
    const stateLabel = this._equipmentStateLabel(item);
    const [risk, riskLabel, riskDetail] = this._equipmentRisk(id, item);
    const reason = this._controlBlockReason(item);
    const action = this._controlActionLabel(item);
    const displayWavemakerOff = this._isDisplayWavemaker(id, item) && state === "off";
    return `
      <article class="panel control-card ${enabled ? "" : "locked-card"}">
        <div class="card-head">
          <div>
            <h3>${this._escape(item.label || id)}</h3>
            <p>${this._escape(this._equipmentType(id, item))}</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${stateClass}">${this._escape(stateLabel)}</span>
            <span class="pill risk-${risk}">${this._escape(riskLabel)}</span>
          </div>
        </div>
        <div class="control-detail">
          <span>${this._escape(item.switch_entity_id || "No switch mapped")}</span>
          <small>${this._escape(riskDetail)}</small>
          <small>${this._escape(this._equipmentUseHint(id, item))}</small>
        </div>
        ${displayWavemakerOff ? `<div class="notice danger-notice compact-notice"><strong>Display wavemaker is off.</strong> Inspect the tank before restarting. Flow is critical for corals.</div>` : ""}
        <div class="control-row">
          <span>${this._escape(reason)}</span>
          <div class="control-actions">
            <button class="secondary compact-button" data-action="show-equipment-detail" data-id="${this._escape(id)}">Details</button>
            <button
              class="control-switch ${isOn ? "on" : "off"} ${enabled ? "" : "locked"}"
              data-action="toggle-equipment"
              data-id="${this._escape(id)}"
              role="switch"
              aria-checked="${isOn ? "true" : "false"}"
              title="${this._escape(enabled ? `Click to ${action}` : reason)}"
              ${enabled ? "" : "disabled"}
            >
              <span></span>
              <strong>${isOn ? "On" : "Off"}</strong>
            </button>
          </div>
        </div>
      </article>
    `;
  }

  _controlConfirmModal() {
    const id = this._controlConfirm;
    const item = this._config.equipment?.[id];
    if (!id || !item) return "";
    const [risk, riskLabel, riskDetail] = this._equipmentRisk(id, item);
    const current = this._stateValue(item.switch_entity_id);
    const action = this._controlActionLabel(item);
    const target = current === "on" ? "off" : "on";
    const displayRestart = this._isDisplayWavemaker(id, item) && target === "on";
    return `
      <div class="modal">
        <section class="wizard confirm-dialog">
          <button class="close" data-action="close-control-confirm">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Confirm Manual Control</p>
              <h2>${this._escape(item.label || id)}</h2>
              <p class="muted">${this._escape(item.switch_entity_id || "No switch mapped")}</p>
            </div>
            <span class="pill risk-${risk}">${this._escape(riskLabel)}</span>
          </div>
          <div class="notice warning-notice">${this._escape(riskDetail)} OpenReef will only continue if this device is still mapped, available, and armed.</div>
          ${displayRestart ? `<div class="notice danger-notice"><strong>Check the display wavemaker before restarting.</strong> Fish can be inside stopped display wavemakers. Inspect the tank first, then restart manually when livestock are clear.</div>` : ""}
          <div class="mode-confirm-list">
            <div class="mode-confirm-row ready">
              <div>
                <strong>Current state</strong>
                <span>${this._escape(current)}</span>
              </div>
              <span class="pill ${current === "on" ? "ok" : current === "off" ? "unknown" : "warning"}">${this._escape(current)}</span>
            </div>
            <div class="mode-confirm-row ready">
              <div>
                <strong>Requested action</strong>
                <span>OpenReef will ${this._escape(action)} this switch.</span>
              </div>
              <span class="pill warning">turn ${this._escape(target)}</span>
            </div>
          </div>
          <footer class="wizard-actions">
            <button class="secondary" data-action="close-control-confirm">Cancel</button>
            <button class="primary" data-action="confirm-toggle-equipment" data-id="${this._escape(id)}">Confirm ${this._escape(action)}</button>
          </footer>
        </section>
      </div>
    `;
  }

  _equipmentDetailModal() {
    const id = this._equipmentDetail;
    const item = this._config.equipment?.[id];
    if (!id || !item) return "";
    const enabled = this._controlAvailable(item);
    const isOn = this._stateValue(item.switch_entity_id) === "on";
    const [risk, riskLabel, riskDetail] = this._equipmentRisk(id, item);
    const switchStatus = this._equipmentStateClass(item);
    const switchLabel = this._equipmentStateLabel(item);
    const mappedCost = this._number(item.cost_entity_id);
    const cost = this._energyCost(item.energy_entity_id, mappedCost);
    const fields = [
      ["Switch", item.switch_entity_id, this._equipmentStateLabel(item)],
      ["Power", item.power_entity_id, `${this._format(this._number(item.power_entity_id), 1)} W`],
      ["Energy", item.energy_entity_id, this._formatEnergyWh(item.energy_entity_id)],
      ["Cost", item.cost_entity_id, this._formatMoney(mappedCost)],
    ];
    return `
      <div class="modal">
        <section class="wizard detail-dialog">
          <button class="close" data-action="close-equipment-detail">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Equipment Detail</p>
              <h2>${this._escape(item.label || id)}</h2>
              <p class="muted">${this._escape(this._equipmentType(id, item))}</p>
            </div>
            <div class="pill-stack">
              <span class="pill ${item.armed ? "ok" : "disabled"}">${item.armed ? "Armed" : "Disarmed"}</span>
              <span class="pill ${switchStatus}">${this._escape(switchLabel)}</span>
              <span class="pill risk-${risk}">${this._escape(riskLabel)}</span>
            </div>
          </div>
          <div class="detail-grid">
            <article class="detail-card">
              <span>Manual Control</span>
              <strong>${this._escape(this._controlBlockReason(item))}</strong>
              <p>${this._escape(riskDetail)}</p>
              <p>${this._escape(this._equipmentUseHint(id, item))}</p>
              <div class="control-actions">
                <button
                  class="control-switch ${isOn ? "on" : "off"} ${enabled ? "" : "locked"}"
                  data-action="toggle-equipment"
                  data-id="${this._escape(id)}"
                  role="switch"
                  aria-checked="${isOn ? "true" : "false"}"
                  ${enabled ? "" : "disabled"}
                >
                  <span></span>
                  <strong>${isOn ? "On" : "Off"}</strong>
                </button>
              </div>
            </article>
            <article class="detail-card">
              <span>Energy</span>
              <strong>${this._formatEnergyWh(item.energy_entity_id)}</strong>
              <p>Power ${this._format(this._number(item.power_entity_id), 1)} W · Cost ${this._escape(this._formatMoney(cost))}</p>
            </article>
          </div>
          <section class="mapping-card entity-card">
            <div class="mapping-head">
              <div>
                <h3>Mapped entities</h3>
                <p class="muted">Only these configured entities are read by OpenReef.</p>
              </div>
              <button class="secondary compact-button" data-action="tab" data-id="settings">Edit mappings</button>
            </div>
            <div class="entity-table">
              ${fields.map(([label, entityId, value]) => this._entityDetailRow(label, entityId, value)).join("")}
            </div>
          </section>
        </section>
      </div>
    `;
  }

  _entityDetailRow(label, entityId, value) {
    const [status, statusLabel] = this._entityStatus(entityId);
    return `
      <div class="entity-detail-row">
        <div>
          <strong>${this._escape(label)}</strong>
          <span>${this._escape(this._friendlyEntityName(entityId))}</span>
          <small>${this._escape(entityId || "Not mapped")}</small>
        </div>
        <div>
          <strong>${this._escape(value || "--")}</strong>
          <span>${this._escape(this._lastChangedLabel(entityId))}</span>
        </div>
        <span class="pill ${status}">${this._escape(statusLabel)}</span>
      </div>
    `;
  }

  _energy() {
    const tariff = Number(this._config.energy.tariff || 0);
    const totals = this._energyTotalMappings();
    const hasEnergyMappings = totals.some(([, energyKey]) => this._config.energy[energyKey]) || Object.values(this._config.equipment || {}).some((item) => item.energy_entity_id || item.power_entity_id);
    return `
      <section class="stack">
        <div class="section-head">
          <h2>Energy</h2>
          <p>${this._escape(this._config.energy.currency || "GBP")} ${tariff.toFixed(2)} per kWh</p>
        </div>
        ${hasEnergyMappings ? "" : this._emptyState("Energy is not mapped yet", "Map daily, weekly, monthly, or per-device energy entities in Settings. OpenReef will show blanks until then.", "settings", "Map energy")}
        <div class="grid three">
          ${totals.map(([label, energyKey, costKey]) => this._energyTotalCard(label, energyKey, costKey)).join("")}
        </div>
        <div class="section-head">
          <h3>Per-device energy</h3>
          <p>Optional per-equipment mappings from Settings.</p>
        </div>
        <div class="grid two">
          ${Object.entries(this._config.equipment || {}).length ? Object.entries(this._config.equipment || {}).map(([id, item]) => this._deviceEnergyCard(id, item)).join("") : this._emptyState("No per-device energy", "Add equipment energy or power entities in Settings when you want device-level usage.", "settings", "Open settings")}
        </div>
      </section>
    `;
  }

  _energyTotalCard(label, energyKey, costKey) {
    const energyEntity = this._config.energy[energyKey];
    const costEntity = this._config.energy[costKey];
    const mappedCost = this._number(costEntity);
    const cost = this._energyCost(energyEntity, mappedCost);
    const [status, statusLabel] = this._entityStatus(energyEntity);
    return `
      <article class="stat energy-total-card">
        <div class="card-head">
          <p>${this._escape(label)}</p>
          <span class="pill ${status}">${this._escape(statusLabel)}</span>
        </div>
        <strong>${this._formatEnergyWh(energyEntity)}</strong>
        <span>${this._escape(this._formatMoney(cost))}</span>
        <small>${this._escape(energyEntity || "Optional energy mapping missing")}</small>
        <small>${costEntity ? `Cost source: ${this._escape(costEntity)}` : "Cost is estimated from tariff when energy is mapped."}</small>
      </article>
    `;
  }

  _deviceEnergyCard(id, item) {
    const power = this._number(item.power_entity_id);
    const mappedCost = this._number(item.cost_entity_id);
    const cost = this._energyCost(item.energy_entity_id, mappedCost);
    const hasAnyEnergy = item.power_entity_id || item.energy_entity_id || item.cost_entity_id;
    const [switchStatus, switchStatusLabel] = this._entityStatus(item.switch_entity_id);
    const [energyStatus, energyStatusLabel] = this._bestEntityStatus([item.energy_entity_id, item.power_entity_id, item.cost_entity_id]);
    return `
      <article class="panel device-energy-card ${hasAnyEnergy ? "" : "locked-card"}">
        <div class="card-head">
          <div>
            <h3>${this._escape(item.label || id)}</h3>
            <p>${this._escape(this._equipmentType(id, item))} · ${this._escape(item.switch_entity_id || "No switch mapped")}</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${switchStatus}">${this._escape(switchStatusLabel)}</span>
            <span class="pill ${energyStatus}">${hasAnyEnergy ? this._escape(energyStatusLabel) : "optional"}</span>
          </div>
        </div>
        <div class="energy-metrics">
          <div><span>Power</span><strong>${this._format(power, 1)} W</strong></div>
          <div><span>Energy</span><strong>${this._formatEnergyWh(item.energy_entity_id)}</strong></div>
          <div><span>Cost</span><strong>${this._escape(this._formatMoney(cost))}</strong></div>
        </div>
        <div class="button-row">
          <button class="secondary compact-button" data-action="show-equipment-detail" data-id="${this._escape(id)}">Details</button>
          <button class="secondary compact-button" data-action="tab" data-id="settings">Edit mapping</button>
        </div>
        ${hasAnyEnergy ? "" : `<p class="hint">Map power or energy entities in Settings to track this device.</p>`}
      </article>
    `;
  }

  _energyTotalMappings() {
    return [
      ["Daily", "daily_energy_entity_id", "daily_cost_entity_id"],
      ["Weekly", "weekly_energy_entity_id", "weekly_cost_entity_id"],
      ["Monthly", "monthly_energy_entity_id", "monthly_cost_entity_id"],
    ];
  }

  _emptyState(title, detail, tab = "settings", actionLabel = "Open settings") {
    return `
      <article class="empty-state">
        <strong>${this._escape(title)}</strong>
        <p>${this._escape(detail)}</p>
        <button class="secondary" data-action="tab" data-id="${this._escape(tab)}">${this._escape(actionLabel)}</button>
      </article>
    `;
  }

  _settingsSectionOpen(id) {
    return this._settingsSections[id] !== false;
  }

  _settingsPanel(id, title, description, content) {
    const open = this._settingsSectionOpen(id);
    return `
      <article class="panel settings-section themed-settings-card">
        <button class="settings-section-head" data-action="toggle-settings-section" data-id="${this._escape(id)}">
          <span>
            <strong>${this._escape(title)}</strong>
            <small>${this._escape(description)}</small>
          </span>
          <span class="pill">${open ? "Hide" : "Show"}</span>
        </button>
        ${open ? `<div class="settings-section-body">${content}</div>` : ""}
      </article>
    `;
  }

  _saveControls() {
    return `
      <div class="settings-save">
        <span class="save-state ${this._configDirty ? "dirty" : ""}">${this._configDirty ? "Unsaved changes" : "Saved"}</span>
        <button class="primary" data-action="save">${this._configDirty ? "Save changes" : "Saved"}</button>
      </div>
    `;
  }

  _settings() {
    return `
      <section class="stack">
        <div class="section-head">
          <div>
            <h2>Settings</h2>
            <p>Configure only the controller pieces you own. Entity searches stay targeted and capped.</p>
          </div>
          ${this._saveControls()}
        </div>
        ${this._profileSettings()}
        ${this._missionSettings()}
        ${this._sensorSettings()}
        ${this._equipmentSettings()}
        ${this._modePreviewSettings()}
        ${this._alertsSettings()}
        ${this._interlockSettings()}
        ${this._energySettings()}
      </section>
    `;
  }

  _sensorSettings() {
    return this._settingsPanel(
      "sensors",
      "Sensors",
      "Enable only the probes and room sensors you actually own.",
      this._sensorMappingGroups(),
    );
  }

  _sensorMappingGroups() {
    const sensors = Object.entries(this._config.sensors || {});
    const groups = [
      ["tank", "Tank sensors", "Water readings used for reef health and alerts."],
      ["room", "Room environment", "Air readings around the aquarium."],
    ];
    return groups.map(([group, title, description]) => {
      const groupSensors = sensors.filter(([, sensor]) => (sensor.group || "tank") === group);
      if (!groupSensors.length) return "";
      return `
        <section class="mapping-section">
          <div>
            <p class="eyebrow">${this._escape(title)}</p>
            <h4>${this._escape(description)}</h4>
          </div>
          <div class="grid three compact">
            ${groupSensors.map(([id, sensor]) => this._sensorPicker(id, sensor)).join("")}
          </div>
        </section>
      `;
    }).join("");
  }

  _missionSettings() {
    const cards = this._missionCards();
    return this._settingsPanel(
      "mission",
      "Mission Control",
      "Choose which summary cards appear on the first screen.",
      `
        <div class="grid three compact">
          ${this._missionCardChoices().map(([id, label, description]) => `
            <label class="toggle-card">
              <input type="checkbox" data-scope="mission-card" data-id="${this._escape(id)}" ${cards[id] ? "checked" : ""}>
              <span>
                <strong>${this._escape(label)}</strong>
                <small>${this._escape(description)}</small>
              </span>
            </label>
          `).join("")}
        </div>
      `,
    );
  }

  _profileSettings() {
    const themeColor = this._themeColor();
    return this._settingsPanel(
      "profile",
      "Profile",
      "Name the controller, pick a theme, and set your energy tariff.",
      `
        <div class="grid two compact">
          <label>Tank name<input data-scope="tank" data-field="name" value="${this._escape(this._config.tank.name)}"></label>
          <label>Owner<input data-scope="tank" data-field="owner" value="${this._escape(this._config.tank.owner)}"></label>
          <div class="field-group">
            <span class="field-label">Theme colour</span>
            <div class="theme-picker">
              ${this._themeChoices().map(([color, label]) => `
                <button
                  class="theme-swatch ${themeColor.toLowerCase() === color.toLowerCase() ? "active" : ""}"
                  style="--swatch: ${this._escape(color)}"
                  data-action="set-theme"
                  data-color="${this._escape(color)}"
                  aria-label="${this._escape(label)}"
                  title="${this._escape(label)}"
                ></button>
              `).join("")}
            </div>
            <label class="color-field">Custom colour<input type="color" data-scope="display" data-field="themeColor" value="${this._escape(themeColor)}"></label>
          </div>
          <label>Tariff<input type="number" step="0.01" data-scope="energy" data-field="tariff" value="${this._escape(this._config.energy.tariff)}"></label>
        </div>
      `,
    );
  }

  _sensorPicker(id, sensor) {
    const key = `sensor:${id}`;
    const result = this._searchResults[key];
    const status = this._sensorStatus(sensor, id);
    const enabled = this._sensorEnabled(sensor);
    return `
      <section class="picker mapping-card ${this._sensorGroupClass(sensor)} ${enabled ? "" : "disabled-card"}">
        <div class="mapping-head">
          <div>
            <p class="eyebrow">${this._escape(this._sensorGroupLabel(sensor))}</p>
            <h3>${this._escape(sensor.label)}</h3>
          </div>
          <button
            class="arm-switch ${enabled ? "on" : "off"}"
            data-action="toggle-sensor"
            data-id="${this._escape(id)}"
            role="switch"
            aria-checked="${enabled ? "true" : "false"}"
          >
            <span></span>
            <strong>${enabled ? "Enabled" : "Disabled"}</strong>
          </button>
        </div>
        ${enabled ? `
          <div class="card-head">
            <span class="muted">Used in Live Stats, trends, and Mission Control alerts.</span>
            <span class="pill ${status}">${this._escape(this._sensorStatusLabel(status))}</span>
          </div>
          <label>Entity<input data-scope="sensor" data-id="${this._escape(id)}" data-field="entity_id" value="${this._escape(sensor.entity_id)}" placeholder="sensor.example"></label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="sensor" data-id="${this._escape(id)}" data-field="alertsEnabled" ${sensor.alertsEnabled === false ? "" : "checked"}>
            <span>
              <strong>Mission Control alerts</strong>
              <small>Warn when this reading is missing, near a threshold, or outside range.</small>
            </span>
          </label>
          <div class="mini-grid">
            <label>Min<input type="number" step="0.01" data-scope="sensor" data-id="${this._escape(id)}" data-field="min" value="${this._escape(sensor.min)}"></label>
            <label>Max<input type="number" step="0.01" data-scope="sensor" data-id="${this._escape(id)}" data-field="max" value="${this._escape(sensor.max)}"></label>
            <label>Warning buffer %<input type="number" step="1" min="0" max="50" data-scope="sensor" data-id="${this._escape(id)}" data-field="warningBuffer" value="${this._escape(sensor.warningBuffer ?? 10)}"></label>
          </div>
          <button class="secondary" data-action="search-sensor" data-id="${this._escape(id)}">${result?.loading ? "Finding..." : "Find matches"}</button>
          ${this._candidateList(key, "choose-sensor", id)}
        ` : `<p class="muted">Disabled sensors stay hidden from the dashboard and do not count as missing setup.</p>`}
      </section>
    `;
  }

  _equipmentSettings() {
    const quick = ["Return Pump", "Heater", "Skimmer", "ATO", "Wave Maker", "Lights"];
    return this._settingsPanel(
      "equipment",
      "Equipment",
      "Map switch-controlled devices, then arm them deliberately.",
      `
        <div class="section-head">
          <p class="muted">Add common reef equipment quickly, or rename it after adding.</p>
          <div class="quick-add">${quick.map((label) => `<button class="secondary" data-action="add-equipment" data-label="${this._escape(label)}">+ ${this._escape(label)}</button>`).join("")}</div>
        </div>
        <div class="stack tight">
          ${Object.entries(this._config.equipment || {}).map(([id, item]) => this._equipmentEditor(id, item)).join("") || `<p class="muted">Add equipment to enable safe controls and energy tracking.</p>`}
        </div>
      `,
    );
  }

  _equipmentEditor(id, item) {
    const open = this._equipmentEditorOpen(id);
    const energyOpen = this._equipmentEnergyOpen(id);
    const optionalFields = [
      ["power_entity_id", "Power", "sensor.example_power"],
      ["energy_entity_id", "Energy", "sensor.example_energy"],
      ["cost_entity_id", "Cost", "sensor.example_cost"],
    ];
    const optionalMapped = optionalFields.filter(([field]) => item[field]).length;
    const stateClass = this._equipmentStateClass(item);
    const stateLabel = this._equipmentStateLabel(item);
    const [risk, riskLabel] = this._equipmentRisk(id, item);
    const profile = this._equipmentProfile(id, item);
    const isDisplayWavemaker = profile === "display_wavemaker";
    return `
      <div class="equipment-editor ${item.armed ? "armed-editor" : "disarmed-editor"} ${open ? "open-editor" : "collapsed-editor"}">
        <div class="equipment-editor-head">
          <label class="equipment-name">Name<input data-scope="equipment" data-id="${this._escape(id)}" data-field="label" value="${this._escape(item.label || id)}"></label>
          <div class="equipment-summary">
            <span>${this._escape(item.switch_entity_id || "No switch mapped")}</span>
            <div class="pill-stack inline">
              <span class="pill ${stateClass}">${this._escape(stateLabel)}</span>
              <span class="pill risk-${risk}">${this._escape(riskLabel)}</span>
              <span class="pill">${this._escape(this._equipmentProfileLabel(profile))}</span>
              <span class="pill ${optionalMapped ? "ok" : "unknown"}">${optionalMapped}/3 energy</span>
            </div>
          </div>
          <div class="settings-actions">
            <button
              class="arm-switch ${item.armed ? "on" : "off"}"
              data-action="toggle-armed"
              data-id="${this._escape(id)}"
              role="switch"
              aria-checked="${item.armed ? "true" : "false"}"
            >
              <span></span>
              <strong>${item.armed ? "Armed" : "Disarmed"}</strong>
            </button>
            <button class="secondary" data-action="toggle-equipment-editor" data-id="${this._escape(id)}">${open ? "Hide" : "Configure"}</button>
            <button class="danger-text" data-action="remove-equipment" data-id="${this._escape(id)}">Remove</button>
          </div>
        </div>
        ${open ? `
          <div class="equipment-editor-body">
            <section class="mapping-card entity-card profile-card">
              <div class="mapping-head">
                <div>
                  <h3>Equipment profile</h3>
                  <p class="muted">Profiles drive presets, safety warnings, grouping, and future automation rules.</p>
                </div>
                <span class="pill ${risk === "critical" ? "critical" : risk === "warning" ? "warning" : "ok"}">${this._escape(this._equipmentProfileLabel(profile))}</span>
              </div>
              <label>Profile
                <select data-scope="equipment" data-id="${this._escape(id)}" data-field="type">
                  ${this._equipmentProfileChoices().map(([value, label]) => `<option value="${this._escape(value)}" ${profile === value ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
                </select>
              </label>
              <p class="hint">${this._escape(this._equipmentUseHint(id, item))}</p>
            </section>
            <section class="picker mapping-card entity-card">
              <div class="mapping-head">
                <h3>Switch</h3>
                <span class="pill">required</span>
              </div>
              <label>Switch<input data-scope="equipment" data-id="${this._escape(id)}" data-field="switch_entity_id" value="${this._escape(item.switch_entity_id)}" placeholder="switch.example"></label>
              <button class="secondary" data-action="search-equipment" data-id="${this._escape(id)}" data-field="switch_entity_id">${this._searchResults[`equipment:${id}:switch_entity_id`]?.loading ? "Finding..." : "Find matches"}</button>
              ${this._candidateList(`equipment:${id}:switch_entity_id`, "choose-equipment", id, "switch_entity_id")}
            </section>
            <section class="mapping-card entity-card energy-mapping-summary">
              <div class="mapping-head">
                <div>
                  <h3>Energy mapping</h3>
                  <p class="muted">Optional power, energy, and cost entities for per-device tracking.</p>
                </div>
                <button class="secondary compact-button" data-action="toggle-equipment-energy" data-id="${this._escape(id)}">${energyOpen ? "Hide fields" : "Show fields"}</button>
              </div>
              ${energyOpen ? `
                <div class="grid three compact">
                  ${optionalFields.map(([field, label, placeholder]) => `
                    <section class="picker mapping-card entity-card nested-card">
                      <div class="mapping-head">
                        <h3>${label}</h3>
                        <span class="pill">optional</span>
                      </div>
                      <label>${label}<input data-scope="equipment" data-id="${this._escape(id)}" data-field="${field}" value="${this._escape(item[field])}" placeholder="${placeholder}"></label>
                      <button class="secondary" data-action="search-equipment" data-id="${this._escape(id)}" data-field="${field}">${this._searchResults[`equipment:${id}:${field}`]?.loading ? "Finding..." : "Find matches"}</button>
                      ${this._candidateList(`equipment:${id}:${field}`, "choose-equipment", id, field)}
                    </section>
                  `).join("")}
                </div>
              ` : `<p class="hint">${optionalMapped ? `${optionalMapped} optional energy field${optionalMapped === 1 ? "" : "s"} mapped.` : "No optional energy fields mapped yet."}</p>`}
            </section>
            <section class="mapping-card entity-card wavemaker-safety-card">
              <div class="mapping-head">
                <div>
                  <h3>Display wavemaker safety</h3>
                  <p class="muted">Choose the Display wavemaker profile for powerheads inside the display tank.</p>
                </div>
                <span class="pill ${isDisplayWavemaker ? "warning" : "unknown"}">${isDisplayWavemaker ? "protected" : "off"}</span>
              </div>
              ${isDisplayWavemaker ? `
                <div class="notice danger-notice"><strong>OpenReef will block automatic restart by default.</strong> If this wavemaker is still off in Running, Mission Control will warn you to inspect livestock and restart manually.</div>
                <label class="toggle-card">
                  <input type="checkbox" data-scope="equipment" data-id="${this._escape(id)}" data-field="allowAutoRestart" ${item.allowAutoRestart ? "checked" : ""}>
                  <span>
                    <strong>Allow automatic restart</strong>
                    <small>Use only if this wavemaker is physically guarded or you are comfortable with automatic restart risk.</small>
                  </span>
                </label>
                <label class="toggle-card">
                  <input type="checkbox" data-scope="equipment" data-id="${this._escape(id)}" data-field="wavemakerNotifications" ${item.wavemakerNotifications !== false ? "checked" : ""}>
                  <span>
                    <strong>Home Assistant reminders</strong>
                    <small>Create and repeat notifications while this armed display wavemaker is off in Running.</small>
                  </span>
                </label>
              ` : `<p class="hint">This device is not treated as a display-tank wavemaker. It will use the normal safety behaviour for its selected profile.</p>`}
            </section>
          </div>
        ` : ""}
      </div>
    `;
  }

  _modePreviewSettings() {
    const equipment = Object.entries(this._config.equipment || {});
    const modeIds = this._editableModeIds();
    return this._settingsPanel(
      "modes",
      "Mode Actions",
      "Define what Feed, Maintenance, and custom modes will do after confirmation.",
      `
        <div class="section-head mode-settings-toolbar">
          <div>
            <p class="eyebrow">Manual modes</p>
            <p class="muted">Custom modes use the same confirmation, arming, and restore safeguards as Feed and Maintenance.</p>
          </div>
          <button class="primary compact-button" data-action="add-custom-mode">+ Custom mode</button>
        </div>
        <div class="grid two">
          ${modeIds.map((modeId) => this._modePreviewEditor(modeId, equipment)).join("")}
        </div>
        ${this._modeScheduleSettings()}
      `,
    );
  }

  _modePreviewEditor(modeId, equipment) {
    const mode = this._modeConfig(modeId);
    const isCustom = this._isCustomMode(modeId);
    const isActive = this._activeMode() === modeId;
    const preview = this._modePreview(modeId);
    const timer = this._modeTimerConfig(modeId);
    const presets = this._modePresetChoices(modeId);
    const planNote = presets.length
      ? `${this._modePreviewSummary(modeId)} Presets only edit this plan; applying the mode still needs confirmation.`
      : `${this._modePreviewSummary(modeId)} Applying the mode still needs confirmation.`;
    const options = [
      ["unchanged", "Leave unchanged"],
      ["off", "Turn off"],
      ["on", "Turn on"],
    ];
    return `
      <section class="mapping-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">${this._escape(isCustom ? "Custom mode" : mode.label)}</p>
            <h4>${this._escape(mode.description || "Preview equipment behavior.")}</h4>
          </div>
          ${isCustom ? `
            <button class="danger-text compact-button" data-action="remove-custom-mode" data-mode="${this._escape(modeId)}" ${isActive ? "disabled" : ""}>
              ${isActive ? "Active" : "Remove"}
            </button>
          ` : `<span class="pill disabled">Built-in</span>`}
        </div>
        <div class="mode-name-grid">
          <label>Mode name
            <input value="${this._escape(mode.label)}" data-scope="mode-settings" data-mode="${this._escape(modeId)}" data-field="label">
          </label>
          <label>Description
            <input value="${this._escape(mode.description)}" data-scope="mode-settings" data-mode="${this._escape(modeId)}" data-field="description">
          </label>
        </div>
        ${presets.length ? `
          <div class="preset-row">
            ${presets.map(([presetId, label, detail]) => `
            <button class="setup-choice mode-preset-choice" data-action="apply-mode-preset" data-mode="${this._escape(modeId)}" data-preset="${this._escape(presetId)}">
              <strong>${this._escape(label)}</strong>
              <span>${this._escape(detail)}</span>
            </button>
            `).join("")}
          </div>
        ` : ""}
        <div class="setup-status-line">${this._escape(planNote)}</div>
        <div class="mode-timer-card">
          <label>Timer minutes
            <input type="number" min="0" max="720" step="1" value="${this._escape(String(timer.durationMinutes))}" data-scope="mode-timer" data-mode="${this._escape(modeId)}" data-field="durationMinutes">
            <small>Use 0 for no timer. The timer starts when this mode is applied.</small>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="mode-timer" data-mode="${this._escape(modeId)}" data-field="autoReturn" ${timer.autoReturn ? "checked" : ""}>
            <span>
              <strong>Auto-return to Running</strong>
              <small>Off by default. If enabled, Home Assistant restores the captured Running state when the timer ends.</small>
            </span>
          </label>
        </div>
        ${equipment.length ? `<div class="stack tight">
          ${equipment.map(([equipmentId, item]) => {
            const selected = preview[equipmentId] || "unchanged";
            return `
              <label>${this._escape(item.label || equipmentId)}
                <small>${this._escape(this._equipmentUseHint(equipmentId, item))}</small>
                <select data-scope="mode-preview" data-mode="${this._escape(modeId)}" data-equipment="${this._escape(equipmentId)}">
                  ${options.map(([value, label]) => `<option value="${this._escape(value)}" ${selected === value ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
                </select>
              </label>
            `;
          }).join("")}
        </div>` : `<p class="muted">Add equipment first, then choose what this mode should do.</p>`}
      </section>
    `;
  }

  _scheduleDayLabel(days) {
    if (!Array.isArray(days) || !days.length) return "Every day";
    const names = new Map(this._scheduleDays());
    return days.map((day) => names.get(day) || day).join(", ");
  }

  _schedulePreview(item) {
    const schedule = this._modeSchedule();
    const mode = this._modeConfig(item.mode);
    const timer = this._modeTimerConfig(item.mode);
    const counts = this._modeActionCounts(item.mode);
    if (!schedule.enabled) {
      return ["disabled", "Scheduler off", "Turn on scheduled modes to allow this item to run."];
    }
    if (!item.enabled) {
      return ["disabled", "Paused", "This schedule is saved but will not run."];
    }
    if (!item.time) {
      return ["warning", "Needs a time", "Choose a time before this schedule can run."];
    }
    if (item.requireAutoReturn && !timer.autoReturn) {
      return ["warning", "Auto-return required", `${mode.label} will not run on schedule until auto-return is enabled for the mode.`];
    }
    if (!counts.rows.length) {
      return ["warning", "No actions configured", `${mode.label} needs at least one equipment action.`];
    }
    if (counts.rows.some((row) => row.autoRestartBlocked)) {
      return ["warning", "Wavemaker restart blocked", "A display wavemaker will not be turned on automatically; inspect the tank and restart it manually."];
    }
    if (!counts.ready) {
      return ["warning", "No armed equipment ready", `${counts.locked} locked and ${counts.missing} unavailable item(s) will be skipped.`];
    }
    return ["ok", `${counts.ready} ready`, `${mode.label} will run ${this._scheduleDayLabel(item.days)} at ${item.time}.`];
  }

  _modeScheduleSettings() {
    const schedule = this._modeSchedule();
    const items = schedule.items;
    const modeIds = this._editableModeIds();
    return `
      <section class="mapping-section scheduler-preview">
        <div class="section-head">
          <div>
            <p class="eyebrow">Mode Schedules</p>
            <h4>Run a saved mode at a chosen time and day.</h4>
            <p class="muted">Schedules are off by default and still only control armed equipment. OpenReef skips schedules that are unsafe or incomplete.</p>
          </div>
          <div class="schedule-toolbar">
            <label class="toggle-card compact-toggle">
              <input type="checkbox" data-scope="mode-schedule-global" data-field="enabled" ${schedule.enabled ? "checked" : ""}>
              <span><strong>Scheduled modes</strong><small>${schedule.enabled ? "Enabled" : "Off"}</small></span>
            </label>
            <button class="primary compact-button" data-action="add-mode-schedule">+ Schedule</button>
          </div>
        </div>
        ${items.length ? `
          <div class="schedule-list">
            ${items.map((item) => {
              const [status, title, detail] = this._schedulePreview(item);
              const days = Array.isArray(item.days) ? item.days : [];
              return `
                <article class="schedule-card ${this._escape(status)}">
                  <div class="section-head">
                    <div>
                      <p class="eyebrow">Schedule</p>
                      <h4>${this._escape(this._modeConfig(item.mode).label)}</h4>
                      <p class="muted">${this._escape(detail)}</p>
                    </div>
                    <div class="pill-stack">
                      <span class="pill ${this._escape(status)}">${this._escape(title)}</span>
                      <button class="danger-text compact-button" data-action="remove-mode-schedule" data-schedule="${this._escape(item.id)}">Remove</button>
                    </div>
                  </div>
                  <div class="schedule-fields">
                    <label>Mode
                      <select data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="mode">
                        ${modeIds.map((modeId) => {
                          const mode = this._modeConfig(modeId);
                          return `<option value="${this._escape(modeId)}" ${item.mode === modeId ? "selected" : ""}>${this._escape(mode.label)}</option>`;
                        }).join("")}
                      </select>
                    </label>
                    <label>Time
                      <input type="time" value="${this._escape(item.time || "12:00")}" data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="time">
                    </label>
                    <label class="toggle-card compact-toggle">
                      <input type="checkbox" data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="enabled" ${item.enabled ? "checked" : ""}>
                      <span><strong>Enable item</strong><small>Runs only while global scheduling is on.</small></span>
                    </label>
                    <label class="toggle-card compact-toggle">
                      <input type="checkbox" data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="requireAutoReturn" ${item.requireAutoReturn !== false ? "checked" : ""}>
                      <span><strong>Require auto-return</strong><small>Recommended for unattended schedules.</small></span>
                    </label>
                  </div>
                  <div class="schedule-days">
                    <button class="${days.length ? "" : "active"}" data-action="toggle-schedule-day" data-schedule="${this._escape(item.id)}" data-day="all">Every day</button>
                    ${this._scheduleDays().map(([day, label]) => `
                      <button class="${days.includes(day) ? "active" : ""}" data-action="toggle-schedule-day" data-schedule="${this._escape(item.id)}" data-day="${this._escape(day)}">${this._escape(label)}</button>
                    `).join("")}
                  </div>
                </article>
              `;
            }).join("")}
          </div>
        ` : `<p class="muted">No schedules yet. Add one when you want a mode to run automatically.</p>`}
      </section>
    `;
  }

  _alertsSettings() {
    const alerts = this._config.alerts || {};
    const sensors = this._enabledSensors();
    const alertRows = sensors.map(([id, sensor]) => {
      const status = this._sensorStatus(sensor, id);
      const mutedUntil = this._formatMutedUntil(id);
      const statusDetail = mutedUntil
        ? `Muted until ${mutedUntil}`
        : sensor.alertsEnabled === false
          ? "Alerts muted for this sensor"
          : this._escape(sensor.entity_id || "No entity mapped");
      return `
        <div class="row alert-row">
          <div>
            <strong>${this._escape(sensor.label || id)}</strong>
            <span>${statusDetail}</span>
          </div>
          <div class="alert-actions">
            <span class="pill ${status}">${this._escape(this._sensorStatusLabel(status))}</span>
            ${this._isAlertMuted(id)
              ? `<button class="secondary compact-button" data-action="unmute-alert" data-id="${this._escape(id)}">Unmute</button>`
              : `
                <button class="secondary compact-button" data-action="mute-alert" data-id="${this._escape(id)}" data-minutes="60">Mute 1h</button>
                <button class="secondary compact-button" data-action="mute-alert" data-id="${this._escape(id)}" data-minutes="1440">Mute 24h</button>
              `}
          </div>
        </div>
      `;
    }).join("");
    const history = Array.isArray(alerts.history) ? alerts.history.slice(0, 10) : [];
    return this._settingsPanel(
      "alerts",
      "Alerts",
      "Control Mission Control alert behaviour and optional Home Assistant notifications.",
      `
        <div class="grid two compact">
          <label class="toggle-card">
            <input type="checkbox" data-scope="alerts" data-field="persistentNotifications" ${alerts.persistentNotifications ? "checked" : ""}>
            <span>
              <strong>Home Assistant notifications</strong>
              <small>Create persistent notifications when OpenReef detects configured sensor alerts.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="alerts" data-field="notifyCriticalOnly" ${alerts.notifyCriticalOnly !== false ? "checked" : ""}>
            <span>
              <strong>Critical notifications only</strong>
              <small>Keep warnings inside Mission Control unless a reading moves outside range.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="alerts" data-field="wavemakerReminders" ${alerts.wavemakerReminders !== false ? "checked" : ""}>
            <span>
              <strong>Display wavemaker reminders</strong>
              <small>Repeat Home Assistant reminders while an armed display wavemaker is off in Running.</small>
            </span>
          </label>
          <label>Wavemaker reminder interval
            <input type="number" min="1" max="240" step="1" data-scope="alerts" data-field="wavemakerReminderMinutes" value="${this._escape(String(alerts.wavemakerReminderMinutes || 10))}">
            <small>Minutes between reminders. OpenReef only checks mapped display-wavemaker switches.</small>
          </label>
        </div>
        <div class="status-list">
          ${alertRows || `<p class="muted">Enable sensor types to see their alert state here.</p>`}
        </div>
        <div class="section-head">
          <div>
            <h3>Alert history</h3>
            <p>Recorded when OpenReef checks, saves, or mutes alert state.</p>
          </div>
          ${history.length ? `<button class="secondary compact-button" data-action="clear-alert-history">Clear history</button>` : ""}
        </div>
        <div class="alert-history">
          ${history.length ? history.map((item) => `
            <div class="activity-item ${this._escape(item.state || "info")}">
              <span>${this._escape(this._formatActivityTime(item.timestamp))}</span>
              <strong>${this._escape(item.title || item.label || item.sensor_id)}</strong>
              <small>${this._escape(item.message || "")}</small>
            </div>
          `).join("") : `<p class="muted">No alert history yet. Use Check to refresh alert state.</p>`}
        </div>
      `,
    );
  }

  _interlockSettings() {
    const interlocks = this._config.interlocks || {};
    return this._settingsPanel(
      "interlocks",
      "Interlocks",
      "Configure safety rules before future automation is allowed to act.",
      `
        <div class="grid two compact">
          <label class="toggle-card">
            <input type="checkbox" data-scope="interlocks" data-field="heaterRequiresTankTemp" ${interlocks.heaterRequiresTankTemp !== false ? "checked" : ""}>
            <span>
              <strong>Heater requires tank temperature</strong>
              <small>Warn if a heater is armed without a live tank temperature reading.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="interlocks" data-field="returnPumpSkimmerWarning" ${interlocks.returnPumpSkimmerWarning !== false ? "checked" : ""}>
            <span>
              <strong>Skimmer follows return flow</strong>
              <small>Warn if skimmer control is armed without a return-pump relationship.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="interlocks" data-field="atoMaxRuntimeEnabled" ${interlocks.atoMaxRuntimeEnabled ? "checked" : ""}>
            <span>
              <strong>ATO max-runtime guard</strong>
              <small>Prepare a maximum top-off run time before unattended ATO automation is introduced.</small>
            </span>
          </label>
          <label>ATO max runtime seconds
            <input type="number" min="5" max="1800" step="5" data-scope="interlocks" data-field="atoMaxRuntimeSeconds" value="${this._escape(interlocks.atoMaxRuntimeSeconds ?? 300)}">
          </label>
        </div>
        ${this._interlockWarnings().length ? `<div class="notice warning-notice">${this._interlockWarnings().length} interlock warning(s) currently visible in Mission Control.</div>` : `<p class="muted">No interlock warnings are active.</p>`}
      `,
    );
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
    return this._settingsPanel(
      "energy",
      "Energy Totals",
      "Optional daily, weekly, monthly, and cost sensors.",
      `
        <div class="grid two compact">
          ${fields.map(([field, label]) => this._energyPicker(field, label)).join("")}
        </div>
      `,
    );
  }

  _energyPicker(field, label) {
    const key = `energy:${field}`;
    const result = this._searchResults[key];
    return `
      <section class="picker mapping-card entity-card">
        <div class="mapping-head">
          <h3>${this._escape(label)}</h3>
          <span class="pill">optional</span>
        </div>
        <label>${this._escape(label)}<input data-scope="energy" data-field="${this._escape(field)}" value="${this._escape(this._config.energy[field])}" placeholder="sensor.optional"></label>
        <button class="secondary" data-action="search-energy" data-field="${this._escape(field)}" data-label="${this._escape(label)}">${result?.loading ? "Finding..." : "Find matches"}</button>
        ${this._candidateList(key, "choose-energy", "", field)}
      </section>
    `;
  }

  _candidateList(key, action, id, field = "") {
    const result = this._searchResults[key];
    if (!result) return `<p class="hint">Paste an entity ID or find matches.</p>`;
    if (result.error) return `<p class="hint error-text">${this._escape(result.error)}</p>`;
    if (result.loading) return `<p class="hint">Searching Home Assistant...</p>`;
    if (!result.candidates?.length) return `<p class="hint">No matches found. Manual entry still works.</p>`;
    return `
      <div class="candidate-tools">
        <span>${result.candidates.length} match${result.candidates.length === 1 ? "" : "es"}</span>
        <button class="secondary compact-button" data-action="hide-matches" data-key="${this._escape(key)}">Hide matches</button>
      </div>
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

  _trendSummary(points) {
    if (!points.length) return null;
    const values = points.map((point) => point.value);
    return {
      latest: values[values.length - 1],
      min: Math.min(...values),
      max: Math.max(...values),
    };
  }

  _trendSvg(points, unit, range) {
    if (points.length < 2) return `<div class="empty-chart">No trend points yet.</div>`;
    const width = 640;
    const height = 220;
    const pad = 22;
    const minTime = points[0].time;
    const maxTime = points[points.length - 1].time;
    const values = points.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const valueRange = max - min || 1;
    const timeRange = maxTime - minTime || 1;
    const coords = points.map((point) => {
      const x = pad + ((point.time - minTime) / timeRange) * (width - pad * 2);
      const y = height - pad - ((point.value - min) / valueRange) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const fillCoords = [
      `${pad},${height - pad}`,
      ...coords,
      `${width - pad},${height - pad}`,
    ].join(" ");

    return `
      <div class="chart-wrap">
        <svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${this._escape(this._trendRangeLabel(range))} trend">
          <line x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}" />
          <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" />
          <polygon points="${fillCoords}" />
          <polyline points="${coords.join(" ")}" />
        </svg>
        <div class="chart-labels">
          <span>${this._formatTrendTime(minTime, range)}</span>
          <strong>${this._format(max, 2)} ${this._escape(unit || "")}</strong>
          <span>${this._formatTrendTime(maxTime, range)}</span>
        </div>
      </div>
    `;
  }

  _trendModal() {
    const sensor = this._config.sensors?.[this._trend.sensorId] || {};
    const points = this._trend.points || [];
    const summary = this._trendSummary(points);
    const range = this._trend.range || "24h";
    const coverageMessage = this._trendCoverageMessage(points, range);
    return `
      <div class="modal">
        <section class="wizard trend-dialog">
          <button class="close" data-action="close-trend">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">${this._escape(this._trendRangeLabel(range))} trend</p>
              <h2>${this._escape(sensor.label || "Sensor")}</h2>
              <p class="muted">${this._escape(this._trend.entityId || "Not mapped")}</p>
            </div>
            <button class="secondary" data-action="refresh-trend" data-id="${this._escape(this._trend.sensorId)}" ${this._trend.loading ? "disabled" : ""}>Refresh</button>
          </div>
          <div class="range-picker">
            ${this._trendRanges().map(([id, label]) => `
              <button
                class="${range === id ? "active" : ""}"
                data-action="trend-range"
                data-id="${this._escape(this._trend.sensorId)}"
                data-range="${this._escape(id)}"
                ${this._trend.loading ? "disabled" : ""}
              >
                ${this._escape(label)}
              </button>
            `).join("")}
          </div>
          ${this._trend.loading ? `<div class="center-card compact-center"><div class="spinner"></div><p>Loading trend...</p></div>` : ""}
          ${this._trend.error ? `<div class="notice error">${this._escape(this._trend.error)}</div>` : ""}
          ${coverageMessage ? `<div class="notice warning-notice">${this._escape(coverageMessage)}</div>` : ""}
          ${!this._trend.loading && !this._trend.error ? this._trendSvg(points, sensor.unit, range) : ""}
          ${summary ? `
            <div class="trend-summary">
              <article><span>Latest</span><strong>${this._format(summary.latest, 2)} ${this._escape(sensor.unit || "")}</strong></article>
              <article><span>Low</span><strong>${this._format(summary.min, 2)} ${this._escape(sensor.unit || "")}</strong></article>
              <article><span>High</span><strong>${this._format(summary.max, 2)} ${this._escape(sensor.unit || "")}</strong></article>
            </div>
          ` : ""}
        </section>
      </div>
    `;
  }

  _modeConfirmModal() {
    const modeId = this._modeConfirm;
    const mode = this._modeChoices().find(([id]) => id === modeId) || [modeId, modeId, ""];
    const counts = this._modeActionCounts(modeId);
    const timerSummary = this._modeTimerSummary(modeId);
    const blockedDisplayWavemakers = counts.rows.filter((row) => row.autoRestartBlocked);
    const canApply = counts.ready || (modeId === "running" && counts.rows.length);
    return `
      <div class="modal">
        <section class="wizard confirm-dialog">
          <button class="close" data-action="close-mode-confirm">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Confirm Mode Action</p>
              <h2>${this._escape(mode[1])}</h2>
              <p class="muted">${this._escape(mode[2])}</p>
              <p class="muted">${this._escape(timerSummary)}</p>
            </div>
            <span class="pill ${counts.ready ? "warning" : "unknown"}">${counts.ready} ready</span>
          </div>
          <div class="notice warning-notice">OpenReef will only control mapped switch entities that are explicitly armed in Settings. Locked or unavailable equipment will be skipped.</div>
          ${blockedDisplayWavemakers.length ? `<div class="notice danger-notice"><strong>Display wavemaker restart is blocked.</strong> Inspect the tank before manually restarting any display wavemaker. Fish can be inside stopped wavemakers, and flow is critical for corals.</div>` : ""}
          ${this._configDirty ? `<div class="notice">OpenReef will save your pending Settings changes before applying this mode.</div>` : ""}
          ${counts.rows.length ? `
            <div class="mode-confirm-list">
              ${counts.rows.map((row) => `
                <div class="mode-confirm-row ${this._escape(row.status)}">
                  <div>
                    <strong>${this._escape(row.label)}</strong>
                    <span>${this._escape(row.detail)}</span>
                  </div>
                  <span class="pill ${row.autoRestartBlocked ? "warning" : row.status === "ready" ? "ok" : row.status === "locked" ? "disabled" : "warning"}">${this._escape(row.status === "ready" ? `turn ${row.desiredState}` : row.autoRestartBlocked ? "blocked" : row.status)}</span>
                </div>
              `).join("")}
            </div>
          ` : `<p class="muted">No equipment actions are configured for this mode yet. Add them in Settings.</p>`}
          <footer class="wizard-actions">
            <button class="secondary" data-action="close-mode-confirm">Cancel</button>
            <button class="primary" data-action="apply-mode" data-mode="${this._escape(modeId)}" ${canApply ? "" : "disabled"}>${this._configDirty ? "Save and apply" : "Apply"} ${this._escape(mode[1])}</button>
          </footer>
        </section>
      </div>
    `;
  }

  _setupStats() {
    const sensors = Object.entries(this._config.sensors || {});
    const enabledSensors = sensors.filter(([, sensor]) => this._sensorEnabled(sensor));
    const mappedSensors = enabledSensors.filter(([, sensor]) => sensor.entity_id);
    const equipment = Object.entries(this._config.equipment || {});
    const mappedEquipment = equipment.filter(([, item]) => item.switch_entity_id);
    const armedEquipment = equipment.filter(([, item]) => item.armed);
    const energyMapped = this._energyTotalMappings().filter(([, energyKey]) => this._config.energy[energyKey]).length;
    return {
      sensors,
      enabledSensors,
      mappedSensors,
      equipment,
      mappedEquipment,
      armedEquipment,
      energyMapped,
    };
  }

  _setupShell(title, description, content) {
    const steps = ["Profile", "Sensors", "Equipment", "Review"];
    return `
      <div class="modal">
        <section class="wizard setup-wizard">
          <button class="close" data-action="close-setup">x</button>
          <div class="setup-progress">
            <div class="stepper">${steps.map((step, index) => `
              <button class="${index <= this._setupStep ? "on" : ""}" data-action="setup-step" data-step="${index}" title="${this._escape(step)}">${index + 1}</button>
            `).join("")}</div>
            <span>Step ${this._setupStep + 1} of ${steps.length}: ${this._escape(steps[this._setupStep])}</span>
          </div>
          <div class="setup-title">
            <h2>${this._escape(title)}</h2>
            <p class="muted">${this._escape(description)}</p>
          </div>
          ${content}
          <footer class="wizard-actions">
            <button class="secondary" data-action="prev-step" ${this._setupStep === 0 ? "disabled" : ""}>Back</button>
            ${this._setupStep < 3 ? `<button class="primary" data-action="next-step">Next</button>` : `<button class="primary" data-action="finish-setup">Finish setup</button>`}
          </footer>
        </section>
      </div>
    `;
  }

  _setupProfileStep() {
    const themeColor = this._themeColor();
    return this._setupShell(
      "Welcome to OpenReef",
      "Name the controller and choose a theme. You can change everything later in Settings.",
      `
        <div class="setup-guide">
          <article><strong>1. Pick your sensors</strong><span>Enable only probes and room sensors you actually own.</span></article>
          <article><strong>2. Map equipment</strong><span>Switch controls stay locked until you arm each device.</span></article>
          <article><strong>3. Review safety</strong><span>Mission Control checks only OpenReef entities.</span></article>
        </div>
        <article class="panel setup-panel">
          <div class="grid two compact">
            <label>Tank name<input data-scope="tank" data-field="name" value="${this._escape(this._config.tank.name)}"></label>
            <label>Owner<input data-scope="tank" data-field="owner" value="${this._escape(this._config.tank.owner)}"></label>
            <div class="field-group">
              <span class="field-label">Theme colour</span>
              <div class="theme-picker">
                ${this._themeChoices().map(([color, label]) => `
                  <button
                    class="theme-swatch ${themeColor.toLowerCase() === color.toLowerCase() ? "active" : ""}"
                    style="--swatch: ${this._escape(color)}"
                    data-action="set-theme"
                    data-color="${this._escape(color)}"
                    aria-label="${this._escape(label)}"
                    title="${this._escape(label)}"
                  ></button>
                `).join("")}
              </div>
              <label class="color-field">Custom colour<input type="color" data-scope="display" data-field="themeColor" value="${this._escape(themeColor)}"></label>
            </div>
            <label>Energy tariff<input type="number" step="0.01" data-scope="energy" data-field="tariff" value="${this._escape(this._config.energy.tariff)}"></label>
          </div>
        </article>
      `,
    );
  }

  _setupSensorStep() {
    const stats = this._setupStats();
    return this._setupShell(
      "Choose and map sensors",
      "Start with the probes you own. Missing optional sensors will not count against setup if they are disabled.",
      `
        <div class="setup-choice-grid">
          <button class="setup-choice" data-action="setup-sensor-preset" data-id="tank">
            <strong>Tank sensors</strong>
            <span>Temperature, pH, and salinity.</span>
          </button>
          <button class="setup-choice" data-action="setup-sensor-preset" data-id="all">
            <strong>Tank + room</strong>
            <span>Add room temperature, CO2, and humidity.</span>
          </button>
          <button class="setup-choice" data-action="setup-sensor-preset" data-id="minimal">
            <strong>Temperature only</strong>
            <span>Safest starting point for a basic install.</span>
          </button>
        </div>
        <div class="setup-status-line">${stats.mappedSensors.length}/${stats.enabledSensors.length} enabled sensors mapped.</div>
        ${this._sensorMappingGroups()}
      `,
    );
  }

  _setupEquipmentStep() {
    const stats = this._setupStats();
    return this._setupShell(
      "Add equipment",
      "Add common reef devices now or skip this for a read-only monitor. Nothing can be controlled until you arm it.",
      `
        <div class="setup-choice-grid two-choice">
          <button class="setup-choice" data-action="setup-add-starter-equipment">
            <strong>Add starter equipment</strong>
            <span>Return pump, heater, lights, skimmer, and ATO. All start disarmed.</span>
          </button>
          <article class="setup-choice passive">
            <strong>Monitor-only is fine</strong>
            <span>You can finish setup with no equipment and add controls later.</span>
          </article>
        </div>
        <div class="setup-status-line">${stats.mappedEquipment.length}/${stats.equipment.length} equipment switches mapped. ${stats.armedEquipment.length} armed.</div>
        ${this._equipmentSettings()}
      `,
    );
  }

  _setupReviewStep() {
    const stats = this._setupStats();
    const sensorsReady = stats.enabledSensors.length && stats.mappedSensors.length === stats.enabledSensors.length;
    const controlsReady = stats.equipment.length ? stats.mappedEquipment.length === stats.equipment.length : true;
    return this._setupShell(
      "Review setup",
      "Finish when the basics look right. OpenReef will stay safe even if you finish with missing optional mappings.",
      `
        <div class="summary-grid">
          ${this._setupReviewCard("Sensors", `${stats.mappedSensors.length}/${stats.enabledSensors.length}`, sensorsReady ? "Mapped" : "Needs attention", sensorsReady ? "ok" : "warning", 1)}
          ${this._setupReviewCard("Equipment", `${stats.mappedEquipment.length}/${stats.equipment.length}`, stats.equipment.length ? `${stats.armedEquipment.length} armed` : "Monitor only", controlsReady ? "ok" : "warning", 2)}
          ${this._setupReviewCard("Energy", `${stats.energyMapped}/3`, stats.energyMapped ? "Totals mapped" : "Optional", stats.energyMapped ? "ok" : "unknown", 3)}
        </div>
        <article class="panel setup-panel">
          <h3>What happens next</h3>
          <div class="setup-next-list">
            <div><span class="pill ok">Safe</span><p>OpenReef reads only the entities you mapped or enabled.</p></div>
            <div><span class="pill disabled">Locked</span><p>Equipment stays locked until each device is armed in Settings.</p></div>
            <div><span class="pill unknown">Flexible</span><p>Optional sensors, energy totals, and equipment can be added later.</p></div>
          </div>
        </article>
      `,
    );
  }

  _setupReviewCard(label, value, detail, status, step) {
    return `
      <button class="summary-card ${status}" data-action="setup-step" data-step="${step}">
        <span>${this._escape(label)}</span>
        <strong>${this._escape(value)}</strong>
        <small>${this._escape(detail)}</small>
      </button>
    `;
  }

  _setupWizard() {
    if (this._setupStep === 0) return this._setupProfileStep();
    if (this._setupStep === 1) return this._setupSensorStep();
    if (this._setupStep === 2) return this._setupEquipmentStep();
    return this._setupReviewStep();
  }

  _styles() {
    const accent = this._themeColor();
    return `
      <style>
        :host {
          --openreef-accent: ${accent};
          --openreef-accent-soft: ${accent}24;
          --openreef-accent-border: ${accent}88;
          display: block;
          min-height: 100vh;
          background: #07111a;
          color: #e5edf5;
          font-family: var(--ha-font-family-body, Arial, sans-serif);
        }
        * { box-sizing: border-box; }
        button, input, select { font: inherit; }
        button { cursor: pointer; color: inherit; }
        button:disabled { cursor: not-allowed; opacity: .45; }
        .page { min-height: 100vh; padding: 24px; background: radial-gradient(circle at 20% 0%, var(--openreef-accent-soft), transparent 28%), #07111a; }
        .topbar, .hero, .panel, .stat, .wizard { border: 1px solid #24364a; background: #121f2f; border-radius: 8px; }
        .topbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 22px; margin-bottom: 18px; }
        h1, h2, h3, h4, p { margin: 0; }
        h1 { font-size: clamp(26px, 3vw, 42px); color: var(--openreef-accent); }
        h2 { font-size: 24px; margin-bottom: 8px; }
        h3 { font-size: 17px; margin-bottom: 14px; }
        h4 { font-size: 14px; color: #cbd5e1; font-weight: 700; }
        .eyebrow, .muted, .hint, small, .topbar p, .section-head p, .row span { color: #8da2ba; }
        .eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: 12px; font-weight: 700; margin-bottom: 6px; }
        .actions, .button-row, .quick-add, .wizard-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
        .tabs { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 8px; margin-bottom: 18px; }
        .tabs button, .primary, .secondary, .warning, .candidate, .danger-text, .range-picker button, .mode-button { border: 1px solid #294055; border-radius: 8px; padding: 11px 14px; color: #dcecff; background: #172536; }
        .tabs button.active, .primary, .range-picker button.active, .mode-button.active { background: var(--openreef-accent); border-color: var(--openreef-accent); color: #041019; font-weight: 800; }
        .secondary:hover, .tabs button:hover { border-color: var(--openreef-accent); }
        .compact-button { min-height: 30px; padding: 6px 10px; font-size: 12px; }
        .warning { background: #47351a; color: #fde68a; border-color: #a16207; }
        .danger-text { color: #fecaca; background: transparent; border-color: #7f1d1d; }
        .notice { padding: 12px 14px; border-radius: 8px; margin-bottom: 12px; background: #0f2c3d; border: 1px solid #075985; }
        .notice.error, .error-text { color: #fecaca; border-color: #7f1d1d; }
        .notice.warning-notice { color: #fde68a; border-color: #a16207; background: #2f2614; }
        .notice.danger-notice { color: #fecaca; border-color: #ef4444; background: #2b171c; }
        .notice.compact-notice { margin-bottom: 0; }
        .notice.success { color: #bbf7d0; border-color: #166534; }
        .stack { display: grid; gap: 16px; }
        .stack.tight { gap: 10px; }
        .grid { display: grid; gap: 16px; }
        .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        .grid.compact { gap: 12px; }
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
        .hero { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 22px; }
        .ok-border { border-color: #22c55e; background: #0b2b24; }
        .warning-border { border-color: #f59e0b; background: #2f2614; }
        .danger-border { border-color: #ef4444; background: #2b171c; }
        .panel, .stat { padding: 18px; }
        .summary-card, .empty-state, .issue-item { border: 1px solid #24364a; background: #121f2f; border-radius: 8px; color: #e5edf5; }
        .summary-card { display: grid; gap: 7px; text-align: left; padding: 16px; min-height: 118px; }
        .summary-card span { color: #8da2ba; font-weight: 800; }
        .summary-card strong { color: #67e8f9; font-size: 28px; }
        .summary-card small { color: #9fb2c7; }
        .summary-card.ok { border-color: #166534; background: #0b2b24; }
        .summary-card.warning { border-color: #a16207; background: #2f2614; }
        .summary-card.critical { border-color: #7f1d1d; background: #2b171c; }
        .summary-card.unknown { border-color: #334155; background: #101d2c; }
        .issue-list { display: grid; gap: 8px; }
        .issue-item { width: 100%; display: grid; grid-template-columns: auto minmax(160px, .45fr) 1fr; gap: 12px; align-items: center; padding: 12px; text-align: left; }
        .issue-item small { color: #9fb2c7; }
        .empty-state { display: grid; grid-column: 1 / -1; gap: 10px; place-items: start; padding: 18px; border-style: dashed; color: #cbd5e1; }
        .empty-state p { color: #8da2ba; }
        .section-head, .card-head, .row { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .mode-panel { display: grid; gap: 14px; }
        .mode-strip { display: flex; justify-content: space-between; gap: 14px; align-items: center; border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96)); }
        .mode-strip h3 { margin-bottom: 6px; }
        .mode-strip p:not(.eyebrow) { color: #a8bed4; }
        .mode-strip.running { border-color: #166534; background: #0b2b24; }
        .mode-strip.expired { border-color: #a16207; background: #2f2614; }
        .mode-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .mode-button { display: grid; gap: 5px; text-align: left; }
        .mode-button span { color: #9fb2c7; font-size: 12px; font-weight: 500; }
        .mode-button.active span { color: #06202a; }
        .mode-restore-panel { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0b1724; display: grid; gap: 12px; }
        .mode-mini-list { display: grid; gap: 8px; }
        .mode-mini-row { display: grid; grid-template-columns: minmax(160px, 1fr) auto minmax(220px, 1.4fr); gap: 10px; align-items: center; border: 1px solid #24364a; border-radius: 8px; padding: 10px; background: rgba(18, 31, 47, .76); }
        .mode-mini-row.ready { border-color: #166534; }
        .mode-mini-row.locked { opacity: .75; border-color: #334155; }
        .mode-mini-row.missing { border-color: #a16207; }
        .mode-mini-row span { color: #67e8f9; font-weight: 800; text-transform: uppercase; }
        .mode-mini-row small { color: #8da2ba; }
        .mode-name-grid { display: grid; grid-template-columns: minmax(160px, .35fr) minmax(240px, 1fr); gap: 12px; }
        .mode-timer-card { display: grid; grid-template-columns: minmax(160px, .45fr) minmax(260px, 1fr); gap: 12px; align-items: stretch; border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: rgba(11, 23, 36, .72); }
        .activity-list { display: grid; gap: 8px; }
        .activity-item { display: grid; grid-template-columns: minmax(130px, .22fr) 1fr; gap: 12px; align-items: center; border-top: 1px solid #223447; padding: 10px 0; }
        .activity-item:first-child { border-top: 0; }
        .activity-item span { color: #8da2ba; font-size: 12px; font-weight: 800; }
        .activity-item strong { color: #dcecff; overflow-wrap: anywhere; }
        .activity-item.control strong { color: #bbf7d0; }
        .activity-item.critical strong { color: #fecaca; }
        .activity-item.warning strong { color: #fde68a; }
        .activity-item.muted strong { color: #ddd6fe; }
        .activity-item.resolved strong { color: #bbf7d0; }
        .settings-save { display: flex; gap: 10px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
        .save-state { border: 1px solid #166534; border-radius: 999px; padding: 7px 11px; color: #bbf7d0; background: #0b2b24; font-size: 12px; font-weight: 800; }
        .save-state.dirty { border-color: #a16207; color: #fde68a; background: #2f2614; }
        .settings-section { display: grid; gap: 14px; position: relative; overflow: hidden; }
        .themed-settings-card { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96) 34%, #121f2f); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .settings-section-head { width: 100%; border: 0; background: transparent; padding: 0; display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; text-align: left; color: #e5edf5; }
        .settings-section-head span:first-child { display: grid; gap: 4px; }
        .settings-section-head strong { font-size: 18px; }
        .settings-section-head small { color: #a8bed4; }
        .settings-section-body { display: grid; gap: 14px; }
        .status-list { display: grid; gap: 6px; margin-top: 14px; }
        .alert-row { align-items: center; }
        .alert-actions { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
        .alert-history { display: grid; gap: 8px; }
        .alert-history .activity-item { grid-template-columns: minmax(130px, .18fr) minmax(180px, .28fr) 1fr; }
        .mode-confirm-list { display: grid; gap: 8px; }
        .mode-confirm-row { border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: #0b1724; display: flex; justify-content: space-between; gap: 12px; align-items: center; }
        .mode-confirm-row div { display: grid; gap: 4px; }
        .mode-confirm-row span { color: #8da2ba; }
        .mode-confirm-row.ready { border-color: #166534; }
        .mode-confirm-row.locked { opacity: .72; }
        .confirm-dialog { max-width: 780px; }
        .detail-dialog { max-width: 960px; }
        .detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
        .detail-card { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0b1724; display: grid; gap: 8px; }
        .detail-card span { color: #8da2ba; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
        .detail-card strong { color: #67e8f9; font-size: 24px; }
        .detail-card p { color: #9fb2c7; }
        .entity-table { display: grid; gap: 8px; }
        .entity-detail-row { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(130px, .45fr) auto; gap: 12px; align-items: center; border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: rgba(11, 23, 36, .72); }
        .entity-detail-row div { display: grid; gap: 3px; min-width: 0; }
        .entity-detail-row span, .entity-detail-row small { color: #8da2ba; overflow-wrap: anywhere; }
        .control-card { display: grid; gap: 14px; }
        .control-card.locked-card { opacity: .82; }
        .control-detail { display: grid; gap: 4px; color: #9fb2c7; overflow-wrap: anywhere; }
        .control-detail small { color: #8da2ba; }
        .control-actions { display: flex; gap: 10px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
        .control-row, .settings-actions { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
        .control-row { padding-top: 18px; color: #8da2ba; }
        .control-switch, .arm-switch { display: inline-flex; align-items: center; gap: 10px; min-width: 112px; min-height: 44px; border: 1px solid #334155; border-radius: 999px; padding: 5px 14px 5px 5px; background: #1f2937; color: #dcecff; font-weight: 800; }
        .control-switch span, .arm-switch span { display: block; width: 32px; height: 32px; border-radius: 50%; background: #94a3b8; transition: transform .16s ease, background .16s ease; }
        .control-switch.on, .arm-switch.on { background: #0f3f2c; border-color: #22c55e; color: #bbf7d0; }
        .control-switch.on span, .arm-switch.on span { background: #22c55e; transform: translateX(42px); }
        .control-switch.on strong, .arm-switch.on strong { transform: translateX(-32px); }
        .control-switch.locked { opacity: .5; filter: grayscale(.8); }
        .arm-switch.off { background: #172536; color: #cbd5e1; }
        .row { padding: 12px 0; border-top: 1px solid #223447; align-items: center; }
        .row:first-of-type { border-top: 0; }
        .row div { display: grid; gap: 4px; }
        .pill { display: inline-flex; align-items: center; justify-content: center; min-width: 74px; min-height: 30px; padding: 5px 10px; border-radius: 999px; background: #203247; color: #dbeafe; font-weight: 800; }
        .pill.ok { background: #14532d; color: #bbf7d0; }
        .pill.warning { background: #713f12; color: #fde68a; }
        .pill.critical { background: #7f1d1d; color: #fecaca; }
        .pill.unknown { background: #334155; color: #cbd5e1; }
        .pill.disabled { background: #1f2937; color: #94a3b8; }
        .pill.muted { background: #312e81; color: #ddd6fe; }
        .pill.risk-ok { background: #14532d; color: #bbf7d0; }
        .pill.risk-warning { background: #713f12; color: #fde68a; }
        .pill.risk-critical { background: #7f1d1d; color: #fecaca; }
        .pill-stack { display: flex; gap: 7px; flex-wrap: wrap; justify-content: flex-end; }
        .pill-stack.inline { justify-content: flex-start; }
        .stat { display: grid; gap: 8px; min-height: 150px; color: #e5edf5; }
        .stat p { color: #dcecff; font-weight: 800; }
        .stat strong { font-size: 34px; color: #67e8f9; }
        .stat span { color: #dcecff; }
        .stat small { color: #9fb2c7; }
        .stat-button { position: relative; width: 100%; text-align: left; }
        .stat-button:hover, .stat-button:focus-visible { border-color: var(--openreef-accent); box-shadow: 0 0 0 1px var(--openreef-accent-border); outline: none; }
        .trend-hint { position: absolute; top: 14px; right: 14px; border: 1px solid #294055; border-radius: 999px; padding: 4px 9px; color: #a7f3d0; background: #0b2b24; font-size: 12px; font-weight: 800; }
        .energy-total-card { align-content: start; }
        .device-energy-card { display: grid; gap: 14px; }
        .energy-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .energy-metrics div { border: 1px solid #24364a; border-radius: 8px; background: rgba(11, 23, 36, .72); padding: 12px; display: grid; gap: 5px; }
        .energy-metrics span { color: #8da2ba; font-size: 12px; font-weight: 800; }
        .energy-metrics strong { color: #67e8f9; overflow-wrap: anywhere; }
        label { display: grid; gap: 7px; color: #a7b7ca; font-size: 13px; font-weight: 700; }
        input, select { width: 100%; min-width: 0; border: 1px solid #2b4056; border-radius: 8px; background: #0b1724; color: #f8fafc; padding: 11px 12px; min-height: 42px; }
        select { cursor: pointer; }
        input[type="color"] { min-height: 48px; padding: 4px; cursor: pointer; }
        .field-group { display: grid; gap: 9px; }
        .field-label { color: #a7b7ca; font-size: 13px; font-weight: 800; }
        .toggle-card { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: rgba(14, 26, 40, .88); grid-template-columns: auto 1fr; align-items: start; }
        .toggle-card input { width: 20px; min-height: 20px; margin-top: 2px; accent-color: var(--openreef-accent); }
        .toggle-card span { display: grid; gap: 4px; }
        .theme-picker { display: grid; grid-template-columns: repeat(8, minmax(34px, 1fr)); gap: 8px; }
        .theme-swatch { min-height: 42px; border: 1px solid #2b4056; border-radius: 8px; background: var(--swatch); padding: 0; }
        .theme-swatch.active { border-color: #f8fafc; box-shadow: 0 0 0 2px var(--openreef-accent-border); }
        .color-field { gap: 6px; }
        .picker { display: grid; gap: 9px; align-content: start; }
        .mini-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .candidate-tools { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #8da2ba; font-size: 12px; font-weight: 800; }
        .candidates { display: grid; gap: 7px; }
        .candidate { display: grid; gap: 3px; min-width: 0; text-align: left; }
        .candidate strong, .candidate span, small { min-width: 0; overflow-wrap: anywhere; }
        .candidate span { color: #93a4b8; font-size: 12px; }
        .mapping-card, .equipment-editor { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0e1a28; }
        .mapping-card { gap: 11px; }
        .mapping-card.tank-card, .mapping-card.room-card { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(14, 26, 40, .96) 34%, #0e1a28); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .mapping-card.entity-card { border-color: #3b4257; background: #101d2c; }
        .mapping-card.disabled-card { border-color: #334155; background: #101824; box-shadow: inset 4px 0 0 #475569; }
        .mapping-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .mapping-head h3 { margin-bottom: 0; }
        .mapping-section { display: grid; gap: 12px; border: 1px solid color-mix(in srgb, var(--openreef-accent) 22%, #223447); border-radius: 8px; padding: 14px; background: rgba(11, 23, 36, .82); }
        .mapping-section + .mapping-section { margin-top: 12px; }
        .equipment-editor { position: relative; overflow: hidden; background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(14, 26, 40, .96) 32%, #0e1a28); border-color: var(--openreef-accent-border); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .equipment-editor.disarmed-editor { border-color: #334155; background: #101824; box-shadow: inset 4px 0 0 #475569; }
        .equipment-editor-head { display: grid; grid-template-columns: minmax(180px, 260px) 1fr auto; gap: 12px; align-items: end; padding-bottom: 12px; margin-bottom: 4px; border-bottom: 1px solid rgba(148, 163, 184, .16); }
        .equipment-name input { font-weight: 800; }
        .equipment-summary { display: grid; gap: 7px; min-width: 0; color: #9fb2c7; overflow-wrap: anywhere; }
        .equipment-editor-body { display: grid; gap: 12px; padding-top: 12px; }
        .energy-mapping-summary { display: grid; gap: 12px; }
        .nested-card { background: rgba(11, 23, 36, .72); }
        .equipment-editor .mapping-card.entity-card { background: rgba(16, 29, 44, .82); }
        .equipment-editor.armed-editor .mapping-card.entity-card { border-color: color-mix(in srgb, var(--openreef-accent) 34%, #3b4257); }
        .equipment-group { display: grid; gap: 12px; border: 1px solid #223447; border-radius: 8px; padding: 14px; background: #0b1724; }
        .trend-dialog { max-width: 900px; }
        .range-picker { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
        .compact-center { min-height: 220px; }
        .chart-wrap { display: grid; gap: 8px; border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0b1724; }
        .trend-chart { width: 100%; min-height: 260px; overflow: visible; }
        .trend-chart line { stroke: #24364a; stroke-width: 1; }
        .trend-chart polygon { fill: var(--openreef-accent-soft); }
        .trend-chart polyline { fill: none; stroke: var(--openreef-accent); stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
        .chart-labels, .trend-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; align-items: center; }
        .chart-labels { color: #8da2ba; font-size: 12px; }
        .chart-labels strong { text-align: center; color: #e5edf5; }
        .chart-labels span:last-child { text-align: right; }
        .trend-summary article { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0b1724; display: grid; gap: 6px; }
        .trend-summary span { color: #8da2ba; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
        .trend-summary strong { color: #67e8f9; font-size: 22px; }
        .empty-chart { min-height: 220px; display: grid; place-items: center; color: #8da2ba; border: 1px dashed #294055; border-radius: 8px; }
        .modal { position: fixed; inset: 0; display: grid; place-items: center; padding: 18px; background: rgba(0,0,0,.72); z-index: 10; overflow: hidden; }
        .wizard { position: relative; width: min(1100px, 100%); max-height: min(900px, 92vh); overflow: auto; overscroll-behavior: contain; padding: 28px; display: grid; gap: 18px; box-shadow: 0 24px 80px rgba(0,0,0,.45); }
        .setup-wizard { width: min(1180px, 100%); }
        .close { position: absolute; top: 14px; right: 14px; width: 38px; height: 38px; border-radius: 50%; border: 1px solid #294055; background: #172536; color: #dcecff; }
        .setup-progress { display: grid; gap: 8px; justify-items: center; color: #8da2ba; font-size: 12px; font-weight: 800; }
        .stepper { display: flex; gap: 10px; justify-content: center; }
        .stepper span, .stepper button { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; border: 0; background: #203247; color: #94a3b8; font-weight: 800; padding: 0; }
        .stepper span.on, .stepper button.on { background: var(--openreef-accent); color: #041019; }
        .setup-title { display: grid; gap: 4px; }
        .setup-guide, .setup-choice-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
        .setup-choice-grid.two-choice { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .setup-guide article, .setup-choice, .setup-panel { border: 1px solid color-mix(in srgb, var(--openreef-accent) 24%, #24364a); border-radius: 8px; background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(11, 23, 36, .9)); }
        .setup-guide article, .setup-choice { display: grid; gap: 6px; min-height: 96px; padding: 14px; text-align: left; }
        .setup-choice { color: #e5edf5; }
        .setup-choice:hover, .setup-choice:focus-visible { border-color: var(--openreef-accent); outline: none; box-shadow: 0 0 0 1px var(--openreef-accent-border); }
        .setup-choice.passive { cursor: default; }
        .setup-guide span, .setup-choice span { color: #9fb2c7; }
        .setup-status-line { border: 1px solid #24364a; border-radius: 8px; background: #0b1724; color: #cbd5e1; padding: 12px 14px; font-weight: 800; }
        .preset-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .mode-preset-choice { min-height: 90px; }
        .scheduler-preview { margin-top: 14px; border-style: dashed; }
        .schedule-toolbar { display: flex; gap: 10px; align-items: stretch; justify-content: flex-end; flex-wrap: wrap; }
        .schedule-list { display: grid; gap: 12px; }
        .schedule-card { display: grid; gap: 12px; border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: rgba(11, 23, 36, .72); }
        .schedule-card.ok { border-color: #166534; }
        .schedule-card.warning { border-color: #a16207; background: rgba(47, 38, 20, .48); }
        .schedule-card.disabled { opacity: .82; border-color: #334155; }
        .schedule-fields { display: grid; grid-template-columns: minmax(170px, .7fr) minmax(130px, .35fr) minmax(220px, 1fr) minmax(220px, 1fr); gap: 10px; align-items: stretch; }
        .schedule-days { display: flex; gap: 7px; flex-wrap: wrap; }
        .schedule-days button { border: 1px solid #294055; border-radius: 999px; padding: 7px 10px; background: #172536; color: #dcecff; font-weight: 800; }
        .schedule-days button.active { border-color: var(--openreef-accent); background: var(--openreef-accent); color: #041019; }
        .compact-toggle { min-width: 220px; padding: 10px; }
        .setup-next-list { display: grid; gap: 10px; }
        .setup-next-list div { display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: center; border-top: 1px solid #223447; padding-top: 10px; }
        .setup-next-list div:first-child { border-top: 0; padding-top: 0; }
        .wizard-actions { justify-content: space-between; padding-top: 8px; }
        .center-card { min-height: 60vh; display: grid; place-items: center; gap: 16px; color: #8da2ba; }
        .spinner { width: 36px; height: 36px; border: 3px solid #203247; border-top-color: var(--openreef-accent); border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 900px) {
          .page { padding: 12px; }
          .topbar, .hero, .section-head, .card-head, .settings-section-head, .mode-confirm-row, .mode-strip { flex-direction: column; align-items: stretch; }
          .equipment-editor-head { grid-template-columns: 1fr; align-items: stretch; }
          .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .grid.two, .grid.three, .grid.four { grid-template-columns: 1fr; }
          .mode-actions { grid-template-columns: 1fr; }
          .mode-mini-row, .preset-row, .mode-timer-card, .mode-name-grid, .scheduler-preview, .schedule-fields { grid-template-columns: 1fr; }
          .issue-item { grid-template-columns: 1fr; }
          .activity-item { grid-template-columns: 1fr; }
          .detail-grid, .entity-detail-row, .energy-metrics { grid-template-columns: 1fr; }
          .range-picker { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .trend-summary { grid-template-columns: 1fr; }
          .setup-guide, .setup-choice-grid, .setup-choice-grid.two-choice { grid-template-columns: 1fr; }
          .setup-next-list div { grid-template-columns: 1fr; }
        }
      </style>
    `;
  }
}

customElements.define("openreef-panel", OpenReefPanel);
