"""從證交所抓上市股票每日行情與加權指數，存到 data/raw/。

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
STOCK_DIR = RAW / "stocks"
NODATA_FILE = RAW / "nodata.txt"  # 已確認休市的日期
INDEX_FILE = RAW / "index.csv"

START = date(2024, 10, 1)  # 歷史資料起點（約兩年）
TPE = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0"
PAUSE = 3.5  # 證交所限制請求頻率，太快會被封鎖


def now_tpe():
    return datetime.now(TPE)


def get_json(url):
    # 用 curl 而非 urllib：證交所的憑證在部分 Python 版本會驗證失敗
    for attempt in range(4):
        try:
            out = subprocess.run(["curl", "-sf", "--max-time", "30", "-A", USER_AGENT, url],
                                 capture_output=True, check=True).stdout
            return json.loads(out.decode("utf-8"))
        except Exception as e:  # 網路不穩就等一下再試
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def data_ready(d):
    """當天行情約下午 2:30 後公布；保守一點，4 點後才算當天有資料。"""
    n = now_tpe()
    return d < n.date() or (d == n.date() and n.hour >= 16)


def fetch_stocks():
    nodata = set(NODATA_FILE.read_text().split()) if NODATA_FILE.exists() else set()
    d = START
    today = now_tpe().date()
    while d <= today:
        key = d.strftime("%Y%m%d")
        out = STOCK_DIR / f"{key}.csv"
        if d.weekday() < 5 and not out.exists() and key not in nodata and data_ready(d):
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={key}&type=ALLBUT0999&response=json"
            js = get_json(url)
            table = next((t for t in js.get("tables", []) if "每日收盤行情" in (t.get("title") or "")), None)
            if js.get("stat") != "OK" or not table:
                if d < today:  # 當天可能只是還沒公布，不記成休市，下次再試
                    print(f"{key} 休市")
                    nodata.add(key)
                    NODATA_FILE.write_text("\n".join(sorted(nodata)) + "\n")
                else:
                    print(f"{key} 尚無資料")
            else:
                rows = []
                for r in table["data"]:
                    code = r[0].strip()
                    if not re.fullmatch(r"[1-9]\d{3}", code):  # 只留一般股票（排除 ETF 等）
                        continue
                    o, h, l, c = (num(x) for x in r[5:9])
                    if c is None:  # 當天沒成交
                        continue
                    rows.append([code, r[1].strip(), o, h, l, c, int(num(r[2]) or 0)])
                with out.open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["code", "name", "open", "high", "low", "close", "volume"])
                    w.writerows(rows)
                print(f"{key} {len(rows)} 檔")
            time.sleep(PAUSE)
        d += timedelta(days=1)


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
                y, mo, dd = (int(x) for x in r[0].split("/"))
                dt = date(y + 1911, mo, dd)
                if not data_ready(dt):
                    continue
                have[dt.isoformat()] = {"date": dt.isoformat(), "open": num(r[1]), "high": num(r[2]),
                                        "low": num(r[3]), "close": num(r[4])}
            print(f"指數 {m:%Y-%m}")
            time.sleep(PAUSE)
        m = nxt
    with INDEX_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close"])
        w.writeheader()
        for k in sorted(have):
            w.writerow(have[k])


if __name__ == "__main__":
    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    fetch_index()
    fetch_stocks()
