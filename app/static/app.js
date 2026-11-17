/* Reporting ETL — dashboard client (vanilla JS + Chart.js, no build step). */
"use strict";

/* ============================================================== utilities */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const fmt = {
  usd: (v) => "$" + Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }),
  usdCompact: (v) => {
    const n = Number(v || 0);
    if (Math.abs(n) >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
    if (Math.abs(n) >= 1e3) return "$" + (n / 1e3).toFixed(1) + "K";
    return "$" + n.toFixed(0);
  },
  usd2: (v) => "$" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  int: (v) => Number(v || 0).toLocaleString("en-US"),
  pct: (v, d = 1) => (v == null ? "—" : Number(v).toFixed(d) + "%"),
  dur: (s) => (s == null ? "—" : s < 1 ? Math.round(s * 1000) + " ms" : s < 60 ? s.toFixed(2) + " s" : Math.floor(s / 60) + "m " + Math.round(s % 60) + "s"),
  month: (ym, style = "short") => new Date(ym + "-01T00:00:00").toLocaleDateString("en-US", { month: style, year: style === "long" ? "numeric" : undefined }),
  date: (d) => new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
  datetime: (iso) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
  ago: (iso) => {
    if (!iso) return "—";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 45) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  },
};

const ICON = {
  check: '<svg viewBox="0 0 24 24"><path d="m9.5 16.2-4.2-4.2-1.4 1.4 5.6 5.6 11-11-1.4-1.4z"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4z"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3 1.5 21h21zm-1 6h2v6h-2zm0 8h2v2h-2z"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="m12 6 6 7h-4v5h-4v-5H6z"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="m12 18-6-7h4V6h4v5h4z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M6 2h8l6 6v14H6zm7 1.5V9h5.5z"/></svg>',
  db: '<svg viewBox="0 0 24 24"><path d="M12 3C7.6 3 4 4.3 4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6c0-1.7-3.6-3-8-3z"/></svg>',
  arrow: '<svg viewBox="0 0 24 24"><path d="M5 11h10.2l-4.6-4.6L12 5l7 7-7 7-1.4-1.4 4.6-4.6H5z"/></svg>',
  dot: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/></svg>',
  revenue: '<svg viewBox="0 0 24 24"><path d="M11 3h2v2.1c1.9.3 3.4 1.5 3.6 3.4h-2.1c-.2-.9-1-1.6-2.5-1.6-1.6 0-2.4.7-2.4 1.6 0 .8.6 1.3 2.7 1.8 2.6.6 4.5 1.5 4.5 3.9 0 1.9-1.5 3.1-3.8 3.4V20h-2v-2.4c-2.2-.3-3.8-1.6-3.9-3.7h2.1c.1 1.1 1 1.9 2.8 1.9 1.7 0 2.6-.8 2.6-1.8 0-.9-.6-1.4-2.9-1.9-2.4-.6-4.3-1.5-4.3-3.8 0-1.8 1.5-3 3.6-3.3z"/></svg>',
  cart: '<svg viewBox="0 0 24 24"><path d="M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm10 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM3 2h3l.8 4H21l-2.5 8H8.3l-.5 2H19v2H5.2l1.2-4.6L4.4 4H3z"/></svg>',
  tag: '<svg viewBox="0 0 24 24"><path d="M3 3h8l10 10-8 8L3 11zm4.5 3a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"/></svg>',
  users: '<svg viewBox="0 0 24 24"><path d="M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm7.5 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM9 13c-3.3 0-7 1.6-7 4v3h14v-3c0-2.4-3.7-4-7-4zm7.5 0c-.5 0-1 0-1.6.1 1.3.9 2.1 2.2 2.1 3.9v3h6v-3c0-2.3-3.4-4-6.5-4z"/></svg>',
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* not json */ }
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res.json();
}

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

const pill = (status) => {
  const map = { success: ["success", ICON.check, "Success"], failed: ["failed", ICON.x, "Failed"], running: ["running", '<span class="spinner" style="border-color:var(--ring);border-top-color:var(--accent)"></span>', "Running"],
    error: ["error", ICON.x, "Error"], warning: ["warning", ICON.warn, "Warning"] };
  const [cls, icon, label] = map[status] || ["neutral", ICON.dot, status];
  return `<span class="pill ${cls}">${icon}${esc(label)}</span>`;
};

/* ================================================================ charts */
const charts = {};
const SERIES = () => [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5"), css("--s6"), css("--s7"), css("--s8")];
const STAGES = ["extract", "transform", "validate", "load"];
const stageColor = (i) => SERIES()[i];

function chartDefaults() {
  Chart.defaults.font.family = css("--font") || "system-ui";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css("--ink-3");
  Chart.defaults.borderColor = css("--grid");
  Chart.defaults.animation.duration = 450;
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: css("--ink"), titleColor: css("--page"), bodyColor: css("--page"), footerColor: css("--page"),
    padding: 10, cornerRadius: 8, boxPadding: 4, titleFont: { weight: "600" }, displayColors: true, usePointStyle: true,
  });
  Chart.defaults.plugins.legend.display = false;
}

function makeChart(id, config) {
  if (charts[id]) charts[id].destroy();
  const el = document.getElementById(id);
  if (!el) return null;
  charts[id] = new Chart(el, config);
  return charts[id];
}

const axisX = (extra = {}) => ({ grid: { display: false }, border: { color: css("--line-strong") }, ticks: { color: css("--ink-3") }, ...extra });
const axisY = (extra = {}) => ({ grid: { color: css("--grid"), drawTicks: false }, border: { display: false }, ticks: { color: css("--ink-3"), padding: 8 }, ...extra });

