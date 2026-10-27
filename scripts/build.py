"""把 data/raw/ 的每日資料組成週K，計算日出日落與布林通道，輸出網頁用的 site/data/。

規則：
- 日出：本週收盤 > 上週最高點
- 日落：本週收盤 < 上週最低點
- 布林通道：20 週收盤平均（中軌）± 2 倍標準差
- MACD(12,26,9)：DIF > 訊號線 為多頭
- KD(9,3,3)：K > D 為多頭
- 建議進場：本週出現日出，且收盤在布林中軌之上、MACD 多頭、KD 多頭
- 不建議進場：本週出現日落，且 MACD 或 KD 至少一個轉弱
- 反彈觀察：KD 低檔黃金交叉、跌破布林下軌後收回、MACD 綠柱連續縮短、負乖離過大（任一項）
- 過熱警示：KD 高檔死亡交叉、衝出布林上軌後跌回、MACD 紅柱連續縮短、正乖離過大（任一項）
"""
import csv
import json
import math
import shutil
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "data"
TPE = timezone(timedelta(hours=8))
BB_N, BB_K = 20, 2
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
KD_N = 9
KD_LOW, KD_HIGH = 20, 80   # KD 低檔／高檔
BIAS_LIMIT = 20            # 收盤離 20 週均線超過 ±20% 視為乖離過大
TOP_N = 20


def week_of(d):
    return d - timedelta(days=d.weekday())  # 該週週一


def week_is_final(monday):
    """週五收盤（下午 4 點後）或之後，這一週的週K才算定案。"""
    now = datetime.now(TPE)
    friday = monday + timedelta(days=4)
    return friday < now.date() or (friday == now.date() and now.hour >= 16)


def to_weekly(daily):
    """daily: [(date, o, h, l, c, v)] 依日期排序 → 週K list of dict"""
    weeks = {}
    for d, o, h, l, c, v in daily:
        k = week_of(d)
        w = weeks.get(k)
        if w is None:
            weeks[k] = {"week": k, "start": d, "end": d, "o": o if o else c, "h": h or c, "l": l or c, "c": c, "v": v}
        else:
            w["end"] = d
            w["h"] = max(w["h"], h or c)
            w["l"] = min(w["l"], l or c)
            w["c"] = c
            w["v"] += v
    return [weeks[k] for k in sorted(weeks)]


def analyze(bars):
    """在每根週K上加入布林通道、日出日落事件與目前狀態。"""
    closes = [b["c"] for b in bars]
    state, since = None, None
    for i, b in enumerate(bars):
        if i + 1 >= BB_N:
            win = closes[i + 1 - BB_N:i + 1]
            mid = sum(win) / BB_N
            sd = statistics.pstdev(win)
            b["mid"], b["up"], b["lo"] = mid, mid + BB_K * sd, mid - BB_K * sd
        else:
            b["mid"] = b["up"] = b["lo"] = None
        b["event"] = None
        if i > 0:
            p = bars[i - 1]
            b["prev_h"], b["prev_l"] = p["h"], p["l"]
            b["chg"] = (b["c"] / p["c"] - 1) * 100 if p["c"] else None
            if b["c"] > p["h"]:
                b["event"] = "rise"
            elif b["c"] < p["l"]:
                b["event"] = "set"
        else:
            b["prev_h"] = b["prev_l"] = b["chg"] = None
        b["flip"] = bool(b["event"]) and b["event"] != state  # 狀態翻轉（日落→日出或反之）
        if b["flip"]:
            state, since = b["event"], b["week"]
        b["state"], b["since"] = state, since
    add_macd(bars)
    add_kd(bars)
    return bars


def add_macd(bars):
    """MACD：DIF = EMA12 − EMA26，訊號線 = DIF 的 EMA9，柱狀 = DIF − 訊號線。"""
    a = lambda n: 2 / (n + 1)
    fast = slow = sig = None
    warmup = MACD_SLOW + MACD_SIG - 2  # 資料太少時指標不可靠，先不判斷
    for i, b in enumerate(bars):
        c = b["c"]
        fast = c if fast is None else fast + a(MACD_FAST) * (c - fast)
        slow = c if slow is None else slow + a(MACD_SLOW) * (c - slow)
        dif = fast - slow
        sig = dif if sig is None else sig + a(MACD_SIG) * (dif - sig)
        ready = i >= warmup
        b["dif"], b["dea"], b["osc"] = (dif, sig, dif - sig) if ready else (None, None, None)


