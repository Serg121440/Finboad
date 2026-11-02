"""Графики над таблицами «Рекламы», «Финансового результата» и «ОПиУ по месяцам».

Суммы — из того же расчёта, что и таблицы под графиками (Result.facts); по дням — pnl.engine.daily_results
и ads_daily, которые сходятся с месячным итогом (по дням — до налогов: налог считается за месяц)."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.common import MP_NAMES, rub
from dashboard.theme import ACCENT, ADS_COLOR, DANGER, MP_COLORS, SUCCESS, WARN, apply_plotly_theme, kpi_card
from dashboard.views.products_overview import PLOT, SEP, _donut, _pp
from pnl.engine import NO_SKU

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
          "ноябрь", "декабрь"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
# what 100 ₽ of revenue turns into; «Хранение и прочее» closes the sum to the result
PER100 = {"Комиссия МП": ["commission"], "Себестоимость": ["cogs"], "Логистика": ["logistics"],
          "Реклама": ["ads"], "Налоги": ["vat", "tax"], "Хранение и прочее": ["storage", "penalties", "services", "other"]}
PER100_COLORS = ["#5C9DFF", "#8B5CF6", "#14B8A6", ADS_COLOR, "#EC4899", "#64748B"]
# Ozon / WB cabinets one after another get lighter shades of the marketplace colour
MP_SHADES = {"ozon": ["#005BFF", "#5C9DFF", "#9CC2FF", "#C7DBFF"], "wb": ["#8B5CF6", "#A78BFA", "#C4B5FD", "#DDD6FE"]}
HEAT_ROWS = 15
WINDOW = 7                 # days in the heatmap's rolling ДРР


def _pct(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _loaded(days: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Days after the last one with data are not zeros, they are not loaded yet."""
    has = days[(days[cols] != 0).any(axis=1)]
    return days[days["date"] <= has["date"].max()] if not has.empty else days.iloc[0:0]


def cabinet_colors(cabinets: pd.DataFrame) -> dict:
    out, used = {}, {"ozon": 0, "wb": 0}
    for _, c in cabinets.sort_values("id").iterrows():
        mp = c["marketplace"]
        shades = MP_SHADES.get(mp, ["#94A3B8"])
        out[c["id"]] = shades[used.get(mp, 0) % len(shades)]
        used[mp] = used.get(mp, 0) + 1
    return out


def _cab_name(cabinets: pd.DataFrame, cid) -> str:
    c = cabinets[cabinets["id"] == cid]
    if c.empty:
        return str(cid)
    c = c.iloc[0]
    return f"{'WB' if c['marketplace'] == 'wb' else MP_NAMES.get(c['marketplace'], c['marketplace'])} · {c['name']}"


# ── Реклама ──────────────────────────────────────────────────────────────────

def _ads_totals(facts: pd.DataFrame, orders: pd.DataFrame) -> dict:
    ads, rev = -facts["ads"].sum(), facts["revenue"].sum()
    ordered = orders["ordered_sum"].sum() - orders.get("cancelled_sum", pd.Series(dtype=float)).sum() \
        if not orders.empty else 0.0
    common = -facts.loc[facts["sku"] == NO_SKU, "ads"].sum()
    return {"ads": ads, "drr": ads / rev if rev > 0 else np.nan,
            "drr_orders": ads / ordered if ordered > 0 else np.nan, "common": common / ads if ads > 0 else np.nan}


