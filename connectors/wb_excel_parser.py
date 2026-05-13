"""Parser for WB Excel detailed sales report (Отчёт о реализации).

Captures ALL cost components per the official WB commission structure:
- Комиссия WB (ВВ без НДС)
- НДС на комиссию
- Эквайринг (компенсация платёжных услуг)
- Логистика до клиента
- Логистика возврата / ПВЗ
- Хранение
- Приёмка
- Перевозка / складские операции
- Штрафы
- Корректировки ВВ
- Скидки (софинансирование, лояльность, промокоды)
"""

import pandas as pd
import numpy as np
from datetime import date


WB_COLUMNS = {
    # Идентификация товара
    "predmet":      "Предмет",
    "sku":          "Код номенклатуры",
    "article":      "Артикул поставщика",
    "name":         "Название",
    # Тип документа и дата
    "doc_type":     "Тип документа",
    "sale_date":    "Дата продажи",
    # Количество
    "quantity":     "Кол-во",
    "deliveries":   "Количество доставок",
    "returns_qty":  "Количество возврата",
    # Цены
    "retail_price": "Цена розничная",
    "revenue":      "Вайлдберриз реализовал Товар (Пр)",
    # К перечислению
    "net_to_seller": "К перечислению Продавцу за реализованный Товар",
    # Комиссия WB
    "commission":   "Вознаграждение Вайлдберриз (ВВ), без НДС",
    "vat_commission": "НДС с Вознаграждения Вайлдберриз",
    "commission_adj": "Корректировка Вознаграждения Вайлдберриз",
    # Эквайринг
    "acquiring":    "Компенсация платёжных услуг",
    # Логистика
    "logistics":    "Услуги по доставке товара покупателю",
    "pvz_returns":  "Возмещение за выдачу и возврат товаров на ПВЗ",
    "transport":    "Возмещение издержек по перевозке",
    # Хранение и приёмка
    "storage":      "Хранение",
    "acceptance":   "Операции на приемке",
    # Штрафы
    "penalties":    "Общая сумма штрафов",
    # Скидки (удержания продавца)
    "cofinancing":  "Скидка по программе софинансирования",
    "loyalty_cost": "Стоимость участия в программе лояльности",
    "loyalty_pts":  "Сумма баллов, удержанных по программе лояльности",
    "promo":        "Скидка за промокод",
}


def _safe_float(val) -> float:
    try:
        if pd.isna(val):
            return 0.0
        return float(str(val).replace(",", ".").replace(" ", "").replace("\xa0", "") or 0)
    except (ValueError, TypeError):
        return 0.0


def _safe_sku(val) -> str:
    try:
        if pd.isna(val):
            return "unknown"
        return str(int(float(val)))
    except (ValueError, TypeError):
        v = str(val).strip()
        return v if v else "unknown"


