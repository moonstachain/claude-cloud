// 原力OS — one screen, one keystroke per decision. No framework, no build step.
const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
const precise = new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: 4 });
const fmt = (value) => (typeof value !== "number" ? esc(value) : Math.abs(value) >= 10000 ? compact.format(value) : precise.format(value));
const STATUS = { open: "待拍板", approved: "进行中", deferred: "已推迟", rejected: "已否决", done: "已结算", candidate: "候选", canon: "正典", retired: "已退役" };
const EVENT = { "item.proposed": "提出", "item.decided": "拍板", "item.noted": "备注", "item.settled": "结算" };

const store = (() => { try { return window.localStorage; } catch { return null; } })();
const params = new URLSearchParams(location.search);
if (params.get("token")) {
  store?.setItem("yuanli.token", params.get("token"));
  history.replaceState(null, "", location.pathname + location.hash);
}
const token = store?.getItem("yuanli.token") || null;
const ui = { tab: "today", brief: null, cards: [], sel: 0, seq: null, snap: null, query: "" };

// ------------------------------------------------------------------ data
async function api(path, body) {
  if (ui.snap) return fromSnapshot(path);
  const headers = { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { "Content-Type": "application/json" } : {}) };
  const response = await fetch(path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function fromSnapshot(path) {
  const snap = ui.snap;
  if (path === "/api/brief") return snap.brief;
  if (path === "/api/calibration") return snap.calibration;
  if (path === "/api/canon") return snap.canon;
  const domain = path.match(/^\/api\/domains\/(.+)$/);
  if (domain) return snap.domains[domain[1]];
  throw new Error("静态快照只读");
}

// ---------------------------------------------------------------- render
const domainTitle = (key) => ui.brief?.domains.find((d) => d.key === key)?.title || key;

function card(c, lane) {
  const suggest = c.suggest ? `<span class="flag ${c.suggest.outcome ? "ok" : "bad"}">建议结算：${c.suggest.outcome ? "达成" : "未达成"}（${fmt(c.suggest.value)} / 目标 ${fmt(c.suggest.target)}）</span>` : "";
  const due = c.overdue ? `<span class="flag bad">逾期 · ${esc(c.due)}</span>` : c.due ? `<span class="chip">到期 ${esc(c.due)}</span>` : "";
  const acts = lane === "decide"
    ? `<button class="primary" data-act="approve">批准<kbd>a</kbd></button><button data-act="reject">否决<kbd>r</kbd></button><button data-act="defer">推迟<kbd>d</kbd></button>`
    : `<button class="primary" data-act="settle">结算<kbd>s</kbd></button><button data-act="note">备注<kbd>n</kbd></button>`;
  return `<div class="card" data-id="${esc(c.id)}" data-lane="${lane}">
    <div class="top"><span class="pri p${c.priority}">P${c.priority}</span><span class="title">${esc(c.title)}</span><span class="chip">${esc(domainTitle(c.domain))}</span></div>
    ${c.why ? `<div class="why">${esc(c.why)}</div>` : ""}
    ${c.recommend ? `<div class="rec">建议：${esc(c.recommend)}</div>` : ""}
    <div class="meta">${c.status === "deferred" ? `<span class="flag warn">推迟到期</span>` : ""}${due}
      ${c.forecast != null ? `<span class="chip">预测 ${Math.round(c.forecast * 100)}%</span>` : ""}
      ${c.manual ? `<span class="chip">人工执行</span>` : ""}${suggest}
      <span class="acts">${acts}</span></div></div>`;
}

function lanes(view) {
  ui.cards = [...view.decide, ...view.doing];
  const more = (shown, total) => (total > shown ? `<div class="empty">还有 ${total - shown} 项未显示 —— 先处理上面的。</div>` : "");
  return `<h2>待拍板 <span class="muted">${view.decide_total}</span></h2>
    ${view.decide.map((c) => card(c, "decide")).join("") || `<div class="empty">没有待你拍板的事。</div>`}${more(view.decide.length, view.decide_total)}
    <h2>进行中 <span class="muted">${view.doing_total}${view.overdue_total ? ` · 逾期 ${view.overdue_total}` : ""}</span></h2>
    ${view.doing.map((c) => card(c, "doing")).join("") || `<div class="empty">没有进行中的事。</div>`}${more(view.doing.length, view.doing_total)}`;
}

function spark(points) {
  if (points.length < 2) return "";
  const values = points.map((p) => p[1]);
  const [w, h] = [160, 30];
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const xy = values.map((v, i) => [(i * w) / (values.length - 1), h - 3 - ((v - min) / span) * (h - 6)]);
  const [lx, ly] = xy[xy.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" data-points='${esc(JSON.stringify(points))}'>
    <polyline points="${xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}"/><circle cx="${lx}" cy="${ly}" r="3.5"/></svg>`;
}

function tile(t) {
  const values = t.spark.map((p) => p[1]);
  let delta = "";
  if (values.length > 1) {
    const d = values[values.length - 1] - values[values.length - 2];
    const direction = d > 0 ? "up" : "down";
    const good = (d > 0) === (t.good === "up") ? "good" : "bad";
    delta = d === 0 ? "持平" : `<span class="${direction}-${good}">${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}</span> 较上次`;
  }
  return `<div class="tile"><div class="label">${esc(t.label)}</div>
    <div class="value">${fmt(t.value)}<span class="unit">${esc(t.unit)}</span></div>
    <div class="delta">${delta}</div>${spark(t.spark)}<div class="peek">${esc(t.at.slice(0, 10))}</div></div>`;
}

function renderToday(brief) {
  const domains = brief.domains.map((d) => {
    const lead = d.metrics[0];
    return `<div class="domain" data-tab="${esc(d.key)}"><b>${esc(d.title)}</b>
      <span class="muted">${d.open ? `${d.open} 件待拍板` : "无待拍板"}</span>
      ${lead ? `<div>${esc(lead.label)} <strong>${fmt(lead.value)}</strong>${esc(lead.unit)}</div>${spark(lead.spark)}` : ""}</div>`;
  }).join("");
  const cal = brief.calibration;
  const down = brief.sources.down;
  return `${lanes(brief)}
    <h2>领域</h2><div class="domains">${domains}</div>
    <h2>系统</h2><div class="meta">
      <span class="flag ${down.length ? "bad" : "ok"}">${down.length ? `${down.length} 个数据源掉线：${down.map((s) => esc(s.name)).join("、")}` : `数据源 ${brief.sources.total} 个正常`}</span>
      <span class="chip">校准 n=${cal.n}${cal.brier != null ? ` · Brier ${cal.brier}` : ""}</span>
      <span class="chip">ledger #${brief.seq}</span></div>`;
}

function renderDomain(view) {
  const sources = view.sources.map((s) => `<tr><td>${esc(s.name)}</td><td><span class="flag ${s.ok ? "ok" : s.ok === false ? "bad" : "warn"}">${s.ok ? "正常" : s.ok === false ? "掉线" : "未采集"}</span></td><td class="detail">${esc(s.detail)}</td><td class="num">${s.ms ?? ""}${s.ms != null ? " ms" : ""}</td></tr>`).join("");
  return `<div class="tiles">${view.metrics.map(tile).join("") || `<div class="empty">还没有数据。把 .csv / .jsonl 放进收件箱目录，或从 App 推送到 /api/facts。</div>`}</div>
    <h2 class="compose">新判断 / 新决策</h2>
    <form class="new" data-domain="${esc(view.key)}"><input name="title" placeholder="一句话：要决定什么，或预测什么会发生" required>
      <input name="forecast" type="number" min="0" max="100" placeholder="概率 %" class="narrow"><input name="due" type="date">
      <button class="primary">提交</button></form>
    ${lanes(view)}
    ${sources ? `<h2>数据源</h2><table>${sources}</table>` : ""}`;
}

function reliability(bins) {
  const size = 260, pad = 30, inner = size - pad * 2;
  const x = (v) => pad + v * inner, y = (v) => size - pad - v * inner;
  const dots = bins.map((b) => `<circle cx="${x(b.forecast)}" cy="${y(b.observed)}" r="${4 + Math.min(6, b.n)}"><title>预测 ${Math.round(b.forecast * 100)}% · 实际 ${Math.round(b.observed * 100)}% · n=${b.n}</title></circle>`).join("");
  return `<svg class="reliability" viewBox="0 0 ${size} ${size}" role="img" aria-label="校准曲线">
    <line class="axis" x1="${pad}" y1="${y(0)}" x2="${x(1)}" y2="${y(0)}"/><line class="axis" x1="${pad}" y1="${y(0)}" x2="${pad}" y2="${y(1)}"/>
    <line class="ref" x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}"/>${dots}
    <text x="${x(0)}" y="${size - 10}">0</text><text x="${x(1) - 6}" y="${size - 10}">1</text><text x="${x(0.5) - 24}" y="${size - 10}">预测概率</text>
    <text x="6" y="${y(1) + 4}">1</text><text x="6" y="${y(0.5)}">实际</text></svg>`;
}

function renderCalibration(cal) {
  const row = (name, g) => `<tr><td>${esc(name)}</td><td class="num">${g.n}</td><td class="num">${g.brier ?? "—"}</td></tr>`;
  const label = (name) => ({ "by:human": "人", "by:machine": "机器" })[name] || domainTitle(name.replace("domain:", ""));
  return `<div class="tiles"><div class="tile"><div class="label">总体 Brier（越低越准，0.25 = 抛硬币）</div>
      <div class="value">${cal.overall.brier ?? "—"}</div><div class="delta">已结算 ${cal.overall.n} 个带概率的判断</div></div></div>
    <h2>分组</h2><table><tr><th>分组</th><th class="num">n</th><th class="num">Brier</th></tr>
      ${Object.entries(cal.groups).map(([name, g]) => row(label(name), g)).join("") || `<tr><td colspan="3" class="muted">还没有结算的概率判断。</td></tr>`}</table>
    <h2>校准曲线 <span class="muted">点越贴近虚线越准</span></h2>
    <div class="split">${cal.reliability.length ? reliability(cal.reliability) : ""}
      <table class="compact"><tr><th class="num">预测</th><th class="num">实际</th><th class="num">n</th></tr>
      ${cal.reliability.map((b) => `<tr><td class="num">${Math.round(b.forecast * 100)}%</td><td class="num">${Math.round(b.observed * 100)}%</td><td class="num">${b.n}</td></tr>`).join("")}</table></div>`;
}

function renderCanon(list) {
  ui.cards = [];
  const item = (c) => `<div class="card"><div class="top"><span class="chip">${STATUS[c.status]}</span><span class="title">${esc(c.statement)}</span><span class="chip">${esc(domainTitle(c.domain))}</span></div>
    <div class="meta">${c.evidence.map((e) => `<span class="chip">${esc(e)}</span>`).join("")}<span class="acts">
    ${c.status === "candidate" ? `<button class="primary" data-canon="admit" data-id="${esc(c.id)}">采纳</button><button data-canon="reject" data-id="${esc(c.id)}">驳回</button>` : c.status === "canon" ? `<button data-canon="retire" data-id="${esc(c.id)}">退役</button>` : ""}</span></div></div>`;
  return `<h2>正典 <span class="muted">从现实里学到、经你采纳的原则</span></h2>${list.map(item).join("") || `<div class="empty">还没有候选原则。</div>`}`;
}

async function renderSearch(query) {
  const result = await api(`/api/ask?q=${encodeURIComponent(query)}`);
  ui.cards = [];
  return `<h2>「${esc(query)}」</h2><p>${esc(result.answer)}</p>
    ${result.citations.map((h, n) => `<div class="card" ${h.kind === "item" ? `data-open="${esc(h.id)}"` : ""}><div class="top"><span class="chip">[${n + 1}] ${esc(h.kind)}</span><span class="title">${esc(h.title)}</span><span class="chip">${esc(STATUS[h.status] || h.status || domainTitle(h.domain))}</span></div>${h.text ? `<div class="why">${esc(h.text)}</div>` : ""}</div>`).join("")}`;
}

// --------------------------------------------------------------- control
async function refresh() {
  const keep = ui.cards[ui.sel]?.id;
  ui.brief = await api("/api/brief");
  $("#verdict").textContent = ui.brief.verdict;
  const tabs = [{ id: "today", label: "今天", count: ui.brief.decide_total }, ...ui.brief.domains.map((d) => ({ id: d.key, label: d.title, count: d.open })),
    { id: "calibration", label: "校准" }, { id: "canon", label: "正典" }];
  $("#tabs").innerHTML = tabs.map((t, i) => `<button data-tab="${t.id}" class="${t.id === ui.tab ? "on" : ""}" title="${i + 1}">${esc(t.label)}${t.count ? `<span class="count">${t.count}</span>` : ""}</button>`).join("");
  let html;
  if (ui.tab === "today") html = renderToday(ui.brief);
  else if (ui.tab === "calibration") html = renderCalibration(await api("/api/calibration"));
  else if (ui.tab === "canon") html = renderCanon(await api("/api/canon"));
  else if (ui.tab === "search") html = await renderSearch(ui.query);
  else html = renderDomain(await api(`/api/domains/${ui.tab}`));
  $("#view").innerHTML = html;
  const index = ui.cards.findIndex((c) => c.id === keep);
  select(index >= 0 ? index : Math.min(ui.sel, ui.cards.length - 1));
}

function select(index) {
  ui.sel = Math.max(0, index);
  document.querySelectorAll(".card.sel").forEach((el) => el.classList.remove("sel"));
  const id = ui.cards[ui.sel]?.id;
  const el = id && document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  if (el) { el.classList.add("sel"); el.scrollIntoView({ block: "nearest" }); }
}

function go(tab) {
  ui.tab = tab;
  ui.sel = 0;
  $("#drawer").hidden = true;
  refresh().catch(fail);
}

function ask(label, value = "") {
  const dialog = $("#prompt");
  $("#prompt-label").textContent = label;
  $("#prompt-input").value = value;
  dialog.showModal();
  $("#prompt-input").select();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok" ? $("#prompt-input").value.trim() : null), { once: true }));
}

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("on");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("on"), 2200);
}
const fail = (error) => toast(`✗ ${error.message}`);

