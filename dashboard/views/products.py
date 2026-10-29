"""Товары: юнит-экономика по каждому товару на выбранной базе.

Деньги — из начислений по дате продажи, заказы — по дате заказа. Это разные
штуки (в октябре выкупают и сентябрьские заказы), поэтому деньги не делятся
на заказы напрямую: на один заказ = на одну продажу × доля заказов без отмен.
"""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, hide_cogs_columns, result_for, period_filters, summarize, with_names,
)
from pnl.engine import NO_SKU

BASES = {
    "Выкупы": ("на 1 выкуп", "к выручке",
               "Деньги из начислений делятся на выкупленные штуки (продано минус возвраты)."),
    "Заказы": ("на 1 заказ", "к заказам",
               "Сколько приносит один заказ: показатели на выкуп × доля заказов без отмен. "
               "Реклама и ДРР — прямо к заказам: реклама крутится за заказы того же периода."),
    "Сделки": ("на 1 сделку", "к сделкам",
               "Сделка = продажа (в т. ч. потом возвращённая) или отмена: всё, что маркетплейс обработал."),
}
SHORT_PERIOD_DAYS = 14
UNIT_LINES = {"price": "Цена", "commission": "Комиссия", "acquiring": "Эквайринг", "logistics": "Логистика",
              "ads": "Реклама", "cogs": "Себестоимость", "profit": "Прибыль"}


def unit_economics(g: pd.DataFrame, base: str) -> pd.DataFrame:
    """Per-unit money and % of the base sum. g: summarize() merged with order totals."""
    g = g.copy()
    g["commission_net"] = g["commission"] - g["acquiring"]
    g["kept"] = g["ordered_qty"] - g["cancelled_qty"]
    g["keep_rate"] = g["kept"] / g["ordered_qty"].replace(0, np.nan)
    net = g["net_qty"].where(g["net_qty"] > 0)
    lines = {"commission": "commission_net", "acquiring": "acquiring", "logistics": "logistics",
             "ads": "ads", "cogs": "cogs", "profit": "profit"}
    u = pd.DataFrame(index=g.index)

    if base == "Выкупы":
        u["price"] = g["revenue"] / net
        for k, col in lines.items():
            u[k] = g[col] / net
        base_sum = g["revenue"]
    elif base == "Заказы":
        ordered = g["ordered_qty"].replace(0, np.nan)
        u["price"] = g["ordered_sum"] / ordered
        for k, col in lines.items():
            u[k] = g[col] / net * g["keep_rate"]
        # ads and orders are the same period: no conversion
        u["profit"] = u["profit"] - u["ads"] + g["ads"] / ordered
        u["ads"] = g["ads"] / ordered
        base_sum = g["ordered_sum"]
    else:
        deals = (g["sold"] + g["cancelled_qty"]).replace(0, np.nan)
        u["price"] = (g["sales_gross"] + g["cancelled_sum"]) / deals
        for k, col in lines.items():
            u[k] = g[col] / deals
        base_sum = g["sales_gross"] + g["cancelled_sum"]

    if base == "Заказы":
        u["margin"] = u["profit"] / u["price"]
    else:
        u["margin"] = g["profit"] / base_sum.replace(0, np.nan)
    u["drr"] = -g["ads"] / base_sum.replace(0, np.nan)
    return u


def status_of(g: pd.DataFrame) -> pd.Series:
    return pd.Series(np.select(
        [g["sku"] == NO_SKU, (g["sold"] == 0) & (g["returned"] > 0), g["cost_missing_qty"] != 0,
         g["profit"] < 0],
        ["общие расходы", "только возвраты", "нет себестоимости", "убыток"], "прибыль"), index=g.index)


