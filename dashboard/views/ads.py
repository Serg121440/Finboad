"""Реклама: три главных числа, динамика рядом с тем, что требует внимания, таблица товаров с
выборками и разбором товара, диагностика (тепловые карты) и кабинеты во вкладках."""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, Filters, ads_daily_for, data_version, pct, picked_now, result_for, rub, period_filters, summarize,
    with_names,
)
from dashboard.quality import quality_block, status_line
from dashboard.theme import card
from dashboard.views.products import cabinet_tag, drr_limit
from dashboard.views.products_overview import previous_period
from dashboard.views.report_charts import (
    DRR_NAMES, MIN_VIEWS, _pct, ads_daily_chart, ads_donut, ads_kpis, ads_product_map, ctr_heatmap, ctr_vs_drr,
    drr_heatmap, traffic_html,
)
from dashboard.xlsx import MIME, to_xlsx
from pnl.engine import NO_SKU

# table selections: the signals on the right open them
PICKS = ["Все товары", "Выше цели", "Расход без заказов", "Плохой CTR и дорого"]
NAME_LEN = 46


def short_name(name: str, n: int = NAME_LEN) -> str:
    """Product name cut to the model and variant: the start of it, on a word boundary."""
    name = " ".join(str(name).split())
    if len(name) <= n:
        return name
    cut = name[:n].rsplit(" ", 1)[0].rstrip(",.;:-–")
    return cut + "…"


