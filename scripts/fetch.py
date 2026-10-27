"""從證交所（上市）與櫃買中心（上櫃）抓每日行情、加權指數與除權息／減資／分割資料，存到 data/raw/。

只抓還沒抓過的日期，所以每天執行只會多抓一天。
"""
import csv
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INDEX_FILE = RAW / "index.csv"
ACTIONS_FILE = RAW / "actions.csv"  # 上市＋上櫃的除權息、減資、面額變更

START = date(2024, 10, 1)  # 歷史資料起點（約兩年）
TPE = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0"
PAUSE = 3.5  # 證交所、櫃買中心限制請求頻率，太快會被封鎖
COLUMNS = ["code", "name", "open", "high", "low", "close", "volume", "ref"]  # ref：次日參考價（只有上櫃有）


def now_tpe():
    return datetime.now(TPE)


def get_json(url):
    # 用 curl 而非 urllib：證交所的憑證在部分 Python 版本會驗證失敗
    for attempt in range(6):
        try:
            out = subprocess.run(["curl", "-sf", "--max-time", "60", "-A", USER_AGENT, url],
                                 capture_output=True, check=True).stdout
            return json.loads(out.decode("utf-8"))
        except Exception as e:  # 網路不穩（櫃買中心常斷線）就等一下再試
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr, flush=True)
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def roc_date(s):
    """民國日期（113/10/01、113年10月01日 或 1131001）→ date"""
    parts = re.findall(r"\d+", s)
    if len(parts) == 1:  # 1131001
        parts = [parts[0][:-4], parts[0][-4:-2], parts[0][-2:]]
    y, m, d = (int(x) for x in parts[:3])
    return date(y + 1911, m, d)


def data_ready(d):
    """當天行情約下午 2:30 後公布；保守一點，4 點後才算當天有資料。"""
    n = now_tpe()
    return d < n.date() or (d == n.date() and n.hour >= 16)


def is_stock(code):
    return re.fullmatch(r"[1-9]\d{3}", code)  # 只留一般股票（排除 ETF、權證等）


def twse_day(key):
    """上市：回傳當天股票列；休市回傳 None。"""
    js = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={key}&type=ALLBUT0999&response=json")
    table = next((t for t in js.get("tables", []) if "每日收盤行情" in (t.get("title") or "")), None)
    if js.get("stat") != "OK" or not table:
        return None
    rows = []
    for r in table["data"]:
        code = r[0].strip()
        if not is_stock(code):
            continue
        o, h, l, c = (num(x) for x in r[5:9])
        if c is None:  # 當天沒成交
            continue
        rows.append([code, r[1].strip(), o, h, l, c, int(num(r[2]) or 0), ""])
    return rows


def tpex_day(key):
    """上櫃：回傳當天股票列；休市回傳 None。沒成交但有次日參考價的也留著（用來還原減資、分割）。"""
    d = datetime.strptime(key, "%Y%m%d")
    js = get_json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d:%Y}%2F{d:%m}%2F{d:%d}&response=json")
    tables = js.get("tables") or []
    if not tables or not tables[0].get("data"):
        return None
    f = {name.replace(" ", ""): i for i, name in enumerate(tables[0]["fields"])}
    rows = []
    for r in tables[0]["data"]:
        code = r[f["代號"]].strip()
        if not is_stock(code):
            continue
        c, ref = num(r[f["收盤"]]), num(r[f["次日參考價"]])
        if c is None and ref is None:
            continue
        o, h, l = (num(r[f[k]]) for k in ("開盤", "最高", "最低"))
        rows.append([code, r[f["名稱"]].strip(), o, h, l, c if c is not None else "",
                     int(num(r[f["成交股數"]]) or 0), ref if ref is not None else ""])
    return rows


MARKETS = [  # (資料夾, 休市記錄檔, 抓取函式)
    ("stocks", "nodata.txt", twse_day),
    ("otc", "otc_nodata.txt", tpex_day),
]


