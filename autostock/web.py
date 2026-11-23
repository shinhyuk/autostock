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
from datetime import datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from . import config, market_hours

MODES = {"paper": "가상매매", "kis-demo": "모의투자", "live": "실계좌"}
KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
ACTION = {"BUY": "매수", "SELL": "청산", "HOLD": "관망"}
CSS = """
:root{--bg:#f4f5f7;--card:#fff;--fg:#14161a;--mut:#667085;--line:#e4e7ec;--up:#d92d20;--dn:#1d4ed8;--acc:#111827;--ok:#16a34a;--warn:#d97706;--track:#eceef2}
@media(prefers-color-scheme:dark){:root{--bg:#0e1014;--card:#171a20;--fg:#eceef2;--mut:#98a2b3;--line:#272b34;--up:#ff6b5e;--dn:#6ea8ff;--acc:#eceef2;--ok:#4ade80;--warn:#fbbf24;--track:#22262e}}
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
footer{color:var(--mut);font-size:12px;margin:20px 2px}
"""


CHART_JS = r"""
(()=>{const box=document.getElementById('chart');if(!box)return;
const q=new URLSearchParams(location.search),K=q.get('k'),M=box.dataset.mode;let sym=box.dataset.sym,D=null,hover=null;
const NS='http://www.w3.org/2000/svg',el=(n,a,t)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(t!=null)e.textContent=t;return e};
const hm=t=>new Date(t).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Seoul'});
const tip=document.getElementById('tip'),msg=document.getElementById('cmsg');
async function load(){try{const r=await fetch(`/data?k=${encodeURIComponent(K)}&mode=${M}&sym=${sym}`);D=await r.json()}catch(e){D={error:'연결 실패'}}draw()}
function draw(){box.innerHTML='';const b=(D&&D.bars)||[];
 if(b.length<2){msg.textContent=(D&&D.error)?'차트를 불러오지 못했습니다: '+D.error:'표시할 시세가 아직 없습니다';tip.style.display='none';return}
 msg.textContent=sym+' 1분봉 · 최근 '+b.length+'분 · 10초마다 갱신'+(D.last?' · 현재 $'+D.last.toFixed(2):'');
 const W=box.clientWidth,H=230,pl=6,pr=50,pt=14,pb=22,tr=D.trades||[];
 let lo=Math.min(...b.map(x=>x[1]),...tr.map(x=>x[2])),hi=Math.max(...b.map(x=>x[1]),...tr.map(x=>x[2]));const pad=(hi-lo)*.08||.05;lo-=pad;hi+=pad;
 const t0=b[0][0],t1=b[b.length-1][0],X=t=>pl+(t-t0)/(t1-t0||1)*(W-pl-pr),Y=v=>pt+(hi-v)/(hi-lo)*(H-pt-pb);
 const s=el('svg',{width:W,height:H,viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':sym+' 가격 추이와 매매 지점'});
 for(let i=0;i<=3;i++){const v=lo+(hi-lo)*i/3,y=Y(v);s.append(el('line',{x1:pl,x2:W-pr,y1:y,y2:y,stroke:'var(--line)','stroke-width':1}),el('text',{x:W-pr+6,y:y+4,'font-size':11,fill:'var(--mut)'},'$'+v.toFixed(2)))}
 for(let i=0;i<=2;i++){const t=t0+(t1-t0)*i/2;s.append(el('text',{x:X(t),y:H-6,'font-size':11,fill:'var(--mut)','text-anchor':i==0?'start':i==2?'end':'middle'},hm(t)))}
 s.append(el('path',{d:b.map((x,i)=>(i?'L':'M')+X(x[0]).toFixed(1)+' '+Y(x[1]).toFixed(1)).join(''),fill:'none',stroke:'var(--fg)','stroke-width':2,'stroke-linejoin':'round','stroke-linecap':'round',opacity:.8}));
 const L=b[b.length-1];s.append(el('circle',{cx:X(L[0]),cy:Y(L[1]),r:4,fill:'var(--fg)',stroke:'var(--card)','stroke-width':2}));
 for(const x of tr){if(x[0]<t0||x[0]>t1+6e4)continue;const cx=X(Math.min(x[0],t1)),cy=Y(x[2]),buy=x[1]=='buy',d=buy?`M${cx} ${cy-8}L${cx+7} ${cy+5}L${cx-7} ${cy+5}Z`:`M${cx} ${cy+8}L${cx+7} ${cy-5}L${cx-7} ${cy-5}Z`;
  s.append(el('path',{d,fill:buy?'var(--up)':'var(--dn)',stroke:'var(--card)','stroke-width':2,'stroke-linejoin':'round'}))}
 if(hover!=null){let i=0,best=1e18;b.forEach((x,k)=>{const dd=Math.abs(X(x[0])-hover);if(dd<best){best=dd;i=k}});const p=b[i],cx=X(p[0]);
  s.append(el('line',{x1:cx,x2:cx,y1:pt,y2:H-pb,stroke:'var(--mut)','stroke-width':1,'stroke-dasharray':'3 3'}),el('circle',{cx,cy:Y(p[1]),r:4,fill:'var(--card)',stroke:'var(--fg)','stroke-width':2}));
  const near=tr.filter(x=>Math.abs(x[0]-p[0])<6e4).map(x=>(x[1]=='buy'?'▲ 매수 ':'▼ 매도 ')+x[3]+'주 @ $'+x[2].toFixed(2)).join('<br>');
  tip.innerHTML='<b>'+hm(p[0])+'</b> · $'+p[1].toFixed(2)+(near?'<br>'+near:'');tip.style.display='block';tip.style.left=Math.min(Math.max(cx-70,0),W-150)+'px'}else tip.style.display='none';
 box.append(s)}
const mv=e=>{const r=box.getBoundingClientRect();hover=(e.touches?e.touches[0].clientX:e.clientX)-r.left;draw()};
box.addEventListener('pointermove',mv);box.addEventListener('pointerdown',mv);box.addEventListener('pointerleave',()=>{hover=null;draw()});
document.querySelectorAll('[data-sym]').forEach(a=>a.tagName=='BUTTON'&&a.addEventListener('click',()=>{sym=a.dataset.sym;document.querySelectorAll('button[data-sym]').forEach(x=>x.classList.toggle('on',x==a));hover=null;load()}));
addEventListener('resize',draw);load();setInterval(load,10000)})();
"""

