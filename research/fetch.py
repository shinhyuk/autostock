"""Yahoo 1분봉(최근 30일, 7일씩)과 5분봉(60일)을 받아 data/ 에 JSON 으로 저장."""
import json, sys, time, urllib.request, os
OUT = sys.argv[1]
SYMS = ["SOXL", "SOXS", "NVDA", "SOXX", "QQQ"]
UA = {"User-Agent": "Mozilla/5.0"}

def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("retry", e, file=sys.stderr); time.sleep(2)
    raise SystemExit("failed " + url)

now = int(time.time())
for s in SYMS:
    rows = {}
    for k in range(5):                       # 1분봉: 7일 창 x 5 (yahoo 는 최근 30일까지만)
        p2 = now - k * 7 * 86400
        p1 = p2 - 7 * 86400
        if now - p1 > 29 * 86400:
            p1 = now - 29 * 86400
        if p1 >= p2:
            break
        j = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1m&period1={p1}&period2={p2}&includePrePost=true")
        r = j["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        for i, t in enumerate(r.get("timestamp") or []):
            if q["close"][i] is None:
                continue
            rows[t] = [t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0]
        time.sleep(0.5)
    data = [rows[t] for t in sorted(rows)]
    json.dump(data, open(os.path.join(OUT, f"{s}_1m.json"), "w"))
    print(s, "1m", len(data))
