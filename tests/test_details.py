"""Line breakdown: accrual types under each P&L line add up to that line."""

from datetime import date

import pandas as pd
import pytest

from pnl.engine import DETAIL_LINES, Data, compute


def _data(ledger: list[dict], selected=None) -> Data:
    return Data(
        cabinets=pd.DataFrame([{"id": 1, "marketplace": "ozon", "name": "A", "entity_id": 1},
                               {"id": 2, "marketplace": "ozon", "name": "B", "entity_id": 1}]),
        entities=pd.DataFrame([{"id": 1, "name": "ИП", "kind": "ip"}]),
        tax_settings=pd.DataFrame(columns=["entity_id", "valid_from", "regime"]),
        ledger=pd.DataFrame(ledger),
        ads=pd.DataFrame(columns=["cabinet_id", "date", "sku", "amount", "kind", "campaign_id"]),
        campaigns=pd.DataFrame(columns=["cabinet_id", "campaign_id", "type"]),
        orders=pd.DataFrame(columns=["cabinet_id", "date", "sku", "qty", "amount", "cancelled"]),
        products=pd.DataFrame(columns=["cabinet_id", "sku", "article", "name", "category", "vat10"]),
        cogs=pd.DataFrame(columns=["article", "cabinet_id", "valid_from", "cost"]),
        fixed=pd.DataFrame(columns=["entity_id", "cabinet_id", "month", "item", "amount"]),
        date_from=date(2026, 10, 24), date_to=date(2026, 10, 30), extra={"selected": selected})


def _row(cab, day, category, amount, raw, sku=None, qty=0):
    return {"cabinet_id": cab, "date": date(2026, 10, day), "sku": sku, "category": category,
            "amount": amount, "qty": qty, "posting": "", "raw_type": raw}


LEDGER = [
    _row(1, 24, "sale", 6084.0, "Выручка", "s1", 1),
    _row(1, 24, "sale", 6716.0, "Баллы за скидки", "s1"),
    _row(1, 24, "commission", -6656.0, "Вознаграждение за продажу", "s1"),
    _row(1, 25, "fbo_services", -8255.0, "Обработка товара в составе грузоместа"),
    _row(1, 26, "storage", -3.33, "Размещение на складе"),
    _row(1, 27, "storage", -3.33, "Размещение на складе"),
    _row(1, 28, "storage", -30.0, "Временное размещение товара партнерами"),
    _row(1, 28, "ads_mp", -100.0, "Оплата за клик", "s1"),
    _row(2, 26, "storage", -50.0, None),
    _row(1, 20, "storage", -999.0, "Размещение на складе"),   # before the period
]


def test_breakdown_adds_up_to_each_line():
    r = compute(_data(LEDGER))
    det = r.details
    for line in DETAIL_LINES:
        assert det[det["line"] == line]["amount"].sum() == pytest.approx(r.facts[line].sum(), abs=0.01), line


def test_breakdown_groups_by_category_and_type_inside_period():
    det = compute(_data(LEDGER)).details
    st = det[(det["line"] == "storage") & (det["cabinet_id"] == 1)].set_index(["category", "raw_type"])["amount"]
    assert st.to_dict() == pytest.approx({
        ("fbo_services", "Обработка товара в составе грузоместа"): -8255.0,
        ("storage", "Размещение на складе"): -6.66,
        ("storage", "Временное размещение товара партнерами"): -30.0,
    })
    assert "ads" not in set(det["line"])
    # missing type stays as an empty string, shown as «Без типа»
    assert det[det["cabinet_id"] == 2]["raw_type"].tolist() == [""]


def test_breakdown_keeps_selected_cabinets_only():
    det = compute(_data(LEDGER, selected=[2])).details
    assert set(det["cabinet_id"]) == {2}
