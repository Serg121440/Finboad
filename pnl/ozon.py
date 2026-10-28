"""Ozon accruals -> ledger rows.

Two inputs give the same result (checked to the kopeck on 13.09–13.10.2026):
- Seller API `/v1/finance/accrual/by-day` (JSON);
- «Отчёт по начислениям» xlsx from the seller cabinet.

Seller price of a sale = Выручка + Баллы за скидки + Программы партнёров,
which in the API is `posting.products[].commission.sale_amount`.
"""

import json
import os
from datetime import date, datetime

from pnl.categories import OZON_TYPES, OZON_REPORT_TYPES, OZON_REPORT_GROUPS

_TYPES_FILE = os.path.join(os.path.dirname(__file__), "ozon_accrual_types.json")


def load_types(api_types: list | None = None) -> dict[int, dict]:
    """type_id -> {name, description}. API answer wins over the bundled copy."""
    with open(_TYPES_FILE, encoding="utf-8") as f:
        types = {int(k): v for k, v in json.load(f).items()}
    for t in api_types or []:
        types[int(t["id"])] = {"name": t["name"], "description": t.get("description", "")}
    return types


def _money(m) -> float:
    if not m:
        return 0.0
    return float(m.get("amount") or 0)


def _category(type_id: int, types: dict) -> tuple[str, str]:
    t = types.get(type_id, {})
    name = t.get("name", f"type_{type_id}")
    return OZON_TYPES.get(name, "other"), t.get("description") or name


def accruals_to_ledger(accruals: list[dict], types: dict) -> list[dict]:
    """Convert accrual objects from /v1/finance/accrual/by-day to ledger rows."""
    rows = []
    for a in accruals:
        d = date.fromisoformat(a["date"][:10])
        aid = a["accrual_id"]
        unit = a.get("unit_number") or ""
        n = 0

        def add(category, amount, sku=None, qty=0, raw=""):
            nonlocal n
            if not amount and not qty:
                return
            rows.append({
                "date": d, "sku": str(sku) if sku else None, "category": category,
                "amount": round(amount, 2), "qty": qty, "posting": unit,
                "raw_type": raw, "source_key": f"{aid}:{n}",
            })
            n += 1

        posting = a.get("posting") or {}
        for p in posting.get("products") or []:
            sku = p.get("sku")
            c = p.get("commission")
            if c:
                amount = _money(c.get("sale_amount"))
                qty = int(p.get("quantity") or 0)
                if amount >= 0:
                    add("sale", amount, sku, qty, "Продажа")
                else:
                    add("return", amount, sku, -qty, "Возврат")
                add("commission", _money(c.get("commission")), sku, 0, "Вознаграждение Ozon")
            for s in (p.get("delivery") or {}).get("services") or []:
                cat, raw = _category(s["type_id"], types)
                add(cat, _money(s.get("accrued")), sku, 0, raw)

        for item in (a.get("item_fees") or {}).get("fees") or []:
            for f in item.get("fees") or []:
                cat, raw = _category(f["type_id"], types)
                add(cat, _money(f.get("accrued")), item.get("sku"), 0, raw)

        fee = a.get("non_item_fee")
        if fee:
            cat, raw = _category(fee["type_id"], types)
            add(cat, _money(fee.get("accrued")), None, 0, raw)

        for f in (a.get("container_fees") or {}).get("fees") or []:
            cat, raw = _category(f["type_id"], types)
            add(cat, _money(f.get("accrued")), None, 0, raw)
    return rows


# ── xlsx «Отчёт по начислениям» ───────────────────────────────────────────────

REPORT_COLUMNS = {
    "id": "ID начисления",
    "date": "Дата начисления",
    "group": "Группа услуг",
    "type": "Тип начисления",
    "sku": "SKU",
    "qty": "Количество",
    "amount": "Сумма итого, руб.",
}


def _report_category(group: str, type_: str, by_description: dict) -> str:
    if group == "Возвраты":
        return "return"
    if type_ in OZON_REPORT_TYPES:
        return OZON_REPORT_TYPES[type_]
    if type_ in by_description:
        return by_description[type_]
    return OZON_REPORT_GROUPS.get(group, "other")


def report_to_ledger(df, types: dict | None = None) -> list[dict]:
    """Rows of the accrual xlsx (pandas DataFrame, header row = column names)."""
    types = types or load_types()
    by_description = {}
    for t in types.values():
        cat = OZON_TYPES.get(t["name"])
        if cat:
            by_description.setdefault(t["description"], cat)

    c = REPORT_COLUMNS
    missing = [v for v in c.values() if v not in df.columns]
    if missing:
        raise ValueError("В файле нет колонок: " + ", ".join(missing))

    rows, seen = [], {}
    for r in df.itertuples(index=False):
        rec = dict(zip(df.columns, r))
        amount = float(rec[c["amount"]] or 0)
        group, type_ = str(rec[c["group"]] or ""), str(rec[c["type"]] or "")
        cat = _report_category(group, type_, by_description)
        sku = rec[c["sku"]]
        sku = None if sku in (None, "") or str(sku) == "nan" else str(sku).split(".")[0]
        qty = 0
        # A negative sale line is a reversal: count it as a return, like the API does.
        if cat == "sale" and amount < 0:
            cat = "return"
        if type_ == "Выручка":
            qty = int(rec[c["qty"]] or 0) * (1 if amount >= 0 else -1)
        elif type_ == "Возврат выручки":
            qty = -int(rec[c["qty"]] or 0)
        d = rec[c["date"]]
        d = d.date() if isinstance(d, datetime) else date.fromisoformat(str(d)[:10])
        base = f"x:{rec[c['id']]}:{type_}"
        seen[base] = seen.get(base, 0) + 1
        rows.append({
            "date": d, "sku": sku, "category": cat, "amount": round(amount, 2),
            "qty": qty, "posting": str(rec[c["id"]]), "raw_type": type_,
            "source_key": f"{base}:{seen[base]}",
        })
    return rows


def read_report(path_or_buffer):
    """Read the cabinet xlsx: first row is «Период: …», headers on the second."""
    import pandas as pd
    return pd.read_excel(path_or_buffer, header=1)
