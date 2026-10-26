// 週K日出日落：單頁網站。#/ 是首頁，#/2330 是個股頁。
const $ = (s) => document.querySelector(s);
const app = $("#app");
let summary = null;
let chart = null;

const fmt = (x, d = 2) => (x == null ? "—" : Number(x).toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (x) => (x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(2) + "%");
const cls = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
const md = (s) => (s ? s.slice(5).replace("-", "/") : "");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const STATE = {
  rise: { text: "☀ 日出", cls: "up" },
  set: { text: "🌙 日落", cls: "down" },
};
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
      </div>
    </a>
    <div class="week-title">
      <h1>本週訊號</h1>
      <span class="muted">依 ${md(s.week.start)}–${md(s.week.end)} 週K收盤判斷</span>
    </div>
    <div class="lists">
      ${listCard("up", "本週建議進場", "週K日出 ＋ 收盤在布林中軌之上", s.buy, s.counts.buy)}
      ${listCard("down", "本週不建議進場", "週K日落（收盤跌破上週最低點）", s.avoid, s.counts.avoid)}
    </div>`;
  app.querySelectorAll("tr[data-code]").forEach((tr) => tr.addEventListener("click", () => (location.hash = "#/" + tr.dataset.code)));
}

function listCard(kind, title, rule, items, total) {
  const rows = items
    .map(
      (x, i) => `<tr data-code="${x.code}">
        <td><span class="rank">${i + 1}</span>${x.code}<span class="sname">${esc(x.name)}</span></td>
        <td class="num">${fmt(x.close)}</td>
        <td class="num ${cls(x.chg)}">${pct(x.chg)}</td>
        <td class="num hide-sm">${x.vol.toLocaleString()}</td></tr>`
    )
    .join("");
  return `<section class="card list">
    <div class="list-head ${kind}">
      <h2 class="${kind}">${title}</h2>
      <p>${rule}｜共 ${total} 檔，依成交量列前 ${Math.min(20, total)} 檔</p>
    </div>
    ${items.length ? `<table><thead><tr><th>股票</th><th>收盤</th><th>週漲跌</th><th class="hide-sm">週量(張)</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty">本週沒有符合的股票</div>`}
  </section>`;
}

// ---------- 個股頁 ----------
async function renderStock(code) {
  app.innerHTML = `<p class="muted center">載入中…</p>`;
  let d;
  try {
    d = await getJSON(`data/s/${code}.json`);
  } catch {
    app.innerHTML = `<a class="back" href="#/">← 回首頁</a><p class="center muted">找不到「${esc(code)}」，請確認是上市股票代號。</p>`;
    return;
  }
  const f = d.final;
  const p = d.prov;
  const isIdx = code === "TAIEX";
  const ok = f.ok;
  const reason = !f.bb_ready
    ? "上市未滿 20 週，布林通道資料不足"
    : ok
    ? `週K處於日出狀態，且收盤在布林中軌之上`
    : f.state !== "rise"
    ? f.state === "set" ? "週K處於日落狀態" : "尚未出現日出訊號"
    : "雖在日出狀態，但收盤跌回布林中軌之下";

  const check = (met, title, sub) => `<li><span class="dot ${met ? "up" : "down"}">${met ? "✓" : "✗"}</span>
    <div><div class="t">${title}</div><div class="s">${sub}</div></div></li>`;

  app.innerHTML = `
    <a class="back" href="#/">← 回首頁</a>
    <div class="stock-head">
      <h1>${esc(d.name)}</h1><span class="code">${isIdx ? "大盤" : code}</span>
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
      </div>
      <div class="side">
        <div class="card">
          <h2>進場條件檢查</h2>
          <ul class="checks">
            ${check(f.state === "rise", "週K處於日出狀態", f.state ? `${STATE[f.state].text}，自 ${md(f.since)} 那週開始` : "尚無日出或日落訊號")}
            ${check(f.above_mid, "收盤在布林中軌之上", `收盤 ${fmt(f.close)}／中軌 ${fmt(f.mid)}`)}
          </ul>
          <p class="sub">參考指標（不影響結論）</p>
          <ul class="checks">
            ${check(f.event === "rise", "本週剛出現日出", `收盤 ${fmt(f.close)} vs 上週高點 ${fmt(f.prev_high)}`)}
            ${check(f.mid_up, "布林中軌方向向上", "中軌上揚代表中期趨勢偏多")}
          </ul>
        </div>
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

function drawChart(d) {
  if (chart) chart.remove();
  const el = $("#chart");
  chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: "#868b98", fontSize: 11 },
    grid: { vertLines: { color: "#22262f" }, horzLines: { color: "#22262f" } },
    rightPriceScale: { borderColor: "#2a2e39" },
    timeScale: { borderColor: "#2a2e39" },
    crosshair: { mode: 0 },
    localization: { locale: "zh-TW" },
  });
  const candles = chart.addCandlestickSeries({
    upColor: "#f23645", downColor: "#089981", borderUpColor: "#f23645", borderDownColor: "#089981",
    wickUpColor: "#f23645", wickDownColor: "#089981",
  });
  candles.setData(d.bars.map(([t, o, h, l, c]) => ({ time: t, open: o, high: h, low: l, close: c })));
  const line = (color, i, style = 0) => {
    const s = chart.addLineSeries({ color, lineWidth: 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(d.bb.map((r) => ({ time: r[0], value: r[i] })));
  };
  line("#f0b90b", 1);
  line("#5b8def", 2, 2);
  line("#5b8def", 3, 2);
  candles.setMarkers(
    d.events.map(([t, e]) =>
      e === "rise"
        ? { time: t, position: "belowBar", color: "#f23645", shape: "arrowUp", text: "日出" }
        : { time: t, position: "aboveBar", color: "#089981", shape: "arrowDown", text: "日落" }
    )
  );
  if (d.code !== "TAIEX") {
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(d.bars.map(([t, o, , , c, v]) => ({ time: t, value: v, color: c >= o ? "rgba(242,54,69,.35)" : "rgba(8,153,129,.35)" })));
  }
  // 預設顯示最近約一年（手機半年）；等圖表量好寬度後再設定
  const n = d.bars.length;
  const span = el.clientWidth < 500 ? 26 : 52;
  requestAnimationFrame(() => chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - span), to: n + 1 }));
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
  sug.innerHTML = hits.map(([c, n], i) => `<li data-code="${c}" class="${i === 0 ? "on" : ""}"><span class="code">${c === "TAIEX" ? "大盤" : c}</span>${esc(n)}</li>`).join("");
  sug.hidden = false;
}

function go(code) {
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

// ---------- 路由 ----------
function route() {
  const code = location.hash.replace(/^#\/?/, "");
  window.scrollTo(0, 0);
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