_clients: dict = {}
_bar_cache: dict = {}


def chart_data(cfg, mode: str, sym: str) -> dict:
    """차트용 1분봉(15초 캐시)과 그 종목의 체결 지점."""
    import time as _time

    from .brokers.kis import KISClient, KISMarket
    if sym not in cfg.symbols:
        return {"error": "알 수 없는 종목"}
    market_hours.ENABLED = cfg.sessions
    c = cfg.kis_real if cfg.kis_real.ok else cfg.kis_demo
    if not c.ok:
        return {"error": "KIS 키 없음"}
    hit = _bar_cache.get(sym)
    if not hit or _time.time() - hit[0] > 15:
        try:
            key = (c.env, c.app_key[-6:])
            if key not in _clients:
                _clients[key] = KISMarket(KISClient(c.app_key, c.app_secret, c.env, cfg.data_dir))
            bars = _clients[key].bars(sym, 120)
            hit = _bar_cache[sym] = (_time.time(), [[int(b.ts.timestamp() * 1000), b.close] for b in bars])
        except Exception as e:               # 차트는 부가 기능: 실패해도 페이지는 유지
            return {"error": f"{type(e).__name__}: {e}"[:200]}
    _, events, live = _read(cfg, mode)
    trades = []
    for x in events:
        if x.get("kind") in ("buy", "sell") and x.get("symbol") == sym:
            try:
                trades.append([int(datetime.fromisoformat(x["ts"]).timestamp() * 1000), x["kind"],
                               float(x.get("price", 0)), x.get("qty")])
            except (ValueError, KeyError):
                continue
    bars = hit[1]
    return {"bars": bars, "trades": trades[-60:], "last": bars[-1][1] if bars else None}


