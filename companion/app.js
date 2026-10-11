"use strict";
// Companion app: reads the backend's /replay NDJSON stream, pushes a notification for each NEW alert,
// and shows the pre-written response for that alert type (content/responses.json).
const $ = id => document.getElementById(id);
const SEV = {info: 0, warning: 1, critical: 2};
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: run without saving */ } },
};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

let CONTENT = null, swReg = null, abort = null, running = false;
let alerts = store.get("alerts", []);          // newest first; {a: backend alert, ds, test, acked}
const seen = new Set(alerts.map(x => x.a.id));
const snoozed = store.get("snoozed", {});      // type -> epoch ms
const cfg = Object.assign({backend: (location.protocol.startsWith("http") && location.port !== "5173" ? location.origin : "http://localhost:8000"), dataset: "S2", speed: 100000, minsev: "info", mutesensor: false}, store.get("cfg", {}));

// ---------------------------------------------------------------- content
const resp = type => CONTENT.types[type] || {
  title: type, push: "An alert was raised. Open for details.", meaning: "No pre-written response exists for this alert type.",
  safe_to_wait: "Unknown. Ask an engineer.", do_now: ["Contact an engineer"], check: [], escalate_if: "Always.", who: "Engineer",
  urgency: {critical: "24h", warning: "7d", info: "7d"},
};
const urgencyOf = (r, sev) => CONTENT.urgency_label[r.urgency[sev] || r.urgency.warning] || "";
const fmt = v => (typeof v === "number" ? +v.toPrecision(4) : v);
const when = ts => { const d = new Date(ts); return isNaN(d) ? String(ts) : d.toLocaleString([], {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}); };

// ---------------------------------------------------------------- notifications
async function notify(entry) {
  const a = entry.a, r = resp(a.type);
  if (a.origin === "sensor" && cfg.mutesensor) return;
  if (SEV[a.severity] < SEV[cfg.minsev]) return;
  if (!entry.test && (snoozed[a.type] || 0) > Date.now()) return;
  const title = `${entry.test ? "TEST: " : ""}${CONTENT.severity_label[a.severity] || a.severity}: ${r.title}`;
  const body = `${r.push}${a.simulated ? " (simulated data)" : ""}`;
  if (a.severity === "critical" && navigator.vibrate) navigator.vibrate([200, 100, 200]);
  if ("Notification" in window && Notification.permission === "granted") {
    const opts = {body, tag: a.id, data: {id: a.id}, requireInteraction: a.severity === "critical", icon: "icon.svg"};
    try { if (swReg) await swReg.showNotification(title, opts); else new Notification(title, opts); } catch { /* fall back to in-app only */ }
  }
  setNotice(`${title} — ${r.push}`);
}
function setNotice(t) { const n = $("notice"); n.textContent = t; n.classList.remove("hidden"); clearTimeout(setNotice.t); setNotice.t = setTimeout(() => n.classList.add("hidden"), 8000); }

function addAlert(a, ds, test) {
  if (seen.has(a.id)) return;
  seen.add(a.id);
  const entry = {a, ds, test: !!test, acked: false};
  alerts.unshift(entry);
  alerts = alerts.slice(0, 200);
  store.set("alerts", alerts);
  render();
  notify(entry);
}

// ---------------------------------------------------------------- rendering
function render() {
  const ul = $("feed"); ul.innerHTML = "";
  alerts.forEach(e => {
    const r = resp(e.a.type), li = document.createElement("li");
    li.className = `card ${e.a.severity}${e.acked ? " acked" : ""}`;
    li.innerHTML = `<div class="top"><span><span class="tag ${esc(e.a.severity)}">${esc(CONTENT.severity_label[e.a.severity] || e.a.severity)}</span>
      ${e.a.simulated ? '<span class="tag sim">SIMULATED</span>' : ""}${e.test ? '<span class="tag test">TEST</span>' : ""}
      ${e.a.origin === "sensor" ? '<span class="tag">Sensor</span>' : ""}</span><span>${esc(when(e.a.timestamp))}</span></div>
      <div class="title">${esc(r.title)}</div><div class="muted">${esc(r.push)}${e.acked ? " · Acknowledged" : ""}</div>`;
    li.onclick = () => openSheet(e.a.id);
    ul.appendChild(li);
  });
  $("empty").classList.toggle("hidden", alerts.length > 0);
  const open = alerts.filter(e => !e.acked && !e.test).length;
  $("badge").textContent = open; $("badge").classList.toggle("hidden", !open);
  document.title = open ? `(${open}) Transformer Alerts` : "Transformer Alerts";
}

function renderLibrary() {
  const ul = $("library"); ul.innerHTML = "";
  Object.entries(CONTENT.types).forEach(([type, r]) => {
    const li = document.createElement("li"); li.className = "card";
    li.innerHTML = `<div class="top"><span>${esc(type)}</span><span>${esc(r.who)}</span></div><div class="title">${esc(r.title)}</div>
      <div class="muted">${esc(r.push)}</div><div class="btns"><button data-t="${esc(type)}">Send test</button></div>`;
    li.querySelector("button").onclick = ev => { ev.stopPropagation(); sendTest(type); };
    li.onclick = () => openSheet(null, type);
    ul.appendChild(li);
  });
}

