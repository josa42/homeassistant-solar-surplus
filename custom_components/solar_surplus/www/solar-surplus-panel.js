// Solar Surplus panel.
//
// Registered by the integration via panel_custom. No build step and no
// dependencies: plain DOM in a shadow root, styled with Home Assistant's theme
// variables, so it works before (and without) any of the frontend's lazily
// loaded ha-* elements.
//
// Bump PANEL_VERSION here and in const.py together. The query string on the
// module URL is the only cache-buster.
const PANEL_VERSION = "0.3.0";

const NARROW_QUERY = "(max-width: 700px)";
const TABS = ["overview", "priority"];
// How many days back the forecast card goes: what the recorder keeps by default.
const HISTORY_DAYS = 7;
// Today's history is read again after this long.
const HISTORY_REFRESH = 60 * 1000;
const TAB_KEY = "solar-surplus-tab";

// The tab last open, for this viewer only. Storage can be missing or throw.
function storedTab() {
  try {
    const tab = window.localStorage.getItem(TAB_KEY);
    return TABS.includes(tab) ? tab : TABS[0];
  } catch {
    return TABS[0];
  }
}

// A line of [time, value] points cut to [start, end], with a point where it
// crosses either.
function clip(points, start, end) {
  const at = (a, b, time) => [time, a[1] + ((b[1] - a[1]) * (time - a[0])) / (b[0] - a[0])];
  const out = [];
  points.forEach((point, i) => {
    const previous = points[i - 1];
    if (previous && previous[0] < start && point[0] > start) out.push(at(previous, point, start));
    if (point[0] >= start && point[0] <= end) out.push(point);
    if (previous && previous[0] < end && point[0] > end) out.push(at(previous, point, end));
  });
  return out;
}

// The SG Ready states by the names a signal tells them by.
const SIGNAL_LEVELS = { 1: "blocked", 2: "normal", 3: "recommended", 4: "forced" };

// Home Assistant only ships a fixed set of translation categories to the
// frontend, and a custom panel's keys are not one of them, so the panel carries
// its own table.
const STRINGS = {
  en: {
    title: "Solar Surplus",
    loading: "Loading…",
    not_set_up: "Solar Surplus is not set up yet. Add it under Settings → Devices & Services.",
    error: "Something went wrong.",
    "control.on": "Control on",
    "control.off": "Control off",
    "control.banner": "Control is off: every decision is shown, but nothing is switched.",
    "test_mode.on": "Test mode on",
    "test_mode.off": "Test mode off",
    "test_mode.banner":
      "Test mode: nothing is switched. Consumers are shown as if they had been, and each change is sent as a notification.",
    "card.surplus": "Surplus",
    "card.surplus_raw": "now {value}",
    "card.grid": "Grid",
    "card.importing": "drawing",
    "card.exporting": "exporting",
    "card.battery": "Battery",
    "card.battery_charging": "charging",
    "card.battery_discharging": "discharging",
    "card.allocated": "Allocated",
    "card.remaining": "{value} left",
    "card.forecast": "Forecast",
    "forecast.none": "No forecast configured.",
    "forecast.remaining": "{value} left today",
    "forecast.threshold": "Base load and reserve",
    "forecast.threshold_learned": "Learned base load and reserve",
    "forecast.soc": "Battery charge",
    "forecast.soc_expected": "Expected charge",
    "forecast.total": "{value} expected",
    "forecast.today": "Today",
    "forecast.previous": "Previous day",
    "forecast.next": "Next day",
    "forecast.plan": "Consumers",
    "forecast.no_forecast": "No forecast for this day.",
    "legend.on": "On / recommended",
    "legend.forced": "Forced",
    "legend.blocked": "Locked / blocked",
    "legend.ran": "Ran",
    "legend.planned": "Expected",
    "tab.overview": "Overview",
    "tab.priority": "Priority",
    "list.title": "Priority",
    "list.hint": "Served from the top. Drag a row, or use the arrows, to change the order.",
    "list.empty": "No consumers yet. Add one on the integration's page.",
    "list.up": "Move up",
    "list.down": "Move down",
    "override.auto": "Auto",
    "override.on": "On",
    "override.off": "Off",
    "adapter.switch": "Switched",
    "adapter.number": "Variable",
    "adapter.sg_ready": "SG Ready",
    "adapter.script": "Scripts",
    "adapter.deferrable": "Deferrable",
    "adapter.signal": "Signal",
    "state.off": "Off",
    "state.on": "On",
    "state.locked": "Locked",
    "state.waiting": "Waiting",
    "state.running": "Running",
    "state.done": "Done",
    "state.idle": "Not ready",
    "state.unavailable": "Unavailable",
    "signal.blocked": "Blocked",
    "signal.normal": "Normal",
    "signal.recommended": "Recommended",
    "signal.forced": "Forced",
    "signal.unavailable": "Unavailable",
    "reason.override_on": "Switched on by hand",
    "reason.override_off": "Switched off by hand",
    "reason.unavailable": "An entity is unavailable",
    "reason.surplus": "Enough surplus",
    "reason.insufficient_surplus": "Not enough surplus: {available} of {needed}",
    "reason.on_delay": "Enough surplus; switches on at {until} if it holds",
    "reason.off_delay": "Too little surplus; switches off at {until} unless it comes back",
    "reason.min_on_time": "Minimum on time until {until}",
    "reason.min_off_time": "Minimum off time until {until}",
    "reason.forced_surplus": "Plenty of surplus: forced",
    "reason.grid_import": "Drawing from the grid: locked until {until} at most",
    "reason.grid_import_signal": "Drawing from the grid with the battery empty",
    "reason.lock_limit": "Lock limit reached; can lock again from {until}",
    "reason.not_ready": "Not ready",
    "reason.waiting_forecast": "Waiting for the best window from {expected_start}",
    "detail.expected": "expected {start}–{end}",
    "detail.solar_share": "{share} solar expected",
    "reason.waiting_deadline": "No surplus expected; starts at {latest_start}",
    "reason.deadline": "Started to be done by {deadline}",
    "reason.running": "Running since {started_at}",
    "reason.finished": "Done",
    "reason.no_data": "No grid reading",
    "detail.deadline": "done by {deadline}",
    "detail.latest_start": "starts by {latest_start} at the latest",
    "detail.expected_end": "until about {expected_end}",
  },
  de: {
    title: "Solarüberschuss",
    loading: "Lädt…",
    not_set_up:
      "Solarüberschuss ist noch nicht eingerichtet. Unter Einstellungen → Geräte & Dienste hinzufügen.",
    error: "Etwas ist schiefgegangen.",
    "control.on": "Steuerung an",
    "control.off": "Steuerung aus",
    "control.banner": "Die Steuerung ist aus: Alle Entscheidungen werden angezeigt, aber nichts wird geschaltet.",
    "test_mode.on": "Testmodus an",
    "test_mode.off": "Testmodus aus",
    "test_mode.banner":
      "Testmodus: Es wird nichts geschaltet. Die Verbraucher werden gezeigt, als wären sie geschaltet worden, und jede Änderung kommt als Benachrichtigung.",
    "card.surplus": "Überschuss",
    "card.surplus_raw": "gerade {value}",
    "card.grid": "Netz",
    "card.importing": "Bezug",
    "card.exporting": "Einspeisung",
    "card.battery": "Batterie",
    "card.battery_charging": "lädt",
    "card.battery_discharging": "entlädt",
    "card.allocated": "Verteilt",
    "card.remaining": "{value} übrig",
    "card.forecast": "Prognose",
    "forecast.none": "Keine Prognose eingerichtet.",
    "forecast.remaining": "heute noch {value}",
    "forecast.threshold": "Grundlast und Reserve",
    "forecast.threshold_learned": "Gelernte Grundlast und Reserve",
    "forecast.soc": "Batterieladung",
    "forecast.soc_expected": "Erwartete Ladung",
    "forecast.total": "{value} erwartet",
    "forecast.today": "Heute",
    "forecast.previous": "Vorheriger Tag",
    "forecast.next": "Nächster Tag",
    "forecast.plan": "Verbraucher",
    "forecast.no_forecast": "Keine Prognose für diesen Tag.",
    "legend.on": "Ein / empfohlen",
    "legend.forced": "Erzwungen",
    "legend.blocked": "Gesperrt",
    "legend.ran": "Lief",
    "legend.planned": "Voraussichtlich",
    "tab.overview": "Übersicht",
    "tab.priority": "Priorität",
    "list.title": "Priorität",
    "list.hint": "Von oben nach unten bedient. Zeile ziehen oder Pfeile nutzen, um die Reihenfolge zu ändern.",
    "list.empty": "Noch keine Verbraucher. Auf der Seite der Integration hinzufügen.",
    "list.up": "Nach oben",
    "list.down": "Nach unten",
    "override.auto": "Auto",
    "override.on": "Ein",
    "override.off": "Aus",
    "adapter.switch": "Geschaltet",
    "adapter.number": "Variabel",
    "adapter.sg_ready": "SG Ready",
    "adapter.script": "Skripte",
    "adapter.deferrable": "Aufschiebbar",
    "adapter.signal": "Signal",
    "state.off": "Aus",
    "state.on": "Ein",
    "state.locked": "Gesperrt",
    "state.waiting": "Wartet",
    "state.running": "Läuft",
    "state.done": "Fertig",
    "state.idle": "Nicht bereit",
    "state.unavailable": "Nicht verfügbar",
    "signal.blocked": "Gesperrt",
    "signal.normal": "Normal",
    "signal.recommended": "Empfohlen",
    "signal.forced": "Erzwungen",
    "signal.unavailable": "Nicht verfügbar",
    "reason.override_on": "Von Hand eingeschaltet",
    "reason.override_off": "Von Hand ausgeschaltet",
    "reason.unavailable": "Eine Entität ist nicht verfügbar",
    "reason.surplus": "Genug Überschuss",
    "reason.insufficient_surplus": "Zu wenig Überschuss: {available} von {needed}",
    "reason.on_delay": "Genug Überschuss; schaltet um {until} ein, wenn er hält",
    "reason.off_delay": "Zu wenig Überschuss; schaltet um {until} aus, wenn er nicht zurückkommt",
    "reason.min_on_time": "Mindestlaufzeit bis {until}",
    "reason.min_off_time": "Mindestpause bis {until}",
    "reason.forced_surplus": "Reichlich Überschuss: erzwungen",
    "reason.grid_import": "Netzbezug: gesperrt bis höchstens {until}",
    "reason.grid_import_signal": "Netzbezug bei leerer Batterie",
    "reason.lock_limit": "Sperrgrenze erreicht; wieder möglich ab {until}",
    "reason.not_ready": "Nicht bereit",
    "reason.waiting_forecast": "Wartet auf das beste Fenster ab {expected_start}",
    "detail.expected": "voraussichtlich {start}–{end}",
    "detail.solar_share": "voraussichtlich {share} Solar",
    "reason.waiting_deadline": "Kein Überschuss erwartet; startet um {latest_start}",
    "reason.deadline": "Gestartet, um bis {deadline} fertig zu sein",
    "reason.running": "Läuft seit {started_at}",
    "reason.finished": "Fertig",
    "reason.no_data": "Kein Netzwert",
    "detail.deadline": "fertig bis {deadline}",
    "detail.latest_start": "startet spätestens {latest_start}",
    "detail.expected_end": "bis etwa {expected_end}",
  },
};

