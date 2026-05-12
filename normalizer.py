"""Normalize data from all sources to a unified schema and persist to DB."""

import logging
from datetime import date, timedelta

from connectors.wb_connector import fetch_sales_report, normalize_wb_sales
from connectors.ozon_connector import (
    fetch_transactions,
    fetch_analytics,
    normalize_ozon_transactions,
)
from connectors.google_sheets_connector import import_from_google_sheets
from database.db import upsert_records, log_sync, init_db

logger = logging.getLogger(__name__)

UNIFIED_FIELDS = {
    "marketplace", "date", "sku", "product_name", "category",
    "revenue", "returns", "commission", "logistics", "net_profit",
    "quantity", "return_quantity", "source",
}


def _validate(record: dict) -> dict:
    clean = {k: v for k, v in record.items() if k in UNIFIED_FIELDS}
    clean.setdefault("marketplace", "unknown")
    clean.setdefault("product_name", "")
    clean.setdefault("category", "")
    clean.setdefault("revenue", 0.0)
    clean.setdefault("returns", 0.0)
    clean.setdefault("commission", 0.0)
    clean.setdefault("logistics", 0.0)
    clean.setdefault("net_profit", 0.0)
    clean.setdefault("quantity", 0)
    clean.setdefault("return_quantity", 0)
    clean.setdefault("source", "api")
    return clean


def sync_wb(date_from: date, date_to: date) -> int:
    logger.info("Syncing WB data %s — %s", date_from, date_to)
    try:
        raw = fetch_sales_report(date_from, date_to)
        records = [_validate(r) for r in normalize_wb_sales(raw)]
        count = upsert_records(records)
        log_sync("wb", "ok", len(records))
        logger.info("WB sync done: %d records", len(records))
        return len(records)
    except Exception as e:
        log_sync("wb", "error", error=str(e))
        logger.error("WB sync failed: %s", e)
        return 0


def sync_ozon(date_from: date, date_to: date) -> int:
    logger.info("Syncing Ozon data %s — %s", date_from, date_to)
    try:
        txns = fetch_transactions(date_from, date_to)
        analytics = fetch_analytics(date_from, date_to)
        records = [_validate(r) for r in normalize_ozon_transactions(txns, analytics)]
        count = upsert_records(records)
        log_sync("ozon", "ok", len(records))
        logger.info("Ozon sync done: %d records", len(records))
        return len(records)
    except Exception as e:
        log_sync("ozon", "error", error=str(e))
        logger.error("Ozon sync failed: %s", e)
        return 0


def sync_google_sheets() -> int:
    logger.info("Importing Google Sheets data")
    try:
        records = [_validate(r) for r in import_from_google_sheets()]
        count = upsert_records(records)
        log_sync("gsheets", "ok", len(records))
        logger.info("Google Sheets import done: %d records", len(records))
        return len(records)
    except Exception as e:
        log_sync("gsheets", "error", error=str(e))
        logger.error("Google Sheets import failed: %s", e)
        return 0


def full_sync(days_back: int = 90):
    """Run full sync for all sources over the last N days."""
    init_db()
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)

    results = {
        "wb": sync_wb(date_from, date_to),
        "ozon": sync_ozon(date_from, date_to),
        "gsheets": sync_google_sheets(),
    }
    return results
