"""Реклама: расход по кабинетам и товарам, доля общей рекламы, ДРР."""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, Filters, ads_daily_for, data_version, pct, result_for, rub, period_filters, summarize, with_names,
)
from dashboard.quality import quality_block
from dashboard.views.products import drr_limit
from dashboard.views.products_overview import previous_period
from dashboard.views.report_charts import ads_overview
from pnl.engine import NO_SKU


def render():
    st.title("Реклама")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    mps = [m for m in ("ozon", "wb") if (f.cabinets[f.cabinets["id"].isin(f.cabinet_ids)]["marketplace"] == m).any()]
    if len(mps) > 1:
        pick = st.segmented_control("Площадка", ["Все"] + [MP_NAMES[m] for m in mps], key="ads_mp",
                                    default="Все", label_visibility="collapsed") or "Все"
        if pick != "Все":
            code = {v: k for k, v in MP_NAMES.items()}[pick]
            ids = f.cabinets[f.cabinets["id"].isin(f.cabinet_ids) & (f.cabinets["marketplace"] == code)]["id"].tolist()
            f = Filters(f.date_from, f.date_to, ids, f.cabinets)
    res = result_for(f)
    if res.facts.empty:
        st.warning("За период нет данных.")
        return
    quality_block(f, res, compact=True)
    facts = res.facts
    p0, p1, label = previous_period(f.date_from, f.date_to)
    prev = result_for(Filters(p0, p1, f.cabinet_ids, f.cabinets))
    daily = ads_daily_for(f.date_from, f.date_to, tuple(sorted(f.cabinet_ids)), data_version())
    named = with_names(summarize(facts, ["cabinet_id", "sku"]), f.cabinets, res.products)
    ads_overview(res, prev, label, daily, named, f.cabinets, drr_limit())
    st.subheader("По кабинетам")
    by_cab = summarize(facts, ["cabinet_id"])
    common = facts[facts["sku"] == NO_SKU].groupby("cabinet_id")["ads"].sum()
    rows = []
    for _, r in by_cab.iterrows():
        c = f.cabinets[f.cabinets["id"] == r["cabinet_id"]].iloc[0]
        ads = -r["ads"]
        com = -common.get(r["cabinet_id"], 0.0)
        rows.append({"Кабинет": f"{MP_NAMES[c['marketplace']]} · {c['name']}", "Реклама": rub(ads),
                     "по товарам": rub(ads - com), "общая (не делится по товарам)": rub(com),
                     "ДРР к выручке": pct(r["drr"])})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Ozon: сумма — из отчёта по начислениям. Клики раскладываются по товарам по статистике кампаний, "
               "«оплата за заказ: выбранные товары» — по отчёту о заказах. «Оплата за заказ — все товары» по "
               "товарам не делится и остаётся общей. WB: расход из кабинета продвижения.")

    g = summarize(facts[facts["sku"] != NO_SKU], ["cabinet_id", "sku"])
    g = with_names(g, f.cabinets, res.products)
    g = g[g["ads"] != 0].sort_values("ads")
    rev = g["revenue"].replace(0, np.nan)
    out = pd.DataFrame({
        "Кабинет": g["cabinet"], "Артикул": g["article"], "Товар": g["name"],
        "Реклама, ₽": -g["ads"], "Выручка, ₽": g["revenue"], "ДРР, %": -g["ads"] / rev * 100,
        "Прибыль до рекламы, ₽": g["profit"] - g["ads"], "Прибыль, ₽": g["profit"],
    })
    st.subheader("По товарам")
    st.dataframe(out, use_container_width=True, hide_index=True, height=500, column_config={
        c: st.column_config.NumberColumn(format="%.0f" if "₽" in c else "%.1f") for c in out.columns
        if "₽" in c or "%" in c})