/* ================================================================= state */
const state = { meta: null, period: "all", region: "", periods: [], runs: [], polling: null, issuesPage: 0, lastRunId: null };

function buildPeriods(minDate, maxDate) {
  const periods = [{ key: "all", label: "All time", start: null, end: null }];
  if (!minDate || !maxDate) return periods;
  const min = new Date(minDate + "T00:00:00"), max = new Date(maxDate + "T00:00:00");
  const quarters = [];
  let y = min.getFullYear(), q = Math.floor(min.getMonth() / 3);
  while (y < max.getFullYear() || (y === max.getFullYear() && q <= Math.floor(max.getMonth() / 3))) {
    const s = new Date(y, q * 3, 1), e = new Date(y, q * 3 + 3, 0);
    const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    quarters.push({ key: `${y}Q${q + 1}`, label: `Q${q + 1}${min.getFullYear() !== max.getFullYear() ? " '" + String(y).slice(2) : ""}`, start: iso(s), end: iso(e) });
    q++; if (q > 3) { q = 0; y++; }
  }
  return periods.concat(quarters.slice(-4));
}
const currentPeriod = () => state.periods.find((p) => p.key === state.period) || state.periods[0];
function filterQS(withRegion = true) {
  const p = currentPeriod(), qs = new URLSearchParams();
  if (p?.start) qs.set("start", p.start);
  if (p?.end) qs.set("end", p.end);
  if (withRegion && state.region) qs.set("region", state.region);
  return qs.toString();
}

