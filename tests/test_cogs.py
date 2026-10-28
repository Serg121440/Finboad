"""Cost page helpers: template round trip and per-cabinet coverage."""

import io
from datetime import date

import pandas as pd

from dashboard.views.cogs import (ALL, _catalog, _cost_for, _current_costs, _template_xlsx, card_cost_rows,
                                  parse_cost_file, read_cost_xlsx)


def _prods():
    return pd.DataFrame([
        {"cabinet_id": 1, "key": "A1", "article": "A1", "name": "Мяч", "cab": "Ozon · A", "card_cost": 100.0, "qty": 5},
        {"cabinet_id": 2, "key": "A1", "article": "A1", "name": "Мяч", "cab": "Ozon · B", "card_cost": 100.0, "qty": 3},
        {"cabinet_id": 1, "key": "B2", "article": "B2", "name": "Гиря", "cab": "Ozon · A", "card_cost": 50.0, "qty": 1},
    ])


def _costs(rows):
    return _current_costs(pd.DataFrame(rows, columns=["id", "article", "cabinet_id", "valid_from", "cost"]))


def test_template_round_trip():
    current = _costs([(1, "B2", None, date(2026, 9, 1), 40.0)])
    raw = read_cost_xlsx(io.BytesIO(_template_xlsx(_catalog(_prods(), current))))
    got = parse_cost_file(raw, ALL)
    assert list(got["Артикул"]) == ["B2"]
    assert got["Себестоимость, ₽/шт"].iloc[0] == 40.0
    assert got["Действует с"].iloc[0] == date(2026, 9, 1)


def test_cabinet_cost_does_not_cover_other_cabinet():
    current = _costs([(1, "A1", 1, date(2000, 1, 1), 100.0)])
    assert _cost_for(current, 1, "A1") and _cost_for(current, 2, "A1") is None
    cat = _catalog(_prods(), current).set_index("key")
    assert cat.loc["A1", "missing"]

    prods = _prods()
    prods["ours"] = [(_cost_for(current, c, k) or (None,))[0] for c, k in zip(prods["cabinet_id"], prods["key"])]
    missing = prods[prods["ours"].isna()]
    assert set(zip(missing["cabinet_id"], missing["key"])) == {(2, "A1"), (1, "B2")}
    rows = card_cost_rows(prods, missing, current)
    # no all-cabinets row for A1 yet and cards agree -> one row for all; B2 likewise
    assert sorted(zip(rows["Артикул"], rows["Кабинет"])) == [("A1", ALL), ("B2", ALL)]


def test_per_cabinet_rows_when_cards_disagree():
    prods = _prods()
    prods.loc[1, "card_cost"] = 120.0
    rows = card_cost_rows(prods, prods[prods["key"] == "A1"], {})
    assert sorted(zip(rows["Кабинет"], rows["Себестоимость, ₽/шт"])) == [("Ozon · A", 100.0), ("Ozon · B", 120.0)]
