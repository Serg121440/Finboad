"""Товары: юнит-экономика по каждому товару.

Суммы — факт по начислениям (по дате продажи), заказы — по дате заказа. Это
разные штуки (в октябре выкупают и сентябрьские заказы), поэтому деньги не
делятся на заказы напрямую: на один заказ = на одну продажу × доля выкупа
заказов (по исходам заказов периода; пока статусов нет — доля без отмен).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import (
    MP_NAMES, Filters, daily_totals_for, data_version, hide_cogs_columns, result_for, period_filters, rub,
    summarize, with_names,
)
from dashboard.quality import attention_issues, quality_block, status_line
from dashboard.views.products_overview import NO_SALES, overview, previous_period
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
COMMON_LINES = ["ads", "logistics", "storage", "penalties", "services", "other", "commission", "vat", "tax"]
FILTER_KEYS = ("prod_query", "prod_quick", "prod_mp")
HIGH_DRR = 10.0          # % of revenue: default «высокий ДРР», changed on the page
QUICK = ["Все", "Убыточные", "Высокий ДРР", "Нет себестоимости", "Без продаж"]
NAME_LEN = 48            # longer names are cut in the table; the card shows the full one


SHARE_COLS = {"Комиссия с эквайрингом": ["commission"], "Логистика": ["logistics"],
              "Хранение и прочее": ["storage", "penalties", "services", "other"]}


def revenue_share(g: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Cost lines as % of revenue; no positive revenue — no share."""
    return -g[cols].sum(axis=1) / g["revenue"].where(g["revenue"] > 0) * 100


def buyout_rate(g: pd.DataFrame) -> pd.Series:
    """Share of the period's orders that were bought out, among orders with a known outcome
    (all in transit — unknown yet). Without statuses (WB, old loads) — share of orders not cancelled."""
    resolved = g["delivered_qty"] + g["cancelled_qty"]
    known = g["delivered_qty"] / resolved.replace(0, np.nan)
    fallback = (g["ordered_qty"] - g["cancelled_qty"]) / g["ordered_qty"].replace(0, np.nan)
    return known.where(g["unknown_qty"] == 0, fallback)


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


def _weights(primary: pd.Series, secondary: pd.Series) -> pd.Series | None:
    for s in (primary, secondary):
        s = s.clip(lower=0)
        if s.sum() > 0:
            return s / s.sum()
    return None


def allocate_common(g: pd.DataFrame) -> pd.DataFrame:
    """Spread the cabinet's expenses without a product over its products.

    Ad money without a product (Ozon «оплата за заказ — все товары»: a % of the order
    price, never broken down by SKU) goes by share of ordered sum; everything else
    (logistics, storage, services without a product) by share of revenue. Adds
    ads_common and other_common (included in ads and profit); the common row stays
    only when there is nothing to spread it over."""
    g = g.copy()
    g["ads_common"] = 0.0
    g["other_common"] = 0.0
    drop = []
    for _, part in g.groupby("cabinet_id"):
        com = part[part["sku"] == NO_SKU]
        items = part[part["sku"] != NO_SKU]
        if com.empty or items.empty:
            continue
        wa = _weights(items["ordered_sum"], items["revenue"])
        wo = _weights(items["revenue"], items["ordered_sum"])
        if wa is None or wo is None:
            continue
        ads = com["ads"].sum()
        g.loc[items.index, "ads_common"] = ads * wa
        g.loc[items.index, "other_common"] = (com["profit"].sum() - ads) * wo
        drop += list(com.index)
    g["ads"] = g["ads"] + g["ads_common"]
    g["profit"] = g["profit"] + g["ads_common"] + g["other_common"]
    return g.drop(index=drop)


def _reset_filters():
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


def drr_limit() -> float:
    return float(st.session_state.get("prod_drr_limit", HIGH_DRR))


