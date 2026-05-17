"""Parser for Ozon advertising statistics report (Statistics sheet).

Report is period-aggregated (no per-day dates). All records are assigned
the report start date supplied by the caller.
"""

import pandas as pd
from datetime import date


def parse_ozon_ads_excel(file, report_date: date) -> tuple[list[dict], dict]:
    """
    Parse Ozon ads report (sheet 'Statistics' or first sheet).
    report_date: start date of the report period (from UI date picker).
    Returns (records, stats).
    """
    # Ozon ads report: row 0 = "Период: ...", row 1 = actual column headers
    try:
        df = pd.read_excel(file, sheet_name="Statistics", header=1)
    except Exception:
        df = pd.read_excel(file, sheet_name=0, header=1)
    df.columns = [str(c).strip() for c in df.columns]

    def _find(pattern: str) -> str | None:
        pat = pattern.lower()
        return next((c for c in df.columns if pat in c.lower()), None)

    col_sku      = _find("sku")
    col_name     = _find("название товара")
    col_tool     = _find("инструмент")
    col_campaign = _find("id кампании")
    col_spend    = _find("расход")
    col_sales    = _find("продажи")
    col_orders   = _find("заказы")

    if not col_sku or not col_spend:
        raise ValueError("Не найдены колонки SKU и Расход. Используй отчёт Ozon → Реклама → Статистика.")

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

    records = []
    for _, row in df.iterrows():
        sku    = _safe_sku(row.get(col_sku, ""))
        spend  = _safe_float(row.get(col_spend, 0))
        if sku in ("0", "unknown") or spend == 0:
            continue

        campaign_id = str(row.get(col_campaign, "") or "").strip() if col_campaign else ""
        name        = str(row.get(col_name, "") or "").strip() if col_name else ""
        tool        = str(row.get(col_tool, "") or "").strip() if col_tool else ""

        records.append({
            "marketplace":   "ozon",
            "date":          report_date,
            "campaign_id":   campaign_id,
            "campaign_name": name,
            "campaign_type": tool,
            "amount":        spend,
            "sku":           sku,
            "source":        "excel",
        })

    stats = {
        "total_rows":  len(df),
        "campaigns":   len(set(r["campaign_id"] for r in records)),
        "skus":        len(set(r["sku"] for r in records)),
        "total_spend": sum(r["amount"] for r in records),
        "date_from":   report_date,
        "date_to":     report_date,
    }

    return records, stats
