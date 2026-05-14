"""Parser for WB Excel detailed sales report (Отчёт о реализации).

net_profit = К_перечислению(Продажа) − К_перечислению(Возврат)
             − логистика − хранение − приёмка − удержания − штрафы
This matches WB's "Итого к оплате" exactly.
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
    "reason":       "Обоснование для оплаты",
    "sale_date":    "Дата продажи",
    # Количество
    "quantity":     "Кол-во",
    # Цены
    "revenue":      "Вайлдберриз реализовал Товар (Пр)",
    # К перечислению (per row — already has commission/vat/acquiring deducted)
    "net_to_seller": "К перечислению Продавцу за реализованный Товар",
    # Комиссия WB (информационно)
    "commission":    "Вознаграждение Вайлдберриз (ВВ), без НДС",
    "vat_commission":"НДС с Вознаграждения Вайлдберриз",
    "commission_adj":"Корректировка Вознаграждения Вайлдберриз",
    # Эквайринг (информационно)
    "acquiring":     "Компенсация платёжных услуг",
    # Логистика — отдельные строки
    "logistics":     "Услуги по доставке товара покупателю",   # строки «Логистика»
    "pvz_returns":   "Возмещение за выдачу и возврат товаров на ПВЗ",
    "transport":     "Возмещение издержек по перевозке",        # строки «Возмещение издержек»
    # Хранение и приёмка — отдельные строки
    "storage":       "Хранение",
    "acceptance":    "Операции на приемке",
    # Штрафы и удержания
    "penalties":     "Общая сумма штрафов",
    "uderzhaniya":   "Удержания",                               # «Прочие удержания/выплаты»
    # Скидки (информационно)
    "cofinancing":   "Скидка по программе софинансирования",
    "loyalty_cost":  "Стоимость участия в программе лояльности",
    "loyalty_pts":   "Сумма баллов, удержанных по программе лояльности",
    "loyalty_comp":  "Компенсация скидки по программе лояльности",
    "promo":         "Скидка за промокод",
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

        sku      = _safe_sku(row.get(col.get("sku", ""), None))
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
                # Commission breakdown (informational)
                "commission":     0.0,
                "vat_commission": 0.0,
                "acquiring":      0.0,
                # Logistics breakdown
                "logistics":         0.0,   # Общая = прямая (AI) + ПВЗ обратная (AJ)
                "logistics_direct":  0.0,   # Прямая доставка (AI)
                # Хранение + Приёмка + Возмещение издержек (отдельная статья)
                "storage":           0.0,
                # Other deductions
                "penalties":      0.0,   # штрафы WB
                "uderzhaniya":    0.0,   # прочие удержания/выплаты WB
                "cofinancing":    0.0,   # скидки/лояльность/промо
                # Quantities
                "quantity":       0,
                "return_quantity": 0,
                "source":         "excel",
                # Temp fields for net_profit calculation (filtered out before DB save)
                "_k_sales":      0.0,
                "_k_returns":    0.0,
                "_log_delivery": 0.0,
                "_log_transport":0.0,
                "_pvz":          0.0,
                "_storage":      0.0,
                "_acceptance":   0.0,
            }

        rec = aggregated[key]

        revenue     = _safe_float(row.get(col.get("revenue", ""), 0))
        net         = _safe_float(row.get(col.get("net_to_seller", ""), 0))
        commission  = _safe_float(row.get(col.get("commission", ""), 0))
        vat_comm    = _safe_float(row.get(col.get("vat_commission", ""), 0))
        comm_adj    = _safe_float(row.get(col.get("commission_adj", ""), 0))
        acquiring   = abs(_safe_float(row.get(col.get("acquiring", ""), 0)))
        logistics   = abs(_safe_float(row.get(col.get("logistics", ""), 0)))
        pvz         = abs(_safe_float(row.get(col.get("pvz_returns", ""), 0)))
        transport   = abs(_safe_float(row.get(col.get("transport", ""), 0)))
        storage     = abs(_safe_float(row.get(col.get("storage", ""), 0)))
        acceptance  = abs(_safe_float(row.get(col.get("acceptance", ""), 0)))
        penalties   = abs(_safe_float(row.get(col.get("penalties", ""), 0)))
        uderzhaniya = abs(_safe_float(row.get(col.get("uderzhaniya", ""), 0)))
        cofinancing = abs(_safe_float(row.get(col.get("cofinancing", ""), 0)))
        loyalty_cost= abs(_safe_float(row.get(col.get("loyalty_cost", ""), 0)))
        loyalty_pts = abs(_safe_float(row.get(col.get("loyalty_pts", ""), 0)))
        loyalty_comp= abs(_safe_float(row.get(col.get("loyalty_comp", ""), 0)))
        promo       = abs(_safe_float(row.get(col.get("promo", ""), 0)))
        qty         = int(_safe_float(row.get(col.get("quantity", ""), 0)))

        is_return = doc_type in ("Возврат", "Коррекция возврата") or revenue < 0

        if is_return:
            # Financial return: deducted from seller payout
            rec["returns"]    += abs(revenue)
            rec["_k_returns"] += abs(net)
            # return_quantity counts physical items via PVZ rows below, not here
        elif doc_type == "Продажа":
            # Only actual sales contribute to quantity and revenue
            rec["revenue"]   += revenue
            rec["quantity"]  += qty
            rec["_k_sales"]  += net

        # Physical return count: PVZ fee rows (AJ column) track items returned via PVZ
        if pvz > 0:
            rec["return_quantity"] += abs(qty)

        # Commission components (informational — already embedded in К перечислению)
        rec["commission"]    += abs(commission) + abs(comm_adj)
        rec["vat_commission"]+= abs(vat_comm)
        rec["acquiring"]     += acquiring

        # Cost rows — used both for display (logistics) and net_profit deduction
        rec["_log_delivery"] += logistics    # «Логистика» rows — Услуги по доставке
        rec["_log_transport"]+= transport    # «Возмещение издержек» rows
        rec["_pvz"]          += pvz          # ПВЗ выдача/возврат
        rec["_storage"]      += storage      # «Хранение» rows
        rec["_acceptance"]   += acceptance   # «Обработка товара» rows

        rec["penalties"]     += penalties
        rec["uderzhaniya"]   += uderzhaniya

        # Cofinancing / loyalty / promo (informational)
        rec["cofinancing"]   += cofinancing + loyalty_cost + loyalty_pts + loyalty_comp + promo

    # Finalize records
    records = list(aggregated.values())
    for r in records:
        k_sales   = r.pop("_k_sales", 0)
        k_returns = r.pop("_k_returns", 0)
        log_del   = r.pop("_log_delivery", 0)
        log_trans = r.pop("_log_transport", 0)
        pvz       = r.pop("_pvz", 0)
        stor      = r.pop("_storage", 0)
        acc       = r.pop("_acceptance", 0)

        # net_profit = actual payout (matches WB «Итого к оплате»)
        # log_trans (Возмещение издержек) and pvz are already embedded in
        # per-sale К перечислению — do NOT deduct again here.
        r["net_profit"] = (
            k_sales
            - k_returns
            - log_del
            - stor
            - acc
            - r["penalties"]
            - r["uderzhaniya"]
        )

        # Логистика = только «Услуги по доставке покупателю» (matches WB summary «Логистика»)
        r["logistics"]        = log_del
        r["logistics_direct"] = log_del
        # Хранение + Приёмка + ПВЗ + Возмещение издержек (informational, not in net_profit)
        r["storage"] = stor + acc + log_trans + pvz

    stats = {
        "total_rows":    len(df),
        "records":       len(records),
        "skus":          len(set(r["sku"] for r in records)),
        "revenue":       sum(r["revenue"] for r in records),
        "returns":       sum(r["returns"] for r in records),
        "commission":    sum(r["commission"] for r in records),
        "vat_commission":sum(r["vat_commission"] for r in records),
        "acquiring":     sum(r["acquiring"] for r in records),
        "logistics":          sum(r["logistics"] for r in records),
        "logistics_direct":   sum(r["logistics_direct"] for r in records),
        "storage":            sum(r["storage"] for r in records),
        "penalties":     sum(r["penalties"] for r in records),
        "uderzhaniya":   sum(r["uderzhaniya"] for r in records),
        "cofinancing":   sum(r["cofinancing"] for r in records),
        "net_profit":    sum(r["net_profit"] for r in records),
        "quantity":      sum(r["quantity"] for r in records),
        "return_quantity":sum(r["return_quantity"] for r in records),
        "date_from":     min(r["date"] for r in records) if records else None,
        "date_to":       max(r["date"] for r in records) if records else None,
    }

    return records, stats
