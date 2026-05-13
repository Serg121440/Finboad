"""Streamlit dashboard — Finboard marketplace financial analytics."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta

from database.db import init_db
from analytics.metrics import (
    load_data, load_cogs, load_ad_spend,
    gross_revenue, net_revenue, total_net_profit, total_ad_spend,
    total_cogs, real_profit, drr,
    margin_by_sku, revenue_by_day, marketplace_comparison,
    cost_structure, abc_analysis, top_skus_by_profit,
    get_all_categories, get_date_range,
)
from config import WB_API_TOKEN, OZON_CLIENT_ID, OZON_API_KEY

st.set_page_config(
    page_title="Finboard — Маркетплейс Аналитика",
    page_icon="📊",
    layout="wide",
)

init_db()

MP_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "other": "Прочие"}
MP_COLORS = {"wb": "#CB11AB", "ozon": "#005BFF", "other": "#999999"}


def rub(v: float) -> str:
    """Format rubles: whole number with thousands separator."""
    return f"{int(round(v)):,}".replace(",", " ") + " ₽"

def pct(v: float) -> str:
    """Format percentage: 1 decimal."""
    return f"{v:.1f}%"

def qty(v) -> str:
    """Format quantity: whole number with thousands separator."""
    return f"{int(round(v)):,}".replace(",", " ") + " шт."

def num(v: float) -> str:
    """Format number: whole with thousands separator."""
    return f"{int(round(v)):,}".replace(",", " ")


# ── SIDEBAR ───────────────────────────────────────────────────────────────────

st.sidebar.title("Finboard")

# 1. WB Отчёт о реализации
with st.sidebar.expander("📥 Отчёт WB (реализация)", expanded=True):
    st.caption("ЛК WB → Аналитика → Финансы → Отчёт о реализации → Скачать xlsx")
    wb_files = st.file_uploader(
        "Выбери .xlsx файлы (можно несколько)",
        type=["xlsx"], accept_multiple_files=True, key="wb_sales",
    )
    if wb_files and st.button("Загрузить отчёт", key="btn_wb_sales"):
        from connectors.wb_excel_parser import parse_wb_excel
        from database.db import upsert_records, log_sync
        total = 0
        for f in wb_files:
            try:
                with st.spinner(f"Обрабатываю {f.name}…"):
                    records, stats = parse_wb_excel(f)
                    upsert_records(records)
                    total += len(records)
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['total_rows'])} строк → {num(len(records))} записей | {num(stats['skus'])} SKU  \n"
                    f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                    f"Выручка: **{rub(stats['revenue'])}** | К перечислению: **{rub(stats['net_profit'])}**  \n"
                    f"Комиссия: {rub(stats['commission'])} | Эквайринг: {rub(stats['acquiring'])} | "
                    f"Логистика: {rub(stats['logistics'])}"
                )
            except Exception as e:
                st.error(f"{f.name}: {e}")
        if total:
            log_sync("wb", "ok", total)
            st.rerun()

# 2. WB Реклама
with st.sidebar.expander("📥 Реклама WB (история затрат)", expanded=False):
    st.caption("ЛК WB → Реклама → История затрат → Скачать xlsx")
    ads_files = st.file_uploader(
        "Выбери .xlsx файлы рекламных расходов",
        type=["xlsx"], accept_multiple_files=True, key="wb_ads",
    )
    ads_method = st.radio(
        "Метод распределения по SKU",
        ["Пропорционально выручке", "Без привязки к SKU"],
        key="ads_method",
    )
    if ads_files and st.button("Загрузить рекламу", key="btn_wb_ads"):
        from connectors.wb_ads_parser import parse_wb_ads_excel, distribute_ad_spend_by_revenue
        from database.db import insert_ad_spend
        total = 0
        for f in ads_files:
            try:
                with st.spinner(f"Обрабатываю {f.name}…"):
                    records, stats = parse_wb_ads_excel(f)
                    if ads_method == "Пропорционально выручке":
                        all_data_tmp = load_data()
                        records = distribute_ad_spend_by_revenue(records, all_data_tmp)
                    n = insert_ad_spend(records)
                    total += n
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['campaigns'])} кампаний | {num(stats['total_rows'])} строк  \n"
                    f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                    f"Расходы: **{rub(stats['total_spend'])}**"
                )
            except Exception as e:
                st.error(f"{f.name}: {e}")
        if total:
            st.rerun()

# 3. Себестоимость
with st.sidebar.expander("📥 Себестоимость (COGS)", expanded=False):
    from connectors.cogs_parser import generate_cogs_template, parse_cogs_excel
    from database.db import upsert_cogs

    try:
        with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
            existing = pd.read_sql_query(
                __import__("sqlalchemy", fromlist=["text"]).text(
                    "SELECT sku, product_name, cost_per_unit FROM cost_of_goods"
                ), conn,
            ).to_dict("records")
    except Exception:
        existing = []

    tmpl_bytes = generate_cogs_template(existing or None)
    st.download_button(
        "⬇ Скачать шаблон Excel",
        data=tmpl_bytes,
        file_name="cogs_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_cogs",
    )
    st.caption("Заполни себестоимость по каждому SKU и загрузи обратно")

    cogs_file = st.file_uploader("Загрузить заполненный шаблон", type=["xlsx"], key="cogs_upload")
    if cogs_file and st.button("Сохранить себестоимость", key="btn_cogs"):
        try:
            records, n = parse_cogs_excel(cogs_file)
            upsert_cogs(records)
            st.success(f"Сохранено {n} записей себестоимости")
            st.rerun()
        except Exception as e:
            st.error(str(e))

# 4. API синхронизация
with st.sidebar.expander("🔄 API синхронизация", expanded=False):
    missing_tokens = []
    if not WB_API_TOKEN:
        missing_tokens.append("WB_API_TOKEN")
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        missing_tokens.append("OZON_CLIENT_ID / OZON_API_KEY")

    if missing_tokens:
        st.warning(f"Не заданы токены: {', '.join(missing_tokens)}")
    else:
        days_back = st.number_input("Глубина (дней)", min_value=7, max_value=365, value=90)
        if st.button("Синхронизировать WB/Ozon"):
            from normalizer import full_sync
            with st.spinner("Синхронизация…"):
                results = full_sync(days_back=int(days_back))
            st.success(f"WB: {results['wb']} зап. | Ozon: {results['ozon']} зап.")
            st.rerun()

# 5. Очистка данных
with st.sidebar.expander("🗑 Управление данными", expanded=False):
    src_options = ["Все данные", "Только демо-данные (source=demo)", "Только Excel (source=excel)",
                   "Только API (source=api)", "Только Google Sheets (source=gsheets)",
                   "Только рекламные расходы (ad_spend)"]
    clear_target = st.selectbox("Что удалить", src_options, key="clear_target")

    if st.button("🗑 Очистить", key="btn_clear", type="secondary"):
        st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("Подтвердить удаление?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ Да, удалить", key="btn_yes"):
                try:
                    from sqlalchemy import text as sqlt
                    with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
                        if clear_target == "Все данные":
                            conn.execute(sqlt("DELETE FROM sales"))
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                            conn.execute(sqlt("DELETE FROM sync_log"))
                        elif "demo" in clear_target:
                            conn.execute(sqlt("DELETE FROM sales WHERE source = 'demo'"))
                        elif "excel" in clear_target:
                            conn.execute(sqlt("DELETE FROM sales WHERE source IN ('excel', 'excel_distributed')"))
                            conn.execute(sqlt("DELETE FROM ad_spend WHERE source IN ('excel', 'excel_distributed')"))
                        elif "api" in clear_target:
                            conn.execute(sqlt("DELETE FROM sales WHERE source = 'api'"))
                        elif "gsheets" in clear_target:
                            conn.execute(sqlt("DELETE FROM sales WHERE source = 'gsheets'"))
                        elif "ad_spend" in clear_target:
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                            conn.execute(sqlt("UPDATE sales SET ad_spend = 0.0"))
                        conn.commit()
                    st.session_state["confirm_clear"] = False
                    st.success("Данные удалены")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with col_no:
            if st.button("❌ Отмена", key="btn_no"):
                st.session_state["confirm_clear"] = False
                st.rerun()

# ── LOAD DATA ─────────────────────────────────────────────────────────────────

all_data = load_data()

if all_data.empty:
    st.title("📊 Finboard — Финансовая аналитика маркетплейсов")
    st.info(
        "База данных пуста. Загрузи **Отчёт о реализации WB** через боковую панель.\n\n"
        "ЛК WB → Аналитика → Финансы → Отчёт о реализации → Скачать xlsx"
    )
    st.stop()

# ── FILTERS ───────────────────────────────────────────────────────────────────

st.sidebar.divider()
st.sidebar.subheader("Фильтры")

min_date, max_date = get_date_range(all_data)
default_from = max(min_date, max_date - timedelta(days=30))

date_from = st.sidebar.date_input("С даты", value=default_from, min_value=min_date, max_value=max_date)
date_to   = st.sidebar.date_input("По дату", value=max_date, min_value=min_date, max_value=max_date)

avail_mp = sorted(all_data["marketplace"].unique())
mp_sel = st.sidebar.multiselect("Маркетплейс", ["Все"] + [MP_LABELS.get(m, m) for m in avail_mp], default=["Все"])
mp_filter = None if "Все" in mp_sel or not mp_sel else [
    {v: k for k, v in MP_LABELS.items()}.get(m, m) for m in mp_sel
]

cats = get_all_categories(all_data)
if cats:
    cat_sel = st.sidebar.multiselect("Категория", ["Все"] + cats, default=["Все"])
    cat_filter = None if "Все" in cat_sel or not cat_sel else cat_sel
else:
    cat_filter = None

df = load_data(date_from=date_from, date_to=date_to, marketplaces=mp_filter, categories=cat_filter)
cogs_map = load_cogs()
has_cogs = bool(cogs_map)

# ── HEADER ────────────────────────────────────────────────────────────────────

st.title("📊 Finboard — Финансовая аналитика маркетплейсов")
st.caption(
    f"Период: {date_from} — {date_to} | "
    f"Записей: {num(len(df))} | "
    f"Себестоимость: {'✅ загружена' if has_cogs else '❌ не задана'}"
)

if df.empty:
    st.warning("Нет данных для выбранных фильтров.")
    st.stop()

# ── KPI ROW ───────────────────────────────────────────────────────────────────

gross   = gross_revenue(df)
net     = net_revenue(df)
profit  = total_net_profit(df)
ads     = total_ad_spend(df)
cogs    = total_cogs(df, cogs_map)
r_profit = real_profit(df, cogs_map)
costs   = cost_structure(df)
margin  = profit / net * 100 if net > 0 else 0
r_margin = r_profit / net * 100 if net > 0 else 0
total_qty = int(df["quantity"].sum())
total_returns = int(df["return_quantity"].sum())

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Выручка (брутто)", rub(gross))
col2.metric("Выручка (нетто)", rub(net))
col3.metric("К перечислению WB", rub(profit), delta=pct(margin))
col4.metric(
    "Продано / Возвращено",
    f"{num(total_qty)} шт.",
    delta=f"возвраты: {num(total_returns)} шт.",
    delta_color="inverse" if total_returns > 0 else "off",
    help="Общее количество проданных единиц товара за период",
)
col5.metric(
    "Реклама (ДРР)",
    rub(ads) if ads > 0 else "не загружена",
    delta=pct(drr(df)) if ads > 0 else None,
    delta_color="inverse",
)
if has_cogs:
    col6.metric("Реальная прибыль", rub(r_profit), delta=pct(r_margin))
else:
    col6.metric("Себестоимость", "не задана", delta="загрузи COGS", delta_color="off")

st.divider()

# ── COST BREAKDOWN ROW ────────────────────────────────────────────────────────

st.subheader("Структура затрат")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Комиссия WB",     rub(costs["commission"]),     pct(costs.get("commission_pct", 0)),     delta_color="off")
c2.metric("НДС на комиссию", rub(costs["vat_commission"]), pct(costs.get("vat_commission_pct", 0)), delta_color="off")
c3.metric("Эквайринг",       rub(costs["acquiring"]),      pct(costs.get("acquiring_pct", 0)),      delta_color="off")
c4.metric("Логистика",       rub(costs["logistics"]),      pct(costs.get("logistics_pct", 0)),      delta_color="off")
c5.metric("Возвраты",        rub(costs["returns"]),        pct(costs.get("returns_pct", 0)),        delta_color="off")
c6.metric("Штрафы + скидки",
          rub(costs["penalties"] + costs["cofinancing"]),
          pct(costs.get("penalties_pct", 0) + costs.get("cofinancing_pct", 0)),
          delta_color="off")

st.divider()

# ── PIE + DYNAMICS ─────────────────────────────────────────────────────────────

col_pie, col_dyn = st.columns([1, 2])

with col_pie:
    pie_labels = ["Комиссия WB", "НДС", "Эквайринг", "Логистика",
                  "Возвраты", "Штрафы/Скидки", "Реклама", "К перечислению"]
    pie_values = [
        max(costs["commission"], 0),
        max(costs["vat_commission"], 0),
        max(costs["acquiring"], 0),
        max(costs["logistics"], 0),
        max(costs["returns"], 0),
        max(costs["penalties"] + costs["cofinancing"], 0),
        max(costs["ad_spend"], 0),
        max(costs["net_profit"], 0),
    ]
    if sum(pie_values) > 0:
        fig_pie = px.pie(
            names=pie_labels, values=pie_values,
            title="Распределение выручки",
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_pie.update_traces(textinfo="percent+label", textfont_size=11)
        fig_pie.update_layout(showlegend=False, height=380)
        st.plotly_chart(fig_pie, width="stretch")

with col_dyn:
    st.markdown("**Динамика выручки и прибыли по дням**")
    daily = revenue_by_day(df)
    if not daily.empty:
        fig_daily = go.Figure()
        for mp in daily["marketplace"].unique():
            sub = daily[daily["marketplace"] == mp]
            label = MP_LABELS.get(mp, mp)
            color = MP_COLORS.get(mp)
            fig_daily.add_trace(go.Scatter(
                x=sub["day"], y=sub["revenue"].round(0),
                name=f"Выручка {label}", mode="lines+markers",
                line=dict(color=color, width=2),
            ))
            fig_daily.add_trace(go.Scatter(
                x=sub["day"], y=sub["net_profit"].round(0),
                name=f"К перечислению {label}", mode="lines",
                line=dict(color=color, dash="dot", width=1.5),
            ))
        fig_daily.update_layout(
            xaxis_title="Дата", yaxis_title="₽",
            yaxis=dict(tickformat=",.0f"),
            legend=dict(orientation="h", y=-0.25),
            hovermode="x unified", height=380,
            margin=dict(t=10),
        )
        st.plotly_chart(fig_daily, width="stretch")

st.divider()

# ── GROUPING BY CATEGORY ──────────────────────────────────────────────────────

st.subheader("Анализ по категориям")

if not cats:
    st.info("Категории не определены — они берутся из поля «Предмет» в отчёте WB.")
else:
    cat_df = df.groupby("category").agg(
        revenue=("revenue", "sum"),
        returns=("returns", "sum"),
        commission=("commission", "sum"),
        logistics=("logistics", "sum"),
        net_profit=("net_profit", "sum"),
        quantity=("quantity", "sum"),
        return_quantity=("return_quantity", "sum"),
        skus=("sku", "nunique"),
    ).reset_index()
    cat_df["net_revenue"] = cat_df["revenue"] - cat_df["returns"]
    cat_df["margin_pct"] = (
        cat_df["net_profit"] / cat_df["net_revenue"] * 100
    ).where(cat_df["net_revenue"] > 0, 0).round(1)
    cat_df["return_rate_pct"] = (
        cat_df["return_quantity"] / cat_df["quantity"] * 100
    ).where(cat_df["quantity"] > 0, 0).round(1)
    cat_df = cat_df.sort_values("net_profit", ascending=False)

    col_cat1, col_cat2 = st.columns(2)
    with col_cat1:
        fig_cat_rev = px.bar(
            cat_df, x="net_profit", y="category", orientation="h",
            color="margin_pct",
            color_continuous_scale="RdYlGn",
            labels={"net_profit": "К перечислению, ₽", "category": "Категория", "margin_pct": "Маржа, %"},
            title="К перечислению по категориям",
            text=cat_df["net_profit"].apply(lambda v: rub(v)),
        )
        fig_cat_rev.update_layout(yaxis=dict(autorange="reversed"), height=400)
        fig_cat_rev.update_traces(textposition="outside")
        st.plotly_chart(fig_cat_rev, width="stretch")

    with col_cat2:
        fig_cat_mg = px.bar(
            cat_df, x="margin_pct", y="category", orientation="h",
            color="margin_pct",
            color_continuous_scale="RdYlGn",
            labels={"margin_pct": "Маржа, %", "category": "Категория"},
            title="Маржинальность по категориям",
            text=cat_df["margin_pct"].apply(lambda v: pct(v)),
        )
        fig_cat_mg.update_layout(yaxis=dict(autorange="reversed"), height=400)
        fig_cat_mg.update_traces(textposition="outside")
        st.plotly_chart(fig_cat_mg, width="stretch")

    st.dataframe(
        cat_df.rename(columns={
            "category": "Категория",
            "revenue": "Выручка, ₽",
            "returns": "Возвраты, ₽",
            "commission": "Комиссия, ₽",
            "logistics": "Логистика, ₽",
            "net_profit": "К перечислению, ₽",
            "quantity": "Продано, шт.",
            "return_quantity": "Возвращено, шт.",
            "skus": "SKU",
            "net_revenue": "Нетто-выручка, ₽",
            "margin_pct": "Маржа, %",
            "return_rate_pct": "Возвраты, %",
        }).style.format({
            "Выручка, ₽": lambda v: num(v),
            "Возвраты, ₽": lambda v: num(v),
            "Комиссия, ₽": lambda v: num(v),
            "Логистика, ₽": lambda v: num(v),
            "К перечислению, ₽": lambda v: num(v),
            "Нетто-выручка, ₽": lambda v: num(v),
            "Продано, шт.": lambda v: num(v),
            "Возвращено, шт.": lambda v: num(v),
            "Маржа, %": lambda v: f"{v:.1f}%",
            "Возвраты, %": lambda v: f"{v:.1f}%",
        }),
        width="stretch", hide_index=True,
    )

st.divider()

# ── MARKETPLACE COMPARISON ────────────────────────────────────────────────────

st.subheader("Сравнение маркетплейсов")
mp_comp = marketplace_comparison(df)
if not mp_comp.empty:
    col_a, col_b = st.columns(2)
    with col_a:
        fig_mp = px.bar(
            mp_comp, x="marketplace", y=["revenue", "net_profit"],
            barmode="group",
            labels={"value": "₽", "marketplace": "Маркетплейс", "variable": ""},
            color_discrete_map={"revenue": "#4CAF50", "net_profit": "#2196F3"},
            title="Выручка и к перечислению",
        )
        fig_mp.update_xaxes(tickvals=mp_comp["marketplace"], ticktext=[MP_LABELS.get(m, m) for m in mp_comp["marketplace"]])
        fig_mp.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig_mp, width="stretch")
    with col_b:
        fig_mg = px.bar(
            mp_comp, x="marketplace", y="margin_pct",
            color="marketplace", color_discrete_map=MP_COLORS,
            labels={"margin_pct": "Маржа, %", "marketplace": ""},
            title="Маржинальность (нетто-выручка)",
        )
        fig_mg.update_xaxes(tickvals=mp_comp["marketplace"], ticktext=[MP_LABELS.get(m, m) for m in mp_comp["marketplace"]])
        fig_mg.update_yaxes(ticksuffix="%", tickformat=".1f")
        st.plotly_chart(fig_mg, width="stretch")

    st.dataframe(
        mp_comp.assign(marketplace=mp_comp["marketplace"].map(lambda m: MP_LABELS.get(m, m)))
        .rename(columns={
            "marketplace": "Маркетплейс", "revenue": "Выручка, ₽", "returns": "Возвраты, ₽",
            "commission": "Комиссия WB, ₽", "vat_commission": "НДС, ₽", "acquiring": "Эквайринг, ₽",
            "logistics": "Логистика, ₽", "penalties": "Штрафы, ₽", "ad_spend": "Реклама, ₽",
            "net_profit": "К перечислению, ₽", "net_revenue": "Нетто-выручка, ₽",
            "margin_pct": "Маржа, %", "quantity": "Продано, шт.",
        }).style.format({
            "Выручка, ₽": lambda v: num(v),
            "Возвраты, ₽": lambda v: num(v),
            "Комиссия WB, ₽": lambda v: num(v),
            "НДС, ₽": lambda v: num(v),
            "Эквайринг, ₽": lambda v: num(v),
            "Логистика, ₽": lambda v: num(v),
            "Штрафы, ₽": lambda v: num(v),
            "Реклама, ₽": lambda v: num(v),
            "К перечислению, ₽": lambda v: num(v),
            "Нетто-выручка, ₽": lambda v: num(v),
            "Продано, шт.": lambda v: num(v),
            "Маржа, %": lambda v: f"{v:.1f}%",
        }),
        width="stretch", hide_index=True,
    )

st.divider()

# ── TOP-20 SKU ────────────────────────────────────────────────────────────────

st.subheader("Топ-20 SKU по прибыли")
top = top_skus_by_profit(df, cogs_map, n=20)
if not top.empty:
    profit_col = "real_profit" if has_cogs else "net_profit"
    profit_label = "Реальная прибыль" if has_cogs else "К перечислению"
    display_name = top.apply(lambda r: r["product_name"] if r["product_name"] else r["sku"], axis=1)

    fig_top = px.bar(
        top.assign(label=display_name),
        x=profit_col, y="label", orientation="h",
        color="marketplace", color_discrete_map=MP_COLORS,
        labels={profit_col: f"{profit_label}, ₽", "label": "Товар"},
        title=f"Топ-20 SKU ({profit_label})",
    )
    fig_top.update_layout(yaxis=dict(autorange="reversed"), height=600)
    fig_top.update_xaxes(tickformat=",.0f")
    st.plotly_chart(fig_top, width="stretch")

    show_cols = ["sku", "product_name", "category", "marketplace",
                 "revenue", "net_profit", "margin_pct", "real_margin_pct",
                 "return_rate_pct", "commission_pct", "drr_pct",
                 "logistics_per_unit", "quantity", "return_quantity"]
    show_cols = [c for c in show_cols if c in top.columns]
    fmt_map = {
        "Выручка, ₽": lambda v: num(v),
        "К перечислению, ₽": lambda v: num(v),
        "Маржа WB, %": lambda v: f"{v:.1f}%",
        "Реальная маржа, %": lambda v: f"{v:.1f}%",
        "Возвраты, %": lambda v: f"{v:.1f}%",
        "Комиссия, %": lambda v: f"{v:.1f}%",
        "ДРР, %": lambda v: f"{v:.1f}%",
        "Лог./ед, ₽": lambda v: num(v),
        "Продано, шт.": lambda v: num(v),
        "Возвращено, шт.": lambda v: num(v),
    }
    st.dataframe(
        top[show_cols].rename(columns={
            "sku": "Артикул", "product_name": "Наименование", "category": "Категория",
            "marketplace": "МП", "revenue": "Выручка, ₽",
            "net_profit": "К перечислению, ₽", "margin_pct": "Маржа WB, %",
            "real_margin_pct": "Реальная маржа, %",
            "return_rate_pct": "Возвраты, %", "commission_pct": "Комиссия, %",
            "drr_pct": "ДРР, %", "logistics_per_unit": "Лог./ед, ₽",
            "quantity": "Продано, шт.", "return_quantity": "Возвращено, шт.",
        }).style.format(fmt_map),
        width="stretch", hide_index=True,
    )

st.divider()

# ── ABC ANALYSIS ──────────────────────────────────────────────────────────────

st.subheader("ABC-анализ по прибыли")
col_abc1, col_abc2 = st.columns([1, 2])

abc = abc_analysis(df, cogs_map)
with col_abc1:
    if not abc.empty:
        abc_sum = abc.groupby("abc_class").agg(count=("sku", "count"), profit=("net_profit", "sum")).reset_index()
        fig_abc = px.bar(
            abc_sum, x="abc_class", y="profit",
            color="abc_class",
            color_discrete_map={"A": "#4CAF50", "B": "#FF9800", "C": "#F44336"},
            labels={"abc_class": "Класс", "profit": "Прибыль, ₽"},
            text="count",
        )
        fig_abc.update_traces(texttemplate="%{text} SKU", textposition="outside")
        fig_abc.update_layout(showlegend=False, height=320)
        fig_abc.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig_abc, width="stretch")

with col_abc2:
    if not abc.empty:
        st.dataframe(
            abc[["abc_class", "sku", "product_name", "net_profit", "cumulative_pct"]].rename(columns={
                "abc_class": "Класс", "sku": "Артикул",
                "product_name": "Наименование", "net_profit": "Прибыль, ₽",
                "cumulative_pct": "Нарастающий итог, %",
            }).style.format({
                "Прибыль, ₽": lambda v: num(v),
                "Нарастающий итог, %": lambda v: f"{v:.1f}%",
            }),
            width="stretch", hide_index=True, height=320,
        )

# ── SIDEBAR SYNC LOG ──────────────────────────────────────────────────────────

with st.sidebar:
    st.divider()
    st.caption("История загрузок:")
    try:
        from sqlalchemy import text as sqlt
        with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
            logs = pd.read_sql_query(
                sqlt("SELECT marketplace, sync_at, status, records_count FROM sync_log ORDER BY sync_at DESC LIMIT 8"),
                conn,
            )
        for _, row in logs.iterrows():
            icon = "✅" if row["status"] == "ok" else "❌"
            mp = MP_LABELS.get(row["marketplace"], row["marketplace"])
            st.caption(f"{icon} {mp}: {str(row['sync_at'])[:16]} ({num(row['records_count'])} зап.)")
    except Exception:
        pass