/* ================================================================ router */
const pages = { dashboard: loadDashboard, runs: loadRuns, quality: loadQuality, model: loadModel };
function parseHash() {
  const [path, query] = (location.hash.replace(/^#\/?/, "") || "dashboard").split("?");
  return { page: pages[path] ? path : "dashboard", params: new URLSearchParams(query || "") };
}
async function route() {
  const { page, params } = parseHash();
  $$(".page").forEach((p) => (p.hidden = p.id !== "page-" + page));
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  document.title = { dashboard: "Sales performance", runs: "Pipeline runs", quality: "Data quality", model: "Data model" }[page] + " · Reporting ETL";
  try { await pages[page](params); } catch (e) { console.error(e); toast("Could not load data: " + e.message); }
}

/* ============================================================= dashboard */
async function loadDashboard() {
  if (!state.meta) await refreshMeta();
  renderFilters();
  const qs = filterQS(), qsNoRegion = filterQS(false);
  const regionQS = state.region ? "region=" + encodeURIComponent(state.region) : "";
  const [overview, monthly, regions, categories, channels, products, status] = await Promise.all([
    api("/api/overview?" + qs), api("/api/sales/monthly?" + regionQS), api("/api/sales/by-region?" + qsNoRegion),
    api("/api/sales/by-category?" + qs), api("/api/sales/by-channel?" + qs), api("/api/sales/top-products?limit=8&" + qs),
    api("/api/pipeline/status"),
  ]);
  renderKpis(overview);
  renderMonthly(monthly);
  renderRegions(regions);
  renderCategories(categories);
  renderTopProducts(products);
  renderChannels(channels);
  renderFacts(overview, status);
}

function renderFilters() {
  const seg = $("#period-filter");
  seg.innerHTML = state.periods.map((p) => `<button type="button" role="radio" aria-checked="${p.key === state.period}" data-key="${p.key}">${esc(p.label)}</button>`).join("");
  const sel = $("#region-filter");
  const opts = ['<option value="">All regions</option>'].concat((state.meta.regions || []).map((r) => `<option ${r === state.region ? "selected" : ""}>${esc(r)}</option>`));
  sel.innerHTML = opts.join("");
}

function periodLabel() {
  const p = currentPeriod();
  if (!p.start) return state.meta?.min_date ? `${fmt.date(state.meta.min_date)} – ${fmt.date(state.meta.max_date)}` : "All loaded data";
  return `${p.label} ${p.start.slice(0, 4)} · ${fmt.date(p.start)} – ${fmt.date(p.end)}`;
}

function renderKpis({ current, previous }) {
  const prevLabel = previous ? "vs previous period" : periodLabel();
  const tile = (label, icon, value, cur, prev, fmtDelta = true) => {
    let delta = "";
    if (previous && prev) {
      const d = ((cur - prev) / prev) * 100;
      delta = `<span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? ICON.up : ICON.down}${Math.abs(d).toFixed(1)}%</span>`;
    }
    return `<article class="kpi"><div class="label">${icon}${label}</div><div class="value">${value}</div>
            <div class="sub">${delta}<span>${esc(prevLabel)}</span></div></article>`;
  };
  $("#kpis").innerHTML = [
    tile("Net revenue", ICON.revenue, fmt.usdCompact(current.revenue), current.revenue, previous?.revenue),
    tile("Orders", ICON.cart, fmt.int(current.orders), current.orders, previous?.orders),
    tile("Avg order value", ICON.tag, fmt.usd2(current.aov), current.aov, previous?.aov),
    tile("Active customers", ICON.users, fmt.int(current.customers), current.customers, previous?.customers),
  ].join("");
}

function renderMonthly(monthly) {
  const p = currentPeriod();
  const inPeriod = (m) => !p.start || (m.month >= p.start.slice(0, 7) && m.month <= p.end.slice(0, 7));
  const s1 = css("--s1"), muted = css("--line-strong");
  $("#monthly-sub").textContent = `USD${state.region ? " · " + state.region : ""} · ${p.start ? "selected period highlighted" : "all months loaded"}`;
  $("#monthly-legend").innerHTML = p.start
    ? `<span><i style="background:${s1}"></i>${esc(p.label)}</span><span><i style="background:${muted}"></i>Other months</span>` : "";
  makeChart("chart-monthly", {
    type: "bar",
    data: {
      labels: monthly.map((m) => fmt.month(m.month)),
      datasets: [{ label: "Net revenue", data: monthly.map((m) => m.revenue), backgroundColor: monthly.map((m) => (inPeriod(m) ? s1 : muted)),
        hoverBackgroundColor: monthly.map((m) => (inPeriod(m) ? css("--accent-ink") : css("--ink-3"))),
        borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", maxBarThickness: 44, categoryPercentage: 0.78 }],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { x: axisX(), y: axisY({ ticks: { color: css("--ink-3"), padding: 8, callback: (v) => fmt.usdCompact(v) } }) },
      plugins: {
        tooltip: { callbacks: {
          title: (items) => fmt.month(monthly[items[0].dataIndex].month, "long"),
          label: (c) => " Net revenue  " + fmt.usd(c.raw),
          afterLabel: (c) => { const m = monthly[c.dataIndex]; return [`  Orders  ${fmt.int(m.orders)}`, `  Avg order  ${fmt.usd2(m.aov)}`]; },
        } },
      },
    },
  });
}

function hbarChart(id, rows, labelKey, { onClick, highlight } = {}) {
  const s1 = css("--s1"), muted = css("--line-strong");
  const total = rows.reduce((a, r) => a + r.revenue, 0);
  return makeChart(id, {
    type: "bar",
    data: {
      labels: rows.map((r) => r[labelKey]),
      datasets: [{ label: "Net revenue", data: rows.map((r) => r.revenue),
        backgroundColor: rows.map((r) => (!highlight || r[labelKey] === highlight ? s1 : muted)),
        borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "left", maxBarThickness: 26, categoryPercentage: 0.8 }],
    },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      onClick: onClick ? (_, els) => els.length && onClick(rows[els[0].index]) : undefined,
      onHover: onClick ? (e, els) => (e.native.target.style.cursor = els.length ? "pointer" : "default") : undefined,
      scales: { x: axisY({ ticks: { color: css("--ink-3"), callback: (v) => fmt.usdCompact(v), maxTicksLimit: 4, maxRotation: 0 } }), y: axisX({ ticks: { color: css("--ink-2") } }) },
      plugins: { tooltip: { callbacks: {
        label: (c) => ` ${fmt.usd(c.raw)}  ·  ${((c.raw / total) * 100).toFixed(1)}% of total`,
        afterLabel: (c) => `  ${fmt.int(rows[c.dataIndex].orders)} orders`,
      } } },
    },
  });
}

function renderRegions(regions) {
  hbarChart("chart-region", regions, "region", {
    highlight: state.region || null,
    onClick: (r) => { state.region = state.region === r.region ? "" : r.region; loadDashboard(); },
  });
}
const renderCategories = (cats) => hbarChart("chart-category", cats, "category");

function renderTopProducts(products) {
  const max = Math.max(...products.map((p) => p.revenue), 1);
  $("#top-products").innerHTML = `<thead><tr><th>#</th><th>Product</th><th class="num">Units</th><th>Net revenue</th></tr></thead><tbody>${
    products.map((p, i) => `<tr><td><span class="rank">${i + 1}</span></td>
      <td><div class="cell-main">${esc(p.product_name)}</div><div class="cell-sub">${esc(p.category)} · ${esc(p.product_id)}</div></td>
      <td class="num">${fmt.int(p.units)}</td>
      <td><div class="bar-cell"><div class="bar"><i style="width:${(p.revenue / max) * 100}%"></i></div><b class="num">${fmt.usd(p.revenue)}</b></div></td></tr>`).join("")
  }</tbody>`;
  if (!products.length) $("#top-products").innerHTML = `<tbody><tr><td class="empty-state">No sales in this period.</td></tr></tbody>`;
}

function renderChannels(channels) {
  const total = channels.reduce((a, c) => a + c.revenue, 0) || 1;
  const colors = SERIES();
  const order = ["web", "mobile", "marketplace"];          // colour follows the entity, not its rank
  const color = (ch) => colors[Math.max(order.indexOf(ch), 0)];
  const label = (ch) => ch.charAt(0).toUpperCase() + ch.slice(1);
  $("#channel-mix").innerHTML = `
    <div class="mix-bar" role="img" aria-label="Channel share of revenue">${channels.map((c) => `<i title="${esc(label(c.channel))}: ${((c.revenue / total) * 100).toFixed(1)}%" style="width:${(c.revenue / total) * 100}%;background:${color(c.channel)}"></i>`).join("")}</div>
    <div class="mix-rows">${channels.map((c) => `<div class="mix-row"><i style="background:${color(c.channel)}"></i><span>${esc(label(c.channel))}</span>
      <span class="abs">${fmt.usdCompact(c.revenue)} · ${fmt.int(c.orders)} orders</span><span class="pct">${((c.revenue / total) * 100).toFixed(1)}%</span></div>`).join("")}</div>`;
}

function renderFacts(overview, status) {
  const last = state.meta?.last_run;
  const flagged = overview.flagged || { flagged: 0, total: 0 };
  const loadedFiles = status.processed_files.length;
  $("#data-facts").innerHTML = [
    `${ICON.file}<span><b>${loadedFiles} monthly order files</b> loaded from CSV${status.pending_files.length ? `, <a href="#/runs">${status.pending_files.length} waiting</a>` : ""}, plus the customer master export and product/FX data from the REST API.</span>`,
    `${ICON.check}<span><b>${fmt.int(status.rows_loaded)} rows</b> loaded across ${status.runs} runs; rows that broke a rule are <a href="#/quality">quarantined</a>, not silently dropped.</span>`,
    `${ICON.warn}<span><b>${fmt.int(flagged.flagged)} of ${fmt.int(flagged.total)} orders</b> in this view carry a warning flag (bulk quantity or price drift) and are included in totals.</span>`,
    `${ICON.db}<span>Last refresh <b>${last ? "run #" + last.run_id + ", " + fmt.ago(last.finished_at || last.started_at) : "never"}</b>. Totals exclude cancelled and returned orders; all amounts converted to USD.</span>`,
  ].map((li) => `<li>${li}</li>`).join("");
}

/* ================================================================== runs */
async function loadRuns() {
  const [runs, status] = await Promise.all([api("/api/runs?limit=100"), api("/api/pipeline/status")]);
  state.runs = runs;
  renderPending(status);
  renderRunStats(status, runs);
  renderRunsTable(runs);
  updateHealth(runs, status);
  const anyRunning = runs.some((r) => r.status === "running") || status.running;
  if (anyRunning) startPolling();
}

function renderPending(status) {
  const p = status.pending_files;
  const el = $("#pending");
  el.classList.toggle("idle", !p.length);
  el.innerHTML = p.length
    ? `<span class="icon">${ICON.file}</span><div><strong>${p.length} new file${p.length > 1 ? "s" : ""} waiting to load</strong>
       <span class="muted">Detected in <code>data/raw/orders/</code> by checksum. Run the pipeline to ingest.</span></div>
       <div class="chips">${p.map((f) => `<span class="tag">${esc(f)}</span>`).join("")}</div>`
    : `<span class="icon">${ICON.check}</span><div><strong>Up to date</strong>
       <span class="muted">All ${status.processed_files.length} order files are loaded. A run now refreshes the customer master and API reference data; toggle full refresh to reprocess every file.</span></div>`;
}

function renderRunStats(status, runs) {
  const finished = status.succeeded + status.failed;
  const rate = finished ? (status.succeeded / finished) * 100 : null;
  const tile = (label, value, sub) => `<article class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></article>`;
  $("#run-stats").innerHTML = [
    tile("Total runs", fmt.int(status.runs), runs[0] ? "Latest " + fmt.ago(runs[0].started_at) : "No runs yet"),
    tile("Success rate", fmt.pct(rate, 0), `${fmt.int(status.succeeded)} succeeded · ${fmt.int(status.failed)} failed`),
    tile("Avg duration", fmt.dur(status.avg_duration_s), "Successful runs, end to end"),
    tile("Rows loaded", fmt.int(status.rows_loaded), "Valid rows written to PostgreSQL"),
  ].join("");
}

function stageBar(d) {
  const total = STAGES.reduce((a, s) => a + (d?.[s] || 0), 0) || 1;
  return `<div class="stagebar" title="${STAGES.map((s) => `${s}: ${fmt.dur(d?.[s] || 0)}`).join(" · ")}">${
    STAGES.map((s, i) => `<i style="width:${((d?.[s] || 0) / total) * 100}%;background:${stageColor(i)}"></i>`).join("")}</div>`;
}

function renderRunsTable(runs) {
  $("#stage-legend").innerHTML = STAGES.map((s, i) => `<span><i style="background:${stageColor(i)}"></i>${s}</span>`).join("");
  if (!runs.length) {
    $("#runs-table").innerHTML = `<tbody><tr><td class="empty-state">No runs yet — press <b>Run pipeline</b> to load the sample data.</td></tr></tbody>`;
    return;
  }
  $("#runs-table").innerHTML = `<thead><tr><th>Run</th><th>Status</th><th>Started</th><th class="num">Duration</th><th>Files</th>
    <th class="num">Extracted</th><th class="num">Loaded</th><th class="num">Rejected</th><th class="num">Flagged</th><th>Stages</th></tr></thead>
    <tbody>${runs.map((r) => `<tr data-run="${r.run_id}">
      <td><div class="cell-main">#${r.run_id}</div><div class="cell-sub">${esc(r.triggered_by)}${r.full_refresh ? " · full" : ""}</div></td>
      <td>${pill(r.status)}</td>
      <td><div>${fmt.ago(r.started_at)}</div><div class="cell-sub">${fmt.datetime(r.started_at)}</div></td>
      <td class="num">${fmt.dur(r.duration_s)}</td>
      <td>${r.files_processed.length ? r.files_processed.length === 1 ? `<span class="tag">${esc(r.files_processed[0])}</span>` : `<span class="tag">${r.files_processed.length} files</span>` : '<span class="cell-sub">reference only</span>'}</td>
      <td class="num">${fmt.int(r.rows_extracted)}</td><td class="num">${fmt.int(r.rows_loaded)}</td>
      <td class="num">${r.rows_rejected ? `<b style="color:var(--crit-ink)">${fmt.int(r.rows_rejected)}</b>` : "0"}</td>
      <td class="num">${fmt.int(r.rows_warned)}</td>
      <td>${r.status === "running" ? '<span class="cell-sub">in progress…</span>' : stageBar(r.stage_durations)}</td></tr>`).join("")}</tbody>`;
}

async function triggerRun() {
  const btn = $("#run-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span><span>Running…</span>';
  try {
    state.lastRunId = state.runs[0]?.run_id || 0;
    await api("/api/runs", { method: "POST", body: JSON.stringify({ full_refresh: $("#full-refresh").checked }) });
    toast("Pipeline started");
    startPolling(true);
  } catch (e) {
    toast(e.status === 409 ? "A run is already in progress" : "Could not start run: " + e.message);
    resetRunButton();
  }
}
function resetRunButton() {
  const btn = $("#run-btn");
  btn.disabled = false;
  btn.innerHTML = ICON.play + "<span>Run pipeline</span>";
}

function startPolling(expectNew = false) {
  if (state.polling) return;
  $("#run-btn").disabled = true;
  $("#run-btn").innerHTML = '<span class="spinner"></span><span>Running…</span>';
  const started = Date.now();
  state.polling = setInterval(async () => {
    try {
      const [runs, status] = await Promise.all([api("/api/runs?limit=100"), api("/api/pipeline/status")]);
      const newest = runs[0];
      const waitingForNew = expectNew && (!newest || newest.run_id <= state.lastRunId) && Date.now() - started < 15000;
      const busy = waitingForNew || runs.some((r) => r.status === "running") || status.running;
      state.runs = runs;
      if (parseHash().page === "runs") { renderRunsTable(runs); renderPending(status); renderRunStats(status, runs); }
      updateHealth(runs, status);
      if (!busy) {
        clearInterval(state.polling); state.polling = null; resetRunButton();
        state.meta = null; await refreshMeta();
        if (newest && expectNew) {
          toast(newest.status === "success"
            ? `Run #${newest.run_id} succeeded · ${fmt.int(newest.rows_loaded)} loaded, ${fmt.int(newest.rows_rejected)} rejected`
            : `Run #${newest.run_id} failed — see the run log`, 4500);
          if (parseHash().page === "runs") openRun(newest.run_id);
        }
      }
    } catch (e) { console.error(e); }
  }, 1200);
}

/* ---------------------------------------------------------------- drawer */
async function openRun(runId) {
  const r = await api(`/api/runs/${runId}`);
  $$("#runs-table tbody tr").forEach((tr) => tr.classList.toggle("selected", Number(tr.dataset.run) === runId));
  $("#drawer-eyebrow").innerHTML = `${pill(r.status)}`;
  $("#drawer-title").textContent = `Run #${r.run_id}`;
  const maxStage = Math.max(...STAGES.map((s) => r.stage_durations?.[s] || 0), 0.001);
  const failing = r.rules.filter((x) => x.rows_failed > 0);
  $("#drawer-body").innerHTML = `
    <p class="muted">Started ${fmt.datetime(r.started_at)} by <b>${esc(r.triggered_by)}</b>${r.full_refresh ? " (full refresh)" : ""} · API source:
      <span class="tag">${esc(r.api_source || "—")}</span></p>
    ${r.error_message ? `<div class="error-box">${esc(r.error_message)}</div>` : ""}
    <section class="dl">
      <div><span>Extracted</span><b>${fmt.int(r.rows_extracted)}</b></div>
      <div><span>Loaded</span><b>${fmt.int(r.rows_loaded)}</b></div>
      <div><span>Rejected</span><b style="color:${r.rows_rejected ? "var(--crit-ink)" : "inherit"}">${fmt.int(r.rows_rejected)}</b></div>
      <div><span>Flagged</span><b>${fmt.int(r.rows_warned)}</b></div>
      <div><span>Duration</span><b>${fmt.dur(r.duration_s)}</b></div>
      <div><span>Pass rate</span><b>${r.rows_extracted ? fmt.pct(((r.rows_extracted - r.rows_rejected) / r.rows_extracted) * 100) : "—"}</b></div>
    </section>
    <section><h3>Files</h3>${r.files_processed.length ? `<div class="chips" style="display:flex;gap:6px;flex-wrap:wrap">${r.files_processed.map((f) => `<span class="tag">${esc(f)}</span>`).join("")}</div>` : '<p class="muted">No new order files; reference data refreshed only.</p>'}</section>
    <section><h3>Stage timings</h3><div class="stages">${STAGES.map((s, i) => `<div class="stage"><span>${s}</span>
      <div class="track"><i style="width:${((r.stage_durations?.[s] || 0) / maxStage) * 100}%;background:${stageColor(i)}"></i></div>
      <span class="t">${fmt.dur(r.stage_durations?.[s])}</span></div>`).join("")}</div></section>
    <section><h3>Rules triggered (${failing.length} of ${r.rules.length})</h3>
      ${failing.length ? `<table class="table"><thead><tr><th>Rule</th><th>Dataset</th><th>Severity</th><th class="num">Rows</th></tr></thead><tbody>${
        failing.map((x) => `<tr><td><a href="#/quality?run=${r.run_id}&rule=${encodeURIComponent(x.rule_name)}"><span class="tag">${esc(x.rule_name)}</span></a></td><td>${esc(x.dataset)}</td><td>${pill(x.severity)}</td><td class="num">${fmt.int(x.rows_failed)}</td></tr>`).join("")
      }</tbody></table>` : '<p class="muted">Every rule passed.</p>'}
      ${failing.length ? `<p style="margin-top:10px"><a href="#/quality?run=${r.run_id}">Inspect rejected rows for this run →</a></p>` : ""}</section>
    <section><h3>Log</h3><div class="log">${(r.log || []).map((l) => `<div class="lv-${esc(l.level)}"><time>${new Date(l.ts).toLocaleTimeString("en-US", { hour12: false })}</time><span>${esc(l.msg)}</span></div>`).join("")}</div></section>`;
  $("#scrim").hidden = false;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#drawer-close").focus();
}
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
  $$("#runs-table tbody tr.selected").forEach((tr) => tr.classList.remove("selected"));
}

/* =============================================================== quality */
async function loadQuality(params) {
  const runs = state.runs.length ? state.runs : (state.runs = await api("/api/runs?limit=100"));
  const sel = $("#quality-run");
  const want = params?.get("run") ?? sel.value;
  sel.innerHTML = '<option value="">All runs</option>' + runs.filter((r) => r.status !== "running")
    .map((r) => `<option value="${r.run_id}">Run #${r.run_id} · ${r.files_processed[0] ? esc(r.files_processed[0]) : "reference only"}</option>`).join("");
  sel.value = want || "";
  if (params?.get("rule") != null) { $("#issue-rule").dataset.want = params.get("rule"); state.issuesPage = 0; }
  const runId = sel.value;
  const [trend, rules] = await Promise.all([api("/api/quality/trend"), api("/api/quality/rules" + (runId ? "?run_id=" + runId : ""))]);
  renderQualityKpis(trend, rules, runId);
  renderPassRate(trend, runId);
  renderRuleChart(rules, runId);
  renderRulesTable(rules);
  const ruleSel = $("#issue-rule");
  const wantRule = ruleSel.dataset.want ?? ruleSel.value;
  delete ruleSel.dataset.want;
  const ruleNames = [...new Set(rules.map((r) => r.rule_name))].sort();
  ruleSel.innerHTML = '<option value="">Any rule</option>' + ruleNames.map((n) => `<option>${esc(n)}</option>`).join("");
  ruleSel.value = ruleNames.includes(wantRule) ? wantRule : "";
  await loadIssues();
  if (params?.get("rule")) $("#issues-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderQualityKpis(trend, rules, runId) {
  const scope = runId ? trend.filter((t) => String(t.run_id) === String(runId)) : trend;
  const ext = scope.reduce((a, t) => a + t.rows_extracted, 0);
  const rej = scope.reduce((a, t) => a + t.rows_rejected, 0);
  const warn = scope.reduce((a, t) => a + t.rows_warned, 0);
  const triggered = rules.filter((r) => r.rows_failed > 0).length;
  const scopeLabel = runId ? `Run #${runId}` : `Across ${trend.length} successful runs`;
  const tile = (label, value, sub, tone = "") => `<article class="kpi"><div class="label">${label}</div><div class="value" ${tone ? `style="color:${tone}"` : ""}>${value}</div><div class="sub">${sub}</div></article>`;
  $("#quality-kpis").innerHTML = [
    tile("Pass rate", ext ? fmt.pct(((ext - rej) / ext) * 100, 2) : "—", `${fmt.int(ext - rej)} of ${fmt.int(ext)} rows · ${scopeLabel}`),
    tile("Rows rejected", fmt.int(rej), `${pill("error")} quarantined in <code>etl.row_issues</code>`),
    tile("Rows flagged", fmt.int(warn), `${pill("warning")} loaded with <code>is_flagged</code>`),
    tile("Rules triggered", `${triggered}<span class="muted" style="font-size:16px;font-weight:500"> / ${rules.length}</span>`, "Rules with at least one failing row"),
  ].join("");
}

function renderPassRate(trend, runId) {
  const s1 = css("--s1");
  const min = Math.min(...trend.map((t) => t.pass_rate ?? 100), 100);
  makeChart("chart-passrate", {
    type: "line",
    data: {
      labels: trend.map((t) => "#" + t.run_id),
      datasets: [{ label: "Pass rate", data: trend.map((t) => t.pass_rate), borderColor: s1, borderWidth: 2, tension: 0.3, fill: true,
        backgroundColor: (ctx) => { const { chart } = ctx; if (!chart.chartArea) return "transparent";
          const g = chart.ctx.createLinearGradient(0, chart.chartArea.top, 0, chart.chartArea.bottom);
          g.addColorStop(0, s1 + "33"); g.addColorStop(1, s1 + "00"); return g; },
        pointRadius: trend.map((t) => (String(t.run_id) === String(runId) ? 6 : 3)), pointHoverRadius: 6,
        pointBackgroundColor: trend.map((t) => (String(t.run_id) === String(runId) ? s1 : css("--surface"))),
        pointBorderColor: s1, pointBorderWidth: 2 }],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      onClick: (_, els) => { if (els.length) location.hash = `#/quality?run=${trend[els[0].index].run_id}`; },
      onHover: (e, els) => (e.native.target.style.cursor = els.length ? "pointer" : "default"),
      scales: { x: axisX(), y: axisY({ suggestedMin: Math.max(0, Math.floor(min - 1)), suggestedMax: 100, ticks: { color: css("--ink-3"), padding: 8, callback: (v) => v + "%" } }) },
      plugins: { tooltip: { callbacks: {
        title: (i) => `Run ${i[0].label}`,
        label: (c) => ` Pass rate  ${fmt.pct(c.raw, 2)}`,
        afterLabel: (c) => { const t = trend[c.dataIndex]; return [`  Rejected  ${fmt.int(t.rows_rejected)}`, `  Flagged  ${fmt.int(t.rows_warned)}`, `  Extracted  ${fmt.int(t.rows_extracted)}`]; },
      } } },
    },
  });
}

function renderRuleChart(rules, runId) {
  const failing = rules.filter((r) => r.rows_failed > 0).sort((a, b) => b.rows_failed - a.rows_failed).slice(0, 10);
  const crit = css("--crit"), warn = css("--warn");
  $("#rules-chart-sub").textContent = (runId ? `Run #${runId}` : "All runs") + " · top " + failing.length + " rules";
  $("#severity-legend").innerHTML = `<span><i style="background:${crit}"></i>Error · rejected</span><span><i style="background:${warn}"></i>Warning · flagged</span>`;
  makeChart("chart-rules", {
    type: "bar",
    data: {
      labels: failing.map((r) => r.rule_name),
      datasets: [{ label: "Rows", data: failing.map((r) => r.rows_failed), backgroundColor: failing.map((r) => (r.severity === "error" ? crit : warn)),
        borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "left", maxBarThickness: 18, categoryPercentage: 0.82 }],
    },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      onClick: (_, els) => { if (els.length) selectRule(failing[els[0].index].rule_name); },
      onHover: (e, els) => (e.native.target.style.cursor = els.length ? "pointer" : "default"),
      scales: { x: axisY({ ticks: { color: css("--ink-3"), precision: 0, maxTicksLimit: 6 } }), y: axisX({ ticks: { color: css("--ink-2"), font: { family: css("--mono"), size: 11 } } }) },
      plugins: { tooltip: { callbacks: {
        title: (i) => failing[i[0].dataIndex].rule_name,
        label: (c) => ` ${fmt.int(c.raw)} rows · ${failing[c.dataIndex].severity}`,
        afterLabel: (c) => "  " + failing[c.dataIndex].description,
      } } },
    },
  });
}

function renderRulesTable(rules) {
  const passing = rules.filter((r) => !r.rows_failed).length;
  const shown = state.showAllRules ? rules : rules.filter((r) => r.rows_failed);
  $("#rules-table").innerHTML = `<thead><tr><th>Rule</th><th>Dataset</th><th>Severity</th><th class="num">Checked</th><th class="num">Failed</th><th class="num">Pass rate</th></tr></thead>
    <tbody>${shown.map((r) => {
      const pass = r.rows_checked ? ((r.rows_checked - r.rows_failed) / r.rows_checked) * 100 : 100;
      return `<tr data-rule="${esc(r.rule_name)}"><td><div class="cell-main"><span class="tag">${esc(r.rule_name)}</span></div><div class="cell-sub" style="margin-top:3px">${esc(r.description)}</div></td>
        <td>${esc(r.dataset)}</td><td>${r.rows_failed ? pill(r.severity) : `<span class="pill success">${ICON.check}Passing</span>`}</td><td class="num">${fmt.int(r.rows_checked)}</td>
        <td class="num">${r.rows_failed ? `<b>${fmt.int(r.rows_failed)}</b>` : '<span class="cell-sub">0</span>'}</td>
        <td class="num">${fmt.pct(pass, 2)}</td></tr>`;
    }).join("") || `<tr><td colspan="6" class="empty-state">Every rule passed.</td></tr>`}</tbody>`;
  const more = $("#rules-more");
  more.hidden = !passing;
  more.textContent = state.showAllRules ? "Hide passing rules" : `Show ${passing} passing rule${passing === 1 ? "" : "s"}`;
  state._rules = rules;
}

function selectRule(rule) {
  $("#issue-rule").value = rule;
  state.issuesPage = 0;
  loadIssues();
  $("#issues-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

const PAGE_SIZE = 10;
const FIELD_ORDER = {
  orders: ["order_id", "order_date", "customer_id", "product_id", "quantity", "unit_price", "discount", "currency", "status", "channel"],
  customers: ["customer_id", "first_name", "last_name", "email", "region", "country", "signup_date"],
  products: ["product_id", "name", "category", "list_price_usd", "active"],
};
async function loadIssues() {
  const qs = new URLSearchParams({ limit: PAGE_SIZE, offset: state.issuesPage * PAGE_SIZE });
  const filters = { run_id: $("#quality-run").value, dataset: $("#issue-dataset").value, severity: $("#issue-severity").value, rule: $("#issue-rule").value, q: $("#issue-q").value.trim() };
  Object.entries(filters).forEach(([k, v]) => v && qs.set(k, v));
  const csvQS = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
  $("#issues-csv").href = "/api/quality/issues.csv?" + csvQS;
  const { total, items } = await api("/api/quality/issues?" + qs);
  $("#issues-sub").textContent = `${fmt.int(total)} row${total === 1 ? "" : "s"} · original source values, failing fields highlighted`;
  $("#issues-list").innerHTML = items.length ? items.map((it) => {
    const cls = it.severity === "error" ? "bad" : "warn";
    const order = FIELD_ORDER[it.dataset] || [];
    const entries = Object.entries(it.record).sort(([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    const fields = entries.map(([k, v]) => {
      const isBad = it.columns.includes(k), empty = v === null || v === "";
      return `<div class="field ${isBad ? cls : ""} ${empty ? "empty" : ""}"><span>${esc(k)}</span><b title="${esc(v)}">${empty ? "(empty)" : esc(v)}</b></div>`;
    }).join("");
    return `<div class="issue"><div class="issue-head">${pill(it.severity)}<span class="src">${esc(it.source_file)}:${it.source_row}</span>
      <span>· ${esc(it.dataset)} · run #${it.run_id}</span>${it.reasons.map((r) => `<span class="reason ${it.severity}">${esc(r)}</span>`).join("")}</div>
      <div class="record">${fields}</div></div>`;
  }).join("") : `<div class="empty-state">${ICON.check}<div>No rows match these filters.</div></div>`;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  $("#issues-pager").innerHTML = total ? `<span>Showing ${fmt.int(state.issuesPage * PAGE_SIZE + 1)}–${fmt.int(Math.min(total, (state.issuesPage + 1) * PAGE_SIZE))} of ${fmt.int(total)}</span>
    <div class="btns"><button class="btn btn-ghost" data-pg="-1" ${state.issuesPage === 0 ? "disabled" : ""}>Previous</button>
    <button class="btn btn-ghost" data-pg="1" ${state.issuesPage >= pages - 1 ? "disabled" : ""}>Next</button></div>` : "";
}

/* ================================================================= model */
async function loadModel() {
  const steps = [
    ["Sources", "CSV + REST API", "orders_2024_*.csv · customers.csv · /products (paginated) · /fx-rates"],
    ["Extract", "pandas readers", "All columns as strings; checksum manifest for incremental loads; API retries + fixture fallback"],
    ["Transform", "clean & type", "Trim, normalise case, coerce numbers & dates; bad values become NaN, never crash"],
    ["Validate", "29 declarative rules", "Errors reject + quarantine with reasons; warnings load with a flag"],
    ["Load", "PostgreSQL upsert", "One transaction: dims, fact, rule results, row issues, file manifest"],
    ["Serve", "reporting views", "v_sales, v_monthly_revenue … → this dashboard and any BI tool"],
  ];
  $("#flow").innerHTML = steps.map(([k, b, s], i) => `<div class="flow-step"><div class="flow-node"><span class="k">${i + 1} · ${k}</span><b>${b}</b><small>${s}</small></div>${i < steps.length - 1 ? `<span class="flow-arrow">${ICON.arrow}</span>` : ""}</div>`).join("");
  const objs = await api("/api/model");
  const typeName = (t) => t.replace("timestamp with time zone", "timestamptz").replace("character varying", "varchar").replace("character", "char").replace("ARRAY", "text[]");
  const card = (o) => `<article class="card model-card"><header><h3>${esc(o.schema)}.${esc(o.name)}</h3><span class="kind ${o.kind}">${o.kind}</span></header>
    <p class="muted" style="margin-bottom:10px">${fmt.int(o.rows)} rows</p>
    <ul>${o.columns.map((c) => `<li><span>${esc(c.name)}</span><em>${esc(typeName(c.type))}</em></li>`).join("")}</ul></article>`;
  const section = (schema, title, blurb) => `<div class="model-section"><h2>${title}</h2><p>${blurb}</p></div>
    <div class="model-grid">${objs.filter((o) => o.schema === schema).map(card).join("")}</div>`;
  $("#model-grid").innerHTML = section("reporting", "reporting.*", "Star schema + views that dashboards and BI tools read")
    + section("etl", "etl.*", "Pipeline metadata: runs, file manifest, rule results and quarantined rows");
}

/* ================================================================ health */
async function refreshMeta() {
  state.meta = await api("/api/meta");
  state.periods = buildPeriods(state.meta.min_date, state.meta.max_date);
  if (!state.periods.find((p) => p.key === state.period)) state.period = "all";
}

function updateHealth(runs, status) {
  const h = $("#health"), last = runs[0];
  h.className = "health";
  const running = runs.some((r) => r.status === "running") || status?.running;
  if (running) { h.classList.add("running"); $("#health-title").textContent = "Pipeline running…"; $("#health-sub").textContent = "Loading new data"; }
  else if (!last) { $("#health-title").textContent = "No runs yet"; $("#health-sub").textContent = "Start one from Pipeline runs"; }
  else {
    h.classList.add(last.status === "success" ? "ok" : "bad");
    $("#health-title").textContent = last.status === "success" ? "Pipeline healthy" : "Last run failed";
    $("#health-sub").textContent = `Run #${last.run_id} · ${fmt.ago(last.finished_at || last.started_at)}`;
  }
  const badge = $("#nav-pending"), n = status?.pending_files?.length || 0;
  badge.hidden = !n; badge.textContent = n;
  badge.title = `${n} file(s) waiting to load`;
}

async function pollHealth() {
  try {
    const [runs, status] = await Promise.all([api("/api/runs?limit=5"), api("/api/pipeline/status")]);
    updateHealth(runs, status);
    if ((runs.some((r) => r.status === "running") || status.running) && !state.polling) {
      state.runs = await api("/api/runs?limit=100"); state.lastRunId = state.runs[0]?.run_id || 0; startPolling();
    }
  } catch (e) { /* offline */ }
}

/* ================================================================ events */
function bind() {
  $("#period-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-key]"); if (!b) return;
    state.period = b.dataset.key; loadDashboard();
  });
  $("#region-filter").addEventListener("change", (e) => { state.region = e.target.value; loadDashboard(); });
  $("#run-btn").addEventListener("click", triggerRun);
  $("#runs-table").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-run]"); if (tr) openRun(Number(tr.dataset.run)); });
  $("#rules-more").addEventListener("click", () => { state.showAllRules = !state.showAllRules; renderRulesTable(state._rules || []); });
  $("#rules-table").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-rule]"); if (tr) selectRule(tr.dataset.rule); });
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#drawer").addEventListener("click", (e) => { if (e.target.closest("a[href^='#/']")) closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  $("#quality-run").addEventListener("change", (e) => { state.issuesPage = 0; location.hash = "#/quality" + (e.target.value ? "?run=" + e.target.value : ""); });
  ["#issue-dataset", "#issue-severity", "#issue-rule"].forEach((s) => $(s).addEventListener("change", () => { state.issuesPage = 0; loadIssues(); }));
  let t; $("#issue-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { state.issuesPage = 0; loadIssues(); }, 250); });
  $("#issues-pager").addEventListener("click", (e) => { const b = e.target.closest("button[data-pg]"); if (!b) return; state.issuesPage += Number(b.dataset.pg); loadIssues(); });
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch (e) { /* storage blocked */ }
    chartDefaults(); route();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { chartDefaults(); route(); });
  window.addEventListener("hashchange", route);
}

(async function init() {
  chartDefaults();
  bind();
  try { await refreshMeta(); } catch (e) { toast("API unavailable: " + e.message); }
  route();
  pollHealth();
  setInterval(pollHealth, 10000);
})();
