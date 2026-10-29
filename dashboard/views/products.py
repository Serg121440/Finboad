"""Товары: юнит-экономика по каждому товару.

Суммы — факт по начислениям (по дате продажи), заказы — по дате заказа. Это
разные штуки (в октябре выкупают и сентябрьские заказы), поэтому деньги не
делятся на заказы напрямую: на один заказ = на одну продажу × доля выкупа
заказов (по исходам заказов периода; пока статусов нет — доля без отмен).
"""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, hide_cogs_columns, result_for, period_filters, rub, summarize, with_names,
)
from dashboard.quality import quality_block, status_line
from pnl.engine import LINE_TITLES, NO_SKU, ORDER_COLS

BASES = {
    "Выкупы": ("1 выкуп", "на 1 выкуп", "к выручке",
               "Факт по начислениям делится на выкупленные штуки (продано минус возвраты)."),
    "Заказы": ("1 заказ", "на 1 заказ", "к заказам",
               "Показатели на заказанную единицу: на выкуп × доля выкупа заказов. Реклама и ДРР — прямо к "
               "заказам: реклама крутится за заказы того же периода. Это не прогноз прибыли заказов."),
    "Сделки": ("1 сделку", "на 1 сделку", "к сделкам",
               "Сделка = продажа (в т. ч. потом возвращённая) или отмена: всё, что маркетплейс обработал."),
}
SHORT_PERIOD_DAYS = 14
UNIT_LINES = {"price": "Цена", "commission": "Комиссия", "acquiring": "Эквайринг", "logistics": "Логистика",
              "ads": "Реклама", "cogs": "Себестоимость", "profit": "Прибыль"}
COMMON_LINES = ["ads", "logistics", "storage", "penalties", "services", "other", "commission"]
FILTER_KEYS = ("prod_query", "prod_status")


def buyout_rate(g: pd.DataFrame) -> pd.Series:
    """Share of the period's orders that were bought out, among orders with a known outcome.
    Without statuses (WB, old loads) — share of orders not cancelled."""
    resolved = g["delivered_qty"] + g["cancelled_qty"]
    known = g["delivered_qty"] / resolved.where((resolved > 0) & (g["delivered_qty"] > 0))
    fallback = (g["ordered_qty"] - g["cancelled_qty"]) / g["ordered_qty"].replace(0, np.nan)
    return known.fillna(fallback)


def unit_economics(g: pd.DataFrame, base: str) -> pd.DataFrame:
    """Per-unit money and % of the base sum. g: summarize() merged with order totals."""
    g = g.copy()
    g["commission_net"] = g["commission"] - g["acquiring"]
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
        rate = buyout_rate(g)
        u["price"] = g["ordered_sum"] / ordered
        for k, col in lines.items():
            u[k] = g[col] / net * rate
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
        [g["sku"] == NO_SKU, (g["sold"] == 0) & (g["returned"] > 0), (g["sold"] == 0) & (g["returned"] == 0),
         g["cost_missing_qty"] != 0, g["profit"] < 0],
        ["общие расходы", "только возвраты", "нет продаж", "нет себестоимости", "убыток"], "прибыль"),
        index=g.index)


def reconcile(g: pd.DataFrame) -> pd.DataFrame:
    """Per cabinet: products + common expenses = cabinet total."""
    items = g[g["sku"] != NO_SKU].groupby("cabinet", as_index=False)["profit"].sum()
    common = g[g["sku"] == NO_SKU].groupby("cabinet", as_index=False)["profit"].sum()
    t = items.merge(common, on="cabinet", how="outer", suffixes=("_items", "_common")).fillna(0)
    total = g.groupby("cabinet", as_index=False)["profit"].sum().rename(columns={"profit": "total"})
    t = t.merge(total, on="cabinet")
    t["diff"] = t["profit_items"] + t["profit_common"] - t["total"]
    return t


def _reset_filters():
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


