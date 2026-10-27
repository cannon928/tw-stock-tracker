// 週K日出日落：單頁網站。#/ 是首頁，#/2330 是個股頁。
const $ = (s) => document.querySelector(s);
const app = $("#app");
let summary = null;
let charts = [];

const fmt = (x, d = 2) => (x == null ? "—" : Number(x).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (x) => (x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(2) + "%");
const cls = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
const md = (s) => (s ? s.slice(5).replace("-", "/") : "");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const STATE = {
  rise: { text: "☀ 日出", cls: "up" },
  set: { text: "🌙 日落", cls: "down" },
};
// 反彈／過熱訊號的名稱（對應 build.py 的 turn_signals）
const TURN = {
  rebound: {
    title: "反彈觀察", cls: "watch",
    rule: "跌深可能反彈，出現任一項就列入（只供觀察，不是進場訊號）",
    tags: { kd_cross: "KD低檔黃金交叉", bb_back: "跌破下軌後收回", macd_shrink: "MACD綠柱縮短", bias: "負乖離過大" },
    desc: { kd_cross: "K 在 20 以下向上穿過 D", bb_back: "上週收在布林下軌之下，本週收回下軌之上", macd_shrink: "MACD 柱狀為負，且連續兩週縮短", bias: "收盤低於 20 週均線超過 20%" },
  },
  hot: {
    title: "過熱警示", cls: "hot",
    rule: "漲多可能拉回，出現任一項就列入（持有者留意）",
    tags: { kd_cross: "KD高檔死亡交叉", bb_back: "衝出上軌後跌回", macd_shrink: "MACD紅柱縮短", bias: "正乖離過大" },
    desc: { kd_cross: "K 在 80 以上向下穿過 D", bb_back: "上週收在布林上軌之上，本週跌回上軌之下", macd_shrink: "MACD 柱狀為正，且連續兩週縮短", bias: "收盤高於 20 週均線超過 20%" },
  },
};
const tagChips = (kind, tags) => tags.map((t) => `<span class="chip ${TURN[kind].cls}">${TURN[kind].tags[t]}</span>`).join("");

const badge = (k, suffix = "") =>
  k ? `<span class="badge ${STATE[k].cls}">${STATE[k].text}${suffix}</span>` : `<span class="badge none">尚無訊號</span>`;

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

// ---------- 首頁 ----------
function renderHome() {
  const s = summary;
  const idx = s.index;
  app.innerHTML = `
    <a class="card index-card" href="#/TAIEX">
      <div>
        <div class="label">加權指數（週K）</div>
        <div><span class="price num">${fmt(idx.close)}</span>
          <span class="num ${cls(idx.chg)}">${pct(idx.chg)}</span></div>
      </div>
      <div class="idx-state">
        <div class="label">大盤目前狀態</div>
        ${badge(idx.state)} <span class="badge ${idx.above_mid ? "up" : "down"}">${idx.above_mid ? "中軌之上" : "中軌之下"}</span>
        ${idx.rebound.length || idx.hot.length ? `<div class="idx-tags">${tagChips("rebound", idx.rebound)}${tagChips("hot", idx.hot)}</div>` : ""}
      </div>
    </a>
    <div class="week-title">
      <h1>本週訊號</h1>
      <span class="muted">依 ${md(s.week.start)}–${md(s.week.end)} 週K收盤判斷</span>
    </div>
    <p class="fresh">資料已更新到 <b>${md(s.updated)}</b> 收盤。首頁清單用「已收完的一週」判斷，每週五收盤後才換一次；這週每天的變化請點進個股看「本週暫定」。</p>
    <div class="lists">
      ${listCard("up", "本週建議進場", "週K日出 ＋ 布林中軌之上 ＋ MACD 多頭 ＋ KD 多頭", s.buy, s.counts.buy)}
      ${listCard("down", "本週不建議進場", "週K日落 ＋ MACD 或 KD 轉弱", s.avoid, s.counts.avoid)}
    </div>
    <div class="week-title section2">
      <h1>反彈與過熱觀察</h1>
      <span class="muted">依同時出現的訊號數、訊號強弱、成交量排序</span>
    </div>
    <div class="lists">
      ${listCard(TURN.rebound.cls, TURN.rebound.title, TURN.rebound.rule, s.rebound, s.counts.rebound, "rebound")}
      ${listCard(TURN.hot.cls, TURN.hot.title, TURN.hot.rule, s.hot, s.counts.hot, "hot")}
    </div>`;
  app.onclick = onHomeClick;
}

// 首頁清單：點表頭可依收盤、週漲跌、週量排序（大→小 → 小→大 → 恢復原本順序）
const homeLists = {};
const SORT_COLS = [
  ["close", "收盤"],
  ["chg", "週漲跌"],
  ["vol", "週量(張)"],
];

function listCard(kind, title, rule, items, total, turn) {
  const key = title;
  homeLists[key] = { items, turn, col: null, dir: 0 };
  return `<section class="card list" data-list="${key}">
    <div class="list-head ${kind}">
      <h2 class="${kind}">${title}</h2>
      <p>${rule}｜共 ${total} 檔，列前 ${Math.min(20, total)} 檔${turn ? "" : "（依成交量）"}</p>
    </div>
    ${items.length ? `<table><thead>${headRow(homeLists[key])}</thead><tbody>${listRows(homeLists[key])}</tbody></table>` : `<div class="empty">本週沒有符合的股票</div>`}
  </section>`;
}

function headRow(L) {
  const th = SORT_COLS.map(([col, label]) => {
    const arrow = L.col === col ? (L.dir < 0 ? " ▼" : " ▲") : " ⇅";
    return `<th class="sortable${L.col === col ? " on" : ""}" data-sort="${col}">${label}<span class="arrow">${arrow}</span></th>`;
  }).join("");
  return `<tr><th>股票</th>${th}</tr>`;
}

function listRows(L) {
  const items = L.col ? [...L.items].sort((a, b) => ((a[L.col] ?? 0) - (b[L.col] ?? 0)) * L.dir) : L.items;
  return items
    .map(
      (x, i) => `<tr data-code="${x.code}">
        <td><span class="rank">${i + 1}</span>${x.code}<span class="sname">${esc(x.name)}</span>${L.turn ? `<div class="tags">${tagChips(L.turn, x.tags)}</div>` : ""}</td>
        <td class="num">${fmt(x.close)}</td>
        <td class="num ${cls(x.chg)}">${pct(x.chg)}</td>
        <td class="num">${x.vol.toLocaleString()}</td></tr>`
    )
    .join("");
}

function onHomeClick(e) {
  const th = e.target.closest("th[data-sort]");
  if (th) {
    const sec = th.closest("[data-list]");
    const L = homeLists[sec.dataset.list];
    const col = th.dataset.sort;
    if (L.col !== col) [L.col, L.dir] = [col, -1];
    else if (L.dir < 0) L.dir = 1;
    else [L.col, L.dir] = [null, 0];
    sec.querySelector("thead").innerHTML = headRow(L);
    sec.querySelector("tbody").innerHTML = listRows(L);
    return;
  }
  const tr = e.target.closest("tr[data-code]");
  if (tr) location.hash = "#/" + tr.dataset.code;
}

// ---------- 個股頁 ----------
async function renderStock(code) {
  app.onclick = null;
  app.innerHTML = `<p class="muted center">載入中…</p>`;
  let d;
  try {
    d = await getJSON(`data/s/${code}.json`);
  } catch {
    app.innerHTML = `<a class="back" href="#/">← 回首頁</a><p class="center muted">找不到「${esc(code)}」，請確認是上市或上櫃股票代號。</p>`;
    return;
  }
  const f = d.final;
  const p = d.prov;
  const isIdx = code === "TAIEX";
  const ok = f.ok;
  const missing = [
    f.state !== "rise" && (f.state === "set" ? "週K處於日落狀態" : "尚未出現日出訊號"),
    !f.above_mid && "收盤在布林中軌之下",
    !f.macd_bull && "MACD 偏空",
    !f.kd_bull && "KD 偏空",
  ].filter(Boolean);
  const reason = !f.bb_ready || !f.ind_ready
    ? "上市時間太短，指標資料不足"
    : ok
    ? "日出、布林、MACD、KD 四項條件全部符合"
    : "未符合：" + missing.join("、");

  const check = (met, title, sub) => `<li><span class="dot ${met ? "up" : "down"}">${met ? "✓" : "✗"}</span>
    <div><div class="t">${title}</div><div class="s">${sub}</div></div></li>`;

  app.innerHTML = `
    <a class="back" href="#/">← 回首頁</a>
    <div class="stock-head">
      <h1>${esc(d.name)}</h1><span class="code">${isIdx ? "大盤" : `${code}　${d.market}`}</span>
      <span class="price num">${fmt(f.close)}</span><span class="num ${cls(f.chg)}">${pct(f.chg)}</span>
    </div>
    <div class="verdict ${ok ? "up" : "down"}">
      <div class="big">${ok ? "✅ 符合進場條件" : "⛔ 不建議進場"}</div>
      <p>${reason}（依 ${md(f.start)}–${md(f.end)} 週K收盤）</p>
    </div>
    <div class="detail">
      <div class="card chart-card">
        <div class="legend">
          <span><i style="background:#f0b90b"></i>中軌(20週)</span>
          <span><i style="background:#5b8def"></i>上軌／下軌</span>
          <span>▲日出　▼日落</span>
        </div>
        <div id="chart"></div>
        <div class="legend sub-legend">MACD(12,26,9)　<span><i style="background:#f0b90b"></i>DIF</span><span><i style="background:#5b8def"></i>訊號線</span></div>
        <div id="macd" class="sub-chart"></div>
        <div class="legend sub-legend">KD(9,3,3)　<span><i style="background:#f0b90b"></i>K</span><span><i style="background:#5b8def"></i>D</span></div>
        <div id="kd" class="sub-chart"></div>
      </div>
      <div class="side">
        <div class="card">
          <h2>進場條件檢查</h2>
          <ul class="checks">
            ${check(f.state === "rise", "週K處於日出狀態", f.state ? `${STATE[f.state].text}，自 ${md(f.since)} 那週開始` : "尚無日出或日落訊號")}
            ${check(f.above_mid, "收盤在布林中軌之上", `收盤 ${fmt(f.close)}／中軌 ${fmt(f.mid)}`)}
            ${check(f.macd_bull, "MACD 多頭", `DIF ${fmt(f.dif)} ${f.macd_bull ? "高於" : "低於"}訊號線 ${fmt(f.dea)}`)}
            ${check(f.kd_bull, "KD 多頭", `K ${fmt(f.k, 1)} ${f.kd_bull ? "高於" : "低於"} D ${fmt(f.d, 1)}`)}
          </ul>
          <p class="sub">參考指標（不影響結論）</p>
          <ul class="checks">
            ${check(f.event === "rise", "本週剛出現日出", `收盤 ${fmt(f.close)} vs 上週高點 ${fmt(f.prev_high)}`)}
            ${check(f.mid_up, "布林中軌方向向上", "中軌上揚代表中期趨勢偏多")}
            ${check(f.osc > 0, "MACD 柱狀體為正", `柱狀 ${fmt(f.osc)}`)}
            ${check(f.k != null && f.k < 80, "KD 未過熱（K < 80）", f.k >= 80 ? "K 值偏高，追高要小心" : f.k <= 20 ? "K 值低於 20，處於超賣區" : `K ${fmt(f.k, 1)}`)}
          </ul>
        </div>
        ${turnCard(f)}
        ${p ? provCard(p) : ""}
        <div class="card">
          <h2>本週數據</h2>
          <div class="kv num">
            <span>上週最高（日出線）</span><span>${fmt(f.prev_high)}</span>
            <span>上週最低（日落線）</span><span>${fmt(f.prev_low)}</span>
            <span>布林上軌</span><span>${fmt(f.up)}</span>
            <span>布林中軌</span><span>${fmt(f.mid)}</span>
            <span>布林下軌</span><span>${fmt(f.lo)}</span>
            ${isIdx ? "" : `<span>週成交量</span><span>${f.vol.toLocaleString()} 張</span>`}
          </div>
        </div>
      </div>
    </div>`;
  drawChart(d);
}

function turnCard(f) {
  const rows = (kind) =>
    Object.keys(TURN[kind].tags)
      .map((t) => {
        const on = f[kind].includes(t);
        return `<li><span class="dot ${on ? TURN[kind].cls : "off"}">${on ? "!" : ""}</span>
          <div><div class="t">${TURN[kind].tags[t]}</div><div class="s">${TURN[kind].desc[t]}</div></div></li>`;
      })
      .join("");
  return `<div class="card">
    <h2>反彈／過熱訊號 <span class="muted" style="font-size:12px;font-weight:400">（觀察用）</span></h2>
    <p class="sub">反彈觀察：出現 ${f.rebound.length} 項</p>
    <ul class="checks">${rows("rebound")}</ul>
    <p class="sub">過熱警示：出現 ${f.hot.length} 項</p>
    <ul class="checks">${rows("hot")}</ul>
    <p class="sub">目前乖離率（收盤 vs 20 週均線）：${f.bias == null ? "—" : pct(f.bias)}</p>
  </div>`;
}

function provCard(p) {
  const ev = p.event === "rise" ? "暫時站上上週高點（日出）" : p.event === "set" ? "暫時跌破上週低點（日落）" : "在上週高低點之間，尚無新訊號";
  return `<div class="card">
    <h2>本週進行中（暫定）</h2>
    <p class="sub" style="margin-top:6px">截至 ${md(p.end)} 收盤 ${fmt(p.close)}：${ev}。<br>要等週五收盤才定案。</p>
    <div class="kv num">
      <span>日出線（上週高）</span><span>${fmt(p.prev_high)}</span>
      <span>日落線（上週低）</span><span>${fmt(p.prev_low)}</span>
    </div>
  </div>`;
}

const CHART_OPTS = {
  autoSize: true,
  layout: { background: { color: "transparent" }, textColor: "#868b98", fontSize: 11 },
  grid: { vertLines: { color: "#22262f" }, horzLines: { color: "#22262f" } },
  rightPriceScale: { borderColor: "#2a2e39", minimumWidth: 72 },  // 三張圖右側同寬，K棒才會上下對齊
  timeScale: { borderColor: "#2a2e39" },
  crosshair: { mode: 0 },
  localization: { locale: "zh-TW" },
};
const plain = { lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };

function drawChart(d) {
  charts.forEach((c) => c.remove());
  const main = LightweightCharts.createChart($("#chart"), CHART_OPTS);
  const candles = main.addCandlestickSeries({
    upColor: "#f23645", downColor: "#089981", borderUpColor: "#f23645", borderDownColor: "#089981",
    wickUpColor: "#f23645", wickDownColor: "#089981",
  });
  candles.setData(d.bars.map(([t, o, h, l, c]) => ({ time: t, open: o, high: h, low: l, close: c })));
  const bbLine = (color, i, style = 0) =>
    main.addLineSeries({ ...plain, color, lineStyle: style }).setData(d.bb.map((r) => ({ time: r[0], value: r[i] })));
  bbLine("#f0b90b", 1);
  bbLine("#5b8def", 2, 2);
  bbLine("#5b8def", 3, 2);
  candles.setMarkers(
    d.events.map(([t, e]) =>
      e === "rise"
        ? { time: t, position: "belowBar", color: "#f23645", shape: "arrowUp", text: "日出" }
        : { time: t, position: "aboveBar", color: "#089981", shape: "arrowDown", text: "日落" }
    )
  );
  if (d.code !== "TAIEX") {
    const vol = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(d.bars.map(([t, o, , , c, v]) => ({ time: t, value: v, color: c >= o ? "rgba(242,54,69,.35)" : "rgba(8,153,129,.35)" })));
  }

  // 副圖：指標前幾週還沒算出來的地方用空白補齊，讓每根K棒位置跟主圖一致
  const times = d.bars.map((b) => b[0]);
  const series = (rows, i, map = (v) => ({ value: v })) => {
    const byTime = new Map(rows.map((r) => [r[0], r[i]]));
    return times.map((t) => (byTime.has(t) ? { time: t, ...map(byTime.get(t)) } : { time: t }));
  };

  const macd = LightweightCharts.createChart($("#macd"), CHART_OPTS);
  macd.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false })
    .setData(series(d.macd, 3, (v) => ({ value: v, color: v >= 0 ? "rgba(242,54,69,.6)" : "rgba(8,153,129,.6)" })));
  macd.addLineSeries({ ...plain, color: "#f0b90b" }).setData(series(d.macd, 1));
  macd.addLineSeries({ ...plain, color: "#5b8def" }).setData(series(d.macd, 2));

  const kd = LightweightCharts.createChart($("#kd"), CHART_OPTS);
  const k = kd.addLineSeries({ ...plain, color: "#f0b90b" });
  k.setData(series(d.kd, 1));
  kd.addLineSeries({ ...plain, color: "#5b8def" }).setData(series(d.kd, 2));
  [80, 20].forEach((p) => k.createPriceLine({ price: p, color: "#3a3f4b", lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));

  charts = [main, macd, kd];
  // 三張圖一起捲動、縮放
  let syncing = false;
  charts.forEach((c) =>
    c.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (syncing || !r) return;
      syncing = true;
      charts.forEach((o) => o !== c && o.timeScale().setVisibleLogicalRange(r));
      syncing = false;
    })
  );

  // 預設顯示最近約一年（手機半年）；等圖表量好寬度後再設定
  const n = d.bars.length;
  const span = $("#chart").clientWidth < 500 ? 26 : 52;
  requestAnimationFrame(() => main.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - span), to: n + 1 }));
}

