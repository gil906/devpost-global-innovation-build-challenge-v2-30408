const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { scenario: null, result: null, resultScenario: null, dirty: false, snapshots: [], editing: null };
const categories = ["produce", "bakery", "chilled"];
const time = (minute) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const minutes = (value) => {
  const [hours, minute] = value.split(":").map(Number);
  return hours * 60 + minute;
};
const number = (value) => new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

function button(text, className, action, label) {
  const node = el("button", { type: "button", class: `button ${className}`, text });
  if (label) node.setAttribute("aria-label", label);
  node.addEventListener("click", action);
  return node;
}

function announce(message, isError = false) {
  $("#error").hidden = true;
  $("#message").hidden = true;
  const target = $(isError ? "#error" : "#message");
  target.textContent = message;
  target.hidden = false;
}

async function request(path, body, method = body === undefined ? "GET" : "POST") {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Cannot reach the local server. Keep your inputs and try again when it is running.");
  }
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).error; }
    catch { detail = `Server returned HTTP ${response.status}.`; }
    throw new Error(detail || `Server returned HTTP ${response.status}.`);
  }
  return response;
}

function handle(action) {
  return async (...args) => {
    try { await action(...args); }
    catch (error) { announce(error.message, true); }
  };
}

function changed() {
  state.dirty = JSON.stringify(state.scenario) !== JSON.stringify(state.resultScenario);
  $("#stale-warning").hidden = !state.dirty;
  $("#scenario-title").textContent = state.scenario.name;
  $("#location-count").textContent = state.scenario.donors.length + state.scenario.hubs.length;
}

function fillSettings() {
  const scenario = state.scenario;
  $("#scenario-name").value = scenario.name;
  $("#start-time").value = time(scenario.start_minute);
  $("#speed").value = scenario.speed_kph;
  $("#handling").value = scenario.handling_minutes;
  $("#vehicle-capacity").value = scenario.vehicle_capacity;
  // Imported scenarios support the entire API range, not just the slider's initial range.
  $("#max-distance").min = "0.1";
  $("#max-distance").max = "30";
  $("#max-distance").step = "any";
  $("#max-distance").value = scenario.max_leg_km;
  $(".range-labels").replaceChildren(el("span", { text: "0.1 km" }), el("span", { text: "30 km" }));
  $("#distance-value").textContent = `${number(scenario.max_leg_km)} km`;
  changed();
}

async function runPlan({ notify = true } = {}) {
  if (!state.scenario) throw new Error("Load or import a scenario first.");
  if (!$("#settings-form").reportValidity()) return;
  const input = structuredClone(state.scenario);
  $("#run-button").disabled = true;
  $("#run-button").textContent = "Finding connections...";
  try {
    const result = await (await request("/api/plan", input)).json();
    state.result = result;
    state.resultScenario = input;
    changed();
    renderResults();
    if (notify) announce(`Plan ready: ${number(result.summary.allocated)} servings assigned across ${result.transfers.length} transfers.`);
  } finally {
    $("#run-button").disabled = false;
    $("#run-button").textContent = "Run planner \u2192";
  }
}

async function replaceScenario(scenario, message) {
  const result = await (await request("/api/plan", scenario)).json();
  state.scenario = scenario;
  state.resultScenario = structuredClone(scenario);
  state.result = result;
  fillSettings();
  renderLocations();
  renderResults();
  if (message) announce(message);
}

function showView(name) {
  $$(".view").forEach((view) => { view.hidden = view.id !== `view-${name}`; });
  $$(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === name);
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
}

