import pandas as pd
import pytest

from datetime import date

from dashboard.quality import find_issues, month_label
from dashboard.views.products import buyout_rate, reconcile, status_of, unit_economics
from pnl.engine import NO_SKU


def _row(**kw):
    base = dict(sku="1", revenue=0.0, commission=0.0, acquiring=0.0, logistics=0.0, ads=0.0, cogs=0.0,
                profit=0.0, sold=0, returned=0, net_qty=0, sales_gross=0.0, cost_missing_qty=0,
                ordered_qty=0, ordered_sum=0.0, cancelled_qty=0, cancelled_sum=0.0, delivered_qty=0,
                transit_qty=0, unknown_qty=0)
    return pd.DataFrame([{**base, **kw}])


def test_order_base_scales_sale_unit_by_kept_orders():
    # 10 sold for 10 000, profit 2 000 → 200 per sale; 4 of 20 orders cancelled → 160 per order
    g = _row(revenue=10000, profit=2000, ads=-400, sold=10, net_qty=10, sales_gross=10000,
             ordered_qty=20, ordered_sum=21000, cancelled_qty=4)
    u = unit_economics(g, "Заказы").iloc[0]
    assert u["price"] == 1050
    assert u["ads"] == -20                      # ads go straight to orders
    assert u["profit"] == pytest.approx((2000 + 400) / 10 * 0.8 - 20)
    assert u["drr"] == pytest.approx(400 / 21000)


def test_bases_differ_in_units_not_in_money():
    g = _row(revenue=7374 * 2, commission=-8805, acquiring=-1136, profit=-3000, sold=2, net_qty=2,
             sales_gross=7374 * 2, ordered_qty=28, ordered_sum=200000, cancelled_qty=0)
    buy = unit_economics(g, "Выкупы").iloc[0]
    assert buy["commission"] == pytest.approx((-8805 + 1136) / 2)
    assert buy["acquiring"] == pytest.approx(-1136 / 2)
    deals = unit_economics(g, "Сделки").iloc[0]
    assert deals["profit"] == -1500


def test_returns_only_is_not_a_loss():
    g = pd.concat([_row(sku="1", revenue=-7448, profit=-750, returned=2, net_qty=-2),
                   _row(sku="2", revenue=100, profit=-5, sold=1, net_qty=1),
                   _row(sku=NO_SKU, profit=-10)], ignore_index=True)
    assert list(status_of(g)) == ["только возвраты", "убыток", "общие расходы"]
    # no per-unit numbers from negative units
    assert unit_economics(g, "Выкупы")["profit"].isna().iloc[0]


def test_wb_acquiring_split_keeps_total():
    from pnl.wb import rows_to_ledger
    rows = [{"rr_dt": "2026-10-01", "nm_id": 1, "supplier_oper_name": "Продажа", "quantity": 1,
             "retail_price_withdisc_rub": 1000, "ppvz_for_pay": 700, "acquiring_fee": 15},
            {"rr_dt": "2026-10-02", "nm_id": 1, "supplier_oper_name": "Возврат", "quantity": 1,
             "retail_price_withdisc_rub": 1000, "ppvz_for_pay": 700, "acquiring_fee": 15}]
    led = pd.DataFrame(rows_to_ledger(rows)).astype({"date": str})
    by = led.groupby(["date", "category"])["amount"].sum()
    assert by[("2026-10-01", "acquiring")] == -15
    assert by[("2026-10-01", "commission")] == -285
    assert by[("2026-10-02", "acquiring")] == 15
    assert led["amount"].sum() == 0


def test_buyout_from_outcomes_ignores_orders_in_transit():
    g = _row(ordered_qty=10, delivered_qty=6, cancelled_qty=2, transit_qty=2)
    assert buyout_rate(g).iloc[0] == 0.75
    # no statuses stored yet: share not cancelled
    assert buyout_rate(_row(ordered_qty=10, cancelled_qty=2, unknown_qty=8)).iloc[0] == 0.8


def test_no_sales_status_and_reconciliation():
    g = pd.concat([_row(sku="1", profit=100, sold=1, net_qty=1), _row(sku="2", profit=-30, ordered_qty=3),
                   _row(sku=NO_SKU, profit=-50)], ignore_index=True).assign(cabinet="Ozon · A")
    assert list(status_of(g)) == ["прибыль", "нет продаж", "общие расходы"]
    r = reconcile(g).iloc[0]
    assert (r["profit_items"], r["profit_common"], r["total"], r["diff"]) == (70, -50, 20, 0)


def test_quality_issues_mark_result_preliminary():
    facts = pd.DataFrame({"sku": ["1", "2"], "cost_missing_qty": [0, 5]})
    cabs = pd.DataFrame({"id": [1], "name": ["Перфетто"], "entity_id": [None]})
    taxes = pd.DataFrame(columns=["entity_id", "month", "note"])
    issues = find_issues(facts, taxes, cabs, date(2026, 10, 1), date(2026, 10, 28), set(), {"Ozon · Перфетто": 0})
    texts = " | ".join(i.text for i in issues)
    assert "Нет себестоимости: 5 шт., 1 товаров" in texts
    assert "Налог не считается: Перфетто" in texts
    assert "Постоянные расходы не заполнены: 10.2026" in texts
    assert "Октябрь 2026 · 1–28 · неполный" in texts
    filled = find_issues(facts.iloc[:1], taxes.assign(entity_id=[]), cabs.assign(entity_id=[7]),
                         date(2026, 9, 1), date(2026, 9, 30), {date(2026, 9, 1)}, {})
    assert [i.text for i in filled if i.blocking] == ["Налог не считается: Перфетто — нет юрлица или "
                                                       "налогового режима"]
    assert month_label(date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 30)) == "Сентябрь 2026"
