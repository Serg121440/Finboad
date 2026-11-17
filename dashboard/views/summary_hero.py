"""Top of «Финансовый результат»: the result on a dark panel with the revenue pace, what 100 ₽ of
revenue turns into, the indicator strip, what needs attention and the cabinets side by side.
Builders return HTML (tested without Streamlit); render() puts them on the page."""

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from dashboard.common import num, pct, rub
from dashboard.theme import card
from dashboard.views.report_charts import PER100, PER100_COLORS, _cab_name, _loaded, _pct, _period_name, per100

W, H, PAD_T, PAD_B = 760, 250, 30, 40          # the pace chart's viewBox
CAB_SCALE = 115                                # ₽ per 100 ₽ of revenue the cabinet bar is wide, at least


def _money(v: float, sign: bool = False) -> str:
    """Typographic minus instead of a hyphen; «+» for a result shown as a change."""
    s = rub(abs(v))
    return ("−" if v < 0 else "+" if sign and v > 0 else "") + s


def _per(v: float) -> str:
    return ("−" if v < 0 else "+") + _pct(abs(v)) + " ₽"


def pace(cur: pd.DataFrame, prev: pd.DataFrame, d0: date, d1: date, p0: date, p1: date):
    """Revenue to date by day of the period: (days of this period, days of the previous one, change
    or None). A period loaded to its last day is compared with the whole previous one, a period in
    progress — with the same number of days. Days after the last loaded one are left out."""
    days = pd.DataFrame({"date": pd.date_range(d0, d1).date})
    c = cur.groupby("date")["revenue"].sum() if not cur.empty else pd.Series(dtype=float)
    days["revenue"] = days["date"].map(c).fillna(0.0)
    days = _loaded(days, ["revenue"])
    days = days.assign(cum=days["revenue"].cumsum())
    before = pd.DataFrame({"date": pd.date_range(p0, p1).date})
    pc = prev.groupby("date")["revenue"].sum() if not prev.empty else pd.Series(dtype=float)
    before["cum"] = before["date"].map(pc).fillna(0.0).cumsum()
    change = None
    if len(days) and len(before):
        whole = len(days) == (d1 - d0).days + 1
        same = before["cum"].iloc[-1 if whole else min(len(days), len(before)) - 1]
        if same > 0:
            change = days["cum"].iloc[-1] / same - 1
    if before.empty or before["cum"].iloc[-1] <= 0:
        before = before.iloc[0:0]
    return days, before, change


def _short(v: float) -> str:
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}".replace(".", ",") + " млн"
    return f"{v / 1e3:.0f} тыс."


def pace_svg(days: pd.DataFrame, before: pd.DataFrame, total_days: int, pname: str) -> str:
    """The pace as one inline SVG: this period — line with a fill, the previous one — dashes."""
    if len(days) < 2:
        return ""
    top = max(days["cum"].max(), before["cum"].max() if len(before) else 0) or 1
    n = max(total_days, len(before), 2)

    def xy(i, v):
        return 20 + i / (n - 1) * (W - 40), H - PAD_B - max(v, 0) / top * (H - PAD_B - PAD_T)

    def path(vals):
        return " ".join(f"{x:.1f} {y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(vals)))

    base = H - PAD_B
    grid = "".join(f'<path d="M20 {base - k / 4 * (base - PAD_T):.1f}H{W - 20}"/>' for k in range(5))
    line = path(days["cum"])
    last_x, last_y = xy(len(days) - 1, days["cum"].iloc[-1])
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="transparent">'
                   f'<title>{d:%d.%m}: {escape(rub(v))}</title></circle>'
                   for (x, y), d, v in ((xy(i, v), d, v) for i, (d, v) in enumerate(zip(days["date"], days["cum"]))))
    prev_line = prev_label = ""
    if len(before):
        prev_line = (f'<path d="M{path(before["cum"])}" fill="none" stroke="#8A91A0" stroke-width="1.6" '
                     'stroke-dasharray="5 5"/>')
        prev_label = (f'<text x="{W - 20}" y="18" text-anchor="end" fill="#B8BECB">'
                      f'{escape(pname)} · {_short(before["cum"].iloc[-1])}</text>')
    label = (f"Выручка нарастающим итогом за {len(days)} дн.: {_short(days['cum'].iloc[-1])} ₽"
             + (f", {pname} — {_short(before['cum'].iloc[-1])} ₽" if len(before) else ""))
    return (
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}">'
        '<defs><linearGradient id="fbPace" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#8EA0FF" stop-opacity=".34"/>'
        '<stop offset="1" stop-color="#8EA0FF" stop-opacity="0"/></linearGradient></defs>'
        f'<g stroke="#fff" stroke-opacity=".08">{grid}</g>'
        f'<g fill="#8A91A0" font-size="16"><text x="20" y="{H - 10}">{days["date"].iloc[0]:%d.%m}</text>'
        f'<text x="{last_x:.1f}" y="{H - 10}" text-anchor="{"end" if last_x > W - 60 else "middle"}">'
        f'{days["date"].iloc[-1]:%d.%m}</text><text x="24" y="{PAD_T + 20}">{_short(top)}</text></g>'
        f'{prev_line}<path d="M{line} V{base} H20Z" fill="url(#fbPace)"/>'
        f'<path d="M{line}" fill="none" stroke="#A9B6FF" stroke-width="2.6" stroke-linejoin="round" '
        'stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="5" fill="#A9B6FF" stroke="#14161C" stroke-width="2"/>'
        f'<g font-size="16" font-weight="600">{prev_label}</g>{dots}</svg>')


