"""Wildberries Statistics API connector."""

import time
import logging
from datetime import date, timedelta
from typing import Optional

import requests

from config import WB_API_TOKEN, WB_BASE_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": WB_API_TOKEN,
    "Content-Type": "application/json",
}


def _get(path: str, params: dict = None, retries: int = 3) -> list | dict:
    url = f"{WB_BASE_URL}{path}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("WB rate limit hit, waiting %ds", wait)
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return []


def fetch_sales_report(date_from: date, date_to: date) -> list[dict]:
    """Fetch detailed sales report from WB for the given period."""
    if not WB_API_TOKEN:
        logger.warning("WB_API_TOKEN not set — returning empty data")
        return []

    all_rows = []
    rrd_id = 0

    while True:
        params = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "limit": 100000,
            "rrdid": rrd_id,
        }
        rows = _get("/api/v5/supplier/reportDetailByPeriod", params)
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 100000:
            break
        rrd_id = rows[-1].get("rrd_id", 0)

    return all_rows


def fetch_stocks() -> list[dict]:
    """Fetch current warehouse stocks."""
    if not WB_API_TOKEN:
        return []
    return _get("/api/v3/warehouses") or []


def fetch_returns(date_from: date, date_to: date) -> list[dict]:
    """Fetch returns for the period."""
    if not WB_API_TOKEN:
        return []
    params = {
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
    }
    return _get("/api/v1/supplier/returns", params) or []


def normalize_wb_sales(rows: list[dict]) -> list[dict]:
    """Convert raw WB report rows to unified schema."""
    from datetime import datetime

    aggregated: dict[tuple, dict] = {}

    for row in rows:
        doc_type = row.get("doc_type_name", "")
        sale_date_str = row.get("sale_dt") or row.get("rr_dt", "")
        try:
            sale_date = datetime.fromisoformat(sale_date_str[:10]).date()
        except Exception:
            continue

        sku = str(row.get("nm_id", row.get("sa_name", "unknown")))
        key = ("wb", sale_date, sku)

        if key not in aggregated:
            aggregated[key] = {
                "marketplace": "wb",
                "date": sale_date,
                "sku": sku,
                "product_name": row.get("subject_name", ""),
                "category": row.get("subject_name", ""),
                "revenue": 0.0,
                "returns": 0.0,
                "commission": 0.0,
                "logistics": 0.0,
                "net_profit": 0.0,
                "quantity": 0,
                "return_quantity": 0,
                "source": "api",
            }

        rec = aggregated[key]
        retail_amount = float(row.get("retail_amount", 0) or 0)
        ppvz_for_pay = float(row.get("ppvz_for_pay", 0) or 0)
        delivery_rub = float(row.get("delivery_rub", 0) or 0)
        penalty = float(row.get("penalty", 0) or 0)
        additional_payment = float(row.get("additional_payment", 0) or 0)

        if doc_type in ("Продажа", ""):
            rec["revenue"] += retail_amount
            rec["quantity"] += int(row.get("quantity", 1) or 1)
            commission = retail_amount - ppvz_for_pay - delivery_rub
            rec["commission"] += max(commission, 0)
            rec["logistics"] += delivery_rub
        elif doc_type == "Возврат":
            rec["returns"] += retail_amount
            rec["return_quantity"] += int(row.get("quantity", 1) or 1)

        rec["net_profit"] += ppvz_for_pay - penalty + additional_payment

    return list(aggregated.values())