def product_rows(named: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Products with ad money: spend tied to the product, both ДРР, orders, CTR and profit.
    named: summarize by (cabinet_id, sku) with names; daily: ads_daily of the period."""
    g = named[(named["sku"] != NO_SKU) & (named["ads"] != 0)].copy()
    cols = ["ordered_sum", "views", "clicks"]
    if daily.empty:                         # accruals without ad statistics or orders
        g = g.assign(**{c: 0.0 for c in cols})
    else:
        stats = daily[daily["sku"] != NO_SKU].groupby(["cabinet_id", "sku"])[cols].sum()
        g = g.merge(stats, left_on=["cabinet_id", "sku"], right_index=True, how="left")
    g[cols] = g[cols].fillna(0)
    g["spend"] = -g["ads"]
    g["drr"] = np.where(g["revenue"] > 0, g["spend"] / g["revenue"].where(g["revenue"] > 0) * 100, np.nan)
    g["drr_orders"] = np.where(g["ordered_sum"] > 0, g["spend"] / g["ordered_sum"].where(g["ordered_sum"] > 0) * 100,
                               np.nan)
    g["ctr"] = np.where(g["views"] >= MIN_VIEWS, g["clicks"] / g["views"].where(g["views"] > 0) * 100, np.nan)
    return g.sort_values("spend", ascending=False).reset_index(drop=True)


def picks(g: pd.DataFrame, limit: float) -> dict[str, pd.Series]:
    """Masks of the table selections."""
    views, clicks = g["views"].sum(), g["clicks"].sum()
    avg = clicks / views * 100 if views > 0 else np.nan
    return {
        "Все товары": pd.Series(True, index=g.index),
        "Выше цели": g["drr_orders"] > limit,
        "Расход без заказов": (g["ordered_sum"] <= 0) & (g["spend"] > 0),
        "Плохой CTR и дорого": (g["ctr"] < avg) & (g["drr_orders"] > limit) if pd.notna(avg)
        else pd.Series(False, index=g.index),
    }


def signals(g: pd.DataFrame, limit: float, issues: list) -> list[dict]:
    """What the right column shows: each selection that is not empty, with its money, and open data gaps."""
    m = picks(g, limit)
    out = []
    texts = {
        "Выше цели": f"{DRR_NAMES['drr_orders']} выше {_pct(limit, 0)} %",
        "Расход без заказов": "реклама идёт, заказов за период нет",
        "Плохой CTR и дорого": f"CTR ниже среднего и {DRR_NAMES['drr_orders']} выше {_pct(limit, 0)} %",
    }
    for key, text in texts.items():
        n = int(m[key].sum())
        if n:
            out.append({"pick": key, "title": f"{key}: {n} {_word(n)}",
                        "text": f"{text} · расход {rub(g.loc[m[key], 'spend'].sum())}"})
    for i in issues:
        if i.blocking:
            out.append({"pick": "", "title": i.text.split(" — ")[0], "text": i.where and f"→ {i.where}"})
    return out


def _word(n: int) -> str:
    return "товар" if n % 10 == 1 and n % 100 != 11 else \
        "товара" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "товаров"


def _signals_block(items: list[dict]):
    st.markdown("**Требует внимания**")
    if not items:
        st.caption("Товаров выше цели и без заказов нет, данные за период полные.")
    for n, it in enumerate(items):
        st.html(f'<div class="fb-signal"><b>{it["title"]}</b><span>{it["text"]}</span></div>')
        if it["pick"] and st.button("Показать", key=f"ads_sig_{n}", icon=":material/filter_list:", type="tertiary"):
            st.session_state["ads_pick"] = it["pick"]
            st.session_state["ads_scroll"] = True


@st.dialog("Товар", width="large")
def _product_dialog(row: dict, daily: pd.DataFrame, limit: float):
    st.markdown(f"**{row['name'] or row['sku']}**")
    st.caption(f"{row['cabinet']} · артикул {row['article'] or '—'} · SKU {row['sku']}")
    c = st.columns(4)
    c[0].metric("Расход", rub(row["spend"]))
    c[1].metric(DRR_NAMES["drr_orders"], f"{_pct(row['drr_orders'])} %" if pd.notna(row["drr_orders"]) else "нет заказов")
    c[2].metric(DRR_NAMES["drr"], f"{_pct(row['drr'])} %" if pd.notna(row["drr"]) else "—")
    c[3].metric("CTR", f"{_pct(row['ctr'], 2)} %" if pd.notna(row["ctr"]) else "мало показов")
    d = daily[(daily["cabinet_id"] == row["cabinet_id"]) & (daily["sku"] == row["sku"])]
    cab = pd.DataFrame({"id": [row["cabinet_id"]], "marketplace": [row["marketplace"]]})
    ads_daily_chart(d, cab, limit)
    st.caption(f"Прибыль за период {rub(row['profit'])}, до рекламы {rub(row['profit'] + row['spend'])}. "
               "Период и кабинеты — как на странице.")


@st.fragment
def _table(g: pd.DataFrame, limit: float, daily: pd.DataFrame):
    """A fragment: a click on a row or another selection reruns only the table, not the whole page."""
    m = picks(g, limit)
    counts = {k: int(v.sum()) for k, v in m.items()}
    options = [k for k in PICKS if k == "Все товары" or counts[k]]
    if st.session_state.get("ads_pick") not in options:
        st.session_state["ads_pick"] = "Все товары"
    pick = st.segmented_control("Выборка", options, key="ads_pick", label_visibility="collapsed",
                                format_func=lambda k: f"{k} · {counts[k]}") or "Все товары"
    v = g[m[pick]].reset_index(drop=True)
    out = _frame(v)
    # «localized»: the viewer's own digit grouping and decimal comma
    money = st.column_config.NumberColumn(format="localized")
    out = out.round({c: 1 for c in out.columns if "ДРР" in c} | {"CTR, %": 2} | {c: 0 for c in out.columns if "₽" in c})
    ev = st.dataframe(out.assign(Товар=out["Товар"].map(short_name)), hide_index=True, use_container_width=True,
                      height=min(36 * len(out) + 40, 520),
                      on_select="rerun", selection_mode="single-row", key=f"ads_tbl_{pick}",
                      column_config={
                          "Товар": st.column_config.TextColumn(pinned=True, width="large"),
                          "Артикул": st.column_config.TextColumn(pinned=True, width=120),
                          "Кабинет": st.column_config.TextColumn(pinned=True, width=170),
                          "Расход, ₽": money, "Заказы, ₽": money, "Прибыль, ₽": money,
                          **{c: money for c in out.columns if "ДРР" in c}, "CTR, %": money,
                      })
    st.caption("Расход здесь — реклама, отнесённая к конкретному товару. Общая реклама в таблицу не входит. "
               "Нажмите на строку — откроется разбор товара по дням.")
    rows = ev.selection.rows if ev and ev.selection else []
    if picked_now("ads", (pick, rows[0]) if rows else None):
        _product_dialog(v.iloc[rows[0]].to_dict(), daily, limit)


def _frame(v: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Товар": v["name"].map(short_name), "Артикул": v["article"], "Кабинет": cabinet_tag(v),
        "Расход, ₽": v["spend"],
        DRR_NAMES["drr"] + ", %": v["drr"], DRR_NAMES["drr_orders"] + ", %": v["drr_orders"],
        "Заказы, ₽": v["ordered_sum"], "CTR, %": v["ctr"], "Прибыль, ₽": v["profit"],
    })


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
    issues = quality_block(f, res, key="q_ads", scopes=("data", "ads"))
    facts = res.facts
    p0, p1, label = previous_period(f.date_from, f.date_to)
    prev = result_for(Filters(p0, p1, f.cabinet_ids, f.cabinets))
    ids = tuple(sorted(f.cabinet_ids))
    daily = ads_daily_for(f.date_from, f.date_to, ids, data_version())
    prev_daily = ads_daily_for(p0, p1, ids, data_version())
    named = with_names(summarize(facts, ["cabinet_id", "sku"]), f.cabinets, res.products)
    limit = drr_limit()
    ads_kpis(res, prev, label, daily)
    st.html(traffic_html(res, daily, prev_daily, label))
    g = product_rows(named, daily)
    left, right = st.columns([2, 1])
    with card(left):
        ads_daily_chart(daily, f.cabinets, limit)
    with card(right):
        _signals_block(signals(g, limit, issues))
    st.markdown("#### Товары")
    _table(g, limit, daily)
    names = named[["cabinet_id", "sku", "name", "article", "marketplace"]]
    t_diag, t_cab = st.tabs(["Диагностика", "По кабинетам"])
    with t_diag:
        with card():
            drr_heatmap(daily, names, limit)
        if daily["views"].sum() > 0:
            with card():
                ctr_heatmap(daily, names)
        a, b = st.columns([3, 2])
        with card(a):
            if not ctr_vs_drr(daily, names, limit):
                ads_product_map(named, limit)
        with card(b):
            ads_donut(facts, f.cabinets)
    with t_cab:
        cab_x = _cabinets(facts, f)
    header = [f"Реклама {f.date_from:%d.%m.%Y} — {f.date_to:%d.%m.%Y}", status_line(issues)]
    st.download_button("Скачать Excel", to_xlsx([("По кабинетам", pd.DataFrame(cab_x)), ("По товарам", _frame(g))],
                                                header),
                       mime=MIME, file_name=f"реклама_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.xlsx")


def _cabinets(facts: pd.DataFrame, f) -> list[dict]:
    """Spend per cabinet: tied to products and common (not split by product), with its share."""
    by_cab = summarize(facts, ["cabinet_id"])
    common = facts[facts["sku"] == NO_SKU].groupby("cabinet_id")["ads"].sum()
    total = -facts["ads"].sum()
    rows, cab_x = [], []
    for _, r in by_cab.iterrows():
        c = f.cabinets[f.cabinets["id"] == r["cabinet_id"]].iloc[0]
        ads = -r["ads"]
        com = -common.get(r["cabinet_id"], 0.0)
        name = f"{MP_NAMES[c['marketplace']]} · {c['name']}"
        rows.append({"Кабинет": name, "Расход": rub(ads), "по товарам": rub(ads - com),
                     "общая реклама": rub(com), "доля общей в бюджете": pct(com / total) if total else "—",
                     DRR_NAMES["drr"]: pct(r["drr"])})
        cab_x.append({"Кабинет": name, "Расход, ₽": ads, "по товарам, ₽": ads - com, "общая реклама, ₽": com,
                      "Выручка, ₽": r["revenue"], DRR_NAMES["drr"] + ", %": r["drr"] * 100})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Ozon: сумма — из отчёта по начислениям. Клики раскладываются по товарам по статистике кампаний, "
               "«оплата за заказ: выбранные товары» — по отчёту о заказах. «Оплата за заказ — все товары» по "
               "товарам не делится и остаётся общей рекламой. WB: расход из кабинета продвижения.")
    return cab_x