def parse_wb_excel(file) -> tuple[list[dict], dict]:
    """
    Parse WB Отчёт о реализации Excel.
    Returns (records, summary_stats).
    """
    df = pd.read_excel(file, sheet_name=0, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    # Map logical names → actual column names (fuzzy match)
    col = {}
    for key, name in WB_COLUMNS.items():
        matches = [c for c in df.columns if name.lower() in c.lower()]
        if matches:
            col[key] = matches[0]

    required = ["sku", "sale_date", "revenue"]
    missing = [k for k in required if k not in col]
    if missing:
        raise ValueError(f"Не найдены колонки: {[WB_COLUMNS[k] for k in missing]}")

    aggregated: dict[tuple, dict] = {}

    for _, row in df.iterrows():
        raw_date = row.get(col.get("sale_date", ""), None)
        try:
            if pd.isna(raw_date):
                continue
            sale_date = pd.to_datetime(raw_date).date()
        except Exception:
            continue

        sku = _safe_sku(row.get(col.get("sku", ""), None))
        doc_type = str(row.get(col.get("doc_type", ""), "")).strip()

        key = ("wb", sale_date, sku)
        if key not in aggregated:
            aggregated[key] = {
                "marketplace":    "wb",
                "date":           sale_date,
                "sku":            sku,
                "product_name":   str(row.get(col.get("name", ""), "") or ""),
                "category":       str(row.get(col.get("predmet", ""), "") or ""),
                # Core financials
                "revenue":        0.0,
                "returns":        0.0,
                "net_profit":     0.0,
                # Commission breakdown
                "commission":     0.0,   # ВВ без НДС
                "vat_commission": 0.0,   # НДС на комиссию
                "acquiring":      0.0,   # Эквайринг
                # Logistics breakdown
                "logistics":      0.0,   # Доставка до клиента
                "pvz_returns":    0.0,   # Выдача/возврат ПВЗ
                "storage":        0.0,   # Хранение
                "acceptance":     0.0,   # Приёмка
                # Deductions
                "penalties":      0.0,   # Штрафы
                "cofinancing":    0.0,   # Скидки/лояльность/промо
                # Quantities
                "quantity":       0,
                "return_quantity": 0,
                "source":         "excel",
            }

        rec = aggregated[key]

        revenue      = _safe_float(row.get(col.get("revenue", ""), 0))
        net          = _safe_float(row.get(col.get("net_to_seller", ""), 0))
        commission   = abs(_safe_float(row.get(col.get("commission", ""), 0)))
        vat_comm     = abs(_safe_float(row.get(col.get("vat_commission", ""), 0)))
        comm_adj     = _safe_float(row.get(col.get("commission_adj", ""), 0))
        acquiring    = abs(_safe_float(row.get(col.get("acquiring", ""), 0)))
        logistics    = abs(_safe_float(row.get(col.get("logistics", ""), 0)))
        pvz          = abs(_safe_float(row.get(col.get("pvz_returns", ""), 0)))
        transport    = abs(_safe_float(row.get(col.get("transport", ""), 0)))
        storage      = abs(_safe_float(row.get(col.get("storage", ""), 0)))
        acceptance   = abs(_safe_float(row.get(col.get("acceptance", ""), 0)))
        penalties    = abs(_safe_float(row.get(col.get("penalties", ""), 0)))
        cofinancing  = abs(_safe_float(row.get(col.get("cofinancing", ""), 0)))
        loyalty_cost = abs(_safe_float(row.get(col.get("loyalty_cost", ""), 0)))
        loyalty_pts  = abs(_safe_float(row.get(col.get("loyalty_pts", ""), 0)))
        promo        = abs(_safe_float(row.get(col.get("promo", ""), 0)))
        qty          = int(_safe_float(row.get(col.get("quantity", ""), 0)))
        ret_qty      = int(_safe_float(row.get(col.get("returns_qty", ""), 0)))

        is_return = doc_type in ("Возврат", "Коррекция возврата") or revenue < 0

        if is_return:
            rec["returns"] += abs(revenue)
            rec["return_quantity"] += max(ret_qty, abs(qty))
        else:
            rec["revenue"] += revenue
            rec["quantity"] += qty

        # Commission components
        rec["commission"]   += commission + abs(comm_adj)
        rec["vat_commission"] += vat_comm
        rec["acquiring"]    += acquiring

        # Logistics components
        rec["logistics"]  += logistics + transport
        rec["pvz_returns"] += pvz
        rec["storage"]    += storage
        rec["acceptance"] += acceptance

        # Other deductions
        rec["penalties"]    += penalties
        rec["cofinancing"]  += cofinancing + loyalty_cost + loyalty_pts + promo

        # Net to seller (as reported by WB — most accurate)
        rec["net_profit"] += net - penalties

    records = list(aggregated.values())

    # Total logistics for the unified `logistics` field used by normalizer
    for r in records:
        r["logistics"] = r["logistics"] + r["pvz_returns"] + r["storage"] + r["acceptance"]

    stats = {
        "total_rows":   len(df),
        "records":      len(records),
        "revenue":      sum(r["revenue"] for r in records),
        "returns":      sum(r["returns"] for r in records),
        "commission":   sum(r["commission"] for r in records),
        "vat_commission": sum(r["vat_commission"] for r in records),
        "acquiring":    sum(r["acquiring"] for r in records),
        "logistics":    sum(r["logistics"] for r in records),
        "penalties":    sum(r["penalties"] for r in records),
        "cofinancing":  sum(r["cofinancing"] for r in records),
        "net_profit":   sum(r["net_profit"] for r in records),
        "skus":         len(set(r["sku"] for r in records)),
        "date_from":    min(r["date"] for r in records) if records else None,
        "date_to":      max(r["date"] for r in records) if records else None,
    }

    return records, stats
