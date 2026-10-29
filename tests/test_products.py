import pandas as pd
import pytest

from dashboard.views.products import status_of, unit_economics
from pnl.engine import NO_SKU


def _row(**kw):
    base = dict(sku="1", revenue=0.0, commission=0.0, acquiring=0.0, logistics=0.0, ads=0.0, cogs=0.0,
                profit=0.0, sold=0, returned=0, net_qty=0, sales_gross=0.0, cost_missing_qty=0,
                ordered_qty=0, ordered_sum=0.0, cancelled_qty=0, cancelled_sum=0.0)
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