def hero_html(total: dict, final: str, change, compare: str, svg: str, hide_cogs: bool = False) -> str:
    net = total["net"]
    margin, roi, fixed = total.get("margin"), total.get("roi"), -total.get("fixed", 0)
    chips = []
    if margin is not None and not pd.isna(margin):
        chips.append(f'<span class="fb-chip {"neg" if margin < 0 else "pos"}">маржа {pct(margin).replace("-", "−")}</span>')
    if not hide_cogs and roi is not None and not pd.isna(roi):
        chips.append(f'<span class="fb-chip">ROI {pct(roi).replace("-", "−")}</span>')
    if fixed:
        chips.append(f'<span class="fb-chip">постоянные {rub(fixed)}</span>')
    delta = ""
    if change is not None:
        delta = (f'<div class="fb-hero-delta {"up" if change >= 0 else "down"}">{"▲" if change >= 0 else "▼"} '
                 f'{_pct(abs(change) * 100, 0)} % {escape(compare)}</div>')
    return (
        '<div class="fb-hero"><div class="fb-hero-top"><div>'
        f'<div class="fb-hero-label">Чистая прибыль{escape(final and " · предварительно")}</div>'
        f'<div class="fb-hero-value">{_money(net)}</div><div class="fb-chips">{"".join(chips)}</div></div>'
        '<div class="fb-hero-side"><div class="fb-hero-label">Выручка</div>'
        f'<div class="fb-hero-rev">{rub(total.get("revenue"))}</div>{delta}</div></div>{svg}</div>')


def per100_html(facts: pd.DataFrame) -> str:
    """What 100 ₽ of revenue goes to, biggest first, and what is left."""
    s = per100(facts)
    left = facts["profit"].sum() / facts["revenue"].sum() * 100
    color = dict(zip(PER100, PER100_COLORS))
    rows = s[s.abs() >= 0.05].sort_values(ascending=False)
    top = max(rows.max(), 1)
    body = "".join(
        f'<div><div class="fb-part-head"><span>{escape(k)}</span><b>{_pct(v)} ₽</b></div>'
        f'<div class="fb-track"><i style="width:{max(v, 0) / top * 100:.1f}%;background:{color[k]}"></i></div></div>'
        for k, v in rows.items())
    spent = 100 - left
    note = (f"Расходы — {_pct(spent)} ₽. Убыток {_pct(-left)} ₽ с каждой сотни." if left < 0 else
            f"Расходы — {_pct(spent)} ₽, остаётся {_pct(left)} ₽.")
    return ('<div class="fb-panel fb-parts"><div><h4>Куда уходят 100 ₽ выручки</h4>'
            f'<p class="fb-sub">{note}</p></div><div class="fb-part-list">{body}</div>'
            f'<div class="fb-left {"neg" if left < 0 else "pos"}"><span>Остаётся</span>'
            f'<b>{_per(left)}</b></div></div>')