function renderResults() {
  const { summary, baseline, improvement, transfers, donors, hubs } = state.result;
  const scenario = state.resultScenario;
  const donorById = new Map(scenario.donors.map((item) => [item.id, item]));
  const hubById = new Map(scenario.hubs.map((item) => [item.id, item]));
  const metrics = [
    ["SERVINGS CONNECTED", number(summary.allocated), `of ${number(summary.available)} available`],
    ["DEMAND COVERED", `${number(summary.coverage_pct)}%`, `${number(summary.unmet)} servings still needed`],
    ["VS. NEAREST-FIRST", `+${number(improvement)}`, "additional servings assigned"],
    ["PARALLEL LOADS", number(summary.trips), `${number(summary.trip_km)} one-way trip-km`],
  ];
  $("#metrics").replaceChildren(...metrics.map(([label, value, detail]) =>
    el("div", { class: "metric" },
      el("p", { class: "metric-label", text: label }),
      el("p", { class: "metric-number", text: value }),
      el("p", { class: "metric-detail", text: detail }))));
  renderMap(scenario, transfers);
  $("#hub-coverage").replaceChildren(...hubs.map((item) => {
    const hub = hubById.get(item.id);
    return el("div", { class: "coverage-row", title: item.explanation },
      el("div", { class: "coverage-title" }, el("span", { text: hub.name }),
        el("span", { text: `${item.received} / ${hub.demand}` })),
      el("progress", { max: Math.max(1, hub.demand), value: item.received, "aria-label": `${hub.name} demand covered` }),
      ...(item.unmet ? [el("p", { class: "muted small", text: item.explanation })] : []));
  }));
  if (!hubs.length) $("#hub-coverage").append(el("p", { class: "empty-state", text: "Add a receiving hub to see demand coverage." }));
  $("#comparison").replaceChildren(
    el("p", { class: "comparison-number", text: `+${number(improvement)}` }, el("span", { text: "servings connected" })),
    el("div", { class: "comparison-bars" },
      ...[["CommonTable", summary.allocated, ""], ["Nearest-first", baseline.allocated, "baseline"]].map(([label, value, style]) =>
        el("div", { class: `compare-line ${style}` }, el("span", { text: label }),
          el("progress", { max: Math.max(summary.demand, 1), value, "aria-label": `${label} assigned servings` }),
          el("strong", { text: value })))),
  );
  $("#transfers").replaceChildren(...transfers.map((transfer) => {
    const donor = donorById.get(transfer.donor_id);
    return el("tr", {},
      el("td", {}, el("strong", { text: donor.name }), el("span", { class: "food-label", text: donor.category })),
      el("td", { text: hubById.get(transfer.hub_id).name }),
      el("td", {}, el("strong", { text: transfer.quantity })),
      el("td", { text: transfer.distance_km }),
      el("td", { text: time(transfer.arrive_minute), title: `Depart at ${time(transfer.depart_minute)}` }),
      el("td", { text: transfer.trips }));
  }));
  if (!transfers.length) $("#transfers").append(el("tr", {}, el("td", { colspan: "6", class: "empty-state", text: "No eligible transfers. Inspect the constraints below or adjust the scenario." })));
  const gaps = donors.filter((donor) => donor.remaining);
  $("#unassigned-label").textContent = `${summary.unassigned} servings`;
  $("#unassigned").replaceChildren(...gaps.map((donor) =>
    el("div", { class: "gap-card" },
      el("div", { class: "gap-title" }, el("span", { text: donorById.get(donor.id).name }), el("span", { text: `${donor.remaining} unassigned` })),
      el("p", { text: donor.explanation }),
      ...(donor.constraints.length ? [el("details", {},
        el("summary", { text: "Inspect blocked connections" }),
        el("ul", {}, ...donor.constraints.map((reason) => el("li", { text: `${reason.text} (${reason.hubs} hub${reason.hubs === 1 ? "" : "s"})` }))))] : []))));
  if (!gaps.length) $("#unassigned").append(el("p", { class: "empty-state", text: summary.available ? "Every available serving has an eligible destination in this simulation." : "No available supply. Add a batch to begin." }));
  $("#evidence-summary").replaceChildren(
    el("span", { text: `Current plan: ${summary.allocated} servings vs. ${baseline.allocated} nearest-first.` }),
    el("span", { text: `Cost: ${number(summary.serving_km)} serving-km. Algorithm v${state.result.version}.` }),
  );
  $("#pair-audit").replaceChildren(...state.result.pairs.map((pair) =>
    el("tr", {},
      el("td", { text: donorById.get(pair.donor_id).name }),
      el("td", { text: hubById.get(pair.hub_id).name }),
      el("td", { class: `eligibility-badge ${pair.eligible ? "" : "blocked"}`,
        text: pair.eligible ? `Eligible / ${time(pair.arrive_minute)} earliest delivery` :
          pair.reasons.map((reason) => state.result.reason_labels[reason]).join("; ") }))));
}