// ---------- 搜尋 ----------
const q = $("#q");
const sug = $("#suggest");
let hits = [];
let active = 0;

function search(text) {
  text = text.trim().toLowerCase();
  if (!text || !summary) return [];
  const all = [["TAIEX", "加權指數 大盤"], ...summary.stocks];
  const starts = all.filter(([c, n]) => c.toLowerCase().startsWith(text) || n.toLowerCase().startsWith(text));
  const contains = all.filter((x) => !starts.includes(x) && x[1].toLowerCase().includes(text));
  return [...starts, ...contains].slice(0, 8);
}

function showSuggest() {
  hits = search(q.value);
  active = 0;
  if (!hits.length) return (sug.hidden = true);
  sug.innerHTML = hits.map(([c, n, m], i) => `<li data-code="${c}" class="${i === 0 ? "on" : ""}"><span class="code">${c === "TAIEX" ? "大盤" : c}</span>${esc(n)}<span class="mkt">${m || ""}</span></li>`).join("");
  sug.hidden = false;
}

function go(code) {
  remember(code);
  sug.hidden = true;
  q.value = "";
  q.blur();
  location.hash = "#/" + code;
}

q.addEventListener("input", showSuggest);
q.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!hits.length) return;
    active = (active + (e.key === "ArrowDown" ? 1 : -1) + hits.length) % hits.length;
    sug.querySelectorAll("li").forEach((li, i) => li.classList.toggle("on", i === active));
  } else if (e.key === "Enter") {
    if (hits[active]) go(hits[active][0]);
    else if (/^\d{4}$/.test(q.value.trim())) go(q.value.trim());
  } else if (e.key === "Escape") sug.hidden = true;
});
sug.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li");
  if (li) go(li.dataset.code);
});
q.addEventListener("blur", () => setTimeout(() => (sug.hidden = true), 150));