def ads_kpis(res, prev, label: str):
    t = _ads_totals(res.facts, res.orders)
    p = _ads_totals(prev.facts, prev.orders) if prev is not None and not prev.facts.empty else None
    c = st.columns(4)
    with c[0]:
        d = t["ads"] / p["ads"] - 1 if p and p["ads"] > 0 else None
        # spending more is neither good nor bad by itself: the arrow without a colour
        kpi_card("Расход на рекламу", rub(t["ads"]), f"{_pct(abs(d) * 100)} % {label}" if d is not None else "",
                 "muted", arrow=("▲ " if d > 0 else "▼ ") if d else None)
    for col, key, title in ((c[1], "drr", "ДРР к выручке"), (c[2], "drr_orders", "ДРР к заказам без отмен")):
        with col:
            d = t[key] - p[key] if p and pd.notna(p[key]) and pd.notna(t[key]) else None
            kpi_card(title, f"{_pct(t[key] * 100)} %" if pd.notna(t[key]) else "—",
                     f"{_pp(d)} {label}" if d is not None else "",
                     "up" if d is not None and d < 0 else "down" if d else "muted",
                     arrow=("▼ " if d < 0 else "▲ ") if d else None)
    with c[3]:
        kpi_card("Не делится по товарам", f"{_pct(t['common'] * 100, 0)} %" if pd.notna(t["common"]) else "—",
                 "«оплата за заказ — все товары» и т. п.", "muted")


