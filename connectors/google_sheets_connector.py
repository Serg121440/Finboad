"""Read-only Google Sheets connector for initial data import."""

import logging
import os
from datetime import datetime, date
from typing import Optional

import pandas as pd

from config import GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_SPREADSHEET_ID

logger = logging.getLogger(__name__)


def _get_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        if not os.path.exists(GOOGLE_SHEETS_CREDENTIALS_JSON):
            logger.warning(
                "Google Sheets credentials file '%s' not found",
                GOOGLE_SHEETS_CREDENTIALS_JSON,
            )
            return None

        creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDENTIALS_JSON, scopes=scopes
        )
        return gspread.authorize(creds)
    except ImportError:
        logger.error("gspread / google-auth not installed")
        return None
    except Exception as e:
        logger.error("Failed to init Google Sheets client: %s", e)
        return None


def _parse_date(value: str) -> Optional[date]:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", "").replace("\xa0", "") or 0)
    except (ValueError, TypeError):
        return 0.0


def _infer_marketplace(sheet_name: str) -> str:
    name = sheet_name.lower()
    if "wb" in name or "wildberries" in name or "вб" in name:
        return "wb"
    if "ozon" in name or "озон" in name:
        return "ozon"
    return "other"


COLUMN_ALIASES = {
    "date": ["дата", "date", "период", "день"],
    "sku": ["артикул", "sku", "nmid", "nm_id", "арт", "баркод", "barcode"],
    "product_name": ["наименование", "товар", "название", "product", "name"],
    "category": ["категория", "category", "предмет"],
    "revenue": ["выручка", "revenue", "продажи", "сумма продаж", "retail_amount"],
    "returns": ["возвраты", "returns", "сумма возвратов"],
    "commission": ["комиссия", "commission", "вознаграждение wb", "вознаграждение"],
    "logistics": ["логистика", "logistics", "доставка", "delivery"],
    "net_profit": ["чистая прибыль", "net_profit", "к перечислению", "ppvz_for_pay"],
    "quantity": ["количество продаж", "quantity", "кол-во", "продано"],
    "return_quantity": ["количество возвратов", "return_quantity", "возвращено"],
}


def _map_columns(headers: list[str]) -> dict[str, int]:
    mapping = {}
    lowered = [h.lower().strip() for h in headers]
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                mapping[field] = lowered.index(alias)
                break
    return mapping


def import_from_google_sheets() -> list[dict]:
    """Read all sheets and return normalized records. Read-only — never writes."""
    client = _get_client()
    if client is None:
        logger.warning("Google Sheets unavailable — skipping import")
        return []

    try:
        spreadsheet = client.open_by_key(GOOGLE_SPREADSHEET_ID)
    except Exception as e:
        logger.error("Cannot open spreadsheet %s: %s", GOOGLE_SPREADSHEET_ID, e)
        return []

    all_records = []

    for worksheet in spreadsheet.worksheets():
        sheet_name = worksheet.title
        logger.info("Processing sheet: %s", sheet_name)

        try:
            rows = worksheet.get_all_values()
        except Exception as e:
            logger.error("Failed to read sheet '%s': %s", sheet_name, e)
            continue

        if len(rows) < 2:
            continue

        headers = rows[0]
        col_map = _map_columns(headers)
        marketplace = _infer_marketplace(sheet_name)

        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue

            def get(field):
                idx = col_map.get(field)
                if idx is None or idx >= len(row):
                    return None
                return row[idx]

            raw_date = get("date")
            sale_date = _parse_date(raw_date) if raw_date else None
            if sale_date is None:
                continue

            sku = str(get("sku") or "unknown").strip()
            if not sku or sku == "unknown":
                continue

            record = {
                "marketplace": marketplace,
                "date": sale_date,
                "sku": sku,
                "product_name": str(get("product_name") or ""),
                "category": str(get("category") or ""),
                "revenue": _to_float(get("revenue")),
                "returns": _to_float(get("returns")),
                "commission": _to_float(get("commission")),
                "logistics": _to_float(get("logistics")),
                "net_profit": _to_float(get("net_profit")),
                "quantity": int(_to_float(get("quantity"))),
                "return_quantity": int(_to_float(get("return_quantity"))),
                "source": "gsheets",
            }

            if record["net_profit"] == 0 and record["revenue"] > 0:
                record["net_profit"] = (
                    record["revenue"]
                    - record["returns"]
                    - record["commission"]
                    - record["logistics"]
                )

            all_records.append(record)

    logger.info("Imported %d records from Google Sheets", len(all_records))
    return all_records
