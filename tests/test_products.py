import pandas as pd
import pytest

from datetime import date

from dashboard.quality import find_issues, month_label
from dashboard.views.products import allocate_common, buyout_rate, status_of, unit_economics
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
             ordered_qty=20, ordered_sum=21000, cancelled_qty=4, unknown_qty=16)
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
    # cancellations and transit only: nothing bought out yet, not «share not cancelled»
    assert buyout_rate(_row(ordered_qty=10, cancelled_qty=2, transit_qty=8)).iloc[0] == 0
    assert pd.isna(buyout_rate(_row(ordered_qty=3, transit_qty=3)).iloc[0])
    # no statuses stored yet: share not cancelled
    assert buyout_rate(_row(ordered_qty=10, cancelled_qty=2, unknown_qty=8)).iloc[0] == 0.8


def test_no_sales_status():
    g = pd.concat([_row(sku="1", profit=100, sold=1, net_qty=1), _row(sku="2", profit=-30, ordered_qty=3),
                   _row(sku=NO_SKU, profit=-50)], ignore_index=True)
    assert list(status_of(g)) == ["прибыль", "нет продаж", "общие расходы"]


def test_common_expenses_spread_over_products():
    # «все товары» ads 90 by ordered sum (1:2), other common 10 by revenue (3:1)
    g = pd.concat([_row(sku="1", revenue=300, profit=100, ordered_sum=100, cabinet_id=1),
                   _row(sku="2", revenue=100, profit=50, ordered_sum=200, cabinet_id=1),
                   _row(sku=NO_SKU, ads=-90, logistics=-10, profit=-100, cabinet_id=1)], ignore_index=True)
    a = allocate_common(g)
    assert list(a["sku"]) == ["1", "2"]
    assert list(a["ads_common"]) == [-30, -60]
    assert list(a["other_common"]) == [-7.5, -2.5]
    assert list(a["profit"]) == [62.5, -12.5]
    assert a["profit"].sum() == g["profit"].sum()
    # nothing to spread over: the common row stays
    lone = _row(sku=NO_SKU, ads=-5, profit=-5, cabinet_id=2)
    assert list(allocate_common(lone)["sku"]) == [NO_SKU]


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


def test_wb_ads_gap_keeps_result_preliminary():
    facts = pd.DataFrame({"sku": ["1"], "cost_missing_qty": [0]})
    cabs = pd.DataFrame({"id": [2], "name": ["ВБ"], "entity_id": [7]})
    taxes = pd.DataFrame({"entity_id": [7], "month": [date(2026, 9, 1)], "note": [""]})
    issues = find_issues(facts, taxes, cabs, date(2026, 9, 1), date(2026, 9, 30), {date(2026, 9, 1)},
                         {"Wildberries · ВБ": 0}, {"Wildberries · ВБ": 30})
    assert [i.text for i in issues if i.blocking] == ["Wildberries · ВБ: реклама не загружена за дней — 30, "
                                                       "расходы занижены"]


def test_wb_days_after_last_weekly_report_are_flagged():
    facts = pd.DataFrame({"sku": ["1"], "cost_missing_qty": [0]})
    cabs = pd.DataFrame({"id": [2], "name": ["ВБ"], "entity_id": [7]})
    taxes = pd.DataFrame({"entity_id": [7], "month": [date(2026, 10, 1)], "note": [""]})
    args = (facts, taxes, cabs, date(2026, 10, 24), date(2026, 10, 31), {date(2026, 10, 1)}, {})
    # the last report ends 25.10, today is 31.10: 26–30.10 have no WB sales yet
    late = find_issues(*args, None, {"Wildberries · ВБ": date(2026, 10, 25)}, date(2026, 10, 30))
    assert [i.text for i in late if i.blocking] == [
        "Wildberries · ВБ: отчёта WB о реализации за 26.10–30.10 ещё нет — продажи, комиссия и логистика "
        "WB за эти дни не учтены"]
    none = find_issues(*args, None, {"Wildberries · ВБ": None}, date(2026, 10, 30))
    assert "за 24.10–30.10 ещё нет" in none[0].text
    covered = find_issues(*args, None, {"Wildberries · ВБ": date(2026, 11, 1)}, date(2026, 10, 30))
    assert not [i for i in covered if i.blocking]


def test_month_without_tax_setting_is_blocking():
    facts = pd.DataFrame({"sku": ["1"], "cost_missing_qty": [0]})
    cabs = pd.DataFrame({"id": [1], "name": ["A"], "entity_id": [7]})
    taxes = pd.DataFrame({"entity_id": [7, 7], "month": [date(2026, 9, 1), date(2026, 10, 1)],
                          "note": ["налог не считается", ""]})
    issues = find_issues(facts, taxes, cabs, date(2026, 9, 1), date(2026, 10, 31),
                         {date(2026, 9, 1), date(2026, 10, 1)}, {})
    assert [i.text for i in issues if i.blocking] == ["Налоги, 09.2026: налог не считается"]
