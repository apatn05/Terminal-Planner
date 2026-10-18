// Terminal Planner dashboard. Everything on screen comes from the Python API;
// this file only draws it and sends button clicks back.

// What colour each action gets, grouped by the kind of work it is.
const TAG_KIND = {
  POWER: "cold", COLD_STORE: "cold", WAIT_COOL: "wait", ESCALATE: "hold",
  MOVE: "move", REROUTE: "move", SAFETY: "safety",
  REWEIGH: "verify", WAIT_INSPECT: "wait", HOLD: "hold", RECORD: "wait",
  RELEASE: "release", NEXT: "wait", DELAY: "wait", MONITOR: "cold",
};
const TAG_LABEL = {
  POWER: "POWER", COLD_STORE: "COLD STORE", WAIT_COOL: "WAIT PLUG", ESCALATE: "ESCALATE",
  MOVE: "MOVE", REROUTE: "REROUTE", SAFETY: "SAFETY", REWEIGH: "REWEIGH",
  WAIT_INSPECT: "WAIT SCALE", HOLD: "HOLD", RECORD: "FIX RECORD",
  RELEASE: "RELEASE", NEXT: "NEXT HOUR", DELAY: "DELAY", MONITOR: "MONITOR",
};
const LOCATION = {
  gate: "at gate", reefer_rack: "reefer rack", cold_storage: "cold storage",
  hold_area: "hold area", released: "released",
};

let current = null;
let filter = "all";

// ---------- helpers ----------

function showError(message) {
  const banner = document.getElementById("error-banner");
  banner.textContent = message;
  banner.hidden = !message;
}

