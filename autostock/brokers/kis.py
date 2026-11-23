"""한국투자증권 Open API (해외주식) 시세/주문.

엔드포인트와 TR ID는 공식 샘플(github.com/koreainvestment/open-trading-api)을 따른다.
미국 주식은 API로 시장가 주문이 안 되므로(모의투자는 지정가만) 현재가에서
약간 불리한 가격의 지정가로 즉시 체결을 노리고, 일정 시간 안에 안 되면 취소한다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .. import market_hours
from ..market_hours import ET
from ..models import Bar, Fill, Position, Quote

log = logging.getLogger("kis")
KST = ZoneInfo("Asia/Seoul")

BASE = {
    "real": "https://openapi.koreainvestment.com:9443",
    "demo": "https://openapivts.koreainvestment.com:29443",
}
# SOXL/SOXS는 NYSE Arca 상장 → 시세 코드 AMS, 주문 코드 AMEX
EXCD_QUOTE = {"SOXL": "AMS", "SOXS": "AMS", "TSM": "NYS"}     # 표에 없으면 나스닥(NAS)
_ORDER_CODE = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}


class _OrderCodes(dict):
    def __missing__(self, symbol: str) -> str:
        return _ORDER_CODE[EXCD_QUOTE.get(symbol, "NAS")]


EXCD_ORDER = _OrderCodes()
EXCD_DAY = {"NAS": "BAQ", "NYS": "BAY", "AMS": "BAA"}           # 주간거래 시세 코드


def _is_day() -> bool:
    s = market_hours.current(market_hours.now_et())
    return bool(s and s.name == "day")


def _extended() -> bool:
    s = market_hours.current(market_hours.now_et())
    return bool(s and s.name != "regular")


def _excd(symbol: str) -> str:
    code = EXCD_QUOTE.get(symbol, "NAS")
    return EXCD_DAY[code] if _is_day() else code


class KISError(RuntimeError):
    pass


class KISClient:
    def __init__(self, app_key: str, app_secret: str, env: str = "demo", data_dir: str = "data"):
        if env not in BASE:
            raise ValueError("KIS_ENV는 demo 또는 real")
        if not app_key or not app_secret:
            raise ValueError("KIS_APP_KEY / KIS_APP_SECRET 이 필요합니다")
        self.key, self.secret, self.env = app_key, app_secret, env
        self.base = BASE[env]
        self.token_path = os.path.join(data_dir, f"kis_token_{env}.json")
        # 초당 호출 제한: 모의 2건, 실전 20건(신규 계좌는 한동안 더 낮음). 봇은 호출이 적으니 넉넉히 띄운다.
        self.min_gap = 1.0 if env == "demo" else 0.4
        self._last = 0.0
        self._token = ""
        self._exp = 0.0
        self.http = requests.Session()

    def _auth(self) -> str:
        if self._token and time.time() < self._exp - 600:
            return self._token
        if os.path.exists(self.token_path):
            with open(self.token_path) as f:
                t = json.load(f)
            if t.get("key") == self.key[-6:] and time.time() < t["exp"] - 600:
                self._token, self._exp = t["token"], t["exp"]
                return self._token
        r = self.http.post(f"{self.base}/oauth2/tokenP", timeout=10, json={
            "grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret})
        if r.status_code != 200:
            raise KISError(f"토큰 발급 실패 {r.status_code}: {r.text[:200]}")
        j = r.json()
        self._token, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 86400))
        os.makedirs(os.path.dirname(self.token_path) or ".", exist_ok=True)
        self._last = time.time()
        with open(self.token_path, "w") as f:      # 토큰 발급은 분당 1회 제한 → 파일 캐시
            json.dump({"token": self._token, "exp": self._exp, "key": self.key[-6:]}, f)
        os.chmod(self.token_path, 0o600)
        return self._token

    def call(self, method: str, path: str, tr_id: str, payload: dict) -> dict:
        for attempt in range(1, 5):
            try:
                j = self._call_once(method, path, tr_id, payload)
            except (requests.ConnectionError, requests.Timeout):
                # 조회는 다시 보내도 안전하다. 주문(POST)은 서버가 받았을 수 있으므로 재전송하지 않는다.
                if method != "GET" or attempt == 4:
                    raise
                self.http = requests.Session()       # 끊긴 keep-alive 연결을 버린다
                time.sleep(attempt)
                continue
            # EGW00201 = 초당 거래건수 초과. 게이트웨이에서 거절된 것이라 처리되지 않았으므로 재시도해도 안전.
            if j.get("msg_cd") != "EGW00201" or attempt == 4:
                break
            time.sleep(attempt)
        if str(j.get("rt_cd")) != "0":
            raise KISError(f"{path} [{j.get('msg_cd')}] {j.get('msg1')}")
        return j

    def _call_once(self, method: str, path: str, tr_id: str, payload: dict) -> dict:
        token = self._auth()
        wait = self.min_gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.key, "appsecret": self.secret,
            "tr_id": tr_id, "custtype": "P",
        }
        url = self.base + path
        try:
            if method == "GET":
                r = self.http.get(url, headers=headers, params=payload, timeout=10)
            else:
                r = self.http.post(url, headers=headers, json=payload, timeout=10)
        finally:
            self._last = time.time()
        try:
            return r.json()
        except ValueError:
            raise KISError(f"{path} HTTP {r.status_code}: {r.text[:200]}") from None


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class KISMarket:
    def __init__(self, client: KISClient):
        self.c = client

    def quote(self, symbol: str) -> Quote:
        j = self.c.call("GET", "/uapi/overseas-price/v1/quotations/price", "HHDFS00000300",
                        {"AUTH": "", "EXCD": _excd(symbol), "SYMB": symbol})
        o = j["output"]
        last = _num(o.get("last"))
        if last <= 0:
            raise KISError(f"{symbol} 현재가 없음: {o}")
        return Quote(symbol, last, _num(o.get("base")))

    def book(self, symbol: str) -> tuple[float, float] | None:
        """(매수1호가, 매도1호가). 조회가 안 되면 None — 호출부는 현재가 기준으로 주문한다."""
        try:
            j = self.c.call("GET", "/uapi/overseas-price/v1/quotations/inquire-asking-price", "HHDFS76200100",
                            {"AUTH": "", "EXCD": _excd(symbol), "SYMB": symbol})
            o = j.get("output2") or {}
            if isinstance(o, list):
                o = o[0] if o else {}
            bid, ask = _num(o.get("pbid1")), _num(o.get("pask1"))
            return (bid, ask) if bid > 0 and ask >= bid else None
        except (KISError, requests.RequestException) as e:
            log.warning("호가 조회 실패: %s", e)
            return None

    def bars(self, symbol: str, n: int = 120) -> list[Bar]:
        j = self.c.call("GET", "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice",
                        "HHDFS76950200",
                        {"AUTH": "", "EXCD": _excd(symbol), "SYMB": symbol, "NMIN": "1",
                         "PINC": "1", "NEXT": "", "NREC": str(min(n, 120)), "FILL": "", "KEYB": ""})
        out, day = [], _is_day()
        for r in j.get("output2") or []:
            try:
                if day and r.get("kymd") and r.get("khms"):     # 주간거래는 한국시간 필드가 확실
                    ts = datetime.strptime(r["kymd"] + r["khms"], "%Y%m%d%H%M%S").replace(tzinfo=KST).astimezone(ET)
                else:
                    ts = datetime.strptime(r["xymd"] + r["xhms"], "%Y%m%d%H%M%S").replace(tzinfo=ET)
            except (KeyError, ValueError):
                continue
            out.append(Bar(ts, _num(r.get("open")), _num(r.get("high")), _num(r.get("low")),
                           _num(r.get("last")), _num(r.get("evol"))))
        out.sort(key=lambda b: b.ts)       # API는 최신순 → 시간순으로
        return out[-n:]


class KISBroker:
    def __init__(self, client: KISClient, account_no: str, product: str = "01",
                 limit_slip_pct: float = 0.3, fill_timeout: float = 20.0, day_slip_pct: float = 0.5,
                 book=None):
        if len(account_no) != 8:
            raise ValueError("KIS_ACCOUNT_NO는 계좌번호 앞 8자리")
        self.c, self.cano, self.prdt = client, account_no, product
        self.slip, self.timeout, self.day_slip = limit_slip_pct / 100, fill_timeout, day_slip_pct / 100
        self.v = "V" if client.env == "demo" else "T"
        self.book = book             # 호가 조회 함수(없어도 됨)

    def position(self, symbol: str) -> Position | None:
        j = self.c.call("GET", "/uapi/overseas-stock/v1/trading/inquire-balance", self.v + "TTS3012R",
                        {"CANO": self.cano, "ACNT_PRDT_CD": self.prdt,
                         "OVRS_EXCG_CD": EXCD_ORDER[symbol], "TR_CRCY_CD": "USD",
                         "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""})
        for r in j.get("output1") or []:
            if r.get("ovrs_pdno") == symbol and int(_num(r.get("ovrs_cblc_qty"))) > 0:
                return Position(symbol, int(_num(r["ovrs_cblc_qty"])), _num(r.get("pchs_avg_pric")))
        return None

    def _qty(self, symbol: str) -> int:
        p = self.position(symbol)
        return p.qty if p else 0

    def _order(self, side: str, symbol: str, qty: int, limit: float) -> Fill | None:
        day = _is_day()
        body = {"CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "OVRS_EXCG_CD": EXCD_ORDER[symbol],
                "PDNO": symbol, "ORD_QTY": str(qty), "OVRS_ORD_UNPR": f"{limit:.2f}",
                "CTAC_TLNO": "", "MGCO_APTM_ODNO": "", "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00"}
        if day:                     # 주간거래는 별도 주문 API (실전 전용, 지정가만)
            if self.v == "V":
                raise KISError("모의투자는 주간거래 주문을 지원하지 않습니다")
            path, tr = "/uapi/overseas-stock/v1/trading/daytime-order", "TTTS6036U" if side == "buy" else "TTTS6037U"
        else:
            path = "/uapi/overseas-stock/v1/trading/order"
            body["SLL_TYPE"] = "00" if side == "sell" else ""
            if side == "buy":
                tr = self.v + "TTT1002U"
            else:                   # 미국 매도: 실전 TTTT1006U / 모의 VTTT1001U
                tr = "VTTT1001U" if self.v == "V" else "TTTT1006U"
        before = self._qty(symbol)
        j = self.c.call("POST", path, tr, body)
        odno = (j.get("output") or {}).get("ODNO", "")
        log.info("주문 접수 %s %s x%d @%.2f (주문번호 %s)", side, symbol, qty, limit, odno)

        filled, deadline = 0, time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(2)
            filled = abs(self._qty(symbol) - before)
            if filled >= qty:
                break
        if filled < qty:
            self._cancel(symbol, odno, qty - filled, day)
            time.sleep(1.5)
            filled = abs(self._qty(symbol) - before)   # 취소 직전 체결분 반영
        if filled <= 0:
            log.warning("미체결로 취소됨: %s %s", side, symbol)
            return None
        return Fill(symbol, side, min(filled, qty), self._fill_price(symbol, side, odno) or limit)

    def _cancel(self, symbol: str, odno: str, qty: int, day: bool = False) -> None:
        body = {"CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "OVRS_EXCG_CD": EXCD_ORDER[symbol],
                "PDNO": symbol, "ORGN_ODNO": odno, "RVSE_CNCL_DVSN_CD": "02",
                "ORD_QTY": str(qty), "OVRS_ORD_UNPR": "0", "MGCO_APTM_ODNO": "", "ORD_SVR_DVSN_CD": "0"}
        try:
            if day:
                self.c.call("POST", "/uapi/overseas-stock/v1/trading/daytime-order-rvsecncl", "TTTS6038U",
                            {**body, "CTAC_TLNO": ""})
            else:
                self.c.call("POST", "/uapi/overseas-stock/v1/trading/order-rvsecncl", self.v + "TTT1004U", body)
        except KISError as e:       # 이미 전량 체결된 경우 등
            log.warning("주문 취소 실패(이미 체결됐을 수 있음): %s", e)

    def _fill_price(self, symbol: str, side: str, odno: str) -> float | None:
        """체결내역에서 평균 체결가 조회. 실패하면 None(호출부가 지정가로 대체)."""
        if side == "buy":
            p = self.position(symbol)
            if p and p.avg_price > 0:
                return p.avg_price
        try:
            today = datetime.now(KST)
            demo = self.v == "V"       # 모의투자는 전체 조회만 가능
            j = self.c.call("GET", "/uapi/overseas-stock/v1/trading/inquire-ccnl", self.v + "TTS3035R", {
                "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "PDNO": "" if demo else symbol,
                "ORD_STRT_DT": (today - timedelta(days=1)).strftime("%Y%m%d"),
                "ORD_END_DT": today.strftime("%Y%m%d"),
                "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "" if demo else EXCD_ORDER[symbol], "SORT_SQN": "DS",
                "ORD_DT": "", "ORD_GNO_BRNO": "", "ODNO": "",
                "CTX_AREA_NK200": "", "CTX_AREA_FK200": ""})
            for r in j.get("output") or []:
                if r.get("odno") == odno and _num(r.get("ft_ccld_unpr3")) > 0:
                    return _num(r["ft_ccld_unpr3"])
        except KISError as e:
            log.warning("체결가 조회 실패, 지정가로 대체: %s", e)
        return None

    def _limit(self, side: str, symbol: str, ref: float) -> float:
        """즉시 체결을 노리는 지정가. 현재가에 여유를 주되, 호가가 그보다 멀면 호가까지 따라간다(상한 있음).
        거래가 뜸한 시간대에는 현재가(마지막 체결가)와 실제 호가가 크게 벌어져 있기 때문."""
        slip, cap = (self.day_slip, 0.015) if _extended() else (self.slip, 0.008)
        bk = self.book(symbol) if self.book else None
        if side == "buy":
            px = ref * (1 + slip)
            if bk:
                px = min(max(px, bk[1]), ref * (1 + cap))
        else:
            px = ref * (1 - slip)
            if bk:
                px = max(min(px, bk[0]), ref * (1 - cap))
        return round(px, 2)

    def buy(self, symbol: str, qty: int, ref_price: float) -> Fill | None:
        return self._order("buy", symbol, qty, self._limit("buy", symbol, ref_price))

    def sell(self, symbol: str, qty: int, ref_price: float) -> Fill | None:
        return self._order("sell", symbol, qty, self._limit("sell", symbol, ref_price))