def _read(cfg, mode):
    def load(name):
        try:
            with open(os.path.join(cfg.data_dir, name), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return None
    events = []
    try:
        with open(os.path.join(cfg.data_dir, f"journal_{mode}.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return load(f"state_{mode}.json"), events, load(f"live_{mode}.json")


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

    def won(usd: float, sign: bool = True) -> str:
        return f"{usd * fx:+,.0f}원" if sign else f"{usd * fx:,.0f}원"

    def cls(v: float) -> str:
        return "up" if v > 0 else "dn" if v < 0 else "mut"

    def arrow(v: float) -> str:
        return "▲" if v > 0 else "▼" if v < 0 else ""

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
    out.append(f"<section class='card hero'><div class=k>오늘 손익{' (평가 포함)' if unreal is not None else ''}"
               f"{' · ' + e(s['date']) if s['date'] else ''}</div>"
               f"<div class='big {cls(total)}'>{arrow(total)} {won(total)}</div>"
               f"<div class=sub>{pct:+.2f}% · ${total:+.2f}"
               f"{' · 실현 ' + won(s['realized_usd']) if unreal is not None else ''}</div>"
               f"<div class=meter role=img aria-label='손실한도와 목표 사이 현재 위치'><i style='left:{lo:.1f}%;width:{hi - lo:.1f}%;background:{color}'></i>"
               f"<b style='left:{zero:.1f}%'></b></div>"
               f"<div class=ends><span>손실한도 -{cfg.daily_max_loss_krw:,.0f}</span><span>목표 +{cfg.daily_target_krw:,.0f}</span></div>"
               f"<div class=stats><div><div class=k>거래</div><div class=v>{s['trades']}회</div></div>"
               f"<div><div class=k>승 / 패</div><div class=v>{s['wins']} / {s['losses']}</div></div>"
               f"<div><div class=k>운용자금</div><div class=v>{cfg.capital_krw:,.0f}</div></div></div>"
               + (f"<div class=note>종료 사유: {e(s['halted'])}</div>" if s["halted"] else "") + "</section>")

    # ── 가격 차트
    held = o["symbol"] if o else cfg.bull
    out.append("<h2>가격 차트</h2><section class=card><div class=seg>"
               + "".join(f"<button data-sym='{e(s_)}'{' class=on' if s_ == held else ''}>{e(s_)}</button>" for s_ in cfg.symbols)
               + "<span class=lg><i class=b></i>매수 <i class=s></i>매도</span></div>"
               f"<div class=chartwrap><div id=chart data-mode='{e(mode)}' data-sym='{e(held)}'></div><div id=tip></div></div>"
               "<div id=cmsg class=note>불러오는 중…</div></section>")

    # ── 보유 포지션
    out.append("<h2>보유 포지션</h2>")
    if o:
        ent = o["entry_price"]
        last = (live or {}).get("last") if unreal is not None else None
        chg = (last / ent - 1) * 100 if last else None
        head = (f"<div class='{cls(unreal)}' style='font-size:20px;font-weight:800'>{arrow(unreal)} {won(unreal)} "
                f"<span style='font-size:14px'>({chg:+.2f}%)</span></div>") if unreal is not None and chg is not None else ""
        trail = f"<div><span>추적 손절</span> 고점 -{o['trail_pct']:.1f}%</div>" if o.get("trail_pct") else ""
        out.append(f"<section class=card><div class=pos><div class=sym>{e(o['symbol'])} <span class=mut style='font-size:15px;font-weight:600'>{o['qty']}주</span></div>{head}</div>"
                   f"<div class=kv><div><span>진입가</span> ${ent:.2f}</div><div><span>현재가</span> {'$%.2f' % last if last else '-'}</div>"
                   f"<div><span>손절</span> ${ent * (1 - o['stop_pct'] / 100):.2f} (-{o['stop_pct']:.1f}%)</div>"
                   f"<div><span>익절</span> ${ent * (1 + o['take_pct'] / 100):.2f} (+{o['take_pct']:.1f}%)</div>"
                   f"<div><span>진입</span> {_kst(o['entry_ts'])}</div>{trail}</div></section>")
    else:
        out.append("<section class=card><span class=mut>없음 (현금 대기)</span></section>")

    # ── 시스템 기록 (주문 테스트 결과, 오류)
    system = [x for x in events if x.get("kind") in ("ordertest", "error")][-6:][::-1]
    if system:
        out.append("<h2>시스템 기록 (한국시간)</h2><section class='card feed'>")
        for x in system:
            if x["kind"] == "ordertest":
                title = f"주문 테스트 {'통과' if x.get('ok') else '실패'}" + (f" ({x.get('attempt')}회차)" if x.get("attempt") else "")
            else:
                title = "오류"
            out.append(f"<div class=row><div class=t>{_kst(x['ts'], '%m-%d %H:%M')[6:]}<br>{_kst(x['ts'], '%m-%d')}</div><div><div class=h><span>{e(title)}</span></div>"
                       f"<div class=r>{e(str(x.get('detail', '')))}</div></div></div>")
        out.append("</section>")

    # ── 체결
    trades = [x for x in events if x.get("kind") in ("buy", "sell")][-30:][::-1]
    if trades:
        out.append("<h2>최근 체결 (한국시간)</h2><section class='card feed'>")
        for x in trades:
            buy = x["kind"] == "buy"
            pnl = x.get("pnl_usd", 0)
            right = "" if buy else f"<span class='{cls(pnl)}'>{arrow(pnl)} {won(pnl)}</span>"
            out.append(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div><div class=h><span>"
                       f"<span class='tag {'buy' if buy else 'sell'}'>{'매수' if buy else '매도'}</span> "
                       f"{e(str(x.get('symbol')))} {x.get('qty')}주 @ ${x.get('price', 0):.2f}</span>{right}</div>"
                       f"<div class=r>{e(str(x.get('reason', '')))}</div></div></div>")
        out.append("</section>")

    # ── AI 판단
    decisions = [x for x in events if x.get("kind") == "decision"][-25:][::-1]
    if decisions:
        out.append("<h2>AI 판단 기록 (한국시간)</h2><section class='card feed'>")
        for x in decisions:
            act = x.get("action", "")
            kind = "buy" if act == "BUY" else "sell" if act == "SELL" else ""
            out.append(f"<div class=row><div class=t>{_kst(x['ts'])}</div><div><div class=h><span>"
                       f"<span class='tag {kind}'>{ACTION.get(act, e(str(act)))}</span> {e(str(x.get('symbol') or ''))}</span>"
                       f"<span class=mut style='font-weight:500;font-size:13px'>확신 {x.get('confidence', 0) * 100:.0f}%</span></div>"
                       f"<div class=r>{e(str(x.get('reason', '')))}</div></div></div>")
        out.append("</section>")

    # ── 일별
    sells = [x for x in events if x.get("kind") == "sell"]
    if sells:
        days = defaultdict(lambda: [0.0, 0, 0])
        for x in sells:
            d = days[x["ts"][:10]]
            d[0] += x.get("pnl_usd", 0)
            d[1] += 1
            d[2] += x.get("pnl_usd", 0) >= 0
        cum = sum(d[0] for d in days.values())
        out.append(f"<h2>일별 손익 · 누적 <span class='{cls(cum)}'>{won(cum)}</span></h2><section class=card><table>"
                   "<tr><th>날짜(미국)</th><th class=r>손익</th><th class=r>수익률</th><th class=r>청산</th><th class=r>승률</th></tr>")
        for day in sorted(days, reverse=True)[:60]:
            p, n, w = days[day]
            out.append(f"<tr><td>{e(day[5:])}</td><td class='r {cls(p)}'>{won(p)}</td>"
                       f"<td class='r {cls(p)}'>{p / cfg.capital_usd * 100:+.1f}%</td><td class=r>{n}</td><td class=r>{w / n * 100:.0f}%</td></tr>")
        out.append("</table></section>")

    if not state and not events:
        out.append("<div class='card note' style='margin-top:14px'>아직 기록이 없습니다. 이 모드로 장이 열린 적이 없습니다.</div>")
    model = (live or {}).get("model") or cfg.model
    out.append(f"<footer>{now:%m-%d %H:%M:%S} 기준 · 2분마다 자동 새로고침 · ● 실행 중인 모드<br>"
               f"차트는 10초마다 갱신 · 환율 {fx:,.0f}원 환산 · 수수료 편도 {cfg.fee_pct}% 반영 · AI {e(model)} · 정규장 한국시간 23:30~06:00 (서머타임 22:30~05:00)"
               f"{' · 주간거래 10:00~17:15' if 'day' in cfg.sessions else ''}"
               f"{' · 프리마켓 18:00~23:25' if 'pre' in cfg.sessions else ''}</footer></main>"
               f"<script>{CHART_JS}</script>")
    return "".join(out)


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
            if u.path == "/data":
                body = json.dumps(chart_data(cfg, mode, q.get("sym", [cfg.bull])[0])).encode()
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
    print(f"결과 페이지: 포트 {port}")
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(token)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
