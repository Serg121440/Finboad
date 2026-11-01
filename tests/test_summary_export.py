"""Financial result: shares of revenue and the Excel export."""

from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from dashboard.views.products import revenue_share
from dashboard.views.summary import excel_report, table_rows


def _cols():
    stats = {"revenue": 1000.0, "commission": -524.0, "logistics": -55.0, "profit": 50.0, "margin": 0.05,
             "ordered_sum": 2000.0}
    return {"Ozon": stats, "Wildberries": {"revenue": 0.0, "commission": 0.0, "ordered_sum": 500.0}}


DETAILS = pd.DataFrame([
    {"cabinet_id": 1, "line": "commission", "category": "commission", "raw_type": "Вознаграждение", "amount": -500.0},
    {"cabinet_id": 1, "line": "commission", "category": "acquiring", "raw_type": "Эквайринг", "amount": -24.0},
])


def test_costs_show_share_of_column_revenue():
    rows = {r["label"]: r for r in table_rows(_cols(), [[1], [2]], DETAILS)}
    com = rows["Комиссия МП с эквайрингом"]
    assert com["shares"] == [0.524, None]          # no revenue — no share
    assert [k["shares"][0] for k in com["children"]] == [0.5, 0.024]
    assert rows["Прибыль до постоянных расходов"]["shares"][0] == 0.05
    assert rows["Заказы, ₽"]["shares"] == [None, None]
    assert "Себестоимость" not in {r["label"] for r in table_rows(_cols(), [[1], [2]], DETAILS, {"cogs"})}


def test_excel_has_values_shares_and_breakdown():
    rows = table_rows(_cols(), [[1], [2]], DETAILS)
    data = excel_report([("Финрезультат", list(_cols()), rows)], ["Период", "Расчёт полный"])
    ws = load_workbook(BytesIO(data))["Финрезультат"]
    table = {r[0]: r[1:] for r in ws.iter_rows(min_row=4, values_only=True)}
    assert table["Показатель"] == ("Ozon", "Ozon, % выручки", "Wildberries", "Wildberries, % выручки")
    assert table["Комиссия МП с эквайрингом"][:2] == (-524, 0.524)
    assert table["Эквайринг"][:2] == (-24, 0.024)


def test_product_cost_shares():
    g = pd.DataFrame({"revenue": [1000.0, 0.0], "commission": [-300.0, -10.0], "logistics": [-50.0, 0.0]})
    s = revenue_share(g, ["commission"])
    assert s.iloc[0] == 30.0 and pd.isna(s.iloc[1])
