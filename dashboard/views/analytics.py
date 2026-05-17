"""Analytics page — categories, top-20 SKU, ABC analysis, MP comparison."""

import streamlit as st
import plotly.express as px

from analytics.metrics import (
    marketplace_comparison, abc_analysis, top_skus_by_profit,
)
from dashboard.shared import (
    render_filters_and_load, render_sync_log_sidebar, rub, pct, num,
)
from dashboard.theme import apply_plotly_theme, MP_LABELS, MP_COLORS


def render():
    ctx = render_filters_and_load()
    render_sync_log_sidebar()

    st.title("Аналитика")

    if ctx is None:
        st.info("Загрузи данные в разделе «Загрузка данных», чтобы начать анализ.")
        return

    df = ctx.df
    cogs_map = ctx.cogs_map
    has_cogs = ctx.has_cogs

    if df.empty:
        st.warning("Нет данных для выбранных фильтров.")
        return

    # ── Categories ────────────────────────────────────────────────────────────
    st.subheader("Анализ по категориям")

    df_cat = df.copy()
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
            color="margin_pct", color_continuous_scale="RdYlGn",
            labels={"net_profit": "К перечислению, ₽", "category": "",
                    "margin_pct": "Маржа, %"},
            title="К перечислению по категориям",
            text=cat_df["net_profit"].apply(lambda v: rub(v)),
        )
        fig_cat_rev.update_layout(yaxis=dict(autorange="reversed"), height=420)
        fig_cat_rev.update_traces(textposition="outside")
        st.plotly_chart(apply_plotly_theme(fig_cat_rev), width="stretch")
    with col_cat2:
        fig_cat_mg = px.bar(
            cat_df, x="margin_pct", y="category", orientation="h",
            color="margin_pct", color_continuous_scale="RdYlGn",
            labels={"margin_pct": "Маржа, %", "category": ""},
            title="Маржинальность по категориям",
            text=cat_df["margin_pct"].apply(lambda v: pct(v)),
        )
        fig_cat_mg.update_layout(yaxis=dict(autorange="reversed"), height=420)
        fig_cat_mg.update_traces(textposition="outside")
        st.plotly_chart(apply_plotly_theme(fig_cat_mg), width="stretch")

    cat_show = cat_df.copy()
    rename_map = {
        "category": "Категория", "revenue": "Выручка, ₽",
        "returns": "Возвраты, ₽", "commission": "Комиссия, ₽",
        "logistics": "Логистика, ₽", "net_profit": "К перечислению, ₽",
        "quantity": "Продано, шт.", "return_quantity": "Возвращено, шт.",
        "skus": "Товаров, шт.", "net_revenue": "Нетто-выручка, ₽",
        "margin_pct": "Маржа, %", "return_rate_pct": "Возвраты, %",
    }
    fmt_map = {
        "Выручка, ₽": lambda v: num(v), "Возвраты, ₽": lambda v: num(v),
        "Комиссия, ₽": lambda v: num(v), "Логистика, ₽": lambda v: num(v),
        "К перечислению, ₽": lambda v: num(v), "Нетто-выручка, ₽": lambda v: num(v),
        "Продано, шт.": lambda v: num(v), "Возвращено, шт.": lambda v: num(v),
        "Маржа, %": lambda v: f"{v:.1f}%", "Возвраты, %": lambda v: f"{v:.1f}%",
    }
    if has_cogs:
        rename_map["cogs_total"] = "Себестоимость, ₽"
        rename_map["real_profit"] = "Реальная прибыль, ₽"
        fmt_map["Себестоимость, ₽"] = lambda v: num(v)
        fmt_map["Реальная прибыль, ₽"] = lambda v: num(v)
    else:
        cat_show = cat_show.drop(columns=["cogs_total", "real_profit"])

    st.dataframe(cat_show.rename(columns=rename_map).style.format(fmt_map),
                 width="stretch", hide_index=True)

    st.divider()

    # ── Marketplace comparison ────────────────────────────────────────────────
    st.subheader("Сравнение маркетплейсов")
    mp_comp = marketplace_comparison(df)
    if not mp_comp.empty:
        col_a, col_b = st.columns(2)
        with col_a:
            _mp_bar = mp_comp.rename(columns={"revenue": "Выручка",
                                              "net_profit": "К перечислению"})
            fig_mp = px.bar(
                _mp_bar, x="marketplace", y=["Выручка", "К перечислению"],
                barmode="group",
                labels={"value": "₽", "marketplace": "", "variable": ""},
                color_discrete_map={"Выручка": "#10B981",
                                    "К перечислению": "#3B82F6"},
                title="Выручка и к перечислению",
            )
            fig_mp.update_xaxes(tickvals=_mp_bar["marketplace"],
                                ticktext=[MP_LABELS.get(m, m) for m in _mp_bar["marketplace"]])
            fig_mp.update_yaxes(tickformat=",.0f")
            st.plotly_chart(apply_plotly_theme(fig_mp), width="stretch")
        with col_b:
            fig_mg = px.bar(
                mp_comp, x="marketplace", y="margin_pct",
                color="marketplace", color_discrete_map=MP_COLORS,
                labels={"margin_pct": "Маржа, %", "marketplace": ""},
                title="Маржинальность (нетто-выручка)",
            )
            fig_mg.update_xaxes(tickvals=mp_comp["marketplace"],
                                ticktext=[MP_LABELS.get(m, m) for m in mp_comp["marketplace"]])
            fig_mg.update_yaxes(ticksuffix="%", tickformat=".1f")
            st.plotly_chart(apply_plotly_theme(fig_mg), width="stretch")

        _mp_cols = ["marketplace", "revenue", "returns", "commission",
                    "vat_commission", "acquiring", "logistics", "storage",
                    "penalties", "uderzhaniya", "ad_spend", "net_profit",
                    "net_revenue", "margin_pct", "quantity"]
        st.dataframe(
            mp_comp[[c for c in _mp_cols if c in mp_comp.columns]]
            .assign(marketplace=mp_comp["marketplace"].map(lambda m: MP_LABELS.get(m, m)))
            .rename(columns={
                "marketplace": "Маркетплейс", "revenue": "Выручка, ₽",
                "returns": "Возвраты, ₽", "commission": "Комиссия МП, ₽",
                "vat_commission": "НДС, ₽", "acquiring": "Эквайринг, ₽",
                "logistics": "Логистика, ₽", "storage": "Хранение+Приёмка, ₽",
                "penalties": "Штрафы, ₽", "uderzhaniya": "Удержания, ₽",
                "ad_spend": "Реклама, ₽", "net_profit": "К перечислению, ₽",
                "net_revenue": "Нетто-выручка, ₽", "margin_pct": "Маржа, %",
                "quantity": "Продано, шт.",
            }).style.format({k: (lambda v: num(v)) for k in [
                "Выручка, ₽", "Возвраты, ₽", "Комиссия МП, ₽", "НДС, ₽",
                "Эквайринг, ₽", "Логистика, ₽", "Хранение+Приёмка, ₽",
                "Штрафы, ₽", "Удержания, ₽", "Реклама, ₽",
                "К перечислению, ₽", "Нетто-выручка, ₽", "Продано, шт.",
            ]} | {"Маржа, %": lambda v: f"{v:.1f}%"}),
            width="stretch", hide_index=True,
        )

    st.divider()

    # ── Top-20 SKU ────────────────────────────────────────────────────────────
    st.subheader("Топ-20 SKU по прибыли")
    top = top_skus_by_profit(df, cogs_map, n=20)
    if not top.empty:
        profit_col = "real_profit" if has_cogs else "net_profit"
        profit_label = "Реальная прибыль" if has_cogs else "К перечислению"
        display_name = top.apply(
            lambda r: r["product_name"] if r["product_name"] else r["sku"], axis=1
        )

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
        fmt_top = {
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
        top_display["marketplace"] = top_display["marketplace"].map(
            lambda m: MP_LABELS.get(m, m))
        st.dataframe(
            top_display.rename(columns={
                "sku": "Артикул", "product_name": "Наименование",
                "category": "Категория", "marketplace": "МП",
                "revenue": "Выручка, ₽", "net_profit": "К перечислению, ₽",
                "margin_pct": "Маржа МП, %", "real_margin_pct": "Реальная маржа, %",
                "return_rate_pct": "Возвраты, %", "commission_pct": "Комиссия, %",
                "drr_pct": "ДРР, %", "logistics_per_unit": "Лог./ед, ₽",
                "quantity": "Продано, шт.", "return_quantity": "Возвращено, шт.",
            }).style.format(fmt_top),
            width="stretch", hide_index=True,
        )

    st.divider()

    # ── ABC analysis ──────────────────────────────────────────────────────────
    st.subheader("ABC-анализ по прибыли")
    col_abc1, col_abc2 = st.columns([1, 2])
    abc = abc_analysis(df, cogs_map)
    with col_abc1:
        if not abc.empty:
            abc_sum = abc.groupby("abc_class").agg(
                count=("sku", "count"), profit=("net_profit", "sum")
            ).reset_index()
            fig_abc = px.bar(
                abc_sum, x="abc_class", y="profit", color="abc_class",
                color_discrete_map={"A": "#10B981", "B": "#F59E0B", "C": "#EF4444"},
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
                abc[["abc_class", "sku", "product_name", "net_profit",
                     "cumulative_pct"]].rename(columns={
                    "abc_class": "Класс", "sku": "Артикул",
                    "product_name": "Наименование", "net_profit": "Прибыль, ₽",
                    "cumulative_pct": "Нарастающий итог, %",
                }).style.format({
                    "Прибыль, ₽": lambda v: num(v),
                    "Нарастающий итог, %": lambda v: f"{v:.1f}%",
                }),
                width="stretch", hide_index=True, height=320,
            )