def add_kd(bars):
    """KD（台股常用）：RSV = (收盤 − 9週最低) / (9週最高 − 9週最低)；K、D 各以 1/3 平滑，起始 50。"""
    k = d = 50.0
    for i, b in enumerate(bars):
        if i + 1 < KD_N:
            b["k"] = b["d"] = None
            continue
        win = bars[i + 1 - KD_N:i + 1]
        hi, lo = max(x["h"] for x in win), min(x["l"] for x in win)
        rsv = (b["c"] - lo) / (hi - lo) * 100 if hi > lo else 50
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        b["k"], b["d"] = k, d


def status(bars, i):
    """第 i 根週K的判斷結果（給網頁顯示）。"""
    if i is None or i < 0:
        return None
    b = bars[i]
    prev_mid = bars[i - 1]["mid"] if i > 0 else None
    above = b["mid"] is not None and b["c"] > b["mid"]
    macd_bull = b["dif"] is not None and b["dif"] > b["dea"]
    kd_bull = b["k"] is not None and b["k"] > b["d"]
    return {
        "start": b["start"].isoformat(), "end": b["end"].isoformat(),
        "close": r2(b["c"]), "chg": r2(b["chg"]), "vol": round(b["v"] / 1000),
        "prev_high": r2(b["prev_h"]), "prev_low": r2(b["prev_l"]),
        "event": b["event"], "state": b["state"], "since": b["since"].isoformat() if b["since"] else None,
        "mid": r2(b["mid"]), "up": r2(b["up"]), "lo": r2(b["lo"]),
        "above_mid": above,
        "mid_up": b["mid"] is not None and prev_mid is not None and b["mid"] > prev_mid,
        "bb_ready": b["mid"] is not None,
        "dif": r2(b["dif"]), "dea": r2(b["dea"]), "osc": r2(b["osc"]), "macd_bull": macd_bull,
        "k": r2(b["k"]), "d": r2(b["d"]), "kd_bull": kd_bull,
        "ind_ready": b["dif"] is not None and b["k"] is not None,
        "ok": b["state"] == "rise" and above and macd_bull and kd_bull,  # 個股頁的進場結論
        "buy": b["event"] == "rise" and above and macd_bull and kd_bull,  # 首頁「建議進場」
        "avoid": b["event"] == "set" and (not macd_bull or not kd_bull),  # 首頁「不建議進場」
        "bias": r2((b["c"] / b["mid"] - 1) * 100) if b["mid"] else None,
        **turn_signals(bars, i),
    }


def turn_signals(bars, i):
    """反彈／過熱訊號（觀察用，不影響進場結論）。回傳各自觸發的項目代號。"""
    rebound, hot = [], []
    if i < 2:
        return {"rebound": rebound, "hot": hot}
    b, p, pp = bars[i], bars[i - 1], bars[i - 2]
    if None not in (b["k"], p["k"]):
        if p["k"] <= p["d"] and b["k"] > b["d"] and min(p["k"], b["k"]) < KD_LOW:
            rebound.append("kd_cross")      # KD 低檔黃金交叉
        if p["k"] >= p["d"] and b["k"] < b["d"] and max(p["k"], b["k"]) > KD_HIGH:
            hot.append("kd_cross")          # KD 高檔死亡交叉
    if None not in (b["lo"], p["lo"]):
        if p["c"] < p["lo"] and b["c"] > b["lo"]:
            rebound.append("bb_back")       # 跌破布林下軌後收回
        if p["c"] > p["up"] and b["c"] < b["up"]:
            hot.append("bb_back")           # 衝出布林上軌後跌回
    if None not in (b["osc"], p["osc"], pp["osc"]):
        if pp["osc"] < p["osc"] < b["osc"] < 0:
            rebound.append("macd_shrink")   # MACD 綠柱連續兩週縮短
        if pp["osc"] > p["osc"] > b["osc"] > 0:
            hot.append("macd_shrink")       # MACD 紅柱連續兩週縮短
    if b["mid"]:
        bias = (b["c"] / b["mid"] - 1) * 100
        if bias < -BIAS_LIMIT:
            rebound.append("bias")          # 負乖離過大（跌深）
        if bias > BIAS_LIMIT:
            hot.append("bias")              # 正乖離過大（漲多）
    return {"rebound": rebound, "hot": hot}


