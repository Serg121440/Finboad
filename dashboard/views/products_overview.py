"""Товары: обзор над таблицей — KPI к прошлому периоду, заказы и реклама по дням, куда уходит
выручка, статусы товаров, карта товаров, лидеры и аутсайдеры, структура расходов и групп.

Все суммы — из той же таблицы товаров (product_table), что и таблица ниже, поэтому графики и
таблица сходятся между собой и с итогом кабинета."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.common import rub
from dashboard.theme import (
    ACCENT, ADS_COLOR, DANGER, MP_COLORS, SUCCESS, WARN, apply_plotly_theme, kpi_card,
)
from pnl.engine import NO_SKU

PLOT = {"displayModeBar": False}
SEP = ", "                   # plotly separators: decimal comma, thin space for thousands
NO_SALES = ("нет продаж", "только возвраты")
STATUS_COLORS = {"прибыль": SUCCESS, "убыток": DANGER, "нет продаж": "#64748B", "только возвраты": "#94A3B8",
                 "нет себестоимости": WARN}
EXPENSES = {"Комиссия МП": ["commission"], "Себестоимость": ["cogs"], "Реклама": ["ads"],
            "Логистика": ["logistics"], "Налоги": ["vat", "tax"],
            "Хранение и прочее": ["storage", "penalties", "services", "other"]}
EXPENSE_COLORS = ["#5C9DFF", "#8B5CF6", ADS_COLOR, "#14B8A6", "#EC4899", "#64748B"]
GROUP_COLORS = ["#8B5CF6", "#5C9DFF", "#14B8A6", "#EC4899", WARN, "#64748B"]
TOP_GROUPS = 5


def previous_period(d0: date, d1: date) -> tuple[date, date, str]:
    """The period to compare with: the previous whole month for a whole month, else as many days before."""
    if d0.day == 1 and (d1 + timedelta(days=1)).day == 1:
        p1 = d0 - timedelta(days=1)
        return p1.replace(day=1), p1, "к прошлому месяцу"
    n = (d1 - d0).days + 1
    return d0 - timedelta(days=n), d0 - timedelta(days=1), f"к прошлым {n} дн."


def totals(g: pd.DataFrame) -> dict:
    rev, ads, profit = g["revenue"].sum(), -g["ads"].sum(), g["profit"].sum()
    return {"revenue": rev, "profit": profit, "ads": ads, "net_qty": g["net_qty"].sum(),
            "ordered_sum": g["ordered_sum"].sum(),
            "margin": profit / rev if rev > 0 else np.nan, "drr": ads / rev if rev > 0 else np.nan}


def _pp(x: float) -> str:
    return f"{abs(x) * 100:.1f}".replace(".", ",") + " п.п."


def kpi_row(g: pd.DataFrame, prev: pd.DataFrame | None, label: str):
    t = totals(g)
    p = totals(prev) if prev is not None and not prev.empty else None
    c = st.columns(4)
    with c[0]:
        d = (t["revenue"] / p["revenue"] - 1) if p and p["revenue"] > 0 else None
        kpi_card("Выручка", rub(t["revenue"]),
                 f"{abs(d) * 100:.1f} % {label}".replace(".", ",") if d is not None else
                 f"{t['net_qty']:.0f} шт. выкуплено", "up" if d and d > 0 else "down" if d else "muted")
    with c[1]:
        d = t["profit"] - p["profit"] if p else None
        kpi_card("Прибыль", rub(t["profit"]),
                 f"{'лучше' if d >= 0 else 'хуже'} на {rub(abs(d))} {label}" if d is not None else "",
                 "up" if d is not None and d >= 0 else "down" if d is not None else "muted")
    with c[2]:
        d = t["margin"] - p["margin"] if p and pd.notna(p["margin"]) and pd.notna(t["margin"]) else None
        kpi_card("Маржа к выручке", f"{t['margin'] * 100:.1f} %".replace(".", ",") if pd.notna(t["margin"]) else "—",
                 f"{_pp(d)} {label}" if d is not None else "", "up" if d and d > 0 else "down" if d else "muted")
    with c[3]:
        d = t["drr"] - p["drr"] if p and pd.notna(p["drr"]) and pd.notna(t["drr"]) else None
        # less ad money per rouble of revenue is the good direction
        kpi_card("ДРР к выручке", f"{t['drr'] * 100:.1f} %".replace(".", ",") if pd.notna(t["drr"]) else "—",
                 f"{_pp(d)} {label}" if d is not None else f"реклама {rub(t['ads'])}",
                 "up" if d is not None and d < 0 else "down" if d else "muted",
                 arrow=("▼ " if d < 0 else "▲ ") if d else None)


def mp_color(g: pd.DataFrame) -> str:
    mps = g.loc[g["sku"] != NO_SKU, "marketplace"].dropna().unique()
    return MP_COLORS.get(mps[0], ACCENT) if len(mps) == 1 else ACCENT


def daily_chart(t: pd.DataFrame, color: str):
    """Orders by order date and ad money by day, one x axis."""
    if t.empty or (t["ordered_sum"].sum() == 0 and t["ads"].sum() == 0):
        return
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.06)
    r, gg, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    fig.add_scatter(x=t["date"], y=t["ordered_sum"], name="Заказано, ₽", mode="lines", fill="tozeroy",
                    line=dict(color=color, width=2.5, shape="spline", smoothing=0.4),
                    fillcolor=f"rgba({r},{gg},{b},0.16)", hovertemplate="%{x|%d.%m}: %{y:,.0f} ₽<extra>заказы</extra>",
                    row=1, col=1)
    fig.add_bar(x=t["date"], y=-t["ads"], name="Реклама, ₽", marker_color=ADS_COLOR, marker_line_width=0,
                hovertemplate="%{x|%d.%m}: %{y:,.0f} ₽<extra>реклама</extra>", row=2, col=1)
    fig.update_layout(height=340, showlegend=True, legend=dict(orientation="h", y=1.1, x=0), bargap=0.25,
                      separators=SEP, margin=dict(t=30, l=10, r=10, b=10))
    fig.update_xaxes(tickformat="%d.%m")
    fig.update_yaxes(tickformat=",.0f")
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def _expenses(before: pd.DataFrame) -> pd.Series:
    """Costs of the period as positive roubles, the cabinet's common rows included (before spreading)."""
    s = pd.Series({k: -before[cols].sum().sum() for k, cols in EXPENSES.items()})
    return s