function sendTest(type) {
  const sev = type.endsWith("sensor") || type === "dead_channel" ? "warning" : "critical";
  addAlert({id: `test-${type}-${Date.now()}`, timestamp: new Date().toISOString(), type, severity: sev,
    origin: ["jump_sensor", "range_sensor", "stuck_sensor", "dead_channel", "drift_sensor", "implausible_sensor"].includes(type) ? "sensor" : "asset",
    value: null, threshold: null, explanation: "Test alert from the library. Not from the backend.", simulated: false, lead_time_h: null}, "test", true);
}

function openSheet(id, previewType) {
  const e = id ? alerts.find(x => x.a.id === id) : null;
  const type = e ? e.a.type : previewType, r = resp(type), sev = e ? e.a.severity : "warning";
  const a = e && e.a;
  const list = xs => xs.length ? `<ul>${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p class=muted>None.</p>";
  let html = `<h2>${esc(r.title)}</h2><p>`;
  if (a) html += `<span class="tag ${esc(sev)}">${esc(CONTENT.severity_label[sev] || sev)}</span> ${a.simulated ? '<span class="tag sim">SIMULATED</span> ' : ""}${e.test ? '<span class="tag test">TEST</span> ' : ""}<span class="muted">${esc(when(a.timestamp))}</span>`;
  html += `</p><div class="box"><b>${esc(urgencyOf(r, sev))}</b> · ${esc(r.who)}</div>`;
  if (a && a.origin === "sensor") html += `<div class="box">This points to the sensor or data link. Check the device, not the transformer.</div>`;
  html += `<h3>What it means</h3><p>${esc(r.meaning)}</p><h3>Can it wait?</h3><p>${esc(r.safe_to_wait)}</p>
    <h3>Do now</h3><ol>${r.do_now.map(x => `<li>${esc(x)}</li>`).join("")}</ol><h3>Check</h3>${list(r.check)}
    <h3>Escalate if</h3><p>${esc(r.escalate_if)}</p>`;
  if (a) {
    const bits = [];
    if (a.value != null) bits.push(`value ${fmt(a.value)}`);
    if (a.threshold != null) bits.push(`threshold ${fmt(a.threshold)}`);
    if (a.lead_time_h != null) bits.push(`caught ${fmt(a.lead_time_h)} h before a plain threshold would`);
    html += `<h3>Technical detail</h3><div class="box">${esc(a.type)} · ${esc(a.detector)}${bits.length ? " · " + esc(bits.join(", ")) : ""}<br>${esc(a.explanation)}</div>`;
    html += `<div class="btns"><button class="primary" id="b-ack">${e.acked ? "Acknowledged" : "Acknowledge"}</button><button id="b-snz">Snooze 1 h</button><button id="b-esc">Escalate</button></div><div id="reply" class="reply hidden"></div>`;
  } else html += `<p class="muted">Library preview. Buttons appear on a real alert.</p>`;
  $("sheet-content").innerHTML = html;
  $("sheet").classList.remove("hidden");
  if (!a) return;
  const reply = t => { const el = $("reply"); el.textContent = t; el.classList.remove("hidden"); };
  $("b-ack").onclick = () => { e.acked = true; store.set("alerts", alerts); render(); reply(CONTENT.actions.ack_reply); };
  $("b-snz").onclick = () => { snoozed[a.type] = Date.now() + 3600e3; store.set("snoozed", snoozed); reply(CONTENT.actions.snooze_reply); };
  $("b-esc").onclick = async () => {
    const vl = a.value != null ? `Value ${fmt(a.value)}${a.threshold != null ? " against threshold " + fmt(a.threshold) : ""}. ` : "";
    const text = CONTENT.actions.escalate_template
      .replace("{title}", r.title).replace("{severity}", sev).replace("{time}", when(a.timestamp)).replace("{value_line}", vl)
      .replace("{dataset}", e.ds || "-").replace("{sim}", a.simulated ? " (SIMULATED)" : "").replace("{meaning}", r.meaning);
    try { if (navigator.share) { await navigator.share({title: "Transformer alert", text}); reply("Shared."); return; } } catch { /* cancelled */ }
    try { await navigator.clipboard.writeText(text); reply("Message copied. Paste it into your chat or email to the engineer:\n\n" + text); }
    catch { reply("Copy this message and send it to the engineer:\n\n" + text); }
  };
}

// ---------------------------------------------------------------- monitoring
const api = p => cfg.backend.replace(/\/+$/, "") + p;
function setStatus(t) { $("status").textContent = t; }

async function loadDatasets() {
  const sel = $("dataset");
  try {
    const list = await (await fetch(api("/api/datasets"))).json();
    sel.innerHTML = list.map(d => `<option value="${esc(d.dataset_id)}">${esc(d.dataset_id)} - ${esc(d.name)}${d.simulated ? " (simulated)" : ""}</option>`).join("");
    if (list.some(d => d.dataset_id === cfg.dataset)) sel.value = cfg.dataset; else cfg.dataset = sel.value;
  } catch {
    sel.innerHTML = `<option value="${esc(cfg.dataset)}">${esc(cfg.dataset)}</option>`;
    setStatus("Cannot reach the backend at " + cfg.backend);
  }
}

function setHealth(h) {
  const el = $("health");
  if (!h) { el.classList.add("hidden"); return; }
  el.className = `pill ${h.band}`; el.textContent = `Health ${Math.round(h.score)} ${h.band}`;
}

async function start() {
  if (running) return;
  running = true; abort = new AbortController();
  $("toggle").textContent = "Stop monitoring";
  const ds = cfg.dataset;
  setStatus(`Connecting to ${cfg.backend} …`);
  try {
    const url = api(`/api/datasets/${encodeURIComponent(ds)}/replay?speed=${encodeURIComponent(cfg.speed)}&limit=50000`);
    const res = await fetch(url, {signal: abort.signal});
    if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 120)}`);
    const rd = res.body.getReader(), dec = new TextDecoder();
    let buf = "", n = 0;
    for (;;) {
      const {done, value} = await rd.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line) continue;
        let s; try { s = JSON.parse(line); } catch { continue; }
        n++; setHealth(s.health); setStatus(`Monitoring ${ds} · ${when(s.timestamp)} · ${n} samples`);
        (s.alerts || []).slice().sort((x, y) => String(x.timestamp).localeCompare(String(y.timestamp))).forEach(a => addAlert(a, ds, false));
      }
    }
    setStatus(`Replay of ${ds} finished (${n} samples)`);
  } catch (err) {
    if (err.name !== "AbortError") setStatus("Stopped: " + err.message);
    else setStatus("Not monitoring");
  } finally { running = false; $("toggle").textContent = "Start monitoring"; }
}
const stop = () => abort && abort.abort();

