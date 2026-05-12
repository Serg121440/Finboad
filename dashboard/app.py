"""Streamlit dashboard for marketplace financial analysis."""

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
    load_data,
    gross_revenue,
    net_revenue,
    total_net_profit,
    margin_by_sku,
    revenue_by_day,
    marketplace_comparison,
    cost_structure,
    abc_analysis,
    top_skus_by_profit,
    get_all_categories,
    get_date_range,
)

st.set_page_config(
    page_title="Finboard — Маркетплейс Аналитика",
    page_icon="📊",
    layout="wide",
)

init_db()

MARKETPLACE_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "other": "Прочие", "gsheets": "Google Sheets"}
MARKETPLACE_COLORS = {"wb": "#CB11AB", "ozon": "#005BFF", "other": "#999999"}


def fmt_rub(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.title("Фильтры")

with st.sidebar.expander("Загрузить отчёт WB (Excel)", expanded=True):
    st.caption("Скачай в ЛК WB: Аналитика → Отчёт о реализации → Скачать")
    uploaded_files = st.file_uploader(
        "Выбери один или несколько .xlsx файлов",
        type=["xlsx"],
        accept_multiple_files=True,
        key="wb_excel_upload",
    )
    if uploaded_files and st.button("Загрузить в базу", key="btn_upload_wb"):
        from connectors.wb_excel_parser import parse_wb_excel
        from database.db import upsert_records

        total_records = 0
        for f in uploaded_files:
            try:
                with st.spinner(f"Обрабатываю {f.name}..."):
                    records, stats = parse_wb_excel(f)
                    upsert_records(records)
                    total_records += len(records)
                st.success(
                    f"**{f.name}**: {stats['total_rows']} строк → {len(records)} записей "
                    f"| {stats['skus']} SKU | {stats['date_from']} — {stats['date_to']}\n"
                    f"Выручка: {stats['revenue']:,.0f} ₽ | Прибыль: {stats['net_profit']:,.0f} ₽"
                )
            except Exception as e:
                st.error(f"{f.name}: {e}")
        if total_records:
            st.rerun()

with st.sidebar.expander("API синхронизация", expanded=False):
    days_back = st.number_input("Глубина синхронизации (дней)", min_value=7, max_value=365, value=90)
    if st.button("Синхронизировать WB/Ozon API"):
        from normalizer import full_sync

        with st.spinner("Получаем данные из WB и Ozon..."):
            results = full_sync(days_back=int(days_back))
        st.success(
            f"Готово! WB: {results['wb']} зап., Ozon: {results['ozon']} зап., "
            f"Google Sheets: {results['gsheets']} зап."
        )
        st.rerun()

    if st.button("Импорт из Google Sheets"):
        from normalizer import sync_google_sheets

        with st.spinner("Читаем Google Sheets..."):
            n = sync_google_sheets()
        st.success(f"Импортировано {n} записей из Google Sheets")
        st.rerun()

all_data = load_data()

if all_data.empty:
    st.title("📊 Finboard — Финансовая аналитика маркетплейсов")
    st.info(
        "База данных пуста. Загрузи Excel-отчёт WB через боковую панель "
        "(скачать в ЛК WB: Аналитика → Отчёт о реализации)."
    )
    st.sidebar.markdown("---")
    st.sidebar.info("Загрузи Excel-файл для начала работы.")
    st.stop()

min_date, max_date = get_date_range(all_data)
default_from = max(min_date, max_date - timedelta(days=30)) if min_date else date.today() - timedelta(days=30)

date_from = st.sidebar.date_input("С даты", value=default_from, min_value=min_date, max_value=max_date)
date_to = st.sidebar.date_input("По дату", value=max_date, min_value=min_date, max_value=max_date)

marketplaces_available = sorted(all_data["marketplace"].unique().tolist())
marketplace_options = ["Все"] + [MARKETPLACE_LABELS.get(m, m) for m in marketplaces_available]
marketplace_sel = st.sidebar.multiselect("Маркетплейс", marketplace_options, default=["Все"])

if "Все" in marketplace_sel or not marketplace_sel:
    mp_filter = None
else:
    reverse_labels = {v: k for k, v in MARKETPLACE_LABELS.items()}
    mp_filter = [reverse_labels.get(m, m) for m in marketplace_sel]

categories_available = get_all_categories(all_data)
if categories_available:
    cat_sel = st.sidebar.multiselect("Категория товара", ["Все"] + categories_available, default=["Все"])
    cat_filter = None if "Все" in cat_sel or not cat_sel else cat_sel
else:
    cat_filter = None

df = load_data(date_from=date_from, date_to=date_to, marketplaces=mp_filter, categories=cat_filter)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("📊 Finboard — Финансовая аналитика маркетплейсов")
st.caption(f"Период: {date_from} — {date_to} | Записей: {len(df):,}")

if df.empty:
    st.warning("Нет данных для выбранных фильтров.")
    st.stop()

# ── KPI row ──────────────────────────────────────────────────────────────────

gross = gross_revenue(df)
net = net_revenue(df)
profit = total_net_profit(df)
margin = profit / net * 100 if net > 0 else 0
costs = cost_structure(df)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Выручка (брутто)", fmt_rub(gross))
col2.metric("Выручка (нетто)", fmt_rub(net))
col3.metric("Чистая прибыль", fmt_rub(profit))
col4.metric("Маржинальность", fmt_pct(margin))
col5.metric("Доля возвратов", fmt_pct(costs.get("returns_pct", 0)))

st.divider()

# ── Revenue dynamics ─────────────────────────────────────────────────────────

st.subheader("Динамика выручки и прибыли по дням")

daily = revenue_by_day(df)
if not daily.empty:
    fig_daily = go.Figure()
    for mp in daily["marketplace"].unique():
        sub = daily[daily["marketplace"] == mp]
        label = MARKETPLACE_LABELS.get(mp, mp)
        color = MARKETPLACE_COLORS.get(mp, None)
        fig_daily.add_trace(go.Scatter(
            x=sub["day"], y=sub["revenue"],
            name=f"Выручка {label}",
            mode="lines+markers",
            line=dict(color=color, width=2),
        ))
        fig_daily.add_trace(go.Scatter(
            x=sub["day"], y=sub["net_profit"],
            name=f"Прибыль {label}",
            mode="lines",
            line=dict(color=color, dash="dot", width=1.5),
        ))

    fig_daily.update_layout(
        xaxis_title="Дата",
        yaxis_title="Сумма, ₽",
        legend=dict(orientation="h", y=-0.2),
        hovermode="x unified",
        height=400,
    )
    st.plotly_chart(fig_daily, use_container_width=True)

st.divider()

# ── Marketplace comparison ────────────────────────────────────────────────────

st.subheader("Сравнение WB vs Ozon по маржинальности")

mp_comp = marketplace_comparison(df)
if not mp_comp.empty:
    col_a, col_b = st.columns(2)

    with col_a:
        fig_bar = px.bar(
            mp_comp,
            x="marketplace",
            y=["revenue", "net_profit"],
            barmode="group",
            labels={"value": "Сумма, ₽", "marketplace": "Маркетплейс", "variable": "Метрика"},
            color_discrete_map={"revenue": "#4CAF50", "net_profit": "#2196F3"},
            title="Выручка и прибыль",
        )
        fig_bar.update_xaxes(
            tickvals=mp_comp["marketplace"].tolist(),
            ticktext=[MARKETPLACE_LABELS.get(m, m) for m in mp_comp["marketplace"]],
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_b:
        fig_margin = px.bar(
            mp_comp,
            x="marketplace",
            y="margin_pct",
            color="marketplace",
            color_discrete_map=MARKETPLACE_COLORS,
            labels={"margin_pct": "Маржинальность, %", "marketplace": "Маркетплейс"},
            title="Маржинальность по маркетплейсу",
        )
        fig_margin.update_xaxes(
            tickvals=mp_comp["marketplace"].tolist(),
            ticktext=[MARKETPLACE_LABELS.get(m, m) for m in mp_comp["marketplace"]],
        )
        fig_margin.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig_margin, use_container_width=True)

    st.dataframe(
        mp_comp.assign(
            marketplace=mp_comp["marketplace"].map(lambda m: MARKETPLACE_LABELS.get(m, m))
        ).rename(columns={
            "marketplace": "Маркетплейс",
            "revenue": "Выручка",
            "returns": "Возвраты",
            "commission": "Комиссия",
            "logistics": "Логистика",
            "net_profit": "Чистая прибыль",
            "quantity": "Кол-во продаж",
            "net_revenue": "Нетто-выручка",
            "margin_pct": "Маржа, %",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Top-20 SKUs ───────────────────────────────────────────────────────────────

st.subheader("Топ-20 SKU по чистой прибыли")

top = top_skus_by_profit(df, n=20)
if not top.empty:
    display_name = top.apply(
        lambda r: r["product_name"] if r["product_name"] else r["sku"], axis=1
    )

    fig_top = px.bar(
        top.assign(label=display_name),
        x="net_profit",
        y="label",
        orientation="h",
        color="marketplace",
        color_discrete_map=MARKETPLACE_COLORS,
        labels={"net_profit": "Чистая прибыль, ₽", "label": "Товар"},
        title="Топ-20 SKU",
    )
    fig_top.update_layout(yaxis=dict(autorange="reversed"), height=600)
    st.plotly_chart(fig_top, use_container_width=True)

    st.dataframe(
        top[["sku", "product_name", "category", "marketplace", "revenue", "net_profit",
             "margin_pct", "return_rate_pct", "commission_pct", "logistics_per_unit",
             "quantity", "return_quantity"]].rename(columns={
            "sku": "Артикул",
            "product_name": "Наименование",
            "category": "Категория",
            "marketplace": "Маркетплейс",
            "revenue": "Выручка, ₽",
            "net_profit": "Прибыль, ₽",
            "margin_pct": "Маржа, %",
            "return_rate_pct": "Возвраты, %",
            "commission_pct": "Комиссия, %",
            "logistics_per_unit": "Лог./ед., ₽",
            "quantity": "Продано",
            "return_quantity": "Возвращено",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Cost structure ────────────────────────────────────────────────────────────

st.subheader("Структура затрат")

col_pie, col_abc = st.columns(2)

with col_pie:
    labels = ["Комиссия", "Логистика", "Возвраты", "Чистая прибыль"]
    values = [
        max(costs.get("commission", 0), 0),
        max(costs.get("logistics", 0), 0),
        max(costs.get("returns", 0), 0),
        max(costs.get("net_profit", 0), 0),
    ]
    if sum(values) > 0:
        fig_pie = px.pie(
            names=labels,
            values=values,
            title="Распределение выручки",
            color_discrete_sequence=["#FF6B6B", "#4ECDC4", "#FFE66D", "#2196F3"],
        )
        fig_pie.update_traces(textinfo="percent+label")
        st.plotly_chart(fig_pie, use_container_width=True)

with col_abc:
    st.markdown("**ABC-анализ по прибыли**")
    abc = abc_analysis(df)
    if not abc.empty:
        abc_summary = abc.groupby("abc_class").agg(
            count=("sku", "count"),
            profit=("net_profit", "sum"),
        ).reset_index()
        fig_abc = px.bar(
            abc_summary,
            x="abc_class",
            y="profit",
            color="abc_class",
            color_discrete_map={"A": "#4CAF50", "B": "#FF9800", "C": "#F44336"},
            labels={"abc_class": "Класс", "profit": "Суммарная прибыль, ₽"},
            title="ABC по чистой прибыли",
            text="count",
        )
        fig_abc.update_traces(texttemplate="%{text} SKU", textposition="outside")
        st.plotly_chart(fig_abc, use_container_width=True)

st.divider()

# ── ABC table ─────────────────────────────────────────────────────────────────

with st.expander("Детальный ABC-анализ"):
    abc = abc_analysis(df)
    if not abc.empty:
        st.dataframe(
            abc[["abc_class", "sku", "product_name", "net_profit", "cumulative_pct"]].rename(
                columns={
                    "abc_class": "Класс",
                    "sku": "Артикул",
                    "product_name": "Наименование",
                    "net_profit": "Прибыль, ₽",
                    "cumulative_pct": "Нарастающий итог, %",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

# ── Last sync info ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.divider()
    st.caption("Последние синхронизации:")
    try:
        from sqlalchemy import text as sql_text

        with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
            logs = pd.read_sql_query(
                sql_text("SELECT marketplace, sync_at, status, records_count FROM sync_log ORDER BY sync_at DESC LIMIT 10"),
                conn,
            )
        if not logs.empty:
            for _, row in logs.iterrows():
                icon = "✅" if row["status"] == "ok" else "❌"
                mp = MARKETPLACE_LABELS.get(row["marketplace"], row["marketplace"])
                st.caption(f"{icon} {mp}: {row['sync_at'][:16]} ({row['records_count']} зап.)")
    except Exception:
        pass