def waterfall(before: pd.DataFrame):
    """Revenue → each kind of cost → profit. «Хранение и прочее» takes what is left, so it always closes."""
    rev, profit = before["revenue"].sum(), before["profit"].sum()
    if rev <= 0:
        return
    e = _expenses(before)
    e["Хранение и прочее"] = rev - profit - e.drop("Хранение и прочее").sum()
    e = e[e.abs() >= 1]
    labels = ["Выручка", *e.index, "Прибыль"]
    values = [rev, *(-e.values), profit]
    fig = go.Figure(go.Waterfall(
        # revenue as a «relative» step from zero: an «absolute» bar takes the totals colour
        x=labels, y=values, measure=["relative", *["relative"] * len(e), "total"],
        text=[f"{v / 1e6:.2f}".replace(".", ",") if abs(rev) >= 1e6 else f"{v / 1e3:.0f} тыс." for v in values],
        textposition="outside", connector=dict(line=dict(color="rgba(148,163,184,0.35)", width=1)),
        increasing=dict(marker=dict(color=ACCENT)), decreasing=dict(marker=dict(color="rgba(239,68,68,0.6)")),
        totals=dict(marker=dict(color=SUCCESS if profit >= 0 else DANGER)),
        customdata=[100, *(e.values / rev * 100), profit / rev * 100],
        hovertemplate="%{x}: %{y:,.0f} ₽ · %{customdata:.1f} % выручки<extra></extra>"))
    fig.update_layout(height=340, showlegend=False, separators=SEP, yaxis=dict(tickformat=",.0f"),
                      margin=dict(t=30, l=10, r=10, b=10))
    big = e.idxmax()
    st.markdown(f"**{big} — {e.max() / rev * 100:.0f} % выручки, самый большой расход**".replace(".", ","))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def _donut(labels, values, colors, center: str, sub: str, hover: str = "%{label}: %{value:,.0f}"):
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.64, sort=False, direction="clockwise",
                           marker=dict(colors=colors, line=dict(width=2, color="rgba(0,0,0,0)")),
                           textinfo="none", hovertemplate=hover + " · %{percent}<extra></extra>"))
    fig.add_annotation(text=f"<b>{center}</b><br><span style='font-size:11px'>{sub}</span>", showarrow=False,
                       font=dict(size=20))
    fig.update_layout(height=260, showlegend=True, separators=SEP, margin=dict(t=10, l=10, r=10, b=10),
                      legend=dict(orientation="v", x=1.02, y=0.5, yanchor="middle"))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def status_donut(items: pd.DataFrame):
    counts = items["status"].value_counts()
    counts = counts[[s for s in STATUS_COLORS if s in counts.index]]
    if counts.empty:
        return
    gain = items.loc[items["profit"] > 0, "profit"].sum()
    loss = items.loc[items["profit"] < 0, "profit"].sum()
    head = (f"**Убыточные съедают {abs(loss) / gain:.1f}× от того, что дают прибыльные**".replace(".", ",")
            if gain > 0 and abs(loss) > gain else f"**В плюсе {rub(gain)}, в минусе {rub(loss)}**")
    st.markdown(head)
    _donut(counts.index, counts.values, [STATUS_COLORS[s] for s in counts.index], f"{len(items)}", "товаров",
           "%{label}: %{value}")
    st.caption(f"В плюсе {rub(gain)} · в минусе {rub(loss)}")