async function api(path, method = "GET") {
  let res;
  try {
    // no-store: Safari otherwise likes to reuse old responses
    res = await fetch(path, { method, cache: "no-store" });
  } catch (err) {
    showError("Can't reach the Terminal Planner server. Is `python backend/app.py` still running in the terminal?");
    throw err;
  }
  if (!res.ok) {
    showError(`The server answered ${res.status} for ${path}. Check the terminal for the error.`);
    throw new Error(`${path} failed: ${res.status}`);
  }
  showError("");
  return res.json();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtHours(h) {
  if (h === null || h === undefined) return "";
  const minutes = Math.round(h * 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 10 ? `${hours} h ${String(minutes % 60).padStart(2, "0")}` : `${hours} h`;
}

function fmtAge(minutes) {
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

// Charges are worked out in US dollars, then shown in the selected port's currency (approximate rate).
const money = (n) => {
  const port = current ? current.port : { symbol: "$", rate: 1 };
  return port.symbol + Math.round(n * port.rate).toLocaleString("en-US");
};
const tag = (type) => `<span class="tag ${TAG_KIND[type] || "wait"}">${TAG_LABEL[type] || type}</span>`;

function formatId(id) {
  // ISO 6346 style: owner code, serial, boxed check digit
  return `${esc(id.slice(0, 4))} ${esc(id.slice(4, 10))}<span class="chk">${esc(id.slice(10))}</span>`;
}

function setPill(id, text, kind) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = `pill ${kind}`;
}

// ---------- render ----------

function render(s) {
  current = s;
  renderClock(s);
  renderMode(s.mode);
  renderTwists(s.twists);
  renderProblem(s.problem);
  renderStats(s.summary);
  renderLanes(s);
  renderQueue();
  renderCompare(s.comparison);
  renderLog(s.log);
  renderPort(s);
}

// Twist 2, global expansion: the port picker only changes names, map and ships.
function renderPort(s) {
  const select = document.getElementById("port-select");
  if (!select.options.length) {
    select.innerHTML = s.ports.map((p) => `<option value="${p.id}">${esc(p.name)}${p.country !== p.name ? " · " + esc(p.country) : ""}</option>`).join("");
  }
  select.value = s.port.id;
  document.getElementById("map-title").textContent = s.port.name;
  document.getElementById("map-hint").textContent = s.port.id === "la_lb"
    ? "Real Port of LA berth lines and live AIS ships"
    : `Live AIS ships around ${s.port.name}`;
  moveMap(s.port);
}

function renderClock(s) {
  const t = new Date(new Date(s.started_at).getTime() + s.clock * 3600 * 1000);
  document.getElementById("clock-time").textContent =
    t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  document.getElementById("clock-sub").textContent =
    `${t.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })} · hour ${s.clock}`;
}

const MODE_TEXT = {
  daily: "<b>Daily operations.</b> The planner keeps charges and spoilage down. Critical cargo gets a small boost.",
  crisis: "<b>Crisis.</b> Critical cargo (medical, relief, defense) goes first. Holds and safety rules don't change.",
};

function renderMode(mode) {
  document.getElementById("mode-bar").classList.toggle("crisis", mode === "crisis");
  document.querySelectorAll("#mode-switch button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  document.getElementById("mode-text").innerHTML = MODE_TEXT[mode];
}

function renderTwists(twists) {
  document.getElementById("twists").innerHTML = twists.map((t) => `
    <button class="twist ${t.active ? "active" : ""}" data-twist="${t.id}">
      <span class="twist-title">${esc(t.title)}</span>
      <span class="twist-effect">${esc(t.effect)}</span>
      <span class="twist-state">${t.active ? "ACTIVE" : "APPLY"}</span>
    </button>`).join("");
}

function renderProblem(p) {
  if (!p) {
    document.getElementById("pb-id").textContent = "No problem box in the terminal";
    return;
  }
  document.getElementById("pb-id").innerHTML = formatId(p.id);
  document.getElementById("pb-meta").textContent =
    `${p.size} ft reefer · ${p.carrier} · booked lane ${p.lane} · now: ${LOCATION[p.location]} · priority #${p.rank}`;

  const countdown = document.getElementById("pb-countdown");
  if (p.hours_left !== null) {
    countdown.className = "countdown urgent";
    countdown.innerHTML = `<div class="label">Cargo damage in</div><div class="value">${fmtHours(p.hours_left)}</div>`;
  } else {
    countdown.className = "countdown safe";
    countdown.innerHTML = `<div class="label">Temperature</div><div class="value">Cooling</div>`;
  }

  document.getElementById("pb-sources").innerHTML = p.sources.map((src) => `
    <div class="source ${src.conflict ? "conflict" : ""} ${src.untrusted ? "untrusted" : ""}">
      <div class="source-top">
        <span class="source-title">${esc(src.title)}</span>
        ${src.untrusted ? '<span class="badge untrusted">IGNORED</span>' : '<span class="badge">SIMULATED</span>'}
      </div>
      <div class="source-says">${esc(src.says)}</div>
      <div class="source-detail">${esc(src.detail)}</div>
      ${src.weight_check ? `<div class="weight-check">${esc(src.weight_check.text)}${
        src.weight_check.result ? `<b class="${src.weight_check.ok ? "pass" : "flag"}">${esc(src.weight_check.result)}</b>` : ""}</div>` : ""}
      <div class="source-verdict">${esc(src.verdict)}</div>
      <div class="source-foot">
        <span>${fmtAge(src.age_min)}</span>
        <span class="trust">Trusted for ${esc(src.trust)}</span>
      </div>
    </div>`).join("");

  const t = p.ticket;
  const tierEl = document.getElementById("pb-tier");
  tierEl.textContent = `Priority ticket · ${t.tier}`;
  tierEl.className = `tier-pill t${t.tier[1]}`;
  document.getElementById("pb-ticket").innerHTML = [
    ["Container", p.id], ["Need", t.need], ["Route", t.route],
    ["Weight", t.weight], ["Customs", t.customs], ["Action", t.action],
  ].map(([k, v]) => `<div class="ticket-row"><span>${k}</span><b>${esc(v)}</b></div>`).join("");

  // What the model learned from our dataset suggests, next to what the planner decided.
  const modelBox = document.getElementById("pb-model");
  modelBox.hidden = !p.model;
  if (p.model) {
    modelBox.className = `model-box ${p.model.check}`;
    modelBox.innerHTML = `
      <div class="model-head">Model suggests <span>decision tree · learned from ${current.model_rows} past decisions</span></div>
      <div class="model-action">${esc(p.model.action)}</div>
      <div class="model-sub">Risk: ${esc(p.model.risk)} · ${p.model.confidence}% of similar past cases</div>
      <div class="model-check">${p.model.check === "agree" ? "✓ " : ""}${esc(p.model.note)}</div>`;
  }

  document.getElementById("pb-story").innerHTML = p.story.map((line) => `<li>${esc(line)}</li>`).join("");
  document.getElementById("pb-actions").innerHTML = p.actions.map((a) => `
    <li>
      ${tag(a.type)}
      <div>
        <div class="step-text">${esc(a.text)}</div>
        <div class="step-why">${esc(a.why)}</div>
        <div class="step-who">${esc(a.who)}</div>
      </div>
    </li>`).join("");
}

function renderStats(sum) {
  const cards = [
    { label: "Boxes in terminal", value: sum.in_terminal, sub: `${sum.critical_cargo} critical (medical, relief, defense)` },
    { label: "Critical exceptions", value: sum.critical, sub: "warming or weight in doubt", cls: sum.critical ? "alert" : "" },
    { label: "Gate capacity", value: `${sum.lanes_open}/${sum.lanes_total}`, sub: `lanes open · ${sum.gate_per_hour} trucks/h`, cls: sum.lanes_open < sum.lanes_total ? "warn" : "" },
    { label: "Reefer plugs free", value: sum.plugs_free, sub: `cold storage free: ${sum.cold_free}` },
    { label: "Inspection slots free", value: sum.inspection_free, sub: "for reweigh and exams" },
    { label: "Charges accrued", value: money(sum.charges_total), sub: `+${money(sum.charges_per_hour)} per hour now`, cls: "warn" },
  ];
  document.getElementById("stats").innerHTML = cards.map((c) => `
    <div class="stat ${c.cls || ""}">
      <div class="stat-label">${c.label}</div>
      <div class="stat-value">${c.value}</div>
      <div class="stat-sub">${c.sub}</div>
    </div>`).join("");
}

function renderLanes(s) {
  // How many boxes the plan sends through each lane this hour.
  const using = {};
  for (const row of s.queue) {
    for (const a of row.actions) if (a.lane) using[a.lane] = (using[a.lane] || 0) + 1;
  }
  const perLane = s.summary.lanes_open ? s.summary.gate_per_hour / s.summary.lanes_open : 0;

  document.getElementById("lanes").innerHTML = s.lanes.map((lane) => {
    if (lane.status !== "open") {
      return `<button class="lane down" data-lane="${lane.id}">
        <span class="lane-id">${lane.id}</span>
        <span class="lane-state">DOWN</span>
        <span class="lane-sub">${esc(lane.reason)}</span>
      </button>`;
    }
    const used = using[lane.id] || 0;
    const pct = perLane ? Math.min(100, (used / perLane) * 100) : 0;
    return `<button class="lane open" data-lane="${lane.id}">
      <span class="lane-id">${lane.id}</span>
      <span class="lane-state">OPEN</span>
      <span class="lane-sub">${used} of ${perLane} trucks this hour</span>
      <span class="lane-bar"><span style="width:${pct}%"></span></span>
    </button>`;
  }).join("");
}

function rowMatches(row) {
  if (filter === "critical") return row.flags.includes("critical");
  if (filter === "perishable") return row.perishable;
  if (filter === "hold") return row.flags.includes("hold");
  if (filter === "weight") return row.flags.includes("weight");
  if (filter === "out") return row.actions.some((a) => a.type === "RELEASE" || a.type === "REROUTE");
  return true;
}

function renderQueue() {
  const rows = current.queue.filter(rowMatches);
  document.getElementById("queue").innerHTML = rows.map((row) => {
    const main = row.actions[0] || { type: "NEXT", text: "", why: "" };
    const extra = row.actions.length > 1 ? `<div class="sub">+${row.actions.length - 1} more actions</div>` : "";
    const flags = row.flags.map((f) => `<span class="flag ${f}">${f.toUpperCase()}</span>`).join("");

    let spoils = '<span class="t-dim">·</span>';
    if (row.damaged) spoils = '<span class="t-red">damaged</span>';
    else if (row.hours_left !== null) {
      const cls = row.hours_left < 2 ? "t-red" : row.hours_left < 6 ? "t-amber" : "";
      spoils = `<span class="mono ${cls}">${fmtHours(row.hours_left)}</span>`;
    }

    let free;
    if (row.free_h <= 0) free = `<span class="t-red mono">over ${Math.round(-row.free_h)} h</span><div class="sub">${money(row.charges)} so far</div>`;
    else if (row.free_h < 24) free = `<span class="t-amber mono">${Math.round(row.free_h)} h</span>`;
    else free = `<span class="mono">${Math.round(row.free_h)} h</span>`;

    const why = row.reasons.length ? row.reasons.join(" · ") : main.why;
    return `<tr class="${row.problem ? "problem" : ""}">
      <td class="num">${row.rank}</td>
      <td><span class="tier-pill t${row.tier}">P${row.tier}</span></td>
      <td><span class="id">${esc(row.id)}</span>${flags}<div class="sub">${row.size} ft ${row.kind} · ${LOCATION[row.location]}</div></td>
      <td>${esc(row.cargo)}${row.cargo_guessed ? '<div class="sub">guessed from set point</div>' : ""}${row.critical && row.critical !== row.cargo ? `<div class="sub">${esc(row.critical)}</div>` : ""}</td>
      <td class="nowrap">${spoils}</td>
      <td class="nowrap">${free}</td>
      <td>${tag(main.type)}<div class="sub">${esc(main.text)}</div>${extra}${modelTag(row.model)}</td>
      <td class="why">${esc(why)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="8" class="empty">Nothing matches this filter.</td></tr>`;
}

function modelTag(m) {
  if (!m) return "";
  const mark = { agree: "✓", override: "✗ rules override", differs: "≠ planner" }[m.check];
  return `<div class="model-tag ${m.check}">Model: ${esc(m.action)} ${mark}</div>`;
}

function renderCompare(c) {
  const columns = [["hold_all", "Hold all"], ["fifo", "First come"], ["planner", "Terminal Planner"]];
  const hours = (v) => (v === null ? "·" : `${v} h`);
  const metrics = [
    ["Critical cargo wait", "critical_wait", "low", hours],
    ["Cargo lost", "spoiled", "low"],
    ["Unsafe moves", "unsafe", "low"],
    ["Charges", "charges", "low", money],
    ["Boxes out", "released", "high"],
    ["Still waiting", "waiting", "low"],
  ];
  let html = `<div class="head"></div>` +
    columns.map(([key, name]) => `<div class="head val ${key === "planner" ? "ours" : ""}">${name}</div>`).join("");
  for (const [label, key, better, format] of metrics) {
    const values = columns.map(([col]) => c[col][key]);
    const known = values.filter((v) => v !== null);
    const best = better === "low" ? Math.min(...known) : Math.max(...known);
    const worst = better === "low" ? Math.max(...known) : Math.min(...known);
    html += `<div class="metric">${label}</div>`;
    html += values.map((v) => {
      const cls = best !== worst && v === best ? "best" : best !== worst && v === worst ? "worst" : "";
      return `<div class="val ${cls}">${format ? format(v) : v}</div>`;
    }).join("");
  }
  document.getElementById("compare").innerHTML = `<div class="compare">${html}</div>`;
}

function renderLog(log) {
  if (!log.length) return;
  document.getElementById("log").innerHTML = log.map((line) => `<li>${esc(line)}</li>`).join("");
}

// ---------- map and ships ----------

let map, shipLayer, berthLayer, mapPort = null;

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([33.735, -118.235], 12);
  // OpenStreetMap tiles need no API key. CSS (.dark-tiles) turns them dark to match the dashboard.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
    className: "dark-tiles",
  }).addTo(map);
  shipLayer = L.layerGroup().addTo(map);
  berthLayer = L.layerGroup().addTo(map);
}

function moveMap(port) {
  if (!map || port.id === mapPort) return;
  mapPort = port.id;
  map.setView(port.center, port.zoom);
  // Berth lines are Port of LA data, so only show them there.
  if (port.id === "la_lb") berthLayer.addTo(map);
  else berthLayer.remove();
  shipLayer.clearLayers();
  document.getElementById("ships").innerHTML = '<li class="empty">Loading ships…</li>';
  setTimeout(loadShips, 1500);     // give the AIS feed a moment to reconnect to the new area
}

async function loadBerths() {
  try {
    const data = await api("/api/berths");
    for (const berth of data.berths) {
      L.polyline(berth.lines, { color: "#67e8f9", weight: 3, opacity: 0.8 })
        .bindTooltip(berth.berth).addTo(berthLayer);
    }
    if (data.source === "unavailable") setPill("pill-berths", "Berths · offline", "off");
    else setPill("pill-berths", `Berths · ${data.source === "live" ? "LIVE" : "REAL, CACHED"} (${data.berths.length})`, data.source === "live" ? "live" : "cached");
  } catch (err) {
    setPill("pill-berths", "Berths · offline", "off");
  }
}

const SHIP_COLOR = { "At anchor": "#fbbf24", Moored: "#8a97ab", "Under way": "#60a5fa" };

async function loadShips() {
  if (!map) return;
  let data;
  try {
    data = await api("/api/ships");
  } catch (err) {
    return;
  }
  const ships = data.ships.slice().sort((a, b) =>
    (a.type === "Cargo" ? 0 : 1) - (b.type === "Cargo" ? 0 : 1) || (a.name || "").localeCompare(b.name || ""));

  shipLayer.clearLayers();
  for (const s of ships) {
    L.circleMarker([s.lat, s.lon], {
      radius: s.type === "Cargo" ? 6 : 4, weight: 1, color: "#0a0f19",
      fillColor: SHIP_COLOR[s.status] || "#a78bfa", fillOpacity: 0.95,
    }).bindPopup(`<b>${esc(s.name || "MMSI " + s.mmsi)}</b><br>${esc(s.type)} · ${esc(s.status)}<br>
        ${s.speed_kt ?? "?"} kt${s.destination ? " · to " + esc(s.destination) : ""}`)
      .addTo(shipLayer);
  }

  const anchored = ships.filter((s) => s.status === "At anchor").length;
  document.getElementById("ship-count").textContent = ships.length ? `${ships.length} ships · ${anchored} at anchor` : "";
  document.getElementById("ships").innerHTML = ships.map((s) => `
    <li>
      <div class="ship-name">${esc(s.name || "MMSI " + s.mmsi)}</div>
      <div class="ship-sub">${esc(s.type)} · ${esc(s.status)} · ${s.speed_kt ?? "?"} kt${s.destination ? " · " + esc(s.destination) : ""}</div>
    </li>`).join("") || `<li class="empty">${
      data.source === "no_key" ? "Add an aisstream.io API key to .env to see live ships." : "Waiting for the first AIS messages…"}</li>`;

  if (data.source === "live") setPill("pill-ships", `Ships · LIVE (${ships.length})`, "live");
  else if (data.source === "recorded") setPill("pill-ships", `Ships · RECORDED ${data.recorded_at.slice(11, 16)} UTC`, "recorded");
  else if (data.source === "no_key") setPill("pill-ships", "Ships · no API key", "off");
  else setPill("pill-ships", "Ships · connecting", "off");
}

// ---------- buttons ----------

async function run(button, path) {
  button.disabled = true;
  try {
    render(await api(path, "POST"));
  } finally {
    button.disabled = false;
  }
}

document.getElementById("btn-next").addEventListener("click", (e) => run(e.currentTarget, "/api/next-hour"));
document.getElementById("port-select").addEventListener("change", async (e) => {
  render(await api(`/api/port/${e.target.value}`, "POST"));
});
document.getElementById("btn-reset").addEventListener("click", (e) => run(e.currentTarget, "/api/reset"));

document.getElementById("mode-switch").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-mode]");
  if (button) render(await api(`/api/mode/${button.dataset.mode}`, "POST"));
});

document.getElementById("twists").addEventListener("click", async (e) => {
  const twist = e.target.closest("[data-twist]");
  if (twist && !twist.classList.contains("active")) {
    render(await api(`/api/twists/${twist.dataset.twist}`, "POST"));
  }
});

document.getElementById("lanes").addEventListener("click", async (e) => {
  const lane = e.target.closest("[data-lane]");
  if (lane) render(await api(`/api/lanes/${lane.dataset.lane}/toggle`, "POST"));
});

document.getElementById("filters").addEventListener("click", (e) => {
  const chip = e.target.closest("[data-filter]");
  if (!chip) return;
  filter = chip.dataset.filter;
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === chip));
  renderQueue();
});

// ---------- start ----------

async function refresh() {
  render(await api("/api/state"));
}

// The map is a nice-to-have: if it fails, the planner still works.
try {
  initMap();
  loadBerths();
} catch (err) {
  document.getElementById("map").innerHTML = '<p class="empty">Map could not load.</p>';
}
refresh();
setInterval(loadShips, 20 * 1000);
