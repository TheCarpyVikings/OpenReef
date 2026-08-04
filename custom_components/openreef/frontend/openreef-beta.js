/*
 * OpenReef beta feedback — the "Ask Reece" button.
 *
 * WHY THIS IS ITS OWN FILE AND ITS OWN ELEMENT
 * --------------------------------------------
 * Beta feedback is scaffolding that has to come out cleanly when the beta
 * ends. So it is a standalone custom element with its own shadow root, its
 * own styles, and its own state — it borrows nothing from the panel except
 * `hass` (to call websockets) and a `support` callback (to read the support
 * summary the panel already builds).
 *
 * The panel's entire involvement is one method, `_mountBetaFab()`, tagged
 * BETA-FEEDBACK. Deleting this file and that method removes the feature. If
 * this file is deleted but the panel method survives, the dynamic import
 * fails, `<openreef-beta-fab>` stays an undefined element with no styles and
 * no content, and nothing breaks — an undefined custom element renders
 * nothing and occupies no space.
 *
 * MOUNTING NOTE
 * -------------
 * The panel re-writes `shadowRoot.innerHTML` on every render, so this element
 * is created once and re-appended afterwards — the same node object each
 * time, which preserves an open modal and a half-typed message across the
 * re-render. That means connectedCallback fires repeatedly and must stay
 * idempotent; it must never reset state.
 */

const KINDS = [
  { value: "bug", emoji: "🐛", label: "Bug", hint: "Something is broken or wrong" },
  { value: "feature", emoji: "✨", label: "Feature request", hint: "Something you want OpenReef to do" },
  { value: "idea", emoji: "💡", label: "Idea", hint: "Half-formed is fine" },
  { value: "question", emoji: "❓", label: "Question", hint: "Something that isn't clear" },
  { value: "praise", emoji: "🩵", label: "Nice thing", hint: "What's working — it's genuinely useful to know" },
  { value: "unsafe", emoji: "⚠️", label: "Something unsafe", hint: "Equipment did something you didn't expect" },
];

const SEVERITIES = [
  { value: "low", label: "Minor" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "Painful" },
  { value: "blocker", label: "Blocking me" },
];

const STATUS_LABEL = {
  new: "New",
  triaged: "Seen",
  planned: "Planned",
  in_progress: "Being worked on",
  actioned: "Done",
  wontfix: "Not doing",
  duplicate: "Already tracked",
};

const STATUS_TONE = {
  new: "tone-new",
  triaged: "tone-seen",
  planned: "tone-seen",
  in_progress: "tone-work",
  actioned: "tone-done",
  wontfix: "tone-closed",
  duplicate: "tone-closed",
};