def strip_html(total: dict, limit: float) -> str:
    """Orders, units, ads and ДРР with the limit mark (limit — % of revenue)."""
    drr = (total.get("drr") or 0) * 100
    scale = max(limit * 1.5, drr * 1.1, 1)
    cells = [
        ("Заказы", rub(total.get("ordered_sum")), f"выкуплено на {rub(total.get('revenue'))}"),
        ("Продано", f"{num(total.get('sold'))} шт", f"возвратов {num(total.get('returned'))} шт"),
        ("Реклама", rub(-total.get("ads", 0)),
         f"{pct(total.get('drr_orders'))} к заказам" if total.get("drr_orders") is not None else " "),
    ]
    out = "".join(f'<div class="fb-cell"><div class="fb-cell-label">{a}</div><div class="fb-cell-value">{b}</div>'
                  f'<div class="fb-cell-sub">{c}</div></div>' for a, b, c in cells)
    over = drr > limit
    out += (f'<div class="fb-cell"><div class="fb-cell-label fb-between"><span>ДРР к выручке</span>'
            f'<span>порог {_pct(limit, 0)} %</span></div><div class="fb-cell-value">{pct(total.get("drr"))}</div>'
            f'<div class="fb-track fb-meter"><i class="{"over" if over else ""}" '
            f'style="width:{min(drr / scale, 1) * 100:.1f}%"></i><u style="left:{limit / scale * 100:.1f}%"></u>'
            '</div></div>')
    return f'<div class="fb-panel fb-strip">{out}</div>'


def cabinet_rows(facts: pd.DataFrame, cabinets: pd.DataFrame) -> list[dict]:
    """Cabinets with revenue, biggest first: money, the result per 100 ₽ and where the 100 ₽ went."""
    rows = []
    for cid, part in facts.groupby("cabinet_id"):
        rev = part["revenue"].sum()
        if rev <= 0:
            continue
        c = cabinets[cabinets["id"] == cid]
        mp = c.iloc[0]["marketplace"] if not c.empty else ""
        rows.append({"id": cid, "name": _cab_name(cabinets, cid), "mp": mp, "revenue": rev,
                     "profit": part["profit"].sum(), "per": part["profit"].sum() / rev * 100, "parts": per100(part)})
    return sorted(rows, key=lambda r: -r["revenue"])


def cabinet_scale(rows: list[dict]) -> float:
    """One scale for every cabinet's bar and the 100 ₽ mark: wide enough for the costliest cabinet."""
    return max(CAB_SCALE, *(r["parts"].clip(lower=0).sum() for r in rows))


def cabinets_html(rows: list[dict]) -> str:
    color = dict(zip(PER100, PER100_COLORS))
    top = max(r["revenue"] for r in rows)
    scale = cabinet_scale(rows)
    legend = "".join(f'<span><i style="background:{c}"></i>{escape(k)}</span>' for k, c in color.items())
    body = ""
    for r in rows:
        tone = "pos" if r["profit"] >= 0 else "neg"
        seg = "".join(f'<i style="width:{max(v, 0) / scale * 100:.2f}%;background:{color[k]}" '
                      f'title="{escape(k)}: {_pct(v)} ₽ из 100"></i>' for k, v in r["parts"].items())
        tag = {"ozon": "OZ", "wb": "WB"}.get(r["mp"], "")
        body += (
            f'<div class="fb-cab"><div class="fb-cab-name"><span class="fb-mp {r["mp"]}">{tag}</span>'
            f'<span>{escape(r["name"].split(" · ", 1)[-1])}</span></div>'
            f'<div><b>{rub(r["revenue"])}</b><div class="fb-track thin"><i style="width:{r["revenue"] / top * 100:.1f}%">'
            f'</i></div></div><div class="fb-num {tone}">{_money(r["profit"], sign=True)}</div>'
            f'<div class="fb-stack">{seg}<u style="left:{100 / scale * 100:.2f}%"></u></div>'
            f'<div class="fb-num"><span class="fb-chip {tone}">{_per(r["per"])}</span></div></div>')
    return ('<div class="fb-panel"><div class="fb-between fb-wrap"><h4>Кабинеты</h4>'
            f'<div class="fb-legend">{legend}</div></div><div class="fb-scroll"><div class="fb-cabs">'
            '<div class="fb-cab head"><span>Кабинет</span><span>Выручка</span><span class="fb-num">Результат</span>'
            '<span>Расходы на 100 ₽ выручки</span><span class="fb-num">Остаётся</span></div>'
            f'{body}</div></div><p class="fb-sub">Отметка — 100 ₽: всё, что правее, уже убыток.</p></div>')


