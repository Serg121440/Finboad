"""Golden test: Ozon ООО «Перфетто Спорт», 13.09–13.10.2026.

Reference numbers come from the unit-economics file reconciled with the cabinet
accrual report to the kopeck. Seller data is private, so the fixtures live in
tests/private/ (gitignored) and the test is skipped without them.
"""

import json
import os
from datetime import date

import pandas as pd
import pytest

HERE = os.path.dirname(__file__)
P = os.path.join(HERE, "private")
FILES = {
    "acc": os.path.join(P, "ozon_ooo_accruals_0913_1013.json"),
    "xlsx": os.path.join(P, "ozon_ooo_accruals_0913_1013.xlsx"),
    "camps": os.path.join(P, "ozon_ooo_perf_campaigns_0913_1013.json"),
    "sku": os.path.join(P, "ozon_ooo_perf_sku_0913_1013.json"),
    "unit": os.path.join(P, "ozon_ooo_unit_0913_1013.xlsx"),
}
pytestmark = pytest.mark.skipif(not all(os.path.exists(f) for f in FILES.values()),
                                reason="private fixtures not present")

D0, D1 = date(2026, 9, 13), date(2026, 10, 13)


@pytest.fixture(scope="module")
def data():
    from pnl import ozon
    from pnl.engine import Data

    acc = json.load(open(FILES["acc"]))
    types = ozon.load_types(acc["types"]["accrual_types"])
    rows = ozon.accruals_to_ledger([x for v in acc["days"].values() for x in v], types)
    led = pd.DataFrame(rows).assign(cabinet_id=1)

    perf = json.load(open(FILES["camps"]))
    camps = pd.DataFrame([{"cabinet_id": 1, "campaign_id": cid, "type": c.get("advObjectType"), "name": ""}
                          for cid, c in perf["camps"].items()])
    sku = json.load(open(FILES["sku"]))
    ads = pd.DataFrame(
        [{"cabinet_id": 1, "date": date.fromisoformat(r["date"]), "sku": r["sku"], "amount": r["amount"],
          "kind": "alloc_cpc", "campaign_id": r["campaign_id"]} for r in sku["cpc"]]
        + [{"cabinet_id": 1, "date": date.fromisoformat(r["date"]), "sku": r["sku"], "amount": r["amount"],
            "kind": "alloc_cpo", "campaign_id": ""} for r in sku["cpo"]])

    rep = pd.read_excel(FILES["xlsx"], header=1)
    prods = (rep[rep["SKU"].notna()][["SKU", "Артикул", "Название товара"]].drop_duplicates("SKU")
             .rename(columns={"SKU": "sku", "Артикул": "article", "Название товара": "name"}))
    prods["sku"] = prods["sku"].astype(str).str.split(".").str[0]
    prods = prods.assign(cabinet_id=1, category="", vat10=False)

    unit = pd.read_excel(FILES["unit"], sheet_name="Юнитка", header=3)
    unit = unit[unit["Артикул"].notna() & (unit["Артикул"] != "ИТОГО")]
    cogs = unit[unit["Себестоимость, ₽/шт"].notna()][["Артикул", "Себестоимость, ₽/шт"]]
    cogs = cogs.rename(columns={"Артикул": "article", "Себестоимость, ₽/шт": "cost"}).assign(
        cabinet_id=None, valid_from=date(2026, 1, 1))

    return Data(
        cabinets=pd.DataFrame([{"id": 1, "marketplace": "ozon", "name": "ООО", "entity_id": 1}]),
        entities=pd.DataFrame([{"id": 1, "name": "ООО", "kind": "ooo"}]),
        tax_settings=pd.DataFrame(columns=["entity_id", "valid_from", "regime"]),
        ledger=led, ads=ads, campaigns=camps,
        orders=pd.DataFrame(columns=["cabinet_id", "date", "sku", "qty", "amount", "cancelled"]),
        products=prods, cogs=cogs,
        fixed=pd.DataFrame(columns=["entity_id", "cabinet_id", "month", "item", "amount"]),
        date_from=D0, date_to=D1, extra={}), unit


def test_store_totals_match_accrual_report(data):
    from pnl.engine import compute
    d, unit = data
    f = compute(d).facts
    assert f["revenue"].sum() == pytest.approx(20042685.00, abs=0.01)
    assert f["commission"].sum() == pytest.approx(-10248200.14 - 126445.06 - 326018.64, abs=0.01)
    assert f["ads"].sum() == pytest.approx(-2561904.02, abs=0.01)
    # everything the marketplace accrued = report total
    assert f["mp_result"].sum() == pytest.approx(5667227.17, abs=0.01)


def test_all_sku_promo_stays_common(data):
    from pnl.engine import ads_by_sku, normalize
    d, _ = data
    a = ads_by_sku(normalize(d))
    common = a[a["sku"] == ""]["ads"].sum()
    # «Оплата за заказ — все товары» = 734 864.20 cannot be split by SKU
    assert common == pytest.approx(-734864.20, abs=1.0)


def test_cogs_and_treadmill(data):
    from pnl.engine import compute
    d, unit = data
    f = compute(d).facts
    # unit file: 6 663 500 for 2144 net units; we count 3 sale reversals as returns (2138 net)
    assert f["cogs"].sum() == pytest.approx(-6663500, rel=0.01)
    t = f[f["sku"] == "5764919957"]
    assert t["revenue"].sum() == pytest.approx(2562597, abs=1)
    # treadmill ads: clicks 362 197.73 + «оплата за заказ» 227 075.70 in the unit file
    assert t["ads"].sum() == pytest.approx(-589273.43, rel=0.02)
