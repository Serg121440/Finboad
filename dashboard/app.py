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
from dashboard.theme import (
    inject_css, brand_block, theme_toggle_sidebar, apply_plotly_theme,
    MP_LABELS, MP_COLORS, PLOTLY_PALETTE, WB_ACCENT, OZON_ACCENT, SUCCESS, DANGER, INFO,
)

st.set_page_config(
    page_title="Finboard — Маркетплейс Аналитика",
    page_icon="📊",
    layout="wide",
)

init_db()
inject_css()


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

with st.sidebar:
    brand_block()
theme_toggle_sidebar()

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
                log_sync(
                    "wb", "ok", len(records),
                    filename=f.name,
                    date_from=stats.get("date_from"),
                    date_to=stats.get("date_to"),
                    revenue=stats.get("revenue", 0),
                )
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['total_rows'])} строк → {num(len(records))} записей | {num(stats['skus'])} SKU  \n"
                    f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                    f"Выручка: **{rub(stats['revenue'])}** | К перечислению: **{rub(stats['net_profit'])}**  \n"
                    f"Комиссия: {rub(stats['commission'])} | Эквайринг: {rub(stats['acquiring'])}  \n"
                    f"Логистика (дост.): {rub(stats['logistics'])} | "
                    f"Хранение+Приёмка: {rub(stats.get('storage', 0))} | "
                    f"Удержания: {rub(stats.get('uderzhaniya', 0))}"
                )
            except Exception as e:
                log_sync("wb", "error", error=str(e), filename=f.name)
                st.error(f"{f.name}: {e}")
        if total:
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
        from database.db import insert_ad_spend, log_sync as _log_sync
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
                _log_sync(
                    "wb_ads", "ok", n,
                    filename=f.name,
                    date_from=stats.get("date_from"),
                    date_to=stats.get("date_to"),
                    revenue=stats.get("total_spend", 0),
                )
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['campaigns'])} кампаний | {num(stats['total_rows'])} строк  \n"
                    f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                    f"Расходы: **{rub(stats['total_spend'])}**"
                )
            except Exception as e:
                _log_sync("wb_ads", "error", error=str(e), filename=f.name)
                st.error(f"{f.name}: {e}")
        if total:
            st.rerun()

# 3. Ozon — Начисления
with st.sidebar.expander("📥 Отчёт Ozon (начисления)", expanded=False):
    st.caption("ЛК Ozon → Финансы → Начисления → Скачать xlsx (широкий формат, 25 колонок)")
    ozon_files = st.file_uploader(
        "Выбери .xlsx файлы (можно несколько)",
        type=["xlsx"], accept_multiple_files=True, key="ozon_sales",
    )
    if ozon_files and st.button("Загрузить отчёт Ozon", key="btn_ozon_sales"):
        from connectors.ozon_excel_parser import parse_ozon_excel
        from database.db import upsert_records, log_sync as _log
        total = 0
        for f in ozon_files:
            try:
                with st.spinner(f"Обрабатываю {f.name}…"):
                    records, stats = parse_ozon_excel(f)
                    upsert_records(records)
                    total += len(records)
                _log(
                    "ozon", "ok", len(records),
                    filename=f.name,
                    date_from=stats.get("date_from"),
                    date_to=stats.get("date_to"),
                    revenue=stats.get("revenue", 0),
                )
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['total_rows'])} строк → {num(len(records))} записей | {num(stats['skus'])} SKU  \n"
                    f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                    f"Выручка: **{rub(stats['revenue'])}** | К перечислению: **{rub(stats['net_profit'])}**  \n"
                    f"Комиссия: {rub(stats['commission'])} | Эквайринг: {rub(stats['acquiring'])}  \n"
                    f"Логистика: {rub(stats['logistics'])} | Хранение+Возвраты: {rub(stats['storage'])} | "
                    f"Удержания: {rub(stats.get('uderzhaniya', 0))}"
                )
            except Exception as e:
                _log("ozon", "error", error=str(e), filename=f.name)
                st.error(f"{f.name}: {e}")
        if total:
            st.rerun()

