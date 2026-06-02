class OpenReefPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._integrationVersion = "";
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
    this._healthTrends = { checkedAt: "", items: {}, error: "" };
    this._consumption = { checkedAt: "", items: {}, error: "" };
    this._modeConfirm = null;
    this._controlConfirm = null;
    this._equipmentDetail = null;
    this._configDirty = false;
    this._modeCountdownTimer = null;
    this._lastModeAutoReturnRefresh = 0;
    this._equipmentEditors = {};
    this._equipmentEnergyEditors = {};
    this._settingsSections = this._loadSettingsSections();
    this._healthSections = this._loadHealthSections();
    this._manualHistoryOpen = {};
    this._manualEntryDefaults = {};
    this._onboarding = null;
    this._onboardingChecked = false;
    this._avatarPoses = {};
    this._stickerReady = false;
    this._walkReady = false;
    this._buddy = { dismissed: false, expanded: false, lastKey: "", timer: null };
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
    if (this._onboarding && this._onboarding.active) return false;
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

  _defaultSettingsSections() {
    return {
      profile: false,
      mission: false,
      sensors: false,
      manualTests: false,
      equipment: false,
      modes: false,
      alerts: false,
      interlocks: false,
      energy: false,
      system: false,
    };
  }

  _setupSteps() {
    return ["Profile", "Sensors", "Manual Tests", "Equipment", "Safety", "Review"];
  }

  _lastSetupStep() {
    return this._setupSteps().length - 1;
  }

  _loadSettingsSections() {
    const defaults = this._defaultSettingsSections();
    try {
      const stored = window.localStorage?.getItem("openreef:settingsSections:v1");
      if (!stored) return defaults;
      const parsed = JSON.parse(stored);
      return { ...defaults, ...(parsed && typeof parsed === "object" ? parsed : {}) };
    } catch {
      return defaults;
    }
  }

  _saveSettingsSections() {
    try {
      window.localStorage?.setItem("openreef:settingsSections:v1", JSON.stringify(this._settingsSections));
    } catch {
      // Section memory is a convenience only; OpenReef still works without localStorage.
    }
  }

  _defaultHealthSections() {
    return {
      details: false,
      action: false,
      watch: false,
      context: false,
      learning: false,
      "dosing-advice": false,
    };
  }

  _loadHealthSections() {
    const defaults = this._defaultHealthSections();
    try {
      const stored = window.localStorage?.getItem("openreef:healthSections:v2");
      if (!stored) return defaults;
      const parsed = JSON.parse(stored);
      return { ...defaults, ...(parsed && typeof parsed === "object" ? parsed : {}) };
    } catch {
      return defaults;
    }
  }

  _saveHealthSections() {
    try {
      window.localStorage?.setItem("openreef:healthSections:v2", JSON.stringify(this._healthSections));
    } catch {
      // Insight section memory is a convenience only.
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
      this._integrationVersion = result.version || this._integrationVersion;
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
      this._integrationVersion = result.version || this._integrationVersion;
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
      this._integrationVersion = result.version || this._integrationVersion;
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
    this._integrationVersion = result.version || this._integrationVersion;
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
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      this._validation = await this._callWS({ type: "openreef/validate_config" });
      await this._refreshHealthTrends();
      this._message = "Checks refreshed";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not validate OpenReef";
    } finally {
      this._busy = false;
    }
    this._render();
  }

  async _refreshHealthTrends() {
    const sensors = this._enabledSensors()
      .filter(([id, sensor]) => this._sensorKind(sensor, id) !== "binary")
      .filter(([, sensor]) => Boolean(sensor.entity_id));
    const items = {};
    const consumptionItems = {};
    const dosingIds = new Set(this._dosingParameterIds());

    for (let index = 0; index < sensors.length; index += 2) {
      const chunk = sensors.slice(index, index + 2);
      await Promise.all(chunk.map(async ([id, sensor]) => {
        try {
          // Fetch once, analyse twice: the same 7d trend feeds both the
          // Reef Health Score and the advisory Dosing & Consumption Advisor.
          const trendData = await this._fetchHealthTrendData(sensor.entity_id);
          const healthItem = this._analyseHealthTrend(id, sensor, trendData);
          items[id] = healthItem;
          if (dosingIds.has(id)) {
            // Stability is borrowed from the health trend (single source of truth).
            consumptionItems[id] = this._analyseConsumption(id, sensor, trendData, healthItem);
          }
        } catch (err) {
          const detail = err instanceof Error ? err.message : "Trend history unavailable.";
          items[id] = {
            status: "learning",
            group: "learning",
            category: this._sensorHealthCategory(id, sensor),
            penalty: 0,
            affectsScore: false,
            label: `${sensor.label || id} trend learning`,
            detail,
          };
          if (dosingIds.has(id)) {
            consumptionItems[id] = this._consumptionLearning(id, sensor, detail);
          }
        }
      }));
    }

    this._dosingActiveParameters().forEach(([id, sensor]) => {
      if ((consumptionItems[id] && consumptionItems[id].status !== "learning") || this._manualReadings(id).length < 2) return;
      const trendData = this._manualTrendData(id);
      const healthItem = this._analyseHealthTrend(id, sensor, trendData);
      consumptionItems[id] = this._analyseConsumption(id, sensor, trendData, healthItem);
    });

    const checkedAt = new Date().toISOString();
    this._healthTrends = {
      checkedAt,
      items,
      error: "",
    };
    this._consumption = {
      checkedAt,
      items: consumptionItems,
      error: "",
    };
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
      const result = await this._callWS({ type: "openreef/toggle_equipment", equipment_id: equipmentId });
      this._config = result.config || this._config;
      this._validation = result.validation || this._validation;
      const safetyActions = result.safety_actions || [];
      this._recordActivity(`${label} turned ${desired}`, "control");
      await this._persistConfigSilently();
      this._message = `${label} turned ${desired}${safetyActions.length ? `; ${safetyActions.length} safety action${safetyActions.length === 1 ? "" : "s"} applied` : ""}`;
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
      this._integrationVersion = refreshed.version || this._integrationVersion;
      this._validation = refreshed.validation || this._validation;
      this._configDirty = false;
      const applied = result.applied?.length || 0;
      const delayed = (result.applied || []).filter((item) => item?.state === "delayed_on").length;
      const locked = result.skipped_locked?.length || 0;
      const unavailable = result.skipped_missing?.length || 0;
      const wavemakerBlocked = (result.skipped_locked || []).filter(
        (item) => item?.reason === "Display wavemaker automatic restart blocked",
      ).length;
      this._message = `Mode applied: ${applied} changed${delayed ? `, ${delayed} delayed restart` : ""}, ${locked} locked, ${unavailable} unavailable${wavemakerBlocked ? `, ${wavemakerBlocked} display wavemaker restart blocked` : ""}`;
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
      this._integrationVersion = result.version || this._integrationVersion;
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
      this._integrationVersion = result.version || this._integrationVersion;
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

  _loadManualTrend(parameterId, range = this._trend?.source === "manual" ? this._trend.range : "all") {
    const meta = this._manualTestMeta(parameterId);
    const points = this._manualTrendPoints(parameterId, range);
    this._trendRequest = `manual:${parameterId}:${range}:${Date.now()}`;
    this._trend = {
      sensorId: parameterId,
      entityId: "Manual test results",
      range,
      source: "manual",
      loading: false,
      points,
      error: points.length >= 2 ? "" : "Add at least two dated manual results to chart this parameter.",
      manualMeta: meta,
    };
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

  async _fetchHealthTrendData(entityId) {
    const end = new Date();
    const sevenDayStart = new Date(end.getTime() - this._trendRangeMs("7d"));
    const dayStart = new Date(end.getTime() - this._trendRangeMs("24h"));
    const statisticPoints = await this._fetchStatisticTrendPoints(entityId, sevenDayStart, end, "7d");

    if (statisticPoints.length >= 8 && this._trendDays(statisticPoints).length >= 4) {
      return { points: statisticPoints, range: "7d", source: "statistics" };
    }

    const sevenDayHistoryPoints = await this._fetchHistoryTrendPoints(entityId, sevenDayStart, end, {
      maxPoints: 420,
    });
    if (sevenDayHistoryPoints.length >= 8 && this._trendDays(sevenDayHistoryPoints).length >= 2) {
      return { points: sevenDayHistoryPoints, range: "7d", source: "history" };
    }

    const historyPoints = await this._fetchHistoryTrendPoints(entityId, dayStart, end, {
      maxPoints: 240,
    });
    return {
      points: historyPoints.length ? historyPoints : statisticPoints,
      range: historyPoints.length ? "24h" : "7d",
      source: historyPoints.length ? "history" : "statistics",
    };
  }

  async _fetchHistoryTrendPoints(entityId, start, end, options = {}) {
    const significantChangesOnly = Boolean(options.significantChangesOnly);
    if (typeof this._hass?.callApi === "function") {
      const params = new URLSearchParams({
        end_time: end.toISOString(),
        filter_entity_id: entityId,
        minimal_response: "1",
        no_attributes: "1",
        significant_changes_only: significantChangesOnly ? "1" : "0",
      });
      const raw = await this._hass.callApi(
        "GET",
        `history/period/${encodeURIComponent(start.toISOString())}?${params.toString()}`,
      );
      return this._thinTrendPoints(this._historyPoints(raw, entityId), options.maxPoints);
    }

    const raw = await this._callWS({
      type: "history/history_during_period",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      entity_ids: [entityId],
      minimal_response: true,
      significant_changes_only: significantChangesOnly,
    });
    return this._thinTrendPoints(this._historyPoints(raw, entityId), options.maxPoints);
  }

  _thinTrendPoints(points, maxPoints) {
    if (!Number.isFinite(maxPoints) || !Array.isArray(points) || points.length <= maxPoints) return points;
    if (maxPoints <= 2) return [points[0], points[points.length - 1]].filter(Boolean);
    const indexes = new Set([0, points.length - 1]);
    const step = (points.length - 1) / (maxPoints - 1);
    for (let index = 1; index < maxPoints - 1; index += 1) {
      indexes.add(Math.round(index * step));
    }
    return [...indexes].sort((a, b) => a - b).map((index) => points[index]).filter(Boolean);
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

  _manualTrendRanges() {
    return [
      ["30d", "30 days", 30 * 24 * 60 * 60 * 1000],
      ["90d", "90 days", 90 * 24 * 60 * 60 * 1000],
      ["180d", "180 days", 180 * 24 * 60 * 60 * 1000],
      ["365d", "1 year", 365 * 24 * 60 * 60 * 1000],
      ["all", "All history", Number.POSITIVE_INFINITY],
    ];
  }

  _trendRangeMs(range) {
    return this._trendRanges().find(([id]) => id === range)?.[2]
      || this._manualTrendRanges().find(([id]) => id === range)?.[2]
      || 24 * 60 * 60 * 1000;
  }

  _trendRangeLabel(range) {
    return this._trendRanges().find(([id]) => id === range)?.[1]
      || this._manualTrendRanges().find(([id]) => id === range)?.[1]
      || "24 hours";
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
      if (action === "onboarding-start") this._startOnboarding();
      if (action === "onboarding-next") this._onboardingNext();
      if (action === "onboarding-back") this._onboardingBack();
      if (action === "onboarding-skip") this._endOnboarding(true);
      if (action === "onboarding-tone") this._toggleTone();
      if (action === "buddy-toggle") {
        if (this._buddy.timer) { clearTimeout(this._buddy.timer); this._buddy.timer = null; }
        this._buddy.expanded = !this._buddy.expanded;
        this._render();
      }
      if (action === "buddy-dismiss") {
        // Session hide only (he's on by default and returns next load — no dead-end).
        if (this._buddy.timer) { clearTimeout(this._buddy.timer); this._buddy.timer = null; }
        this._buddy.dismissed = true;
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
        this._setupStep = Math.min(this._setupStep + 1, this._lastSetupStep());
        this._render();
      }
      if (action === "prev-step") {
        this._setupStep = Math.max(this._setupStep - 1, 0);
        this._render();
      }
      if (action === "setup-step") {
        this._setupStep = Math.max(0, Math.min(Number(target.dataset.step || 0), this._lastSetupStep()));
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
      if (action === "clear-sensor") {
        this._config.sensors[id].entity_id = "";
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
      if (action === "clear-equipment-field") {
        this._config.equipment[id][field] = "";
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
      if (action === "clear-energy-field") {
        this._config.energy[field] = "";
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
      if (action === "apply-manual-schedule-preset") {
        this._applyManualSchedulePreset();
        this._setDirty(true);
        this._render();
      }
      if (action === "save-manual-reading") this._saveManualReadingFromForm();
      if (action === "save-manual-batch") this._saveManualBatchFromForm();
      if (action === "copy-manual-csv") this._copyManualCsv();
      if (action === "download-manual-csv") this._downloadManualCsv();
      if (action === "copy-manual-template") this._copyManualTemplate();
      if (action === "import-manual-csv") this._importManualCsvFromForm();
      if (action === "delete-manual-reading") this._deleteManualReading(id, target.dataset.reading);
      if (action === "toggle-manual-history") {
        this._manualHistoryOpen[id] = !this._manualHistoryOpen[id];
        this._render();
      }
      if (action === "show-manual-trend") this._loadManualTrend(id);
      if (action === "manual-entry-now") {
        this._manualEntryDefaults.timestamp = this._nowLocalInputValue();
        this._render();
      }
      if (action === "setup-add-starter-equipment") this._addStarterEquipment();
      if (action === "add-custom-mode") this._addCustomMode();
      if (action === "remove-custom-mode") this._removeCustomMode(target.dataset.mode);
      if (action === "add-mode-schedule") this._addModeSchedule();
      if (action === "remove-mode-schedule") this._removeModeSchedule(target.dataset.schedule);
      if (action === "add-schedule-time") this._addScheduleTime(target.dataset.schedule);
      if (action === "remove-schedule-time") this._removeScheduleTime(target.dataset.schedule, Number(target.dataset.index));
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
        this._saveSettingsSections();
        this._render();
      }
      if (action === "expand-settings") {
        Object.keys(this._settingsSections).forEach((section) => {
          this._settingsSections[section] = true;
        });
        this._saveSettingsSections();
        this._render();
      }
      if (action === "collapse-settings") {
        Object.keys(this._settingsSections).forEach((section) => {
          this._settingsSections[section] = false;
        });
        this._saveSettingsSections();
        this._render();
      }
      if (action === "toggle-health-section") {
        const section = target.dataset.section;
        this._healthSections[section] = !this._healthSectionOpen(section);
        this._saveHealthSections();
        this._render();
      }
      if (action === "copy-support-summary") this._copySupportSummary();
      if (action === "copy-dosing-summary") this._copyDosingSummary();
      if (action === "copy-beta-smoke-test") this._copyBetaSmokeTest();
      if (action === "copy-beta-feedback-template") this._copyBetaFeedbackTemplate();
      if (action === "clear-activity") {
        this._config.activity = [];
        this._saveConfig();
      }
      if (action === "show-trend") this._loadTrend(id);
      if (action === "trend-range") {
        if (this._trend?.source === "manual") this._loadManualTrend(id, target.dataset.range);
        else this._loadTrend(id, target.dataset.range);
      }
      if (action === "close-trend") {
        this._trend = null;
        this._trendRequest = "";
        this._render();
      }
      if (action === "refresh-trend") {
        if (this._trend?.source === "manual") this._loadManualTrend(id, this._trend?.range || "all");
        else this._loadTrend(id, this._trend?.range || "24h");
      }
    });

    const handleFieldInput = (event) => {
      const target = event.target;
      if (!target.dataset) return;
      const scope = target.dataset.scope;
      const id = target.dataset.id;
      const field = target.dataset.field;
      const value = target.type === "checkbox" ? target.checked : target.type === "number" ? Number(target.value) : target.value;

      if (target.dataset.manualField === "parameter") {
        const unitInput = this.shadowRoot.querySelector('[data-manual-field="unit"]');
        if (unitInput) unitInput.value = this._manualTestMeta(value).unit || "";
        const sourceInput = this.shadowRoot.querySelector('[data-manual-field="source"]');
        if (sourceInput) sourceInput.value = this._manualTestConfig(value).preferredSource || "";
        return;
      }
      if (target.dataset.manualBatchField) {
        this._manualEntryDefaults[target.dataset.manualBatchField] = value;
        return;
      }
      if (target.dataset.manualBatchSource) {
        this._manualEntryDefaults.sources = this._manualEntryDefaults.sources || {};
        this._manualEntryDefaults.sources[target.dataset.manualBatchSource] = value;
        return;
      }
      if (target.dataset.manualImportField) {
        this._manualEntryDefaults.importText = value;
        return;
      }
      if (scope === "tank") this._config.tank[field] = value;
      if (scope === "display") this._config.display[field] = value;
      if (scope === "sensor") {
        this._config.sensors = this._config.sensors || {};
        this._config.sensors[id] = this._config.sensors[id] || {};
        this._config.sensors[id][field] = value;
      }
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
      if (scope === "mode-schedule-time") {
        const schedule = this._scheduleItem(id);
        const index = Number(target.dataset.index);
        if (schedule && Number.isInteger(index)) {
          schedule.times = this._scheduleTimes(schedule);
          schedule.times[index] = value;
          schedule.time = schedule.times[0] || "";
        }
      }
      if (scope === "mission-card") {
        this._config.display.missionCards = this._missionCards();
        this._config.display.missionCards[id] = value;
      }
      if (scope === "dosing") {
        this._config.dosing = this._config.dosing || { enabled: true, parameters: {} };
        if (field === "enabled") {
          this._config.dosing.enabled = value;
        } else {
          this._config.dosing.parameters = this._config.dosing.parameters || {};
          this._config.dosing.parameters[id] = this._config.dosing.parameters[id] || {};
          if (field === "productPreset") {
            this._applyDosingProductPreset(id, value);
          } else {
            this._config.dosing.parameters[id][field] = Math.max(0, Number(value) || 0);
          }
        }
      }
      if (scope === "dosing-system") {
        this._config.dosing = this._config.dosing || { enabled: true, parameters: {}, system: {} };
        this._config.dosing.system = this._config.dosing.system || {};
        if (target.type === "checkbox") {
          this._config.dosing.system[field] = value;
        } else if (target.type === "number") {
          this._config.dosing.system[field] = Math.max(0, Number(value) || 0);
        } else {
          this._config.dosing.system[field] = value;
        }
      }
      if (scope === "manual-tests") {
        this._config.manualTests = this._config.manualTests || { enabled: true, schedules: {} };
        this._config.manualTests[field] = value;
      }
      if (scope === "manual-test") {
        this._config.manualTests = this._config.manualTests || { enabled: true, schedules: {} };
        this._config.manualTests.schedules = this._config.manualTests.schedules || {};
        this._config.manualTests.schedules[id] = this._config.manualTests.schedules[id] || {};
        const schedule = this._config.manualTests.schedules[id];
        if (field === "cadenceDays") {
          const cadenceDays = Math.max(1, Math.min(365, Number(value) || 1));
          schedule.cadenceDays = cadenceDays;
          const criticalAfterDays = Number(schedule.criticalAfterDays);
          if (!Number.isFinite(criticalAfterDays) || criticalAfterDays < cadenceDays) {
            schedule.criticalAfterDays = Math.min(730, cadenceDays * 2);
          }
        } else if (field === "criticalAfterDays") {
          const cadenceDays = Math.max(1, Math.min(365, Number(schedule.cadenceDays) || this._manualSuggestedCadenceDays(id)));
          schedule.criticalAfterDays = Math.max(cadenceDays, Math.min(730, Number(value) || cadenceDays * 2));
        } else {
          schedule[field] = value;
        }
      }
      if (scope) this._setDirty(true);
      if (scope === "display" && field === "themeColor") this._render();
      if (
        (scope === "mode-schedule" || scope === "mode-schedule-time" || scope === "mode-schedule-global" || scope === "manual-tests" || (scope === "manual-test" && ["enabled", "cadenceDays", "criticalAfterDays"].includes(field)) || scope === "dosing-system" || (scope === "dosing" && field === "productPreset") || (scope === "equipment" && field === "type") || (scope === "tank" && field === "profile"))
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
      powerOnDelaySeconds: type === "skimmer" ? 300 : type === "ato" ? 120 : 0,
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
        powerOnDelaySeconds: type === "skimmer" ? 300 : type === "ato" ? 120 : 0,
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

  _scheduleTimes(item) {
    const rawTimes = Array.isArray(item?.times) ? item.times : [];
    const times = rawTimes.filter((time) => typeof time === "string" && time);
    if (!times.length && item?.time) times.push(item.time);
    return [...new Set(times)].slice(0, 24);
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
      times: ["12:00"],
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

  _addScheduleTime(scheduleId) {
    const item = this._scheduleItem(scheduleId);
    if (!item) return;
    item.times = this._scheduleTimes(item);
    if (item.times.length >= 24) return;
    item.times.push("12:00");
    item.time = item.times[0] || "";
    this._setDirty(true);
    this._render();
  }

  _removeScheduleTime(scheduleId, index) {
    const item = this._scheduleItem(scheduleId);
    if (!item) return;
    item.times = this._scheduleTimes(item).filter((_, itemIndex) => itemIndex !== index);
    if (!item.times.length) item.times = ["12:00"];
    item.time = item.times[0] || "";
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

  _sensorPresetDefinitions() {
    const apexBase = ["temp", "sump_temp", "ph", "orp", "salinity"];
    const trident = ["alkalinity", "calcium", "magnesium"];
    const tridentNp = ["nitrate", "phosphate"];
    const fmm = ["flow", "leak", "high_water", "low_water"];
    return {
      tank: {
        label: "OpenReef basics",
        sensors: ["temp", "ph", "salinity"],
      },
      apex: {
        label: "Apex controller",
        sensors: apexBase,
      },
      trident: {
        label: "Apex + Trident",
        sensors: [...apexBase, ...trident],
      },
      trident_np: {
        label: "Apex + Trident NP",
        sensors: [...apexBase, ...tridentNp],
      },
      apex_trident_np: {
        label: "Apex + Trident + Trident NP",
        sensors: [...apexBase, ...trident, ...tridentNp],
      },
      apex_np: {
        label: "Apex + Trident + Trident NP",
        sensors: [...apexBase, ...trident, ...tridentNp],
      },
      apex_fmm: {
        label: "Apex + FMM",
        sensors: [...apexBase, ...fmm],
      },
      apex_full: {
        label: "Apex full ecosystem",
        sensors: [...apexBase, ...trident, ...tridentNp, ...fmm],
      },
      all: {
        label: "Everything available",
        sensors: null,
      },
      minimal: {
        label: "Temperature only",
        sensors: ["temp"],
      },
    };
  }

  _sensorPresetDefinition(preset) {
    const definitions = this._sensorPresetDefinitions();
    return definitions[preset] || definitions.tank;
  }

  _applySensorPreset(preset) {
    const sensors = this._config.sensors || {};
    const definition = this._sensorPresetDefinition(preset);
    const enabled = definition.sensors ? new Set(definition.sensors) : null;
    Object.entries(sensors).forEach(([id, sensor]) => {
      sensor.enabled = enabled ? enabled.has(id) : true;
    });
    this._recordActivity(`Setup sensor preset selected: ${definition.label}`);
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

  _sensorKind(sensor, sensorId = "") {
    return sensor?.kind || this._sensorMeta?.[sensorId]?.kind || "numeric";
  }

  _binarySensorStatus(rawState) {
    const value = String(rawState || "").trim().toLowerCase();
    if (["on", "wet", "detected", "leaking", "leak", "flood", "problem", "unsafe", "active", "high", "low", "1", "true"].includes(value)) {
      return "critical";
    }
    if (["off", "dry", "clear", "safe", "ok", "normal", "inactive", "closed", "0", "false"].includes(value)) {
      return "ok";
    }
    return "warning";
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
    if (this._sensorKind(sensor, sensorId) === "binary") {
      const state = this._state(sensor.entity_id);
      if (!sensor.entity_id || !state || ["unknown", "unavailable"].includes(state.state)) return "unknown";
      return this._binarySensorStatus(state.state);
    }
    const value = this._number(sensor.entity_id);
    if (value === null) return "unknown";
    if (value < Number(sensor.min) || value > Number(sensor.max)) return "critical";
    const bufferPercent = Math.max(0, Math.min(Number(sensor.warningBuffer ?? 10), 50)) / 100;
    const buffer = (Number(sensor.max) - Number(sensor.min)) * bufferPercent;
    const hysteresisPercent = Math.max(0, Math.min(Number(this._config?.alerts?.hysteresisPercent ?? 2), 20)) / 100;
    const hysteresis = (Number(sensor.max) - Number(sensor.min)) * hysteresisPercent;
    const lowerWarning = Number(sensor.min) + buffer;
    const upperWarning = Number(sensor.max) - buffer;
    const previousState = this._config?.alerts?.lastStates?.[sensorId];
    const stickyWarning = ["warning", "critical"].includes(previousState)
      && (value < lowerWarning + hysteresis || value > upperWarning - hysteresis);
    if (value < lowerWarning || value > upperWarning || stickyWarning) return "warning";
    return "ok";
  }

  _sensorStatusLabel(status) {
    if (status === "muted") return "alerts off";
    if (status === "unknown") return "not reporting";
    if (status === "ok") return "ok";
    return status;
  }

  _sensorStatusDetail(sensor, sensorId = "") {
    if (!this._sensorEnabled(sensor)) return "Disabled and hidden from dashboards.";
    const mutedUntil = this._formatMutedUntil(sensorId);
    if (mutedUntil) return `Alerts muted until ${mutedUntil}. The live reading can still be used.`;
    if (sensor.alertsEnabled === false) return "Mission Control alerts are off. The live reading can still be used.";
    const status = this._sensorStatus(sensor, sensorId);
    if (this._sensorKind(sensor, sensorId) === "binary") {
      if (status === "unknown") return sensor.entity_id ? "Mapped, but Home Assistant is not reporting a clear state." : "No entity is mapped yet.";
      if (status === "critical") return "This safety sensor is active.";
      if (status === "warning") return "Home Assistant returned an unexpected state for this safety sensor.";
      return "Live and reporting its normal state.";
    }
    if (status === "unknown") return sensor.entity_id ? "Mapped, but Home Assistant is not reporting a numeric value." : "No entity is mapped yet.";
    if (status === "critical") return "Outside the configured safe range.";
    if (status === "warning") return "Near the configured warning threshold.";
    return "Live and inside the configured range.";
  }

  _sensorSupportStatus(sensor, sensorId = "") {
    const status = this._sensorStatus(sensor, sensorId);
    if (status === "muted") return `alerts off; ${this._sensorStatusDetail(sensor, sensorId)}`;
    return status;
  }

  _sensorDisplayValue(sensorId, sensor) {
    if (this._sensorKind(sensor, sensorId) === "binary") {
      const state = this._state(sensor.entity_id);
      if (!sensor.entity_id) return "Not mapped";
      if (!state || state.state === "unknown" || state.state === "unavailable") return "Unknown";
      return String(state.state).replaceAll("_", " ");
    }
    return this._format(this._number(sensor.entity_id), this._sensorDigits(sensorId));
  }

  _sensorDisplayUnit(sensorId, sensor) {
    return this._sensorKind(sensor, sensorId) === "binary" ? "" : (sensor.unit || "");
  }

  _format(value, digits = 1) {
    return Number.isFinite(value) ? Number(value).toFixed(digits) : "--";
  }

  _sensorDigits(sensorId) {
    if (sensorId === "ph" || sensorId === "alkalinity") return 2;
    if (sensorId === "phosphate") return 3;
    if (["nitrate", "dissolved_oxygen"].includes(sensorId)) return 2;
    if (["orp", "calcium", "magnesium", "co2", "flow", "par"].includes(sensorId)) return 0;
    return 1;
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

  _tankProfileChoices() {
    return [
      ["fish_only_fowlr", "Fish-only / FOWLR", "Life support and equipment reliability matter most."],
      ["soft_coral", "Soft coral", "Forgiving weighting for easier coral systems."],
      ["lps", "LPS reef", "Balanced stability and chemistry weighting."],
      ["sps", "SPS reef", "Tighter stability and chemistry weighting."],
      ["mixed_reef", "Mixed reef", "Balanced default for most reef tanks."],
      ["anemone_dominant", "Anemone-dominant", "Emphasises stable life support and display flow."],
    ];
  }

  _tankProfile() {
    const profile = this._config?.tank?.profile || "mixed_reef";
    return this._tankProfileChoices().some(([id]) => id === profile) ? profile : "mixed_reef";
  }

  _tankProfileLabel(profile = this._tankProfile()) {
    return this._tankProfileChoices().find(([id]) => id === profile)?.[1] || "Mixed reef";
  }

  _tankProfileDetail(profile = this._tankProfile()) {
    return this._tankProfileChoices().find(([id]) => id === profile)?.[2] || "Balanced default for most reef tanks.";
  }

  _tankProfileHealthNote(profile = this._tankProfile()) {
    const notes = {
      fish_only_fowlr: "FOWLR scoring cares most about temperature, oxygen, flow, water safety, and reliable equipment. Coral chemistry trends are kept lighter.",
      soft_coral: "Soft coral scoring is forgiving: OpenReef still checks stability, but it avoids overreacting to small chemistry movement.",
      lps: "LPS scoring balances water stability, chemistry, and life-support. Small daily movement is expected; persistent drift matters more.",
      sps: "SPS scoring is stricter on alkalinity, salinity, temperature stability, and chemistry drift because these tanks usually have less margin.",
      mixed_reef: "Mixed reef scoring is balanced: life-support comes first, then stability and chemistry trends. Normal pH day/night movement is expected.",
      anemone_dominant: "Anemone scoring emphasises life-support, stable conditions, and display flow because wandering or stressed anemones can affect the whole tank.",
    };
    return notes[profile] || notes.mixed_reef;
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
    if (sensor?.group === "room") return "Room";
    if (sensor?.group === "sump") return "Sump";
    if (sensor?.group === "chemistry") return "Chemistry";
    if (sensor?.group === "water") return "Water";
    if (sensor?.group === "safety") return "Safety";
    if (sensor?.group === "flow") return "Flow";
    if (sensor?.group === "lighting") return "Lighting";
    return "Display";
  }

  _sensorGroupClass(sensor) {
    if (sensor?.group === "room") return "room-card";
    if (sensor?.group === "sump") return "sump-card";
    if (sensor?.group === "chemistry") return "chemistry-card";
    if (sensor?.group === "water") return "water-card";
    if (sensor?.group === "safety") return "safety-sensor-card";
    if (sensor?.group === "flow") return "flow-card";
    if (sensor?.group === "lighting") return "lighting-card";
    return "tank-card";
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
        const display = this._sensorDisplayValue(id, sensor);
        const unit = this._sensorDisplayUnit(id, sensor);
        const isBinary = this._sensorKind(sensor, id) === "binary";
        const range = isBinary ? "normal state" : `${sensor.min} - ${sensor.max} ${unit}`.trim();
        const title = status === "unknown"
          ? `${sensor.label} is not reporting`
          : isBinary
            ? `${sensor.label} active`
            : `${sensor.label} ${status === "critical" ? "outside range" : "near threshold"}`;
        const detail = status === "unknown"
          ? (sensor.entity_id || "No entity mapped")
          : isBinary
            ? `${sensor.entity_id || "Sensor"} reports ${display}`
            : `${display} ${unit} · target ${range}`;
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
      return "Top-off control should stay deliberate. If you want scheduled ATO power windows, use the duty-cycle safety schedule.";
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

  _returnPumpDependencyIssues() {
    return Object.entries(this._config.equipment || {})
      .filter(([id, item]) => item.armed && this._equipmentProfile(id, item) === "return_pump" && item.switch_entity_id)
      .filter(([, item]) => this._stateValue(item.switch_entity_id) !== "on")
      .map(([id, item]) => item.label || id);
  }

  _atoHeldByReturnPump() {
    const interlocks = this._config.interlocks || {};
    return interlocks.atoBlockWhenReturnPumpOff === true && this._returnPumpDependencyIssues().length > 0;
  }

  _equipmentSafetyStatus(id, item) {
    const profile = this._equipmentProfile(id, item);
    if (profile === "ato" && this._atoHeldByReturnPump()) {
      return ["critical", "Held by return pump safety", `Return flow is not confirmed: ${this._returnPumpDependencyIssues().join(", ")}`];
    }
    if (profile === "ato" && this._config.interlocks?.atoDutyCycleEnabled === true) {
      const state = this._stateValue(item.switch_entity_id);
      return [
        state === "on" ? "warning" : "unknown",
        state === "on" ? "ATO schedule window active" : "Held by ATO schedule",
        `ATO power is limited to ${this._config.interlocks.atoDutyCycleOnSeconds || 120}s every ${this._config.interlocks.atoDutyCycleIntervalMinutes || 60}m.`,
      ];
    }
    if (profile === "skimmer" && this._returnPumpDependencyIssues().length > 0) {
      const autoOff = this._config.interlocks?.skimmerAutoOffWhenReturnPumpOff === true;
      return [
        autoOff ? "warning" : "unknown",
        autoOff ? "Skimmer protected by return pump safety" : "Return pump is not running",
        autoOff
          ? "If the return pump is turned off through OpenReef, armed skimmers are turned off automatically."
          : "Consider enabling skimmer auto-off before leaving this unattended.",
      ];
    }
    if (Number.isFinite(Number(item?.powerOnDelaySeconds)) && Number(item.powerOnDelaySeconds) > 0) {
      return ["unknown", "Delayed restart configured", `When restored by a mode, restart waits ${item.powerOnDelaySeconds}s.`];
    }
    return null;
  }

  _controlAvailable(id, item) {
    if (!item?.switch_entity_id) return false;
    if (!item.armed) return false;
    const state = this._stateValue(item.switch_entity_id);
    if (this._equipmentProfile(id, item) === "ato" && state === "off" && this._atoHeldByReturnPump()) return false;
    return state === "on" || state === "off";
  }

  _controlBlockReason(item, id = "") {
    if (!item?.switch_entity_id) return "Map a switch in Settings";
    if (!item.armed) return "Disarmed in Settings";
    const state = this._stateValue(item.switch_entity_id);
    if (state !== "on" && state !== "off") return `Switch is ${state}`;
    if (this._equipmentProfile(id, item) === "ato" && state === "off" && this._atoHeldByReturnPump()) return "Held by return pump safety";
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
    if (interlocks.atoDutyCycleEnabled === true) {
      const armedAto = equipment.filter(
        ([id, item]) => item.armed && this._equipmentProfile(id, item) === "ato" && item.switch_entity_id,
      );
      if (!armedAto.length) {
        warnings.push({
          title: "ATO safety schedule has no armed ATO",
          detail: "Enable an ATO equipment item, map its switch, and arm it before the duty-cycle safety schedule can run.",
        });
      }
    }
    const returnPumpIssues = this._returnPumpDependencyIssues();
    const armedAtoWithSwitch = equipment.filter(
      ([id, item]) => item.armed && this._equipmentProfile(id, item) === "ato" && item.switch_entity_id,
    );
    if (armedAtoWithSwitch.length && returnPumpIssues.length && (interlocks.atoReturnPumpWarning !== false || interlocks.atoBlockWhenReturnPumpOff === true)) {
      warnings.push({
        title: interlocks.atoBlockWhenReturnPumpOff === true ? "ATO held by return pump safety" : "ATO can run while return pump is off",
        detail: interlocks.atoBlockWhenReturnPumpOff === true
          ? `OpenReef will block ATO power-on while return flow is not confirmed: ${returnPumpIssues.join(", ")}.`
          : `Return flow is not confirmed: ${returnPumpIssues.join(", ")}. Consider enabling the ATO return-pump block before unattended use.`,
      });
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
            const delay = Number(item.powerOnDelaySeconds || 0);
            detail = modeId === "running"
              ? `${switchEntity} is currently ${current}; restore to ${desiredState}${desiredState === "on" && delay ? ` after ${delay}s delay` : ""}`
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

  async _copySupportSummary() {
    await this._copyText(this._supportSummaryText(), "Support summary copied", "Could not copy support summary");
  }

  async _copyDosingSummary() {
    await this._copyText(this._dosingSummaryText(), "Dosing summary copied", "Could not copy dosing summary");
  }

  async _copyBetaSmokeTest() {
    await this._copyText(this._betaSmokeTestText(), "Beta smoke-test checklist copied", "Could not copy beta smoke-test checklist");
  }

  async _copyBetaFeedbackTemplate() {
    await this._copyText(this._betaFeedbackTemplateText(), "Beta feedback template copied", "Could not copy beta feedback template");
  }

  async _copyText(text, successMessage, failureMessage) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        this.shadowRoot.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      this._message = successMessage;
      this._error = "";
    } catch {
      this._error = failureMessage;
      this._message = "";
    }
    this._render();
  }

  _formatActivityTime(timestamp) {
    const date = new Date(timestamp);
    if (!Number.isFinite(date.getTime())) return "Unknown time";
    return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  _missionCards() {
    const saved = this._config?.display?.missionCards || {};
    const hasDosingParameters = this._dosingActiveParameters().length > 0;
    return {
      health: saved.health !== false,
      live: saved.live !== false,
      controls: saved.controls !== false,
      energy: saved.energy !== false,
      dosing: saved.dosing === true || (hasDosingParameters && saved.dosing !== false),
    };
  }

  _missionCardChoices() {
    return [
      ["health", "Reef Health", "Show an explainable 0-100 health score."],
      ["dosing", "Dosing Advisor", "Show consumption, projections, and advisory dose tips."],
      ["live", "Live Stats", "Show mapped sensor readings in Mission Control."],
      ["controls", "Controls", "Show armed equipment status in Mission Control."],
      ["energy", "Energy", "Show energy and cost summaries in Mission Control."],
    ];
  }

  _healthCategoryChoices() {
    return [
      ["life", "Life Support"],
      ["stability", "Stability"],
      ["chemistry", "Chemistry / Parameters"],
      ["equipment", "Equipment"],
      ["maintenance", "Maintenance / Modes"],
      ["confidence", "Confidence"],
    ];
  }

  _healthWeights(profile = this._tankProfile()) {
    const weights = {
      fish_only_fowlr: { life: 0.35, stability: 0.15, chemistry: 0.10, equipment: 0.25, maintenance: 0.08, confidence: 0.07 },
      soft_coral: { life: 0.32, stability: 0.18, chemistry: 0.14, equipment: 0.20, maintenance: 0.08, confidence: 0.08 },
      lps: { life: 0.30, stability: 0.20, chemistry: 0.18, equipment: 0.18, maintenance: 0.07, confidence: 0.07 },
      sps: { life: 0.25, stability: 0.28, chemistry: 0.25, equipment: 0.12, maintenance: 0.05, confidence: 0.05 },
      mixed_reef: { life: 0.28, stability: 0.22, chemistry: 0.20, equipment: 0.18, maintenance: 0.07, confidence: 0.05 },
      anemone_dominant: { life: 0.32, stability: 0.24, chemistry: 0.12, equipment: 0.20, maintenance: 0.06, confidence: 0.06 },
    };
    return weights[profile] || weights.mixed_reef;
  }

  _healthStatus(score, caps = []) {
    if (caps.some((cap) => cap.status === "critical") || score < 70) return "critical";
    if (caps.length || score < 90) return "warning";
    return "ok";
  }

  _healthGrade(score) {
    if (score >= 90) return "A";
    if (score >= 80) return "B";
    if (score >= 70) return "C";
    if (score >= 60) return "D";
    return "E";
  }

  _healthTrendFreshness() {
    const checkedAt = this._healthTrends?.checkedAt;
    if (!checkedAt) return "Not checked this session";
    const date = new Date(checkedAt);
    if (!Number.isFinite(date.getTime())) return "Not checked this session";
    return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  _healthSectionOpen(section) {
    const defaults = this._defaultHealthSections();
    return Boolean(this._healthSections?.[section] ?? defaults[section]);
  }

  _healthTrendMultiplier() {
    return {
      fish_only_fowlr: 1.25,
      soft_coral: 1.15,
      lps: 1,
      mixed_reef: 1,
      anemone_dominant: 0.9,
      sps: 0.75,
    }[this._tankProfile()] || 1;
  }

  _healthTrendRule(sensorId) {
    const multiplier = this._healthTrendMultiplier();
    const context = { kind: "context", category: "stability", affectsScore: false };
    const rules = {
      temp: { kind: "temperature", category: "stability", warningSwing: 1.5 * multiplier, criticalSwing: 2.5 * multiplier, warningDelta: 0.8 * multiplier, criticalDelta: 1.5 * multiplier, penaltyWarning: 5, penaltyCritical: 12 },
      sump_temp: { kind: "context", category: "stability", affectsScore: false },
      ph: { kind: "daily-envelope", category: "chemistry", warningAvg: 0.12 * multiplier, criticalAvg: 0.25 * multiplier, warningEnvelope: 0.18 * multiplier, criticalEnvelope: 0.35 * multiplier, penaltyWarning: 5, penaltyCritical: 10 },
      salinity: { kind: "daily-baseline", category: "chemistry", warningAvg: 0.7 * multiplier, criticalAvg: 1.5 * multiplier, penaltyWarning: 8, penaltyCritical: 18 },
      alkalinity: { kind: "daily-baseline", category: "chemistry", warningAvg: 0.35 * multiplier, criticalAvg: 0.7 * multiplier, penaltyWarning: 10, penaltyCritical: 20 },
      calcium: { kind: "daily-baseline", category: "chemistry", warningAvg: 30 * multiplier, criticalAvg: 60 * multiplier, penaltyWarning: 5, penaltyCritical: 10 },
      magnesium: { kind: "daily-baseline", category: "chemistry", warningAvg: 60 * multiplier, criticalAvg: 120 * multiplier, penaltyWarning: 5, penaltyCritical: 10 },
      nitrate: { kind: "slow-baseline", category: "chemistry", warningAvg: 5 * multiplier, criticalAvg: 10 * multiplier, warningRelative: 0.5 * multiplier, criticalRelative: 1 * multiplier, penaltyWarning: 4, penaltyCritical: 8 },
      phosphate: { kind: "slow-baseline", category: "chemistry", warningAvg: 0.05 * multiplier, criticalAvg: 0.1 * multiplier, warningRelative: 0.75 * multiplier, criticalRelative: 1.5 * multiplier, penaltyWarning: 4, penaltyCritical: 8 },
      dissolved_oxygen: { kind: "daily-baseline", category: "life", warningAvg: 1 * multiplier, criticalAvg: 2 * multiplier, penaltyWarning: 8, penaltyCritical: 16 },
      flow: { kind: "context", category: "stability", affectsScore: false },
      orp: { kind: "context", category: "chemistry", affectsScore: false },
      par: { kind: "context", category: "stability", affectsScore: false },
      room_temp: { kind: "context", category: "stability", affectsScore: false },
      co2: { kind: "context", category: "stability", affectsScore: false },
      humidity: { kind: "context", category: "stability", affectsScore: false },
    };
    return rules[sensorId] || context;
  }

  _trendDays(points) {
    const buckets = new Map();
    points.forEach((point) => {
      if (!Number.isFinite(point?.time) || !Number.isFinite(Number(point?.value))) return;
      const key = new Date(point.time).toISOString().slice(0, 10);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(Number(point.value));
    });
    return [...buckets.entries()]
      .map(([day, values]) => {
        const count = values.length;
        const sum = values.reduce((total, value) => total + value, 0);
        return {
          day,
          count,
          avg: sum / count,
          low: Math.min(...values),
          high: Math.max(...values),
        };
      })
      .filter((item) => item.count >= 1)
      .sort((a, b) => a.day.localeCompare(b.day));
  }

  _average(values) {
    const safe = values.filter(Number.isFinite);
    if (!safe.length) return 0;
    return safe.reduce((total, value) => total + value, 0) / safe.length;
  }

  _healthTrendLearning(sensorId, sensor, detail = "OpenReef needs more history before judging this trend.") {
    return {
      status: "learning",
      group: "learning",
      category: this._sensorHealthCategory(sensorId, sensor),
      penalty: 0,
      affectsScore: false,
      label: `${sensor.label || sensorId} trend learning`,
      detail,
    };
  }

  _healthTrendContext(sensorId, sensor, detail) {
    return {
      status: "context",
      group: "context",
      category: this._sensorHealthCategory(sensorId, sensor),
      penalty: 0,
      affectsScore: false,
      label: `${sensor.label || sensorId} context`,
      detail,
    };
  }

  _healthTrendResult(sensorId, sensor, rule, status, detail) {
    const penalty = status === "critical" ? rule.penaltyCritical : status === "warning" ? rule.penaltyWarning : 0;
    if (!penalty) return this._healthTrendContext(sensorId, sensor, detail);
    return {
      status,
      group: status === "critical" ? "action" : "watch",
      category: rule.category || this._sensorHealthCategory(sensorId, sensor),
      penalty,
      affectsScore: true,
      label: `${sensor.label || sensorId} trend needs attention`,
      detail,
    };
  }

  _analyseHealthTrend(sensorId, sensor, trendData) {
    const points = Array.isArray(trendData) ? trendData : trendData?.points || [];
    const range = Array.isArray(trendData) ? "24h" : trendData?.range || "24h";
    const rule = this._healthTrendRule(sensorId);
    if (!Array.isArray(points) || points.length < 4) {
      return this._healthTrendLearning(sensorId, sensor);
    }
    const values = points.map((point) => Number(point.value)).filter(Number.isFinite);
    if (values.length < 4) return this._healthTrendLearning(sensorId, sensor, "No numeric history is available yet.");

    const first = values[0];
    const latest = values[values.length - 1];
    const low = Math.min(...values);
    const high = Math.max(...values);
    const delta = Math.abs(latest - first);
    const swing = high - low;
    const unit = sensor.unit ? ` ${sensor.unit}` : "";
    const digits = this._sensorDigits(sensorId);
    const direction = latest >= first ? "up" : "down";

    if (rule.kind === "context") {
      return this._healthTrendContext(sensorId, sensor, `${this._trendRangeLabel(range)} ${direction} ${this._format(delta, digits)}${unit}; swing ${this._format(swing, digits)}${unit}. Context only: useful for troubleshooting wider patterns, not scored by itself.`);
    }

    if (rule.kind === "temperature") {
      let trendDelta = delta;
      let trendSwing = swing;
      let trendDirection = direction;
      let detailPrefix = this._trendRangeLabel(range);
      if (range === "7d") {
        const days = this._trendDays(points);
        if (days.length) {
          const latestDay = days[days.length - 1];
          const baselineAvg = days.length > 1 ? this._average(days.slice(0, -1).map((day) => day.avg)) : latestDay.avg;
          trendDelta = Math.abs(latestDay.avg - baselineAvg);
          trendSwing = latestDay.high - latestDay.low;
          trendDirection = latestDay.avg >= baselineAvg ? "up" : "down";
          detailPrefix = "Latest day";
        }
      }
      const status = trendSwing >= rule.criticalSwing || trendDelta >= rule.criticalDelta
        ? "critical"
        : trendSwing >= rule.warningSwing || trendDelta >= rule.warningDelta
          ? "warning"
          : "ok";
      return this._healthTrendResult(sensorId, sensor, rule, status, `${detailPrefix} ${trendDirection} ${this._format(trendDelta, digits)}${unit}; swing ${this._format(trendSwing, digits)}${unit}.`);
    }

    const days = this._trendDays(points);
    if ((rule.kind === "daily-envelope" || rule.kind === "daily-baseline" || rule.kind === "slow-baseline") && (range !== "7d" || days.length < 4)) {
      return this._healthTrendLearning(sensorId, sensor, "OpenReef needs several days of history before comparing this tank against its own normal pattern.");
    }

    const latestDay = days[days.length - 1];
    const baselineDays = days.slice(0, -1);
    const baselineAvg = this._average(baselineDays.map((day) => day.avg));
    const avgDrift = Math.abs(latestDay.avg - baselineAvg);

    if (rule.kind === "daily-envelope") {
      const lowDrift = Math.abs(latestDay.low - this._average(baselineDays.map((day) => day.low)));
      const highDrift = Math.abs(latestDay.high - this._average(baselineDays.map((day) => day.high)));
      const envelopeDrift = Math.max(lowDrift, highDrift);
      const status = avgDrift >= rule.criticalAvg || envelopeDrift >= rule.criticalEnvelope
        ? "critical"
        : avgDrift >= rule.warningAvg || envelopeDrift >= rule.warningEnvelope
          ? "warning"
          : "ok";
      return this._healthTrendResult(sensorId, sensor, rule, status, `Today avg ${this._format(latestDay.avg, digits)}${unit}; baseline ${this._format(baselineAvg, digits)}${unit}; envelope shift ${this._format(envelopeDrift, digits)}${unit}. Normal day/night swing is expected.`);
    }

    if (rule.kind === "slow-baseline") {
      const relativeDrift = avgDrift / Math.max(Math.abs(baselineAvg), 0.01);
      const status = avgDrift >= rule.criticalAvg || relativeDrift >= rule.criticalRelative
        ? "critical"
        : avgDrift >= rule.warningAvg || relativeDrift >= rule.warningRelative
          ? "warning"
          : "ok";
      return this._healthTrendResult(sensorId, sensor, rule, status, `Latest daily avg ${this._format(latestDay.avg, digits)}${unit}; baseline ${this._format(baselineAvg, digits)}${unit}; slow drift ${this._format(avgDrift, digits)}${unit}.`);
    }

    const status = avgDrift >= rule.criticalAvg
      ? "critical"
      : avgDrift >= rule.warningAvg
        ? "warning"
        : "ok";
    return this._healthTrendResult(sensorId, sensor, rule, status, `Latest daily avg ${this._format(latestDay.avg, digits)}${unit}; baseline ${this._format(baselineAvg, digits)}${unit}; drift ${this._format(avgDrift, digits)}${unit}.`);
  }

  // --- Dosing & Consumption Advisor (advisory only) -----------------------

  _dosingEnabled() {
    return this._config?.dosing?.enabled !== false;
  }

  _dosingSystemDefaults() {
    return {
      primaryProduct: "",
      secondaryProduct: "",
      secondaryDelivery: "",
      tankVolumeLitres: 0,
      kalkDailyDoseMl: 0,
      kalkConcentrationTspPerGallon: 0,
      kalkEvaporationLimitMlPerDay: 0,
      kalkMaxPh: 8.45,
      kalkMaxPhRise: 0.2,
      freshTestRequired: true,
      safetyAcknowledged: false,
      customProductName: "",
      customProductClass: "custom_verified_strength",
      customNotes: "",
    };
  }

  _dosingSystem() {
    const raw = this._config?.dosing?.system || {};
    const parameterVolumes = Object.values(this._config?.dosing?.parameters || {})
      .map((item) => Number(item?.tankVolumeLitres) || 0)
      .filter((value) => value > 0);
    return {
      ...this._dosingSystemDefaults(),
      ...raw,
      tankVolumeLitres: Number(raw.tankVolumeLitres) || Math.max(0, ...parameterVolumes),
      kalkDailyDoseMl: Math.max(0, Number(raw.kalkDailyDoseMl) || 0),
      kalkConcentrationTspPerGallon: Math.max(0, Number(raw.kalkConcentrationTspPerGallon) || 0),
      kalkEvaporationLimitMlPerDay: Math.max(0, Number(raw.kalkEvaporationLimitMlPerDay) || 0),
      kalkMaxPh: Math.max(0, Number(raw.kalkMaxPh) || 8.45),
      kalkMaxPhRise: Math.max(0, Number(raw.kalkMaxPhRise) || 0.2),
      freshTestRequired: raw.freshTestRequired !== false,
      safetyAcknowledged: raw.safetyAcknowledged === true,
    };
  }

  _dosingParameterIds() {
    const params = this._config?.dosing?.parameters;
    if (params && typeof params === "object") {
      const keys = Object.keys(params);
      if (keys.length) return keys;
    }
    return ["alkalinity", "calcium", "magnesium"];
  }

  _dosingParamConfig(sensorId) {
    return this._config?.dosing?.parameters?.[sensorId] || {};
  }

  _dosingProductLibrary() {
    return [
      {
        id: "",
        label: "Choose a dosing system",
        brand: "",
        classId: "unconfigured",
        roles: ["primary"],
        parameters: [],
        note: "Select the main system you use so OpenReef can apply the right safety model.",
      },
      {
        id: "custom_verified_strength",
        label: "Custom verified-strength product",
        brand: "Custom",
        classId: "custom_verified_strength",
        roles: ["primary", "secondary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        exactMaintenance: true,
        exactCorrection: true,
        note: "Use this only when you have verified the product strength yourself, such as 1 mL raises X in Y litres.",
      },
      {
        id: "tropic_marin_all_for_reef",
        label: "Tropic Marin All-For-Reef",
        brand: "Tropic Marin",
        classId: "single_solution_balanced",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Balanced all-in-one maintenance. OpenReef tracks consumption and direction, but does not use it as a one-off correction calculator.",
      },
      {
        id: "seachem_reef_fusion",
        label: "Seachem Reef Fusion 1/2",
        brand: "Seachem",
        classId: "equal_part_two_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium"],
        exactMaintenance: true,
        exactCorrection: true,
        exactParameters: {
          calcium: { productDoseMl: 1, productVolumeLitres: 25, productRaise: 4 },
          alkalinity: { productDoseMl: 1, productVolumeLitres: 25, productRaise: 0.493 },
        },
        note: "Exact-strength two-part preset. Dose parts separately and verify against the bottle before acting.",
      },
      {
        id: "aquaforest_component_123",
        label: "Aquaforest Component 1+2+3+",
        brand: "Aquaforest",
        classId: "equal_part_three_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Balanced three-part maintenance normally dosed in equal amounts and tuned from test trends.",
      },
      {
        id: "ati_essentials",
        label: "ATI Essentials / Essentials Pro",
        brand: "ATI",
        classId: "equal_part_two_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Balanced maintenance system. OpenReef shows consumption direction and conservative review guidance.",
      },
      {
        id: "red_sea_complete_reef_care_4",
        label: "Red Sea Complete Reef Care 4-part",
        brand: "Red Sea",
        classId: "calcium_led_multi_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Calcium-led multi-part method. OpenReef treats this as guided maintenance, not a simple correction calculator.",
      },
      {
        id: "triton_core7_flex",
        label: "TRITON Core7 Flex",
        brand: "TRITON",
        classId: "icp_guided_multi_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "ICP-guided multi-part method. OpenReef gives trend context and review prompts, not one-off correction maths.",
      },
      {
        id: "fauna_marin_balling_light",
        label: "Fauna Marin Balling Light",
        brand: "Fauna Marin",
        classId: "equal_part_three_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        requiresCustomStrength: true,
        note: "Recipe-dependent Balling method. Enter your verified recipe strength for exact mL advice.",
      },
      {
        id: "brs_pharma_two_part",
        label: "BRS Pharma 2-Part / DIY Recipe",
        brand: "Bulk Reef Supply",
        classId: "equal_part_two_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        requiresCustomStrength: true,
        note: "Recipe strength depends on how the solution was mixed. Use custom verified strength for exact mL advice.",
      },
      {
        id: "esv_b_ionic",
        label: "ESV B-Ionic",
        brand: "ESV",
        classId: "equal_part_two_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium"],
        requiresCustomStrength: true,
        note: "Two-part system with variant-specific strength. Use custom verified strength for exact mL advice.",
      },
      {
        id: "kalkwasser_calcium_hydroxide",
        label: "Kalkwasser / calcium hydroxide",
        brand: "Generic / BRS / Brightwell",
        classId: "kalkwasser",
        roles: ["secondary"],
        parameters: ["alkalinity", "calcium"],
        note: "High-pH balanced support method, usually limited by evaporation. OpenReef never treats kalkwasser as a correction bolus.",
      },
    ];
  }

  _dosingProduct(productId) {
    return this._dosingProductLibrary().find((product) => product.id === productId) || this._dosingProductLibrary()[0];
  }

  _dosingProductClassLabel(classId) {
    return {
      single_solution_balanced: "Single-solution balanced",
      equal_part_two_part: "Equal-part two-part",
      equal_part_three_part: "Equal-part three-part",
      calcium_led_multi_part: "Calcium-led multi-part",
      icp_guided_multi_part: "ICP-guided multi-part",
      kalkwasser: "Kalkwasser",
      custom_verified_strength: "Custom verified strength",
      unconfigured: "Not configured",
    }[classId] || classId || "Product";
  }

  _dosingProductSupportsParameter(product, sensorId) {
    return Array.isArray(product?.parameters) && product.parameters.includes(sensorId);
  }

  _dosingProductForParameter(sensorId) {
    const system = this._dosingSystem();
    const primary = this._dosingProduct(system.primaryProduct);
    const secondary = this._dosingProduct(system.secondaryProduct);
    if (primary.id && this._dosingProductSupportsParameter(primary, sensorId)) return primary;
    if (secondary.id && this._dosingProductSupportsParameter(secondary, sensorId)) return secondary;
    return primary.id ? primary : secondary.id ? secondary : this._dosingProduct("");
  }

  _kalkSafetyContext(system = this._dosingSystem()) {
    const ph = this._config?.sensors?.ph || {};
    const hasPhGuard = this._sensorEnabled(ph) && !!ph.entity_id;
    const phValue = hasPhGuard ? this._number(ph.entity_id) : null;
    const maxPh = Math.max(0, Number(system.kalkMaxPh) || 8.45);
    const maxPhRise = Math.max(0, Number(system.kalkMaxPhRise) || 0.2);
    const dailyDoseMl = Math.max(0, Number(system.kalkDailyDoseMl) || 0);
    const concentrationTspPerGallon = Math.max(0, Number(system.kalkConcentrationTspPerGallon) || 0);
    const evaporationLimitMlPerDay = Math.max(0, Number(system.kalkEvaporationLimitMlPerDay) || 0);
    const evaporationHeadroomMl = evaporationLimitMlPerDay > 0 ? Math.max(0, evaporationLimitMlPerDay - dailyDoseMl) : null;
    const capacityConfigured = dailyDoseMl > 0 && concentrationTspPerGallon > 0 && evaporationLimitMlPerDay > 0;
    const phStatus = !hasPhGuard
      ? "missing"
      : Number.isFinite(phValue)
        ? phValue >= maxPh
          ? "high"
          : phValue >= maxPh - 0.05
            ? "near"
            : "ok"
        : "unknown";
    return {
      hasPhGuard,
      phValue,
      phStatus,
      maxPh,
      maxPhRise,
      dailyDoseMl,
      concentrationTspPerGallon,
      evaporationLimitMlPerDay,
      evaporationHeadroomMl,
      capacityConfigured,
      canIncreaseByEvaporation: evaporationLimitMlPerDay <= 0 || dailyDoseMl < evaporationLimitMlPerDay,
      safeToConsiderIncrease: hasPhGuard && phStatus === "ok" && capacityConfigured && (evaporationLimitMlPerDay <= 0 || dailyDoseMl < evaporationLimitMlPerDay),
    };
  }

  _dosingProductPreset(sensorId) {
    return this._dosingProductForParameter(sensorId);
  }

  _applyDosingProductPreset(sensorId, presetId) {
    this._config.dosing = this._config.dosing || { enabled: true, parameters: {}, system: {} };
    this._config.dosing.system = this._config.dosing.system || {};
    const product = this._dosingProduct(presetId);
    if (product.classId === "kalkwasser") {
      this._config.dosing.system.secondaryProduct = product.id;
    } else {
      this._config.dosing.system.primaryProduct = product.id;
    }
    this._config.dosing.parameters = this._config.dosing.parameters || {};
    this._config.dosing.parameters[sensorId] = this._config.dosing.parameters[sensorId] || {};
    this._config.dosing.parameters[sensorId].productPreset = presetId;
  }

  _dosingProductOptions(role, selectedId) {
    return this._dosingProductLibrary()
      .filter((product) => product.id === "" || product.roles?.includes(role))
      .map((product) => {
        const label = product.id ? product.label : role === "secondary" ? "No secondary supplement" : product.label;
        return `<option value="${this._escape(product.id)}" ${product.id === selectedId ? "selected" : ""}>${this._escape(label)}</option>`;
      })
      .join("");
  }

  _dosingPresetNumber(config, preset, field) {
    const value = Number(config?.[field]) || 0;
    if (value > 0) return value;
    return Number(preset?.[field]) || 0;
  }

  _dosingActiveParameters() {
    return this._dosingParameterIds()
      .map((id) => {
        const sensor = this._config?.sensors?.[id] || {};
        const meta = this._manualTestMeta(id);
        return [id, { ...meta, ...sensor, label: sensor.label || meta.label, unit: sensor.unit ?? meta.unit }];
      })
      .filter(([id, sensor]) => (sensor && this._sensorEnabled(sensor) && sensor.entity_id) || this._manualReadings(id).length >= 2);
  }

  _consumptionFreshness() {
    const checkedAt = this._consumption?.checkedAt;
    if (!checkedAt) return "Not checked this session";
    const date = new Date(checkedAt);
    if (!Number.isFinite(date.getTime())) return "Not checked this session";
    return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  }

  // Least-squares fit of ys against xs. xs are real day offsets so the slope
  // is per calendar day even when some days were dropped for sparse readings.
  _linearFit(xs, ys) {
    const n = ys.length;
    if (n < 2) return { slope: 0, intercept: ys[0] || 0, residualStdev: 0 };
    let sumX = 0;
    let sumY = 0;
    let sumXY = 0;
    let sumXX = 0;
    for (let i = 0; i < n; i += 1) {
      sumX += xs[i];
      sumY += ys[i];
      sumXY += xs[i] * ys[i];
      sumXX += xs[i] * xs[i];
    }
    const denom = n * sumXX - sumX * sumX;
    const slope = denom === 0 ? 0 : (n * sumXY - sumX * sumY) / denom;
    const intercept = (sumY - slope * sumX) / n;
    let residSq = 0;
    for (let i = 0; i < n; i += 1) {
      const predicted = intercept + slope * xs[i];
      residSq += (ys[i] - predicted) ** 2;
    }
    return { slope, intercept, residualStdev: Math.sqrt(residSq / n) };
  }

  _formatDays(days) {
    if (!Number.isFinite(days)) return "--";
    if (days < 1) {
      const hours = Math.max(1, Math.round(days * 24));
      return `${hours} hour${hours === 1 ? "" : "s"}`;
    }
    const rounded = days >= 10 ? Math.round(days) : Math.round(days * 10) / 10;
    return `${this._format(rounded, days >= 10 ? 0 : 1)} day${rounded === 1 ? "" : "s"}`;
  }

  // Stability is borrowed from the Reef Health Score trend analysis so the two
  // surfaces can never disagree for the same parameter.
  _consumptionStability(healthItem) {
    const status = healthItem?.status;
    if (!healthItem || status === "learning") return { stars: "", label: "Learning baseline", status: "learning" };
    if (status === "critical") return { stars: "★★☆☆☆", label: "Drifting", status: "critical" };
    if (status === "warning") return { stars: "★★★☆☆", label: "Some drift", status: "warning" };
    return { stars: "★★★★★", label: "Steady", status: "ok" };
  }

  _consumptionLearning(sensorId, sensor, detail = "Collecting history before estimating consumption.", options = {}) {
    return {
      id: sensorId,
      label: sensor.label || sensorId,
      group: "learning",
      status: options.status || "learning",
      unit: sensor.unit || "",
      digits: this._sensorDigits(sensorId),
      current: this._number(sensor.entity_id),
      slopePerDay: null,
      confident: false,
      projectionDays: null,
      projectionEdge: null,
      projectionValue: null,
      extraMlPerDay: null,
      correctionMl: null,
      suggestedDoseMlPerDay: null,
      reviewDoseMlPerDay: null,
      maxDailyAdjustmentUnits: null,
      doseText: detail,
      trendText: detail,
      projectionText: "",
      confidenceText: detail,
      source: options.source || "unknown",
      potencyInfo: null,
      productInfo: this._dosingProductForParameter(sensorId),
      recommendationState: "learning",
      maintenanceText: detail,
      correctionText: "Locked until OpenReef has enough trustworthy trend and manual-test data.",
      doNotDoseText: "",
      safetyText: detail,
      productAssumption: this._dosingProductForParameter(sensorId).label,
      stability: { stars: "", label: "Learning baseline", status: "learning" },
    };
  }

  _manualDosingFreshness(sensorId) {
    const latest = this._manualLatestReading(sensorId);
    const meta = this._manualTestMeta(sensorId);
    const schedule = this._manualTestConfig(sensorId);
    const scheduleActive = this._manualTestsConfig().enabled && schedule.enabled;
    const cadenceDays = scheduleActive ? schedule.cadenceDays : this._manualSuggestedCadenceDays(sensorId);
    const criticalAfterDays = scheduleActive ? schedule.criticalAfterDays : Math.max(cadenceDays * 2, cadenceDays + 1);
    if (!latest) {
      return {
        fresh: false,
        status: "learning",
        detail: `Add a fresh ${meta.label} result before OpenReef gives manual-test dosing advice.`,
      };
    }
    const age = this._manualAgeDays(latest);
    if (age > criticalAfterDays) {
      return {
        fresh: false,
        status: "critical",
        detail: `${meta.label} was last logged ${this._format(age, 0)} days ago. Retest before using manual history for dose advice.`,
      };
    }
    if (age > cadenceDays) {
      return {
        fresh: false,
        status: "warning",
        detail: `${meta.label} is due for a fresh test. Retest before using manual history for dose advice.`,
      };
    }
    return {
      fresh: true,
      status: "ok",
      detail: `${meta.label} manual history is fresh enough for advisory trend checks.`,
    };
  }

  _dosingDailyAdjustmentLimit(sensorId, sensor) {
    if (sensorId === "alkalinity") return 0.3;
    if (sensorId === "calcium") return 20;
    if (sensorId === "magnesium") return 50;
    const min = Number(sensor?.min);
    const max = Number(sensor?.max);
    const range = Number.isFinite(min) && Number.isFinite(max) ? Math.abs(max - min) : 0;
    return range > 0 ? range * 0.1 : 1;
  }

  _formatDoseMl(value) {
    return `${this._format(Math.max(0, Number(value) || 0), 1)} mL/day`;
  }

  _dosingMinimumSignal(sensorId, sensor) {
    if (sensorId === "alkalinity") return 0.1;
    if (sensorId === "calcium") return 8;
    if (sensorId === "magnesium") return 20;
    const min = Number(sensor?.min);
    const max = Number(sensor?.max);
    const range = Number.isFinite(min) && Number.isFinite(max) ? Math.abs(max - min) : 0;
    return range > 0 ? Math.max(range * 0.02, 0.01) : 0.05;
  }

  _consumptionConfidence(sensorId, sensor, source, days, fit, span, totalChange) {
    const minDays = source === "manual" ? 4 : 4;
    if (days.length < minDays) {
      return {
        confident: false,
        detail: `OpenReef needs at least ${minDays} dated day${minDays === 1 ? "" : "s"} before estimating ${sensor.label || sensorId} consumption.`,
      };
    }
    const minSpan = source === "manual"
      ? Math.max(6, Math.min(21, this._manualSuggestedCadenceDays(sensorId) * 2))
      : 3;
    if (span < minSpan) {
      return {
        confident: false,
        detail: `OpenReef needs about ${this._format(minSpan, 0)} days of ${source === "manual" ? "manual results" : "chemistry history"} before advising dose changes.`,
      };
    }
    const minSignal = this._dosingMinimumSignal(sensorId, sensor);
    const unitSuffix = sensor.unit ? ` ${sensor.unit}` : "";
    const digits = this._sensorDigits(sensorId);
    if (totalChange < minSignal) {
      return {
        confident: false,
        reason: "low_signal",
        detail: `Net movement is smaller than the useful signal for this test (${this._format(minSignal, digits)}${unitSuffix}). No dosing change suggested yet.`,
      };
    }
    const residualLimit = source === "manual" ? 1.5 : 1.2;
    if (fit.residualStdev > 0 && totalChange < fit.residualStdev * residualLimit) {
      return {
        confident: false,
        detail: "The readings are too noisy to separate real consumption from testing/measurement noise yet.",
      };
    }
    return { confident: true, detail: "Consumption trend is strong enough for advisory dosing." };
  }

  _dosingCalculatedPotency(config, product = null, sensorId = "", system = this._dosingSystem()) {
    const exact = product?.exactParameters?.[sensorId] || null;
    const tankVolume = Number(system?.tankVolumeLitres) || Number(config?.tankVolumeLitres) || 0;
    const productDose = this._dosingPresetNumber(config, exact, "productDoseMl");
    const productVolume = this._dosingPresetNumber(config, exact, "productVolumeLitres");
    const productRaise = this._dosingPresetNumber(config, exact, "productRaise");
    if (tankVolume <= 0 || productDose <= 0 || productVolume <= 0 || productRaise <= 0) {
      return { value: 0, complete: false };
    }
    return {
      value: (productRaise * productVolume) / (productDose * tankVolume),
      complete: true,
    };
  }

  _dosingEffectivePotency(sensorId, sensor, config = this._dosingParamConfig(sensorId), product = this._dosingProductForParameter(sensorId), system = this._dosingSystem()) {
    const manual = Number(config?.potencyPerMl) || 0;
    const calculated = this._dosingCalculatedPotency(config, product, sensorId, system);
    if (manual > 0) {
      return {
        value: manual,
        source: "manual",
        exactMaintenance: true,
        exactCorrection: product?.classId !== "kalkwasser",
        label: `Manual override: ${this._format(manual, 4)} ${sensor.unit || "units"}/mL`,
      };
    }
    if (!product?.id) {
      return { value: 0, source: "unconfigured", exactMaintenance: false, exactCorrection: false, label: "Choose a dosing system in Settings" };
    }
    if (product.classId === "kalkwasser") {
      return {
        value: 0,
        source: "kalkwasser",
        exactMaintenance: false,
        exactCorrection: false,
        label: "Kalkwasser is pH and evaporation constrained; OpenReef gives maintenance guidance only",
      };
    }
    if (calculated.value > 0) {
      const source = product?.exactParameters?.[sensorId] ? "preset" : "calculator";
      return {
        value: calculated.value,
        source,
        exactMaintenance: product.exactMaintenance === true || product.classId === "custom_verified_strength",
        exactCorrection: product.exactCorrection === true || product.classId === "custom_verified_strength",
        label: `${product.label}: calculated ${this._format(calculated.value, 4)} ${sensor.unit || "units"}/mL in this tank`,
      };
    }
    if (product.requiresCustomStrength || product.classId === "custom_verified_strength") {
      return {
        value: 0,
        source: "custom-required",
        exactMaintenance: false,
        exactCorrection: false,
        label: `${product.label}: enter verified solution strength before exact mL advice appears`,
      };
    }
    return {
      value: 0,
      source: "maintenance",
      exactMaintenance: false,
      exactCorrection: false,
      label: `${product.label}: maintenance-style product; tune daily dose from tests and trend direction`,
    };
  }

  _dosingFreshManualGate(sensorId) {
    const freshness = this._manualDosingFreshness(sensorId);
    return {
      fresh: freshness.fresh,
      detail: freshness.detail,
      status: freshness.status,
    };
  }

  _dosingSafetyState(sensorId, sensor, product, potencyInfo, config, source) {
    const system = this._dosingSystem();
    const currentDose = Number(config?.doserMlPerDay) || 0;
    const tankVolume = Number(system.tankVolumeLitres) || 0;
    const locks = [];
    const warnings = [];
    let kalkContext = null;
    if (!product?.id) locks.push("Choose a primary dosing system or secondary supplement.");
    const productCoversParameter = !product?.id || this._dosingProductSupportsParameter(product, sensorId);
    if (product?.id && !productCoversParameter) {
      warnings.push(product.classId === "kalkwasser"
        ? `Kalkwasser does not maintain ${sensor.label || sensorId}; use a magnesium-specific product or water-change plan for magnesium drift.`
        : `${product.label} is not a ${sensor.label || sensorId} dosing product.`);
    }
    if (!system.safetyAcknowledged) locks.push("Acknowledge that OpenReef is advisory only and never doses for you.");
    if (potencyInfo.value <= 0 && ["preset", "calculator", "manual"].includes(potencyInfo.source)) locks.push("Complete product strength details.");
    if ((potencyInfo.exactMaintenance || potencyInfo.exactCorrection) && tankVolume <= 0) locks.push("Enter real net tank water volume.");
    if (potencyInfo.exactMaintenance && currentDose <= 0) locks.push("Enter the current daily dose before exact maintenance changes appear.");
    const manual = this._dosingFreshManualGate(sensorId);
    if (potencyInfo.exactCorrection && !manual.fresh) warnings.push(`Correction advice locked: ${manual.detail}`);
    if (product?.classId === "kalkwasser") {
      kalkContext = this._kalkSafetyContext(system);
      warnings.push("Kalkwasser is high-pH and evaporation-limited. Do not use it as a one-off correction bolus.");
      if (!kalkContext.hasPhGuard) {
        warnings.push("No mapped pH guard is available for kalkwasser context.");
      } else if (!Number.isFinite(kalkContext.phValue)) {
        warnings.push("Mapped pH guard is unavailable or non-numeric right now.");
      } else if (kalkContext.phStatus === "high") {
        locks.push(`Current pH ${this._format(kalkContext.phValue, 2)} is at or above the kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser.`);
      } else if (kalkContext.phStatus === "near") {
        warnings.push(`Current pH ${this._format(kalkContext.phValue, 2)} is close to the kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser without reviewing the pH pattern.`);
      }
      if (!system.secondaryDelivery) warnings.push("Choose how kalkwasser is delivered: ATO, dosing pump, or manual top-off.");
      if (!kalkContext.capacityConfigured) {
        warnings.push("Kalk capacity is not fully configured. Add daily kalk volume, concentration, and evaporation ceiling before judging whether kalk can keep up.");
      }
      if (kalkContext.evaporationLimitMlPerDay > 0 && kalkContext.dailyDoseMl > kalkContext.evaporationLimitMlPerDay) {
        locks.push(`Daily kalk volume ${this._format(kalkContext.dailyDoseMl, 0)} mL/day exceeds the evaporation ceiling ${this._format(kalkContext.evaporationLimitMlPerDay, 0)} mL/day.`);
      } else if (kalkContext.evaporationLimitMlPerDay > 0 && kalkContext.dailyDoseMl >= kalkContext.evaporationLimitMlPerDay * 0.9) {
        warnings.push(`Daily kalk volume is close to the evaporation limit; remaining headroom is about ${this._format(kalkContext.evaporationHeadroomMl, 0)} mL/day.`);
      }
    }
    if (source === "manual" && !manual.fresh) locks.push(manual.detail);
    const actionWarnings = warnings.filter((warning) => {
      if (warning.startsWith("Kalkwasser is high-pH and evaporation-limited")) return false;
      if (warning.startsWith("Kalkwasser does not maintain")) return false;
      if (warning.includes(" is not a ") && warning.includes(" dosing product")) return false;
      return true;
    });
    const status = locks.length ? "locked" : actionWarnings.length ? "warning" : "ready";
    return {
      status,
      locks,
      warnings,
      actionWarnings,
      manual,
      currentDose,
      tankVolume,
      kalkContext,
      canExactMaintenance: !locks.length && potencyInfo.exactMaintenance && potencyInfo.value > 0 && currentDose > 0,
      canExactCorrection: !locks.length && !warnings.some((warning) => warning.startsWith("Correction advice locked")) && potencyInfo.exactCorrection && potencyInfo.value > 0 && manual.fresh,
    };
  }

  _kalkMaintenanceText(label, sensorId, slope, rateText, safety) {
    const context = safety.kalkContext || this._kalkSafetyContext();
    if (!this._dosingProductSupportsParameter(this._dosingProduct("kalkwasser_calcium_hydroxide"), sensorId)) {
      return `Kalkwasser does not maintain ${label}. Track magnesium separately and use a magnesium-specific product or water-change plan if it keeps drifting.`;
    }
    const maxPhText = this._format(context.maxPh, 2);
    if (!safety.manual.fresh) {
      return `${label} manual tests are not fresh enough for kalkwasser advice. Retest before changing any kalk routine.`;
    }
    if (safety.locks.length) {
      return `Kalkwasser action is locked: ${safety.locks.join(" ")}`;
    }
    if (!context.capacityConfigured) {
      return `Net ${slope < 0 ? "loss" : "rise"} ~${rateText}. Kalk capacity is not configured yet. Add daily kalk volume, concentration, and evaporation ceiling before OpenReef judges whether kalk can keep up.`;
    }
    if (!context.hasPhGuard) {
      return `Net ${slope < 0 ? "loss" : "rise"} ~${rateText}. No mapped pH guard is available, so OpenReef will not suggest increasing kalkwasser.`;
    }
    if (context.phStatus === "high" || context.phStatus === "near") {
      return `Net ${slope < 0 ? "loss" : "rise"} ~${rateText}. Do not increase kalkwasser while pH is ${context.phStatus === "high" ? "high" : "near the safety ceiling"} (${Number.isFinite(context.phValue) ? this._format(context.phValue, 2) : "--"} / max ${maxPhText}).`;
    }
    if (slope < 0) {
      const headroom = Number.isFinite(context.evaporationHeadroomMl) ? `${this._format(context.evaporationHeadroomMl, 0)} mL/day evaporation headroom` : "unknown evaporation headroom";
      if (!context.canIncreaseByEvaporation) {
        return `Net loss ~${rateText}. Kalk may not keep up because the configured daily kalk volume is already at the evaporation limit. Add a primary dosing system or reduce demand rather than pushing kalk harder.`;
      }
      return `Net loss ~${rateText}. Kalk may not keep up if this trend continues. Review a small maintenance increase only within ${headroom}, max pH ${maxPhText}, and max pH rise ${this._format(context.maxPhRise, 2)}; otherwise add a primary dosing system.`;
    }
    if (slope > 0) {
      return `Net rise ~${rateText}. Do not increase kalkwasser. Review whether the current kalk dose is too strong before making further changes.`;
    }
    return `Kalkwasser appears steady. Keep monitoring pH and evaporation before changing the routine.`;
  }

  _analyseConsumption(sensorId, sensor, trendData, healthItem) {
    const label = sensor.label || sensorId;
    const unit = sensor.unit || "";
    const unitSuffix = unit ? ` ${unit}` : "";
    const digits = this._sensorDigits(sensorId);
    let points = Array.isArray(trendData) ? trendData : Array.isArray(trendData?.points) ? trendData.points : [];
    const range = Array.isArray(trendData) ? "24h" : trendData?.range || "24h";
    const source = Array.isArray(trendData) ? "history" : trendData?.source || "history";

    if (source === "manual") {
      const manualFreshness = this._manualDosingFreshness(sensorId);
      if (!manualFreshness.fresh) {
        return this._consumptionLearning(sensorId, sensor, manualFreshness.detail, {
          status: manualFreshness.status,
          source: "manual",
        });
      }
      const schedule = this._manualTestConfig(sensorId);
      const lookbackDays = Math.max(45, Math.min(180, schedule.criticalAfterDays * 3));
      const cutoff = Date.now() - lookbackDays * 86400000;
      points = points.filter((point) => point.time >= cutoff);
    }

    const days = this._trendDays(points);

    if ((source !== "manual" && range !== "7d") || days.length < 4) {
      return this._consumptionLearning(
        sensorId,
        sensor,
        source === "manual"
          ? "Collecting manual test history — OpenReef needs about 4 dated results before it can estimate consumption."
          : "Collecting mapped chemistry history — OpenReef needs about 4 days of readings before it can estimate consumption.",
        { source },
      );
    }

    // Net trend: least-squares slope of daily averages (units/day). Daily
    // averaging collapses the dose-event sawtooth into a stable baseline.
    const firstDay = Date.parse(`${days[0].day}T00:00:00Z`);
    const xs = days.map((day) => (Date.parse(`${day.day}T00:00:00Z`) - firstDay) / 86400000);
    const ys = days.map((day) => day.avg);
    const fit = this._linearFit(xs, ys);
    const slope = fit.slope;
    const span = xs[xs.length - 1] - xs[0] || 1;
    const totalChange = Math.abs(slope) * span;
    const confidence = this._consumptionConfidence(sensorId, sensor, source, days, fit, span, totalChange);
    const confident = confidence.confident;
    const noUsefulMovement = confidence.reason === "low_signal";

    const latestAvg = days[days.length - 1].avg;
    const liveValue = this._number(sensor.entity_id);
    const value = Number.isFinite(liveValue) ? liveValue : latestAvg;
    const stability = this._consumptionStability(healthItem);

    const min = Number(sensor.min);
    const max = Number(sensor.max);
    let projectionDays = null;
    let projectionEdge = null;
    let projectionValue = null;
    if (confident && slope < 0 && Number.isFinite(min) && value > min) {
      projectionDays = (value - min) / Math.abs(slope);
      projectionEdge = "low";
      projectionValue = min;
    } else if (confident && slope > 0 && Number.isFinite(max) && value < max) {
      projectionDays = (max - value) / slope;
      projectionEdge = "high";
      projectionValue = max;
    }
    if (projectionDays !== null && (!Number.isFinite(projectionDays) || projectionDays > 60)) {
      projectionDays = null;
      projectionEdge = null;
      projectionValue = null;
    }

    const paramConfig = this._dosingParamConfig(sensorId);
    const currentDoseMlPerDay = Math.max(0, Number(paramConfig.doserMlPerDay) || 0);
    const productInfo = this._dosingProductForParameter(sensorId);
    const potencyInfo = this._dosingEffectivePotency(sensorId, sensor, paramConfig, productInfo);
    const safety = this._dosingSafetyState(sensorId, sensor, productInfo, potencyInfo, paramConfig, source);
    const potency = potencyInfo.value;
    const target = Number(paramConfig.target) || 0;
    const holdOffsetUnits = -slope; // +ve => add this many units/day to hold steady
    const maxDailyAdjustmentUnits = this._dosingDailyAdjustmentLimit(sensorId, sensor);
    let extraMlPerDay = null;
    let correctionMl = null;
    let suggestedDoseMlPerDay = null;
    let reviewDoseMlPerDay = null;
    let correctionText = "";
    const productSupportsParameter = !productInfo.id || this._dosingProductSupportsParameter(productInfo, sensorId);
    const unsupportedProduct = productInfo.id && !productSupportsParameter;
    if (potency > 0 && safety.canExactMaintenance) {
      const cappedHoldOffsetUnits = Math.max(-maxDailyAdjustmentUnits, Math.min(holdOffsetUnits, maxDailyAdjustmentUnits));
      extraMlPerDay = cappedHoldOffsetUnits / potency;
      suggestedDoseMlPerDay = Math.max(0, currentDoseMlPerDay + holdOffsetUnits / potency);
      reviewDoseMlPerDay = Math.max(0, currentDoseMlPerDay + extraMlPerDay);
      if (target > 0 && safety.canExactCorrection) {
        const correctionUnits = target - value;
        correctionMl = correctionUnits / potency;
        if (correctionUnits > 0) {
          const correctionDays = Math.max(1, Math.ceil(correctionUnits / maxDailyAdjustmentUnits));
          const dailyCorrectionUnits = correctionUnits / correctionDays;
          const dailyCorrectionMl = Math.max(0, dailyCorrectionUnits / potency);
          correctionText = ` If correcting toward ${this._format(target, digits)}${unitSuffix}, split it across about ${correctionDays} day${correctionDays === 1 ? "" : "s"} (roughly ${this._format(dailyCorrectionMl, 1)} mL/day), then retest.`;
        } else if (correctionUnits < 0) {
          correctionText = " Target is below the current reading; do not use a one-off chemical correction downward. Let normal consumption or water changes bring it down gradually.";
        }
      }
    }

    const rateDigits = Math.max(digits, 2);
    const rateText = `${this._format(Math.abs(slope), rateDigits)}${unitSuffix}/day`;
    let maintenanceText;
    if (unsupportedProduct) {
      maintenanceText = `${productInfo.label} does not maintain ${label}. Track ${label} separately and choose a ${label.toLowerCase()} supplement, water-change plan, or primary dosing system if this keeps drifting.`;
    } else if (noUsefulMovement) {
      maintenanceText = "Movement is below OpenReef's useful signal for this test. No dosing change suggested.";
    } else if (!confident) {
      maintenanceText = `${confidence.detail} No dosing change suggested yet.`;
    } else if (!productInfo.id) {
      maintenanceText = "Choose your dosing system in Settings before OpenReef gives product-specific advice.";
    } else if (productInfo.classId === "kalkwasser") {
      maintenanceText = this._kalkMaintenanceText(label, sensorId, slope, rateText, safety);
    } else if (slope < 0) {
      if (potency > 0 && safety.canExactMaintenance) {
        const capped = Math.abs(holdOffsetUnits) > maxDailyAdjustmentUnits;
        maintenanceText = `Net loss ~${rateText}. Current dose ${this._formatDoseMl(currentDoseMlPerDay)}; estimated holding dose ${this._formatDoseMl(suggestedDoseMlPerDay)}. `;
        maintenanceText += capped
          ? `Use ${this._formatDoseMl(reviewDoseMlPerDay)} as the first review step because OpenReef limits advice to ${this._format(maxDailyAdjustmentUnits, rateDigits)}${unitSuffix}/day.`
          : `Suggested next dose ${this._formatDoseMl(reviewDoseMlPerDay)}.`;
      } else if (potency > 0 && !safety.canExactMaintenance) {
        maintenanceText = `Net loss ~${rateText}. Exact mL maintenance advice is locked: ${safety.locks.concat(currentDoseMlPerDay <= 0 ? ["enter the current daily dose"] : []).join(" ")}`;
      } else {
        maintenanceText = `Net loss ~${rateText}. ${productInfo.note || "Increase daily dosing only after confirming with a manual test."}`;
      }
    } else if (potency > 0 && safety.canExactMaintenance) {
      maintenanceText = `Net rise ~${rateText}. Current dose ${this._formatDoseMl(currentDoseMlPerDay)}; estimated holding dose ${this._formatDoseMl(suggestedDoseMlPerDay)}. `;
      maintenanceText += reviewDoseMlPerDay <= 0
        ? "Suggested next dose is 0 mL/day; avoid further dosing and investigate the source before making more changes."
        : `Suggested next dose ${this._formatDoseMl(reviewDoseMlPerDay)}. Retest before further reductions.`;
    } else {
      maintenanceText = `Net rise ~${rateText}. Consider reducing daily dosing after confirming with a manual test. Do not add chemical correction for a parameter that is already rising.`;
    }

    if (!correctionText) {
      if (unsupportedProduct) {
        correctionText = `No ${label} correction advice: ${productInfo.label} is not a ${label} dosing product.`;
      } else if (noUsefulMovement) {
        correctionText = "No correction advice because recent movement is below the useful signal.";
      } else if (!confident) {
        correctionText = "Correction dosing is locked until the trend is trustworthy.";
      } else if (!target) {
        correctionText = "Set a target in Settings before OpenReef discusses correction dosing.";
      } else if (productInfo.classId === "kalkwasser") {
        correctionText = "Do not use kalkwasser as a one-off correction bolus.";
      } else if (target < value) {
        correctionText = "Do not chemically correct downward. Let normal consumption or water changes bring the value down gradually.";
      } else if (!safety.canExactCorrection) {
        correctionText = `Correction dosing is locked: ${safety.locks.concat(safety.warnings).join(" ") || "fresh manual test required."}`;
      } else if (correctionMl !== null) {
        correctionText = `Advisory correction total is about ${this._format(Math.max(0, correctionMl), 1)} mL, split across safe daily steps and verified with fresh tests.`;
      }
    }

    const safetyText = safety.locks.length
      ? `Locked: ${safety.locks.join(" ")}`
      : safety.warnings.length
        ? safety.warnings.join(" ")
        : "Ready for advisory guidance only. OpenReef will not control a doser.";
    const doNotDoseText = unsupportedProduct
      ? `Do not use ${productInfo.label} to adjust ${label}.`
      : target > 0 && value > target
      ? "Do not add a chemical correction while the current reading is above target."
      : productInfo.classId === "kalkwasser"
        ? "Do not use kalkwasser for one-off correction doses."
        : "";
    const doseText = [maintenanceText, correctionText, doNotDoseText].filter(Boolean).join(" ");

    let status = "ok";
    if (projectionDays !== null) {
      if (projectionDays <= 3) status = "critical";
      else if (projectionDays <= 10) status = "warning";
    }
    if (safety.status === "locked" && status === "ok") status = "learning";
    if (safety.status === "warning" && status === "ok") status = "warning";
    if (unsupportedProduct && status === "learning") status = "ok";

    const sourceText = source === "manual" ? "from manual test history" : "net of your current dosing";
    const trendText = confident
      ? `${slope < 0 ? "Falling" : "Rising"} ~${rateText}, ${sourceText}.`
      : confidence.detail;
    const projectionText = projectionDays !== null
      ? `At this rate ${label} reaches your ${projectionEdge === "low" ? "low" : "high"} limit of ${this._format(projectionValue, digits)}${unitSuffix} in about ${this._formatDays(projectionDays)}.`
      : confident ? "No threshold crossing projected within 60 days." : "";

    return {
      id: sensorId,
      label,
      group: "advice",
      status,
      unit,
      digits,
      current: value,
      slopePerDay: slope,
      confident,
      projectionDays,
      projectionEdge,
      projectionValue,
      extraMlPerDay,
      correctionMl,
      suggestedDoseMlPerDay,
      reviewDoseMlPerDay,
      maxDailyAdjustmentUnits,
      doseText,
      maintenanceText,
      correctionText,
      doNotDoseText,
      safetyText,
      trendText,
      projectionText,
      confidenceText: confidence.detail,
      source,
      potencyInfo,
      productInfo,
      recommendationState: unsupportedProduct
        ? "not-covered"
        : safety.status === "locked"
          ? "locked"
          : safety.status === "warning"
            ? "warning"
            : noUsefulMovement
              ? "steady"
              : !confident
                ? "learning"
                : potency > 0
                  ? "ready"
                  : "guidance",
      productAssumption: `${productInfo.label} (${this._dosingProductClassLabel(productInfo.classId)})`,
      safety,
      stability,
    };
  }

  _consumptionItem(id, sensor) {
    return this._consumption?.items?.[id] || this._consumptionLearning(id, sensor);
  }

  _dosingMissionState() {
    const active = this._dosingActiveParameters();
    if (!active.length) {
      return { value: "Not set", detail: "Map alkalinity, calcium, or magnesium to enable", status: "unknown" };
    }
    const system = this._dosingSystem();
    const selectedProduct = system.primaryProduct || system.secondaryProduct;
    if (!selectedProduct) {
      return { value: "Setup needed", detail: "Choose a dosing system before product-specific advice appears", status: "warning" };
    }
    if (!system.safetyAcknowledged) {
      return { value: "Locked", detail: "Acknowledge advisory-only dosing safety in Settings", status: "warning" };
    }
    const items = active.map(([id, sensor]) => this._consumptionItem(id, sensor));
    if (!this._consumption?.checkedAt) {
      return { value: `${active.length} ready`, detail: "Press Refresh checks to estimate consumption", status: "unknown" };
    }
    const critical = items.filter((item) => item.status === "critical");
    const warning = items.filter((item) => item.status === "warning");
    const learning = items.filter((item) => item.status === "learning");
    const projected = items
      .filter((item) => Number.isFinite(item.projectionDays))
      .sort((a, b) => a.projectionDays - b.projectionDays)[0];
    if (critical.length || warning.length) {
      const lead = projected || critical[0] || warning[0];
      return {
        value: projected ? this._formatDays(projected.projectionDays) : `${critical.length + warning.length} to watch`,
        detail: projected ? `${lead.label} nears its limit` : (lead.trendText || `${lead.label} needs attention`),
        status: critical.length ? "critical" : "warning",
      };
    }
    if (learning.length === items.length) {
      return { value: "Learning", detail: "Building consumption baseline from chemistry history", status: "unknown" };
    }
    const ready = items.filter((item) => item.recommendationState === "ready").length;
    return { value: ready ? "Ready" : "Guided", detail: `${items.length} parameter${items.length === 1 ? "" : "s"} tracked safely`, status: "ok" };
  }

  _dosingParameterCard(item) {
    const unitSuffix = item.unit ? ` ${item.unit}` : "";
    const statusClass = item.status === "critical"
      ? "critical"
      : item.status === "warning"
        ? "warning"
        : item.status === "learning"
          ? "unknown"
          : "ok";
    const currentText = Number.isFinite(item.current) ? `${this._format(item.current, item.digits)}${unitSuffix}` : "--";
    const stabilityText = `${item.stability.stars ? `${item.stability.stars} ` : ""}${item.stability.label}`;
    const product = item.productInfo || this._dosingProductPreset(item.id);
    const stateLabel = {
      ready: "Ready",
      guidance: "Guided",
      warning: "Review",
      locked: "Locked",
      learning: "Learning",
    }[item.recommendationState] || "Advisor";
    return `
      <article class="dosing-card ${statusClass}">
        <div class="dosing-card-head">
          <span>${this._escape(item.label)}</span>
          <strong>${this._escape(currentText)}</strong>
        </div>
        <div class="pill ${item.recommendationState === "ready" ? "ok" : item.recommendationState === "locked" ? "warning" : "unknown"}">${this._escape(stateLabel)}</div>
        <ul class="dosing-card-lines">
          <li><span>Product assumption</span><small>${this._escape(item.productAssumption || product.label)}</small></li>
          <li><span>Trend</span><small>${this._escape(item.trendText)}</small></li>
          ${item.projectionText ? `<li><span>Projection</span><small>${this._escape(item.projectionText)}</small></li>` : ""}
          <li><span>Maintenance</span><small>${this._escape(item.maintenanceText || item.doseText)}</small></li>
          <li><span>Correction</span><small>${this._escape(item.correctionText || "Correction advice is locked until safety gates pass.")}</small></li>
          ${item.doNotDoseText ? `<li><span>Do not dose</span><small>${this._escape(item.doNotDoseText)}</small></li>` : ""}
          <li><span>Safety gate</span><small>${this._escape(item.safetyText || "Advisory only.")}</small></li>
          <li><span>Solution strength</span><small>${this._escape(item.potencyInfo?.label || "No solution strength set")}</small></li>
          <li><span>Stability</span><small>${this._escape(stabilityText)}</small></li>
        </ul>
      </article>
    `;
  }

  _dosingBreakdown() {
    if (!this._dosingEnabled()) return "";
    const active = this._dosingActiveParameters();
    if (!active.length) {
      return `
        <article class="panel">
          <div class="section-head">
            <div>
              <p class="eyebrow">Dosing &amp; Consumption Advisor</p>
              <h3>Advisory dosing insight</h3>
            </div>
          </div>
          ${this._emptyState("No dosing parameters mapped", "Map alkalinity, calcium, or magnesium (for example your Trident) in Settings. OpenReef can then estimate consumption and advise dose changes — something Apex Fusion does not do.", "settings", "Map chemistry")}
        </article>
      `;
    }
    const cards = active.map(([id, sensor]) => this._dosingParameterCard(this._consumptionItem(id, sensor))).join("");
    const methodOpen = this._healthSectionOpen("dosing-advice");
    const system = this._dosingSystem();
    const primary = this._dosingProduct(system.primaryProduct);
    const secondary = this._dosingProduct(system.secondaryProduct);
    const delivery = {
      ato: "ATO",
      dosing_pump: "dosing pump",
      manual_top_off: "manual top-off",
    }[system.secondaryDelivery] || "not set";
    const primaryTitle = primary.id
      ? primary.label
      : secondary.classId === "kalkwasser"
        ? "Kalkwasser support only"
        : "Not selected";
    const primaryDetail = primary.id
      ? this._dosingProductClassLabel(primary.classId)
      : secondary.classId === "kalkwasser"
        ? "No primary two-part/AFR selected"
        : "Choose in Settings";
    return `
      <article class="panel" data-tour="dosing">
        <div class="section-head">
          <div>
            <p class="eyebrow">Dosing &amp; Consumption Advisor</p>
            <h3>Consumption, projections &amp; advisory dosing</h3>
            <p class="muted">Estimated from mapped chemistry history or manual tests. Trend data: ${this._escape(this._consumptionFreshness())}.</p>
          </div>
          <div class="pill-stack">
            <button class="secondary compact-button" data-action="validate">Refresh advisor</button>
            <button class="secondary compact-button" data-action="toggle-health-section" data-section="dosing-advice">${methodOpen ? "Hide how this works" : "How this works"}</button>
          </div>
        </div>
        <div class="notice warning-notice"><strong>Advisory only.</strong> OpenReef never doses for you. Verify every figure against your own test kit before changing your doser.</div>
        <div class="health-reason-grid">
          <div class="health-reason-card">
            <span>Primary system</span>
            <strong>${this._escape(primaryTitle)}</strong>
            <p>${this._escape(primaryDetail)}</p>
          </div>
          <div class="health-reason-card">
            <span>Secondary supplement</span>
            <strong>${this._escape(secondary.id ? secondary.label : "None")}</strong>
            <p>${this._escape(secondary.id ? `Delivery: ${delivery}` : "Optional")}</p>
          </div>
          <div class="health-reason-card">
            <span>Safety state</span>
            <strong>${this._escape(system.safetyAcknowledged ? "Acknowledged" : "Locked")}</strong>
            <p>${this._escape(system.tankVolumeLitres ? `${this._format(system.tankVolumeLitres, 0)} L net volume` : "Enter real net tank volume")}</p>
          </div>
        </div>
        <div class="dosing-grid">${cards}</div>
        ${methodOpen ? `
          <div class="notice">
            <strong>How this works.</strong> OpenReef starts with your dosing system, then applies product-class safety rules. Maintenance advice estimates net daily movement after your current dose. Correction advice stays locked unless the product supports exact strength, tank volume is set, and a fresh manual test confirms the reading. Kalkwasser is always treated as high-pH maintenance support, never a one-off correction bolus.
          </div>
        ` : ""}
      </article>
    `;
  }

  _sensorHealthCategory(sensorId, sensor) {
    if (["temp", "dissolved_oxygen", "leak", "high_water", "low_water"].includes(sensorId)) return "life";
    if (sensor?.group === "chemistry") return "chemistry";
    if (["flow", "lighting", "room", "sump", "water"].includes(sensor?.group)) return "stability";
    return "confidence";
  }

  _sensorAlertImpact(sensorId, sensor, status) {
    if (status === "unknown") {
      return { category: "confidence", points: 8, group: "watch", affectsScore: true };
    }
    if (["room_temp", "co2", "humidity", "orp", "par", "sump_temp"].includes(sensorId)) {
      return { category: this._sensorHealthCategory(sensorId, sensor), points: 0, group: "context", affectsScore: false };
    }
    if (sensorId === "flow") {
      return { category: "stability", points: status === "critical" ? 10 : 4, group: status === "critical" ? "action" : "watch", affectsScore: true };
    }
    if (["leak", "high_water", "low_water", "temp", "dissolved_oxygen"].includes(sensorId)) {
      return { category: "life", points: status === "critical" ? 22 : 9, group: status === "critical" ? "action" : "watch", affectsScore: true };
    }
    if (sensor?.group === "chemistry") {
      return { category: "chemistry", points: status === "critical" ? 18 : 6, group: status === "critical" ? "action" : "watch", affectsScore: true };
    }
    return { category: this._sensorHealthCategory(sensorId, sensor), points: status === "critical" ? 12 : 4, group: status === "critical" ? "action" : "watch", affectsScore: true };
  }

  _reefHealthScore(sensors = this._enabledSensors(), equipment = Object.entries(this._config.equipment || {}), sensorAlerts = this._sensorAlerts(sensors), interlocks = this._interlockWarnings()) {
    const profile = this._tankProfile();
    const weights = this._healthWeights(profile);
    const losses = [];
    const caps = [];
    const groups = { action: [], watch: [], context: [], learning: [] };
    const categoryLoss = Object.fromEntries(this._healthCategoryChoices().map(([id]) => [id, 0]));
    const addInsight = (group, item) => {
      const safeGroup = groups[group] ? group : "context";
      groups[safeGroup].push({
        status: item.status || (safeGroup === "action" ? "critical" : safeGroup === "watch" ? "warning" : "context"),
        category: item.category || "confidence",
        points: Math.max(0, Number(item.points) || 0),
        affectsScore: item.affectsScore === true,
        label: item.label || "OpenReef insight",
        detail: item.detail || "",
        cap: item.cap || null,
      });
    };
    const addLoss = (category, points, label, detail = "", status = "warning") => {
      const safeCategory = categoryLoss[category] === undefined ? "confidence" : category;
      const safePoints = Math.max(0, Number(points) || 0);
      if (!safePoints) return;
      categoryLoss[safeCategory] += safePoints;
      losses.push({ category: safeCategory, points: safePoints, label, detail, status });
      addInsight(status === "critical" ? "action" : "watch", {
        category: safeCategory,
        points: safePoints,
        affectsScore: true,
        label,
        detail,
        status,
      });
    };
    const addCap = (limit, label, detail, status = "critical") => {
      const cap = { limit: Math.max(0, Math.min(Number(limit) || 100, 100)), label, detail, status };
      caps.push(cap);
      addInsight(status === "critical" ? "action" : "watch", {
        category: "life",
        affectsScore: true,
        label,
        detail,
        status,
        cap: cap.limit,
      });
    };

    const activeMode = this._activeMode();
    const running = activeMode === "running";
    const mappedSensors = sensors.filter(([, sensor]) => sensor.entity_id).length;
    const unmappedSensors = sensors.filter(([, sensor]) => !sensor.entity_id);
    const noSensors = sensors.length === 0;
    const missing = Number(this._validation?.missing_entities?.length || 0);
    const armedUnavailable = Number(this._validation?.armed_unavailable?.length || 0);
    const armedEquipment = equipment.filter(([, item]) => item.armed).length;
    const critical = sensorAlerts.filter((alert) => alert.status === "critical");
    const warnings = sensorAlerts.filter((alert) => alert.status === "warning");
    const unknowns = sensorAlerts.filter((alert) => alert.status === "unknown");

    if (noSensors) addLoss("confidence", 30, "No enabled sensors", "Enable the sensors you actually own.");
    unmappedSensors.forEach(([, sensor]) => {
      addLoss("confidence", 12, `${sensor.label || "Sensor"} is enabled but unmapped`, "Disabled sensors are ignored; enabled sensors should be mapped.");
    });
    if (missing) addLoss("confidence", missing * 8, `${missing} mapped entity missing`, "Update mappings or remove stale entities.", "critical");
    if (armedUnavailable) addLoss("equipment", armedUnavailable * 18, `${armedUnavailable} armed device unavailable`, "Disarm or remap unavailable equipment before relying on controls.", "critical");

    sensorAlerts.forEach((alert) => {
      const impact = this._sensorAlertImpact(alert.id, alert.sensor, alert.status);
      const status = alert.status === "unknown" ? "warning" : alert.status;
      if (impact.affectsScore && impact.points > 0) {
        addLoss(impact.category, impact.points, alert.title, alert.detail, status);
      } else {
        addInsight(impact.group, {
          category: impact.category,
          affectsScore: false,
          label: alert.title,
          detail: `${alert.detail}. Shown as context; it does not reduce Reef Health unless it explains a tank-water issue.`,
          status,
        });
      }
    });
    const phAlert = sensorAlerts.find((alert) => alert.id === "ph" && ["warning", "critical"].includes(alert.status));
    const co2Sensor = this._config.sensors?.co2;
    const co2Value = co2Sensor?.entity_id ? Number.parseFloat(this._stateValue(co2Sensor.entity_id)) : Number.NaN;
    if (phAlert && this._sensorEnabled(co2Sensor) && Number.isFinite(co2Value) && co2Value >= Number(co2Sensor.max)) {
      addInsight("context", {
        category: "chemistry",
        affectsScore: false,
        label: "CO2 may explain pH pressure",
        detail: `${co2Sensor.label || "CO2"} is ${this._format(co2Value, 0)} ${co2Sensor.unit || "ppm"}. Fresh air or gas exchange may help if pH is low.`,
        status: "warning",
      });
    }

    const tempSensor = this._config.sensors?.temp || {};
    const tempStatus = this._sensorStatus(tempSensor, "temp");
    const heaters = equipment.filter(([id, item]) => item.armed && this._equipmentProfile(id, item) === "heater");
    if (tempStatus === "critical") addCap(65, "Tank temperature outside range", "Temperature is a life-support reading.");
    if (heaters.length && (!this._sensorEnabled(tempSensor) || !tempSensor.entity_id || ["unknown", "muted"].includes(tempStatus))) {
      addCap(60, "Heater armed without verified tank temperature", "OpenReef cannot confidently supervise temperature equipment.");
      addLoss("life", 24, "Heater interlock cannot verify temperature", "Map a live display temperature sensor before relying on armed heaters.", "critical");
    }

    sensors.forEach(([id, sensor]) => {
      if (this._sensorKind(sensor, id) !== "binary") return;
      if (this._sensorStatus(sensor, id) !== "critical") return;
      if (id === "leak") addCap(35, "Leak detector active", "Treat this as a physical water safety issue.");
      if (id === "high_water") addCap(45, "High water level active", "Overflow or sump/rear chamber level may be unsafe.");
    });

    const armedUnavailableSet = new Set(this._validation?.armed_unavailable || []);
    equipment.forEach(([id, item]) => {
      if (!item.armed || !item.switch_entity_id || !armedUnavailableSet.has(item.switch_entity_id)) return;
      const profileType = this._equipmentProfile(id, item);
      if (running && ["heater", "return_pump", "ato"].includes(profileType)) {
        addCap(70, `${item.label || id} unavailable`, "An armed life-support control entity is unavailable.");
      }
    });

    if (running && this._atoHeldByReturnPump()) {
      addCap(60, "ATO held by return pump safety", "Top-off is blocked until return flow is confirmed.");
      addLoss("life", 16, "ATO return-pump safety active", this._returnPumpDependencyIssues().join(", "), "critical");
    }

    const displayWavemakers = equipment.filter(([id, item]) => item.armed && this._equipmentProfile(id, item) === "display_wavemaker" && item.switch_entity_id);
    const displayWavemakersOff = running
      ? displayWavemakers.filter(([, item]) => this._stateValue(item.switch_entity_id) !== "on")
      : [];
    if (displayWavemakersOff.length) {
      addLoss("equipment", 15, "Display wavemaker off in Running", "Inspect before restarting; fish can enter stopped wavemakers and flow is critical for corals.", "critical");
      addLoss("stability", 10, "Display flow reduced", "Corals can suffer when display flow is left off.", "warning");
      if (displayWavemakersOff.length === displayWavemakers.length) {
        addCap(75, "All mapped display wavemakers are off", "Restore display flow manually after inspecting the tank.", "warning");
      }
    }

    interlocks.forEach((issue) => {
      addLoss("maintenance", 8, issue.title, issue.detail, "warning");
    });
    if (activeMode !== "running" && this._modeTimerExpired() && !this._config?.mode?.autoReturn) {
      addLoss("maintenance", 12, `${this._activeModeLabel()} timer expired`, "Return to Running when the work is complete.", "warning");
    }

    Object.entries(this._healthTrends?.items || {}).forEach(([sensorId, trend]) => {
      const sensor = this._config.sensors?.[sensorId];
      if (!sensor || !this._sensorEnabled(sensor) || !sensor.entity_id) return;
      if (trend.affectsScore && trend.penalty > 0) {
        addLoss(trend.category || this._sensorHealthCategory(sensorId, sensor), trend.penalty, trend.label || `${sensor.label || sensorId} trend needs attention`, trend.detail, trend.status);
        return;
      }
      addInsight(trend.group || "context", {
        category: trend.category || this._sensorHealthCategory(sensorId, sensor),
        affectsScore: false,
        label: trend.label || `${sensor.label || sensorId} trend`,
        detail: trend.detail,
        status: trend.status || "context",
      });
    });

    this._manualTestFreshnessItems().forEach((item) => {
      if (item.affectsScore && item.points > 0) {
        addLoss(item.category, item.points, item.label, item.detail, item.status);
        return;
      }
      addInsight("context", {
        category: item.category,
        affectsScore: false,
        label: item.label,
        detail: item.detail,
        status: item.status,
      });
    });

    const categories = Object.fromEntries(this._healthCategoryChoices().map(([id, label]) => {
      const score = Math.max(0, Math.round(100 - Math.min(categoryLoss[id] || 0, 100)));
      return [id, { label, score, weight: weights[id] || 0, lost: Math.round(categoryLoss[id] || 0) }];
    }));
    let weightedScore = 0;
    Object.entries(categories).forEach(([id, item]) => {
      weightedScore += item.score * (weights[id] || 0);
    });
    let score = Math.max(0, Math.min(100, Math.round(weightedScore)));
    const appliedCap = caps.length ? caps.reduce((lowest, cap) => cap.limit < lowest.limit ? cap : lowest, caps[0]) : null;
    if (appliedCap) score = Math.min(score, appliedCap.limit);
    const sortedLosses = [...losses].sort((a, b) => {
      const statusRank = { critical: 2, warning: 1 };
      return (statusRank[b.status] || 0) - (statusRank[a.status] || 0) || b.points - a.points;
    });
    const topInsight = groups.action[0] || groups.watch[0] || null;
    const topReason = appliedCap?.label || topInsight?.label || "All scoring checks look steady";
    const learningCount = groups.learning.length;
    const contextCount = groups.context.length;
    const nextAction = appliedCap
      ? appliedCap.detail
      : topInsight?.detail
        || (learningCount
          ? "No action needed. OpenReef is still learning one or more normal trend patterns; current safety checks are still active."
          : contextCount
            ? "No action needed. Context notes are there for troubleshooting and do not affect the score by themselves."
            : "Keep monitoring and refresh health after the next meaningful tank change.");
    const grade = this._healthGrade(score);
    const status = this._healthStatus(score, caps);
    const gradeDetail = [
      `${grade} grade`,
      appliedCap ? `cap ${appliedCap.limit}` : "no hard cap",
      learningCount ? `${learningCount} trend${learningCount === 1 ? "" : "s"} learning` : "",
      contextCount ? `${contextCount} context note${contextCount === 1 ? "" : "s"}` : "",
    ].filter(Boolean).join(" · ");
    const detail = [
      this._tankProfileLabel(profile),
      `${mappedSensors}/${sensors.length} sensors mapped`,
      `${armedEquipment}/${equipment.length} armed`,
      `${critical.length} critical`,
      `${warnings.length} warning`,
    ].join(" · ");
    return {
      score,
      grade,
      gradeDetail,
      status,
      detail,
      profile,
      profileLabel: this._tankProfileLabel(profile),
      profileNote: this._tankProfileHealthNote(profile),
      categories,
      losses: sortedLosses,
      groups,
      caps,
      appliedCap,
      topReason,
      nextAction,
      trendFreshness: this._healthTrendFreshness(),
      learningCount,
      contextCount,
      criticalCount: critical.length,
      warningCount: warnings.length,
      unknownCount: unknowns.length,
    };
  }

  _systemCheck() {
    const sensors = Object.entries(this._config.sensors || {});
    const enabledSensors = sensors.filter(([, sensor]) => this._sensorEnabled(sensor));
    const mappedSensors = enabledSensors.filter(([, sensor]) => sensor.entity_id);
    const equipment = Object.entries(this._config.equipment || {});
    const mappedEquipment = equipment.filter(([, item]) => item.switch_entity_id);
    const armedEquipment = equipment.filter(([, item]) => item.armed);
    const sensorAlerts = this._sensorAlerts(enabledSensors);
    const interlocks = this._interlockWarnings();
    const missing = this._validation?.missing_entities || [];
    const armedUnavailable = this._validation?.armed_unavailable || [];
    const schedule = this._modeSchedule();
    const activeSchedules = Array.isArray(schedule.items)
      ? schedule.items.filter((item) => item?.enabled).length
      : 0;
    const customModes = this._customModes().length;
    const interlockConfig = this._config.interlocks || {};
    const lastActivity = Array.isArray(this._config.activity) && this._config.activity[0]
      ? this._config.activity[0].message || "Recorded"
      : "None yet";
    const health = this._reefHealthScore(enabledSensors, equipment, sensorAlerts, interlocks);
    const sensorSummary = this._sensorSummaryState(sensorAlerts, !enabledSensors.length);
    const manualTracked = this._manualTestParameterIds().filter((id) => this._manualTestConfig(id).enabled);
    const manualDue = this._manualTestFreshnessItems().filter((item) => item.status === "warning" || item.status === "critical");
    const manualLogged = this._manualTestParameterIds().filter((id) => this._manualReadings(id).length > 0);
    return {
      version: this._integrationVersion || "unknown",
      schema: this._config.schemaVersion || "unknown",
      tankProfile: health.profileLabel,
      health,
      controlMode: armedEquipment.length ? "OpenReef control armed" : "Monitor-only valid",
      activeMode: this._activeModeLabel(),
      modeTimer: this._activeModeCountdownText(),
      sensors: `${mappedSensors.length}/${enabledSensors.length}`,
      equipment: `${armedEquipment.length}/${equipment.length}`,
      mappedEquipment: `${mappedEquipment.length}/${equipment.length}`,
      energy: `${this._energyTotalMappings().filter(([, key]) => this._config.energy[key]).length}/3`,
      manualTests: `${manualTracked.length}/${this._manualTestParameterIds().length}`,
      manualDue: manualDue.length,
      manualLogged: manualLogged.length,
      alerts: [
        `${sensorSummary.criticalCount} critical`,
        `${sensorSummary.warningCount} warning`,
        sensorSummary.contextCount ? `${sensorSummary.contextCount} context warning${sensorSummary.contextCount === 1 ? "" : "s"}` : "",
      ].filter(Boolean).join(", "),
      interlocks: interlocks.length,
      atoDutyCycle: interlockConfig.atoDutyCycleEnabled
        ? `${interlockConfig.atoDutyCycleOnSeconds || 120}s every ${interlockConfig.atoDutyCycleIntervalMinutes || 60}m`
        : "off",
      missing: missing.length,
      armedUnavailable: armedUnavailable.length,
      customModes,
      schedules: `${activeSchedules} active / ${Array.isArray(schedule.items) ? schedule.items.length : 0} saved`,
      lastActivity,
      dirty: this._configDirty,
    };
  }

  _atoDutyCycleSummary() {
    const interlocks = this._config.interlocks || {};
    if (!interlocks.atoDutyCycleEnabled) {
      return "Off. OpenReef will not duty-cycle the ATO; continuous/manual ATO power is allowed.";
    }
    return `On. OpenReef powers armed ATO switches for ${interlocks.atoDutyCycleOnSeconds || 120} seconds every ${interlocks.atoDutyCycleIntervalMinutes || 60} minutes, then forces them off outside that window.`;
  }

  _betaChecklist(check = this._systemCheck()) {
    const sensors = Object.entries(this._config.sensors || {});
    const enabledSensors = sensors.filter(([, sensor]) => this._sensorEnabled(sensor));
    const mappedSensors = enabledSensors.filter(([, sensor]) => sensor.entity_id);
    const equipment = Object.entries(this._config.equipment || {});
    const mappedEquipment = equipment.filter(([, item]) => item.switch_entity_id);
    const armedEquipment = equipment.filter(([, item]) => item.armed);
    const displayWavemakers = equipment.filter(([id, item]) => this._equipmentProfile(id, item) === "display_wavemaker");
    const remindersOn = this._config.alerts?.wavemakerReminders !== false;
    const reminderMinutes = Number(this._config.alerts?.wavemakerReminderMinutes || 10);
    const missing = Number(check.missing || 0);
    const armedUnavailable = Number(check.armedUnavailable || 0);
    return [
      {
        state: this._config.display?.setupComplete ? "ok" : "warning",
        label: "Setup wizard",
        status: this._config.display?.setupComplete ? "ready" : "not finished",
        detail: this._config.display?.setupComplete
          ? "Setup is complete. The tester can still reopen Setup or Settings later."
          : "Finish setup before handing this build to a tester.",
      },
      {
        state: enabledSensors.length && mappedSensors.length === enabledSensors.length ? "ok" : "warning",
        label: "Owned sensors",
        status: `${mappedSensors.length}/${enabledSensors.length} mapped`,
        detail: "Disabled sensors are intentionally ignored.",
      },
      {
        state: missing || armedUnavailable ? "critical" : "ok",
        label: "Entity health",
        status: missing || armedUnavailable ? "needs attention" : "clean",
        detail: `${missing} missing, ${armedUnavailable} armed unavailable.`,
      },
      {
        state: equipment.length && mappedEquipment.length === equipment.length ? "ok" : equipment.length ? "warning" : "unknown",
        label: "Control safety",
        status: equipment.length ? `${armedEquipment.length}/${equipment.length} armed` : "monitor only",
        detail: "Only mapped and armed switch entities can be controlled.",
      },
      {
        state: this._config.interlocks?.atoDutyCycleEnabled ? "warning" : "unknown",
        label: "ATO duty cycle",
        status: this._config.interlocks?.atoDutyCycleEnabled ? "enabled" : "off",
        detail: this._atoDutyCycleSummary(),
      },
      {
        state: !displayWavemakers.length ? "unknown" : remindersOn && reminderMinutes >= 5 ? "ok" : remindersOn ? "warning" : "critical",
        label: "Display wavemaker reminders",
        status: !displayWavemakers.length ? "not mapped" : remindersOn ? `${reminderMinutes}m` : "off",
        detail: !displayWavemakers.length
          ? "Map display wavemakers only for pumps inside the display tank."
          : remindersOn
            ? "Warns while a display wavemaker remains off in Running."
            : "Turn this on before giving control access to a tester.",
      },
      {
        state: "unknown",
        label: "Manual smoke test",
        status: "tester to confirm",
        detail: "Open on desktop and phone, run Find matches, open trends, and copy this summary.",
      },
    ];
  }

  _dosingSummaryText() {
    const system = this._dosingSystem();
    const primary = this._dosingProduct(system.primaryProduct);
    const secondary = this._dosingProduct(system.secondaryProduct);
    const delivery = {
      ato: "ATO reservoir",
      dosing_pump: "dosing pump",
      manual_top_off: "manual top-off",
    }[system.secondaryDelivery] || "not set";
    const active = this._dosingActiveParameters();
    const lines = [
      "OpenReef Dosing Advisor summary",
      `Version: ${this._integrationVersion || "unknown"}`,
      `Advisory only: yes`,
      `Dosing Advisor enabled: ${this._dosingEnabled() ? "yes" : "no"}`,
      `Safety acknowledged: ${system.safetyAcknowledged ? "yes" : "no"}`,
      `Net tank volume: ${system.tankVolumeLitres ? `${this._format(system.tankVolumeLitres, 0)} L` : "not set"}`,
      `Primary system: ${primary.id ? `${primary.label} (${this._dosingProductClassLabel(primary.classId)})` : "not selected"}`,
      `Secondary supplement: ${secondary.id ? `${secondary.label} (${this._dosingProductClassLabel(secondary.classId)})` : "none"}`,
      secondary.id ? `Secondary delivery: ${delivery}` : "",
      ...(secondary.classId === "kalkwasser" ? [
        `Kalk daily volume: ${system.kalkDailyDoseMl ? `${this._format(system.kalkDailyDoseMl, 0)} mL/day` : "not set"}`,
        `Kalk concentration: ${system.kalkConcentrationTspPerGallon ? `${this._format(system.kalkConcentrationTspPerGallon, 2)} tsp/US gal` : "not set"}`,
        `Kalk evaporation ceiling: ${system.kalkEvaporationLimitMlPerDay ? `${this._format(system.kalkEvaporationLimitMlPerDay, 0)} mL/day` : "not set"}`,
        `Kalk max pH: ${this._format(system.kalkMaxPh || 8.45, 2)}`,
        `Kalk max pH rise: ${this._format(system.kalkMaxPhRise || 0.2, 2)}`,
      ] : []),
      `Trend data: ${this._consumptionFreshness()}`,
      "",
      "Safety model",
      "- OpenReef never controls dosing pumps in this build.",
      "- Exact mL advice requires product strength, tank volume, current dose, and safety acknowledgement.",
      "- Correction advice requires a fresh manual test.",
      "- Downward chemical correction is never suggested.",
      "- Kalkwasser is maintenance/support only and is never used as a correction bolus.",
      "",
      "Tracked parameters",
      ...(active.length ? active.map(([id, sensor]) => {
        const item = this._consumptionItem(id, sensor);
        const product = item.productInfo || this._dosingProductForParameter(id);
        const potency = item.potencyInfo || this._dosingEffectivePotency(id, sensor, this._dosingParamConfig(id), product);
        const status = item.recommendationState || item.status || "learning";
        return `- ${item.label || sensor.label || id}: ${status}, product ${product.label}, ${item.trendText || "trend not checked"}, maintenance: ${item.maintenanceText || item.doseText || "learning"}, correction: ${item.correctionText || "locked"}, strength: ${potency.label}`;
      }) : ["- no active dosing parameters"]),
    ].filter((line) => line !== "");
    return lines.join("\n");
  }

  _supportSummaryText() {
    const check = this._systemCheck();
    const sensors = Object.entries(this._config.sensors || {})
      .filter(([, sensor]) => this._sensorEnabled(sensor))
      .map(([id, sensor]) => {
        const status = this._sensorSupportStatus(sensor, id);
        return `- ${sensor.label || id}: ${sensor.entity_id || "not mapped"} (${status})`;
      });
    const equipment = Object.entries(this._config.equipment || {})
      .map(([id, item]) => {
        const profile = this._equipmentProfileLabel(this._equipmentProfile(id, item));
        const state = this._equipmentStateLabel(item);
        return `- ${item.label || id}: ${profile}, switch ${item.switch_entity_id || "not mapped"}, ${item.armed ? "armed" : "disarmed"}, ${state}`;
      });
    const energy = this._energyTotalMappings()
      .map(([label, energyKey, costKey]) => `- ${label}: energy ${this._config.energy?.[energyKey] || "not mapped"}, cost ${this._config.energy?.[costKey] || "not mapped"}`);
    const manualTests = this._manualTestParameterIds()
      .filter((id) => this._manualTestConfig(id).enabled || this._manualReadings(id).length)
      .map((id) => {
        const meta = this._manualTestMeta(id);
        const schedule = this._manualTestConfig(id);
        const state = this._manualDueState(id);
        const latest = state.latest;
        const latestText = latest
          ? `${this._format(Number(latest.value), this._sensorDigits(id))}${latest.unit ? ` ${latest.unit}` : meta.unit ? ` ${meta.unit}` : ""} on ${this._formatActivityTime(latest.timestamp)}`
          : "no result logged";
        const range = `${meta.min} - ${meta.max}${meta.unit ? ` ${meta.unit}` : ""}`;
        const source = schedule.preferredSource ? `, preferred source ${schedule.preferredSource}` : "";
        return `- ${meta.label}: ${schedule.enabled ? `due after ${schedule.cadenceDays}d, critical after ${schedule.criticalAfterDays}d` : "not scheduled"}, target ${range}${source}, ${state.label}, ${latestText}`;
      });
    const dosingSystem = this._dosingSystem();
    const primaryProduct = this._dosingProduct(dosingSystem.primaryProduct);
    const secondaryProduct = this._dosingProduct(dosingSystem.secondaryProduct);
    const dosingAdvisor = this._dosingEnabled()
      ? this._dosingActiveParameters().map(([id, sensor]) => {
        const item = this._consumptionItem(id, sensor);
        const product = item.productInfo || this._dosingProductPreset(id);
        const potency = item.potencyInfo || this._dosingEffectivePotency(id, sensor, this._dosingParamConfig(id), product);
        const status = item.status === "learning" ? "learning" : item.status;
        const advice = item.projectionText ? `${item.trendText} ${item.projectionText}` : item.trendText;
        return `- ${item.label}: ${status}/${item.recommendationState || "learning"}, product ${product.label}, ${advice} Maintenance: ${item.maintenanceText || item.doseText}. Correction: ${item.correctionText || "locked"}. Safety: ${item.safetyText || "advisory only"}. Solution strength: ${potency.label}.`;
      })
      : ["- disabled"];
    const interlocks = this._config.interlocks || {};
    const alerts = this._config.alerts || {};
    const activity = Array.isArray(this._config.activity)
      ? this._config.activity.slice(0, 5).map((item) => `- ${this._formatActivityTime(item.timestamp)}: ${item.message || item.type || "activity"}`)
      : [];
    const checklist = this._betaChecklist(check).map((item) => `- ${item.label}: ${item.status}${item.detail ? ` - ${item.detail}` : ""}`);
    const health = check.health || this._reefHealthScore();
    const healthCategories = this._healthCategoryChoices()
      .map(([id]) => health.categories?.[id])
      .filter(Boolean)
      .map((category) => `- ${category.label}: ${category.score}/100 (${category.lost} lost, ${Math.round(category.weight * 100)}% weight)`);
    const healthCaps = health.caps?.length
      ? health.caps.map((cap) => `- ${cap.label}: cap ${cap.limit} - ${cap.detail}`)
      : ["- none"];
    const healthLosses = health.losses?.length
      ? health.losses.slice(0, 5).map((loss) => `- ${loss.label}: -${loss.points} (${loss.category})${loss.detail ? ` - ${loss.detail}` : ""}`)
      : ["- none"];
    const healthGroupLines = (label, group) => [
      label,
      ...((health.groups?.[group] || []).length
        ? health.groups[group].slice(0, 6).map((item) => `- ${item.label}: ${item.affectsScore ? `${item.points ? `-${item.points}` : "cap"} score impact` : "info only"}${item.detail ? ` - ${item.detail}` : ""}`)
        : ["- none"]),
    ];
    const lines = [
      "OpenReef support summary",
      `Version: ${check.version}`,
      `Schema: ${check.schema}`,
      `Setup complete: ${this._config.display?.setupComplete ? "yes" : "no"}`,
      `Tank profile: ${check.tankProfile}`,
      `OpenReef control mode: ${check.controlMode}`,
      `Reef Health Score: ${health.score}/100 (${health.grade}, ${health.status})`,
      `Reef Health detail: ${health.gradeDetail || `${health.grade} grade`}`,
      `Reef Health top reason: ${health.topReason}`,
      `Reef Health next action: ${health.nextAction}`,
      `Reef Health trend data: ${health.trendFreshness}`,
      `Reef Health learning items: ${health.learningCount || 0}`,
      `Active mode: ${check.activeMode}`,
      `Mode timer: ${check.modeTimer}`,
      `Sensors mapped/enabled: ${check.sensors}`,
      `Equipment armed/total: ${check.equipment}`,
      `Equipment mapped/total: ${check.mappedEquipment}`,
      `Energy totals mapped: ${check.energy}`,
      `Manual tests tracked: ${check.manualTests}`,
      `Manual tests due: ${check.manualDue}`,
      `Manual parameters logged: ${check.manualLogged}`,
      `Alerts: ${check.alerts}`,
      `Interlock warnings: ${check.interlocks}`,
      `ATO duty cycle: ${check.atoDutyCycle}`,
      `Missing entities: ${check.missing}`,
      `Armed unavailable: ${check.armedUnavailable}`,
      `Custom modes: ${check.customModes}`,
      `Schedules: ${check.schedules}`,
      `Last activity: ${check.lastActivity}`,
      `Unsaved changes: ${check.dirty ? "yes" : "no"}`,
      "",
      "Reef Health categories",
      ...healthCategories,
      "",
      "Reef Health hard caps",
      ...healthCaps,
      "",
      "Reef Health point losses",
      ...healthLosses,
      "",
      "Reef Health insights",
      ...healthGroupLines("Needs action", "action"),
      ...healthGroupLines("Worth watching", "watch"),
      ...healthGroupLines("Context", "context"),
      ...healthGroupLines("Learning", "learning"),
      "",
      "Enabled sensors",
      ...(sensors.length ? sensors : ["- none"]),
      "",
      "Equipment",
      ...(equipment.length ? equipment : ["- none"]),
      "",
      "Energy mappings",
      ...energy,
      "",
      "Manual testing",
      ...(manualTests.length ? manualTests : ["- no manual test schedules or readings yet"]),
      "",
      "Dosing system",
      `- advisory only: yes`,
      `- safety acknowledged: ${dosingSystem.safetyAcknowledged ? "yes" : "no"}`,
      `- net tank volume: ${dosingSystem.tankVolumeLitres ? `${this._format(dosingSystem.tankVolumeLitres, 0)} L` : "not set"}`,
      `- primary: ${primaryProduct.id ? `${primaryProduct.label} (${this._dosingProductClassLabel(primaryProduct.classId)})` : "not selected"}`,
      `- secondary: ${secondaryProduct.id ? `${secondaryProduct.label} (${this._dosingProductClassLabel(secondaryProduct.classId)})` : "none"}`,
      ...(secondaryProduct.classId === "kalkwasser" ? [
        `- kalk daily volume: ${dosingSystem.kalkDailyDoseMl ? `${this._format(dosingSystem.kalkDailyDoseMl, 0)} mL/day` : "not set"}`,
        `- kalk concentration: ${dosingSystem.kalkConcentrationTspPerGallon ? `${this._format(dosingSystem.kalkConcentrationTspPerGallon, 2)} tsp/US gal` : "not set"}`,
        `- kalk evaporation ceiling: ${dosingSystem.kalkEvaporationLimitMlPerDay ? `${this._format(dosingSystem.kalkEvaporationLimitMlPerDay, 0)} mL/day` : "not set"}`,
        `- kalk max pH: ${this._format(dosingSystem.kalkMaxPh || 8.45, 2)}`,
        `- kalk max pH rise: ${this._format(dosingSystem.kalkMaxPhRise || 0.2, 2)}`,
      ] : []),
      "",
      "Dosing Advisor",
      ...(dosingAdvisor.length ? dosingAdvisor : ["- no active dosing parameters"]),
      "",
      "Safety settings",
      `- heater requires tank temp: ${interlocks.heaterRequiresTankTemp !== false ? "on" : "off"}`,
      `- ATO return-pump warning: ${interlocks.atoReturnPumpWarning !== false ? "on" : "off"}`,
      `- ATO block if return pump off: ${interlocks.atoBlockWhenReturnPumpOff ? "on" : "off"}`,
      `- ATO duty cycle: ${check.atoDutyCycle}`,
      `- skimmer auto-off with return pump: ${interlocks.skimmerAutoOffWhenReturnPumpOff ? "on" : "off"}`,
      `- wavemaker reminders: ${alerts.wavemakerReminders !== false ? "on" : "off"} (${alerts.wavemakerReminderMinutes || 10}m)`,
      `- HA persistent notifications: ${alerts.persistentNotifications ? "on" : "off"}`,
      "",
      "Beta handoff checklist",
      ...checklist,
      "",
      "Recent activity",
      ...(activity.length ? activity : ["- none"]),
    ];
    return lines.join("\n");
  }

  _betaSmokeTestText() {
    const check = this._systemCheck();
    const enabledSensors = Object.entries(this._config.sensors || {})
      .filter(([, sensor]) => this._sensorEnabled(sensor))
      .map(([, sensor]) => sensor.label || "Sensor");
    const equipment = Object.values(this._config.equipment || {})
      .map((item) => item.label || "Equipment");
    const lines = [
      "OpenReef beta smoke-test checklist",
      `OpenReef version: ${check.version}`,
      "",
      "Before testing",
      "- Update OpenReef in HACS and restart Home Assistant.",
      "- Open OpenReef from the Home Assistant sidebar.",
      "- Keep Home Assistant open on another tab or device so disconnections are obvious.",
      "",
      "Desktop stability",
      "- Open OpenReef, hard refresh the browser, and reopen it from the sidebar.",
      "- Confirm Home Assistant does not show Connection lost / Reconnecting.",
      "- Open Settings -> System Check and press Refresh checks.",
      "- Open Mission Control and press Refresh health. Confirm the category breakdown, top reason, and trend freshness update without HA reconnecting.",
      "",
      "Setup and mapping",
      "- Open Setup and confirm the wizard can move through every step.",
      "- Pick the closest tank type/profile and confirm the wording matches the reef being tested.",
      "- If testing Neptune data, choose the closest guide: Apex controller, Apex + Trident, Apex + Trident NP, Apex + Trident + Trident NP, Apex + FMM, or Apex full ecosystem.",
      "- Confirm Apex/Trident entities already exist in Home Assistant; OpenReef maps HA entities and does not connect directly to Apex hardware yet.",
      `- Confirm enabled sensors match the tester's system: ${enabledSensors.join(", ") || "none enabled"}.`,
      "- Use Find matches for at least two sensors and confirm suggestions are sensible.",
      "- Do not paste HA tokens or secrets anywhere in OpenReef.",
      "",
      "Manual tests",
      "- Open Manual Tests and apply the suggested routine for the selected tank profile.",
      "- Change one cadence to confirm the routine is configurable, then save Settings.",
      "- Record a batch test session with two or more values using one shared date/time.",
      "- Backdate the session, save it, then confirm the next entry keeps that date/time instead of resetting to now.",
      "- Open a Manual Tests trend for one parameter with at least two results.",
      "- Delete any test-only manual entries afterwards.",
      "- Confirm the support summary shows tracked, due, and logged manual parameters.",
      "",
      "Live Stats and trends",
      "- Open Live Stats and confirm mapped readings show current values.",
      "- Open a trend for temperature and pH if available.",
      "- Test 1 hour, 24 hours, 7 days, and 30 days. Long ranges may be limited by HA recorder history.",
      "- Repeat one trend test on a phone or narrow browser window.",
      "",
      "Controls and safety",
      `- Review mapped equipment: ${equipment.join(", ") || "none mapped"}.`,
      "- Only arm equipment the tester is comfortable controlling.",
      "- Confirm disarmed equipment switches are greyed/locked.",
      "- Toggle one safe mapped switch, then return it to the expected state.",
      "- If display wavemakers are mapped, confirm the warning/reminder wording is visible and understood.",
      "",
      "Modes",
      "- Open Feed and Maintenance confirmation dialogs.",
      "- Confirm the plan shows exactly what will change before applying.",
      "- Apply a mode only when safe to do so, then confirm Running restores the expected state.",
      "- If ATO duty cycle is enabled, confirm the tester expects short ATO on-windows.",
      "",
      "Mobile",
      "- Open OpenReef on a phone.",
      "- Check Mission Control, Live Stats, Controls, Energy, Settings, and System Check.",
      "- Confirm setup/settings sections scroll normally and buttons are tappable.",
      "",
      "Report back",
      "- Copy Settings -> System Check -> Copy feedback template.",
      "- Copy Settings -> System Check -> Copy support summary.",
      "- Note any wrong entity suggestions, confusing wording, mobile layout issues, or HA reconnects.",
      "- Do not send API keys, passwords, or Home Assistant long-lived access tokens.",
    ];
    return lines.join("\n");
  }

  _betaFeedbackTemplateText() {
    const check = this._systemCheck();
    const lines = [
      "OpenReef beta feedback",
      `OpenReef version: ${check.version}`,
      `Config schema: ${check.schema}`,
      "",
      "Tester setup",
      "- Home Assistant version:",
      "- Device type: HA Green / HA Yellow / Raspberry Pi / VM / other:",
      "- Browser and device used:",
      "- Reef equipment being tested:",
      "- Neptune entities in Home Assistant: Apex / Trident / Trident NP / FMM / none:",
      "",
      "Install and setup",
      "- Did OpenReef install/update cleanly?",
      "- Did OpenReef appear in the sidebar after restart?",
      "- Did the setup wizard make sense?",
      "- Which Apex/OpenReef sensor guide did you choose?",
      "- Which entity suggestions were correct?",
      "- Which entity suggestions were missing or wrong?",
      "",
      "Manual tests",
      "- Which manual test routine did OpenReef suggest?",
      "- Did the cadence controls make sense for your reef?",
      "- Were you able to record and delete a batch of manual results?",
      "- Did historical date entry feel easy enough?",
      "- Did manual charts make sense for your test history?",
      "- Should any test be checked more or less often by default?",
      "",
      "Live Stats and trends",
      "- Which readings showed correctly?",
      "- Which trend ranges worked? 1 hour / 6 hours / 24 hours / 7 days / 30 days",
      "- Any values, units, labels, or graph ranges look wrong?",
      "",
      "Controls, modes, and safety",
      "- Which equipment did you map?",
      "- Which equipment did you arm?",
      "- Did disarmed equipment stay locked?",
      "- Did Feed, Maintenance, Running, or custom modes do what the preview said?",
      "- Did ATO duty cycle behaviour match your expectation?",
      "- If display wavemakers were used, were the warnings clear?",
      "",
      "Mobile",
      "- Phone/tablet tested:",
      "- Were buttons tappable?",
      "- Did setup/settings scroll properly?",
      "- Any text too small, hidden, or hard to read?",
      "",
      "Stability",
      "- Any Home Assistant Connection lost / Reconnecting messages?",
      "- Any browser freezes, restarts, or slow screens?",
      "- Any action that felt unsafe or confusing?",
      "",
      "Screenshots or notes",
      "-",
      "",
      "Support summary",
      "Paste Settings -> System Check -> Copy support summary below this line.",
      "",
      "Do not include API keys, passwords, Home Assistant long-lived access tokens, or private network credentials.",
    ];
    return lines.join("\n");
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
        ${this._onboarding && this._onboarding.active ? this._onboardingOverlay() : ""}
        ${this._buddyOverlay()}
      </main>
    `;

    this._lastRenderedSetupOpen = this._setupOpen;
    this._lastRenderedSetupStep = this._setupOpen ? this._setupStep : null;
    if (preserveSetupScroll) this._restoreScrollState(scrollState);
    if (this._onboarding && this._onboarding.active) {
      requestAnimationFrame(() => this._positionOnboarding());
    }
    this._maybeAutoStartOnboarding();
  }

  // --- Avatar onboarding tour (Phase 1) -----------------------------------

  _onboardingDone() {
    try { return window.localStorage?.getItem("openreef:onboarding:v1:done") === "1"; }
    catch { return false; }
  }

  _setOnboardingDone() {
    try { window.localStorage?.setItem("openreef:onboarding:v1:done", "1"); } catch { /* ignore */ }
  }

  _tone() {
    try { return window.localStorage?.getItem("openreef:tone") === "professional" ? "professional" : "cheeky"; }
    catch { return "cheeky"; }
  }

  _toggleTone() {
    const next = this._tone() === "cheeky" ? "professional" : "cheeky";
    try { window.localStorage?.setItem("openreef:tone", next); } catch { /* ignore */ }
    this._render();
  }

  _avatarBase() { return "/openreef_static/avatar/"; }

  _avatarEmoji(pose) {
    return { idle: "👋", point: "👉", smug: "😏", facepalm: "🤦", celebrate: "🎉", concerned: "😟", thinking: "🤔", chilled: "😎" }[pose] || "🙂";
  }

  _probeAvatar() {
    if (this._avatarProbing) return;
    this._avatarProbing = true;
    ["idle", "point", "smug", "facepalm", "celebrate", "concerned", "thinking", "chilled"].forEach((pose) => {
      const img = new Image();
      img.onload = () => { this._avatarPoses[pose] = true; this._render(); };
      img.src = `${this._avatarBase()}${pose}.png`;
    });
  }

  _probeSticker() {
    if (this._stickerReady || this._stickerProbing) return;
    this._stickerProbing = true;
    const img = new Image();
    img.onload = () => { this._stickerReady = true; this._stickerProbing = false; if (this._onboarding && this._onboarding.active) this._render(); };
    img.onerror = () => { this._stickerProbing = false; };
    img.src = `${this._avatarBase()}apex-throne.png`;
  }

  _probeWalk() {
    if (this._walkReady || this._walkProbing) return;
    this._walkProbing = true;
    // Preload all four so frame swaps are instant once the cycle runs.
    ["walk-1", "walk-2", "walk-3", "walk-4"].forEach((f) => { const i = new Image(); i.src = `${this._avatarBase()}${f}.png`; });
    const img = new Image();
    img.onload = () => { this._walkReady = true; this._walkProbing = false; };
    img.onerror = () => { this._walkProbing = false; };
    img.src = `${this._avatarBase()}walk-1.png`;
  }

  _runWalk(dx) {
    if (!this._onboarding) return;
    clearInterval(this._onboarding.walkInterval);
    clearTimeout(this._onboarding.walkEndTimer);
    const walkingNow = this._onboarding.walking && this._walkReady && window.innerWidth > 640;
    if (!walkingNow) { this._onboarding.walking = false; return; }
    const img = this.shadowRoot.querySelector(".or-walk-img");
    // Frames face LEFT; flip when heading right.
    if (img) img.style.transform = dx > 4 ? "scaleX(-1)" : "none";
    this._onboarding.walkFrame = 0;
    this._onboarding.walkInterval = setInterval(() => {
      const el = this.shadowRoot.querySelector(".or-walk-img");
      if (!el) return;
      this._onboarding.walkFrame = (this._onboarding.walkFrame + 1) % 4;
      el.src = `${this._avatarBase()}walk-${this._onboarding.walkFrame + 1}.png`;
    }, 140);
    this._onboarding.walkEndTimer = setTimeout(() => {
      clearInterval(this._onboarding.walkInterval);
      this._onboarding.walkInterval = null;
      if (this._onboarding) { this._onboarding.walking = false; this._render(); }
    }, 640);
  }

  _avatarMarkup(pose) {
    if (this._avatarPoses[pose]) {
      return `<img class="or-avatar-img" src="${this._avatarBase()}${this._escape(pose)}.png" alt="">`;
    }
    return `<div class="or-avatar-ph" data-pose="${this._escape(pose)}">${this._avatarEmoji(pose)}</div>`;
  }

  _onboardingScript() {
    return [
      { id: "welcome", anchor: null, pose: "idle",
        cheeky: "Welcome aboard! A 30-second tour — and not a single line of Apex code. No virtual outlets, no Defer commands, no hunting through scattered docs for the one setting you need.",
        professional: "Welcome to OpenReef. Here's a quick 30-second tour of the main features." },
      { id: "reef-health", anchor: "reef-health", pose: "point",
        cheeky: "Your whole reef's health in one honest number. Apex Fusion shows you the graphs and leaves you to play detective — I actually tell you what they mean.",
        professional: "Your Reef Health Score: one explainable 0-100 read on the tank, weighted for your reef type." },
      { id: "dosing", anchor: "dosing", pose: "smug",
        cheeky: "Your alk, cal and mag consumption — worked out, with exactly how much to dose. The maths is free; the Trident's reagents sadly aren't. Good news: my mate Harry does ABC reagents cheaper.",
        link: { label: "Harry's ABC reagents → marine-spec.co.uk", url: "https://www.marine-spec.co.uk" },
        professional: "The Dosing Advisor estimates alk/cal/mag consumption from history, projects when you'll reach a limit, and suggests dose changes. Advisory only." },
      { id: "attention", anchor: "attention", pose: "facepalm",
        cheeky: "Anything wrong shows up here in plain English. No fault codes to Google, no scattered docs, no three-day forum thread just to get your auto top-off behaving.",
        professional: "Anything that needs attention - alerts, missing mappings, safety interlocks - is summarised here in plain English." },
      { id: "sensors", anchor: "sensors", pose: "point",
        cheeky: "Tap any reading for its full trend. Apex probes, Trident, and the cheap non-Apex sensors your controller flatly refuses to talk to — all in one place.",
        professional: "Tap any reading to open its trend, with ranges from 1 hour to 30 days." },
      { id: "safety", anchor: "settings", pose: "idle",
        cheeky: "One serious note: OpenReef never switches an outlet until you map it and arm it yourself. Your livestock is never automated behind your back. Set that up in Settings.",
        professional: "One serious note: OpenReef never switches an outlet until you map it and arm it yourself. Your livestock is never automated behind your back. Set that up in Settings." },
      { id: "done", anchor: null, pose: "celebrate",
        cheeky: "That's the tour — your reef's in good hands. Now go show your Apex who's boss. 🪸",
        professional: "That's the tour. You can replay it any time from the Tour button." },
    ];
  }

  _onboardingVisibleSteps() {
    // Always show every step (so every pose and the supplier tip appear). A step
    // whose anchor element isn't on screen just renders centred with no spotlight
    // (see _positionOnboarding).
    return this._onboardingScript();
  }

  _startOnboarding() {
    const steps = this._onboardingVisibleSteps();
    if (!steps.length) return;
    this._probeAvatar();
    this._probeSticker();
    this._probeWalk();
    this._onboarding = { active: true, step: 0, steps, scrolledStep: -1, walking: false, walkFrame: 0, walkInterval: null, walkEndTimer: null };
    this._render();
  }

  _endOnboarding(markDone = true) {
    if (markDone) this._setOnboardingDone();
    if (this._onboarding) {
      clearInterval(this._onboarding.walkInterval);
      clearTimeout(this._onboarding.walkEndTimer);
    }
    this._onboarding = null;
    this._render();
  }

  _onboardingNext() {
    if (!this._onboarding) return;
    if (this._onboarding.step >= this._onboarding.steps.length - 1) { this._endOnboarding(true); return; }
    this._onboarding.step += 1;
    this._onboarding.walking = true;
    this._render();
  }

  _onboardingBack() {
    if (!this._onboarding) return;
    if (this._onboarding.step === 0) return;
    this._onboarding.step -= 1;
    this._onboarding.walking = true;
    this._render();
  }

  _maybeAutoStartOnboarding() {
    if (this._onboardingChecked) return;
    this._onboardingChecked = true;
    if (this._onboardingDone()) return;
    if (this._setupOpen || this._trend || this._activeTab !== "mission") return;
    if (this._onboarding && this._onboarding.active) return;
    requestAnimationFrame(() => {
      if (!this._setupOpen && !this._trend && this._activeTab === "mission" && !this._onboardingDone()) {
        this._startOnboarding();
      }
    });
  }

  _positionOnboarding() {
    if (!this._onboarding || !this._onboarding.active) return;
    const narrator = this.shadowRoot.querySelector(".or-narrator");
    const spotlight = this.shadowRoot.querySelector(".or-spotlight");
    if (!spotlight || !narrator) return;
    const step = this._onboarding.steps[this._onboarding.step];
    const anchorEl = step && step.anchor ? this.shadowRoot.querySelector(`[data-tour="${step.anchor}"]`) : null;
    // Bring the target into view first (instant, so rects are correct for placement).
    if (anchorEl && this._onboarding.scrolledStep !== this._onboarding.step) {
      this._onboarding.scrolledStep = this._onboarding.step;
      anchorEl.scrollIntoView({ block: "center", behavior: "auto" });
    }
    // Spotlight ring on the anchored card (or hidden for centre-stage steps).
    if (anchorEl) {
      const r = anchorEl.getBoundingClientRect();
      const pad = 8;
      spotlight.style.opacity = "1";
      spotlight.style.top = `${r.top - pad}px`;
      spotlight.style.left = `${r.left - pad}px`;
      spotlight.style.width = `${r.width + pad * 2}px`;
      spotlight.style.height = `${r.height + pad * 2}px`;
    } else {
      spotlight.style.opacity = "0";
      spotlight.style.width = "0px";
      spotlight.style.height = "0px";
    }
    // Mobile keeps the docked stacked bar (CSS); desktop walks the guide to the card.
    if (window.innerWidth <= 640) {
      ["left", "top", "right", "bottom", "transform"].forEach((p) => { narrator.style[p] = ""; });
      this._onboarding.pos = null;
      return;
    }
    const m = 14;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const nw = narrator.offsetWidth;
    const nh = narrator.offsetHeight;
    let centreX;
    let top;
    if (anchorEl) {
      const r = anchorEl.getBoundingClientRect();
      centreX = r.left + r.width / 2;
      if (vh - r.bottom >= nh + 20) top = r.bottom + 14;
      else if (r.top >= nh + 20) top = r.top - nh - 14;
      else top = Math.max(m, vh - nh - m);
    } else {
      // Centre-stage steps (welcome / finale) sit centred on screen, not at the
      // bottom — the finale's tall sticker bubble would otherwise run off-screen.
      centreX = vw / 2;
      top = Math.max(m, (vh - nh) / 2);
    }
    const left = Math.round(Math.max(m, Math.min(centreX - nw / 2, vw - nw - m)));
    top = Math.round(top);
    // First placement snaps; later steps animate the walk between cards.
    const firstPlace = !this._onboarding.pos;
    const prevLeft = this._onboarding.pos ? this._onboarding.pos.left : left;
    if (firstPlace) narrator.style.transition = "none";
    narrator.style.left = `${left}px`;
    narrator.style.top = `${top}px`;
    narrator.style.right = "auto";
    narrator.style.bottom = "auto";
    narrator.style.transform = "none";
    if (firstPlace) { void narrator.offsetWidth; narrator.style.transition = ""; }
    this._onboarding.pos = { left, top };
    this._runWalk(left - prevLeft);
  }

  _onboardingOverlay() {
    const ob = this._onboarding;
    const steps = ob.steps;
    const idx = Math.min(ob.step, steps.length - 1);
    const step = steps[idx];
    const tone = this._tone();
    const line = step[tone] || step.cheeky;
    const isLast = idx === steps.length - 1;
    const dots = steps.map((_, i) => `<span class="or-dot ${i === idx ? "active" : ""}"></span>`).join("");
    // On desktop, render the guide where it last stood so it walks to the next card.
    const seed = window.innerWidth > 640 && ob.pos
      ? ` style="left:${ob.pos.left}px;top:${ob.pos.top}px;right:auto;bottom:auto;transform:none;"`
      : "";
    // While moving between cards (desktop, frames loaded) show the walk cycle; otherwise the pose.
    const walkingNow = ob.walking && this._walkReady && window.innerWidth > 640;
    const avatarInner = walkingNow
      ? `<img class="or-avatar-img or-walk-img" src="${this._avatarBase()}walk-${(ob.walkFrame % 4) + 1}.png" alt="">`
      : this._avatarMarkup(step.pose);
    return `
      <div class="or-onboard" role="dialog" aria-label="OpenReef guided tour">
        <div class="or-spotlight"></div>
        <div class="or-narrator"${seed}>
          <div class="or-avatar pose-${this._escape(step.pose)}">${avatarInner}</div>
          <div class="or-bubble">
            <div class="or-bubble-top">
              <span class="eyebrow">Your guide · ${idx + 1}/${steps.length}</span>
              <button class="or-tone" data-action="onboarding-tone" title="Switch tone">${tone === "cheeky" ? "😏 Cheeky" : "👔 Pro"}</button>
            </div>
            ${isLast && tone === "cheeky" && this._stickerReady ? `<img class="or-sticker" src="${this._avatarBase()}apex-throne.png" alt="OpenReef's professional assessment of the competition">` : ""}
            <p class="or-line">${this._escape(line)}</p>
            ${step.link && tone === "cheeky" ? `<a class="or-link" href="${this._escape(step.link.url)}" target="_blank" rel="noopener noreferrer">${this._escape(step.link.label)}</a>` : ""}
            <div class="or-dots">${dots}</div>
            <div class="or-actions">
              <button class="secondary compact-button" data-action="onboarding-skip">Skip</button>
              <span class="or-spacer"></span>
              ${idx > 0 ? `<button class="secondary compact-button" data-action="onboarding-back">Back</button>` : ""}
              <button class="primary compact-button" data-action="onboarding-next">${isLast ? "Finish 🍻" : "Next"}</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // --- Phase 3: reactive corner buddy ------------------------------------

  _buddyEnabled() {
    try { return window.localStorage?.getItem("openreef:buddy") !== "off"; }
    catch { return true; }
  }

  _setBuddyEnabled(on) {
    try { window.localStorage?.setItem("openreef:buddy", on ? "on" : "off"); } catch { /* ignore */ }
  }

  _buddyReaction(health, tone) {
    const critical = health.status === "critical"
      || health.criticalCount > 0
      || (health.appliedCap && health.appliedCap.status === "critical");
    const warning = !critical && (health.status === "warning" || health.warningCount > 0 || Boolean(health.appliedCap));
    if (critical) {
      // Serious — identical in both tones, no jokes. Uses the engine's own text.
      return { mood: "critical", pose: "concerned", title: health.topReason || "Needs attention now", line: health.nextAction || "Check this as soon as you can.", key: `crit|${health.topReason || ""}` };
    }
    if (warning) {
      return { mood: "warning", pose: "point", title: health.topReason || "Worth a look", line: health.nextAction || "", key: `warn|${health.topReason || ""}` };
    }
    if (health.learningCount > 0) {
      return {
        mood: "learning", pose: "thinking",
        title: tone === "cheeky" ? "Still learning your tank" : "Learning baselines",
        line: tone === "cheeky" ? "Give me a few more days of data and I'll spot the patterns Fusion never would." : "Some trends are still establishing a baseline.",
        key: "learn",
      };
    }
    const great = health.grade === "A";
    return {
      mood: "ok", pose: great ? "celebrate" : "chilled",
      title: tone === "cheeky" ? (great ? "Boringly stable" : "All cruising") : "All in range",
      line: tone === "cheeky"
        ? (great ? "Exactly how a reef should be. Nothing for you to do." : "Nothing needs you right now.")
        : "All monitored parameters are within range.",
      key: great ? "ok-a" : "ok",
    };
  }

  _buddyOverlay() {
    if (!this._config || this._activeTab !== "mission") return "";
    if (this._onboarding && this._onboarding.active) return "";
    if (this._setupOpen || this._trend || this._modeConfirm || this._equipmentDetail || this._controlConfirm) return "";
    if (this._buddy.dismissed || !this._buddyEnabled()) return "";
    this._probeAvatar();

    const tone = this._tone();
    const reaction = this._buddyReaction(this._reefHealthScore(), tone);
    // Auto-open the bubble when the situation changes; collapse non-critical after a while.
    if (reaction.key !== this._buddy.lastKey) {
      this._buddy.lastKey = reaction.key;
      this._buddy.expanded = true;
      if (this._buddy.timer) { clearTimeout(this._buddy.timer); this._buddy.timer = null; }
      if (reaction.mood !== "critical") {
        this._buddy.timer = setTimeout(() => {
          if (this._buddy) { this._buddy.expanded = false; this._buddy.timer = null; this._render(); }
        }, 9000);
      }
    }
    const expanded = this._buddy.expanded;
    const bubble = expanded ? `
      <div class="or-buddy-bubble mood-${reaction.mood}">
        <button class="or-buddy-close" data-action="buddy-dismiss" title="Hide your reef buddy">×</button>
        <div class="or-bubble-top">
          <span class="eyebrow">Reef buddy</span>
          <button class="or-tone" data-action="onboarding-tone" title="Switch tone">${tone === "cheeky" ? "😏 Cheeky" : "👔 Pro"}</button>
        </div>
        <strong class="or-buddy-title">${this._escape(reaction.title)}</strong>
        ${reaction.line ? `<p class="or-buddy-line">${this._escape(reaction.line)}</p>` : ""}
      </div>` : "";
    return `
      <div class="or-buddy">
        ${bubble}
        <button class="or-buddy-avatar mood-${reaction.mood}" data-action="buddy-toggle" title="Your reef buddy">
          <span class="or-buddy-dot mood-${reaction.mood}"></span>
          ${this._avatarMarkup(reaction.pose)}
        </button>
      </div>
    `;
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
      ["manual", "Manual Tests"],
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
    if (this._activeTab === "manual") return this._manualTests();
    if (this._activeTab === "controls") return this._controls();
    if (this._activeTab === "energy") return this._energy();
    if (this._activeTab === "settings") return this._settings();
    return this._mission();
  }

  _sensorAlertBuckets(sensorAlerts = []) {
    const buckets = {
      scoringCritical: [],
      scoringWarning: [],
      context: [],
      unknown: [],
    };
    sensorAlerts.forEach((alert) => {
      const impact = this._sensorAlertImpact(alert.id, alert.sensor, alert.status);
      if (!impact.affectsScore) {
        buckets.context.push(alert);
      } else if (alert.status === "critical") {
        buckets.scoringCritical.push(alert);
      } else if (alert.status === "unknown") {
        buckets.unknown.push(alert);
      } else {
        buckets.scoringWarning.push(alert);
      }
    });
    return buckets;
  }

  _sensorSummaryState(sensorAlerts = [], noEnabledSensors = false) {
    const buckets = this._sensorAlertBuckets(sensorAlerts);
    const criticalCount = buckets.scoringCritical.length;
    const warningCount = buckets.scoringWarning.length + buckets.unknown.length;
    const contextCount = buckets.context.length;
    const detail = [
      `${criticalCount} critical`,
      `${warningCount} warning`,
      contextCount ? `${contextCount} context warning${contextCount === 1 ? "" : "s"}` : "",
    ].filter(Boolean).join(" · ");
    return {
      ...buckets,
      criticalCount,
      warningCount,
      contextCount,
      detail,
      status: criticalCount ? "critical" : warningCount || contextCount || noEnabledSensors ? "warning" : "ok",
    };
  }

  _mission() {
    const sensors = this._enabledSensors();
    const equipment = Object.entries(this._config.equipment || {});
    const sensorAlerts = this._sensorAlerts(sensors);
    const sensorSummary = this._sensorSummaryState(sensorAlerts, !sensors.length);
    const missing = this._validation?.missing_entities || [];
    const armedUnavailable = this._validation?.armed_unavailable || [];
    const interlocks = this._interlockWarnings();
    const mappedSensors = sensors.filter(([, sensor]) => sensor.entity_id).length;
    const armedEquipment = equipment.filter(([, item]) => item.armed).length;
    const mappedEnergy = this._energyTotalMappings().filter(([, energyKey]) => this._config.energy[energyKey]).length;
    const noEnabledSensors = !sensors.length;
    const health = this._reefHealthScore(sensors, equipment, sensorAlerts, interlocks);
    const status = sensorSummary.criticalCount || armedUnavailable.length ? "Action needed" : sensorSummary.warningCount || sensorSummary.contextCount || missing.length || noEnabledSensors || interlocks.length ? "Watch closely" : "All systems nominal";
    const cards = this._missionCards();
    const dosing = this._dosingEnabled() ? this._dosingMissionState() : null;
    const summaryCards = [
      cards.health ? this._missionSummaryCard("Reef Health", `${health.score}/100`, `${health.gradeDetail || `${health.grade} grade`} · ${health.topReason}`, health.status, "mission") : "",
      cards.dosing && dosing ? this._missionSummaryCard("Dosing Advisor", dosing.value, dosing.detail, dosing.status, "mission") : "",
      cards.live ? this._missionSummaryCard("Sensors", `${mappedSensors}/${sensors.length}`, sensorSummary.detail, sensorSummary.status, "live") : "",
      cards.controls ? this._missionSummaryCard("Equipment", `${armedEquipment}/${equipment.length}`, equipment.length ? "armed devices" : "none mapped", armedUnavailable.length ? "critical" : armedEquipment ? "ok" : "unknown", "controls") : "",
      cards.energy ? this._missionSummaryCard("Energy", `${mappedEnergy}/3`, "daily, weekly, monthly totals", mappedEnergy ? "ok" : "unknown", "energy") : "",
    ].join("");

    return `
      <section class="stack">
        <div class="hero ${sensorSummary.criticalCount || armedUnavailable.length ? "danger-border" : sensorSummary.warningCount || sensorSummary.contextCount || missing.length || noEnabledSensors || interlocks.length ? "warning-border" : "ok-border"}">
          <div>
            <p class="eyebrow">Mission Control</p>
            <h2>${status}</h2>
            <p>${sensorSummary.criticalCount} critical alert(s), ${sensorSummary.warningCount} warning(s), ${sensorSummary.contextCount} context warning(s), ${interlocks.length} interlock warning(s), ${missing.length} missing mapping(s), ${armedUnavailable.length} armed device issue(s).</p>
          </div>
          <div class="actions">
            <button class="secondary" data-action="onboarding-start" title="Take the guided tour">👋 Tour</button>
            <button class="secondary" data-action="validate">Refresh checks</button>
            <button class="primary" data-action="tab" data-id="settings" data-tour="settings">Open settings</button>
          </div>
        </div>
        ${this._modePanel()}
        ${summaryCards ? `<div class="summary-grid">${summaryCards}</div>` : ""}
        ${cards.health ? this._reefHealthBreakdown(health) : ""}
        ${cards.dosing ? this._dosingBreakdown() : ""}
        <article class="panel" data-tour="attention">
          <div class="section-head">
            <h3>Attention</h3>
            <p>Only configured OpenReef entities are checked here.</p>
          </div>
          ${this._missionIssueList(sensors, equipment, sensorAlerts, missing, armedUnavailable, interlocks)}
        </article>
        ${this._activityPanel()}
        <div class="grid two">
          ${cards.live ? `<article class="panel" data-tour="sensors">
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

  _reefHealthInsightGroup(key, title, group, emptyText, summary) {
    const items = group || [];
    const hasUrgentScoreItem = ["action", "watch"].includes(key) && items.some((item) => item.affectsScore);
    const open = this._healthSectionOpen(key) || hasUrgentScoreItem;
    const scoreItems = items.filter((item) => item.affectsScore).length;
    const countLabel = items.length ? `${items.length} item${items.length === 1 ? "" : "s"}` : "Clear";
    return `
      <section class="health-insight-group ${open ? "open" : "collapsed"}">
        <button class="health-insight-head" data-action="toggle-health-section" data-section="${this._escape(key)}" aria-expanded="${open ? "true" : "false"}">
          <span>
            <strong>${this._escape(title)}</strong>
            <small>${this._escape(summary || emptyText)}</small>
          </span>
          <span class="pill ${scoreItems ? "warning" : items.length ? "unknown" : "ok"}">${this._escape(open ? "Hide" : countLabel)}</span>
        </button>
        ${open ? `
          <div class="health-insight-body">
            ${items.length ? items.slice(0, 6).map((item) => `
              <div class="health-insight-row ${this._escape(item.status)}">
                <div>
                  <strong>${this._escape(item.label)}</strong>
                  <small>${this._escape(item.detail || "")}</small>
                </div>
                <span class="pill ${item.affectsScore ? item.status : "unknown"}">${item.affectsScore ? (item.points ? `-${this._escape(item.points)}` : `cap ${this._escape(item.cap || "")}`) : "info"}</span>
              </div>
            `).join("") : `<p class="muted">${this._escape(emptyText)}</p>`}
          </div>
        ` : ""}
      </section>
    `;
  }

  _reefHealthBreakdown(health) {
    const categories = this._healthCategoryChoices().map(([id]) => health.categories[id]).filter(Boolean);
    const groups = health.groups || {};
    const detailsOpen = this._healthSectionOpen("details");
    return `
      <article class="panel health-breakdown ${this._escape(health.status)}" data-tour="reef-health">
        <div class="section-head">
          <div>
            <p class="eyebrow">Why this score?</p>
            <h3>${this._escape(health.profileLabel)} · ${this._escape(health.score)}/100</h3>
            <p class="muted">${this._escape(health.gradeDetail || `${health.grade} grade`)} · ${this._escape(health.topReason)}. ${this._escape(health.nextAction)}</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${this._escape(health.status)}">${this._escape(health.grade)} grade</span>
            ${health.learningCount ? `<span class="pill unknown">${this._escape(health.learningCount)} learning</span>` : ""}
            <span class="pill ${health.appliedCap ? "warning" : "unknown"}">${health.appliedCap ? `cap ${this._escape(health.appliedCap.limit)}` : "no cap"}</span>
            <button class="secondary compact-button" data-action="validate">Refresh health</button>
            <button class="secondary compact-button" data-action="toggle-health-section" data-section="details">${detailsOpen ? "Hide details" : "Show details"}</button>
          </div>
        </div>
        ${detailsOpen ? `
          <div class="health-category-grid">
            ${categories.map((category) => `
              <article class="health-category ${category.score >= 90 ? "ok" : category.score >= 70 ? "warning" : "critical"}">
                <span>${this._escape(category.label)}</span>
                <strong>${this._escape(category.score)}/100</strong>
                <small>${this._escape(Math.round(category.weight * 100))}% weight · ${this._escape(category.lost)} lost</small>
              </article>
            `).join("")}
          </div>
          <div class="health-reason-grid">
            <section class="health-reason-card">
              <span>Top reason</span>
              <strong>${this._escape(health.topReason)}</strong>
              <p>${this._escape(health.nextAction)}</p>
            </section>
            <section class="health-reason-card">
              <span>Trend data</span>
              <strong>${this._escape(health.trendFreshness)}</strong>
              <p>Trends are checked only when you press Check/Refresh health, using configured numeric sensors only.</p>
            </section>
            <section class="health-reason-card">
              <span>${this._escape(health.profileLabel)} scoring</span>
              <strong>Profile preset</strong>
              <p>${this._escape(health.profileNote || this._tankProfileHealthNote(health.profile))}</p>
            </section>
          </div>
          ${health.appliedCap ? `<div class="notice ${health.appliedCap.status === "critical" ? "danger-notice" : "warning-notice"}"><strong>Hard cap applied:</strong> ${this._escape(health.appliedCap.label)}. ${this._escape(health.appliedCap.detail)}</div>` : ""}
          <div class="health-insight-grid">
            ${this._reefHealthInsightGroup("action", "Needs action", groups.action, "No urgent Reef Health actions.", "Score-affecting safety issues appear here.")}
            ${this._reefHealthInsightGroup("watch", "Worth watching", groups.watch, "No scoring warnings right now.", "Gentle warnings that may affect the score.")}
            ${this._reefHealthInsightGroup("context", "Context", groups.context, "No extra context from optional readings.", "Informational notes; not scored unless linked to a real tank issue.")}
            ${this._reefHealthInsightGroup("learning", "Learning", groups.learning, "Trend learning is up to date.", "OpenReef is building a normal baseline for this tank.")}
          </div>
        ` : ""}
      </article>
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

    sensorAlerts.forEach((alert) => {
      const impact = this._sensorAlertImpact(alert.id, alert.sensor, alert.status);
      if (alert.status === "unknown") {
        issues.push(["warning", alert.title, alert.detail, "settings"]);
        return;
      }
      if (!impact.affectsScore) {
        issues.push(["warning", `${alert.title} (context)`, `${alert.detail} · context only`, "live"]);
        return;
      }
      issues.push([alert.status === "critical" ? "critical" : "warning", alert.title, alert.detail, "live"]);
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
    const display = this._sensorDisplayValue(id, sensor);
    const unit = this._sensorDisplayUnit(id, sensor);
    return `
      <div class="row">
        <div>
          <strong>${this._escape(sensor.label)}</strong>
          <span>${this._escape(sensor.entity_id || "Not mapped")}</span>
        </div>
        <div class="pill ${status}">${this._escape(display)} ${this._escape(unit)}</div>
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
            const display = this._sensorDisplayValue(id, sensor);
            const unit = this._sensorDisplayUnit(id, sensor);
            const trendEnabled = this._sensorKind(sensor, id) !== "binary" && Boolean(sensor.entity_id);
            const content = `
                <p>${this._escape(sensor.label)}</p>
                <strong>${this._escape(display)}</strong>
                <span>${this._escape(unit)}</span>
                <small>${this._escape(sensor.entity_id || "Not mapped")}</small>
                <span class="trend-hint">${trendEnabled ? "Trend" : "State"}</span>
            `;
            return trendEnabled ? `
              <button class="stat stat-button ${this._sensorGroupClass(sensor)}" data-action="show-trend" data-id="${this._escape(id)}" aria-label="Open ${this._escape(sensor.label)} trend">
                ${content}
              </button>
            ` : `
              <article class="stat ${this._sensorGroupClass(sensor)} no-trend">
                ${content}
              </article>
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
    const enabled = this._controlAvailable(id, item);
    const stateClass = this._equipmentStateClass(item);
    const stateLabel = this._equipmentStateLabel(item);
    const [risk, riskLabel, riskDetail] = this._equipmentRisk(id, item);
    const reason = this._controlBlockReason(item, id);
    const safetyStatus = this._equipmentSafetyStatus(id, item);
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
        ${safetyStatus ? `<div class="notice compact-notice ${safetyStatus[0] === "critical" ? "danger-notice" : safetyStatus[0] === "warning" ? "warning-notice" : ""}"><strong>${this._escape(safetyStatus[1])}.</strong> ${this._escape(safetyStatus[2])}</div>` : ""}
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
    const enabled = this._controlAvailable(id, item);
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
              <strong>${this._escape(this._controlBlockReason(item, id))}</strong>
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

  // --- Manual Tests -------------------------------------------------------

  _manualTestParameterIds() {
    return ["alkalinity", "calcium", "magnesium", "nitrate", "phosphate", "salinity", "ph", "temp"];
  }

  _manualTestSourceChoices() {
    return ["", "Hanna", "Salifert", "Red Sea", "Nyos", "API", "ICP", "Apex", "Trident", "Trident NP", "Other"];
  }

  _manualTestMeta(id) {
    const sensor = this._config?.sensors?.[id] || {};
    const fallback = {
      alkalinity: ["Alkalinity", "dKH", 7, 11],
      calcium: ["Calcium", "ppm", 380, 460],
      magnesium: ["Magnesium", "ppm", 1250, 1450],
      nitrate: ["Nitrate", "ppm", 0.5, 20],
      phosphate: ["Phosphate", "ppm", 0.02, 0.12],
      salinity: ["Salinity", "ppt", 32, 36],
      ph: ["pH Level", "", 7.8, 8.4],
      temp: ["Display Tank Temperature", "°C", 24.5, 27.5],
    }[id] || [id, "", 0, 0];
    return {
      id,
      label: sensor.label || fallback[0],
      unit: sensor.unit ?? fallback[1],
      min: Number.isFinite(Number(sensor.min)) ? Number(sensor.min) : fallback[2],
      max: Number.isFinite(Number(sensor.max)) ? Number(sensor.max) : fallback[3],
    };
  }

  _manualTestsConfig() {
    this._config.manualTests = this._config.manualTests || { enabled: true, schedules: {} };
    this._config.manualTests.schedules = this._config.manualTests.schedules || {};
    return this._config.manualTests;
  }

  _manualTestConfig(id) {
    const config = this._manualTestsConfig();
    const schedules = config.schedules;
    const suggested = this._manualSuggestedCadenceDays(id);
    schedules[id] = schedules[id] || { enabled: false, cadenceDays: suggested, criticalAfterDays: suggested * 2, preferredSource: "" };
    const cadenceDays = Math.max(1, Math.min(365, Number(schedules[id].cadenceDays) || suggested));
    const criticalAfterDays = Math.max(cadenceDays, Math.min(730, Number(schedules[id].criticalAfterDays) || cadenceDays * 2));
    return {
      enabled: schedules[id].enabled === true,
      cadenceDays,
      criticalAfterDays,
      preferredSource: schedules[id].preferredSource || "",
    };
  }

  _manualSuggestedCadenceDays(id, profile = this._tankProfile()) {
    const presets = {
      fish_only_fowlr: { alkalinity: 30, calcium: 30, magnesium: 60, nitrate: 14, phosphate: 30, salinity: 14, ph: 30, temp: 7 },
      soft_coral: { alkalinity: 7, calcium: 21, magnesium: 30, nitrate: 14, phosphate: 14, salinity: 7, ph: 30, temp: 7 },
      lps: { alkalinity: 7, calcium: 14, magnesium: 30, nitrate: 7, phosphate: 7, salinity: 7, ph: 21, temp: 7 },
      sps: { alkalinity: 3, calcium: 7, magnesium: 14, nitrate: 7, phosphate: 7, salinity: 7, ph: 14, temp: 7 },
      mixed_reef: { alkalinity: 4, calcium: 14, magnesium: 21, nitrate: 7, phosphate: 7, salinity: 7, ph: 21, temp: 7 },
      anemone_dominant: { alkalinity: 14, calcium: 21, magnesium: 30, nitrate: 7, phosphate: 7, salinity: 7, ph: 14, temp: 7 },
    };
    return presets[profile]?.[id] || presets.mixed_reef[id] || 14;
  }

  _manualSuggestedEnabled(id) {
    if (["alkalinity", "calcium", "magnesium", "nitrate", "phosphate", "salinity"].includes(id)) return true;
    return ["sps", "mixed_reef", "anemone_dominant"].includes(this._tankProfile()) && ["ph", "temp"].includes(id);
  }

  _applyManualSchedulePreset() {
    const config = this._manualTestsConfig();
    config.enabled = true;
    this._manualTestParameterIds().forEach((id) => {
      config.schedules[id] = {
        ...(config.schedules[id] || {}),
        enabled: this._manualSuggestedEnabled(id),
        cadenceDays: this._manualSuggestedCadenceDays(id),
        criticalAfterDays: this._manualSuggestedCadenceDays(id) * 2,
      };
    });
    this._recordActivity(`Manual testing routine suggested for ${this._tankProfileLabel(this._tankProfile())}`);
  }

  _manualReadings(id) {
    const readings = this._config?.manualReadings?.[id];
    if (!Array.isArray(readings)) return [];
    return [...readings]
      .filter((entry) => Number.isFinite(Number(entry?.value)))
      .sort((a, b) => this._manualReadingTime(b) - this._manualReadingTime(a));
  }

  _manualReadingTime(entry) {
    const time = Date.parse(entry?.timestamp || entry?.date || "");
    return Number.isFinite(time) ? time : 0;
  }

  _manualLatestReading(id) {
    return this._manualReadings(id)[0] || null;
  }

  _manualAgeDays(entry) {
    const time = this._manualReadingTime(entry);
    if (!time) return Number.POSITIVE_INFINITY;
    return Math.max(0, (Date.now() - time) / 86400000);
  }

  _manualDueState(id) {
    const meta = this._manualTestMeta(id);
    const schedule = this._manualTestConfig(id);
    const latest = this._manualLatestReading(id);
    if (!this._manualTestsConfig().enabled || !schedule.enabled) {
      return { status: "unknown", label: "not tracked", detail: "Freshness reminders are off for this test.", latest };
    }
    if (!latest) {
      return { status: "warning", label: "not logged", detail: `${meta.label} is on a ${schedule.cadenceDays}-day schedule but has no manual entry yet. Critical after ${schedule.criticalAfterDays} days.`, latest };
    }
    const age = this._manualAgeDays(latest);
    if (age > schedule.criticalAfterDays) {
      return { status: "critical", label: "overdue", detail: `${meta.label} was last logged ${this._format(age, 0)} days ago; critical threshold is ${schedule.criticalAfterDays} days.`, latest };
    }
    if (age > schedule.cadenceDays) {
      return { status: "warning", label: "due", detail: `${meta.label} is due. Last logged ${this._format(age, 0)} days ago; target cadence is every ${schedule.cadenceDays} days. Critical after ${schedule.criticalAfterDays} days.`, latest };
    }
    return { status: "ok", label: "fresh", detail: `${meta.label} logged ${this._format(age, age < 2 ? 1 : 0)} days ago; target cadence is every ${schedule.cadenceDays} days. Critical after ${schedule.criticalAfterDays} days.`, latest };
  }

  _manualTestFreshnessItems() {
    if (!this._manualTestsConfig().enabled) return [];
    return this._manualTestParameterIds()
      .filter((id) => this._manualTestConfig(id).enabled)
      .map((id) => {
        const meta = this._manualTestMeta(id);
        const state = this._manualDueState(id);
        const category = ["alkalinity", "calcium", "magnesium", "nitrate", "phosphate", "salinity", "ph"].includes(id) ? "chemistry" : "confidence";
        const points = state.status === "critical" ? 10 : state.status === "warning" ? 4 : 0;
        return {
          id,
          label: `${meta.label} manual test ${state.label}`,
          detail: state.detail,
          status: state.status,
          category,
          points,
          affectsScore: points > 0,
        };
      });
  }

  _manualTrendData(id) {
    const points = this._manualReadings(id)
      .map((entry) => ({ time: this._manualReadingTime(entry), value: Number(entry.value) }))
      .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
      .sort((a, b) => a.time - b.time);
    return { points, range: points.length >= 4 ? "7d" : "manual", source: "manual" };
  }

  _manualTrendPoints(id, range = "all") {
    const points = this._manualTrendData(id).points;
    if (range === "all" || !Number.isFinite(this._trendRangeMs(range))) return points;
    const cutoff = Date.now() - this._trendRangeMs(range);
    return points.filter((point) => point.time >= cutoff);
  }

  _manualTrendSummary(id) {
    const readings = this._manualReadings(id);
    if (readings.length < 2) return "Add two or more results to show a manual trend.";
    const latest = readings[0];
    const previous = readings[1];
    const meta = this._manualTestMeta(id);
    const delta = Number(latest.value) - Number(previous.value);
    const direction = delta > 0 ? "up" : delta < 0 ? "down" : "steady";
    return `${direction} ${this._format(Math.abs(delta), this._sensorDigits(id))}${meta.unit ? ` ${meta.unit}` : ""} since last test.`;
  }

  _nowLocalInputValue() {
    const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
    return date.toISOString().slice(0, 16);
  }

  _manualEntryTimestampValue() {
    return this._manualEntryDefaults.timestamp || this._nowLocalInputValue();
  }

  _manualParameterAlias(value) {
    const key = this._slug(String(value || "").replaceAll("/", " "));
    const aliases = {
      alk: "alkalinity",
      alkalinity: "alkalinity",
      dkh: "alkalinity",
      kh: "alkalinity",
      ca: "calcium",
      calcium: "calcium",
      mg: "magnesium",
      magnesium: "magnesium",
      no3: "nitrate",
      nitrate: "nitrate",
      po4: "phosphate",
      phosphate: "phosphate",
      salinity: "salinity",
      sal: "salinity",
      ppt: "salinity",
      sg: "salinity",
      ph: "ph",
      ph_level: "ph",
      temp: "temp",
      temperature: "temp",
      display_tank_temperature: "temp",
    };
    return aliases[key] || (this._manualTestParameterIds().includes(key) ? key : "");
  }

  _csvCell(value) {
    const text = String(value ?? "");
    if (/[",\n\r]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
    return text;
  }

  _parseCsvLine(line) {
    const cells = [];
    let current = "";
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      if (char === '"') {
        if (quoted && line[index + 1] === '"') {
          current += '"';
          index += 1;
        } else {
          quoted = !quoted;
        }
      } else if (char === "," && !quoted) {
        cells.push(current);
        current = "";
      } else {
        current += char;
      }
    }
    cells.push(current);
    return cells.map((cell) => cell.trim());
  }

  _manualCsvRows() {
    return this._manualTestParameterIds()
      .flatMap((parameter) => this._manualReadings(parameter).map((entry) => {
        const meta = this._manualTestMeta(parameter);
        return {
          parameter,
          label: meta.label,
          timestamp: entry.timestamp || "",
          value: Number(entry.value),
          unit: entry.unit || meta.unit || "",
          source: entry.source || "",
          notes: entry.notes || "",
        };
      }))
      .sort((a, b) => Date.parse(a.timestamp || "") - Date.parse(b.timestamp || ""));
  }

  _manualCsvText() {
    const header = ["parameter", "label", "timestamp", "value", "unit", "source", "notes"];
    const rows = this._manualCsvRows().map((row) => [
      row.parameter,
      row.label,
      row.timestamp,
      Number.isFinite(row.value) ? row.value : "",
      row.unit,
      row.source,
      row.notes,
    ]);
    return [header, ...rows].map((row) => row.map((cell) => this._csvCell(cell)).join(",")).join("\n");
  }

  _manualCsvTemplateText() {
    return [
      "parameter,timestamp,value,unit,source,notes",
      "alkalinity,2026-05-30T19:30,8.1,dKH,Hanna,evening test",
      "calcium,2026-05-30T19:30,430,ppm,Salifert,evening test",
      "magnesium,2026-05-30T19:30,1350,ppm,Salifert,evening test",
      "nitrate,2026-05-30T19:30,8,ppm,Hanna,evening test",
      "phosphate,2026-05-30T19:30,0.06,ppm,Hanna,evening test",
    ].join("\n");
  }

  async _copyManualCsv() {
    await this._copyText(this._manualCsvText(), "Manual test CSV copied", "Could not copy manual test CSV");
  }

  _downloadManualCsv() {
    try {
      const blob = new Blob([this._manualCsvText()], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `openreef-manual-tests-${new Date().toISOString().slice(0, 10)}.csv`;
      this.shadowRoot.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      this._message = "Manual test CSV downloaded";
      this._error = "";
    } catch {
      this._error = "Could not download manual test CSV";
      this._message = "";
    }
    this._render();
  }

  async _copyManualTemplate() {
    await this._copyText(this._manualCsvTemplateText(), "Manual import template copied", "Could not copy manual import template");
  }

  _parseManualCsv(text) {
    const lines = String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!lines.length) return { rows: [], errors: ["Paste CSV rows before importing."] };
    if (lines.length > 501) return { rows: [], errors: ["Import up to 500 manual test rows at a time."] };
    let header = ["parameter", "timestamp", "value", "unit", "source", "notes"];
    let start = 0;
    const first = this._parseCsvLine(lines[0]).map((cell) => this._slug(cell));
    if (first.includes("parameter") && first.includes("value")) {
      header = first.map((cell) => cell === "date" ? "timestamp" : cell);
      start = 1;
    }
    const rows = [];
    const errors = [];
    lines.slice(start).forEach((line, rowIndex) => {
      const cells = this._parseCsvLine(line);
      const raw = {};
      header.forEach((column, index) => {
        raw[column] = cells[index] ?? "";
      });
      const parameter = this._manualParameterAlias(raw.parameter || raw.test || raw.label);
      if (!parameter) {
        errors.push(`Row ${rowIndex + start + 1}: unknown parameter.`);
        return;
      }
      const value = Number(String(raw.value || "").replace(",", "."));
      if (!Number.isFinite(value)) {
        errors.push(`Row ${rowIndex + start + 1}: value must be numeric.`);
        return;
      }
      const timestampText = raw.timestamp || raw.time || raw.date || "";
      const timestampMs = Date.parse(timestampText.includes("T") || timestampText.includes(":") ? timestampText : `${timestampText}T12:00:00`);
      if (!Number.isFinite(timestampMs)) {
        errors.push(`Row ${rowIndex + start + 1}: timestamp/date is invalid.`);
        return;
      }
      const meta = this._manualTestMeta(parameter);
      rows.push({
        parameter,
        timestamp: new Date(timestampMs).toISOString(),
        value,
        unit: raw.unit || meta.unit || "",
        source: raw.source || raw.kit || "",
        notes: raw.notes || raw.note || "",
      });
    });
    return { rows, errors };
  }

  _importManualCsvFromForm() {
    const text = this.shadowRoot.querySelector("[data-manual-import-field='text']")?.value || this._manualEntryDefaults.importText || "";
    const parsed = this._parseManualCsv(text);
    if (parsed.errors.length) {
      this._error = parsed.errors.slice(0, 4).join(" ");
      this._message = "";
      this._render();
      return;
    }
    if (!parsed.rows.length) {
      this._error = "No manual test rows found to import.";
      this._message = "";
      this._render();
      return;
    }
    this._config.manualReadings = this._config.manualReadings || {};
    parsed.rows.forEach((row, index) => {
      this._config.manualReadings[row.parameter] = this._manualReadings(row.parameter);
      this._config.manualReadings[row.parameter].push({
        id: `${row.parameter}:import:${Date.now()}:${index}`,
        timestamp: row.timestamp,
        value: row.value,
        unit: row.unit,
        source: row.source,
        notes: row.notes,
      });
    });
    this._manualEntryDefaults.importText = "";
    this._recordActivity(`Manual CSV imported: ${parsed.rows.length} result${parsed.rows.length === 1 ? "" : "s"}`, "control");
    this._saveConfig();
  }

  _saveManualReadingFromForm() {
    const field = (name) => this.shadowRoot.querySelector(`[data-manual-field="${name}"]`);
    const parameter = field("parameter")?.value || "alkalinity";
    const meta = this._manualTestMeta(parameter);
    const value = Number(field("value")?.value);
    if (!Number.isFinite(value)) {
      this._error = "Enter a numeric manual test value.";
      this._message = "";
      this._render();
      return;
    }
    const localTime = field("timestamp")?.value;
    const timestamp = localTime ? new Date(localTime).toISOString() : new Date().toISOString();
    const unit = field("unit")?.value || meta.unit || "";
    const source = field("source")?.value || "";
    const notes = field("notes")?.value || "";
    this._config.manualReadings = this._config.manualReadings || {};
    this._config.manualReadings[parameter] = this._manualReadings(parameter);
    this._config.manualReadings[parameter].push({
      id: `${parameter}:${Date.now()}`,
      timestamp,
      value,
      unit,
      source,
      notes,
    });
    this._recordActivity(`Manual ${meta.label} test recorded: ${this._format(value, this._sensorDigits(parameter))}${unit ? ` ${unit}` : ""}`, "control");
    this._saveConfig();
  }

  _saveManualBatchFromForm() {
    const field = (name) => this.shadowRoot.querySelector(`[data-manual-batch-field="${name}"]`);
    const localTime = field("timestamp")?.value || this._nowLocalInputValue();
    const parsedTime = Date.parse(localTime);
    if (!Number.isFinite(parsedTime)) {
      this._error = "Choose a valid date/time for this manual test session.";
      this._message = "";
      this._render();
      return;
    }
    const timestamp = new Date(localTime).toISOString();
    const notes = field("notes")?.value || "";
    const rows = [...this.shadowRoot.querySelectorAll("[data-manual-batch-value]")]
      .map((input) => {
        const parameter = input.dataset.manualBatchValue;
        const raw = String(input.value || "").trim();
        if (!raw) return null;
        const value = Number(raw);
        if (!Number.isFinite(value)) {
          return { parameter, error: true };
        }
        const source = this.shadowRoot.querySelector(`[data-manual-batch-source="${parameter}"]`)?.value || "";
        return { parameter, value, source };
      })
      .filter(Boolean);

    if (rows.some((row) => row.error)) {
      this._error = "Every manual test value must be numeric.";
      this._message = "";
      this._render();
      return;
    }
    if (!rows.length) {
      this._error = "Enter at least one manual test result.";
      this._message = "";
      this._render();
      return;
    }

    const sources = {};
    [...this.shadowRoot.querySelectorAll("[data-manual-batch-source]")].forEach((select) => {
      sources[select.dataset.manualBatchSource] = select.value || "";
    });
    this._manualEntryDefaults = { timestamp: localTime, sources, notes };
    this._config.manualReadings = this._config.manualReadings || {};
    rows.forEach((row, index) => {
      const meta = this._manualTestMeta(row.parameter);
      this._config.manualReadings[row.parameter] = this._manualReadings(row.parameter);
      this._config.manualReadings[row.parameter].push({
        id: `${row.parameter}:${Date.now()}:${index}`,
        timestamp,
        value: row.value,
        unit: meta.unit || "",
        source: row.source,
        notes,
      });
    });
    this._recordActivity(`Manual test session recorded: ${rows.length} result${rows.length === 1 ? "" : "s"}`, "control");
    this._saveConfig();
  }

  _deleteManualReading(parameter, readingId) {
    const readings = this._config.manualReadings?.[parameter];
    if (!Array.isArray(readings)) return;
    this._config.manualReadings[parameter] = readings.filter((entry) => entry.id !== readingId);
    this._recordActivity(`Manual ${this._manualTestMeta(parameter).label} test deleted`, "warning");
    this._saveConfig();
  }

  _manualTests() {
    const tracked = this._manualTestParameterIds().filter((id) => this._manualTestConfig(id).enabled);
    const due = this._manualTestFreshnessItems().filter((item) => item.status === "warning" || item.status === "critical");
    return `
      <section class="stack">
        <div class="section-head">
          <div>
            <h2>Manual Tests</h2>
            <p>Log test-kit results and let OpenReef keep you consistent with your own routine.</p>
          </div>
          <div class="button-row">
            <button class="secondary" data-action="apply-manual-schedule-preset">Use ${this._escape(this._tankProfileLabel(this._tankProfile()))} routine</button>
            <button class="primary" data-action="tab" data-id="settings">Edit schedule</button>
          </div>
        </div>
        <div class="summary-grid">
          ${this._missionSummaryCard("Tracked tests", `${tracked.length}/${this._manualTestParameterIds().length}`, "user-selected cadence", tracked.length ? "ok" : "unknown", "settings")}
          ${this._missionSummaryCard("Due now", `${due.length}`, due.length ? "review manual testing" : "routine is current", due.some((item) => item.status === "critical") ? "critical" : due.length ? "warning" : "ok", "manual")}
          ${this._missionSummaryCard("Dosing insight", `${this._dosingActiveParameters().length}`, "mapped sensors or manual history", this._dosingActiveParameters().length ? "ok" : "unknown", "mission")}
        </div>
        ${this._manualEntryPanel()}
        ${this._manualDataToolsPanel()}
        <div class="grid four">
          ${this._manualTestParameterIds().map((id) => this._manualTestCard(id)).join("")}
        </div>
      </section>
    `;
  }

  _manualEntryPanel() {
    const tracked = this._manualTestParameterIds().filter((id) => this._manualTestConfig(id).enabled);
    const orderedIds = [
      ...tracked,
      ...this._manualTestParameterIds().filter((id) => !tracked.includes(id)),
    ];
    return `
      <article class="panel manual-entry-panel">
        <div class="section-head">
          <div>
            <h3>Record a manual test session</h3>
            <p>Use one date for a full round of results. Pick the kit/source per result, because most reefers mix Hanna, Salifert, ICP, and other tests.</p>
          </div>
          <button class="secondary compact-button" data-action="manual-entry-now">Use now</button>
        </div>
        <div class="manual-session-grid">
          <label>Date/time<input type="datetime-local" data-manual-batch-field="timestamp" value="${this._escape(this._manualEntryTimestampValue())}"></label>
          <label class="manual-notes">Session notes<textarea data-manual-batch-field="notes" rows="2" placeholder="Optional note, e.g. before water change">${this._escape(this._manualEntryDefaults.notes || "")}</textarea></label>
        </div>
        <div class="manual-batch-grid">
          ${orderedIds.map((id) => {
            const meta = this._manualTestMeta(id);
            const schedule = this._manualTestConfig(id);
            const rowSource = this._manualEntryDefaults.sources?.[id] ?? schedule.preferredSource ?? this._manualEntryDefaults.source ?? "";
            return `
              <div class="manual-batch-row ${schedule.enabled ? "tracked" : ""}">
                <span>
                  <strong>${this._escape(meta.label)}</strong>
                  <small>${this._escape(meta.unit || "unitless")}${schedule.enabled ? " · tracked" : " · optional"}</small>
                </span>
                <input type="number" step="0.001" data-manual-batch-value="${this._escape(id)}" placeholder="${this._escape(meta.min && meta.max ? `${meta.min} - ${meta.max}` : "0.00")}" aria-label="${this._escape(meta.label)} value">
                <select data-manual-batch-source="${this._escape(id)}" aria-label="${this._escape(meta.label)} source">
                  ${this._manualTestSourceChoices().map((source) => `<option value="${this._escape(source)}" ${source === rowSource ? "selected" : ""}>${this._escape(source || "Source")}</option>`).join("")}
                </select>
              </div>
            `;
          }).join("")}
        </div>
        <div class="button-row end">
          <button class="primary" data-action="save-manual-batch">Save test session</button>
        </div>
      </article>
    `;
  }

  _manualDataToolsPanel() {
    const count = this._manualCsvRows().length;
    return `
      <article class="panel manual-data-tools">
        <div class="section-head">
          <div>
            <h3>Import and export history</h3>
            <p>Bring in old test-kit results or export the OpenReef chemistry log as CSV.</p>
          </div>
          <div class="button-row">
            <button class="secondary compact-button" data-action="copy-manual-template">Copy template</button>
            <button class="secondary compact-button" data-action="copy-manual-csv" ${count ? "" : "disabled"}>Copy CSV</button>
            <button class="secondary compact-button" data-action="download-manual-csv" ${count ? "" : "disabled"}>Download CSV</button>
          </div>
        </div>
        <label>Paste CSV history
          <textarea data-manual-import-field="text" rows="5" placeholder="parameter,timestamp,value,unit,source,notes&#10;alkalinity,2026-05-30T19:30,8.1,dKH,Hanna,evening test">${this._escape(this._manualEntryDefaults.importText || "")}</textarea>
        </label>
        <div class="button-row end">
          <small>${this._escape(count)} saved result${count === 1 ? "" : "s"}. Supported names include alkalinity/alk/dKH, calcium/Ca, magnesium/Mg, nitrate/NO3, phosphate/PO4, salinity, pH, and temp.</small>
          <button class="primary" data-action="import-manual-csv">Import CSV</button>
        </div>
      </article>
    `;
  }

  _manualTestCard(id) {
    const meta = this._manualTestMeta(id);
    const schedule = this._manualTestConfig(id);
    const state = this._manualDueState(id);
    const latest = state.latest;
    const readings = this._manualReadings(id);
    const open = this._manualHistoryOpen[id] === true;
    const value = latest ? `${this._format(Number(latest.value), this._sensorDigits(id))}${latest.unit ? ` ${latest.unit}` : meta.unit ? ` ${meta.unit}` : ""}` : "--";
    return `
      <article class="manual-test-card ${state.status}">
        <div class="card-head">
          <div>
            <h3>${this._escape(meta.label)}</h3>
            <p>${schedule.enabled ? `Every ${this._escape(schedule.cadenceDays)} day${schedule.cadenceDays === 1 ? "" : "s"}` : "Schedule off"}</p>
          </div>
          <span class="pill ${state.status}">${this._escape(state.label)}</span>
        </div>
        <strong>${this._escape(value)}</strong>
        <small>${this._escape(latest ? this._formatActivityTime(latest.timestamp) : "No manual result yet")}</small>
        <p>${this._escape(state.detail)}</p>
        <p class="hint">${this._escape(this._manualTrendSummary(id))}</p>
        <div class="button-row">
          <button class="secondary compact-button" data-action="show-manual-trend" data-id="${this._escape(id)}" ${readings.length < 2 ? "disabled" : ""}>Trend</button>
          <button class="secondary compact-button" data-action="toggle-manual-history" data-id="${this._escape(id)}">${open ? "Hide history" : `Show history (${readings.length})`}</button>
        </div>
        ${open ? `
          <div class="manual-history">
            ${readings.length ? readings.slice(0, 12).map((entry) => `
              <div class="manual-history-row">
                <div>
                  <strong>${this._escape(this._format(Number(entry.value), this._sensorDigits(id)))}${entry.unit ? ` ${this._escape(entry.unit)}` : ""}</strong>
                  <small>${this._escape(this._formatActivityTime(entry.timestamp))}${entry.source ? ` · ${this._escape(entry.source)}` : ""}</small>
                  ${entry.notes ? `<small>${this._escape(entry.notes)}</small>` : ""}
                </div>
                <button class="danger-text compact-button" data-action="delete-manual-reading" data-id="${this._escape(id)}" data-reading="${this._escape(entry.id)}">Delete</button>
              </div>
            `).join("") : `<p class="muted">No history yet.</p>`}
          </div>
        ` : ""}
      </article>
    `;
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

  _settingsPanel(id, title, description, content, forceOpen = false) {
    const open = forceOpen || this._settingsSectionOpen(id);
    return `
      <article class="panel settings-section themed-settings-card">
        <button class="settings-section-head ${forceOpen ? "static-section-head" : ""}" ${forceOpen ? "disabled" : `data-action="toggle-settings-section" data-id="${this._escape(id)}"`}>
          <span>
            <strong>${this._escape(title)}</strong>
            <small>${this._escape(description)}</small>
          </span>
          <span class="pill">${forceOpen ? "Setup" : open ? "Hide" : "Show"}</span>
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
          <div class="settings-toolbar">
            <button class="secondary compact-button" data-action="expand-settings">Show all</button>
            <button class="secondary compact-button" data-action="collapse-settings">Hide all</button>
            ${this._saveControls()}
          </div>
        </div>
        ${this._configDirty ? `<div class="notice warning-notice sticky-save-warning"><strong>Unsaved changes.</strong> Save before applying modes or leaving Settings.</div>` : ""}
        ${this._profileSettings()}
        ${this._missionSettings()}
        ${this._sensorSettings()}
        ${this._manualTestSettings()}
        ${this._dosingSettings()}
        ${this._equipmentSettings()}
        ${this._modePreviewSettings()}
        ${this._alertsSettings()}
        ${this._interlockSettings()}
        ${this._energySettings()}
        ${this._systemCheckSettings()}
      </section>
    `;
  }

  _sensorSettings() {
    return this._settingsPanel(
      "sensors",
      "Sensors",
      "Enable only the probes, safety sensors, and room sensors you actually own.",
      `${this._apexImportGuide("settings")}${this._sensorMappingGroups()}`,
    );
  }

  _apexImportGuide(context = "setup") {
    const compact = context === "settings";
    const choices = [
      ["tank", "No Apex / OpenReef sensors", "Use normal Home Assistant reef sensors: display temp, pH, and salinity."],
      ["apex", "Apex controller", "Enable Apex-style temp, sump temp, pH, ORP, and salinity readings."],
      ["trident", "Apex + Trident", "Add alkalinity, calcium, and magnesium for Trident-style chemistry insight."],
      ["trident_np", "Apex + Trident NP", "Add nitrate and phosphate readings from Trident NP."],
      ["apex_trident_np", "Apex + Trident + Trident NP", "Enable the full Trident chemistry set: alkalinity, calcium, magnesium, nitrate, and phosphate."],
      ["apex_fmm", "Apex + FMM", "Add flow, leak, high-water, and low-water safety sensors."],
      ["apex_full", "Apex full ecosystem", "Enable Apex controller, Trident, Trident NP, and FMM-style sensors."],
    ];
    return `
      <article class="apex-guide ${compact ? "compact-guide" : ""}">
        <div>
          <p class="eyebrow">Apex / Trident beta helper</p>
          <h3>Which Neptune data is already in Home Assistant?</h3>
          <p>OpenReef reads Home Assistant entities that already exist. It does not connect directly to Apex hardware yet, so set up the Apex/Trident entities in Home Assistant first, then use one of these guided presets.</p>
        </div>
        <div class="setup-choice-grid">
          ${choices.map(([id, title, description]) => `
            <button class="setup-choice" data-action="setup-sensor-preset" data-id="${this._escape(id)}">
              <strong>${this._escape(title)}</strong>
              <span>${this._escape(description)}</span>
            </button>
          `).join("")}
        </div>
        <div class="notice info-notice">
          <strong>Monitor-only is valid.</strong> Apex users can use OpenReef for Reef Health, trends, chemistry insight, and alerts without arming any OpenReef-controlled switches.
        </div>
      </article>
    `;
  }

  _sensorMappingGroups() {
    const sensors = Object.entries(this._config.sensors || {});
    const groups = [
      ["tank", "Display tank", "Core readings from the main display."],
      ["sump", "Sump / rear chamber", "Readings from the filtration chamber or sump."],
      ["chemistry", "Chemistry", "Apex and Trident style chemistry probes and test values."],
      ["water", "Water safety", "Dissolved oxygen, water level, and other water-condition sensors."],
      ["safety", "Leak and safety", "Binary safety sensors that should normally stay clear or off."],
      ["flow", "Flow", "Return or circulation flow readings from HA sensors."],
      ["lighting", "Lighting", "PAR and other light-measurement sensors."],
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

  _manualTestSettings(forceOpen = false) {
    const manualTests = this._manualTestsConfig();
    return this._settingsPanel(
      "manualTests",
      "Manual Tests",
      "Choose the chemistry routine OpenReef should keep you consistent with.",
      `
        <div class="section-head">
          <div>
            <p class="eyebrow">${this._escape(this._tankProfileLabel(this._tankProfile()))} suggestion</p>
            <h4>Use the preset as a starting point, then change any test cadence to match how you reef.</h4>
          </div>
          <button class="secondary" data-action="apply-manual-schedule-preset">Apply suggested routine</button>
        </div>
        <label class="toggle-card">
          <input type="checkbox" data-scope="manual-tests" data-field="enabled" ${manualTests.enabled === false ? "" : "checked"}>
          <span>
            <strong>Use manual tests in Reef Health</strong>
            <small>Only enabled test schedules affect Chemistry and Confidence. Disabled tests are ignored.</small>
          </span>
        </label>
        <div class="grid four compact">
          ${this._manualTestParameterIds().map((id) => {
            const meta = this._manualTestMeta(id);
            const schedule = this._manualTestConfig(id);
            const due = this._manualDueState(id);
            const suggested = this._manualSuggestedCadenceDays(id);
            return `
              <section class="mapping-card manual-schedule-card ${schedule.enabled ? "manual-enabled" : "disabled-card"}">
                <div class="mapping-head">
                  <div>
                    <p class="eyebrow">${this._escape(meta.unit || "manual")}</p>
                    <h3>${this._escape(meta.label)}</h3>
                  </div>
                  <span class="pill ${due.status}">${this._escape(due.label)}</span>
                </div>
                <label class="toggle-card">
                  <input type="checkbox" data-scope="manual-test" data-id="${this._escape(id)}" data-field="enabled" ${schedule.enabled ? "checked" : ""}>
                  <span>
                    <strong>Track this test</strong>
                    <small>Suggested for ${this._escape(this._tankProfileLabel(this._tankProfile()))}: every ${this._escape(suggested)} day${suggested === 1 ? "" : "s"}.</small>
                  </span>
                </label>
                ${schedule.enabled ? `
                  <div class="mini-grid">
                    <label>Due after days<input type="number" min="1" max="365" step="1" data-scope="manual-test" data-id="${this._escape(id)}" data-field="cadenceDays" value="${this._escape(schedule.cadenceDays)}"></label>
                    <label>Critical after days<input type="number" min="${this._escape(schedule.cadenceDays)}" max="730" step="1" data-scope="manual-test" data-id="${this._escape(id)}" data-field="criticalAfterDays" value="${this._escape(schedule.criticalAfterDays)}"></label>
                    <label>Target low<input type="number" step="0.001" data-scope="sensor" data-id="${this._escape(id)}" data-field="min" value="${this._escape(meta.min)}"></label>
                    <label>Target high<input type="number" step="0.001" data-scope="sensor" data-id="${this._escape(id)}" data-field="max" value="${this._escape(meta.max)}"></label>
                    <label>Preferred source
                      <select data-scope="manual-test" data-id="${this._escape(id)}" data-field="preferredSource">
                        ${this._manualTestSourceChoices().map((source) => `<option value="${this._escape(source)}" ${schedule.preferredSource === source ? "selected" : ""}>${this._escape(source || "No preference")}</option>`).join("")}
                      </select>
                    </label>
                  </div>
                  <p class="hint">${this._escape(due.detail)}</p>
                ` : `<p class="muted">Ignored by Reef Health until you enable it.</p>`}
              </section>
            `;
          }).join("")}
        </div>
      `,
      forceOpen,
    );
  }

  _dosingSettings() {
    const dosing = this._config.dosing || {};
    const enabled = dosing.enabled !== false;
    const active = this._dosingActiveParameters();
    const system = this._dosingSystem();
    const primary = this._dosingProduct(system.primaryProduct);
    const secondary = this._dosingProduct(system.secondaryProduct);
    const selected = primary.id || secondary.id;
    const productNote = selected
      ? [primary.id ? primary.note : "", secondary.id ? secondary.note : ""].filter(Boolean).join(" ")
      : "Choose the system you use before OpenReef shows product-specific advice.";
    const secondaryDeliveryVisible = secondary.classId === "kalkwasser";
    const body = `
      <label class="toggle-card">
        <input type="checkbox" data-scope="dosing" data-field="enabled" ${enabled ? "checked" : ""}>
        <span>
          <strong>Show the Dosing Advisor</strong>
          <small>Advisory only. OpenReef estimates consumption and explains safe dose changes, but never controls dosing pumps.</small>
        </span>
      </label>
      <section class="mapping-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Dosing setup</p>
            <h4>Pick the product system first, then enter only the dose details OpenReef needs.</h4>
          </div>
          <span class="pill ${system.safetyAcknowledged ? "ok" : "warning"}">${system.safetyAcknowledged ? "safety acknowledged" : "locked"}</span>
        </div>
        <div class="grid two compact">
          <label>Net tank water volume (L)
            <input type="number" min="0" step="1" data-scope="dosing-system" data-field="tankVolumeLitres" value="${this._escape(system.tankVolumeLitres || 0)}">
            <small>Use real system water volume after rock, sand, sump level, and displacement.</small>
          </label>
          <label>Primary dosing system
            <select data-scope="dosing-system" data-field="primaryProduct">
              ${this._dosingProductOptions("primary", system.primaryProduct)}
            </select>
            <small>${this._escape(primary.id ? this._dosingProductClassLabel(primary.classId) : "Required for product-specific advice.")}</small>
          </label>
          <label>Optional secondary supplement
            <select data-scope="dosing-system" data-field="secondaryProduct">
              ${this._dosingProductOptions("secondary", system.secondaryProduct)}
            </select>
            <small>Use this for kalkwasser or another supporting product.</small>
          </label>
          ${secondaryDeliveryVisible ? `
            <label>Kalkwasser delivery
              <select data-scope="dosing-system" data-field="secondaryDelivery">
                <option value="" ${!system.secondaryDelivery ? "selected" : ""}>Choose delivery method</option>
                <option value="ato" ${system.secondaryDelivery === "ato" ? "selected" : ""}>ATO reservoir</option>
                <option value="dosing_pump" ${system.secondaryDelivery === "dosing_pump" ? "selected" : ""}>Dosing pump</option>
                <option value="manual_top_off" ${system.secondaryDelivery === "manual_top_off" ? "selected" : ""}>Manual top-off</option>
              </select>
              <small>Kalkwasser is high-pH and evaporation-limited.</small>
            </label>
          ` : `
            <label>Custom product name
              <input data-scope="dosing-system" data-field="customProductName" value="${this._escape(system.customProductName || "")}">
              <small>Optional label for custom or verified-strength products.</small>
            </label>
          `}
        </div>
        <div class="notice ${secondary.classId === "kalkwasser" ? "warning-notice" : "compact-notice"}">
          <strong>${this._escape(selected ? "Product safety model" : "Setup required")}.</strong> ${this._escape(productNote)}
        </div>
        ${secondaryDeliveryVisible ? `
          <div class="setting-card subtle-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Kalkwasser safety limits</p>
                <h4>Capacity, evaporation, and pH guardrails</h4>
                <p class="muted">These are advisory-only limits. OpenReef uses them to avoid telling you to push kalk harder when pH or evaporation makes that unsafe.</p>
              </div>
            </div>
            <div class="grid three compact">
              <label>Daily kalk volume (mL/day)
                <input type="number" min="0" step="10" data-scope="dosing-system" data-field="kalkDailyDoseMl" value="${this._escape(system.kalkDailyDoseMl || 0)}">
                <small>How much kalkwasser solution you currently add per day.</small>
              </label>
              <label>Kalk concentration (tsp/US gal)
                <input type="number" min="0" step="0.25" data-scope="dosing-system" data-field="kalkConcentrationTspPerGallon" value="${this._escape(system.kalkConcentrationTspPerGallon || 0)}">
                <small>Use your actual mixed strength, not the powder amount left in the container.</small>
              </label>
              <label>Evaporation ceiling (mL/day)
                <input type="number" min="0" step="10" data-scope="dosing-system" data-field="kalkEvaporationLimitMlPerDay" value="${this._escape(system.kalkEvaporationLimitMlPerDay || 0)}">
                <small>Approximate daily top-off capacity before salinity risk becomes likely.</small>
              </label>
              <label>Max pH
                <input type="number" min="0" step="0.01" data-scope="dosing-system" data-field="kalkMaxPh" value="${this._escape(system.kalkMaxPh || 8.45)}">
                <small>OpenReef blocks kalk increase advice at or above this pH.</small>
              </label>
              <label>Max pH rise
                <input type="number" min="0" step="0.01" data-scope="dosing-system" data-field="kalkMaxPhRise" value="${this._escape(system.kalkMaxPhRise || 0.2)}">
                <small>Maximum rise you are comfortable seeing from a dosing window.</small>
              </label>
            </div>
          </div>
        ` : ""}
        <label class="toggle-card">
          <input type="checkbox" data-scope="dosing-system" data-field="safetyAcknowledged" ${system.safetyAcknowledged ? "checked" : ""}>
          <span>
            <strong>I understand this is advisory only</strong>
            <small>OpenReef will not dose automatically. I will verify advice against fresh tests and product instructions before changing any doser.</small>
          </span>
        </label>
      </section>
      ${active.length ? active.map(([id, sensor]) => {
        const cfg = this._dosingParamConfig(id);
        const unitLabel = sensor.unit ? ` (${sensor.unit})` : "";
        const name = sensor.label || id;
        const product = this._dosingProductForParameter(id);
        const potencyInfo = this._dosingEffectivePotency(id, sensor, cfg, product);
        const productUnit = sensor.unit || "units";
        const exact = product.exactParameters?.[id] || {};
        const productDose = this._dosingPresetNumber(cfg, exact, "productDoseMl");
        const productVolume = this._dosingPresetNumber(cfg, exact, "productVolumeLitres");
        const productRaise = this._dosingPresetNumber(cfg, exact, "productRaise");
        const showStrengthFields = product.classId === "custom_verified_strength" || product.requiresCustomStrength || cfg.potencyPerMl || cfg.productRaise;
        return `
          <section class="mapping-section">
            <div>
              <p class="eyebrow">${this._escape(name)}</p>
              <h4>Current dose, target, and optional verified strength for ${this._escape(product.label)}.</h4>
            </div>
            <div class="mini-grid">
              <label>Current dose (mL/day)<input type="number" step="0.1" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="doserMlPerDay" value="${this._escape(cfg.doserMlPerDay ?? 0)}"></label>
              <label>Target${this._escape(unitLabel)}<input type="number" step="0.01" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="target" value="${this._escape(cfg.target ?? 0)}"></label>
            </div>
            <div class="notice compact-notice">
              <strong>${this._escape(this._dosingProductClassLabel(product.classId))}.</strong> ${this._escape(product.note || "OpenReef will use rate-only guidance until a safe exact strength is available.")}
            </div>
            ${showStrengthFields ? `
              <div class="mini-grid">
                <label>Instruction dose (mL)<input type="number" step="0.1" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="productDoseMl" value="${this._escape(productDose)}"></label>
                <label>Instruction volume (L)<input type="number" step="1" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="productVolumeLitres" value="${this._escape(productVolume)}"></label>
                <label>Raises by${this._escape(unitLabel)}<input type="number" step="0.0001" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="productRaise" value="${this._escape(productRaise)}"></label>
                <label>Manual strength override (${this._escape(productUnit)}/mL)<input type="number" step="0.0001" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="potencyPerMl" value="${this._escape(cfg.potencyPerMl ?? 0)}"></label>
              </div>
            ` : ""}
            <p class="hint">${this._escape(potencyInfo.label)}. Always verify against your bottle and confirm with a fresh test before changing a doser.</p>
          </section>
        `;
      }).join("") : `<p class="muted">Map alkalinity, calcium, or magnesium sensors, or add at least two manual results for a parameter, to use the Dosing Advisor.</p>`}
    `;
    return this._settingsPanel(
      "dosing",
      "Dosing Advisor",
      "Advisory consumption tracking and dose suggestions for alkalinity, calcium, and magnesium.",
      body,
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
          <label>Tank type
            <select data-scope="tank" data-field="profile">
              ${this._tankProfileChoices().map(([id, label]) => `<option value="${this._escape(id)}" ${this._tankProfile() === id ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
            </select>
            <small>${this._escape(this._tankProfileDetail())}</small>
          </label>
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
    const statusDetail = this._sensorStatusDetail(sensor, id);
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
          <p class="status-detail">${this._escape(statusDetail)}</p>
          <label>Entity<input data-scope="sensor" data-id="${this._escape(id)}" data-field="entity_id" value="${this._escape(sensor.entity_id)}" placeholder="sensor.example"></label>
          ${sensor.entity_id ? `
            <div class="selected-entity">
              <span>${this._escape(this._friendlyEntityName(sensor.entity_id))}</span>
              <button class="secondary compact-button" data-action="clear-sensor" data-id="${this._escape(id)}">Clear</button>
            </div>
          ` : ""}
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

  _equipmentSettings(forceOpen = false) {
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
      forceOpen,
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
            <section class="mapping-card entity-card safety-card">
              <div class="mapping-head">
                <div>
                  <h3>Restart delay</h3>
                  <p class="muted">Delay automatic turn-on when OpenReef returns to Running.</p>
                </div>
                <span class="pill ${Number(item.powerOnDelaySeconds || 0) ? "warning" : "unknown"}">${Number(item.powerOnDelaySeconds || 0) ? `${this._escape(String(item.powerOnDelaySeconds))}s` : "off"}</span>
              </div>
              <label>Power-on delay seconds
                <input type="number" min="0" max="1800" step="5" data-scope="equipment" data-id="${this._escape(id)}" data-field="powerOnDelaySeconds" value="${this._escape(item.powerOnDelaySeconds ?? 0)}">
                <small>Useful for skimmers and ATO after return-pump pauses while water levels stabilise.</small>
              </label>
            </section>
            <section class="picker mapping-card entity-card">
              <div class="mapping-head">
                <h3>Switch</h3>
                <span class="pill">required</span>
              </div>
              <label>Switch<input data-scope="equipment" data-id="${this._escape(id)}" data-field="switch_entity_id" value="${this._escape(item.switch_entity_id)}" placeholder="switch.example"></label>
              ${item.switch_entity_id ? `
                <div class="selected-entity">
                  <span>${this._escape(this._friendlyEntityName(item.switch_entity_id))}</span>
                  <button class="secondary compact-button" data-action="clear-equipment-field" data-id="${this._escape(id)}" data-field="switch_entity_id">Clear</button>
                </div>
              ` : ""}
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
                      ${item[field] ? `
                        <div class="selected-entity">
                          <span>${this._escape(this._friendlyEntityName(item[field]))}</span>
                          <button class="secondary compact-button" data-action="clear-equipment-field" data-id="${this._escape(id)}" data-field="${field}">Clear</button>
                        </div>
                      ` : ""}
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
    const times = this._scheduleTimes(item);
    if (!schedule.enabled) {
      return ["disabled", "Scheduler off", "Turn on scheduled modes to allow this item to run."];
    }
    if (!item.enabled) {
      return ["disabled", "Paused", "This schedule is saved but will not run."];
    }
    if (!times.length) {
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
    const timeLabel = times.length === 1 ? times[0] : `${times.length} times (${times.join(", ")})`;
    return ["ok", `${counts.ready} ready`, `${mode.label} will run ${this._scheduleDayLabel(item.days)} at ${timeLabel}.`];
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
            <h4>Run a saved mode at chosen times and days.</h4>
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
              const times = this._scheduleTimes(item);
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
                    <label class="toggle-card compact-toggle">
                      <input type="checkbox" data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="enabled" ${item.enabled ? "checked" : ""}>
                      <span><strong>Enable item</strong><small>Runs only while global scheduling is on.</small></span>
                    </label>
                    <label class="toggle-card compact-toggle">
                      <input type="checkbox" data-scope="mode-schedule" data-id="${this._escape(item.id)}" data-field="requireAutoReturn" ${item.requireAutoReturn !== false ? "checked" : ""}>
                      <span><strong>Require auto-return</strong><small>Recommended for unattended schedules.</small></span>
                    </label>
                  </div>
                  <div class="schedule-times">
                    <div class="section-head compact-head">
                      <div>
                        <strong>Run times</strong>
                        <p class="muted">Add multiple times when the same safe mode should run more than once per day.</p>
                      </div>
                      <button class="secondary compact-button" data-action="add-schedule-time" data-schedule="${this._escape(item.id)}">+ Time</button>
                    </div>
                    <div class="time-list">
                      ${times.map((time, index) => `
                        <label>Time ${index + 1}
                          <span class="time-input-row">
                            <input type="time" value="${this._escape(time)}" data-scope="mode-schedule-time" data-id="${this._escape(item.id)}" data-index="${index}" data-field="times">
                            <button class="danger-text compact-button" data-action="remove-schedule-time" data-schedule="${this._escape(item.id)}" data-index="${index}" ${times.length <= 1 ? "disabled" : ""}>Remove</button>
                          </span>
                        </label>
                      `).join("")}
                    </div>
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
          <label>Alert hysteresis %
            <input type="number" min="0" max="20" step="0.5" data-scope="alerts" data-field="hysteresisPercent" value="${this._escape(String(alerts.hysteresisPercent ?? 2))}">
            <small>Helps prevent readings near a threshold from flickering between warning and resolved.</small>
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
    const atoDutySummary = this._atoDutyCycleSummary();
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
            <input type="checkbox" data-scope="interlocks" data-field="skimmerAutoOffWhenReturnPumpOff" ${interlocks.skimmerAutoOffWhenReturnPumpOff ? "checked" : ""}>
            <span>
              <strong>Auto-off skimmer with return pump</strong>
              <small>If OpenReef turns an armed return pump off, it also turns armed skimmers off.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="interlocks" data-field="atoReturnPumpWarning" ${interlocks.atoReturnPumpWarning !== false ? "checked" : ""}>
            <span>
              <strong>Warn ATO when return pump is off</strong>
              <small>Surface Mission Control warnings if top-off could run while return flow is not confirmed.</small>
            </span>
          </label>
          <label class="toggle-card">
            <input type="checkbox" data-scope="interlocks" data-field="atoBlockWhenReturnPumpOff" ${interlocks.atoBlockWhenReturnPumpOff ? "checked" : ""}>
            <span>
              <strong>Block ATO if return pump is off</strong>
              <small>Prevents manual and scheduled ATO power-on while an armed return pump is off or unavailable.</small>
            </span>
          </label>
        </div>
        <section class="mapping-section ato-duty-section">
          <div class="section-head">
            <div>
              <p class="eyebrow">ATO Safety Schedule</p>
              <h4>Power the ATO only for short windows.</h4>
              <p class="muted">${this._escape(atoDutySummary)}</p>
            </div>
            <span class="pill ${interlocks.atoDutyCycleEnabled ? "warning" : "unknown"}">${interlocks.atoDutyCycleEnabled ? "enabled" : "off"}</span>
          </div>
          <div class="notice warning-notice"><strong>ATO duty cycle only runs in Running mode and only controls armed ATO equipment.</strong> Leave it off when the ATO should stay powered continuously.</div>
          <div class="grid four compact">
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="atoDutyCycleEnabled" ${interlocks.atoDutyCycleEnabled ? "checked" : ""}>
              <span>
                <strong>ATO duty cycle</strong>
                <small>Turn armed ATO switches on briefly, then force them off outside the window.</small>
              </span>
            </label>
            <label>On duration seconds
              <input type="number" min="5" max="1800" step="5" data-scope="interlocks" data-field="atoDutyCycleOnSeconds" value="${this._escape(interlocks.atoDutyCycleOnSeconds ?? 120)}">
            </label>
            <label>Every minutes
              <input type="number" min="5" max="1440" step="5" data-scope="interlocks" data-field="atoDutyCycleIntervalMinutes" value="${this._escape(interlocks.atoDutyCycleIntervalMinutes ?? 60)}">
            </label>
            <label>Anchor time
              <input type="time" data-scope="interlocks" data-field="atoDutyCycleAnchorTime" value="${this._escape(interlocks.atoDutyCycleAnchorTime || "00:00")}">
              <small>Example: 00:00 runs hourly on the hour when interval is 60.</small>
            </label>
          </div>
        </section>
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

  _systemCheckSettings() {
    const check = this._systemCheck();
    const checklist = this._betaChecklist(check);
    const rows = [
      ["OpenReef version", check.version],
      ["Config schema", check.schema],
      ["Tank profile", check.tankProfile],
      ["Reef Health", `${check.health.score}/100 (${check.health.grade})`],
      ["Health trend data", check.health.trendFreshness],
      ["Active mode", check.activeMode],
      ["Mode timer", check.modeTimer],
      ["Sensors", `${check.sensors} mapped/enabled`],
      ["Manual tests", `${check.manualTests} tracked, ${check.manualDue} due`],
      ["Dosing Advisor", this._dosingMissionState().value],
      ["Equipment", `${check.equipment} armed/total`],
      ["Entity mappings", `${check.mappedEquipment} equipment, ${check.energy} energy totals`],
      ["Alerts", check.alerts],
      ["Interlocks", `${check.interlocks} warning(s)`],
      ["ATO duty cycle", check.atoDutyCycle],
      ["Missing entities", check.missing],
      ["Armed unavailable", check.armedUnavailable],
      ["Custom modes", check.customModes],
      ["Schedules", check.schedules],
      ["Last activity", check.lastActivity],
      ["Unsaved changes", check.dirty ? "yes" : "no"],
    ];
    return this._settingsPanel(
      "system",
      "System Check",
      "A beta-tester snapshot with counts only. No tokens or secrets are included.",
      `
        <div class="system-grid">
          ${rows.map(([label, value]) => `
            <article class="system-card">
              <span>${this._escape(label)}</span>
              <strong>${this._escape(value)}</strong>
            </article>
          `).join("")}
        </div>
        <section class="mapping-section beta-checklist">
          <div class="section-head">
            <div>
              <p class="eyebrow">Beta handoff</p>
              <h4>Quick readiness checklist for your tester.</h4>
              <p class="muted">This does not expose tokens or secrets. It turns the support summary into a simple go/no-go scan.</p>
            </div>
          </div>
          <div class="system-grid">
            ${checklist.map((item) => `
              <article class="system-card ${this._escape(item.state)}">
                <span>${this._escape(item.label)}</span>
                <strong>${this._escape(item.status)}</strong>
                <small>${this._escape(item.detail)}</small>
              </article>
            `).join("")}
          </div>
        </section>
        <div class="button-row">
          <button class="secondary" data-action="validate">Refresh checks</button>
          <button class="secondary" data-action="copy-beta-smoke-test">Copy beta smoke test</button>
          <button class="secondary" data-action="copy-beta-feedback-template">Copy feedback template</button>
          <button class="secondary" data-action="copy-dosing-summary">Copy dosing summary</button>
          <button class="primary" data-action="copy-support-summary">Copy support summary</button>
        </div>
      `,
    );
  }

  _energyPicker(field, label) {
    const key = `energy:${field}`;
    const result = this._searchResults[key];
    const entityId = this._config.energy[field];
    return `
      <section class="picker mapping-card entity-card">
        <div class="mapping-head">
          <h3>${this._escape(label)}</h3>
          <span class="pill">optional</span>
        </div>
        <label>${this._escape(label)}<input data-scope="energy" data-field="${this._escape(field)}" value="${this._escape(entityId)}" placeholder="sensor.optional"></label>
        ${entityId ? `
          <div class="selected-entity">
            <span>${this._escape(this._friendlyEntityName(entityId))}</span>
            <button class="secondary compact-button" data-action="clear-energy-field" data-field="${this._escape(field)}">Clear</button>
          </div>
        ` : ""}
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

  _trendSvg(points, unit, range, digits = 2) {
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
        <svg class="trend-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${this._escape(this._trendRangeLabel(range))} trend">
          <line x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}" vector-effect="non-scaling-stroke" />
          <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" vector-effect="non-scaling-stroke" />
          <polygon points="${fillCoords}" />
          <polyline points="${coords.join(" ")}" vector-effect="non-scaling-stroke" />
        </svg>
        <div class="chart-labels">
          <span>${this._formatTrendTime(minTime, range)}</span>
          <strong>${this._format(max, digits)} ${this._escape(unit || "")}</strong>
          <span>${this._formatTrendTime(maxTime, range)}</span>
        </div>
      </div>
    `;
  }

  _trendModal() {
    const manual = this._trend.source === "manual";
    const sensor = manual ? this._trend.manualMeta || this._manualTestMeta(this._trend.sensorId) : this._config.sensors?.[this._trend.sensorId] || {};
    const points = this._trend.points || [];
    const summary = this._trendSummary(points);
    const range = this._trend.range || "24h";
    const digits = this._sensorDigits(this._trend.sensorId);
    const coverageMessage = manual ? "" : this._trendCoverageMessage(points, range);
    const ranges = manual ? this._manualTrendRanges() : this._trendRanges();
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
            ${ranges.map(([id, label]) => `
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
          ${!this._trend.loading && !this._trend.error ? this._trendSvg(points, sensor.unit, range, digits) : ""}
          ${summary ? `
            <div class="trend-summary">
              <article><span>Latest</span><strong>${this._format(summary.latest, digits)} ${this._escape(sensor.unit || "")}</strong></article>
              <article><span>Low</span><strong>${this._format(summary.min, digits)} ${this._escape(sensor.unit || "")}</strong></article>
              <article><span>High</span><strong>${this._format(summary.max, digits)} ${this._escape(sensor.unit || "")}</strong></article>
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
    const manualTracked = this._manualTestParameterIds().filter((id) => this._manualTestConfig(id).enabled);
    const manualDue = this._manualTestFreshnessItems().filter((item) => item.status === "warning" || item.status === "critical");
    return {
      sensors,
      enabledSensors,
      mappedSensors,
      equipment,
      mappedEquipment,
      armedEquipment,
      energyMapped,
      manualTracked,
      manualDue,
    };
  }

  _setupShell(title, description, content) {
    const steps = this._setupSteps();
    const lastStep = this._lastSetupStep();
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
            ${this._setupStep < lastStep ? `<button class="primary" data-action="next-step">Next</button>` : `<button class="primary" data-action="finish-setup">Finish setup</button>`}
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
            <label>Tank type
              <select data-scope="tank" data-field="profile">
                ${this._tankProfileChoices().map(([id, label]) => `<option value="${this._escape(id)}" ${this._tankProfile() === id ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
              </select>
              <small>${this._escape(this._tankProfileDetail())}</small>
            </label>
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
        ${this._apexImportGuide("setup")}
        <div class="setup-choice-grid two-choice">
          <button class="setup-choice" data-action="setup-sensor-preset" data-id="all">
            <strong>Everything available</strong>
            <span>Add all reef, chemistry, water, safety, flow, lighting, sump, and room sensors.</span>
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

  _setupManualTestsStep() {
    const stats = this._setupStats();
    return this._setupShell(
      "Manual testing routine",
      "OpenReef can suggest a routine for your tank profile, but you decide what to track and how often.",
      `
        <div class="setup-choice-grid two-choice">
          <button class="setup-choice" data-action="apply-manual-schedule-preset">
            <strong>Use ${this._escape(this._tankProfileLabel(this._tankProfile()))} suggestion</strong>
            <span>Enable a sensible starting routine for chemistry and salinity, then adjust it any time.</span>
          </button>
          <article class="setup-choice passive">
            <strong>Skip for now</strong>
            <span>Manual testing is optional. You can still log results later without a schedule.</span>
          </article>
        </div>
        <div class="setup-status-line">${stats.manualTracked.length} manual tests tracked. ${stats.manualDue.length} currently due.</div>
        ${this._manualTestSettings(true)}
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
        ${this._equipmentSettings(true)}
      `,
    );
  }

  _setupSafetyStep() {
    const interlocks = this._config.interlocks || {};
    const alerts = this._config.alerts || {};
    const atoDutySummary = this._atoDutyCycleSummary();
    const hasAto = Object.values(this._config.equipment || {}).some((item) => this._equipmentProfile("", item) === "ato");
    const hasDisplayWavemaker = Object.values(this._config.equipment || {}).some((item) => this._equipmentProfile("", item) === "display_wavemaker");
    return this._setupShell(
      "Review safety defaults",
      "These settings make the first beta safer without forcing advanced automation on.",
      `
        <div class="setup-guide">
          <article><strong>Control stays deliberate</strong><span>Switches only work after a device is mapped and armed.</span></article>
          <article><strong>ATO can be limited</strong><span>Use duty cycling only if you want OpenReef to power your ATO for short windows.</span></article>
          <article><strong>Display wavemakers are special</strong><span>OpenReef warns before automatic restart because livestock can enter stopped pumps.</span></article>
        </div>
        <article class="panel setup-panel">
          <div class="section-head">
            <div>
              <h3>Recommended beta safety settings</h3>
              <p>Leave these enabled unless your tester understands the trade-off.</p>
            </div>
          </div>
          <div class="grid two compact">
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="heaterRequiresTankTemp" ${interlocks.heaterRequiresTankTemp !== false ? "checked" : ""}>
              <span>
                <strong>Heater requires tank temperature</strong>
                <small>Mission Control warns if heater control is armed without a live display temperature.</small>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="atoReturnPumpWarning" ${interlocks.atoReturnPumpWarning !== false ? "checked" : ""}>
              <span>
                <strong>Warn ATO when return flow is not confirmed</strong>
                <small>Useful for rear chambers and sumps where water level can lie during flow problems.</small>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="atoBlockWhenReturnPumpOff" ${interlocks.atoBlockWhenReturnPumpOff ? "checked" : ""}>
              <span>
                <strong>Block ATO if return pump is off</strong>
                <small>Optional stricter rule: OpenReef will not turn an armed ATO on while return flow is off or unavailable.</small>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="skimmerAutoOffWhenReturnPumpOff" ${interlocks.skimmerAutoOffWhenReturnPumpOff ? "checked" : ""}>
              <span>
                <strong>Turn skimmer off with return pump</strong>
                <small>Optional helper for water-level changes. It only affects mapped, armed skimmers.</small>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" data-scope="alerts" data-field="persistentNotifications" ${alerts.persistentNotifications ? "checked" : ""}>
              <span>
                <strong>Home Assistant notifications</strong>
                <small>Create persistent HA notifications for OpenReef alerts.</small>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" data-scope="alerts" data-field="wavemakerReminders" ${alerts.wavemakerReminders !== false ? "checked" : ""}>
              <span>
                <strong>Display wavemaker reminders</strong>
                <small>Repeat reminders while an armed display wavemaker remains off in Running.</small>
              </span>
            </label>
          </div>
        </article>
        <article class="panel setup-panel">
          <div class="section-head">
            <div>
              <h3>ATO duty cycle</h3>
              <p>${this._escape(atoDutySummary)}</p>
            </div>
            <span class="pill ${interlocks.atoDutyCycleEnabled ? "warning" : "unknown"}">${interlocks.atoDutyCycleEnabled ? "enabled" : "off"}</span>
          </div>
          ${hasAto ? "" : `<div class="notice compact-notice">No ATO equipment is mapped yet. These settings can still be saved now and will apply later.</div>`}
          <div class="grid four compact">
            <label class="toggle-card">
              <input type="checkbox" data-scope="interlocks" data-field="atoDutyCycleEnabled" ${interlocks.atoDutyCycleEnabled ? "checked" : ""}>
              <span>
                <strong>Enable ATO duty cycle</strong>
                <small>Use for short, repeated ATO power windows.</small>
              </span>
            </label>
            <label>On duration seconds
              <input type="number" min="5" max="1800" step="5" data-scope="interlocks" data-field="atoDutyCycleOnSeconds" value="${this._escape(interlocks.atoDutyCycleOnSeconds ?? 120)}">
            </label>
            <label>Every minutes
              <input type="number" min="5" max="1440" step="5" data-scope="interlocks" data-field="atoDutyCycleIntervalMinutes" value="${this._escape(interlocks.atoDutyCycleIntervalMinutes ?? 60)}">
            </label>
            <label>Anchor time
              <input type="time" data-scope="interlocks" data-field="atoDutyCycleAnchorTime" value="${this._escape(interlocks.atoDutyCycleAnchorTime || "00:00")}">
            </label>
          </div>
        </article>
        ${hasDisplayWavemaker ? `<div class="notice danger-notice"><strong>Display wavemaker warning:</strong> if a display wavemaker has been off, inspect it before restarting. Fish can enter stopped wavemakers, and flow is critical for corals.</div>` : ""}
      `,
    );
  }

  _setupReviewStep() {
    const stats = this._setupStats();
    const sensorsReady = stats.enabledSensors.length && stats.mappedSensors.length === stats.enabledSensors.length;
    const controlsReady = stats.equipment.length ? stats.mappedEquipment.length === stats.equipment.length : true;
    const safetyReady = (this._config.interlocks?.heaterRequiresTankTemp !== false) && (this._config.alerts?.wavemakerReminders !== false);
    return this._setupShell(
      "Review setup",
      "Finish when the basics look right. OpenReef will stay safe even if you finish with missing optional mappings.",
      `
        <div class="summary-grid">
          ${this._setupReviewCard("Sensors", `${stats.mappedSensors.length}/${stats.enabledSensors.length}`, sensorsReady ? "Mapped" : "Needs attention", sensorsReady ? "ok" : "warning", 1)}
          ${this._setupReviewCard("Manual Tests", `${stats.manualTracked.length}`, stats.manualTracked.length ? "Routine selected" : "Optional", stats.manualDue.length ? "warning" : stats.manualTracked.length ? "ok" : "unknown", 2)}
          ${this._setupReviewCard("Equipment", `${stats.mappedEquipment.length}/${stats.equipment.length}`, stats.equipment.length ? `${stats.armedEquipment.length} armed` : "Monitor only", controlsReady ? "ok" : "warning", 3)}
          ${this._setupReviewCard("Safety", safetyReady ? "On" : "Review", "Core warnings and reminders", safetyReady ? "ok" : "warning", 4)}
          ${this._setupReviewCard("Energy", `${stats.energyMapped}/3`, stats.energyMapped ? "Totals mapped" : "Optional", stats.energyMapped ? "ok" : "unknown", 5)}
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
    if (this._setupStep === 2) return this._setupManualTestsStep();
    if (this._setupStep === 3) return this._setupEquipmentStep();
    if (this._setupStep === 4) return this._setupSafetyStep();
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
          -webkit-text-size-adjust: 100%;
          text-size-adjust: 100%;
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
        .button-row.end { justify-content: flex-end; }
        .tabs { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 18px; }
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
        .health-breakdown { display: grid; gap: 14px; border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96)); }
        .health-breakdown.warning { border-color: #a16207; }
        .health-breakdown.critical { border-color: #7f1d1d; }
        .health-category-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
        .health-category, .health-reason-card, .health-insight-group, .health-insight-row { border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: rgba(11, 23, 36, .72); display: grid; gap: 5px; }
        .health-category span, .health-reason-card span, .health-insight-head strong { color: #8da2ba; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
        .health-category strong { color: #67e8f9; font-size: 22px; }
        .health-category.ok { border-color: #166534; }
        .health-category.warning { border-color: #a16207; }
        .health-category.critical { border-color: #7f1d1d; }
        .health-reason-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .health-reason-card strong { color: #e5edf5; font-size: 16px; overflow-wrap: anywhere; }
        .health-reason-card p { color: #9fb2c7; }
        .health-insight-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
        .health-insight-group { align-content: start; padding: 0; overflow: hidden; }
        .health-insight-group.open { padding-bottom: 12px; }
        .health-insight-group.collapsed { background: rgba(11, 23, 36, .55); }
        .health-insight-head, .health-insight-row { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
        .health-insight-head { width: 100%; border: 0; border-radius: 0; background: transparent; padding: 12px; text-align: left; }
        .health-insight-head span:first-child { display: grid; gap: 4px; min-width: 0; }
        .health-insight-head small { color: #8da2ba; overflow-wrap: anywhere; }
        .health-insight-head:hover, .health-insight-head:focus-visible { background: rgba(103, 232, 249, .05); outline: none; }
        .health-insight-body { display: grid; gap: 7px; padding: 0 12px; }
        .health-insight-row { background: rgba(18, 31, 47, .76); }
        .health-insight-row div { display: grid; gap: 4px; min-width: 0; }
        .health-insight-row strong { color: #e5edf5; overflow-wrap: anywhere; }
        .health-insight-row small { color: #9fb2c7; overflow-wrap: anywhere; }
        .health-insight-row.critical { border-color: #7f1d1d; }
        .health-insight-row.warning { border-color: #a16207; }
        .health-insight-row.learning { border-color: #334155; }
        .health-insight-row.context { border-color: #294055; }
        .dosing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
        .dosing-card { border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: rgba(11, 23, 36, .72); display: grid; gap: 8px; align-content: start; }
        .dosing-card.ok { border-color: #166534; }
        .dosing-card.warning { border-color: #a16207; }
        .dosing-card.critical { border-color: #7f1d1d; }
        .dosing-card.unknown { border-color: #334155; }
        .dosing-card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
        .dosing-card-head span { color: #8da2ba; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }
        .dosing-card-head strong { color: #67e8f9; font-size: 20px; }
        .dosing-card-lines { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
        .dosing-card-lines li { display: grid; gap: 2px; min-width: 0; }
        .dosing-card-lines span { color: #8da2ba; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
        .dosing-card-lines small { color: #cbd5e1; overflow-wrap: anywhere; }
        .or-onboard { position: fixed; inset: 0; z-index: 12; pointer-events: none; }
        .or-spotlight { position: fixed; border-radius: 12px; box-shadow: 0 0 0 9999px rgba(4, 12, 20, .62); outline: 2px solid var(--openreef-accent); outline-offset: 2px; opacity: 0; transition: top .25s ease, left .25s ease, width .25s ease, height .25s ease, opacity .2s ease; pointer-events: none; }
        .or-narrator { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); width: min(520px, calc(100vw - 28px)); display: flex; gap: 12px; align-items: flex-end; pointer-events: auto; z-index: 13; transition: left .6s cubic-bezier(.34,.6,.26,1), top .6s cubic-bezier(.34,.6,.26,1); }
        .or-avatar { flex: 0 0 auto; width: 176px; display: grid; place-items: end center; }
        .or-avatar-img { width: 100%; height: auto; display: block; filter: drop-shadow(0 6px 10px rgba(0,0,0,.45)); animation: or-bob 2.6s ease-in-out infinite; }
        .or-walk-img { animation: none; transform-origin: center bottom; }
        @keyframes or-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
        .or-avatar-ph { width: 168px; height: 168px; border-radius: 50%; display: grid; place-items: center; font-size: 74px; background: radial-gradient(circle at 50% 35%, var(--openreef-accent-soft), #0b1724); border: 2px solid var(--openreef-accent-border); box-shadow: 0 6px 14px rgba(0,0,0,.45); }
        .or-bubble { flex: 1 1 auto; min-width: 0; background: #101f2f; border: 1px solid var(--openreef-accent-border); border-radius: 16px; padding: 18px 20px; box-shadow: 0 18px 50px rgba(0,0,0,.5); }
        .or-bubble-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 6px; }
        .or-tone { border: 1px solid #294055; border-radius: 999px; background: #172536; color: #dcecff; font-size: 11px; font-weight: 800; padding: 3px 10px; }
        .or-tone:hover { border-color: var(--openreef-accent); }
        .or-sticker { display: block; width: 100%; max-height: 360px; object-fit: contain; border-radius: 10px; margin-bottom: 12px; }
        .or-line { color: #e9f1f8; font-size: 17px; line-height: 1.5; overflow-wrap: anywhere; }
        .or-link { display: inline-block; margin-top: 8px; color: var(--openreef-accent); font-weight: 800; text-decoration: none; border-bottom: 1px solid var(--openreef-accent-border); overflow-wrap: anywhere; }
        .or-link:hover { border-bottom-color: var(--openreef-accent); }
        .or-dots { display: flex; gap: 6px; margin: 10px 0; }
        .or-dot { width: 7px; height: 7px; border-radius: 50%; background: #2b4056; }
        .or-dot.active { background: var(--openreef-accent); }
        .or-actions { display: flex; gap: 8px; align-items: center; }
        .or-actions .or-spacer { flex: 1 1 auto; }
        .or-buddy { position: fixed; right: 16px; bottom: 16px; z-index: 11; display: flex; align-items: flex-end; gap: 10px; pointer-events: none; }
        .or-buddy-avatar { position: relative; flex: 0 0 auto; width: 122px; padding: 0; border: 0; background: transparent; cursor: pointer; pointer-events: auto; display: block; }
        .or-buddy-avatar .or-avatar-img { width: 100%; height: auto; display: block; filter: drop-shadow(0 6px 12px rgba(0,0,0,.5)); }
        .or-buddy-avatar .or-avatar-ph { width: 92px; height: 92px; margin: 0 auto; }
        .or-buddy-dot { position: absolute; top: 8px; right: 12px; width: 14px; height: 14px; border-radius: 50%; border: 2px solid #07111a; background: #22c55e; }
        .or-buddy-dot.mood-warning { background: #f59e0b; }
        .or-buddy-dot.mood-critical { background: #ef4444; animation: or-pulse 1.2s ease-in-out infinite; }
        .or-buddy-dot.mood-learning { background: #38bdf8; }
        @keyframes or-pulse { 50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, .25); } }
        .or-buddy-bubble { position: relative; pointer-events: auto; max-width: 300px; background: #101f2f; border: 1px solid var(--openreef-accent-border); border-radius: 14px; padding: 12px 30px 12px 14px; box-shadow: 0 16px 44px rgba(0,0,0,.5); }
        .or-buddy-bubble.mood-warning { border-color: #a16207; }
        .or-buddy-bubble.mood-critical { border-color: #ef4444; background: #2b171c; }
        .or-buddy-title { display: block; color: #f1f6fb; margin-top: 2px; }
        .or-buddy-line { color: #cbd9e8; margin-top: 4px; line-height: 1.4; overflow-wrap: anywhere; }
        .or-buddy-close { position: absolute; top: 6px; right: 8px; width: 22px; height: 22px; border: 0; border-radius: 50%; background: transparent; color: #8da2ba; font-size: 16px; line-height: 1; cursor: pointer; }
        .or-buddy-close:hover { color: #e5edf5; }
        .manual-entry-panel { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96)); }
        .manual-entry-grid { display: grid; grid-template-columns: minmax(150px, .8fr) minmax(130px, .5fr) minmax(110px, .45fr) minmax(180px, .8fr) minmax(140px, .6fr) minmax(220px, 1fr) auto; gap: 12px; align-items: end; }
        .manual-session-grid { display: grid; grid-template-columns: minmax(180px, .45fr) minmax(260px, 1fr); gap: 12px; align-items: end; }
        .manual-batch-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
        .manual-batch-row { border: 1px solid #24364a; border-radius: 8px; background: rgba(11, 23, 36, .72); padding: 10px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(92px, .45fr) minmax(116px, .55fr); gap: 10px; align-items: center; }
        .manual-batch-row.tracked { border-color: var(--openreef-accent-border); background: var(--openreef-accent-soft); }
        .manual-batch-row span { display: grid; gap: 3px; min-width: 0; }
        .manual-batch-row input, .manual-batch-row select { min-height: 38px; }
        .manual-notes { min-width: 0; }
        textarea { width: 100%; min-height: 44px; resize: vertical; border: 1px solid #294055; border-radius: 8px; background: #0b1724; color: #f8fafc; padding: 10px; }
        .manual-test-card { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #121f2f; display: grid; gap: 9px; align-content: start; min-height: 220px; }
        .manual-test-card.ok { border-color: #166534; background: #0b2b24; }
        .manual-test-card.warning { border-color: #a16207; background: #2f2614; }
        .manual-test-card.critical { border-color: #7f1d1d; background: #2b171c; }
        .manual-test-card.unknown { border-color: #334155; }
        .manual-test-card > strong { color: #67e8f9; font-size: 24px; overflow-wrap: anywhere; }
        .manual-test-card p { color: #9fb2c7; }
        .manual-history { display: grid; gap: 8px; border-top: 1px solid #24364a; padding-top: 10px; }
        .manual-history-row { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; border: 1px solid #24364a; border-radius: 8px; padding: 10px; background: rgba(11, 23, 36, .72); }
        .manual-history-row div { display: grid; gap: 4px; min-width: 0; }
        .manual-history-row strong, .manual-history-row small { overflow-wrap: anywhere; }
        .manual-schedule-card.manual-enabled { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .88)); }
        .issue-list { display: grid; gap: 8px; }
        .issue-item { width: 100%; display: grid; grid-template-columns: auto minmax(160px, .45fr) 1fr; gap: 12px; align-items: center; padding: 12px; text-align: left; }
        .issue-item small { color: #9fb2c7; }
        .empty-state { display: grid; grid-column: 1 / -1; gap: 10px; place-items: start; padding: 18px; border-style: dashed; color: #cbd5e1; }
        .empty-state p { color: #8da2ba; }
        .section-head, .card-head, .row { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .section-head > div { min-width: 0; }
        .section-head p { overflow-wrap: anywhere; }
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
        .settings-toolbar, .settings-save { display: flex; gap: 10px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
        .settings-save { position: sticky; top: 10px; z-index: 2; }
        .sticky-save-warning { position: sticky; top: 10px; z-index: 3; box-shadow: 0 10px 30px rgba(0,0,0,.28); }
        .save-state { border: 1px solid #166534; border-radius: 999px; padding: 7px 11px; color: #bbf7d0; background: #0b2b24; font-size: 12px; font-weight: 800; }
        .save-state.dirty { border-color: #a16207; color: #fde68a; background: #2f2614; }
        .settings-section { display: grid; gap: 14px; position: relative; overflow: hidden; }
        .themed-settings-card { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96) 34%, #121f2f); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .settings-section-head { width: 100%; border: 0; background: transparent; padding: 0; display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; text-align: left; color: #e5edf5; }
        .settings-section-head.static-section-head:disabled { opacity: 1; cursor: default; }
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
        .row div { display: grid; gap: 4px; min-width: 0; }
        .row strong, .row span { overflow-wrap: anywhere; }
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
        .selected-entity { display: flex; justify-content: space-between; align-items: center; gap: 10px; border: 1px solid color-mix(in srgb, var(--openreef-accent) 32%, #24364a); border-radius: 8px; padding: 9px 10px; background: var(--openreef-accent-soft); color: #dcecff; overflow-wrap: anywhere; }
        .selected-entity span { min-width: 0; color: #dcecff; font-weight: 800; }
        .mapping-card, .equipment-editor { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0e1a28; }
        .mapping-card { gap: 11px; }
        .mapping-card.tank-card, .mapping-card.sump-card, .mapping-card.chemistry-card, .mapping-card.room-card, .mapping-card.water-card, .mapping-card.safety-sensor-card, .mapping-card.flow-card, .mapping-card.lighting-card { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(14, 26, 40, .96) 34%, #0e1a28); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .stat.water-card, .stat.safety-sensor-card, .stat.flow-card, .stat.lighting-card { border-color: var(--openreef-accent-border); background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(18, 31, 47, .96)); }
        .stat.no-trend { text-align: left; cursor: default; }
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
        .trend-chart { display: block; width: 100%; height: 240px; overflow: hidden; }
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
        .apex-guide { display: grid; gap: 14px; border: 1px solid color-mix(in srgb, var(--openreef-accent) 28%, #24364a); border-radius: 8px; padding: 16px; background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(11, 23, 36, .88)); }
        .apex-guide.compact-guide { margin-bottom: 12px; }
        .apex-guide h3 { margin-bottom: 4px; }
        .apex-guide p { color: #a8bed4; }
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
        .schedule-fields { display: grid; grid-template-columns: minmax(170px, .7fr) minmax(220px, 1fr) minmax(220px, 1fr); gap: 10px; align-items: stretch; }
        .schedule-times { border: 1px solid #24364a; border-radius: 8px; padding: 12px; background: rgba(9, 18, 30, .56); display: grid; gap: 10px; }
        .compact-head { align-items: center; }
        .time-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
        .time-input-row { display: flex; gap: 8px; align-items: center; }
        .time-input-row input { flex: 1; }
        .schedule-days { display: flex; gap: 7px; flex-wrap: wrap; }
        .schedule-days button { border: 1px solid #294055; border-radius: 999px; padding: 7px 10px; background: #172536; color: #dcecff; font-weight: 800; }
        .schedule-days button.active { border-color: var(--openreef-accent); background: var(--openreef-accent); color: #041019; }
        .compact-toggle { min-width: 220px; padding: 10px; }
        .system-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
        .system-card { border: 1px solid color-mix(in srgb, var(--openreef-accent) 28%, #24364a); border-radius: 8px; padding: 12px; background: rgba(11, 23, 36, .72); display: grid; gap: 5px; }
        .system-card.ok { border-color: #166534; background: rgba(11, 43, 36, .82); }
        .system-card.warning { border-color: #a16207; background: rgba(47, 38, 20, .68); }
        .system-card.critical { border-color: #7f1d1d; background: rgba(43, 23, 28, .82); }
        .system-card.unknown { border-color: #334155; background: rgba(16, 29, 44, .82); }
        .system-card span { color: #8da2ba; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
        .system-card strong { color: #dcecff; overflow-wrap: anywhere; }
        .system-card small, .status-detail { color: #a8bed4; line-height: 1.35; }
        .status-detail { margin-top: -2px; }
        .beta-checklist { border-color: var(--openreef-accent-border); background: rgba(11, 23, 36, .74); }
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
          .manual-entry-grid, .manual-session-grid { grid-template-columns: 1fr; }
          .issue-item { grid-template-columns: 1fr; }
          .activity-item { grid-template-columns: 1fr; }
          .detail-grid, .entity-detail-row, .energy-metrics { grid-template-columns: 1fr; }
          .range-picker { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .trend-summary { grid-template-columns: 1fr; }
          .health-category-grid, .health-reason-grid, .health-insight-grid, .dosing-grid { grid-template-columns: 1fr; }
          .health-insight-head, .health-insight-row { flex-direction: column; align-items: stretch; }
          .setup-guide, .setup-choice-grid, .setup-choice-grid.two-choice { grid-template-columns: 1fr; }
          .setup-next-list div { grid-template-columns: 1fr; }
        }
        @media (max-width: 640px) {
          .page { padding: 8px; }
          .modal { padding: 8px; align-items: stretch; overflow: auto; }
          .wizard { width: 100%; max-height: calc(100vh - 16px); padding: 18px; }
          .close { top: 10px; right: 10px; width: 34px; height: 34px; }
          .setup-progress { padding-right: 40px; }
          .stepper { gap: 6px; flex-wrap: wrap; }
          .stepper span, .stepper button { width: 30px; height: 30px; }
          .tabs { grid-template-columns: 1fr; }
          .actions, .button-row, .quick-add, .wizard-actions, .settings-toolbar, .settings-save, .control-actions, .alert-actions, .schedule-toolbar { align-items: stretch; flex-direction: column; }
          .actions button, .button-row button, .quick-add button, .wizard-actions button, .settings-toolbar button, .settings-save button, .control-actions button, .alert-actions button, .schedule-toolbar button { width: 100%; }
          .theme-picker { grid-template-columns: repeat(4, minmax(0, 1fr)); }
          .candidate-tools, .selected-entity, .time-input-row { align-items: stretch; flex-direction: column; }
          .mapping-head, .equipment-editor-head, .control-row { align-items: stretch; }
          .control-switch, .arm-switch { justify-content: space-between; width: 100%; max-width: 220px; }
          .chart-wrap { padding: 10px; }
          .trend-chart { height: 200px; }
          .summary-card { min-height: auto; }
          .or-narrator { bottom: 10px; width: calc(100vw - 12px); flex-direction: column; align-items: flex-start; gap: 0; }
          .or-avatar { width: 168px; margin-left: 8px; margin-bottom: -8px; }
          .or-avatar-ph { width: 120px; height: 120px; font-size: 52px; }
          .or-bubble { width: 100%; padding: 14px 16px; }
          .or-line { font-size: 16px; }
          .or-sticker { max-height: 260px; }
          .or-buddy { right: 10px; bottom: 10px; flex-direction: column; align-items: flex-end; gap: 8px; }
          .or-buddy-avatar { width: 92px; }
          .or-buddy-bubble { max-width: calc(100vw - 24px); }
          .manual-history-row { flex-direction: column; }
          .manual-batch-row { grid-template-columns: 1fr; }
        }
        /* Tablet tier: re-expand content grids that the phone collapse would
           otherwise force into a single wasteful column. Bounded at 641px so
           true phones keep the single-column layout above. */
        @media (min-width: 641px) and (max-width: 1024px) {
          .tabs { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          .grid.two, .grid.three, .grid.four { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .manual-entry-grid, .manual-session-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .manual-notes { grid-column: 1 / -1; }
          .dosing-grid, .health-insight-grid, .health-reason-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .health-category-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
      </style>
    `;
  }
}

customElements.define("openreef-panel", OpenReefPanel);
