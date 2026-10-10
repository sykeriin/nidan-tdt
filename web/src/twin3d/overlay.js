import Chart from 'chart.js/auto';
// HTML drawn over the canvas: tooltip, sensor badges, detail boxes with leader lines,
// X-ray button and the loading / fallback message (UI_DESIGN §6.4, §6.5).

import { ESTIMATED_NOTE, PART_MAP, SENSOR_NOTE, STATUS_WORD, UNMONITORED } from './partMap.js';

const TOOLTIP_OFFSET = 14;
const MAX_BOXES = 2;
const SVG_NS = 'http://www.w3.org/2000/svg';
const SEVERITY_RANK = { critical: 0, warning: 1, info: 2 };
const URGENCY = { immediate: 'Immediate', '24h': '24 h', '7d': '7 d', next_scheduled: 'Next scheduled' };

// Alert text can come from imported files, so everything placed in markup is escaped.
const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);

const withUnit = (value, unit) => (unit ? `${value} ${unit}` : `${value}`);

function formatReading(reading) {
  if (!reading) return '';
  const twin = reading.twin == null ? '' : ` (twin ${withUnit(reading.twin, reading.unit)})`;
  return `${reading.label} ${withUnit(reading.value, reading.unit)}${twin}`;
}

// Python decides status and availability; this only words them.
function statusWord(part) {
  const key = part?.status ?? 'grey';
  return key === 'grey' && part?.estimated ? ESTIMATED_NOTE : STATUS_WORD[key] ?? key;
}

// Alerts placed on a part: asset before sensor, then worst severity, then newest.
function alertsFor(view, id) {
  return (view?.alerts ?? []).filter((a) => a.part === id).sort((a, b) =>
    (a.origin === 'sensor') - (b.origin === 'sensor')
    || (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3)
    || (a.timestamp < b.timestamp ? 1 : -1));
}

function alertMarkup(id, part, alerts) {
  if (UNMONITORED[id]) return `<p class="box__plain">${esc(PART_MAP[id].label)}: ${esc(UNMONITORED[id])}.</p>`;
  const lines = [];
  const [primary, ...others] = alerts;
  if (primary) {
    const since = `Since ${esc(primary.timestamp.slice(0, 16).replace('T', ' '))}`;
    const lead = primary.lead_time_h == null ? '' : ` · lead time ${esc(primary.lead_time_h)} h vs baseline`;
    lines.push(
      `<p class="box__meta num">${esc(primary.type)} · detector: ${esc(primary.detector)} · origin: ${esc(primary.origin)}</p>`,
      `<p class="box__since">${since}${lead}</p>`,
      `<p class="box__explain">“${esc(primary.explanation)}”</p>`,
    );
    if (primary.origin === 'sensor') lines.push(`<p class="box__sensor">${esc(SENSOR_NOTE)}.</p>`);
    if (others.length) {
      const list = others.map((a) => `${esc(a.type)} (${esc(a.origin === 'sensor' ? 'sensor' : a.severity)})`).join(', ');
      lines.push(`<p class="box__more">Also active: ${list}</p>`);
    }
  } else if (part?.available === false && !part.estimated) {
    lines.push(`<p class="box__plain">No data: ${esc(PART_MAP[id].noData)}.</p>`);
  } else if (part?.status === 'grey') {
    lines.push(`<p class="box__plain">${esc(ESTIMATED_NOTE)}: ${esc(PART_MAP[id].noData)}.</p>`);
  } else {
    lines.push('<p class="box__ok">Operating normally</p>');
  }
  if (part?.estimated && part.status !== 'grey') lines.push(`<p class="box__plain">${esc(ESTIMATED_NOTE)}</p>`);
  return lines.join('');
}