# 4. Ozon — Реклама
with st.sidebar.expander("📥 Реклама Ozon (статистика)", expanded=False):
    st.caption("ЛК Ozon → Продвижение → Статистика → Скачать xlsx")
    ozon_ads_files = st.file_uploader(
        "Выбери .xlsx файлы",
        type=["xlsx"], accept_multiple_files=True, key="ozon_ads",
    )
    ozon_ads_date = st.date_input(
        "Дата начала периода отчёта",
        value=date.today().replace(day=1),
        key="ozon_ads_date",
    )
    if ozon_ads_files and st.button("Загрузить рекламу Ozon", key="btn_ozon_ads"):
        from connectors.ozon_ads_parser import parse_ozon_ads_excel
        from database.db import insert_ad_spend, log_sync as _log2
        total = 0
        for f in ozon_ads_files:
            try:
                with st.spinner(f"Обрабатываю {f.name}…"):
                    records, stats = parse_ozon_ads_excel(f, ozon_ads_date)
                    n = insert_ad_spend(records)
                    total += n
                _log2(
                    "ozon_ads", "ok", n,
                    filename=f.name,
                    date_from=stats.get("date_from"),
                    date_to=stats.get("date_to"),
                    revenue=stats.get("total_spend", 0),
                )
                st.success(
                    f"**{f.name}**  \n"
                    f"{num(stats['campaigns'])} кампаний | {num(stats['skus'])} SKU  \n"
                    f"Расходы: **{rub(stats['total_spend'])}**"
                )
            except Exception as e:
                _log2("ozon_ads", "error", error=str(e), filename=f.name)
                st.error(f"{f.name}: {e}")
        if total:
            st.rerun()

# 5. Себестоимость
with st.sidebar.expander("📥 Себестоимость (COGS)", expanded=False):
    from connectors.cogs_parser import generate_cogs_template, parse_cogs_excel
    from database.db import upsert_cogs

    try:
        from sqlalchemy import text as _sqlt
        with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
            existing = pd.read_sql_query(
                _sqlt("SELECT sku, product_name, cost_per_unit FROM cost_of_goods"), conn,
            ).to_dict("records")
            if not existing:
                # Pre-populate template: prefer Артикул поставщика, fallback to WB numeric SKU
                sales_skus = pd.read_sql_query(
                    _sqlt("SELECT DISTINCT sku, article, product_name FROM sales ORDER BY product_name"),
                    conn,
                ).to_dict("records")
                existing = [
                    {
                        "sku": r["article"] if r.get("article") else r["sku"],
                        "product_name": r["product_name"],
                        "cost_per_unit": 0,
                    }
                    for r in sales_skus
                ]
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

# 7. API синхронизация
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
    src_options = [
        "Отчёт WB (продажи)",        # только sales, реклама и себест. не затронуты
        "Рекламные расходы",          # только ad_spend
        "Себестоимость (COGS)",       # только cost_of_goods
        "Все продажи и реклама",      # sales + ad_spend
    ]
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
                        if clear_target == "Все продажи и реклама":
                            conn.execute(sqlt("DELETE FROM sales"))
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                        elif clear_target == "Рекламные расходы":
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                            conn.execute(sqlt("UPDATE sales SET ad_spend = 0.0"))
                        elif clear_target == "Себестоимость (COGS)":
                            conn.execute(sqlt("DELETE FROM cost_of_goods"))
                        elif clear_target == "Отчёт WB (продажи)":
                            # Удаляем только продажи; реклама и себестоимость остаются
                            conn.execute(sqlt("DELETE FROM sales"))
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
    f"Себестоимость: {'✅ загружена (' + str(len(cogs_map)) + ' SKU)' if has_cogs else '❌ не задана'} | "
    f"v2026.05.17"
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

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
col1.metric("Выручка (брутто)", rub(gross))
col2.metric("Выручка (нетто)", rub(net))
col3.metric("К перечислению МП", rub(profit), delta=pct(margin))
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
col6.metric(
    "Себестоимость",
    rub(cogs) if has_cogs else "не задана",
    delta="загрузи COGS" if not has_cogs else None,
    delta_color="off",
)
if has_cogs:
    col7.metric("Реальная прибыль", rub(r_profit), delta=pct(r_margin))