const ICONS = {
  menu: "M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z",
  up: "M7.41 15.41 12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41Z",
  down: "M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41Z",
  drag: "M7 19v-2h2v2H7m4 0v-2h2v2h-2m4 0v-2h2v2h-2m-8-4v-2h2v2H7m4 0v-2h2v2h-2m4 0v-2h2v2h-2m-8-4V9h2v2H7m4 0V9h2v2h-2m4 0V9h2v2h-2M7 7V5h2v2H7m4 0V5h2v2h-2m4 0V5h2v2h-2Z",
  previous: "M15.41 16.58 10.83 12l4.58-4.59L14 6l-6 6 6 6 1.41-1.42Z",
  next: "M8.59 16.58 13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.42Z",
  calendar: "M19 19H5V8h14m-3-7v2H8V1H6v2H5c-1.11 0-2 .89-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-1V1m-1 11h-5v5h5v-5Z",
};

function language(hass) {
  const lang = ((hass && (hass.locale?.language || hass.language)) || "en").split("-")[0];
  return STRINGS[lang] ? lang : "en";
}

function t(hass, key, values = {}) {
  const table = STRINGS[language(hass)];
  let text = table[key] ?? STRINGS.en[key] ?? key;
  for (const [name, value] of Object.entries(values)) {
    text = text.replaceAll(`{${name}}`, value);
  }
  return text;
}

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  path.setAttribute("fill", "currentColor");
  svg.append(path);
  return svg;
}

function formatPower(hass, watts) {
  if (watts === null || watts === undefined || Number.isNaN(watts)) return "–";
  const lang = language(hass);
  const abs = Math.abs(watts);
  if (abs >= 1000) {
    return `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(watts / 1000)} kW`;
  }
  return `${new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(watts)} W`;
}

function formatEnergy(hass, wattHours) {
  const lang = language(hass);
  return `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(wattHours / 1000)} kWh`;
}

function timeZone(hass) {
  return hass?.locale?.time_zone === "local" ? undefined : hass?.config?.time_zone;
}

// A time today shows as 14:30, another day with its weekday in front.
function formatTime(hass, iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const lang = language(hass);
  const zone = timeZone(hass);
  const dayOf = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: zone, dateStyle: "short" }).format(d);
  const options = { ...clock(hass), minute: "2-digit", timeZone: zone };
  if (dayOf(date) !== dayOf(new Date())) options.weekday = "short";
  return new Intl.DateTimeFormat(lang, options).format(date);
}

// The day a moment falls on in the server's time zone, as YYYY-MM-DD.
function dayKey(hass, value) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: timeZone(hass), dateStyle: "short" }).format(new Date(value));
}

