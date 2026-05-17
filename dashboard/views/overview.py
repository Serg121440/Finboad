"""Overview page — KPI row, cost breakdown, dynamics chart, distribution pie."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from analytics.metrics import (
    gross_revenue, net_revenue, total_net_profit, total_ad_spend,
    total_cogs, real_profit, drr, revenue_by_day, cost_structure,
)
from dashboard.shared import (
    render_filters_and_load, render_sync_log_sidebar, rub, pct, num,
)
from dashboard.theme import (
    apply_plotly_theme, MP_LABELS, MP_COLORS,
    WB_ACCENT, OZON_ACCENT, SUCCESS, DANGER, INFO,
)


def render():
    ctx = render_filters_and_load()
    render_sync_log_sidebar()

    st.title("Обзор")

    if ctx is None:
        st.info(
            "База данных пуста. Перейди в «Загрузка данных» и загрузи отчёт "
            "о реализации WB или Ozon."
        )
        return

    df = ctx.df
    cogs_map = ctx.cogs_map
    has_cogs = ctx.has_cogs

    st.caption(
        f"Период: {ctx.date_from} — {ctx.date_to} | "
        f"Записей: {num(len(df))} | "
        f"Себестоимость: "
        f"{'✅ загружена (' + str(len(cogs_map)) + ' SKU)' if has_cogs else '❌ не задана'}"
    )

    if df.empty:
        st.warning("Нет данных для выбранных фильтров.")
        return

    # KPI row
    gross = gross_revenue(df)
    net = net_revenue(df)
    profit = total_net_profit(df)
    ads = total_ad_spend(df)
    cogs = total_cogs(df, cogs_map)
    r_profit = real_profit(df, cogs_map)
    costs = cost_structure(df)
    margin = profit / net * 100 if net > 0 else 0
    r_margin = r_profit / net * 100 if net > 0 else 0
    total_qty = int(df["quantity"].sum())
    total_returns = int(df["return_quantity"].sum())

    cols = st.columns(7)
    cols[0].metric("Выручка (брутто)", rub(gross))
    cols[1].metric("Выручка (нетто)", rub(net))
    cols[2].metric("К перечислению МП", rub(profit), delta=pct(margin))
    cols[3].metric(
        "Продано / Возвращено",
        f"{num(total_qty)} шт.",
        delta=f"возвраты: {num(total_returns)} шт.",
        delta_color="inverse" if total_returns > 0 else "off",
    )
    cols[4].metric(
        "Реклама (ДРР)",
        rub(ads) if ads > 0 else "не загружена",
        delta=pct(drr(df)) if ads > 0 else None,
        delta_color="inverse",
    )
    cols[5].metric(
        "Себестоимость",
        rub(cogs) if has_cogs else "не задана",
        delta="загрузи COGS" if not has_cogs else None,
        delta_color="off",
    )
    if has_cogs:
        cols[6].metric("Реальная прибыль", rub(r_profit), delta=pct(r_margin))
    else:
        cols[6].metric("Реальная прибыль", "—", delta_color="off")

    st.divider()

    # Cost breakdown
    st.subheader("Структура затрат")
    c = st.columns(8)
    c[0].metric("Комиссия МП", rub(costs["commission"]),
                pct(costs.get("commission_pct", 0)), delta_color="off")
    c[1].metric("НДС на комиссию", rub(costs["vat_commission"]),
                pct(costs.get("vat_commission_pct", 0)), delta_color="off")
    c[2].metric("Эквайринг", rub(costs["acquiring"]),
                pct(costs.get("acquiring_pct", 0)), delta_color="off")
    c[3].metric("Логистика", rub(costs["logistics"]),
                pct(costs.get("logistics_pct", 0)), delta_color="off")
    c[4].metric("Хранение + ПВЗ", rub(costs["storage"]),
                pct(costs.get("storage_pct", 0)), delta_color="off")
    c[5].metric("Возвраты", rub(costs["returns"]),
                pct(costs.get("returns_pct", 0)), delta_color="off")
    c[6].metric("Штрафы", rub(costs["penalties"]),
                pct(costs.get("penalties_pct", 0)), delta_color="off")
    c[7].metric("Удержания МП", rub(costs["uderzhaniya"]),
                pct(costs.get("uderzhaniya_pct", 0)), delta_color="off")

    st.divider()

    # Pie + dynamics
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
                names=pie_labels, values=pie_values, hole=0.55,
                title="Распределение выручки",
                color_discrete_sequence=[WB_ACCENT, OZON_ACCENT, SUCCESS, INFO,
                                         DANGER, "#EC4899", "#14B8A6", "#A855F7",
                                         "#F472B6", "#22C55E"],
            )
            fig_pie.update_traces(textinfo="percent+label", textfont_size=11)
            fig_pie.update_layout(showlegend=False, height=400)
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
                    line=dict(color=color, width=2, shape="spline"),
                ))
                fig_daily.add_trace(go.Scatter(
                    x=sub["day"], y=sub["net_profit"].round(0),
                    name=f"К перечислению {label}", mode="lines",
                    line=dict(color=color, dash="dot", width=1.5, shape="spline"),
                ))
            fig_daily.update_layout(
                xaxis_title="Дата", yaxis_title="₽",
                yaxis=dict(tickformat=",.0f"),
                legend=dict(orientation="h", y=-0.25),
                hovermode="x unified", height=400,
                margin=dict(t=20),
            )
            st.plotly_chart(apply_plotly_theme(fig_daily), width="stretch")