def product_table(f, res) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Products of the period with orders, names and the cabinet's common expenses spread over them.
    Returns (before spreading — for the reconciliation, after)."""
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
    before = g
    g = allocate_common(g)
    g["status"] = status_of(g)
    g["buyout_pct"] = buyout_rate(g) * 100
    g["drr_rev"] = -g["ads"] / g["revenue"].where(g["revenue"] > 0) * 100
    return before, g


def quick_mask(g: pd.DataFrame, quick: str, limit: float) -> pd.Series:
    """Rows of a quick selection. «Высокий ДРР» — ads above limit % of revenue (common ads included)."""
    item = g["sku"] != NO_SKU
    if quick == "Убыточные":
        return item & (g["profit"] < 0) & ~g["status"].isin(["нет продаж", "только возвраты"])
    if quick == "Высокий ДРР":
        return item & (g["drr_rev"] > limit)
    if quick == "Нет себестоимости":
        return item & (g["cost_missing_qty"] != 0)
    if quick == "Без продаж":
        return g["status"].isin(["нет продаж", "только возвраты"])
    return pd.Series(True, index=g.index)


def attention_counts(g: pd.DataFrame, limit: float) -> dict:
    loss = quick_mask(g, "Убыточные", limit)
    return {"loss": int(loss.sum()), "loss_sum": rub(g.loc[loss, "profit"].sum()),
            "high_drr": int(quick_mask(g, "Высокий ДРР", limit).sum())}


def short_name(name: str) -> str:
    return name if len(name) <= NAME_LEN else name[:NAME_LEN - 1].rstrip() + "…"


def unit_columns(per: str, to: str) -> list[str]:
    """Columns that depend on the unit base."""
    return [f"Прибыль {per}, ₽", f"Маржа {to}, %", f"ДРР {to}, %",
            *[f"{t} {per}, ₽" for k, t in UNIT_LINES.items() if k != "profit"]]


def views(per: str, to: str) -> dict[str, list[str] | None]:
    """Column sets of the table (Артикул, Товар are always first and pinned)."""
    return {
        "Прибыль": ["Статус", "Выручка, ₽", "Прибыль, ₽", f"Прибыль {per}, ₽", f"Маржа {to}, %", "Выкуп нетто, шт",
                    "Себестоимость, ₽", "Налоги, ₽", f"ДРР {to}, %"],
        "Реклама": ["Статус", "Заказано, ₽", "Выручка, ₽", "Реклама по товару, ₽", "Реклама «все товары», ₽",
                    f"ДРР {to}, %", f"Реклама {per}, ₽", "Прибыль, ₽", f"Прибыль {per}, ₽"],
        "Расходы": ["Выручка, ₽", "Комиссия, ₽", "Эквайринг, ₽", "Логистика, ₽", "Хранение и прочее, ₽",
                    "Общие расходы МП, ₽", "Себестоимость, ₽", "Налоги, ₽",
                    *[f"{t}, % выручки" for t in SHARE_COLS], "Прибыль, ₽"],
        "Заказы и продажи": ["Заказано, шт", "Доставлено, шт", "Отменено, шт", "В пути, шт", "% выкупа заказов",
                             "Продано, шт", "Возвраты, шт", "Выкуп нетто, шт", "Сделки, шт", "Заказано, ₽",
                             "Выручка, ₽"],
        "Все показатели": None,
    }


def render():
    st.title("Товары")
    f = period_filters()
    if f is None:
        st.info("Кабинетов пока нет.")
        return
    # the unit base is chosen above the table; the card and the cached table key need it before that
    st.session_state.setdefault("prod_base", "Выкупы")
    if st.session_state["prod_base"] not in BASES:
        st.session_state["prod_base"] = "Выкупы"
    base = st.session_state["prod_base"]
    _, per, to, note = BASES[base]
    days = (f.date_to - f.date_from).days + 1
    if days < SHORT_PERIOD_DAYS:
        st.caption(f":material/info: Период {days} дн.: выкупают в основном заказы прошлых недель, а заказы "
                   "периода ещё в пути. Юнит-экономику смотрите за месяц.")
    res = result_for(f)
    if res.facts.empty:
        st.warning("За период нет данных.")
        return
    before, g = product_table(f, res)
    limit = drr_limit()
    issues = quality_block(f, res, [i for i in attention_issues(attention_counts(g, limit), limit)
                                    if "Высокий" in i.text], key="q_prod", compact=True)
    u = unit_economics(g, base)

    p0, p1, label = previous_period(f.date_from, f.date_to)
    pres = result_for(Filters(p0, p1, f.cabinet_ids, f.cabinets))
    prev = None if pres.facts.empty else product_table(Filters(p0, p1, f.cabinet_ids, f.cabinets), pres)[1]
    daily = daily_totals_for(f.date_from, f.date_to, tuple(sorted(f.cabinet_ids)), data_version())
    overview(g, before, prev, label, daily)
    st.subheader("Все товары")

    mps = [m for m in ("ozon", "wb") if (g["marketplace"] == m).any()]
    if st.session_state.get("prod_mp") not in ["Все"] + mps:
        st.session_state.pop("prod_mp", None)    # remembered from a selection with another marketplace
    if st.session_state.get("prod_quick") not in QUICK:
        st.session_state.pop("prod_quick", None)
    c1, c4 = st.columns([3, 1])
    query = c1.text_input("Поиск по артикулу или названию", key="prod_query")
    mp = c4.selectbox("Площадка", ["Все"] + mps, key="prod_mp", format_func=lambda m: MP_NAMES.get(m, m),
                      disabled=len(mps) < 2)
    scope = g if mp == "Все" else g[g["marketplace"] == mp]

    # set before the widgets (a value + key from another page must not clash with a default)
    st.session_state.setdefault("prod_quick", "Все")
    st.session_state.setdefault("prod_view", "Прибыль")
    st.session_state.setdefault("prod_drr_limit", HIGH_DRR)
    q1, q2 = st.columns([4, 1])
    quick = q1.segmented_control("Быстрые выборки", QUICK, key="prod_quick") or "Все"
    q2.number_input("Высокий ДРР — больше, % выручки", min_value=1.0, max_value=100.0, step=1.0,
                    key="prod_drr_limit", disabled=quick != "Высокий ДРР")
    vnames = views(per, to)
    w1, w3, w2 = st.columns([3, 2, 1])
    view_name = w1.segmented_control("Представление", list(vnames), key="prod_view") or "Прибыль"
    unit_cols = [c for c in (vnames[view_name] or unit_columns(per, to)) if c in unit_columns(per, to)]
    w3.segmented_control("Показатели «на единицу»", list(BASES), key="prod_base",
                         format_func=lambda b: "на " + BASES[b][0], disabled=not unit_cols,
                         help="Меняет только столбцы «на 1 …», маржу и ДРР. Суммы в ₽ — факт по начислениям "
                              "за период, от выбора не зависят.")
    sort = w2.selectbox("Сортировка", ["Прибыль ↑", "Прибыль ↓", "Выручка ↓", "ДРР ↓"])
    if unit_cols:
        st.caption(f"База «{BASES[base][0]}» меняет столбцы: " + ", ".join(f"«{c}»" for c in unit_cols)
                   + f". {note}")
    else:
        st.caption("В этом представлении нет показателей «на единицу» — база на него не влияет.")

    v = g.assign(**{f"u_{k}": u[k] for k in u.columns})
    if query:
        ql = query.lower()
        v = v[v["article"].str.lower().str.contains(ql, regex=False) |
              v["name"].str.lower().str.contains(ql, regex=False) | (v["sku"] == query)]
    v = v[quick_mask(v, quick, limit)]
    if mp != "Все":
        v = v[v["marketplace"] == mp]
    if v.empty:
        st.info("Ничего не найдено.")
        st.button("Сбросить фильтры", on_click=_reset_filters)
        return
    by, asc = {"Прибыль ↑": ("profit", True), "Прибыль ↓": ("profit", False),
               "Выручка ↓": ("revenue", False), "ДРР ↓": ("u_drr", False)}[sort]
    # products without sales carry only storage and spread ads: they go last, not on top of «Прибыль ↑»
    v = v.assign(_idle=v["status"].isin(NO_SALES)).sort_values(["_idle", by], ascending=[True, asc]) \
        .drop(columns="_idle").reset_index(drop=True)

    out = pd.DataFrame({
        "Артикул": v["article"], "Товар": v["name"], "Статус": v["status"],
        "Прибыль, ₽": v["profit"], f"Прибыль {per}, ₽": v["u_profit"], f"Маржа {to}, %": v["u_margin"] * 100,
        # costs as a share of the period's revenue (выкупы), whatever the base above
        **{f"{t}, % выручки": revenue_share(v, cols) for t, cols in SHARE_COLS.items()},
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
        "Реклама по товару, ₽": v["ads"] - v["ads_common"], "Реклама «все товары», ₽": v["ads_common"],
        "Общие расходы МП, ₽": v["other_common"], f"ДРР {to}, %": v["u_drr"] * 100,
        "Себестоимость, ₽": v["cogs"], "Налоги, ₽": v["vat"] + v["tax"],
        **{f"{t} {per}, ₽": v[f"u_{k}"] for k, t in UNIT_LINES.items() if k != "profit"},
        "SKU": v["sku"], "Кабинет": v["cabinet"], "МП": v["marketplace"].map(MP_NAMES),
    })
    out = hide_cogs_columns(out)
    csv = status_line(issues) + "\n\n" + out.to_csv(index=False, sep=";")

    cols = vnames[view_name]
    tail = ["МП"] if len(mps) > 1 else []
    shown = out[["Артикул", "Товар"] + [c for c in (cols or list(out.columns[2:])) if c in out.columns
                                         and c not in ("Артикул", "Товар")] + [c for c in tail if cols]]
    shown = shown.assign(Товар=shown["Товар"].map(short_name))
    # the grid draws empty numbers as «None»: columns that can be empty become text with «—»
    blank = [c for c in shown.columns if shown[c].dtype.kind == "f" and shown[c].isna().any()]
    for c in blank:
        shown[c] = shown[c].map(lambda x, p="%" in c: "—" if pd.isna(x) else
                                (f"{x:.1f}".replace(".", ",") if p else f"{x:,.0f}".replace(",", " ")))
    money = [c for c in shown.columns if "₽" in c and c not in blank]
    perc = [c for c in shown.columns if "%" in c and c not in blank]
    qty = [c for c in shown.columns if c.endswith(", шт")]
    styled = (shown.style
              .format(precision=0, thousands=" ", subset=money + qty)
              .format(precision=1, decimal=",", subset=perc)
              .map(lambda x: "color: #EF4444" if isinstance(x, (int, float)) and x < 0 else "",
                   subset=[c for c in ("Прибыль, ₽", f"Прибыль {per}, ₽") if c in money])
              .map(lambda x: {"убыток": "color: #EF4444", "нет себестоимости": "color: #F59E0B"}.get(x, ""),
                   subset=["Статус"] if "Статус" in shown.columns else []))
    # the selection is a row position: a new filter, sort or view must not open another product's card
    sel_key = "prod_table_" + str(abs(hash((query, quick, limit, mp, sort, view_name, base, f.date_from, f.date_to,
                                             tuple(f.cabinet_ids)))))
    event = st.dataframe(styled, use_container_width=True, hide_index=True, key=sel_key,
                         height=min(560, 35 * (len(shown) + 1) + 3),
                         on_select="rerun", selection_mode="single-row", column_config={
                             "Артикул": st.column_config.TextColumn(pinned=True),
                             "Товар": st.column_config.TextColumn(pinned=True, width="medium",
                                                                  help="Полное название — в карточке товара"),
                             **{c: st.column_config.TextColumn(alignment="right") for c in blank},
                         })
    st.caption(f"Товаров: {len(out)}. Нажмите на строку — ниже откроется карточка товара.")
    with st.expander("Как читать таблицу"):
        st.caption(
            f"«—» — показатель не "
            f"применяется: нет продаж (не на что делить), нет заказов или только возвраты. От выбора выше зависят "
            f"колонки «{per}» и «{to}». «% выкупа заказов» — доставлено / (доставлено + отменено) среди заказов "
            "периода; заказы в пути не учитываются. «только возвраты» — продаж нет, вернули проданное раньше: "
            "выручка и комиссия сторнируются, себестоимость возвращается. «Реклама «все товары»» и «Общие расходы "
            "МП» — расходы кабинета без товара, распределённые по товарам (см. ниже); они входят в прибыль и ДРР. "
            "Эквайринг Ozon берёт при оплате заказа, комиссию — при продаже. «нет в каталоге» — карточка не найдена "
            "в кабинете, название подтянется при следующей загрузке.")

    rows = event.selection.rows if event and event.selection else []
    if rows and rows[0] < len(v):
        product_card(v.iloc[rows[0]], f, base)

    _reconciliation(before, g)
    st.download_button("Скачать CSV (все показатели)", csv.encode("utf-8-sig"),
                       file_name=f"товары_{base.lower()}_{f.date_from:%Y%m%d}_{f.date_to:%Y%m%d}.csv",
                       mime="text/csv")


# ── product card ─────────────────────────────────────────────────────────────

def _cell(x, kind: str) -> str:
    if x is None or pd.isna(x):
        return "—"
    if kind == "%":
        return f"{x * 100:.1f} %".replace(".", ",")
    return f"{x:,.0f} ₽".replace(",", " ")


def card_unit_table(row: pd.Series) -> pd.DataFrame:
    """Per-unit money on all three bases side by side."""
    one = pd.DataFrame([row]).reset_index(drop=True).infer_objects()
    cols = {}
    for b, (_, per, to, _) in BASES.items():
        u = unit_economics(one, b).iloc[0]
        cols[per] = [("нет данных" if k == "cogs" and row["cost_missing_qty"] != 0 else _cell(u[k], "₽"))
                     for k in UNIT_LINES] + [_cell(u["margin"], "%"), _cell(u["drr"], "%")]
    labels = list(UNIT_LINES.values()) + ["Маржа", "ДРР"]
    return pd.DataFrame({"Показатель": labels, **cols})


def card_costs(row: pd.Series) -> pd.DataFrame:
    """Where the revenue went: every line of the product's profit, ₽ and % of revenue. Sums to the profit."""
    r = row
    lines = [("Выручка", r["revenue"]), ("Комиссия", r["commission"] - r["acquiring"]),
             ("Эквайринг", r["acquiring"]), ("Логистика", r["logistics"]), ("Хранение и склад", r["storage"]),
             ("Штрафы и удержания", r["penalties"]), ("Подписки и сервисы", r["services"]), ("Прочее", r["other"]),
             ("Реклама по товару", r["ads"] - r["ads_common"]), ("Реклама «все товары»", r["ads_common"]),
             ("Общие расходы МП", r["other_common"]), ("Себестоимость", r["cogs"]), ("НДС", r["vat"]),
             ("Налог", r["tax"]), ("Прибыль", r["profit"])]
    rev = r["revenue"] if r["revenue"] > 0 else np.nan
    df = pd.DataFrame([(t, x, x / rev if pd.notna(rev) else np.nan) for t, x in lines
                       if t in ("Выручка", "Прибыль") or abs(x) >= 0.5], columns=["Статья", "₽", "% выручки"])
    if r["cost_missing_qty"] != 0:
        if (df["Статья"] == "Себестоимость").any():
            df.loc[df["Статья"] == "Себестоимость", "Статья"] = "Себестоимость (не заполнена у части продаж)"
        else:
            df = pd.concat([df.iloc[:-1], pd.DataFrame([("Себестоимость — не заполнена", np.nan, np.nan)],
                                                       columns=df.columns), df.iloc[-1:]], ignore_index=True)
    return df


