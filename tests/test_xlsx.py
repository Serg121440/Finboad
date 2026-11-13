"""Excel export: numbers stay numbers with ₽ / % / pieces formats."""

from io import BytesIO

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from dashboard.xlsx import PCT, QTY, RUB, to_xlsx


def _sheet(data: bytes, name: str):
    return load_workbook(BytesIO(data))[name]


def test_columns_keep_numbers_and_get_formats():
    df = pd.DataFrame({"Артикул": ["A1", "A2"], "Товар": ["Стенка", "Мат"],
                       "Выручка, ₽": [66580.0, np.nan], "ДРР к выручке, %": [20.4, np.nan],
                       "Выкуп нетто, шт": [np.int64(2), np.int64(0)]})
    ws = _sheet(to_xlsx([("Товары", df)], ["Товары 24.10 — 29.10", "Расчёт полный"]), "Товары")
    assert ws["A1"].value == "Товары 24.10 — 29.10" and ws["A2"].value == "Расчёт полный"
    assert [c.value for c in ws[4]] == list(df.columns)
    assert ws["C5"].value == 66580 and ws["C5"].number_format == RUB
    assert ws["D5"].value == 0.204 and ws["D5"].number_format == PCT
    assert ws["E5"].value == 2 and ws["E5"].number_format == QTY
    # empty values stay empty, not «—» or NaN
    assert ws["C6"].value is None and ws["D6"].value is None
    assert ws.freeze_panes == "C5" and ws.auto_filter.ref == "A4:E6"


def test_row_formats_for_a_statement():
    df = pd.DataFrame({"Статья": ["Выручка", "Маржинальность", "Постоянные расходы"],
                       "Октябрь": [1000.0, 0.125, -0.0]})
    ws = _sheet(to_xlsx([("ОПиУ", df, [RUB, PCT, RUB])]), "ОПиУ")
    assert ws["B4"].value == 0 and not str(ws["B4"].value).startswith("-")      # not «-0 ₽»
    assert ws["B2"].value == 1000 and ws["B2"].number_format == RUB
    # a percent row already holds the fraction
    assert ws["B3"].value == 0.125 and ws["B3"].number_format == PCT


def test_several_sheets():
    a, b = pd.DataFrame({"Кабинет": ["X"], "Реклама, ₽": [5.0]}), pd.DataFrame({"Товар": ["Y"]})
    wb = load_workbook(BytesIO(to_xlsx([("По кабинетам", a), ("По товарам", b)])))
    assert wb.sheetnames == ["По кабинетам", "По товарам"]


def test_marked_cells_are_filled():
    df = pd.DataFrame({"Товар": ["A", "B"], "Маржа, %": [40.0, -30.0]})
    marks = pd.DataFrame({"Товар": ["", ""], "Маржа, %": ["good", "bad"]})
    ws = _sheet(to_xlsx([("Т", df, None, marks)]), "Т")
    assert ws["B2"].fill.fgColor.rgb.endswith("C6EFCE") and ws["B3"].fill.fgColor.rgb.endswith("FFC7CE")
    assert ws["A2"].fill.fill_type is None
