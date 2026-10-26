"""把 data/raw/ 的每日資料組成週K，計算日出日落與布林通道，輸出網頁用的 site/data/。

規則：
- 日出：本週收盤 > 上週最高點
- 日落：本週收盤 < 上週最低點
- 布林通道：20 週收盤平均（中軌）± 2 倍標準差
- 建議進場：本週出現日出，且收盤在布林中軌之上
- 不建議進場：本週出現日落
"""
import csv
import json
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
    return bars


def status(bars, i):
    """第 i 根週K的判斷結果（給網頁顯示）。"""
    if i is None or i < 0:
        return None
    b = bars[i]
    prev_mid = bars[i - 1]["mid"] if i > 0 else None
    above = b["mid"] is not None and b["c"] > b["mid"]
    return {
        "start": b["start"].isoformat(), "end": b["end"].isoformat(),
        "close": r2(b["c"]), "chg": r2(b["chg"]), "vol": round(b["v"] / 1000),
        "prev_high": r2(b["prev_h"]), "prev_low": r2(b["prev_l"]),
        "event": b["event"], "state": b["state"], "since": b["since"].isoformat() if b["since"] else None,
        "mid": r2(b["mid"]), "up": r2(b["up"]), "lo": r2(b["lo"]),
        "above_mid": above,
        "mid_up": b["mid"] is not None and prev_mid is not None and b["mid"] > prev_mid,
        "bb_ready": b["mid"] is not None,
        "ok": b["state"] == "rise" and above,  # 個股頁的進場結論
    }


def r2(x):
    return None if x is None else round(x, 2)


def final_index(bars):
    """最近一根已定案週K的位置；本週還沒結束就退回上一根。"""
    for i in range(len(bars) - 1, -1, -1):
        if week_is_final(bars[i]["week"]):
            return i
    return None


def export(code, name, bars):
    fi = final_index(bars)
    last = len(bars) - 1
    doc = {
        "code": code, "name": name,
        "bars": [[b["start"].isoformat(), r2(b["o"]), r2(b["h"]), r2(b["l"]), r2(b["c"]), round(b["v"] / 1000)] for b in bars],
        "bb": [[b["start"].isoformat(), r2(b["mid"]), r2(b["up"]), r2(b["lo"])] for b in bars if b["mid"] is not None],
        "events": [[b["start"].isoformat(), b["event"]] for b in bars if b["flip"]],
        "final": status(bars, fi),
        "prov": status(bars, last) if last != fi else None,  # 本週暫定
    }
    (OUT / "s" / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return fi


def load_stocks():
    daily, names = defaultdict(list), {}
    for f in sorted((RAW / "stocks").glob("*.csv")):
        d = datetime.strptime(f.stem, "%Y%m%d").date()
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                fl = lambda k: float(r[k]) if r[k] else None
                daily[r["code"]].append((d, fl("open"), fl("high"), fl("low"), float(r["close"]), int(r["volume"])))
                names[r["code"]] = r["name"]
    return daily, names, d


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

    idx_bars = analyze(to_weekly(load_index()))
    export("TAIEX", "加權指數", idx_bars)
    idx_fi = final_index(idx_bars)
    final_week = idx_bars[idx_fi]["week"]

    daily, names, last_day = load_stocks()
    buy, avoid = [], []
    for code, rows in daily.items():
        bars = analyze(to_weekly(rows))
        fi = export(code, names[code], bars)
        if fi is None or bars[fi]["week"] != final_week:  # 本週沒交易的股票不列入
            continue
        s = status(bars, fi)
        item = {"code": code, "name": names[code], "close": s["close"], "chg": s["chg"], "vol": s["vol"]}
        if s["event"] == "rise" and s["above_mid"]:
            buy.append(item)
        elif s["event"] == "set":
            avoid.append(item)

    summary = {
        "updated": last_day.isoformat(),
        "generated": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "week": {"start": idx_bars[idx_fi]["start"].isoformat(), "end": idx_bars[idx_fi]["end"].isoformat()},
        "index": status(idx_bars, idx_fi),
        "index_prov": status(idx_bars, len(idx_bars) - 1) if idx_fi != len(idx_bars) - 1 else None,
        "counts": {"buy": len(buy), "avoid": len(avoid)},
        "buy": sorted(buy, key=lambda x: -x["vol"])[:TOP_N],
        "avoid": sorted(avoid, key=lambda x: -x["vol"])[:TOP_N],
        "stocks": sorted([[c, names[c]] for c in daily]),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：{len(daily)} 檔，定案週 {summary['week']}，建議 {len(buy)}、不建議 {len(avoid)}")


if __name__ == "__main__":
    main()