def fetch_daily(folder, nodata_name, fetch_day):
    out_dir = RAW / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    nodata_file = RAW / nodata_name
    nodata = set(nodata_file.read_text().split()) if nodata_file.exists() else set()
    d = START
    today = now_tpe().date()
    while d <= today:
        key = d.strftime("%Y%m%d")
        out = out_dir / f"{key}.csv"
        if d.weekday() < 5 and not out.exists() and key not in nodata and data_ready(d):
            try:
                rows = fetch_day(key)
            except RuntimeError as e:  # 這天一直抓不到就先跳過，下次執行會再補
                print(f"{folder} {key} 暫時抓不到，下次再試：{e}", file=sys.stderr, flush=True)
                d += timedelta(days=1)
                continue
            if rows is None:
                if d < today:  # 當天可能只是還沒公布，不記成休市，下次再試
                    print(f"{folder} {key} 休市", flush=True)
                    nodata.add(key)
                    nodata_file.write_text("\n".join(sorted(nodata)) + "\n")
                else:
                    print(f"{folder} {key} 尚無資料", flush=True)
            else:
                with out.open("w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(COLUMNS)
                    w.writerows(rows)
                print(f"{folder} {key} {len(rows)} 檔", flush=True)
            time.sleep(PAUSE)
        d += timedelta(days=1)


def fetch_actions():
    """除權息、減資、面額變更（分割）：每次整段重抓（只要 5 個請求）。
    每筆記錄「事件前收盤價」與「事件後參考價」，計算時用兩者比例還原歷史價格。
    櫃買中心沒有公開面額變更資料，上櫃分割由 build.py 依停牌後的整數比例跳空自動辨識。"""
    twse = f"startDate={START:%Y%m%d}&endDate={now_tpe():%Y%m%d}&response=json"
    tpex = f"startDate={START:%Y}%2F{START:%m}%2F{START:%d}&endDate={now_tpe():%Y}%2F{now_tpe():%m}%2F{now_tpe():%d}&response=json"
    sources = [  # (網址, 代號欄, 日期欄, 前收盤欄, 參考價欄)
        (f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?{twse}", "股票代號", "資料日期", "除權息前收盤價", "除權息參考價"),
        (f"https://www.twse.com.tw/rwd/zh/change/TWTB8U?{twse}", "股票代號", "恢復買賣日期", "停止買賣前收盤價格", "恢復買賣參考價"),
        (f"https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?{twse}", "股票代號", "恢復買賣日期", "停止買賣前收盤價格", "恢復買賣參考價"),
        (f"https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?{tpex}", "代號", "除權息日期", "除權息前收盤價", "除權息參考價"),
        (f"https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?{tpex}", "股票代號", "恢復買賣日期", "最後交易日之收盤價格", "減資恢復買賣開始日參考價格"),
    ]
    rows = set()
    for url, ccol, dcol, pcol, rcol in sources:
        js = get_json(url)
        if "tables" in js:  # 櫃買中心的格式
            js = (js["tables"] or [{}])[0]
        f = {name: i for i, name in enumerate(js.get("fields") or [])}
        for r in js.get("data") or []:
            code = r[f[ccol]].strip()
            prev, ref = num(r[f[pcol]]), num(r[f[rcol]])
            if is_stock(code) and prev and ref:
                rows.add((roc_date(r[f[dcol]]).isoformat(), code, prev, ref))
        time.sleep(PAUSE)
    with ACTIONS_FILE.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "code", "prev_close", "ref"])
        w.writerows(sorted(rows))
    print(f"除權息／減資／分割 {len(rows)} 筆", flush=True)


def fetch_index():
    """加權指數每月一個請求；已完整的月份不重抓。"""
    have = {}
    if INDEX_FILE.exists():
        with INDEX_FILE.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                have[r["date"]] = r
    today = now_tpe().date()
    m = date(START.year, START.month, 1)
    while m <= today:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        month_done = any(k >= nxt.isoformat() for k in have)  # 已有下個月的資料，表示這個月抓完了
        if not month_done:
            js = get_json(f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={m.strftime('%Y%m%d')}&response=json")
            for r in js.get("data", []):
                dt = roc_date(r[0])
                if not data_ready(dt):
                    continue
                have[dt.isoformat()] = {"date": dt.isoformat(), "open": num(r[1]), "high": num(r[2]),
                                        "low": num(r[3]), "close": num(r[4])}
            print(f"指數 {m:%Y-%m}", flush=True)
            time.sleep(PAUSE)
        m = nxt
    with INDEX_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close"])
        w.writeheader()
        for k in sorted(have):
            w.writerow(have[k])


if __name__ == "__main__":
    fetch_index()
    fetch_actions()
    for market in MARKETS:
        fetch_daily(*market)