def expense_donut(before: pd.DataFrame):
    rev, profit = before["revenue"].sum(), before["profit"].sum()
    if rev <= 0:
        return
    e = _expenses(before)
    e["Хранение и прочее"] = rev - profit - e.drop("Хранение и прочее").sum()
    e = e[e > 0]
    per100 = e.sum() / rev * 100
    st.markdown(f"**На 100 ₽ выручки — {per100:.1f} ₽ расходов**".replace(".", ","))
    _donut(e.index, e.values, EXPENSE_COLORS[:len(e)], f"{per100:.1f} ₽".replace(".", ","), "на 100 ₽ выручки",
           "%{label}: %{value:,.0f} ₽")


ADJ_ENDINGS = ("ая", "яя", "ый", "ий", "ой", "ое", "ее", "ые", "ие")


def product_group(name: str) -> str:
    """A rough product group from the name (the catalog keeps categories as ids only): the first word,
    with the next one when the first is an adjective — «Шведская стенка», «Беговая дорожка», «Батут»."""
    w = [x.strip(",.;:()«»\"") for x in str(name).split()]
    w = [x for x in w if x]
    if not w:
        return "—"
    if len(w) > 1 and w[0].lower().endswith(ADJ_ENDINGS):
        return f"{w[0].capitalize()} {w[1].lower()}"
    return w[0].capitalize()


def group_donut(items: pd.DataFrame):
    s = items[items["revenue"] > 0]
    if s.empty:
        return
    gr = s.assign(group=s["name"].map(product_group)).groupby("group")[["revenue", "profit"]].sum() \
        .sort_values("revenue", ascending=False)
    top = gr.head(TOP_GROUPS)
    rest = gr.iloc[TOP_GROUPS:]
    if not rest.empty:
        top = pd.concat([top, pd.DataFrame({"revenue": [rest["revenue"].sum()], "profit": [rest["profit"].sum()]},
                                           index=[f"Остальные ({len(rest)} групп)"])])
    plus = [g for g in top.index[:TOP_GROUPS] if top.loc[g, "profit"] > 0]
    st.markdown(f"**В плюсе из крупных групп: {', '.join(plus)}**" if plus else "**Все крупные группы в минусе**")
    labels = [f"{g} · {'+' if p >= 0 else '−'}{abs(p) / 1000:.0f} тыс." for g, p in top["profit"].items()]
    _donut(labels, top["revenue"].values, GROUP_COLORS[:len(top)], f"{s['revenue'].sum() / 1e6:.1f} млн".replace(".", ","),
           "выручка", "%{label}<br>выручка %{value:,.0f} ₽")


