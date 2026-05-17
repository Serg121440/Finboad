"""Parser for Ozon accruals report — wide format (25 columns, one row per shipment).

net_profit = sum(Итого, руб.) for all rows of a (date, sku) group.
This matches Ozon's final payout exactly.
"""

import pandas as pd
from datetime import date

# --- Row-type sets (lowercase for comparison) ---

# Main sale rows: contain revenue (J), commission (L), logistics (U)
SALE_TYPES = {
    "доставка покупателю",
}

# Return rows with revenue reversal: J<0 (refund to seller), L>0 (commission refunded)
RETURN_REVENUE_TYPES = {
    "получение возврата, отмены, невыкупа от покупателя",
}

# Return logistics cost rows: J=0, L=0 — charge is in U or X
RETURN_LOGISTICS_TYPES = {
    "доставка и обработка возврата, отмены, невыкупа",
}

# --- Column name patterns for fuzzy matching ---

OZON_COLUMNS = {
    "sale_date":         "Дата начисления",
    "charge_type":       "Тип начисления",
    "shipment_id":       "Номер отправления",
    "sku":               "SKU",
    "article":           "Артикул",
    "name":              "Название товара",
    "quantity":          "Количество",
    "gross_revenue":     "За продажу или возврат до вычета",
    "total":             "Итого, руб.",
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


def _find_col(columns, pattern: str) -> str | None:
    """Return first column whose name contains pattern (case-insensitive)."""
    pat = pattern.lower()
    for c in columns:
        if pat in c.lower():
            return c
    return None


def _classify_service(charge_type: str) -> str:
    """Classify service-fee rows for display breakdown."""
    ct = charge_type.lower()
    if "эквайринг" in ct:
        return "acquiring"
    if any(k in ct for k in ("хранение", "размещение товаров на складе", "временное размещение")):
        return "storage"
    if any(k in ct for k in ("нерекомендованный слот", "индекса ошибок", "жалобы покупателей",
                              "превышение индекса", "брак", "отмена начисления")):
        return "penalty"
    if any(k in ct for k in ("агентское вознаграждение", "услуги доставки партнерами",
                              "организация выезда курьера", "доставка курьером",
                              "вывоз товара со склада", "упаковка товара", "материалами для упаковки",
                              "перечисление за доставку от покупателя")):
        return "logistics_extra"
    # Advertising rows: already baked into net_profit (Y), don't add to ad_spend
    if any(k in ct for k in ("оплата за клик", "продвижение с оплатой за заказ",
                              "продвижение бренда", "ускоренный сбор отзывов")):
        return "ad_uderz"
    if any(k in ct for k in ("звёздные товары", "подписка", "подготовка товара к вывозу")):
        return "uderzhaniya"
    return "other"


def parse_ozon_excel(file) -> tuple[list[dict], dict]:
    """
    Parse Ozon Начисления Excel (wide format, 25 cols).
    Returns (records, summary_stats).
    """
    df = pd.read_excel(file, sheet_name=0, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    # Fuzzy-match key columns
    col = {}
    for key, pattern in OZON_COLUMNS.items():
        col[key] = _find_col(df.columns, pattern)

    # Commission columns: distinguish amount vs %
    comm_cols = [c for c in df.columns
                 if "вознаграждение ozon" in c.lower() or "вознаграждение озон" in c.lower()]
    col["commission_pct"] = next((c for c in comm_cols if "%" in c), None)
    col["commission"]     = next((c for c in comm_cols if "%" not in c), None)

    # Logistics columns: distinguish forward (U) vs reverse (X)
    log_cols = [c for c in df.columns if "логистика" in c.lower()]
    col["reverse_logistics"] = next((c for c in log_cols if "обратная" in c.lower()), None)
    col["logistics"]         = next((c for c in log_cols if "обратная" not in c.lower()), None)

    required = ["sku", "sale_date", "total"]
    missing = [k for k in required if not col.get(k)]
    if missing:
        raise ValueError(f"Не найдены колонки: {[OZON_COLUMNS.get(k, k) for k in missing]}")

    aggregated: dict[tuple, dict] = {}

    # Collect service-level costs (sku=0 / unknown) for proportional distribution
    service_costs = {
        "acquiring": 0.0,
        "storage": 0.0,
        "penalty": 0.0,
        "logistics_extra": 0.0,
        "uderzhaniya": 0.0,
        "ad_uderz": 0.0,
        "net_contribution": 0.0,
    }

    for _, row in df.iterrows():
        raw_date = row.get(col.get("sale_date") or "", None)
        try:
            if pd.isna(raw_date):
                continue
            sale_date = pd.to_datetime(raw_date).date()
        except Exception:
            continue

        sku        = _safe_sku(row.get(col.get("sku") or "", None))
        charge_type = str(row.get(col.get("charge_type") or "", "") or "").strip()
        ct_lower   = charge_type.lower()
        total_y    = _safe_float(row.get(col.get("total") or "", 0))

        if sku in ("0", "unknown"):
            cat = _classify_service(charge_type)
            service_costs[cat] = service_costs.get(cat, 0.0) + abs(total_y)
            service_costs["net_contribution"] += total_y
            continue

        key = ("ozon", sale_date, sku)
        if key not in aggregated:
            aggregated[key] = {
                "marketplace":     "ozon",
                "date":            sale_date,
                "sku":             sku,
                "article":         str(row.get(col.get("article") or "", "") or "").strip().upper(),
                "product_name":    str(row.get(col.get("name") or "", "") or ""),
                "category":        "",
                "revenue":         0.0,
                "returns":         0.0,
                "net_profit":      0.0,
                "commission":      0.0,
                "vat_commission":  0.0,
                "acquiring":       0.0,
                "logistics":       0.0,
                "logistics_direct":0.0,
                "storage":         0.0,
                "penalties":       0.0,
                "uderzhaniya":     0.0,
                "cofinancing":     0.0,
                "ad_spend":        0.0,
                "quantity":        0,
                "return_quantity": 0,
                "source":          "excel",
            }

        rec = aggregated[key]

        # Update article from any non-empty row
        if not rec.get("article"):
            art = str(row.get(col.get("article") or "", "") or "").strip().upper()
            if art:
                rec["article"] = art

        gross   = _safe_float(row.get(col.get("gross_revenue") or "", 0))
        comm    = _safe_float(row.get(col.get("commission") or "", 0))
        log_fwd = abs(_safe_float(row.get(col.get("logistics") or "", 0)))
        log_rev = abs(_safe_float(row.get(col.get("reverse_logistics") or "", 0)))
        qty     = int(_safe_float(row.get(col.get("quantity") or "", 0)))

        # Always accumulate net_profit from Y (covers everything)
        rec["net_profit"] += total_y

        if ct_lower in SALE_TYPES:
            rec["revenue"]    += max(gross, 0.0)
            rec["commission"] += abs(comm)
            rec["logistics"]  += log_fwd
            rec["logistics_direct"] += log_fwd
            rec["quantity"]   += max(qty, 0)

        elif ct_lower in RETURN_REVENUE_TYPES:
            rec["returns"]         += abs(gross)   # gross < 0 on returns
            rec["return_quantity"] += abs(qty)
            # commission refunded (comm > 0 on return) — informational, no separate field

        elif ct_lower in RETURN_LOGISTICS_TYPES:
            rec["storage"] += log_fwd + log_rev

        else:
            # Service fee rows — categorize for display
            svc = _classify_service(charge_type)
            if svc == "acquiring":
                rec["acquiring"]   += abs(total_y) if total_y < 0 else 0.0
            elif svc == "storage":
                rec["storage"]     += abs(total_y) if total_y < 0 else 0.0
            elif svc == "penalty":
                rec["penalties"]   += abs(total_y) if total_y < 0 else 0.0
            elif svc in ("ad_uderz", "uderzhaniya"):
                rec["uderzhaniya"] += abs(total_y) if total_y < 0 else 0.0
            elif svc == "logistics_extra":
                rec["logistics"]   += abs(total_y) if total_y < 0 else 0.0

    # Distribute service-level (sku=0) costs proportionally by revenue
    records = list(aggregated.values())
    total_rev = sum(r["revenue"] for r in records)

    for r in records:
        share = (r["revenue"] / total_rev) if total_rev > 0 else (1.0 / len(records) if records else 0.0)
        r["acquiring"]   += service_costs["acquiring"]   * share
        r["storage"]     += service_costs["storage"]     * share
        r["penalties"]   += service_costs["penalty"]     * share
        r["uderzhaniya"] += (service_costs["uderzhaniya"] + service_costs["ad_uderz"]) * share
        r["logistics"]   += service_costs["logistics_extra"] * share
        r["net_profit"]  += service_costs["net_contribution"] * share

    stats = {
        "total_rows":     len(df),
        "records":        len(records),
        "skus":           len(set(r["sku"] for r in records)),
        "revenue":        sum(r["revenue"] for r in records),
        "returns":        sum(r["returns"] for r in records),
        "commission":     sum(r["commission"] for r in records),
        "acquiring":      sum(r["acquiring"] for r in records),
        "logistics":      sum(r["logistics"] for r in records),
        "storage":        sum(r["storage"] for r in records),
        "penalties":      sum(r["penalties"] for r in records),
        "uderzhaniya":    sum(r["uderzhaniya"] for r in records),
        "net_profit":     sum(r["net_profit"] for r in records),
        "quantity":       sum(r["quantity"] for r in records),
        "return_quantity":sum(r["return_quantity"] for r in records),
        "date_from":      min(r["date"] for r in records) if records else None,
        "date_to":        max(r["date"] for r in records) if records else None,
    }

    return records, stats
