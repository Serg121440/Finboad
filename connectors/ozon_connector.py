"""Ozon Seller API connector."""

import time
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from config import OZON_CLIENT_ID, OZON_API_KEY, OZON_BASE_URL

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "Client-Id": str(OZON_CLIENT_ID),
        "Api-Key": OZON_API_KEY,
        "Content-Type": "application/json",
    }


def _post(path: str, body: dict, retries: int = 3) -> dict:
    url = f"{OZON_BASE_URL}{path}"
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=_headers(), json=body, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("Ozon rate limit hit, waiting %ds", wait)
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def fetch_transactions(date_from: date, date_to: date) -> list[dict]:
    """Fetch finance transactions from Ozon."""
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        logger.warning("Ozon credentials not set — returning empty data")
        return []

    all_ops = []
    page = 1

    while True:
        body = {
            "filter": {
                "date": {
                    "from": datetime.combine(date_from, datetime.min.time()).isoformat() + "Z",
                    "to": datetime.combine(date_to, datetime.max.time()).replace(microsecond=0).isoformat() + "Z",
                },
                "transaction_type": "all",
            },
            "page": page,
            "page_size": 1000,
        }
        data = _post("/v3/finance/transaction/list", body)
        ops = data.get("result", {}).get("operations", [])
        if not ops:
            break
        all_ops.extend(ops)
        if len(ops) < 1000:
            break
        page += 1

    return all_ops


def fetch_analytics(date_from: date, date_to: date) -> list[dict]:
    """Fetch sales analytics from Ozon."""
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        return []

    body = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "metrics": ["revenue", "returns", "cancellations", "ordered_units", "returned_units"],
        "dimension": ["sku", "day"],
        "sort": [{"key": "revenue", "order": "DESC"}],
        "limit": 1000,
        "offset": 0,
    }
    data = _post("/v1/analytics/data", body)
    return data.get("result", {}).get("data", [])


def fetch_returns(date_from: date, date_to: date) -> list[dict]:
    """Fetch returns from Ozon."""
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        return []

    body = {
        "filter": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
        "limit": 1000,
        "offset": 0,
    }
    data = _post("/v3/returns/company/fbo", body)
    return data.get("returns", [])


def normalize_ozon_transactions(transactions: list[dict], analytics: list[dict]) -> list[dict]:
    """Convert raw Ozon data to unified schema."""
    analytics_map: dict[tuple, dict] = {}
    for row in analytics:
        dims = {d["id"]: d["value"] for d in row.get("dimensions", [])}
        sku = dims.get("sku", "unknown")
        day = dims.get("day", "")
        try:
            sale_date = datetime.fromisoformat(day[:10]).date()
        except Exception:
            continue

        metrics = {m["id"]: m["value"] for m in row.get("metrics", [])}
        key = ("ozon", sale_date, str(sku))
        analytics_map[key] = {
            "marketplace": "ozon",
            "date": sale_date,
            "sku": str(sku),
            "product_name": dims.get("sku", ""),
            "category": "",
            "revenue": float(metrics.get("revenue", 0) or 0),
            "returns": float(metrics.get("returns", 0) or 0),
            "commission": 0.0,
            "logistics": 0.0,
            "net_profit": 0.0,
            "quantity": int(metrics.get("ordered_units", 0) or 0),
            "return_quantity": int(metrics.get("returned_units", 0) or 0),
            "source": "api",
        }

    for txn in transactions:
        txn_date_str = txn.get("operation_date", "")[:10]
        try:
            txn_date = datetime.fromisoformat(txn_date_str).date()
        except Exception:
            continue

        for item in txn.get("items", []):
            sku = str(item.get("sku", "unknown"))
            key = ("ozon", txn_date, sku)
            if key not in analytics_map:
                analytics_map[key] = {
                    "marketplace": "ozon",
                    "date": txn_date,
                    "sku": sku,
                    "product_name": item.get("name", ""),
                    "category": "",
                    "revenue": 0.0,
                    "returns": 0.0,
                    "commission": 0.0,
                    "logistics": 0.0,
                    "net_profit": 0.0,
                    "quantity": 0,
                    "return_quantity": 0,
                    "source": "api",
                }

        services = txn.get("services", [])
        for svc in services:
            name = svc.get("name", "")
            amount = float(svc.get("price", 0) or 0)
            sku = str(txn.get("items", [{}])[0].get("sku", "unknown")) if txn.get("items") else "unknown"
            key = ("ozon", txn_date, sku)
            if key in analytics_map:
                if "MarketplaceCommission" in name or "commission" in name.lower():
                    analytics_map[key]["commission"] += abs(amount)
                elif "Delivery" in name or "logistics" in name.lower() or "logistic" in name.lower():
                    analytics_map[key]["logistics"] += abs(amount)

    for key, rec in analytics_map.items():
        rec["net_profit"] = rec["revenue"] - rec["returns"] - rec["commission"] - rec["logistics"]

    return list(analytics_map.values())
