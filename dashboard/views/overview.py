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
    apply_plotly_theme, kpi_card, MP_LABELS, MP_COLORS,
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

    # Daily trends for sparklines
    _daily = df.groupby(df["date"].dt.date).agg(
        revenue=("revenue", "sum"),
        net_profit=("net_profit", "sum"),
        ad_spend=("ad_spend", "sum"),
        quantity=("quantity", "sum"),
    ).sort_index()
    trend_revenue = _daily["revenue"].tolist()
    trend_profit  = _daily["net_profit"].tolist()
    trend_ads     = _daily["ad_spend"].tolist()
    trend_qty     = _daily["quantity"].tolist()

    # ── KPI row 1: revenue + payout + qty ────────────────────────────────────
    row1 = st.columns(4)
    with row1[0]:
        kpi_card("Выручка (брутто)", rub(gross), trend=trend_revenue, accent=WB_ACCENT)
    with row1[1]:
        kpi_card("Выручка (нетто)", rub(net), trend=trend_revenue, accent=INFO)
    with row1[2]:
        kpi_card("К перечислению МП", rub(profit), delta=pct(margin),
                 delta_color="up" if margin >= 0 else "down",
                 trend=trend_profit, accent=SUCCESS)
    with row1[3]:
        ret_color = "down" if total_returns > 0 else "muted"
        kpi_card("Продано / Возвращено", f"{num(total_qty)} шт.",
                 delta=f"возвраты: {num(total_returns)}",
                 delta_color=ret_color, trend=trend_qty, accent=OZON_ACCENT)

    # ── KPI row 2: ads + cogs + real profit + margin target ──────────────────
    row2 = st.columns(4)
    with row2[0]:
        kpi_card("Реклама (ДРР)",
                 rub(ads) if ads > 0 else "не загружена",
                 delta=pct(drr(df)) if ads > 0 else "—",
                 delta_color="down" if ads > 0 else "muted",
                 trend=trend_ads if ads > 0 else None, accent=DANGER)
    with row2[1]:
        kpi_card("Себестоимость",
                 rub(cogs) if has_cogs else "не задана",
                 delta="загрузи COGS" if not has_cogs else "",
                 delta_color="muted")
    with row2[2]:
        if has_cogs:
            kpi_card("Реальная прибыль", rub(r_profit), delta=pct(r_margin),
                     delta_color="up" if r_margin >= 0 else "down",
                     trend=trend_profit, accent=SUCCESS)
        else:
            kpi_card("Реальная прибыль", "—", delta_color="muted")
    with row2[3]:
        # Compact margin target
        margin_target = st.session_state.get("margin_target_pct", 30.0)
        margin_target = st.number_input(
            "Цель по марже, %", min_value=0.0, max_value=100.0,
            value=float(margin_target), step=1.0, key="margin_target_pct",
        )

    st.divider()

    # ── Margin bullet chart ───────────────────────────────────────────────────
    fig_bullet = go.Figure(go.Indicator(
        mode="number+gauge+delta",
        value=margin,
        domain={"x": [0, 1], "y": [0, 1]},
        delta={"reference": margin_target, "suffix": " п.п."},
        number={"suffix": "%", "valueformat": ".1f"},
        title={"text": "Маржа vs цель", "font": {"size": 14}},
        gauge={
            "shape": "bullet",
            "axis": {"range": [0, max(margin_target * 1.5, 50)]},
            "threshold": {
                "line": {"color": SUCCESS, "width": 3},
                "thickness": 0.85,
                "value": margin_target,
            },
            "steps": [
                {"range": [0, margin_target * 0.5], "color": "rgba(239,68,68,0.25)"},
                {"range": [margin_target * 0.5, margin_target], "color": "rgba(245,158,11,0.25)"},
                {"range": [margin_target, margin_target * 1.5], "color": "rgba(16,185,129,0.20)"},
            ],
            "bar": {"color": WB_ACCENT, "thickness": 0.5},
        },
    ))
    fig_bullet.update_layout(height=100, margin=dict(l=10, r=10, t=30, b=5))
    st.plotly_chart(apply_plotly_theme(fig_bullet), use_container_width=True)

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
