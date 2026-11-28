"""신호 장부: 봇이 본 진입 신호(산 것 + 걸러서 안 산 것)에 '그때 샀다면' 결과를 붙인다.

엔진이 data/signals_{모드}.jsonl 에 신호를 적고(engine._signal), 웹 서버가 모아 둔 1분봉으로
결과를 계산해 data/signals_res_{모드}.jsonl 에 따로 적는다 (같은 파일을 두 프로세스가 고치지 않게).
결과 = 신호 가격에 사서 손절·익절·보유 시간·장 마감(15:55) 중 먼저 오는 것에 판 손익 − 비용 0.6%.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from . import market_hours

log = logging.getLogger(__name__)
COST_PCT = 0.6


def _path(cfg, mode: str, res: bool = False) -> str:
    return os.path.join(cfg.data_dir, f"signals_{'res_' if res else ''}{mode}.jsonl")


def _read(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def sid(sig: dict) -> str:
    return f"{sig['ts']}|{sig['kind']}|{sig['symbol']}|{int(sig.get('taken', False))}"


def simulate(sig: dict, bars: list[list], now_ms: float) -> dict | None:
    """bars: [[시각ms, 시가, 고가, 저가, 종가, 거래량], ...] (그 종목 1분봉). 아직 결론이 안 났으면 None."""
    t0 = datetime.fromisoformat(sig["ts"])
    start_ms = (t0.replace(second=0, microsecond=0) + timedelta(minutes=1)).timestamp() * 1000
    et = t0.astimezone(market_hours.ET)
    close_ms = et.replace(hour=15, minute=55, second=0, microsecond=0).timestamp() * 1000
    end_ms = close_ms
    if sig.get("hold_min"):
        end_ms = min(end_ms, start_ms + sig["hold_min"] * 60_000)
    ref = sig["ref"]
    stop = ref * (1 - sig["stop_pct"] / 100)
    take = ref * (1 + sig["take_pct"] / 100)
    last = None
    for t, o, h, l, c, *_ in bars:
        if t < start_ms:
            continue
        if t >= end_ms:
            break
        if l <= stop:
            return {"pct": round((min(o, stop) / ref - 1) * 100 - COST_PCT, 3), "exit": "손절", "at": int(t)}
        if h >= take:
            return {"pct": round((max(o, take) / ref - 1) * 100 - COST_PCT, 3), "exit": "익절", "at": int(t)}
        last = (t, c)
    if now_ms < end_ms + 120_000 or last is None:
        return None                                   # 아직 보유 시간이 안 끝났거나 봉이 없음
    return {"pct": round((last[1] / ref - 1) * 100 - COST_PCT, 3),
            "exit": "시간 정리" if end_ms < close_ms else "장 마감", "at": int(last[0])}


def label(cfg, mode: str, get_bars, now: float | None = None) -> int:
    """결과가 아직 없는 신호에 결과를 붙인다. get_bars(종목, since초) → 1분봉 목록. 새로 붙인 개수."""
    now = time.time() if now is None else now
    sigs = _read(_path(cfg, mode))
    done = {r["id"] for r in _read(_path(cfg, mode, True))}
    new = []
    for s in sigs:
        i = sid(s)
        if i in done:
            continue
        t0 = datetime.fromisoformat(s["ts"]).timestamp()
        if now - t0 > 4 * 86400:                      # 1분봉 저장소에 없는 오래된 신호
            new.append({"id": i, "pct": None, "exit": "봉 없음"})
            continue
        r = simulate(s, get_bars(s["symbol"], t0 - 120), now * 1000)
        if r:
            new.append({"id": i, **r})
    if new:
        with open(_path(cfg, mode, True), "a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


def rows(cfg, mode: str) -> list[dict]:
    """신호 + 결과(있으면), 오래된 순."""
    res = {r["id"]: r for r in _read(_path(cfg, mode, True))}
    out = []
    for s in _read(_path(cfg, mode)):
        r = res.get(sid(s))
        out.append({**s, "res": r if r and r.get("pct") is not None else None})
    return out


def summary(rs: list[dict]) -> list[dict]:
    """종류 × 산 것/거른 것 별: 신호 수, 결과 난 수, 평균, 승률."""
    out = []
    for kind in ("fade", "orb", "box"):
        for taken in (True, False):
            g = [r for r in rs if r["kind"] == kind and bool(r.get("taken")) == taken]
            if not g:
                continue
            v = [r["res"]["pct"] for r in g if r["res"]]
            out.append({"kind": kind, "taken": taken, "n": len(g), "done": len(v),
                        "avg": sum(v) / len(v) if v else None, "win": sum(x > 0 for x in v) / len(v) if v else None})
    return out


def labeler(store, modes_fn, cfg_fn, stop: threading.Event, every: float = 300) -> None:
    """웹 서버 백그라운드: 5분마다 모든 모드의 신호에 결과를 붙인다."""
    while not stop.is_set():
        try:
            for m in modes_fn():
                n = label(cfg_fn(m), m, store.get)
                if n:
                    log.info("신호 장부 %s: 결과 %d건 추가", m, n)
        except Exception as e:
            log.info("신호 장부 결과 계산 실패: %s", e)
        stop.wait(every)
