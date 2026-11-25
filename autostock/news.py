"""뉴스 호재·악재로 SOXL / SOXS 중 하나 고르기 (가상매매 실험).

주간거래 시작과 프리마켓 시작 때 한 번씩(하루 2번) 야후 뉴스 검색에서 엔비디아·반도체 기사 제목을 모아
Claude 에게 '오늘 반도체가 오를지 내릴지'를 묻는다. 고른 종목과 근거를 기록해 두고, 나중에 실제 결과와 비교한다.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("news")
QUERIES = ("NVDA", "SOXL", "semiconductor stocks")

SYSTEM = """\
당신은 미국 반도체 3배 레버리지 ETF {bull}(오르면 이익)와 {bear}(내리면 이익) 중 하나를 고르는 뉴스 판단 모듈입니다.
최근 기사 제목들(발행 시각, 매체)을 읽고, 다음 미국 정규장에서 반도체 지수가 오를 가능성이 큰지 내릴 가능성이 큰지 판단하세요.
- 엔비디아·대형 반도체 실적, 가이던스, 수출 규제, 금리·물가 지표, AI 투자 뉴스를 중시하세요.
- 이미 오래된 뉴스나 가격에 반영됐을 법한 뉴스(예: '어제 급등')는 약하게 보세요.
- 뚜렷한 쪽이 없으면 NEUTRAL 을 고르세요. 억지로 고르지 마세요.
- strength 는 0~1 (0.5 미만이면 약한 근거)."""


class NewsPick(BaseModel):
    pick: Literal["SOXL", "SOXS", "NEUTRAL"] = Field(description="오를 것 같으면 SOXL, 내릴 것 같으면 SOXS, 모르겠으면 NEUTRAL")
    strength: float = Field(description="근거의 세기 0~1")
    reason: str = Field(description="판단 근거 한두 문장 (한국어)")


def headlines(max_age_h: float = 18, timeout: float = 10) -> list[dict]:
    """야후 뉴스 검색에서 최근 기사 제목 (중복 제거, 최신순)."""
    seen, out = set(), []
    cut = time.time() - max_age_h * 3600
    for q in QUERIES:
        url = "https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode(
            {"q": q, "newsCount": 10, "quotesCount": 0})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
                items = json.load(r).get("news") or []
        except Exception as e:
            log.info("뉴스 검색 실패 %s: %s", q, e)
            continue
        for n in items:
            t = (n.get("title") or "").strip()
            ts = n.get("providerPublishTime") or 0
            if t and t not in seen and ts >= cut:
                seen.add(t)
                out.append({"ts": ts, "publisher": n.get("publisher", ""), "title": t})
    return sorted(out, key=lambda x: -x["ts"])[:20]


def judge(cfg, heads: list[dict], client=None) -> NewsPick:
    import anthropic
    client = client or anthropic.Anthropic(timeout=90.0, max_retries=1)
    text = "\n".join(f"- {datetime.fromtimestamp(h['ts']).strftime('%m-%d %H:%M')} UTC · {h['publisher']} · {h['title']}"
                     for h in heads)
    resp = client.messages.parse(model=cfg.model, max_tokens=4000,
                                 system=SYSTEM.format(bull=cfg.bull, bear=cfg.bear or "SOXS"),
                                 output_format=NewsPick,
                                 messages=[{"role": "user", "content": f"최근 기사 제목:\n{text}"}])
    if resp.parsed_output is None:
        raise ValueError(f"뉴스 판단 응답 없음 (stop_reason={resp.stop_reason})")
    return resp.parsed_output


class NewsBook:
    """세션(주간거래·프리마켓)마다 한 번 판단하고 기록한다. 판단 실패 시 그 세션은 NEUTRAL."""

    def __init__(self, path: str):
        self.path = path
        self.cache: dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        x = json.loads(line)
                        self.cache[x["key"]] = x
                    except (ValueError, KeyError):
                        continue
        except FileNotFoundError:
            pass

    def get(self, key: str, cfg, fetch=None, judge_fn=None) -> dict:
        if key in self.cache:
            return self.cache[key]
        fetch, judge_fn = fetch or headlines, judge_fn or judge
        heads = fetch()
        try:
            p = judge_fn(cfg, heads) if heads else NewsPick(pick="NEUTRAL", strength=0, reason="최근 기사 없음")
        except Exception as e:
            log.warning("뉴스 판단 실패: %s", e)
            p = NewsPick(pick="NEUTRAL", strength=0, reason=f"판단 실패: {type(e).__name__}")
        rec = {"key": key, "ts": datetime.now().astimezone().isoformat(), **p.model_dump(),
               "headlines": [h["title"] for h in heads[:8]]}
        self.cache[key] = rec
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.info("뉴스 판단 %s: %s (%.2f) %s", key, p.pick, p.strength, p.reason)
        return rec


def history(path: str, n: int = 20) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (FileNotFoundError, ValueError):
        return []
    return rows[-n:]
