"""Tables to an Excel workbook: numbers stay numbers, formats follow the column names."""

from io import BytesIO

import numpy as np
import pandas as pd

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
RUB, PCT, QTY = "#,##0 ₽;-#,##0 ₽", "0.0%", "#,##0"


def _format(col: str) -> str | None:
    """«…, ₽» — rubles, «…, %» / «% …» — percent (the frame holds 54.1 for 54.1 %), «…, шт» — pieces."""
    c = str(col)
    if "₽" in c:
        return RUB
    if "%" in c:
        return PCT
    if c.endswith(", шт"):
        return QTY
    return None


def _cell(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v) + 0.0          # −0.0 → 0
    return v


def to_xlsx(sheets: list[tuple], header: list[str] = ()) -> bytes:
    """sheets: (title, frame) or (title, frame, row_formats). row_formats — one number format per row
    that overrides the column formats (a statement with ₽ and % rows); percent rows then hold fractions."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for title, df, *rest in sheets:
        row_formats = rest[0] if rest else None
        ws = wb.create_sheet(str(title)[:31])
        for line in header:
            ws.append([line])
        if header:
            ws.append([])
        ws.append([str(c) for c in df.columns])
        head = ws.max_row
        for c in ws[head]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="EEEAFB")
        fmts = [_format(c) for c in df.columns]
        for i, row in enumerate(df.itertuples(index=False)):
            vals = []
            for v, fmt in zip(row, fmts):
                v = _cell(v)
                # a percent column holds 54.1 for 54.1 %: Excel wants the fraction
                if fmt == PCT and row_formats is None and isinstance(v, (int, float)):
                    v = v / 100
                vals.append(v)
            ws.append(vals)
            for c, fmt in zip(ws[ws.max_row], fmts):
                f = row_formats[i] if row_formats is not None else fmt
                if f and isinstance(c.value, (int, float)):
                    c.number_format = f
        for j, col in enumerate(df.columns, start=1):
            texts = [str(col)] + [str(v) for v in df.iloc[:, j - 1] if isinstance(v, str)]
            width = max(len(t) for t in texts) + 2 if fmts[j - 1] is None and row_formats is None else 15
            ws.column_dimensions[get_column_letter(j)].width = min(max(width, 10), 60)
        if len(df.columns):
            ws.auto_filter.ref = f"A{head}:{get_column_letter(len(df.columns))}{ws.max_row}"
        pinned = 2 if list(df.columns[:2]) == ["Артикул", "Товар"] else 1
        ws.freeze_panes = ws.cell(row=head + 1, column=pinned + 1)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
