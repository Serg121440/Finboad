"""Товары: юнит-экономика по каждому товару на выбранной базе."""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, hide_cogs_columns, result_for, period_filters, summarize, with_names,
)
from pnl.engine import NO_SKU

BASES = {
    "Выкупы": "Деньги и штуки по отчёту маркетплейса: продано минус возвраты.",
    "Заказы": "Те же деньги, но на заказанную штуку; маржа и ДРР к сумме заказов.",
    "Сделки": "Выкупы + возвраты + отмены: на каждую попытку продажи.",
}


def render():
    st.title("Товары")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    base = st.radio("База расчёта", list(BASES), horizontal=True)
    st.caption(BASES[base])
    res = result_for(f)
    if res.facts.empty:
        st.warning("За период нет данных.")
        return

    keys = ["cabinet_id", "sku"]
    g = summarize(res.facts, keys)
    o = res.orders.groupby(keys, as_index=False)[["ordered_qty", "ordered_sum", "cancelled_qty",
                                                  "cancelled_sum"]].sum() if not res.orders.empty else \
        pd.DataFrame(columns=keys + ["ordered_qty", "ordered_sum", "cancelled_qty", "cancelled_sum"])
    if not o.empty:
        o["sku"] = o["sku"].astype(str)
    g = g.merge(o, on=keys, how="left").fillna({"ordered_qty": 0, "ordered_sum": 0,
                                                 "cancelled_qty": 0, "cancelled_sum": 0})
    g = with_names(g, f.cabinets, res.products)

    if base == "Выкупы":
        g["base_qty"], g["base_sum"] = g["net_qty"], g["revenue"]
    elif base == "Заказы":
        g["base_qty"], g["base_sum"] = g["ordered_qty"], g["ordered_sum"]
    else:
        g["base_qty"] = g["sold"] + g["cancelled_qty"]
        g["base_sum"] = g["sales_gross"] + g["cancelled_sum"]

    q = g["base_qty"].replace(0, np.nan)
    s = g["base_sum"].replace(0, np.nan)
    g["per_unit"] = g["profit"] / q
    g["price"] = g["base_sum"] / q
    g["mp_per_unit"] = g["mp_result"] / q
    g["cogs_unit"] = -g["cogs"] / g["net_qty"].replace(0, np.nan)
    g["margin_b"] = g["profit"] / s
    g["drr_b"] = -g["ads"] / s
    g["buyout"] = g["net_qty"] / g["ordered_qty"].replace(0, np.nan)
    g["status"] = np.select(
        [g["sku"] == NO_SKU, g["cost_missing_qty"] != 0, g["profit"] < 0],
        ["общие расходы", "нет себестоимости", "убыток"], "прибыль")

    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Поиск по артикулу или названию")
    status = c2.selectbox("Статус", ["Все", "убыток", "прибыль", "нет себестоимости"])
    sort = c3.selectbox("Сортировка", ["Прибыль ↑", "Прибыль ↓", "Выручка ↓", "ДРР ↓"])
    v = g
    if query:
        ql = query.lower()
        v = v[v["article"].str.lower().str.contains(ql, regex=False) |
              v["name"].str.lower().str.contains(ql, regex=False) | (v["sku"] == query)]
    if status != "Все":
        v = v[v["status"] == status]
    by, asc = {"Прибыль ↑": ("profit", True), "Прибыль ↓": ("profit", False),
               "Выручка ↓": ("revenue", False), "ДРР ↓": ("drr_b", False)}[sort]
    v = v.sort_values(by, ascending=asc)

    out = pd.DataFrame({
        "МП": v["marketplace"].map(MP_NAMES), "Кабинет": v["cabinet"], "Артикул": v["article"],
        "SKU": v["sku"], "Товар": v["name"],
        "Заказано, шт": v["ordered_qty"], "Выкуплено нетто, шт": v["net_qty"], "Возвраты, шт": v["returned"],
        "% выкупа": v["buyout"] * 100,
        "Выручка, ₽": v["revenue"], "Цена на базе, ₽": v["price"],
        "Комиссия, ₽": v["commission"], "Логистика, ₽": v["logistics"],
        "Хранение и прочее, ₽": v["storage"] + v["penalties"] + v["services"] + v["other"],
        "Реклама, ₽": v["ads"], "ДРР, %": v["drr_b"] * 100,
        "Себестоимость, ₽/шт": v["cogs_unit"], "Себестоимость, ₽": v["cogs"],
        "Налоги, ₽": v["vat"] + v["tax"],
        "Прибыль, ₽": v["profit"], "Прибыль на шт, ₽": v["per_unit"], "Маржа, %": v["margin_b"] * 100,
        "Статус": v["status"],
    })
    out = hide_cogs_columns(out)
    money = {c: st.column_config.NumberColumn(format="%.0f") for c in out.columns if "₽" in c}
    perc = {c: st.column_config.NumberColumn(format="%.1f") for c in out.columns if "%" in c}
    st.dataframe(out, use_container_width=True, hide_index=True, height=600,
                 column_config={**money, **perc})
    st.caption(f"Товаров: {len(out)}. Строка «общие расходы» — начисления маркетплейса без товара "
               "(реклама «все товары», подписки, услуги склада).")
    st.download_button("Скачать CSV", out.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name=f"товары_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.csv", mime="text/csv")