def ads_daily_chart(daily: pd.DataFrame, cabinets: pd.DataFrame):
    """Ad money by day, stacked by marketplace, and ДРР к заказам on the right axis."""
    if daily.empty or daily["ads"].sum() == 0:
        return
    mp = dict(zip(cabinets["id"], cabinets["marketplace"]))
    d = daily.assign(mp=daily["cabinet_id"].map(mp))
    days = pd.DataFrame({"date": sorted(d["date"].unique())})
    by = d.pivot_table(index="date", columns="mp", values="ads", aggfunc="sum", fill_value=0)
    days = days.merge(by, left_on="date", right_index=True, how="left").fillna(0)
    days["ordered"] = days["date"].map(d.groupby("date")["ordered_sum"].sum()).fillna(0)
    mps = [m for m in ("ozon", "wb") if m in days]
    days = _loaded(days, mps)
    if days.empty:
        return
    days["total"] = days[mps].sum(axis=1)
    days["drr"] = np.where(days["ordered"] > 0, days["total"] / days["ordered"] * 100, np.nan)
    half = len(days) // 2
    head = "Реклама по дням"
    if half >= 7:
        a, b = days["total"].iloc[:half].mean(), days["total"].iloc[half:].mean()
        if a > 0 and b > 0 and max(a, b) / min(a, b) >= 1.3:
            head += (f" — во второй половине периода в {_pct(a / b)} раза дешевле" if b < a else
                     f" — во второй половине периода в {_pct(b / a)} раза дороже")
    st.markdown(f"**{head}**")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for m in mps:
        fig.add_bar(x=days["date"], y=days[m], name=MP_NAMES[m], marker_color=MP_COLORS[m], marker_line_width=0,
                    hovertemplate="%{x|%d.%m}: %{y:,.0f} ₽<extra>" + MP_NAMES[m] + "</extra>")
    fig.add_scatter(x=days["date"], y=days["drr"], name="ДРР к заказам, %", mode="lines",
                    line=dict(color=ADS_COLOR, width=2.5, shape="spline", smoothing=0.4),
                    hovertemplate="%{x|%d.%m}: %{y:.1f} %<extra>ДРР к заказам</extra>", secondary_y=True)
    fig.update_layout(barmode="stack", bargap=0.25, height=320, separators=SEP,
                      legend=dict(orientation="h", y=1.12, x=0), margin=dict(t=30, l=10, r=10, b=10))
    fig.update_xaxes(tickformat="%d.%m")
    fig.update_yaxes(tickformat=",.0f", secondary_y=False)
    fig.update_yaxes(ticksuffix=" %", tickformat=".0f", showgrid=False, rangemode="tozero", secondary_y=True)
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def drr_heatmap(daily: pd.DataFrame, names: pd.DataFrame, limit: float):
    """Products with the most ad money × day; colour — ДРР к заказам over the last WINDOW days."""
    d = daily[daily["sku"] != NO_SKU]
    if d.empty or d["ads"].sum() == 0:
        return
    days = sorted(daily["date"].unique())
    last = daily.loc[(daily["ads"] != 0) | (daily["ordered_sum"] != 0), "date"].max()
    days = [x for x in days if x <= last]
    tot = d.groupby(["cabinet_id", "sku"])[["ads", "ordered_sum"]].sum()
    top = tot.nlargest(HEAT_ROWS, "ads")
    top = top[top["ads"] > 0]
    n_high = int((top["ads"] > top["ordered_sum"] * limit / 100).sum())
    st.markdown(f"**Тепловая карта ДРР: {n_high} из {len(top)} самых рекламируемых товаров тратят больше "
                f"{_pct(limit, 0)} % заказов**")
    st.caption(f"Строка — товар, столбец — день. Цвет — реклама к заказам за {WINDOW} дней по этот день (за один "
               "день у товара заказов бывает 0–1, такой ДРР ничего не говорит): зелёный — дёшево, жёлтый — около "
               "порога, красный — дорого, тёмно-красный — расход был, заказов нет. Пусто — рекламы не было.")
    nm = names.set_index(["cabinet_id", "sku"])
    cap = limit * 3
    z, text, labels = [], [], []
    for (cid, sku), row in top.iterrows():
        part = d[(d["cabinet_id"] == cid) & (d["sku"] == sku)].groupby("date")[["ads", "ordered_sum"]].sum() \
            .reindex(days, fill_value=0.0)
        roll = part.rolling(WINDOW, min_periods=1).sum()
        zr, tr = [], []
        for (a, o) in roll[["ads", "ordered_sum"]].itertuples(index=False):
            if a <= 0:
                zr.append(None)
                tr.append("рекламы нет")
            elif o <= 0:
                zr.append(cap * 1.1)
                tr.append(f"за {WINDOW} дн.: реклама {rub(a)}, заказов нет")
            else:
                zr.append(min(a / o * 100, cap))
                tr.append(f"за {WINDOW} дн.: ДРР {_pct(a / o * 100)} % · реклама {rub(a)} · заказы {rub(o)}")
        z.append(zr)
        text.append(tr)
        name = nm["name"].get((cid, sku), "") if (cid, sku) in nm.index else ""
        art = nm["article"].get((cid, sku), "") if (cid, sku) in nm.index else ""
        name = str(name or sku)
        short = (name if len(name) <= 28 else name[:27].rstrip() + "…") + f" · {art or sku}"
        drr = row["ads"] / row["ordered_sum"] * 100 if row["ordered_sum"] > 0 else None
        labels.append(f"{short} · {_pct(drr, 0) + ' %' if drr is not None else 'нет заказов'}")
    hi = cap * 1.1
    scale = [[0, "#0F766E"], [limit / 2 / hi, "#10B981"], [limit / hi, "#F59E0B"], [cap / hi * 0.999, "#EF4444"],
             [cap / hi, "#991B1B"], [1, "#991B1B"]]
    fig = go.Figure(go.Heatmap(
        z=z, x=days, y=labels, text=text, zmin=0, zmax=hi, colorscale=scale, xgap=2, ygap=2,
        hovertemplate="%{y}<br>%{x|%d.%m}: %{text}<extra></extra>",
        colorbar=dict(title="ДРР, %", ticksuffix=" %", thickness=10, len=0.9,
                      tickvals=[0, limit, cap], ticktext=["0", f"{_pct(limit, 0)}", f"{_pct(cap, 0)}+"])))
    fig.update_layout(height=26 * len(labels) + 70, separators=SEP, margin=dict(t=10, l=10, r=10, b=10),
                      yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=11)),
                      xaxis=dict(tickformat="%d.%m", showgrid=False))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def ads_product_map(g: pd.DataFrame, limit: float):
    """Revenue (log) against ДРР к выручке; the dot is ad money; red — above the limit."""
    s = g[(g["sku"] != NO_SKU) & (g["revenue"] > 0) & (g["ads"] < 0)].copy()
    if len(s) < 3:
        return
    s["ad"] = -s["ads"]
    s["d"] = (s["ad"] / s["revenue"] * 100).clip(upper=60)
    high = s["d"] > limit
    share = s.loc[high, "revenue"].sum() / s["revenue"].sum() * 100
    st.markdown(f"**Товары с ДРР выше {_pct(limit, 0)} % — {high.sum()} шт., {_pct(share, 0)} % выручки рекламируемых**")
    size = np.sqrt(s["ad"]) / max(1, np.sqrt(s["ad"].max())) * 34 + 6
    fig = go.Figure(go.Scatter(
        x=s["revenue"], y=s["d"], mode="markers",
        marker=dict(size=size, color=np.where(high, DANGER, ACCENT), opacity=0.7, line=dict(width=0)),
        customdata=np.stack([s["name"].astype(str).str.slice(0, 60), s["ad"], s["profit"]], axis=-1),
        hovertemplate="%{customdata[0]}<br>выручка %{x:,.0f} ₽ · ДРР %{y:.1f} %<br>реклама %{customdata[1]:,.0f} ₽"
                      " · прибыль %{customdata[2]:,.0f} ₽<extra></extra>"))
    fig.add_hrect(y0=limit, y1=62, fillcolor=DANGER, opacity=0.06, line_width=0)
    fig.add_hline(y=limit, line_color=ADS_COLOR, line_dash="dash", line_width=1)
    fig.update_layout(height=340, separators=SEP, margin=dict(t=10, l=10, r=10, b=10),
                      xaxis=dict(type="log", title="выручка, ₽", tickformat=",.0f"),
                      yaxis=dict(title="ДРР к выручке, %", range=[0, 62], ticksuffix=" %"))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)
    st.caption("Размер точки — расход на рекламу. ДРР обрезан на 60 %.")


