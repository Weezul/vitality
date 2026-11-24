const tag = "vitality-card";
const kinds = ["morning", "evening", "other"];

function element(name, text, attrs = {}) {
  const node = document.createElement(name);
  if (text != null) node.textContent = text;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function add(parent, ...children) {
  parent.append(...children);
  return parent;
}

function input(name, value = "", type = "text", attrs = {}) {
  const node = element("input", null, { name, type, ...attrs });
  node.value = value ?? "";
  return node;
}

function select(name, options, value) {
  const node = element("select", null, { name });
  for (const [id, label] of options) node.append(element("option", label, { value: id }));
  if (value != null) node.value = value;
  return node;
}

const field = (name, node) => add(element("label", name), node);
const submit = (label) => element("button", label, { type: "submit" });
function button(label, handler) {
  const node = element("button", label, { type: "button" });
  node.onclick = handler;
  return node;
}

export function shiftDay(date, delta) {
  const value = new Date(date + "T00:00:00Z");
  value.setUTCDate(value.getUTCDate() + delta);
  return value.toISOString().slice(0, 10);
}

export function calendarDay(zone, now = new Date()) {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const value = (type) => parts.find((part) => part.type === type).value;
  return [value("year"), value("month"), value("day")].join("-");
}

export function paths(values, x, y, timestamps, gap) {
  const segments = [];
  let segment = [];
  for (const [index, value] of values.entries()) {
    if (value == null || (timestamps && index && timestamps[index] - timestamps[index - 1] > gap)) {
      if (segment.length) segments.push(segment);
      segment = [];
    }
    if (value != null) segment.push([x(index), y(value)]);
  }
  if (segment.length) segments.push(segment);
  return segments;
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function chart(title, labels, series, { min = 0, max, bars = false, timestamps, gap, extent } = {}) {
  const container = element("section");
  container.append(element("h3", title));
  if (!series.some(({ values }) => values.some((value) => value != null))) {
    return add(container, element("p", "No observations in this range."));
  }
  max ??= Math.max(min + 1, ...series.flatMap(({ values }) => values.filter((value) => value != null)));
  const svg = svgElement("svg", { viewBox: "0 0 600 168", role: "img", "aria-label": title });
  const count = Math.max(1, labels.length);
  const x = (i) => {
    if (timestamps?.length) {
      const [first, last] = extent || [timestamps[0], timestamps.at(-1)];
      return 52 + 520 * (timestamps[i] - first) / Math.max(1, last - first);
    }
    return 48 + (i + 0.5) * 536 / count;
  };
  const y = (v) => 135 - ((v - min) / (max - min || 1)) * 122;
  for (const v of [min, (min + max) / 2, max]) {
    svg.append(svgElement("line", { x1: 47, y1: y(v), x2: 584, y2: y(v), class: "gridline" }));
    const tick = svgElement("text", { x: 42, y: y(v) + 4, "text-anchor": "end" });
    tick.textContent = Number(v.toFixed(2));
    svg.append(tick);
  }
  const labelIndices = extent ? [] : new Set([0, Math.floor((count - 1) / 2), count - 1]);
  for (const i of labelIndices) {
    const label = svgElement("text", { x: Math.max(55, Math.min(553, x(i))), y: 157, "text-anchor": "middle" });
    label.textContent = labels[i];
    svg.append(label);
  }
  const legend = element("ul", null, { class: "legend" });
  for (const [index, line] of series.entries()) {
    const symbol = index === 0 ? "●" : "◆";
    legend.append(element("li", `${symbol} ${line.name}`));
    const className = index === 0 ? "first" : "second";
    if (bars) {
      const w = Math.min(24, 390 / count);
      for (const [i, value] of line.values.entries()) {
        if (value == null) continue;
        const rect = svgElement("rect", { x: x(i) - w / 2, y: Math.min(y(0), y(value)),
          width: w, height: Math.max(1, Math.abs(y(0) - y(value))), class: className });
        const tooltip = svgElement("title");
        tooltip.textContent = `${labels[i]} · ${line.name}: ${value}`;
        svg.append(add(rect, tooltip));
      }
    } else {
      for (const segment of paths(line.values, x, y, timestamps, gap)) {
        svg.append(svgElement("polyline", { points: segment.map((point) => point.join(",")).join(" "),
          class: `trace ${className}` }));
      }
      for (const [i, value] of line.values.entries()) {
        if (value == null) continue;
        const marker = index === 0 ? svgElement("circle", { cx: x(i), cy: y(value), r: 3, class: className })
          : svgElement("rect", { x: x(i) - 3, y: y(value) - 3, width: 6, height: 6, class: className });
        const tooltip = svgElement("title");
        tooltip.textContent = `${labels[i]} · ${line.name}: ${value}`;
        svg.append(add(marker, tooltip));
      }
    }
  }
  return add(container, svg, legend);
}

const css = `
  :host { display:block; color:var(--primary-text-color); }
  ha-card { padding: clamp(12px, 3vw, 22px); }
  h2,h3,h4,p { margin:0 0 10px; }
  section, details { border-top:1px solid var(--divider-color,#bbb); padding:14px 0; }
  summary { cursor:pointer; font-weight:600; }
  details > div { margin-top:12px; }
  form,.row { display:flex; flex-wrap:wrap; align-items:end; gap:8px; margin:8px 0; }
  label { display:grid; gap:4px; min-width:0; max-width:100%; }
  input,select,button { font:inherit; color:inherit; background:var(--card-background-color,#fff);
    border:1px solid var(--divider-color,#777); border-radius:6px; min-height:42px; padding:4px 8px;
    box-sizing:border-box; max-width:100%; }
  input,select { width:min(100%, 230px); }
  input[type=checkbox] { width:24px; }
  input[type=number] { width:105px; }
  button { cursor:pointer; }
  button[type=submit] { background:var(--primary-color,#146594); color:var(--text-primary-color,#fff); }
  button:disabled { opacity:.55; cursor:default; }
  :focus-visible { outline:2px solid var(--primary-color,#146594); outline-offset:1px; }
  .note { color:var(--secondary-text-color,#555); }
  .error { color:var(--error-color,#b32121); }
  .record { padding:8px 0; border-bottom:1px solid var(--divider-color,#bbb); overflow-wrap:anywhere; }
  svg { display:block; width:100%; overflow:visible; }
  svg text { fill:currentColor; font-size:12px; }
  .gridline { stroke:var(--divider-color,#aaa); }
  .first { color:var(--primary-color,#1269a0); }
  .second { color:var(--accent-color,#a64f1b); }
  circle,rect { fill:currentColor; }
  .trace { fill:none; stroke:currentColor; stroke-width:2; }
  .trace.second { stroke-dasharray:6 4; }
  .legend { display:flex; flex-wrap:wrap; gap:12px; list-style:none; padding:0; margin:0; }
  .status { min-height:20px; }
`;

class VitalityCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.types = [];
    this.filters = { source: "all", name: "", category: "" };
    this.queryVersion = 0;
    this.preset = 30;
    this.range = {};
    this.detailsOpen = new Set();
    this.shadowRoot.addEventListener("input", () => { this.dirty = true; });
  }

  setConfig(config) {
    this.title = config.title || "Vitality diary";
  }

  set hass(hass) {
    this.client = hass;
    if (!this.booted && this.isConnected) this.boot();
  }

  connectedCallback() {
    if (this.client && !this.booted) this.boot();
    this.timer = setInterval(() => {
      if (this.today && !this.dirty && !this.busy && !this.editing &&
          !this.shadowRoot.activeElement && !document.hidden) {
        this.advanceToday();
        this.refresh().catch(() => {});
      }
    }, 60000);
  }

  disconnectedCallback() { clearInterval(this.timer); }

  advanceToday() {
    const now = calendarDay(this.zone);
    if (this.today === now) return;
    if (this.detail === this.today) this.detail = now;
    this.today = now;
    if (this.preset) this.range = { start: shiftDay(now, 1 - this.preset), end: now };
  }

  getCardSize() { return 12; }

  call(operation, data = {}) {
    return this.client.callWS({ type: "vitality/diary", operation, data });
  }

  async boot() {
    this.booted = true;
    try {
      ({ timezone: this.zone } = await this.call("info"));
      this.today = calendarDay(this.zone);
      this.detail = this.today;
      this.range = { start: shiftDay(this.today, -29), end: this.today };
      this.message = "";
      this.error = false;
      await this.refresh();
    } catch (err) {
      this.message = err.message || "Cannot load Vitality.";
      this.error = true;
      this.render();
    }
  }

  async refresh() {
    const token = ++this.queryVersion;
    const selected = this.seriesType ? { activity_type: this.seriesType } : (
      this.seriesCategory ? { category: this.seriesCategory } : {}
    );
    const detailRange = { start: this.detail, end: this.detail };
    const [types, days, history, todayRows, timeline, garmin, dayRows, battery, analysis] = await Promise.all([
      this.call("types"),
      this.call("daily", { ...this.range, ...selected }),
      this.call("history", { ...this.range, ...this.filters, offset: this.offset || 0 }),
      this.call("daily", { start: this.today, end: this.today }),
      this.call("history", { ...detailRange, limit: 100, offset: this.timelineOffset || 0 }),
      this.call("garmin"),
      this.call("daily", detailRange),
      this.call("samples", { ...detailRange, metric: this.sampleKey || "body_battery" }),
      this.analysisSettings ? this.call("analyze", { ...this.range, ...selected, ...this.analysisSettings }) : null,
    ]);
    if (token !== this.queryVersion) return;
    Object.assign(this, { types, days, history, todayRow: todayRows[0], timeline, garmin, dayRow: dayRows[0], battery, analysis });
    this.render();
  }

  async action(task, message) {
    if (this.busy) return;
    this.busy = true;
    const previous = this.shadowRoot.querySelectorAll("button");
    previous.forEach((node) => { node.disabled = true; });
    try {
      this.undo = null;
      const result = await task();
      this.dirty = false;
      this.message = message ?? (typeof result === "string" ? result : "");
      this.error = false;
      await this.refresh();
    } catch (err) {
      this.message = err.message || "Vitality could not complete the request.";
      this.error = true;
      const status = this.shadowRoot.querySelector(".status");
      if (status) {
        status.textContent = this.message;
        status.classList.add("error");
      } else this.render();
    } finally {
      this.busy = false;
      previous.forEach((node) => { node.disabled = false; });
    }
  }

  form(build, callback, label = "Save") {
    const form = add(element("form"), ...build, submit(label));
    form.onsubmit = (event) => {
      event.preventDefault();
      callback(Object.fromEntries(new FormData(form)));
    };
    return form;
  }

  typesOptions(includeArchived = false) {
    return this.types.filter((type) => includeArchived || !type.archived)
      .map((type) => [type.id, type.name + (type.archived ? " (archived)" : "")]);
  }

  labelTime(value) {
    if (!value) return "—";
    return new Intl.DateTimeFormat(undefined, { timeZone: this.zone, dateStyle: "medium", timeStyle: "short" })
      .format(new Date(value));
  }

  clockTime(value) {
    return new Intl.DateTimeFormat(undefined, { timeZone: this.zone, hour: "2-digit", minute: "2-digit" })
      .format(new Date(value));
  }

  recordForm(source, record) {
    const checkin = source === "checkin";
    const fields = checkin ? [
      field("Check-in", select("kind", kinds.map((k) => [k, k]), record?.kind)),
      field("Score (0–100)", input("score", record?.score, "number", { min: 0, max: 100, step: 1, required: "" })),
    ] : [
      field("Activity", select("activity_type", this.typesOptions(Boolean(record)), record?.activity_type_id)),
      field("Quantity", input("quantity", record?.quantity ?? 1, "number", { min: 0, step: "any", required: "" })),
      field("Unit override", input("unit", record?.unit, "text", { maxlength: 32 })),
      field("Duration (min)", input("duration_minutes", record?.duration_minutes, "number", { min: 0, step: "any" })),
    ];
    fields.push(field(record ? "Timestamp (ISO with offset)" : "Backdate (ISO with offset, optional)",
      input("occurred_at", record?.occurred_at, "text", { placeholder: "2026-11-24T08:00:00+01:00" })));
    fields.push(field("Notes", input("notes", record?.notes, "text", { maxlength: 2000 })));
    return this.form(fields, (data) => this.action(async () => {
      if (checkin) data.score = Number(data.score);
      else {
        data.quantity = Number(data.quantity);
        data.duration_minutes = data.duration_minutes ? Number(data.duration_minutes) : null;
        if (!record && !data.unit) delete data.unit;
      }
      if (!data.occurred_at) delete data.occurred_at;
      const table = checkin ? "checkin" : "event";
      const result = await this.call(`${record ? "update" : "log"}_${table}`, record ? { ...data, id: record.id } : data);
      this.editing = null;
      if (!record) this.undo = { table, id: result.id };
    }, record ? "Changes saved." : "Saved."));
  }

  typeEditor() {
    const target = this.types.find(({ id }) => id === this.editType);
    const pick = select("type", [["", "New activity type"], ...this.typesOptions(true)], target?.id);
    pick.onchange = () => { this.editType = pick.value; this.render(); };
    return add(element("div"), field("Activity to edit", pick), this.form([
      field("Stable ID", input("id", target?.id, "text", { required: "", pattern: "[a-z][a-z0-9_]*",
        maxlength: 64, ...(target ? { readonly: "" } : {}) })),
      field("Name", input("name", target?.name, "text", { required: "", maxlength: 120 })),
      field("Category", input("category", target?.category, "text", { maxlength: 120 })),
      field("Default unit", input("unit", target?.unit, "text", { maxlength: 32 })),
      field("Aliases, comma separated", input("aliases", target?.aliases.join(", "))),
      field("Archived", select("archived", [["false", "No"], ["true", "Yes"]], String(Boolean(target?.archived)))),
    ], (data) => this.action(async () => {
      data.aliases = data.aliases.split(",").map((value) => value.trim()).filter(Boolean);
      data.archived = data.archived === "true";
      data.create_only = !target;
      this.editType = await this.call("save_type", data);
    }, "Activity type saved.")));
  }

  collapsible(id, title, child) {
    const details = add(element("details"), element("summary", title), child);
    details.open = this.detailsOpen.has(id);
    details.ontoggle = () => {
      if (details.open) this.detailsOpen.add(id);
      else this.detailsOpen.delete(id);
    };
    return details;
  }

  logControls() {
    const row = this.todayRow;
    const panel = add(element("section"), element("h3", "Today"),
      element("p", `Morning ${row?.morning ?? "—"} / 100 · Evening ${row?.evening ?? "—"} / 100`),
      element("h4", "Check in"), this.recordForm("checkin"));
    const options = this.typesOptions();
    panel.append(element("h4", "Log an activity"));
    if (!options.length) return add(panel, element("p", "Add an activity type below to start logging."));
    panel.append(this.recordForm("manual"));
    const quick = element("div", null, { class: "row", role: "group", "aria-label": "Quick log" });
    const recent = this.types.filter((type) => !type.archived)
      .sort((a, b) => (b.recent_at || "").localeCompare(a.recent_at || ""));
    for (const { id, name } of recent.slice(0, 8)) quick.append(button(`+ ${name}`, () => this.action(async () => {
      const result = await this.call("log_event", { activity_type: id });
      this.undo = { table: "event", id: result.id };
    }, `Logged ${name}.`)));
    return add(panel, quick);
  }

  records(rows, context) {
    const list = element("div");
    for (const item of rows) {
      const checkin = item.source === "checkin";
      const panel = add(element("article", null, { class: "record" }),
        element("strong", checkin ? `${item.kind} · ${item.score}/100` : item.name || "Workout"),
        element("p", `${this.labelTime(item.occurred_at)} · ${item.source}${item.quantity == null ? "" : ` · ${item.quantity} ${item.unit}`}${item.duration_minutes == null ? "" : ` · ${Math.round(item.duration_minutes)} min`}`));
      if (item.notes) panel.append(element("p", item.notes));
      if (item.prior_battery) panel.append(element("p",
        `Prior Body Battery: ${item.prior_battery.value}% at ${this.clockTime(item.prior_battery.observed_at)} · ${item.prior_battery.provenance}`,
        { class: "note" }));
      if (item.source === "garmin") this.workoutControls(panel, item, context);
      else {
        const table = checkin ? "checkin" : "event";
        panel.append(add(element("div", null, { class: "row" }),
          button("Edit", () => { this.editing = { id: item.id, context }; this.render(); }),
          button("Delete", () => {
            if (confirm("Permanently delete this diary record?")) {
              this.action(() => this.call(`delete_${table}`, { id: item.id }), "Record deleted.");
            }
          })));
        if (this.editing?.id === item.id && this.editing.context === context) panel.append(this.recordForm(item.source, item),
          button("Cancel edit", () => { this.editing = null; this.dirty = false; this.render(); }));
      }
      list.append(panel);
    }
    if (!rows.length) list.append(element("p", "No matching records."));
    return list;
  }

  workoutControls(panel, item, context) {
    const labels = [item.original_type, item.original_name !== item.name ? item.original_name : null,
      item.distance_m != null ? `${Number((item.distance_m / 1000).toFixed(2))} km` : null,
      item.late ? "Late exercise" : null, item.excluded ? "Excluded from totals" : null,
      item.manual_id ? "Linked manual log" : null].filter(Boolean);
    if (labels.length) panel.append(element("p", labels.join(" · ")));
    panel.append(add(element("div", null, { class: "row" }),
      button("Edit workout", () => { this.editing = { id: item.id, context }; this.render(); }),
      button(item.excluded ? "Restore to totals" : "Exclude from totals", () => {
        if (item.excluded || confirm("Exclude this workout from totals? You can restore it later.")) {
          this.action(() => this.call("workout_override", { id: item.id, excluded: !item.excluded }),
            item.excluded ? "Workout restored." : "Workout excluded.");
        }
      })));
    if (this.editing?.id !== item.id || this.editing.context !== context) return;
    const manual = new Map([...this.timeline.records, ...this.history.records].filter((row) => row.source === "manual")
      .map((row) => [row.id, `${row.name} · ${this.labelTime(row.occurred_at)}`]));
    if (item.manual_id && !manual.has(item.manual_id)) manual.set(item.manual_id, "Previously linked log");
    panel.append(this.form([
      field("Local note", input("notes", item.notes, "text", { maxlength: 2000 })),
      field("Corrected timestamp (with offset)", input("occurred_at", item.override_at, "text",
        { placeholder: item.occurred_at })),
      field("Corrected duration (min)", input("duration_minutes", item.override_duration, "number",
        { min: 0, step: "any", placeholder: item.duration_minutes ?? "" })),
      field("Link to a visible manual log", select("manual_id", [["", "None"], ...manual], item.manual_id)),
    ], (data) => this.action(async () => {
      await this.call("workout_override", { ...data, id: item.id, occurred_at: data.occurred_at || null,
        duration_minutes: data.duration_minutes === "" ? null : Number(data.duration_minutes) });
      this.editing = null;
    }, "Workout corrections saved.")),
    element("p", "Linking records keeps both sources visible. Use Exclude if they should not both contribute to their totals."),
    button("Cancel edit", () => { this.editing = null; this.dirty = false; this.render(); }));
  }

  get categories() {
    return [...new Set(this.types.map(({ category }) => category).filter(Boolean))].sort();
  }

  dateControls() {
    const controls = element("section");
    const presets = element("div", null, { class: "row", role: "group", "aria-label": "Date range presets" });
    for (const n of [7, 30, 90]) {
      const node = button(`${n} days`, () => this.action(() => {
        this.preset = n;
        this.offset = 0;
        this.range = { start: shiftDay(this.today, 1 - n), end: this.today };
      }));
      node.setAttribute("aria-pressed", this.preset === n);
      presets.append(node);
    }
    return add(controls, element("h3", "Date range"), presets, this.form([
      field("From", input("start", this.range.start, "date", { required: "" })),
      field("Through", input("end", this.range.end, "date", { required: "" })),
    ], (data) => this.action(() => {
      const count = (Date.parse(data.end) - Date.parse(data.start)) / 86400000 + 1;
      if (count < 1 || count > 366) throw new Error("Choose a date range of 1 to 366 days.");
      this.range = data;
      this.preset = null;
      this.offset = 0;
    }), "Apply range"));
  }

  charts() {
    const panel = add(element("div"), this.dateControls());
    const labels = this.days.map(({ date }) => date.slice(5));
    panel.append(chart("Subjective scores (0–100)", labels, [
      { name: "Morning", values: this.days.map(({ morning }) => morning) },
      { name: "Evening", values: this.days.map(({ evening }) => evening) },
    ], { max: 100 }));
    const units = [...new Set(this.days.flatMap(({ quantities }) => Object.keys(quantities)))].sort();
    const quantity = this.quantityMode && units.includes(this.quantityUnit);
    panel.append(this.form([
      field("Activity series", select("activity", [["", "All manual activities"], ...this.typesOptions(true)], this.seriesType)),
      field("Category series", select("category", [["", "All categories"], ...this.categories.map((c) => [c, c])], this.seriesCategory)),
      field("Activity measure", select("measure", [["count", "Occurrence count"], ...units.map((u) => [`unit:${u}`, `Quantity (${u || "no unit"})`])],
        quantity ? `unit:${this.quantityUnit}` : "count")),
    ], ({ activity, category, measure }) => this.action(() => {
      this.seriesType = activity;
      this.seriesCategory = activity ? "" : category;
      this.quantityMode = measure !== "count";
      this.quantityUnit = measure.slice(5);
    }), "Apply activity series"));
    const activityName = quantity ? `Quantity (${this.quantityUnit || "no unit"})` : "Occurrences";
    panel.append(chart("Logged manual activities", labels, [{
      name: activityName, values: this.days.map((d) => quantity ? (d.quantities[this.quantityUnit] ?? 0) : d.count),
    }], { bars: true }), element("p", "Zero means no matching logs were recorded.", { class: "note" }));
    return add(panel, this.garminCharts(labels));
  }

  metricOptions() {
    const metrics = new Map();
    for (const day of this.days) {
      for (const [key, value] of Object.entries(day.metrics)) {
        if (["numeric", "timestamp"].includes(value.value_type)) metrics.set(key, value);
      }
    }
    return metrics;
  }

  garminCharts(labels) {
    const metrics = this.metricOptions();
    const choices = [["", "No additional series"], ["workout_count", "Imported workouts"], ["late_workouts", "Late workouts"],
      ...[...metrics].map(([key, value]) => [`metric:${key}`, this.metricLabel(key, value)])];
    const selected = choices.find(([key]) => key === this.garminSeries);
    const panel = this.form([field("Garmin comparison", select("metric", choices, this.garminSeries))],
      ({ metric }) => this.action(() => { this.garminSeries = metric; }), "Apply Garmin series");
    const result = add(element("section"), panel);
    if (!selected?.[0]) return result;
    const key = selected[0].slice(7);
    const selectedValue = metrics.get(key);
    const values = this.days.map((row) => {
      if (!selected[0].startsWith("metric:")) return row[selected[0]];
      const value = row.metrics[key];
      if (!value || value.unit !== selectedValue.unit || value.value_type !== selectedValue.value_type) return null;
      if (value.value_type === "numeric") return value.value;
      return this.minutesFromAnchor(value.value);
    });
    return add(result, chart(selected[1], labels, [{ name: selected[1], values }],
      { min: Math.min(0, ...values.filter((v) => v != null)), bars: !selected[0].startsWith("metric:") }),
    element("p", "Gaps indicate unavailable observations or incomplete workout coverage.", { class: "note" }));
  }

  metricLabel(key, value) {
    const suffix = value.value_type === "timestamp" ? `min from ${this.garmin.workouts.sleep_anchor}` : value.unit;
    return this.metricName(key) + (suffix ? ` (${suffix})` : "");
  }

  minutesFromAnchor(timestamp) {
    const parts = new Intl.DateTimeFormat("en", { timeZone: this.zone, hour: "2-digit",
      minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(timestamp));
    const value = (type) => Number(parts.find((part) => part.type === type).value);
    const [hour, minute] = this.garmin.workouts.sleep_anchor.split(":").map(Number);
    return (value("hour") * 60 + value("minute") - hour * 60 - minute + 1440) % 1440;
  }

  analyticsPanel() {
    const metrics = this.metricOptions();
    const units = [...new Set(this.days.flatMap((day) => Object.keys(day.quantities)))];
    const panel = add(element("div"),
      element("p", "Manual comparisons use the activity series filter above. Only complete pairs within the selected range are used."),
      this.form([
        field("Predictor", select("predictor", [["count", "Logged occurrence count"],
          ...units.map((unit) => [`quantity:${unit}`, `Logged quantity (${unit || "no unit"})`]),
          ["workout_count", "Imported workouts"], ["late_workouts", "Late workouts"],
          ...[...metrics].map(([key, value]) => [`metric:${key}`, this.metricLabel(key, value)])], this.analysisChoice || "count")),
        field("Outcome", select("outcome", [["evening", "Same-day evening score"],
          ["next_morning", "Next-day morning score"], ["change", "Same-day evening minus morning"]],
        this.analysisSettings?.outcome)),
        field("Optional group threshold", input("threshold", this.analysisSettings?.threshold, "number", { step: "any" })),
      ], (data) => this.action(() => {
        this.analysisChoice = data.predictor;
        const [predictor, key = ""] = data.predictor.split(":");
        let unit = predictor === "quantity" ? key : "";
        if (predictor === "metric") unit = metrics.get(key).unit;
        this.analysisSettings = { predictor, outcome: data.outcome, unit };
        if (predictor === "metric") {
          this.analysisSettings.metric = key;
          this.analysisSettings.anchor = this.garmin.workouts.sleep_anchor;
        }
        if (data.threshold !== "") this.analysisSettings.threshold = Number(data.threshold);
      }), "Compare"));
    const result = this.analysis;
    if (result) {
      const format = (value) => value == null ? "—" : value.toFixed(2);
      panel.append(element("p", `${result.start} through ${result.end} · ${result.outcome} · ${result.n} paired days`),
        element("p", result.r == null ? "Pearson correlation unavailable. At least 7 pairs and variation in both values are required."
          : `Exploratory Pearson r = ${format(result.r)}${result.warning ? " · Fewer than 30 paired days." : ""}`));
      const group = result.groups;
      if (group) panel.append(element("p", `≤ ${group.threshold}: n=${group.lower_n}, mean ${format(group.lower_mean)} · > ${group.threshold}: n=${group.upper_n}, mean ${format(group.upper_mean)} · difference ${format(group.difference)} points`));
    }
    return add(panel, element("p", "Zero logs can reflect incomplete logging. Associations can reflect other factors, including sleep, illness or work stress.", { class: "note" }));
  }

  metricName(key) {
    return key.replaceAll("_", " ").replace(".first", " · first observed").replace(".last", " · last observed");
  }

  overview(row, title) {
    const panel = add(element("section"), element("h3", title));
    const metrics = Object.entries(row.metrics);
    const mandatory = ["bedtime", "wake_time", "sleep_duration", "sleep_score", "body_battery.last"];
    const keys = [...new Set([...mandatory, ...metrics.map(([key]) => key)])];
    const values = element("ul");
    for (const key of keys) {
      const metric = row.metrics[key];
      const value = metric ? (metric.value_type === "timestamp" ? this.labelTime(metric.value)
        : `${metric.value}${metric.unit ? " " + metric.unit : ""}`) : "No observation";
      values.append(element("li", `${this.metricName(key)} · ${value}${metric ? ` · ${metric.source} · ${metric.provenance}` : ""}`));
    }
    const workouts = row.workout_count == null ? "Workout coverage unknown"
      : `${row.workout_count} imported workout(s) · ${row.late_workouts} late`;
    return add(panel, values, element("p", workouts));
  }

  batteryChart() {
    const { samples, bounds, truncated } = this.battery;
    const selected = this.sampleKey || "body_battery";
    const options = new Map([["body_battery", "Body Battery (%)"]]);
    for (const [key, mapping] of Object.entries(this.garmin.metrics)) {
      if (mapping.mode === "sample" && mapping.type === "numeric") options.set(key,
        key === "body_battery" ? "Body Battery (%)" : this.metricName(key));
    }
    const chooser = this.form([field("Intraday metric", select("metric", options, selected))],
      ({ metric }) => this.action(() => { this.sampleKey = metric; }), "Show intraday series");
    const times = samples.map((row) => Date.parse(row.observed_at));
    const unit = samples.at(-1)?.unit ?? "";
    const label = selected === "body_battery" ? "Body Battery (%)" : `${this.metricName(selected)}${unit ? ` (${unit})` : ""}`;
    const values = samples.map((row) => row.unit === unit && row.value_type === "numeric" ? row.value : null);
    const view = chart(`${label} · intraday`, samples.map((row) => this.clockTime(row.observed_at)),
      [{ name: label, values }],
      { min: Math.min(0, ...values.filter((v) => v != null)), max: selected === "body_battery" ? 100 : undefined,
        timestamps: times, extent: bounds.map(Date.parse), gap: 2 * 60 * 60 * 1000 });
    if (samples.length) view.append(element("p", `${this.labelTime(samples[0].observed_at)} to ${this.labelTime(samples.at(-1).observed_at)} · gaps over 2 hours are disconnected.`));
    if (truncated) view.append(element("p", "Chart shows the first 1,500 observations. Use CSV for the full day."));
    const source = this.garmin.metrics.body_battery;
    const container = add(element("div"), chooser, view);
    if (selected === "body_battery" && source?.enabled && source.entity && !source.attribute && this.client.callApi) {
      container.append(button("Import HA history for this day", () => this.action(async () => {
        const query = new URLSearchParams({
          filter_entity_id: source.entity, end_time: bounds[1], minimal_response: "", no_attributes: "",
          skip_initial_state: "", significant_changes_only: "0",
        });
        const result = await this.client.callApi("GET", `history/period/${encodeURIComponent(bounds[0])}?${query}`);
        const readings = (result[0] || []).flatMap((state) => {
          if (!state.last_changed || !String(state.state ?? "").trim()) return [];
          const value = Number(state.state);
          return Number.isFinite(value) && value >= 0 && value <= 100
            ? [{ value, observed_at: state.last_changed }] : [];
        });
        const imported = await this.call("backfill_battery", {
          start: this.detail, end: this.detail, entity: source.entity, readings,
        });
        return `Imported ${imported.inserted} Body Battery change(s) from HA history.`;
      })));
    }
    return container;
  }

  pager(offset, next, handler, size = 50) {
    const nav = element("div", null, { class: "row" });
    if (offset) nav.append(button("Previous", () => handler(Math.max(0, offset - size))));
    if (next != null) nav.append(button("Next", () => handler(next)));
    return nav;
  }

  historyPanel() {
    const panel = add(element("section"), element("h3", "History"), this.form([
      field("Name contains", input("name", this.filters.name, "text", { maxlength: 120 })),
      field("Category", select("category", [["", "All categories"], ...this.categories.map((c) => [c, c])], this.filters.category)),
      field("Source", select("source", [["all", "All"], ["manual", "Manual activities"], ["checkin", "Check-ins"], ["garmin", "Garmin"]], this.filters.source)),
    ], (filters) => this.action(() => { this.filters = filters; this.offset = 0; }), "Apply history filters"));
    return add(panel, this.records(this.history.records, "history"), this.pager(this.offset, this.history.next,
      (offset) => this.action(() => { this.offset = offset; })));
  }

  detailPanel() {
    const panel = add(element("section"), element("h3", "Daily timeline"), this.form([
      field("Detail date", input("date", this.detail, "date", { required: "" })),
    ], ({ date }) => this.action(() => { this.detail = date; this.timelineOffset = 0; }), "Show day"),
    ...(this.detail === this.today ? [] : [this.overview(this.dayRow, "Garmin overview for this day")]),
    this.batteryChart(),
    this.records(this.timeline.records, "timeline"), this.pager(this.timelineOffset, this.timeline.next,
      (offset) => this.action(() => { this.timelineOffset = offset; }), 100));
    return panel;
  }

  exportPanel() {
    return this.form([field("Export table", select("table", [
      ["events", "Events"], ["checkins", "Check-ins"],
      ["daily_observations", "Daily observations"], ["metric_samples", "Metric samples"],
    ]))], ({ table }) => this.action(async () => {
      const parts = [];
      let offset = 0;
      do {
        const page = await this.call("export", { ...this.range, table, offset });
        parts.push(offset === 0 ? page.csv : page.csv.slice(page.csv.indexOf("\n") + 1));
        offset = page.next;
      } while (offset != null);
      const url = URL.createObjectURL(new Blob(parts, { type: "text/csv;charset=utf-8" }));
      element("a", null, { href: url, download: `vitality-${table}-${this.range.start}-${this.range.end}.csv` }).click();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
    }, "Export prepared."), "Download CSV");
  }

  garminEditor() {
    const { metrics, workouts, imports, status } = this.garmin;
    const options = Object.keys(metrics).map((key) => [key, this.metricName(key)]);
    const active = metrics[this.editMetric] || {};
    const pick = select("metric", [["", "New scalar mapping"], ...options], this.editMetric);
    pick.onchange = () => { this.editMetric = pick.value; this.render(); };
    const body = add(element("div"), add(element("div", null, { class: "row" }),
      button("Resync cached states", () => this.action(() => this.call("resync_garmin"), "Garmin cache checked.")),
      button("Backfill visible workouts in range", () => this.action(async () => {
        const result = await this.call("backfill", this.range);
        return `Found ${result.records_seen} workout(s) in cached sources. Skipped ${result.skipped} unreadable records.`;
      }))));
    const statusList = element("ul");
    for (const [key, config] of [...Object.entries(metrics), ["workouts", { status }]]) {
      const state = config.status?.availability || "Waiting for refresh";
      const record = imports[key];
      const stale = record?.latest_day && key !== "workouts" && (record.latest_day < this.today ||
        (key === "body_battery" && Date.now() - Date.parse(record.latest_timestamp) > 2 * 60 * 60 * 1000));
      statusList.append(element("li", `${this.metricName(key)} · Garmin · ${state}${stale ? " · stale observation" : ""}${record ? ` · latest ${record.latest_day} · last import ${this.labelTime(record.last_import)}` : ""}${config.status?.error ? ` · ${config.status.error}` : ""}`));
    }
    const fixed = ["wake_time", "bedtime", "sleep_score", "sleep_duration", "body_battery"].includes(this.editMetric);
    const rawFields = [
      field("Stable metric key", input("key", this.editMetric, "text",
        { required: "", pattern: "[a-z][a-z0-9_]*", ...(this.editMetric ? { readonly: "" } : {}) })),
      field("Sensor entity ID (blank for discovery)", input("entity", active.auto ? "" : active.entity, "text",
        { placeholder: active.entity || "sensor.entity_id" })),
      field("Value attribute (blank for state)", input("attribute", active.attribute)),
      field("Source date attribute (optional)", input("date_attribute", active.date_attribute)),
      field("Observation timestamp attribute (optional)", input("time_attribute", active.time_attribute)),
      field("Enabled", select("enabled", [["true", "Yes"], ["false", "No"]], String(active.enabled ?? true))),
    ];
    if (!fixed) rawFields.push(
      field("Value type", select("type", [["numeric", "Numeric"], ["timestamp", "Timestamp"]], active.type)),
      field("Unit (blank for entity unit)", input("unit", active.unit, "text", { maxlength: 32 })),
      field("Collection", select("mode", [["daily", "Daily snapshot"], ["sample", "Time series"]], active.mode)),
      field("Daily date rule", select("date_policy", [["source", "Require source date"], ["changed", "Infer from fresh HA change"]], active.date_policy)));
    return add(body, this.collapsible("metricStatus", "Source and import status", statusList),
      element("h4", "Metric mappings"), field("Metric to edit", pick),
      this.form(rawFields, (data) => this.action(async () => {
        data.enabled = data.enabled === "true";
        await this.call("save_metric", data);
        this.editMetric = data.key;
      }, "Metric mapping saved."), "Save metric mapping"),
      element("h4", "Workout sources and rules"), this.form([
        field("Workout import", select("enabled", [["true", "Enabled"], ["false", "Disabled"]], String(workouts.enabled))),
        field("List entity (blank for discovery)", input("list_source", workouts.list_source, "text", { placeholder: workouts.list_source_resolved })),
        field("List attribute", input("list_attribute", workouts.list_attribute, "text", { required: "" })),
        field("Latest entity (blank for discovery)", input("latest_source", workouts.latest_source, "text", { placeholder: workouts.latest_source_resolved })),
        field("Source duration unit", select("duration_unit", [["s", "Seconds"], ["min", "Minutes"], ["ignore", "Ignore"]], workouts.duration_unit)),
        field("Source distance unit", select("distance_unit", [["m", "Meters"], ["km", "Kilometers"], ["ignore", "Ignore"]], workouts.distance_unit)),
        field("Late threshold (local)", input("late_threshold", workouts.late_threshold, "time", { required: "" })),
        field("Eligible Garmin types (blank for all)", input("late_types", workouts.late_types.join(", "))),
        field("Garmin type=activity ID, comma separated", input("type_map", Object.entries(workouts.type_map).map((pair) => pair.join("=")).join(", "))),
        field("Body Battery comparison tolerance (min)", input("battery_tolerance", workouts.battery_tolerance, "number", { required: "", min: 1, max: 720 })),
        field("Sleep clock comparison anchor", input("sleep_anchor", workouts.sleep_anchor, "time", { required: "" })),
      ], (data) => this.action(async () => {
        data.enabled = data.enabled === "true";
        data.battery_tolerance = Number(data.battery_tolerance);
        data.late_types = data.late_types.split(",").map((x) => x.trim()).filter(Boolean);
        const pairs = data.type_map.split(",").filter((value) => value.trim()).map((value) => value.split("=").map((word) => word.trim()));
        if (pairs.some((pair) => pair.length !== 2 || !pair.every(Boolean))) throw new Error("Use Garmin type=activity ID for each mapping.");
        data.type_map = Object.fromEntries(pairs);
        await this.call("save_workouts", data);
      }, "Workout settings saved."), "Save workout settings"),
      element("p", "Changing the type mapping or late rule recomputes the historical display.", { class: "note" }));
  }

  render() {
    const status = element("p", this.message || "", { class: `status ${this.error ? "error" : ""}`, role: "status" });
    const card = add(element("ha-card"), element("h2", this.title || "Vitality diary"), status);
    if (this.undo) card.append(button("Undo last log", () => {
      const { table, id } = this.undo;
      this.action(() => this.call(`delete_${table}`, { id }), "Log undone.");
    }));
    if (!this.days && this.error) card.append(button("Retry", () => this.boot()));
    if (this.days) card.append(button("Refresh", () => this.action(() => this.advanceToday())),
      this.logControls(), this.overview(this.todayRow, "Today's Garmin overview"), this.detailPanel(), this.charts(), this.historyPanel(),
      this.collapsible("analytics", "Exploratory comparisons", this.analyticsPanel()),
      this.collapsible("types", "Manage activity types", this.typeEditor()),
      this.collapsible("garmin", "Configure Garmin", this.garminEditor()),
      this.collapsible("export", "Export selected dates", add(element("div"),
        element("p", "CSV may contain private diary data."), this.exportPanel())));
    this.shadowRoot.replaceChildren(element("style", css), card);
  }
}

if (!customElements.get(tag)) customElements.define(tag, VitalityCard);