else:
    col7.metric("Реальная прибыль", "—", delta_color="off")

st.divider()

# ── COST BREAKDOWN ROW ────────────────────────────────────────────────────────

st.subheader("Структура затрат")
c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
c1.metric("Комиссия МП",       rub(costs["commission"]),     pct(costs.get("commission_pct", 0)),     delta_color="off")
c2.metric("НДС на комиссию",   rub(costs["vat_commission"]), pct(costs.get("vat_commission_pct", 0)), delta_color="off")
c3.metric("Эквайринг",         rub(costs["acquiring"]),      pct(costs.get("acquiring_pct", 0)),      delta_color="off")
c4.metric("Логистика",         rub(costs["logistics"]),      pct(costs.get("logistics_pct", 0)),      delta_color="off",
          help="Услуги по доставке товара покупателю (совпадает с WB «Логистика»)")
c5.metric("Хранение + ПВЗ",    rub(costs["storage"]),        pct(costs.get("storage_pct", 0)),        delta_color="off",
          help="Хранение + Приёмка + ПВЗ + Возмещение издержек")
c6.metric("Возвраты",          rub(costs["returns"]),        pct(costs.get("returns_pct", 0)),        delta_color="off")
c7.metric("Штрафы",            rub(costs["penalties"]),      pct(costs.get("penalties_pct", 0)),      delta_color="off")
c8.metric("Удержания МП",      rub(costs["uderzhaniya"]),    pct(costs.get("uderzhaniya_pct", 0)),    delta_color="off")

st.divider()

# ── PIE + DYNAMICS ─────────────────────────────────────────────────────────────

col_pie, col_dyn = st.columns([1, 2])

