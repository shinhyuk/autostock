"""읽기 전용 결과 페이지. 봇과 별도 프로세스로 돌며 data/ 의 상태·기록 파일만 읽는다.

    python -m autostock.web        # http://<서버IP>:8080/?k=<WEB_TOKEN>

주소의 k 값(.env 의 WEB_TOKEN)이 맞아야 열린다. 주문 기능은 없고, 바꿀 수 있는 설정은 실계좌 장외 거래 켜기/끄기 하나뿐이다.
"""
from __future__ import annotations

import hmac
import html
import json
import os
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from . import config, extbox, market_hours

MODES = {"paper": "가상매매", "kis-demo": "모의투자", "live": "실계좌"}
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
ACTION = {"BUY": "매수", "SELL": "청산", "HOLD": "관망", "AGREE": "AI 동의", "DISAGREE": "AI 반대"}
CSS = """
:root{--bg:#f4f5f7;--card:#fff;--fg:#14161a;--mut:#667085;--line:#e4e7ec;--up:#d92d20;--dn:#1d4ed8;--acc:#111827;--ok:#16a34a;--warn:#d97706;--track:#eceef2;--vwap:#7c3aed;--noise:#0e7490}
@media(prefers-color-scheme:dark){:root{--bg:#0e1014;--card:#171a20;--fg:#eceef2;--mut:#98a2b3;--line:#272b34;--up:#ff6b5e;--dn:#6ea8ff;--acc:#eceef2;--ok:#4ade80;--warn:#fbbf24;--track:#22262e;--vwap:#a78bfa;--noise:#22d3ee}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;-webkit-text-size-adjust:100%}
main{max-width:720px;margin:0 auto;padding:14px 14px 40px}
header{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:2px 0 12px}
h1{font-size:17px;margin:0}h2{font-size:13px;color:var(--mut);margin:24px 2px 8px;font-weight:600;letter-spacing:.02em}
nav{display:flex;gap:6px;margin-bottom:12px}nav a{flex:1;text-align:center;padding:8px 2px;white-space:nowrap;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--mut);text-decoration:none;font-size:13.5px}
nav a.on{background:var(--acc);color:var(--bg);border-color:var(--acc);font-weight:700}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card);white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--up)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.note{font-size:13px;color:var(--mut);margin-top:8px}.card.note{margin:0 0 10px}.note a{color:var(--fg)}
.hero .k{font-size:13px;color:var(--mut)}.hero .big{font-size:38px;font-weight:800;line-height:1.15;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.hero .sub{font-size:14px;color:var(--mut);font-variant-numeric:tabular-nums}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--mut)}
.meter{position:relative;height:10px;border-radius:5px;background:var(--track);margin:18px 0 6px}
.meter i{position:absolute;top:0;bottom:0;border-radius:5px}.meter b{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--mut)}
.ends{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}
.stats .k{font-size:12px;color:var(--mut)}.stats .v{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}
.pos{display:flex;justify-content:space-between;align-items:baseline;gap:10px}.pos .sym{font-size:22px;font-weight:800}
.kv{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 14px;margin-top:12px;font-size:14px;font-variant-numeric:tabular-nums}.kv span{color:var(--mut)}
.feed{padding:0}.row{display:grid;grid-template-columns:52px 1fr;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line)}.row:last-child{border-bottom:0}
.row .t{font-size:13px;color:var(--mut);font-variant-numeric:tabular-nums;padding-top:2px}.row .h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-weight:700;font-variant-numeric:tabular-nums}.row .h>span:last-child{white-space:nowrap;flex:none}
.row .r{font-size:13px;color:var(--mut);margin-top:2px;overflow-wrap:anywhere}
.tag{font-size:12px;font-weight:700;padding:2px 8px;border-radius:6px;border:1px solid var(--line)}.tag.buy{border-color:var(--up);color:var(--up)}.tag.sell{border-color:var(--dn);color:var(--dn)}
table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:9px 6px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px}td.r,th.r{text-align:right}tr:last-child td{border-bottom:0}
.seg{display:flex;gap:6px;align-items:center;margin-bottom:8px}.seg button{font:inherit;font-size:13px;padding:5px 12px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--mut);cursor:pointer}
.seg button.on{background:var(--acc);color:var(--bg);border-color:var(--acc);font-weight:700}
.lg{margin-left:auto;font-size:12px;color:var(--mut);display:flex;align-items:center;gap:4px}.lg i{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;margin-left:6px}
.lg i.b{border-bottom:9px solid var(--up)}.lg i.s{border-top:9px solid var(--dn)}
#chart,#bc{width:100%;height:360px;display:block;touch-action:none;cursor:grab}
#tip{display:none;position:absolute;top:0;pointer-events:none;background:var(--acc);color:var(--bg);font-size:12px;padding:5px 8px;border-radius:8px;white-space:nowrap;font-variant-numeric:tabular-nums}
.sp{flex:1}.seg{flex-wrap:wrap}.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--mut);margin:2px 0 6px}
.legend span{display:inline-flex;align-items:center;gap:5px}.legend i{display:inline-block}
.lg-up{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:9px solid var(--up)}
.lg-dn{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:9px solid var(--dn)}
.lg-line{width:16px;height:0;border-top:2px solid}.lg-line.vwap{border-color:var(--vwap)}.lg-line.rng{border-top-style:dashed;border-color:var(--warn)}
.lg-band{width:14px;height:10px;border-radius:2px}.lg-band.bl{background:var(--up);opacity:.3}.lg-band.bs{background:var(--dn);opacity:.3}
.lg-line.bx{border-top-style:dotted;border-color:var(--mut)}.lg-line.nz{border-top-style:dashed;border-color:var(--noise)}
.lg-line.stp{border-top-style:dashed;border-color:var(--dn)}.lg-line.tkp{border-top-style:dashed;border-color:var(--up)}
.big2{font-size:26px;font-weight:800;line-height:1.25;margin:2px 0}.sub{font-size:14px;color:var(--mut);font-variant-numeric:tabular-nums}
.plab{display:flex;justify-content:space-between;gap:8px;margin-top:14px;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}
.pbar{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:4px 0 2px;background:var(--track)}.pbar i{display:block}.pbar .u{background:var(--up)}.pbar .d{background:var(--dn)}
.verdict{margin-top:14px;padding:12px;border-radius:10px;border:1.5px solid var(--line)}.verdict.vu{border-color:var(--up)}.verdict.vd{border-color:var(--dn)}.verdict b{display:block;font-size:16px;margin-bottom:2px}.verdict.vu b{color:var(--up)}.verdict.vd b{color:var(--dn)}
table.plan{margin-top:10px}table.plan td,table.plan th{padding:7px 4px}
#bc{width:100%;height:380px;display:block;touch-action:none;cursor:grab}.zone{margin-top:8px;padding:8px 10px;border-radius:8px;font-size:13.5px;font-variant-numeric:tabular-nums}.zone.zb{border-left:4px solid var(--ok);background:color-mix(in srgb,var(--ok) 10%,transparent)}.zone.zs{border-left:4px solid var(--warn);background:color-mix(in srgb,var(--warn) 10%,transparent)}.lgs,.lgr,.lgb{display:inline-block;width:14px;border-top:2px dashed;margin-right:5px;vertical-align:middle}.lgs{border-color:var(--warn)}.lgr{border-color:var(--ok)}.lgb{border-color:var(--warn);border-top-style:dotted}.brow{position:relative;display:flex;justify-content:space-between;padding:4px 8px;font-size:13.5px;font-variant-numeric:tabular-nums}.brow i{position:absolute;right:0;top:2px;bottom:2px;opacity:.15}.brow.ask span:first-child{color:var(--dn)}.brow.ask i{background:var(--dn)}.brow.bid span:first-child{color:var(--up)}.brow.bid i{background:var(--up)}.brow span{position:relative}.bhead{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);padding:0 8px 4px}.bmid{text-align:center;font-size:12px;color:var(--mut);padding:4px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.tgl{font:inherit;font-weight:700;padding:8px 18px;border-radius:10px;border:1px solid var(--acc);background:var(--acc);color:var(--bg);cursor:pointer}tr.cur td{font-weight:700}details summary{cursor:pointer;font-size:13px;color:var(--mut);margin-top:16px}small{font-size:11.5px}h3{font-size:13px;color:var(--mut);margin:18px 0 4px;font-weight:600}.seg .mutt{font-size:13px;margin-right:2px}.zb{font:inherit;font-size:13px;padding:3px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--mut);cursor:pointer}
.tu{color:var(--up)}.td{color:var(--dn)}.mutt{color:var(--mut)}.warnt{color:var(--warn)}.pad{padding:0 4px}
.hold{margin-bottom:10px}.pnlbig{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}.pnlbig small{font-size:13px}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:5px 14px;margin:12px 0 0;font-size:14px;font-variant-numeric:tabular-nums}
dl.kv dt{color:var(--mut)}dl.kv dd{margin:0;text-align:right}
.actlog{max-height:420px;overflow-y:auto}.actlog .row{padding:8px 14px}.actlog .a{font-size:13.5px;overflow-wrap:anywhere}
.trip .h{flex-wrap:wrap}.trip .h>span:first-child{white-space:nowrap}
.spans{display:flex;gap:4px;margin:0 0 8px}.spans button{flex:1;font:inherit;font-size:12px;padding:4px 0;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--mut);cursor:pointer}
.spans button.on{background:var(--acc);color:var(--bg);border-color:var(--acc);font-weight:700}
.trip .leg{font-size:13px;margin-top:3px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.trip .leg b{font-size:12px;margin-right:4px}
.stats4{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:10px;padding-top:12px;border-top:1px solid var(--line)}
.stats4 .k{font-size:12px;color:var(--mut)}.stats4 .v{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}
#tip .tu{color:#ff9b91}#tip .td{color:#9cc2ff}
footer{color:var(--mut);font-size:12px;margin:20px 2px}

/* ── 정리된 디자인 (공통) */
:root{--r:16px}
body{background:var(--bg);letter-spacing:-.005em}
main{padding:12px 14px 48px}
header{margin:4px 2px 12px}h1{font-size:18px;font-weight:800;letter-spacing:-.02em}h1 small{font-size:12px;font-weight:600;color:var(--mut);margin-left:8px;letter-spacing:0}
h2{font-size:12px;text-transform:none;color:var(--mut);margin:22px 4px 8px;font-weight:700;letter-spacing:.03em;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.hsub{font-weight:500;letter-spacing:0;font-size:12px}
nav{gap:4px;padding:4px;background:var(--track);border-radius:12px;margin-bottom:14px}nav a{border:0;background:transparent;padding:7px 2px;border-radius:9px;font-weight:600}
nav a.on{background:var(--card);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.card{border:0;border-radius:var(--r);box-shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.04)}
@media(prefers-color-scheme:dark){.card{box-shadow:none;border:1px solid var(--line)}}
.card.empty{color:var(--mut);text-align:center;padding:18px}
.hero{margin-top:10px}.hero .big{font-size:34px}.hero .sub{margin-top:2px}
.grid4{grid-template-columns:repeat(4,1fr);gap:8px}.grid4 dt{font-size:11.5px;color:var(--mut)}.grid4 dd{margin:2px 0 0;font-weight:700;font-size:14px}
@media(max-width:420px){.grid4{grid-template-columns:repeat(3,1fr)}}
.pos .sym{font-size:20px}
.trip .tmain{min-width:0}.trip .tr{display:flex;flex-direction:column;align-items:flex-end;line-height:1.25}.trip .tr small{font-weight:600}
.row{padding:11px 14px}.row .t{font-size:12px;line-height:1.35}.row .a{font-size:13.5px}
.more{padding:4px 14px}.more details{border-bottom:1px solid var(--line)}.more details:last-child{border-bottom:0}
.more summary{list-style:none;padding:13px 2px;margin:0;font-size:14px;font-weight:600;color:var(--fg);display:flex;justify-content:space-between}
.more summary::after{content:'＋';color:var(--mut)}.more details[open] summary::after{content:'－'}.more summary::-webkit-details-marker{display:none}
.more .feed .row{padding:8px 2px}.more table{margin-bottom:8px}.more .note{margin:0 2px 10px}
.legend{margin:8px 0 0;gap:4px 10px}.lg-line.fcl{border-color:var(--vwap);border-top-width:3px}.lg-line.okl{border-color:var(--ok)}.lg-line.wrl{border-color:var(--warn)}.lg-line.pdl{border-color:var(--vwap);border-top-style:dashed;opacity:.7}
.lgdot{width:7px;height:7px;border-radius:50%}.lgdot.okd{background:var(--ok)}.lgdot.wrd{background:var(--warn)}
.note.small{font-size:12px}.seg button{border-radius:999px;padding:4px 11px}.zb{border-radius:999px}
footer{font-size:12px;color:var(--mut);text-align:center;margin-top:20px}
.acct .big{font-size:30px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chip{background:var(--track);border-radius:999px;padding:4px 10px;font-size:12.5px;font-variant-numeric:tabular-nums}.chip b{font-weight:700}
.trow{display:flex;justify-content:space-between;align-items:center;gap:10px}.trow .tgl{padding:6px 14px;font-size:13px}
"""


