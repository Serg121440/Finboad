"""Сводка: финансовый результат продаж по каждому маркетплейсу и вместе."""

import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, num, pct, result_for, rub, period_filters, summarize,
)
from dashboard.quality import quality_block, status_line
from dashboard.theme import kpi_card, tree_table, OZON_ACCENT, WB_ACCENT, SUCCESS, DANGER, INFO
from pnl.categories import CATEGORIES
from pnl.engine import DETAIL_LINES

ROWS = [
    ("ordered_sum", "Заказы, ₽", "rub"),
    ("ordered_qty", "Заказы, шт", "num"),
    ("revenue", "Выручка (цена продавца, за вычетом возвратов)", "rub"),
    ("sold", "Продано, шт", "num"),
    ("returned", "Возвраты, шт", "num"),
    ("commission", "Комиссия МП с эквайрингом", "rub"),
    ("logistics", "Логистика", "rub"),
    ("storage", "Хранение и склад", "rub"),
    ("penalties", "Штрафы и удержания", "rub"),
    ("services", "Подписки и сервисы", "rub"),
    ("other", "Компенсации и прочее", "rub"),
    ("ads", "Реклама", "rub"),
    ("mp_result", "К перечислению после рекламы", "rub"),
    ("cogs", "Себестоимость", "rub"),
    ("vat", "НДС", "rub"),
    ("tax", "Налог", "rub"),
    ("profit", "Прибыль до постоянных расходов", "rub"),
    ("margin", "Маржинальность", "pct"),
    ("drr", "ДРР к выручке", "pct"),
    ("drr_orders", "ДРР к заказам", "pct"),
    ("roi", "ROI (прибыль / себестоимость)", "pct"),
    ("fixed", "Постоянные расходы", "rub"),
    ("net", "Чистая прибыль", "rub"),
]


def _column(facts: pd.DataFrame, orders: pd.DataFrame, fixed: float) -> dict:
    s = summarize(facts.assign(_k=1), ["_k"]).iloc[0].to_dict() if not facts.empty else {}
    s["ordered_sum"] = float(orders["ordered_sum"].sum()) if not orders.empty else 0.0
    s["ordered_qty"] = float(orders["ordered_qty"].sum()) if not orders.empty else 0.0
    s["drr_orders"] = (-s.get("ads", 0) / s["ordered_sum"]) if s["ordered_sum"] else None
    s["fixed"] = -fixed
    s["net"] = s.get("profit", 0) - fixed
    return s


def _fmt(v, kind):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return {"rub": rub, "num": num, "pct": pct}[kind](v)


STRONG = {"mp_result", "profit", "net"}
# money lines shown with their share of the column's revenue: costs as a plain share,
# results with their sign (как маржа)
SHARE_LINES = set(DETAIL_LINES) - {"revenue"} | {"ads", "cogs", "vat", "tax", "fixed"}
SIGNED_SHARE = {"mp_result", "profit", "net"}


def _share(v, revenue, signed=False):
    if v is None or pd.isna(v) or not v or not revenue or pd.isna(revenue):
        return None
    return v / revenue if signed else abs(v) / abs(revenue)


def _breakdown(details: pd.DataFrame, line: str, scopes: list, revenues: list) -> list[dict]:
    """Rows under a P&L line: ledger category -> accrual type, one value per column scope."""
    d = details[details["line"] == line] if not details.empty else details
    if d.empty:
        return []

    def node(label, part):
        vals = [part[part["cabinet_id"].isin(ids)]["amount"].sum() if part["cabinet_id"].isin(ids).any()
                else None for ids in scopes]
        shares = [_share(v, r) for v, r in zip(vals, revenues)] if line != "revenue" else [None] * len(vals)
        return {"label": label, "kind": "rub", "values": vals, "shares": shares, "children": []}

    rows = []
    for cat, part in sorted(d.groupby("category"), key=lambda kv: -abs(kv[1]["amount"].sum())):
        types = part.assign(raw_type=part["raw_type"].replace("", "Без типа"))
        kids = [node(t, p) for t, p in sorted(types.groupby("raw_type"), key=lambda kv: -abs(kv[1]["amount"].sum()))]
        label = CATEGORIES.get(cat, ("", cat))[1] or cat
        row = node(label, part)
        # a category with a single accrual type of the same meaning needs no third level
        if not (len(kids) == 1 and kids[0]["label"] in ("Без типа", label)):
            row["children"] = kids
        rows.append(row)
    return rows