function untilDate(text) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const date = new Date();
  date.setDate(date.getDate() + (parseInt(text, 10) || 7));
  return date.toLocaleDateString("sv-SE");
}

async function act(kind, withNote = false) {
  const c = ui.cards[ui.sel];
  if (!c || ui.snap) return;
  const lane = document.querySelector(`.card[data-id="${CSS.escape(c.id)}"]`)?.dataset.lane;
  if ((["approve", "reject", "defer"].includes(kind) && lane !== "decide") || (["settle", "note"].includes(kind) && lane !== "doing")) return;
  let path, body, done;
  if (kind === "approve" || kind === "reject") {
    const note = withNote ? await ask(kind === "approve" ? "批准备注" : "否决理由") : "";
    if (note === null) return;
    [path, body, done] = ["decide", { verdict: kind, note, rev: c.rev }, kind === "approve" ? "已批准" : "已否决"];
  } else if (kind === "defer") {
    const until = await ask("推迟多少天？（或输入日期 2026-10-01）", "7");
    if (until === null) return;
    [path, body, done] = ["decide", { verdict: "defer", until: untilDate(until), rev: c.rev }, "已推迟"];
  } else if (kind === "settle") {
    const guess = c.suggest ? String(c.suggest.outcome) : "1";
    const raw = await ask("结果：1 达成 · 0 未达成 · 0~1 部分 · - 未知", guess);
    if (raw === null) return;
    const note = await ask("结算备注（可空）");
    [path, body, done] = ["settle", { outcome: raw === "-" ? null : Number(raw), note: note || "", rev: c.rev }, "已结算"];
  } else {
    const note = await ask("备注 / 进展");
    if (!note) return;
    [path, body, done] = ["note", { note }, "已备注"];
  }
  if (path !== "note") {
    document.querySelector(`.card[data-id="${CSS.escape(c.id)}"]`)?.classList.add("gone");
  }
  try {
    await api(`/api/items/${encodeURIComponent(c.id)}/${path}`, body);
    toast(`✓ ${done}：${c.title}`);
  } catch (error) {
    fail(error);
  }
  await refresh().catch(fail);
}