function readingsMarkup(part) {
  const readings = part?.readings ?? [];
  if (!readings.length) return '';
  const hasTwin = readings.some((r) => r.twin != null);
  const rows = readings.map((r) => {
    let twin = '';
    if (r.twin != null) {
      const diff = r.value - r.twin;
      twin = `${esc(withUnit(r.twin, r.unit))} <span class="box__diff">(${diff >= 0 ? '+' : ''}${diff.toFixed(1)})</span>`;
    }
    return `<tr><th scope="row">${esc(r.label)}</th><td class="num">${esc(withUnit(r.value, r.unit))}</td>`
      + `${hasTwin ? `<td class="num box__twin">${twin}</td>` : ''}</tr>`;
  }).join('');
  const head = `<tr><th scope="col">Readings</th><th scope="col">measured</th>${hasTwin ? '<th scope="col">twin</th>' : ''}</tr>`;
  return `<table class="box__table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
}

function recommendationMarkup(alert) {
  const rec = alert?.recommendation;
  if (!rec) return '';
  const meta = [
    rec.test ? `Test: ${esc(rec.test)}` : '',
    `Urgency ${esc(URGENCY[rec.urgency] ?? rec.urgency)}`,
    rec.standard_ref ? `ref: ${esc(rec.standard_ref)}` : '',
  ].filter(Boolean).join(' · ');
  return `<p><strong>Recommended:</strong> ${esc(rec.action)}</p><p class="box__recmeta">${meta}</p>`;
}

function createChart(canvas) {
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { data: [], borderColor: token('--accent'), borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 },
        { data: [], borderColor: token('--text'), borderWidth: 1.5, pointRadius: 0,
          fill: '-1', backgroundColor: 'rgba(15, 23, 42, 0.08)' },   // gap to the twin = residual
      ],
    },
    options: {
      animation: false,          // replay ticks must not animate
      responsive: true,
      maintainAspectRatio: false,
      events: [],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { display: false },
        y: {
          border: { display: false },
          grid: { color: token('--border') },
          ticks: { maxTicksLimit: 4, color: token('--muted'), font: { family: 'JetBrains Mono', size: 10 } },
        },
      },
    },
  });
}

// handlers: onXray(on), onResetView(), onBoxes(openPartIds, oldest first)
export function createOverlay(container, handlers = {}) {
  const tooltip = container.querySelector('#tooltip');
  const label = tooltip.querySelector('.tooltip__label');
  const status = tooltip.querySelector('.tooltip__status');
  const word = tooltip.querySelector('.status__word');
  const reading = tooltip.querySelector('.tooltip__reading');
  const note = tooltip.querySelector('.tooltip__note');
  const xrayButton = container.querySelector('#xray');
  const message = container.querySelector('#message');
  const badgeLayer = container.querySelector('#badges');
  const boxLayer = container.querySelector('#boxes');
  const leaderLayer = container.querySelector('#leaders');
  const badges = new Map();   // part id -> element
  const boxes = [];           // open detail boxes, oldest first
  const resetButton = container.querySelector('#reset-view');
  let lastView = null;

  xrayButton.addEventListener('click', () => {
    handlers.onXray?.(xrayButton.getAttribute('aria-pressed') !== 'true');
  });
  resetButton.addEventListener('click', () => handlers.onResetView?.());

  const notifyBoxes = () => handlers.onBoxes?.(boxes.map((box) => box.id));

  function renderBox(box, view) {
    const { id, el } = box;
    const part = view?.parts?.[id];
    const alerts = alertsFor(view, id);
    const key = UNMONITORED[id] ? 'grey' : part?.status ?? 'grey';
    el.dataset.status = key;
    box.leader.dataset.status = key;
    el.querySelector('.box__status').hidden = Boolean(UNMONITORED[id]);
    el.querySelector('.status__word').textContent = statusWord(part);
    el.querySelector('.box__simulated').hidden = !view?.simulated;
    el.querySelector('.box__alert').innerHTML = alertMarkup(id, part, alerts);
    el.querySelector('.box__readings').innerHTML = readingsMarkup(part);
    el.querySelector('.box__rec').innerHTML = recommendationMarkup(alerts[0]);

    const history = view?.history?.[id];
    const chartBlock = el.querySelector('.box__chart');
    chartBlock.hidden = !history;
    if (!chartBlock.hidden) {
      box.chart ??= createChart(chartBlock.querySelector('canvas'));
      box.chart.data.labels = history.t;
      box.chart.data.datasets[0].data = history.twin;
      box.chart.data.datasets[1].data = history.measured;
      box.chart.update('none');
    }
  }

  function removeBox(box) {
    box.chart?.destroy();
    box.el.remove();
    box.leader.remove();
    boxes.splice(boxes.indexOf(box), 1);
  }

  function closeBox(id) {
    const box = boxes.find((b) => b.id === id);
    if (!box) return;
    removeBox(box);
    notifyBoxes();
  }

  function openBox(id) {
    if (!PART_MAP[id] || boxes.some((b) => b.id === id)) return;
    if (boxes.length >= MAX_BOXES) removeBox(boxes[0]);        // a third replaces the oldest
    const slot = boxes.some((b) => b.slot === 'left') ? 'right' : 'left';

    const el = document.createElement('article');
    el.className = 'box glass status';
    el.dataset.slot = slot;
    el.innerHTML = `
      <header class="box__head">
        <span class="box__status"><span class="status__icon" aria-hidden="true"></span><span class="status__word"></span></span>
        <strong class="box__part">${esc(PART_MAP[id].label)}</strong>
        <span class="box__simulated" hidden>SIMULATED</span>
        <button class="box__close" type="button" aria-label="Close ${esc(PART_MAP[id].label)} details">×</button>
      </header>
      <div class="box__alert"></div>
      <div class="box__readings"></div>
      <div class="box__chart" hidden>
        <div class="box__canvas"><canvas></canvas></div>
        <p class="box__legend">Last 48 h: measured (solid) vs twin (dashed)</p>
      </div>
      <div class="box__rec"></div>`;
    el.querySelector('.box__close').addEventListener('click', () => closeBox(id));
    boxLayer.append(el);

    const leader = document.createElementNS(SVG_NS, 'g');
    leader.setAttribute('class', 'leader status');
    leader.append(document.createElementNS(SVG_NS, 'line'), document.createElementNS(SVG_NS, 'circle'));
    leader.querySelector('circle').setAttribute('r', '4');
    leaderLayer.append(leader);

    const box = { id, el, slot, leader, chart: null };
    boxes.push(box);
    renderBox(box, lastView);
    notifyBoxes();
  }

  return {
    openBox,
    closeBox,

    closeAllBoxes() {
      if (!boxes.length) return;
      while (boxes.length) removeBox(boxes[0]);
      notifyBoxes();
    },

    // Every replay tick: refresh the open boxes with the new view.
    updateBoxes(view) {
      lastView = view;
      for (const box of boxes) renderBox(box, view);
    },

    // project(id) -> { x, y, behind, occluded } from the scene; called every frame, so the
    // line follows the part as the model turns.
    positionLeaders(project) {
      for (const box of boxes) {
        const at = project(box.id);
        const hidden = !at || at.behind;
        box.leader.style.display = hidden ? 'none' : '';
        if (hidden) continue;
        const x = box.slot === 'left' ? box.el.offsetLeft + box.el.offsetWidth : box.el.offsetLeft;
        const y = box.el.offsetTop + 20;
        const line = box.leader.firstChild;
        line.setAttribute('x1', x);
        line.setAttribute('y1', y);
        line.setAttribute('x2', at.x);
        line.setAttribute('y2', at.y);
        box.leader.lastChild.setAttribute('cx', at.x);
        box.leader.lastChild.setAttribute('cy', at.y);
        // Part hidden behind the model: the line stays, dashed and dim.
        box.leader.classList.toggle('leader--occluded', at.occluded);
      }
    },

    setXray(on) {
      xrayButton.setAttribute('aria-pressed', String(on));
    },

    setMessage(text) {
      message.textContent = text || '';
      message.hidden = !text;
    },

    // part: the entry from view.parts for this id, or undefined before the first render
    showTooltip(id, part, x, y) {
      label.textContent = PART_MAP[id].label;
      const notes = [];
      if (UNMONITORED[id]) {
        tooltip.dataset.status = 'grey';
        status.hidden = true;
        reading.textContent = UNMONITORED[id];
      } else {
        const key = part?.status ?? 'grey';
        tooltip.dataset.status = key;
        word.textContent = statusWord(part);
        status.hidden = false;
        reading.textContent = formatReading(part?.readings?.[0]);
        if (part?.available === false && !part.estimated) notes.push(`No data: ${PART_MAP[id].noData}`);
        if (part?.estimated && key !== 'grey') notes.push(ESTIMATED_NOTE);
        if (part?.sensor_alert_ids?.length) notes.push(SENSOR_NOTE);
      }
      reading.hidden = !reading.textContent;
      note.textContent = notes.join(' · ');
      note.hidden = !notes.length;
      tooltip.hidden = false;

      // Keep the tooltip inside the component.
      const maxX = container.clientWidth - tooltip.offsetWidth - 8;
      const maxY = container.clientHeight - tooltip.offsetHeight - 8;
      const left = Math.max(8, Math.min(x + TOOLTIP_OFFSET, maxX));
      const top = Math.max(8, Math.min(y + TOOLTIP_OFFSET, maxY));
      tooltip.style.transform = `translate(${left}px, ${top}px)`;
    },

    hideTooltip() {
      tooltip.hidden = true;
    },

    // A badge on every part that has sensor-origin alerts (UI_DESIGN §6.3).
    setSensorBadges(parts) {
      for (const id of Object.keys(PART_MAP)) {
        const wanted = Boolean(parts?.[id]?.sensor_alert_ids?.length);
        if (wanted && !badges.has(id)) {
          const badge = document.createElement('div');
          badge.className = 'sensor-badge';
          badge.innerHTML = '<span class="icon icon--info" aria-hidden="true"></span>Sensor';
          badgeLayer.append(badge);
          badges.set(id, badge);
        } else if (!wanted && badges.has(id)) {
          badges.get(id).remove();
          badges.delete(id);
        }
      }
    },

    positionBadges(project) {
      for (const [id, badge] of badges) {
        const at = project(id);
        badge.hidden = !at || at.behind;
        if (at) badge.style.transform = `translate(${at.x}px, ${at.y}px) translate(-50%, -50%)`;
      }
    },
  };
}