from .webchart import CHART_JS  # noqa: E402
from .boardjs import BOARD_JS  # noqa: E402
from .chartjs import CHART_CORE  # noqa: E402
from . import board  # noqa: E402
from . import webdata  # noqa: E402

STORE: webdata.BarStore | None = None


def _read(cfg, mode):
    return webdata.read(cfg, mode)


def _kst(ts: str, fmt: str = "%H:%M") -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(KST).strftime(fmt)
    except ValueError:
        return ts[11:16]


def _next_open(cfg, now: datetime) -> str:
    market_hours.ENABLED = cfg.sessions
    o = market_hours.next_open(now)
    if o is None:
        return "?"
    o = o.astimezone(KST)
    return f"{'월화수목금토일'[o.weekday()]}요일 {o:%H:%M}"


def _nav(token: str, mode: str, running) -> str:
    e = html.escape
    tabs = [("board", "차트")] + [(m, name + (" ●" if m in running else "")) for m, name in MODES.items()] + [("ext", "시간외")]
    return "".join(f"<a{' class=on' if m == mode else ''} href='/?k={e(token)}&mode={m}'>{e(n)}</a>" for m, n in tabs)


KIND_KO = {"fade": "개장 되돌림", "orb": "돌파", "box": "박스권"}


def _signal_book(cfg, mode: str) -> str:
    """신호 장부: 산 신호와 걸러서 안 산 신호의 '샀다면' 결과 비교."""
    from . import signals as sigbook
    e = html.escape
    cls = lambda v: "up" if v > 0 else "dn" if v < 0 else "mut"
    rs = sigbook.rows(cfg, mode)
    if not rs:
        return ""
    tbl = ""
    for x in sigbook.summary(rs):
        avg = "" if x["avg"] is None else f"{x['avg']:+.2f}%"
        win = "" if x["win"] is None else f"{x['win'] * 100:.0f}%"
        tbl += (f"<tr><td>{KIND_KO.get(x['kind'], x['kind'])}</td><td>{'산 것' if x['taken'] else '거른 것'}</td>"
                f"<td class=r>{x['n']} ({x['done']} 결과)</td><td class='r {cls(x['avg'] or 0)}'>{avg}</td><td class=r>{win}</td></tr>")
    recent = "".join(
        f"<div class=row><div class=t>{_kst(r['ts'], '%m-%d %H:%M')}</div><div class=a>"
        f"<span class='tag {'buy' if r.get('taken') else ''}'>{'샀음' if r.get('taken') else '거름'}</span> "
        f"{KIND_KO.get(r['kind'], r['kind'])} {e(r['symbol'])}"
        + (f" · {e(r.get('why', ''))}" if r.get("why") else "")
        + (f" · 샀다면 <b class={cls(r['res']['pct'])}>{r['res']['pct']:+.2f}%</b> ({e(r['res']['exit'])})" if r.get("res") else " · 결과 대기")
        + "</div></div>" for r in rs[-15:][::-1])
    return ("<details><summary>신호 장부 (산 것 vs 거른 것)</summary><table><tr><th>종류</th><th></th><th class=r>신호</th>"
            "<th class=r>샀다면 평균</th><th class=r>승률</th></tr>" + tbl + "</table>"
            "<div class=note>걸러서 안 산 신호도 '그때 샀다면' 결과(비용 0.6% 뺌)를 계산해, 필터가 실제로 손실을 막았는지 확인합니다.</div>"
            f"<div class=feed>{recent}</div></details>")


def cfg_paper():
    from . import config as _c
    return _c.load("paper")