with col_pie:
    pie_labels = ["Комиссия МП", "НДС", "Эквайринг", "Логистика",
                  "Хранение+ПВЗ", "Возвраты", "Штрафы",
                  "Удержания МП", "Реклама", "К перечислению"]
    pie_values = [
        max(costs["commission"], 0),
        max(costs["vat_commission"], 0),
        max(costs["acquiring"], 0),
        max(costs["logistics"], 0),
        max(costs["storage"], 0),
        max(costs["returns"], 0),
        max(costs["penalties"] + costs["cofinancing"], 0),
        max(costs["uderzhaniya"], 0),
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
        st.plotly_chart(apply_plotly_theme(fig_pie), width="stretch")

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
        st.plotly_chart(apply_plotly_theme(fig_daily), width="stretch")

st.divider()

# ── GROUPING BY CATEGORY ──────────────────────────────────────────────────────

st.subheader("Анализ по категориям")

if df.empty:
    st.info("Нет данных для анализа.")
else:
    # Pre-compute per-row COGS so we can sum it by category
    df_cat = df.copy()
    # Fill empty category with marketplace name so Ozon items aren't lumped into ""
    df_cat["category"] = df_cat.apply(
        lambda r: r["category"] if str(r.get("category") or "").strip()
        else MP_LABELS.get(str(r.get("marketplace", "")), str(r.get("marketplace", "Прочее"))),
        axis=1,
    )
    if has_cogs:
        df_cat["_cogs_row"] = df_cat.apply(
            lambda r: cogs_map.get(str(r["sku"]), 0.0) * int(r.get("quantity", 0)), axis=1
        )
    else:
        df_cat["_cogs_row"] = 0.0

    cat_df = df_cat.groupby("category").agg(
        revenue=("revenue", "sum"),
        returns=("returns", "sum"),
        commission=("commission", "sum"),
        logistics=("logistics", "sum"),
        net_profit=("net_profit", "sum"),
        quantity=("quantity", "sum"),
        return_quantity=("return_quantity", "sum"),
        skus=("sku", "nunique"),
        cogs_total=("_cogs_row", "sum"),
    ).reset_index()
    cat_df["net_revenue"] = cat_df["revenue"] - cat_df["returns"]
    cat_df["real_profit"] = cat_df["net_profit"] - cat_df["cogs_total"]
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
        st.plotly_chart(apply_plotly_theme(fig_cat_rev), width="stretch")

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
        st.plotly_chart(apply_plotly_theme(fig_cat_mg), width="stretch")

    cat_show = cat_df.copy()
    rename_map = {
        "category": "Категория",
        "revenue": "Выручка, ₽",
        "returns": "Возвраты, ₽",
        "commission": "Комиссия, ₽",
        "logistics": "Логистика, ₽",
        "net_profit": "К перечислению, ₽",
        "quantity": "Продано, шт.",
        "return_quantity": "Возвращено, шт.",
        "skus": "Товаров, шт.",
        "net_revenue": "Нетто-выручка, ₽",
        "margin_pct": "Маржа, %",
        "return_rate_pct": "Возвраты, %",
    }
    fmt_map = {
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
    }
    if has_cogs:
        rename_map["cogs_total"] = "Себестоимость, ₽"
        rename_map["real_profit"] = "Реальная прибыль, ₽"
        fmt_map["Себестоимость, ₽"] = lambda v: num(v)
        fmt_map["Реальная прибыль, ₽"] = lambda v: num(v)
    else:
        cat_show = cat_show.drop(columns=["cogs_total", "real_profit"])

    st.dataframe(
        cat_show.rename(columns=rename_map).style.format(fmt_map),
        width="stretch", hide_index=True,
    )

st.divider()

# ── MARKETPLACE COMPARISON ────────────────────────────────────────────────────

st.subheader("Сравнение маркетплейсов")
mp_comp = marketplace_comparison(df)
if not mp_comp.empty:
    col_a, col_b = st.columns(2)
    with col_a:
        _mp_bar = mp_comp.rename(columns={"revenue": "Выручка", "net_profit": "К перечислению"})
        fig_mp = px.bar(
            _mp_bar, x="marketplace", y=["Выручка", "К перечислению"],
            barmode="group",
            labels={"value": "₽", "marketplace": "Маркетплейс", "variable": ""},
            color_discrete_map={"Выручка": "#4CAF50", "К перечислению": "#2196F3"},
            title="Выручка и к перечислению",
        )
        fig_mp.update_xaxes(tickvals=_mp_bar["marketplace"], ticktext=[MP_LABELS.get(m, m) for m in _mp_bar["marketplace"]])
        fig_mp.update_yaxes(tickformat=",.0f")
        st.plotly_chart(apply_plotly_theme(fig_mp), width="stretch")
    with col_b:
        fig_mg = px.bar(
            mp_comp, x="marketplace", y="margin_pct",
            color="marketplace", color_discrete_map=MP_COLORS,
            labels={"margin_pct": "Маржа, %", "marketplace": ""},
            title="Маржинальность (нетто-выручка)",
        )
        fig_mg.update_xaxes(tickvals=mp_comp["marketplace"], ticktext=[MP_LABELS.get(m, m) for m in mp_comp["marketplace"]])
        fig_mg.update_yaxes(ticksuffix="%", tickformat=".1f")
        st.plotly_chart(apply_plotly_theme(fig_mg), width="stretch")

    _mp_display_cols = [
        "marketplace", "revenue", "returns", "commission", "vat_commission", "acquiring",
        "logistics", "storage", "penalties", "uderzhaniya", "ad_spend",
        "net_profit", "net_revenue", "margin_pct", "quantity",
    ]
    st.dataframe(
        mp_comp[[c for c in _mp_display_cols if c in mp_comp.columns]]
        .assign(marketplace=mp_comp["marketplace"].map(lambda m: MP_LABELS.get(m, m)))
        .rename(columns={
            "marketplace": "Маркетплейс", "revenue": "Выручка, ₽", "returns": "Возвраты, ₽",
            "commission": "Комиссия МП, ₽", "vat_commission": "НДС, ₽", "acquiring": "Эквайринг, ₽",
            "logistics": "Логистика (дост.), ₽", "storage": "Хранение+Приёмка, ₽",
            "penalties": "Штрафы, ₽", "uderzhaniya": "Удержания, ₽",
            "ad_spend": "Реклама, ₽",
            "net_profit": "К перечислению, ₽", "net_revenue": "Нетто-выручка, ₽",
            "margin_pct": "Маржа, %", "quantity": "Продано, шт.",
        }).style.format({
            "Выручка, ₽": lambda v: num(v),
            "Возвраты, ₽": lambda v: num(v),
            "Комиссия WB, ₽": lambda v: num(v),
            "НДС, ₽": lambda v: num(v),
            "Эквайринг, ₽": lambda v: num(v),
            "Логистика (дост.), ₽": lambda v: num(v),
            "Хранение+Приёмка, ₽": lambda v: num(v),
            "Штрафы, ₽": lambda v: num(v),
            "Удержания, ₽": lambda v: num(v),
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
    st.plotly_chart(apply_plotly_theme(fig_top), width="stretch")

    show_cols = ["sku", "product_name", "category", "marketplace",
                 "revenue", "net_profit", "margin_pct", "real_margin_pct",
                 "return_rate_pct", "commission_pct", "drr_pct",
                 "logistics_per_unit", "quantity", "return_quantity"]
    show_cols = [c for c in show_cols if c in top.columns]
    fmt_map = {
        "Выручка, ₽": lambda v: num(v),
        "К перечислению, ₽": lambda v: num(v),
        "Маржа МП, %": lambda v: f"{v:.1f}%",
        "Реальная маржа, %": lambda v: f"{v:.1f}%",
        "Возвраты, %": lambda v: f"{v:.1f}%",
        "Комиссия, %": lambda v: f"{v:.1f}%",
        "ДРР, %": lambda v: f"{v:.1f}%",
        "Лог./ед, ₽": lambda v: num(v),
        "Продано, шт.": lambda v: num(v),
        "Возвращено, шт.": lambda v: num(v),
    }
    top_display = top[show_cols].copy()
    top_display["category"] = top_display.apply(
        lambda r: r["category"] if str(r.get("category") or "").strip()
        else MP_LABELS.get(str(r.get("marketplace", "")), ""),
        axis=1,
    )
    top_display["marketplace"] = top_display["marketplace"].map(lambda m: MP_LABELS.get(m, m))
    st.dataframe(
        top_display.rename(columns={
            "sku": "Артикул", "product_name": "Наименование", "category": "Категория",
            "marketplace": "МП", "revenue": "Выручка, ₽",
            "net_profit": "К перечислению, ₽", "margin_pct": "Маржа МП, %",
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
        st.plotly_chart(apply_plotly_theme(fig_abc), width="stretch")

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
    with st.expander("📋 История загрузок", expanded=False):
        try:
            from sqlalchemy import text as sqlt
            from database.db import delete_sync_log
            with __import__("database.db", fromlist=["engine"]).engine.connect() as conn:
                logs = pd.read_sql_query(
                    sqlt("SELECT id, marketplace, sync_at, status, records_count, "
                         "filename, date_from, date_to, revenue FROM sync_log "
                         "ORDER BY sync_at DESC LIMIT 30"),
                    conn,
                )
            if logs.empty:
                st.caption("Загрузок пока нет")
            else:
                MP_ICON = {"wb": "🟣", "wb_ads": "📢", "ozon": "🔵", "ozon_ads": "📣", "other": "⚪"}
                for _, row in logs.iterrows():
                    status_icon = "✅" if row["status"] == "ok" else "❌"
                    mp_icon = MP_ICON.get(str(row["marketplace"]), "⚪")
                    fname = str(row.get("filename") or "").strip()
                    d_from = str(row.get("date_from") or "")[:10]
                    d_to   = str(row.get("date_to")   or "")[:10]
                    rev    = row.get("revenue") or 0
                    dt     = str(row["sync_at"])[:16]
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        period = f"{d_from} — {d_to}" if d_from else dt
                        label = fname if fname else MP_LABELS.get(str(row["marketplace"]), str(row["marketplace"]))
                        st.caption(
                            f"{status_icon} {mp_icon} **{label}**  \n"
                            f"{period}  \n"
                            f"{num(row['records_count'])} зап." +
                            (f" | {rub(rev)}" if rev else "")
                        )
                    with col2:
                        if st.button("🗑", key=f"del_log_{row['id']}", help="Удалить запись из истории"):
                            delete_sync_log(int(row["id"]))
                            st.rerun()
        except Exception:
            pass