// ---------- 最近搜尋（存在這台裝置的瀏覽器裡） ----------
const RECENT_KEY = "recentSearches";
const RECENT_MAX = 10;

function loadRecent() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY)) || [];
  } catch {
    return [];
  }
}

function remember(code) {
  if (code !== "TAIEX" && !summary.stocks.some((x) => x[0] === code)) return;  // 查無此股不記
  const list = [code, ...loadRecent().filter((c) => c !== code)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {}
}

function renderRecent() {
  const names = new Map([["TAIEX", "加權指數"], ...summary.stocks.map(([c, n]) => [c, n])]);
  const list = loadRecent().filter((c) => names.has(c));
  const current = location.hash.replace(/^#\/?/, "");
  $("#recent").innerHTML = `
    <div class="recent-head"><h2>最近搜尋</h2>${list.length ? `<button id="clear-recent" type="button">清除</button>` : ""}</div>
    ${
      list.length
        ? `<ol>${list
            .map((c) => `<li><a href="#/${c}" class="${c === current ? "on" : ""}"><span class="code">${c === "TAIEX" ? "大盤" : c}</span>${esc(names.get(c))}</a></li>`)
            .join("")}</ol>`
        : `<p class="muted">用上方搜尋欄查過的股票會出現在這裡</p>`
    }`;
  const btn = $("#clear-recent");
  if (btn)
    btn.onclick = () => {
      try {
        localStorage.removeItem(RECENT_KEY);
      } catch {}
      renderRecent();
    };
}

// ---------- 路由 ----------
function route() {
  const code = location.hash.replace(/^#\/?/, "");
  window.scrollTo(0, 0);
  renderRecent();
  if (code) renderStock(code);
  else renderHome();
}

(async () => {
  try {
    summary = await getJSON("data/summary.json");
  } catch {
    app.innerHTML = `<p class="center muted">資料載入失敗，請稍後再試。</p>`;
    return;
  }
  $("#updated").textContent = `資料日期：${summary.updated}（每個交易日收盤後自動更新，最後計算 ${summary.generated}）`;
  window.addEventListener("hashchange", route);
  route();
})();