def render():
    st.title("Товары")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    base = st.radio("Показатели «на единицу» считать на", list(BASES), horizontal=True,
                    format_func=lambda b: BASES[b][0])
    _, per, to, note = BASES[base]
    st.caption(f"Суммы в ₽ — факт по начислениям за период, от выбора не зависят. {note}")
    days = (f.date_to - f.date_from).days + 1
    if days < SHORT_PERIOD_DAYS:
        st.warning(f"Период {days} дн.: выкупают в основном заказы прошлых недель, а заказы периода "
                   "ещё в пути. Юнит-экономику смотрите за месяц.")
    res = result_for(f)
    if res.facts.empty:
        st.warning("За период нет данных.")
        return
    issues = quality_block(f, res)

    keys = ["cabinet_id", "sku"]
    g = summarize(res.facts, keys)
    o = res.orders.groupby(keys, as_index=False)[ORDER_COLS].sum() if not res.orders.empty else \
        pd.DataFrame(columns=keys + ORDER_COLS)
    o["sku"] = o["sku"].astype(str)
    # orders without any accrual in the period are products too
    g = g.merge(o, on=keys, how="outer")
    num = [c for c in g.columns if c not in keys]
    g[num] = g[num].fillna(0)
    g = with_names(g, f.cabinets, res.products)
    nameless = (g["name"] == "") & (g["sku"] != NO_SKU)
    g.loc[nameless, "name"] = "SKU " + g.loc[nameless, "sku"] + " · нет в каталоге"
    u = unit_economics(g, base)
    g["status"] = status_of(g)
    g["buyout_pct"] = buyout_rate(g) * 100

    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Поиск по артикулу или названию", key="prod_query")
    status = c2.selectbox("Статус", ["Все", "убыток", "прибыль", "нет себестоимости", "нет продаж",
                                     "только возвраты"], key="prod_status")
    sort = c3.selectbox("Сортировка", ["Прибыль ↑", "Прибыль ↓", "Выручка ↓", "ДРР ↓"])
    v = g.assign(**{f"u_{k}": u[k] for k in u.columns})
    if query:
        ql = query.lower()
        v = v[v["article"].str.lower().str.contains(ql, regex=False) |
              v["name"].str.lower().str.contains(ql, regex=False) | (v["sku"] == query)]
    if status != "Все":
        v = v[v["status"] == status]
    if v.empty:
        st.info("Ничего не найдено.")
        st.button("Сбросить фильтры", on_click=_reset_filters)
        return
    by, asc = {"Прибыль ↑": ("profit", True), "Прибыль ↓": ("profit", False),
               "Выручка ↓": ("revenue", False), "ДРР ↓": ("u_drr", False)}[sort]
    v = v.sort_values(by, ascending=asc)

    out = pd.DataFrame({
        "Артикул": v["article"], "Товар": v["name"], "Статус": v["status"],
        "Прибыль, ₽": v["profit"], f"Прибыль {per}, ₽": v["u_profit"], f"Маржа {to}, %": v["u_margin"] * 100,
        # orders of the period and what became of them
        "Заказано, шт": v["ordered_qty"], "Доставлено, шт": v["delivered_qty"], "Отменено, шт": v["cancelled_qty"],
        "В пути, шт": v["transit_qty"], "% выкупа заказов": v["buyout_pct"],
        # sales of the period
        "Продано, шт": v["sold"], "Возвраты, шт": v["returned"], "Выкуп нетто, шт": v["net_qty"],
        "Сделки, шт": v["sold"] + v["cancelled_qty"],
        "Заказано, ₽": v["ordered_sum"], "Выручка, ₽": v["revenue"],
        "Комиссия, ₽": v["commission"] - v["acquiring"], "Эквайринг, ₽": v["acquiring"],
        "Логистика, ₽": v["logistics"],
        "Хранение и прочее, ₽": v["storage"] + v["penalties"] + v["services"] + v["other"],
        "Реклама, ₽": v["ads"], f"ДРР {to}, %": v["u_drr"] * 100,
        "Себестоимость, ₽": v["cogs"], "Налоги, ₽": v["vat"] + v["tax"],
        **{f"{t} {per}, ₽": v[f"u_{k}"] for k, t in UNIT_LINES.items() if k != "profit"},
        "SKU": v["sku"], "Кабинет": v["cabinet"], "МП": v["marketplace"].map(MP_NAMES),
    })
    out = hide_cogs_columns(out)
    csv = status_line(issues) + "\n\n" + out.to_csv(index=False, sep=";")
    # the grid draws empty numbers as «None»: columns that can be empty become text with «—»
    blank = [c for c in out.columns if out[c].dtype.kind == "f" and out[c].isna().any()]
    for c in blank:
        out[c] = out[c].map(lambda x, p="%" in c: "—" if pd.isna(x) else
                            (f"{x:.1f}".replace(".", ",") if p else f"{x:,.0f}".replace(",", " ")))
    money = [c for c in out.columns if "₽" in c and c not in blank]
    perc = [c for c in out.columns if "%" in c and c not in blank]
    qty = [c for c in out.columns if c.endswith(", шт")]
    view = (out.style
            .format(precision=0, thousands=" ", subset=money + qty)
            .format(precision=1, decimal=",", subset=perc))
    st.dataframe(view, use_container_width=True, hide_index=True, height=600, column_config={
        "Артикул": st.column_config.TextColumn(pinned=True),
        "Товар": st.column_config.TextColumn(pinned=True, width="medium"),
        **{c: st.column_config.TextColumn(alignment="right") for c in blank},
    })
    st.caption(
        f"Товаров: {len(out)}. «—» — показатель не применяется: нет продаж (не на что делить), "
        f"нет заказов или только возвраты. От выбора выше зависят колонки «{per}» и «{to}». "
        "«% выкупа заказов» — доставлено / (доставлено + отменено) среди заказов периода; заказы в пути "
        "не учитываются. «только возвраты» — продаж нет, вернули проданное раньше: выручка и комиссия "
        "сторнируются, себестоимость возвращается. Эквайринг Ozon берёт при оплате заказа, комиссию — при продаже. "
        "«нет в каталоге» — карточка не найдена в кабинете, название подтянется при следующей загрузке.")

    _reconciliation(g)
    st.download_button("Скачать CSV", csv.encode("utf-8-sig"),
                       file_name=f"товары_{base.lower()}_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.csv",
                       mime="text/csv")


def _reconciliation(g: pd.DataFrame):
    st.subheader("Сверка с итогом кабинета")
    r = reconcile(g)
    for _, row in r.iterrows():
        ok = abs(row["diff"]) < 1
        st.markdown(f"**{row['cabinet']}**: товары {rub(row['profit_items'])} + общие расходы "
                    f"{rub(row['profit_common'])} = {rub(row['total'])} — прибыль до постоянных "
                    + ("✅ сходится" if ok else f"⚠️ расхождение {rub(row['diff'])}"))
    common = g[g["sku"] == NO_SKU]
    if common.empty:
        return
    parts = common[COMMON_LINES].sum()
    parts = parts[parts.abs() >= 1].sort_values()
    st.caption("Общие расходы не делятся по товарам и не входят в прибыль товаров: " +
               ", ".join(f"{LINE_TITLES[k].lower()} {rub(a)}" for k, a in parts.items()) +
               ". Реклама здесь — «оплата за заказ: все товары» и прочие кампании без товара.")