def render(cfg, mode: str, token: str, now: datetime | None = None) -> str:
    e = html.escape
    now = now or datetime.now(KST)
    state, events, live = _read(cfg, mode)
    fx = cfg.usdkrw
    if mode != "paper":                               # 실계좌·모의투자: 증권사가 쓰는 오늘 환율로 원화 환산
        fx = (((webdata._acct_cache.get(mode) or {}).get("summary") or {}).get("usd_rate")) or fx
    real = webdata._realized_cache.get(mode) if mode != "paper" else None
    real = real if real and not real.get("error") and real.get("rows") is not None else None

    def won(v: float, sign: bool = True) -> str:
        return f"{v * fx:+,.0f}원" if sign else f"{v * fx:,.0f}원"

    def usd(v: float) -> str:
        return f"${v:,.2f}" if v is not None else "-"

    def cls(v) -> str:
        return "mut" if v is None else "up" if v > 0 else "dn" if v < 0 else "mut"

    def arrow(v) -> str:
        return "" if v is None else "▲" if v > 0 else "▼" if v < 0 else ""

    # ── 상태 표시
    running = mode in cfg.modes
    age = None
    if live:
        try:
            age = (now - datetime.fromisoformat(live["ts"])).total_seconds()
        except (ValueError, KeyError):
            pass
    if not running:
        dot, label = "", "실행 안 함"
    elif age is None or age > 150:
        dot, label = "bad", "봇 응답 없음"
    elif live["status"] == "running":
        dot, label = "ok", "매매 중"
    elif live["status"] == "halted":
        dot, label = "warn", "오늘 매매 종료"
    elif live["status"] == "error":
        dot, label = "bad", "오류 발생"
    else:
        dot, label = "", f"장 닫힘 · {_next_open(cfg, now)} 개장"

    out = [f"<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta http-equiv=refresh content=120><meta name=referrer content=no-referrer><title>autostock</title>"
           f"<style>{CSS}</style><main><header><h1>{e(' · '.join(cfg.symbols))}<small>{MODES[mode]}</small></h1>"
           f"<span class=pill><span class='dot {dot}'></span>{e(label)}</span></header><nav>"]
    out.append(_nav(token, mode, cfg.modes) + "</nav>")
    if not running:
        out.append(f"<div class='card note'>지금 실행 중이 아니라 지난 기록만 보입니다.</div>")

    # ── 총액: 실계좌·모의투자는 증권사 총 평가금액, 가상매매는 봇 장부 자산
    s = state or {"date": "", "realized_usd": 0.0, "trades": 0, "wins": 0, "losses": 0, "halted": "", "open": None, "history": []}
    o = s.get("open")
    unreal = (live or {}).get("unrealized_usd") if o and age is not None and age <= 150 else None
    led = (live or {}).get("ledger")
    if not led:
        try:
            with open(os.path.join(cfg.data_dir, f"ledger_{mode}.json"), encoding="utf-8") as f:
                led = json.load(f)
        except (FileNotFoundError, ValueError):
            led = None
    equity = cfg.capital_usd + (led["realized_usd"] if led else 0)
    acct_total = ((webdata._acct_cache.get(mode) or {}).get("summary") or {}).get("total_krw") if mode != "paper" else None
    total_usd = acct_total / fx if acct_total else equity          # '총액 대비' 계산 기준
    if mode != "paper":
        out.append(_account_card(cfg, mode))
        if mode == "live":
            out.append(_ext_toggle(cfg, mode, token))
    elif cfg.news_pick:
        out.append(_news_card(cfg))
    tests = [x for x in events if x.get("kind") == "ordertest"]
    if mode != "paper" and tests and not tests[-1].get("ok"):
        out.append(_test_status(cfg, mode, events, live))          # 주문 테스트가 실패했을 때만 위에 크게

    # ── 오늘 손익
    total = s["realized_usd"] + (unreal or 0)
    target, limit = cfg.target_usd, cfg.max_loss_usd
    pct = total / cfg.capital_usd * 100 if cfg.capital_usd else 0
    span = target + limit
    zero = limit / span * 100
    pos = min(max((total + limit) / span * 100, 0), 100)
    lo, hi = sorted((zero, pos))
    color = "var(--up)" if total > 0 else "var(--dn)"
    key = s.get("date") or ""
    sname = {"D": "주간거래", "P": "프리마켓", "A": "애프터마켓"}.get(key[-1:], "정규장") if key else ""
    out.append(f"<section class='card hero'><div class=k>{'이번 세션' if len(cfg.sessions) > 1 else '오늘'} 손익"
               f"{' · 평가 포함' if unreal is not None else ''}{' · ' + sname if key else ''}</div>"
               f"<div class='big {cls(total)}'>{arrow(total)} {won(total)}</div>"
               f"<div class=sub>운용금 대비 {pct:+.2f}%{f' · 총액 대비 {total / total_usd * 100:+.2f}%' if mode != 'paper' and total_usd else ''}</div>"
               f"<div class=meter role=img aria-label='손실한도와 목표 사이 현재 위치'><i style='left:{lo:.1f}%;width:{hi - lo:.1f}%;background:{color}'></i>"
               f"<b style='left:{zero:.1f}%'></b></div>"
               f"<div class=ends><span>-{cfg.daily_max_loss_krw / 1e4:,.0f}만</span><span>+{cfg.daily_target_krw / 1e4:,.0f}만</span></div>"
               f"<div class=stats><div><div class=k>거래</div><div class=v>{s['trades']}회</div></div>"
               f"<div><div class=k>승 / 패</div><div class=v>{s['wins']} / {s['losses']}</div></div>"
               f"<div><div class=k>{'봇 운용 자산' if mode != 'paper' else '현재 자산'}</div><div class=v>{equity * fx / 1e4:,.1f}만</div></div></div>"
               + (f"<div class=note>누적 실현 <b class='{cls(led['realized_usd'])}'>{won(led['realized_usd'])}</b> · {led.get('trades', 0)}건"
                  f" · {_kst(led['start'], '%m-%d')}부터</div>" if led else "")
               + (f"<div class='note warnt'>멈춤: {e(s['halted'])}</div>" if s["halted"] else "") + "</section>")

    # ── 보유 종목
    acct = webdata.account(cfg, mode, state, live)
    trips, _open_lots = webdata.round_trips(events, cfg.fee_pct)
    out.append("<h2>보유</h2>")
    if acct.get("loading"):
        out.append("<section class='card note'>증권사 잔고를 불러오는 중입니다 (최대 30초).</section>")
    elif acct.get("error"):
        out.append(f"<section class='card note'>잔고 조회 실패: {e(acct['error'])}</section>")
    elif not acct["holdings"]:
        out.append("<section class='card empty'>보유 종목 없음 · 현금 대기</section>")
    for h in acct.get("holdings", []):
        q, avg, last = h["qty"], h["avg"], h.get("last")
        if o and h["symbol"] == o.get("symbol") and not last:
            last = (live or {}).get("last")
        cost = avg * q
        value = h.get("value") or (last * q if last else None)
        pnl = h.get("pnl") if h.get("pnl") is not None else (value - cost if value else None)
        if h.get("bot") and o and unreal is not None and mode == "paper":
            pnl = unreal
        ppct = pnl / cost * 100 if pnl is not None and cost else None
        head = (f"<div class='{cls(pnl)} pnlbig'>{arrow(pnl)} {won(pnl)} <small>{ppct:+.2f}%</small></div>"
                if pnl is not None else "<div class=mut>평가 중</div>")
        rows = [("수량", f"{q:,}주"), ("평단", usd(avg)), ("현재가", usd(last) if last else "-"),
                ("평가금액", won(value, False) if value else "-")]
        if h.get("bot") and o and h["symbol"] == o["symbol"]:
            ent = o["entry_price"]
            rows += [("손절", usd(ent * (1 - o["stop_pct"] / 100))), ("익절", usd(ent * (1 + o["take_pct"] / 100)))]
        tag = "" if h.get("bot") else " <span class='tag mutt'>봇 관리 밖</span>"
        out.append(f"<section class='card hold'><div class=pos><div class=sym>{e(h['symbol'])}{tag}</div>{head}</div>"
                   "<dl class='kv grid4'>" + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows) + "</dl></section>")
    if acct.get("mismatch"):
        out.append(f"<div class='note pad warnt'>⚠ {e(acct['mismatch'])}</div>")

    # ── 차트
    held_sym = o["symbol"] if o else cfg.bull
    out.append("<h2>차트</h2><section class=card><div class=seg>"
               + "".join(f"<button data-sym='{e(s_)}'{' class=on' if s_ == held_sym else ''}>{e(s_)}</button>" for s_ in cfg.symbols)
               + "<span class=sp></span>"
               + "".join(f"<button data-span='{v}'>{t}</button>" for v, t in ((60, "1h"), (120, "2h"), (240, "4h"), (0, "전체")))
               + "<button data-czoom=out class=zb>－</button><button data-czoom=in class=zb>＋</button></div>"
               f"<canvas id=chart data-mode='{e(mode)}' data-sym='{e(held_sym)}'></canvas>"
               "<div class=legend><span><i class='lg-up'></i>매수</span><span><i class='lg-dn'></i>매도</span>"
               "<span><i class='lg-line vwap'></i>VWAP</span><span><i class='lg-line fcl'></i>예상</span>"
               "<span><i class='lg-line pdl'></i>지난 예측</span><span><i class='lgdot okd'></i>맞음</span><span><i class='lgdot wrd'></i>틀림</span></div>"
               "<div id=cmsg class='note small'>불러오는 중…</div></section>")

    # ── 거래 내역: 각 거래의 손익과 총액 대비 %
    if trips:
        done = [t for t in trips if t["pnl"] is not None]
        today = [t for t in trips if (s.get("date") or "")[:10] and t["sell_ts"][:10] == (s.get("date") or "")[:10]]
        cum = sum(t["pnl"] for t in done)
        if real:                                      # 합계는 증권사가 계산한 실현손익 (수수료·환율이 실제와 같음)
            rk = real["total_krw"]
            out.append(f"<h2>거래 <span class=hsub>오늘 {len(today)} · 전체 {len(trips)} · 실현손익(증권사) "
                       f"<b class={cls(rk)}>{rk:+,.0f}원</b> (총액 대비 {rk / (total_usd * fx) * 100:+.2f}%)</span></h2><section class='card feed'>")
        else:
            out.append(f"<h2>거래 <span class=hsub>오늘 {len(today)} · 전체 {len(trips)} · 합계 "
                       f"<b class={cls(cum)}>{won(cum)}</b> (총액 대비 {cum / total_usd * 100:+.2f}%)</span></h2><section class='card feed'>")
        for t in trips[-30:][::-1]:
            p = t["pnl"]
            tp = p / total_usd * 100 if p is not None and total_usd else None
            right = (f"<span class='{cls(p)}'>{won(p)}</span><small class='{cls(p)}'>{t['pct']:+.2f}% · 총액 {tp:+.2f}%</small>"
                     if p is not None and t["pct"] is not None else "")
            legs = (f"{usd(t['buy_px'])} → {usd(t['sell_px'])}" if t["buy_px"] else f"매도 {usd(t['sell_px'])}")
            held = f" · {t['hold_min']:.0f}분" if t["hold_min"] is not None else ""
            out.append(f"<div class='row trip'><div class=t>{_kst(t['sell_ts'], '%m-%d')}<br>{_kst(t['sell_ts'])}</div>"
                       f"<div class=tmain><div class=h><span>{e(t['symbol'])} <small class=mut>{t['qty']:,}주</small></span><span class=tr>{right}</span></div>"
                       f"<div class=r>{legs}{held} · {e(_short_reason(t['sell_reason']))}</div></div></div>")
        out.append("</section>")
        if done:
            pts, c = [], 0.0
            for t in done:
                c += t["pnl"]
                pts.append(c)
            wins = [t for t in done if t["pnl"] > 0]
            out.append(f"<section class=card style='margin-top:10px'>{_equity_svg(pts, fx)}"
                       f"<div class=stats4><div><div class=k>승률</div><div class=v>{len(wins) / len(done) * 100:.0f}%</div></div>"
                       f"<div><div class=k>평균 이익</div><div class='v up'>{won(sum(t['pnl'] for t in wins) / len(wins)) if wins else '-'}</div></div>"
                       f"<div><div class=k>평균 손실</div><div class='v dn'>{won(sum(t['pnl'] for t in done if t['pnl'] <= 0) / max(1, len(done) - len(wins))) if len(done) > len(wins) else '-'}</div></div>"
                       f"<div><div class=k>수수료</div><div class=v>{won(sum(t['fees'] for t in done), False)}</div></div></div></section>")

    # ── 접어 둔 자세한 정보
    out.append("<h2>자세히</h2><section class='card more'>")
    orb = (live or {}).get("orb") if cfg.strategy == "orb" else None
    out.append(f"<details><summary>전략 · 지금 상태</summary><div class=note>{e((orb or {}).get('status') or '-')}</div>"
               f"<div class=note>{_strategy_text(cfg)}</div></details>")
    acts = webdata.activity(cfg, mode, 40)
    if acts:
        rows = "".join(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div class=a>{e(x.get('msg', ''))}</div></div>" for x in acts[::-1])
        out.append(f"<details><summary>활동 로그 <span class=mut>· {_kst(acts[-1]['ts'])}</span></summary><div class='feed actlog'>{rows}</div></details>")
    if trips and len(cfg.sessions) > 1:
        by = defaultdict(lambda: [0.0, 0, 0])
        for t in trips:
            if t["pnl"] is not None:
                g = by[market_hours.session_of(t["buy_ts"] or t["sell_ts"])]
                g[0] += t["pnl"]
                g[1] += 1
                g[2] += t["pnl"] > 0
        out.append("<details><summary>시간대별</summary><table><tr><th>시간대</th><th class=r>손익</th><th class=r>거래</th><th class=r>승률</th></tr>"
                   + "".join(f"<tr><td>{market_hours.LABEL[x]}</td><td class='r {cls(by[x][0])}'>{won(by[x][0])}</td><td class=r>{by[x][1]}</td>"
                             f"<td class=r>{by[x][2] / by[x][1] * 100:.0f}%</td></tr>" for x in ("regular", "pre", "post", "day") if x in by)
                   + "</table></details>")
    if real and real["rows"]:
        kd = defaultdict(lambda: [0.0, 0, defaultdict(float)])
        for r in real["rows"]:
            d = kd[r["day"]]
            d[0] += r["krw"]
            d[1] += 1
            d[2][r["symbol"]] += r["krw"]
        out.append("<details open><summary>일별 실현손익 (증권사, 미국 날짜)</summary><table><tr><th>날짜</th><th class=r>손익</th><th class=r>총액 대비</th><th>종목별</th></tr>"
                   + "".join(f"<tr><td>{e(d[4:6] + '-' + d[6:8])}</td><td class='r {cls(kd[d][0])}'>{kd[d][0]:+,.0f}원</td>"
                             f"<td class='r {cls(kd[d][0])}'>{kd[d][0] / (total_usd * fx) * 100:+.2f}%</td>"
                             f"<td class=mutt style='font-size:12.5px'>{' · '.join(f'{k} {v:+,.0f}' for k, v in kd[d][2].items())}</td></tr>"
                             for d in sorted(kd, reverse=True))
                   + "</table><div class=note>한국투자증권 '실현손익'과 같은 값입니다 (실제 수수료·환율). 아래 거래별 금액은 봇 기록으로 계산해 조금 다를 수 있습니다.</div></details>")
    elif trips:
        days = defaultdict(lambda: [0.0, 0, 0])
        for t in trips:
            if t["pnl"] is not None:
                d = days[t["sell_ts"][:10]]
                d[0] += t["pnl"]
                d[1] += 1
                d[2] += t["pnl"] > 0
        out.append("<details><summary>일별</summary><table><tr><th>날짜</th><th class=r>손익</th><th class=r>총액 대비</th><th class=r>거래</th><th class=r>승률</th></tr>"
                   + "".join(f"<tr><td>{e(d[5:])}</td><td class='r {cls(days[d][0])}'>{won(days[d][0])}</td>"
                             f"<td class='r {cls(days[d][0])}'>{days[d][0] / total_usd * 100:+.2f}%</td><td class=r>{days[d][1]}</td>"
                             f"<td class=r>{days[d][2] / days[d][1] * 100:.0f}%</td></tr>" for d in sorted(days, reverse=True)[:60])
                   + "</table></details>")
    out.append(_signal_book(cfg, mode))
    decisions = [x for x in events if x.get("kind") == "decision"][-25:][::-1]
    if decisions:
        rows = "".join(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div><span class='tag {'buy' if x.get('action') == 'BUY' else 'sell' if x.get('action') in ('SELL', 'DISAGREE') else ''}'>"
                       f"{ACTION.get(x.get('action', ''), e(str(x.get('action', ''))))}</span> <span class=a>{e(str(x.get('reason', '')))}</span></div></div>" for x in decisions)
        out.append(f"<details><summary>AI 판단 기록</summary><div class=feed>{rows}</div></details>")
    system = [x for x in events if x.get("kind") in ("ordertest", "error")][-6:][::-1]
    if system or mode == "live":
        rows = f"<div class=row><div class=t>호가 기록</div><div class=a>{e(webdata.book_summary(cfg_paper()))}</div></div>" + "".join(f"<div class=row><div class=t>{_kst(x['ts'], '%m-%d %H:%M')}</div><div class=a>"
                       f"{'주문 테스트 ' + ('통과' if x.get('ok') else '실패') if x['kind'] == 'ordertest' else '오류'} · {e(str(x.get('detail', ''))[:160])}</div></div>" for x in system)
        out.append(f"<details><summary>시스템 기록</summary><div class=feed>{rows}</div></details>")
    if mode != "paper" and not (tests and not tests[-1].get("ok")):
        out.append(f"<details><summary>설정 · 주문 테스트</summary>{_test_status(cfg, mode, events, live)}</details>")
    else:
        out.append(f"<details><summary>설정</summary><div class=note>세션 {e(', '.join(market_hours.LABEL.get(x, x) for x in cfg.sessions))} · "
                   f"정규장 밖 전략 {e({'box': '시간외 고정 박스', 'always': '항상 매매', 'ai': 'Claude 판단', 'orb': '없음'}.get(cfg.ext_strategy, '없음'))} · 코드 {e(_code_version())}</div></details>")
    out.append("</section>")
    if not state and not events:
        out.append("<div class='card note' style='margin-top:14px'>아직 기록이 없습니다. 이 모드로 장이 열린 적이 없습니다.</div>")
    out.append(f"<footer>{now:%m-%d %H:%M} · 환율 {fx:,.0f}원 · 수수료 편도 {cfg.fee_pct}%</footer></main>"
               f"{_appv()}<script>{CHART_CORE}</script><script>{CHART_JS}</script>")
    return "".join(out)


def _short_reason(r: str) -> str:
    r = str(r or "")
    for k, v in (("장 마감 전 강제 청산", "마감 정리"), ("손절", "손절"), ("익절", "익절"), ("추적", "추적 청산"), ("반대 방향", "방향 전환"),
                 ("항상 매매", "시간 정리"), ("영역", "노이즈 이탈")):
        if k in r:
            return v if k != "손절" and k != "익절" else r.split("(")[0].strip()[:14]
    return r[:16]


def _strategy_text(cfg) -> str:
    e = html.escape
    parts = [f"<b>돌파</b> 개장 {cfg.orb_minutes}분 범위를 뚫으면 그 방향(엔비디아·SOXX 동조) · 개장 {cfg.orb_window_min}분까지 · 하루 {cfg.orb_max_trades}회 · "
             + ("손절 범위 중간 · " if cfg.orb_stop_mode == "mid" else f"손절 {cfg.orb_stop_pct}% · ") + f"익절 {cfg.orb_take_pct:g}%"
             + (f" · 분할매수 {cfg.scale_in_frac:g}→+{cfg.scale_in_add_pct:g}%" if cfg.scale_in_frac < 1 else "")]
    if cfg.box:
        parts.append(f"<b>박스권</b> 범위 폭 {cfg.box_min_width:g}% 이상, 경계 근처 반등 · " + (f"하루 {cfg.box_max}회" if cfg.box_max else "횟수 제한 없음"))
    if cfg.noise:
        parts.append(f"<b>노이즈</b> 30분마다 {cfg.noise_lookback}일 평균 움직임 밖이면 그 방향")
    if cfg.vol_filter_min:
        parts.append(f"<b>필터</b> 5일 평균 변동폭 {cfg.vol_filter_min:g}% 미만이면 쉼")
    if cfg.risk_per_trade_pct:
        parts.append(f"<b>수량</b> 손절 시 자본 {cfg.risk_per_trade_pct:g}%")
    ext = {"box": "시간외 고정 박스", "always": f"항상 매매 {cfg.fixed_qty or ''}주", "ai": "Claude 판단"}.get(cfg.ext_strategy)
    if ext and len(cfg.sessions) > 1:
        parts.append(f"<b>정규장 밖</b> {e(ext)}")
    return "<br>".join(parts)


def ext_card(adv: dict, cfg) -> str:
    """시간외 탭의 '지금 판단' 카드 (10초마다 /data 로 다시 받아 바꿔 끼운다)."""
    e = html.escape
    x, st, bull, bear = adv["x"], adv.get("stats"), cfg.bull, cfg.bear
    usd = lambda v: f"${v:,.2f}"   # noqa: E731
    sess, out = adv.get("session"), []
    if not sess:
        nxt = adv.get("next")
        when = ""
        if nxt:
            o = nxt[1].astimezone(KST)
            when = f"다음 {extbox.SLABEL[nxt[0]]}: 한국시간 {'월화수목금토일'[o.weekday()]}요일 {o:%H:%M}"
        out.append(f"<div class=big2>지금은 시간외 거래 시간이 아닙니다</div><div class=sub>{e(when)}</div>")
        show = nxt[0] if nxt else "pre"
    else:
        show = sess
        head = f"{extbox.SLABEL[sess]} · 한국시간 {adv['close'].astimezone(KST):%H:%M} 종료"
        if adv.get("stale"):
            out.append(f"<div class=sub>{e(head)}</div><div class=big2>시세가 {adv['age_min']:.0f}분째 멈춰 있습니다</div>"
                       "<div class=sub>거래가 없거나 시세를 받지 못하고 있어 판단하지 않습니다"
                       f"{' · 마지막 ' + usd(adv['last']) if adv.get('last') else ''}</div>")
        elif "zone" not in adv:
            brk = adv.get("last_break")
            why = (f"{datetime.fromtimestamp(brk['ts'], KST):%H:%M} 에 박스({usd(brk['lo'])}~{usd(brk['hi'])})를 "
                   f"{'위' if brk['dir'] == 'up' else '아래'}로 뚫었습니다. 가격이 다시 자리 잡으면 새 박스가 생깁니다." if brk else
                   "위·아래 경계에 각각 2번 이상 닿으며 옆으로 움직이는 구간(45분~3시간)을 찾는 중입니다.")
            out.append(f"<div class=sub>{e(head)}</div><div class=big2>박스 없음 · 기다리기</div>"
                       f"<div class=sub>{e(why)}{' · 현재 ' + usd(adv['last']) if adv.get('last') else ''}</div>")
        else:
            out.append(_ext_box_part(adv, cfg, head))
    # ── 참고: ±폭 확률 (접어 둠)
    ref = []
    if sess and "zone" in adv and not adv.get("stale"):
        b = adv.get("b")
        if b and b["up"] + b["dn"]:
            res = b["up"] + b["dn"]
            pu = b["up"] / res * 100
            half = lambda h: f"{h[0] / sum(h) * 100:.0f}% ({sum(h)}번)" if sum(h) else "사례 없음"   # noqa: E731
            ref.append(f"<div class=plab><span class=tu>▲ +{x:g}% 먼저 {pu:.0f}%</span><span class=td>{100 - pu:.0f}% -{x:g}% 먼저 ▼</span></div>"
                       f"<div class=pbar role=img aria-label='위로 먼저 {pu:.0f}%'><i class=u style='width:{pu:.1f}%'></i><i class=d style='width:{100 - pu:.1f}%'></i></div>"
                       f"<div class=note>과거 {st['days']}일 {extbox.SLABEL[sess]}에서 {e(bull)} 가격이 이 위치에 들어온 {b['n']}번: "
                       f"+{x:g}% 에 먼저 닿음 {b['up']}번, -{x:g}% 에 먼저 닿음 {b['dn']}번, 2시간 안에 둘 다 안 닿음 {b['none']}번. "
                       f"위로 먼저 간 비율: 앞 기간 {half(b['old'])} · 뒤 기간 {half(b['new'])} · {e(adv.get('why', ''))}</div>")
            be = 50 + st["cost"] / (2 * x) * 100
            ref.append(f"<div class=note>±{x:g}% 로 사고팔아 이익이 나려면 맞힐 확률이 {be:.0f}% 를 넘어야 합니다 (수수료·호가 차이 왕복 약 {st['cost']:.1f}%).</div>")
    by = ((st or {}).get("by") or {}).get(show)
    if by:
        ref.append(f"<h3>{extbox.SLABEL[show]} 위치별 (±{x:g}%) · 오른쪽 두 칸은 그 종목을 샀다면 수수료 뺀 1회 평균</h3><table>"
                   f"<tr><th>위치</th><th class=r>▲ 먼저</th><th class=r>사례</th><th class=r>{e(bull)}</th><th class=r>{e(bear)}</th></tr>")
        for z in extbox.ZONES:
            b = by.get(z)
            res = (b["up"] + b["dn"]) if b else 0
            if not res:
                continue
            cur = sess == show and adv.get("zone") == z
            ref.append(f"<tr{' class=cur' if cur else ''}><td>{'● ' if cur else ''}{extbox.ZSHORT[z]}</td>"
                       f"<td class=r>{b['up'] / res * 100:.0f}%</td><td class=r>{res}</td>"
                       f"<td class=r>{b['ev_up']:+.1f}%</td><td class=r>{b['ev_dn']:+.1f}%</td></tr>")
        ref.append("</table>")
    xs = "".join(f"<button data-x='{v:g}'{' class=on' if v == x else ''}>±{v:g}%</button>" for v in extbox.X_CHOICES)
    out.append(f"<details id=ref><summary>참고: 위·아래 어느 쪽에 먼저 닿았나 (±폭 확률)</summary>"
               f"<div class=seg style='margin-top:10px'><span class=mutt>폭</span>{xs}</div>{''.join(ref)}</details>")
    if st:
        out.append(f"<div class=note>과거 자료 {st['since']} ~ {st['until']} (야후 5분봉, 6시간마다 갱신) · 앞·뒤 기간은 {st['split']} 기준 · "
                   f"사례는 그 위치에 새로 들어온 순간만 셈 · {e(bear)} 는 {e(bull)} 반대 방향으로 같은 비율 움직인다고 보고 계산 · "
                   f"수수료 편도 {cfg.fee_pct}% + 호가 차이 편도 {extbox.SLIP_PCT}% 가정</div>")
    elif show == "day":
        out.append("<div class=note>주간거래는 야후에 과거 시세가 없어, 서버가 주간거래 1분봉을 직접 모으는 중입니다. "
                   "며칠 쌓이면 과거 결과가 표시됩니다. 그 전까지는 박스와 권장가만 참고하세요.</div>")
    else:
        out.append("<div class=note>과거 자료를 아직 받지 못했습니다. 서버가 야후 금융에서 받는 중이며, 받으면 과거 결과가 표시됩니다.</div>")
    return "".join(out)


def _ext_box_part(adv: dict, cfg, head: str) -> str:
    """박스 매매 권장: SOXL 이 박스 하단이면 SOXL, 상단이면 SOXS. 매수·매도 목표·손절가."""
    e = html.escape
    bull, bear = cfg.bull, cfg.bear
    usd = lambda v: f"${v:,.2f}"   # noqa: E731
    z, rec, last = adv["zone"], adv.get("rec"), adv["last"]
    hi, lo = adv["hi"], adv["lo"]
    sig_s = hi - extbox.ZONE * (hi - lo)
    lvb, lvs = adv["bull_lv"], adv.get("bear_lv")
    if rec == "bull":
        title, vc = f"{bull} 매수 권장", "vu"
    elif rec == "bear":
        title, vc = f"{bear} 매수 권장", "vd"
    elif z == "mid":
        title, vc = "기다리기 (박스 가운데)", ""
    else:
        title, vc = "쉬기 (박스를 벗어남, 새 박스를 기다림)", ""
    out = [f"<div class=sub>{e(head)}</div><div class='big2 {'tu' if vc == 'vu' else 'td' if vc == 'vd' else ''}'>{e(title)}</div>"
           f"<div class=sub>{e(bull)} {usd(last)} · {extbox.ZLABEL[z]} · 박스 {usd(lo)} ~ {usd(hi)} (폭 {adv['width']:.1f}%, "
           f"{datetime.fromtimestamp(adv['box_start'], KST):%H:%M} 부터)</div>"]
    rows = []

    def row(sym, lv, px, strong):
        base = min(px, lv["buy_max"])                     # 아직 매수가 위에 있으면 매수가 기준으로 %
        g, l_ = (lv["target"] / base - 1) * 100, (lv["stop"] / base - 1) * 100
        nm = f"<b>{e(sym)}</b>" if strong else e(sym)
        rows.append(f"<tr><td>{nm}<br><small class=mutt>지금 {usd(px)}</small></td><td class=r>{usd(lv['buy_max'])} 이하</td>"
                    f"<td class='r tu'>{usd(lv['target'])}<br><small>{g:+.1f}%</small></td>"
                    f"<td class='r td'>{usd(lv['stop'])}<br><small>{l_:+.1f}%</small></td></tr>")
    if rec == "bull":
        row(bull, lvb, last, True)
    elif rec == "bear" and lvs:
        row(bear, lvs, adv["bear_last"], True)
    elif z == "mid":
        row(bull, lvb, last, False)
        if lvs and adv.get("bear_last"):
            row(bear, lvs, adv["bear_last"], False)
    if rows:
        out.append("<table class=plan><tr><th>종목</th><th class=r>매수가</th><th class=r>매도 목표</th><th class=r>손절</th></tr>"
                   + "".join(rows) + "</table>")
    if z == "mid":
        out.append(f"<div class=note>{e(bull)} 가 <b>{usd(lvb['buy_max'])} 이하</b>로 내려오면 {e(bull)} 매수, "
                   f"<b>{usd(sig_s)} 이상</b>으로 오르면 {e(bear)} 매수 차례입니다.</div>")
    elif z in ("above", "below"):
        out.append(f"<div class=note>{e(bull)} 가 박스 {'위' if z == 'above' else '아래'}로 나가 박스 매매를 쉽니다. "
                   "종가가 2봉 연속 박스 밖에 머물면 박스를 지우고, 가격이 다시 옆으로 움직이면 새 박스를 그립니다.</div>")
    bk = adv.get("book") or {}
    if bk:
        parts = []
        for sym_, (bid, ask) in bk.items():
            sp = (ask / bid - 1) * 100
            parts.append(f"{e(sym_)} 매수호가 {usd(bid)} / 매도호가 {usd(ask)} (차이 {sp:.2f}%)")
        worst = max((a / b - 1) * 100 for b, a in bk.values())
        out.append(f"<div class='note{' warnt' if worst > 0.3 else ''}'>지금 호가: {' · '.join(parts)}. "
                   f"사고팔면 수수료 {2 * cfg.fee_pct:.1f}% + 호가 차이만큼 듭니다 — 시장가 말고 위 매수가로 지정가 주문하세요.</div>")
    if adv.get("rec_thin"):
        out.append(f"<div class='note warnt'>박스 폭이 좁아 목표까지 {adv['rec_gain']:+.1f}% 뿐이라, 수수료·호가 차이(왕복 약 0.7%)를 빼면 남는 게 거의 없습니다.</div>")
    bb = adv.get("bbox") or {}
    shown = ["bottom"] if rec == "bull" else ["top"] if rec == "bear" else ["bottom", "top"] if z == "mid" else []
    for k in shown:
        b = bb.get(k)
        if not b:
            continue
        who = bull if k == "bottom" else bear
        oldnew = " · ".join(f"{n_} {v:+.2f}%" for n_, v in (("앞 기간", b["old"]), ("뒤 기간", b["new"])) if v is not None)
        out.append(f"<div class='note{' warnt' if b['avg'] < 0 else ''}'>과거 {adv['stats']['days'] if adv.get('stats') else '?'}일 "
                   f"{extbox.SLABEL[adv['session']]}에 이렇게 {e(who)} 매수했다면 {b['n']}번: 목표 도달 {b['win'] / b['n'] * 100:.0f}% · "
                   f"손절 {b['loss'] / b['n'] * 100:.0f}% · 2시간 안에 둘 다 안 닿음 {b['none'] / b['n'] * 100:.0f}% · "
                   f"1회 평균 {b['avg']:+.2f}% (수수료·호가 차이 뺀 값; {oldnew})</div>")
    if any(bb.get(k) and bb[k]["avg"] < 0 for k in shown):
        out.append("<div class='note warnt'>시간외에서는 경계를 뚫고 계속 가는 경우가 많아, 지금까지 이 박스 매매는 평균적으로 손해였습니다. 금액을 작게 하세요.</div>")
    return "".join(out)


EXT_JS = r"""
(()=>{let x='1';try{x=localStorage.getItem('extx')||'1'}catch(e){}
window.chartQ='&x='+x;
window.onChart=D=>{if(!D||D.advice_html==null)return;const c=document.getElementById('adv'),o=c.querySelector('#ref');const open=o&&o.open;c.innerHTML=D.advice_html;const n=c.querySelector('#ref');if(n&&open)n.open=true};
document.addEventListener('click',ev=>{const b=ev.target.closest('button[data-x]');if(!b)return;x=b.dataset.x;window.chartQ='&x='+x;try{localStorage.setItem('extx',x)}catch(e){}if(window.chartReload)window.chartReload()})})();
"""


# 시간외 방법 비교 (research/README.md, 2026-11-24 기준). 수수료 편도 0.25% + 호가 차이 포함한 1회 평균.
EXT_RESEARCH = (
    "<h2>시간외 방법 비교 (연구 결과)</h2><section class=card>"
    "<div class=big2 style='font-size:19px'>결론: 시간외에서 꾸준히 이익 난 방법은 없었습니다</div>"
    "<div class=note>최근 60일(5분봉)에서 고른 방법을 지난 2년(1시간봉, 약 490일)에 다시 돌려 반기마다 확인했습니다. "
    "60일에서 좋아 보인 것들은 모두 2026년 하반기에만 이익이었고, 그 전 4개 반기는 손해였습니다.</div>"
    "<table><tr><th>방법</th><th class=r>최근 60일</th><th class=r>2년</th></tr>"
    "<tr><td>박스 아래 SOXL · 위 SOXS (이 탭의 권장)</td><td class=r>-0.5~-0.8%</td><td class=r>-</td></tr>"
    "<tr><td>박스 돌파 따라가기</td><td class=r>-0.6% 이하</td><td class=r>-</td></tr>"
    "<tr><td>프리 20:00(한국) 갭 따라가기 → 23:25</td><td class=r>+0.2~0.3%</td><td class=r>-0.0~-0.2%</td></tr>"
    "<tr><td>프리 초반 흐름 따라가기 → 23:30</td><td class=r>+0.4%</td><td class=r>-0.2~-0.5%</td></tr>"
    "<tr><td>정규장 4% 넘게 간 날 애프터에 따라 사서 다음 날 아침 청산</td><td class=r>+0.5~1.7%</td><td class=r>-0.3~-0.5%</td></tr>"
    "<tr><td>프리 갭 보고 정규장 개장에 따라가기 / 되돌림</td><td class=r>-</td><td class=r>-0.1~-1.0%</td></tr>"
    "</table><div class=note>숫자는 1회 평균 손익(수수료·호가 차이 뺀 값). 시간외 움직임은 수수료(왕복 0.5%)와 호가 차이를 넘을 만큼 한쪽으로 꾸준하지 않습니다.<br>"
    "<b>권장</b>: 시간외에 직접 하신다면 위 박스 권장가로 <b>지정가</b> 주문, <b>소액</b>으로만. "
    "큰 금액은 근거가 있는 정규장(한국시간 23:30~) 개장 범위 돌파·박스권 자동매매에 두세요.</div></section>")


def render_board(cfg, token: str, now: datetime | None = None) -> str:
    """차트 탭: 봉 차트(분봉~일봉, 드래그·확대축소), 지지·저항·박스·추천 구간, 호가창. 주문 기능 없음."""
    e = html.escape
    now = now or datetime.now(KST)
    syms = "".join(f"<button data-bsym='{s_}'>{s_}</button>" for s_ in board.SYMBOLS)
    tfs = "".join(f"<button data-btf='{k}'>{v}</button>" for k, v in board.TFLABEL.items())
    return ("<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=referrer content=no-referrer><title>autostock 차트</title>"
            f"<style>{CSS}</style><main><header><h1>차트 · 계획</h1><span class=pill>{now:%m-%d %H:%M}</span></header>"
            f"<nav>{_nav(token, 'board', cfg.modes)}</nav>"
            f"<section class=card><div class=seg>{syms}</div><div class=seg>{tfs}<span class=sp></span>"
            "<button data-bzoom=out>－</button><button data-bzoom=in>＋</button></div>"
            "<canvas id=bc></canvas><div id=bmsg class=note>불러오는 중…</div><div id=bfc class=note></div></section>"
            "<h2>계획 (AI 추천)</h2><section class=card><div id=bplan></div>"
            "<button id=bask class=tgl style='margin-top:10px'>AI 계획 받기</button>"
            "<div class=note>누를 때만 Claude 를 부릅니다 (한 번에 몇 원). 지금 보고 있는 종목·봉 단위 기준입니다.</div></section>"
            "<footer>계획은 이 차트의 지지·저항대, 박스, 예상선(과거 방향 적중률), 지지·저항 근처 과거 반등률, 장기 추세(50·200일 평균, "
            "1년 고점 대비, 레버리지 감가)를 Claude 가 종합해, 'AI 계획 받기'를 누를 때 세웁니다. 참고용이며 수익을 보장하지 않습니다. "
            "봉은 야후 시세(시간외 포함)와 한국투자증권 최근 분봉입니다.</footer></main>"
            f"{_appv()}<script>{CHART_CORE}</script><script>{BOARD_JS}</script>")


def render_ext(cfg, token: str, now: datetime | None = None) -> str:
    """시간외(프리·애프터·주간거래) 직접 매매 탭. 봇은 주문하지 않고, 박스와 과거 확률만 보여 준다."""
    e = html.escape
    now = now or datetime.now(KST)
    sess = extbox.session(now)
    if sess:
        dot, label = "ok", f"{extbox.SLABEL[sess[0]]} · {sess[2].astimezone(KST):%H:%M} 종료"
    else:
        nxt = extbox.next_session(now)
        o = nxt[1].astimezone(KST) if nxt else None
        dot, label = "", f"다음 {extbox.SLABEL[nxt[0]]} {'월화수목금토일'[o.weekday()]} {o:%H:%M}" if nxt else "닫힘"
    return ("<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta http-equiv=refresh content=600><meta name=referrer content=no-referrer><title>autostock 시간외</title>"
            f"<style>{CSS}</style><main><header><h1>{e(cfg.bull)} / {e(cfg.bear)} 시간외 직접 매매</h1>"
            f"<span class=pill><span class='dot {dot}'></span>{e(label)}</span></header><nav>{_nav(token, 'ext', cfg.modes)}</nav>"
            "<div class='card note'>이 탭은 주문하지 않습니다. 주간거래(한국시간 10:00~17:15)·프리마켓(18:00~23:30)·애프터마켓(06:00~10:00, "
            "서머타임에는 프리·애프터가 1시간 빠름)에 "
            f"{e(cfg.bull)}·{e(cfg.bear)} 각자의 박스(위·아래 경계에 2번 이상 닿은 옆걸음 구간, 뚫릴 때까지 고정)를 그리고, {e(cfg.bull)} 가 박스 아래쪽이면 {e(cfg.bull)}, 위쪽이면 {e(cfg.bear)} 매수를 권하며 "
            "매수·매도·손절가를 알려 줍니다. 주문은 한국투자증권 앱에서 직접 하세요.</div>"
            "<h2>지금 판단 (10초마다 갱신)</h2>"
            "<section class=card id=adv><div class=note>불러오는 중…</div></section>"
            "<h2>가격 차트 (1분봉)</h2><section class=card><div class=seg>"
            + "".join(f"<button data-sym='{e(s_)}'{' class=on' if s_ == cfg.bull else ''}>{e(s_)}</button>" for s_ in (cfg.bull, cfg.bear))
            + "</div><div class=spans>"
            + "".join(f"<button data-span='{v}'>{t}</button>" for v, t in ((60, "1시간"), (120, "2시간"), (240, "4시간"), (0, "이번 시간대")))
            + "</div><div class=legend><span><i class='lg-line rng'></i>박스</span>"
              f"<span><i class='lg-band bl'></i>{e(cfg.bull)} 매수 구간</span><span><i class='lg-band bs'></i>{e(cfg.bear)} 매수 구간</span>"
              "<span><i class='lg-line tkp'></i>매도 목표</span><span><i class='lg-line stp'></i>손절</span></div>"
              "<span class=sp></span><button data-czoom=out class=zb>－</button><button data-czoom=in class=zb>＋</button>"
              f"</div><canvas id=chart data-mode='ext' data-sym='{e(cfg.bull)}'></canvas>"
              "<div id=cmsg class=note>불러오는 중…</div></section>"
              + EXT_RESEARCH +
              f"<footer>{now:%m-%d %H:%M:%S} 기준 · 매도 목표·손절선은 권장 종목 차트에만 그립니다 · "
              "참고용 통계이며 수익을 보장하지 않습니다</footer></main>"
              f"{_appv()}<script>{EXT_JS}</script><script>{CHART_CORE}</script><script>{CHART_JS}</script>")


def _news_outcome(cfg, ts_iso: str):
    """뉴스 판단 시각의 SOXL 가격 → 그다음 정규장 종가 변화(%). 야후 5분봉 기록으로 계산, 아직이면 None."""
    from . import extbox
    _, rows = extbox._load(webdata.ext_hist_path(cfg))
    if not rows:
        return None
    try:
        t0 = datetime.fromisoformat(ts_iso).timestamp()
    except ValueError:
        return None
    start = next((r for r in rows if r[0] >= t0), None)
    end = next((r for r in rows if r[0] > t0 and datetime.fromtimestamp(r[0], ET).strftime("%H:%M") == "15:55"), None)
    return (end[4] / start[4] - 1) * 100 if start and end else None


def _news_card(cfg) -> str:
    """뉴스 호재·악재 판단: 지금 고른 종목, 근거, 지난 판단의 적중 여부."""
    from . import news
    e = html.escape
    hist = news.history(os.path.join(cfg.data_dir, "news_picks.jsonl"))
    out = ["<h2>뉴스 판단 (주간거래·프리마켓 시작 때 Claude 가 SOXL/SOXS 고름)</h2><section class=card>"]
    if not hist:
        out.append("<div class=note>아직 판단이 없습니다. 다음 주간거래(한국 10:00)나 프리마켓(18:00) 시작 때 처음 고릅니다.</div></section>")
        return "".join(out)
    last = hist[-1]
    cls_ = "up" if last["pick"] == cfg.bull else "dn" if last["pick"] == (cfg.bear or "") else "mut"
    word = {cfg.bull: "오를 쪽", (cfg.bear or "-"): "내릴 쪽"}.get(last["pick"], "중립")
    out.append(f"<div class=sub>{_kst(last['ts'], '%m-%d %H:%M')} 판단 · 세기 {last['strength']:.2f}</div>"
               f"<div class='big2 {cls_}'>{e(last['pick'])} 추천 ({word})</div><div class=note>{e(last['reason'])}</div>")
    if last.get("headlines"):
        out.append("<details><summary>읽은 기사 제목</summary><div class=note>" +
                   "<br>".join(e(h) for h in last["headlines"]) + "</div></details>")
    rows, hit, n = [], 0, 0
    for x in reversed(hist):
        ch = _news_outcome(cfg, x["ts"]) if x["pick"] != "NEUTRAL" else None
        res = "-"
        if ch is not None:
            ok = (ch > 0) == (x["pick"] == cfg.bull)
            hit, n = hit + ok, n + 1
            res = f"<span class={'up' if ok else 'dn'}>{'맞음' if ok else '틀림'}</span>"
        rows.append(f"<tr><td>{_kst(x['ts'], '%m-%d %H:%M')}</td><td>{e(x['pick'])}</td>"
                    f"<td class=r>{'-' if ch is None else f'{ch:+.1f}%'}</td><td class=r>{res}</td></tr>")
    out.append(f"<h3>지난 판단 · 적중 {hit}/{n}{f' ({hit / n * 100:.0f}%)' if n else ''}</h3><table>"
               f"<tr><th>판단 시각</th><th>추천</th><th class=r>{e(cfg.bull)} → 정규장 종가</th><th class=r>결과</th></tr>"
               + "".join(rows[:12]) + "</table><div class=note>결과는 판단 시각 가격에서 그다음 정규장 종가까지 SOXL 이 오르면 SOXL 맞음, 내리면 SOXS 맞음.</div></section>")
    return "".join(out)


def _ext_toggle(cfg, mode: str, token: str) -> str:
    """장외(프리·애프터·주간거래) 매매 켜기/끄기. 켜면 정규장 밖에서는 시간외 고정 박스 규칙으로 매매."""
    e = html.escape
    on = any(x in cfg.sessions for x in config.EXT_SESSIONS)
    nxt = "off" if on else "on"
    msg = ("정규장 밖에서도 실제 돈으로 매매합니다. 시간외에는 꾸준히 이긴 규칙이 없었고 호가 차이가 넓습니다. 켤까요?"
           if not on else "장외 매매를 끕니다. 보유 중이면 그 포지션이 정리된 뒤 꺼집니다.")
    return (f"<section class='card' style='margin:10px 0;padding:12px 16px'><div class=trow>"
            f"<div><b>장외 거래 (프리·애프터·주간거래)</b> <span class={'up' if on else 'mut'}>{'켜짐' if on else '꺼짐'}</span></div>"
            f"<form method=post action='/toggle?k={e(token)}&mode={e(mode)}&ext={nxt}' onsubmit=\"return confirm('{e(msg)}')\" style='margin:0'>"
            f"<button class=tgl type=submit>{'끄기' if on else '켜기'}</button></form></div></section>")


_ver: list = [0.0, ""]


def _tag(data):
    """화면 데이터에 서버 코드 버전을 붙인다. 화면은 버전이 바뀌면 스스로 새로고침해 옛 스크립트로 새 데이터를 읽지 않는다."""
    if isinstance(data, dict):
        data["v"] = _code_version()
    return data


def _appv() -> str:
    return f"<script>window.APPV={json.dumps(_code_version())};</script>"


def _code_version() -> str:
    """서버에 깔린 코드 버전 (자동 업데이트가 적용됐는지 화면에서 확인용). 1분 동안 재사용."""
    if time.time() - _ver[0] < 60:
        return _ver[1]
    _ver[:] = [time.time(), _code_version0()]
    return _ver[1]


def _code_version0() -> str:
    import subprocess
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h (%cd 한국시간)", "--date=format-local:%m-%d %H:%M"],
                           capture_output=True, text=True, timeout=3, env={**os.environ, "TZ": "Asia/Seoul"},
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return r.stdout.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _test_status(cfg, mode: str, events: list, live) -> str:
    """주문 테스트(첫 1주 매수) 상태와 서버에 실제 적용된 설정. 터미널 없이 왜 안 샀는지 보이게."""
    e = html.escape
    sym = cfg.order_test_symbol or cfg.bull
    tests = [x for x in events if x.get("kind") == "ordertest"]
    passed = []
    for ss in ("regular", "day"):
        fn = os.path.join(cfg.data_dir, f"ordertest_{mode}{'' if ss == 'regular' else '_' + ss}.ok")
        try:
            with open(fn, encoding="utf-8") as f:
                parts = f.read().split()
            if len(parts) > 1 and parts[1] == sym:
                passed.append(("정규장·프리·애프터" if ss == "regular" else "주간거래") + f" {_kst(parts[0], '%m-%d %H:%M')}")
        except FileNotFoundError:
            pass
    last = tests[-1] if tests else None
    if passed:
        head = f"<b class=up>{e(sym)} 주문 테스트 통과</b> · " + " · ".join(e(p) for p in passed)
    elif last and not last.get("ok"):
        head = f"<b class=dn>{e(sym)} 주문 테스트 실패</b> ({_kst(last['ts'], '%m-%d %H:%M')}): {e(str(last.get('detail', ''))[-160:])}"
    else:
        head = (f"<b>{e(sym)} 주문 테스트 아직 안 함</b> · 봇이 켜는 거래 시간({e(', '.join(market_hours.LABEL.get(x, x) for x in cfg.sessions))})이 "
                "열리고 2분 뒤 1주를 사서 보유합니다")
    halted = ((live or {}).get("halted") or "")
    st = (live or {}).get("status")
    return (f"<section class='card note' style='margin-top:10px'>{head}"
            f"{'<br>봇 상태: ' + e(st) if st else ''}{' · 멈춘 이유: ' + e(halted) if halted else ''}"
            f"<br>서버에 적용된 설정: {e(cfg.bull)}/{e(cfg.bear or '-')} · 세션 {e(','.join(cfg.sessions))} · "
            f"운용금 {cfg.capital_krw:,.0f}원 · 코드 {e(_code_version())}</section>")


def _account_card(cfg, mode: str) -> str:
    """증권사 계좌 전체 자산 (봇 장부가 아니라 실제 잔고). 30초마다 백그라운드에서 조회한 값."""
    e = html.escape
    acct = webdata._acct_cache.get(mode) or {}
    sm = acct.get("summary") or {}
    if not acct:
        return "<section class='card acct'><div class=note>계좌를 불러오는 중… (30초마다 갱신)</div></section>"
    if acct.get("error") or sm.get("error") or sm.get("total_krw") is None:
        return f"<section class='card acct'><div class=note>계좌 자산을 불러오지 못했습니다: {e(acct.get('error') or sm.get('error') or '총자산 값 없음')}</div></section>"
    rate = sm.get("usd_rate") or cfg.usdkrw
    usd = sm.get("usd_cash")
    pnl = sm.get("pnl_krw")
    chips = [("원화", f"{sm['cash_krw'] / 1e4:,.0f}만" if sm.get("cash_krw") is not None else None),
             ("달러", f"${usd:,.0f}" if usd is not None else None),
             ("주식", f"{sm['stock_krw'] / 1e4:,.1f}만" if sm.get("stock_krw") is not None else None),
             ("평가손익", f"<span class={'up' if (pnl or 0) > 0 else 'dn' if (pnl or 0) < 0 else 'mut'}>{pnl:+,.0f}원</span>" if pnl is not None else None)]
    return (f"<section class='card acct'><div class=k style='font-size:12px;color:var(--mut)'>총 평가금액</div>"
            f"<div class=big>{sm['total_krw']:,.0f}원</div>"
            f"<div class=chips>{''.join(f'<span class=chip>{k} <b>{v}</b></span>' for k, v in chips if v)}</div>"
            f"<div class=note>봇 운용금 {cfg.capital_krw / 1e4:,.0f}만원 · 달러 ≈ {usd * rate / 1e4:,.0f}만원 · "
            f"{datetime.fromtimestamp(acct['at'], KST):%H:%M} 기준</div></section>"
            if usd is not None else
            f"<section class='card acct'><div class=big>{sm['total_krw']:,.0f}원</div><div class=note>봇은 이 중 운용금 {cfg.capital_krw:,.0f}원만 씁니다</div></section>")


def _equity_svg(pts: list[float], fx: float) -> str:
    """거래마다의 누적 실현손익(원) 선 그래프."""
    W, H, pl, pr, pt, pb = 360, 140, 4, 70, 10, 18
    vals = [0.0] + [p * fx for p in pts]
    lo, hi = min(vals + [0]), max(vals + [0])
    if hi - lo < 1:
        hi, lo = hi + 1, lo - 1
    X = lambda i: pl + i / max(len(vals) - 1, 1) * (W - pl - pr)   # noqa: E731
    Y = lambda v: pt + (hi - v) / (hi - lo) * (H - pt - pb)          # noqa: E731
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f} {Y(v):.1f}" for i, v in enumerate(vals))
    last = vals[-1]
    col = "var(--up)" if last > 0 else "var(--dn)" if last < 0 else "var(--mut)"
    dots = "".join(f"<circle cx='{X(i):.1f}' cy='{Y(v):.1f}' r='3' fill='{'var(--up)' if v >= vals[i - 1] else 'var(--dn)'}' "
                   f"stroke='var(--card)' stroke-width='1.5'><title>{i}번째 거래 후 {v:+,.0f}원</title></circle>"
                   for i, v in enumerate(vals) if i and len(vals) <= 80)
    return (f"<svg viewBox='0 0 {W} {H}' width='100%' role=img aria-label='누적 실현손익'>"
            f"<line x1='{pl}' x2='{W - pr}' y1='{Y(0):.1f}' y2='{Y(0):.1f}' stroke='var(--mut)' stroke-dasharray='3 3'/>"
            f"<text x='{W - pr + 6}' y='{Y(0) + 4:.1f}' font-size='12' fill='var(--mut)'>0원</text>"
            f"<text x='{W - pr + 6}' y='{min(max(Y(last) + 4, 14), H - pb):.1f}' font-size='12' font-weight='700' fill='{col}'>{last / 1e4:+,.1f}만원</text>"
            f"<path d='{path}' fill='none' stroke='{col}' stroke-width='2' stroke-linejoin='round'/>{dots}"
            f"<text x='{pl}' y='{H - 4}' font-size='11' fill='var(--mut)'>첫 거래</text>"
            f"<text x='{W - pr}' y='{H - 4}' font-size='11' fill='var(--mut)' text-anchor='end'>최근 ({len(vals) - 1}건)</text></svg>")