def ads_donut(facts: pd.DataFrame, cabinets: pd.DataFrame):
    by = (-facts.groupby("cabinet_id")["ads"].sum()).sort_values(ascending=False)
    by = by[by > 0]
    if by.empty:
        return
    if len(by) == 1:
        common = -facts.loc[facts["sku"] == NO_SKU, "ads"].sum()
        direct = by.iloc[0] - common
        st.markdown(f"**{_pct(common / by.iloc[0] * 100, 0)} % рекламы не делится по товарам**")
        _donut(["по товарам", "не делится по товарам"], [direct, common], [ACCENT, "#64748B"],
               f"{_pct(by.iloc[0] / 1e6, 2)} млн" if by.iloc[0] >= 1e6 else f"{by.iloc[0] / 1e3:.0f} тыс.", "реклама",
               "%{label}: %{value:,.0f} ₽")
        return
    colors = cabinet_colors(cabinets)
    top = by.index[0]
    st.markdown(f"**{_cab_name(cabinets, top)} — {_pct(by.iloc[0] / by.sum() * 100, 0)} % рекламного бюджета**"
                if len(by) > 1 else "**Рекламный бюджет**")
    total = by.sum()
    _donut([_cab_name(cabinets, c) for c in by.index], by.values, [colors[c] for c in by.index],
           f"{_pct(total / 1e6, 2)} млн" if total >= 1e6 else f"{total / 1e3:.0f} тыс.", "реклама",
           "%{label}: %{value:,.0f} ₽")


def ads_overview(res, prev, label: str, daily: pd.DataFrame, g: pd.DataFrame, cabinets: pd.DataFrame,
                 limit: float):
    ads_kpis(res, prev, label)
    with st.container(border=True):
        ads_daily_chart(daily, cabinets)
    with st.container(border=True):
        drr_heatmap(daily, g[["cabinet_id", "sku", "name", "article"]], limit)
    a, b = st.columns([3, 2])
    with a.container(border=True):
        ads_product_map(g, limit)
    with b.container(border=True):
        ads_donut(res.facts, cabinets)