function renderMap(scenario, transfers) {
  const locations = [...scenario.donors, ...scenario.hubs];
  if (!locations.length) {
    $("#network-map").replaceChildren(el("p", { class: "empty-map", text: "Your network starts here. Add a batch and a receiving hub." }));
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attributes, text) => {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const svg = svgEl("svg", { viewBox: "0 0 960 500", role: "group", "aria-label": "Schematic transfer network. Select a batch or hub to edit it." });
  const defs = svgEl("defs", {});
  const pattern = svgEl("pattern", { id: "grid", width: 40, height: 40, patternUnits: "userSpaceOnUse" });
  pattern.append(svgEl("path", { d: "M 40 0 L 0 0 0 40", fill: "none", stroke: "#e5ebdd", "stroke-width": 1 }));
  defs.append(pattern);
  svg.append(defs, svgEl("rect", { width: 960, height: 500, fill: "url(#grid)" }));
  svg.append(svgEl("path", { d: "M -20 130 C 230 65, 350 300, 540 225 S 800 290, 980 160", stroke: "#e4ede3", "stroke-width": 45, fill: "none" }));
  svg.append(svgEl("text", { x: 26, y: 29, class: "map-axis" }, "SCHEMATIC / NOT A ROAD MAP"));
  const maxX = Math.max(10, ...locations.map((item) => item.x_km));
  const maxY = Math.max(10, ...locations.map((item) => item.y_km));
  const scale = Math.min(720 / maxX, 350 / maxY);
  const offsetX = (960 - maxX * scale) / 2;
  const point = (node) => [offsetX + node.x_km * scale, 425 - node.y_km * scale];
  const byId = new Map(locations.map((item) => [item.id, item]));
  const occupied = locations.map((location) => {
    const [x, y] = point(location);
    return { left: x - 27, right: x + 27, top: y - 27, bottom: y + 27 };
  });
  const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  for (const transfer of transfers) {
    const [x1, y1] = point(byId.get(transfer.donor_id));
    const [x2, y2] = point(byId.get(transfer.hub_id));
    const route = svgEl("path", { d: `M ${x1} ${y1} Q ${(x1 + x2) / 2 + 10} ${(y1 + y2) / 2 - 25} ${x2} ${y2}`,
      class: "map-route", "stroke-width": Math.max(2, Math.sqrt(transfer.quantity) * 0.8) });
    route.append(svgEl("title", {}, `${byId.get(transfer.donor_id).name} to ${byId.get(transfer.hub_id).name}: ${transfer.quantity} servings`));
    svg.append(route);
  }
  for (const [kind, list] of [["donors", scenario.donors], ["hubs", scenario.hubs]]) {
    list.forEach((location, index) => {
      const [x, y] = point(location);
      const donor = kind === "donors";
      const group = svgEl("g", { class: "map-node", tabindex: 0, role: "button", "aria-label": `Edit ${location.name}` });
      group.append(svgEl("title", {}, `${location.name}: ${donor ? location.quantity + " servings available" : location.demand + " servings requested"}`));
      group.append(svgEl("circle", { cx: x, cy: y, r: 24, fill: donor ? "#f5e4b8" : "#dce9d8", class: "node-halo", stroke: "#f4f7ef", "stroke-width": 4 }));
      group.append(donor ? svgEl("circle", { cx: x, cy: y, r: 13, fill: "#dca43f" }) :
        svgEl("rect", { x: x - 13, y: y - 13, width: 26, height: 26, rx: 6, fill: "#195440" }));
      group.append(svgEl("text", { x, y: y + 4, "text-anchor": "middle", class: `map-letter ${donor ? "map-batch-number" : ""}` }, donor ? index + 1 : String.fromCharCode(65 + index)));
      const name = location.name.length > 25 ? location.name.slice(0, 23) + "..." : location.name;
      const width = Math.max(name.length * 7.4, 148);
      const offsets = donor ? [[0, -57], [-125, -15], [125, -15], [0, 45]] :
        [[0, 45], [125, -15], [-125, -15], [0, -57]];
      offsets.push([-110, -75], [110, -75], [-110, 65], [110, 65], [0, -100], [0, 90]);
      const alternatives = [-240, -180, -120, -60, 0, 60, 120, 180, 240].flatMap((dx) =>
        [-140, -95, -50, 0, 50, 95, 140].map((dy) => [dx, dy]));
      offsets.push(...alternatives.sort((a, b) => Math.hypot(...a) - Math.hypot(...b)));
      for (const [dx, dy] of offsets) {
        const box = { left: x + dx - width / 2 - 5, right: x + dx + width / 2 + 5,
          top: y + dy - 14, bottom: y + dy + 21 };
        if (box.left < 15 || box.right > 945 || box.top < 40 || box.bottom > 455 || occupied.some((other) => intersects(box, other))) continue;
        occupied.push(box);
        if (dx || Math.abs(dy) > 60) group.append(svgEl("line", {
          x1: x, y1: y, x2: x + dx, y2: y + dy, stroke: "#afbeaa", "stroke-width": 1, "stroke-dasharray": "2 3",
        }));
        group.append(svgEl("text", { x: x + dx, y: y + dy, "text-anchor": "middle", class: "map-label" }, name));
        group.append(svgEl("text", { x: x + dx, y: y + dy + 16, "text-anchor": "middle", class: "map-sub-label" }, donor ? `${location.quantity} servings / ${location.category}` : `${location.demand} requested`));
        break;
      }
      const edit = () => {
        if (state.dirty) {
          announce("This map shows the previous plan. Use Supply & hubs to edit current inputs, or run the planner first.");
          showView("locations");
          return;
        }
        openEditor(kind, location.id);
      };
      group.addEventListener("click", edit);
      group.addEventListener("keydown", (event) => {
        if (["Enter", " "].includes(event.key)) { event.preventDefault(); edit(); }
      });
      svg.append(group);
    });
  }
  svg.append(svgEl("line", { x1: 35, y1: 465, x2: 35 + scale, y2: 465, stroke: "#859681", "stroke-width": 2 }));
  svg.append(svgEl("text", { x: 35, y: 483, class: "map-axis" }, "1 km"));
  $("#network-map").replaceChildren(svg);
}

function renderLocations() {
  for (const kind of ["donors", "hubs"]) {
    const donor = kind === "donors";
    const items = state.scenario[kind];
    $(`#${donor ? "donor" : "hub"}-count`).textContent = items.length;
    const target = $(`#${donor ? "donor" : "hub"}-list`);
    target.replaceChildren(...items.map((item) =>
      el("article", { class: "location-card" },
        el("div", { class: "location-card-heading" }, el("h3", { text: item.name }),
          el("span", { class: `category-pill ${donor ? item.category : "hub"}`, text: donor ? item.category : item.cold_storage ? "Cold storage" : "Ambient" })),
        el("p", { class: "location-quantity", text: donor ? item.quantity : item.demand },
          el("span", { text: donor ? "servings available" : `requested / ${item.capacity} capacity` })),
        el("p", { class: "muted small", text: donor ? `Ready ${time(item.ready_minute)} / expires ${time(item.expires_minute)}` : `Open ${time(item.open_minute)} - ${time(item.close_minute)}` }),
        el("p", { class: "muted small", text: donor ? `Grid position: ${item.x_km}, ${item.y_km} km` : `Accepts: ${item.accepts.join(", ")}` }),
        el("div", { class: "actions" },
          button("Edit details", "secondary", () => openEditor(kind, item.id), `Edit ${item.name}`),
          button("Remove", "subtle danger", () => {
            if (!confirm(`Remove "${item.name}" from this working scenario? Saved snapshots are unchanged.`)) return;
            state.scenario[kind] = state.scenario[kind].filter((location) => location.id !== item.id);
            changed();
            renderLocations();
          }, `Remove ${item.name}`)))));
    if (!items.length) target.append(el("p", { class: "empty-state", text: donor ? "No surplus batches yet. Add your first fictional batch." : "No receiving hubs yet. Add a destination for the surplus." }));
  }
}

function field(name, label, value, type = "number", constraints = {}) {
  const input = el("input", { id: `edit-${name}`, name, type, required: "", ...constraints });
  input.value = value;
  return el("div", { class: "form-field" }, el("label", { for: `edit-${name}`, text: label }), input);
}

function openEditor(kind, id = null) {
  if (!state.scenario) return;
  if (!id && state.scenario[kind].length >= 20) {
    announce("The prototype supports at most 20 batches and 20 hubs per scenario.", true);
    return;
  }
  const donor = kind === "donors";
  const item = id ? state.scenario[kind].find((location) => location.id === id) : {
    id: `${donor ? "batch" : "hub"}-${[...crypto.getRandomValues(new Uint8Array(8))].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`,
    name: "", x_km: 5, y_km: 5,
    ...(donor ? { quantity: 30, category: "produce", ready_minute: 600, expires_minute: 720 } :
      { demand: 30, capacity: 30, accepts: ["produce", "bakery"], cold_storage: false, open_minute: 600, close_minute: 720 }),
  };
  state.editing = { kind, id, item };
  $("#editor-title").textContent = `${id ? "Edit" : "Add"} ${donor ? "surplus batch" : "receiving hub"}`;
  $("#editor-error").hidden = true;
  const fields = [
    field("name", "Fictional location name", item.name, "text", { maxlength: 80 }),
    el("div", { class: "field-row" },
      field("x_km", "Grid X (km)", item.x_km, "number", { min: 0, max: 20, step: "any" }),
      field("y_km", "Grid Y (km)", item.y_km, "number", { min: 0, max: 20, step: "any" })),
  ];
  if (donor) {
    const select = el("select", { name: "category", id: "edit-category" },
      ...categories.map((category) => el("option", { value: category, text: category[0].toUpperCase() + category.slice(1) })));
    select.value = item.category;
    fields.push(el("div", { class: "field-row" }, field("quantity", "Servings available", item.quantity, "number", { min: 0, max: 10000, step: 1 }),
      el("div", { class: "form-field" }, el("label", { for: "edit-category", text: "Food category" }), select)));
  } else {
    fields.push(el("div", { class: "field-row" },
      field("demand", "Requested servings", item.demand, "number", { min: 0, max: 10000, step: 1 }),
      field("capacity", "Receiving capacity", item.capacity, "number", { min: 0, max: 10000, step: 1 })));
    const accepts = el("fieldset", {}, el("legend", { text: "Accepted food categories (choose at least one)" }));
    for (const category of categories) {
      const checkbox = el("input", { type: "checkbox", name: "accepts", value: category });
      checkbox.checked = item.accepts.includes(category);
      accepts.append(el("label", { class: "checkbox-label" }, checkbox, category));
    }
    fields.push(accepts);
    const cold = el("input", { type: "checkbox", name: "cold_storage" });
    cold.checked = item.cold_storage;
    fields.push(el("div", { class: "form-field" }, el("label", { class: "checkbox-label" }, cold, "Cold storage available")));
  }
  fields.push(el("div", { class: "field-row" },
    field(donor ? "ready_minute" : "open_minute", donor ? "Ready for collection" : "Hub opens", time(donor ? item.ready_minute : item.open_minute), "time"),
    field(donor ? "expires_minute" : "close_minute", donor ? "Batch expires" : "Hub closes", time(donor ? item.expires_minute : item.close_minute), "time")));
  $("#editor-fields").replaceChildren(...fields);
  $("#editor-dialog").showModal();
}

async function refreshSnapshots() {
  state.snapshots = (await (await request("/api/scenarios")).json()).items;
  $("#saved-count").textContent = state.snapshots.length;
  $("#snapshot-list").replaceChildren(...state.snapshots.map((snapshot) =>
    el("div", { class: "snapshot-row" },
      el("div", {}, el("h3", { text: snapshot.name }), el("p", { text: new Date(snapshot.created_at * 1000).toLocaleString("en") })),
      el("div", { class: "actions" },
        button("Load", "secondary", snapshotAction(async () => {
          if (state.dirty && !confirm("Replace your unsaved working changes with this snapshot?")) return;
          const scenario = await (await request(`/api/scenarios/${snapshot.id}`)).json();
          await replaceScenario(scenario, "Snapshot loaded and plan recomputed.");
          $("#snapshots-dialog").close();
        }), `Load ${snapshot.name}`),
        button("Delete", "subtle danger", snapshotAction(async () => {
          if (!confirm(`Delete saved snapshot "${snapshot.name}"? The current working scenario will remain.`)) return;
          await request(`/api/scenarios/${snapshot.id}`, undefined, "DELETE");
          await refreshSnapshots();
        }), `Delete ${snapshot.name}`)))));
  if (!state.snapshots.length) $("#snapshot-list").append(el("p", { class: "empty-state", text: "No saved snapshots yet. Save a scenario to compare your next what-if." }));
}

function snapshotAction(action) {
  return async () => {
    $("#snapshot-error").hidden = true;
    try { await action(); }
    catch (error) {
      $("#snapshot-error").textContent = error.message;
      $("#snapshot-error").hidden = false;
    }
  };
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = el("a", { href: url, download: filename });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("#settings-form").addEventListener("input", (event) => {
  if (!state.scenario) return;
  const input = event.target;
  if (!input.name) return;
  state.scenario[input.name] = input.name === "name" ? input.value :
    input.type === "time" ? minutes(input.value) : input.value === "" ? null : Number(input.value);
  if (input.name === "max_leg_km") $("#distance-value").textContent = `${number(input.value)} km`;
  changed();
});
$("#settings-form").addEventListener("submit", handle(async (event) => {
  event.preventDefault();
  await runPlan();
}));
$$(".tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
$("#method-link").addEventListener("click", (event) => { event.preventDefault(); showView("method"); });
const parameterToggle = button("Adjust plan parameters", "secondary mobile-parameters", () => {
  const open = $(".settings-panel").classList.toggle("mobile-open");
  parameterToggle.setAttribute("aria-expanded", String(open));
});
parameterToggle.setAttribute("aria-expanded", "false");
parameterToggle.setAttribute("aria-controls", "settings-form");
$(".layout").before(parameterToggle);
$("#load-demo").addEventListener("click", handle(async () => {
  if (state.dirty && !confirm("Replace your unsaved working changes with the synthetic sample?")) return;
  await replaceScenario(await (await request("/api/demo")).json(), "Synthetic sample restored.");
  showView("overview");
}));
$("#import-button").addEventListener("click", () => $("#import-file").click());
$("#import-file").addEventListener("change", handle(async () => {
  const file = $("#import-file").files[0];
  $("#import-file").value = "";
  if (!file) return;
  if (file.size > 128 * 1024) throw new Error("Import is limited to 128 KiB.");
  let scenario;
  try { scenario = JSON.parse(await file.text()); }
  catch { throw new Error("The selected file is not valid JSON. Your current scenario is unchanged."); }
  if (state.dirty && !confirm("Replace your unsaved working changes with this imported scenario?")) return;
  await replaceScenario(scenario, "Scenario imported and validated. Its values are simulation inputs, not verified real-world data.");
}));
$("#save-button").addEventListener("click", handle(async () => {
  if (!state.scenario) throw new Error("Load a scenario before saving.");
  if (!$("#settings-form").reportValidity()) return;
  $("#save-button").disabled = true;
  try {
    await request("/api/scenarios", state.scenario);
    await refreshSnapshots();
    announce("Snapshot saved for this browser session. Retained for seven days; export JSON for a permanent copy.");
  } finally { $("#save-button").disabled = false; }
}));
$("#saved-button").addEventListener("click", handle(async () => {
  await refreshSnapshots();
  $("#snapshot-error").hidden = true;
  $("#snapshots-dialog").showModal();
}));
$("#export-json").addEventListener("click", handle(async () => {
  await request("/api/plan", state.scenario);
  download(new Blob([JSON.stringify(state.scenario, null, 2) + "\n"], { type: "application/json" }), "commontable-scenario.json");
  announce("Scenario JSON exported.");
}));
$("#export-csv").addEventListener("click", handle(async () => {
  if (!state.resultScenario) throw new Error("Run the planner before exporting.");
  if (state.dirty) throw new Error("Run the planner before exporting: the displayed results are out of date.");
  const response = await request("/api/export/csv", state.resultScenario);
  download(await response.blob(), "commontable-transfers.csv");
  announce("Transfer plan exported. Each row is a simulated handoff, not dispatch authorization.");
}));
$("#add-donor").addEventListener("click", () => openEditor("donors"));
$("#add-hub").addEventListener("click", () => openEditor("hubs"));
$$("[data-close]").forEach((node) => node.addEventListener("click", () => $(`#${node.dataset.close}`).close()));
$("#editor-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const { kind, id, item } = state.editing;
  const updated = { ...item, name: form.get("name"), x_km: Number(form.get("x_km")), y_km: Number(form.get("y_km")) };
  if (kind === "donors") Object.assign(updated, {
    quantity: Number(form.get("quantity")), category: form.get("category"),
    ready_minute: minutes(form.get("ready_minute")), expires_minute: minutes(form.get("expires_minute")),
  });
  else Object.assign(updated, {
    demand: Number(form.get("demand")), capacity: Number(form.get("capacity")), accepts: form.getAll("accepts"),
    cold_storage: form.has("cold_storage"), open_minute: minutes(form.get("open_minute")), close_minute: minutes(form.get("close_minute")),
  });
  const candidate = structuredClone(state.scenario);
  candidate[kind] = id ? candidate[kind].map((location) => location.id === id ? updated : location) : [...candidate[kind], updated];
  const submit = event.submitter;
  submit.disabled = true;
  try {
    await request("/api/plan", candidate);
    state.scenario = candidate;
    changed();
    renderLocations();
    $("#editor-dialog").close();
    announce("Location updated. Run the planner to recompute transfers.");
  } catch (error) {
    $("#editor-error").textContent = error.message;
    $("#editor-error").hidden = false;
  } finally { submit.disabled = false; }
});

await handle(async () => {
  await replaceScenario(await (await request("/api/demo")).json());
  await refreshSnapshots();
})();
