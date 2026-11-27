"""결과 페이지용 데이터: 기록 파일 읽기, 매수·매도를 거래 단위로 묶기, 계좌 잔고 조회, 1분봉 저장소."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime

from . import config, extbox, market_hours

log = logging.getLogger("web")
_kis_lock = threading.Lock()          # 페이지 요청과 백그라운드 수집이 KIS 클라이언트를 같이 쓰므로 직렬화
_clients: dict = {}
_acct_cache: dict = {}


def read(cfg, mode: str):
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


def activity(cfg, mode: str, n: int = 60) -> list[dict]:
    """활동 기록 끝부분만 읽는다 (파일이 커도 빠르게)."""
    path = os.path.join(cfg.data_dir, f"activity_{mode}.jsonl")
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 60_000))
            raw = f.read().decode("utf-8", "ignore").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in raw[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _mins(a: str, b: str) -> float | None:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60
    except ValueError:
        return None


def round_trips(events: list[dict], fee_pct: float) -> tuple[list[dict], list[dict]]:
    """매수 기록과 매도 기록을 먼저 산 것부터(FIFO) 짝지어 거래 단위로 묶는다.
    돌려주는 값: (끝난 거래들, 아직 안 판 매수 묶음들)."""
    lots: dict[str, list[dict]] = {}
    trips = []
    for x in events:
        k = x.get("kind")
        if k == "buy":
            lots.setdefault(x["symbol"], []).append({"qty": int(x["qty"]), "price": float(x["price"]),
                                                    "ts": x["ts"], "reason": x.get("reason", "")})
        elif k == "sell":
            sym, qty, px = x["symbol"], int(x["qty"]), float(x["price"])
            left, parts, bucket = qty, [], lots.get(sym, [])
            while left > 0 and bucket:
                lot = bucket[0]
                take = min(left, lot["qty"])
                parts.append((take, lot["price"], lot["ts"], lot["reason"]))
                lot["qty"] -= take
                left -= take
                if lot["qty"] == 0:
                    bucket.pop(0)
            sell_amt = px * qty
            if parts:
                q = sum(p[0] for p in parts)
                buy_px = sum(p[0] * p[1] for p in parts) / q
            else:                                     # 매수 기록이 없는 매도(기록 시작 전 보유분 등)
                buy_px = None
            buy_amt = buy_px * qty if buy_px else None
            fees = (sell_amt + (buy_amt or 0)) * fee_pct / 100
            pnl = x.get("pnl_usd")
            if pnl is None and buy_amt:
                pnl = sell_amt - buy_amt - fees
            trips.append({"symbol": sym, "qty": qty, "buy_ts": parts[0][2] if parts else None, "buy_px": buy_px,
                          "buy_amt": buy_amt, "buy_reason": parts[0][3] if parts else "",
                          "sell_ts": x["ts"], "sell_px": px, "sell_amt": sell_amt, "fees": fees, "pnl": pnl,
                          "pct": pnl / buy_amt * 100 if pnl is not None and buy_amt else None,
                          "hold_min": _mins(parts[0][2], x["ts"]) if parts else None,
                          "sell_reason": x.get("reason", "")})
    still = [dict(symbol=s, **lot) for s, b in lots.items() for lot in b if lot["qty"] > 0]
    return trips, still


def _client(cfg, creds):
    from .brokers.kis import KISClient
    key = (creds.env, creds.app_key[-6:])
    if key not in _clients:
        _clients[key] = KISClient(creds.app_key, creds.app_secret, creds.env, cfg.data_dir)
    return _clients[key]


def market(cfg):
    from .brokers.kis import KISMarket
    c = cfg.kis_real if cfg.kis_real.ok else cfg.kis_demo
    return KISMarket(_client(cfg, c)) if c.ok else None


def _fetch_account(cfg, mode: str) -> dict:
    """증권사 잔고 조회 (느릴 수 있으므로 백그라운드에서만 부른다)."""
    from .brokers.kis import KISBroker
    creds = cfg.kis_demo if mode == "kis-demo" else cfg.kis_real
    if not (creds.ok and len(creds.account_no) == 8):
        return {"source": "증권사 잔고", "holdings": [], "error": "키 또는 계좌번호 없음", "at": time.time()}
    try:
        if not _kis_lock.acquire(timeout=30):
            raise TimeoutError("다른 조회가 끝나지 않음")
        try:
            br = KISBroker(_client(cfg, creds), creds.account_no, creds.account_product)
            holds = br.holdings()
            try:
                cash = br.buying_power(cfg.bull, 1.0)
            except Exception as e:                # 주문가능금액은 부가 정보
                log.info("주문가능금액 조회 실패: %s", e)
                cash = None
            try:
                summary = br.account_summary()
            except Exception as e:                # 계좌 총자산도 부가 정보
                log.info("계좌 자산 조회 실패: %s", e)
                summary = {"error": f"{type(e).__name__}: {e}"[:160]}
        finally:
            _kis_lock.release()
        return {"source": "증권사 잔고 (한국투자증권)", "holdings": holds, "cash": cash, "summary": summary, "at": time.time()}
    except Exception as e:
        return {"source": "증권사 잔고", "holdings": [], "error": f"{type(e).__name__}: {e}"[:200], "at": time.time()}


def account_refresher(stop: threading.Event, every: float = 30) -> None:
    """모의투자·실계좌 잔고를 주기적으로 미리 조회해 둔다. 페이지는 이 값만 읽으므로 멈추지 않는다."""
    while not stop.is_set():
        try:
            base = config.load()
            for m in base.modes:
                if m != "paper":
                    _acct_cache[m] = _fetch_account(config.load(m), m)
        except Exception as e:
            log.warning("잔고 갱신 실패: %s", e)
        stop.wait(every)


def account(cfg, mode: str, state: dict | None, live: dict | None) -> dict:
    """보유 종목. 가상매매는 봇 장부, 모의투자·실계좌는 백그라운드에서 받아 둔 증권사 잔고."""
    o = (state or {}).get("open")
    if mode == "paper":
        holds = []
        if o:
            last = (live or {}).get("last")
            holds.append({"symbol": o["symbol"], "name": "", "qty": o["qty"], "avg": o["entry_price"], "last": last,
                          "value": last * o["qty"] if last else None,
                          "pnl": None, "pnl_pct": None, "bot": True})
        return {"source": "봇 장부 (가상 체결)", "holdings": holds, "cash": None}
    res = _acct_cache.get(mode)
    if res is None:
        return {"source": "증권사 잔고", "holdings": [], "loading": True}
    bot_sym = o["symbol"] if o else None
    res = {**res, "holdings": [{**h, "bot": h["symbol"] == bot_sym} for h in res["holdings"]]}
    if o and not any(h["bot"] for h in res["holdings"]) and not res.get("error"):
        res["mismatch"] = f"봇 장부에는 {o['symbol']} {o['qty']}주가 있는데 증권사 잔고에는 없습니다"
    return res


class BarStore:
    """1분봉 저장소. KIS 는 한 번에 최근 120개만 주므로, 1분마다 받아 합쳐서 하루 전체를 만든다."""

    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, dict[int, list]] = {}
        self.lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                self.data = {s: {int(t): v for t, v in d.items()} for s, d in json.load(f).items()}
        except (FileNotFoundError, ValueError):
            pass

    def merge(self, sym: str, bars) -> None:
        with self.lock:
            d = self.data.setdefault(sym, {})
            for b in bars:
                d[int(b.ts.timestamp())] = [b.open, b.high, b.low, b.close, b.volume]
            cut = (max(d) if d else time.time()) - 4 * 86400     # 가장 최근 봉 기준 4일만 보관
            for t in [t for t in d if t < cut]:
                del d[t]

    def get(self, sym: str, since: float) -> list[list]:
        with self.lock:
            d = self.data.get(sym, {})
            return [[t * 1000, *d[t]] for t in sorted(d) if t >= since]

    def save(self) -> None:
        with self.lock:
            snap = {s: {str(t): v for t, v in d.items()} for s, d in self.data.items()}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        os.replace(tmp, self.path)


def collector(store: BarStore, stop: threading.Event) -> None:
    """실행 중인 모든 모드의 매매 종목 1분봉을 1분마다 저장소에 모은다."""
    last_save = 0.0
    while not stop.is_set():
        try:
            cfg = config.load()
            market_hours.ENABLED = cfg.sessions
            cfgs = [config.load(m) for m in cfg.modes]
            market_hours.ENABLED = tuple(sorted({x for c in cfgs for x in c.sessions}))
            syms = sorted({s for c in cfgs for s in c.symbols})
            now = market_hours.now_et()
            es = extbox.session(now)
            ext = es is not None                             # 시간외 탭: 봇이 쉬어도 프리·애프터·주간거래 시세를 모은다
            if ext:
                p = config.load("paper")
                syms = sorted(set(syms) | {p.bull, p.bear} - {""})
                _enable_day(es)
            mk = market(cfg)
            if mk and (ext or market_hours.is_open(now) or not any(store.data.get(s) for s in syms)):
                for s in syms:
                    if not _kis_lock.acquire(timeout=20):
                        continue
                    try:
                        bars = mk.bars(s, 120)
                    finally:
                        _kis_lock.release()
                    store.merge(s, bars)
                    if es and es[0] == "day" and s == p.bull:
                        extbox.save_day_bars(ext_day_path(p), bars)
            if time.time() - last_save > 300:
                store.save()
                last_save = time.time()
        except Exception as e:
            log.warning("1분봉 수집 실패: %s", e)
        stop.wait(60)


def _levels_from_bars(cfg, store: BarStore, sess, now) -> dict:
    """봇 상태 파일에 경계가 없을 때를 대비해, 모아 둔 1분봉과 노이즈 기록으로 직접 계산한다."""
    out: dict = {}
    o0 = sess.open.timestamp()
    lb = store.get(cfg.bull, o0)
    end = o0 + cfg.orb_minutes * 60
    rb = [b for b in lb if b[0] / 1000 < end]
    if now.timestamp() < end or len(rb) < cfg.orb_minutes * 0.7:
        return out
    hh, ll = max(b[2] for b in rb), min(b[3] for b in rb)
    out.update(hh=hh, ll=ll, symbol=cfg.bull, src="1분봉 계산")
    broke = any(b[4] > hh or b[4] < ll for b in lb if b[0] / 1000 >= end)
    w, mid = hh - ll, (hh + ll) / 2
    if cfg.box and not broke and w / mid * 100 >= cfg.box_min_width:
        out["box"] = [round(ll + cfg.box_zone * w, 4), round(hh - cfg.box_zone * w, 4)]
    if cfg.noise and lb and lb[0][0] / 1000 < o0 + 120:
        from .noise import NoiseBook
        book = NoiseBook(os.path.join(cfg.data_dir, f"noise_{cfg.bull}.json"))
        since = (min(now.timestamp(), sess.close.timestamp()) - o0) / 60
        cp = int(since // cfg.noise_every) * cfg.noise_every
        day = sess.key
        sigma = book.sigma(day, cp, cfg.noise_lookback) if cp >= cfg.noise_every else None
        if sigma:
            base = lb[0][1]
            pc = book.prev_close(day) or base
            out["noise"] = [round(min(base, pc) * (1 - sigma), 4), round(max(base, pc) * (1 + sigma), 4)]
    return out


def chart(cfg, mode: str, sym: str, span: int, store: BarStore, state, live, events) -> dict:
    """차트 데이터: 1분봉(OHLCV), 세션 VWAP, 매매 지점, 보유 중이면 진입·손절·익절·추적선, 개장 범위."""
    if sym not in cfg.symbols:
        return {"error": "알 수 없는 종목"}
    market_hours.ENABLED = tuple(sorted(set(config.load().sessions) | set(cfg.sessions)))
    now = market_hours.now_et()
    mk = market(cfg) if _due(sym) else None           # 같은 종목은 15초에 한 번만 증권사에 다시 묻는다
    if mk and _kis_lock.acquire(timeout=0.5):         # 다른 조회 중이면 기다리지 않고 모아 둔 봉으로 그린다
        try:
            store.merge(sym, mk.bars(sym, 120))
        except Exception as e:
            log.info("차트 1분봉 조회 실패: %s", e)
        finally:
            _kis_lock.release()
    sess = market_hours.last_session(now)
    sess_open = sess.open.timestamp() if sess else now.timestamp() - 6.5 * 3600
    since = now.timestamp() - 18 * 3600                # 드래그로 지난 시간도 보도록 넉넉히 (처음 보이는 범위는 화면이 span 으로 정함)
    allb = store.get(sym, min(since, sess_open))[-1100:]
    pv = vv = 0.0
    vwap = {}
    for t, o, h, l, c, v in allb:
        if t / 1000 >= sess_open:
            pv += (h + l + c) / 3 * (v or 1)
            vv += v or 1
            vwap[t] = round(pv / vv, 4)
    bars = [b for b in allb if b[0] / 1000 >= since]
    marks = []
    trips, _ = round_trips(events, cfg.fee_pct)
    for x in events:
        if x.get("kind") in ("buy", "sell") and x.get("symbol") == sym:
            try:
                t = int(datetime.fromisoformat(x["ts"]).timestamp() * 1000)
            except (ValueError, KeyError):
                continue
            if t >= since * 1000:
                marks.append({"t": t, "k": x["kind"], "p": float(x.get("price", 0)), "q": x.get("qty"),
                              "pnl": x.get("pnl_usd"), "why": str(x.get("reason", ""))[:80]})
    lines = []
    o = (state or {}).get("open")
    if o and o.get("symbol") == sym:
        ent = o["entry_price"]
        lines += [{"v": ent, "k": "entry", "l": "진입"},
                  {"v": round(ent * (1 - o["stop_pct"] / 100), 4), "k": "stop", "l": f"손절 -{o['stop_pct']:.1f}%"},
                  {"v": round(ent * (1 + o["take_pct"] / 100), 4), "k": "take", "l": f"익절 +{o['take_pct']:.1f}%"}]
        tr = o.get("trail_pct") or 0
        if tr:
            peak = o.get("peak_price") or ent
            if (peak / ent - 1) * 100 >= tr + 2 * cfg.fee_pct:
                lines.append({"v": round(peak * (1 - tr / 100), 4), "k": "trail", "l": f"추적 청산선 (고점 -{tr}%)"})
            else:
                lines.append({"v": round(ent * (1 + (tr + 2 * cfg.fee_pct) / 100), 4), "k": "trail",
                              "l": "추적 손절 시작선"})
    orb = dict((live or {}).get("orb") or {})
    ext = extbox.session(now)
    if ext or not (sess and sess.name == "regular"):
        orb = {}                                      # 정규장 범위는 정규장에서만 그린다 (시간외 시세 위에 지난 범위가 겹쳐 보이던 문제)
    elif cfg.strategy == "orb":
        orb = {**_levels_from_bars(cfg, store, sess, now), **{k: v for k, v in orb.items() if v}}
    if orb.get("box_off"):                            # 봇이 오늘 박스권을 더 안 한다고 알려 주면 구간을 그리지 않는다
        orb.pop("box", None)
    rng = [orb["ll"], orb["hh"]] if orb.get("hh") and orb.get("symbol") == sym else None
    note, bands = None, []
    if rng:                                           # SOXL 차트에만: 개장 범위와 박스권 매수 시도 구간
        lines += [{"v": orb["hh"], "k": "rng", "l": "범위 상단"}, {"v": orb["ll"], "k": "rng", "l": "범위 하단"}]
        if orb.get("box"):
            lo, hi = orb["box"]
            lines += [{"v": hi, "k": "bxs", "l": f"{cfg.bear} 매수 시도 구간 (이 위 ~ 범위 상단)"},
                      {"v": lo, "k": "bxl", "l": f"{cfg.bull} 매수 시도 구간 (이 아래 ~ 범위 하단)"}]
            bands = [{"lo": orb["ll"], "hi": lo, "k": "bl"}, {"lo": hi, "hi": orb["hh"], "k": "bs"}]
        elif orb.get("box_off"):
            note = "박스권: " + orb["box_off"]
    rng_t = None
    if ext and cfg.ext_strategy == "box" and ext[0] in cfg.sessions and sym == cfg.bull:
        bx, brk = extbox.live_box(store.get(sym, now.timestamp() - 6 * 3600))   # 봇이 쓰는 것과 같은 시간외 고정 박스
        if bx:
            hi, lo = bx["hi"], bx["lo"]
            lv, sig = extbox.box_levels(hi, lo), hi - extbox.ZONE * (hi - lo)
            rng, rng_t = [lo, hi], bx["start"] * 1000
            lines += [{"v": round(hi, 4), "k": "rng", "l": "시간외 박스 상단"}, {"v": round(lo, 4), "k": "rng", "l": "시간외 박스 하단"},
                      {"v": round(sig, 4), "k": "bxs", "l": f"이 위면 {cfg.bear} 매수"},
                      {"v": round(lv["buy_max"], 4), "k": "bxl", "l": f"이 아래면 {cfg.bull} 매수"}]
            bands = [{"lo": lo, "hi": lv["buy_max"], "k": "bl"}, {"lo": sig, "hi": hi, "k": "bs"}]
        else:
            note = "시간외 박스 없음 — 위·아래 경계에 2번씩 닿는 옆걸음 구간이 생기면 그립니다" + (
                f" (최근 박스는 {'위' if brk['dir'] == 'up' else '아래'}로 뚫림)" if brk else "")
    from . import board
    fc = board.REC.view(sym, "1m", bars[0][0]) if bars and board.REC else None
    return {"sym": sym, "bars": bars, "vwap": [vwap.get(b[0]) for b in bars], "marks": marks, "lines": lines,
            "range": rng, "range_t": rng_t, "bands": bands, "last": bars[-1][4] if bars else None, "fx": cfg.usdkrw, "note": note,
            "fc": fc}


_yahoo_at: dict = {}


def _enable_day(es) -> None:
    """주간거래 중이면 KIS 주간거래 시세 코드(BAA 등)를 쓰도록 세션 목록에 넣는다 (봇 설정과 무관하게)."""
    if es and es[0] == "day" and "day" not in market_hours.ENABLED:
        market_hours.ENABLED = tuple(sorted(set(market_hours.ENABLED) | {"day"}))


_fetched: dict = {}


def _due(sym: str, every: float = 15) -> bool:
    """여러 화면이 10초마다 새로 그려도 증권사 조회는 종목당 15초에 한 번 (화면이 조회를 기다리지 않게)."""
    t = time.time()
    if t - _fetched.get(sym, 0) < every:
        return False
    _fetched[sym] = t
    return True


def ext_day_path(cfg) -> str:
    return os.path.join(cfg.data_dir, f"ext_day_{cfg.bull}.json")


def ext_hist_path(cfg) -> str:
    return os.path.join(cfg.data_dir, f"ext_hist_{cfg.bull}.json")


def ext_chart(cfg, sym: str, span: int, store: BarStore, x: float) -> dict:
    """시간외 탭 차트: 두 종목 각자의 고정 박스, 확률이 높은 쪽 종목에 목표·손절선. 'advice' 는 화면 카드용."""
    bull, bear = cfg.bull, cfg.bear
    if sym not in (bull, bear):
        return {"error": "알 수 없는 종목"}
    if x not in extbox.X_CHOICES:
        x = extbox.X_CHOICES[0]
    now = market_hours.now_et()
    _enable_day(extbox.session(now))
    mk = market(cfg)
    book = {}
    if mk and _kis_lock.acquire(timeout=2):
        try:
            for s in (bull, bear):
                store.merge(s, mk.bars(s, 120))
            if extbox.session(now):
                for s in (bull, bear):
                    book[s] = mk.book(s)                 # 지금 호가 차이 = 직접 사고팔 때의 실제 비용
        except Exception as e:
            log.info("시간외 1분봉·호가 조회 실패: %s", e)
        finally:
            _kis_lock.release()
    sess = extbox.session(now)
    t = now.timestamp()
    note = None
    if sess and sess[0] != "day" and not store.get(bull, t - 180):   # 증권사 분봉에 시간외가 없으면 야후 1분봉 (주간거래는 야후에 없음)
        for s in (bull, bear):
            if t - _yahoo_at.get(s, 0) >= 60:
                _yahoo_at[s] = t
                try:
                    store.merge(s, extbox.yahoo_1m(s))
                except Exception as e:
                    log.info("야후 1분봉 실패 %s: %s", s, e)
        note = "시세: 야후 (증권사 시간외 분봉이 비어 있음)"
    bars = store.get(sym, t - 18 * 3600)[-1100:]
    back = t - 6 * 3600                               # 박스는 최대 3시간짜리라 넉넉히
    adv = extbox.advice(store.get(bull, back), store.get(bear, back), now, ext_hist_path(cfg), x, cfg.fee_pct,
                        ext_day_path(cfg))
    adv["book"] = {k: v for k, v in book.items() if v}
    lines, rng, bands, rng_t = [], None, [], None
    r4 = lambda v: round(v, 4)   # noqa: E731
    if sym == bull and adv.get("hi"):
        hi, lo, lv = adv["hi"], adv["lo"], adv["bull_lv"]
        rng, rng_t = [lo, hi], adv["box_start"]
        sell_sig = hi - extbox.ZONE * (hi - lo)
        lines += [{"v": r4(hi), "k": "rng", "l": "박스 상단"}, {"v": r4(lo), "k": "rng", "l": "박스 하단"},
                  {"v": r4(sell_sig), "k": "bxs", "l": f"이 위면 {bear} 매수"}, {"v": r4(lv["buy_max"]), "k": "bxl", "l": f"이 아래면 {bull} 매수"}]
        bands = [{"lo": lo, "hi": lv["buy_max"], "k": "bl"}, {"lo": sell_sig, "hi": hi, "k": "bs"}]
    if sym == bear and adv.get("bear_hi"):
        hi, lo, lv = adv["bear_hi"], adv["bear_lo"], adv["bear_lv"]
        rng, rng_t = [lo, hi], adv["bear_start"]
        lines += [{"v": r4(hi), "k": "rng", "l": "박스 상단"}, {"v": r4(lo), "k": "rng", "l": "박스 하단"},
                  {"v": r4(lv["buy_max"]), "k": "bxs", "l": f"{bear} 매수 구간 (이 아래)"}]
        bands = [{"lo": lo, "hi": lv["buy_max"], "k": "bs"}]
    rec = adv.get("rec")
    if rec and sym == (bull if rec == "bull" else bear):
        lv = adv["bull_lv" if rec == "bull" else "bear_lv"]
        lines += [{"v": r4(lv["target"]), "k": "take", "l": "매도 목표"}, {"v": r4(lv["stop"]), "k": "stop", "l": "손절"}]
    from . import board
    fc = board.REC.view(sym, "1m", bars[0][0]) if bars and board.REC else None
    return {"sym": sym, "bars": bars, "vwap": [None] * len(bars), "marks": [], "lines": lines, "range": rng, "fc": fc,
            "range_t": rng_t * 1000 if rng_t else None, "bands": bands, "last": bars[-1][4] if bars else None, "fx": cfg.usdkrw, "note": note, "advice": adv}


def board_book(cfg, sym: str) -> dict:
    """차트 탭 호가창 (한국투자증권). 주간거래 시간에는 주간거래 시세 코드로."""
    _enable_day(extbox.session(market_hours.now_et()))
    mk = market(cfg)
    if not mk:
        return {"error": "한국투자증권 키 없음"}
    if not _kis_lock.acquire(timeout=3):
        return {"error": "다른 조회 중 (잠시 뒤 자동으로 다시 시도)"}
    try:
        return mk.book_levels(sym)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:160]}
    finally:
        _kis_lock.release()


def board_recent(cfg, store: BarStore, sym: str) -> list[list]:
    """차트 탭용 최근 1분봉: 모아 둔 봉 + (모아 둔 게 1분 넘게 지났으면) 지금 한국투자증권에서 받은 봉."""
    now = market_hours.now_et()
    _enable_day(extbox.session(now))
    mk = market(cfg) if _due(sym) else None                  # 같은 종목은 15초에 한 번만 증권사에 다시 묻는다
    if mk and _kis_lock.acquire(timeout=0.5):
        try:
            store.merge(sym, mk.bars(sym, 120))
        except Exception as e:
            log.info("차트 탭 1분봉 조회 실패 %s: %s", sym, e)
        finally:
            _kis_lock.release()
    return store.get(sym, now.timestamp() - 2 * 86400)