# ── Финансовый результат ─────────────────────────────────────────────────────

def _period_name(d0: date, d1: date) -> str:
    if d0.day == 1 and (d1 + timedelta(days=1)).day == 1 and d0.month == d1.month:
        return MONTHS[d0.month - 1]
    return f"{d0:%d.%m}–{d1:%d.%m}"


def pace_chart(cur: pd.DataFrame, prev: pd.DataFrame, f, p0: date, p1: date):
    """Revenue to date against the previous period day by day, and the result to date."""
    c = cur.groupby("date")[["revenue", "result"]].sum()
    days = pd.DataFrame({"date": pd.date_range(f.date_from, f.date_to).date})
    days = days.merge(c, left_on="date", right_index=True, how="left").fillna(0)
    days = _loaded(days, ["revenue"])
    if len(days) < 3:
        return
    days["n"] = range(1, len(days) + 1)
    days["cum"], days["cum_res"] = days["revenue"].cumsum(), days["result"].cumsum()
    pc = prev.groupby("date")["revenue"].sum() if not prev.empty else pd.Series(dtype=float)
    pd_ = pd.DataFrame({"date": pd.date_range(p0, p1).date})
    pd_["cum"] = pd_["date"].map(pc).fillna(0).cumsum()
    pd_["n"] = range(1, len(pd_) + 1)
    pname = _period_name(p0, p1)
    total_prev = pd_["cum"].iloc[-1] if not pd_.empty else 0
    head = "Выручка нарастающим итогом"
    if total_prev > 0:
        over = days[days["cum"] >= total_prev]
        if not over.empty:
            head = f"Темп: выручка всего периода «{pname}» набрана уже к {over['date'].iloc[0]:%d.%m}"
        else:
            same = pd_.loc[pd_["n"] == days["n"].iloc[-1], "cum"]
            if not same.empty and same.iloc[0] > 0:
                r = days["cum"].iloc[-1] / same.iloc[0] - 1
                head = f"Темп: за {len(days)} дн. выручка {'▲' if r >= 0 else '▼'} {_pct(abs(r) * 100, 0)} % к тем же дням ({pname})"
    st.markdown(f"**{head}**")
    fig = go.Figure()
    neg = days["cum_res"].iloc[-1] < 0
    fig.add_scatter(x=days["n"], y=days["cum_res"], name="Результат до налогов", mode="lines", fill="tozeroy",
                    line=dict(color=DANGER if neg else SUCCESS, width=1.2),
                    fillcolor="rgba(239,68,68,0.25)" if neg else "rgba(16,185,129,0.22)",
                    customdata=days["date"], hovertemplate="%{customdata|%d.%m}: %{y:,.0f} ₽<extra>результат</extra>")
    if total_prev > 0:
        fig.add_scatter(x=pd_["n"], y=pd_["cum"], name=pname.capitalize(), mode="lines",
                        line=dict(color="#94A3B8", width=2, dash="dash"), customdata=pd_["date"],
                        hovertemplate="%{customdata|%d.%m}: %{y:,.0f} ₽<extra>" + pname + "</extra>")
    fig.add_scatter(x=days["n"], y=days["cum"], name="Выручка", mode="lines", line=dict(color=ACCENT, width=3),
                    customdata=days["date"], hovertemplate="%{customdata|%d.%m}: %{y:,.0f} ₽<extra>выручка</extra>")
    fig.update_layout(height=320, separators=SEP, legend=dict(orientation="h", y=1.12, x=0),
                      margin=dict(t=30, l=10, r=10, b=10), xaxis=dict(title="день периода", dtick=5),
                      yaxis=dict(tickformat=",.0f"))
    fig.add_hline(y=0, line_color="rgba(148,163,184,0.6)", line_width=1)
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)
    st.caption("По дням — результат до налогов: налог считается за месяц по юрлицу.")


