"""Сводка: финансовый результат продаж по каждому маркетплейсу и вместе."""

import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, num, pct, result_for, rub, period_filters, summarize, hide_cogs_columns,
)
from dashboard.quality import quality_block
from dashboard.theme import kpi_card, OZON_ACCENT, WB_ACCENT, SUCCESS, DANGER, INFO

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


def _show(table: pd.DataFrame):
    t = table.reset_index().rename(columns={"index": "Показатель"})
    st.dataframe(t, use_container_width=True, hide_index=True, height=35 * (len(t) + 1) + 3,
                 column_config={"Показатель": st.column_config.TextColumn(width="large")})


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

    cols = {}
    for mp in ("wb", "ozon"):
        if (facts["mp"] == mp).any():
            cols[MP_NAMES[mp]] = _column(facts[facts["mp"] == mp],
                                         orders[orders["mp"] == mp] if not orders.empty else orders,
                                         fixed_by_mp.get(mp, 0.0))
    total = _column(facts, orders, sum(fixed_by_mp.values()))
    cols["Всего"] = total

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

    table = pd.DataFrame({name: [_fmt(c.get(key), kind) for key, _, kind in ROWS] for name, c in cols.items()},
                         index=[label for _, label, _ in ROWS])
    if "_common" in fixed_by_mp and len(cols) > 1:
        st.caption(f"Постоянные расходы без привязки к кабинету ({rub(fixed_by_mp['_common'])}) входят только в «Всего».")
    _show(hide_cogs_columns(table.T).T)

    # by cabinet
    if len(f.cabinet_ids) > 1:
        st.subheader("По кабинетам")
        by = {}
        for _, c in f.cabinets[f.cabinets["id"].isin(f.cabinet_ids)].iterrows():
            fc = facts[facts["cabinet_id"] == c["id"]]
            if fc.empty:
                continue
            oc = orders[orders["cabinet_id"] == c["id"]] if not orders.empty else orders
            fxc = float(fixed_sel[fixed_sel["cabinet_id"] == c["id"]]["amount"].sum()) if not fixed_sel.empty else 0.0
            by[f"{MP_NAMES[c['marketplace']]} · {c['name']}"] = _column(fc, oc, fxc)
        if by:
            t2 = pd.DataFrame({n: [_fmt(c.get(key), kind) for key, _, kind in ROWS] for n, c in by.items()},
                              index=[label for _, label, _ in ROWS])
            _show(hide_cogs_columns(t2.T).T)