def insights(rows: list[dict], issues: list) -> list[dict]:
    """Up to three cards: the cabinet that loses most per 100 ₽, open issues that have a page to fix
    them, the cabinet that earns. Each: tone, tag, title, text and an optional (link, button)."""
    out = []
    multi = len(rows) > 1
    worst = min(rows, key=lambda r: r["per"]) if rows else None
    if multi and worst["per"] < 0:
        big = worst["parts"].drop("Себестоимость", errors="ignore")
        others = [r["parts"][big.idxmax()] for r in rows if r is not worst]
        out.append({"tone": "neg", "tag": "Убыточный кабинет",
                    "title": f"{worst['name']} теряет {_pct(-worst['per'])} ₽ с каждых 100 ₽ выручки",
                    "text": f"{big.idxmax()} — {_pct(big.max(), 0)} ₽ из 100; у остальных кабинетов "
                            f"от {_pct(min(others), 0)} до {_pct(max(others), 0)} ₽."})
    best = max(rows, key=lambda r: r["per"]) if rows else None
    good = None
    if multi and best["per"] > 0 and best is not worst:
        plus = sum(r["profit"] > 0 for r in rows)
        good = {"tone": "pos", "tag": "В плюсе",
                "title": (f"{best['name']} — единственный прибыльный кабинет: " if plus == 1 else
                          f"{best['name']} — лучший кабинет: ") + _money(best["profit"], sign=True),
                "text": f"Остаётся {_pct(best['per'])} ₽ с каждых 100 ₽ выручки."}
    linked = sorted((i for i in issues if i.link), key=lambda i: not i.blocking)
    for i in linked[:3 - len(out) - bool(good)]:
        head, tail = _split(i.text)
        out.append({"tone": "neg" if i.blocking else "info", "tag": "Данные" if i.blocking else "Товары",
                    "title": head, "text": tail[:1].upper() + tail[1:] + "." if tail else "",
                    "link": i.link, "button": i.button or "Открыть"})
    if good:
        out.append(good)
    return out


def _split(text: str) -> tuple[str, str]:
    """An issue line as a card: the fact and what follows from it (after the dash or in brackets)."""
    if " (" in text and text.endswith(")"):
        head, _, tail = text[:-1].partition(" (")
    else:
        head, _, tail = text.partition(" — ")
    return head, tail


def _insight_cards(items: list[dict]):
    from dashboard.nav import can_go, go
    st.markdown("#### Что требует внимания")
    for n, (col, it) in enumerate(zip(st.columns(len(items)), items)):
        with card(col):
            st.html(f'<div class="fb-insight"><span class="fb-chip {it["tone"]}">{escape(it["tag"])}</span>'
                    f'<b>{escape(it["title"])}</b><p>{escape(it["text"])}</p></div>')
            page, _, quick = it.get("link", "").partition(":")
            if page and can_go(page) and st.button(it["button"], key=f"ins_{n}", icon=":material/arrow_forward:",
                                                   type="tertiary"):
                go(page, **({"prod_quick": quick} if quick else {}))


def render(f, res, total: dict, final: str, issues: list, limit: float,
           cur: pd.DataFrame, prev: pd.DataFrame, p0: date, p1: date, label: str, hide_cogs: bool = False):
    days, before, change = pace(cur, prev, f.date_from, f.date_to, p0, p1)
    pname = _period_name(p0, p1)
    svg = pace_svg(days, before, (f.date_to - f.date_from).days + 1, pname)
    whole = len(days) == (f.date_to - f.date_from).days + 1
    # a period in progress is compared with as many days of the previous one: name those days
    m = min(len(days), (p1 - p0).days + 1)
    compare = label if whole else f"к {p0:%d.%m}–{p0 + timedelta(days=max(m, 1) - 1):%d.%m} ({m} дн.)"
    hero = hero_html(total, final, change, compare, svg, hide_cogs)
    facts = res.facts
    if facts["revenue"].sum() > 0:
        top = f'<div class="fb-top">{hero}{per100_html(facts)}</div>'
    else:
        top = f'<div class="fb-top">{hero}</div>'
    st.markdown(top, unsafe_allow_html=True)          # st.html drops inline SVG
    st.html(strip_html(total, limit))
    rows = cabinet_rows(facts, f.cabinets)
    items = insights(rows, issues)
    if items:
        _insight_cards(items)
    if len(rows) > 1:
        st.html(cabinets_html(rows))