def incomplete_runs(d0: date, d1: date, loaded: list[tuple[date, date]], complete_to: date) -> list[tuple[date, date]]:
    """Runs of days without full data: not loaded, or after complete_to (no report yet / today)."""
    from dashboard.common import merge_intervals
    have = merge_intervals(loaded)
    runs, start = [], None
    day = d0
    while day <= d1:
        ok = day <= complete_to and any(a <= day <= b for a, b in have)
        if not ok and start is None:
            start = day
        if ok and start is not None:
            runs.append((start, day - timedelta(days=1)))
            start = None
        day += timedelta(days=1)
    if start is not None:
        runs.append((start, d1))
    return runs


def _hide_cogs_rows(df: pd.DataFrame) -> pd.DataFrame:
    acc = st.session_state.get("access")
    if acc and acc.hide_cogs:
        return df[~df.iloc[:, 0].astype(str).str.contains("ебестоим")]
    return df


def product_card(row: pd.Series, f, base: str):
    from dashboard.common import _loaded_intervals, daily_for, data_version
    from dashboard.quality import wb_report_ends
    from dashboard.theme import apply_plotly_theme, DANGER, INFO, SUCCESS, WB_ACCENT
    import plotly.graph_objects as go

    st.divider()
    with st.container(border=True):
        st.subheader(row["name"])
        st.caption(f"Артикул {row['article'] or '—'} · SKU {row['sku']} · {MP_NAMES.get(row['marketplace'], '')} · "
                   f"{row['cabinet']} · статус: {row['status']}")
        k = st.columns(4)
        k[0].metric("Выручка", rub(row["revenue"]), f"продано {row['sold']:.0f}, возвратов {row['returned']:.0f}",
                    delta_color="off", delta_arrow="off")
        margin = row["profit"] / row["revenue"] if row["revenue"] > 0 else np.nan
        k[1].metric("Прибыль", rub(row["profit"]), f"маржа {_cell(margin, '%')}", delta_color="off", delta_arrow="off")
        k[2].metric("Реклама", rub(-row["ads"]),
                    f"ДРР {_cell(row['drr_rev'] / 100 if pd.notna(row['drr_rev']) else np.nan, '%')}",
                    delta_color="off", delta_arrow="off")
        k[3].metric("Заказано", f"{row['ordered_qty']:.0f} шт", f"выкуп {_cell(row['buyout_pct'] / 100, '%')}"
                    if pd.notna(row["buyout_pct"]) else "выкуп —", delta_color="off", delta_arrow="off")

        a, b = st.columns(2)
        with a:
            st.markdown("**Экономика единицы**")
            st.dataframe(_hide_cogs_rows(card_unit_table(row)), hide_index=True, use_container_width=True)
            st.caption(f"Выбранная база — «{BASES[base][0]}». Прибыль — после рекламы, общих расходов МП и налогов.")
        with b:
            st.markdown("**Из чего сложилась прибыль**")
            costs = _hide_cogs_rows(card_costs(row))
            st.dataframe(costs.style.format({"₽": lambda x: _cell(x, "₽"), "% выручки": lambda x: _cell(x, "%")},
                                            na_rep="—")
                         .map(lambda x: "color: #EF4444" if isinstance(x, (int, float)) and x < 0 else "",
                              subset=["₽"]),
                         hide_index=True, use_container_width=True)

        st.markdown("**Заказы, возвраты и невыкупы**")
        o = st.columns(6)
        o[0].metric("Заказано", f"{row['ordered_qty']:.0f}")
        o[1].metric("Доставлено", f"{row['delivered_qty']:.0f}")
        o[2].metric("Отменено", f"{row['cancelled_qty']:.0f}", rub(row["cancelled_sum"]) if row["cancelled_qty"]
                    else None, delta_color="off", delta_arrow="off")
        o[3].metric("В пути", f"{row['transit_qty']:.0f}")
        o[4].metric("Продано", f"{row['sold']:.0f}")
        o[5].metric("Возвраты", f"{row['returned']:.0f}")

        st.markdown("**По дням**")
        d = daily_for(f.date_from, f.date_to, int(row["cabinet_id"]), str(row["sku"]), data_version())
        show_ads = st.toggle("Показать рекламу", value=True, key="card_ads")
        fig = go.Figure()
        fig.add_bar(x=d["date"], y=d["revenue"], name="Выручка", marker_color=INFO, opacity=0.45)
        fig.add_scatter(x=d["date"], y=d["result"], name="Результат до налогов", mode="lines+markers",
                        line=dict(color=SUCCESS, width=2))
        if show_ads:
            fig.add_scatter(x=d["date"], y=-d["ads"], name="Реклама", mode="lines", line=dict(color=WB_ACCENT))
        cab = int(row["cabinet_id"])
        complete = min(f.date_to, date.today() - timedelta(days=1))
        if row["marketplace"] == "wb":
            end = wb_report_ends([cab]).get(cab)
            complete = min(complete, end) if end else f.date_from - timedelta(days=1)
        for n, (a, b) in enumerate(incomplete_runs(f.date_from, f.date_to, _loaded_intervals().get(cab, []), complete)):
            fig.add_vrect(x0=pd.Timestamp(a) - pd.Timedelta(hours=12), x1=pd.Timestamp(b) + pd.Timedelta(hours=12),
                          fillcolor="#F59E0B", opacity=0.12, line_width=0,
                          annotation_text="неполные дни" if n == 0 else None, annotation_position="top left")
        fig.add_hline(y=0, line_color=DANGER, line_width=1, opacity=0.4)
        fig.update_layout(height=320, barmode="overlay", legend=dict(orientation="h", y=1.12), margin=dict(t=30),
                          xaxis=dict(tickformat="%d.%m"), yaxis=dict(tickformat=",.0f"), separators=", ")
        st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config={"displayModeBar": False})
        st.caption("Результат до налогов = выручка − комиссия − логистика − прочие услуги − реклама по товару − "
                   "себестоимость, по дате начисления. Налоги и общие расходы кабинета по дням не делятся, поэтому "
                   "сумма за период выше прибыли в таблице. Жёлтым — дни, за которые отчёта маркетплейса ещё нет.")