// How far the server's time zone is ahead of UTC at a moment, in ms.
function zoneOffset(hass, ms) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone(hass),
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(ms));
  const v = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return Date.UTC(+v.year, +v.month - 1, +v.day, +v.hour, +v.minute, +v.second) - Math.floor(ms / 1000) * 1000;
}

// Midnight of a day in the server's time zone.
function dayStart(hass, key) {
  const [year, month, day] = key.split("-").map(Number);
  const wall = Date.UTC(year, month - 1, day);
  return wall - zoneOffset(hass, wall - zoneOffset(hass, wall));
}

function shiftDay(key, days) {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

function dayLabel(hass, key) {
  const [year, month, day] = key.split("-").map(Number);
  // Noon UTC is the same calendar day in every time zone.
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  const options = { day: "numeric", month: "short", timeZone: "UTC" };
  if (year !== new Date().getFullYear()) options.year = "numeric";
  return new Intl.DateTimeFormat(language(hass), { weekday: "short", ...options }).format(date);
}

function formatShare(hass, share) {
  return new Intl.NumberFormat(language(hass), { style: "percent", maximumFractionDigits: 0 }).format(share);
}

function hourLabel(hass, iso) {
  const lang = language(hass);
  return new Intl.DateTimeFormat(lang, { ...clock(hass), timeZone: timeZone(hass) }).format(new Date(iso));
}

// The user's 12 or 24 hour clock, or the language's own.
function clock(hass) {
  const format = hass?.locale?.time_format;
  if (format === "12") return { hour: "numeric", hour12: true };
  if (format === "24") return { hour: "2-digit", hourCycle: "h23" };
  return { hour: "2-digit" };
}

// The reason, filled in with the figures behind it, plus what a deferrable
// consumer is working towards.
function reasonText(hass, consumer, plan) {
  const d = consumer.details || {};
  const values = {
    available: formatPower(hass, d.available),
    needed: formatPower(hass, d.needed),
    until: formatTime(hass, d.until),
    deadline: formatTime(hass, d.deadline),
    latest_start: formatTime(hass, d.latest_start),
    expected_start: formatTime(hass, d.expected_start),
    started_at: formatTime(hass, d.started_at),
    expected_end: formatTime(hass, d.expected_end),
  };
  const key = consumer.adapter === "signal" && consumer.reason === "grid_import" ? "grid_import_signal" : consumer.reason;
  const parts = [t(hass, `reason.${key}`, values)];
  if (consumer.adapter === "deferrable") {
    if (consumer.reason === "running" || (consumer.state === "running" && d.expected_end)) {
      parts.push(t(hass, "detail.expected_end", values));
    } else if (consumer.state === "waiting") {
      if (consumer.reason !== "waiting_deadline" && d.latest_start) parts.push(t(hass, "detail.latest_start", values));
      if (d.deadline) parts.push(t(hass, "detail.deadline", values));
      if (d.solar_share !== undefined && d.solar_share !== null) {
        parts.push(t(hass, "detail.solar_share", { share: formatShare(hass, d.solar_share) }));
      }
    }
  } else if (plan?.expected_on && !["on", "running"].includes(consumer.state)) {
    parts.push(t(hass, "detail.expected", { start: formatTime(hass, plan.expected_on), end: formatTime(hass, plan.expected_off) }));
  }
  return parts.filter(Boolean).join(" · ");
}

function wantsSidebarToggle(hass, narrow) {
  if (!hass || hass.kioskMode) return false;
  return Boolean(narrow || hass.dockedSidebar === "always_hidden");
}

const STYLE = `
  :host {
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
    box-sizing: border-box;
    background: var(--primary-background-color, #f5f5f5);
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
    --ss-gap: 16px;
    --ss-on: var(--success-color, #43a047);
    --ss-wait: var(--warning-color, #ffa600);
    --ss-off: var(--disabled-text-color, #9e9e9e);
    --ss-locked: var(--error-color, #db4437);
    --ss-run: var(--info-color, #039be5);
    --ss-soc: var(--energy-battery-out-color, #4db6ac);
  }
  .toolbar {
    flex: 0 0 var(--header-height, 56px);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    box-sizing: border-box;
    background: var(--app-header-background-color, var(--primary-color, #03a9f4));
    color: var(--app-header-text-color, #fff);
    border-bottom: var(--app-header-border-bottom, none);
  }
  .toolbar .title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--ha-font-size-xl, 20px);
    padding-inline-start: 12px;
  }
  .toolbar .title.with-icon { padding-inline-start: 0; }
  .tabs {
    flex: 0 0 auto;
    display: flex;
    gap: 4px;
    padding: 0 12px;
    overflow-x: auto;
    background: var(--app-header-background-color, var(--primary-color, #03a9f4));
    color: var(--app-header-text-color, #fff);
  }
  .tab {
    border: 0;
    background: none;
    color: inherit;
    opacity: 0.75;
    padding: 12px 20px 10px;
    border-bottom: 2px solid transparent;
    font-size: var(--ha-font-size-m, 14px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .tab:hover { opacity: 1; }
  .tab.active { opacity: 1; border-bottom-color: currentColor; }
  button {
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  button:disabled { cursor: default; opacity: 0.4; }
  .icon-button {
    border: 0;
    background: none;
    padding: 8px;
    border-radius: 50%;
    line-height: 0;
  }
  .icon-button:hover:not(:disabled) { background: rgba(127, 127, 127, 0.16); }
  .control {
    border: 1px solid currentColor;
    background: none;
    border-radius: 999px;
    padding: 6px 14px;
    font-size: var(--ha-font-size-s, 13px);
    white-space: nowrap;
  }
  .control.off { opacity: 0.75; }
  .control.test.off { opacity: 0.6; }
  .control.test:not(.off) {
    background: var(--warning-color, #ff9800);
    border-color: var(--warning-color, #ff9800);
    color: var(--text-primary-color, #fff);
  }
  main {
    flex: 1;
    overflow: auto;
    padding: var(--ss-gap);
    padding-bottom: calc(var(--ss-gap) + env(safe-area-inset-bottom, 0px));
  }
  .content {
    max-width: 960px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: var(--ss-gap);
  }
  .banner, .message {
    padding: 12px 16px;
    border-radius: var(--ha-card-border-radius, 12px);
    background: var(--secondary-background-color, #e5e5e5);
  }
  .banner {
    background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, var(--card-background-color, #fff));
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: var(--ss-gap);
  }
  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    padding: 16px;
    box-sizing: border-box;
    min-width: 0;
  }
  .card h2 {
    margin: 0 0 8px;
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .stat .label {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
  }
  .stat .value {
    font-size: 26px;
    line-height: 1.3;
    font-weight: var(--ha-font-weight-normal, 400);
    white-space: nowrap;
  }
  .stat .sub {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
    min-height: 1.2em;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: var(--ha-font-size-s, 13px);
    white-space: nowrap;
    background: color-mix(in srgb, var(--chip-color) 18%, transparent);
    color: var(--primary-text-color, #212121);
    border: 1px solid color-mix(in srgb, var(--chip-color) 60%, transparent);
    --chip-color: var(--ss-off);
  }
  .chip.on, .chip.recommended { --chip-color: var(--ss-on); }
  .chip.forced, .chip.running { --chip-color: var(--ss-run); }
  .chip.waiting { --chip-color: var(--ss-wait); }
  .chip.locked, .chip.blocked, .chip.unavailable { --chip-color: var(--ss-locked); }
  .forecast .head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .forecast .head h2 { margin: 0; flex: 1; }
  .forecast .day { display: flex; align-items: center; gap: 2px; }
  .forecast .day .date {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-inline-end: 6px;
    font-size: var(--ha-font-size-m, 14px);
    white-space: nowrap;
  }
  .forecast .day .today {
    border: 0;
    border-radius: 999px;
    padding: 6px 12px;
    font-size: var(--ha-font-size-s, 13px);
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 18%, transparent);
    color: var(--primary-color, #03a9f4);
  }
  .forecast .day .today:disabled { visibility: hidden; }
  .forecast .chart { position: relative; }
  .forecast .now-line {
    position: absolute;
    z-index: 1;
    top: 0;
    bottom: 0;
    width: 0;
    border-left: 2px solid var(--primary-color, #03a9f4);
    pointer-events: none;
  }
  .forecast .plot { position: relative; }
  .forecast .plot > svg { display: block; width: 100%; height: 120px; }
  .forecast .grid { stroke: var(--divider-color, rgba(0, 0, 0, 0.12)); }
  .forecast .axis { position: absolute; z-index: 2; inset: 0; pointer-events: none; }
  /* Text the line of the current time passes behind. */
  .forecast .axis span,
  .forecast .hours b,
  .forecast .plan h3,
  .forecast .plan-row .name {
    position: relative;
    z-index: 2;
    width: fit-content;
    background: var(--ha-card-background, var(--card-background-color, #fff));
  }
  .forecast .hours b { font-weight: inherit; padding: 0 2px; }
  .forecast .axis span { position: absolute; }
  .forecast .axis span {
    position: absolute;
    left: 0;
    transform: translateY(-50%);
    padding: 0 4px 0 0;
    color: var(--secondary-text-color, #727272);
    background: var(--ha-card-background, var(--card-background-color, #fff));
    font-size: 11px;
    line-height: 14px;
  }
  .forecast .axis.right span { left: auto; right: 0; padding: 0 0 0 4px; color: var(--ss-soc); }
  .forecast .hours {
    display: flex;
    color: var(--secondary-text-color, #727272);
    font-size: 11px;
    margin-top: 2px;
  }
  .forecast .hours span { flex: 1 1 0; min-width: 0; text-align: center; white-space: nowrap; overflow: visible; }
  .forecast .bar { fill: color-mix(in srgb, var(--warning-color, #ffa600) 70%, transparent); }
  .forecast .bar.past { fill: color-mix(in srgb, var(--warning-color, #ffa600) 35%, transparent); }
  .forecast .threshold { fill: none; stroke: var(--secondary-text-color, #727272); stroke-dasharray: 4 3; }
  .forecast path.soc { fill: none; stroke: var(--ss-soc); stroke-width: 2; stroke-linejoin: round; }
  .forecast path.soc.planned { stroke-dasharray: 5 4; opacity: 0.8; }
  .forecast .legend .keys { display: inline-flex; flex-wrap: wrap; gap: 4px 14px; }
  .forecast .legend .keys span { display: inline-flex; align-items: center; gap: 6px; }
  .forecast .legend i.soc { display: inline-block; width: 18px; height: 0; border-top: 2px solid var(--ss-soc); }
  .forecast .legend i.soc.planned { border-top-style: dashed; opacity: 0.8; }
  .forecast .plan { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
  .forecast .plan h3 {
    margin: 0;
    font-size: var(--ha-font-size-s, 13px);
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
  }
  .forecast .plan-row .name { font-size: var(--ha-font-size-s, 13px); }
  .forecast .track {
    position: relative;
    height: 10px;
    border-radius: 5px;
    background: color-mix(in srgb, var(--secondary-text-color, #727272) 12%, transparent);
  }
  .forecast .run {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 5px;
    background: var(--ss-on);
  }
  .forecast .run.forced { background: var(--ss-run); }
  .forecast .run.blocked { background: var(--ss-locked); }
  .forecast .run.planned { opacity: 0.45; }
  .forecast .key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
  }
  .forecast .key span { display: inline-flex; align-items: center; gap: 6px; }
  .forecast .key i {
    display: inline-block;
    width: 18px;
    height: 8px;
    border-radius: 4px;
    background: var(--ss-on);
  }
  .forecast .key i.forced { background: var(--ss-run); }
  .forecast .key i.blocked { background: var(--ss-locked); }
  .forecast .key i.planned { opacity: 0.45; }
  .forecast .key i.neutral { background: var(--secondary-text-color, #727272); }
  .forecast .legend {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
    margin-top: 4px;
  }
  .hint {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
    margin: 0 0 8px;
  }
  ol.list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li.row {
    display: grid;
    grid-template-columns: auto auto 1fr auto;
    grid-template-areas: "handle pos main side";
    align-items: center;
    gap: 4px 12px;
    padding: 10px 4px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
    background: var(--card-background-color, #fff);
  }
  li.row:first-child { border-top: 0; }
  li.row.dragging { opacity: 0.4; }
  li.row.drop-before { box-shadow: inset 0 2px 0 var(--primary-color, #03a9f4); }
  li.row.drop-after { box-shadow: inset 0 -2px 0 var(--primary-color, #03a9f4); }
  .handle { grid-area: handle; color: var(--secondary-text-color, #727272); cursor: grab; line-height: 0; }
  .pos {
    grid-area: pos;
    width: 24px;
    text-align: center;
    color: var(--secondary-text-color, #727272);
    font-variant-numeric: tabular-nums;
  }
  .main { grid-area: main; min-width: 0; }
  .name {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .kind {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
    font-weight: var(--ha-font-weight-normal, 400);
  }
  .reason {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 13px);
    margin-top: 2px;
  }
  .side {
    grid-area: side;
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: flex-end;
  }
  .power {
    min-width: 64px;
    text-align: end;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 999px;
    overflow: hidden;
  }
  .segmented button {
    border: 0;
    background: none;
    padding: 4px 10px;
    font-size: var(--ha-font-size-s, 13px);
  }
  .segmented button + button { border-inline-start: 1px solid var(--divider-color, #e0e0e0); }
  .segmented button.active {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }
  .arrows { display: inline-flex; flex-direction: column; }
  .arrows .icon-button { padding: 0 4px; }
  @media ${NARROW_QUERY} {
    :host { --ss-gap: 12px; }
    li.row {
      grid-template-columns: auto 1fr;
      grid-template-areas: "pos main" "pos side";
    }
    .handle { display: none; }
    .side { justify-content: flex-start; flex-wrap: wrap; }
    .power { min-width: 0; text-align: start; }
    .side .arrows { flex-direction: row; margin-inline-start: auto; }
    .stat .value { font-size: 22px; }
    .control { padding: 6px 10px; }
  }
`;

class SolarSurplusPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = null;
    this._error = null;
    this._unsub = null;
    this._subscribing = false;
    this._dragId = null;
    // The day the forecast shows; null follows today.
    this._day = null;
    this._tab = storedTab();
    // Past runs per day, read from the history.
    this._history = {};
  }

  set hass(hass) {
    const previous = this._hass;
    this._hass = hass;
    if (!previous) {
      this._subscribe();
      this._render();
      return;
    }
    // A new hass arrives with every state change anywhere, far too often to
    // repaint on. Only the language and the sidebar setting matter here; the
    // data comes through the subscription.
    const narrow = this._isNarrow();
    if (
      language(previous) !== language(hass) ||
      wantsSidebarToggle(previous, narrow) !== wantsSidebarToggle(hass, narrow)
    ) {
      this._render();
    }
  }

  set narrow(value) {
    const changed = this._narrow !== value;
    this._narrow = value;
    if (changed) this._render();
  }

  set panel(value) {
    this._panel = value;
  }

  _isNarrow() {
    return Boolean(this._narrow || (this._mql && this._mql.matches));
  }

  get _isAdmin() {
    return Boolean(this._hass?.user?.is_admin);
  }

  connectedCallback() {
    if (!this._mql && typeof window.matchMedia === "function") {
      this._mql = window.matchMedia(NARROW_QUERY);
      this._onNarrowChange = () => this._render();
      this._mql.addEventListener("change", this._onNarrowChange);
    }
    if (this._hass && !this._unsub && !this._subscribing) this._subscribe();
    this._render();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    if (this._mql) {
      this._mql.removeEventListener("change", this._onNarrowChange);
      this._mql = null;
    }
  }

  async _subscribe() {
    if (this._subscribing || this._unsub || !this._hass) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage((state) => this._onState(state), {
        type: "solar_surplus/subscribe",
      });
      this._error = null;
    } catch (err) {
      this._error = err?.code === "not_found" ? t(this._hass, "not_set_up") : err?.message || t(this._hass, "error");
      this._render();
    } finally {
      this._subscribing = false;
    }
  }

  _onState(state) {
    this._state = state;
    this._error = null;
    // A drag in progress would lose its row to a repaint; the next push after
    // the drop catches up.
    if (!this._dragId) this._render();
  }

  async _call(message) {
    try {
      const state = await this._hass.callWS(message);
      this._onState(state);
    } catch (err) {
      this._error = err?.message || t(this._hass, "error");
      this._render();
    }
  }

  _order() {
    const state = this._state;
    const order = state?.decision?.order;
    if (order) return order;
    return Object.keys(state?.consumers || {});
  }

  _move(id, offset) {
    const order = this._order().slice();
    const from = order.indexOf(id);
    const to = from + offset;
    if (from < 0 || to < 0 || to >= order.length) return;
    order.splice(from, 1);
    order.splice(to, 0, id);
    this._reorder(order);
  }

  _reorder(order) {
    if (this._state?.decision) this._state.decision.order = order;
    this._render();
    this._call({ type: "solar_surplus/reorder", order });
  }

  _render() {
    if (!this.shadowRoot) return;
    const hass = this._hass;
    const narrow = this._isNarrow();
    const toolbar = h("div", { class: "toolbar" });
    const showToggle = wantsSidebarToggle(hass, narrow);
    if (showToggle) {
      const menu = h("button", {
        class: "icon-button",
        title: "Menu",
        "aria-label": "Menu",
        onClick: () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })),
      });
      menu.append(icon("menu"));
      toolbar.append(menu);
    }
    toolbar.append(h("div", { class: `title${showToggle ? " with-icon" : ""}`, text: t(hass, "title") }));
    if (this._state) {
      const enabled = this._state.control_enabled;
      const testing = !!this._state.test_mode;
      toolbar.append(
        h("button", {
          class: `control test${testing ? "" : " off"}`,
          text: t(hass, testing ? "test_mode.on" : "test_mode.off"),
          disabled: !this._isAdmin,
          "aria-pressed": String(testing),
          onClick: () => this._call({ type: "solar_surplus/set_test_mode", enabled: !testing }),
        }),
        h("button", {
          class: `control${enabled ? "" : " off"}`,
          text: t(hass, enabled ? "control.on" : "control.off"),
          disabled: !this._isAdmin,
          "aria-pressed": String(enabled),
          onClick: () => this._call({ type: "solar_surplus/set_control", enabled: !enabled }),
        })
      );
    }

    const tabs = h("div", { class: "tabs", role: "tablist" });
    for (const tab of TABS) {
      tabs.append(
        h("button", {
          class: `tab${tab === this._tab ? " active" : ""}`,
          role: "tab",
          "aria-selected": String(tab === this._tab),
          text: t(hass, `tab.${tab}`),
          onClick: () => this._showTab(tab),
        })
      );
    }

    const content = h("div", { class: "content" });
    if (this._error) content.append(h("div", { class: "message", text: this._error }));
    if (!this._state) {
      if (!this._error) content.append(h("div", { class: "message", text: t(hass, "loading") }));
    } else {
      if (!this._state.control_enabled) content.append(h("div", { class: "banner", text: t(hass, "control.banner") }));
      else if (this._state.test_mode) content.append(h("div", { class: "banner", text: t(hass, "test_mode.banner") }));
      if (this._tab === "priority") content.append(this._renderList());
      else content.append(this._renderCards(), this._renderForecast());
    }

    this.shadowRoot.replaceChildren(h("style", { text: STYLE }), toolbar, tabs, h("main", {}, content));
  }

  _showTab(tab) {
    if (tab === this._tab) return;
    this._tab = tab;
    try {
      window.localStorage.setItem(TAB_KEY, tab);
    } catch {
      // Remembering the tab is a convenience; without storage it is not kept.
    }
    this._render();
  }

  _stat(label, value, sub, extra) {
    return h(
      "div",
      { class: "card stat" },
      h("div", { class: "label", text: label }),
      extra || h("div", { class: "value", text: value }),
      h("div", { class: "sub", text: sub || "" })
    );
  }

  _renderCards() {
    const hass = this._hass;
    const decision = this._state.decision || {};
    const cards = h("div", { class: "cards" });
    cards.append(
      this._stat(
        t(hass, "card.surplus"),
        formatPower(hass, decision.surplus),
        decision.surplus_raw !== null && decision.surplus_raw !== undefined && decision.surplus_raw !== decision.surplus
          ? t(hass, "card.surplus_raw", { value: formatPower(hass, decision.surplus_raw) })
          : ""
      )
    );
    const grid = decision.grid;
    cards.append(
      this._stat(
        t(hass, "card.grid"),
        formatPower(hass, grid === null || grid === undefined ? null : Math.abs(grid)),
        grid === null || grid === undefined ? "" : t(hass, grid > 0 ? "card.importing" : "card.exporting")
      )
    );
    if (decision.battery !== null && decision.battery !== undefined) {
      const soc = decision.soc !== null && decision.soc !== undefined ? `${Math.round(decision.soc)} %` : "";
      const flow =
        decision.battery > 0
          ? t(hass, "card.battery_charging")
          : decision.battery < 0
            ? t(hass, "card.battery_discharging")
            : "";
      cards.append(
        this._stat(
          t(hass, "card.battery"),
          soc || formatPower(hass, Math.abs(decision.battery)),
          [soc ? formatPower(hass, Math.abs(decision.battery)) : "", flow].filter(Boolean).join(" ")
        )
      );
    }
    cards.append(
      this._stat(
        t(hass, "card.allocated"),
        formatPower(hass, decision.allocated),
        t(hass, "card.remaining", { value: formatPower(hass, decision.remaining) })
      )
    );
    return cards;
  }

  _renderForecast() {
    const hass = this._hass;
    const card = h("div", { class: "card forecast" });
    const periods = this._state.decision?.forecast || [];
    if (!this._state.has_forecast && !Object.values(this._state.consumers || {}).length) {
      card.append(h("h2", { text: t(hass, "card.forecast") }), h("div", { class: "hint", text: t(hass, "forecast.none") }));
      return card;
    }
    const now = Date.now();
    const today = dayKey(hass, now);
    const past = Array.from({ length: HISTORY_DAYS }, (_, i) => shiftDay(today, i - HISTORY_DAYS));
    const days = [...new Set([...past, today, ...periods.map((p) => dayKey(hass, p.start))])].sort();
    if (!days.includes(this._day)) this._day = null;
    const day = this._day || today;
    const index = days.indexOf(day);
    card.append(h("div", { class: "head" }, h("h2", { text: t(hass, "card.forecast") }), this._dayNav(day, today, days, index)));

    const shown = periods.filter((p) => dayKey(hass, p.start) === day);
    // The forecast's periods are the axis; a day without them gets hours.
    let bounds = shown.map((p) => [new Date(p.start).getTime(), new Date(p.end).getTime()]);
    // The hours of the day the forecast leaves out, the night mostly, so the
    // day always runs from midnight to midnight.
    const midnight = dayStart(hass, day);
    const nextMidnight = dayStart(hass, shiftDay(day, 1));
    // As long as the forecast's own periods, so the slots stay even.
    const length = bounds.length ? bounds[0][1] - bounds[0][0] : 3600000;
    const before = [];
    for (let end = bounds.length ? bounds[0][0] : nextMidnight; end > midnight; end -= length) {
      before.unshift([Math.max(end - length, midnight), end]);
    }
    const after = [];
    if (bounds.length) {
      for (let start = bounds[bounds.length - 1][1]; start < nextMidnight; start += length) {
        after.push([start, Math.min(start + length, nextMidnight)]);
      }
    }
    const offset = before.length;
    bounds = [...before, ...bounds, ...after];
    const first = bounds[0][0];
    const last = bounds[bounds.length - 1][1];
    const isToday = day === today;
    const total = shown.reduce((sum, p) => {
      const start = isToday ? Math.max(new Date(p.start).getTime(), now) : new Date(p.start).getTime();
      const end = new Date(p.end).getTime();
      return end > start ? sum + (p.watts * (end - start)) / 3600000 : sum;
    }, 0);
    const settings = this._state.settings || {};
    // The base load learned for each hour of the day, or the one set.
    const learned = settings.base_load_hours || {};
    const thresholdAt = (ms) => {
      const hour = new Date(ms + zoneOffset(hass, ms)).getUTCHours();
      return (learned[hour] ?? settings.base_load ?? 0) + (settings.reserve || 0);
    };
    const thresholds = bounds.map(([start]) => thresholdAt(start));
    // The scale ends on a round step, so the axis reads 0, 1 kW, 2 kW, …
    const highest = Math.max(...thresholds, ...periods.map((p) => p.watts), 1);
    const step = [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000].find((s) => highest / s <= 4) || 50000;
    const peak = Math.ceil(highest / step) * step;

    const at = (value) => {
      const time = new Date(value).getTime();
      if (time <= first) return 0;
      for (let i = 0; i < bounds.length; i++) {
        const [start, end] = bounds[i];
        if (time <= end) return (i + Math.max(0, time - start) / (end - start)) / bounds.length;
      }
      return 1;
    };
    const width = 480;
    const height = 120;
    const plot = height;
    const slot = width / bounds.length;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t(hass, "card.forecast"));
    shown.forEach((p, i) => {
      const barHeight = (p.watts / peak) * (plot - 4);
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("class", `bar${new Date(p.end).getTime() <= now ? " past" : ""}`);
      rect.setAttribute("x", String((i + offset) * slot + 1));
      rect.setAttribute("y", String(plot - barHeight));
      rect.setAttribute("width", String(Math.max(slot - 2, 1)));
      rect.setAttribute("height", String(Math.max(barHeight, 0)));
      const title = document.createElementNS(ns, "title");
      title.textContent = `${formatTime(hass, p.start)}: ${formatPower(hass, p.watts)}`;
      rect.append(title);
      svg.append(rect);
    });
    if (shown.length) {
      // A step per hour: what the hour has to clear.
      const y = (value) => (plot - (value / peak) * (plot - 4)).toFixed(1);
      const d = thresholds.map((value, i) => `${i ? "H" : "M"}${(i * slot).toFixed(1)}${i ? "V" : " "}${y(value)}`).join("");
      const line = document.createElementNS(ns, "path");
      line.setAttribute("class", "threshold");
      line.setAttribute("d", `${d}H${width}`);
      line.setAttribute("vector-effect", "non-scaling-stroke");
      svg.append(line);
    }
    // The battery's charge over the bars, on a scale of its own: 0 to 100 %.
    const soc = [...(this._history[day]?.soc || [])];
    const current = this._state.decision?.soc;
    if (isToday && soc.length && current !== null && current !== undefined) soc.push([now, current]);
    // What the plan expects of it, from now on, cut to the day: where it
    // crosses midnight, at the charge it has then.
    const expected = clip(
      (this._state.decision?.soc_forecast || []).map((point) => [new Date(point.time).getTime(), point.soc]),
      first,
      last
    );
    const point = ([time, value]) => {
      const x = (at(time) * width).toFixed(1);
      const y = (plot - (Math.min(Math.max(value, 0), 100) / 100) * (plot - 4)).toFixed(1);
      return [x, y];
    };
    const socLine = (points, cls, step) => {
      if (!points.length) return;
      const d = points
        .map((p, i) => {
          const [x, y] = point(p);
          // The history holds a value until the next; the plan moves along.
          if (!i) return `M${x} ${y}`;
          return step ? `H${x}V${y}` : `L${x} ${y}`;
        })
        .join("");
      const path = document.createElementNS(ns, "path");
      path.setAttribute("class", cls);
      path.setAttribute("d", d);
      path.setAttribute("vector-effect", "non-scaling-stroke");
      svg.append(path);
    };
    socLine(soc, "soc", true);
    socLine(expected, "soc planned", false);
    // The hours go below in HTML: the SVG stretches to the card's width, and
    // text inside it would stretch along.
    const every = Math.max(1, Math.ceil(bounds.length / 8));
    const hours = h("div", { class: "hours" });
    bounds.forEach(([start], i) => hours.append(h("span", {}, i % every === 0 ? h("b", { text: hourLabel(hass, start) }) : "")));

    const chart = h("div", { class: "chart" });
    if (shown.length || soc.length || expected.length) {
      const ticks = Array.from({ length: Math.round(peak / step) + 1 }, (_, i) => i * step);
      // Faint lines behind the bars, one per step.
      for (const value of ticks.slice(1)) {
        const y = String(plot - (value / peak) * (plot - 4));
        const line = document.createElementNS(ns, "line");
        line.setAttribute("class", "grid");
        line.setAttribute("x1", "0");
        line.setAttribute("x2", String(width));
        line.setAttribute("y1", y);
        line.setAttribute("y2", y);
        line.setAttribute("vector-effect", "non-scaling-stroke");
        svg.prepend(line);
      }
      // The labels are HTML over the SVG, which stretches and would stretch
      // text along.
      const top = (value, scale) => `${((plot - (value / scale) * (plot - 4)) / plot) * 100}%`;
      const axis = h("div", { class: "axis" });
      for (const value of ticks.slice(1)) {
        const label = h("span", { text: formatPower(hass, value) });
        label.style.top = top(value, peak);
        axis.append(label);
      }
      const box = h("div", { class: "plot" }, svg, axis);
      if (soc.length || expected.length) {
        const right = h("div", { class: "axis right" });
        for (const value of [50, 100]) {
          const label = h("span", { text: `${value} %` });
          label.style.top = top(value, 100);
          right.append(label);
        }
        box.append(right);
      }
      chart.append(box);
    }
    if (!shown.length) chart.append(h("div", { class: "hint", text: t(hass, this._state.has_forecast ? "forecast.no_forecast" : "forecast.none") }));
    chart.append(hours, this._renderTracks(at, first, last, now));
    if (isToday) chart.append(this._nowLine(at(now), now));
    const legend = h("div", { class: "legend" });
    legend.append(
      h("span", {
        text: shown.length
          ? t(hass, isToday ? "forecast.remaining" : "forecast.total", { value: formatEnergy(hass, total) })
          : "",
      })
    );
    const keys = h("span", { class: "keys" });
    if (shown.length) {
      const low = Math.min(...thresholds);
      const high = Math.max(...thresholds);
      const range = low === high ? formatPower(hass, low) : `${formatPower(hass, low)}–${formatPower(hass, high)}`;
      const label = t(hass, Object.keys(learned).length ? "forecast.threshold_learned" : "forecast.threshold");
      keys.append(h("span", { text: `– – ${label} (${range})` }));
    }
    if (soc.length) {
      const latest = soc[soc.length - 1][1];
      keys.append(h("span", {}, h("i", { class: "soc" }), `${t(hass, "forecast.soc")} (${Math.round(latest)} %)`));
    }
    if (expected.length) {
      const latest = expected[expected.length - 1][1];
      keys.append(
        h("span", {}, h("i", { class: "soc planned" }), `${t(hass, "forecast.soc_expected")} (${Math.round(latest)} %)`)
      );
    }
    legend.append(keys);
    card.append(chart, legend);
    if (first < now) this._loadHistory(day, first, Math.min(last, now), isToday);
    return card;
  }

  _dayNav(day, today, days, index) {
    const hass = this._hass;
    const go = (key) => {
      this._day = key === today ? null : key;
      this._render();
    };
    const button = (name, label, target) => {
      const el = h("button", {
        class: "icon-button",
        title: label,
        "aria-label": label,
        disabled: !target,
        onClick: () => target && go(target),
      });
      el.append(icon(name));
      return el;
    };
    const date = h("span", { class: "date" }, icon("calendar"), h("span", { text: dayLabel(hass, day) }));
    return h(
      "div",
      { class: "day" },
      date,
      h("button", { class: "today", text: t(hass, "forecast.today"), disabled: day === today, onClick: () => go(today) }),
      button("previous", t(hass, "forecast.previous"), days[index - 1]),
      button("next", t(hass, "forecast.next"), days[index + 1])
    );
  }

  // Read what ran on a day from the history of the status and signal sensors,
  // once for a past day and every minute for today.
  async _loadHistory(day, start, end, isToday) {
    const cached = this._history[day];
    if (cached && (cached.loading || !isToday || Date.now() - cached.at < HISTORY_REFRESH)) return;
    const consumers = this._state.consumers || {};
    const socEntity = this._state.soc_entity;
    const entities = [
      ...Object.values(consumers).flatMap((c) => [c.status_entity, c.signal_entity]),
      socEntity,
    ].filter(Boolean);
    if (!entities.length || !this._hass?.callWS) return;
    this._history[day] = { ...(cached || {}), loading: true };
    try {
      const result = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: new Date(start).toISOString(),
        end_time: new Date(end).toISOString(),
        entity_ids: entities,
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      this._history[day] = { at: Date.now(), runs: this._runs(result, start, end), soc: this._soc(result?.[socEntity], start) };
    } catch (err) {
      this._history[day] = { at: Date.now(), runs: cached?.runs || {}, soc: cached?.soc || [] };
    }
    if (!this._dragId) this._render();
  }

  // The battery's charge from the history, as [time, percent] points.
  _soc(rows, start) {
    return (rows || [])
      .map((row) => [Math.max((row.lu ?? row.lc ?? 0) * 1000, start), Number.parseFloat(row.s)])
      .filter(([, value]) => Number.isFinite(value));
  }

  // The history as runs per consumer: when it was on, forced or locked.
  _runs(result, start, end) {
    const runs = {};
    for (const [id, consumer] of Object.entries(this._state.consumers || {})) {
      const entity = consumer.signal_entity || consumer.status_entity;
      const rows = result?.[entity] || [];
      const kind = (state) => {
        if (consumer.signal_entity) {
          return { recommended: "on", forced: "forced", blocked: "blocked" }[state];
        }
        return { on: "on", running: "on", locked: "blocked" }[state];
      };
      const list = [];
      rows.forEach((row, i) => {
        const type = kind(row.s);
        if (!type) return;
        const from = Math.max((row.lu ?? row.lc ?? 0) * 1000, start);
        const next = rows[i + 1];
        const to = Math.min(next ? (next.lu ?? next.lc) * 1000 : end, end);
        if (to <= from) return;
        // A reload leaves the sensor unavailable for a moment; a run goes on
        // across such a gap.
        const previous = list[list.length - 1];
        if (previous && previous.kind === type && from - previous.end < 60000) previous.end = to;
        else list.push({ start: from, end: to, kind: type });
      });
      runs[id] = list;
    }
    return runs;
  }

  // One track per consumer under the bars, on the same time axis: what ran,
  // from the history, and what the forecast expects to run.
  // The current time, through the bars and the tracks; the text on the way
  // lies over it.
  _nowLine(x, now) {
    const line = h("div", { class: "now-line", title: formatTime(this._hass, new Date(now).toISOString()) });
    line.style.left = `${x * 100}%`;
    return line;
  }

  _renderTracks(at, first, last, now) {
    const hass = this._hass;
    const plans = this._state.decision?.plan || {};
    const consumers = this._state.consumers || {};
    const ran = this._history[dayKey(hass, first)]?.runs || {};
    const box = h("div", { class: "plan" });
    const segments = (id) => {
      const planned = (plans[id]?.windows || [])
        .filter((w) => new Date(w.end).getTime() > Math.max(first, now) && new Date(w.start).getTime() < last)
        .map((w) => ({
          start: Math.max(new Date(w.start).getTime(), now),
          end: new Date(w.end).getTime(),
          kind: { 4: "forced", 1: "blocked" }[w.level] || "on",
          planned: true,
        }));
      return [...(ran[id] || []), ...planned];
    };
    // Every consumer, so one that did not run and is not expected to shows so.
    const rows = this._order()
      .filter((id) => consumers[id])
      .map((id) => [id, segments(id)]);
    if (!rows.length) return box;
    box.append(h("h3", { text: t(hass, "forecast.plan") }));
    const kinds = new Set();
    let anyPlanned = false;
    let anyRan = false;
    for (const [id, list] of rows) {
      const track = h("div", { class: "track" });
      for (const segment of list) {
        const left = at(segment.start);
        const right = at(segment.end);
        if (right <= left) continue;
        kinds.add(segment.kind);
        if (segment.planned) anyPlanned = true;
        else anyRan = true;
        const run = h("div", {
          class: `run ${segment.kind}${segment.planned ? " planned" : ""}`,
          title: `${formatTime(hass, new Date(segment.start).toISOString())}–${formatTime(hass, new Date(segment.end).toISOString())} · ${t(hass, `legend.${segment.kind}`)}`,
        });
        run.style.left = `${left * 100}%`;
        run.style.width = `${(right - left) * 100}%`;
        track.append(run);
      }
      box.append(h("div", { class: "plan-row" }, h("div", { class: "name", text: consumers[id].title }), track));
    }
    if (!kinds.size) return box;
    const key = h("div", { class: "key" });
    for (const kind of ["on", "forced", "blocked"]) {
      if (kinds.has(kind)) key.append(h("span", {}, h("i", { class: kind }), t(hass, `legend.${kind}`)));
    }
    if (anyRan) key.append(h("span", {}, h("i", { class: "neutral" }), t(hass, "legend.ran")));
    if (anyPlanned) key.append(h("span", {}, h("i", { class: "neutral planned" }), t(hass, "legend.planned")));
    box.append(key);
    return box;
  }

  _renderList() {
    const hass = this._hass;
    const card = h(
      "div",
      { class: "card" },
      h("h2", { text: t(hass, "list.title") }),
      h("p", { class: "hint", text: t(hass, "list.hint") })
    );
    const consumers = this._state.consumers || {};
    if (!Object.keys(consumers).length) {
      card.append(h("p", { class: "hint", text: t(hass, "list.empty") }));
    }
    const decisions = Object.fromEntries((this._state.decision?.consumers || []).map((c) => [c.id, c]));
    const order = this._order().filter((id) => consumers[id]);
    const list = h("ol", { class: "list" });
    order.forEach((id, index) => {
      const row = this._consumerRow(id, consumers[id], decisions[id], index, order.length);
      this._makeDraggable(row, id);
      list.append(row);
    });
    card.append(list);
    return card;
  }

  _arrows(id, index, count) {
    const hass = this._hass;
    const up = h("button", {
      class: "icon-button",
      title: t(hass, "list.up"),
      "aria-label": t(hass, "list.up"),
      disabled: !this._isAdmin || index === 0,
      onClick: () => this._move(id, -1),
    });
    up.append(icon("up"));
    const down = h("button", {
      class: "icon-button",
      title: t(hass, "list.down"),
      "aria-label": t(hass, "list.down"),
      disabled: !this._isAdmin || index === count - 1,
      onClick: () => this._move(id, 1),
    });
    down.append(icon("down"));
    return h("span", { class: "arrows" }, up, down);
  }

  _handle() {
    const handle = h("span", { class: "handle" });
    handle.append(icon("drag"));
    return handle;
  }

  _consumerRow(id, consumer, decision, index, count) {
    const hass = this._hass;
    const state = decision?.state || "unavailable";
    const override = consumer.override || "auto";
    const segmented = h("span", { class: "segmented", role: "group" });
    for (const option of ["auto", "on", "off"]) {
      segmented.append(
        h("button", {
          class: option === override ? "active" : "",
          text: t(hass, `override.${option}`),
          "aria-pressed": String(option === override),
          disabled: !this._isAdmin,
          onClick: () =>
            option !== override &&
            this._call({ type: "solar_surplus/set_override", consumer_id: id, override: option }),
        })
      );
    }
    const power = decision && decision.power ? formatPower(hass, decision.power) : "";
    return h(
      "li",
      { class: "row", "data-id": id },
      this._handle(),
      h("span", { class: "pos", text: String(index + 1) }),
      h(
        "div",
        { class: "main" },
        h(
          "div",
          { class: "name" },
          h("span", { text: consumer.title }),
          this._chip(consumer, decision, state),
          h("span", { class: "kind", text: `${t(hass, `adapter.${consumer.adapter}`)} · ${formatPower(hass, consumer.power)}` })
        ),
        h("div", { class: "reason", text: decision ? reasonText(hass, decision, this._state.decision?.plan?.[id]) : "" })
      ),
      h("div", { class: "side" }, h("span", { class: "power", text: power }), segmented, this._arrows(id, index, count))
    );
  }

  // A signal shows what it tells, the others what they do.
  _chip(consumer, decision, state) {
    const hass = this._hass;
    const level = SIGNAL_LEVELS[decision?.details?.level];
    if (consumer.adapter === "signal" && level && state !== "unavailable") {
      return h("span", { class: `chip ${level}`, text: t(hass, `signal.${level}`) });
    }
    return h("span", { class: `chip ${state}`, text: t(hass, `state.${state}`) });
  }

  _makeDraggable(row, id) {
    if (!this._isAdmin) return;
    row.draggable = true;
    row.addEventListener("dragstart", (event) => {
      this._dragId = id;
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", id);
    });
    row.addEventListener("dragend", () => {
      this._dragId = null;
      row.classList.remove("dragging");
      this._render();
    });
    row.addEventListener("dragover", (event) => {
      if (!this._dragId || this._dragId === id) return;
      event.preventDefault();
      const after = event.offsetY > row.offsetHeight / 2;
      row.classList.toggle("drop-before", !after);
      row.classList.toggle("drop-after", after);
    });
    row.addEventListener("dragleave", () => row.classList.remove("drop-before", "drop-after"));
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      const dragged = this._dragId;
      this._dragId = null;
      if (!dragged || dragged === id) return;
      const after = event.offsetY > row.offsetHeight / 2;
      const order = this._order().filter((item) => item !== dragged);
      const target = order.indexOf(id);
      order.splice(after ? target + 1 : target, 0, dragged);
      this._reorder(order);
    });
  }
}

if (!customElements.get("solar-surplus-panel")) {
  customElements.define("solar-surplus-panel", SolarSurplusPanel);
}
