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
    this._cameraFocus = null;
    this._recordingFocus = null;
    this._webrtcSession = null;
    this._timelapse = {
      frames: [], index: 0, playing: false, speed: 1, mode: "all",
      loaded: false, loading: false, windowMid: 0, cameraId: "", cameraLabel: "", error: "",
    };
    this._timelapseTimer = null;
    this._overlayQuip = "";
    this._feedWatch = { sessions: [], loaded: false, loading: false, error: "" };
    this._feedPlayer = { sessionId: "", frames: [], index: 0, playing: false, loading: false };
    this._feedPlayerTimer = null;
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
    this._maintenanceHistoryOpen = {};
    this._manualEntryDefaults = {};
    this._onboarding = null;
    this._onboardingChecked = false;
    this._avatarPoses = {};
    this._stickerReady = false;
    this._walkReady = false;
    this._buddy = { dismissed: false, expanded: false, lastKey: "", timer: null };
    this._stratonEvidence = {
      before: "",
      after: "",
      notes: "",
      fixtureState: "",
      probeFixtureId: "",
      probePath: "",
      extraProbePaths: "",
      result: null,
      fixtureStateResult: null,
      probeResult: null,
      probeScanResult: null,
      testerNoteScenario: "strong",
      testerNote: "",
      testerNoteResult: null,
      probeLoading: false,
      probeScanning: false,
    };
    this._stratonProgramImport = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config) {
      if (this._shouldRenderForHassUpdate()) {
        this._render();
      } else if (this._cameraFocus) {
        // Modal open: patch the live overlay stat values without re-rendering
        // (a full render would restart the WebRTC video).
        this._updateCameraOverlay();
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
    // Don't recreate camera <img> elements on hass updates — it would restart the
    // live MJPEG streams. A manual Refresh button re-renders on demand.
    if (this._activeTab === "cameras" || this._cameraFocus) return false;
    // While a clip is open, don't re-render — it would interrupt <video> playback.
    if (this._recordingFocus) return false;
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
    this._stopCameraWebRTC();
    this._stopTimelapse();
    this._stopFeedPlayer();
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
      maintenance: false,
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
        this._stopCameraWebRTC();
        this._stopTimelapse();
        this._stopFeedPlayer();
        this._feedPlayer.sessionId = "";
        this._activeTab = id;
        this._setupOpen = false;
        this._equipmentDetail = null;
        this._controlConfirm = null;
        this._cameraFocus = null;
        this._recordingFocus = null;
        this._render();
      }
      if (action === "onboarding-start") { this._activeTab = "mission"; this._startOnboarding(); }
      if (action === "onboarding-next") this._onboardingNext();
      if (action === "onboarding-back") this._onboardingBack();
      if (action === "onboarding-skip") this._endOnboarding(true);
      if (action === "onboarding-tone") this._toggleTone();
      if (action === "set-controller") { this._setController(target.dataset.id); this._render(); }
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
      if (action === "toggle-buddy") {
        // Persistent on/off from Settings.
        this._setBuddyEnabled(!this._buddyEnabled());
        this._buddy.dismissed = false;
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
      if (action === "focus-camera") { this._cameraFocus = id; this._overlayQuip = this._pickOverlayQuip(); this._render(); this._startCameraWebRTCForFocus(); }
      if (action === "close-camera") { this._stopCameraWebRTC(); this._cameraFocus = null; this._render(); }
      if (action === "refresh-cameras") { this._stopCameraWebRTC(); this._render(); this._startCameraWebRTCForFocus(); }
      if (action === "snapshot-camera") this._snapshotCamera();
      if (action === "share-card") this._shareTankCard();
      if (action === "open-feed") this._openFeedSession(id);
      if (action === "close-feed") this._closeFeedSession();
      if (action === "delete-feed") this._deleteFeedSession(id);
      if (action === "feed-play") this._feedTogglePlay();
      if (action === "feed-reload") this._loadFeedSessions();
      if (action === "fullscreen-camera") {
        const stage = this.shadowRoot.querySelector("[data-camera-stage]");
        if (stage && stage.requestFullscreen) stage.requestFullscreen().catch(() => {});
      }
      if (action === "add-camera") {
        const input = this.shadowRoot.getElementById("or-add-camera-name");
        const label = (input?.value || "").trim();
        this._addCamera(label || "Camera");
      }
      if (action === "remove-camera") this._removeCamera(id);
      if (action === "search-camera") {
        this._searchEntities(`camera:${id}`, this._cameraTarget(id, this._config.cameras[id] || {}));
      }
      if (action === "choose-camera") {
        this._config.cameras[id].entity_id = target.dataset.entity;
        delete this._searchResults[`camera:${id}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "clear-camera") {
        this._config.cameras[id].entity_id = "";
        delete this._searchResults[`camera:${id}`];
        this._setDirty(true);
        this._render();
      }
      if (action === "capture-now") this._captureNow();
      if (action === "open-recording") { this._recordingFocus = id; this._render(); }
      if (action === "close-recording") { this._recordingFocus = null; this._render(); }
      if (action === "delete-recording") this._deleteRecording(id);
      if (action === "timelapse-play") this._timelapseTogglePlay();
      if (action === "timelapse-mode") this._timelapseSetMode(id);
      if (action === "timelapse-grab") this._timelapseGrab();
      if (action === "timelapse-reload") this._loadTimelapseFrames();
      if (action === "timelapse-clear") this._timelapseClear();
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
      if (action === "add-straton-fixture") this._addStratonFixture();
      if (action === "remove-straton-fixture") this._removeStratonFixture(id);
      if (action === "apply-straton-template") this._applyStratonTemplate(id);
      if (action === "preview-straton-template") this._previewStratonTemplate(id);
      if (action === "straton-quick") this._setStratonQuickMode(id);
      if (action === "confirm-straton-program") this._confirmStratonProgram();
      if (action === "add-straton-light-equipment") this._addEquipment("ATI Straton Lights");
      if (action === "analyze-straton-evidence") this._analyzeStratonEvidence();
      if (action === "clear-straton-evidence") this._clearStratonEvidence();
      if (action === "analyze-straton-tester-note") this._analyzeStratonTesterNote();
      if (action === "clear-straton-tester-note") this._clearStratonTesterNote();
      if (action === "load-straton-example-note") this._loadStratonExampleTesterNote();
      if (action === "analyze-straton-fixture-state") this._analyzeStratonFixtureState();
      if (action === "clear-straton-fixture-state") this._clearStratonFixtureState();
      if (action === "probe-straton-fixture-state") this._probeStratonFixtureState();
      if (action === "probe-straton-path") this._probeStratonFixturePath(id);
      if (action === "probe-straton-scan") this._scanStratonProbePaths();
      if (action === "straton-ap-fallback") this._applyStratonApFallback();
      if (action === "copy-straton-evidence") this._copyStratonEvidenceSummary();
      if (action === "copy-straton-adapter-request") this._copyStratonAdapterEvidenceRequest();
      if (action === "copy-straton-program") this._copyStratonProgramPackage();
      if (action === "copy-straton-support") this._copyStratonSupportNote();
      if (action === "copy-straton-beta-update") this._copyStratonBetaUpdate();
      if (action === "copy-straton-tester-steps") this._copyStratonTesterSteps();
      if (action === "import-straton-program") this._importStratonProgramPackage();
      if (action === "clear-straton-program-import") { this._stratonProgramImport = ""; this._render(); }
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
      if (action === "complete-task") this._completeTask(id);
      if (action === "skip-task") this._skipTask(id);
      if (action === "snooze-task") this._snoozeTask(id, Number(target.dataset.days) || 3);
      if (action === "resume-task") this._resumeTask(id);
      if (action === "toggle-task-history") { this._maintenanceHistoryOpen[id] = !this._maintenanceHistoryOpen[id]; this._render(); }
      if (action === "delete-completion") this._deleteCompletion(id, target.dataset.entry);
      if (action === "add-maintenance-task") { const input = this.shadowRoot.getElementById("or-add-task-name"); this._addMaintenanceTask((input?.value || "").trim()); }
      if (action === "remove-maintenance-task") this._removeMaintenanceTask(id);
      if (action === "load-suggested-tasks") this._loadSuggestedTasks();
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

      if (target.dataset.action === "timelapse-seek") { this._timelapseSeek(Number(target.value)); return; }
      if (target.dataset.action === "feed-seek") { this._feedSeek(Number(target.value)); return; }
      if (target.dataset.action === "timelapse-speed") { this._timelapseSetSpeed(Number(target.value)); return; }

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
      if (target.dataset.stratonEvidence) {
        this._stratonEvidence[target.dataset.stratonEvidence] = value;
        return;
      }
      if (target.dataset.stratonProgramImport) {
        this._stratonProgramImport = value;
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
      if (scope === "camera") {
        this._config.cameras = this._config.cameras || {};
        this._config.cameras[id] = this._config.cameras[id] || {};
        this._config.cameras[id][field] = value;
      }
      if (scope === "energy") this._config.energy[field] = value;
      if (scope === "straton") {
        const straton = this._stratonConfig();
        straton[field] = value;
      }
      if (scope === "straton-program") {
        const program = this._stratonProgram();
        if (field === "peak") program[field] = Math.max(0, Math.min(100, Number(value) || 0));
        else if (field === "startTime") program[field] = String(value || "10:00").slice(0, 5);
        else if (field === "photoperiodHours") program[field] = Math.max(1, Math.min(16, Number(value) || 10));
        else if (field === "rampMinutes") program[field] = Math.max(15, Math.min(240, Number(value) || 90));
        else if (field === "acclimationStart" || field === "acclimationTarget") program[field] = Math.max(0, Math.min(100, Number(value) || 0));
        else if (field === "acclimationDays") program[field] = Math.max(1, Math.min(120, Number(value) || 1));
        else if (field === "moonlight") program[field] = Math.max(0, Math.min(5, Number(value) || 0));
        else if (field === "cloudDim") program[field] = Math.max(0, Math.min(60, Number(value) || 0));
        else program[field] = value;
      }
      if (scope === "straton-fixture") {
        const fixture = this._stratonFixtures().find((item) => item.id === id);
        if (fixture) {
          if (field === "selected") fixture[field] = Boolean(value);
          else if (field === "connectionMode") fixture[field] = ["unknown", "lan", "ap"].includes(value) ? value : "unknown";
          else if (field === "setupState") fixture[field] = ["unknown", "already_on_lan", "brand_new", "stuck_setup"].includes(value) ? value : "unknown";
          else fixture[field] = value;
        }
      }
      if (scope === "alerts") {
        this._config.alerts = this._config.alerts || {};
        this._config.alerts[field] = value;
      }
      if (scope === "interlocks") {
        this._config.interlocks = this._config.interlocks || {};
        this._config.interlocks[field] = value;
      }
      if (scope === "capture") {
        this._config.capture = this._config.capture || {};
        this._config.capture[field] = value;
      }
      if (scope === "capture-trigger") {
        this._config.capture = this._config.capture || {};
        this._config.capture.triggers = this._config.capture.triggers || {};
        this._config.capture.triggers[field] = value;
      }
      if (scope === "capture-cameras") {
        this._config.capture = this._config.capture || {};
        const ids = Array.isArray(this._config.capture.cameraIds) ? this._config.capture.cameraIds : [];
        const set = new Set(ids);
        if (value) set.add(id); else set.delete(id);
        this._config.capture.cameraIds = [...set];
      }
      if (scope === "timelapse") {
        this._config.timelapse = this._config.timelapse || {};
        this._config.timelapse[field] = value;
      }
      if (scope === "timelapse-retention") {
        this._config.timelapse = this._config.timelapse || {};
        this._config.timelapse.retention = this._config.timelapse.retention || {};
        this._config.timelapse.retention[field] = value;
      }
      if (scope === "overlay") {
        this._config.overlay = this._config.overlay || {};
        this._config.overlay[field] = value;
      }
      if (scope === "overlay-stats") {
        this._config.overlay = this._config.overlay || {};
        const ids = Array.isArray(this._config.overlay.stats) ? this._config.overlay.stats : [];
        const set = new Set(ids);
        if (value) set.add(id); else set.delete(id);
        this._config.overlay.stats = [...set];
      }
      if (scope === "feedwatch") {
        this._config.feedWatch = this._config.feedWatch || {};
        this._config.feedWatch[field] = value;
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
          const numericValue = Math.max(0, Number(value) || 0);
          this._config.dosing.system[field] = numericValue;
          if (field === "sharedDailyDoseMl") this._syncSharedDosingDose(numericValue);
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
      if (scope === "maintenance") {
        this._config.maintenance = this._config.maintenance || { enabled: true, tasks: {}, completions: {} };
        this._config.maintenance[field] = value;
      }
      if (scope === "maintenance-reminders") {
        this._config.maintenance = this._config.maintenance || { enabled: true, tasks: {}, completions: {} };
        this._config.maintenance.reminders = this._config.maintenance.reminders || {};
        this._config.maintenance.reminders[field] = value;
      }
      if (scope === "maintenance-task") {
        this._config.maintenance = this._config.maintenance || { enabled: true, tasks: {}, completions: {} };
        this._config.maintenance.tasks = this._config.maintenance.tasks || {};
        this._config.maintenance.tasks[id] = this._config.maintenance.tasks[id] || {};
        const task = this._config.maintenance.tasks[id];
        if (field === "cadenceDays") {
          const cadenceDays = Math.max(1, Math.min(365, Number(value) || 1));
          task.cadenceDays = cadenceDays;
          const critical = Number(task.criticalAfterDays);
          if (!Number.isFinite(critical) || critical < cadenceDays) task.criticalAfterDays = Math.min(730, cadenceDays * 2);
        } else if (field === "criticalAfterDays") {
          const cadenceDays = Math.max(1, Number(task.cadenceDays) || 7);
          task.criticalAfterDays = Math.max(cadenceDays, Math.min(730, Number(value) || cadenceDays * 2));
        } else if (field === "scheduleDay") {
          const day = parseInt(target.dataset.day, 10);
          const set = new Set(Array.isArray(task.scheduleDays) ? task.scheduleDays : []);
          if (value) set.add(day); else set.delete(day);
          task.scheduleDays = [...set].filter((n) => Number.isInteger(n) && n >= 0 && n <= 6).sort((a, b) => a - b);
        } else if (field === "scheduleMonthDays") {
          task.scheduleMonthDays = [...new Set(String(value).split(/[^0-9]+/).map((s) => parseInt(s, 10)).filter((n) => Number.isInteger(n) && n >= 1 && n <= 31))].sort((a, b) => a - b);
        } else {
          task[field] = value;
        }
      }
      if (scope) this._setDirty(true);
      if (scope === "display" && field === "themeColor") this._render();
      if (
        (scope === "mode-schedule" || scope === "mode-schedule-time" || scope === "mode-schedule-global" || scope === "manual-tests" || (scope === "manual-test" && ["enabled", "cadenceDays", "criticalAfterDays"].includes(field)) || scope === "maintenance" || scope === "maintenance-reminders" || (scope === "maintenance-task" && ["enabled", "cadenceDays", "criticalAfterDays", "scheduleMode", "scheduleDay", "notify", "logsVolume"].includes(field)) || scope === "straton" || scope === "straton-program" || scope === "straton-fixture" || scope === "dosing-system" || (scope === "dosing" && field === "productPreset") || (scope === "equipment" && field === "type") || (scope === "tank" && field === "profile"))
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
      light_entity_id: "",
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
        light_entity_id: "",
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
    if (field === "light_entity_id") {
      return {
        ...base,
        domains: ["light"],
        keywords: [label, "straton", "light", "reef", "aquarium"],
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

  _entityDomain(entityId) {
    return String(entityId || "").split(".")[0] || "";
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
      cameras: saved.cameras === true || (this._cameraList().some(([, c]) => c.entity_id) && saved.cameras !== false),
      maintenance: saved.maintenance === true || (this._maintenanceConfig().enabled && this._maintenanceTaskList().some(([id]) => this._maintenanceTask(id).enabled) && saved.maintenance !== false),
    };
  }

  _missionCardChoices() {
    return [
      ["health", "Reef Health", "Show an explainable 0-100 health score."],
      ["dosing", "Dosing Advisor", "Show consumption, projections, and advisory dose tips."],
      ["cameras", "Live Camera", "Show a live tank snapshot that opens the Cameras tab."],
      ["live", "Live Stats", "Show mapped sensor readings in Mission Control."],
      ["controls", "Controls", "Show armed equipment status in Mission Control."],
      ["energy", "Energy", "Show energy and cost summaries in Mission Control."],
      ["maintenance", "Maintenance", "Show how many maintenance tasks are due or overdue."],
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
      sharedDailyDoseMl: 0,
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
      sharedDailyDoseMl: Math.max(0, Number(raw.sharedDailyDoseMl) || 0),
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

  _syncSharedDosingDose(value) {
    const dose = Math.max(0, Number(value) || 0);
    this._config.dosing = this._config.dosing || { enabled: true, parameters: {}, system: {} };
    this._config.dosing.parameters = this._config.dosing.parameters || {};
    this._dosingParameterIds().forEach((id) => {
      this._config.dosing.parameters[id] = this._config.dosing.parameters[id] || {};
      this._config.dosing.parameters[id].doserMlPerDay = dose;
    });
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
        note: "Balanced all-in-one maintenance. Start and adjust slowly from test trends; use separate corrections if parameters are unbalanced before relying on All-For-Reef.",
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
        maxDosePer25LitresMl: 4,
        exactParameters: {
          calcium: { productDoseMl: 1, productVolumeLitres: 25, productRaise: 4 },
          alkalinity: { productDoseMl: 1, productVolumeLitres: 25, productRaise: 0.493 },
        },
        note: "Exact-strength two-part preset. Dose parts separately, never mix the two bottles directly, and verify against the bottle before acting.",
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
        note: "Alkalinity-led balanced maintenance system. Dose the two parts separately and tune from alkalinity trend before leaning on calcium/magnesium.",
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
        classId: "balling_three_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        requiresCustomStrength: true,
        exactMaintenance: true,
        exactCorrection: false,
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
        note: "Two-part system with variant-specific strength. Enter the strength from your actual bottle/recipe before exact mL advice appears.",
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
      {
        id: "brightwell_reef_code_ab",
        label: "Brightwell Reef Code A/B",
        brand: "Brightwell",
        classId: "equal_part_two_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium"],
        exactMaintenance: true,
        exactCorrection: true,
        exactParameters: {
          calcium: { productDoseMl: 1, productVolumeLitres: 3.785, productRaise: 16 },
          alkalinity: { productDoseMl: 1, productVolumeLitres: 3.785, productRaise: 2.22 },
        },
        note: "Exact-strength two-part preset. Dose A and B separately, and allow unequal daily amounts if calcium and alkalinity consumption differ.",
      },
      {
        id: "brightwell_kalk_plus_2",
        label: "Brightwell Kalk+2",
        brand: "Brightwell",
        classId: "kalkwasser",
        roles: ["secondary"],
        parameters: ["alkalinity", "calcium"],
        note: "Kalkwasser-style support with calcium/strontium/magnesium claims. Still high-pH and evaporation-limited, so OpenReef treats it as support only.",
      },
      {
        id: "red_sea_complete_reef_care_7",
        label: "Red Sea Foundation + Trace Colors 7-part",
        brand: "Red Sea",
        classId: "measured_uptake_multi_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Precision multi-bottle method. Track Foundation and Trace Colors separately; OpenReef gives measured-uptake guidance, not a collapsed one-bottle correction.",
      },
      {
        id: "tropic_marin_original_balling",
        label: "Tropic Marin Original Balling",
        brand: "Tropic Marin",
        classId: "balling_three_part",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        requiresCustomStrength: true,
        exactMaintenance: true,
        exactCorrection: false,
        note: "Three-part Balling method. Part C maintains ionic balance; enter your verified recipe strength before exact mL maintenance advice appears.",
      },
      {
        id: "calcium_reactor",
        label: "Calcium reactor",
        brand: "Generic",
        classId: "calcium_reactor",
        roles: ["primary"],
        parameters: ["alkalinity", "calcium", "magnesium"],
        note: "Reactor tuning workflow. OpenReef advises from Alk/Ca/Mg trends, pH context, and slow effluent/CO2 review rather than bottle mL corrections.",
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
      measured_uptake_multi_part: "Measured-uptake multi-part",
      balling_three_part: "Balling three-part",
      calcium_reactor: "Calcium reactor",
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

  _dosingProductDailyMaxMl(product, system = this._dosingSystem()) {
    const maxPer25Litres = Number(product?.maxDosePer25LitresMl) || 0;
    const tankVolume = Number(system?.tankVolumeLitres) || 0;
    return maxPer25Litres > 0 && tankVolume > 0 ? maxPer25Litres * (tankVolume / 25) : 0;
  }

  _dosingUsesSharedDose(product) {
    return product?.classId === "single_solution_balanced";
  }

  _dosingSharedDailyDoseMl(product = this._dosingProduct(this._dosingSystem().primaryProduct), system = this._dosingSystem()) {
    if (!this._dosingUsesSharedDose(product)) return 0;
    const direct = Number(system?.sharedDailyDoseMl);
    if (Number.isFinite(direct) && direct > 0) return Math.max(0, direct);
    const legacyDoses = this._dosingParameterIds()
      .filter((id) => this._dosingProductSupportsParameter(product, id))
      .map((id) => Number(this._dosingParamConfig(id).doserMlPerDay) || 0)
      .filter((value) => value > 0);
    return legacyDoses.length ? legacyDoses[0] : 0;
  }

  _dosingCurrentDoseMlForParameter(sensorId, config = this._dosingParamConfig(sensorId), product = this._dosingProductForParameter(sensorId)) {
    if (this._dosingUsesSharedDose(product)) return this._dosingSharedDailyDoseMl(product);
    return Math.max(0, Number(config?.doserMlPerDay) || 0);
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

  _dosingMinimumCustomPotency(sensorId) {
    if (sensorId === "alkalinity") return 0.001;
    if (sensorId === "calcium") return 0.02;
    if (sensorId === "magnesium") return 0.02;
    return 0.0001;
  }

  _dosingCustomExactAdviceLimitMl(system, currentDoseMlPerDay = 0) {
    const tankVolume = Number(system?.tankVolumeLitres) || 0;
    const volumeLimit = tankVolume > 0 ? tankVolume * 1.5 : 250;
    const doseLimit = currentDoseMlPerDay > 0
      ? Math.max(currentDoseMlPerDay * 1.5, currentDoseMlPerDay + 100)
      : 250;
    return Math.max(100, Math.min(volumeLimit, doseLimit));
  }

  _dosingCustomExactAdviceRisk(sensorId, sensor, product, potencyInfo, safety, advice = {}) {
    const customStrengthProduct = product?.requiresCustomStrength || product?.classId === "custom_verified_strength";
    if (!customStrengthProduct || potencyInfo.value <= 0 || !["calculator", "manual"].includes(potencyInfo.source)) {
      return null;
    }
    const unit = sensor?.unit || "units";
    const minPotency = this._dosingMinimumCustomPotency(sensorId);
    const limit = this._dosingCustomExactAdviceLimitMl(this._dosingSystem(), safety.currentDose);
    const checkValues = [
      advice.suggestedDoseMlPerDay,
      advice.reviewDoseMlPerDay,
      advice.dailyCorrectionMl,
    ].filter((value) => Number.isFinite(value) && value > 0);
    const highestAdvice = checkValues.length ? Math.max(...checkValues) : 0;
    if (potencyInfo.value < minPotency) {
      return {
        limit,
        detail: `${product.label} strength looks implausibly weak (${this._format(potencyInfo.value, 4)} ${unit}/mL). Check the recipe or "1 mL raises X in Y L" fields before changing a doser.`,
      };
    }
    if (highestAdvice > limit) {
      return {
        limit,
        detail: `${product.label} advice would require about ${this._formatDoseMl(highestAdvice)}, above OpenReef's conservative custom-product review limit of ${this._formatDoseMl(limit)}. Verify the product strength or set a safer dosing approach before changing a doser.`,
      };
    }
    return null;
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
    const exact = product?.exactParameters?.[sensorId] || null;
    const tankVolume = Number(system?.tankVolumeLitres) || Number(config?.tankVolumeLitres) || 0;
    const productDose = this._dosingPresetNumber(config, exact, "productDoseMl");
    const productVolume = this._dosingPresetNumber(config, exact, "productVolumeLitres");
    const productRaise = this._dosingPresetNumber(config, exact, "productRaise");
    const exactCorrectionAllowed = product?.exactCorrection === false
      ? false
      : product?.classId !== "kalkwasser";
    if (manual > 0) {
      return {
        value: manual,
        source: "manual",
        exactMaintenance: true,
        exactCorrection: exactCorrectionAllowed,
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
    if ((product.requiresCustomStrength || product.classId === "custom_verified_strength") && productDose > 0 && productVolume > 0 && productRaise > 0 && tankVolume <= 0) {
      return {
        value: 0,
        source: "calculator",
        exactMaintenance: true,
        exactCorrection: exactCorrectionAllowed,
        label: `${product.label}: enter net tank water volume before exact mL advice appears`,
      };
    }
    if (calculated.value > 0) {
      const source = product?.exactParameters?.[sensorId] ? "preset" : "calculator";
      const verifiedRecipe = product.requiresCustomStrength === true || product.classId === "custom_verified_strength";
      return {
        value: calculated.value,
        source,
        exactMaintenance: product.exactMaintenance === true || verifiedRecipe,
        exactCorrection: product.exactCorrection === false ? false : product.exactCorrection === true || verifiedRecipe,
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

  _dosingFreshManualGate(sensorId, source = "manual") {
    if (source !== "manual") {
      return {
        fresh: true,
        detail: "Mapped chemistry history is current enough for advisory trend checks.",
        status: "ok",
      };
    }
    const freshness = this._manualDosingFreshness(sensorId);
    return {
      fresh: freshness.fresh,
      detail: freshness.detail,
      status: freshness.status,
    };
  }

  _dosingSafetyState(sensorId, sensor, product, potencyInfo, config, source) {
    const system = this._dosingSystem();
    const currentDose = this._dosingCurrentDoseMlForParameter(sensorId, config, product);
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
    const manual = this._dosingFreshManualGate(sensorId, source);
    if (potencyInfo.exactCorrection && !manual.fresh) warnings.push(`Correction advice locked: ${manual.detail}`);
    const productDailyMaxMl = this._dosingProductDailyMaxMl(product, system);
    if (product?.id === "seachem_reef_fusion") {
      warnings.push("Dose Reef Fusion 1 and 2 separately in a high-flow area; never mix the two bottles directly.");
    }
    if (product?.id === "brs_pharma_two_part") {
      warnings.push("Dose DIY calcium, alkalinity, and magnesium parts separately in high flow; monitor salinity and pH while using concentrated two/three-part additives.");
    }
    if (product?.id === "esv_b_ionic") {
      warnings.push("Dose ESV B-Ionic parts separately in high flow, verify the exact bottle strength, and never allow pH to rise above the product safety ceiling.");
    }
    if (product?.id === "ati_essentials") {
      warnings.push("ATI Essentials advice is alkalinity-led maintenance guidance. Dose the parts separately, confirm your exact Essentials version, and retest before changing a doser.");
    }
    if (product?.id === "red_sea_complete_reef_care_4") {
      warnings.push("Red Sea Complete Reef Care is calcium-led maintenance guidance. Use the Red Sea method/calculator for separate correction steps; OpenReef does not collapse the four bottles into one correction.");
    }
    if (product?.id === "triton_core7_flex") {
      warnings.push("TRITON Core7 Flex is ICP-guided maintenance. Review trends and ICP/test results before changing the equal-base dose; OpenReef does not give one-off correction maths for Core7.");
    }
    if (product?.id === "fauna_marin_balling_light") {
      warnings.push("Fauna Marin Balling Light is recipe-dependent. Dose the Balling Light solutions separately and only use exact mL advice after entering your verified recipe strength.");
    }
    if (product?.id === "brightwell_reef_code_ab") {
      warnings.push("Dose Brightwell Reef Code A and B separately in high flow; do not mix concentrates, and remember this preset does not cover magnesium.");
    }
    if (product?.id === "brightwell_kalk_plus_2") {
      warnings.push("Brightwell Kalk+2 is still high-pH kalkwasser-style support. Do not use it as a magnesium correction product.");
    }
    if (product?.id === "red_sea_complete_reef_care_7") {
      warnings.push("Red Sea Foundation and Trace Colors are measured separately. OpenReef gives uptake guidance, not a combined seven-bottle correction.");
    }
    if (product?.id === "tropic_marin_original_balling") {
      warnings.push("Tropic Marin Original Balling uses separate A/B/C parts; Part C supports ionic balance and should not be treated as a normal calcium or alkalinity correction bottle.");
    }
    if (product?.id === "calcium_reactor") {
      warnings.push("Calcium reactor advice is tuning guidance. Adjust effluent/CO2 slowly and watch tank pH and alkalinity before making another change.");
    }
    const secondary = this._dosingProduct(system.secondaryProduct);
    const secondaryIsKalk = secondary?.classId === "kalkwasser" && product?.classId !== "kalkwasser" && ["alkalinity", "calcium"].includes(sensorId);
    if (secondaryIsKalk) {
      kalkContext = this._kalkSafetyContext(system);
      warnings.push("Secondary kalkwasser support is configured; keep exact corrections on the primary dosing system and do not use kalkwasser as a one-off correction.");
      if (!kalkContext.hasPhGuard) {
        warnings.push("No mapped pH guard is available for secondary kalkwasser context.");
      } else if (!Number.isFinite(kalkContext.phValue)) {
        warnings.push("Mapped pH guard for secondary kalkwasser is unavailable or non-numeric right now.");
      } else if (kalkContext.phStatus === "high") {
        warnings.push(`Current pH ${this._format(kalkContext.phValue, 2)} is at or above the secondary kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser.`);
      } else if (kalkContext.phStatus === "near") {
        warnings.push(`Current pH ${this._format(kalkContext.phValue, 2)} is close to the secondary kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser without reviewing the pH pattern.`);
      } else {
        warnings.push(`Secondary kalk pH guard OK: current pH ${this._format(kalkContext.phValue, 2)} is below the max pH ${this._format(kalkContext.maxPh, 2)}.`);
      }
      if (!system.secondaryDelivery) warnings.push("Choose how secondary kalkwasser is delivered: ATO, dosing pump, or manual top-off.");
      if (!kalkContext.capacityConfigured) {
        warnings.push("Secondary kalk capacity is not fully configured. Add daily kalk volume, concentration, and evaporation ceiling before judging whether kalk can help.");
      }
    }
    if (productDailyMaxMl > 0 && currentDose > 0) {
      if (currentDose > productDailyMaxMl) {
        locks.push(`Current ${product?.label || "product"} dose ${this._formatDoseMl(currentDose)} is above the product daily maximum of ${this._formatDoseMl(productDailyMaxMl)} for this tank.`);
      } else if (currentDose >= productDailyMaxMl * 0.9) {
        warnings.push(`Current ${product?.label || "product"} dose ${this._formatDoseMl(currentDose)} is close to the product daily maximum of ${this._formatDoseMl(productDailyMaxMl)} for this tank.`);
      }
    }
    if (product?.classId === "kalkwasser") {
      kalkContext = this._kalkSafetyContext(system);
      warnings.push("Kalkwasser is high-pH and evaporation-limited. Do not use it as a one-off correction bolus.");
      if (!kalkContext.hasPhGuard) {
        warnings.push("No mapped pH guard is available for kalkwasser context.");
      } else if (!Number.isFinite(kalkContext.phValue)) {
        warnings.push("Mapped pH guard is unavailable or non-numeric right now.");
      } else if (kalkContext.phStatus === "high") {
        locks.push(`Kalkwasser high-pH safety lock: current pH ${this._format(kalkContext.phValue, 2)} is at or above the kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser.`);
      } else if (kalkContext.phStatus === "near") {
        warnings.push(`Current pH ${this._format(kalkContext.phValue, 2)} is close to the kalk max pH ${this._format(kalkContext.maxPh, 2)}. Do not increase kalkwasser without reviewing the pH pattern.`);
      } else {
        warnings.push(`pH guard OK: current pH ${this._format(kalkContext.phValue, 2)} is below the kalk max pH ${this._format(kalkContext.maxPh, 2)}.`);
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
      if (warning.startsWith("pH guard OK:")) return false;
      if (warning.startsWith("Dose Reef Fusion 1 and 2 separately")) return false;
      if (warning.startsWith("Dose DIY calcium, alkalinity, and magnesium parts separately")) return false;
      if (warning.startsWith("Dose ESV B-Ionic parts separately")) return false;
      if (warning.startsWith("ATI Essentials advice is alkalinity-led")) return false;
      if (warning.startsWith("Red Sea Complete Reef Care is calcium-led")) return false;
      if (warning.startsWith("TRITON Core7 Flex is ICP-guided")) return false;
      if (warning.startsWith("Fauna Marin Balling Light is recipe-dependent")) return false;
      if (warning.startsWith("Dose Brightwell Reef Code A and B separately")) return false;
      if (warning.startsWith("Brightwell Kalk+2 is still high-pH")) return false;
      if (warning.startsWith("Red Sea Foundation and Trace Colors are measured separately")) return false;
      if (warning.startsWith("Tropic Marin Original Balling uses separate A/B/C parts")) return false;
      if (warning.startsWith("Calcium reactor advice is tuning guidance")) return false;
      if (warning.startsWith("Secondary kalkwasser support is configured")) return false;
      if (warning.startsWith("Secondary kalk pH guard OK:")) return false;
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
    if (slope > 0) {
      return `Net rise ~${rateText}. Do not increase kalkwasser. Review whether the current kalk routine is too strong or whether evaporation/pH timing has changed before making further changes.`;
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
    return `Kalkwasser appears steady. Keep monitoring pH and evaporation before changing the routine.`;
  }

  _allForReefDoseContext(currentDoseMlPerDay = 0, system = this._dosingSystem()) {
    const tankVolume = Number(system?.tankVolumeLitres) || 0;
    const startDoseMl = tankVolume > 0 ? tankVolume * 0.05 : 0; // 5 mL / 100 L daily.
    const weeklyStepMl = tankVolume > 0 ? tankVolume * 0.025 : 0; // 2.5 mL / 100 L weekly review step.
    const maxDoseMl = tankVolume > 0 ? tankVolume * 0.25 : 0; // 25 mL / 100 L daily.
    const currentDose = Math.max(0, Number(currentDoseMlPerDay) || 0);
    return {
      tankVolume,
      currentDose,
      startDoseMl,
      weeklyStepMl,
      maxDoseMl,
      nearMax: maxDoseMl > 0 && currentDose >= maxDoseMl * 0.9,
      atOrAboveMax: maxDoseMl > 0 && currentDose >= maxDoseMl,
    };
  }

  _allForReefDoseContextText(context) {
    if (!context.tankVolume) {
      return "Enter net tank volume before OpenReef can compare your All-For-Reef dose with Tropic Marin's start, weekly review, and maximum guidance.";
    }
    return `For ${this._format(context.tankVolume, 0)} L, Tropic Marin's guidance works out to roughly ${this._formatDoseMl(context.startDoseMl)} to start, ${this._formatDoseMl(context.weeklyStepMl)} maximum weekly review step, and ${this._formatDoseMl(context.maxDoseMl)} maximum daily dose.`;
  }

  _allForReefMaintenanceText(label, sensorId, slope, rateText, safety, currentDoseMlPerDay) {
    const context = this._allForReefDoseContext(currentDoseMlPerDay);
    const doseContext = this._allForReefDoseContextText(context);
    if (!safety.manual.fresh) {
      return `${label} manual tests are not fresh enough for All-For-Reef advice. Retest before changing the daily dose.`;
    }
    if (!context.tankVolume) {
      return `${doseContext} Do not change the daily dose from OpenReef guidance yet.`;
    }
    const calciumRegulator = sensorId === "calcium"
      ? " Tropic Marin recommends using calcium as the regular dose regulator once All-For-Reef is established, while still checking alkalinity and magnesium."
      : "";
    const imbalanceGuard = " If calcium, alkalinity, and magnesium are not moving together, correct the imbalance separately first; do not use All-For-Reef as a one-off correction product.";
    if (context.atOrAboveMax && slope < 0) {
      return `Net loss ~${rateText}. Current All-For-Reef dose ${this._formatDoseMl(context.currentDose)} is at or above the ${this._formatDoseMl(context.maxDoseMl)} max for this tank. Do not increase All-For-Reef beyond the max; retest, correct separately if needed, or add a different primary system.${calciumRegulator}${imbalanceGuard}`;
    }
    if (context.nearMax && slope < 0) {
      return `Net loss ~${rateText}. Current All-For-Reef dose ${this._formatDoseMl(context.currentDose)} is close to the ${this._formatDoseMl(context.maxDoseMl)} max for this tank. Review only a small weekly increase up to ${this._formatDoseMl(context.weeklyStepMl)} if fresh tests agree, then retest. If demand keeps rising, add a different primary system.${calciumRegulator}${imbalanceGuard}`;
    }
    if (slope < 0) {
      return `Net loss ~${rateText}. All-For-Reef is a maintenance system: review increasing the total daily dose by no more than ${this._formatDoseMl(context.weeklyStepMl)} this week (current ${this._formatDoseMl(context.currentDose)}, max ${this._formatDoseMl(context.maxDoseMl)}), then retest calcium and alkalinity.${calciumRegulator}${imbalanceGuard}`;
    }
    if (slope > 0) {
      return `Net rise ~${rateText}. Review holding or reducing the total daily All-For-Reef dose by up to ${this._formatDoseMl(context.weeklyStepMl)} this week (current ${this._formatDoseMl(context.currentDose)}), then retest. Do not add a chemical correction downward.${calciumRegulator}${imbalanceGuard}`;
    }
    return `All-For-Reef appears steady. ${doseContext} Keep the dose consistent and retest on your chosen schedule.${calciumRegulator}`;
  }

  _allForReefCorrectionText(label) {
    return `Do not use Tropic Marin All-For-Reef as a one-off ${label} correction. Bring calcium, alkalinity, and magnesium into balance with separate correction products or water changes first, then use All-For-Reef for maintenance.`;
  }

  _aquaforestMaintenanceText(label, sensorId, slope, rateText, safety, currentDoseMlPerDay) {
    if (!safety.manual.fresh) {
      return `${label} tests are not fresh enough for Aquaforest Component 1+2+3+ advice. Retest before changing the equal daily dose.`;
    }
    const currentDose = this._formatDoseMl(currentDoseMlPerDay);
    const balanceGuard = " Aquaforest guidance keeps Components 1, 2, and 3 dosed equally; if one or two parameters are out of balance, correct them separately first, then return to equal maintenance dosing.";
    if (slope < 0) {
      return `Net loss ~${rateText}. Review whether the equal daily Component 1+2+3+ dose (${currentDose}) is no longer keeping up, then increase the equal dose only after fresh calcium, KH, and magnesium tests agree.${balanceGuard}`;
    }
    if (slope > 0) {
      return `Net rise ~${rateText}. Review holding or reducing the equal daily Component 1+2+3+ dose (${currentDose}) and retest. Do not use chemical correction downward.${balanceGuard}`;
    }
    return `Aquaforest Component 1+2+3+ appears steady at ${currentDose}. Keep the three parts equal and retest on your chosen schedule.`;
  }

  _aquaforestCorrectionText(label) {
    return `Do not use Aquaforest Component 1+2+3+ as a one-off ${label} correction. Keep the three components equal for maintenance and use a separate calcium, KH, magnesium, or water-change correction plan if the parameters are unbalanced.`;
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
    const productInfo = this._dosingProductForParameter(sensorId);
    const currentDoseMlPerDay = this._dosingCurrentDoseMlForParameter(sensorId, paramConfig, productInfo);
    const potencyInfo = this._dosingEffectivePotency(sensorId, sensor, paramConfig, productInfo);
    const safety = this._dosingSafetyState(sensorId, sensor, productInfo, potencyInfo, paramConfig, source);
    const potency = potencyInfo.value;
    const productDailyMaxMl = this._dosingProductDailyMaxMl(productInfo);
    const target = Number(paramConfig.target) || 0;
    const holdOffsetUnits = -slope; // +ve => add this many units/day to hold steady
    const maxDailyAdjustmentUnits = this._dosingDailyAdjustmentLimit(sensorId, sensor);
    const correctionUnitsToTarget = target > 0 ? target - value : 0;
    const correctionSignalStrong = target > 0 && Math.abs(correctionUnitsToTarget) >= this._dosingMinimumSignal(sensorId, sensor);
    let extraMlPerDay = null;
    let correctionMl = null;
    let dailyCorrectionMl = null;
    let suggestedDoseMlPerDay = null;
    let reviewDoseMlPerDay = null;
    let correctionText = "";
    let customMaintenanceAdviceRisk = null;
    let customCorrectionAdviceRisk = null;
    const productSupportsParameter = !productInfo.id || this._dosingProductSupportsParameter(productInfo, sensorId);
    const unsupportedProduct = productInfo.id && !productSupportsParameter;
    if (potency > 0 && safety.canExactMaintenance) {
      const cappedHoldOffsetUnits = Math.max(-maxDailyAdjustmentUnits, Math.min(holdOffsetUnits, maxDailyAdjustmentUnits));
      extraMlPerDay = cappedHoldOffsetUnits / potency;
      suggestedDoseMlPerDay = Math.max(0, currentDoseMlPerDay + holdOffsetUnits / potency);
      reviewDoseMlPerDay = Math.max(0, currentDoseMlPerDay + extraMlPerDay);
      if (productDailyMaxMl > 0) {
        reviewDoseMlPerDay = Math.min(reviewDoseMlPerDay, productDailyMaxMl);
      }
      if (target > 0 && safety.canExactCorrection && correctionSignalStrong) {
        const correctionUnits = correctionUnitsToTarget;
        correctionMl = correctionUnits / potency;
        if (correctionUnits > 0) {
          const productCorrectionLimitUnits = productDailyMaxMl > 0
            ? Math.max(0, productDailyMaxMl - currentDoseMlPerDay) * potency
            : Infinity;
          const dailyCorrectionLimitUnits = Math.min(maxDailyAdjustmentUnits, productCorrectionLimitUnits);
          const correctionDays = dailyCorrectionLimitUnits > 0
            ? Math.max(1, Math.ceil(correctionUnits / dailyCorrectionLimitUnits))
            : null;
          if (correctionDays === null) {
            correctionText = productDailyMaxMl > 0
              ? ` Correction dosing is locked because the current daily dose is already at the product maximum of ${this._formatDoseMl(productDailyMaxMl)} for this tank.`
              : " Correction dosing is locked until a safe daily correction limit is available.";
          } else {
            const dailyCorrectionUnits = correctionUnits / correctionDays;
            dailyCorrectionMl = Math.max(0, dailyCorrectionUnits / potency);
            correctionText = ` If correcting toward ${this._format(target, digits)}${unitSuffix}, split it across about ${correctionDays} day${correctionDays === 1 ? "" : "s"} (roughly ${this._format(dailyCorrectionMl, 1)} mL/day), then retest.`;
            if (productDailyMaxMl > 0) {
              correctionText += ` Do not exceed ${this._formatDoseMl(productDailyMaxMl)} total ${productInfo.label} per day for this tank.`;
            }
          }
        } else if (correctionUnits < 0) {
          correctionText = " Target is below the current reading; do not use a one-off chemical correction downward. Let normal consumption or water changes bring it down gradually.";
        }
      }
    }
    customMaintenanceAdviceRisk = this._dosingCustomExactAdviceRisk(sensorId, sensor, productInfo, potencyInfo, safety, {
      suggestedDoseMlPerDay,
      reviewDoseMlPerDay,
    });
    customCorrectionAdviceRisk = this._dosingCustomExactAdviceRisk(sensorId, sensor, productInfo, potencyInfo, safety, {
      dailyCorrectionMl,
    });
    if (customMaintenanceAdviceRisk) {
      extraMlPerDay = null;
      suggestedDoseMlPerDay = null;
      reviewDoseMlPerDay = null;
    }
    if (customCorrectionAdviceRisk) {
      correctionMl = null;
      dailyCorrectionMl = null;
      correctionText = "";
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
    } else if (productInfo.id === "tropic_marin_all_for_reef") {
      maintenanceText = this._allForReefMaintenanceText(label, sensorId, slope, rateText, safety, currentDoseMlPerDay);
    } else if (productInfo.id === "aquaforest_component_123") {
      maintenanceText = this._aquaforestMaintenanceText(label, sensorId, slope, rateText, safety, currentDoseMlPerDay);
    } else if (slope < 0) {
      if (customMaintenanceAdviceRisk) {
        maintenanceText = `Net loss ~${rateText}. Exact custom mL advice is locked: ${customMaintenanceAdviceRisk.detail}`;
      } else if (potency > 0 && safety.canExactMaintenance) {
        const capped = Math.abs(holdOffsetUnits) > maxDailyAdjustmentUnits;
        maintenanceText = `Net loss ~${rateText}. Current dose ${this._formatDoseMl(currentDoseMlPerDay)}; estimated holding dose ${this._formatDoseMl(suggestedDoseMlPerDay)}. `;
        const maxCapped = productDailyMaxMl > 0 && suggestedDoseMlPerDay > productDailyMaxMl;
        maintenanceText += maxCapped
          ? `Suggested holding dose is above the product maximum of ${this._formatDoseMl(productDailyMaxMl)} for this tank. Do not increase past that limit; retest and consider another dosing approach if demand keeps rising.`
          : capped
          ? `Use ${this._formatDoseMl(reviewDoseMlPerDay)} as the first review step because OpenReef limits advice to ${this._format(maxDailyAdjustmentUnits, rateDigits)}${unitSuffix}/day.`
          : `Suggested next dose ${this._formatDoseMl(reviewDoseMlPerDay)}.`;
      } else if (potency > 0 && !safety.canExactMaintenance) {
        maintenanceText = `Net loss ~${rateText}. Exact mL maintenance advice is locked: ${safety.locks.concat(currentDoseMlPerDay <= 0 ? ["enter the current daily dose"] : []).join(" ")}`;
      } else {
        maintenanceText = `Net loss ~${rateText}. ${productInfo.note || "Increase daily dosing only after confirming with a manual test."}`;
      }
    } else if (customMaintenanceAdviceRisk) {
      maintenanceText = `Net rise ~${rateText}. Exact custom mL advice is locked: ${customMaintenanceAdviceRisk.detail}`;
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
      } else if (target > 0 && !correctionSignalStrong) {
        correctionText = "No correction advice because the current reading is close enough to target for this test.";
      } else if (!target) {
        correctionText = "Set a target in Settings before OpenReef discusses correction dosing.";
      } else if (productInfo.classId === "kalkwasser") {
        correctionText = "Do not use kalkwasser as a one-off correction bolus.";
      } else if (productInfo.id === "tropic_marin_all_for_reef") {
        correctionText = this._allForReefCorrectionText(label);
      } else if (productInfo.id === "aquaforest_component_123") {
        correctionText = this._aquaforestCorrectionText(label);
      } else if (target < value) {
        correctionText = "Do not chemically correct downward. Let normal consumption or water changes bring the value down gradually.";
      } else if (customCorrectionAdviceRisk) {
        correctionText = `Correction dosing is locked: ${customCorrectionAdviceRisk.detail}`;
      } else if (!safety.canExactCorrection) {
        correctionText = `Correction dosing is locked: ${safety.locks.concat(safety.warnings).join(" ") || "fresh manual test required."}`;
      } else if (correctionMl !== null) {
        correctionText = `Advisory correction total is about ${this._format(Math.max(0, correctionMl), 1)} mL, split across safe daily steps and verified with fresh tests.`;
      }
    }

    const customAdviceRisk = customMaintenanceAdviceRisk || customCorrectionAdviceRisk;
    const safetyText = customAdviceRisk
      ? `Review product strength: ${customAdviceRisk.detail}`
      : safety.locks.length
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
        : productInfo.id === "tropic_marin_all_for_reef"
          ? "Do not use All-For-Reef for one-off correction doses."
        : "";
    const doseText = [maintenanceText, correctionText, doNotDoseText].filter(Boolean).join(" ");

    let status = "ok";
    if (projectionDays !== null) {
      if (projectionDays <= 3) status = "critical";
      else if (projectionDays <= 10) status = "warning";
    }
    if (safety.status === "locked" && status === "ok") status = "learning";
    if (safety.status === "warning" && status === "ok") status = "warning";
    if (customAdviceRisk && status === "ok") status = "warning";
    if (unsupportedProduct && (status === "learning" || noUsefulMovement)) status = "ok";

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
        : customAdviceRisk
          ? "warning"
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
      customExactAdviceRisk: customAdviceRisk,
      customMaintenanceAdviceRisk,
      customCorrectionAdviceRisk,
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
      steady: "Steady",
      "not-covered": "Not covered",
    }[item.recommendationState] || "Advisor";
    const statePillClass = item.recommendationState === "ready" || item.recommendationState === "steady"
      ? "ok"
      : item.recommendationState === "locked" || item.recommendationState === "warning"
        ? "warning"
        : "unknown";
    return `
      <article class="dosing-card ${statusClass}">
        <div class="dosing-card-head">
          <span>${this._escape(item.label)}</span>
          <strong>${this._escape(currentText)}</strong>
        </div>
        <div class="pill ${statePillClass}">${this._escape(stateLabel)}</div>
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

    this._maintenanceFreshnessItems().forEach((item) => {
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
      this._dosingUsesSharedDose(primary) ? `Shared daily dose: ${this._dosingSharedDailyDoseMl(primary, system) ? this._formatDoseMl(this._dosingSharedDailyDoseMl(primary, system)) : "not set"}` : "",
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
        const light = item.light_entity_id ? `, light ${item.light_entity_id}` : "";
        return `- ${item.label || id}: ${profile}, switch ${item.switch_entity_id || "not mapped"}${light}, ${item.armed ? "armed" : "disarmed"}, ${state}`;
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

  // Controller override: "auto" (detect from entities), "apex", "other", or "none".
  _controllerSetting() {
    try { return window.localStorage?.getItem("openreef:controller") || "auto"; }
    catch { return "auto"; }
  }

  _setController(value) {
    try { window.localStorage?.setItem("openreef:controller", value); } catch { /* ignore */ }
  }

  _detectApex() {
    const ids = [];
    Object.values(this._config?.sensors || {}).forEach((s) => { if (s.entity_id) ids.push(s.entity_id); });
    Object.values(this._config?.equipment || {}).forEach((e) => {
      if (e.switch_entity_id) ids.push(e.switch_entity_id);
      if (e.light_entity_id) ids.push(e.light_entity_id);
      if (e.power_entity_id) ids.push(e.power_entity_id);
    });
    return ids.some((id) => /apex|trident|neptune|fusion/i.test(id));
  }

  // Whether to use the anti-Apex jokes (vs the reef-focused set).
  _hasApex() {
    const c = this._controllerSetting();
    if (c === "apex") return true;
    if (c === "no" || c === "none" || c === "other") return false;
    return this._detectApex();
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
      img.onload = () => { this._avatarPoses[pose] = true; if (!this._isEditingFormControl()) this._render(); };
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

  // Aim the spotlight + (desktop) narrator at the card's CURRENT position. Safe to
  // call every frame, so it tracks a card while the page smooth-scrolls.
  _aimOnboarding(anchorEl, snap = false) {
    const narrator = this.shadowRoot.querySelector(".or-narrator");
    const spotlight = this.shadowRoot.querySelector(".or-spotlight");
    if (!narrator || !spotlight) return;
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
      centreX = vw / 2;
      top = Math.max(m, (vh - nh) / 2);
    }
    const left = Math.round(Math.max(m, Math.min(centreX - nw / 2, vw - nw - m)));
    top = Math.round(top);
    if (snap) narrator.style.transition = "none";
    narrator.style.left = `${left}px`;
    narrator.style.top = `${top}px`;
    narrator.style.right = "auto";
    narrator.style.bottom = "auto";
    narrator.style.transform = "none";
    if (snap) { void narrator.offsetWidth; narrator.style.transition = ""; }
    this._onboarding.pos = { left, top };
  }

  // rAF loop: tracks the card each frame (so the spotlight + guide follow the page
  // as it smooth-scrolls) and plays the walk frames; ends back on the frontal pose.
  _trackOnboarding(anchorEl, dir) {
    cancelAnimationFrame(this._onboarding.walkRaf);
    const walkAnim = this._onboarding.walking && this._walkReady && window.innerWidth > 640;
    const DUR = walkAnim ? 1500 : 700;
    const FRAME_MS = 210;
    const start = performance.now();
    const wi = this.shadowRoot.querySelector(".or-walk-img");
    if (wi) wi.style.transform = dir > 4 ? "scaleX(-1)" : "none"; // frames face left; flip heading right
    const tick = () => {
      if (!this._onboarding || !this._onboarding.active) return;
      this._aimOnboarding(anchorEl);
      const t = performance.now() - start;
      if (walkAnim) {
        const f = (Math.floor(t / FRAME_MS) % 4) + 1;
        const el = this.shadowRoot.querySelector(".or-walk-img");
        if (el) el.src = `${this._avatarBase()}walk-${f}.png`;
      }
      if (t >= DUR) {
        if (this._onboarding.walking) { this._onboarding.walking = false; this._render(); }
        return;
      }
      this._onboarding.walkRaf = requestAnimationFrame(tick);
    };
    this._onboarding.walkRaf = requestAnimationFrame(tick);
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
        cheeky: "Hey — I'm your reef guide, the little reefer who lives in your dashboard. 30-second tour, and not a line of Apex code: no virtual outlets, no Defer commands, no scattered docs.",
        cheekyNoApex: "Hey — I'm your reef guide, the little reefer who lives in your dashboard. Give me 30 seconds and I'll show you round — no spreadsheets, no guesswork.",
        professional: "Welcome to OpenReef. I'm your reef guide — here's a quick 30-second tour of the main features." },
      { id: "reef-health", anchor: "reef-health", pose: "point",
        cheeky: "Your whole reef's health in one honest number. Apex Fusion shows you the graphs and leaves you to play detective — I actually tell you what they mean.",
        cheekyNoApex: "Your whole reef's health in one honest number. No more squinting at separate graphs wondering if it all adds up — I tell you what they mean.",
        professional: "Your Reef Health Score: one explainable 0-100 read on the tank, weighted for your reef type." },
      { id: "dosing", anchor: "dosing", pose: "smug",
        cheeky: "Your alk, cal and mag consumption — worked out, with exactly how much to dose. The maths is free; the Trident's reagents sadly aren't. Good news: my mate Harry does ABC reagents cheaper.",
        cheekyNoApex: "Your alk, cal and mag consumption — worked out from your tests, with exactly how much to dose. The maths most reefers do by hand, or skip entirely and wonder why the corals sulk.",
        link: { label: "Harry's ABC reagents → marine-spec.co.uk", url: "https://www.marine-spec.co.uk" },
        professional: "The Dosing Advisor estimates alk/cal/mag consumption from history, projects when you'll reach a limit, and suggests dose changes. Advisory only." },
      { id: "attention", anchor: "attention", pose: "facepalm",
        cheeky: "Anything wrong shows up here in plain English. No fault codes to Google, no scattered docs, no three-day forum thread just to get your auto top-off behaving.",
        cheekyNoApex: "Anything wrong shows up here in plain English — before your corals tell you the hard way. No cryptic codes, no guesswork.",
        professional: "Anything that needs attention - alerts, missing mappings, safety interlocks - is summarised here in plain English." },
      { id: "sensors", anchor: "sensors", pose: "point",
        cheeky: "Tap any reading for its full trend. Apex probes, Trident, and the cheap non-Apex sensors your controller flatly refuses to talk to — all in one place.",
        cheekyNoApex: "Tap any reading for its full trend. Every probe and smart plug you own — even the cheap ones — in one place, with proper history.",
        professional: "Tap any reading to open its trend, with ranges from 1 hour to 30 days." },
      { id: "safety", anchor: "settings", pose: "idle",
        cheeky: "One serious note: OpenReef never switches an outlet until you map it and arm it yourself. Your livestock is never automated behind your back. Set that up in Settings.",
        professional: "One serious note: OpenReef never switches an outlet until you map it and arm it yourself. Your livestock is never automated behind your back. Set that up in Settings." },
      { id: "done", anchor: null, pose: "celebrate",
        cheeky: "That's the tour — your reef's in good hands. Now go show your Apex who's boss. 🪸",
        cheekyNoApex: "That's the tour — your reef's in good hands. Now go enjoy the tank instead of babysitting it. 🪸",
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
    this._onboarding = { active: true, step: 0, steps, scrolledStep: -1, walking: false, walkRaf: null };
    this._render();
  }

  _endOnboarding(markDone = true) {
    if (markDone) this._setOnboardingDone();
    if (this._onboarding) cancelAnimationFrame(this._onboarding.walkRaf);
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
    const stepChanged = this._onboarding.scrolledStep !== this._onboarding.step;
    if (!stepChanged) {
      // Re-render mid/after walk or on a tone toggle: just keep things aligned.
      this._aimOnboarding(anchorEl);
      return;
    }
    this._onboarding.scrolledStep = this._onboarding.step;
    const firstPlace = !this._onboarding.pos;
    const prevLeft = this._onboarding.pos ? this._onboarding.pos.left : null;
    // First placement snaps with no scroll/walk; later steps smooth-scroll the card
    // into view and the guide tracks + walks to it.
    if (anchorEl) {
      anchorEl.scrollIntoView({ block: "center", behavior: firstPlace ? "auto" : "smooth" });
    }
    this._aimOnboarding(anchorEl, firstPlace);
    if (firstPlace) return;
    const dir = prevLeft == null ? 0 : (this._onboarding.pos.left - prevLeft);
    this._trackOnboarding(anchorEl, dir);
  }

  _onboardingOverlay() {
    const ob = this._onboarding;
    const steps = ob.steps;
    const idx = Math.min(ob.step, steps.length - 1);
    const step = steps[idx];
    const tone = this._tone();
    const hasApex = this._hasApex();
    const line = tone === "cheeky"
      ? (hasApex ? step.cheeky : (step.cheekyNoApex || step.cheeky))
      : (step.professional || step.cheeky);
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
            ${isLast && tone === "cheeky" && hasApex && this._stickerReady ? `<img class="or-sticker" src="${this._avatarBase()}apex-throne.png" alt="OpenReef's professional assessment of the competition">` : ""}
            <p class="or-line">${this._escape(line)}</p>
            ${step.link && tone === "cheeky" && hasApex ? `<a class="or-link" href="${this._escape(step.link.url)}" target="_blank" rel="noopener noreferrer">${this._escape(step.link.label)}</a>` : ""}
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
        line: tone === "cheeky"
          ? (this._hasApex() ? "Give me a few more days of data and I'll spot the patterns Fusion never would." : "Give me a few more days of data and I'll spot the patterns you'd never catch by eye.")
          : "Some trends are still establishing a baseline.",
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
      ["maintenance", "Maintenance"],
      ["controls", "Controls"],
      ["lights", "Lights"],
      ["cameras", "Cameras"],
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
    if (this._activeTab === "maintenance") return this._maintenance();
    if (this._activeTab === "controls") return this._controls();
    if (this._activeTab === "lights") return this._lights();
    if (this._activeTab === "cameras") return this._cameras();
    if (this._activeTab === "energy") return this._energy();
    if (this._activeTab === "settings") return this._settings();
    return this._mission();
  }

  // --- ATI Straton lighting ---------------------------------------------

  _stratonConfig() {
    const defaults = {
      enabled: true,
      adapter: "reeftech_wifi",
      selectedTemplate: "mixed_reef_safe",
      lastReceipt: "",
      fixtures: [],
      endpoints: {
        reachability: "",
        currentState: "",
        program: "",
        firmware: "",
        groups: "",
        lastScanAt: "",
        lastOutcome: "",
      },
      program: {
        peak: 62,
        startTime: "10:00",
        photoperiodHours: 10,
        rampMinutes: 90,
        acclimationStart: 30,
        acclimationTarget: 70,
        acclimationDays: 42,
        quickMode: "auto",
        moonlight: 1,
        lunarMode: "manual",
        cloudDim: 18,
      },
    };
    const current = this._config.straton && typeof this._config.straton === "object" ? this._config.straton : {};
    this._config.straton = {
      ...defaults,
      ...current,
      program: {
        ...defaults.program,
        ...(current.program && typeof current.program === "object" ? current.program : {}),
      },
      endpoints: {
        ...defaults.endpoints,
        ...(current.endpoints && typeof current.endpoints === "object" ? current.endpoints : {}),
      },
    };
    const fixtures = Array.isArray(this._config.straton.fixtures) ? this._config.straton.fixtures : [];
    this._config.straton.fixtures = fixtures.slice(0, 12).map((fixture, index) => {
      const item = fixture && typeof fixture === "object" ? fixture : {};
      const fallbackId = `straton_${index + 1}`;
      const host = String(item.host || item.ip || "192.168.100.1").slice(0, 80);
      const connectionModes = ["unknown", "lan", "ap"];
      const setupStates = ["unknown", "already_on_lan", "brand_new", "stuck_setup"];
      return {
        id: this._slug(item.id || item.name || fallbackId) || fallbackId,
        name: String(item.name || `Straton ${index + 1}`).slice(0, 60),
        host,
        firmware: String(item.firmware || "unknown").slice(0, 32),
        group: String(item.group || "Display").slice(0, 40),
        connectionMode: connectionModes.includes(item.connectionMode) ? item.connectionMode : host === "192.168.100.1" ? "ap" : "unknown",
        setupState: setupStates.includes(item.setupState) ? item.setupState : "unknown",
        selected: item.selected !== false,
      };
    });
    return this._config.straton;
  }

  _stratonProgram() {
    return this._stratonConfig().program;
  }

  _stratonFixtures() {
    return this._stratonConfig().fixtures;
  }

  _stratonEndpoints() {
    return this._stratonConfig().endpoints;
  }

  _stratonCatalogPath(path) {
    const text = String(path || "").trim();
    if (!text || /^(?:https?:)?\/\//i.test(text)) return "";
    const clean = text.replace(/[?#].*$/, "");
    return clean.startsWith("/") ? clean.slice(0, 120) : `/${clean.slice(0, 119)}`;
  }

  _promoteStratonEndpoint(kind, path, outcome = "") {
    const key = ["reachability", "currentState", "program", "firmware", "groups"].includes(kind) ? kind : "currentState";
    const cleanPath = this._stratonCatalogPath(path);
    if (!cleanPath) return false;
    const endpoints = this._stratonEndpoints();
    endpoints[key] = cleanPath;
    endpoints.lastScanAt = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    endpoints.lastOutcome = String(outcome || "Candidate read path").slice(0, 80);
    this._setDirty(true);
    return true;
  }

  _stratonTemplates() {
    return [
      {
        id: "mixed_reef_safe",
        name: "Mixed reef safe",
        source: "OpenReef Straton research",
        tags: "mixed, LPS, starter",
        peak: 62,
        photoperiodHours: 10,
        detail: "Balanced blue-white program with enough guardrail for most mixed reefs.",
        notes: ["Manual IP fallback ready", "Use acclimation when changing from lower output lights"],
      },
      {
        id: "sps_blue_peak",
        name: "SPS blue peak",
        source: "Mobius AB+ style pattern",
        tags: "SPS, blue, high PAR",
        peak: 76,
        photoperiodHours: 10,
        detail: "Strong blue-biased peak for SPS systems with measured PAR and nutrient stability.",
        notes: ["Acclimation strongly recommended", "Measure PAR before running long peaks"],
      },
      {
        id: "saxby_inspired",
        name: "Saxby inspired",
        source: "AI community preset pattern",
        tags: "mixed, community, long day",
        peak: 64,
        photoperiodHours: 12,
        detail: "Community-style long viewing day with smooth ramps and moderate peak.",
        notes: ["Popular import/share pattern", "Watch total daily light on newer tanks"],
      },
      {
        id: "soft_lps_low_shock",
        name: "Soft and LPS low shock",
        source: "ReefBeat/Kessil gentle pattern",
        tags: "soft, LPS, acclimation",
        peak: 48,
        photoperiodHours: 8,
        detail: "Lower intensity template for soft coral, LPS, and recently moved livestock.",
        notes: ["Good first program after setup", "Pairs well with cloud dimming"],
      },
      {
        id: "photo_maintenance",
        name: "Photo and maintenance",
        source: "Quick-view feature request",
        tags: "viewing, photo, temporary",
        peak: 38,
        photoperiodHours: 4,
        detail: "Warmer temporary look for photos, inspection, and maintenance.",
        notes: ["Not intended as a growth program", "Use as a temporary override"],
      },
    ];
  }

  _stratonTemplate(id = this._stratonConfig().selectedTemplate) {
    return this._stratonTemplates().find((template) => template.id === id) || this._stratonTemplates()[0];
  }

  _stratonLightingEquipment() {
    return Object.entries(this._config.equipment || {}).filter(([id, item]) => this._equipmentProfile(id, item) === "lighting");
  }

  _stratonLightEntityId(item) {
    if (item?.light_entity_id) return item.light_entity_id;
    return this._entityDomain(item?.switch_entity_id) === "light" ? item.switch_entity_id : "";
  }

  _stratonLightLiveRows() {
    const program = this._stratonProgram();
    return this._stratonLightingEquipment().map(([id, item]) => {
      const entityId = this._stratonLightEntityId(item);
      const state = this._state(entityId);
      const attributes = state?.attributes || {};
      const brightness = Number(attributes.brightness);
      const brightnessPct = Number.isFinite(brightness) ? Math.round((brightness / 255) * 100) : null;
      const effect = attributes.effect || attributes.mode || attributes.preset || "";
      const colorTempKelvin = attributes.color_temp_kelvin || "";
      const colorTempMired = !colorTempKelvin ? attributes.color_temp || "" : "";
      const colorMode = attributes.color_mode || "";
      const colorLabel = colorTempKelvin
        ? `${colorTempKelvin}K`
        : colorTempMired
          ? `${colorTempMired} mired`
          : colorMode;
      let status = "unknown";
      let statusLabel = "Not mapped";
      let detail = "Map a Home Assistant light entity to read live state.";
      if (entityId && !state) {
        status = "critical";
        statusLabel = "Missing";
        detail = "Home Assistant is not reporting this light entity.";
      } else if (state?.state === "unavailable") {
        status = "critical";
        statusLabel = "Unavailable";
        detail = "The mapped light entity exists but is unavailable.";
      } else if (state?.state === "unknown") {
        status = "warning";
        statusLabel = "Unknown";
        detail = "The mapped light entity is not reporting a clear state.";
      } else if (state) {
        status = state.state === "on" ? "ok" : "unknown";
        statusLabel = state.state === "on" ? "Live" : "Off";
        if (state.state === "on" && brightnessPct !== null) {
          const peak = Number(program.peak) || 0;
          detail = brightnessPct > peak + 5
            ? `${brightnessPct}% live brightness is above the ${peak}% planned peak.`
            : `${brightnessPct}% live brightness read from Home Assistant.`;
        } else {
          detail = `State: ${state.state}.`;
        }
      }
      return {
        id,
        item,
        entityId,
        status,
        statusLabel,
        detail,
        brightnessPct,
        effect,
        colorLabel,
      };
    });
  }

  _stratonLiveBridgeSummary(rows = this._stratonLightLiveRows()) {
    const mapped = rows.filter((row) => row.entityId);
    const live = mapped.filter((row) => row.status === "ok");
    if (!rows.length) return ["unknown", "No lighting equipment", "Add lighting equipment to connect OpenReef with Home Assistant light entities."];
    if (!mapped.length) return ["warning", "No light entity", "Map a light.* entity for read-only live status."];
    if (!live.length) return ["warning", "Bridge not live", "Mapped light entities are missing, off, unknown, or unavailable."];
    return ["ok", `${live.length}/${mapped.length} live`, "OpenReef is reading live Home Assistant light state."];
  }

  _stratonLiveBridgeRows(rows = this._stratonLightLiveRows()) {
    if (!rows.length) {
      return `<p class="muted">Add lighting equipment if you want OpenReef to compare its plan with live Home Assistant light state.</p>`;
    }
    return rows.map((row) => `
      <div class="row">
        <div>
          <strong>${this._escape(row.item.label || row.id)}</strong>
          <span>${this._escape(row.entityId || "No light entity mapped")}</span>
          <small>${this._escape(row.detail)}</small>
        </div>
        <div class="pill-stack inline">
          <span class="pill ${this._escape(row.status)}">${this._escape(row.statusLabel)}</span>
          ${row.brightnessPct !== null ? `<span class="pill">${this._escape(row.brightnessPct)}%</span>` : ""}
          ${row.effect ? `<span class="pill">${this._escape(row.effect)}</span>` : ""}
          ${row.colorLabel ? `<span class="pill">${this._escape(row.colorLabel)}</span>` : ""}
        </div>
      </div>
    `).join("");
  }

  _stratonMatchTokens(value) {
    const ignored = new Set(["ati", "reef", "openreef", "open", "light", "lights", "straton", "fixture"]);
    return String(value || "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .map((token) => token.trim())
      .filter((token) => token.length >= 3 && !ignored.has(token));
  }

  _stratonFixtureLiveMatch(fixture, liveRows, selectedFixtures) {
    const mappedRows = liveRows.filter((row) => row.entityId);
    if (!mappedRows.length) return null;
    const fixtureTokens = new Set([
      ...this._stratonMatchTokens(fixture.name),
      ...this._stratonMatchTokens(fixture.host),
    ]);
    let best = null;
    mappedRows.forEach((row) => {
      const rowTokens = new Set([
        ...this._stratonMatchTokens(row.id),
        ...this._stratonMatchTokens(row.item?.label),
        ...this._stratonMatchTokens(row.entityId),
        ...this._stratonMatchTokens(this._friendlyEntityName(row.entityId)),
      ]);
      const score = [...fixtureTokens].filter((token) => rowTokens.has(token)).length;
      if (score > 0 && (!best || score > best.score)) {
        best = { row, score, confidence: "name" };
      }
    });
    if (best) return best;
    if (mappedRows.length === 1 && selectedFixtures.length === 1 && fixture.selected) {
      return { row: mappedRows[0], score: 1, confidence: "single target" };
    }
    return null;
  }

  _stratonFixtureSyncRows(liveRows = this._stratonLightLiveRows()) {
    const fixtures = this._stratonFixtures();
    const selectedFixtures = fixtures.filter((fixture) => fixture.selected);
    const groupCounts = fixtures.reduce((counts, fixture) => {
      const group = String(fixture.group || "Display").trim() || "Display";
      const current = counts.get(group) || { total: 0, selected: 0 };
      current.total += 1;
      if (fixture.selected) current.selected += 1;
      counts.set(group, current);
      return counts;
    }, new Map());
    return fixtures.map((fixture) => {
      const group = String(fixture.group || "Display").trim() || "Display";
      const groupState = groupCounts.get(group) || { total: 1, selected: fixture.selected ? 1 : 0 };
      const firmwareReady = this._stratonFirmwareReady(fixture.firmware);
      const liveMatch = this._stratonFixtureLiveMatch(fixture, liveRows, selectedFixtures);
      let liveClass = "unknown";
      let liveLabel = "no bridge";
      let liveDetail = "Map a Home Assistant light entity for read-only fixture confidence.";
      if (liveMatch?.row) {
        liveClass = liveMatch.row.status;
        liveLabel = liveMatch.row.statusLabel;
        const source = liveMatch.confidence === "single target" ? "single selected target" : "matching fixture label";
        liveDetail = `Matched ${liveMatch.row.entityId} by ${source}. ${liveMatch.row.detail}`;
      } else if (liveRows.some((row) => row.entityId)) {
        liveClass = "warning";
        liveLabel = "unmatched";
        liveDetail = "A light entity is mapped, but its name does not clearly match this fixture. Match fixture names or host-specific labels for per-fixture confidence.";
      } else if (liveRows.length) {
        liveClass = "warning";
        liveLabel = "not mapped";
        liveDetail = "Lighting equipment exists, but no read-only light entity is mapped yet.";
      }
      const groupLabel = groupState.total > 1
        ? `${groupState.selected}/${groupState.total} in ${group}`
        : group;
      const groupClass = groupState.total > 1
        ? groupState.selected === groupState.total ? "ok" : "warning"
        : "unknown";
      return {
        fixture,
        group,
        groupClass,
        groupLabel,
        targetClass: fixture.selected ? "ok" : "disabled",
        targetLabel: fixture.selected ? "targeted" : "skipped",
        firmwareClass: firmwareReady ? "ok" : "warning",
        firmwareLabel: firmwareReady ? "firmware ready" : "review firmware",
        firmwareReady,
        liveClass,
        liveLabel,
        liveDetail,
        liveEntityId: liveMatch?.row?.entityId || "",
      };
    });
  }

  _stratonSyncMatrix(liveRows = this._stratonLightLiveRows()) {
    const rows = this._stratonFixtureSyncRows(liveRows);
    const targets = rows.filter((row) => row.fixture.selected);
    const groups = new Set(targets.map((row) => row.group));
    const firmwareReady = targets.filter((row) => row.firmwareReady).length;
    const liveMatched = targets.filter((row) => row.liveEntityId && row.liveClass === "ok").length;
    if (!rows.length) {
      return `
        <article class="panel straton-sync-matrix">
          <div class="section-head">
            <div>
              <p class="eyebrow">Sync</p>
              <h3>Fixture sync matrix</h3>
              <p class="muted">Add fixtures to see target, firmware, group, live bridge, and write-readiness in one place.</p>
            </div>
            <span class="pill disabled">write locked</span>
          </div>
          <p class="muted">No Straton fixtures are configured yet.</p>
        </article>
      `;
    }
    return `
      <article class="panel straton-sync-matrix">
        <div class="section-head">
          <div>
            <p class="eyebrow">Sync</p>
            <h3>Fixture sync matrix</h3>
            <p class="muted">Per-fixture confidence before saving: target state, group coverage, firmware readiness, and read-only live bridge matching.</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${targets.length ? "ok" : "warning"}">${this._escape(targets.length)} target(s)</span>
            <span class="pill ${groups.size ? "ok" : "unknown"}">${this._escape(groups.size)} group(s)</span>
            <span class="pill ${firmwareReady === targets.length && targets.length ? "ok" : "warning"}">${this._escape(firmwareReady)}/${this._escape(targets.length)} firmware</span>
            <span class="pill ${liveMatched ? "ok" : "unknown"}">${this._escape(liveMatched)}/${this._escape(targets.length)} live</span>
            <span class="pill disabled">write locked</span>
          </div>
        </div>
        <div class="status-list">
          ${rows.map((row) => `
            <div class="row">
              <div>
                <strong>${this._escape(row.fixture.name)}</strong>
                <span>${this._escape(row.fixture.host || "No host")} · ${this._escape(row.group)} · ${this._escape(this._stratonConnectionModeLabel(row.fixture.connectionMode))} · ${this._escape(this._stratonSetupStateLabel(row.fixture.setupState))}</span>
                <small>${this._escape(row.liveDetail)} Hardware write remains locked until adapter evidence is verified.</small>
              </div>
              <div class="pill-stack inline">
                <span class="pill ${row.targetClass}">${this._escape(row.targetLabel)}</span>
                <span class="pill ${row.firmwareClass}">${this._escape(row.firmwareLabel)}</span>
                <span class="pill ${row.groupClass}">${this._escape(row.groupLabel)}</span>
                <span class="pill ${row.liveClass}">${this._escape(row.liveLabel)}</span>
                <span class="pill disabled">planned only</span>
              </div>
            </div>
          `).join("")}
        </div>
      </article>
    `;
  }

  _stratonTimeMinutes(value, fallback = "10:00") {
    const text = String(value || fallback);
    const match = text.match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return this._stratonTimeMinutes(fallback, "10:00");
    const hours = Math.max(0, Math.min(23, Number(match[1]) || 0));
    const minutes = Math.max(0, Math.min(59, Number(match[2]) || 0));
    return hours * 60 + minutes;
  }

  _stratonClock(minutes) {
    const value = ((Math.round(minutes) % 1440) + 1440) % 1440;
    const hours = Math.floor(value / 60);
    const mins = value % 60;
    return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
  }

  _stratonSchedulePlan() {
    const program = this._stratonProgram();
    const start = this._stratonTimeMinutes(program.startTime || "10:00");
    const photoperiod = Math.max(60, Math.min(16 * 60, Math.round((Number(program.photoperiodHours) || 10) * 60)));
    const ramp = Math.max(15, Math.min(Number(program.rampMinutes) || 90, Math.floor(photoperiod / 2)));
    const end = start + photoperiod;
    const peak = Math.max(0, Math.min(100, Number(program.peak) || 0));
    const cloudPeak = Math.max(0, peak - Math.max(0, Math.min(60, Number(program.cloudDim) || 0)));
    return [
      { label: "Ramp up", kind: "ramp", start, end: start + ramp, level: `0-${peak}%` },
      { label: "Peak window", kind: "peak", start: start + ramp, end: end - ramp, level: `${peak}%` },
      { label: "Ramp down", kind: "ramp", start: end - ramp, end, level: `${peak}-0%` },
      { label: "Cloud floor", kind: "cloud", start: start + ramp, end: end - ramp, level: `${cloudPeak}% when dimmed` },
      { label: "Moonlight", kind: "moon", start: end, end: start + 1440, level: `${Number(program.moonlight) || 0}%` },
    ].filter((phase) => phase.end > phase.start);
  }

  _stratonDaybarSegments(phases) {
    const segments = [];
    phases
      .filter((phase) => phase.kind !== "moon")
      .forEach((phase) => {
        let remaining = Math.max(0, phase.end - phase.start);
        let cursor = ((phase.start % 1440) + 1440) % 1440;
        while (remaining > 0) {
          const span = Math.min(remaining, 1440 - cursor);
          const left = Math.max(0, Math.min(100, (cursor / 1440) * 100));
          const width = Math.max(0.5, Math.min(100 - left, (span / 1440) * 100));
          segments.push(`<span class="${this._escape(phase.kind)}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${this._escape(`${phase.label}: ${this._stratonClock(phase.start)}-${this._stratonClock(phase.end)}`)}"></span>`);
          remaining -= span;
          cursor = 0;
        }
      });
    return segments.join("");
  }

  _stratonSchedulePreview() {
    const program = this._stratonProgram();
    const phases = this._stratonSchedulePlan();
    const daylight = phases.filter((phase) => phase.kind !== "moon");
    const moon = phases.find((phase) => phase.kind === "moon");
    return `
      <article class="panel straton-schedule-preview">
        <div class="section-head">
          <div>
            <p class="eyebrow">Schedule</p>
            <h3>Daily light plan preview</h3>
            <p class="muted">Visual check for ramps, peak window, cloud dimming, and moonlight before saving.</p>
          </div>
          <span class="pill ${Number(program.peak) > 72 ? "warning" : "ok"}">${this._escape(program.peak)}% peak</span>
        </div>
        <div class="grid three compact">
          <label>Start time<input type="time" data-scope="straton-program" data-field="startTime" value="${this._escape(program.startTime || "10:00")}"></label>
          <label>Photoperiod hours<input type="number" min="1" max="16" data-scope="straton-program" data-field="photoperiodHours" value="${this._escape(program.photoperiodHours)}"></label>
          <label>Ramp minutes<input type="number" min="15" max="240" step="5" data-scope="straton-program" data-field="rampMinutes" value="${this._escape(program.rampMinutes || 90)}"></label>
        </div>
        <div class="straton-daybar" aria-label="Straton daily schedule preview">
          ${this._stratonDaybarSegments(phases)}
        </div>
        <div class="straton-time-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
        <div class="status-list">
          ${daylight.map((phase) => `
            <div class="row">
              <div><strong>${this._escape(phase.label)}</strong><span>${this._escape(this._stratonClock(phase.start))} to ${this._escape(this._stratonClock(phase.end))}</span></div>
              <span class="pill ${phase.kind === "peak" ? "ok" : "unknown"}">${this._escape(phase.level)}</span>
            </div>
          `).join("")}
          ${moon ? `
            <div class="row">
              <div><strong>${this._escape(moon.label)}</strong><span>${this._escape(this._stratonClock(moon.start))} to ${this._escape(this._stratonClock(moon.end))}</span></div>
              <span class="pill ${Number(program.moonlight) > 2 ? "warning" : "unknown"}">${this._escape(moon.level)}</span>
            </div>
          ` : ""}
        </div>
      </article>
    `;
  }

  _stratonEvidenceDraft() {
    const fixtures = this._stratonFixtures();
    const fallbackFixture = fixtures.find((fixture) => fixture.selected) || fixtures[0] || null;
    const fallbackFixtureId = fallbackFixture?.id || "";
    const defaults = {
      before: "",
      after: "",
      notes: "",
      fixtureState: "",
      probeFixtureId: fallbackFixtureId,
      probePath: "",
      extraProbePaths: "",
      result: null,
      fixtureStateResult: null,
      probeResult: null,
      probeScanResult: null,
      testerNoteScenario: "strong",
      testerNote: "",
      testerNoteResult: null,
      probeLoading: false,
      probeScanning: false,
    };
    if (!this._stratonEvidence || typeof this._stratonEvidence !== "object") {
      this._stratonEvidence = { ...defaults };
    }
    this._stratonEvidence.before = this._stratonEvidence.before || "";
    this._stratonEvidence.after = this._stratonEvidence.after || "";
    this._stratonEvidence.notes = this._stratonEvidence.notes || "";
    this._stratonEvidence.fixtureState = this._stratonEvidence.fixtureState || "";
    if (!fixtures.some((fixture) => fixture.id === this._stratonEvidence.probeFixtureId)) {
      this._stratonEvidence.probeFixtureId = fallbackFixtureId;
    }
    this._stratonEvidence.probePath = this._stratonEvidence.probePath || "";
    this._stratonEvidence.extraProbePaths = this._stratonEvidence.extraProbePaths || "";
    this._stratonEvidence.result = this._stratonEvidence.result || null;
    this._stratonEvidence.fixtureStateResult = this._stratonEvidence.fixtureStateResult || null;
    this._stratonEvidence.probeResult = this._stratonEvidence.probeResult || null;
    this._stratonEvidence.probeScanResult = this._stratonEvidence.probeScanResult || null;
    this._stratonEvidence.testerNoteScenario = this._stratonEvidence.testerNoteScenario || "strong";
    this._stratonEvidence.testerNote = this._stratonEvidence.testerNote || "";
    this._stratonEvidence.testerNoteResult = this._stratonEvidence.testerNoteResult || null;
    this._stratonEvidence.probeLoading = Boolean(this._stratonEvidence.probeLoading);
    this._stratonEvidence.probeScanning = Boolean(this._stratonEvidence.probeScanning);
    return this._stratonEvidence;
  }

  _stratonParseEvidence(text) {
    const raw = String(text || "").trim();
    if (!raw) return { kind: "empty", value: null, lines: [], warning: "No text pasted." };
    try {
      return { kind: "json", value: JSON.parse(raw), lines: [] };
    } catch {
      return {
        kind: "lines",
        value: null,
        lines: raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
        warning: "Not valid JSON; comparing as redacted lines.",
      };
    }
  }

  _stratonValueSignature(value) {
    if (value === null) return "null";
    if (Array.isArray(value)) return `array:${value.length}`;
    if (typeof value === "object") return `object:${Object.keys(value).length}`;
    return `${typeof value}:${String(value)}`;
  }

  _stratonFlatten(value, prefix = "$", map = new Map(), state = { count: 0, max: 1200 }) {
    if (state.count >= state.max) {
      map.set(`${prefix}.__truncated`, "boolean:true");
      return map;
    }
    state.count += 1;
    if (Array.isArray(value)) {
      value.slice(0, 80).forEach((item, index) => this._stratonFlatten(item, `${prefix}[${index}]`, map, state));
      if (value.length > 80) map.set(`${prefix}.__more_items`, `number:${value.length - 80}`);
      return map;
    }
    if (value && typeof value === "object") {
      const keys = Object.keys(value).sort();
      if (!keys.length) map.set(prefix, "object:0");
      keys.forEach((key) => this._stratonFlatten(value[key], `${prefix}.${key}`, map, state));
      return map;
    }
    map.set(prefix, this._stratonValueSignature(value));
    return map;
  }

  _stratonEvidenceFocus(path) {
    const text = String(path || "").toLowerCase();
    if (/spectrum|channel|colour|color|white|blue|uv|violet|red|green|brightness|intensity|power|peak/.test(text)) return "spectrum";
    if (/schedule|program|time|ramp|day|photoperiod/.test(text)) return "schedule";
    if (/group|fixture|device|master|slave/.test(text)) return "grouping";
    if (/firmware|model|version|serial/.test(text)) return "firmware";
    if (/endpoint|api|url|http|method/.test(text)) return "endpoint";
    return "other";
  }

  _stratonRedactSnippet(text) {
    return String(text || "")
      .replace(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g, "x.x.x.x")
      .replace(/([?&](?:token|key|auth|password|secret|session|sid)=)[^&\s]+/gi, "$1redacted")
      .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer redacted")
      .slice(0, 120);
  }

  _stratonEndpointRows(...texts) {
    const rows = [];
    const seen = new Set();
    const pattern = /\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\b\s+([^\s"']+)/gi;
    texts.forEach((text) => {
      String(text || "").replace(pattern, (_match, method, rawUrl) => {
        let path = String(rawUrl || "");
        try {
          const url = new URL(path);
          path = `${url.pathname}${url.search ? "?redacted" : ""}`;
        } catch {
          path = path.replace(/\?.*$/, "?redacted");
        }
        path = this._stratonRedactSnippet(path);
        const key = `${method.toUpperCase()} ${path}`;
        if (!seen.has(key)) {
          seen.add(key);
          rows.push({ method: method.toUpperCase(), path });
        }
        return "";
      });
    });
    return rows.slice(0, 12);
  }

  _stratonProbeHostAllowed(hostname) {
    const host = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
    if (!host || host === "localhost" || host === "0.0.0.0" || host === "::") return false;
    if (/^10\./.test(host) || /^192\.168\./.test(host) || /^169\.254\./.test(host)) return true;
    const private172 = host.match(/^172\.(\d{1,2})\./);
    if (private172 && Number(private172[1]) >= 16 && Number(private172[1]) <= 31) return true;
    if (/^fe80:/i.test(host)) return true;
    return !host.includes(".") || /\.(local|lan|home|internal)$/.test(host);
  }

  _stratonProbePathPresets() {
    return [
      {
        path: "/",
        label: "Test root",
        detail: "First reachability check. HTML or text is still useful because it proves the controller can talk to the fixture.",
      },
      {
        path: "/settings",
        label: "Try settings",
        detail: "Common read path to test for a current settings response.",
      },
      {
        path: "/api/settings",
        label: "Try API settings",
        detail: "Alternate API-style read path seen in many device apps.",
      },
      {
        path: "/ati.settings.json",
        label: "Try backup JSON",
        detail: "Checks whether the fixture exposes the same style of settings backup file users export manually.",
      },
    ];
  }

  _stratonExtraProbePathPresets(text = this._stratonEvidenceDraft().extraProbePaths) {
    const seen = new Set(this._stratonProbePathPresets().map((preset) => preset.path));
    return String(text || "")
      .split(/[\s,]+/)
      .map((path) => this._stratonCatalogPath(path))
      .filter(Boolean)
      .filter((path) => {
        if (seen.has(path)) return false;
        seen.add(path);
        return true;
      })
      .slice(0, 8)
      .map((path) => ({
        path,
        label: `Try ${path}`,
        detail: "Extra read-only GET path supplied by tester evidence.",
        extra: true,
      }));
  }

  _stratonProbeTarget(fixture, path) {
    const host = String(fixture?.host || "").trim();
    const cleanPath = String(path || "").trim();
    if (!fixture) return { error: "Choose a configured Straton fixture before probing." };
    if (!host) return { error: "Add the fixture IP or host before probing." };
    if (!cleanPath) return { error: "Enter a read-only path from an ATI export or browser network capture." };
    if (/^(?:https?:)?\/\//i.test(cleanPath)) {
      return { error: "Enter only the fixture path, such as /settings. The host comes from the selected fixture." };
    }
    if (/^(?:javascript|data|file|blob):/i.test(cleanPath)) {
      return { error: "That path scheme is not allowed for fixture evidence collection." };
    }
    const hostText = /^https?:\/\//i.test(host) ? host : `http://${host}`;
    try {
      const base = new URL(hostText);
      if (!this._stratonProbeHostAllowed(base.hostname)) {
        return { error: "Only private or local fixture hosts can be probed." };
      }
      const pathText = cleanPath.startsWith("/") ? cleanPath : `/${cleanPath}`;
      const target = new URL(pathText, base.origin);
      if (target.origin !== base.origin) {
        return { error: "The probe path must stay on the selected fixture host." };
      }
      return {
        url: target.toString(),
        fixtureName: fixture.name || "Straton fixture",
        host: this._stratonRedactSnippet(base.host),
        path: `${target.pathname}${target.search ? "?redacted" : ""}`,
      };
    } catch {
      return { error: "The fixture host is not a valid IP, hostname, or URL." };
    }
  }

  _stratonApplyProbeResponse(draft, payload, fixtureName, body, promote = true) {
    const text = String(body || "");
    const parsed = text ? this._stratonParseEvidence(text) : { kind: payload.mode || "empty" };
    const status = payload.status
      ? `${payload.status}${payload.status_text ? ` ${payload.status_text}` : ""}`
      : payload.status_text || "not run";
    const responseOk = Number(payload.status) >= 200 && Number(payload.status) < 300;
    draft.probeLoading = false;
    if (text) draft.fixtureState = text;
    draft.probeResult = {
      checkedAt: new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
      source: payload.source === "home_assistant" ? "Home Assistant backend" : "browser",
      method: payload.method || "GET",
      path: payload.path || "unknown path",
      fixtureName,
      host: payload.host || "redacted",
      status,
      statusClass: payload.success && parsed.kind === "json" ? "ok" : responseOk ? "unknown" : "warning",
      contentType: this._stratonRedactSnippet(payload.content_type || payload.contentType || "unknown"),
      bytes: Number(payload.bytes) || text.length,
      mode: parsed.kind || payload.mode || "unknown",
      warning: payload.warning || (text ? "" : "The probe did not return text for analysis."),
      preview: this._stratonRedactSnippet(text),
    };
    this._recordActivity(`Straton ${draft.probeResult.source} GET ${status} from ${fixtureName}: ${draft.probeResult.path}`, draft.probeResult.statusClass === "ok" ? "control" : "warning");
    if (promote && draft.probeResult.statusClass === "ok" && draft.probeResult.mode === "json") {
      this._promoteStratonEndpoint("currentState", draft.probeResult.path, "Manual probe JSON path");
    } else if (promote && draft.probeResult.statusClass === "unknown" && draft.probeResult.path === "/") {
      this._promoteStratonEndpoint("reachability", draft.probeResult.path, "Root reachable");
    }
    if (text) this._analyzeStratonFixtureState();
    else this._render();
  }

  _stratonProbeRowFromPayload(path, payload = {}, body = "", fallbackWarning = "") {
    const parsed = body ? this._stratonParseEvidence(body) : { kind: payload.mode || "empty" };
    const status = payload.status
      ? `${payload.status}${payload.status_text ? ` ${payload.status_text}` : ""}`
      : payload.status_text || "not run";
    const responseOk = Number(payload.status) >= 200 && Number(payload.status) < 300;
    const statusClass = payload.success && parsed.kind === "json" ? "ok" : responseOk ? "unknown" : "warning";
    return {
      path: payload.path || this._stratonRedactSnippet(path || "unknown"),
      source: payload.source === "home_assistant" ? "Home Assistant backend" : payload.source || "unknown",
      status,
      statusClass,
      contentType: this._stratonRedactSnippet(payload.content_type || payload.contentType || "unknown"),
      bytes: Number(payload.bytes) || body.length,
      mode: parsed.kind || payload.mode || "unknown",
      warning: fallbackWarning || payload.warning || "",
    };
  }

  async _scanStratonProbePaths() {
    const draft = this._stratonEvidenceDraft();
    const fixture = this._stratonProbeFixture();
    const checkedAt = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    if (!fixture) {
      draft.probeScanResult = {
        checkedAt,
        fixtureName: "not selected",
        host: "not set",
        rows: [],
        reachableCount: 0,
        jsonCount: 0,
        warning: "Add a Straton fixture target before scanning safe paths.",
      };
      this._render();
      return;
    }
    draft.probeScanning = true;
    draft.probeScanResult = {
      checkedAt,
      fixtureName: fixture.name || "Straton fixture",
      host: this._stratonRedactSnippet(fixture.host || "not set"),
      rows: [],
      reachableCount: 0,
      jsonCount: 0,
      warning: "Safe path scan in progress.",
    };
    this._render();
    const rows = [];
    let best = null;
    const presets = [
      ...this._stratonProbePathPresets(),
      ...this._stratonExtraProbePathPresets(draft.extraProbePaths),
    ];
    for (const preset of presets) {
      const target = this._stratonProbeTarget(fixture, preset.path);
      if (target.error) {
        rows.push({
          label: preset.label,
          path: this._stratonRedactSnippet(preset.path),
          source: "not run",
          status: "not run",
          statusClass: "warning",
          contentType: "none",
          bytes: 0,
          mode: "invalid",
          warning: target.error,
        });
        continue;
      }
      try {
        const payload = await this._callWS({
          type: "openreef/straton_probe",
          host: fixture.host || "",
          path: preset.path,
        });
        const body = String(payload?.body || "");
        const row = {
          label: preset.label,
          ...this._stratonProbeRowFromPayload(preset.path, payload || {}, body),
        };
        rows.push(row);
        if (!best && row.mode === "json" && row.statusClass === "ok") {
          best = { payload, body, preset };
        }
      } catch {
        rows.push({
          label: preset.label,
          path: this._stratonRedactSnippet(preset.path),
          source: "Home Assistant backend",
          status: "blocked",
          statusClass: "warning",
          contentType: "none",
          bytes: 0,
          mode: "error",
          warning: "OpenReef could not run the backend probe command.",
        });
      }
    }
    const reachableCount = rows.filter((row) => ["ok", "unknown"].includes(row.statusClass)).length;
    const jsonCount = rows.filter((row) => row.mode === "json").length;
    const rootReachable = rows.find((row) => row.path === "/" && ["ok", "unknown"].includes(row.statusClass));
    draft.probeScanning = false;
    draft.probeScanResult = {
      checkedAt: new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
      fixtureName: fixture.name || "Straton fixture",
      host: this._stratonRedactSnippet(fixture.host || "not set"),
      rows,
      reachableCount,
      jsonCount,
      bestPath: best?.payload?.path || "",
      warning: best ? "" : reachableCount ? "Controller reached the fixture, but no JSON path was found yet." : "No safe path was reachable from the controller.",
    };
    if (rootReachable) this._promoteStratonEndpoint("reachability", rootReachable.path, "Root reachable");
    if (best) {
      draft.probePath = best.preset.path;
      this._promoteStratonEndpoint("currentState", best.preset.path, "Safe scan JSON path");
      this._stratonApplyProbeResponse(draft, best.payload || {}, fixture.name || "Straton fixture", best.body, false);
      return;
    }
    this._recordActivity(`Straton safe path scan complete: ${reachableCount} reachable, ${jsonCount} JSON`, reachableCount ? "control" : "warning");
    this._render();
  }

  async _probeStratonFixtureState() {
    const draft = this._stratonEvidenceDraft();
    const fixtures = this._stratonFixtures();
    const fixture = fixtures.find((item) => item.id === draft.probeFixtureId) || fixtures.find((item) => item.selected) || fixtures[0];
    const target = this._stratonProbeTarget(fixture, draft.probePath);
    const checkedAt = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    if (target.error) {
      draft.probeResult = {
        checkedAt,
        source: "not run",
        method: "GET",
        path: this._stratonRedactSnippet(draft.probePath || "not set"),
        fixtureName: fixture?.name || "not selected",
        host: this._stratonRedactSnippet(fixture?.host || "not set"),
        status: "not run",
        statusClass: "warning",
        contentType: "none",
        bytes: 0,
        mode: "invalid",
        warning: target.error,
      };
      this._recordActivity(`Straton read-only probe not run: ${target.error}`, "warning");
      this._render();
      return;
    }
    draft.probeLoading = true;
    draft.probeResult = {
      checkedAt,
      source: "Home Assistant backend",
      method: "GET",
      path: target.path,
      fixtureName: target.fixtureName,
      host: target.host,
      status: "reading",
      statusClass: "unknown",
      contentType: "pending",
      bytes: 0,
      mode: "pending",
      warning: "Read-only GET is in progress.",
    };
    this._render();
    try {
      const result = await this._callWS({
        type: "openreef/straton_probe",
        host: fixture.host || "",
        path: draft.probePath || "",
      });
      this._stratonApplyProbeResponse(draft, result || {}, target.fixtureName, result?.body || "");
      return;
    } catch {
      // Fall back to a direct browser GET for older OpenReef backends or local static testing.
    }
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timeout = controller ? window.setTimeout(() => controller.abort(), 10000) : null;
    try {
      const response = await fetch(target.url, {
        method: "GET",
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
        signal: controller?.signal,
      });
      if (timeout) window.clearTimeout(timeout);
      const contentType = response.headers?.get?.("content-type") || "unknown";
      const rawText = await response.text();
      const text = rawText.length > 60000 ? rawText.slice(0, 60000) : rawText;
      const parsed = this._stratonParseEvidence(text);
      const truncated = rawText.length > text.length;
      draft.probeLoading = false;
      draft.fixtureState = text;
      draft.probeResult = {
        checkedAt: new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
        source: "browser fallback",
        method: "GET",
        path: target.path,
        fixtureName: target.fixtureName,
        host: target.host,
        status: `${response.status} ${response.statusText || ""}`.trim(),
        statusClass: response.ok && parsed.kind === "json" ? "ok" : response.ok ? "unknown" : "warning",
        contentType: this._stratonRedactSnippet(contentType),
        bytes: rawText.length,
        mode: parsed.kind,
        warning: [
          response.ok ? "" : "The fixture returned a non-2xx status.",
          parsed.kind === "json" ? "" : "The response was not structured JSON for planned-vs-observed comparison.",
          truncated ? "The response was truncated before analysis." : "",
        ].filter(Boolean).join(" "),
        preview: this._stratonRedactSnippet(text),
      };
      this._recordActivity(`Straton read-only GET ${response.status} from ${target.fixtureName}: ${target.path}`, response.ok ? "control" : "warning");
      this._analyzeStratonFixtureState();
    } catch (error) {
      if (timeout) window.clearTimeout(timeout);
      const timedOut = error?.name === "AbortError";
      draft.probeLoading = false;
      draft.probeResult = {
        checkedAt: new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
        source: "browser fallback",
        method: "GET",
        path: target.path,
        fixtureName: target.fixtureName,
        host: target.host,
        status: timedOut ? "timeout" : "blocked",
        statusClass: "warning",
        contentType: "none",
        bytes: 0,
        mode: "error",
        warning: timedOut
          ? "The fixture did not answer within 10 seconds."
          : "The browser could not read this fixture path. This may be CORS, mixed-content, network, or offline fixture behavior.",
      };
      this._recordActivity(`Straton read-only probe failed for ${target.fixtureName}: ${draft.probeResult.warning}`, "warning");
      this._render();
    }
  }

  _stratonLineDiff(beforeLines, afterLines) {
    const before = new Set(beforeLines.map((line) => this._stratonRedactSnippet(line)));
    const after = new Set(afterLines.map((line) => this._stratonRedactSnippet(line)));
    const added = [...after].filter((line) => !before.has(line));
    const removed = [...before].filter((line) => !after.has(line));
    return {
      mode: "line",
      changedCount: added.length + removed.length,
      addedCount: added.length,
      removedCount: removed.length,
      rows: [
        ...added.slice(0, 8).map((path) => ({ kind: "added", path, focus: "line" })),
        ...removed.slice(0, 8).map((path) => ({ kind: "removed", path, focus: "line" })),
      ].slice(0, 12),
    };
  }

  _stratonJsonDiff(beforeValue, afterValue) {
    const before = this._stratonFlatten(beforeValue);
    const after = this._stratonFlatten(afterValue);
    const paths = [...new Set([...before.keys(), ...after.keys()])].sort();
    const added = [];
    const removed = [];
    const changed = [];
    paths.forEach((path) => {
      if (!before.has(path)) added.push(path);
      else if (!after.has(path)) removed.push(path);
      else if (before.get(path) !== after.get(path)) changed.push(path);
    });
    return {
      mode: "json",
      changedCount: changed.length,
      addedCount: added.length,
      removedCount: removed.length,
      rows: [
        ...changed.slice(0, 10).map((path) => ({ kind: "changed", path, focus: this._stratonEvidenceFocus(path) })),
        ...added.slice(0, 6).map((path) => ({ kind: "added", path, focus: this._stratonEvidenceFocus(path) })),
        ...removed.slice(0, 6).map((path) => ({ kind: "removed", path, focus: this._stratonEvidenceFocus(path) })),
      ].slice(0, 14),
    };
  }

  _stratonFlattenLeaves(value, prefix = "$", rows = [], state = { count: 0, max: 1600 }) {
    if (state.count >= state.max) {
      rows.push({ path: `${prefix}.__truncated`, value: true, focus: "other" });
      return rows;
    }
    state.count += 1;
    if (Array.isArray(value)) {
      value.slice(0, 120).forEach((item, index) => this._stratonFlattenLeaves(item, `${prefix}[${index}]`, rows, state));
      if (value.length > 120) rows.push({ path: `${prefix}.__more_items`, value: value.length - 120, focus: "other" });
      return rows;
    }
    if (value && typeof value === "object") {
      Object.keys(value).sort().forEach((key) => this._stratonFlattenLeaves(value[key], `${prefix}.${key}`, rows, state));
      return rows;
    }
    rows.push({ path: prefix, value, focus: this._stratonEvidenceFocus(prefix) });
    return rows;
  }

  _stratonSchemaFingerprint(rows = []) {
    const signatures = rows
      .map((row) => `${row.path}:${Array.isArray(row.value) ? "array" : row.value === null ? "null" : typeof row.value}`)
      .sort();
    let hash = 2166136261;
    signatures.join("|").split("").forEach((char) => {
      hash ^= char.charCodeAt(0);
      hash = Math.imul(hash, 16777619) >>> 0;
    });
    const focusCounts = rows.reduce((counts, row) => {
      counts[row.focus] = (counts[row.focus] || 0) + 1;
      return counts;
    }, {});
    return {
      id: hash.toString(16).padStart(8, "0"),
      leafCount: rows.length,
      focusCounts,
    };
  }

  _stratonDisplayValue(value) {
    if (typeof value === "number") return Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : "unknown";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (value === null || value === undefined) return "unknown";
    return this._stratonRedactSnippet(String(value));
  }

  _stratonNumberFromValue(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      const match = value.match(/-?\d+(?:\.\d+)?/);
      if (match) return Number(match[0]);
    }
    return null;
  }

  _stratonFixtureCandidate(rows, pattern, validate = () => true) {
    return rows.find((row) => pattern.test(row.path) && validate(row.value, row));
  }

  _stratonFixtureNumberCandidate(rows, pattern, min = -Infinity, max = Infinity) {
    const row = this._stratonFixtureCandidate(rows, pattern, (value) => {
      const number = this._stratonNumberFromValue(value);
      return number !== null && number >= min && number <= max;
    });
    if (!row) return null;
    return { row, value: this._stratonNumberFromValue(row.value) };
  }

  _stratonFixtureTimeCandidate(rows, pattern) {
    const row = this._stratonFixtureCandidate(rows, pattern, (value) => typeof value === "string" && /\b\d{1,2}:\d{2}\b/.test(value));
    if (!row) return null;
    const match = String(row.value).match(/\b\d{1,2}:\d{2}\b/);
    return { row, value: match ? match[0] : "" };
  }

  _stratonFixtureCompareNumber(label, planned, candidate, unit = "", tolerance = 0) {
    if (!candidate) {
      return { label, status: "unknown", planned: `${planned}${unit}`, observed: "not found", detail: "No obvious matching field in the pasted fixture sample." };
    }
    const observed = Math.round(candidate.value * 10) / 10;
    const delta = Math.abs(observed - planned);
    return {
      label,
      status: delta <= tolerance ? "ok" : "warning",
      planned: `${planned}${unit}`,
      observed: `${observed}${unit}`,
      detail: `Candidate path ${candidate.row.path}`,
    };
  }

  _stratonFixtureCompareTime(label, planned, candidate) {
    if (!candidate) {
      return { label, status: "unknown", planned, observed: "not found", detail: "No obvious matching time field in the pasted fixture sample." };
    }
    return {
      label,
      status: candidate.value === planned ? "ok" : "warning",
      planned,
      observed: candidate.value,
      detail: `Candidate path ${candidate.row.path}`,
    };
  }

  _stratonProbeEvidencePath(draft = this._stratonEvidenceDraft()) {
    const probe = draft.probeResult;
    if (probe?.mode !== "json" || !probe.path) return "";
    return this._stratonCatalogPath(probe.path);
  }

  _promoteStratonReadRoleCandidates(sourcePath, roles = []) {
    const cleanPath = this._stratonCatalogPath(sourcePath);
    if (!cleanPath) return [];
    const endpoints = this._stratonEndpoints();
    const promoted = [];
    roles.forEach(({ kind, label, reason }) => {
      if (!["program", "firmware", "groups"].includes(kind)) return;
      if (endpoints[kind] === cleanPath) {
        promoted.push({ kind, label, path: cleanPath, state: "already mapped", reason });
        return;
      }
      if (this._promoteStratonEndpoint(kind, cleanPath, reason || `${label} candidate from fixture JSON`)) {
        promoted.push({ kind, label, path: cleanPath, state: "promoted", reason });
      }
    });
    return promoted;
  }

  _analyzeStratonFixtureState() {
    const draft = this._stratonEvidenceDraft();
    const parsed = this._stratonParseEvidence(draft.fixtureState);
    const endpoints = this._stratonEndpointRows(draft.fixtureState);
    const checkedAt = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    if (parsed.kind !== "json") {
      draft.fixtureStateResult = {
        checkedAt,
        mode: parsed.kind,
        warning: parsed.warning || "Paste a JSON fixture export or response for planned-vs-observed comparison.",
        leafCount: 0,
        focusCounts: {},
        endpoints,
        observations: [
          { label: "Fixture sample", status: "warning", planned: "JSON", observed: parsed.kind, detail: "Read-only comparison needs structured JSON." },
        ],
        rows: [],
      };
      this._recordActivity("Straton fixture sample needs JSON for read-only comparison", "warning");
      this._render();
      return;
    }
    const program = this._stratonProgram();
    const rows = this._stratonFlattenLeaves(parsed.value);
    const schemaFingerprint = this._stratonSchemaFingerprint(rows);
    const focusCounts = rows.reduce((counts, row) => {
      counts[row.focus] = (counts[row.focus] || 0) + 1;
      return counts;
    }, {});
    const observedPeak = this._stratonFixtureNumberCandidate(rows, /\.(?:peak|brightness|intensity|output|power|maxPower|maxIntensity)(?:\.|$)/i, 0, 100);
    const observedStart = this._stratonFixtureTimeCandidate(rows, /\.(?:start|sunrise|on|begin|from|time)(?:Time)?(?:\.|$)/i);
    const observedPhotoperiod = this._stratonFixtureNumberCandidate(rows, /\.(?:photoperiod(?:Hours)?|duration|dayLength|daylight|period|hours)(?:\.|$)/i, 1, 24);
    const observedRamp = this._stratonFixtureNumberCandidate(rows, /\.(?:ramp|fade|transition)(?:Minutes|Duration|Time)?(?:\.|$)/i, 1, 360);
    const observedMoon = this._stratonFixtureNumberCandidate(rows, /\.(?:moon|moonlight|lunar)(?:Intensity|Power|Brightness)?(?:\.|$)/i, 0, 10);
    const firmwareRow = this._stratonFixtureCandidate(rows, /firmware|version|fw/i, (value) => value !== null && value !== undefined && String(value).trim() !== "");
    const modelRow = this._stratonFixtureCandidate(rows, /model|product|fixture|deviceType/i, (value) => value !== null && value !== undefined && String(value).trim() !== "");
    const groupRows = rows.filter((row) => row.focus === "grouping").slice(0, 4);
    const sourcePath = this._stratonProbeEvidencePath(draft);
    const roleCandidates = [];
    if ([observedPeak, observedStart, observedPhotoperiod, observedRamp, observedMoon].some(Boolean) || focusCounts.schedule || focusCounts.spectrum) {
      roleCandidates.push({ kind: "program", label: "Program", reason: "Fixture JSON includes schedule/spectrum candidates" });
    }
    if (firmwareRow || modelRow) {
      roleCandidates.push({ kind: "firmware", label: "Firmware/model", reason: "Fixture JSON includes firmware/model candidates" });
    }
    if (groupRows.length) {
      roleCandidates.push({ kind: "groups", label: "Groups", reason: "Fixture JSON includes grouping candidates" });
    }
    const promotedEndpoints = this._promoteStratonReadRoleCandidates(sourcePath, roleCandidates);
    const notable = [
      ...(firmwareRow ? [{ path: firmwareRow.path, focus: "firmware", value: this._stratonDisplayValue(firmwareRow.value) }] : []),
      ...(modelRow ? [{ path: modelRow.path, focus: "firmware", value: this._stratonDisplayValue(modelRow.value) }] : []),
      ...groupRows.map((row) => ({ path: row.path, focus: row.focus, value: this._stratonDisplayValue(row.value) })),
      ...rows.filter((row) => row.focus === "schedule" || row.focus === "spectrum").slice(0, 8).map((row) => ({
        path: row.path,
        focus: row.focus,
        value: this._stratonDisplayValue(row.value),
      })),
    ].slice(0, 14);
    const observations = [
      this._stratonFixtureCompareNumber("Peak output", Number(program.peak) || 0, observedPeak, "%", 5),
      this._stratonFixtureCompareTime("Start time", program.startTime || "10:00", observedStart),
      this._stratonFixtureCompareNumber("Photoperiod", Number(program.photoperiodHours) || 10, observedPhotoperiod, "h", 0.5),
      this._stratonFixtureCompareNumber("Ramp", Number(program.rampMinutes) || 90, observedRamp, "m", 10),
      this._stratonFixtureCompareNumber("Moonlight", Number(program.moonlight) || 0, observedMoon, "%", 0.5),
      {
        label: "Firmware",
        status: firmwareRow && this._stratonFirmwareReady(firmwareRow.value) ? "ok" : firmwareRow ? "warning" : "unknown",
        planned: "2024+ baseline",
        observed: firmwareRow ? this._stratonDisplayValue(firmwareRow.value) : "not found",
        detail: firmwareRow ? `Candidate path ${firmwareRow.path}` : "No obvious firmware field in the pasted fixture sample.",
      },
    ];
    draft.fixtureStateResult = {
      checkedAt,
      mode: parsed.kind,
      warning: "",
      leafCount: rows.length,
      focusCounts,
      schemaFingerprint,
      endpoints,
      observations,
      promotedEndpoints,
      rows: notable,
    };
    this._recordActivity(`Straton fixture sample analyzed: ${rows.length} leaf value(s), ${observations.filter((item) => item.status === "ok").length} close match(es)`);
    this._render();
  }

  _clearStratonFixtureState() {
    const draft = this._stratonEvidenceDraft();
    draft.fixtureState = "";
    draft.fixtureStateResult = null;
    draft.probeResult = null;
    draft.probeScanResult = null;
    draft.probeLoading = false;
    draft.probeScanning = false;
    this._render();
  }

  _stratonProbeFixture() {
    const draft = this._stratonEvidenceDraft();
    const fixtures = this._stratonFixtures();
    return fixtures.find((item) => item.id === draft.probeFixtureId) || fixtures.find((item) => item.selected) || fixtures[0] || null;
  }

  _applyStratonApFallback() {
    const draft = this._stratonEvidenceDraft();
    let fixture = this._stratonProbeFixture();
    if (!fixture) {
      this._addStratonFixture();
      fixture = this._stratonFixtures()[0] || null;
    }
    if (fixture) {
      fixture.host = "192.168.100.1";
      fixture.selected = true;
      fixture.connectionMode = "ap";
      draft.probeFixtureId = fixture.id;
    }
    draft.probePath = "/";
    draft.probeResult = null;
    draft.probeScanResult = null;
    draft.probeScanning = false;
    this._recordActivity("Straton AP fallback staged: 192.168.100.1 with root reachability test");
    this._setDirty(true);
    this._render();
  }

  _probeStratonFixturePath(path) {
    const draft = this._stratonEvidenceDraft();
    draft.probePath = path || "/";
    return this._probeStratonFixtureState();
  }

  _analyzeStratonEvidence() {
    const draft = this._stratonEvidenceDraft();
    const before = this._stratonParseEvidence(draft.before);
    const after = this._stratonParseEvidence(draft.after);
    const endpoints = this._stratonEndpointRows(draft.notes, draft.before, draft.after);
    let diff;
    if (before.kind === "json" && after.kind === "json") {
      diff = this._stratonJsonDiff(before.value, after.value);
    } else {
      diff = this._stratonLineDiff(before.lines, after.lines);
    }
    const focusCounts = diff.rows.reduce((counts, row) => {
      counts[row.focus] = (counts[row.focus] || 0) + 1;
      return counts;
    }, {});
    draft.result = {
      checkedAt: new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" }),
      beforeKind: before.kind,
      afterKind: after.kind,
      warning: [before.warning, after.warning].filter(Boolean).join(" "),
      endpoints,
      focusCounts,
      ...diff,
    };
    this._recordActivity(`Straton adapter evidence analyzed: ${diff.changedCount} changed, ${diff.addedCount} added, ${diff.removedCount} removed`);
    this._render();
  }

  _clearStratonEvidence() {
    const draft = this._stratonEvidenceDraft();
    draft.before = "";
    draft.after = "";
    draft.notes = "";
    draft.result = null;
    this._render();
  }

  _stratonTesterNoteValue(lines, label) {
    const prefix = `- ${String(label || "").toLowerCase()}:`;
    const line = (lines || []).find((item) => String(item || "").toLowerCase().startsWith(prefix));
    if (!line) return "";
    return String(line).slice(line.indexOf(":") + 1).trim();
  }

  _stratonTesterNotePath(value) {
    const text = String(value || "").trim();
    if (!text || /^(?:not mapped|none|unknown|n\/a)$/i.test(text)) return "";
    return this._stratonCatalogPath(text);
  }

  _stratonTesterNoteFingerprint(value) {
    const text = String(value || "").trim();
    if (!text || /^(?:not available|not mapped|none|unknown|n\/a)$/i.test(text)) return "";
    const match = text.match(/\b([a-f0-9]{6,16})\b/i);
    return (match ? match[1] : text.split(/\s+/)[0]).toLowerCase();
  }

  _stratonReturnedSetupEvidence(parts = {}) {
    const setupClaimTitle = String(parts.setupClaimTitle || "");
    const setupClaimStatus = String(parts.setupClaimStatus || "");
    const apRouteTitle = String(parts.apRouteTitle || "");
    const apRouteStatus = String(parts.apRouteStatus || "");
    const bypassTitle = String(parts.title || "");
    const bypassStatus = String(parts.status || "");
    const currentState = String(parts.currentState || "");
    const jsonCount = Number(parts.jsonCount) || 0;
    const reachableCount = Number(parts.reachableCount) || 0;
    const hasJson = jsonCount > 0 || Boolean(currentState);
    const apRouteOk = apRouteStatus === "ok" && /^AP\b/i.test(apRouteTitle);
    const apRouteWarning = apRouteStatus === "warning" || /not reachable/i.test(apRouteTitle);
    const preSetupClaim = /pre-setup bypass candidate/i.test(setupClaimTitle) && setupClaimStatus === "ok";
    const lanOnly = /LAN confidence only/i.test(setupClaimTitle) || /^LAN\b/i.test(apRouteTitle);
    if (preSetupClaim && apRouteOk && hasJson) {
      return {
        status: "ok",
        title: "Strong pre-setup evidence",
        detail: "Returned note has AP route proof, pre-setup fixture state, and a JSON read path.",
        next: "Use this for read-adapter mapping, but keep writes locked until program readback and save/apply endpoints are verified.",
      };
    }
    if (apRouteWarning) {
      return {
        status: "warning",
        title: "Route blocker",
        detail: "Returned note says the controller could not reach the Straton AP route.",
        next: "Fix controller-to-AP routing before treating this as an ATI setup or Straton endpoint failure.",
      };
    }
    if (lanOnly && hasJson) {
      return {
        status: "unknown",
        title: "LAN read evidence only",
        detail: "Returned note has useful read evidence, but it appears to be from an already-networked fixture.",
        next: "Use it for read mapping, then test AP fallback on a brand-new/reset or stuck setup fixture.",
      };
    }
    if (apRouteOk && hasJson) {
      return {
        status: "unknown",
        title: "AP read, setup state unclear",
        detail: "Returned note has AP JSON evidence, but setup state was not strong enough to prove ATI onboarding was bypassed.",
        next: "Ask whether the fixture was brand new/reset, stuck in setup, or already configured.",
      };
    }
    if (apRouteStatus === "unknown" && reachableCount > 0 && !hasJson) {
      return {
        status: "unknown",
        title: "Reachable but no setup proof",
        detail: "Returned note has reachability evidence but no useful JSON read path yet.",
        next: "Collect safe read paths from ATI exports or redacted network notes, then scan again.",
      };
    }
    if (bypassStatus === "warning" || /not proven|untested/i.test(bypassTitle)) {
      return {
        status: "warning",
        title: "Setup bypass not proven",
        detail: "Returned note does not prove OpenReef can reach and read the fixture before ATI setup.",
        next: "Run AP fallback and Scan safe paths again after confirming the controller can reach the fixture network.",
      };
    }
    return {
      status: "unknown",
      title: "Setup evidence incomplete",
      detail: "Returned note does not include enough AP route, setup-state, and JSON-read evidence to make a setup-bypass claim.",
      next: "Ask for the full support note after AP fallback and safe path scanning.",
    };
  }

  _stratonTesterNoteResultFromText(text) {
    const raw = String(text || "").trim();
    const checkedAt = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    const isExample = /^Created:\s*example only$/im.test(raw) || /^Example scenario:/im.test(raw);
    if (!raw) {
      return {
        checkedAt,
        status: "warning",
        title: "No tester note",
        detail: "Paste the Straton support note returned by the beta tester.",
        next: "Use Copy tester steps, then ask the tester to send back the copied support note.",
        reachableCount: 0,
        jsonCount: 0,
        endpoints: {},
        promoted: [],
        apRouteTitle: "",
        apRouteStatus: "",
        apRouteDetail: "",
        apRouteNext: "",
        setupEvidenceStatus: "warning",
        setupEvidenceTitle: "No returned evidence",
        setupEvidenceDetail: "No returned support note has been pasted yet.",
        setupEvidenceNext: "Use Copy tester steps, then ask the tester to send back the copied support note.",
        schemaFingerprint: "",
        localSchemaFingerprint: "",
        schemaFingerprintStatus: "unknown",
        schemaFingerprintTitle: "Schema not included",
        schemaFingerprintDetail: "No returned schema fingerprint was found in the pasted note.",
      };
    }
    const lines = raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const verdictRaw = this._stratonTesterNoteValue(lines, "verdict");
    const outcomeRaw = this._stratonTesterNoteValue(lines, "outcome");
    const verdictText = `${verdictRaw} ${outcomeRaw}`.trim();
    const setupClaimRaw = this._stratonTesterNoteValue(lines, "setup claim");
    const setupClaimStatus = (setupClaimRaw.match(/\((ok|unknown|warning)\)\s*$/i)?.[1] || "").toLowerCase();
    const setupClaimTitle = setupClaimRaw.replace(/\s*\((ok|unknown|warning)\)\s*$/i, "").trim();
    const setupClaimDetail = this._stratonTesterNoteValue(lines, "setup claim detail");
    const apRouteRaw = this._stratonTesterNoteValue(lines, "AP route");
    const apRouteStatus = (apRouteRaw.match(/\((ok|unknown|warning)\)\s*$/i)?.[1] || "").toLowerCase();
    const apRouteTitle = apRouteRaw.replace(/\s*\((ok|unknown|warning)\)\s*$/i, "").trim();
    const apRouteDetail = this._stratonTesterNoteValue(lines, "AP route detail");
    const apRouteNext = this._stratonTesterNoteValue(lines, "AP route next");
    const hardwareGeneration = this._stratonTesterNoteValue(lines, "hardware generation");
    const bluetoothControl = this._stratonTesterNoteValue(lines, "Bluetooth evidence");
    const liveParEnergy = this._stratonTesterNoteValue(lines, "Live PAR/Energy");
    const templatesGroups = this._stratonTesterNoteValue(lines, "templates/groups");
    const scheduleSave = this._stratonTesterNoteValue(lines, "schedule save");
    const reefPilotEvidence = /reef pilot|bluetooth|straton x/i.test([
      raw,
      hardwareGeneration,
      bluetoothControl,
      liveParEnergy,
      templatesGroups,
      scheduleSave,
    ].join(" "));
    const reachability = this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "reachability"));
    let currentState = this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "current state"));
    const bestPath = this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "best path"));
    const request = this._stratonTesterNoteValue(lines, "request");
    const requestMatch = request.match(/\bGET\s+([^\s,]+)/i);
    if (!currentState) currentState = bestPath || this._stratonTesterNotePath(requestMatch?.[1] || "");
    const endpoints = {
      reachability,
      currentState,
      program: this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "program")),
      firmware: this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "firmware")),
      groups: this._stratonTesterNotePath(this._stratonTesterNoteValue(lines, "groups")),
    };
    const reachableCount = Math.max(0, Number(this._stratonTesterNoteValue(lines, "reachable paths")) || 0);
    const jsonCount = Math.max(0, Number(this._stratonTesterNoteValue(lines, "JSON paths")) || 0);
    const schemaFingerprint = this._stratonTesterNoteFingerprint(this._stratonTesterNoteValue(lines, "schema fingerprint"));
    const localSchemaFingerprint = String(this._stratonEvidence?.fixtureStateResult?.schemaFingerprint?.id || "").trim().toLowerCase();
    let schemaFingerprintStatus = "unknown";
    let schemaFingerprintTitle = "Schema not included";
    let schemaFingerprintDetail = "No returned schema fingerprint was found in the pasted note.";
    if (schemaFingerprint && localSchemaFingerprint && schemaFingerprint === localSchemaFingerprint) {
      schemaFingerprintStatus = "ok";
      schemaFingerprintTitle = "Schema match";
      schemaFingerprintDetail = "The returned note has the same redacted JSON shape as the current local fixture sample.";
    } else if (schemaFingerprint && localSchemaFingerprint) {
      schemaFingerprintStatus = "warning";
      schemaFingerprintTitle = "Schema mismatch";
      schemaFingerprintDetail = "The returned note has a different redacted JSON shape from the current local fixture sample.";
    } else if (schemaFingerprint) {
      schemaFingerprintStatus = "unknown";
      schemaFingerprintTitle = "Schema captured";
      schemaFingerprintDetail = "The returned note included a schema fingerprint, but there is no local fixture sample to compare against yet.";
    }
    let status = "unknown";
    let title = "Bypass unclear";
    let detail = "The note was parsed, but it does not include a clear bypass verdict.";
    let next = "Ask the tester for the full Straton support note, including the safe path scan section.";
    if (reefPilotEvidence) {
      status = "unknown";
      title = "Reef Pilot Bluetooth evidence";
      detail = "The returned note is for Straton X/Reef Pilot Bluetooth. AP route does not prove this adapter generation.";
      next = "Collect pairing/control, Live PAR/Energy, template/group, and schedule-save confirmation; keep writes locked.";
    } else if (/read-only bypass proven|read path found/i.test(verdictText) || jsonCount > 0 || currentState) {
      status = "ok";
      title = "Read-only bypass proven";
      detail = "The tester note includes a JSON/read path candidate from real fixture evidence.";
      next = "Use this as candidate adapter evidence; keep writes locked until current program and save/apply endpoints are verified.";
    } else if (/reachability bypass only|reachable,\s*no json/i.test(verdictText) || reachableCount > 0) {
      status = "unknown";
      title = "Reachability bypass only";
      detail = "The controller reached the fixture, but the note does not include a usable current-state JSON path.";
      next = "Collect ATI export links or browser network read paths, then retry Controller GET.";
    } else if (/bypass not proven|not reachable/i.test(verdictText)) {
      status = "warning";
      title = "Bypass not proven";
      detail = "The tester note says OpenReef could not reach/read the fixture from that network state.";
      next = "Confirm AP/LAN routing, try the LAN IP, or collect the tester's ATI setup state before promising a bypass.";
    } else if (/bypass untested|not scanned/i.test(verdictText)) {
      status = "warning";
      title = "Bypass untested";
      detail = "The note does not show a completed safe path scan.";
      next = "Ask the tester to run Scan safe paths and resend the support note.";
    }
    const promoted = [];
    if (!isExample && !reefPilotEvidence && endpoints.reachability && this._promoteStratonEndpoint("reachability", endpoints.reachability, "Tester note reachability path")) {
      promoted.push(`reachability ${endpoints.reachability}`);
    }
    if (!isExample && !reefPilotEvidence && status === "ok" && endpoints.currentState && this._promoteStratonEndpoint("currentState", endpoints.currentState, "Tester note current-state path")) {
      promoted.push(`current state ${endpoints.currentState}`);
    }
    const setupEvidence = reefPilotEvidence
      ? {
        status: "unknown",
        title: "Reef Pilot Bluetooth evidence",
        detail: "Returned note is for Straton X/Reef Pilot Bluetooth; AP route does not prove this adapter.",
        next: "Use the Bluetooth observations for generation mapping, then collect protocol/readback evidence before any control work.",
      }
      : this._stratonReturnedSetupEvidence({
        status,
        title,
        setupClaimTitle,
        setupClaimStatus,
        apRouteTitle,
        apRouteStatus,
        currentState: endpoints.currentState,
        reachableCount,
        jsonCount,
      });
    return {
      checkedAt,
      status,
      title,
      detail,
      next,
      verdict: verdictRaw || outcomeRaw || "not found",
      setupClaimTitle,
      setupClaimStatus,
      setupClaimDetail,
      apRouteTitle,
      apRouteStatus,
      apRouteDetail,
      apRouteNext,
      hardwareGeneration,
      bluetoothControl,
      liveParEnergy,
      templatesGroups,
      scheduleSave,
      reefPilotEvidence,
      setupEvidenceStatus: setupEvidence.status,
      setupEvidenceTitle: setupEvidence.title,
      setupEvidenceDetail: setupEvidence.detail,
      setupEvidenceNext: setupEvidence.next,
      reachableCount,
      jsonCount,
      endpoints,
      promoted,
      example: isExample,
      schemaFingerprint,
      localSchemaFingerprint,
      schemaFingerprintStatus,
      schemaFingerprintTitle,
      schemaFingerprintDetail,
      warning: [
        raw.length > 12000 ? "Only the redacted summary was needed; avoid pasting raw ATI exports into this box." : "",
        isExample ? "Example note only; no endpoint candidates were promoted and no hardware access is proven." : "",
      ].filter(Boolean).join(" "),
    };
  }

  _analyzeStratonTesterNote() {
    const draft = this._stratonEvidenceDraft();
    draft.testerNoteResult = this._stratonTesterNoteResultFromText(draft.testerNote);
    this._recordActivity(`Straton tester note analyzed: ${draft.testerNoteResult.title}`, draft.testerNoteResult.status === "ok" ? "control" : "warning");
    this._render();
  }

  _clearStratonTesterNote() {
    const draft = this._stratonEvidenceDraft();
    draft.testerNote = "";
    draft.testerNoteResult = null;
    this._render();
  }

  _stratonTesterNoteScenarioLabel(value) {
    return ({
      strong: "Strong AP read",
      lan: "LAN-only read",
      route: "AP route blocker",
      reachable: "Reachability only",
      bluetooth: "Reef Pilot Bluetooth",
    })[value] || "Strong AP read";
  }

  _stratonExampleTesterNoteText(scenario = "strong") {
    const key = ["strong", "lan", "route", "reachable", "bluetooth"].includes(scenario) ? scenario : "strong";
    const examples = {
      strong: {
        label: "Strong AP read",
        verdict: "Read-only bypass proven (ok)",
        detail: "Example note says OpenReef reached a brand-new/reset fixture through AP fallback and found JSON without using schedule writes.",
        next: "Use this as candidate adapter evidence; keep writes locked until current program and save/apply endpoints are verified.",
        setupClaim: "Pre-setup bypass candidate (ok)",
        setupDetail: "Example fixture was marked brand new/reset, AP fallback was selected, and a JSON read path was found.",
        setupNext: "Treat this as strong setup-bypass evidence only after a real tester reproduces it.",
        apRoute: "AP pre-setup read route (ok)",
        apRouteDetail: "Example controller route reached the direct Straton AP address and returned JSON.",
        apRouteNext: "Send the support note; keep writes locked until program readback and save/apply endpoints are verified.",
        reachablePaths: 3,
        jsonPaths: 1,
        scanRows: [
          "- best path: /api/config",
          "- /: /, ok, text, browser-direct",
          "- config: /api/config, ok, json, controller",
          "- status: /api/status, ok, text, controller",
        ],
        endpoints: {
          reachability: "/",
          current: "/api/config",
          program: "/api/config",
          firmware: "/api/config",
          groups: "/api/config",
        },
        fingerprint: "example1234",
        leaves: 18,
      },
      lan: {
        label: "LAN-only read",
        verdict: "Read-only bypass proven (ok)",
        detail: "Example note says OpenReef read JSON from an already-networked Straton on the home LAN.",
        next: "Use this for read mapping only; it does not prove ATI first-time setup was bypassed.",
        setupClaim: "LAN confidence only (unknown)",
        setupDetail: "Example fixture was already configured on the home network, so the read is not onboarding proof.",
        setupNext: "Repeat with AP fallback on a brand-new/reset or stuck setup fixture before claiming ATI setup replacement.",
        apRoute: "LAN configured route (unknown)",
        apRouteDetail: "Example route used the configured LAN host rather than the direct Straton AP address.",
        apRouteNext: "Use this as LAN read evidence only, then test AP fallback separately.",
        reachablePaths: 2,
        jsonPaths: 1,
        scanRows: [
          "- best path: /api/status",
          "- /: /, ok, text, controller",
          "- status: /api/status, ok, json, controller",
        ],
        endpoints: {
          reachability: "/",
          current: "/api/status",
          program: "not mapped",
          firmware: "/api/status",
          groups: "not mapped",
        },
        fingerprint: "lanread5678",
        leaves: 11,
      },
      route: {
        label: "AP route blocker",
        verdict: "Bypass not proven (warning)",
        detail: "Example note says the controller could not reach the direct Straton AP route.",
        next: "Fix controller-to-AP routing before treating this as an ATI setup or Straton endpoint failure.",
        setupClaim: "Pre-setup bypass candidate (warning)",
        setupDetail: "Example fixture was marked brand new/reset, but the controller could not route to the Straton AP address.",
        setupNext: "Move the controller/network onto a path that can reach the fixture AP, then scan again.",
        apRoute: "AP route not reachable (warning)",
        apRouteDetail: "Example controller could not reach 192.168.100.1 from the Home Assistant network.",
        apRouteNext: "Solve controller/AP routing before testing endpoint paths.",
        reachablePaths: 0,
        jsonPaths: 0,
        scanRows: [
          "- best path: not mapped",
          "- /: /, failed, none, controller",
          "- config: /api/config, failed, none, controller",
        ],
        endpoints: {
          reachability: "not mapped",
          current: "not mapped",
          program: "not mapped",
          firmware: "not mapped",
          groups: "not mapped",
        },
        fingerprint: "not available",
        leaves: 0,
      },
      reachable: {
        label: "Reachability only",
        verdict: "Reachability bypass only (unknown)",
        detail: "Example note says the controller reached the fixture root but did not find a useful JSON state path.",
        next: "Collect ATI export links or redacted browser network read paths, then retry Controller GET.",
        setupClaim: "Pre-setup evidence incomplete (unknown)",
        setupDetail: "Example fixture was reachable, but no current-state JSON path was found.",
        setupNext: "Scan more safe read paths before claiming setup replacement.",
        apRoute: "AP route reachable, no JSON (unknown)",
        apRouteDetail: "Example controller reached the direct Straton AP address, but only text/root responses were found.",
        apRouteNext: "Collect safe read-path hints and scan again.",
        reachablePaths: 1,
        jsonPaths: 0,
        scanRows: [
          "- best path: not mapped",
          "- /: /, ok, text, controller",
          "- config: /api/config, failed, none, controller",
        ],
        endpoints: {
          reachability: "/",
          current: "not mapped",
          program: "not mapped",
          firmware: "not mapped",
          groups: "not mapped",
        },
        fingerprint: "not available",
        leaves: 0,
      },
      bluetooth: {
        label: "Reef Pilot Bluetooth",
        verdict: "Reef Pilot Bluetooth evidence returned (unknown)",
        detail: "Example note reports Straton X/Reef Pilot Bluetooth app observations, not a ReefTECH AP read.",
        next: "Collect pairing/control, Live PAR/Energy, template/group, and schedule-save confirmation; keep writes locked.",
        setupClaim: "Bluetooth generation evidence (unknown)",
        setupDetail: "Example tester identified Straton X / Reef Pilot Bluetooth, so ReefTECH AP setup bypass was not tested.",
        setupNext: "Use this for Bluetooth adapter mapping only; do not treat it as Wi-Fi/AP setup proof.",
        apRoute: "Not Reef Pilot proof (unknown)",
        apRouteDetail: "AP route checks do not prove the Reef Pilot Bluetooth generation.",
        apRouteNext: "Collect real pairing/control, Live PAR/Energy, template/group, and schedule-save observations.",
        reachablePaths: 0,
        jsonPaths: 0,
        scanRows: [
          "- best path: not mapped",
          "- reef pilot: Bluetooth app evidence, not a GET endpoint",
        ],
        endpoints: {
          reachability: "not mapped",
          current: "not mapped",
          program: "not mapped",
          firmware: "not mapped",
          groups: "not mapped",
        },
        fingerprint: "not available",
        leaves: 0,
        hardwareGeneration: "Straton X / Reef Pilot Bluetooth",
        bluetoothControl: "Pairing/control notes returned",
        liveParEnergy: "Observed in Reef Pilot, values not exported",
        templatesGroups: "Template and group behavior observed",
        scheduleSave: "Save confirmation unclear",
      },
    };
    const item = examples[key];
    return [
      "OpenReef Straton support note",
      "Created: example only",
      `Example scenario: ${item.label}`,
      "",
      "Safety boundary",
      "- Hardware write: locked",
      "- Save local plan: saves OpenReef config/receipt only",
      "- Raw ATI exports/network notes: not included in this note",
      "",
      "ATI setup bypass test",
      `- verdict: ${item.verdict}`,
      `- detail: ${item.detail}`,
      `- next: ${item.next}`,
      `- setup claim: ${item.setupClaim}`,
      `- setup claim detail: ${item.setupDetail}`,
      `- setup claim next: ${item.setupNext}`,
      `- AP route: ${item.apRoute}`,
      `- AP route detail: ${item.apRouteDetail}`,
      `- AP route next: ${item.apRouteNext}`,
      ...(item.hardwareGeneration ? [
        "",
        "Hardware generation",
        `- hardware generation: ${item.hardwareGeneration}`,
        `- Bluetooth evidence: ${item.bluetoothControl}`,
        `- Live PAR/Energy: ${item.liveParEnergy}`,
        `- templates/groups: ${item.templatesGroups}`,
        `- schedule save: ${item.scheduleSave}`,
      ] : []),
      "",
      "Safe path scan",
      `- reachable paths: ${item.reachablePaths}`,
      `- JSON paths: ${item.jsonPaths}`,
      ...item.scanRows,
      "",
      "Read endpoint catalog",
      `- reachability: ${item.endpoints.reachability}`,
      `- current state: ${item.endpoints.current}`,
      `- program: ${item.endpoints.program}`,
      `- firmware: ${item.endpoints.firmware}`,
      `- groups: ${item.endpoints.groups}`,
      "",
      "Current fixture sample",
      `- schema fingerprint: ${item.fingerprint}`,
      `- leaf values: ${item.leaves}`,
      "",
      "Privacy",
      "- This example is synthetic and only rehearses the intake parser without a Straton.",
    ].join("\n");
  }

  _loadStratonExampleTesterNote() {
    const draft = this._stratonEvidenceDraft();
    const scenario = draft.testerNoteScenario || "strong";
    draft.testerNote = this._stratonExampleTesterNoteText(scenario);
    draft.testerNoteResult = this._stratonTesterNoteResultFromText(draft.testerNote);
    this._recordActivity(`Loaded example Straton tester note: ${this._stratonTesterNoteScenarioLabel(scenario)}`, "control");
    this._render();
  }

  _stratonReturnReviewRows(result) {
    if (!result || result.title === "No tester note") {
      return [
        {
          label: "Return type",
          status: "warning",
          state: "needed",
          detail: "Paste the tester's returned support note before judging setup bypass or adapter mapping.",
        },
        {
          label: "Write safety",
          status: "warning",
          state: "locked",
          detail: "No returned note can unlock writes until readback, save/apply, and rollback are verified on real hardware.",
        },
      ];
    }

    const title = String(result.title || "");
    const setupTitle = String(result.setupEvidenceTitle || "");
    const isExample = Boolean(result.example);
    const reefPilot = Boolean(result.reefPilotEvidence || /Reef Pilot Bluetooth/i.test(`${title} ${setupTitle}`));
    const strongSetup = !isExample && /Strong pre-setup evidence/i.test(setupTitle);
    const lanOnly = !isExample && /LAN read evidence only/i.test(setupTitle);
    const routeBlocker = !isExample && /Route blocker|Bypass not proven/i.test(`${title} ${setupTitle}`);
    const hasJsonRead = !isExample && (Number(result.jsonCount) > 0 || Boolean(result.endpoints?.currentState));
    const hasReachability = !isExample && (Number(result.reachableCount) > 0 || Boolean(result.endpoints?.reachability));
    const promotedCount = isExample ? 0 : Number(result.promoted?.length) || 0;

    const returnType = isExample
      ? {
        status: "unknown",
        state: "example only",
        detail: "Synthetic rehearsal note. Useful for checking the parser, but not hardware evidence.",
      }
      : reefPilot
        ? {
          status: "unknown",
          state: "Reef Pilot Bluetooth",
          detail: "Returned evidence belongs to the Straton X Bluetooth path, not ReefTECH Wi-Fi AP setup proof.",
        }
        : strongSetup
          ? {
            status: "ok",
            state: "AP setup evidence",
            detail: "Returned note claims AP route, pre-setup state, and JSON read evidence.",
          }
          : lanOnly
            ? {
              status: "unknown",
              state: "LAN read only",
              detail: "Useful adapter evidence, but it does not prove first-time ATI onboarding was bypassed.",
            }
            : routeBlocker
              ? {
                status: "warning",
                state: "route blocker",
                detail: "Controller/AP routing must be fixed before blaming the fixture or ATI endpoint contract.",
              }
              : hasJsonRead
                ? {
                  status: "unknown",
                  state: "read candidate",
                  detail: "Returned note has read evidence, but setup-bypass strength is still incomplete.",
                }
                : hasReachability
                  ? {
                    status: "unknown",
                    state: "reachable only",
                    detail: "The controller reached something, but no useful current-state JSON path was returned.",
                  }
                  : {
                    status: "warning",
                    state: "incomplete",
                    detail: "Returned note is missing the evidence needed to classify setup or read mapping.",
                  };

    const setupReview = isExample
      ? {
        status: "warning",
        state: "not proven",
        detail: "Examples must never count as ATI setup-bypass proof.",
      }
      : reefPilot
        ? {
          status: "unknown",
          state: "not AP proof",
          detail: "For Straton X, collect Bluetooth pairing/control evidence instead of AP-route proof.",
        }
        : strongSetup
          ? {
            status: "ok",
            state: "candidate supported",
            detail: "This supports the setup-bypass claim, but hardware writes remain separate.",
          }
          : routeBlocker
            ? {
              status: "warning",
              state: "blocked",
              detail: "The controller cannot prove setup bypass until it can route to the fixture/AP.",
            }
            : {
              status: "unknown",
              state: "not proven",
              detail: "Current return does not prove OpenReef avoids ATI's first setup path.",
            };

    const readReview = isExample
      ? {
        status: "warning",
        state: "ignored",
        detail: "Example JSON paths are rehearsal data only.",
      }
      : reefPilot
        ? {
          status: "unknown",
          state: "Bluetooth observations",
          detail: "Use Live PAR/Energy, control-state, template/group, and schedule-save observations for the Bluetooth adapter path.",
        }
        : hasJsonRead
          ? {
            status: "ok",
            state: "candidate found",
            detail: "A safe read candidate exists for adapter mapping; verify repeatability before writes.",
          }
          : hasReachability
            ? {
              status: "unknown",
              state: "reachable only",
              detail: "Collect a current-state JSON/read path before mapping program behavior.",
            }
            : {
              status: "warning",
              state: "needed",
              detail: "No usable read evidence was returned.",
            };

    const catalogReview = promotedCount
      ? {
        status: "ok",
        state: `${promotedCount} promoted`,
        detail: "Only safe read-path candidates were promoted from the real returned note.",
      }
      : isExample
        ? {
          status: "unknown",
          state: "none",
          detail: "Examples do not promote endpoint candidates.",
        }
        : reefPilot
          ? {
            status: "unknown",
            state: "not Wi-Fi endpoints",
            detail: "Bluetooth evidence is kept separate from the ReefTECH Wi-Fi read catalog.",
          }
          : {
            status: "warning",
            state: "none",
            detail: "No safe endpoint candidate was promoted from this return.",
          };

    return [
      { label: "Return type", ...returnType },
      { label: "Setup bypass", ...setupReview },
      { label: "Read mapping", ...readReview },
      { label: "Endpoint catalog", ...catalogReview },
      {
        label: "Write safety",
        status: "warning",
        state: "locked",
        detail: "This review never unlocks hardware writes; save/apply still needs verified readback and rollback proof.",
      },
    ];
  }

  _stratonEvidenceSummaryText() {
    const draft = this._stratonEvidenceDraft();
    const result = draft.result;
    const testerNote = draft.testerNoteResult;
    if (!result && !testerNote) return "No Straton adapter evidence summary yet.";
    const probe = draft.probeResult;
    const scan = draft.probeScanResult;
    const fixtureState = draft.fixtureStateResult;
    const scanOutcome = scan ? this._stratonScanOutcome(scan) : null;
    const bypass = this._stratonSetupBypassStatus(scan, this._stratonProbeFixture());
    const bypassClaim = this._stratonSetupBypassClaim(scan, this._stratonProbeFixture());
    const route = this._stratonApRouteStatus(scan, this._stratonProbeFixture());
    const endpoints = this._stratonEndpoints();
    const proofSummaryLines = this._stratonProofSummaryRows()
      .map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    const betaEvidenceLines = this._stratonBetaEvidenceRows()
      .map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    const extraProbePaths = this._stratonExtraProbePathPresets(draft.extraProbePaths);
    const focus = Object.entries(result?.focusCounts || {})
      .map(([name, count]) => `${name}: ${count}`)
      .join(", ") || "none";
    const coverageLines = this._stratonEvidenceCoverageRows(result)
      .map((row) => `- ${row.label}: ${row.state}, ${row.status}`);
    const painPointCoverageLines = this._stratonPainPointCoverageRows()
      .map((row) => `- ${row.label}: ${row.state}, ${row.status}`);
    const returnReviewLines = this._stratonReturnReviewRows(testerNote)
      .map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    return [
      "OpenReef Straton adapter evidence summary",
      `Checked: ${result?.checkedAt || testerNote?.checkedAt || "not checked"}`,
      `Mode: ${result?.mode || "tester-note"}`,
      `Changed: ${result?.changedCount || 0}, added: ${result?.addedCount || 0}, removed: ${result?.removedCount || 0}`,
      `Focus: ${focus}`,
      result?.warning ? `Parse note: ${result.warning}` : "",
      "",
      "Changed paths",
      ...(result?.rows?.length ? result.rows.map((row) => `- ${row.kind}: ${row.path} (${row.focus})`) : ["- none"]),
      "",
      "Endpoint hints",
      ...(result?.endpoints?.length ? result.endpoints.map((row) => `- ${row.method} ${row.path}`) : ["- none pasted"]),
      "",
      "Evidence coverage",
      ...coverageLines,
      "",
      "Proof summary",
      ...proofSummaryLines,
      "",
      "Beta hardware evidence checklist",
      ...betaEvidenceLines,
      "",
      "Pain-point coverage",
      ...painPointCoverageLines,
      "",
      "Returned tester note",
      ...(testerNote ? [
        `- checked: ${testerNote.checkedAt}`,
        `- verdict: ${testerNote.title} (${testerNote.status})`,
        `- reachable/json: ${testerNote.reachableCount || 0}/${testerNote.jsonCount || 0}`,
        `- setup evidence: ${testerNote.setupEvidenceTitle || "not assessed"} (${testerNote.setupEvidenceStatus || "unknown"})`,
        testerNote.setupEvidenceDetail ? `- setup evidence detail: ${testerNote.setupEvidenceDetail}` : "",
        testerNote.apRouteTitle ? `- AP route: ${testerNote.apRouteTitle} (${testerNote.apRouteStatus || "unknown"})` : "",
        testerNote.apRouteDetail ? `- AP route detail: ${testerNote.apRouteDetail}` : "",
        testerNote.reefPilotEvidence ? `- hardware generation: ${testerNote.hardwareGeneration || "Straton X / Reef Pilot Bluetooth"}` : "",
        testerNote.bluetoothControl ? `- Bluetooth evidence: ${testerNote.bluetoothControl}` : "",
        testerNote.liveParEnergy ? `- Live PAR/Energy: ${testerNote.liveParEnergy}` : "",
        testerNote.templatesGroups ? `- templates/groups: ${testerNote.templatesGroups}` : "",
        testerNote.scheduleSave ? `- schedule save: ${testerNote.scheduleSave}` : "",
        `- schema fingerprint: ${testerNote.schemaFingerprint || "not included"}`,
        `- local schema fingerprint: ${testerNote.localSchemaFingerprint || "not analyzed"}`,
        `- schema compare: ${testerNote.schemaFingerprintTitle || "not compared"} (${testerNote.schemaFingerprintStatus || "unknown"})`,
        `- next: ${testerNote.next}`,
        ...(testerNote.promoted || []).map((item) => `- promoted: ${item}`),
      ] : ["- not analyzed"]),
      "",
      "Beta return review",
      ...returnReviewLines,
      "",
      "Read-only endpoint probe",
      ...(probe ? [
        `- ${probe.method || "GET"} ${probe.path || "unknown"} on ${probe.fixtureName || "unknown fixture"}`,
        `- source: ${probe.source || "unknown"}`,
        `- status: ${probe.status}`,
        `- content: ${probe.contentType || "unknown"}, ${probe.bytes || 0} bytes, ${probe.mode || "unknown"}`,
        probe.warning ? `- note: ${probe.warning}` : "",
      ].filter(Boolean) : ["- not run"]),
      "",
      "Current fixture sample",
      ...(fixtureState ? [
        `- schema fingerprint: ${fixtureState.schemaFingerprint?.id || "not available"}`,
        `- leaf values: ${fixtureState.leafCount || 0}`,
        `- focus counts: ${Object.entries(fixtureState.focusCounts || {}).map(([name, count]) => `${name}: ${count}`).join(", ") || "none"}`,
        ...(fixtureState.promotedEndpoints || []).map((item) => `- promoted ${item.kind}: ${item.path}, ${item.state}`),
      ] : ["- not analyzed"]),
      "",
      "Safe path scan",
      ...(scan ? [
        `- fixture: ${scan.fixtureName || "unknown"} (${scan.host || "redacted"})`,
        `- extra safe paths queued: ${extraProbePaths.length}`,
        `- reachable/json: ${scan.reachableCount || 0}/${scan.jsonCount || 0}`,
        scanOutcome ? `- outcome: ${scanOutcome.title}` : "",
        scanOutcome ? `- next: ${scanOutcome.next}` : "",
        scan.bestPath ? `- best path: ${scan.bestPath}` : "",
        ...(scan.rows || []).map((row) => `- ${row.path}: ${row.status}, ${row.mode}, ${row.contentType}`),
      ].filter(Boolean) : ["- not run"]),
      "",
      "ATI setup bypass status",
      `- verdict: ${bypass.title}`,
      `- detail: ${bypass.detail}`,
      `- next: ${bypass.next}`,
      `- setup claim: ${bypassClaim.title} (${bypassClaim.status})`,
      `- setup claim detail: ${bypassClaim.detail}`,
      `- AP route: ${route.title} (${route.status})`,
      `- AP route detail: ${route.detail}`,
      `- AP route next: ${route.next}`,
      "",
      "Read endpoint catalog",
      `- reachability: ${endpoints.reachability || "not mapped"}`,
      `- current state: ${endpoints.currentState || "not mapped"}`,
      `- program: ${endpoints.program || "not mapped"}`,
      `- firmware: ${endpoints.firmware || "not mapped"}`,
      `- groups: ${endpoints.groups || "not mapped"}`,
      "",
      "Privacy",
      "- Raw exports and network text were not saved by this panel.",
    ].filter(Boolean).join("\n");
  }

  async _copyStratonEvidenceSummary() {
    await this._copyText(this._stratonEvidenceSummaryText(), "Straton evidence summary copied", "Could not copy Straton evidence summary");
  }

  _stratonSupportNoteText() {
    const straton = this._stratonConfig();
    const program = this._stratonProgram();
    const template = this._stratonTemplate(straton.selectedTemplate);
    const liveRows = this._stratonLightLiveRows();
    const syncRows = this._stratonFixtureSyncRows(liveRows);
    const [readinessClass, readinessTitle, readinessDetail] = this._stratonReadiness();
    const [bridgeClass, bridgeTitle, bridgeDetail] = this._stratonLiveBridgeSummary(liveRows);
    const draft = this._stratonEvidenceDraft();
    const evidence = draft.result;
    const fixtureState = draft.fixtureStateResult;
    const probe = draft.probeResult;
    const scan = draft.probeScanResult;
    const testerNote = draft.testerNoteResult;
    const scanOutcome = scan ? this._stratonScanOutcome(scan) : null;
    const bypass = this._stratonSetupBypassStatus(scan, this._stratonProbeFixture());
    const bypassClaim = this._stratonSetupBypassClaim(scan, this._stratonProbeFixture());
    const route = this._stratonApRouteStatus(scan, this._stratonProbeFixture());
    const endpoints = this._stratonEndpoints();
    const adapterGateRows = this._stratonAdapterGateRows();
    const proofSummaryRows = this._stratonProofSummaryRows(adapterGateRows);
    const betaEvidenceRows = this._stratonBetaEvidenceRows();
    const evidenceCoverageRows = this._stratonEvidenceCoverageRows(evidence);
    const painPointCoverageRows = this._stratonPainPointCoverageRows();
    const extraProbePaths = this._stratonExtraProbePathPresets(draft.extraProbePaths);
    const targets = syncRows.filter((row) => row.fixture.selected);
    const groups = [...new Set(syncRows.map((row) => row.group))];
    const fixtures = syncRows.length
      ? syncRows.map((row) => [
        `- ${row.fixture.name || "Straton fixture"}`,
        `target: ${row.targetLabel}`,
        `group: ${row.groupLabel}`,
        `host: ${this._stratonRedactSnippet(row.fixture.host || "not set")}`,
        `connection: ${this._stratonConnectionModeLabel(row.fixture.connectionMode)}`,
        `setup: ${this._stratonSetupStateLabel(row.fixture.setupState)}`,
        `firmware: ${row.fixture.firmware || "unknown"} (${row.firmwareLabel})`,
        `live bridge: ${row.liveLabel}${row.liveEntityId ? ` via ${row.liveEntityId}` : ""}`,
        `write: planned only`,
      ].join(", "))
      : ["- none configured"];
    const live = liveRows.length
      ? liveRows.map((row) => [
        `- ${row.item?.label || row.id}`,
        `entity: ${row.entityId || "not mapped"}`,
        `status: ${row.statusLabel}`,
        row.brightnessPct !== null ? `brightness: ${row.brightnessPct}%` : "",
        row.effect ? `effect: ${row.effect}` : "",
        row.colorLabel ? `colour: ${row.colorLabel}` : "",
        row.detail,
      ].filter(Boolean).join(", "))
      : ["- no lighting equipment rows"];
    const evidenceLines = evidence
      ? [
        `- checked: ${evidence.checkedAt}`,
        `- comparison: ${evidence.mode}`,
        `- changed/added/removed: ${evidence.changedCount}/${evidence.addedCount}/${evidence.removedCount}`,
        `- focus: ${Object.entries(evidence.focusCounts || {}).map(([name, count]) => `${name}: ${count}`).join(", ") || "none"}`,
        `- endpoint hints: ${evidence.endpoints?.length || 0}`,
      ]
      : ["- no adapter evidence analyzed in this browser session"];
    const testerNoteLines = testerNote
      ? [
        `- checked: ${testerNote.checkedAt}`,
        `- verdict: ${testerNote.title} (${testerNote.status})`,
        `- reachable/json: ${testerNote.reachableCount || 0}/${testerNote.jsonCount || 0}`,
        `- setup evidence: ${testerNote.setupEvidenceTitle || "not assessed"} (${testerNote.setupEvidenceStatus || "unknown"})`,
        testerNote.setupEvidenceDetail ? `- setup evidence detail: ${testerNote.setupEvidenceDetail}` : "",
        testerNote.apRouteTitle ? `- AP route: ${testerNote.apRouteTitle} (${testerNote.apRouteStatus || "unknown"})` : "",
        testerNote.apRouteDetail ? `- AP route detail: ${testerNote.apRouteDetail}` : "",
        testerNote.reefPilotEvidence ? `- hardware generation: ${testerNote.hardwareGeneration || "Straton X / Reef Pilot Bluetooth"}` : "",
        testerNote.bluetoothControl ? `- Bluetooth evidence: ${testerNote.bluetoothControl}` : "",
        testerNote.liveParEnergy ? `- Live PAR/Energy: ${testerNote.liveParEnergy}` : "",
        testerNote.templatesGroups ? `- templates/groups: ${testerNote.templatesGroups}` : "",
        testerNote.scheduleSave ? `- schedule save: ${testerNote.scheduleSave}` : "",
        `- schema fingerprint: ${testerNote.schemaFingerprint || "not included"}`,
        `- local schema fingerprint: ${testerNote.localSchemaFingerprint || "not analyzed"}`,
        `- schema compare: ${testerNote.schemaFingerprintTitle || "not compared"} (${testerNote.schemaFingerprintStatus || "unknown"})`,
        `- next: ${testerNote.next}`,
        ...(testerNote.promoted || []).map((item) => `- promoted: ${item}`),
      ].filter(Boolean)
      : ["- no returned tester note analyzed in this browser session"];
    const returnReviewLines = this._stratonReturnReviewRows(testerNote)
      .map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    const fixtureStateLines = fixtureState
      ? [
        `- checked: ${fixtureState.checkedAt}`,
        `- mode: ${fixtureState.mode}`,
        `- schema fingerprint: ${fixtureState.schemaFingerprint?.id || "not available"}`,
        `- leaf values: ${fixtureState.leafCount}`,
        `- focus counts: ${Object.entries(fixtureState.focusCounts || {}).map(([name, count]) => `${name}: ${count}`).join(", ") || "none"}`,
        `- close matches: ${fixtureState.observations?.filter((item) => item.status === "ok").length || 0}/${fixtureState.observations?.length || 0}`,
        ...(fixtureState.promotedEndpoints || []).map((item) => `- promoted ${item.kind}: ${item.path}, ${item.state}`),
        ...(fixtureState.observations || []).map((item) => `- ${item.label}: planned ${item.planned}, observed ${item.observed}, ${item.status}`),
      ]
      : ["- no current fixture sample analyzed in this browser session"];
    const probeLines = probe
      ? [
        `- checked: ${probe.checkedAt}`,
        `- source: ${probe.source || "unknown"}`,
        `- fixture: ${probe.fixtureName}`,
        `- host: ${probe.host}`,
        `- request: ${probe.method || "GET"} ${probe.path || "unknown"}`,
        `- status: ${probe.status}`,
        `- content: ${probe.contentType || "unknown"}, ${probe.bytes || 0} bytes, ${probe.mode || "unknown"}`,
        probe.warning ? `- note: ${probe.warning}` : "",
      ].filter(Boolean)
      : ["- no read-only endpoint probe run in this browser session"];
    const scanLines = scan
      ? [
        `- checked: ${scan.checkedAt}`,
        `- fixture: ${scan.fixtureName || "unknown"}`,
        `- host: ${scan.host || "redacted"}`,
        `- extra safe paths queued: ${extraProbePaths.length}`,
        `- reachable paths: ${scan.reachableCount || 0}`,
        `- JSON paths: ${scan.jsonCount || 0}`,
        scanOutcome ? `- outcome: ${scanOutcome.title}` : "",
        scanOutcome ? `- next: ${scanOutcome.next}` : "",
        scan.bestPath ? `- best path: ${scan.bestPath}` : "",
        ...(scan.rows || []).map((row) => `- ${row.label || row.path}: ${row.path}, ${row.status}, ${row.mode}`),
        scan.warning ? `- note: ${scan.warning}` : "",
      ].filter(Boolean)
      : ["- no safe path scan run in this browser session"];
    const endpointLines = [
      `- reachability: ${endpoints.reachability || "not mapped"}`,
      `- current state: ${endpoints.currentState || "not mapped"}`,
      `- program: ${endpoints.program || "not mapped"}`,
      `- firmware: ${endpoints.firmware || "not mapped"}`,
      `- groups: ${endpoints.groups || "not mapped"}`,
      endpoints.lastScanAt ? `- last scan: ${endpoints.lastScanAt} (${endpoints.lastOutcome || "candidate updated"})` : "- last scan: none",
    ];
    const gateLines = [
      "- write state: locked",
      ...adapterGateRows.map((row) => `- ${row.label}: ${row.state}, ${row.status}`),
    ];
    const proofSummaryLines = proofSummaryRows.map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    const betaEvidenceLines = betaEvidenceRows.map((row) => `- ${row.label}: ${row.state}, ${row.status} - ${row.detail}`);
    const coverageLines = evidenceCoverageRows.map((row) => `- ${row.label}: ${row.state}, ${row.status}`);
    const painPointCoverageLines = painPointCoverageRows.map((row) => `- ${row.label}: ${row.state}, ${row.status}`);
    return [
      "OpenReef Straton support note",
      `Created: ${new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" })}`,
      `OpenReef version: ${this._integrationVersion || "unknown"}`,
      "",
      "Safety boundary",
      "- Hardware write: locked",
      "- Save local plan: saves OpenReef config/receipt only",
      "- Raw ATI exports/network notes: not included in this note",
      "",
      "ATI setup bypass test",
      `- verdict: ${bypass.title} (${bypass.status})`,
      `- detail: ${bypass.detail}`,
      `- next: ${bypass.next}`,
      `- setup claim: ${bypassClaim.title} (${bypassClaim.status})`,
      `- setup claim detail: ${bypassClaim.detail}`,
      `- setup claim next: ${bypassClaim.next}`,
      `- AP route: ${route.title} (${route.status})`,
      `- AP route detail: ${route.detail}`,
      `- AP route next: ${route.next}`,
      "",
      "Proof summary",
      ...proofSummaryLines,
      "",
      "Beta hardware evidence checklist",
      ...betaEvidenceLines,
      "",
      "Pain-point coverage",
      ...painPointCoverageLines,
      "",
      "Planner",
      `- readiness: ${readinessTitle} (${readinessClass}) - ${readinessDetail}`,
      `- adapter: ${this._stratonAdapterLabel(straton.adapter)}`,
      `- template: ${template.name} (${template.source})`,
      `- selected targets: ${targets.length}/${syncRows.length}`,
      `- groups: ${groups.join(", ") || "none"}`,
      `- receipt: ${straton.lastReceipt || "none"}`,
      "",
      "Program",
      `- peak: ${Number(program.peak) || 0}%`,
      `- start: ${program.startTime || "10:00"}`,
      `- photoperiod: ${Number(program.photoperiodHours) || 10} hours`,
      `- ramp: ${Number(program.rampMinutes) || 90} minutes`,
      `- quick mode: ${this._stratonQuickLabel(program.quickMode)}`,
      `- cloud dim: ${Number(program.cloudDim) || 0}%`,
      `- moonlight: ${Number(program.moonlight) || 0}% (${program.lunarMode || "manual"})`,
      `- acclimation: ${Number(program.acclimationStart) || 0}% to ${Number(program.acclimationTarget) || 0}% over ${Number(program.acclimationDays) || 1} days`,
      "",
      "Fixtures",
      ...fixtures,
      "",
      "Live Home Assistant bridge",
      `- summary: ${bridgeTitle} (${bridgeClass}) - ${bridgeDetail}`,
      ...live,
      "",
      "Adapter evidence",
      ...evidenceLines,
      "",
      "Evidence coverage",
      ...coverageLines,
      "",
      "Returned tester note intake",
      ...testerNoteLines,
      "",
      "Beta return review",
      ...returnReviewLines,
      "",
      "Read-only endpoint probe",
      ...probeLines,
      "",
      "Safe path scan",
      ...scanLines,
      "",
      "Read endpoint catalog",
      ...endpointLines,
      "",
      "Hardware adapter gate",
      ...gateLines,
      "",
      "Current fixture sample",
      ...fixtureStateLines,
      "",
      "Next evidence needed",
      "- ATI settings export before and after one schedule edit",
      "- ATI settings export before and after one spectrum/channel edit",
      "- ATI settings export before and after grouping two fixtures",
      "- Browser network method/path notes for load, save, and apply",
      "- Firmware/model strings for each Straton generation being tested",
    ].join("\n");
  }

  async _copyStratonSupportNote() {
    await this._copyText(this._stratonSupportNoteText(), "Straton support note copied", "Could not copy Straton support note");
  }

  _stratonBetaUpdateText() {
    return [
      "OpenReef Straton beta update",
      "",
      "I have pushed a new read-only Straton light test into OpenReef. Please update/reload your OpenReef install first, then open:",
      "",
      "Home Assistant -> OpenReef -> Lights",
      "",
      "Important safety boundary:",
      "- Please do not apply an OpenReef schedule to the Straton yet.",
      "- Save local plan only creates an OpenReef receipt.",
      "- Hardware writes are still locked until readback, save/apply, and rollback evidence are proven.",
      "",
      "First thing to tell me:",
      "1. Is your light ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth?",
      "2. Is the light already on your LAN, brand new/reset, or stuck in ATI setup?",
      "",
      "If it is ReefTECH Wi-Fi:",
      "1. Add/select the fixture in the Lights tab.",
      "2. Set the adapter to ReefTECH Wi-Fi.",
      "3. Set Connection path and Setup state.",
      "4. Expand Advanced Straton tools.",
      "5. If testing first-time/stuck setup, click Use AP fallback.",
      "6. Click Scan safe paths.",
      "7. Copy the Straton support note back to me.",
      "",
      "If it is Straton X / Reef Pilot Bluetooth:",
      "1. Set the adapter to Reef Pilot Bluetooth.",
      "2. Do not treat AP route as proof for this hardware.",
      "3. Send pairing/control notes, Live PAR/Energy observations, template/group behaviour, and whether schedule saves are clearly confirmed.",
      "",
      "What I need back:",
      "- The copied Straton support note.",
      "- Whether OpenReef found a JSON/read path, reached only the root page, or could not reach the light.",
      "- Any redacted screenshots or notes that do not include passwords, tokens, Wi-Fi credentials, account details, or public IPs.",
      "",
      "The goal of this test is only to prove whether OpenReef can reach/read the light or collect Bluetooth evidence before guessing any hardware adapter.",
    ].join("\n");
  }

  async _copyStratonBetaUpdate() {
    await this._copyText(this._stratonBetaUpdateText(), "Straton beta update copied", "Could not copy Straton beta update");
  }

  _stratonTesterStepsText() {
    const fixture = this._stratonProbeFixture();
    const draft = this._stratonEvidenceDraft();
    const adapterLabel = this._stratonAdapterLabel(this._stratonConfig().adapter);
    const bypass = this._stratonSetupBypassStatus(draft.probeScanResult, fixture);
    const claim = this._stratonSetupBypassClaim(draft.probeScanResult, fixture);
    const route = this._stratonApRouteStatus(draft.probeScanResult, fixture);
    return [
      "OpenReef Straton beta connection test",
      "",
      "Please test the OpenReef Straton connection only. Do not change your live ATI lighting schedule yet.",
      "",
      "Steps:",
      "1. Open Home Assistant.",
      "2. Open OpenReef.",
      "3. Go to Lights.",
      "4. Tell me the hardware generation: ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth.",
      "5. Set Adapter to the matching generation.",
      "6. Add your ATI Straton as a fixture if it is not already listed.",
      "7. If you know the Straton LAN IP, enter it in IP or host.",
      "8. Set Connection path to LAN IP/host, AP fallback, or Unknown path.",
      "9. Set Setup state to Already on LAN, Brand new/reset, Stuck in setup, or Unknown setup.",
      "10. Expand Advanced Straton tools.",
      "11. For ReefTECH Wi-Fi, click Use AP fallback if testing first-time/stuck setup.",
      "12. Click Scan safe paths for ReefTECH Wi-Fi evidence.",
      "13. For Straton X / Reef Pilot Bluetooth, do not treat AP fallback as proof; collect Bluetooth app/control evidence instead.",
      "14. Copy the Straton support note.",
      "15. Send the support note back with the result shown on screen.",
      "",
      "Tell me which result you saw:",
      "- Read-only bypass proven",
      "- Reachability bypass only",
      "- Bypass not proven",
      "- Bypass untested",
      "- JSON/read path found, root only, or not reachable",
      "- Hardware generation: ReefTECH Wi-Fi or Reef Pilot Bluetooth",
      "",
      "What this test means:",
      "- It is read-only.",
      "- It does not save a schedule to the light.",
      "- It does not push Wi-Fi credentials.",
      "- For ReefTECH Wi-Fi it checks whether OpenReef can reach/read the Straton before relying on ATI's app setup flow.",
      "- For Reef Pilot Bluetooth it only records the separate evidence path; OpenReef does not speak Bluetooth yet.",
      "",
      "AP fallback note:",
      "- AP fallback only works if the Home Assistant controller can actually reach the Straton AP network.",
      "- A phone connected to the Straton AP is not enough if the Home Assistant box is still on the home LAN with no route to 192.168.100.1.",
      "- If AP route says not reachable, do not treat this as a failed light. Treat it as a network-route problem to solve first.",
      "",
      "Current OpenReef status:",
      `- adapter: ${adapterLabel}`,
      `- fixture: ${fixture?.name || "not selected"}`,
      `- bypass verdict: ${bypass.title}`,
      `- setup claim: ${claim.title}`,
      `- AP route: ${route.title} (${route.status})`,
      `- AP route detail: ${route.detail}`,
      `- next: ${bypass.next}`,
    ].join("\n");
  }

  async _copyStratonTesterSteps() {
    await this._copyText(this._stratonTesterStepsText(), "Straton tester steps copied", "Could not copy Straton tester steps");
  }

  _stratonAdapterEvidenceRequestText() {
    const gateRows = this._stratonAdapterGateRows();
    const blocked = gateRows.filter((row) => row.status === "warning");
    const adapterLabel = this._stratonAdapterLabel(this._stratonConfig().adapter);
    return [
      "OpenReef Straton adapter evidence request",
      "",
      "Please collect this only if you are comfortable using ATI's app and browser/network tools. Do not change your normal reef schedule permanently for this test.",
      "",
      "Goal:",
      "- Map ATI Straton read/save/apply behavior safely.",
      "- Keep each test to one tiny change so OpenReef can identify exactly which fields changed.",
      "- Do not send passwords, Wi-Fi credentials, tokens, or full private URLs.",
      `- Current OpenReef adapter selection: ${adapterLabel}.`,
      "",
      "Before each mini-test:",
      "1. Write down the hardware generation: ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth.",
      "2. Copy/export the current ATI settings if the ATI app offers an export/backup option.",
      "3. Write down the fixture model, firmware, and whether it is in a group.",
      "4. Write down whether the light is already on LAN, brand new/reset, stuck in setup, or paired through Reef Pilot Bluetooth.",
      "5. If using browser developer tools, keep only method/path notes such as GET /settings or POST /api/...",
      "",
      "ReefTECH Wi-Fi mini-tests to run one at a time:",
      "1. Change only peak intensity by a small amount, then export/capture again.",
      "2. Change only one schedule time by a small amount, then export/capture again.",
      "3. Change only one spectrum/channel value by a small amount, then export/capture again.",
      "4. If you have multiple Stratons, change only grouping or target membership, then export/capture again.",
      "5. If there is an apply/save button, capture the method/path only. Do not send raw tokens or credentials.",
      "",
      "Straton X / Reef Pilot Bluetooth evidence to collect instead:",
      "1. App name/version and phone OS.",
      "2. Whether Bluetooth pairing/discovery worked first time, needed retries, or lost the fixture.",
      "3. Whether Reef Pilot shows Live PAR and Live Energy, and whether those values change after a small intensity change.",
      "4. Whether templates/coral-farmer presets can be viewed, applied, exported, or shared.",
      "5. Whether group control can target one fixture versus all fixtures clearly.",
      "6. Whether schedule changes visibly confirm saved/applied state.",
      "7. Screenshots are okay only if they do not include private network/account details.",
      "",
      "Send back:",
      "- Before export and after export for each mini-test, if available.",
      "- Redacted method/path notes for load, save, and apply flows.",
      "- Reef Pilot Bluetooth pairing/control notes if testing Straton X.",
      "- Live PAR/Energy, template/group, and schedule-save observations if Reef Pilot exposes them.",
      "- Model and firmware strings.",
      "- Setup state: already on LAN, brand new/reset, stuck in setup, paired through Reef Pilot Bluetooth, or unknown.",
      "- Whether this was AP mode, normal LAN mode, or Reef Pilot Bluetooth.",
      "- The OpenReef Straton support note after any safe path scan.",
      "- Any extra relative GET paths tested through Extra safe GET paths.",
      "",
      "Current OpenReef write gate:",
      ...gateRows.map((row) => `- ${row.label}: ${row.state} (${row.status})`),
      "",
      blocked.length
        ? `Main blockers right now: ${blocked.map((row) => row.label).join(", ")}.`
        : "No blocked rows are shown, but OpenReef still needs real hardware readback before writes are enabled.",
      "",
      "Safety boundary:",
      "- OpenReef is still read-only for Straton hardware.",
      "- Do not expect OpenReef to push a schedule yet.",
      "- The evidence is used to build and verify the future adapter.",
    ].join("\n");
  }

  async _copyStratonAdapterEvidenceRequest() {
    await this._copyText(this._stratonAdapterEvidenceRequestText(), "Straton adapter evidence request copied", "Could not copy Straton adapter evidence request");
  }

  _stratonScanOutcome(result, fixture = this._stratonProbeFixture()) {
    if (!result) {
      return {
        status: "unknown",
        title: "Not scanned",
        detail: "Run a safe path scan before judging Straton reachability.",
        next: "Use AP fallback or enter a LAN IP, then scan safe paths.",
      };
    }
    if (result.jsonCount > 0) {
      return {
        status: "ok",
        title: "Read path found",
        detail: `${result.jsonCount} JSON path(s) found; ${result.bestPath || "the best response"} is ready for comparison.`,
        next: "Send the support note so the endpoint can be mapped into the adapter.",
      };
    }
    if (result.reachableCount > 0) {
      return {
        status: "unknown",
        title: "Reachable, no JSON",
        detail: "The controller can talk to the fixture, but the built-in paths did not return usable JSON.",
        next: "Capture ATI app network paths or export links, then try the exact read path in the adapter lab.",
      };
    }
    const host = String(fixture?.host || "").trim();
    const apMode = host === "192.168.100.1" || fixture?.connectionMode === "ap";
    return {
      status: "warning",
      title: "Not reachable",
      detail: apMode
        ? "The AP fallback address did not answer from the OpenReef controller."
        : "No safe path answered from the configured fixture host.",
      next: apMode
        ? "Check whether the controller is on the Straton AP network; otherwise try the fixture LAN IP."
      : "Try AP fallback or confirm the fixture LAN IP/hostname from the router.",
    };
  }

  _stratonApRouteStatus(result = this._stratonEvidenceDraft().probeScanResult, fixture = this._stratonProbeFixture()) {
    const draft = this._stratonEvidenceDraft();
    const probe = draft.probeResult;
    const host = String(fixture?.host || "").trim();
    const apMode = host === "192.168.100.1" || fixture?.connectionMode === "ap";
    const setupState = fixture?.setupState || "unknown";
    const preSetup = ["brand_new", "stuck_setup"].includes(setupState);
    const scanning = Boolean(draft.probeScanning || result?.warning === "Safe path scan in progress.");
    const scanReachable = Number(result?.reachableCount) || 0;
    const scanJson = Number(result?.jsonCount) || 0;
    const probeReachable = Boolean(probe && ["ok", "unknown"].includes(probe.statusClass) && !["not run", "reading"].includes(probe.status));
    const probeJson = probe?.mode === "json" && probe.statusClass === "ok";
    const reachable = scanReachable > 0 || probeReachable;
    const jsonReady = scanJson > 0 || probeJson;
    const sourceList = [
      ...(result?.rows || []).map((row) => row.source),
      probe?.source,
    ].filter(Boolean);
    const source = [...new Set(sourceList)].slice(0, 2).join(", ") || "not tested";
    if (!fixture) {
      return {
        status: "warning",
        title: "No route target",
        detail: "Add a Straton fixture before testing AP or LAN reachability.",
        next: "Add a fixture, then choose LAN IP/host or AP fallback.",
        source,
      };
    }
    if (!apMode) {
      return {
        status: reachable ? "ok" : "unknown",
        title: reachable ? "LAN route reachable" : "LAN route selected",
        detail: reachable
          ? "OpenReef has reachability evidence for the configured LAN host. This does not prove ATI setup was bypassed."
          : "OpenReef is targeting the fixture's LAN host/IP, so this is not an AP setup-bypass test yet.",
        next: "Use AP fallback on a brand-new/reset or stuck setup fixture before claiming setup replacement.",
        source,
      };
    }
    if (scanning) {
      return {
        status: "unknown",
        title: "AP route scanning",
        detail: "OpenReef is checking whether the controller can reach the direct Straton AP address.",
        next: "Wait for the safe path scan before opening ATI's app.",
        source,
      };
    }
    if (jsonReady) {
      return {
        status: "ok",
        title: preSetup ? "AP pre-setup read route" : "AP JSON route found",
        detail: preSetup
          ? "AP fallback is selected, the fixture is marked brand new/reset or stuck in setup, and OpenReef found JSON."
          : "AP fallback is selected and OpenReef found JSON. Confirm setup state before calling it a setup bypass.",
        next: "Send the support note; keep writes locked until program readback and save/apply endpoints are verified.",
        source,
      };
    }
    if (reachable) {
      return {
        status: "unknown",
        title: "AP route reachable",
        detail: "The controller can reach the Straton AP address, but OpenReef has not found useful JSON yet.",
        next: "Collect safe read paths from ATI exports or redacted network notes, then scan again.",
        source,
      };
    }
    if (result || probe) {
      return {
        status: "warning",
        title: "AP route not reachable",
        detail: "The selected OpenReef read path cannot currently reach 192.168.100.1.",
        next: "Put the Home Assistant/controller network where it can reach the Straton AP, or use the fixture LAN IP if setup is already complete.",
        source,
      };
    }
    return {
      status: "unknown",
      title: "AP route untested",
      detail: "AP fallback is staged, but OpenReef has not checked controller-to-fixture reachability yet.",
      next: "Click Scan safe paths before asking the tester to use ATI's app.",
      source,
    };
  }

  _stratonSetupBypassStatus(result, fixture = this._stratonProbeFixture()) {
    const host = String(fixture?.host || "").trim();
    const apMode = host === "192.168.100.1" || fixture?.connectionMode === "ap";
    if (!result) {
      return {
        status: "unknown",
        title: "Bypass untested",
        detail: "OpenReef has not yet checked whether it can reach this Straton before ATI app setup.",
        next: "Run Scan safe paths before asking the tester to use ATI's app.",
      };
    }
    if (result.warning === "Safe path scan in progress.") {
      return {
        status: "unknown",
        title: "Bypass scan running",
        detail: "OpenReef is checking safe read-only paths from the controller.",
        next: "Wait for the scan result before changing ATI app settings.",
      };
    }
    const outcome = this._stratonScanOutcome(result, fixture);
    if (outcome.status === "ok") {
      return {
        status: "ok",
        title: "Read-only bypass proven",
        detail: "OpenReef reached the fixture and found JSON without using schedule writes.",
        next: "Send the support note so this read path can be mapped; keep hardware writes locked.",
      };
    }
    if (result.reachableCount > 0) {
      return {
        status: "unknown",
        title: "Reachability bypass only",
        detail: "OpenReef can talk to the fixture, but it has not found a useful current-state JSON path yet.",
        next: "Use ATI exports or browser network notes only to discover the exact read path, then retry Controller GET.",
      };
    }
    return {
      status: "warning",
      title: "Bypass not proven",
      detail: apMode
        ? "The AP fallback address did not answer from the controller's current network path."
        : "The configured fixture host did not answer from the controller.",
      next: apMode
        ? "Put the controller/network where it can reach the Straton AP, or try the fixture's LAN IP if it is already joined to Wi-Fi."
        : "Try AP fallback, confirm the LAN IP from the router, or collect the tester's current ATI setup state.",
    };
  }

  _stratonSetupBypassClaim(result, fixture = this._stratonProbeFixture()) {
    const setupState = fixture?.setupState || "unknown";
    const connectionMode = fixture?.connectionMode || (String(fixture?.host || "").trim() === "192.168.100.1" ? "ap" : "unknown");
    const bypass = this._stratonSetupBypassStatus(result, fixture);
    const preSetup = ["brand_new", "stuck_setup"].includes(setupState);
    const alreadySetup = setupState === "already_on_lan" || connectionMode === "lan";
    if (!result) {
      return {
        status: "unknown",
        title: "Setup bypass claim untested",
        detail: "No safe scan has been run, so OpenReef cannot claim it avoids ATI setup yet.",
        next: "Set connection path/setup state, then run Scan safe paths.",
      };
    }
    if (bypass.status === "ok" && preSetup && connectionMode === "ap") {
      return {
        status: "ok",
        title: "Pre-setup bypass candidate",
        detail: "The tester marked the fixture as brand new/reset or stuck in setup, used AP fallback, and OpenReef found JSON from that route.",
        next: "Treat this as the strongest setup-bypass evidence, but keep writes locked until readback/save/apply endpoints are verified.",
      };
    }
    if (bypass.status === "ok" && alreadySetup) {
      return {
        status: "unknown",
        title: "LAN confidence only",
        detail: "OpenReef read a fixture that appears to have already reached the LAN, so this does not prove ATI setup was bypassed.",
        next: "Use this for read-adapter mapping, but test AP fallback on a brand-new/reset or stuck fixture before claiming setup replacement.",
      };
    }
    if (bypass.status === "ok") {
      return {
        status: "unknown",
        title: "Read proof, setup state unknown",
        detail: "OpenReef found JSON, but the fixture setup state is not known.",
        next: "Ask the tester whether the light was already on LAN, brand new/reset, or stuck in setup.",
      };
    }
    if (bypass.status === "unknown" && preSetup && connectionMode === "ap") {
      return {
        status: "unknown",
        title: "Pre-setup reachability candidate",
        detail: "OpenReef may be reaching a pre-setup fixture over AP fallback, but it has not found usable JSON yet.",
        next: "Collect read paths from ATI exports/network notes, then retry Controller GET.",
      };
    }
    if (bypass.status === "warning") {
      return {
        status: "warning",
        title: "Setup bypass not proven",
        detail: "OpenReef could not reach/read the fixture in this setup state.",
        next: bypass.next,
      };
    }
    return {
      status: "unknown",
      title: "Setup bypass evidence incomplete",
      detail: "Connection or setup state is still unclear.",
      next: "Set Connection path and Setup state, then rerun Scan safe paths.",
    };
  }

  _stratonSetupBypassBanner(result, fixture = this._stratonProbeFixture()) {
    const bypass = this._stratonSetupBypassStatus(result, fixture);
    const claim = this._stratonSetupBypassClaim(result, fixture);
    const route = this._stratonApRouteStatus(result, fixture);
    return `
      <div class="notice ${bypass.status === "ok" ? "success" : "warning-notice"}">
        <strong>${this._escape(bypass.title)}.</strong> ${this._escape(bypass.detail)}
      </div>
      <div class="setup-next-list">
        <div><span class="pill ${this._escape(bypass.status)}">test</span><p>${this._escape(bypass.next)}</p></div>
        <div><span class="pill ${this._escape(claim.status)}">claim</span><p><strong>${this._escape(claim.title)}.</strong> ${this._escape(claim.detail)} ${this._escape(claim.next)}</p></div>
        <div><span class="pill ${this._escape(route.status)}">route</span><p><strong>${this._escape(route.title)}.</strong> ${this._escape(route.detail)} ${this._escape(route.next)}</p></div>
        <div><span class="pill disabled">write locked</span><p>OpenReef will not push schedules, Wi-Fi credentials, firmware, or save/apply commands during this evidence pass.</p></div>
      </div>
    `;
  }

  _stratonProbeScanResult(result) {
    if (!result) return "";
    const outcome = this._stratonScanOutcome(result);
    return `
      <div class="summary-grid">
        <article class="summary-card ${result.reachableCount ? "ok" : "warning"}"><span>Reachable paths</span><strong>${this._escape(result.reachableCount || 0)}</strong><small>${this._escape(result.checkedAt)}</small></article>
        <article class="summary-card ${result.jsonCount ? "ok" : "unknown"}"><span>JSON paths</span><strong>${this._escape(result.jsonCount || 0)}</strong><small>${this._escape(result.bestPath || "none selected")}</small></article>
        <article class="summary-card ${this._escape(outcome.status)}"><span>Outcome</span><strong>${this._escape(outcome.title)}</strong><small>${this._escape(outcome.next)}</small></article>
      </div>
      <div class="notice ${outcome.status === "ok" ? "success" : "warning-notice"}"><strong>${this._escape(outcome.title)}.</strong> ${this._escape(outcome.detail)}</div>
      ${result.warning ? `<p class="hint">${this._escape(result.warning)}</p>` : ""}
      <div class="status-list">
        ${(result.rows || []).map((row) => `
          <div class="row">
            <div>
              <strong>${this._escape(row.label || row.path)}</strong>
              <span>${this._escape(row.path || "unknown path")} · ${this._escape(row.contentType || "unknown")}</span>
              <small>${this._escape(row.warning || `${row.bytes || 0} bytes via ${row.source || "unknown"}`)}</small>
            </div>
            <div class="pill-stack inline">
              <span class="pill ${this._escape(row.statusClass || "unknown")}">${this._escape(row.status || "not run")}</span>
              <span class="pill ${row.mode === "json" ? "ok" : "unknown"}">${this._escape(row.mode || "unknown")}</span>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  _stratonEndpointCatalog() {
    const endpoints = this._stratonEndpoints();
    const rows = [
      ["reachability", "Reachability", "First proof the controller can talk to the fixture."],
      ["currentState", "Current state", "Candidate JSON path for fixture state/program comparison."],
      ["program", "Program", "Future verified current program read path."],
      ["firmware", "Firmware", "Future verified model/firmware read path."],
      ["groups", "Groups", "Future verified group membership read path."],
    ];
    return `
      <section class="mapping-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Read catalog</p>
            <h3>Candidate endpoint paths</h3>
            <p class="muted">Read-only paths discovered by setup rescue. These are candidates until confirmed on real Straton hardware.</p>
          </div>
          <span class="pill disabled">writes locked</span>
        </div>
        <div class="status-list">
          ${rows.map(([key, label, detail]) => {
            const value = endpoints[key] || "";
            return `
              <div class="row">
                <div>
                  <strong>${this._escape(label)}</strong>
                  <span>${this._escape(value || "not mapped")}</span>
                  <small>${this._escape(detail)}</small>
                </div>
                <span class="pill ${value ? "ok" : "unknown"}">${value ? "candidate" : "needed"}</span>
              </div>
            `;
          }).join("")}
        </div>
        <p class="hint">${this._escape(endpoints.lastScanAt ? `Last scan: ${endpoints.lastScanAt} - ${endpoints.lastOutcome || "candidate updated"}` : "No endpoint candidate has been promoted yet.")}</p>
      </section>
    `;
  }

  _stratonAdapterGateRows() {
    const draft = this._stratonEvidenceDraft();
    const endpoints = this._stratonEndpoints();
    const fixture = this._stratonProbeFixture();
    const returnedTesterNote = draft.testerNoteResult;
    const testerNote = returnedTesterNote && !returnedTesterNote.example ? returnedTesterNote : null;
    const bypass = testerNote
      ? {
        status: testerNote.status,
        title: testerNote.title,
        detail: testerNote.detail,
        next: testerNote.next,
      }
      : this._stratonSetupBypassStatus(draft.probeScanResult, fixture);
    const setupProof = testerNote?.setupEvidenceTitle
      ? {
        status: testerNote.setupEvidenceStatus || "unknown",
        title: testerNote.setupEvidenceTitle,
        detail: testerNote.setupEvidenceDetail || "Returned support note was assessed for setup-bypass evidence.",
        next: testerNote.setupEvidenceNext || "",
      }
      : this._stratonSetupBypassClaim(draft.probeScanResult, fixture);
    const route = testerNote?.apRouteTitle
      ? {
        status: testerNote.apRouteStatus || "unknown",
        title: testerNote.apRouteTitle,
        detail: testerNote.apRouteDetail || testerNote.apRouteNext || "Returned support note included AP route readiness.",
        next: testerNote.apRouteNext || "",
      }
      : this._stratonApRouteStatus(draft.probeScanResult, fixture);
    const apRouteReady = route.status === "ok" && /^AP\b/i.test(route.title || "");
    const apRouteStatus = apRouteReady ? "ok" : route.status === "warning" ? "warning" : "unknown";
    const writeHints = (draft.result?.endpoints || []).filter((row) => !["GET", "HEAD", "OPTIONS"].includes(row.method));
    const firmwareGroupCount = [endpoints.firmware, endpoints.groups].filter(Boolean).length;
    return [
      {
        label: "Setup-bypass proof",
        status: setupProof.status === "ok" ? "ok" : setupProof.status === "warning" ? "warning" : "unknown",
        state: setupProof.title,
        detail: `${setupProof.detail} ${setupProof.next || ""}`.trim(),
      },
      {
        label: "Fixture read proof",
        status: bypass.status === "ok" ? "ok" : bypass.status === "unknown" ? "unknown" : "warning",
        state: bypass.title,
        detail: `${bypass.detail} ${bypass.next} ${bypass.status === "ok" ? "This supports adapter mapping, but setup replacement is judged separately." : ""}`.trim(),
      },
      {
        label: "AP route proof",
        status: apRouteStatus,
        state: route.title,
        detail: apRouteReady
          ? `${route.detail} ${route.next}`.trim()
          : `${route.detail} ${route.next || "A LAN route or staged AP host is not enough to prove first-time setup replacement."}`.trim(),
      },
      {
        label: "Current-state read",
        status: endpoints.currentState ? "ok" : "warning",
        state: endpoints.currentState ? `candidate ${endpoints.currentState}` : "needed",
        detail: endpoints.currentState
          ? "A read path candidate exists for comparing the fixture state with the OpenReef plan."
          : "Needed before any write work: OpenReef must read the fixture before it can safely change it.",
      },
      {
        label: "Program readback",
        status: endpoints.program ? "unknown" : "warning",
        state: endpoints.program ? `candidate ${endpoints.program}` : "needed",
        detail: "Required before writes so OpenReef can prove the active program before and after any save/apply call.",
      },
      {
        label: "Firmware and groups",
        status: firmwareGroupCount === 2 ? "unknown" : "warning",
        state: firmwareGroupCount === 2 ? "candidates captured" : `${firmwareGroupCount}/2 mapped`,
        detail: "Firmware/model and group membership reads are needed for multi-light confidence and generation-specific adapter behavior.",
      },
      {
        label: "Save/apply endpoint",
        status: "warning",
        state: writeHints.length ? `${writeHints.length} hint(s), locked` : "needed",
        detail: writeHints.length
          ? "Network notes include possible write endpoint hints, but real save/apply remains locked until readback is verified on hardware."
          : "Still missing verified ATI save/apply endpoint evidence. OpenReef will not guess this contract.",
      },
      {
        label: "Rollback package",
        status: "ok",
        state: "available",
        detail: "OpenReef can copy the local program package and redacted support note before any future adapter work.",
      },
    ];
  }

  _stratonProofSummaryRows(rows = this._stratonAdapterGateRows()) {
    const byLabel = Object.fromEntries((rows || []).map((row) => [row.label, row]));
    const setup = byLabel["Setup-bypass proof"] || {};
    const read = byLabel["Fixture read proof"] || {};
    const save = byLabel["Save/apply endpoint"] || {};
    return [
      {
        label: "Setup bypass",
        status: setup.status || "unknown",
        state: setup.status === "ok" ? "supported" : setup.status === "warning" ? "not proven" : "candidate only",
        detail: setup.status === "ok"
          ? `Evidence supports setup bypass: ${setup.state || "ready"}.`
          : setup.status === "warning"
            ? `Does not prove setup bypass: ${setup.state || "blocked"}.`
            : `Setup bypass still needs stronger proof: ${setup.state || "candidate"}.`,
      },
      {
        label: "Fixture read",
        status: read.status || "unknown",
        state: read.status === "ok" ? "read evidence found" : read.status === "warning" ? "not readable yet" : "reachable/candidate",
        detail: read.status === "ok"
          ? `Useful adapter read evidence exists: ${read.state || "read found"}.`
          : read.status === "warning"
            ? `OpenReef still needs a fixture read path: ${read.state || "needed"}.`
            : `Read evidence is still incomplete: ${read.state || "candidate"}.`,
      },
      {
        label: "Hardware writes",
        status: "warning",
        state: "locked",
        detail: save.state && save.state !== "needed"
          ? `Write hints exist (${save.state}), but save/apply remains locked until real readback verifies them.`
          : "No verified ATI save/apply flow yet; OpenReef must not write schedules to the light.",
      },
    ];
  }

  _stratonPainPointCoverageRows() {
    const straton = this._stratonConfig();
    const draft = this._stratonEvidenceDraft();
    const endpoints = this._stratonEndpoints();
    const fixtures = this._stratonFixtures();
    const selected = fixtures.filter((fixture) => fixture.selected);
    const probe = draft.probeResult;
    const scan = draft.probeScanResult;
    const returnedTesterNote = draft.testerNoteResult;
    const testerNote = returnedTesterNote && !returnedTesterNote.example ? returnedTesterNote : null;
    const fixture = this._stratonProbeFixture();
    const fixtureState = draft.fixtureStateResult;
    const [bridgeClass, bridgeTitle, bridgeDetail] = this._stratonLiveBridgeSummary();
    const remoteSetupClaim = testerNote?.setupEvidenceTitle
      ? {
        status: testerNote.setupEvidenceStatus || testerNote.status || "unknown",
        title: testerNote.setupEvidenceTitle,
        detail: testerNote.setupEvidenceDetail || testerNote.detail || "Returned support note was assessed for setup-bypass evidence.",
        next: testerNote.setupEvidenceNext || testerNote.next || "",
      }
      : testerNote?.setupClaimTitle
      ? {
        status: testerNote.setupClaimStatus || testerNote.status || "unknown",
        title: testerNote.setupClaimTitle,
        detail: testerNote.setupClaimDetail || testerNote.detail || "Returned support note included a setup-replacement claim.",
        next: testerNote.next || "",
      }
      : null;
    const setupClaim = remoteSetupClaim || this._stratonSetupBypassClaim(scan, fixture);
    const route = testerNote?.apRouteTitle
      ? {
        status: testerNote.apRouteStatus || "unknown",
        title: testerNote.apRouteTitle,
        detail: testerNote.apRouteDetail || testerNote.apRouteNext || "Returned support note included AP route readiness.",
        next: testerNote.apRouteNext || "",
      }
      : this._stratonApRouteStatus(scan, fixture);
    const reachable = Boolean(
      endpoints.reachability ||
      (scan && Number(scan.reachableCount) > 0) ||
      (probe && ["ok", "unknown"].includes(probe.statusClass) && probe.status !== "not run")
    );
    const currentStateReady = Boolean(
      endpoints.currentState ||
      (scan && Number(scan.jsonCount) > 0) ||
      probe?.mode === "json" ||
      fixtureState?.mode === "json"
    );
    const groupNames = new Set(selected.map((item) => String(item.group || "").trim()).filter(Boolean));
    const grouped = fixtures.length > 1
      ? selected.length > 1 && groupNames.size > 0
      : fixtures.length === 1;
    const saveGate = this._stratonAdapterGateRows().find((row) => row.label === "Save/apply endpoint");
    return [
      {
        label: "ATI setup bypass",
        status: setupClaim.status === "ok" ? "ok" : setupClaim.status === "warning" ? "warning" : "unknown",
        state: setupClaim.title,
        detail: `${setupClaim.detail} ${setupClaim.next || ""} AP route: ${route.title} - ${route.detail}`.trim(),
      },
      {
        label: "Discovery and reachability",
        status: reachable ? "ok" : fixtures.length ? "unknown" : "warning",
        state: reachable ? endpoints.reachability || scan?.bestPath || probe?.path || "reachable" : fixtures.length ? "fixture staged" : "fixture needed",
        detail: reachable
          ? "OpenReef has controller-side reachability evidence for this target."
          : fixtures.length
            ? "Run Test root or Scan safe paths before asking the tester to use ATI setup."
            : "Add a fixture, LAN host/IP, or AP fallback target first.",
      },
      {
        label: "Current fixture read",
        status: currentStateReady ? "ok" : "warning",
        state: endpoints.currentState ? `candidate ${endpoints.currentState}` : currentStateReady ? "JSON sample found" : "needed",
        detail: currentStateReady
          ? "OpenReef has a candidate read/sample path for planned-vs-observed comparison."
          : "A useful read path is needed before OpenReef can safely replace ATI setup or writes.",
      },
      {
        label: "Schedule editing",
        status: "ok",
        state: "local planner ready",
        detail: "Templates, quick modes, day preview, acclimation, clouds, and moonlight can be edited without touching hardware.",
      },
      {
        label: "Multi-light grouping",
        status: grouped ? "ok" : fixtures.length ? "unknown" : "warning",
        state: fixtures.length > 1 ? `${selected.length}/${fixtures.length} target(s), ${groupNames.size} group(s)` : fixtures.length ? "single fixture" : "needed",
        detail: fixtures.length > 1
          ? "Fixture cards and the sync matrix show target and group coverage before future adapter writes."
          : fixtures.length
            ? "Single-fixture setup is staged; multi-light confidence appears when more fixtures are added."
            : "Add fixtures before testing group confidence.",
      },
      {
        label: "Save confidence",
        status: straton.lastReceipt ? "ok" : "unknown",
        state: straton.lastReceipt ? "local receipt recorded" : "local receipt pending",
        detail: straton.lastReceipt
          ? "OpenReef can prove what it saved locally, but this is not ATI hardware acknowledgement."
          : "Use Save local plan to create an OpenReef receipt after reviewing the plan.",
      },
      {
        label: "Controller visibility",
        status: bridgeClass === "ok" ? "ok" : bridgeClass === "warning" ? "warning" : "unknown",
        state: bridgeTitle,
        detail: bridgeDetail,
      },
      {
        label: "Backup and support handoff",
        status: "ok",
        state: "copy flows ready",
        detail: "Program packages, tester steps, evidence requests, and redacted support notes are available.",
      },
      {
        label: "Hardware save/apply",
        status: "warning",
        state: saveGate?.state || "needed",
        detail: saveGate?.detail || "OpenReef keeps Straton hardware writes locked until save/apply is verified on real hardware.",
      },
    ];
  }

  _stratonPainPointCoveragePanel() {
    const rows = this._stratonPainPointCoverageRows();
    const fixed = rows.filter((row) => row.status === "ok").length;
    const candidate = rows.filter((row) => row.status === "unknown").length;
    const blocked = rows.filter((row) => row.status === "warning").length;
    return `
      <article class="panel straton-painpoint-coverage">
        <div class="section-head">
          <div>
            <p class="eyebrow">Coverage</p>
            <h3>Pain-point status</h3>
            <p class="muted">Research complaints mapped to the current OpenReef Straton state.</p>
          </div>
          <div class="pill-stack">
            <span class="pill ok">${this._escape(fixed)} fixed</span>
            <span class="pill unknown">${this._escape(candidate)} candidate</span>
            <span class="pill warning">${this._escape(blocked)} blocked</span>
          </div>
        </div>
        <div class="status-list">
          ${rows.map((row) => `
            <div class="row">
              <div>
                <strong>${this._escape(row.label)}</strong>
                <span>${this._escape(row.state)}</span>
                <small>${this._escape(row.detail)}</small>
              </div>
              <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "ok" ? "fixed" : row.status === "unknown" ? "candidate" : "blocked")}</span>
            </div>
          `).join("")}
        </div>
      </article>
    `;
  }

  _stratonBetaEvidenceRows() {
    const draft = this._stratonEvidenceDraft();
    const straton = this._stratonConfig();
    const adapterLabel = this._stratonAdapterLabel(straton.adapter);
    const selectedReefPilot = straton.adapter === "reefpilot_bluetooth";
    const selectedReefTech = straton.adapter === "reeftech_wifi";
    const fixture = this._stratonProbeFixture();
    const endpoints = this._stratonEndpoints();
    const scan = draft.probeScanResult;
    const probe = draft.probeResult;
    const fixtureState = draft.fixtureStateResult;
    const returnedTesterNote = draft.testerNoteResult;
    const testerNote = returnedTesterNote && !returnedTesterNote.example ? returnedTesterNote : null;
    const testerReefPilot = Boolean(testerNote?.reefPilotEvidence || testerNote?.title === "Reef Pilot Bluetooth evidence");
    const reefPilot = selectedReefPilot || testerReefPilot;
    const reefTech = selectedReefTech && !testerReefPilot;
    const adapterState = testerReefPilot && !selectedReefPilot ? "Returned note: Reef Pilot Bluetooth" : adapterLabel;
    const route = testerNote?.apRouteTitle
      ? {
        status: testerNote.apRouteStatus || "unknown",
        title: testerNote.apRouteTitle,
        detail: testerNote.apRouteDetail || testerNote.apRouteNext || "Returned support note included AP route readiness.",
      }
      : this._stratonApRouteStatus(scan, fixture);
    const setupProof = testerNote?.setupEvidenceTitle
      ? {
        status: testerNote.setupEvidenceStatus || "unknown",
        title: testerNote.setupEvidenceTitle,
        detail: testerNote.setupEvidenceDetail || testerNote.setupEvidenceNext || "Returned support note was assessed for setup-bypass evidence.",
      }
      : this._stratonSetupBypassClaim(scan, fixture);
    const hasRealTesterNote = Boolean(testerNote);
    const hasJsonRead = Boolean(
      endpoints.currentState ||
      (scan && Number(scan.jsonCount) > 0) ||
      (probe && probe.mode === "json") ||
      (fixtureState && fixtureState.mode === "json") ||
      (hasRealTesterNote && Number(testerNote.jsonCount) > 0)
    );
    const schemaId = testerNote?.schemaFingerprint || fixtureState?.schemaFingerprint?.id || "";
    const setupState = fixture?.setupState || "unknown";
    const setupStateLabel = this._stratonSetupStateLabel(setupState);
    const firstSetupState = ["brand_new", "stuck_setup"].includes(setupState);
    const apTarget = fixture?.connectionMode === "ap" || fixture?.host === "192.168.100.1";
    const routeOk = route.status === "ok" && /^AP\b/i.test(route.title || "");
    return [
      {
        label: "Fixture target",
        status: fixture ? "ok" : "warning",
        state: fixture ? `${fixture.name || "Straton"} at ${this._stratonRedactSnippet(fixture.host || "no host")}` : "needed",
        detail: fixture
          ? `Connection path is ${this._stratonConnectionModeLabel(fixture.connectionMode)}; setup state is ${setupStateLabel}.`
          : "Add or select a Straton fixture before asking the tester to run AP/LAN evidence.",
      },
      {
        label: "Adapter generation",
        status: reefTech ? "ok" : reefPilot ? "unknown" : "warning",
        state: adapterState,
        detail: testerReefPilot
          ? "Returned tester note identifies Straton X / Reef Pilot Bluetooth. AP route evidence should not be interpreted as ReefTECH Wi-Fi proof."
          : reefTech
          ? "ReefTECH Wi-Fi fixtures use the LAN/AP safe-read evidence path below."
          : reefPilot
            ? "Straton X / Reef Pilot uses a separate Bluetooth path. AP route evidence does not prove this adapter."
            : "This adapter path is for read-only bridge/manual backup use, not direct ATI setup replacement.",
      },
      {
        label: "First-setup route",
        status: reefPilot ? "unknown" : apTarget && firstSetupState ? "ok" : apTarget ? "unknown" : "warning",
        state: reefPilot ? "Bluetooth setup path" : apTarget ? "AP fallback staged" : "LAN or unknown route",
        detail: reefPilot
          ? "For Reef Pilot Bluetooth, collect real pairing/control evidence from Straton X instead of treating AP fallback as setup proof."
          : apTarget && firstSetupState
            ? "Fixture is staged for the real ATI setup-bypass test: AP fallback plus brand-new/reset or stuck setup state."
            : apTarget
              ? "AP fallback is staged, but setup state still needs brand-new/reset or stuck setup proof before claiming ATI onboarding replacement."
              : "A LAN read can map endpoints, but it does not prove first-time ATI setup replacement.",
      },
      {
        label: "Controller/AP route",
        status: reefPilot ? "unknown" : routeOk ? "ok" : route.status === "warning" ? "warning" : "unknown",
        state: reefPilot ? "not Bluetooth proof" : route.title,
        detail: reefPilot
          ? "AP route checks are still useful for ReefTECH Wi-Fi fixtures, but Straton X/Reef Pilot needs separate Bluetooth evidence."
          : route.detail,
      },
      {
        label: "Returned tester note",
        status: hasRealTesterNote ? testerNote.status === "warning" ? "warning" : "unknown" : returnedTesterNote?.example ? "unknown" : "warning",
        state: hasRealTesterNote ? testerNote.title : returnedTesterNote?.example ? "example only" : "needed",
        detail: hasRealTesterNote
          ? `${testerNote.detail} ${testerNote.next || ""}`.trim()
          : returnedTesterNote?.example
            ? "Synthetic examples rehearse the parser but do not prove hardware access or promote endpoints."
            : "Paste the tester's copied support note after they run Scan safe paths.",
      },
      {
        label: "Setup-bypass evidence",
        status: reefPilot ? "unknown" : setupProof.status === "ok" ? "ok" : setupProof.status === "warning" ? "warning" : "unknown",
        state: reefPilot ? "Bluetooth proof needed" : setupProof.title,
        detail: reefPilot
          ? "Need real Reef Pilot Bluetooth evidence for pairing, template/group control, Live PAR/Energy, and schedule behavior."
          : setupProof.detail,
      },
      {
        label: "Readback candidate",
        status: hasJsonRead ? "unknown" : "warning",
        state: endpoints.currentState ? `candidate ${endpoints.currentState}` : hasJsonRead ? "JSON found" : "needed",
        detail: reefPilot
          ? "For Reef Pilot Bluetooth, readback evidence should include Live PAR/Energy or current schedule/control state from real Straton X hardware."
          : hasJsonRead
            ? "Useful read evidence exists, but hardware writes still need program readback and save/apply proof."
            : "OpenReef still needs a safe current-state JSON/read path from real fixture evidence.",
      },
      {
        label: "Schema fingerprint",
        status: schemaId ? "unknown" : "warning",
        state: schemaId || "missing",
        detail: schemaId
          ? "A redacted schema fingerprint exists for comparing repeated tester reads without sharing raw settings."
          : "Capture a redacted schema fingerprint from a current fixture sample or returned tester note.",
      },
      {
        label: "Write safety",
        status: "warning",
        state: "locked",
        detail: "Save/apply remains locked until verified current-state readback, program readback, firmware/group context, save/apply endpoint evidence, and rollback proof all exist.",
      },
    ];
  }

  _stratonBetaEvidencePanel() {
    const rows = this._stratonBetaEvidenceRows();
    const ready = rows.filter((row) => row.status === "ok").length;
    const candidate = rows.filter((row) => row.status === "unknown").length;
    const blocked = rows.filter((row) => row.status === "warning").length;
    return `
      <article class="panel straton-beta-evidence">
        <div class="section-head">
          <div>
            <p class="eyebrow">Beta proof</p>
            <h3>Hardware evidence checklist</h3>
            <p class="muted">The simple tester-facing view of what is proven, candidate, or still blocked.</p>
          </div>
          <div class="pill-stack">
            <span class="pill ok">${this._escape(ready)} ready</span>
            <span class="pill unknown">${this._escape(candidate)} candidate</span>
            <span class="pill warning">${this._escape(blocked)} blocked</span>
          </div>
        </div>
        <div class="status-list">
          ${rows.map((row) => `
            <div class="row">
              <div>
                <strong>${this._escape(row.label)}</strong>
                <span>${this._escape(row.state)}</span>
                <small>${this._escape(row.detail)}</small>
              </div>
              <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "ok" ? "ready" : row.status === "unknown" ? "candidate" : "blocked")}</span>
            </div>
          `).join("")}
        </div>
      </article>
    `;
  }

  _stratonAdapterGatePanel() {
    const rows = this._stratonAdapterGateRows();
    const proofRows = this._stratonProofSummaryRows(rows);
    const candidateRows = rows.filter((row) => row.status === "ok" || row.status === "unknown").length;
    const blockingRows = rows.filter((row) => row.status === "warning").length;
    return `
      <article class="panel straton-adapter-gate">
        <div class="section-head">
          <div>
            <p class="eyebrow">Adapter gate</p>
            <h3>Hardware write unlock checklist</h3>
            <p class="muted">OpenReef must pass these evidence checks before replacing ATI save/apply flows.</p>
          </div>
          <div class="pill-stack">
            <span class="pill disabled">writes locked</span>
            <span class="pill ${candidateRows ? "unknown" : "warning"}">${this._escape(candidateRows)}/${this._escape(rows.length)} evidence items</span>
            <span class="pill warning">${this._escape(blockingRows)} blocker(s)</span>
            <button class="secondary compact-button" data-action="copy-straton-adapter-request">Copy evidence request</button>
          </div>
        </div>
        <div class="notice warning-notice"><strong>Do not unlock writes yet.</strong> Candidate read paths are useful evidence, but a safe adapter still needs verified program readback and save/apply confirmation on real Straton hardware.</div>
        <div class="setup-next-list">
          ${proofRows.map((row) => `
            <div><span class="pill ${this._escape(row.status)}">${this._escape(row.label)}</span><p><strong>${this._escape(row.state)}.</strong> ${this._escape(row.detail)}</p></div>
          `).join("")}
        </div>
        <div class="status-list">
          ${rows.map((row) => `
            <div class="row">
              <div>
                <strong>${this._escape(row.label)}</strong>
                <span>${this._escape(row.state)}</span>
                <small>${this._escape(row.detail)}</small>
              </div>
              <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "ok" ? "ready" : row.status === "unknown" ? "candidate" : "blocked")}</span>
            </div>
          `).join("")}
        </div>
      </article>
    `;
  }

  _stratonProbeResult(result) {
    if (!result) {
      return `
        <div class="setup-next-list">
          <div><span class="pill unknown">optional</span><p>Use this only after you have a likely read-only path from ATI exports or browser network notes.</p></div>
          <div><span class="pill warning">GET only</span><p>The probe asks OpenReef's Home Assistant backend to read the selected fixture path. It does not write, save, or call light services.</p></div>
        </div>
      `;
    }
    return `
      <div class="summary-grid">
        <article class="summary-card ${this._escape(result.statusClass || "unknown")}"><span>GET status</span><strong>${this._escape(result.status)}</strong><small>${this._escape(result.checkedAt)}</small></article>
        <article class="summary-card ${result.mode === "json" ? "ok" : "warning"}"><span>Response</span><strong>${this._escape(result.mode)}</strong><small>${this._escape(result.bytes || 0)} bytes</small></article>
        <article class="summary-card unknown"><span>Source</span><strong>${this._escape(result.source || "unknown")}</strong><small>${this._escape(result.host || "redacted")}</small></article>
      </div>
      <div class="setup-next-list">
        <div><span class="pill ${this._escape(result.statusClass || "unknown")}">${this._escape(result.method || "GET")}</span><p>${this._escape(result.path || "unknown path")}</p></div>
        <div><span class="pill ${result.warning ? "warning" : "ok"}">${result.warning ? "review" : "usable"}</span><p>${this._escape(result.warning || "Response copied into the fixture sample box for planned-vs-observed comparison.")}</p></div>
        <div><span class="pill unknown">private</span><p>Raw probe text is transient. Copied notes include status and redacted path only.</p></div>
      </div>
    `;
  }

  _stratonFixtureStateResult(result) {
    if (!result) {
      return `
        <div class="setup-next-list">
          <div><span class="pill unknown">read only</span><p>Paste a current fixture JSON export or GET response to compare obvious fields against the OpenReef plan.</p></div>
          <div><span class="pill warning">no write</span><p>This does not call a fixture or apply settings. It only analyzes the pasted sample in this browser session.</p></div>
        </div>
      `;
    }
    const close = result.observations?.filter((item) => item.status === "ok").length || 0;
    return `
      <div class="summary-grid">
        <article class="summary-card ${result.mode === "json" ? "ok" : "warning"}"><span>Sample</span><strong>${this._escape(result.mode)}</strong><small>${this._escape(result.checkedAt)}</small></article>
        <article class="summary-card ${result.leafCount ? "ok" : "unknown"}"><span>Leaf values</span><strong>${this._escape(result.leafCount)}</strong><small>candidate fields scanned</small></article>
        <article class="summary-card ${close ? "ok" : "warning"}"><span>Close matches</span><strong>${this._escape(close)} / ${this._escape(result.observations?.length || 0)}</strong><small>planned vs observed</small></article>
        <article class="summary-card unknown"><span>Schema</span><strong>${this._escape(result.schemaFingerprint?.id || "none")}</strong><small>redacted fingerprint</small></article>
      </div>
      ${result.warning ? `<p class="hint">${this._escape(result.warning)}</p>` : ""}
      <div class="status-list">
        ${(result.observations || []).map((item) => `
          <div class="row">
            <div>
              <strong>${this._escape(item.label)}</strong>
              <span>Planned ${this._escape(item.planned)} · observed ${this._escape(item.observed)}</span>
              <small>${this._escape(item.detail)}</small>
            </div>
            <span class="pill ${this._escape(item.status)}">${this._escape(item.status)}</span>
          </div>
        `).join("")}
      </div>
      <div class="setup-next-list">
        ${(result.promotedEndpoints || []).length ? result.promotedEndpoints.map((item) => `
          <div><span class="pill ok">${this._escape(item.label)}</span><p>${this._escape(`${item.path} - ${item.state}`)}</p></div>
        `).join("") : ""}
        ${(result.rows || []).length ? result.rows.map((row) => `
          <div><span class="pill ${row.focus === "other" ? "unknown" : "ok"}">${this._escape(row.focus)}</span><p>${this._escape(row.path)} = ${this._escape(row.value)}</p></div>
        `).join("") : `<div><span class="pill warning">needed</span><p>No obvious schedule, spectrum, grouping, firmware, or model fields found in this sample.</p></div>`}
      </div>
    `;
  }

  _stratonTesterNoteResult(result) {
    if (!result) {
      return `
        <div class="setup-next-list">
          <div><span class="pill unknown">paste</span><p>Paste the tester's copied Straton support note here after they run Scan safe paths.</p></div>
          <div><span class="pill warning">candidate</span><p>The intake can promote safe read paths into the candidate endpoint catalog, but it does not unlock hardware writes.</p></div>
        </div>
      `;
    }
    const endpointRows = Object.entries(result.endpoints || {})
      .filter(([, value]) => value)
      .map(([key, value]) => [key.replace(/[A-Z]/g, (letter) => ` ${letter.toLowerCase()}`), value]);
    const returnReviewRows = this._stratonReturnReviewRows(result);
    const reefPilotRows = result.reefPilotEvidence ? [
      {
        label: "Hardware generation",
        status: "unknown",
        state: result.hardwareGeneration || "Straton X / Reef Pilot Bluetooth",
        detail: "Returned note identified the newer Bluetooth control path; do not treat AP route as proof for this adapter.",
      },
      {
        label: "Bluetooth evidence",
        status: result.bluetoothControl ? "unknown" : "warning",
        state: result.bluetoothControl || "needed",
        detail: result.bluetoothControl || "Ask for pairing and direct control observations from the Reef Pilot app.",
      },
      {
        label: "Live PAR/Energy",
        status: result.liveParEnergy ? "unknown" : "warning",
        state: result.liveParEnergy || "needed",
        detail: result.liveParEnergy || "Ask whether Reef Pilot shows Live PAR and Live Energy for the tested Straton X.",
      },
      {
        label: "Templates/groups",
        status: result.templatesGroups ? "unknown" : "warning",
        state: result.templatesGroups || "needed",
        detail: result.templatesGroups || "Ask whether template loading and grouped fixture control were observed.",
      },
      {
        label: "Schedule save",
        status: result.scheduleSave ? "unknown" : "warning",
        state: result.scheduleSave || "needed",
        detail: result.scheduleSave || "Ask whether saving a schedule was confirmed or only changed on screen.",
      },
    ] : [];
    return `
      <div class="summary-grid">
        <article class="summary-card ${this._escape(result.status || "unknown")}"><span>Bypass verdict</span><strong>${this._escape(result.title)}</strong><small>${this._escape(result.checkedAt)}</small></article>
        <article class="summary-card ${this._escape(result.setupEvidenceStatus || "unknown")}"><span>Setup evidence</span><strong>${this._escape(result.setupEvidenceTitle || "not assessed")}</strong><small>${this._escape(result.setupEvidenceNext || "review returned note")}</small></article>
        <article class="summary-card ${result.jsonCount ? "ok" : result.reachableCount ? "unknown" : "warning"}"><span>Reachable / JSON</span><strong>${this._escape(result.reachableCount || 0)} / ${this._escape(result.jsonCount || 0)}</strong><small>${this._escape(result.verdict || "no verdict line")}</small></article>
        <article class="summary-card ${result.promoted?.length ? "ok" : "unknown"}"><span>Catalog updates</span><strong>${this._escape(result.promoted?.length || 0)}</strong><small>${this._escape(result.promoted?.join(", ") || "none promoted")}</small></article>
        <article class="summary-card ${this._escape(result.schemaFingerprintStatus || "unknown")}"><span>Schema</span><strong>${this._escape(result.schemaFingerprint || "none")}</strong><small>${this._escape(result.schemaFingerprintTitle || "not compared")}</small></article>
      </div>
      <div class="notice ${result.status === "ok" ? "success" : "warning-notice"}"><strong>${this._escape(result.title)}.</strong> ${this._escape(result.detail)}</div>
      ${result.warning ? `<p class="hint">${this._escape(result.warning)}</p>` : ""}
      <div class="status-list">
        ${returnReviewRows.map((row) => `
          <div class="row">
            <div>
              <strong>${this._escape(row.label)}</strong>
              <span>${this._escape(row.state)}</span>
              <small>${this._escape(row.detail)}</small>
            </div>
            <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "ok" ? "ready" : row.status === "unknown" ? "candidate" : "blocked")}</span>
          </div>
        `).join("")}
        <div class="row">
          <div><strong>Next step</strong><span>${this._escape(result.next)}</span></div>
          <span class="pill ${this._escape(result.status || "unknown")}">${this._escape(result.status || "unknown")}</span>
        </div>
        <div class="row">
          <div>
            <strong>Setup evidence</strong>
            <span>${this._escape(result.setupEvidenceTitle || "Setup evidence incomplete")}</span>
            <small>${this._escape(result.setupEvidenceDetail || result.setupEvidenceNext || "Returned note does not include enough setup-bypass evidence yet.")}</small>
          </div>
          <span class="pill ${this._escape(result.setupEvidenceStatus || "unknown")}">${this._escape(result.setupEvidenceStatus || "unknown")}</span>
        </div>
        ${result.setupClaimTitle ? `
          <div class="row">
            <div>
              <strong>Setup claim</strong>
              <span>${this._escape(result.setupClaimTitle)}</span>
              <small>${this._escape(result.setupClaimDetail || "Returned support note included a setup-replacement claim.")}</small>
            </div>
            <span class="pill ${this._escape(result.setupClaimStatus || "unknown")}">${this._escape(result.setupClaimStatus || "unknown")}</span>
          </div>
        ` : ""}
        ${result.apRouteTitle ? `
          <div class="row">
            <div>
              <strong>AP route</strong>
              <span>${this._escape(result.apRouteTitle)}</span>
              <small>${this._escape(result.apRouteDetail || result.apRouteNext || "Returned support note included AP route readiness.")}</small>
            </div>
            <span class="pill ${this._escape(result.apRouteStatus || "unknown")}">${this._escape(result.apRouteStatus || "unknown")}</span>
          </div>
        ` : ""}
        ${reefPilotRows.map((row) => `
          <div class="row">
            <div>
              <strong>${this._escape(row.label)}</strong>
              <span>${this._escape(row.state)}</span>
              <small>${this._escape(row.detail)}</small>
            </div>
            <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "warning" ? "needed" : "candidate")}</span>
          </div>
        `).join("")}
        <div class="row">
          <div>
            <strong>Schema fingerprint</strong>
            <span>${this._escape(result.schemaFingerprintTitle || "Schema not compared")}</span>
            <small>${this._escape(result.schemaFingerprintDetail || "No returned schema fingerprint was found in the pasted note.")}</small>
          </div>
          <span class="pill ${this._escape(result.schemaFingerprintStatus || "unknown")}">${this._escape(result.schemaFingerprintStatus || "unknown")}</span>
        </div>
        ${endpointRows.length ? endpointRows.map(([key, value]) => `
          <div class="row">
            <div><strong>${this._escape(key)}</strong><span>${this._escape(value)}</span><small>Candidate path from returned support note.</small></div>
            <span class="pill ok">candidate</span>
          </div>
        `).join("") : `
          <div class="row">
            <div><strong>Endpoint candidates</strong><span>None found in the pasted note.</span><small>Ask for the full support note if the tester ran Scan safe paths.</small></div>
            <span class="pill warning">needed</span>
          </div>
        `}
      </div>
    `;
  }

  _stratonEvidenceCoverageRows(result = this._stratonEvidenceDraft().result) {
    const focusCounts = result?.focusCounts || {};
    const endpoints = result?.endpoints || [];
    const readHints = endpoints.filter((row) => ["GET", "HEAD"].includes(row.method));
    const writeHints = endpoints.filter((row) => ["POST", "PUT", "PATCH", "DELETE"].includes(row.method));
    const coverage = (label, key, detail) => {
      const count = Number(focusCounts[key]) || 0;
      return {
        label,
        status: count ? "ok" : "warning",
        state: count ? `${count} changed path(s)` : "needed",
        detail,
      };
    };
    return [
      coverage("Schedule mapping", "schedule", "Run one small ATI schedule-time change and compare before/after exports."),
      coverage("Spectrum mapping", "spectrum", "Run one small ATI channel/intensity change and compare before/after exports."),
      coverage("Grouping mapping", "grouping", "Run one grouping or fixture-target change on a multi-light setup where possible."),
      coverage("Firmware/model context", "firmware", "Capture model and firmware strings so adapter behavior can be generation-aware."),
      {
        label: "Read endpoint hints",
        status: readHints.length ? "ok" : "warning",
        state: readHints.length ? `${readHints.length} read hint(s)` : "needed",
        detail: "GET/HEAD method-path notes help map load/current-state reads before writes.",
      },
      {
        label: "Save/apply hints",
        status: writeHints.length ? "unknown" : "warning",
        state: writeHints.length ? `${writeHints.length} write hint(s), locked` : "needed",
        detail: "POST/PUT/PATCH/DELETE hints are evidence only. Save/apply stays locked until readback is verified on hardware.",
      },
    ];
  }

  _stratonEvidenceCoverage(result = this._stratonEvidenceDraft().result) {
    const rows = this._stratonEvidenceCoverageRows(result);
    const ready = rows.filter((row) => row.status === "ok" || row.status === "unknown").length;
    return `
      <section class="mapping-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Coverage</p>
            <h3>Adapter evidence coverage</h3>
            <p class="muted">Shows which ATI one-change tests are already represented in the pasted evidence.</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${ready ? "unknown" : "warning"}">${this._escape(ready)}/${this._escape(rows.length)} covered</span>
            <span class="pill disabled">writes locked</span>
          </div>
        </div>
        <div class="status-list">
          ${rows.map((row) => `
            <div class="row">
              <div>
                <strong>${this._escape(row.label)}</strong>
                <span>${this._escape(row.state)}</span>
                <small>${this._escape(row.detail)}</small>
              </div>
              <span class="pill ${this._escape(row.status)}">${this._escape(row.status === "ok" ? "covered" : row.status === "unknown" ? "candidate" : "needed")}</span>
            </div>
          `).join("")}
        </div>
      </section>
    `;
  }

  _stratonEvidenceLab() {
    const draft = this._stratonEvidenceDraft();
    const result = draft.result;
    const fixtureStateResult = draft.fixtureStateResult;
    const probeResult = draft.probeResult;
    const testerNoteResult = draft.testerNoteResult;
    const fixtures = this._stratonFixtures();
    const probeBusy = draft.probeLoading || draft.probeScanning;
    return `
      <article class="panel straton-evidence-lab">
        <div class="section-head">
          <div>
            <p class="eyebrow">Adapter lab</p>
            <h3>ATI evidence collector</h3>
            <p class="muted">Paste before/after ATI exports or network notes to find changed keys for a safe fixture adapter.</p>
          </div>
          <div class="button-row end">
            <button class="secondary compact-button" data-action="clear-straton-evidence">Clear</button>
            <button class="secondary compact-button" data-action="copy-straton-adapter-request">Copy evidence request</button>
            <button class="secondary compact-button" data-action="copy-straton-evidence" ${result || testerNoteResult ? "" : "disabled"}>Copy summary</button>
            <button class="primary compact-button" data-action="analyze-straton-evidence">Analyze</button>
          </div>
        </div>
        <div class="notice warning-notice"><strong>Privacy boundary.</strong> Raw pasted exports stay in this browser session and are not saved to OpenReef config. The copied summary is redacted.</div>
        <section class="mapping-section">
          <div class="section-head">
            <div>
              <p class="eyebrow">Beta return</p>
              <h3>Tester support-note intake</h3>
              <p class="muted">Paste the returned Straton support note to summarize the bypass verdict and promote safe candidate read paths.</p>
            </div>
            <div class="button-row end">
              <button class="secondary compact-button" data-action="clear-straton-tester-note">Clear note</button>
              <button class="secondary compact-button" data-action="load-straton-example-note">Load example note</button>
              <button class="primary compact-button" data-action="analyze-straton-tester-note">Analyze note</button>
            </div>
          </div>
          <div class="grid three compact">
            <label>Example scenario
              <select data-straton-evidence="testerNoteScenario">
                <option value="strong" ${draft.testerNoteScenario === "strong" ? "selected" : ""}>Strong AP read</option>
                <option value="lan" ${draft.testerNoteScenario === "lan" ? "selected" : ""}>LAN-only read</option>
                <option value="route" ${draft.testerNoteScenario === "route" ? "selected" : ""}>AP route blocker</option>
                <option value="reachable" ${draft.testerNoteScenario === "reachable" ? "selected" : ""}>Reachability only</option>
                <option value="bluetooth" ${draft.testerNoteScenario === "bluetooth" ? "selected" : ""}>Reef Pilot Bluetooth</option>
              </select>
            </label>
          </div>
          <label>Returned support note<textarea data-straton-evidence="testerNote" rows="7" placeholder="Paste the copied OpenReef Straton support note from the beta tester.">${this._escape(draft.testerNote || "")}</textarea></label>
          ${this._stratonTesterNoteResult(testerNoteResult)}
        </section>
        <section class="mapping-section">
          <div class="section-head">
            <div>
              <p class="eyebrow">Read-only adapter</p>
              <h3>Current fixture sample</h3>
              <p class="muted">Paste a current Straton JSON export or run a read-only GET against a mapped fixture path, then compare candidate fields with the OpenReef plan.</p>
            </div>
            <div class="button-row end">
              <button class="secondary compact-button" data-action="clear-straton-fixture-state">Clear sample</button>
              <button class="primary compact-button" data-action="analyze-straton-fixture-state">Analyze sample</button>
            </div>
          </div>
          <div class="grid three compact">
            <label>Probe fixture
              <select data-straton-evidence="probeFixtureId">
                ${fixtures.length ? fixtures.map((fixture) => `
                  <option value="${this._escape(fixture.id)}" ${draft.probeFixtureId === fixture.id ? "selected" : ""}>${this._escape(fixture.name)} - ${this._escape(this._stratonRedactSnippet(fixture.host || "no host"))}</option>
                `).join("") : `<option value="">Add a fixture first</option>`}
              </select>
            </label>
            <label>GET path<input data-straton-evidence="probePath" value="${this._escape(draft.probePath)}" placeholder="/settings or path from network capture"></label>
            <div class="button-row end">
              <button class="secondary compact-button" data-action="probe-straton-fixture-state" ${fixtures.length && !probeBusy ? "" : "disabled"}>${probeBusy ? "Reading..." : "Controller GET"}</button>
            </div>
          </div>
          ${this._stratonProbeResult(probeResult)}
          <label>Fixture sample<textarea data-straton-evidence="fixtureState" rows="7" placeholder="{&#10;  &quot;program&quot;: { &quot;peak&quot;: 62, &quot;startTime&quot;: &quot;10:00&quot; },&#10;  &quot;firmware&quot;: &quot;2024.4&quot;&#10;}">${this._escape(draft.fixtureState)}</textarea></label>
          <div class="notice compact-notice"><strong>Candidate comparison only.</strong> This does not prove an ATI endpoint contract; it helps map likely fields before a real read-only adapter is built.</div>
          ${this._stratonFixtureStateResult(fixtureStateResult)}
        </section>
        <div class="grid three compact">
          <label>Before export<textarea data-straton-evidence="before" rows="6" placeholder="{...before schedule or spectrum edit...}">${this._escape(draft.before)}</textarea></label>
          <label>After export<textarea data-straton-evidence="after" rows="6" placeholder="{...after one small edit...}">${this._escape(draft.after)}</textarea></label>
          <label>Network notes<textarea data-straton-evidence="notes" rows="6" placeholder="POST /api/...&#10;GET /settings?...">${this._escape(draft.notes)}</textarea></label>
        </div>
        ${this._stratonEvidenceCoverage(result)}
        ${result ? `
          <div class="summary-grid">
            <article class="summary-card ${result.changedCount ? "warning" : "ok"}"><span>Changed</span><strong>${this._escape(result.changedCount)}</strong><small>${this._escape(result.mode)} comparison</small></article>
            <article class="summary-card ${result.addedCount || result.removedCount ? "warning" : "unknown"}"><span>Added / removed</span><strong>${this._escape(result.addedCount)} / ${this._escape(result.removedCount)}</strong><small>Key or line presence</small></article>
            <article class="summary-card ${result.endpoints.length ? "ok" : "unknown"}"><span>Endpoint hints</span><strong>${this._escape(result.endpoints.length)}</strong><small>${this._escape(result.checkedAt)}</small></article>
          </div>
          ${result.warning ? `<p class="hint">${this._escape(result.warning)}</p>` : ""}
          <div class="status-list">
            ${result.rows?.length ? result.rows.map((row) => `
              <div class="row">
                <div><strong>${this._escape(row.kind)}</strong><span>${this._escape(row.path)}</span></div>
                <span class="pill ${row.focus === "other" || row.focus === "line" ? "unknown" : "ok"}">${this._escape(row.focus)}</span>
              </div>
            `).join("") : `<p class="muted">No differences detected between the pasted evidence blocks.</p>`}
          </div>
          <div class="setup-next-list">
            ${result.endpoints.length ? result.endpoints.map((row) => `
              <div><span class="pill ok">${this._escape(row.method)}</span><p>${this._escape(row.path)}</p></div>
            `).join("") : `<div><span class="pill warning">needed</span><p>Paste method/path notes from the browser network panel to map load/save endpoints.</p></div>`}
          </div>
        ` : `
          <div class="setup-next-list">
            <div><span class="pill unknown">1</span><p>Export ATI settings before one small schedule, channel, or grouping edit.</p></div>
            <div><span class="pill unknown">2</span><p>Export again after the edit, then paste both exports here.</p></div>
            <div><span class="pill unknown">3</span><p>Add method/path notes from the browser network panel if available.</p></div>
          </div>
        `}
      </article>
    `;
  }

  _stratonProgramPackage() {
    const straton = this._stratonConfig();
    const template = this._stratonTemplate(straton.selectedTemplate);
    return {
      kind: "openreef-straton-program",
      version: 1,
      exportedAt: new Date().toISOString(),
      selectedTemplate: straton.selectedTemplate,
      templateName: template.name,
      adapter: straton.adapter,
      program: {
        peak: Number(straton.program.peak) || 0,
        startTime: straton.program.startTime || "10:00",
        photoperiodHours: Number(straton.program.photoperiodHours) || 10,
        rampMinutes: Number(straton.program.rampMinutes) || 90,
        acclimationStart: Number(straton.program.acclimationStart) || 0,
        acclimationTarget: Number(straton.program.acclimationTarget) || 0,
        acclimationDays: Number(straton.program.acclimationDays) || 1,
        quickMode: straton.program.quickMode || "auto",
        moonlight: Number(straton.program.moonlight) || 0,
        lunarMode: straton.program.lunarMode || "manual",
        cloudDim: Number(straton.program.cloudDim) || 0,
      },
      endpoints: {
        ...this._stratonEndpoints(),
      },
      fixtures: this._stratonFixtures().map((fixture) => ({
        name: fixture.name,
        host: fixture.host,
        firmware: fixture.firmware,
        group: fixture.group,
        connectionMode: fixture.connectionMode || "unknown",
        setupState: fixture.setupState || "unknown",
        selected: fixture.selected !== false,
      })),
      receipt: straton.lastReceipt || "",
    };
  }

  _stratonProgramPackageText() {
    return JSON.stringify(this._stratonProgramPackage(), null, 2);
  }

  async _copyStratonProgramPackage() {
    await this._copyText(this._stratonProgramPackageText(), "Straton program package copied", "Could not copy Straton program package");
  }

  _stratonImportedProgram(source) {
    const program = source?.program && typeof source.program === "object" ? source.program : {};
    const startTime = String(program.startTime || "10:00").slice(0, 5);
    return {
      peak: Math.max(0, Math.min(100, Number(program.peak) || 0)),
      startTime: /^\d{1,2}:\d{2}$/.test(startTime) ? startTime : "10:00",
      photoperiodHours: Math.max(1, Math.min(16, Number(program.photoperiodHours) || 10)),
      rampMinutes: Math.max(15, Math.min(240, Number(program.rampMinutes) || 90)),
      acclimationStart: Math.max(0, Math.min(100, Number(program.acclimationStart) || 0)),
      acclimationTarget: Math.max(0, Math.min(100, Number(program.acclimationTarget) || 0)),
      acclimationDays: Math.max(1, Math.min(120, Number(program.acclimationDays) || 1)),
      quickMode: ["auto", "blue", "photo", "feeding"].includes(program.quickMode) ? program.quickMode : "auto",
      moonlight: Math.max(0, Math.min(5, Number(program.moonlight) || 0)),
      lunarMode: ["manual", "seasonal", "off"].includes(program.lunarMode) ? program.lunarMode : "manual",
      cloudDim: Math.max(0, Math.min(60, Number(program.cloudDim) || 0)),
    };
  }

  _stratonImportedFixtures(source) {
    const fixtures = Array.isArray(source?.fixtures) ? source.fixtures : [];
    return fixtures.slice(0, 12).map((fixture, index) => {
      const item = fixture && typeof fixture === "object" ? fixture : {};
      const connectionModes = ["unknown", "lan", "ap"];
      const setupStates = ["unknown", "already_on_lan", "brand_new", "stuck_setup"];
      const host = String(item.host || item.ip || "192.168.100.1").slice(0, 80);
      return {
        id: this._slug(item.id || item.name || `straton_${index + 1}`) || `straton_${index + 1}`,
        name: String(item.name || `Straton ${index + 1}`).slice(0, 60),
        host,
        firmware: String(item.firmware || "unknown").slice(0, 32),
        group: String(item.group || "Display").slice(0, 40),
        connectionMode: connectionModes.includes(item.connectionMode) ? item.connectionMode : host === "192.168.100.1" ? "ap" : "unknown",
        setupState: setupStates.includes(item.setupState) ? item.setupState : "unknown",
        selected: item.selected !== false,
      };
    });
  }

  _importStratonProgramPackage() {
    const raw = String(this._stratonProgramImport || "").trim();
    if (!raw) {
      this._error = "Paste an OpenReef Straton program package before importing.";
      this._render();
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this._error = "That Straton program package is not valid JSON.";
      this._render();
      return;
    }
    const source = parsed?.kind === "openreef-straton-program"
      ? parsed
      : parsed?.straton && typeof parsed.straton === "object"
        ? parsed.straton
        : null;
    if (!source || !source.program || typeof source.program !== "object") {
      this._error = "That JSON does not look like an OpenReef Straton program package.";
      this._render();
      return;
    }
    const straton = this._stratonConfig();
    const knownTemplate = this._stratonTemplates().some((template) => template.id === source.selectedTemplate);
    const knownAdapter = ["reeftech_wifi", "reefpilot_bluetooth", "home_assistant", "manual_backup"].includes(source.adapter);
    straton.selectedTemplate = knownTemplate ? source.selectedTemplate : straton.selectedTemplate;
    straton.adapter = knownAdapter ? source.adapter : straton.adapter;
    straton.program = this._stratonImportedProgram(source);
    if (source.endpoints && typeof source.endpoints === "object") {
      straton.endpoints = {
        ...this._stratonEndpoints(),
        reachability: this._stratonCatalogPath(source.endpoints.reachability),
        currentState: this._stratonCatalogPath(source.endpoints.currentState),
        program: this._stratonCatalogPath(source.endpoints.program),
        firmware: this._stratonCatalogPath(source.endpoints.firmware),
        groups: this._stratonCatalogPath(source.endpoints.groups),
        lastScanAt: String(source.endpoints.lastScanAt || "").slice(0, 40),
        lastOutcome: String(source.endpoints.lastOutcome || "").slice(0, 80),
      };
    }
    const importedFixtures = this._stratonImportedFixtures(source);
    if (importedFixtures.length) straton.fixtures = importedFixtures;
    const timestamp = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    straton.lastReceipt = `${timestamp}: Imported Straton program package locally. Save local plan after review.`;
    this._stratonProgramImport = "";
    this._recordActivity("Imported Straton program package locally", "control");
    this._setDirty(true);
    this._render();
  }

  _stratonBackupPanel() {
    const packageText = this._stratonProgramPackageText();
    return `
      <article class="panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">Backup</p>
            <h3>Program package</h3>
            <p class="muted">Copy, restore, or share a local Straton plan without touching hardware.</p>
          </div>
          <div class="button-row end">
            <button class="secondary compact-button" data-action="clear-straton-program-import">Clear import</button>
            <button class="secondary compact-button" data-action="import-straton-program">Import</button>
            <button class="primary compact-button" data-action="copy-straton-program">Copy package</button>
          </div>
        </div>
        <div class="grid two compact">
          <label>Current package<textarea rows="8" readonly>${this._escape(packageText)}</textarea></label>
          <label>Import package<textarea data-straton-program-import="text" rows="8" placeholder="{&#10;  &quot;kind&quot;: &quot;openreef-straton-program&quot;,&#10;  ...&#10;}">${this._escape(this._stratonProgramImport || "")}</textarea></label>
        </div>
        <div class="notice warning-notice"><strong>Review before saving.</strong> Program packages include fixture host/IP fields for backup restore. Use the support summary when you need a redacted diagnostic note.</div>
      </article>
    `;
  }

  _stratonAdapterLabel(value) {
    return {
      reeftech_wifi: "ReefTECH Wi-Fi",
      reefpilot_bluetooth: "Reef Pilot Bluetooth",
      home_assistant: "Home Assistant light entity",
      manual_backup: "Manual backup only",
    }[value] || "Unknown adapter";
  }

  _stratonQuickLabel(value) {
    return {
      auto: "Auto schedule",
      blue: "Blue phase",
      photo: "Photo white",
      feeding: "Feeding hold",
    }[value] || "Auto schedule";
  }

  _stratonConnectionModeLabel(value) {
    return {
      lan: "LAN IP/host",
      ap: "AP fallback",
      unknown: "Unknown path",
    }[value] || "Unknown path";
  }

  _stratonSetupStateLabel(value) {
    return {
      already_on_lan: "Already on LAN",
      brand_new: "Brand new/reset",
      stuck_setup: "Stuck in setup",
      unknown: "Unknown setup",
    }[value] || "Unknown setup";
  }

  _stratonFirmwareReady(firmware) {
    const year = Number(String(firmware || "").split(".")[0]);
    return Number.isFinite(year) && year >= 2024;
  }

  _stratonReadiness() {
    const fixtures = this._stratonFixtures();
    const selected = fixtures.filter((fixture) => fixture.selected);
    if (!fixtures.length) return ["warning", "Add fixtures", "Add each Straton by IP, host, or AP fallback before using the program planner."];
    if (!selected.length) return ["warning", "No targets", "Select at least one fixture target before saving a local plan."];
    const oldFirmware = selected.filter((fixture) => !this._stratonFirmwareReady(fixture.firmware));
    if (oldFirmware.length) return ["warning", "Firmware review", `${oldFirmware.length} selected fixture(s) need firmware confirmation before future app control.`];
    return ["ok", "Local planner ready", "Targets are selected. Hardware write support still waits for a verified adapter."];
  }

  _addStratonFixture() {
    const fixtures = this._stratonFixtures();
    const index = fixtures.length + 1;
    fixtures.push({
      id: `straton_${Date.now().toString(36)}`,
      name: `Straton ${index}`,
      host: index === 1 ? "192.168.100.1" : `192.168.1.${47 + index}`,
      firmware: "unknown",
      group: "Display",
      connectionMode: index === 1 ? "ap" : "unknown",
      setupState: "unknown",
      selected: true,
    });
    this._recordActivity("Added ATI Straton fixture");
    this._setDirty(true);
    this._render();
  }

  _removeStratonFixture(id) {
    const fixture = this._stratonFixtures().find((item) => item.id === id);
    this._stratonConfig().fixtures = this._stratonFixtures().filter((item) => item.id !== id);
    this._recordActivity(`Removed Straton fixture: ${fixture?.name || id}`, "warning");
    this._setDirty(true);
    this._render();
  }

  _applyStratonTemplate(id) {
    const template = this._stratonTemplate(id);
    const straton = this._stratonConfig();
    const program = this._stratonProgram();
    straton.selectedTemplate = template.id;
    program.peak = template.peak;
    program.photoperiodHours = template.photoperiodHours;
    straton.lastReceipt = `Draft: ${template.name} applied locally. Save local plan before any future hardware sync.`;
    this._recordActivity(`Straton template staged: ${template.name}`);
    this._setDirty(true);
    this._render();
  }

  _previewStratonTemplate(id) {
    const template = this._stratonTemplate(id);
    this._stratonConfig().lastReceipt = `Preview: ${template.name} - ${template.detail}`;
    this._render();
  }

  _setStratonQuickMode(mode) {
    const program = this._stratonProgram();
    program.quickMode = mode || "auto";
    if (mode === "blue") program.peak = 34;
    if (mode === "photo") program.peak = 38;
    if (mode === "feeding") program.peak = 18;
    this._stratonConfig().lastReceipt = `Draft quick mode: ${this._stratonQuickLabel(program.quickMode)}. Temporary until saved as a local plan.`;
    this._recordActivity(`Straton quick mode staged: ${this._stratonQuickLabel(program.quickMode)}`);
    this._setDirty(true);
    this._render();
  }

  async _confirmStratonProgram() {
    const straton = this._stratonConfig();
    const selected = this._stratonFixtures().filter((fixture) => fixture.selected);
    if (!selected.length) {
      this._error = "Select at least one Straton fixture before saving a local plan.";
      this._render();
      return;
    }
    const template = this._stratonTemplate(straton.selectedTemplate);
    const timestamp = new Date().toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    straton.lastReceipt = `${timestamp}: ${template.name} saved as a local plan for ${selected.length} fixture target(s). Hardware write adapter not enabled yet.`;
    this._recordActivity(`Straton local plan saved: ${template.name}`, "control");
    this._setDirty(true);
    await this._saveConfig();
  }

  _stratonFixtureRows() {
    const fixtures = this._stratonFixtures();
    if (!fixtures.length) {
      return `<p class="muted">No ATI Straton fixtures yet. Add one with the AP fallback address or the fixture's LAN host/IP.</p>`;
    }
    return fixtures.map((fixture) => {
      const ready = this._stratonFirmwareReady(fixture.firmware);
      return `
        <section class="mapping-card entity-card straton-fixture-card">
          <div class="mapping-head">
            <div>
              <p class="eyebrow">${this._escape(fixture.group || "Display")}</p>
              <h3>${this._escape(fixture.name)}</h3>
            </div>
            <div class="pill-stack inline">
              <span class="pill ${fixture.connectionMode === "ap" ? "warning" : fixture.connectionMode === "lan" ? "ok" : "unknown"}">${this._escape(this._stratonConnectionModeLabel(fixture.connectionMode))}</span>
              <span class="pill ${ready ? "ok" : "warning"}">${ready ? "firmware ready" : "review firmware"}</span>
            </div>
          </div>
          <div class="grid two compact">
            <label>Name<input data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="name" value="${this._escape(fixture.name)}"></label>
            <label>IP or host<input data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="host" value="${this._escape(fixture.host)}" placeholder="192.168.100.1"></label>
            <label>Firmware<input data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="firmware" value="${this._escape(fixture.firmware)}" placeholder="2024.4"></label>
            <label>Group<input data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="group" value="${this._escape(fixture.group)}" placeholder="Display"></label>
            <label>Connection path
              <select data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="connectionMode">
                <option value="unknown" ${fixture.connectionMode === "unknown" ? "selected" : ""}>Unknown path</option>
                <option value="lan" ${fixture.connectionMode === "lan" ? "selected" : ""}>LAN IP/host</option>
                <option value="ap" ${fixture.connectionMode === "ap" ? "selected" : ""}>AP fallback</option>
              </select>
            </label>
            <label>Setup state
              <select data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="setupState">
                <option value="unknown" ${fixture.setupState === "unknown" ? "selected" : ""}>Unknown setup</option>
                <option value="already_on_lan" ${fixture.setupState === "already_on_lan" ? "selected" : ""}>Already on LAN</option>
                <option value="brand_new" ${fixture.setupState === "brand_new" ? "selected" : ""}>Brand new/reset</option>
                <option value="stuck_setup" ${fixture.setupState === "stuck_setup" ? "selected" : ""}>Stuck in setup</option>
              </select>
            </label>
          </div>
          <div class="control-row">
            <label class="toggle-card compact-toggle">
              <input type="checkbox" data-scope="straton-fixture" data-id="${this._escape(fixture.id)}" data-field="selected" ${fixture.selected ? "checked" : ""}>
              <span><strong>Target this fixture</strong><small>Included in local receipts and future adapter sync.</small></span>
            </label>
            <button class="danger-text compact-button" data-action="remove-straton-fixture" data-id="${this._escape(fixture.id)}">Remove</button>
          </div>
        </section>
      `;
    }).join("");
  }

  _stratonTemplateCards() {
    const straton = this._stratonConfig();
    return this._stratonTemplates().map((template) => `
      <article class="mapping-card entity-card straton-template ${straton.selectedTemplate === template.id ? "active-template" : ""}">
        <div class="mapping-head">
          <div>
            <p class="eyebrow">${this._escape(template.source)}</p>
            <h3>${this._escape(template.name)}</h3>
          </div>
          <span class="pill ${template.peak > 70 ? "warning" : "ok"}">${this._escape(template.peak)}% peak</span>
        </div>
        <p class="muted">${this._escape(template.detail)}</p>
        <div class="pill-stack inline">
          <span class="pill">${this._escape(template.photoperiodHours)} h</span>
          <span class="pill">${this._escape(template.tags)}</span>
        </div>
        <div class="setup-next-list">
          ${template.notes.map((note) => `<div><span class="pill unknown">note</span><p>${this._escape(note)}</p></div>`).join("")}
        </div>
        <div class="button-row end">
          <button class="secondary compact-button" data-action="preview-straton-template" data-id="${this._escape(template.id)}">Preview</button>
          <button class="primary compact-button" data-action="apply-straton-template" data-id="${this._escape(template.id)}">Apply</button>
        </div>
      </article>
    `).join("");
  }

  _stratonConnectionRescuePanel() {
    const draft = this._stratonEvidenceDraft();
    const fixture = this._stratonProbeFixture();
    const result = draft.probeResult;
    const reachable = result && ["ok", "unknown"].includes(result.statusClass) && result.status !== "not run";
    const jsonReady = result?.mode === "json";
    const presets = this._stratonProbePathPresets();
    const extraPresets = this._stratonExtraProbePathPresets(draft.extraProbePaths);
    const probeBusy = draft.probeLoading || draft.probeScanning;
    const route = this._stratonApRouteStatus(draft.probeScanResult, fixture);
    return `
      <article class="panel straton-connection-rescue">
        <div class="section-head">
          <div>
            <p class="eyebrow">Setup rescue</p>
            <h3>Controller reachability</h3>
            <p class="muted">First prove OpenReef can reach the Straton directly. Program reads and writes come after this.</p>
          </div>
          <div class="button-row end">
            <button class="secondary compact-button" data-action="straton-ap-fallback">Use AP fallback</button>
            <button class="secondary compact-button" data-action="copy-straton-beta-update">Copy beta update</button>
            <button class="secondary compact-button" data-action="copy-straton-tester-steps">Copy tester steps</button>
            <button class="secondary compact-button" data-action="probe-straton-scan" ${fixture && !probeBusy ? "" : "disabled"}>${draft.probeScanning ? "Scanning..." : "Scan safe paths"}</button>
            <button class="primary compact-button" data-action="probe-straton-path" data-id="/" ${fixture && !probeBusy ? "" : "disabled"}>${probeBusy ? "Reading..." : "Test root"}</button>
          </div>
        </div>
        <div class="summary-grid">
          <article class="summary-card ${fixture ? "ok" : "warning"}"><span>Fixture host</span><strong>${this._escape(fixture?.host || "none")}</strong><small>${this._escape(fixture?.name || "add a fixture")}</small></article>
          <article class="summary-card ${reachable ? "ok" : result ? "warning" : "unknown"}"><span>Reachability</span><strong>${this._escape(result?.status || "not tested")}</strong><small>${this._escape(result?.source || "controller probe")}</small></article>
          <article class="summary-card ${jsonReady ? "ok" : reachable ? "unknown" : "warning"}"><span>Fixture JSON</span><strong>${jsonReady ? "found" : reachable ? "not yet" : "unknown"}</strong><small>${this._escape(result?.path || draft.probePath || "/")}</small></article>
          <article class="summary-card ${this._escape(route.status)}"><span>AP route</span><strong>${this._escape(route.title)}</strong><small>${this._escape(route.source)}</small></article>
          <article class="summary-card ${extraPresets.length ? "unknown" : "ok"}"><span>Extra paths</span><strong>${this._escape(extraPresets.length)}</strong><small>GET-only queue</small></article>
        </div>
        ${this._stratonSetupBypassBanner(draft.probeScanResult, fixture)}
        <div class="setup-next-list">
          <div><span class="pill ${fixture ? "ok" : "warning"}">1</span><p>${fixture ? `Target ${this._escape(fixture.name)} at ${this._escape(this._stratonRedactSnippet(fixture.host))}` : "Add a Straton fixture target."}</p></div>
          <div><span class="pill ${reachable ? "ok" : "warning"}">2</span><p>${reachable ? `Controller reached ${this._escape(result.path || "/")}.` : "Use AP fallback or a LAN IP, then test root."}</p></div>
          <div><span class="pill ${jsonReady ? "ok" : "unknown"}">3</span><p>${jsonReady ? "JSON response is ready for planned-vs-observed comparison." : "Try read-only candidate paths until a JSON response appears."}</p></div>
        </div>
        <div class="button-row">
          ${presets.map((preset) => `
            <button class="secondary compact-button" data-action="probe-straton-path" data-id="${this._escape(preset.path)}" ${fixture && !probeBusy ? "" : "disabled"} title="${this._escape(preset.detail)}">${this._escape(preset.label)}</button>
          `).join("")}
        </div>
        <label>Extra safe GET paths<textarea data-straton-evidence="extraProbePaths" rows="2" placeholder="/api/config&#10;/data/settings">${this._escape(draft.extraProbePaths || "")}</textarea></label>
        <p class="hint">${this._escape(extraPresets.length ? `${extraPresets.length} extra path(s) will be included in Scan safe paths.` : "Optional: paste relative GET paths from ATI exports or redacted network notes. Full URLs are ignored.")}</p>
        ${this._stratonProbeScanResult(draft.probeScanResult)}
        ${this._stratonEndpointCatalog()}
      </article>
    `;
  }

  _stratonAdvancedTools() {
    return `
      <details class="straton-advanced-tools">
        <summary>
          <span>Advanced Straton tools</span>
          <small>Connection rescue, beta evidence, adapter gates, and read-only mapping.</small>
        </summary>
        <div class="stack tight">
          ${this._stratonConnectionRescuePanel()}
          ${this._stratonBetaEvidencePanel()}
          ${this._stratonAdapterGatePanel()}
          ${this._stratonPainPointCoveragePanel()}
          ${this._stratonEvidenceLab()}
        </div>
      </details>
    `;
  }

  _lights() {
    const straton = this._stratonConfig();
    const program = this._stratonProgram();
    const fixtures = this._stratonFixtures();
    const targets = fixtures.filter((fixture) => fixture.selected);
    const template = this._stratonTemplate(straton.selectedTemplate);
    const equipment = this._stratonLightingEquipment();
    const liveRows = this._stratonLightLiveRows();
    const [bridgeClass, bridgeTitle, bridgeDetail] = this._stratonLiveBridgeSummary(liveRows);
    const [readinessClass, readinessTitle, readinessDetail] = this._stratonReadiness();
    const dailyChange = program.acclimationDays
      ? Math.round(((Number(program.acclimationTarget) - Number(program.acclimationStart)) / Number(program.acclimationDays)) * 10) / 10
      : 0;
    return `
      <section class="missionControl straton-screen">
        <div class="hero">
          <div>
            <p class="eyebrow">ATI Straton</p>
            <h2>OpenReef light planner</h2>
            <p class="muted">Native controller planning for Straton fixtures. Saves local plans and receipts now; hardware writes wait for a verified adapter.</p>
          </div>
          <div class="pill-stack">
            <span class="pill ${readinessClass}">${this._escape(readinessTitle)}</span>
            <button class="secondary compact-button" data-action="copy-straton-support">Copy support note</button>
            <button class="primary compact-button" data-action="confirm-straton-program">Save local plan</button>
          </div>
        </div>

        <div class="summary-grid">
          <article class="summary-card ${fixtures.length ? "ok" : "warning"}"><span>Fixtures</span><strong>${this._escape(fixtures.length)}</strong><small>${this._escape(targets.length)} selected target(s)</small></article>
          <article class="summary-card ok"><span>Template</span><strong>${this._escape(template.name)}</strong><small>${this._escape(template.source)}</small></article>
          <article class="summary-card ${program.peak > 72 ? "warning" : "ok"}"><span>Peak</span><strong>${this._escape(program.peak)}%</strong><small>${this._escape(program.photoperiodHours)} hour photoperiod</small></article>
          <article class="summary-card ${bridgeClass}"><span>Live bridge</span><strong>${this._escape(bridgeTitle)}</strong><small>${this._escape(this._stratonAdapterLabel(straton.adapter))}</small></article>
        </div>

        <div class="notice ${readinessClass === "ok" ? "success" : "warning-notice"}"><strong>${this._escape(readinessTitle)}.</strong> ${this._escape(readinessDetail)}</div>

        <div class="grid two">
          <article class="panel">
            <div class="section-head">
              <div><p class="eyebrow">Fixtures</p><h3>Targets and direct-IP fallback</h3></div>
              <button class="secondary compact-button" data-action="add-straton-fixture">Add fixture</button>
            </div>
            <div class="stack tight">${this._stratonFixtureRows()}</div>
          </article>

          <article class="panel">
            <div class="section-head">
              <div><p class="eyebrow">Live</p><h3>Quick controls and natural effects</h3></div>
              <span class="pill ok">${this._escape(this._stratonQuickLabel(program.quickMode))}</span>
            </div>
            <div class="mode-actions">
              ${["auto", "blue", "photo", "feeding"].map((mode) => `
                <button class="mode-button ${program.quickMode === mode ? "active" : ""}" data-action="straton-quick" data-id="${this._escape(mode)}">
                  <strong>${this._escape(this._stratonQuickLabel(mode))}</strong>
                  <span>${mode === "auto" ? "Return to planned schedule" : mode === "blue" ? "Actinic coral check" : mode === "photo" ? "Warmer inspection light" : "Soft feeding hold"}</span>
                </button>
              `).join("")}
            </div>
            <div class="grid two compact">
              <label>Peak output<input type="number" min="0" max="100" data-scope="straton-program" data-field="peak" value="${this._escape(program.peak)}"></label>
              <label>Photoperiod hours<input type="number" min="1" max="16" data-scope="straton-program" data-field="photoperiodHours" value="${this._escape(program.photoperiodHours)}"></label>
              <label>Cloud dim %<input type="number" min="0" max="60" data-scope="straton-program" data-field="cloudDim" value="${this._escape(program.cloudDim)}"></label>
              <label>Moonlight %<input type="number" min="0" max="5" step="0.1" data-scope="straton-program" data-field="moonlight" value="${this._escape(program.moonlight)}"></label>
              <label>Lunar mode
                <select data-scope="straton-program" data-field="lunarMode">
                  <option value="manual" ${program.lunarMode === "manual" ? "selected" : ""}>Manual moon</option>
                  <option value="seasonal" ${program.lunarMode === "seasonal" ? "selected" : ""}>Seasonal moon sync</option>
                  <option value="off" ${program.lunarMode === "off" ? "selected" : ""}>Off</option>
                </select>
              </label>
              <label>Adapter
                <select data-scope="straton" data-field="adapter">
                  <option value="reeftech_wifi" ${straton.adapter === "reeftech_wifi" ? "selected" : ""}>ReefTECH Wi-Fi</option>
                  <option value="reefpilot_bluetooth" ${straton.adapter === "reefpilot_bluetooth" ? "selected" : ""}>Reef Pilot Bluetooth</option>
                  <option value="home_assistant" ${straton.adapter === "home_assistant" ? "selected" : ""}>Home Assistant light entity</option>
                  <option value="manual_backup" ${straton.adapter === "manual_backup" ? "selected" : ""}>Manual backup only</option>
                </select>
              </label>
            </div>
          </article>
        </div>

        ${this._stratonSyncMatrix(liveRows)}

        ${this._stratonSchedulePreview()}

        <article class="panel">
          <div class="section-head">
            <div><p class="eyebrow">Templates</p><h3>Research-backed program library</h3></div>
            <span class="pill">${this._escape(this._stratonTemplates().length)} templates</span>
          </div>
          <div class="grid three compact">${this._stratonTemplateCards()}</div>
        </article>

        <div class="grid two">
          <article class="panel">
            <div class="section-head">
              <div><p class="eyebrow">Acclimation</p><h3>Ramp guardrail</h3></div>
              <span class="pill ${Math.abs(dailyChange) > 1.5 ? "warning" : "ok"}">${this._escape(dailyChange)}% per day</span>
            </div>
            <div class="grid three compact">
              <label>Start %<input type="number" min="0" max="100" data-scope="straton-program" data-field="acclimationStart" value="${this._escape(program.acclimationStart)}"></label>
              <label>Target %<input type="number" min="0" max="100" data-scope="straton-program" data-field="acclimationTarget" value="${this._escape(program.acclimationTarget)}"></label>
              <label>Days<input type="number" min="1" max="120" data-scope="straton-program" data-field="acclimationDays" value="${this._escape(program.acclimationDays)}"></label>
            </div>
            <p class="hint">Acclimation reduces shock when changing lights, fixtures, mounting height, or template intensity. It is still advisory until hardware write support is enabled.</p>
          </article>

          <article class="panel">
            <div class="section-head">
              <div><p class="eyebrow">Controller bridge</p><h3>OpenReef integration status</h3></div>
              ${equipment.length ? `<span class="pill ok">${this._escape(equipment.length)} light equipment item(s)</span>` : `<button class="secondary compact-button" data-action="add-straton-light-equipment">Add lighting equipment</button>`}
            </div>
            <p class="hint">${this._escape(bridgeDetail)}</p>
            <div class="status-list">${this._stratonLiveBridgeRows(liveRows)}</div>
            <div class="setup-next-list">
              <div><span class="pill warning">needed</span><p>Exported ATI settings before and after schedule/color changes.</p></div>
              <div><span class="pill warning">needed</span><p>Browser network capture or fixture endpoint proof for safe read/write.</p></div>
              <div><span class="pill ok">read only</span><p>Home Assistant light entity bridge reads live state; it does not write programs.</p></div>
            </div>
          </article>
        </div>

        ${this._stratonBackupPanel()}

        ${this._stratonAdvancedTools()}

        <article class="panel">
          <div class="section-head">
            <div><p class="eyebrow">Receipt</p><h3>Save confidence</h3></div>
            <span class="pill ${straton.lastReceipt ? "ok" : "unknown"}">${straton.lastReceipt ? "recorded" : "none"}</span>
          </div>
          <p class="muted">${this._escape(straton.lastReceipt || "No Straton program receipt yet. Apply a template or confirm a program to create one.")}</p>
        </article>
      </section>
    `;
  }

  // --- Live cameras ------------------------------------------------------

  _cameraList() {
    return Object.entries(this._config.cameras || {});
  }

  _cameraSnapshotUrl(entityId) {
    const st = this._state(entityId);
    const pic = st?.attributes?.entity_picture;
    if (pic) return pic;
    const token = st?.attributes?.access_token;
    return token ? `/api/camera_proxy/${entityId}?token=${token}` : "";
  }

  _cameraStreamUrl(entityId) {
    const snap = this._cameraSnapshotUrl(entityId);
    return snap ? snap.replace("/camera_proxy/", "/camera_proxy_stream/") : "";
  }

  _cameraOnline(entityId) {
    const st = this._state(entityId);
    if (!st || ["unavailable", "unknown"].includes(st.state)) return false;
    return Boolean(this._cameraSnapshotUrl(entityId));
  }

  _startCameraWebRTCForFocus() {
    const id = this._cameraFocus;
    const cam = id && (this._config.cameras || {})[id];
    if (cam && cam.entity_id && this._cameraOnline(cam.entity_id)) {
      this._startCameraWebRTC(cam.entity_id);
    }
  }

  // Smooth live view: negotiate WebRTC through Home Assistant's own same-origin
  // websocket API (the flow ha-web-rtc-player uses). No external library, no
  // backend. Falls back to the MJPEG <img> if anything fails, so the worst case
  // is the previous (jumpy-but-working) behaviour, never worse.
  async _startCameraWebRTC(entityId) {
    this._stopCameraWebRTC();
    const conn = this._hass && this._hass.connection;
    const video = this.shadowRoot && this.shadowRoot.querySelector("video[data-camera-video]");
    if (!entityId || !conn || !video || typeof RTCPeerConnection === "undefined") {
      this._cameraWebRtcFallback(entityId);
      return;
    }
    const session = {
      entityId, pc: null, unsub: null, sessionId: null,
      pending: [], closed: false, fellBack: false, gotTrack: false,
      timer: null, connectionTimer: null,
    };
    this._webrtcSession = session;
    try {
      let configuration = {};
      try {
        const cfg = await conn.sendMessagePromise({
          type: "camera/webrtc/get_client_config", entity_id: entityId,
        });
        configuration = (cfg && cfg.configuration) || {};
      } catch {
        // Some setups don't expose client config; host candidates suffice for local go2rtc.
      }
      if (session.closed) return;
      const pc = new RTCPeerConnection(configuration);
      session.pc = pc;
      const remote = new MediaStream();
      video.srcObject = remote;
      pc.addTransceiver("video", { direction: "recvonly" });
      const clearConnectionTimer = () => {
        if (session.connectionTimer) {
          window.clearTimeout(session.connectionTimer);
          session.connectionTimer = null;
        }
      };
      const scheduleConnectionFallback = (delay) => {
        clearConnectionTimer();
        session.connectionTimer = window.setTimeout(() => {
          if (session.closed || !session.pc) return;
          const states = [session.pc.connectionState, session.pc.iceConnectionState];
          if (states.includes("failed") || states.includes("closed") || states.includes("disconnected")) {
            this._cameraWebRtcFallback(entityId);
          }
        }, delay);
      };
      const watchConnection = () => {
        if (session.closed || !session.pc) return;
        const states = [session.pc.connectionState, session.pc.iceConnectionState];
        if (states.includes("failed") || states.includes("closed")) scheduleConnectionFallback(0);
        else if (states.includes("disconnected")) scheduleConnectionFallback(3000);
        else if (states.includes("connected") || states.includes("completed")) clearConnectionTimer();
      };
      pc.addEventListener("connectionstatechange", watchConnection);
      pc.addEventListener("iceconnectionstatechange", watchConnection);
      pc.addEventListener("track", (ev) => {
        session.gotTrack = true;
        remote.addTrack(ev.track);
        const p = video.play();
        if (p && p.catch) p.catch(() => {});
      });
      pc.addEventListener("icecandidate", (ev) => {
        if (!ev.candidate) return;
        const candidate = ev.candidate.toJSON();
        if (session.sessionId) {
          conn.sendMessagePromise({
            type: "camera/webrtc/candidate", entity_id: entityId,
            session_id: session.sessionId, candidate,
          }).catch(() => {});
        } else {
          session.pending.push(candidate);
        }
      });
      const offer = await pc.createOffer({ offerToReceiveVideo: true });
      if (session.closed) return;
      await pc.setLocalDescription(offer);
      if (session.closed) return;
      const unsub = await conn.subscribeMessage(
        (msg) => this._handleWebRtcEvent(session, msg),
        { type: "camera/webrtc/offer", entity_id: entityId, offer: offer.sdp },
      );
      if (session.closed) { try { unsub(); } catch {} return; }
      session.unsub = unsub;
      // If no media arrives within a few seconds, drop to the MJPEG fallback.
      session.timer = window.setTimeout(() => {
        if (!session.closed && !session.gotTrack) this._cameraWebRtcFallback(entityId);
      }, 7000);
    } catch {
      this._cameraWebRtcFallback(entityId);
    }
  }

  _handleWebRtcEvent(session, msg) {
    if (!session || session.closed || !session.pc || !msg) return;
    const conn = this._hass && this._hass.connection;
    try {
      if (msg.type === "session") {
        session.sessionId = msg.session_id;
        for (const candidate of session.pending) {
          if (conn) {
            conn.sendMessagePromise({
              type: "camera/webrtc/candidate", entity_id: session.entityId,
              session_id: session.sessionId, candidate,
            }).catch(() => {});
          }
        }
        session.pending = [];
      } else if (msg.type === "answer") {
        session.pc.setRemoteDescription({ type: "answer", sdp: msg.answer })
          .catch(() => this._cameraWebRtcFallback(session.entityId));
      } else if (msg.type === "candidate") {
        if (msg.candidate) session.pc.addIceCandidate(msg.candidate).catch(() => {});
      } else if (msg.type === "error") {
        this._cameraWebRtcFallback(session.entityId);
      }
    } catch {
      this._cameraWebRtcFallback(session.entityId);
    }
  }

  _cameraWebRtcFallback(entityId) {
    const session = this._webrtcSession;
    if (session) {
      if (session.fellBack) return;
      session.fellBack = true;
    }
    this._teardownWebRtcPeer();
    const root = this.shadowRoot;
    if (!root) return;
    const video = root.querySelector("video[data-camera-video]");
    const img = root.querySelector("img[data-camera-fallback]");
    if (video) {
      try { video.srcObject = null; } catch {}
      video.style.display = "none";
    }
    if (img) {
      const url = this._cameraStreamUrl(entityId);
      if (url && img.getAttribute("src") !== url) img.src = url;
      img.style.display = "";
    }
  }

  _teardownWebRtcPeer() {
    const session = this._webrtcSession;
    if (!session) return;
    if (session.timer) { window.clearTimeout(session.timer); session.timer = null; }
    if (session.connectionTimer) { window.clearTimeout(session.connectionTimer); session.connectionTimer = null; }
    if (session.unsub) { try { session.unsub(); } catch {} session.unsub = null; }
    if (session.pc) {
      try { if (session.pc.getReceivers) session.pc.getReceivers().forEach((r) => { if (r.track) r.track.stop(); }); } catch {}
      try { session.pc.close(); } catch {}
      session.pc = null;
    }
  }

  _stopCameraWebRTC() {
    const session = this._webrtcSession;
    if (!session) return;
    session.closed = true;
    this._teardownWebRtcPeer();
    const video = this.shadowRoot && this.shadowRoot.querySelector("video[data-camera-video]");
    if (video) { try { video.srcObject = null; } catch {} }
    const img = this.shadowRoot && this.shadowRoot.querySelector("img[data-camera-fallback]");
    if (img) {
      try { img.removeAttribute("src"); } catch {}
      img.style.display = "none";
    }
    this._webrtcSession = null;
  }

  // Snapshot the CURRENT live frame straight from the <video> (or the MJPEG
  // fallback <img>) via canvas → download. No server round-trip, so no
  // camera_proxy 500s and no new tab. Falls back to opening HA's still image
  // only if there's no live frame ready to grab.
  async _snapshotCamera() {
    const cam = (this._config.cameras || {})[this._cameraFocus];
    const root = this.shadowRoot;
    const video = root && root.querySelector("video[data-camera-video]");
    const img = root && root.querySelector("img[data-camera-fallback]");
    const openStill = () => {
      const url = cam && this._cameraSnapshotUrl(cam.entity_id);
      if (url) window.open(url, "_blank", "noopener");
    };
    let source = null;
    let w = 0;
    let h = 0;
    if (video && video.videoWidth && video.readyState >= 2) {
      source = video;
      w = video.videoWidth;
      h = video.videoHeight;
    } else if (img && img.naturalWidth && img.style.display !== "none") {
      source = img;
      w = img.naturalWidth;
      h = img.naturalHeight;
    }
    if (!source || !w || !h) {
      openStill();
      return;
    }
    try {
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      canvas.getContext("2d").drawImage(source, 0, 0, w, h);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
      if (!blob) throw new Error("encode failed");
      const label = (cam && cam.label) || this._cameraFocus || "camera";
      const safe = label.replace(/[^a-z0-9_-]+/gi, "_").replace(/^_+|_+$/g, "") || "camera";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${safe}_${stamp}.jpg`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
    } catch {
      // Canvas blocked (rare) — fall back to HA's still image in a tab.
      openStill();
    }
  }

  // --- Live overlay + shareable tank card (Phase C) ----------------------

  _overlayCfg() {
    const cfg = this._config && this._config.overlay;
    return cfg && typeof cfg === "object" ? cfg : {};
  }

  // Rotating anti-Apex one-liners. Shown to ANY cheeky user on a calm tank — the
  // whole point is letting non-Apex owners have a dig too (deliberate exception to
  // the usual Apex-owner gating). Kept fact-fair: no subscription jokes.
  _overlayQuips() {
    return [
      "But can your Apex do this? 😏",
      "No virtual outlets here.",
      "Try that in Fusion.",
      "Clicks, not code.",
      "No Defer commands required.",
      "All this, zero lines of Apex code.",
      "Apex who? 🪸",
      "One dashboard. No spreadsheets.",
    ];
  }

  _pickOverlayQuip() {
    const quips = this._overlayQuips();
    return quips[Math.floor(Math.random() * quips.length)] || "";
  }

  _overlayReaction() {
    return this._buddyReaction(this._reefHealthScore(), this._tone());
  }

  _overlayIsCalm() {
    return this._overlayReaction().mood === "ok";
  }

  // The quip only shows in cheeky tone, on a calm tank, when enabled. Not Apex-gated.
  _overlayQuipText() {
    const cfg = this._overlayCfg();
    if (!cfg.enabled || !cfg.showQuip) return "";
    if (this._tone() !== "cheeky") return "";
    if (!this._overlayIsCalm()) return "";
    if (!this._overlayQuip) this._overlayQuip = this._pickOverlayQuip();
    return this._overlayQuip;
  }

  _overlayPose() {
    if (this._overlayQuipText()) return "smug";  // cocky pose when it's throwing the jab
    return this._overlayReaction().pose;
  }

  _overlayShortLabel(id, sensor) {
    const short = {
      temp: "Temp", temperature: "Temp", ph: "pH", alkalinity: "Alk", calcium: "Ca",
      magnesium: "Mg", salinity: "Salinity", orp: "ORP", nitrate: "NO₃", phosphate: "PO₄",
      dissolved_oxygen: "DO", co2: "CO₂", par: "PAR", flow: "Flow",
    }[id];
    return short || (sensor && sensor.label) || id;
  }

  // The chips to show: selected sensors (mapped + enabled) + optional Reef Health.
  _overlayStatList() {
    const cfg = this._overlayCfg();
    const sensors = this._config.sensors || {};
    const chips = [];
    for (const id of Array.isArray(cfg.stats) ? cfg.stats : []) {
      const sensor = sensors[id];
      if (!sensor || !sensor.entity_id || !this._sensorEnabled(sensor)) continue;
      chips.push({
        key: id,
        label: this._overlayShortLabel(id, sensor),
        value: this._sensorDisplayValue(id, sensor),
        unit: this._sensorDisplayUnit(id, sensor),
      });
    }
    if (cfg.showReefHealth) {
      const health = this._reefHealthScore();
      chips.push({
        key: "reefHealth",
        label: "Reef Health",
        value: String(health.score ?? "--"),
        unit: health.grade || "",
      });
    }
    return chips;
  }

  _cameraOverlayMarkup() {
    const cfg = this._overlayCfg();
    if (!cfg.enabled) return "";
    const chips = this._overlayStatList();
    const tank = this._config.tank || {};
    const showName = cfg.showTankName && tank.name;
    const quip = this._overlayQuipText();
    const pos = ["top-left", "top-right", "bottom-left", "bottom-right"].includes(cfg.position)
      ? cfg.position
      : "bottom-left";
    if (!chips.length && !showName && !(cfg.showAvatar)) return "";
    const chipsHtml = chips.map((chip) => `
      <span class="cam-overlay-chip ${chip.key === "reefHealth" ? "is-health" : ""}">
        <small>${this._escape(chip.label)}</small>
        <strong data-overlay-stat="${this._escape(chip.key)}">${this._escape(chip.value)}${chip.unit ? ` ${this._escape(chip.unit)}` : ""}</strong>
      </span>`).join("");
    const avatar = cfg.showAvatar
      ? `<div class="cam-overlay-avatar">
          ${quip ? `<span class="cam-overlay-bubble">${this._escape(quip)}</span>` : ""}
          ${this._avatarMarkup(this._overlayPose())}
        </div>`
      : "";
    return `
      <div class="cam-overlay pos-${pos}" data-camera-overlay>
        ${showName ? `<span class="cam-overlay-title">${this._escape(tank.name)}</span>` : ""}
        ${chips.length ? `<div class="cam-overlay-chips">${chipsHtml}</div>` : ""}
        ${avatar}
      </div>`;
  }

  // Patch the live overlay's stat values in place (no re-render -> video keeps playing).
  _updateCameraOverlay() {
    const cfg = this._overlayCfg();
    if (!cfg.enabled) return;
    const root = this.shadowRoot;
    if (!root || !root.querySelector("[data-camera-overlay]")) return;
    const sensors = this._config.sensors || {};
    root.querySelectorAll("[data-overlay-stat]").forEach((el) => {
      const key = el.getAttribute("data-overlay-stat");
      if (key === "reefHealth") {
        const health = this._reefHealthScore();
        el.textContent = `${health.score ?? "--"}${health.grade ? ` ${health.grade}` : ""}`;
        return;
      }
      const sensor = sensors[key];
      if (!sensor) return;
      const value = this._sensorDisplayValue(key, sensor);
      const unit = this._sensorDisplayUnit(key, sensor);
      el.textContent = `${value}${unit ? ` ${unit}` : ""}`;
    });
  }

  _loadImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = src;
    });
  }

  _roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  _downloadBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
  }

  // One-tap shareable tank card: bakes the stats + avatar + quip + wordmark into the
  // current frame via canvas, then native-shares (phones) or downloads (desktop).
  async _shareTankCard() {
    const cam = (this._config.cameras || {})[this._cameraFocus];
    const root = this.shadowRoot;
    const video = root && root.querySelector("video[data-camera-video]");
    const img = root && root.querySelector("img[data-camera-fallback]");
    const openStill = () => {
      const url = cam && this._cameraSnapshotUrl(cam.entity_id);
      if (url) window.open(url, "_blank", "noopener");
    };
    let source = null;
    let w = 0;
    let h = 0;
    if (video && video.videoWidth && video.readyState >= 2) {
      source = video;
      w = video.videoWidth;
      h = video.videoHeight;
    } else if (img && img.naturalWidth && img.style.display !== "none") {
      source = img;
      w = img.naturalWidth;
      h = img.naturalHeight;
    }
    if (!source || !w || !h) {
      openStill();
      return;
    }
    try {
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(source, 0, 0, w, h);
      await this._drawTankCard(ctx, w, h);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
      if (!blob) throw new Error("encode failed");
      const tankName = (this._config.tank && this._config.tank.name) || "My Reef";
      const safe = String(tankName).replace(/[^a-z0-9_-]+/gi, "_").replace(/^_+|_+$/g, "") || "reef";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const filename = `${safe}_tankcard_${stamp}.jpg`;
      const quip = this._overlayQuipText();
      const shareText = quip ? `${tankName} — ${quip}` : `${tankName} · built with OpenReef`;
      const file = new File([blob], filename, { type: "image/jpeg" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: tankName, text: shareText });
        } catch (err) {
          // AbortError = user cancelled the share sheet; anything else -> save instead.
          if (err && err.name !== "AbortError") this._downloadBlob(blob, filename);
        }
        return;
      }
      this._downloadBlob(blob, filename);
    } catch {
      openStill();
    }
  }

  async _drawTankCard(ctx, w, h) {
    const cfg = this._overlayCfg();
    const scale = w / 1280;
    const pad = Math.round(28 * scale);
    const font = (px, weight = "600") =>
      `${weight} ${Math.round(px * scale)}px -apple-system, "Segoe UI", Roboto, sans-serif`;
    const pos = ["top-left", "top-right", "bottom-left", "bottom-right"].includes(cfg.position)
      ? cfg.position
      : "bottom-left";

    // --- stats panel ---
    const chips = this._overlayStatList().map((chip) => ({
      label: chip.label,
      value: `${chip.value}${chip.unit ? ` ${chip.unit}` : ""}`,
      health: chip.key === "reefHealth",
    }));
    const tank = this._config.tank || {};
    const title = cfg.showTankName && tank.name ? String(tank.name) : "";
    if (title || chips.length) {
      const titleH = title ? Math.round(48 * scale) : 0;
      const rowH = Math.round(50 * scale);
      ctx.save();
      ctx.font = font(34, "700");
      let maxW = title ? ctx.measureText(title).width : 0;
      for (const chip of chips) {
        ctx.font = font(26, "600");
        const labelW = ctx.measureText(chip.label).width;
        ctx.font = font(34, "700");
        const valueW = ctx.measureText(chip.value).width;
        maxW = Math.max(maxW, labelW + valueW + Math.round(40 * scale));
      }
      const panelW = Math.min(w - pad * 2, Math.round(maxW + pad * 2));
      const panelH = Math.round(titleH + chips.length * rowH + pad);
      const x = pos.includes("right") ? w - pad - panelW : pad;
      const y = pos.includes("top") ? pad : h - pad - panelH;
      this._roundRect(ctx, x, y, panelW, panelH, Math.round(18 * scale));
      ctx.fillStyle = "rgba(4, 10, 16, 0.55)";
      ctx.fill();
      let cy = y + Math.round(pad * 0.6);
      ctx.textBaseline = "top";
      if (title) {
        ctx.font = font(34, "700");
        ctx.fillStyle = "#e9f4fb";
        ctx.fillText(title, x + pad, cy);
        cy += titleH;
      }
      for (const chip of chips) {
        ctx.font = font(26, "600");
        ctx.fillStyle = chip.health ? "#7fe0c4" : "#9fc7e0";
        ctx.fillText(chip.label, x + pad, cy + Math.round(12 * scale));
        ctx.font = font(34, "700");
        ctx.fillStyle = "#ffffff";
        const valueW = ctx.measureText(chip.value).width;
        ctx.fillText(chip.value, x + panelW - pad - valueW, cy + Math.round(8 * scale));
        cy += rowH;
      }
      ctx.restore();
    }

    // --- avatar + speech bubble (opposite side from the stats panel) ---
    if (cfg.showAvatar) {
      const avSize = Math.round(240 * scale);
      const ax = pos.includes("right") ? pad : w - pad - avSize;
      const ay = h - pad - avSize;
      const quip = this._overlayQuipText();
      if (quip) {
        ctx.save();
        ctx.font = font(28, "700");
        const tw = ctx.measureText(quip).width;
        const bw = Math.round(tw + 40 * scale);
        const bh = Math.round(56 * scale);
        const bx = Math.max(pad, Math.min(Math.round(ax + avSize / 2 - bw / 2), w - pad - bw));
        const by = ay - bh - Math.round(14 * scale);
        this._roundRect(ctx, bx, by, bw, bh, Math.round(14 * scale));
        ctx.fillStyle = "rgba(255, 255, 255, 0.94)";
        ctx.fill();
        ctx.fillStyle = "#0a2230";
        ctx.textBaseline = "middle";
        ctx.fillText(quip, bx + Math.round(20 * scale), by + bh / 2);
        ctx.restore();
      }
      const pose = this._overlayPose();
      const avatar = await this._loadImage(`${this._avatarBase()}${pose}.png`).catch(() => null);
      if (avatar) ctx.drawImage(avatar, ax, ay, avSize, avSize);
    }

    // --- OpenReef wordmark (top-right, out of the stats panel's way) ---
    ctx.save();
    ctx.font = font(26, "800");
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    ctx.textBaseline = "top";
    const mark = "OpenReef";
    const markW = ctx.measureText(mark).width;
    const markX = pos === "top-right" ? pad : w - pad - markW;
    ctx.fillText(mark, markX, pad);
    ctx.restore();
  }

  _overlaySettings() {
    const cfg = this._overlayCfg();
    const sensors = this._enabledSensors();
    const selected = Array.isArray(cfg.stats) ? cfg.stats : [];
    const positions = [
      ["top-left", "Top left"],
      ["top-right", "Top right"],
      ["bottom-left", "Bottom left"],
      ["bottom-right", "Bottom right"],
    ];
    const extra = (field, title, desc) => `
      <label class="toggle-card">
        <input type="checkbox" data-scope="overlay" data-field="${field}" ${cfg[field] ? "checked" : ""}>
        <span><strong>${this._escape(title)}</strong><small>${this._escape(desc)}</small></span>
      </label>`;
    const body = `
      <label class="toggle-card">
        <input type="checkbox" data-scope="overlay" data-field="enabled" ${cfg.enabled ? "checked" : ""}>
        <span><strong>Show stats on the live feed</strong><small>Burn selected readings (and the Reef Buddy) onto the camera view, and into a shareable tank card.</small></span>
      </label>
      <p class="eyebrow">Stats to show</p>
      ${sensors.length
        ? `<div class="grid two compact">${sensors.map(([id, sensor]) => `
            <label class="toggle-card">
              <input type="checkbox" data-scope="overlay-stats" data-id="${this._escape(id)}" ${selected.includes(id) ? "checked" : ""}>
              <span><strong>${this._escape(this._overlayShortLabel(id, sensor))}</strong><small>${this._escape(sensor.label || id)}</small></span>
            </label>`).join("")}</div>`
        : `<p class="muted">No sensors mapped yet.</p>`}
      <p class="eyebrow">Extras</p>
      <div class="grid two compact">
        ${extra("showReefHealth", "Reef Health score", "Show the overall health grade.")}
        ${extra("showTankName", "Tank name", "Title the overlay with your tank's name.")}
        ${extra("showAvatar", "Reef Buddy avatar", "Your reef guide, reacting to the tank's health.")}
        ${extra("showQuip", "Cheeky one-liner", "A rotating Apex jab — cheeky mode + calm tank only. Your dig to share.")}
      </div>
      <p class="eyebrow">Position</p>
      <label>Overlay corner
        <select data-scope="overlay" data-field="position">
          ${positions.map(([value, lbl]) => `<option value="${value}" ${cfg.position === value ? "selected" : ""}>${lbl}</option>`).join("")}
        </select>
      </label>
      <p class="muted">Open a camera and tap <strong>Share card</strong> to save or share a photo with all this baked in.</p>
    `;
    return this._settingsPanel(
      "overlay",
      "Live overlay & tank card",
      "Burn your stats (and a cheeky one-liner) onto the live feed and into a shareable photo.",
      body,
    );
  }

  // --- Feed-watch (Phase D): a scrubbable snapshot burst per feeding ------

  _feedWatchSection() {
    const fw = this._config.feedWatch || {};
    const state = this._feedWatch;
    if (!state.loaded && !state.loading) this._loadFeedSessions();
    const sessions = Array.isArray(state.sessions) ? state.sessions : [];
    const header = `
      <div class="section-head">
        <div>
          <h2>Feeds</h2>
          <p>OpenReef snaps a burst through each feeding — scrub a session to check every fish showed up and ate.</p>
        </div>
        <div class="actions">
          <button class="secondary compact-button" data-action="feed-reload">Refresh</button>
          <button class="secondary compact-button" data-action="tab" data-id="settings">Settings</button>
        </div>
      </div>`;
    let body;
    if (state.loading && !sessions.length) {
      body = `<div class="muted">Loading feeds…</div>`;
    } else if (state.error && !sessions.length) {
      body = `<div class="notice warning-notice">${this._escape(state.error)}</div>`;
    } else if (!sessions.length) {
      body = this._emptyState(
        fw.enabled ? "No feeds yet" : "Feed-watch is off",
        fw.enabled
          ? "Apply Feed mode and OpenReef will record the whole feeding here to scrub through."
          : "Turn on Feed-watch in Settings — then every Feed mode is captured as a scrubbable session.",
        "settings",
        fw.enabled ? "Open settings" : "Turn on feed-watch",
      );
    } else {
      body = `<div class="cam-grid recordings-grid">${sessions.map((s) => this._feedSessionCard(s)).join("")}</div>`;
    }
    return `
      <section class="stack feeds-section">${header}${body}</section>
      ${this._feedPlayer.sessionId ? this._feedModal() : ""}`;
  }

  _feedSessionCard(session) {
    const thumb = this._captureUrl(session.thumbnail);
    const recording = session.status === "recording";
    const count = session.frameCount || 0;
    return `
      <div class="cam-tile recording-tile">
        <button class="recording-open" data-action="open-feed" data-id="${this._escape(session.id)}" title="Feed at ${this._escape(this._formatActivityTime(session.startedAt))}">
          ${thumb
            ? `<img class="cam-feed" src="${this._escape(thumb)}" alt="Feed session">`
            : `<div class="cam-placeholder"><span class="cam-glyph">🐟</span><small>${recording ? "Recording…" : "No preview"}</small></div>`}
          ${recording ? `<span class="cam-live feed-rec"><span class="cam-dot"></span>REC</span>` : ""}
          <span class="cam-label">${this._escape(this._formatActivityTime(session.startedAt))}</span>
        </button>
        <div class="recording-meta">
          <span class="pill ${recording ? "warning" : "ok"}">${recording ? "recording" : `${count} frame${count === 1 ? "" : "s"}`}</span>
          <button class="secondary compact-button danger-button" data-action="delete-feed" data-id="${this._escape(session.id)}">Delete</button>
        </div>
      </div>`;
  }

  async _loadFeedSessions() {
    const state = this._feedWatch;
    state.loading = true;
    state.error = "";
    try {
      const result = await this._callWS({ type: "openreef/list_feed_sessions" });
      state.sessions = Array.isArray(result.sessions) ? result.sessions : [];
    } catch (err) {
      state.error = err instanceof Error ? err.message : "Could not load feeds";
      state.sessions = [];
    } finally {
      state.loaded = true;
      state.loading = false;
      if (this._activeTab === "cameras") this._render();
    }
  }

  async _openFeedSession(id) {
    const player = this._feedPlayer;
    player.sessionId = id;
    player.frames = [];
    player.index = 0;
    player.playing = false;
    player.loading = true;
    this._render();
    try {
      const result = await this._callWS({ type: "openreef/list_feed_frames", session_id: id });
      if (this._feedPlayer.sessionId !== id) return;
      player.frames = Array.isArray(result.frames) ? result.frames : [];
      player.index = 0;
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not load this feed";
    } finally {
      player.loading = false;
      if (this._feedPlayer.sessionId === id) this._render();
    }
  }

  _closeFeedSession() {
    this._stopFeedPlayer();
    this._feedPlayer.sessionId = "";
    this._feedPlayer.frames = [];
    this._render();
  }

  _feedModal() {
    const player = this._feedPlayer;
    const session = (this._feedWatch.sessions || []).find((s) => s.id === player.sessionId);
    const frames = player.frames;
    const title = session ? this._formatActivityTime(session.startedAt) : "Feed session";
    let stage;
    if (player.loading) {
      stage = `<div class="cam-placeholder"><span class="cam-glyph">🐟</span><small>Loading frames…</small></div>`;
    } else if (!frames.length) {
      stage = `<div class="cam-placeholder"><span class="cam-glyph">🐟</span><small>No frames in this feed yet</small></div>`;
    } else {
      const idx = Math.max(0, Math.min(player.index, frames.length - 1));
      stage = `<img class="cam-feed-large feed-frame" src="${this._escape(this._captureUrl(frames[idx].file))}" alt="Feed frame"><span class="timelapse-stamp feed-counter">${idx + 1} / ${frames.length}</span>`;
    }
    const controls = frames.length
      ? `<div class="timelapse-controls">
          <button class="secondary compact-button" data-action="feed-play">${player.playing ? "⏸ Pause" : "▶ Play"}</button>
          <input type="range" class="timelapse-scrubber feed-scrubber" min="0" max="${Math.max(0, frames.length - 1)}" value="${Math.max(0, Math.min(player.index, frames.length - 1))}" data-action="feed-seek">
        </div>`
      : "";
    return `
      <div class="modal">
        <section class="wizard cam-dialog">
          <button class="close" data-action="close-feed">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Feed-watch · ${this._escape(session?.cameraLabel || "Camera")}</p>
              <h2>${this._escape(title)}</h2>
              <p class="muted">Scrub through to confirm every fish came out and ate.</p>
            </div>
          </div>
          <div class="cam-stage">${stage}</div>
          ${controls}
          <div class="actions">
            <button class="secondary compact-button danger-button" data-action="delete-feed" data-id="${this._escape(player.sessionId)}">Delete feed</button>
          </div>
        </section>
      </div>`;
  }

  _stopFeedPlayer() {
    if (this._feedPlayerTimer) {
      window.clearInterval(this._feedPlayerTimer);
      this._feedPlayerTimer = null;
    }
    if (this._feedPlayer) this._feedPlayer.playing = false;
  }

  _feedTogglePlay() {
    const player = this._feedPlayer;
    if (player.playing) {
      this._stopFeedPlayer();
      this._render();
      return;
    }
    if (player.frames.length < 2) return;
    if (player.index >= player.frames.length - 1) player.index = 0;
    player.playing = true;
    this._render();
    this._updateFeedDom();
    this._feedPlayerTimer = window.setInterval(() => this._feedAdvance(), 400);
  }

  _feedAdvance() {
    const player = this._feedPlayer;
    if (!player.frames.length) {
      this._stopFeedPlayer();
      return;
    }
    if (player.index >= player.frames.length - 1) {
      this._stopFeedPlayer();
      this._render();
      return;
    }
    player.index += 1;
    this._updateFeedDom();
  }

  _feedSeek(value) {
    const player = this._feedPlayer;
    this._stopFeedPlayer();
    player.index = Math.max(0, Math.min(Math.round(value || 0), player.frames.length - 1));
    this._updateFeedDom();
    const btn = this.shadowRoot?.querySelector('[data-action="feed-play"]');
    if (btn) btn.textContent = "▶ Play";
  }

  _updateFeedDom() {
    const root = this.shadowRoot;
    if (!root) return;
    const player = this._feedPlayer;
    const frames = player.frames;
    if (!frames.length) return;
    const idx = Math.max(0, Math.min(player.index, frames.length - 1));
    const img = root.querySelector(".feed-frame");
    if (img) img.src = this._captureUrl(frames[idx].file);
    const counter = root.querySelector(".feed-counter");
    if (counter) counter.textContent = `${idx + 1} / ${frames.length}`;
    const scrubber = root.querySelector(".feed-scrubber");
    if (scrubber && document.activeElement !== scrubber) scrubber.value = String(idx);
    for (let i = idx + 1; i <= idx + 8 && i < frames.length; i += 1) {
      const preload = new Image();
      preload.src = this._captureUrl(frames[i].file);
    }
  }

  async _deleteFeedSession(id) {
    if (typeof window.confirm === "function" && !window.confirm("Delete this feed session? This can't be undone.")) {
      return;
    }
    this._error = "";
    try {
      await this._callWS({ type: "openreef/delete_feed_session", session_id: id });
      this._message = "Feed deleted";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not delete feed";
    }
    this._stopFeedPlayer();
    if (this._feedPlayer.sessionId === id) {
      this._feedPlayer.sessionId = "";
      this._feedPlayer.frames = [];
    }
    await this._loadFeedSessions();
  }

  _feedWatchSettings() {
    const fw = this._config.feedWatch || {};
    const cams = this._cameraList();
    const body = `
      <label class="toggle-card">
        <input type="checkbox" data-scope="feedwatch" data-field="enabled" ${fw.enabled ? "checked" : ""}>
        <span><strong>Watch every feeding</strong><small>When Feed mode runs, capture a snapshot burst across the whole feeding so you can scrub through and confirm every fish ate.</small></span>
      </label>
      ${cams.length ? "" : `<div class="notice warning-notice">Map a camera under <strong>Cameras</strong> first.</div>`}
      <p class="eyebrow">Camera</p>
      <label>Feed-watch camera
        <select data-scope="feedwatch" data-field="cameraId">
          <option value="" ${!fw.cameraId ? "selected" : ""}>First mapped camera</option>
          ${cams.map(([id, cam]) => `<option value="${this._escape(id)}" ${fw.cameraId === id ? "selected" : ""}>${this._escape(cam.label || id)}</option>`).join("")}
        </select>
      </label>
      <p class="eyebrow">Capture</p>
      <div class="grid two compact">
        <label>Frame every (s)
          <input type="number" min="3" max="60" step="1" data-scope="feedwatch" data-field="cadenceSeconds" value="${this._escape(fw.cadenceSeconds ?? 10)}">
        </label>
        <label>Keep last (feeds)
          <input type="number" min="1" max="200" step="1" data-scope="feedwatch" data-field="retentionSessions" value="${this._escape(fw.retentionSessions ?? 25)}">
        </label>
      </div>
      <p class="muted">Runs for the whole Feed-mode window (your feed timer), then stops. While on, it replaces the single Feed-mode clip in Auto-capture.</p>
    `;
    return this._settingsPanel(
      "feedwatch",
      "Feed-watch",
      "Record each feeding as a scrubbable session — confirm every fish came out and ate.",
      body,
    );
  }

  _cameraTarget(id, cam) {
    return {
      id,
      label: cam?.label || id,
      domains: ["camera"],
      keywords: [cam?.label || id, "camera", "cam", "tank", "reef"],
      prefer: ["reef", "tank", "aquarium", "display", "sump"],
      avoid: [],
      device_classes: [],
      units: [],
    };
  }

  _addCamera(label) {
    const base = this._slug(label || "Camera");
    let id = base;
    let suffix = 2;
    this._config.cameras = this._config.cameras || {};
    while (this._config.cameras[id]) { id = `${base}_${suffix}`; suffix += 1; }
    this._config.cameras[id] = { label: label || "Camera", entity_id: "" };
    this._setDirty(true);
    this._render();
  }

  _removeCamera(id) {
    if (this._config.cameras) delete this._config.cameras[id];
    this._setDirty(true);
    this._render();
  }

  _cameras() {
    const cams = this._cameraList();
    return `
      <section class="stack">
        <div class="section-head">
          <div>
            <h2>Cameras</h2>
            <p>Watch your tank live. Camera entities are mapped in Settings.</p>
          </div>
          <div class="actions">
            <button class="secondary compact-button" data-action="refresh-cameras">Refresh</button>
            <button class="secondary compact-button" data-action="tab" data-id="settings">Manage cameras</button>
          </div>
        </div>
        ${cams.length
          ? `<div class="cam-grid">${cams.map(([id, cam]) => this._cameraTile(id, cam)).join("")}</div>`
          : this._emptyState(
              "No cameras yet",
              "Add a camera in Settings. Set it up in Home Assistant first (Generic Camera, ONVIF, RTSP or go2rtc), then map its camera.* entity here.",
              "settings",
              "Add a camera",
            )}
      </section>
      ${this._timelapseSection()}
      ${this._feedWatchSection()}
      ${this._recordingsGallery()}
      ${this._cameraFocus ? this._cameraModal() : ""}
      ${this._recordingFocus ? this._recordingModal() : ""}
    `;
  }

  _cameraTile(id, cam) {
    const online = cam.entity_id && this._cameraOnline(cam.entity_id);
    const snap = online ? this._cameraSnapshotUrl(cam.entity_id) : "";
    return `
      <button class="cam-tile ${online ? "" : "offline"}" data-action="focus-camera" data-id="${this._escape(id)}" title="${this._escape(cam.label || id)}">
        ${online
          ? `<img class="cam-feed" src="${this._escape(snap)}" alt="${this._escape(cam.label || id)}" loading="lazy" decoding="async">`
          : `<div class="cam-placeholder"><span class="cam-glyph">📷</span><small>${cam.entity_id ? "Offline" : "Not mapped"}</small></div>`}
        ${online ? `<span class="cam-live"><span class="cam-dot"></span>ONLINE</span>` : ""}
        <span class="cam-label">${this._escape(cam.label || id)}</span>
      </button>
    `;
  }

  _cameraModal() {
    const cam = (this._config.cameras || {})[this._cameraFocus];
    if (!cam) return "";
    const online = cam.entity_id && this._cameraOnline(cam.entity_id);
    const snap = online ? this._cameraSnapshotUrl(cam.entity_id) : "";
    return `
      <div class="modal">
        <section class="wizard cam-dialog">
          <button class="close" data-action="close-camera">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Live camera</p>
              <h2>${this._escape(cam.label || this._cameraFocus)}</h2>
              <p class="muted">${this._escape(cam.entity_id || "Not mapped")}</p>
            </div>
          </div>
          <div class="cam-stage" data-camera-stage>
            ${online
              ? `<video class="cam-feed-large" data-camera-video poster="${this._escape(snap)}" autoplay muted playsinline></video><img class="cam-feed-large" data-camera-fallback alt="${this._escape(cam.label || "")}" style="display:none"><span class="cam-live"><span class="cam-dot"></span>LIVE</span>${online ? this._cameraOverlayMarkup() : ""}`
              : `<div class="cam-placeholder"><span class="cam-glyph">📷</span><small>${cam.entity_id ? "Camera offline or unavailable" : "Not mapped"}</small></div>`}
          </div>
          <div class="actions">
            ${online ? `<button class="secondary compact-button" data-action="snapshot-camera">Snapshot</button>` : ""}
            ${online ? `<button class="secondary compact-button" data-action="share-card">Share card</button>` : ""}
            ${online ? `<button class="secondary compact-button" data-action="fullscreen-camera">Fullscreen</button>` : ""}
            <button class="secondary compact-button" data-action="refresh-cameras">Refresh</button>
          </div>
        </section>
      </div>
    `;
  }

  _missionCameraCard() {
    const mapped = this._cameraList().filter(([, c]) => c.entity_id);
    if (!mapped.length) {
      return this._missionSummaryCard("Cameras", "0", "no cameras mapped yet", "unknown", "cameras");
    }
    const [id, cam] = mapped[0];
    const online = this._cameraOnline(cam.entity_id);
    const snap = online ? this._cameraSnapshotUrl(cam.entity_id) : "";
    const extra = mapped.length > 1 ? ` · +${mapped.length - 1} more` : "";
    return `
      <button class="summary-card cam-card" data-action="tab" data-id="cameras">
        <span>Live Camera</span>
        ${online
          ? `<img class="cam-card-img" src="${this._escape(snap)}" alt="${this._escape(cam.label || id)}">`
          : `<div class="cam-card-img cam-placeholder"><span class="cam-glyph">📷</span></div>`}
        <small>${this._escape(cam.label || id)}${extra}</small>
      </button>
    `;
  }

  _cameraSettings() {
    const cams = this._cameraList();
    const body = `
      <div class="quick-add">
        <input id="or-add-camera-name" placeholder="Camera name (e.g. Display Tank)">
        <button class="secondary compact-button" data-action="add-camera">Add camera</button>
      </div>
      ${cams.length
        ? cams.map(([id, cam]) => this._cameraPicker(id, cam)).join("")
        : `<p class="muted">No cameras yet. Add one above, then map its Home Assistant <code>camera.*</code> entity. You'll need the camera set up in Home Assistant first.</p>`}
    `;
    return this._settingsPanel(
      "cameras",
      "Cameras",
      "Map Home Assistant camera entities to watch your tank live on the Cameras tab.",
      body,
    );
  }

  _captureSettings() {
    const capture = this._config.capture || {};
    const triggers = capture.triggers || {};
    const cams = this._cameraList();
    const selected = Array.isArray(capture.cameraIds) ? capture.cameraIds : [];
    const triggerDefs = [
      ["criticalAlerts", "Critical alerts", "A sensor crosses into critical — temp, leak, water level, chemistry."],
      ["warningAlerts", "Warning alerts", "Also capture warning-level transitions, not just critical (more footage)."],
      ["modeChanges", "Mode changes", "When any mode is applied — feed, maintenance, water change, custom."],
      ["feedMode", "Feed mode", "Specifically when Feed mode starts — check everyone's eating."],
      ["skimmerAutoOff", "Skimmer safety auto-off", "When OpenReef turns a skimmer off because the return pump went off."],
      ["atoWindows", "ATO safety windows", "When the ATO duty-cycle safety window opens or closes."],
    ];
    const body = `
      <label class="toggle-card">
        <input type="checkbox" data-scope="capture" data-field="enabled" ${capture.enabled ? "checked" : ""}>
        <span>
          <strong>Auto-capture clips</strong>
          <small>Record a short clip (with a snapshot fallback) from a camera when the events you pick below happen.</small>
        </span>
      </label>
      ${cams.length ? "" : `<div class="notice warning-notice">Map a camera under <strong>Cameras</strong> first — auto-capture needs one to record.</div>`}
      <p class="eyebrow">Capture when…</p>
      <div class="grid two compact">
        ${triggerDefs.map(([field, title, desc]) => `
          <label class="toggle-card">
            <input type="checkbox" data-scope="capture-trigger" data-field="${field}" ${triggers[field] ? "checked" : ""}>
            <span><strong>${this._escape(title)}</strong><small>${this._escape(desc)}</small></span>
          </label>
        `).join("")}
      </div>
      <p class="eyebrow">Cameras to capture</p>
      ${cams.length
        ? `<div class="grid two compact">${cams.map(([id, cam]) => `
            <label class="toggle-card">
              <input type="checkbox" data-scope="capture-cameras" data-id="${this._escape(id)}" ${selected.includes(id) ? "checked" : ""}>
              <span><strong>${this._escape(cam.label || id)}</strong><small>${this._escape(cam.entity_id || "Not mapped")}</small></span>
            </label>
          `).join("")}</div>
          <p class="muted">Leave all unticked to use the first mapped camera.</p>`
        : `<p class="muted">No cameras mapped yet.</p>`}
      <p class="eyebrow">Clip &amp; retention</p>
      <div class="grid four compact">
        <label>Clip length (s)
          <input type="number" min="3" max="60" step="1" data-scope="capture" data-field="durationSeconds" value="${this._escape(capture.durationSeconds ?? 12)}">
        </label>
        <label>Pre-roll (s)
          <input type="number" min="0" max="30" step="1" data-scope="capture" data-field="lookbackSeconds" value="${this._escape(capture.lookbackSeconds ?? 0)}">
        </label>
        <label>Keep last
          <input type="number" min="1" max="50" step="1" data-scope="capture" data-field="retention" value="${this._escape(capture.retention ?? 10)}">
        </label>
        <label>Cooldown (s)
          <input type="number" min="0" max="600" step="5" data-scope="capture" data-field="cooldownSeconds" value="${this._escape(capture.cooldownSeconds ?? 20)}">
        </label>
      </div>
      <p class="muted">Pre-roll needs the camera's stream kept warm; leave it at 0 if clips come out empty. Cooldown stops a flapping sensor spamming clips.</p>
      <div class="actions">
        <button class="secondary compact-button" data-action="capture-now" ${cams.length ? "" : "disabled"}>Capture now</button>
      </div>
    `;
    return this._settingsPanel(
      "capture",
      "Auto-capture",
      "Record a clip from a camera when key OpenReef events fire. Keeps the last N, prunes the rest.",
      body,
    );
  }

  _cameraPicker(id, cam) {
    const key = `camera:${id}`;
    const result = this._searchResults[key];
    const online = cam.entity_id && this._cameraOnline(cam.entity_id);
    return `
      <section class="picker mapping-card">
        <div class="mapping-head">
          <div><p class="eyebrow">Camera</p><h3>${this._escape(cam.label || id)}</h3></div>
          <button class="secondary compact-button" data-action="remove-camera" data-id="${this._escape(id)}">Remove</button>
        </div>
        <label>Name<input data-scope="camera" data-id="${this._escape(id)}" data-field="label" value="${this._escape(cam.label || "")}" placeholder="Display Tank"></label>
        <label>Entity<input data-scope="camera" data-id="${this._escape(id)}" data-field="entity_id" value="${this._escape(cam.entity_id || "")}" placeholder="camera.reef_display"></label>
        ${cam.entity_id ? `
          <div class="selected-entity">
            <span>${this._escape(this._friendlyEntityName(cam.entity_id))} · ${online ? "Live" : "Offline or missing"}</span>
            <button class="secondary compact-button" data-action="clear-camera" data-id="${this._escape(id)}">Clear</button>
          </div>
        ` : ""}
        <button class="secondary" data-action="search-camera" data-id="${this._escape(id)}">${result?.loading ? "Finding..." : "Find matches"}</button>
        ${this._candidateList(key, "choose-camera", id)}
      </section>
    `;
  }

  // --- Timelapse (Phase B): scheduled frames + in-panel slideshow ---------

  _stopTimelapse() {
    if (this._timelapseTimer) {
      window.clearInterval(this._timelapseTimer);
      this._timelapseTimer = null;
    }
    if (this._timelapse) this._timelapse.playing = false;
  }

  async _loadTimelapseFrames() {
    const state = this._timelapse;
    state.loading = true;
    state.error = "";
    try {
      const tl = this._config.timelapse || {};
      const payload = { type: "openreef/list_timelapse_frames" };
      if (tl.cameraId) payload.camera_id = tl.cameraId;
      const result = await this._callWS(payload);
      state.frames = Array.isArray(result.frames) ? result.frames : [];
      state.windowMid = Number(result.windowMidMinutes) || 0;
      state.cameraId = result.cameraId || "";
      state.cameraLabel = result.cameraLabel || "";
      state.index = Math.max(0, this._timelapseViewFrames().length - 1);
    } catch (err) {
      state.error = err instanceof Error ? err.message : "Could not load timelapse";
      state.frames = [];
    } finally {
      state.loaded = true;
      state.loading = false;
      if (this._activeTab === "cameras") this._render();
    }
  }

  _timelapseViewFrames() {
    const state = this._timelapse;
    const frames = Array.isArray(state.frames) ? state.frames : [];
    if (state.mode !== "daily") return frames;
    return this._timelapseDailyFrames(frames, state.windowMid || 0);
  }

  // One frame per calendar day — the one closest to the daylight-window midpoint.
  _timelapseDailyFrames(frames, windowMid) {
    const byDay = new Map();
    for (const frame of frames) {
      const date = new Date(frame.ts);
      if (Number.isNaN(date.getTime())) continue;
      const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
      const dist = Math.abs(date.getHours() * 60 + date.getMinutes() - windowMid);
      const current = byDay.get(key);
      if (!current || dist < current.dist) byDay.set(key, { frame, dist });
    }
    return [...byDay.values()]
      .map((entry) => entry.frame)
      .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  }

  _formatTimelapseStamp(ts) {
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return ts || "";
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  _timelapseSection() {
    const tl = this._config.timelapse || {};
    const hasCamera = this._cameraList().some(([, cam]) => cam.entity_id);
    const state = this._timelapse;
    if (!state.loaded && !state.loading) this._loadTimelapseFrames();
    const frames = state.frames;
    const header = `
      <div class="section-head">
        <div>
          <h2>Timelapse</h2>
          <p>Replay a day's light cycle, or watch coral grow over months. Frames are captured automatically during your daylight window.</p>
        </div>
        <div class="actions">
          <button class="secondary compact-button" data-action="timelapse-grab" ${hasCamera ? "" : "disabled"}>Grab frame now</button>
          <button class="secondary compact-button" data-action="timelapse-reload">Reload</button>
          <button class="secondary compact-button" data-action="tab" data-id="settings">Settings</button>
        </div>
      </div>`;
    let body;
    if (state.loading && !frames.length) {
      body = `<div class="muted">Loading timelapse…</div>`;
    } else if (state.error && !frames.length) {
      body = `<div class="notice warning-notice">${this._escape(state.error)}</div>`;
    } else if (!frames.length) {
      body = this._emptyState(
        tl.enabled ? "No frames yet" : "Timelapse is off",
        tl.enabled
          ? "Frames are captured on a schedule during your daylight window. Hit Grab frame now to seed one."
          : "Turn on Timelapse in Settings and OpenReef will quietly build a reef timelapse you can scrub through.",
        "settings",
        tl.enabled ? "Open settings" : "Turn on timelapse",
      );
    } else {
      body = this._timelapsePlayer();
    }
    return `<section class="stack timelapse-section">${header}${body}</section>`;
  }

  _timelapsePlayer() {
    const state = this._timelapse;
    const view = this._timelapseViewFrames();
    if (!view.length) return `<div class="muted">No frames in this view.</div>`;
    const idx = Math.max(0, Math.min(state.index, view.length - 1));
    const frame = view[idx];
    const speeds = [0.5, 1, 2, 4];
    return `
      <div class="cam-stage timelapse-stage">
        <img class="cam-feed-large timelapse-frame" src="${this._escape(this._captureUrl(frame.file))}" alt="Timelapse frame">
        <span class="timelapse-stamp">${this._escape(this._formatTimelapseStamp(frame.ts))}</span>
      </div>
      <div class="timelapse-controls">
        <button class="secondary compact-button" data-action="timelapse-play">${state.playing ? "⏸ Pause" : "▶ Play"}</button>
        <input type="range" class="timelapse-scrubber" min="0" max="${view.length - 1}" value="${idx}" data-action="timelapse-seek">
        <span class="timelapse-counter">${idx + 1} / ${view.length}</span>
        <label class="timelapse-speed">Speed
          <select data-action="timelapse-speed">
            ${speeds.map((s) => `<option value="${s}" ${state.speed === s ? "selected" : ""}>${s}×</option>`).join("")}
          </select>
        </label>
        <span class="seg">
          <button class="secondary compact-button ${state.mode === "all" ? "active" : ""}" data-action="timelapse-mode" data-id="all">Full day</button>
          <button class="secondary compact-button ${state.mode === "daily" ? "active" : ""}" data-action="timelapse-mode" data-id="daily">Growth</button>
        </span>
      </div>
      <p class="muted">Full day replays every frame (a day's light cycle); Growth shows one frame per day (watch it grow).</p>
    `;
  }

  _updateTimelapseDom() {
    const root = this.shadowRoot;
    if (!root) return;
    const state = this._timelapse;
    const view = this._timelapseViewFrames();
    const idx = Math.max(0, Math.min(state.index, view.length - 1));
    const frame = view[idx];
    if (!frame) return;
    const img = root.querySelector(".timelapse-frame");
    if (img) img.src = this._captureUrl(frame.file);
    const stamp = root.querySelector(".timelapse-stamp");
    if (stamp) stamp.textContent = this._formatTimelapseStamp(frame.ts);
    const scrubber = root.querySelector(".timelapse-scrubber");
    if (scrubber && document.activeElement !== scrubber) scrubber.value = String(idx);
    const counter = root.querySelector(".timelapse-counter");
    if (counter) counter.textContent = `${idx + 1} / ${view.length}`;
    // Rolling preload so the next frames are warm in cache (no flicker).
    for (let i = idx + 1; i <= idx + 12 && i < view.length; i += 1) {
      const preload = new Image();
      preload.src = this._captureUrl(view[i].file);
    }
  }

  _timelapseInterval() {
    return Math.max(80, Math.round(500 / (this._timelapse.speed || 1)));
  }

  _timelapseTogglePlay() {
    const state = this._timelapse;
    if (state.playing) {
      this._stopTimelapse();
      this._render();
      return;
    }
    const view = this._timelapseViewFrames();
    if (view.length < 2) return;
    if (state.index >= view.length - 1) state.index = 0;
    state.playing = true;
    this._render();
    this._updateTimelapseDom();
    this._timelapseTimer = window.setInterval(() => this._timelapseAdvance(), this._timelapseInterval());
  }

  _timelapseAdvance() {
    const state = this._timelapse;
    const view = this._timelapseViewFrames();
    if (!view.length) {
      this._stopTimelapse();
      return;
    }
    if (state.index >= view.length - 1) {
      this._stopTimelapse();
      this._render();
      return;
    }
    state.index += 1;
    this._updateTimelapseDom();
  }

  _timelapseSeek(value) {
    const state = this._timelapse;
    this._stopTimelapse();
    state.index = Math.max(0, Math.min(Math.round(value || 0), this._timelapseViewFrames().length - 1));
    this._updateTimelapseDom();
    const btn = this.shadowRoot?.querySelector('[data-action="timelapse-play"]');
    if (btn) btn.textContent = "▶ Play";
  }

  _timelapseSetSpeed(value) {
    const state = this._timelapse;
    state.speed = value || 1;
    if (state.playing && this._timelapseTimer) {
      window.clearInterval(this._timelapseTimer);
      this._timelapseTimer = window.setInterval(() => this._timelapseAdvance(), this._timelapseInterval());
    }
  }

  _timelapseSetMode(mode) {
    if (mode !== "all" && mode !== "daily") return;
    const state = this._timelapse;
    this._stopTimelapse();
    state.mode = mode;
    state.index = Math.max(0, this._timelapseViewFrames().length - 1);
    this._render();
  }

  async _timelapseGrab() {
    this._error = "";
    try {
      if (this._configDirty) await this._persistConfigSilently();
      await this._callWS({ type: "openreef/capture_timelapse_frame" });
      this._message = "Timelapse frame captured";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not capture a frame — check a camera is mapped and online";
    }
    await this._loadTimelapseFrames();
  }

  async _timelapseClear() {
    if (typeof window.confirm === "function" && !window.confirm("Delete ALL timelapse frames for this camera? This can't be undone.")) {
      return;
    }
    this._error = "";
    try {
      await this._callWS({ type: "openreef/clear_timelapse" });
      this._message = "Timelapse cleared";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not clear timelapse";
    }
    this._stopTimelapse();
    this._timelapse.index = 0;
    await this._loadTimelapseFrames();
  }

  _timelapseSettings() {
    const tl = this._config.timelapse || {};
    const retention = tl.retention || {};
    const cams = this._cameraList();
    const body = `
      <label class="toggle-card">
        <input type="checkbox" data-scope="timelapse" data-field="enabled" ${tl.enabled ? "checked" : ""}>
        <span><strong>Build a reef timelapse</strong><small>Snap a frame on a schedule during your daylight window, then play it back in the Cameras tab.</small></span>
      </label>
      ${cams.length ? "" : `<div class="notice warning-notice">Map a camera under <strong>Cameras</strong> first — timelapse needs one to capture.</div>`}
      <p class="eyebrow">Camera</p>
      <label>Timelapse camera
        <select data-scope="timelapse" data-field="cameraId">
          <option value="" ${!tl.cameraId ? "selected" : ""}>First mapped camera</option>
          ${cams.map(([id, cam]) => `<option value="${this._escape(id)}" ${tl.cameraId === id ? "selected" : ""}>${this._escape(cam.label || id)}</option>`).join("")}
        </select>
      </label>
      <p class="eyebrow">Cadence &amp; daylight window</p>
      <div class="grid three compact">
        <label>Every (min)
          <input type="number" min="5" max="1440" step="5" data-scope="timelapse" data-field="cadenceMinutes" value="${this._escape(tl.cadenceMinutes ?? 30)}">
        </label>
        <label>From
          <input type="time" data-scope="timelapse" data-field="windowStart" value="${this._escape(tl.windowStart || "08:00")}">
        </label>
        <label>To
          <input type="time" data-scope="timelapse" data-field="windowEnd" value="${this._escape(tl.windowEnd || "22:00")}">
        </label>
      </div>
      <p class="muted">Frames are only captured inside this window, so the timelapse skips the dark lights-off hours.</p>
      <p class="eyebrow">Retention — tiered downsampling</p>
      <div class="grid four compact">
        <label>Every frame for (days)
          <input type="number" min="0" max="3650" step="1" data-scope="timelapse-retention" data-field="detailDays" value="${this._escape(retention.detailDays ?? 14)}">
        </label>
        <label>Then 1/day until (days)
          <input type="number" min="0" max="3650" step="1" data-scope="timelapse-retention" data-field="dailyUntilDays" value="${this._escape(retention.dailyUntilDays ?? 90)}">
        </label>
        <label>Then 1/week until (days)
          <input type="number" min="0" max="3650" step="1" data-scope="timelapse-retention" data-field="weeklyUntilDays" value="${this._escape(retention.weeklyUntilDays ?? 365)}">
        </label>
        <label>Then 1/month until (days, 0=∞)
          <input type="number" min="0" max="3650" step="1" data-scope="timelapse-retention" data-field="monthlyUntilDays" value="${this._escape(retention.monthlyUntilDays ?? 0)}">
        </label>
      </div>
      <p class="muted">Recent frames stay detailed for day-cycle replay; older days thin to 1/day, then 1/week, then 1/month — so years of growth fit in a few hundred frames.</p>
      <div class="actions">
        <button class="secondary compact-button" data-action="timelapse-grab" ${cams.length ? "" : "disabled"}>Grab a frame now</button>
        <button class="secondary compact-button danger-button" data-action="timelapse-clear">Clear timelapse</button>
      </div>
    `;
    return this._settingsPanel(
      "timelapse",
      "Reef timelapse",
      "Scheduled snapshots played back as a slideshow. Tiered retention keeps months of growth in a few hundred frames.",
      body,
    );
  }

  // --- Recordings (event-triggered capture) ------------------------------

  _captureUrl(name) {
    return name ? `/openreef_captures/${name}` : "";
  }

  _recordingsList() {
    const list = this._config?.captures;
    return Array.isArray(list) ? list.filter((rec) => rec && typeof rec === "object") : [];
  }

  async _captureNow() {
    this._busy = true;
    this._message = "";
    this._error = "";
    this._render();
    try {
      if (this._configDirty) await this._persistConfigSilently();
      const result = await this._callWS({ type: "openreef/capture_now" });
      this._config = result.config || this._config;
      const status = result.record?.status || "capture";
      this._recordActivity(`Manual ${status} captured`, "control");
      this._message = `Captured ${status} from ${result.record?.cameraLabel || "camera"}`;
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not capture — check a camera is mapped and online";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _deleteRecording(id) {
    this._busy = true;
    this._error = "";
    this._render();
    try {
      const result = await this._callWS({ type: "openreef/delete_recording", recording_id: id });
      this._config = result.config || this._config;
      if (this._recordingFocus === id) this._recordingFocus = null;
      this._message = "Recording deleted";
    } catch (err) {
      this._error = err instanceof Error ? err.message : "Could not delete recording";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _recordingsGallery() {
    const recs = this._recordingsList();
    const hasCamera = this._cameraList().some(([, c]) => c.entity_id);
    return `
      <section class="stack recordings-section">
        <div class="section-head">
          <div>
            <h2>Recordings</h2>
            <p>Clips OpenReef grabbed automatically when something happened — plus anything you capture by hand.</p>
          </div>
          <div class="actions">
            <button class="secondary compact-button" data-action="capture-now" ${hasCamera ? "" : "disabled"}>Capture now</button>
            <button class="secondary compact-button" data-action="tab" data-id="settings">Auto-capture</button>
          </div>
        </div>
        ${recs.length
          ? `<div class="cam-grid recordings-grid">${recs.map((rec) => this._recordingCard(rec)).join("")}</div>`
          : this._emptyState(
              "No recordings yet",
              hasCamera
                ? "Turn on Auto-capture in Settings and OpenReef records a clip when an alert fires — or hit Capture now."
                : "Map a camera in Settings first, then switch on Auto-capture so OpenReef can record when something happens.",
              "settings",
              "Set up auto-capture",
            )}
      </section>
    `;
  }

  _recordingCard(rec) {
    const thumb = this._captureUrl(rec.thumbnail);
    const status = rec.status || "snapshot";
    const pill = status === "clip" ? "ok" : status === "failed" ? "critical" : "unknown";
    const playable = Boolean(rec.video || rec.thumbnail);
    return `
      <div class="cam-tile recording-tile">
        <button class="recording-open" data-action="open-recording" data-id="${this._escape(rec.id)}" title="${this._escape(rec.label || "Recording")}" ${playable ? "" : "disabled"}>
          ${thumb
            ? `<img class="cam-feed" src="${this._escape(thumb)}" alt="${this._escape(rec.label || "Recording")}">`
            : `<div class="cam-placeholder"><span class="cam-glyph">🎞️</span><small>${status === "failed" ? "Capture failed" : "No preview"}</small></div>`}
          ${rec.video ? `<span class="cam-live play-badge">▶ CLIP</span>` : ""}
          <span class="cam-label">${this._escape(rec.label || "Event")}</span>
        </button>
        <div class="recording-meta">
          <span class="pill ${pill}">${this._escape(status)}</span>
          <span class="recording-time">${this._escape(this._formatActivityTime(rec.timestamp))}</span>
          <button class="secondary compact-button danger-button" data-action="delete-recording" data-id="${this._escape(rec.id)}">Delete</button>
        </div>
      </div>
    `;
  }

  _recordingModal() {
    const rec = this._recordingsList().find((item) => item.id === this._recordingFocus);
    if (!rec) return "";
    const video = this._captureUrl(rec.video);
    const thumb = this._captureUrl(rec.thumbnail);
    return `
      <div class="modal">
        <section class="wizard cam-dialog">
          <button class="close" data-action="close-recording">x</button>
          <div class="section-head">
            <div>
              <p class="eyebrow">Recording · ${this._escape(rec.cameraLabel || rec.cameraId || "Camera")}</p>
              <h2>${this._escape(rec.label || "Event")}</h2>
              <p class="muted">${this._escape(this._formatActivityTime(rec.timestamp))}</p>
            </div>
          </div>
          <div class="cam-stage">
            ${video
              ? `<video class="cam-feed-large" src="${this._escape(video)}" poster="${this._escape(thumb)}" controls autoplay playsinline></video>`
              : thumb
                ? `<img class="cam-feed-large" src="${this._escape(thumb)}" alt="${this._escape(rec.label || "")}">`
                : `<div class="cam-placeholder"><span class="cam-glyph">🎞️</span><small>No media for this capture</small></div>`}
          </div>
          <div class="actions">
            ${video ? `<a class="secondary compact-button" href="${this._escape(video)}" target="_blank" rel="noopener noreferrer">Open clip</a>` : ""}
            ${thumb ? `<a class="secondary compact-button" href="${this._escape(thumb)}" target="_blank" rel="noopener noreferrer">Snapshot</a>` : ""}
            <button class="secondary compact-button danger-button" data-action="delete-recording" data-id="${this._escape(rec.id)}">Delete</button>
          </div>
        </section>
      </div>
    `;
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
      cards.cameras ? this._missionCameraCard() : "",
      cards.maintenance ? this._missionMaintenanceCard() : "",
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
    if (this._maintenanceConfig().enabled) {
      this._maintenanceTaskList()
        .filter(([id]) => this._maintenanceTask(id).enabled)
        .forEach(([id]) => {
          const state = this._maintenanceDueState(id);
          const task = this._maintenanceTask(id);
          if (state.status === "critical") issues.push(["critical", `${task.label} overdue`, state.detail, "maintenance"]);
          else if (state.status === "warning") issues.push(["warning", `${task.label} due`, state.detail, "maintenance"]);
        });
    }
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
        ${this._guideSettings()}
        ${this._missionSettings()}
        ${this._sensorSettings()}
        ${this._manualTestSettings()}
        ${this._maintenanceSettings()}
        ${this._dosingSettings()}
        ${this._equipmentSettings()}
        ${this._cameraSettings()}
        ${this._captureSettings()}
        ${this._timelapseSettings()}
        ${this._overlaySettings()}
        ${this._feedWatchSettings()}
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

  // --- Maintenance Tasks V1 (mirrors Manual Tests; HA-native, no Google) ----

  _maintenanceConfig() {
    this._config.maintenance = this._config.maintenance || { enabled: true, tasks: {}, completions: {} };
    this._config.maintenance.tasks = this._config.maintenance.tasks || {};
    this._config.maintenance.completions = this._config.maintenance.completions || {};
    return this._config.maintenance;
  }

  _maintenanceTaskList() {
    return Object.entries(this._maintenanceConfig().tasks || {});
  }

  _maintenanceTask(id) {
    const raw = this._maintenanceConfig().tasks[id] || {};
    const cadenceDays = Math.max(1, Math.min(365, Number(raw.cadenceDays) || 7));
    const criticalAfterDays = Math.max(cadenceDays, Math.min(730, Number(raw.criticalAfterDays) || cadenceDays * 2));
    const toIntList = (v, lo, hi) => (Array.isArray(v)
      ? [...new Set(v.map((n) => parseInt(n, 10)).filter((n) => Number.isInteger(n) && n >= lo && n <= hi))].sort((a, b) => a - b)
      : []);
    return {
      label: raw.label || id,
      cadenceDays,
      criticalAfterDays,
      enabled: raw.enabled === true,
      notes: raw.notes || "",
      builtin: raw.builtin === true,
      scheduleMode: raw.scheduleMode === "fixed" ? "fixed" : "interval",
      scheduleDays: toIntList(raw.scheduleDays, 0, 6),
      scheduleMonthDays: toIntList(raw.scheduleMonthDays, 1, 31),
      notify: raw.notify !== false,
      snoozedUntil: typeof raw.snoozedUntil === "string" ? raw.snoozedUntil : null,
      logsVolume: raw.logsVolume === true,
    };
  }

  _maintenanceCompletions(id) {
    const list = this._maintenanceConfig().completions?.[id];
    if (!Array.isArray(list)) return [];
    return [...list].sort((a, b) => this._maintenanceCompletionTime(b) - this._maintenanceCompletionTime(a));
  }

  _maintenanceCompletionTime(entry) {
    const time = Date.parse(entry?.timestamp || entry?.date || "");
    return Number.isFinite(time) ? time : 0;
  }

  _maintenanceLatestCompletion(id) {
    return this._maintenanceCompletions(id)[0] || null;
  }

  // Latest NON-skipped completion — skips are logged history but don't count as
  // "done", so they never reset the cadence (lockstep with backend _maintenance_last_done).
  _maintenanceLatestDone(id) {
    return this._maintenanceCompletions(id).find((entry) => !entry?.skipped) || null;
  }

  _maintenanceOrdinal(n) {
    const s = ["th", "st", "nd", "rd"];
    const v = n % 100;
    return s[(v - 20) % 10] || s[v] || s[0];
  }

  _maintenanceFormatDate(date) {
    try {
      return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    } catch {
      return date.toISOString().slice(0, 10);
    }
  }

  _maintenanceScheduleLabel(task) {
    const dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const parts = [];
    if (task.scheduleDays?.length) parts.push(task.scheduleDays.map((d) => dow[d] || "?").join("/"));
    if (task.scheduleMonthDays?.length) parts.push(task.scheduleMonthDays.map((d) => `${d}${this._maintenanceOrdinal(d)}`).join("/"));
    return parts.join(" + ") || "no days set";
  }

  // Most recent (and previous) scheduled local date <= today, for fixed-schedule tasks.
  // Weekdays stored Mon=0..Sun=6 (matches backend date.weekday()); JS getDay() is Sun=0.
  _maintenanceScheduledDates(task, today) {
    const days = new Set(task.scheduleDays || []);
    const monthDays = new Set(task.scheduleMonthDays || []);
    if (!days.size && !monthDays.size) return [null, null];
    const found = [];
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    for (let i = 0; i < 366; i += 1) {
      const isoDow = (d.getDay() + 6) % 7;
      if (days.has(isoDow) || monthDays.has(d.getDate())) {
        found.push(new Date(d));
        if (found.length === 2) break;
      }
      d.setDate(d.getDate() - 1);
    }
    return [found[0] || null, found[1] || null];
  }

  _maintenanceNextScheduledAfter(task, fromDate) {
    const days = new Set(task.scheduleDays || []);
    const monthDays = new Set(task.scheduleMonthDays || []);
    if (!days.size && !monthDays.size) return null;
    const d = new Date(fromDate.getFullYear(), fromDate.getMonth(), fromDate.getDate() + 1);
    for (let i = 0; i < 366; i += 1) {
      const isoDow = (d.getDay() + 6) % 7;
      if (days.has(isoDow) || monthDays.has(d.getDate())) return new Date(d);
      d.setDate(d.getDate() + 1);
    }
    return null;
  }

  // When this task next becomes due (ms). Already-due tasks return now so they sort first.
  _maintenanceNextDueMs(id) {
    const state = this._maintenanceDueState(id);
    if (state.status === "warning" || state.status === "critical") return Date.now();
    const task = this._maintenanceTask(id);
    const snoozeMs = Date.parse(task.snoozedUntil || "");
    let baseMs;
    if (task.scheduleMode === "fixed") {
      const next = this._maintenanceNextScheduledAfter(task, new Date());
      baseMs = next ? next.getTime() : Number.POSITIVE_INFINITY;
    } else {
      const latest = this._maintenanceLatestDone(id);
      const lastMs = latest ? this._maintenanceCompletionTime(latest) : Date.now();
      baseMs = lastMs + task.cadenceDays * 86400000;
    }
    return Number.isFinite(snoozeMs) && snoozeMs > baseMs ? snoozeMs : baseMs;
  }

  _maintenanceUpcoming(days = 7) {
    const horizon = Date.now() + days * 86400000;
    return this._maintenanceTaskList()
      .filter(([id]) => this._maintenanceTask(id).enabled)
      .map(([id]) => ({ id, task: this._maintenanceTask(id), state: this._maintenanceDueState(id), nextMs: this._maintenanceNextDueMs(id) }))
      .filter((x) => x.state.status !== "unknown" && Number.isFinite(x.nextMs) && x.nextMs <= horizon)
      .sort((a, b) => a.nextMs - b.nextMs);
  }

  _maintenanceAgeDays(entry) {
    const time = this._maintenanceCompletionTime(entry);
    if (!time) return Number.POSITIVE_INFINITY;
    return Math.max(0, (Date.now() - time) / 86400000);
  }

  _maintenanceDueState(id) {
    const task = this._maintenanceTask(id);
    const latest = this._maintenanceLatestDone(id);
    if (!this._maintenanceConfig().enabled || !task.enabled) {
      return { status: "unknown", label: "not tracked", detail: "This task isn't being tracked.", latest };
    }
    const snoozeMs = Date.parse(task.snoozedUntil || "");
    if (Number.isFinite(snoozeMs) && snoozeMs > Date.now()) {
      return { status: "ok", label: "snoozed", detail: `Snoozed until ${this._formatActivityTime(task.snoozedUntil)}.`, latest, snoozed: true };
    }
    if (task.scheduleMode === "fixed") {
      const [lastSched, prevSched] = this._maintenanceScheduledDates(task, new Date());
      const dayLabel = this._maintenanceScheduleLabel(task);
      if (!lastSched) {
        return { status: "unknown", label: "no schedule", detail: "Pick the day(s) this task runs in Settings → Maintenance.", latest };
      }
      const doneMs = latest ? this._maintenanceCompletionTime(latest) : 0;
      if (doneMs >= lastSched.getTime()) {
        return { status: "ok", label: "done", detail: `${task.label} done for ${this._maintenanceFormatDate(lastSched)} (${dayLabel}).`, latest };
      }
      if (prevSched && doneMs < prevSched.getTime()) {
        return { status: "critical", label: "overdue", detail: `${task.label} missed ${this._maintenanceFormatDate(prevSched)}; due again ${this._maintenanceFormatDate(lastSched)} (${dayLabel}).`, latest };
      }
      return { status: "warning", label: "due", detail: `${task.label} is due for ${this._maintenanceFormatDate(lastSched)} (${dayLabel}).`, latest };
    }
    if (!latest) {
      return { status: "warning", label: "never done", detail: `${task.label} is on a ${task.cadenceDays}-day cadence but hasn't been logged yet.`, latest };
    }
    const age = this._maintenanceAgeDays(latest);
    if (age > task.criticalAfterDays) {
      return { status: "critical", label: "overdue", detail: `${task.label} last done ${this._format(age, 0)} days ago; overdue past ${task.criticalAfterDays} days.`, latest };
    }
    if (age > task.cadenceDays) {
      return { status: "warning", label: "due", detail: `${task.label} is due. Last done ${this._format(age, 0)} days ago; every ${task.cadenceDays} days.`, latest };
    }
    return { status: "ok", label: "done", detail: `${task.label} done ${this._format(age, age < 2 ? 1 : 0)} days ago; every ${task.cadenceDays} days.`, latest };
  }

  // Overdue/due chores nudge Reef Health via the weighted "maintenance" category —
  // modest points (less than chemistry) so a missed glass-clean can't tank the score.
  _maintenanceFreshnessItems() {
    if (!this._maintenanceConfig().enabled) return [];
    return this._maintenanceTaskList()
      .filter(([id]) => this._maintenanceTask(id).enabled)
      .map(([id]) => {
        const task = this._maintenanceTask(id);
        const state = this._maintenanceDueState(id);
        const points = state.status === "critical" ? 6 : state.status === "warning" ? 2 : 0;
        return {
          id: `maintenance:${id}`,
          label: `${task.label} ${state.label}`,
          detail: state.detail,
          status: state.status,
          category: "maintenance",
          points,
          affectsScore: points > 0,
        };
      });
  }

  _maintenanceDueStates() {
    return this._maintenanceTaskList()
      .filter(([id]) => this._maintenanceTask(id).enabled)
      .map(([id]) => this._maintenanceDueState(id).status);
  }

  _maintenanceDueCount() {
    return this._maintenanceDueStates().filter((s) => s === "warning" || s === "critical").length;
  }

  _maintenanceOverdueCount() {
    return this._maintenanceDueStates().filter((s) => s === "critical").length;
  }

  _missionMaintenanceCard() {
    const due = this._maintenanceDueCount();
    const overdue = this._maintenanceOverdueCount();
    return this._missionSummaryCard(
      "Maintenance",
      due ? `${due} due` : "All done",
      overdue ? `${overdue} overdue` : due ? "tasks need doing" : "maintenance is current",
      overdue ? "critical" : due ? "warning" : "ok",
      "maintenance",
    );
  }

  _maintenance() {
    const enabledTasks = this._maintenanceTaskList().filter(([id]) => this._maintenanceTask(id).enabled);
    const due = this._maintenanceDueCount();
    const overdue = this._maintenanceOverdueCount();
    return `
      <section class="stack">
        <div class="section-head">
          <div>
            <h2>Maintenance</h2>
            <p>Your recurring reef chores — tick them off and OpenReef tracks what's due.</p>
          </div>
          <div class="button-row">
            <button class="secondary" data-action="tab" data-id="settings">Edit tasks</button>
          </div>
        </div>
        <div class="summary-grid">
          ${this._missionSummaryCard("Tracked", String(enabledTasks.length), "tasks on a schedule", enabledTasks.length ? "ok" : "unknown", "settings")}
          ${this._missionSummaryCard("Due now", String(due), due ? "need doing soon" : "all caught up", due ? (overdue ? "critical" : "warning") : "ok", "maintenance")}
          ${this._missionSummaryCard("Overdue", String(overdue), overdue ? "past their window" : "none overdue", overdue ? "critical" : "ok", "maintenance")}
        </div>
        ${this._maintenanceUpcomingSection()}
        ${enabledTasks.length
          ? `<div class="grid four">${enabledTasks.map(([id]) => this._maintenanceTaskCard(id)).join("")}</div>`
          : this._emptyState("No tasks tracked yet", "Turn on the chores you do in Settings → Maintenance — or add your own.", "settings", "Set up tasks")}
      </section>
    `;
  }

  _maintenanceUpcomingSection() {
    const upcoming = this._maintenanceUpcoming(7);
    if (!upcoming.length) return "";
    const rows = upcoming.map(({ task, state, nextMs }) => {
      const dueNow = state.status === "warning" || state.status === "critical";
      const days = Math.max(0, Math.round((nextMs - Date.now()) / 86400000));
      const when = dueNow
        ? (state.status === "critical" ? "overdue" : "due now")
        : (days <= 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`);
      return `
        <div class="manual-history-row">
          <div><strong>${this._escape(task.label)}</strong></div>
          <span class="pill ${state.status}">${this._escape(when)}</span>
        </div>`;
    }).join("");
    return `
      <section class="setting-card subtle-card">
        <div class="section-head"><div><p class="eyebrow">Coming up</p><h3>Due this week</h3></div></div>
        <div class="manual-history">${rows}</div>
      </section>`;
  }

  _maintenanceTaskCard(id) {
    const task = this._maintenanceTask(id);
    const state = this._maintenanceDueState(id);
    const latest = state.latest;
    const completions = this._maintenanceCompletions(id);
    const open = this._maintenanceHistoryOpen[id] === true;
    const due = state.status === "warning" || state.status === "critical";
    const snoozed = state.snoozed === true;
    const scheduleLine = task.scheduleMode === "fixed"
      ? `Every ${this._escape(this._maintenanceScheduleLabel(task))}`
      : `Every ${this._escape(task.cadenceDays)} day${task.cadenceDays === 1 ? "" : "s"}`;
    return `
      <article class="manual-test-card ${state.status}">
        <div class="card-head">
          <div>
            <h3>${this._escape(task.label)}</h3>
            <p>${scheduleLine}</p>
          </div>
          <span class="pill ${state.status}">${this._escape(state.label)}</span>
        </div>
        <small>${this._escape(latest ? `Last done ${this._formatActivityTime(latest.timestamp)}` : "Never logged")}</small>
        <p>${this._escape(state.detail)}</p>
        ${task.logsVolume ? `
          <div class="mini-grid">
            <label>Volume logged<input id="or-vol-${this._escape(id)}" type="number" min="0" step="1" placeholder="optional"></label>
            <label>Unit<select id="or-volunit-${this._escape(id)}"><option value="pct">%</option><option value="L">litres</option></select></label>
          </div>
        ` : ""}
        <div class="button-row">
          <button class="primary compact-button" data-action="complete-task" data-id="${this._escape(id)}">Mark done</button>
          ${due ? `
            <button class="secondary compact-button" data-action="skip-task" data-id="${this._escape(id)}">Skip</button>
            <button class="secondary compact-button" data-action="snooze-task" data-id="${this._escape(id)}" data-days="3">Snooze 3d</button>
            <button class="secondary compact-button" data-action="snooze-task" data-id="${this._escape(id)}" data-days="7">7d</button>
          ` : ""}
          ${snoozed ? `<button class="secondary compact-button" data-action="resume-task" data-id="${this._escape(id)}">Resume now</button>` : ""}
          <button class="secondary compact-button" data-action="toggle-task-history" data-id="${this._escape(id)}">${open ? "Hide history" : `History (${completions.length})`}</button>
        </div>
        ${open ? `
          <div class="manual-history">
            ${completions.length ? completions.slice(0, 12).map((entry) => {
              const vol = (typeof entry.volume === "number") ? ` · ${entry.volume}${entry.volumeUnit === "L" ? " L" : "%"}` : "";
              return `
              <div class="manual-history-row">
                <div>
                  <strong>${this._escape(this._formatActivityTime(entry.timestamp))}${this._escape(vol)}</strong>${entry.skipped ? ` <span class="pill warning">skipped</span>` : ""}
                  ${entry.notes ? `<small>${this._escape(entry.notes)}</small>` : ""}
                </div>
                <button class="danger-text compact-button" data-action="delete-completion" data-id="${this._escape(id)}" data-entry="${this._escape(entry.id)}">Delete</button>
              </div>
            `;
            }).join("") : `<p class="muted">No history yet.</p>`}
          </div>
        ` : ""}
      </article>
    `;
  }

  _maintenanceSettings(forceOpen = false) {
    const config = this._maintenanceConfig();
    const tasks = this._maintenanceTaskList();
    const reminders = config.reminders || {};
    return this._settingsPanel(
      "maintenance",
      "Maintenance",
      "Your recurring reef chores. Enable the ones you do, set cadences, or add your own.",
      `
        <label class="toggle-card">
          <input type="checkbox" data-scope="maintenance" data-field="enabled" ${config.enabled === false ? "" : "checked"}>
          <span>
            <strong>Track maintenance tasks</strong>
            <small>Enabled tasks show on the Maintenance tab; overdue ones surface in Attention and gently nudge Reef Health.</small>
          </span>
        </label>
        <div class="setting-card subtle-card">
          <div class="section-head"><div><p class="eyebrow">Reminders</p><h3>HA-native nudges — free, unlimited, no app paywall</h3></div></div>
          <label class="toggle-card">
            <input type="checkbox" data-scope="maintenance-reminders" data-field="enabled" ${reminders.enabled === false ? "" : "checked"}>
            <span><strong>Remind me when tasks are due</strong><small>One daily check fires an in-Home-Assistant notification (plus an optional phone push) for anything due or overdue — never a second-by-second nag.</small></span>
          </label>
          ${reminders.enabled === false ? "" : `
            <div class="mini-grid">
              <label>Daily check time<input type="time" data-scope="maintenance-reminders" data-field="time" value="${this._escape(reminders.time || "09:00")}"></label>
              <label>Phone push target<input data-scope="maintenance-reminders" data-field="notifyTarget" value="${this._escape(reminders.notifyTarget || "")}" placeholder="e.g. mobile_app_pixel"></label>
            </div>
            <label class="toggle-card">
              <input type="checkbox" data-scope="maintenance-reminders" data-field="persistent" ${reminders.persistent === false ? "" : "checked"}>
              <span><strong>Show in-HA persistent notifications</strong><small>A dashboard notification per due task that clears the moment you mark it done. Turn off for phone-push only.</small></span>
            </label>
            <p class="muted">Phone push calls a Home Assistant <code>notify.&lt;target&gt;</code> service — the companion app creates one like <code>notify.mobile_app_yourphone</code>, so enter <code>mobile_app_yourphone</code>. Leave it empty for in-HA notifications only.</p>
          `}
        </div>
        <div class="section-head">
          <div><p class="eyebrow">Add a task</p></div>
          <div class="button-row">
            <input id="or-add-task-name" placeholder="e.g. Replace UV bulb" maxlength="80">
            <button class="secondary" data-action="add-maintenance-task">Add task</button>
            <button class="secondary" data-action="load-suggested-tasks">Load suggested</button>
          </div>
        </div>
        ${tasks.length ? `
          <div class="grid four compact">
            ${tasks.map(([id]) => {
              const task = this._maintenanceTask(id);
              const due = this._maintenanceDueState(id);
              return `
                <section class="mapping-card manual-schedule-card ${task.enabled ? "manual-enabled" : "disabled-card"}">
                  <div class="mapping-head">
                    <div><p class="eyebrow">${task.builtin ? "suggested" : "custom"}</p><h3>${this._escape(task.label)}</h3></div>
                    <span class="pill ${due.status}">${this._escape(due.label)}</span>
                  </div>
                  <label class="toggle-card">
                    <input type="checkbox" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="enabled" ${task.enabled ? "checked" : ""}>
                    <span><strong>Track this task</strong><small>Every ${this._escape(task.cadenceDays)} days; overdue after ${this._escape(task.criticalAfterDays)}.</small></span>
                  </label>
                  ${task.enabled ? `
                    <div class="mini-grid">
                      <label>Name<input data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="label" value="${this._escape(task.label)}" maxlength="80"></label>
                      <label>Schedule
                        <select data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="scheduleMode">
                          <option value="interval" ${task.scheduleMode !== "fixed" ? "selected" : ""}>Every N days</option>
                          <option value="fixed" ${task.scheduleMode === "fixed" ? "selected" : ""}>Fixed days</option>
                        </select>
                      </label>
                    </div>
                    ${task.scheduleMode === "fixed" ? `
                      <label>Days of week
                        <div class="button-row">
                          ${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => `
                            <label class="day-toggle"><input type="checkbox" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="scheduleDay" data-day="${i}" ${task.scheduleDays.includes(i) ? "checked" : ""}> ${d}</label>
                          `).join("")}
                        </div>
                      </label>
                      <div class="mini-grid">
                        <label>Days of month<input data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="scheduleMonthDays" value="${this._escape(task.scheduleMonthDays.join(", "))}" placeholder="e.g. 1, 15"></label>
                      </div>
                    ` : `
                      <div class="mini-grid">
                        <label>Due after days<input type="number" min="1" max="365" step="1" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="cadenceDays" value="${this._escape(task.cadenceDays)}"></label>
                        <label>Overdue after days<input type="number" min="${this._escape(task.cadenceDays)}" max="730" step="1" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="criticalAfterDays" value="${this._escape(task.criticalAfterDays)}"></label>
                      </div>
                    `}
                    <div class="mini-grid">
                      <label>Notes<input data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="notes" value="${this._escape(task.notes)}" maxlength="300"></label>
                    </div>
                    <label class="toggle-card">
                      <input type="checkbox" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="notify" ${task.notify ? "checked" : ""}>
                      <span><strong>Remind me about this task</strong><small>Include it in due/overdue notifications.</small></span>
                    </label>
                    <label class="toggle-card">
                      <input type="checkbox" data-scope="maintenance-task" data-id="${this._escape(id)}" data-field="logsVolume" ${task.logsVolume ? "checked" : ""}>
                      <span><strong>Log a volume when done</strong><small>Adds an optional litres/% field on the task card — handy for water changes.</small></span>
                    </label>
                  ` : ""}
                  <button class="danger-text compact-button" data-action="remove-maintenance-task" data-id="${this._escape(id)}">Remove task</button>
                </section>
              `;
            }).join("")}
          </div>
        ` : `<p class="muted">No tasks yet — add one above or hit "Load suggested".</p>`}
      `,
      forceOpen,
    );
  }

  async _completeTask(id) {
    const task = this._maintenanceTask(id);
    const config = this._maintenanceConfig();
    if (!Array.isArray(config.completions[id])) config.completions[id] = [];
    const timestamp = new Date().toISOString();
    const entry = {
      id: `${id}:${timestamp}:${config.completions[id].length}`,
      timestamp,
      notes: "",
    };
    let volumeNote = "";
    if (task.logsVolume) {
      const volInput = this.shadowRoot.getElementById(`or-vol-${id}`);
      const unitSel = this.shadowRoot.getElementById(`or-volunit-${id}`);
      const vol = parseFloat(volInput?.value);
      if (Number.isFinite(vol) && vol > 0) {
        entry.volume = Math.round(vol * 100) / 100;
        entry.volumeUnit = unitSel?.value === "L" ? "L" : "pct";
        volumeNote = ` (${entry.volume}${entry.volumeUnit === "L" ? " L" : "%"})`;
      }
    }
    config.completions[id].unshift(entry);
    // Marking it done clears any active snooze.
    if (config.tasks[id]?.snoozedUntil) config.tasks[id] = { ...config.tasks[id], snoozedUntil: null };
    this._setDirty(true);
    this._recordActivity(`Maintenance done: ${task.label}${volumeNote}`, "control");
    this._render();
    await this._persistConfigSilently();
  }

  // Skip this occurrence: log a (non-counting) skip entry + snooze past the next
  // occurrence, so it stops nagging this cycle without resetting the cadence.
  async _skipTask(id) {
    const task = this._maintenanceTask(id);
    const config = this._maintenanceConfig();
    if (!Array.isArray(config.completions[id])) config.completions[id] = [];
    const timestamp = new Date().toISOString();
    config.completions[id].unshift({
      id: `${id}:${timestamp}:${config.completions[id].length}`,
      timestamp,
      notes: "Skipped",
      skipped: true,
    });
    let untilMs;
    if (task.scheduleMode === "fixed") {
      const next = this._maintenanceNextScheduledAfter(task, new Date());
      untilMs = next ? next.getTime() : Date.now() + task.cadenceDays * 86400000;
    } else {
      untilMs = Date.now() + task.cadenceDays * 86400000;
    }
    config.tasks[id] = { ...(config.tasks[id] || {}), snoozedUntil: new Date(untilMs).toISOString() };
    this._setDirty(true);
    this._recordActivity(`Maintenance skipped: ${task.label}`, "warning");
    this._render();
    await this._persistConfigSilently();
  }

  async _snoozeTask(id, days) {
    const task = this._maintenanceTask(id);
    const config = this._maintenanceConfig();
    const span = Math.max(1, Number(days) || 1);
    config.tasks[id] = { ...(config.tasks[id] || {}), snoozedUntil: new Date(Date.now() + span * 86400000).toISOString() };
    this._setDirty(true);
    this._recordActivity(`Maintenance snoozed ${span}d: ${task.label}`);
    this._render();
    await this._persistConfigSilently();
  }

  async _resumeTask(id) {
    const task = this._maintenanceTask(id);
    const config = this._maintenanceConfig();
    config.tasks[id] = { ...(config.tasks[id] || {}), snoozedUntil: null };
    this._setDirty(true);
    this._recordActivity(`Maintenance resumed: ${task.label}`);
    this._render();
    await this._persistConfigSilently();
  }

  async _deleteCompletion(id, entryId) {
    const config = this._maintenanceConfig();
    const list = config.completions[id];
    if (Array.isArray(list)) {
      config.completions[id] = list.filter((entry) => (entry?.id || "") !== entryId);
    }
    this._setDirty(true);
    this._render();
    await this._persistConfigSilently();
  }

  async _addMaintenanceTask(label) {
    const tasks = this._maintenanceConfig().tasks;
    const base = this._slug(label || "task") || "task";
    let id = base;
    let n = 2;
    while (tasks[id]) id = `${base}_${n++}`;
    tasks[id] = { label: label || "Task", cadenceDays: 7, criticalAfterDays: 14, enabled: true, notes: "", builtin: false };
    this._setDirty(true);
    this._recordActivity(`Added maintenance task: ${label || "Task"}`);
    this._render();
    await this._persistConfigSilently();
  }

  async _removeMaintenanceTask(id) {
    const config = this._maintenanceConfig();
    const label = (config.tasks[id] || {}).label || id;
    delete config.tasks[id];
    if (config.completions) delete config.completions[id];
    delete this._maintenanceHistoryOpen[id];
    this._setDirty(true);
    this._recordActivity(`Removed maintenance task: ${label}`, "warning");
    this._render();
    await this._persistConfigSilently();
  }

  async _loadSuggestedTasks() {
    const defaults = {
      water_change: ["Water change", 7], clean_skimmer: ["Clean skimmer cup", 7],
      replace_filter_sock: ["Replace filter sock / floss", 7], blow_detritus: ["Blow detritus off rocks", 7],
      clean_glass: ["Clean glass / viewing panes", 3], refill_dosing: ["Refill dosing / kalk reservoir", 14],
      inspect_ato: ["Check / clean ATO reservoir", 14], replace_carbon: ["Replace carbon", 30],
      replace_gfo: ["Replace GFO (phosphate media)", 30], calibrate_ph: ["Calibrate pH probe", 30],
      calibrate_salinity: ["Calibrate salinity / refractometer", 30], clean_pumps: ["Clean / descale pumps & powerheads", 90],
      replace_rodi: ["Replace RO/DI filters", 180],
    };
    const tasks = this._maintenanceConfig().tasks;
    let added = 0;
    for (const [id, [label, cadence]] of Object.entries(defaults)) {
      if (!tasks[id]) {
        tasks[id] = { label, cadenceDays: cadence, criticalAfterDays: cadence * 2, enabled: false, notes: "", builtin: true };
        added += 1;
      }
    }
    this._setDirty(true);
    this._recordActivity(added ? `Loaded ${added} suggested maintenance task(s)` : "Suggested maintenance tasks already present");
    this._render();
    await this._persistConfigSilently();
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
    const primaryUsesSharedDose = this._dosingUsesSharedDose(primary);
    const sharedDailyDoseMl = this._dosingSharedDailyDoseMl(primary, system);
    const sharedDoseContext = primary.id === "tropic_marin_all_for_reef"
      ? this._allForReefDoseContext(sharedDailyDoseMl, system)
      : null;
    const sharedDoseText = sharedDoseContext
      ? this._allForReefDoseContextText(sharedDoseContext)
      : "Single-solution systems use one total daily dose across every parameter they maintain.";
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
        ${primaryUsesSharedDose ? `
          <div class="setting-card subtle-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Single-solution daily dose</p>
                <h4>Enter the total ${this._escape(primary.label)} dose once.</h4>
                <p class="muted">OpenReef uses this same shared dose for alkalinity, calcium, and magnesium guidance. Do not enter separate per-parameter doses for a one-bottle system.</p>
              </div>
              <span class="pill ${sharedDailyDoseMl > 0 ? "ok" : "unknown"}">${sharedDailyDoseMl > 0 ? this._escape(this._formatDoseMl(sharedDailyDoseMl)) : "not set"}</span>
            </div>
            <div class="grid two compact">
              <label>Total daily dose (mL/day)
                <input type="number" min="0" step="0.1" data-scope="dosing-system" data-field="sharedDailyDoseMl" value="${this._escape(sharedDailyDoseMl)}">
                <small>Use the actual daily amount your doser adds from this bottle.</small>
              </label>
              <div class="notice compact-notice">
                <strong>Shared dose.</strong> ${this._escape(sharedDoseText)}
              </div>
            </div>
          </div>
        ` : ""}
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
        const sharedDoseProduct = this._dosingUsesSharedDose(product);
        const sharedDoseForCard = this._dosingSharedDailyDoseMl(product, system);
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
              <h4>${sharedDoseProduct
                ? `Target for ${this._escape(product.label)}. The daily dose is set once in Dosing Setup.`
                : `Current dose, target, and optional verified strength for ${this._escape(product.label)}.`}</h4>
            </div>
            <div class="mini-grid">
              ${sharedDoseProduct ? "" : `<label>Current dose (mL/day)<input type="number" step="0.1" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="doserMlPerDay" value="${this._escape(cfg.doserMlPerDay ?? 0)}"></label>`}
              <label>Target${this._escape(unitLabel)}<input type="number" step="0.01" min="0" data-scope="dosing" data-id="${this._escape(id)}" data-field="target" value="${this._escape(cfg.target ?? 0)}"></label>
            </div>
            ${sharedDoseProduct ? `
              <div class="notice compact-notice">
                <strong>Uses shared dose.</strong> ${this._escape(sharedDoseForCard > 0
                  ? `${this._formatDoseMl(sharedDoseForCard)} total ${product.label} per day.`
                  : `Set the total daily ${product.label} dose above.`)} OpenReef uses this target to judge whether the shared dose should be reviewed.
              </div>
            ` : `
              <div class="notice compact-notice">
                <strong>${this._escape(this._dosingProductClassLabel(product.classId))}.</strong> ${this._escape(product.note || "OpenReef will use rate-only guidance until a safe exact strength is available.")}
              </div>
            `}
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

  // OpenReef is the controller. This only asks whether the user ALSO runs a Neptune
  // Apex (a minority), which unlocks the Apex-specific tips + jokes.
  _apexControl() {
    const c = this._controllerSetting();
    const active = (c === "other" || c === "none") ? "no" : c; // normalise older values
    const detected = this._detectApex() ? "Apex found" : "none found";
    const opts = [["auto", `Auto (${detected})`], ["apex", "Yes — I have an Apex"], ["no", "No — OpenReef only"]];
    return `<div class="range-picker controller-picker">${opts.map(([id, label]) => `<button class="${active === id ? "active" : ""}" data-action="set-controller" data-id="${this._escape(id)}">${this._escape(label)}</button>`).join("")}</div>`;
  }

  _guideSettings() {
    const buddyOn = this._buddyEnabled();
    const cheeky = this._tone() === "cheeky";
    return this._settingsPanel(
      "guide",
      "Guide & buddy",
      "Your reef guide's personality, the live reactive buddy, and the guided tour.",
      `
        <div class="stack tight">
          <div class="control-row">
            <div><strong>Reef buddy</strong><div class="muted">A live mascot in the Mission Control corner that reacts to your tank state.</div></div>
            <button class="${buddyOn ? "primary" : "secondary"} compact-button" data-action="toggle-buddy">${buddyOn ? "On" : "Off"}</button>
          </div>
          <div class="control-row">
            <div><strong>Tone</strong><div class="muted">Cheeky adds the humour; Professional keeps it plain. Safety messages stay serious either way.</div></div>
            <button class="secondary compact-button" data-action="onboarding-tone">${cheeky ? "😏 Cheeky" : "👔 Professional"}</button>
          </div>
          <div class="control-row">
            <div><strong>Guided tour</strong><div class="muted">Replay the walkthrough on Mission Control any time.</div></div>
            <button class="secondary compact-button" data-action="onboarding-start">👋 Replay</button>
          </div>
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
          <label>Tank type
            <select data-scope="tank" data-field="profile">
              ${this._tankProfileChoices().map(([id, label]) => `<option value="${this._escape(id)}" ${this._tankProfile() === id ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
            </select>
            <small>${this._escape(this._tankProfileDetail())}</small>
          </label>
          <div class="field-group">
            <span class="field-label">Also running a Neptune Apex?</span>
            ${this._apexControl()}
            <small>OpenReef is your reef controller. Tell it if you also run an Apex (data in Home Assistant) to unlock Apex-specific tips and jokes.</small>
          </div>
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
    const isLighting = profile === "lighting";
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
              ${isLighting ? `<span class="pill ${item.light_entity_id ? "ok" : "unknown"}">${item.light_entity_id ? "light mapped" : "no light entity"}</span>` : ""}
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
            ${isLighting ? `
              <section class="picker mapping-card entity-card lighting-card">
                <div class="mapping-head">
                  <div>
                    <h3>Light entity</h3>
                    <p class="muted">Read live brightness, state, effect, and colour from Home Assistant without writing programs.</p>
                  </div>
                  <span class="pill">read only</span>
                </div>
                <label>Light entity<input data-scope="equipment" data-id="${this._escape(id)}" data-field="light_entity_id" value="${this._escape(item.light_entity_id || "")}" placeholder="light.display_lights"></label>
                ${item.light_entity_id ? `
                  <div class="selected-entity">
                    <span>${this._escape(this._friendlyEntityName(item.light_entity_id))}</span>
                    <button class="secondary compact-button" data-action="clear-equipment-field" data-id="${this._escape(id)}" data-field="light_entity_id">Clear</button>
                  </div>
                ` : ""}
                <button class="secondary" data-action="search-equipment" data-id="${this._escape(id)}" data-field="light_entity_id">${this._searchResults[`equipment:${id}:light_entity_id`]?.loading ? "Finding..." : "Find matches"}</button>
                ${this._candidateList(`equipment:${id}:light_entity_id`, "choose-equipment", id, "light_entity_id")}
              </section>
            ` : ""}
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
    this._probeAvatar();
    return this._setupShell(
      "Welcome to OpenReef",
      "OpenReef is your Home Assistant-native reef controller. Let's get the basics set up — you can change everything later in Settings.",
      `
        <div class="setup-intro">
          <div class="setup-intro-avatar">${this._avatarMarkup("idle")}</div>
          <div class="setup-intro-bubble">
            <strong>Hi, I'm your reef guide 👋</strong>
            <p class="muted">A little reefer who lives in your dashboard. I'll keep an eye on the tank with you — and once you're set up, I'll show you round in a quick tour.</p>
          </div>
        </div>
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
              <span class="field-label">Also running a Neptune Apex?</span>
              ${this._apexControl()}
              <small>OpenReef is your reef controller. If you also run an Apex (data already in Home Assistant), I'll tailor a few tips — and the jokes — to it. Optional; change it any time in Settings.</small>
            </div>
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
        .or-narrator { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); width: min(520px, calc(100vw - 28px)); display: flex; gap: 12px; align-items: flex-end; pointer-events: auto; z-index: 13; transition: left 1.4s cubic-bezier(.4,.15,.35,1), top 1.4s cubic-bezier(.4,.15,.35,1); }
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
        .straton-screen { display: grid; gap: 16px; }
        .straton-screen > .hero .pill-stack { align-items: center; }
        .straton-advanced-tools { border: 1px solid #24364a; border-radius: 8px; padding: 14px; background: #0e1a28; }
        .straton-advanced-tools > summary { display: flex; justify-content: space-between; gap: 12px; align-items: center; cursor: pointer; list-style: none; color: #dcecff; font-weight: 800; }
        .straton-advanced-tools > summary::-webkit-details-marker { display: none; }
        .straton-advanced-tools > summary small { color: #8da2ba; font-weight: 700; }
        .straton-advanced-tools > .stack { margin-top: 12px; }
        .straton-fixture-card, .straton-template { background: linear-gradient(180deg, var(--openreef-accent-soft), rgba(16, 29, 44, .92) 34%, #101d2c); }
        .straton-sync-matrix .section-head { align-items: flex-start; }
        .straton-sync-matrix .row { align-items: flex-start; }
        .straton-sync-matrix .pill-stack { max-width: 560px; }
        .straton-template.active-template { border-color: var(--openreef-accent); box-shadow: inset 4px 0 0 var(--openreef-accent); }
        .straton-template .setup-next-list { margin-top: 4px; }
        .straton-daybar { position: relative; height: 38px; border: 1px solid #24364a; border-radius: 8px; overflow: hidden; background: linear-gradient(90deg, #07111a, #0f2234 50%, #07111a); margin-top: 12px; }
        .straton-daybar span { position: absolute; top: 0; bottom: 0; display: block; border-left: 1px solid rgba(255,255,255,.12); border-right: 1px solid rgba(0,0,0,.24); }
        .straton-daybar .ramp { background: linear-gradient(90deg, rgba(34, 211, 238, .18), rgba(34, 211, 238, .72)); }
        .straton-daybar .peak { background: rgba(45, 212, 191, .88); }
        .straton-daybar .cloud { top: 24px; bottom: 0; background: rgba(148, 163, 184, .45); }
        .straton-time-axis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; color: #8da2ba; font-size: 12px; font-weight: 800; margin-top: 6px; }
        .straton-time-axis span:not(:first-child):not(:last-child) { text-align: center; }
        .straton-time-axis span:last-child { text-align: right; }
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
        .cam-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
        .cam-tile { position: relative; aspect-ratio: 16 / 9; border: 1px solid #24364a; border-radius: 10px; overflow: hidden; background: #0b1724; padding: 0; cursor: pointer; display: block; }
        .cam-tile:hover { border-color: var(--openreef-accent); }
        .cam-tile.offline { cursor: default; }
        .cam-feed { width: 100%; height: 100%; object-fit: cover; display: block; }
        .cam-placeholder { width: 100%; height: 100%; display: grid; place-items: center; gap: 6px; color: #8da2ba; text-align: center; }
        .cam-glyph { font-size: 34px; opacity: .55; }
        .cam-label { position: absolute; left: 8px; bottom: 8px; padding: 3px 9px; border-radius: 6px; background: rgba(4, 12, 20, .66); color: #e5edf5; font-weight: 800; font-size: 12px; }
        .cam-live { position: absolute; right: 8px; top: 8px; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: 999px; background: rgba(4, 12, 20, .66); color: #fecaca; font-weight: 800; font-size: 11px; letter-spacing: .06em; }
        .cam-dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; animation: or-pulse 1.4s ease-in-out infinite; }
        .cam-dialog { max-width: 1100px; }
        .cam-stage { position: relative; width: 100%; aspect-ratio: 16 / 9; background: #04080d; border-radius: 10px; overflow: hidden; display: grid; place-items: center; }
        .cam-feed-large { width: 100%; height: 100%; object-fit: contain; display: block; background: #04080d; }
        .cam-card { position: relative; padding: 0; overflow: hidden; min-height: 0; border: 1px solid #24364a; }
        .cam-card > span { position: absolute; left: 10px; top: 9px; z-index: 1; padding: 2px 8px; border-radius: 6px; background: rgba(4, 12, 20, .66); color: #8da2ba; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
        .cam-card-img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; }
        .cam-card small { position: absolute; left: 10px; bottom: 9px; padding: 2px 8px; border-radius: 6px; background: rgba(4, 12, 20, .66); color: #e5edf5; }
        .recordings-section { margin-top: 18px; }
        .recording-tile { aspect-ratio: auto; cursor: default; display: flex; flex-direction: column; }
        .recording-open { position: relative; width: 100%; aspect-ratio: 16 / 9; border: 0; padding: 0; background: #0b1724; cursor: pointer; display: block; }
        .recording-open:disabled { cursor: default; opacity: .85; }
        .recording-open:not(:disabled):hover { filter: brightness(1.08); }
        .recording-meta { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-top: 1px solid #24364a; background: #0b1724; }
        .recording-time { color: #8da2ba; font-size: 12px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .play-badge { color: #d1fae5; letter-spacing: .05em; }
        .danger-button { color: #fecaca; }
        .danger-button:hover { border-color: #ef4444; }
        video.cam-feed-large { background: #04080d; }
        .timelapse-section { margin-top: 18px; }
        .timelapse-stamp { position: absolute; top: 10px; left: 12px; background: rgba(4, 8, 13, 0.72); color: #e6f1f7; padding: 4px 9px; border-radius: 6px; font-size: 0.8em; letter-spacing: 0.02em; }
        .timelapse-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
        .timelapse-scrubber { flex: 1 1 180px; min-width: 120px; accent-color: var(--primary-color, #00b4d8); }
        .timelapse-counter { font-variant-numeric: tabular-nums; color: #9fb3c8; font-size: 0.85em; }
        .timelapse-speed { display: flex; align-items: center; gap: 6px; font-size: 0.85em; color: #9fb3c8; }
        .timelapse-section .seg { display: inline-flex; gap: 4px; }
        .timelapse-section .seg .active { background: var(--primary-color, #00b4d8); color: #04222b; border-color: var(--primary-color, #00b4d8); }
        .feeds-section { margin-top: 18px; }
        .feed-rec { color: #fecaca; }
        .cam-overlay { position: absolute; inset: 0; pointer-events: none; display: flex; flex-direction: column; gap: 8px; padding: 14px; }
        .cam-overlay.pos-top-left { align-items: flex-start; justify-content: flex-start; }
        .cam-overlay.pos-top-right { align-items: flex-end; justify-content: flex-start; }
        .cam-overlay.pos-bottom-left { align-items: flex-start; justify-content: flex-end; }
        .cam-overlay.pos-bottom-right { align-items: flex-end; justify-content: flex-end; }
        .cam-overlay-title { background: rgba(4, 10, 16, .55); color: #e9f4fb; font-weight: 800; font-size: 14px; letter-spacing: .02em; padding: 4px 10px; border-radius: 8px; }
        .cam-overlay-chips { display: flex; flex-direction: column; gap: 6px; max-width: 60%; }
        .cam-overlay-chip { display: inline-flex; align-items: baseline; gap: 8px; background: rgba(4, 10, 16, .55); border-radius: 8px; padding: 4px 10px; }
        .cam-overlay-chip small { color: #9fc7e0; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
        .cam-overlay-chip strong { color: #fff; font-size: 14px; font-weight: 800; }
        .cam-overlay-chip.is-health small { color: #7fe0c4; }
        .cam-overlay-avatar { position: absolute; bottom: 10px; right: 12px; display: flex; flex-direction: column; align-items: center; gap: 6px; width: 96px; }
        .cam-overlay.pos-bottom-right .cam-overlay-avatar, .cam-overlay.pos-top-right .cam-overlay-avatar { right: auto; left: 12px; }
        .cam-overlay-avatar .or-avatar-img, .cam-overlay-avatar .or-avatar-ph { width: 96px; height: 96px; object-fit: contain; }
        .cam-overlay-avatar .or-avatar-ph { display: grid; place-items: center; font-size: 48px; }
        .cam-overlay-bubble { background: rgba(255, 255, 255, .94); color: #0a2230; font-weight: 800; font-size: 12px; padding: 5px 10px; border-radius: 12px; max-width: 180px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.3); }
        .range-picker { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
        .controller-picker { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); margin-top: 6px; }
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
        .setup-intro { display: flex; align-items: center; gap: 16px; padding: 6px 4px 14px; }
        .setup-intro-avatar { flex: 0 0 auto; width: 110px; }
        .setup-intro-avatar .or-avatar-img { width: 100%; height: auto; display: block; filter: drop-shadow(0 6px 12px rgba(0,0,0,.45)); }
        .setup-intro-avatar .or-avatar-ph { width: 88px; height: 88px; border-radius: 50%; display: grid; place-items: center; font-size: 40px; background: radial-gradient(circle at 50% 35%, var(--openreef-accent-soft), #0b1724); border: 2px solid var(--openreef-accent-border); }
        .setup-intro-bubble { flex: 1 1 auto; min-width: 0; background: #101f2f; border: 1px solid var(--openreef-accent-border); border-radius: 14px; padding: 14px 16px; }
        .setup-intro-bubble strong { color: #f1f6fb; }
        .setup-intro-bubble p { margin-top: 4px; line-height: 1.4; }
        @media (max-width: 640px) { .setup-intro { flex-direction: column; align-items: flex-start; gap: 8px; } .setup-intro-avatar { width: 96px; } }
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
          .straton-screen > .hero .pill-stack { align-items: stretch; flex-direction: column; justify-content: flex-start; width: 100%; }
          .straton-screen > .hero .pill-stack .pill, .straton-screen > .hero .pill-stack button { width: 100%; }
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