def _reconciliation(before: pd.DataFrame, after: pd.DataFrame):
    bad = []
    for cab, part in before.groupby("cabinet"):
        a = after[after["cabinet"] == cab]
        if abs(a["profit"].sum() - part["profit"].sum()) >= 1:
            bad.append(cab)
    title = ("Сверка с итогом кабинета: всё сходится" if not bad else
             f"Сверка с итогом кабинета: расхождение — {', '.join(bad)}")
    with st.expander(title, icon=":material/check_circle:" if not bad else ":material/warning:", expanded=bool(bad)):
        _reconciliation_lines(before, after)


def _reconciliation_lines(before: pd.DataFrame, after: pd.DataFrame):
    for cab, part in before.groupby("cabinet"):
        total = part["profit"].sum()
        a = after[after["cabinet"] == cab]
        kept = a[a["sku"] == NO_SKU]["profit"].sum()  # nothing to spread it over
        items = a[a["sku"] != NO_SKU]["profit"].sum()
        ok = abs(items + kept - total) < 1
        com = part[part["sku"] == NO_SKU]
        parts = com[COMMON_LINES].sum()
        parts = parts[parts.abs() >= 1].sort_values()
        spread = ", ".join(f"{LINE_TITLES[k].lower()} {rub(x)}" for k, x in parts.items())
        rest = f" + не распределено {rub(kept)}" if (a["sku"] == NO_SKU).any() else ""
        st.markdown(f"**{cab}**: сумма прибыли товаров {rub(items)}{rest} = прибыль до постоянных кабинета "
                    f"{rub(total)} " + ("✅ сходится" if ok else f"⚠️ расхождение {rub(items + kept - total)}"))
        if rest:
            st.caption(f"Не распределено: {spread}. У товаров кабинета нет ни выручки, ни заказов за период — "
                       "распределять не на что.")
        elif spread:
            st.caption(f"Распределено по товарам ({rub(com['profit'].sum())}): {spread}. Реклама без товара "
                       "(«оплата за заказ — все товары»: Ozon берёт % от цены заказа и не раскладывает его по "
                       "товарам) — по доле товара в сумме заказов; остальное — по доле в выручке. В ОПиУ и "
                       "финрезультате эти суммы стоят своими статьями.")