class OpenReefBetaFab extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._context = { tab: "", version: "" };
    this._support = null;
    this._state = null;          // last public_state from the backend
    this._open = false;
    this._view = "send";         // send | list | news | settings
    this._draft = { kind: "bug", severity: "normal", body: "", intent: "" };
    this._showsPayload = false;
    this._busy = false;
    this._error = "";
    this._sentRef = "";
    this._code = "";
    this._acceptTerms = false;
    this._loaded = false;
    this._bound = false;
    this._focusId = "";
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  /* --- inputs from the panel ------------------------------------------- */

  set hass(value) {
    const first = !this._hass;
    this._hass = value;
    // First hass is the trigger to load status; later ones are just refreshes
    // of a rapidly-changing object and must not cause work.
    if (first) this._load();
    else if (this._loaded && !this._open) this._renderFab();
  }

  set context(value) {
    this._context = value || { tab: "", version: "" };
  }

  /** A () => string callback the panel provides so we can read its support
   *  summary without this file knowing anything about how it is built. */
  set support(fn) {
    this._support = typeof fn === "function" ? fn : null;
  }

  /*
   * The panel creates this element and sets hass/context/support IMMEDIATELY,
   * while the dynamic import that defines it is still in flight. At that
   * moment the element is undefined, so each assignment lands as an own data
   * property on the instance — and an own data property permanently shadows
   * the prototype accessor once the element upgrades. Without this, `set hass`
   * never fires, _load() is never called, and the button never appears.
   *
   * Re-applying each one through delete-then-reassign routes it back through
   * the setter. This is the standard custom-element "lazy properties" fix.
   */
  _upgradeProperty(name) {
    if (!Object.prototype.hasOwnProperty.call(this, name)) return;
    const value = this[name];
    delete this[name];
    this[name] = value;
  }

  connectedCallback() {
    for (const name of ["context", "support", "hass"]) this._upgradeProperty(name);
    // Idempotent by design — the panel re-appends this node on every render.
    if (!this.shadowRoot.firstChild) this._render();
    document.addEventListener("keydown", this._onKeyDown);
    this._restoreFocus();
  }

  /*
   * Safety net for the panel re-rendering underneath us.
   *
   * A full panel render wipes its shadow root, which detaches this element and
   * blurs whatever was focused inside it; re-appending restores the DOM but not
   * the caret. The panel's _isEditingFormControl now looks through shadow roots
   * and won't re-render mid-keystroke, but it can't cover every path — a config
   * refresh or an explicit render still gets through. Losing your place every
   * few seconds turns writing a bug report into a fight, so put it back.
   */
  _restoreFocus() {
    if (!this._open || !this._focusId) return;
    const field = this.shadowRoot.getElementById(this._focusId);
    if (!field || field === this.shadowRoot.activeElement) return;
    const start = field.selectionStart;
    const end = field.selectionEnd;
    field.focus();
    // focus() drops the caret at the end of a text field — restore where it was,
    // or someone editing mid-sentence gets thrown to the end of it.
    if (typeof start === "number" && typeof field.setSelectionRange === "function") {
      try {
        field.setSelectionRange(start, end);
      } catch {
        /* not a control that supports selection ranges */
      }
    }
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKeyDown);
  }

  _onKeyDown(event) {
    if (event.key === "Escape" && this._open) this._close();
  }

  /* --- backend --------------------------------------------------------- */

  async _ws(payload) {
    if (!this._hass) throw new Error("not ready");
    if (typeof this._hass.callWS === "function") return this._hass.callWS(payload);
    return this._hass.connection.sendMessagePromise(payload);
  }

  async _load() {
    try {
      this._state = await this._ws({ type: "openreef/beta_status" });
    } catch {
      // The backend module isn't there (removed after beta, or an older
      // install). Stay silent and stay invisible — never show a broken button.
      this._state = null;
    }
    this._loaded = true;
    this._render();
  }

  async _sync() {
    try {
      this._state = await this._ws({ type: "openreef/beta_sync" });
    } catch {
      /* offline is fine; we render whatever we last knew */
    }
  }

  /* --- visibility ------------------------------------------------------ */

  _visible() {
    if (!this._loaded || !this._state) return false;
    // Only Home Assistant admins can submit (the backend requires it), so
    // showing the button to anyone else would just be a promise we break.
    return this._hass?.user?.is_admin !== false;
  }

  /* --- actions --------------------------------------------------------- */

  _openModal() {
    this._open = true;
    this._error = "";
    this._sentRef = "";
    this._view = this._state?.enrolled ? "send" : "enrol";
    this._render();
    // Refresh in the background: opening the modal is the moment a tester is
    // most likely to be looking for a reply.
    if (this._state?.enrolled) {
      this._sync().then(() => {
        if (this._open) this._render();
      });
    }
    requestAnimationFrame(() => {
      this.shadowRoot.getElementById("orb-body")?.focus();
    });
  }

  _close() {
    this._open = false;
    this._showsPayload = false;
    this._focusId = "";
    this._render();
  }

  async _enrol() {
    const code = (this.shadowRoot.getElementById("orb-code")?.value || "").trim();
    if (!code) return;
    // Held so a rejected code stays in the box — retyping it after a typo
    // rejection is a small thing that feels like being punished for trying.
    this._code = code;
    this._busy = true;
    this._error = "";
    this._render();
    try {
      this._state = await this._ws({
        type: "openreef/beta_enrol",
        code,
        accept: this._acceptTerms,
      });
      this._view = "send";
    } catch (err) {
      this._error = this._friendly(err, "That code didn't work. Check it and try again.");
    }
    this._busy = false;
    this._render();
  }

  async _submit() {
    const body = (this.shadowRoot.getElementById("orb-body")?.value || "").trim();
    if (!body) return;
    const intent = (this.shadowRoot.getElementById("orb-intent")?.value || "").trim();
    this._draft.body = body;
    this._draft.intent = intent;
    this._busy = true;
    this._error = "";
    this._render();
    try {
      const result = await this._ws({
        type: "openreef/beta_submit",
        kind: this._draft.kind,
        severity: this._draft.severity,
        body,
        intent,
        tab: this._context.tab || "",
        userAgent: navigator.userAgent || "",
        support: this._supportText(),
      });
      if (result?.state) this._state = result.state;
      this._sentRef = result?.sent ? result.ref || "sent" : "";
      if (!result?.sent) {
        this._error = "You're offline (or the portal is). Saved — it'll send itself later.";
      }
      this._draft = { kind: "bug", severity: "normal", body: "", intent: "" };
    } catch (err) {
      this._error = this._friendly(err, "Couldn't send that. Try again in a moment.");
    }
    this._busy = false;
    this._render();
  }

  async _setSetting(key, value) {
    try {
      this._state = await this._ws({ type: "openreef/beta_settings", [key]: value });
    } catch (err) {
      this._error = this._friendly(err, "Couldn't save that.");
    }
    this._render();
  }

  async _markRead(ref) {
    try {
      this._state = await this._ws({ type: "openreef/beta_mark_read", ...(ref ? { ref } : {}) });
    } catch {
      /* cosmetic only */
    }
    this._render();
  }

  _friendly(err, fallback) {
    const message = err?.message || err?.error || "";
    if (/not_enrolled/.test(message)) return "Enter your invite code first.";
    if (/agreement_required/.test(message)) return "Tick the agreement box first — the links above are the short version of what you're agreeing to.";
    if (/invalid_code|enrol_failed/.test(message)) return "That code didn't work. Check it and try again.";
    return message && message.length < 160 ? message : fallback;
  }

  /** Portal page URL — follows a custom endpoint if one was set at enrolment,
   *  so the agreement links never point at a portal this install doesn't use. */
  _portalUrl(pagePath) {
    const base = (this._state?.endpoint || "https://beta.openreef.co.uk").replace(/\/+$/, "");
    return `${this._esc(base)}${pagePath}`;
  }

  _supportText() {
    if (!this._support) return "";
    try {
      return this._support() || "";
    } catch {
      // A half-configured install can't build a summary. That's exactly when
      // someone reports a bug, so send the message without it rather than
      // blocking the report.
      return "";
    }
  }

  /* --- rendering ------------------------------------------------------- */

  _esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  _when(iso) {
    if (!iso) return "";
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return "";
    const mins = Math.round((Date.now() - then.getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  }

  _render() {
    if (!this._visible()) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    this.shadowRoot.innerHTML = `${this._styles()}${this._fab()}${this._open ? this._modal() : ""}`;
    this._bind();
  }

  /** Cheap path for hass churn: only the badge can change. */
  _renderFab() {
    const badge = this.shadowRoot.querySelector(".orb-badge");
    const unread = this._state?.unread || 0;
    if (badge) badge.textContent = unread > 9 ? "9+" : String(unread);
    if (badge) badge.hidden = !unread;
  }

  _fab() {
    const unread = this._state?.unread || 0;
    return `
      <button class="orb-fab" type="button" data-orb="open"
              aria-label="Ask Reece — send beta feedback">
        <span class="orb-fab-icon" aria-hidden="true">💬</span>
        <span class="orb-fab-label">Ask Reece</span>
        <span class="orb-badge" ${unread ? "" : "hidden"}>${unread > 9 ? "9+" : unread}</span>
      </button>
    `;
  }

  _modal() {
    return `
      <div class="orb-scrim" data-orb="scrim">
        <div class="orb-sheet" role="dialog" aria-modal="true" aria-label="Ask Reece">
          <header class="orb-head">
            <div>
              <p class="orb-eyebrow">OpenReef beta</p>
              <h2>Ask Reece</h2>
            </div>
            <button class="orb-icon" type="button" data-orb="close" aria-label="Close">✕</button>
          </header>
          ${this._state?.enrolled ? this._nav() : ""}
          <div class="orb-body">${this._view === "enrol" ? this._enrolView() : this._viewBody()}</div>
        </div>
      </div>
    `;
  }

  _nav() {
    const unreadItems = (this._state?.items || []).filter((item) => item.unread).length;
    const unreadNews = (this._state?.announcements || []).filter((note) => note.unread).length;
    const tabs = [
      ["send", "Send feedback", 0],
      ["list", "Yours", unreadItems],
      ["news", "News", unreadNews],
      ["settings", "Sharing", 0],
    ];
    return `
      <nav class="orb-nav">
        ${tabs.map(([id, label, count]) => `
          <button type="button" class="${this._view === id ? "active" : ""}" data-orb="view" data-id="${id}">
            ${this._esc(label)}${count ? `<span class="orb-dot">${count}</span>` : ""}
          </button>
        `).join("")}
      </nav>
    `;
  }

  _viewBody() {
    if (this._view === "list") return this._listView();
    if (this._view === "news") return this._newsView();
    if (this._view === "settings") return this._settingsView();
    return this._sendView();
  }

  /* --- enrol ----------------------------------------------------------- */

  _enrolView() {
    return `
      <p class="orb-lede">
        Paste the invite code Reece sent you. It links this install to the beta
        so your feedback arrives with the context needed to actually fix things.
      </p>
      ${this._error ? `<p class="orb-error">${this._esc(this._error)}</p>` : ""}
      <label class="orb-label" for="orb-code">Invite code</label>
      <input class="orb-input" id="orb-code" type="text" placeholder="e.g. REEF-7K2Q"
             autocomplete="off" spellcheck="false" value="${this._esc(this._code)}">

      <label class="orb-toggle" style="margin-top:14px">
        <input type="checkbox" data-orb="accept-terms" ${this._acceptTerms ? "checked" : ""}>
        <span>
          <strong>I've read the <a class="orb-link" href="${this._portalUrl("/agreement")}" target="_blank" rel="noopener">beta agreement</a>
          and <a class="orb-link" href="${this._portalUrl("/privacy")}" target="_blank" rel="noopener">privacy notice</a></strong>
          <em>Two short pages, written to be read. The one-line version: it's unfinished
          software, your tank stays your responsibility, and you can see and stop
          everything it sends.</em>
        </span>
      </label>

      <div class="orb-actions">
        <button class="orb-primary" type="button" data-orb="enrol"
                ${this._busy || !this._acceptTerms ? "disabled" : ""}>
          ${this._busy ? "Checking…" : "Join the beta"}
        </button>
      </div>
      <p class="orb-fine">
        Once enrolled, your install checks in every 30 minutes with setup counts and
        its Trust Check status — so if you get stuck, Reece notices without you having
        to say so. Everything else only leaves when you press send, and the
        <strong>Sharing</strong> tab controls what rides along.
      </p>
    `;
  }

  /* --- send ------------------------------------------------------------ */

  _sendView() {
    if (this._sentRef) {
      return `
        <div class="orb-sent">
          <p class="orb-sent-icon" aria-hidden="true">🩵</p>
          <p class="orb-sent-title">Sent. Thank you.</p>
          <p class="orb-fine">Reference <code>${this._esc(this._sentRef)}</code> — you'll get a
          notification here when Reece acts on it.</p>
          <div class="orb-actions">
            <button class="orb-secondary" type="button" data-orb="again">Send another</button>
            <button class="orb-primary" type="button" data-orb="close">Done</button>
          </div>
        </div>
      `;
    }

    const kind = KINDS.find((option) => option.value === this._draft.kind) || KINDS[0];
    const showSeverity = this._draft.kind === "bug";
    return `
      ${this._state?.queued ? `<p class="orb-warn">${this._state.queued} message${this._state.queued === 1 ? "" : "s"} waiting to send — they'll go automatically.</p>` : ""}
      ${this._error ? `<p class="orb-error">${this._esc(this._error)}</p>` : ""}

      <label class="orb-label">What kind of thing is this?</label>
      <div class="orb-chips">
        ${KINDS.map((option) => `
          <button type="button" class="orb-chip ${this._draft.kind === option.value ? "active" : ""} ${option.value === "unsafe" ? "danger" : ""}"
                  data-orb="kind" data-id="${option.value}" aria-pressed="${this._draft.kind === option.value}">
            <span aria-hidden="true">${option.emoji}</span> ${this._esc(option.label)}
          </button>
        `).join("")}
      </div>
      <p class="orb-fine">${this._esc(kind.hint)}</p>

      ${this._draft.kind === "unsafe" ? `
        <p class="orb-warn danger">
          If equipment is doing something dangerous <strong>right now</strong>, deal with the
          tank first — disarm it in Controls or pull the plug. This form can wait.
        </p>` : ""}

      ${showSeverity ? `
        <label class="orb-label" for="orb-sev">How much is it hurting?</label>
        <div class="orb-chips">
          ${SEVERITIES.map((option) => `
            <button type="button" class="orb-chip small ${this._draft.severity === option.value ? "active" : ""}"
                    data-orb="sev" data-id="${option.value}">${this._esc(option.label)}</button>
          `).join("")}
        </div>` : ""}

      <label class="orb-label" for="orb-body">
        ${this._draft.kind === "bug" || this._draft.kind === "unsafe" ? "What happened?" : "Tell Reece"}
      </label>
      <textarea class="orb-input orb-textarea" id="orb-body" rows="5" maxlength="4000"
                placeholder="${this._esc(this._placeholder())}">${this._esc(this._draft.body)}</textarea>

      <label class="orb-label" for="orb-intent">What were you trying to do? <span class="orb-optional">optional</span></label>
      <input class="orb-input" id="orb-intent" type="text" maxlength="500"
             placeholder="e.g. setting up a second dosing channel"
             value="${this._esc(this._draft.intent)}">

      <button type="button" class="orb-disclose" data-orb="payload">
        ${this._showsPayload ? "▾" : "▸"} See exactly what gets sent with this
      </button>
      ${this._showsPayload ? this._payloadPreview() : ""}

      <div class="orb-actions">
        <button class="orb-primary" type="button" data-orb="submit" ${this._busy ? "disabled" : ""}>
          ${this._busy ? "Sending…" : "Send to Reece"}
        </button>
        <button class="orb-secondary" type="button" data-orb="close">Cancel</button>
      </div>
    `;
  }

  _placeholder() {
    switch (this._draft.kind) {
      case "bug": return "What you did, what you expected, what happened instead.";
      case "unsafe": return "Which equipment, what it did, and what state the tank is in now.";
      case "feature": return "What you want to be able to do — and why the current way doesn't work.";
      case "question": return "What isn't clear?";
      case "praise": return "What's working well? Knowing what to protect is as useful as knowing what to fix.";
      default: return "Half-formed thoughts welcome.";
    }
  }

  _payloadPreview() {
    const support = this._state?.shareSupport ? this._supportText() : "";
    return `
      <div class="orb-payload">
        <p class="orb-fine">Always attached — this is the whole list:</p>
        <ul class="orb-meta">
          <li>The tab you're on: <code>${this._esc(this._context.tab || "unknown")}</code></li>
          <li>OpenReef version: <code>${this._esc(this._state?.version || "unknown")}</code></li>
          <li>Your Home Assistant version and browser</li>
          <li>Your tester name — nothing else identifying</li>
        </ul>
        <p class="orb-fine">
          ${this._state?.shareSupport
            ? "Plus your support summary (below) — toggle it off under Sharing."
            : "Support summary is <strong>off</strong> — turn it on under Sharing if you want faster fixes."}
          ${this._state?.shareLogs ? " Plus the OpenReef lines from your HA log." : " Log lines are <strong>off</strong>."}
        </p>
        ${support ? `<pre class="orb-pre">${this._esc(support)}</pre>` : ""}
        <p class="orb-fine">Anything that looks like a key, token or password is stripped before sending.</p>
      </div>
    `;
  }

  /* --- your feedback --------------------------------------------------- */

  _listView() {
    const items = this._state?.items || [];
    if (!items.length) {
      return `<p class="orb-lede">Nothing sent yet. Whatever you send shows up here with
              Reece's reply once he's looked at it.</p>`;
    }
    return `
      <div class="orb-actions end">
        <button class="orb-secondary small" type="button" data-orb="readall">Mark all read</button>
      </div>
      <ul class="orb-list">
        ${items.map((item) => `
          <li class="orb-item ${item.unread ? "unread" : ""}">
            <div class="orb-item-head">
              <span class="orb-status ${STATUS_TONE[item.status] || "tone-new"}">
                ${this._esc(STATUS_LABEL[item.status] || item.status)}
              </span>
              <code class="orb-ref">${this._esc(item.ref)}</code>
              <span class="orb-when">${this._esc(this._when(item.createdAt))}</span>
            </div>
            <p class="orb-item-body">${this._esc(item.body)}</p>
            ${item.reply ? `
              <div class="orb-reply">
                <p class="orb-eyebrow">Reece said</p>
                <p>${this._esc(item.reply)}</p>
              </div>` : ""}
            ${item.unread ? `<button class="orb-secondary small" type="button" data-orb="read" data-id="${this._esc(item.ref)}">Got it</button>` : ""}
          </li>
        `).join("")}
      </ul>
    `;
  }

  /* --- news ------------------------------------------------------------ */

  _newsView() {
    const notes = this._state?.announcements || [];
    if (!notes.length) {
      return `<p class="orb-lede">No announcements yet. When Reece ships something worth
              testing, it lands here instead of in your inbox.</p>`;
    }
    return `
      <ul class="orb-list">
        ${notes.map((note) => `
          <li class="orb-item ${note.unread ? "unread" : ""}">
            <div class="orb-item-head">
              <strong>${this._esc(note.title)}</strong>
              <span class="orb-when">${this._esc(this._when(note.publishedAt))}</span>
            </div>
            <p class="orb-item-body">${this._esc(note.body)}</p>
          </li>
        `).join("")}
      </ul>
      <div class="orb-actions end">
        <button class="orb-secondary small" type="button" data-orb="readall">Mark all read</button>
      </div>
    `;
  }

  /* --- sharing --------------------------------------------------------- */

  _settingsView() {
    const state = this._state || {};
    return `
      <p class="orb-lede">
        You're in the beta as <strong>${this._esc(state.testerName || "a tester")}</strong>.
        These control what travels with a message. Both are optional — feedback
        works without them, it just takes longer to fix things.
      </p>
      ${this._error ? `<p class="orb-error">${this._esc(this._error)}</p>` : ""}

      <label class="orb-toggle">
        <input type="checkbox" data-orb="toggle" data-id="shareSupport" ${state.shareSupport ? "checked" : ""}>
        <span>
          <strong>Send my support summary</strong>
          <em>Versions, which sensors and equipment are mapped and armed, trust check,
          health score, recent activity. No credentials — the same summary the Settings
          tab lets you copy by hand.</em>
        </span>
      </label>

      <label class="orb-toggle">
        <input type="checkbox" data-orb="toggle" data-id="shareLogs" ${state.shareLogs ? "checked" : ""}>
        <span>
          <strong>Send OpenReef log lines</strong>
          <em>The last ${80} lines of your Home Assistant log that mention OpenReef.
          Other integrations' lines are never included.</em>
        </span>
      </label>

      <div class="orb-sep"></div>
      <p class="orb-fine">
        Last synced ${this._esc(this._when(state.lastSyncAt) || "never")}.
        ${state.lastError ? `Last error: <code>${this._esc(state.lastError)}</code>.` : ""}
      </p>
      <div class="orb-actions">
        <button class="orb-danger" type="button" data-orb="leave">Leave the beta</button>
      </div>
      <p class="orb-fine">
        Leaving stops all sending immediately and forgets your token. Everything
        already sent stays with Reece; ask him to delete it and he will.
      </p>
    `;
  }

  /* --- events ---------------------------------------------------------- */

  _bind() {
    // Once only. The listeners live on the shadow ROOT, which _render() never
    // replaces — it only rewrites innerHTML — so re-binding would stack a fresh
    // handler on every render and fire each action N times.
    if (this._bound) return;
    this._bound = true;

    this.shadowRoot.addEventListener("click", (event) => {
      const target = event.target.closest("[data-orb]");
      if (!target) return;
      const action = target.dataset.orb;
      const id = target.dataset.id;

      if (action === "scrim" && event.target === target) return this._close();
      if (action === "open") return this._openModal();
      if (action === "close") return this._close();
      if (action === "view") { this._view = id; this._error = ""; this._render(); return; }
      if (action === "kind") { this._captureDraft(); this._draft.kind = id; this._render(); return; }
      if (action === "sev") { this._captureDraft(); this._draft.severity = id; this._render(); return; }
      if (action === "payload") { this._captureDraft(); this._showsPayload = !this._showsPayload; this._render(); return; }
      if (action === "again") { this._sentRef = ""; this._error = ""; this._render(); return; }
      if (action === "enrol") return this._enrol();
      if (action === "submit") return this._submit();
      if (action === "read") return this._markRead(id);
      if (action === "readall") return this._markRead("");
      if (action === "leave") return this._setSetting("enabled", false);
      return undefined;
    });

    this.shadowRoot.addEventListener("change", (event) => {
      const accept = event.target.closest("[data-orb='accept-terms']");
      if (accept) {
        // Capture the typed code BEFORE re-rendering, or ticking the box would
        // wipe a code the tester just pasted — the exact papercut the focus
        // work exists to prevent.
        this._code = this.shadowRoot.getElementById("orb-code")?.value ?? this._code;
        this._acceptTerms = accept.checked;
        this._render();
        return;
      }
      const target = event.target.closest("[data-orb='toggle']");
      if (target) this._setSetting(target.dataset.id, target.checked);
    });

    // Remember which field is being edited so _restoreFocus can put the caret
    // back after the panel detaches and re-appends us.
    this.shadowRoot.addEventListener("focusin", (event) => {
      const id = event.target?.id;
      if (id) this._focusId = id;
    });
  }

  /** Keep what's typed when a chip click forces a re-render. */
  _captureDraft() {
    const body = this.shadowRoot.getElementById("orb-body");
    const intent = this.shadowRoot.getElementById("orb-intent");
    if (body) this._draft.body = body.value;
    if (intent) this._draft.intent = intent.value;
  }

  /* --- styles ---------------------------------------------------------- */

  _styles() {
    return `
      <style>
        :host { --orb-accent: var(--openreef-accent, #38bdf8); }
        * { box-sizing: border-box; }
        button, input, textarea { font: inherit; color: inherit; }
        button { cursor: pointer; }
        button:disabled { cursor: not-allowed; opacity: .45; }

        .orb-fab {
          position: fixed; right: 18px; bottom: 18px; z-index: 900;
          display: inline-flex; align-items: center; gap: 8px;
          padding: 11px 16px; border-radius: 999px;
          border: 1px solid var(--orb-accent); background: #121f2f; color: #e5edf5;
          box-shadow: 0 8px 28px rgba(0,0,0,.45);
          font-family: var(--ha-font-family-body, Arial, sans-serif); font-size: 14px; font-weight: 700;
          margin-bottom: env(safe-area-inset-bottom);
        }
        .orb-fab:hover { background: #172536; }
        .orb-fab-icon { font-size: 16px; }
        .orb-badge {
          min-width: 19px; height: 19px; padding: 0 5px; border-radius: 999px;
          background: #ef4444; color: #fff; font-size: 11px; font-weight: 800;
          display: inline-flex; align-items: center; justify-content: center;
        }
        .orb-badge[hidden] { display: none; }
        @media (max-width: 640px) {
          .orb-fab-label { display: none; }
          .orb-fab { right: 14px; bottom: 14px; padding: 13px; }
        }

        .orb-scrim {
          position: fixed; inset: 0; z-index: 950; background: rgba(3,10,17,.72);
          display: flex; align-items: center; justify-content: center; padding: 16px;
          font-family: var(--ha-font-family-body, Arial, sans-serif);
        }
        .orb-sheet {
          width: 100%; max-width: 560px; max-height: min(88vh, 780px);
          display: flex; flex-direction: column;
          background: #121f2f; color: #e5edf5;
          border: 1px solid #24364a; border-radius: 12px;
          box-shadow: 0 24px 60px rgba(0,0,0,.6);
          padding-bottom: env(safe-area-inset-bottom);
        }
        .orb-head {
          display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
          padding: 18px 20px 12px;
        }
        .orb-head h2 { margin: 0; font-size: 21px; color: var(--orb-accent); }
        .orb-eyebrow {
          margin: 0 0 4px; text-transform: uppercase; letter-spacing: .08em;
          font-size: 11px; font-weight: 700; color: #8da2ba;
        }
        .orb-icon {
          border: 1px solid #294055; background: #172536; border-radius: 8px;
          width: 32px; height: 32px; line-height: 1; flex: none;
        }
        .orb-nav { display: flex; gap: 6px; padding: 0 20px 10px; flex-wrap: wrap; }
        .orb-nav button {
          border: 1px solid #294055; background: #172536; border-radius: 999px;
          padding: 6px 12px; font-size: 12.5px; color: #cbd5e1;
          display: inline-flex; align-items: center; gap: 6px;
        }
        .orb-nav button.active { background: var(--orb-accent); border-color: var(--orb-accent); color: #041019; font-weight: 800; }
        .orb-dot {
          background: #ef4444; color: #fff; border-radius: 999px;
          min-width: 17px; height: 17px; font-size: 10.5px; font-weight: 800;
          display: inline-flex; align-items: center; justify-content: center; padding: 0 4px;
        }
        .orb-body { overflow-y: auto; padding: 4px 20px 20px; -webkit-overflow-scrolling: touch; }

        .orb-lede, .orb-fine { color: #8da2ba; line-height: 1.55; }
        .orb-lede { margin: 4px 0 14px; font-size: 14px; }
        .orb-fine { margin: 8px 0 0; font-size: 12px; }
        .orb-optional { color: #64748b; font-weight: 400; text-transform: none; letter-spacing: 0; }
        .orb-label {
          display: block; margin: 16px 0 7px; font-size: 11.5px; font-weight: 700;
          text-transform: uppercase; letter-spacing: .07em; color: #cbd5e1;
        }
        .orb-input {
          width: 100%; padding: 10px 12px; border-radius: 8px;
          border: 1px solid #294055; background: #0d1926; color: #e5edf5;
        }
        .orb-input:focus { outline: 2px solid var(--orb-accent); outline-offset: 1px; }
        .orb-textarea { resize: vertical; min-height: 104px; line-height: 1.5; }

        .orb-chips { display: flex; flex-wrap: wrap; gap: 7px; }
        .orb-chip {
          border: 1px solid #294055; background: #172536; border-radius: 999px;
          padding: 7px 13px; font-size: 13px; color: #dcecff;
        }
        .orb-chip.small { padding: 6px 11px; font-size: 12.5px; }
        .orb-chip:hover { border-color: var(--orb-accent); }
        .orb-chip.active { background: var(--orb-accent); border-color: var(--orb-accent); color: #041019; font-weight: 800; }
        .orb-chip.danger.active { background: #ef4444; border-color: #ef4444; color: #fff; }

        .orb-actions { display: flex; gap: 9px; flex-wrap: wrap; align-items: center; margin-top: 18px; }
        .orb-actions.end { justify-content: flex-end; margin-top: 0; }
        .orb-primary, .orb-secondary, .orb-danger {
          border-radius: 8px; padding: 10px 15px; border: 1px solid #294055; background: #172536; color: #dcecff;
        }
        .orb-primary { background: var(--orb-accent); border-color: var(--orb-accent); color: #041019; font-weight: 800; }
        .orb-danger { border-color: #7f1d1d; color: #fecaca; background: transparent; }
        .orb-secondary.small { padding: 6px 11px; font-size: 12.5px; }

        .orb-error, .orb-warn {
          margin: 12px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5;
        }
        .orb-error { background: #2b171c; border: 1px solid #7f1d1d; color: #fecaca; }
        .orb-warn { background: #2f2614; border: 1px solid #a16207; color: #fde68a; }
        .orb-warn.danger { background: #2b171c; border-color: #ef4444; color: #fecaca; }

        .orb-link { color: var(--orb-accent); text-decoration: underline; text-underline-offset: 2px; }
        .orb-disclose {
          display: block; margin-top: 16px; background: none; border: 0; padding: 0;
          color: #8da2ba; font-size: 12.5px; text-decoration: underline; text-underline-offset: 3px;
        }
        .orb-payload {
          margin-top: 9px; padding: 12px; border: 1px dashed #294055;
          border-radius: 8px; background: #0d1926;
        }
        .orb-meta { margin: 6px 0 0; padding-left: 18px; color: #8da2ba; font-size: 12.5px; line-height: 1.7; }
        .orb-pre {
          margin: 10px 0 0; max-height: 190px; overflow: auto; white-space: pre-wrap;
          word-break: break-word; font-size: 11px; line-height: 1.45; color: #94a3b8;
          background: #07111a; border: 1px solid #1e2d3d; border-radius: 6px; padding: 9px;
        }
        code { background: #0d1926; border-radius: 4px; padding: 1px 5px; font-size: 11.5px; }

        .orb-list { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 10px; }
        .orb-item { border: 1px solid #24364a; border-radius: 9px; padding: 13px; background: #0d1926; }
        .orb-item.unread { border-color: var(--orb-accent); }
        .orb-item-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 7px; }
        .orb-item-body { margin: 0; font-size: 13.5px; line-height: 1.55; white-space: pre-wrap; }
        .orb-ref { color: #64748b; }
        .orb-when { margin-left: auto; color: #64748b; font-size: 12px; }
        .orb-status { font-size: 11px; font-weight: 800; padding: 3px 9px; border-radius: 999px; }
        .tone-new { background: rgba(56,189,248,.16); color: #7dd3fc; }
        .tone-seen { background: #1e293b; color: #cbd5e1; }
        .tone-work { background: rgba(250,204,21,.14); color: #fde68a; }
        .tone-done { background: rgba(34,197,94,.15); color: #86efac; }
        .tone-closed { background: #1e293b; color: #94a3b8; }
        .orb-reply {
          margin-top: 10px; padding: 10px; border-left: 2px solid var(--orb-accent);
          background: #121f2f; border-radius: 0 8px 8px 0;
        }
        .orb-reply p { margin: 0; font-size: 13.5px; line-height: 1.55; }

        .orb-toggle { display: flex; gap: 11px; align-items: flex-start; margin-top: 15px; cursor: pointer; }
        .orb-toggle input { margin-top: 3px; width: 17px; height: 17px; accent-color: var(--orb-accent); flex: none; }
        .orb-toggle strong { display: block; font-size: 13.5px; }
        .orb-toggle em { display: block; margin-top: 3px; font-style: normal; font-size: 12px; color: #8da2ba; line-height: 1.55; }
        .orb-sep { height: 1px; background: #24364a; margin: 18px 0 4px; }

        .orb-sent { text-align: center; padding: 22px 0 6px; }
        .orb-sent-icon { font-size: 30px; margin: 0; }
        .orb-sent-title { margin: 9px 0 0; font-size: 17px; font-weight: 700; }
        .orb-sent .orb-actions { justify-content: center; }
      </style>
    `;
  }
}

if (!customElements.get("openreef-beta-fab")) {
  customElements.define("openreef-beta-fab", OpenReefBetaFab);
}