def per100(facts: pd.DataFrame) -> pd.Series:
    """What 100 ₽ of revenue turned into: costs as positive ₽, «Хранение и прочее» closes to the result."""
    rev, profit = facts["revenue"].sum(), facts["profit"].sum()
    s = pd.Series({k: -facts[[c for c in cols if c in facts]].sum().sum() / rev * 100 for k, cols in PER100.items()})
    s["Хранение и прочее"] = 100 - profit / rev * 100 - s.drop("Хранение и прочее").sum()
    return s


def per100_bars(groups: dict[str, pd.DataFrame], title_by: str):
    """One 100 % bar per group (cabinet or month) and the result per 100 ₽ to the right."""
    rows = {k: (per100(v), v["profit"].sum() / v["revenue"].sum() * 100) for k, v in groups.items()
            if v["revenue"].sum() > 0}
    if not rows:
        return
    big = {k: s.drop("Себестоимость").idxmax() for k, (s, _) in rows.items()}
    worst = max(rows, key=lambda k: rows[k][0][big[k]])
    st.markdown(f"**Из каждых 100 ₽ выручки: {big[worst].lower()} у «{worst}» — "
                f"{_pct(rows[worst][0][big[worst]], 0)} ₽**" if len(rows) > 1 else
                f"**Из каждых 100 ₽ выручки {_pct(rows[worst][0].sum(), 1)} ₽ уходит на расходы**")
    names = list(rows)
    fig = go.Figure()
    for (cat, color) in zip(PER100, PER100_COLORS):
        vals = [max(rows[n][0][cat], 0) for n in names]
        fig.add_bar(y=names, x=vals, name=cat, orientation="h", marker_color=color, marker_line_width=0,
                    text=[_pct(v, 0) if v >= 5 else "" for v in vals], textposition="inside",
                    insidetextanchor="middle", hovertemplate="%{y} · " + cat + ": %{x:.1f} ₽ на 100 ₽<extra></extra>")
    res = [rows[n][1] for n in names]
    top = max(sum(max(rows[n][0][c], 0) for c in PER100) for n in names)
    fig.add_scatter(y=names, x=[top * 1.04] * len(names), mode="text", showlegend=False,
                    text=[f"<b>{'+' if r >= 0 else '−'}{_pct(abs(r))} ₽</b>" for r in res], textposition="middle right",
                    textfont=dict(color=[SUCCESS if r >= 0 else DANGER for r in res]), hoverinfo="skip")
    fig.add_vline(x=100, line_color="rgba(148,163,184,0.7)", line_dash="dash", line_width=1)
    fig.update_layout(barmode="stack", height=46 * len(names) + 150, separators=SEP, bargap=0.3,
                      legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0, traceorder="normal"),
                      margin=dict(t=60, l=10, r=10, b=10),
                      xaxis=dict(range=[0, top * 1.18], ticksuffix=" ₽", title=f"₽ на 100 ₽ выручки"),
                      yaxis=dict(autorange="reversed", showgrid=False))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)
    st.caption(f"Пунктир — 100 ₽: всё, что правее, — убыток. Справа — результат на 100 ₽ ({title_by}).")