async function openItem(id) {
  if (ui.snap) return;
  const item = await api(`/api/items/${encodeURIComponent(id)}`);
  const field = (name, value) => (value == null || value === "" || (Array.isArray(value) && !value.length) ? "" : `<dt>${name}</dt><dd>${esc(Array.isArray(value) ? value.join("，") : value)}</dd>`);
  const trail = item.trail.map((e) => `<div><b>${EVENT[e.type] || e.type}</b> · ${esc(e.actor)} · <span class="muted">${esc(e.ts)}</span><br>${esc(e.data.verdict ? `${e.data.verdict} ${e.data.note || ""}` : e.data.note || e.data.why || "")}</div>`).join("");
  $("#drawer").innerHTML = `<button class="ghost close" data-close>关闭 Esc</button><h3>${esc(item.title)}</h3><dl>
    ${field("状态", STATUS[item.status])}${field("编号", item.id)}${field("领域", domainTitle(item.domain))}${field("优先级", `P${item.priority}`)}
    ${field("原因", item.why)}${field("建议", item.recommend)}${field("预测", item.forecast != null ? `${Math.round(item.forecast * 100)}%（${item.forecast_by}）` : null)}
    ${field("结果", item.outcome)}${field("Brier", item.brier)}${field("到期", item.due)}${field("推迟至", item.until)}${field("证据", item.evidence)}${field("备注", item.note)}
    ${field("可见范围", item.scope)}${field("版本", item.rev)}</dl><div class="trail">${trail}</div>`;
  $("#drawer").hidden = false;
}

