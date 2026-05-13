"""Parser for WB advertising report — История затрат."""

import pandas as pd
from datetime import date


def parse_wb_ads_excel(file) -> tuple[list[dict], dict]:
    """
    Parse WB 'История затрат' advertising report.
    Columns: ID кампании, Кампания, Раздел, Дата списания, Источник списания, Сумма, Номер документа
    Returns (records, stats).
    """
    df = pd.read_excel(file, sheet_name=0, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    required = ["Сумма", "Дата списания"]
    missing = [c for c in required if not any(c.lower() in col.lower() for col in df.columns)]
    if missing:
        raise ValueError(f"Не найдены колонки: {missing}")

    col_date     = next(c for c in df.columns if "дата" in c.lower())
    col_amount   = next(c for c in df.columns if "сумма" in c.lower())
    col_campaign = next((c for c in df.columns if "кампани" in c.lower()), None)
    col_camp_id  = next((c for c in df.columns if "id" in c.lower()), None)
    col_section  = next((c for c in df.columns if "раздел" in c.lower()), None)

    records = []
    for _, row in df.iterrows():
        raw_date = row.get(col_date)
        try:
            if pd.isna(raw_date):
                continue
            spend_date = pd.to_datetime(raw_date).date()
        except Exception:
            continue

        amount = float(str(row.get(col_amount, 0)).replace(",", ".") or 0)
        if amount <= 0:
            continue

        records.append({
            "marketplace":   "wb",
            "date":          spend_date,
            "campaign_id":   str(row.get(col_camp_id, "")) if col_camp_id else "",
            "campaign_name": str(row.get(col_campaign, "")) if col_campaign else "",
            "campaign_type": str(row.get(col_section, "")) if col_section else "",
            "amount":        amount,
            "sku":           None,
            "source":        "excel",
        })

    stats = {
        "total_rows":  len(df),
        "records":     len(records),
        "total_spend": sum(r["amount"] for r in records),
        "campaigns":   len(set(r["campaign_name"] for r in records if r["campaign_name"])),
        "date_from":   min(r["date"] for r in records) if records else None,
        "date_to":     max(r["date"] for r in records) if records else None,
    }

    return records, stats


def distribute_ad_spend_by_revenue(
    ad_records: list[dict],
    sales_df: "pd.DataFrame",
) -> list[dict]:
    """
    Distribute ad spend proportionally by SKU revenue within the same date range.
    Returns ad_records with sku field filled.
    """
    import pandas as pd

    if sales_df.empty or not ad_records:
        return ad_records

    date_from = min(r["date"] for r in ad_records)
    date_to   = max(r["date"] for r in ad_records)

    mask = (sales_df["date"].dt.date >= date_from) & (sales_df["date"].dt.date <= date_to)
    period_df = sales_df[mask]

    if period_df.empty:
        return ad_records

    total_revenue = period_df["revenue"].sum()
    if total_revenue <= 0:
        return ad_records

    sku_shares = (
        period_df.groupby("sku")["revenue"].sum() / total_revenue
    ).to_dict()

    total_spend = sum(r["amount"] for r in ad_records)

    distributed = []
    for sku, share in sku_shares.items():
        distributed.append({
            "marketplace":   "wb",
            "date":          date_to,
            "campaign_id":   "distributed",
            "campaign_name": "Распределено пропорционально выручке",
            "campaign_type": "auto",
            "amount":        round(total_spend * share, 2),
            "sku":           sku,
            "source":        "excel_distributed",
        })

    return distributed
