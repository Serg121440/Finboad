"""Parser for WB Excel detailed sales report (Отчёт о реализации)."""

import pandas as pd
import numpy as np
from datetime import date
from typing import Optional


WB_COLUMNS = {
    "predmet": "Предмет",
    "sku": "Код номенклатуры",
    "article": "Артикул поставщика",
    "name": "Название",
    "doc_type": "Тип документа",
    "sale_date": "Дата продажи",
    "quantity": "Кол-во",
    "retail_price": "Цена розничная",
    "revenue": "Вайлдберриз реализовал Товар (Пр)",
    "commission": "Вознаграждение Вайлдберриз (ВВ), без НДС",
    "net_to_seller": "К перечислению Продавцу за реализованный Товар",
    "deliveries": "Количество доставок",
    "returns_qty": "Количество возврата",
    "logistics": "Услуги по доставке товара покупателю",
    "penalties": "Общая сумма штрафов",
    "storage": "Хранение",
}


def _to_float(val) -> float:
    try:
        return float(str(val).replace(",", ".").replace(" ", "").replace("\xa0", "") or 0)
    except (ValueError, TypeError):
        return 0.0


def parse_wb_excel(file) -> tuple[list[dict], dict]:
    """
    Parse WB detailed sales report Excel file.
    Returns (records, summary_stats).
    file: file path string or file-like object.
    """
    df = pd.read_excel(file, sheet_name=0, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    col = {}
    for key, name in WB_COLUMNS.items():
        matches = [c for c in df.columns if name.lower() in c.lower()]
        if matches:
            col[key] = matches[0]

    required = ["sku", "sale_date", "revenue"]
    missing = [k for k in required if k not in col]
    if missing:
        raise ValueError(f"Не найдены обязательные колонки: {[WB_COLUMNS[k] for k in missing]}")

    aggregated: dict[tuple, dict] = {}

    for _, row in df.iterrows():
        raw_date = row.get(col.get("sale_date", ""), None)
        try:
            if pd.isna(raw_date):
                continue
            sale_date = pd.to_datetime(raw_date).date()
        except Exception:
            continue

        sku = str(int(row[col["sku"]])) if col.get("sku") else "unknown"
        doc_type = str(row.get(col.get("doc_type", ""), "")).strip()

        key = ("wb", sale_date, sku)
        if key not in aggregated:
            aggregated[key] = {
                "marketplace": "wb",
                "date": sale_date,
                "sku": sku,
                "product_name": str(row.get(col.get("name", ""), "") or ""),
                "category": str(row.get(col.get("predmet", ""), "") or ""),
                "revenue": 0.0,
                "returns": 0.0,
                "commission": 0.0,
                "logistics": 0.0,
                "net_profit": 0.0,
                "quantity": 0,
                "return_quantity": 0,
                "source": "excel",
            }

        rec = aggregated[key]
        revenue = _to_float(row.get(col.get("revenue", ""), 0))
        commission = abs(_to_float(row.get(col.get("commission", ""), 0)))
        net = _to_float(row.get(col.get("net_to_seller", ""), 0))
        logistics = abs(_to_float(row.get(col.get("logistics", ""), 0)))
        penalties = abs(_to_float(row.get(col.get("penalties", ""), 0)))
        storage = abs(_to_float(row.get(col.get("storage", ""), 0)))
        qty = int(_to_float(row.get(col.get("quantity", ""), 0)))
        ret_qty = int(_to_float(row.get(col.get("returns_qty", ""), 0)))

        is_return = doc_type in ("Возврат", "Коррекция возврата") or revenue < 0

        if is_return:
            rec["returns"] += abs(revenue)
            rec["return_quantity"] += max(ret_qty, abs(qty))
        else:
            rec["revenue"] += revenue
            rec["quantity"] += qty

        rec["commission"] += commission
        rec["logistics"] += logistics + storage
        rec["net_profit"] += net - penalties

    records = list(aggregated.values())

    stats = {
        "total_rows": len(df),
        "records": len(records),
        "revenue": sum(r["revenue"] for r in records),
        "returns": sum(r["returns"] for r in records),
        "commission": sum(r["commission"] for r in records),
        "logistics": sum(r["logistics"] for r in records),
        "net_profit": sum(r["net_profit"] for r in records),
        "skus": len(set(r["sku"] for r in records)),
        "date_from": min(r["date"] for r in records) if records else None,
        "date_to": max(r["date"] for r in records) if records else None,
    }

    return records, stats
