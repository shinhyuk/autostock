import json, sys, time, urllib.request, os
for s in sys.argv[2].split(","):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=5m&range=60d"
    j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    rows = [[t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0]
            for i, t in enumerate(r.get("timestamp") or []) if q["close"][i] is not None]
    json.dump(rows, open(os.path.join(sys.argv[1], f"{s}_5m.json"), "w")); print(s, len(rows)); time.sleep(0.5)
