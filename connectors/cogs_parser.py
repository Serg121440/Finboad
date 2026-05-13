"""Себестоимость: шаблон и парсер Excel."""

import io
import pandas as pd


TEMPLATE_COLUMNS = ["Артикул (SKU)", "Наименование товара", "Себестоимость (руб/ед)"]


def generate_cogs_template(existing_skus: list[dict] | None = None) -> bytes:
    """
    Generate Excel template for cost of goods input.
    existing_skus: list of dicts with keys sku, product_name, cost_per_unit
    """
    if existing_skus:
        df = pd.DataFrame([
            {
                "Артикул (SKU)": r.get("sku", ""),
                "Наименование товара": r.get("product_name", ""),
                "Себестоимость (руб/ед)": r.get("cost_per_unit", 0),
            }
            for r in existing_skus
        ])
    else:
        df = pd.DataFrame(columns=TEMPLATE_COLUMNS)
        df.loc[0] = ["123456789", "Пример товара", 500.0]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Себестоимость")
        ws = writer.sheets["Себестоимость"]
        ws.column_dimensions["A"].width = 20
        ws.column_dimensions["B"].width = 40
        ws.column_dimensions["C"].width = 25
    buf.seek(0)
    return buf.read()


def parse_cogs_excel(file) -> tuple[list[dict], int]:
    """
    Parse uploaded COGS Excel file.
    Returns (records, count).
    """
    df = pd.read_excel(file, sheet_name=0, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    col_sku  = next((c for c in df.columns if "артикул" in c.lower() or "sku" in c.lower()), None)
    col_name = next((c for c in df.columns if "наим" in c.lower() or "название" in c.lower()), None)
    col_cost = next((c for c in df.columns if "себест" in c.lower() or "cost" in c.lower()), None)

    if not col_sku or not col_cost:
        raise ValueError("Не найдены колонки 'Артикул' и 'Себестоимость'. Используй шаблон.")

    records = []
    for _, row in df.iterrows():
        sku = str(row.get(col_sku, "")).strip()
        if not sku or sku.lower() in ("nan", "none", ""):
            continue
        try:
            cost = float(str(row.get(col_cost, 0)).replace(",", ".") or 0)
        except (ValueError, TypeError):
            cost = 0.0

        records.append({
            "sku":           sku,
            "product_name":  str(row.get(col_name, "")) if col_name else "",
            "cost_per_unit": cost,
        })

    return records, len(records)
