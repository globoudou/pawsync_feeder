/* Pawsync Feeder card — shipped with the pawsync_feeder integration.
 * Finds the feeder's entities by itself (device + translation keys), so no YAML
 * entity ids to edit. Config: { type: custom:pawsync-feeder-card, device?: <device_id>, title?: str }
 */
const DOMAIN = "pawsync_feeder";

const T = {
  fr: {
    hopper: "Réservoir", bowl: "Gamelle", next: "Prochain repas", eaten: "Mangé aujourd'hui",
    dispensed: "Distribué aujourd'hui", days: "Autonomie", lastMeal: "Dernier repas",
    feed: "Nourrir", confirm: "Confirmer ?", call: "Appeler", portion: "Portion",
    sleep: "Mode nuit", offline: "Hors ligne", bowlMissing: "Gamelle retirée",
    desiccant: "Déshydratant à changer", desiccantDays: "Déshydratant", noDevice: "Aucun distributeur Pawsync trouvé.",
    daysUnit: "j", ago: "il y a", tomorrow: "demain",
  },
  en: {
    hopper: "Hopper", bowl: "Bowl", next: "Next meal", eaten: "Eaten today",
    dispensed: "Dispensed today", days: "Food supply", lastMeal: "Last meal",
    feed: "Feed", confirm: "Confirm?", call: "Call", portion: "Portion",
    sleep: "Sleep mode", offline: "Offline", bowlMissing: "Bowl removed",
    desiccant: "Replace desiccant", desiccantDays: "Desiccant", noDevice: "No Pawsync feeder found.",
    daysUnit: "d", ago: "", tomorrow: "tomorrow",
  },
};

class PawsyncFeederCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "device", selector: { device: { integration: DOMAIN } } },
        { name: "title", selector: { text: {} } },
      ],
    };
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config || {};
    this._sig = undefined;
    this._confirmUntil = 0;
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    this._hass = hass;
    // Only redraw when one of this feeder's entities (or the language) changed.
    const deviceId = this._deviceId();
    const ids = deviceId ? Object.values(this._entities(deviceId)) : [];
    const sig = [hass.locale?.language, ...ids.map((id) => hass.states[id]?.last_updated + hass.states[id]?.state)].join("|");
    if (sig === this._sig && this.shadowRoot) return;
    this._sig = sig;
    this._render();
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return T[lang] || T.en;
  }

  _deviceId() {
    if (this._config.device) return this._config.device;
    const ent = Object.values(this._hass.entities || {}).find((e) => e.platform === DOMAIN && e.device_id);
    return ent?.device_id;
  }

  _entities(deviceId) {
    const map = {};
    for (const e of Object.values(this._hass.entities || {})) {
      if (e.platform !== DOMAIN || e.device_id !== deviceId) continue;
      const domain = e.entity_id.split(".")[0];
      let key = e.translation_key;
      if (!key && domain === "binary_sensor") {
        const st = this._hass.states[e.entity_id];
        if (st?.attributes?.device_class === "connectivity") key = "online";
      }
      if (key) map[`${domain}.${key}`] = e.entity_id;
    }
    return map;
  }

  _state(map, key) {
    const id = map[key];
    return id ? this._hass.states[id] : undefined;
  }

  _num(map, key) {
    const s = this._state(map, key);
    const v = s ? parseFloat(s.state) : NaN;
    return Number.isFinite(v) ? v : null;
  }

  _fmt(map, key, digits = 0) {
    const s = this._state(map, key);
    if (!s || ["unknown", "unavailable"].includes(s.state)) return "—";
    if (this._hass.formatEntityState) return this._hass.formatEntityState(s);
    const v = parseFloat(s.state);
    const unit = s.attributes.unit_of_measurement || "";
    return Number.isFinite(v) ? `${v.toFixed(digits)} ${unit}`.trim() : s.state;
  }

  _time(map, key, relative = false) {
    const s = this._state(map, key);
    if (!s || ["unknown", "unavailable"].includes(s.state)) return "—";
    const d = new Date(s.state);
    if (Number.isNaN(d.getTime())) return "—";
    const lang = this._hass.locale?.language || "fr";
    if (relative) {
      const mins = Math.round((Date.now() - d.getTime()) / 60000);
      const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
      if (Math.abs(mins) < 60) return rtf.format(-mins, "minute");
      if (Math.abs(mins) < 1440) return rtf.format(-Math.round(mins / 60), "hour");
      return rtf.format(-Math.round(mins / 1440), "day");
    }
    const hm = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    const today = new Date();
    return d.toDateString() === today.toDateString() ? hm : `${this._t.tomorrow} ${hm}`;
  }

  _press(entityId) {
    this._hass.callService("button", "press", { entity_id: entityId });
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = this._t;
    const deviceId = this._deviceId();
    if (!deviceId) {
      this.shadowRoot.innerHTML = `<ha-card><div class="empty">${t.noDevice}</div></ha-card>`;
      return;
    }
    const m = this._entities(deviceId);
    const device = this._hass.devices?.[deviceId];
    const title = this._config.title || device?.name_by_user || device?.name || "Pawsync";

    const online = this._state(m, "binary_sensor.online")?.state !== "off";
    const bowlProblem = this._state(m, "binary_sensor.bowl")?.state === "on";
    const desiccant = this._state(m, "binary_sensor.desiccant")?.state === "on";
    const hopper = this._num(m, "sensor.hopper_level");
    const bowl = this._num(m, "sensor.bowl_weight");
    const portion = this._num(m, "number.portion");
    const sleep = this._state(m, "switch.sleep_mode");
    const confirming = Date.now() < this._confirmUntil;

    const hopperPct = hopper == null ? 0 : Math.max(0, Math.min(100, hopper));
    const hopperColor = hopperPct < 15 ? "var(--error-color)" : hopperPct < 35 ? "var(--warning-color)" : "var(--success-color)";
    const bowlMax = Math.max(50, (portion || 11) * 4, bowl || 0);
    const bowlPct = bowl == null ? 0 : Math.min(100, (bowl / bowlMax) * 100);

    const alerts = [];
    if (!online) alerts.push(["mdi:wifi-off", t.offline]);
    if (bowlProblem) alerts.push(["mdi:bowl-outline", t.bowlMissing]);
    if (desiccant) alerts.push(["mdi:water-alert", t.desiccant]);

    const stat = (icon, label, value, key) => `
      <button class="stat" data-more="${m[key] || ""}">
        <ha-icon icon="${icon}"></ha-icon>
        <span class="label">${label}</span>
        <span class="value">${value}</span>
      </button>`;

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
        .head { display: flex; align-items: center; gap: 10px; }
        .head ha-icon { --mdc-icon-size: 28px; color: var(--primary-color); }
        .title { font-size: 1.2em; font-weight: 500; flex: 1; }
        .dot { width: 10px; height: 10px; border-radius: 50%; background: ${online ? "var(--success-color)" : "var(--error-color)"}; }
        .alerts { display: flex; flex-wrap: wrap; gap: 6px; }
        .alert { display: flex; align-items: center; gap: 4px; font-size: .85em; padding: 4px 10px; border-radius: 12px;
          background: rgba(var(--rgb-error-color, 219,68,55), .15); color: var(--error-color); }
        .alert ha-icon { --mdc-icon-size: 16px; }
        .bars { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .bar { cursor: pointer; }
        .bar .row { display: flex; justify-content: space-between; font-size: .9em; margin-bottom: 4px; }
        .bar .row b { font-weight: 600; }
        .track { height: 10px; border-radius: 5px; background: var(--divider-color); overflow: hidden; }
        .fill { height: 100%; border-radius: 5px; transition: width .4s; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .stat { all: unset; cursor: pointer; display: grid; grid-template-columns: 24px 1fr; grid-template-rows: auto auto;
          column-gap: 8px; padding: 8px 10px; border-radius: 12px; background: var(--secondary-background-color); }
        .stat ha-icon { grid-row: span 2; align-self: center; color: var(--secondary-text-color); --mdc-icon-size: 20px; }
        .stat .label { font-size: .75em; color: var(--secondary-text-color); }
        .stat .value { font-size: .95em; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .actions { display: flex; gap: 8px; align-items: stretch; }
        .btn { all: unset; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px;
          padding: 10px 14px; border-radius: 12px; font-weight: 500; background: var(--secondary-background-color); }
        .btn.feed { flex: 1; background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .btn.feed.confirm { background: var(--warning-color); }
        .btn[disabled] { opacity: .5; pointer-events: none; }
        .portion { display: flex; align-items: center; border-radius: 12px; background: var(--secondary-background-color); }
        .portion button { all: unset; cursor: pointer; padding: 10px; display: flex; }
        .portion span { min-width: 44px; text-align: center; font-weight: 500; }
        .sleep { display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
        .sleep .lbl { display: flex; align-items: center; gap: 8px; }
        .empty { padding: 16px; color: var(--secondary-text-color); }
      </style>
      <ha-card>
      <div class="head">
        <ha-icon icon="mdi:cat"></ha-icon>
        <div class="title">${title}</div>
        <div class="dot" title="${online ? "online" : t.offline}"></div>
      </div>
      ${alerts.length ? `<div class="alerts">${alerts.map(([i, l]) => `<div class="alert"><ha-icon icon="${i}"></ha-icon>${l}</div>`).join("")}</div>` : ""}
      <div class="bars">
        <div class="bar" data-more="${m["sensor.hopper_level"] || ""}">
          <div class="row"><span>${t.hopper}</span><b>${hopper == null ? "—" : Math.round(hopper) + " %"}</b></div>
          <div class="track"><div class="fill" style="width:${hopperPct}%;background:${hopperColor}"></div></div>
        </div>
        <div class="bar" data-more="${m["sensor.bowl_weight"] || ""}">
          <div class="row"><span>${t.bowl}</span><b>${this._fmt(m, "sensor.bowl_weight")}</b></div>
          <div class="track"><div class="fill" style="width:${bowlPct}%;background:var(--primary-color)"></div></div>
        </div>
      </div>
      <div class="stats">
        ${stat("mdi:clock-outline", t.next, `${this._time(m, "sensor.next_meal")} · ${this._fmt(m, "sensor.next_meal_amount")}`, "sensor.next_meal")}
        ${stat("mdi:cat", t.lastMeal, this._time(m, "sensor.last_eaten", true), "sensor.last_eaten")}
        ${stat("mdi:food", t.eaten, this._fmt(m, "sensor.eaten_today"), "sensor.eaten_today")}
        ${stat("mdi:shaker", t.dispensed, this._fmt(m, "sensor.dispensed_today"), "sensor.dispensed_today")}
        ${stat("mdi:calendar-clock", t.days, this._fmt(m, "sensor.food_days_left"), "sensor.food_days_left")}
        ${stat("mdi:water-percent", t.desiccantDays, this._fmt(m, "sensor.desiccant_days_left"), "sensor.desiccant_days_left")}
      </div>
      <div class="actions">
        <button class="btn feed ${confirming ? "confirm" : ""}" id="feed" ${!online || !m["button.feed"] ? "disabled" : ""}>
          <ha-icon icon="mdi:food-drumstick"></ha-icon>${confirming ? t.confirm : t.feed}
        </button>
        <div class="portion" title="${t.portion}">
          <button id="minus"><ha-icon icon="mdi:minus"></ha-icon></button>
          <span>${portion == null ? "—" : Math.round(portion) + " g"}</span>
          <button id="plus"><ha-icon icon="mdi:plus"></ha-icon></button>
        </div>
        <button class="btn" id="call" title="${t.call}" ${!online || !m["button.meal_call"] ? "disabled" : ""}><ha-icon icon="mdi:bullhorn"></ha-icon></button>
      </div>
      ${sleep ? `
      <div class="sleep" id="sleep">
        <div class="lbl"><ha-icon icon="${sleep.state === "on" ? "mdi:sleep" : "mdi:sleep-off"}"></ha-icon>${t.sleep}
          <span style="color:var(--secondary-text-color);font-size:.85em">${this._fmt(m, "time.sleep_start").slice(0, 5)} → ${this._fmt(m, "time.sleep_end").slice(0, 5)}</span></div>
        <ha-switch ${sleep.state === "on" ? "checked" : ""}></ha-switch>
      </div>` : ""}
      </ha-card>
    `;

    const root = this.shadowRoot;
    root.querySelectorAll("[data-more]").forEach((el) => {
      const id = el.dataset.more;
      if (!id) return;
      el.addEventListener("click", () =>
        this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: id }, bubbles: true, composed: true })),
      );
    });
    root.getElementById("feed")?.addEventListener("click", () => {
      if (Date.now() < this._confirmUntil) {
        this._confirmUntil = 0;
        this._press(m["button.feed"]);
      } else {
        this._confirmUntil = Date.now() + 3000;
        setTimeout(() => this._render(), 3100);
      }
      this._render();
    });
    root.getElementById("call")?.addEventListener("click", () => this._press(m["button.meal_call"]));
    const step = (delta) => {
      if (!m["number.portion"] || portion == null) return;
      const value = Math.max(1, Math.min(110, Math.round(portion) + delta));
      this._hass.callService("number", "set_value", { entity_id: m["number.portion"], value });
    };
    root.getElementById("minus")?.addEventListener("click", () => step(-1));
    root.getElementById("plus")?.addEventListener("click", () => step(1));
    root.getElementById("sleep")?.addEventListener("click", () =>
      this._hass.callService("switch", "toggle", { entity_id: m["switch.sleep_mode"] }),
    );
  }
}

if (!customElements.get("pawsync-feeder-card")) {
  customElements.define("pawsync-feeder-card", PawsyncFeederCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "pawsync-feeder-card",
    name: "Pawsync Feeder",
    description: "Distributeur de croquettes Pawsync",
    preview: true,
    documentationURL: "https://github.com/globoudou/pawsync_feeder",
  });
}
