"""ОПиУ по месяцам: статьи по строкам, месяцы по столбцам."""

import pandas as pd
import streamlit as st

from dashboard.common import MP_NAMES, pct, result_for, rub, period_filters, summarize, hide_cogs_columns
from dashboard.quality import month_label, quality_block
from pnl.engine import LINE_TITLES

LINES = ["revenue", "commission", "logistics", "storage", "penalties", "services", "other", "ads",
         "mp_result", "cogs", "vat", "tax", "profit"]


def render():
    st.title("ОПиУ по месяцам")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    mp = st.radio("Маркетплейс", ["Все", "Wildberries", "Ozon"], horizontal=True)
    res = result_for(f)
    facts = res.facts
    cab_mp = dict(zip(f.cabinets["id"], f.cabinets["marketplace"]))
    facts = facts.assign(mp=facts["cabinet_id"].map(cab_mp))
    if mp != "Все":
        code = {v: k for k, v in MP_NAMES.items()}[mp]
        facts = facts[facts["mp"] == code]
    if facts.empty:
        st.warning("За период нет данных.")
        return

    quality_block(f, res)
    g = summarize(facts, ["month"]).sort_values("month")
    fx = res.fixed
    if not fx.empty:
        fx = fx[fx["cabinet_id"].isna() | fx["cabinet_id"].isin(f.cabinet_ids)]
        if mp != "Все":
            fx = fx[fx["cabinet_id"].map(cab_mp) == code]
        fxm = fx.groupby("month")["amount"].sum()
    else:
        fxm = pd.Series(dtype=float)
    g["fixed"] = -g["month"].map(fxm).fillna(0)
    g["net"] = g["profit"] + g["fixed"]

    titles = {**LINE_TITLES, "fixed": "Постоянные расходы", "net": "Чистая прибыль",
              "margin": "Маржинальность", "drr": "ДРР"}
    order = LINES + ["fixed", "net", "margin", "drr"]
    months = [month_label(pd.Timestamp(m).date(), f.date_from, f.date_to) for m in g["month"]]
    table = pd.DataFrame(index=[titles[k] for k in order])
    for m, (_, row) in zip(months, g.iterrows()):
        table[m] = [pct(row[k]) if k in ("margin", "drr") else rub(row[k]) for k in order]
    if len(months) > 1:
        tot = summarize(facts.assign(_k=1), ["_k"]).iloc[0]
        tot["fixed"], tot["net"] = g["fixed"].sum(), g["profit"].sum() + g["fixed"].sum()
        table["Итого"] = [pct(tot[k]) if k in ("margin", "drr") else rub(tot[k]) for k in order]
    t = hide_cogs_columns(table.T).T.reset_index().rename(columns={"index": "Статья"})
    st.dataframe(t, use_container_width=True, hide_index=True, height=35 * (len(t) + 1) + 3,
                 column_config={"Статья": st.column_config.TextColumn(width="large")})
    if any("неполный" in m for m in months) and len(months) > 1:
        st.warning("В таблице месяцы разной длины: неполный месяц сравнивайте с другими по средним за день, "
                   "а не по сумме.")
    st.caption("Неполный месяц показан только за дни периода; постоянные расходы такого месяца "
               "пропорциональны числу дней.")

    with st.expander("Статьи начислений маркетплейса подробно"):
        from pnl.data import load
        from pnl.categories import CATEGORIES
        d = load(f.date_from, f.date_to, f.cabinet_ids)
        led = d.ledger
        led = led[(pd.to_datetime(led["date"]).dt.date >= f.date_from) & led["cabinet_id"].isin(f.cabinet_ids)]
        if mp != "Все":
            led = led[led["cabinet_id"].map(cab_mp) == code]
        det = led.groupby(["category", "raw_type"], as_index=False)["amount"].sum()
        det["Статья"] = det["category"].map(lambda c: CATEGORIES.get(c, ("", c))[1])
        det = det.sort_values("amount")[["Статья", "raw_type", "amount"]].rename(
            columns={"raw_type": "Начисление в отчёте", "amount": "Сумма, ₽"})
        st.dataframe(det, use_container_width=True, hide_index=True,
                     column_config={"Сумма, ₽": st.column_config.NumberColumn(format="%.2f")})