def product_map(items: pd.DataFrame):
    """Revenue (log) against margin; the dot is ad money. Red — sold at a loss."""
    s = items[(items["revenue"] > 0)].copy()
    if len(s) < 3:
        return
    s["m"] = (s["profit"] / s["revenue"] * 100).clip(-60, 40)
    s["ad"] = -s["ads"]
    top = s.nlargest(5, "revenue")
    near0 = (top["profit"] / top["revenue"]).abs().lt(0.05).sum()
    st.markdown(f"**{near0} из 5 самых продаваемых товаров работают около нуля (±5 %)**" if near0 >= 3 else
                "**Карта товаров: выручка против маржи**")
    size = (np.sqrt(s["ad"].clip(lower=0)) / max(1, np.sqrt(s["ad"].max())) * 34 + 6)
    fig = go.Figure(go.Scatter(
        x=s["revenue"], y=s["m"], mode="markers",
        marker=dict(size=size, color=np.where(s["profit"] < 0, DANGER, SUCCESS), opacity=0.7, line=dict(width=0)),
        customdata=np.stack([s["name"].str.slice(0, 60), s["profit"], s["ad"]], axis=-1),
        hovertemplate="%{customdata[0]}<br>выручка %{x:,.0f} ₽ · маржа %{y:.1f} %<br>прибыль %{customdata[1]:,.0f} ₽"
                      " · реклама %{customdata[2]:,.0f} ₽<extra></extra>"))
    fig.add_hrect(y0=-60, y1=0, fillcolor=DANGER, opacity=0.06, line_width=0)
    fig.add_hline(y=0, line_color="rgba(148,163,184,0.6)", line_width=1)
    fig.update_layout(height=360, separators=SEP, margin=dict(t=10, l=10, r=10, b=10),
                      xaxis=dict(type="log", title="выручка, ₽", tickformat=",.0f"),
                      yaxis=dict(title="маржа, %", range=[-62, 42], ticksuffix=" %"))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)
    st.caption("Красная зона — продажа стоит денег. Крупные точки справа внизу — первые кандидаты на пересмотр "
               "цены или ставок. Маржа обрезана на −60 % и +40 %.")


def leaders(items: pd.DataFrame, n: int = 5):
    s = items[items["revenue"] > 0]
    if s.empty:
        return
    worst = s.nsmallest(n, "profit")
    worst = worst[worst["profit"] < 0]
    best = s.nlargest(n, "profit")
    best = best[best["profit"] > 0]
    scale = max(abs(worst["profit"]).max() if not worst.empty else 0, best["profit"].max() if not best.empty else 0)
    for title, part, color in (("Тянут вниз", worst, DANGER), ("Тянут вверх", best, SUCCESS)):
        if part.empty:
            continue
        if title == "Тянут вниз":
            drr = (-part["ads"] / part["revenue"] * 100)
            title += f" · ДРР у всех от {drr.min():.0f} %" if drr.min() >= 15 else ""
        st.markdown(f"**{title}**")
        # the article keeps two products with the same start of the name on separate bars
        names = [(n if len(n) <= 26 else n[:25].rstrip() + "…") + f" · {a or s}"
                 for n, a, s in zip(part["name"], part["article"], part["sku"])]
        fig = go.Figure(go.Bar(x=part["profit"].abs(), y=names, orientation="h", marker_color=color,
                               text=part["profit"].map(rub), textposition="outside", cliponaxis=False,
                               customdata=part["name"], hovertemplate="%{customdata}: %{text}<extra></extra>"))
        fig.update_layout(height=40 * len(part) + 20, separators=SEP, margin=dict(t=0, l=10, r=10, b=0),
                          xaxis=dict(visible=False, range=[0, scale * 1.6]),
                          yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=11)))
        st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def overview(g: pd.DataFrame, before: pd.DataFrame, prev: pd.DataFrame | None, label: str, daily: pd.DataFrame):
    items = g[g["sku"] != NO_SKU]
    kpi_row(g, prev, label)
    with st.container(border=True):
        # days after the last loaded one are not zeros, they are not there yet
        has = daily[(daily["ordered_sum"] != 0) | (daily["ads"] != 0)]
        t = daily[daily["date"] <= has["date"].max()] if not has.empty else daily
        cut = ""
        if not t.empty and len(t) >= 14:
            ads = -t["ads"]
            half = len(t) // 2
            a, b = ads.iloc[:half].mean(), ads.iloc[half:].mean()
            if a > 0 and b / a < 0.7:
                cut = f" — реклама во второй половине периода в {a / b:.1f} раза дешевле".replace(".", ",")
        st.markdown(f"**Заказы и реклама по дням{cut}**")
        daily_chart(t, mp_color(g))
    a, b = st.columns([2, 1])
    with a.container(border=True):
        waterfall(before)
    with b.container(border=True):
        status_donut(items)
    a, b = st.columns([2, 1])
    with a.container(border=True):
        product_map(items)
    with b.container(border=True):
        leaders(items)
    a, b = st.columns(2)
    with a.container(border=True):
        expense_donut(before)
    with b.container(border=True):
        group_donut(items)
