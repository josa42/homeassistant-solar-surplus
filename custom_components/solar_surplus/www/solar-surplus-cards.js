// The traffic light as a dashboard card and a badge. Plain JS, no build step.
// PANEL_VERSION is the version of the integration's frontend; the release
// workflow bumps it here, in the panel and in const.py together.
const PANEL_VERSION = "0.4.0";

const DOMAIN = "solar_surplus";
const CARD = "solar-surplus-traffic-light-card";
const EDITOR = "solar-surplus-traffic-light-card-editor";
const BADGE = "solar-surplus-traffic-light-badge";

// Custom translation keys never reach hass.localize, so the strings the
// entity's own translations do not cover live here. The states come from
// hass.formatEntityState, which does know them.
const STRINGS = {
  en: {
    surplus: "{watts} surplus",
    card_name: "Solar Surplus traffic light",
    card_description: "Whether now is a good time to use power.",
    badge_name: "Solar Surplus traffic light",
    editor_entity: "Traffic light",
  },
  de: {
    surplus: "{watts} Überschuss",
    card_name: "Solar Surplus Ampel",
    card_description: "Ob gerade ein guter Moment ist, Strom zu verbrauchen.",
    badge_name: "Solar Surplus Ampel",
    editor_entity: "Ampel",
  },
};

const LIGHTS = {
  grid: { color: "var(--error-color, #db4437)", icon: "mdi:transmission-tower" },
  low: { color: "var(--warning-color, #ffa600)", icon: "mdi:weather-partly-cloudy" },
  plenty: { color: "var(--success-color, #43a047)", icon: "mdi:white-balance-sunny" },
};
const UNKNOWN = {
  color: "var(--state-unavailable-color, #bdbdbd)",
  icon: "mdi:white-balance-sunny",
};

function language(hass) {
  const lang = ((hass && (hass.locale?.language || hass.language)) || "en").split("-")[0];
  return STRINGS[lang] ? lang : "en";
}

function t(hass, key, values = {}) {
  const text = STRINGS[language(hass)][key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
}

/** What a card or badge shows for the traffic light's state. */
function display(hass, entityId) {
  const stateObj = hass.states[entityId];
  if (!stateObj) {
    return { ...UNKNOWN, label: entityId, detail: "" };
  }
  const light = LIGHTS[stateObj.state] || UNKNOWN;
  const label = hass.formatEntityState
    ? hass.formatEntityState(stateObj)
    : stateObj.state;
  const surplus = stateObj.attributes.surplus;
  let detail = "";
  if (light !== UNKNOWN && typeof surplus === "number") {
    const number = new Intl.NumberFormat(hass.locale?.language || "en", {
      maximumFractionDigits: 0,
    }).format(surplus);
    const watts = `${number} W`;
    detail = surplus > 0 ? t(hass, "surplus", { watts }) : watts;
  }
  return { ...light, label, detail };
}

/** The traffic light the card and the badge show unless told otherwise. */
function findTrafficLight(hass) {
  const entities = (hass && hass.entities) || {};
  return (
    Object.keys(entities).find(
      (id) =>
        entities[id].platform === DOMAIN &&
        entities[id].translation_key === "traffic_light"
    ) ||
    Object.keys((hass && hass.states) || {}).find((id) =>
      id.endsWith("_traffic_light")
    ) ||
    ""
  );
}

function moreInfo(element, entityId) {
  element.dispatchEvent(
    new CustomEvent("hass-more-info", {
      detail: { entityId },
      bubbles: true,
      composed: true,
    })
  );
}

const CARD_STYLE = `
  :host { display: block; height: 100%; }
  ha-card {
    height: 100%;
    min-height: 56px;
    box-sizing: border-box;
    padding: 0 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }
  ha-card:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .icon {
    flex: none;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--light);
    background: color-mix(in srgb, var(--light) 20%, transparent);
    --mdc-icon-size: 24px;
  }
  .text { display: flex; flex-direction: column; min-width: 0; }
  .label, .detail { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .label {
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 20px;
    color: var(--primary-text-color);
  }
  .detail {
    font-size: var(--ha-font-size-s, 12px);
    line-height: 16px;
    color: var(--secondary-text-color);
  }
`;

/** A tile: the light as a coloured icon, the state and the surplus. */
class TrafficLightCard extends HTMLElement {
  static getStubConfig(hass) {
    return { entity: findTrafficLight(hass) };
  }

  static async getConfigElement() {
    await customElements.whenDefined(EDITOR);
    return document.createElement(EDITOR);
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("You need to define an entity");
    }
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 1;
  }

  getGridOptions() {
    return { columns: 6, rows: 1, min_columns: 4, min_rows: 1 };
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CARD_STYLE;
    const card = document.createElement("ha-card");
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.addEventListener("click", () => moreInfo(this, this._config.entity));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        moreInfo(this, this._config.entity);
      }
    });
    const icon = document.createElement("div");
    icon.className = "icon";
    this._icon = document.createElement("ha-icon");
    icon.append(this._icon);
    const text = document.createElement("div");
    text.className = "text";
    this._label = document.createElement("span");
    this._label.className = "label";
    this._detail = document.createElement("span");
    this._detail.className = "detail";
    text.append(this._label, this._detail);
    card.append(icon, text);
    root.append(style, card);
    this._card = card;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._card) this._build();
    const shown = display(this._hass, this._config.entity);
    this._card.style.setProperty("--light", shown.color);
    this._icon.icon = shown.icon;
    this._label.textContent = shown.label;
    this._detail.textContent = shown.detail;
    this._detail.hidden = !shown.detail;
    this._card.setAttribute(
      "aria-label",
      shown.detail ? `${shown.label}, ${shown.detail}` : shown.label
    );
  }
}