def table_rows(cols: dict, scopes: list, details: pd.DataFrame, hidden: set = frozenset()) -> list[dict]:
    """Numbers of the report: one row per P&L line with values, shares of revenue and breakdown.
    cols: column name -> stats; scopes: cabinet ids behind each column (same order)."""
    revenues = [c.get("revenue") for c in cols.values()]
    rows = []
    for key, label, kind in ROWS:
        if key in hidden:
            continue
        vals = [c.get(key) for c in cols.values()]
        shares = ([_share(v, r, key in SIGNED_SHARE) for v, r in zip(vals, revenues)]
                  if key in SHARE_LINES | SIGNED_SHARE else [None] * len(vals))
        rows.append({"label": label, "kind": kind, "values": vals, "shares": shares,
                     "children": _breakdown(details, key, scopes, revenues) if key in DETAIL_LINES else [],
                     "strong": key in STRONG})
    return rows


def _hidden() -> set:
    acc = st.session_state.get("access")
    return {"cogs", "roi"} if acc and acc.hide_cogs else set()


def _html_rows(rows: list[dict]) -> list[dict]:
    return [{"label": r["label"], "strong": r.get("strong"),
             "values": [(_fmt(v, r["kind"]), pct(sh) if sh is not None else "")
                        for v, sh in zip(r["values"], r["shares"])],
             "children": _html_rows(r["children"])} for r in rows]


def _show(cols: dict, scopes: list, details: pd.DataFrame) -> list[dict]:
    rows = table_rows(cols, scopes, details, _hidden())
    tree_table(list(cols), _html_rows(rows))
    return rows