// ---------------------------------------------------------------- events
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-act],[data-tab],[data-canon],[data-open],[data-close],.card");
  if (!target) return;
  if (target.dataset.tab) return go(target.dataset.tab);
  if (target.dataset.close !== undefined) return ($("#drawer").hidden = true);
  if (target.dataset.canon) {
    await api(`/api/canon/${encodeURIComponent(target.dataset.id)}/rule`, { verdict: target.dataset.canon }).catch(fail);
    return refresh().catch(fail);
  }
  if (target.dataset.open) return openItem(target.dataset.open).catch(fail);
  const cardEl = target.closest(".card[data-id]");
  if (cardEl) select(ui.cards.findIndex((c) => c.id === cardEl.dataset.id));
  if (target.dataset.act) return act(target.dataset.act);
  if (cardEl && !event.target.closest("button")) openItem(cardEl.dataset.id).catch(fail);
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form.new");
  if (!form) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const body = { domain: form.dataset.domain, title: data.title, priority: 2, due: data.due || null, forecast: data.forecast ? Number(data.forecast) / 100 : null };
  await api("/api/items", body).then(() => toast("✓ 已提交")).catch(fail);
  refresh().catch(fail);
});

document.addEventListener("mousemove", (event) => {
  const svg = event.target.closest("svg.spark");
  if (!svg) return;
  const points = JSON.parse(svg.dataset.points);
  const box = svg.getBoundingClientRect();
  const index = Math.round(((event.clientX - box.left) / box.width) * (points.length - 1));
  const point = points[Math.max(0, Math.min(points.length - 1, index))];
  const peek = svg.parentElement.querySelector(".peek");
  if (peek) peek.textContent = `${point[0]} · ${point[1]}`;
});

