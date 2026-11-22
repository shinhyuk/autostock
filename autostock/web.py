"""읽기 전용 결과 페이지. 봇과 별도 프로세스로 돌며 data/ 의 상태·기록 파일만 읽는다.

    python -m autostock.web        # http://<서버IP>:8080/?k=<WEB_TOKEN>

주소의 k 값(.env 의 WEB_TOKEN)이 맞아야 열린다. 주문/설정을 바꾸는 기능은 없다.
"""
from __future__ import annotations

import hmac
import html
import json
import os
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config

MODES = {"paper": "가상매매", "kis-demo": "모의투자", "live": "실계좌"}
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#16181d;--mut:#6b7280;--line:#e5e7eb;--up:#d92d20;--dn:#1d4ed8;--acc:#111827}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--fg:#e8eaed;--mut:#9aa1ac;--line:#2a2e37;--up:#ff6b5e;--dn:#6ea8ff;--acc:#e8eaed}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:18px;margin:4px 0 12px}h2{font-size:14px;color:var(--mut);margin:22px 0 8px;font-weight:600}
nav{display:flex;gap:6px;margin-bottom:14px}nav a{padding:6px 12px;border-radius:999px;border:1px solid var(--line);color:var(--fg);text-decoration:none;font-size:13px}
nav a.on{background:var(--acc);color:var(--bg);border-color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.k{font-size:12px;color:var(--mut)}.v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--mut)}
.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}td.wrap{white-space:normal;min-width:220px}
th{color:var(--mut);font-weight:600}td.r,th.r{text-align:right}tr:last-child td{border-bottom:0}
.tag{font-size:12px;padding:1px 7px;border-radius:6px;border:1px solid var(--line)}
footer{color:var(--mut);font-size:12px;margin:18px 0}
"""


def _read(cfg, mode):
    state, events = None, []
    try:
        with open(os.path.join(cfg.data_dir, f"state_{mode}.json"), encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        pass
    try:
        with open(os.path.join(cfg.data_dir, f"journal_{mode}.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return state, events


def render(cfg, mode: str, token: str) -> str:
    e = html.escape
    state, events = _read(cfg, mode)
    fx = cfg.usdkrw

    def money(usd: float) -> str:
        cls = "up" if usd > 0 else "dn" if usd < 0 else "mut"
        return f'<span class="{cls}">{usd * fx:+,.0f}원</span> <span class="mut">(${usd:+.2f})</span>'

    def when(ts: str) -> str:
        return e(ts[5:16].replace("T", " "))

    out = [f"<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta http-equiv=refresh content=60><meta name=referrer content=no-referrer><title>autostock</title>"
           f"<style>{CSS}</style><main><h1>autostock · {e(cfg.bull)}/{e(cfg.bear)}</h1><nav>"]
    for m, label in MODES.items():
        on = " class=on" if m == mode else ""
        out.append(f"<a{on} href='/?k={e(token)}&mode={m}'>{label}{' ●' if m == cfg.mode else ''}</a>")
    out.append("</nav>")

    if not state and not events:
        out.append("<div class=card>아직 기록이 없습니다. 이 모드로 장이 열린 적이 없습니다.</div>")
    if state:
        s = state
        out.append(f"<h2>오늘 ({e(s.get('date') or '-')}, 미국 동부 기준)</h2><div class='card grid'>"
                   f"<div><div class=k>실현손익</div><div class=v>{money(s['realized_usd'])}</div></div>"
                   f"<div><div class=k>거래</div><div class=v>{s['trades']}회 <span class=mut>승 {s['wins']} · 패 {s['losses']}</span></div></div>"
                   f"<div><div class=k>목표 / 손실한도</div><div class=v>+{cfg.daily_target_krw:,.0f} / -{cfg.daily_max_loss_krw:,.0f}</div></div>"
                   f"<div><div class=k>상태</div><div class=v>{e(s['halted']) if s['halted'] else '매매 가능'}</div></div></div>")
        o = s.get("open")
        out.append("<h2>보유 포지션</h2><div class=card>")
        if o:
            out.append(f"<b>{e(o['symbol'])}</b> {o['qty']}주 · 진입 ${o['entry_price']:.2f} ({when(o['entry_ts'])} ET) · "
                       f"손절 -{o['stop_pct']:.1f}% / 익절 +{o['take_pct']:.1f}%")
        else:
            out.append("<span class=mut>없음</span>")
        out.append("</div>")

    sells = [x for x in events if x.get("kind") == "sell"]
    if sells:
        days = defaultdict(lambda: [0.0, 0, 0])
        for x in sells:
            d = days[x["ts"][:10]]
            d[0] += x.get("pnl_usd", 0)
            d[1] += 1
            d[2] += x.get("pnl_usd", 0) >= 0
        total = sum(d[0] for d in days.values())
        out.append(f"<h2>일별 손익 · 누적 {money(total)}</h2><div class='card scroll'><table>"
                   "<tr><th>날짜</th><th class=r>손익</th><th class=r>청산</th><th class=r>승률</th></tr>")
        for day in sorted(days, reverse=True)[:60]:
            p, n, w = days[day]
            out.append(f"<tr><td>{e(day)}</td><td class=r>{money(p)}</td><td class=r>{n}</td><td class=r>{w / n * 100:.0f}%</td></tr>")
        out.append("</table></div>")

    trades = [x for x in events if x.get("kind") in ("buy", "sell")][-40:][::-1]
    if trades:
        out.append("<h2>최근 체결</h2><div class='card scroll'><table><tr><th>시각(ET)</th><th>구분</th><th>종목</th>"
                   "<th class=r>수량</th><th class=r>가격</th><th class=r>손익</th><th>사유</th></tr>")
        for x in trades:
            buy = x["kind"] == "buy"
            pnl = "" if buy else money(x.get("pnl_usd", 0))
            out.append(f"<tr><td>{when(x['ts'])}</td><td><span class=tag>{'매수' if buy else '매도'}</span></td>"
                       f"<td>{e(str(x.get('symbol')))}</td><td class=r>{x.get('qty')}</td><td class=r>${x.get('price', 0):.2f}</td>"
                       f"<td class=r>{pnl}</td><td class=wrap>{e(str(x.get('reason', '')))}</td></tr>")
        out.append("</table></div>")

    decisions = [x for x in events if x.get("kind") == "decision"][-30:][::-1]
    if decisions:
        out.append("<h2>최근 AI 판단</h2><div class='card scroll'><table><tr><th>시각(ET)</th><th>판단</th>"
                   "<th class=r>확신</th><th>근거</th></tr>")
        for x in decisions:
            act = f"{x.get('action')} {x.get('symbol') or ''}".strip()
            out.append(f"<tr><td>{when(x['ts'])}</td><td><span class=tag>{e(act)}</span></td>"
                       f"<td class=r>{x.get('confidence', 0):.2f}</td><td class=wrap>{e(str(x.get('reason', '')))}</td></tr>")
        out.append("</table></div>")

    out.append(f"<footer>● 현재 실행 중인 모드 · 60초마다 자동 새로고침 · 환율 {fx:,.0f}원 기준 환산 · 수수료 편도 {cfg.fee_pct}% 반영</footer></main>")
    return "".join(out)


def make_handler(token: str):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path != "/" or not hmac.compare_digest(q.get("k", [""])[0], token):
                self.send_error(404)
                return
            cfg = config.load()
            mode = q.get("mode", [cfg.mode])[0]
            if mode not in MODES:
                mode = "paper"
            body = render(cfg, mode, token).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):       # 주소에 토큰이 있으므로 접근 로그를 남기지 않는다
            pass
    return H


def main() -> int:
    config.load()
    token = os.getenv("WEB_TOKEN", "").strip()
    if len(token) < 16:
        print("WEB_TOKEN 이 없습니다. './bot web' 으로 설정하세요.")
        return 2
    port = int(os.getenv("WEB_PORT") or 8080)
    print(f"결과 페이지: 포트 {port}")
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(token)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