def render():
    st.title("Товары")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    base = st.radio("База расчёта", list(BASES), horizontal=True)
    per, to, note = BASES[base]
    st.caption(f"{note} Деньги — из начислений по дате продажи, заказы и отмены — по дате заказа.")
    days = (f.date_to - f.date_from).days + 1
    if days < SHORT_PERIOD_DAYS:
        st.warning(f"Период {days} дн.: выкупают в основном заказы прошлых недель, а заказы периода "
                   "ещё в пути. Юнит-экономику смотрите за месяц.")
    res = result_for(f)
    if res.facts.empty:
        st.warning("За период нет данных.")
        return

    keys = ["cabinet_id", "sku"]
    order_cols = ["ordered_qty", "ordered_sum", "cancelled_qty", "cancelled_sum"]
    g = summarize(res.facts, keys)
    o = res.orders.groupby(keys, as_index=False)[order_cols].sum() if not res.orders.empty else \
        pd.DataFrame(columns=keys + order_cols)
    o["sku"] = o["sku"].astype(str)
    # orders without any accrual in the period are products too
    g = g.merge(o, on=keys, how="outer")
    num = [c for c in g.columns if c not in keys]
    g[num] = g[num].fillna(0)
    g = with_names(g, f.cabinets, res.products)
    u = unit_economics(g, base)
    g["status"] = status_of(g)
    g["keep_pct"] = (g["ordered_qty"] - g["cancelled_qty"]) / g["ordered_qty"].replace(0, np.nan) * 100

    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Поиск по артикулу или названию")
    status = c2.selectbox("Статус", ["Все", "убыток", "прибыль", "нет себестоимости", "только возвраты"])
    sort = c3.selectbox("Сортировка", ["Прибыль ↑", "Прибыль ↓", "Выручка ↓", "ДРР ↓"])
    v = g.assign(**{f"u_{k}": u[k] for k in u.columns})
    if query:
        ql = query.lower()
        v = v[v["article"].str.lower().str.contains(ql, regex=False) |
              v["name"].str.lower().str.contains(ql, regex=False) | (v["sku"] == query)]
    if status != "Все":
        v = v[v["status"] == status]
    by, asc = {"Прибыль ↑": ("profit", True), "Прибыль ↓": ("profit", False),
               "Выручка ↓": ("revenue", False), "ДРР ↓": ("u_drr", False)}[sort]
    v = v.sort_values(by, ascending=asc)

    out = pd.DataFrame({
        "МП": v["marketplace"].map(MP_NAMES), "Кабинет": v["cabinet"], "Артикул": v["article"],
        "SKU": v["sku"], "Товар": v["name"], "Статус": v["status"],
        # three bases in pieces, always
        "Заказано, шт": v["ordered_qty"], "Отменено, шт": v["cancelled_qty"], "% без отмен": v["keep_pct"],
        "Продано, шт": v["sold"], "Возвраты, шт": v["returned"], "Выкуп нетто, шт": v["net_qty"],
        "Сделки, шт": v["sold"] + v["cancelled_qty"],
        # money of the period, the same on every base
        "Заказано, ₽": v["ordered_sum"], "Выручка, ₽": v["revenue"],
        "Комиссия, ₽": v["commission"] - v["acquiring"], "Эквайринг, ₽": v["acquiring"],
        "Логистика, ₽": v["logistics"],
        "Хранение и прочее, ₽": v["storage"] + v["penalties"] + v["services"] + v["other"],
        "Реклама, ₽": v["ads"], "Себестоимость, ₽": v["cogs"], "Налоги, ₽": v["vat"] + v["tax"],
        "Прибыль, ₽": v["profit"],
        **{f"{t} {per}, ₽": v[f"u_{k}"] for k, t in UNIT_LINES.items()},
        f"Маржа {to}, %": v["u_margin"] * 100, f"ДРР {to}, %": v["u_drr"] * 100,
    })
    out = hide_cogs_columns(out)
    money = {c: st.column_config.NumberColumn(format="%.0f") for c in out.columns if "₽" in c}
    perc = {c: st.column_config.NumberColumn(format="%.1f") for c in out.columns if "%" in c}
    st.dataframe(out, use_container_width=True, hide_index=True, height=600,
                 column_config={**money, **perc})
    st.caption(f"Товаров: {len(out)}. Колонки «₽» — суммы за период, от базы не зависят; "
               f"от базы зависят колонки «{per}» и «{to}». "
               "«только возвраты» — в периоде нет продаж, вернули проданное раньше: выручка и комиссия "
               "сторнируются, себестоимость возвращается (товар снова на складе). "
               "Эквайринг Ozon берёт при оплате заказа, комиссию — при продаже. "
               "Строка «общие расходы» — начисления без товара (реклама «все товары», подписки, услуги склада).")
    st.download_button("Скачать CSV", out.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name=f"товары_{base.lower()}_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.csv",
                       mime="text/csv")
