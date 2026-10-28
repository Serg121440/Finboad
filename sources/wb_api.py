"""Wildberries API client (read-only).

One token per cabinet; it needs the categories Статистика, Финансы, Продвижение
(and Аналитика/Контент for product names). The financial report endpoint allows
about one request per minute, so the first load of a long history is slow.
"""

import time
from datetime import date, timedelta

import requests

STAT_URL = "https://statistics-api.wildberries.ru"
FIN_URL = "https://finance-api.wildberries.ru"
ADV_URL = "https://advert-api.wildberries.ru"

PING = {
    "Статистика": STAT_URL + "/ping",
    "Продвижение": ADV_URL + "/ping",
    "Финансы": FIN_URL + "/ping",
    "Контент": "https://content-api.wildberries.ru/ping",
}


class WbError(RuntimeError):
    pass


class WbClient:
    def __init__(self, token: str, report_pause: float = 61.0):
        self.headers = {"Authorization": token}
        self.report_pause = report_pause
        self._last_report_call = 0.0

    def _get(self, url: str, params=None, retries: int = 6, pause_429: float = 60):
        for i in range(retries):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=120)
            except (requests.Timeout, requests.ConnectionError):
                time.sleep(10 * (i + 1))
                continue
            if r.status_code == 429:
                time.sleep(pause_429)
                continue
            if r.status_code >= 500:
                time.sleep(10 * (i + 1))
                continue
            if r.status_code == 204:
                return []
            if r.status_code != 200:
                raise WbError(f"{url.split('wildberries.ru')[-1]}: {r.status_code} {r.text[:300]}")
            return r.json()
        raise WbError(f"{url}: нет ответа после {retries} попыток")

    def _post(self, url: str, body: dict, retries: int = 6, pause_429: float = 60):
        for i in range(retries):
            try:
                r = requests.post(url, headers=self.headers, json=body, timeout=180)
            except (requests.Timeout, requests.ConnectionError):
                time.sleep(10 * (i + 1))
                continue
            if r.status_code == 429:
                time.sleep(pause_429)
                continue
            if r.status_code >= 500:
                time.sleep(10 * (i + 1))
                continue
            if r.status_code == 204:
                return []
            if r.status_code != 200:
                raise WbError(f"{url.split('wildberries.ru')[-1]}: {r.status_code} {r.text[:300]}")
            return r.json()
        raise WbError(f"{url}: нет ответа после {retries} попыток")

    def check(self) -> dict[str, str]:
        """Which API categories the token can use: {category: 'ok' | error}."""
        out = {}
        for name, url in PING.items():
            try:
                r = requests.get(url, headers=self.headers, timeout=30)
                out[name] = "ok" if r.status_code == 200 else f"{r.status_code} {r.text[:120]}"
            except requests.RequestException as e:
                out[name] = type(e).__name__
        return out

    # ── finance ──────────────────────────────────────────────────────────────

    def report_detail(self, date_from: date, date_to: date, progress=None) -> list[dict]:
        """Weekly realization report rows for reports in [date_from, date_to].

        POST /api/finance/v1/sales-reports/detailed (camelCase fields, money as
        strings); the old /api/v5/supplier/reportDetailByPeriod is switched off.
        Paged by rrdId until 204, 1 request per minute.
        """
        rows, rrd = [], 0
        while True:
            wait = self.report_pause - (time.time() - self._last_report_call)
            if wait > 0:
                time.sleep(wait)
            self._last_report_call = time.time()
            batch = self._post(FIN_URL + "/api/finance/v1/sales-reports/detailed", {
                "dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat(),
                "limit": 100000, "rrdId": rrd, "period": "weekly"}) or []
            rows += batch
            if progress:
                progress(len(rows))
            if not batch:
                return rows
            rrd = batch[-1]["rrdId"]

    # ── orders ───────────────────────────────────────────────────────────────

    def orders(self, date_from: date) -> list[dict]:
        """Orders changed since date_from (flag=0, paged by lastChangeDate)."""
        out, since = [], date_from.isoformat()
        while True:
            batch = self._get(STAT_URL + "/api/v1/supplier/orders",
                              {"dateFrom": since, "flag": 0}) or []
            out += batch
            if len(batch) < 80000:
                return out
            since = batch[-1]["lastChangeDate"]
            time.sleep(61)

    # ── ads ──────────────────────────────────────────────────────────────────

    def campaigns(self) -> dict[str, dict]:
        data = self._get(ADV_URL + "/adv/v1/promotion/count") or {}
        out = {}
        for g in data.get("adverts") or []:
            for a in g.get("advert_list") or []:
                out[str(a["advertId"])] = {"type": g.get("type"), "status": g.get("status")}
        if out:
            ids = list(out)
            for i in range(0, len(ids), 50):
                info = requests.post(ADV_URL + "/adv/v1/promotion/adverts", headers=self.headers,
                                     json=[int(x) for x in ids[i:i + 50]], timeout=60)
                if info.status_code == 200:
                    for a in info.json() or []:
                        out[str(a["advertId"])]["name"] = a.get("name", "")
                time.sleep(1)
        return out

    def ad_spend(self, campaign_ids: list[str], date_from: date, date_to: date) -> list[dict]:
        """[{campaign_id, date, sku, amount}] from /adv/v3/fullstats (≤50 ids, ≤31 days)."""
        out = []
        start = date_from
        while start <= date_to:
            end = min(date_to, start + timedelta(days=30))
            for i in range(0, len(campaign_ids), 50):
                data = self._get(ADV_URL + "/adv/v3/fullstats", {
                    "ids": ",".join(campaign_ids[i:i + 50]),
                    "beginDate": start.isoformat(), "endDate": end.isoformat()},
                    pause_429=25) or []
                for camp in data:
                    cid = str(camp.get("advertId"))
                    for day in camp.get("days") or []:
                        d = date.fromisoformat(day["date"][:10])
                        per_nm = {}
                        for app in day.get("apps") or []:
                            for nm in app.get("nms") or app.get("nm") or []:
                                key = str(nm.get("nmId"))
                                per_nm[key] = per_nm.get(key, 0.0) + float(nm.get("sum") or 0)
                        spread = sum(per_nm.values())
                        total = float(day.get("sum") or 0)
                        for sku, amount in per_nm.items():
                            if amount:
                                out.append({"campaign_id": cid, "date": d, "sku": sku, "amount": amount})
                        if total - spread > 0.01:
                            out.append({"campaign_id": cid, "date": d, "sku": None,
                                        "amount": total - spread})
                time.sleep(20)
            start = end + timedelta(days=1)
        return out