const EDITOR_SCHEMA = [
  {
    name: "entity",
    required: true,
    selector: { entity: { filter: { integration: DOMAIN, domain: "sensor" } } },
  },
];

class TrafficLightCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      const form = document.createElement("ha-form");
      form.schema = EDITOR_SCHEMA;
      form.computeLabel = (schema) => t(this._hass, `editor_${schema.name}`);
      form.addEventListener("value-changed", (event) => {
        this._config = { ...this._config, ...event.detail.value };
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          })
        );
      });
      this._form = form;
      this.append(form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

const BADGE_STYLE = `
  :host { display: inline-block; }
  button {
    height: var(--ha-badge-size, 36px);
    box-sizing: border-box;
    padding: 0 12px 0 8px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: var(--ha-badge-border-radius, 18px);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    background: var(--ha-card-background, var(--card-background-color, #fff));
    box-shadow: var(--ha-card-box-shadow, none);
    color: var(--primary-text-color);
    font: inherit;
    cursor: pointer;
  }
  button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .dot { flex: none; width: 18px; height: 18px; border-radius: 50%; background: var(--light); }
  .label {
    font-size: var(--ha-font-size-s, 12px);
    font-weight: var(--ha-font-weight-medium, 500);
    white-space: nowrap;
  }
  .detail {
    font-size: var(--ha-font-size-s, 12px);
    color: var(--secondary-text-color);
    white-space: nowrap;
  }
`;

/** A badge: a dot in the light's colour, the state and the surplus. */
class TrafficLightBadge extends HTMLElement {
  static getStubConfig(hass) {
    return { entity: findTrafficLight(hass) };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("You need to define an entity");
    }
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = BADGE_STYLE;
    const button = document.createElement("button");
    button.type = "button";
    button.addEventListener("click", () => moreInfo(this, this._config.entity));
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");
    this._label = document.createElement("span");
    this._label.className = "label";
    this._detail = document.createElement("span");
    this._detail.className = "detail";
    button.append(dot, this._label, this._detail);
    root.append(style, button);
    this._button = button;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._button) this._build();
    const shown = display(this._hass, this._config.entity);
    this._button.style.setProperty("--light", shown.color);
    this._label.textContent = shown.label;
    // The badge is small: the figure without the word "surplus".
    const surplus = this._hass.states[this._config.entity]?.attributes.surplus;
    this._detail.textContent =
      shown.detail && typeof surplus === "number"
        ? `${new Intl.NumberFormat(this._hass.locale?.language || "en", {
            maximumFractionDigits: 0,
          }).format(surplus)} W`
        : "";
    this._detail.hidden = !this._detail.textContent;
  }
}

const REGISTRATIONS = [
  [CARD, TrafficLightCard],
  [EDITOR, TrafficLightCardEditor],
  [BADGE, TrafficLightBadge],
];

function register() {
  const registry = window.customElements;
  if (!registry) return;
  for (const [name, cls] of REGISTRATIONS) {
    if (registry.get(name)) continue;
    try {
      registry.define(name, cls);
    } catch (error) {
      console.error(`[${DOMAIN}] failed to define`, name, error);
    }
  }
}

register();

// HA swaps in a scoped custom elements polyfill while it boots, which can drop
// what was defined before. Re-assert until HA has booted; cheap.
let registerTicks = 0;
const registerTimer = setInterval(() => {
  register();
  if (++registerTicks >= 60) clearInterval(registerTimer);
}, 200);
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", register);
}
window.addEventListener("load", register);

const pickerLanguage = { locale: { language: navigator.language || "en" } };
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: t(pickerLanguage, "card_name"),
    description: t(pickerLanguage, "card_description"),
    preview: true,
  });
}
window.customBadges = window.customBadges || [];
if (!window.customBadges.some((badge) => badge.type === BADGE)) {
  window.customBadges.push({
    type: BADGE,
    name: t(pickerLanguage, "badge_name"),
    description: t(pickerLanguage, "card_description"),
    preview: true,
  });
}