// ---------------------------------------------------------------- test alerts sent from the dashboard
let testSince = null;
async function pollTests() {
  try {
    const r = await fetch(api("/api/companion/test-alerts" + (testSince == null ? "" : `?since=${testSince}`)));
    if (r.ok) {
      const j = await r.json();
      if (testSince != null) j.items.forEach(t => (t.alert.live ? addAlert(t.alert, "live", false) : addAlert(t.alert, "test", true)));
      testSince = j.latest;
    }
  } catch { /* backend unreachable: try again on the next tick */ }
}
setInterval(pollTests, 2500);

// ---------------------------------------------------------------- wiring
function permState() {
  const p = !("Notification" in window) ? "not supported in this browser" : Notification.permission === "granted" ? "allowed" : Notification.permission === "denied" ? "blocked in browser settings" : "not asked yet";
  $("permstate").textContent = "Notifications: " + p;
}

function bind() {
  document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
    document.querySelectorAll("nav button").forEach(x => x.classList.toggle("active", x === b));
    ["feed", "library", "settings"].forEach(t => $("tab-" + t).classList.toggle("hidden", t !== b.dataset.tab));
  });
  $("toggle").onclick = () => running ? stop() : start();
  $("clear").onclick = () => { alerts = []; seen.clear(); store.set("alerts", alerts); render(); };
  $("close-sheet").onclick = () => $("sheet").classList.add("hidden");
  $("sheet").onclick = ev => { if (ev.target === $("sheet")) $("sheet").classList.add("hidden"); };
  $("backend").value = cfg.backend; $("speed").value = cfg.speed; $("minsev").value = cfg.minsev; $("mutesensor").checked = cfg.mutesensor;
  const save = () => { cfg.backend = $("backend").value.trim() || cfg.backend; cfg.speed = Math.max(1, +$("speed").value || 100000);
    cfg.minsev = $("minsev").value; cfg.mutesensor = $("mutesensor").checked; cfg.dataset = $("dataset").value || cfg.dataset; store.set("cfg", cfg); };
  ["backend", "speed", "minsev", "mutesensor", "dataset"].forEach(id => $(id).onchange = () => { save(); if (id === "backend") loadDatasets(); });
  $("reload-ds").onclick = () => { save(); loadDatasets(); };
  $("perm").onclick = async () => { if ("Notification" in window) await Notification.requestPermission(); permState(); };
  navigator.serviceWorker && navigator.serviceWorker.addEventListener("message", ev => ev.data && ev.data.open && openSheet(ev.data.open));
}

(async function init() {
  try { CONTENT = await (await fetch("content/responses.json")).json(); }
  catch { document.body.innerHTML = "<p style='padding:16px'>Could not load content/responses.json. Serve this folder over http (see companion/README.md).</p>"; return; }
  if ("serviceWorker" in navigator) { try { swReg = await navigator.serviceWorker.register("sw.js"); } catch { /* needs https or localhost */ } }
  bind(); permState(); render(); renderLibrary(); loadDatasets();
  const h = decodeURIComponent(location.hash.slice(1)); if (h && alerts.some(x => x.a.id === h)) openSheet(h);
})();