document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, dialog") || event.metaKey || event.ctrlKey || event.altKey) {
    if (event.key === "Escape") event.target.blur();
    return;
  }
  const key = event.key;
  if (key === "j" || key === "ArrowDown") select(Math.min(ui.sel + 1, ui.cards.length - 1));
  else if (key === "k" || key === "ArrowUp") select(ui.sel - 1);
  else if ("ardsn".includes(key) && key.length === 1) act({ a: "approve", r: "reject", d: "defer", s: "settle", n: "note" }[key]);
  else if (key === "A" || key === "R") act(key === "A" ? "approve" : "reject", true);
  else if (key === "Enter" && ui.cards[ui.sel]) openItem(ui.cards[ui.sel].id).catch(fail);
  else if (key === "Escape") $("#drawer").hidden = true;
  else if (key === "/") { event.preventDefault(); $("#search").focus(); }
  else if (key === "t") toggleTheme();
  else if (/^[1-9]$/.test(key)) document.querySelectorAll("#tabs button")[Number(key) - 1]?.click();
  else return;
  event.preventDefault();
});

$("#search").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.value.trim()) {
    ui.query = event.target.value.trim();
    event.target.blur();
    go("search");
  }
});

function toggleTheme() {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  store?.setItem("yuanli.theme", document.documentElement.dataset.theme);
}
$("#theme").addEventListener("click", toggleTheme);
if (store?.getItem("yuanli.theme")) document.documentElement.dataset.theme = store.getItem("yuanli.theme");

// ------------------------------------------------------------------ boot
function live() {
  const stream = new EventSource(`/api/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`);
  let pending;
  stream.addEventListener("seq", (event) => {
    $("#live").classList.add("on");
    const seq = Number(event.data);
    if (ui.seq !== null && seq !== ui.seq) {
      clearTimeout(pending);
      pending = setTimeout(() => refresh().catch(fail), 150);
    }
    ui.seq = seq;
  });
  stream.onerror = () => $("#live").classList.remove("on");
}

(async () => {
  const snapshot = document.querySelector('meta[name="yuanli-static"]')?.content;
  ui.snap = snapshot ? await fetch(snapshot).then((r) => r.json()).catch(() => null) : null;
  if (ui.snap) {
    document.body.classList.add("static");
    $("#live").textContent = `快照 · ${ui.snap.audience}`;
  } else {
    live();
  }
  await refresh().catch(fail);
})();