def turn_rank(x):
    """反彈／過熱清單排序：同時出現的訊號越多越前面，其次看有沒有較強的訊號，再看成交量。"""
    strong = any(t in ("kd_cross", "bb_back") for t in x["tags"])
    return (-len(x["tags"]), not strong, -x["vol"])


def r2(x):
    return None if x is None else round(x, 2)


def final_index(bars):
    """最近一根已定案週K的位置；本週還沒結束就退回上一根。"""
    for i in range(len(bars) - 1, -1, -1):
        if week_is_final(bars[i]["week"]):
            return i
    return None


def latest(daily):
    """最新一個交易日的收盤、日漲跌、成交量（張）。"""
    d, *_, c, v = daily[-1]
    prev = daily[-2][4] if len(daily) > 1 else None
    return {"date": d.isoformat(), "close": r2(c), "chg": r2((c / prev - 1) * 100) if prev else None, "vol": round(v / 1000)}


def export(code, name, bars, daily, market=""):
    fi = final_index(bars)
    last = len(bars) - 1
    doc = {
        "code": code, "name": name, "market": market,
        "last": latest(daily),
        # 日K：指標由網頁端計算，檔案比較小
        "days": [[d.isoformat(), r2(o), r2(h), r2(l), r2(c), round(v / 1000)] for d, o, h, l, c, v in daily],
        "bars": [[b["start"].isoformat(), r2(b["o"]), r2(b["h"]), r2(b["l"]), r2(b["c"]), round(b["v"] / 1000)] for b in bars],
        "bb": [[b["start"].isoformat(), r2(b["mid"]), r2(b["up"]), r2(b["lo"])] for b in bars if b["mid"] is not None],
        "macd": [[b["start"].isoformat(), r2(b["dif"]), r2(b["dea"]), r2(b["osc"])] for b in bars if b["dif"] is not None],
        "kd": [[b["start"].isoformat(), r2(b["k"]), r2(b["d"])] for b in bars if b["k"] is not None],
        "events": [[b["start"].isoformat(), b["event"]] for b in bars if b["flip"]],
        "final": status(bars, fi),
        "prov": status(bars, last) if last != fi else None,  # 本週暫定
    }
    (OUT / "s" / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return fi


MARKETS = [("stocks", "上市"), ("otc", "上櫃")]


def load_stocks():
    """讀上市＋上櫃每日資料，並把分割、減資、除權息之前的價格還原（最新價格不變）。"""
    raw, names, market = defaultdict(dict), {}, {}
    trading_days = set()
    for folder, label in MARKETS:
        for f in sorted((RAW / folder).glob("*.csv")):
            d = datetime.strptime(f.stem, "%Y%m%d").date()
            with f.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    fl = lambda k: float(r[k]) if r.get(k) else None
                    code = r["code"]
                    if fl("close") is None:  # 沒成交
                        continue
                    raw[code][d] = (d, fl("open"), fl("high"), fl("low"), fl("close"), int(r["volume"]))
                    names[code], market[code] = r["name"], label
            trading_days.add(d)
    trading_days = sorted(trading_days)

    actions = defaultdict(list)  # 證交所、櫃買中心公布的除權息／減資／分割
    if (RAW / "actions.csv").exists():
        with (RAW / "actions.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                actions[r["code"]].append((date.fromisoformat(r["date"]), float(r["ref"]) / float(r["prev_close"])))

    daily = {}
    for code, by_day in raw.items():
        rows = [by_day[d] for d in sorted(by_day)]
        events = actions[code] + guess_splits(rows, actions[code], trading_days)
        daily[code] = adjust(rows, events)
    return daily, names, market, trading_days[-1]


SPLIT_RATIOS = [1 / 2, 1 / 2.5, 1 / 4, 1 / 5, 1 / 8, 1 / 10, 1 / 20, 2, 2.5, 4, 5, 10]


def guess_splits(rows, known, trading_days):
    """櫃買中心沒有公開面額變更（分割）資料，用特徵辨識：
    停止交易 2 天以上、恢復後股價跳動超過漲跌停限制，且接近 1/2、1/4、1/10 等整數比例，
    又沒有官方公布的事件 → 視為分割，回傳 (恢復交易日, 比例)。"""
    pos = {d: i for i, d in enumerate(trading_days)}
    events = []
    for (d0, *_, c0, _v0), (d1, *_, c1, _v1) in zip(rows, rows[1:]):
        if pos[d1] - pos[d0] < 3 or 0.89 < c1 / c0 < 1.11:
            continue
        if any(d0 < when <= d1 for when, _ in known):
            continue
        ratio = c1 / c0
        best = min(SPLIT_RATIOS, key=lambda r: abs(math.log(ratio / r)))
        if abs(ratio / best - 1) < 0.12:
            events.append((d1, best))
    return events


def adjust(rows, events):
    """事件生效日之前的開高低收，乘上該事件的比例（多個事件連乘）。成交量不調整。"""
    if not events:
        return rows
    out = []
    for d, o, h, l, c, v in rows:
        f = 1.0
        for when, ratio in events:
            if d < when:
                f *= ratio
        m = lambda x: x * f if x is not None else None
        out.append((d, m(o), m(h), m(l), c * f, v))
    return out


def load_index():
    rows = []
    with (RAW / "index.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append((date.fromisoformat(r["date"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), 0))
    return rows


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "s").mkdir(parents=True)

    idx_daily = load_index()
    idx_bars = analyze(to_weekly(idx_daily))
    export("TAIEX", "加權指數", idx_bars, idx_daily)
    idx_fi = final_index(idx_bars)
    final_week = idx_bars[idx_fi]["week"]

    daily, names, market, last_day = load_stocks()
    buy, avoid, rebound, hot = [], [], [], []
    for code, rows in daily.items():
        bars = analyze(to_weekly(rows))
        fi = export(code, names[code], bars, rows, market[code])
        if fi is None or bars[fi]["week"] != final_week:  # 本週沒交易的股票不列入
            continue
        s = status(bars, fi)
        now = latest(rows)
        item = {"code": code, "name": names[code], "close": now["close"], "dchg": now["chg"], "chg": s["chg"], "vol": s["vol"]}
        if s["buy"]:
            buy.append(item)
        elif s["avoid"]:
            avoid.append(item)
        if s["rebound"]:
            rebound.append({**item, "tags": s["rebound"]})
        if s["hot"]:
            hot.append({**item, "tags": s["hot"]})

    summary = {
        "updated": last_day.isoformat(),
        "generated": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "week": {"start": idx_bars[idx_fi]["start"].isoformat(), "end": idx_bars[idx_fi]["end"].isoformat()},
        "index": status(idx_bars, idx_fi),
        "index_last": latest(idx_daily),
        "index_prov": status(idx_bars, len(idx_bars) - 1) if idx_fi != len(idx_bars) - 1 else None,
        "counts": {"buy": len(buy), "avoid": len(avoid), "rebound": len(rebound), "hot": len(hot)},
        "buy": sorted(buy, key=lambda x: -x["vol"])[:TOP_N],
        "avoid": sorted(avoid, key=lambda x: -x["vol"])[:TOP_N],
        "rebound": sorted(rebound, key=turn_rank)[:TOP_N],
        "hot": sorted(hot, key=turn_rank)[:TOP_N],
        "stocks": sorted([[c, names[c], market[c]] for c in daily]),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：{len(daily)} 檔，定案週 {summary['week']}，建議 {len(buy)}、不建議 {len(avoid)}")


if __name__ == "__main__":
    main()