def excel_report(sections: list[tuple[str, list[str], list[dict]]], header: list[str]) -> bytes:
    """xlsx: one sheet per table; each column as ₽ and % of revenue, breakdown rows indented."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    wb.remove(wb.active)
    for title, names, rows in sections:
        ws = wb.create_sheet(title[:31])
        for line in header:
            ws.append([line])
        ws.append([])
        ws.append(["Показатель"] + [h for n in names for h in (n, f"{n}, % выручки")])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)

        def put(r, level):
            vals = []
            for v, sh in zip(r["values"], r["shares"]):
                v = None if v is None or pd.isna(v) else float(v)
                vals += [round(v, 4) if r["kind"] == "pct" and v is not None else
                         (round(v, 2) if v is not None else None),
                         round(sh, 4) if sh is not None else None]
            ws.append([r["label"]] + vals)
            row = ws[ws.max_row]
            row[0].alignment = Alignment(indent=2 * level)
            if r.get("strong"):
                for c in row:
                    c.font = Font(bold=True)
            for i, c in enumerate(row[1:]):
                if i % 2:
                    c.number_format = "0.0%"
                else:
                    c.number_format = {"rub": "#,##0 ₽;-#,##0 ₽", "num": "#,##0", "pct": "0.0%"}[r["kind"]]
            # a single accrual type repeats its group's sum: the group is enough in a sheet
            for k in r["children"] if len(r["children"]) > 1 else []:
                put(k, level + 1)

        for r in rows:
            put(r, 0)
        ws.column_dimensions["A"].width = 52
        for i in range(2, 2 + 2 * len(names)):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 18 if i % 2 == 0 else 11
        ws.freeze_panes = ws.cell(row=len(header) + 3, column=2)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render():
    st.title("Финансовый результат")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет. Добавьте кабинет на странице «Кабинеты и налоги» — данные загрузятся по API.")
        return
    res = result_for(f)
    facts, orders, fixed = res.facts, res.orders, res.fixed
    cab_mp = dict(zip(f.cabinets["id"], f.cabinets["marketplace"]))
    facts = facts.assign(mp=facts["cabinet_id"].map(cab_mp))
    orders = orders.assign(mp=orders["cabinet_id"].map(cab_mp)) if not orders.empty else orders

    fixed_sel = fixed
    if not fixed.empty:
        cab_fixed = fixed["cabinet_id"].notna()
        fixed_sel = fixed[~cab_fixed | fixed["cabinet_id"].isin(f.cabinet_ids)]
    fixed_by_mp = {}
    if not fixed_sel.empty:
        fx = fixed_sel.assign(mp=fixed_sel["cabinet_id"].map(cab_mp))
        fixed_by_mp = fx.groupby(fx["mp"].fillna("_common"))["amount"].sum().to_dict()

    st.caption(f"{f.date_from:%d.%m.%Y} — {f.date_to:%d.%m.%Y} · база: выкупы по дате начисления в отчёте "
               "маркетплейса · заказы по дате заказа")

    if facts.empty:
        st.warning("За период нет данных. Проверьте загрузку на странице «Кабинеты и налоги».")
        return

    issues = quality_block(f, res)
    final = "" if not any(i.blocking for i in issues) else " (предварительно)"

    cols, scopes = {}, []
    for mp in ("wb", "ozon"):
        if (facts["mp"] == mp).any():
            cols[MP_NAMES[mp]] = _column(facts[facts["mp"] == mp],
                                         orders[orders["mp"] == mp] if not orders.empty else orders,
                                         fixed_by_mp.get(mp, 0.0))
            scopes.append([i for i, m in cab_mp.items() if m == mp])
    total = _column(facts, orders, sum(fixed_by_mp.values()))
    cols["Всего"] = total
    scopes.append(list(f.cabinet_ids))

    k = st.columns(4)
    with k[0]:
        kpi_card("Выручка", rub(total.get("revenue")), f"заказы {rub(total['ordered_sum'])}", accent=INFO)
    with k[1]:
        p = total.get("profit", 0)
        kpi_card("Прибыль до постоянных", rub(p), f"маржа {pct(total.get('margin'))}",
                 "up" if p >= 0 else "down", accent=SUCCESS if p >= 0 else DANGER)
    with k[2]:
        kpi_card("Реклама", rub(-total.get("ads", 0)), f"ДРР {pct(total.get('drr'))}", accent=WB_ACCENT)
    with k[3]:
        n = total["net"]
        kpi_card("Чистая прибыль" + final, rub(n), f"постоянные {rub(-total['fixed'])}",
                 "up" if n >= 0 else "down", accent=OZON_ACCENT)

    if "_common" in fixed_by_mp and len(cols) > 1:
        st.caption(f"Постоянные расходы без привязки к кабинету ({rub(fixed_by_mp['_common'])}) входят только в «Всего».")
    st.caption("Строки со стрелкой ▸ раскрываются до групп и типов начислений из отчёта маркетплейса. "
               "Под суммой — доля от выручки этой колонки.")
    sections = [("Финрезультат", list(cols), _show(cols, scopes, res.details))]

    # by cabinet
    if len(f.cabinet_ids) > 1:
        st.subheader("По кабинетам")
        by, by_scopes = {}, []
        for _, c in f.cabinets[f.cabinets["id"].isin(f.cabinet_ids)].iterrows():
            fc = facts[facts["cabinet_id"] == c["id"]]
            if fc.empty:
                continue
            oc = orders[orders["cabinet_id"] == c["id"]] if not orders.empty else orders
            fxc = float(fixed_sel[fixed_sel["cabinet_id"] == c["id"]]["amount"].sum()) if not fixed_sel.empty else 0.0
            by[f"{MP_NAMES[c['marketplace']]} · {c['name']}"] = _column(fc, oc, fxc)
            by_scopes.append([c["id"]])
        if by:
            sections.append(("По кабинетам", list(by), _show(by, by_scopes, res.details)))

    header = [f"Финансовый результат {f.date_from:%d.%m.%Y} — {f.date_to:%d.%m.%Y}", status_line(issues)]
    st.download_button("Скачать Excel", excel_report(sections, header), type="secondary",
                       file_name=f"финрезультат_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
