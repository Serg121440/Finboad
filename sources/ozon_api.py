"""Ozon Seller API and Performance API clients (read-only methods only)."""

import csv
import io
import time
import zipfile
from datetime import date, timedelta

import requests

SELLER_URL = "https://api-seller.ozon.ru"
PERF_URL = "https://api-performance.ozon.ru"


class OzonError(RuntimeError):
    pass


def _num(v) -> float:
    """«1 406,59» / «7,20» / «12 730» -> float. Empty and dashes -> 0."""
    if v is None:
        return 0.0
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "—"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


class SellerClient:
    def __init__(self, client_id: str, api_key: str):
        self.headers = {"Client-Id": str(client_id), "Api-Key": api_key}
        self.s = requests.Session()

    def post(self, path: str, body: dict, retries: int = 8) -> dict:
        for i in range(retries):
            try:
                r = self.s.post(SELLER_URL + path, headers=self.headers, json=body, timeout=90)
            except (requests.Timeout, requests.ConnectionError):
                time.sleep(3 * (i + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (i + 1))
                continue
            if r.status_code != 200:
                raise OzonError(f"{path}: {r.status_code} {r.text[:300]}")
            return r.json()
        raise OzonError(f"{path}: нет ответа после {retries} попыток")

    def seller_info(self) -> dict:
        """Company on file: legal_name, ownership_form, inn, tax_system."""
        return self.post("/v1/seller/info", {}).get("company", {})

    # ── finance ──────────────────────────────────────────────────────────────

    def accrual_types(self) -> list[dict]:
        return self.post("/v1/finance/accrual/types", {}).get("accrual_types", [])

    def accruals_by_day(self, day: date) -> list[dict]:
        out, last = [], ""
        while True:
            j = self.post("/v1/finance/accrual/by-day", {"date": day.isoformat(), "last_id": last})
            batch = j.get("accruals") or []
            out += batch
            last = j.get("last_id") or ""
            if not last or not batch:
                return out

    # ── catalog ──────────────────────────────────────────────────────────────

    def products(self) -> list[dict]:
        """All products incl. archived: [{sku, offer_id, name}]."""
        ids = []
        for visibility in ("ALL", "ARCHIVED"):
            last = ""
            while True:
                j = self.post("/v3/product/list", {"filter": {"visibility": visibility},
                                                   "last_id": last, "limit": 1000})
                items = j["result"]["items"]
                ids += [i["product_id"] for i in items]
                last = j["result"].get("last_id") or ""
                if not last or not items:
                    break
        out = []
        for i in range(0, len(ids), 1000):
            j = self.post("/v3/product/info/list", {"product_id": ids[i:i + 1000]})
            for it in j.get("items", []):
                skus = {str(s["sku"]) for s in it.get("sources") or [] if s.get("sku")}
                if it.get("sku"):
                    skus.add(str(it["sku"]))
                for sku in skus:
                    out.append({"sku": sku, "offer_id": it.get("offer_id", ""),
                                "name": it.get("name", ""),
                                "category": str(it.get("description_category_id") or "")})
        return out

    def net_prices(self) -> dict[str, float]:
        """offer_id -> себестоимость из карточки (price.net_price), только заполненные."""
        out, cursor = {}, ""
        while True:
            j = self.post("/v5/product/info/prices", {"filter": {"visibility": "ALL"},
                                                     "cursor": cursor, "limit": 1000})
            for it in j.get("items") or []:
                v = float((it.get("price") or {}).get("net_price") or 0)
                if v > 0:
                    out[str(it.get("offer_id"))] = v
            cursor = j.get("cursor") or ""
            if not cursor or not j.get("items"):
                return out

    # ── orders ───────────────────────────────────────────────────────────────

    def postings(self, date_from: date, date_to: date) -> list[dict]:
        """FBO + FBS postings created in [date_from, date_to] (MSK days)."""
        since = f"{(date_from - timedelta(days=1)).isoformat()}T21:00:00Z"
        to = f"{date_to.isoformat()}T20:59:59Z"
        out, cursor = [], ""
        while True:
            j = self.post("/v3/posting/fbo/list", {
                "sort_dir": "ASC", "filter": {"since": since, "to": to},
                "limit": 100, "cursor": cursor})
            out += [dict(p, _scheme="fbo") for p in j.get("postings") or []]
            cursor = j.get("cursor") or ""
            if not j.get("has_next") or not cursor:
                break
        cursor = ""
        while True:
            j = self.post("/v4/posting/fbs/list", {
                "sort_dir": "ASC", "filter": {"since": since, "to": to},
                "limit": 100, "cursor": cursor})
            out += [dict(p, _scheme="fbs") for p in j.get("postings") or []]
            cursor = j.get("cursor") or ""
            if not j.get("has_next") or not cursor:
                break
        return out


class PerformanceClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._exp = None, 0.0

    def _headers(self) -> dict:
        if not self._token or time.time() > self._exp - 60:
            for i in range(4):
                try:
                    r = requests.post(PERF_URL + "/api/client/token", json={
                        "client_id": self.client_id, "client_secret": self.client_secret,
                        "grant_type": "client_credentials"}, timeout=60)
                    if r.status_code == 200:
                        break
                    if r.status_code in (400, 401, 403):
                        raise OzonError(f"Performance API: {r.status_code} {r.text[:200]}")
                except (requests.Timeout, requests.ConnectionError):
                    pass
                time.sleep(5 * (i + 1))
            else:
                raise OzonError("Performance API: не удалось получить токен")
            d = r.json()
            self._token, self._exp = d["access_token"], time.time() + d.get("expires_in", 1800)
        return {"Authorization": f"Bearer {self._token}"}

    def get(self, path: str, params=None, retries: int = 6) -> requests.Response:
        for i in range(retries):
            try:
                r = requests.get(PERF_URL + path, headers=self._headers(), params=params, timeout=90)
            except (requests.Timeout, requests.ConnectionError):
                time.sleep(5 * (i + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (i + 1))
                continue
            if r.status_code != 200:
                raise OzonError(f"{path}: {r.status_code} {r.text[:300]}")
            return r
        raise OzonError(f"{path}: нет ответа")

    def campaigns(self) -> dict[str, dict]:
        """All campaigns. A plain list is capped at ~250, so also read by state."""
        out = {str(c["id"]): c for c in self.get("/api/client/campaign").json().get("list", [])}
        for state in ("CAMPAIGN_STATE_RUNNING", "CAMPAIGN_STATE_INACTIVE",
                      "CAMPAIGN_STATE_STOPPED", "CAMPAIGN_STATE_ARCHIVED"):
            time.sleep(1)
            for c in self.get("/api/client/campaign", {"state": state}).json().get("list", []):
                out[str(c["id"])] = c
        return out

    def daily_spend(self, date_from: date, date_to: date) -> list[dict]:
        """[{campaign_id, date, money_spent}] for all campaigns."""
        r = self.get("/api/client/statistics/daily/json",
                     {"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()})
        return [{"campaign_id": str(x.get("id")), "date": x.get("date"),
                 "money_spent": _num(x.get("moneySpent"))} for x in r.json().get("rows", [])]

    def _report(self, path: str, body: dict) -> bytes:
        r = None
        for i in range(6):
            r = requests.post(PERF_URL + path, headers={**self._headers(), "Content-Type": "application/json"},
                              json=body, timeout=90)
            if r.status_code == 429:
                time.sleep(10 * (i + 1))
                continue
            break
        if r.status_code != 200:
            raise OzonError(f"{path}: {r.status_code} {r.text[:300]}")
        uuid = r.json()["UUID"]
        deadline = time.time() + 900
        while time.time() < deadline:
            st = self.get(f"/api/client/statistics/{uuid}").json()
            if st.get("state") == "OK":
                return self.get("/api/client/statistics/report", {"UUID": uuid}).content
            if st.get("state") == "ERROR":
                raise OzonError(f"отчёт {uuid}: {st.get('error')}")
            time.sleep(5)
        raise OzonError(f"отчёт {uuid} не собрался за 15 минут")

    def cpc_sku_daily(self, campaign_ids: list[str], date_from: date, date_to: date) -> list[dict]:
        """Spend per campaign/day/SKU for pay-per-click campaigns (≤10 per report)."""
        out = []
        for i in range(0, len(campaign_ids), 10):
            chunk = campaign_ids[i:i + 10]
            content = self._report("/api/client/statistics", {
                "campaigns": chunk, "groupBy": "DATE",
                "from": _msk_from(date_from), "to": _msk_to(date_to)})
            files = {}
            if content[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for name in z.namelist():
                        files[name.split("_", 1)[0]] = z.read(name).decode("utf-8-sig")
            else:
                files[chunk[0]] = content.decode("utf-8-sig")
            for cid, text in files.items():
                lines = text.splitlines()
                if len(lines) < 3:
                    continue
                for r in csv.DictReader(lines[1:], delimiter=";"):
                    sku = (r.get("sku") or "").strip()
                    day = (r.get("Дата") or r.get("День") or "").strip()
                    if not sku.isdigit() or not day:
                        continue
                    spend = _num(r.get("Расход, ₽, с НДС") or r.get("Расход, ₽"))
                    if spend:
                        out.append({"campaign_id": cid, "date": _parse_day(day), "sku": sku,
                                    "amount": spend, "name": (r.get("Название товара") or "").strip()})
        return out

    def cpo_orders(self, date_from: date, date_to: date) -> list[dict]:
        """«Оплата за заказ» per order: [{date, sku, amount}] (SEARCH_PROMO)."""
        content = self._report("/api/client/statistics/orders/generate", {
            "from": _msk_from(date_from), "to": _msk_to(date_to)})
        lines = content.decode("utf-8-sig").splitlines()
        out = []
        for r in csv.DictReader(lines[1:], delimiter=";"):
            sku = (r.get("SKU") or "").strip()
            day = (r.get("Дата") or "").strip()
            spend = _num(r.get("Расход, ₽") or r.get("Расход"))
            if sku.isdigit() and day and spend:
                out.append({"date": _parse_day(day), "sku": sku, "amount": spend})
        return out


def _msk_from(d: date) -> str:
    return f"{(d - timedelta(days=1)).isoformat()}T21:00:00.000Z"


def _msk_to(d: date) -> str:
    return f"{d.isoformat()}T20:59:59.000Z"


def _parse_day(s: str) -> date:
    s = s.strip()[:10]
    if "." in s:
        d, m, y = s.split(".")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(s)