def cabinets_chart(facts: pd.DataFrame, cabinets: pd.DataFrame):
    by = facts.groupby("cabinet_id")[["revenue", "profit"]].sum().sort_values("revenue", ascending=False)
    by = by[by["revenue"] != 0]
    if len(by) < 2:
        return
    names = [_cab_name(cabinets, c) for c in by.index]
    loss = by["profit"].clip(upper=0)
    if loss.sum() < 0:
        w = loss.idxmin()
        st.markdown(f"**{_cab_name(cabinets, w)} даёт {_pct(by.loc[w, 'revenue'] / by['revenue'].sum() * 100, 0)} % "
                    f"выручки и {_pct(loss[w] / loss.sum() * 100, 0)} % убытка**")
    else:
        st.markdown("**Выручка и прибыль по кабинетам**")
    colors = cabinet_colors(cabinets)
    fig = go.Figure()
    fig.add_bar(y=names, x=by["revenue"], name="Выручка", orientation="h",
                marker_color=[colors[c] for c in by.index], marker_line_width=0,
                text=[rub(v) for v in by["revenue"]], textposition="outside", cliponaxis=False,
                hovertemplate="%{y}: выручка %{x:,.0f} ₽<extra></extra>")
    fig.add_bar(y=names, x=by["profit"], name="Прибыль", orientation="h",
                marker_color=[SUCCESS if v >= 0 else DANGER for v in by["profit"]], marker_line_width=0,
                text=[rub(v) for v in by["profit"]], textposition="outside", cliponaxis=False,
                hovertemplate="%{y}: прибыль %{x:,.0f} ₽<extra></extra>")
    lo = min(0, by["profit"].min())
    fig.update_layout(barmode="group", height=70 * len(names) + 60, separators=SEP, bargap=0.25,
                      legend=dict(orientation="h", y=1.08, x=0), margin=dict(t=30, l=10, r=10, b=10),
                      xaxis=dict(visible=False, range=[lo * 1.6, by["revenue"].max() * 1.35]),
                      yaxis=dict(autorange="reversed", showgrid=False))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def summary_overview(f, res, cur: pd.DataFrame, prev: pd.DataFrame, p0: date, p1: date):
    from dashboard.views.products_overview import waterfall
    with st.container(border=True):
        pace_chart(cur, prev, f, p0, p1)
    a, b = st.columns(2)
    with a.container(border=True):
        waterfall(res.facts)
    with b.container(border=True):
        if res.facts["cabinet_id"].nunique() > 1:
            cabinets_chart(res.facts, f.cabinets)
        else:
            per100_bars({_cab_name(f.cabinets, res.facts["cabinet_id"].iloc[0]): res.facts}, "кабинет")
    if res.facts["cabinet_id"].nunique() > 1:
        with st.container(border=True):
            per100_bars({_cab_name(f.cabinets, c): p for c, p in res.facts.groupby("cabinet_id")}, "по кабинетам")


# ── ОПиУ по месяцам ──────────────────────────────────────────────────────────