def make_handler(token: str):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path not in ("/", "/data") or not hmac.compare_digest(q.get("k", [""])[0], token):
                self.send_error(404)
                return
            load_dotenv(override=True)   # 실행 중에 .env 가 바뀌어도 최신 설정으로 보여준다
            cfg = config.load()
            mode = q.get("mode", [cfg.mode])[0]
            if mode not in MODES and mode not in ("ext", "board"):
                mode = cfg.mode
            cfg = config.load("paper" if mode in ("ext", "board") else mode)   # 탭마다 그 모드의 자금·종목 설정으로 보여준다
            if mode == "board":
                if u.path == "/data":
                    sym = q.get("sym", ["SOXL"])[0]
                    sym = sym if sym in board.SYMBOLS else "SOXL"
                    if q.get("what", [""])[0] == "book":
                        data = webdata.board_book(cfg, sym)
                    elif q.get("what", [""])[0] == "plan":
                        tf = q.get("tf", ["5m"])[0]
                        tf = tf if tf in board.TF else "5m"
                        if q.get("ask", [""])[0] != "1":           # 버튼을 누르기 전에는 Claude 를 부르지 않는다
                            data = board.cached_plan(sym, tf) or {"none": True}
                            body, ctype = json.dumps(_tag(data)).encode(), "application/json"
                            self._send(body, ctype)
                            return
                        try:
                            extra = webdata.board_recent(cfg, STORE, sym) if STORE is not None else []
                            data = board.plan(sym, tf, board.analyze(sym, tf, extra), cfg.model)
                        except Exception as ex:
                            data = {"error": f"{type(ex).__name__}: {ex}"[:160]}
                    elif q.get("what", [""])[0] == "long":
                        try:
                            data = board.longterm(sym)
                        except Exception as ex:
                            data = {"error": f"{type(ex).__name__}: {ex}"[:160]}
                    else:
                        tf = q.get("tf", ["5m"])[0]
                        try:
                            extra = webdata.board_recent(cfg, STORE, sym) if STORE is not None else []
                            data = board.analyze(sym, tf if tf in board.TF else "5m", extra)
                        except Exception as ex:
                            data = {"error": f"{type(ex).__name__}: {ex}"[:160], "bars": []}
                    body, ctype = json.dumps(_tag(data)).encode(), "application/json"
                else:
                    body, ctype = render_board(cfg, token).encode(), "text/html; charset=utf-8"
            elif mode == "ext":
                if u.path == "/data":
                    try:
                        span, x = int(q.get("span", ["120"])[0]), float(q.get("x", ["1"])[0])
                    except ValueError:
                        span, x = 120, 1.0
                    data = webdata.ext_chart(cfg, q.get("sym", [cfg.bull])[0], span, STORE, x)
                    adv = data.pop("advice", None)
                    data["advice_html"] = ext_card(adv, cfg) if adv else ""
                    body, ctype = json.dumps(_tag(data)).encode(), "application/json"
                else:
                    body, ctype = render_ext(cfg, token).encode(), "text/html; charset=utf-8"
            elif u.path == "/data":
                state, events, live = webdata.read(cfg, mode)
                try:
                    span = int(q.get("span", ["120"])[0])
                except ValueError:
                    span = 120
                data = webdata.chart(cfg, mode, q.get("sym", [cfg.bull])[0], span, STORE, state, live, events)
                body = json.dumps(_tag(data)).encode()
                ctype = "application/json"
            else:
                body = render(cfg, mode, token).encode()
                ctype = "text/html; charset=utf-8"
            self._send(body, ctype)

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            """결과 페이지에서 바꿀 수 있는 유일한 설정: 실계좌 장외 거래 켜기/끄기."""
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path != "/toggle" or not hmac.compare_digest(q.get("k", [""])[0], token):
                self.send_error(404)
                return
            mode, ext = q.get("mode", [""])[0], q.get("ext", [""])[0]
            if mode != "live" or ext not in ("on", "off"):
                self.send_error(400)
                return
            load_dotenv(override=True)
            cfg = config.load(mode)
            config.write_override(cfg.data_dir, mode, "ext_trading", ext == "on")
            self.send_response(303)
            self.send_header("Location", f"/?k={token}&mode={mode}")
            self.end_headers()

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
    global STORE
    import threading
    STORE = webdata.BarStore(os.path.join(config.load().data_dir, "bars_cache.json"))
    threading.Thread(target=webdata.collector, args=(STORE, threading.Event()), daemon=True).start()
    threading.Thread(target=webdata.account_refresher, args=(threading.Event(),), daemon=True).start()
    threading.Thread(target=webdata.book_recorder, args=(threading.Event(),), daemon=True).start()
    from . import signals as sigbook
    threading.Thread(target=sigbook.labeler, args=(STORE, lambda: config.load().modes, config.load, threading.Event()),
                     daemon=True).start()
    board.REC = board.Recorder(config.load("paper").data_dir)
    threading.Thread(target=board.REC.loop, args=(threading.Event(), lambda s_: webdata.board_recent(config.load("paper"), STORE, s_)),
                     daemon=True).start()
    threading.Thread(target=board.warmer, args=(threading.Event(), lambda s_: webdata.board_recent(config.load("paper"), STORE, s_)),
                     daemon=True).start()
    pc = config.load("paper")
    threading.Thread(target=extbox.history_refresher, args=(pc.bull, webdata.ext_hist_path(pc), threading.Event()),
                     daemon=True).start()
    print(f"결과 페이지: 포트 {port}")
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(token)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
