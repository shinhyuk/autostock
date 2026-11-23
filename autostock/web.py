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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from . import config, market_hours

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
nav{display:flex;gap:6px;margin-bottom:12px}nav a{flex:1;text-align:center;padding:8px 6px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--mut);text-decoration:none;font-size:14px}
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
.chartwrap{position:relative;touch-action:pan-y}#chart{min-height:230px}#chart svg{display:block}
#tip{display:none;position:absolute;top:0;pointer-events:none;background:var(--acc);color:var(--bg);font-size:12px;padding:5px 8px;border-radius:8px;white-space:nowrap;font-variant-numeric:tabular-nums}
.sp{flex:1}.seg{flex-wrap:wrap}.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--mut);margin:2px 0 6px}
.legend span{display:inline-flex;align-items:center;gap:5px}.legend i{display:inline-block}
.lg-up{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:9px solid var(--up)}
.lg-dn{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:9px solid var(--dn)}
.lg-line{width:16px;height:0;border-top:2px solid}.lg-line.vwap{border-color:var(--vwap)}.lg-line.rng{border-top-style:dashed;border-color:var(--warn)}
.lg-line.bx{border-top-style:dotted;border-color:var(--mut)}.lg-line.nz{border-top-style:dashed;border-color:var(--noise)}
.lg-line.stp{border-top-style:dashed;border-color:var(--dn)}.lg-line.tkp{border-top-style:dashed;border-color:var(--up)}
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
"""


from .webchart import CHART_JS  # noqa: E402
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


def render(cfg, mode: str, token: str, now: datetime | None = None) -> str:
    e = html.escape
    now = now or datetime.now(KST)
    state, events, live = _read(cfg, mode)
    fx = cfg.usdkrw

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
           f"<style>{CSS}</style><main><header><h1>{e(' / '.join(cfg.symbols))} 자동매매</h1>"
           f"<span class=pill><span class='dot {dot}'></span>{e(label)}</span></header><nav>"]
    for m, name in MODES.items():
        out.append(f"<a{' class=on' if m == mode else ''} href='/?k={e(token)}&mode={m}'>{name}{' ●' if m in cfg.modes else ''}</a>")
    out.append("</nav>")
    if not running:
        links = " · ".join(f"<a href='/?k={e(token)}&mode={m}'>{MODES[m]} 보기</a>" for m in cfg.modes if m in MODES)
        out.append(f"<div class='card note'>이 탭({MODES[mode]})은 지금 실행 중이 아니라 지난 기록만 보입니다. 현재 실행 중: {links}</div>")

    # ── 오늘 손익
    s = state or {"date": "", "realized_usd": 0.0, "trades": 0, "wins": 0, "losses": 0, "halted": "", "open": None, "history": []}
    o = s.get("open")
    unreal = (live or {}).get("unrealized_usd") if o and age is not None and age <= 150 else None
    total = s["realized_usd"] + (unreal or 0)
    target, limit = cfg.target_usd, cfg.max_loss_usd
    pct = total / cfg.capital_usd * 100 if cfg.capital_usd else 0
    span = target + limit
    zero = limit / span * 100
    pos = min(max((total + limit) / span * 100, 0), 100)
    lo, hi = sorted((zero, pos))
    color = "var(--up)" if total > 0 else "var(--dn)"
    led = (live or {}).get("ledger")
    if not led:
        try:
            with open(os.path.join(cfg.data_dir, f"ledger_{mode}.json"), encoding="utf-8") as f:
                led = json.load(f)
        except (FileNotFoundError, ValueError):
            led = None
    equity = cfg.capital_usd + (led["realized_usd"] if led else 0)
    key = s.get("date") or ""
    sname = {"D": "주간거래", "P": "프리마켓", "A": "애프터마켓"}.get(key[-1:], "정규장") if key else ""
    out.append(f"<section class='card hero'><div class=k>{'이번 세션' if len(cfg.sessions) > 1 else '오늘'} 손익"
               f"{' (평가 포함)' if unreal is not None else ''}"
               f"{' · ' + sname + ' ' + e(key[:10]) if key else ''}</div>"
               f"<div class='big {cls(total)}'>{arrow(total)} {won(total)}</div>"
               f"<div class=sub>{pct:+.2f}% · ${total:+.2f}"
               f"{' · 실현 ' + won(s['realized_usd']) if unreal is not None else ''}</div>"
               f"<div class=meter role=img aria-label='손실한도와 목표 사이 현재 위치'><i style='left:{lo:.1f}%;width:{hi - lo:.1f}%;background:{color}'></i>"
               f"<b style='left:{zero:.1f}%'></b></div>"
               f"<div class=ends><span>손실한도 -{cfg.daily_max_loss_krw:,.0f}</span><span>목표 +{cfg.daily_target_krw:,.0f}</span></div>"
               f"<div class=stats><div><div class=k>거래</div><div class=v>{s['trades']}회</div></div>"
               f"<div><div class=k>승 / 패</div><div class=v>{s['wins']} / {s['losses']}</div></div>"
               f"<div><div class=k>현재 자산</div><div class=v>{equity * fx:,.0f}</div></div></div>"
               + (f"<div class=note>시작 {cfg.capital_krw:,.0f}원 ({_kst(led['start'], '%m-%d %H:%M')}) → 누적 실현 "
                  f"<b class='{cls(led['realized_usd'])}'>{won(led['realized_usd'])}</b> · {led.get('trades', 0)}건 · "
                  f"채우지 않고 이 자산으로 계속 매매</div>" if led else "")
               + (f"<div class=note>종료 사유: {e(s['halted'])}</div>" if s["halted"] else "") + "</section>")

    # ── 전략 상태
    orb = (live or {}).get("orb") if cfg.strategy == "orb" else None
    if cfg.strategy == "orb":
        rng = (f" · 오늘 범위 ${orb['ll']:.2f} ~ ${orb['hh']:.2f}" if orb and orb.get("hh") else "")
        out.append(f"<h2>전략</h2><section class=card><b>개장 {cfg.orb_minutes}분 범위 돌파</b>"
                   f"<span class=mut>{e(rng)}</span>"
                   f"<div class=note>상태: {e((orb or {}).get('status') or '-')}<br>"
                   f"범위 위로 뚫으면 {e(cfg.bull)}, 아래로 뚫으면 {e(cfg.bear or '-')} 매수 · 엔비디아·SOXX 동조 필요 · "
                   + ("손절 범위 중간값 · " if cfg.orb_stop_mode == "mid" else f"손절 {cfg.orb_stop_pct}% · ")
                   + f"익절 {cfg.orb_take_pct}% · " + (f"추적 {cfg.orb_trail_pct}% · " if cfg.orb_trail_pct else "추적 손절 없음 · ")
                   + f"개장 {cfg.orb_window_min}분까지 · 하루 {cfg.orb_max_trades}회<br>"
                   + (f"<b>박스권</b>: 범위 폭 {cfg.box_min_width}% 이상인 날, 범위를 벗어나기 전까지 아래 경계 근처 반등 → {e(cfg.bull)}, "
                      f"위 경계 근처 반락 → {e(cfg.bear)} · 익절은 반대 경계의 {cfg.box_target * 100:.0f}% 지점, 손절은 경계 밖 "
                      f"{cfg.box_stop * 100:.0f}% · 하루 {cfg.box_max}회<br>" if cfg.box else "")
                   + (f"<b>노이즈 영역</b>: 개장 후 30분마다, 지난 {cfg.noise_lookback}일 같은 시각의 평균 움직임 밖이면 그 방향 매수, "
                      f"영역 안으로 돌아오면 청산 (확인 사이 안전 손절 {cfg.noise_stop_pct}%)<br>" if cfg.noise else "")
                   + (f"<b>변동성 필터</b>: 최근 5일 평균 하루 변동폭 {cfg.vol_filter_min}% 미만이면 그날 쉼<br>" if cfg.vol_filter_min else "")
                   + (f"<b>매수 금액</b>: 손절 시 자본의 {cfg.risk_per_trade_pct}%만 잃도록 수량 조절<br>" if cfg.risk_per_trade_pct else "")
                   + "Claude 는 진입마다 동의/반대 의견만 남깁니다(주문에는 미반영)."
                   + (f"<br><b>정규장 밖({', '.join(market_hours.LABEL[x] for x in cfg.sessions if x != 'regular')})</b>: "
                      f"Claude 가 3분마다 직접 판단하는 실험 — 백테스트에서 이 시간대에 통한 규칙이 없었습니다."
                      if cfg.ext_strategy == "ai" and len(cfg.sessions) > 1 else "")
                   + (f"<br>지금: <b>{market_hours.LABEL.get((live or {}).get('session') or '', '장 닫힘')}</b>"
                      if live else "") + "</div></section>")

    # ── 활동 로그
    acts = webdata.activity(cfg, mode, 40)
    if acts:
        last_age = None
        try:
            last_age = (now - datetime.fromisoformat(acts[-1]["ts"])).total_seconds()
        except (ValueError, KeyError):
            pass
        stale = f" · <span class=warnt>마지막 기록 {last_age / 60:.0f}분 전</span>" if last_age and last_age > 180 else ""
        out.append(f"<h2>활동 로그 (1분마다, 한국시간){stale}</h2><section class='card feed actlog'>")
        for x in acts[::-1]:
            meta = " · ".join(v for v in (x.get("session"), x.get("strategy"), x.get("pnl")) if v)
            out.append(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div><div class=a>{e(x.get('msg', ''))}</div>"
                       + (f"<div class=r>{e(meta)}</div>" if meta else "") + "</div></div>")
        out.append("</section>")

    # ── 보유 종목
    acct = webdata.account(cfg, mode, state, live)
    trips, _open_lots = webdata.round_trips(events, cfg.fee_pct)
    out.append(f"<h2>보유 종목 <span class=mut style='font-weight:500'>· {e(acct.get('source', ''))}</span></h2>")
    if acct.get("loading"):
        out.append("<section class='card note'>증권사 잔고를 불러오는 중입니다 (최대 30초). 잠시 뒤 새로고침하세요.</section>")
    elif acct.get("error"):
        out.append(f"<section class='card note'>잔고 조회 실패: {e(acct['error'])}</section>")
    elif not acct["holdings"]:
        out.append("<section class=card><span class=mut>보유 종목 없음 (현금 대기)</span></section>")
    for h in acct.get("holdings", []):
        q, avg, last = h["qty"], h["avg"], h.get("last")
        if o and h["symbol"] == o.get("symbol") and not last:
            last = (live or {}).get("last")
        cost = avg * q
        value = h.get("value") or (last * q if last else None)
        pnl = h.get("pnl") if h.get("pnl") is not None else (value - cost if value else None)
        if h.get("bot") and o and unreal is not None and mode == "paper":
            pnl = unreal                                   # 봇 장부: 왕복 수수료까지 뺀 평가손익
        ppct = pnl / cost * 100 if pnl is not None and cost else None
        head = (f"<div class='{cls(pnl)} pnlbig'>{arrow(pnl)} {won(pnl)} <small>({ppct:+.2f}%)</small></div>"
                if pnl is not None else "<div class=mut>평가 중</div>")
        tag = "<span class=tag>봇 관리</span>" if h.get("bot") else "<span class='tag mutt'>봇 관리 밖</span>"
        rows = [("수량", f"{q:,}주"), ("평균 단가", usd(avg)), ("현재가", usd(last) if last else "-"),
                ("매입 금액", f"{usd(cost)} · {won(cost, False)}"),
                ("평가 금액", f"{usd(value)} · {won(value, False)}" if value else "-")]
        if h.get("bot") and o and h["symbol"] == o["symbol"]:
            ent = o["entry_price"]
            rows += [("손절가", f"{usd(ent * (1 - o['stop_pct'] / 100))} (-{o['stop_pct']:.1f}%)"),
                     ("익절가", f"{usd(ent * (1 + o['take_pct'] / 100))} (+{o['take_pct']:.1f}%)")]
            if o.get("trail_pct"):
                rows.append(("추적 손절", f"고점 {usd(o.get('peak_price') or ent)}에서 -{o['trail_pct']}%"))
            held = webdata._mins(o["entry_ts"], now.astimezone(ET).isoformat())
            rows.append(("매수 시각", f"{_kst(o['entry_ts'], '%m-%d %H:%M')} ({held:.0f}분 보유)" if held is not None else _kst(o["entry_ts"])))
        if h.get("name"):
            rows.insert(0, ("종목명", h["name"]))
        out.append(f"<section class='card hold'><div class=pos><div class=sym>{e(h['symbol'])} {tag}</div>{head}</div>"
                   "<dl class=kv>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl></section>")
    if acct.get("at"):
        out.append(f"<div class='note pad'>잔고 기준 {datetime.fromtimestamp(acct['at'], KST):%H:%M:%S} (30초마다 갱신)</div>")
    if acct.get("cash") is not None:
        out.append(f"<div class='note pad'>주문 가능 금액 {usd(acct['cash'])} · {won(acct['cash'], False)}</div>")
    if acct.get("mismatch"):
        out.append(f"<div class='note pad warnt'>⚠ {e(acct['mismatch'])}</div>")

    # ── 가격 차트
    held_sym = o["symbol"] if o else cfg.bull
    out.append("<h2>가격 차트 (1분봉)</h2><section class=card><div class=seg>"
               + "".join(f"<button data-sym='{e(s_)}'{' class=on' if s_ == held_sym else ''}>{e(s_)}</button>" for s_ in cfg.symbols)
               + "</div><div class=spans>"
               + "".join(f"<button data-span='{v}'>{t}</button>" for v, t in ((60, "1시간"), (120, "2시간"), (240, "4시간"), (0, "오늘 전체")))
               + "</div><div class=legend><span><i class='lg-up'></i>매수</span><span><i class='lg-dn'></i>매도</span>"
               "<span><i class='lg-line vwap'></i>VWAP</span>"
               + ("<span><i class='lg-line rng'></i>개장 범위</span>" if cfg.strategy == "orb" else "")
               + ("<span><i class='lg-line bx'></i>박스 매수 구간</span>" if cfg.box else "")

               + ("<span><i class='lg-line stp'></i>손절</span><span><i class='lg-line tkp'></i>익절</span>" if o else "")
               + f"</div><div class=chartwrap><div id=chart data-mode='{e(mode)}' data-sym='{e(held_sym)}'></div><div id=tip></div></div>"
               "<div id=cmsg class=note>불러오는 중…</div></section>")

    # ── 거래 내역
    if trips:
        today = [t for t in trips if (s.get("date") or "")[:10] and t["sell_ts"][:10] == (s.get("date") or "")[:10]]
        shown = trips[-30:][::-1]
        out.append(f"<h2>거래 내역 (한국시간) · 오늘 {len(today)}건 · 전체 {len(trips)}건</h2><section class='card feed'>")
        for t in shown:
            p = t["pnl"]
            head = f"<span class='{cls(p)}'>{arrow(p)} {won(p)}" + (f" ({t['pct']:+.2f}%)" if t["pct"] is not None else "") + "</span>" if p is not None else ""
            buy = (f"{_kst(t['buy_ts'], '%m-%d %H:%M')} · {usd(t['buy_px'])} × {t['qty']:,}주 = {usd(t['buy_amt'])} ({won(t['buy_amt'], False)})"
                   if t["buy_px"] else "매수 기록 없음")
            sell = f"{_kst(t['sell_ts'], '%m-%d %H:%M')} · {usd(t['sell_px'])} × {t['qty']:,}주 = {usd(t['sell_amt'])} ({won(t['sell_amt'], False)})"
            held = f" · {t['hold_min']:.0f}분 보유" if t["hold_min"] is not None else ""
            out.append(f"<div class='row trip'><div class=t>{_kst(t['sell_ts'])}</div><div><div class=h><span>{e(t['symbol'])} {t['qty']:,}주</span>{head}</div>"
                       f"<div class=leg><b class=tu>매수</b> {buy}</div>"
                       f"<div class=leg><b class=td>매도</b> {sell}</div>"
                       f"<div class=r>수수료 {usd(t['fees'])} ({won(t['fees'], False)}){held} · {e(t['sell_reason'])}</div></div></div>")
        out.append("</section>")

        # ── 누적 손익
        done = [t for t in trips if t["pnl"] is not None]
        if done:
            cum, pts = 0.0, []
            for t in done:
                cum += t["pnl"]
                pts.append(cum)
            wins = [t for t in done if t["pnl"] > 0]
            fees = sum(t["fees"] for t in done)
            bought = sum(t["buy_amt"] or 0 for t in done)
            out.append(f"<h2>누적 성과 · {len(done)}건</h2><section class=card>{_equity_svg(pts, fx)}"
                       f"<div class=stats4><div><div class=k>누적 실현손익</div><div class='v {cls(cum)}'>{won(cum)}</div></div>"
                       f"<div><div class=k>승률</div><div class=v>{len(wins) / len(done) * 100:.0f}% <small class=mut>({len(wins)}/{len(done)})</small></div></div>"
                       f"<div><div class=k>총 매수 금액</div><div class=v>{won(bought, False)}</div></div>"
                       f"<div><div class=k>낸 수수료</div><div class=v>{won(fees, False)}</div></div>"
                       f"<div><div class=k>평균 이익</div><div class='v up'>{won(sum(t['pnl'] for t in wins) / len(wins)) if wins else '-'}</div></div>"
                       f"<div><div class=k>평균 손실</div><div class='v dn'>{won(sum(t['pnl'] for t in done if t['pnl'] <= 0) / max(1, len(done) - len(wins))) if len(done) > len(wins) else '-'}</div></div></div></section>")

    # ── 세션별
    if trips and len(cfg.sessions) > 1:
        by = defaultdict(lambda: [0.0, 0, 0, 0.0])
        for t in trips:
            if t["pnl"] is None:
                continue
            g = by[market_hours.session_of(t["buy_ts"] or t["sell_ts"])]
            g[0] += t["pnl"]
            g[1] += 1
            g[2] += t["pnl"] > 0
            g[3] += t["fees"]
        strat = lambda x: ("개장 범위 돌파" if cfg.strategy == "orb" else "Claude 판단") if x == "regular" else (  # noqa: E731
            "Claude 판단" if (cfg.ext_strategy or cfg.strategy) == "ai" else "개장 범위 돌파")
        out.append("<h2>시간대별 성과</h2><section class=card><table>"
                   "<tr><th>시간대</th><th>전략</th><th class=r>손익</th><th class=r>거래</th><th class=r>승률</th></tr>")
        for x in ("regular", "pre", "post", "day"):
            if x in by:
                p_, n_, w_, _f = by[x]
                out.append(f"<tr><td>{market_hours.LABEL[x]}</td><td class=mutt>{strat(x)}</td>"
                           f"<td class='r {cls(p_)}'>{won(p_)}</td><td class=r>{n_}</td><td class=r>{w_ / n_ * 100:.0f}%</td></tr>")
        out.append("</table></section>")

    # ── 일별
    if trips:
        days = defaultdict(lambda: [0.0, 0, 0, 0.0])
        for t in trips:
            if t["pnl"] is None:
                continue
            d = days[t["sell_ts"][:10]]
            d[0] += t["pnl"]
            d[1] += 1
            d[2] += t["pnl"] > 0
            d[3] += t["fees"]
        out.append("<h2>일별 손익 (미국 날짜)</h2><section class=card><table>"
                   "<tr><th>날짜</th><th class=r>손익</th><th class=r>수익률</th><th class=r>거래</th><th class=r>승률</th><th class=r>수수료</th></tr>")
        for day in sorted(days, reverse=True)[:60]:
            p, n_, w, f_ = days[day]
            out.append(f"<tr><td>{e(day[5:])}</td><td class='r {cls(p)}'>{won(p)}</td>"
                       f"<td class='r {cls(p)}'>{p / cfg.capital_usd * 100:+.1f}%</td><td class=r>{n_}</td>"
                       f"<td class=r>{w / n_ * 100:.0f}%</td><td class=r>{won(f_, False)}</td></tr>")
        out.append("</table></section>")

    # ── AI 판단
    decisions = [x for x in events if x.get("kind") == "decision"][-25:][::-1]
    if decisions:
        out.append("<h2>AI 판단 기록 (한국시간)</h2><section class='card feed'>")
        for x in decisions:
            act = x.get("action", "")
            kind = "buy" if act == "BUY" else "sell" if act in ("SELL", "DISAGREE") else ""
            out.append(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div><div class=h><span>"
                       f"<span class='tag {kind}'>{ACTION.get(act, e(str(act)))}</span> {e(str(x.get('symbol') or ''))}</span>"
                       f"<span class=mut style='font-weight:500;font-size:13px'>확신 {x.get('confidence', 0) * 100:.0f}%</span></div>"
                       f"<div class=r>{e(str(x.get('reason', '')))}</div></div></div>")
        out.append("</section>")

    # ── 시스템 기록
    system = [x for x in events if x.get("kind") in ("ordertest", "error")][-6:][::-1]
    if system:
        out.append("<h2>시스템 기록 (한국시간)</h2><section class='card feed'>")
        for x in system:
            if x["kind"] == "ordertest":
                title = f"주문 테스트 {'통과' if x.get('ok') else '실패'}" + (f" ({x.get('attempt')}회차)" if x.get("attempt") else "")
            else:
                title = "오류"
            out.append(f"<div class=row><div class=t>{_kst(x['ts'])}<br>{_kst(x['ts'], '%m-%d')}</div><div><div class=h><span>{e(title)}</span></div>"
                       f"<div class=r>{e(str(x.get('detail', '')))}</div></div></div>")
        out.append("</section>")

    if not state and not events:
        out.append("<div class='card note' style='margin-top:14px'>아직 기록이 없습니다. 이 모드로 장이 열린 적이 없습니다.</div>")
    model = (live or {}).get("model") or cfg.model
    out.append(f"<footer>{now:%m-%d %H:%M:%S} 기준 · 차트 10초, 나머지 2분마다 갱신 · ● 실행 중인 모드<br>"
               f"환율 {fx:,.0f}원 환산 · 수수료 편도 {cfg.fee_pct}% 반영 · AI {e(model)} · 정규장 한국시간 23:30~06:00 (서머타임 22:30~05:00)"
               f"{' · 애프터마켓 06:00~09:55' if 'post' in cfg.sessions else ''}"
               f"{' · 주간거래 10:00~17:15' if 'day' in cfg.sessions else ''}"
               f"{' · 프리마켓 18:00~23:25' if 'pre' in cfg.sessions else ''}</footer></main>"
               f"<script>{CHART_JS}</script>")
    return "".join(out)


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
            if mode not in MODES:
                mode = cfg.mode
            cfg = config.load(mode)      # 탭마다 그 모드의 자금·종목 설정으로 보여준다
            if u.path == "/data":
                state, events, live = webdata.read(cfg, mode)
                try:
                    span = int(q.get("span", ["120"])[0])
                except ValueError:
                    span = 120
                data = webdata.chart(cfg, mode, q.get("sym", [cfg.bull])[0], span, STORE, state, live, events)
                body = json.dumps(data).encode()
                ctype = "application/json"
            else:
                body = render(cfg, mode, token).encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
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
    global STORE
    import threading
    STORE = webdata.BarStore(os.path.join(config.load().data_dir, "bars_cache.json"))
    threading.Thread(target=webdata.collector, args=(STORE, threading.Event()), daemon=True).start()
    threading.Thread(target=webdata.account_refresher, args=(threading.Event(),), daemon=True).start()
    print(f"결과 페이지: 포트 {port}")
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(token)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