def _weeks(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    dt = pd.to_datetime(d["date"])
    d["week"] = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.date
    w = d.groupby("week", as_index=False).agg(revenue=("revenue", "sum"), ads=("ads", "sum"),
                                               result=("result", "sum"), days=("date", "nunique"))
    # a week cut by the period is not comparable with whole ones: say so on the axis
    w["label"] = [f"{x:%d.%m}" + (f" ({n} дн.)" if n < 7 else "") for x, n in zip(w["week"], w["days"])]
    return w.rename(columns={"result": "profit"})


def _comparable(periods: pd.DataFrame) -> pd.DataFrame:
    """Whole weeks only when there are at least two of them (months are compared as they are)."""
    if "days" in periods:
        full = periods[periods["days"] == 7]
        if len(full) >= 2:
            return full
    return periods


def trend_chart(periods: pd.DataFrame, step: str):
    """periods: label, revenue, profit, ads (ads negative)."""
    if periods.empty:
        return
    c = _comparable(periods)
    first, last = c.iloc[0], c.iloc[-1]
    if len(c) >= 2 and first["revenue"] > 0:
        r = last["revenue"] / first["revenue"]
        head = (f"Выручка {'выросла' if r >= 1 else 'снизилась'} в {_pct(max(r, 1 / r))} раза "
                f"с {first['label']} по {last['label']}") if abs(r - 1) >= 0.15 else "Выручка держится на одном уровне"
        head += ", прибыль в минусе" if last["profit"] < 0 else ", прибыль в плюсе"
    else:
        head = "Выручка и прибыль"
    st.markdown(f"**{head}**")
    fig = go.Figure()
    fig.add_bar(x=periods["label"], y=periods["revenue"], name="Выручка", marker_color=ACCENT, marker_line_width=0,
                text=[f"{v / 1e6:.1f}".replace(".", ",") if abs(v) >= 1e6 else f"{v / 1e3:.0f} т" for v in periods["revenue"]],
                textposition="outside", cliponaxis=False, hovertemplate="%{x}: %{y:,.0f} ₽<extra>выручка</extra>")
    fig.add_bar(x=periods["label"], y=periods["profit"], name="Прибыль" if step == "м" else "Результат до налогов",
                marker_color=[SUCCESS if v >= 0 else DANGER for v in periods["profit"]], marker_line_width=0,
                hovertemplate="%{x}: %{y:,.0f} ₽<extra>прибыль</extra>")
    fig.update_layout(barmode="group", bargap=0.3, height=320, separators=SEP, legend=dict(orientation="h", y=1.12, x=0),
                      margin=dict(t=30, l=10, r=10, b=10), yaxis=dict(tickformat=",.0f"),
                      xaxis=dict(type="category"))
    fig.add_hline(y=0, line_color="rgba(148,163,184,0.6)", line_width=1)
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def ratio_chart(periods: pd.DataFrame):
    """Margin and ДРР in % of revenue per period."""
    p = _comparable(periods[periods["revenue"] > 0])
    if len(p) < 2:
        return
    m = p["profit"] / p["revenue"] * 100
    d = -p["ads"] / p["revenue"] * 100
    dm, dd = m.iloc[-1] - m.iloc[0], d.iloc[-1] - d.iloc[0]
    st.markdown(f"**Маржа {'▲' if dm >= 0 else '▼'} {_pct(abs(dm))} п.п., ДРР {'▼' if dd <= 0 else '▲'} "
                f"{_pct(abs(dd))} п.п. с {p['label'].iloc[0]}**")
    fig = go.Figure()
    fig.add_scatter(x=p["label"], y=m, name="Маржа", mode="lines+markers", line=dict(color=DANGER if m.iloc[-1] < 0 else SUCCESS, width=2.5),
                    hovertemplate="%{x}: %{y:.1f} %<extra>маржа</extra>")
    fig.add_scatter(x=p["label"], y=d, name="ДРР", mode="lines+markers", line=dict(color=ADS_COLOR, width=2.5),
                    hovertemplate="%{x}: %{y:.1f} %<extra>ДРР</extra>")
    fig.add_hline(y=0, line_color="rgba(148,163,184,0.6)", line_width=1)
    fig.update_layout(height=300, separators=SEP, legend=dict(orientation="h", y=1.12, x=0),
                      margin=dict(t=30, l=10, r=10, b=10), yaxis=dict(ticksuffix=" %"), xaxis=dict(type="category"))
    st.plotly_chart(apply_plotly_theme(fig), use_container_width=True, config=PLOT)


def opiu_overview(facts: pd.DataFrame, g: pd.DataFrame, daily: pd.DataFrame, months: list[str]):
    """g: summarize by month (sorted); daily: daily_results of the same scope (for weeks)."""
    step = st.segmented_control("Шаг графиков", ["По месяцам", "По неделям"], key="opiu_step",
                                default="По месяцам" if len(g) >= 3 else "По неделям") or "По месяцам"
    if step == "По неделям" and not daily.empty:
        periods = _weeks(daily)
        periods = periods[periods["revenue"] != 0]
        s = "н"
    else:
        periods = g.assign(label=[m.split(" ·")[0] for m in months])[["label", "revenue", "profit", "ads"]]
        s = "м"
    with st.container(border=True):
        trend_chart(periods, s)
        if s == "н":
            st.caption("По неделям — результат до налогов: налог считается за месяц. Неделя — с понедельника.")
    a, b = st.columns(2)
    with a.container(border=True):
        per100_bars({m.split(" ·")[0]: p for m, (_, p) in zip(months, facts.groupby("month"))}, "по месяцам")
    with b.container(border=True):
        ratio_chart(periods)
