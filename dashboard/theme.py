"""Finboard design system — colors, CSS, custom components.

Light and dark themes are Streamlit's own (.streamlit/config.toml): the app follows
the device and the user switches in the ⋮ menu.
"""

from html import escape

import streamlit as st

# Page, sidebar, text, inputs and menus come from Streamlit's own light/dark theme
# (.streamlit/config.toml). Our CSS never names a background or text colour: cards and
# borders are tints of the current text colour, so they follow a theme switch in the
# ⋮ menu instantly, without a rerun.
CARD = "color-mix(in srgb, currentColor 4%, transparent)"
BORDER = "color-mix(in srgb, currentColor 14%, transparent)"
MUTED = "color-mix(in srgb, currentColor 62%, transparent)"
HOVER = "rgba(79,70,229,0.08)"
ACCENT_BG = "rgba(79,70,229,0.14)"
# UI accent (buttons, tabs, focus, hover borders) — deeper than the WB purple so white
# text on it and small accent text pass 4.5:1. Accent text is mixed with the current
# text colour: darker in the light theme, lighter in the dark one.
ACCENT = "#4F46E5"
ACCENT_TEXT = "color-mix(in srgb, #6366F1 70%, currentColor)"
# Card layer: white on the warm page («Бумага»), a lighter step on the dark one («Графит»).
# light-dark() reads the colour scheme Streamlit sets on .stApp, so it follows a theme
# switch without a rerun; browsers without it keep the tints above.
SURFACE = "var(--fb-card)"
LINE = "var(--fb-line)"
SHADOW = "var(--fb-shadow)"
SPARE = "#94A3B8"        # ordinary expenses in charts: neither good nor bad

# Brand accents (одинаковы в обеих темах)
WB_ACCENT   = "#8B5CF6"
OZON_ACCENT = "#005BFF"   # Ozon's own blue; amber stays for ads and warnings
SUCCESS     = "#10B981"
DANGER      = "#EF4444"
INFO        = "#3B82F6"
WARN        = "#F59E0B"
ADS_COLOR   = WARN       # ad money in charts

MP_COLORS = {"wb": WB_ACCENT, "ozon": OZON_ACCENT, "other": "#94A3B8"}
MP_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "other": "Прочие"}

PLOTLY_PALETTE = [WB_ACCENT, OZON_ACCENT, "#14B8A6", "#EC4899", WARN, "#64748B", SUCCESS, DANGER]

def theme_toggle_sidebar():
    with st.sidebar:
        st.caption("Тема следует за устройством (день/ночь); переключить — меню ⋮ справа сверху → "
                   "Light / Dark / System.")


def plotly_layout() -> dict:
    grid = "rgba(148,163,184,0.16)"
    font = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    axis = dict(gridcolor=grid, gridwidth=1, zerolinecolor="rgba(148,163,184,0.4)", zerolinewidth=1,
                showline=False, ticks="", automargin=True)
    return dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=font, color="#8A94A6", size=12),
        xaxis=axis, yaxis=axis, barcornerradius=5,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        hoverlabel=dict(font=dict(family=font, size=13), bordercolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
    )


def apply_plotly_theme(fig):
    """Apply Finboard theme to a Plotly figure."""
    fig.update_layout(**plotly_layout())
    return fig


def inject_css():
    """Global CSS; colours that differ between themes are left to Streamlit."""
    st.session_state["_fb_cards"] = 0          # card keys restart with every run
    st.html(f"""
    <style>
      .stApp {{
        --fb-card: {CARD}; --fb-line: {BORDER}; --fb-shadow: none; --fb-soft: {CARD}; --fb-hero: #14161C;
        --fb-pos: {SUCCESS}; --fb-neg: {DANGER}; --fb-posbg: rgba(16,185,129,0.14); --fb-negbg: rgba(239,68,68,0.14);
        font-variant-numeric: tabular-nums;
      }}
      @supports (color: light-dark(#fff, #000)) {{
        .stApp {{
          --fb-card: light-dark(#FFFFFF, #161B26);
          --fb-line: light-dark(#E4E2DB, #262D3D);
          --fb-soft: light-dark(#F3F2ED, #1D2330);
          --fb-hero: light-dark(#14161C, #1A2030);
          --fb-pos: light-dark(#0B7A5C, #3DD6A3); --fb-neg: light-dark(#C2371D, #FF8D73);
          --fb-posbg: light-dark(#E2F3EC, #12332A); --fb-negbg: light-dark(#FBE6E0, #3A1D17);
          --fb-shadow: 0 1px 2px light-dark(rgba(17,24,39,0.05), rgba(0,0,0,0.30)),
                       0 8px 24px light-dark(rgba(17,24,39,0.06), rgba(0,0,0,0.22));
        }}
      }}

      .fb-spark {{ display: block; width: 100%; height: 30px; margin-top: 10px; }}

      /* Type scale: 12 / 13 / 14 / 16 / 20 / 28 */
      h1, h2, h3, h4 {{ letter-spacing: -0.02em; font-weight: 700 !important; }}
      h1 {{ font-size: 28px !important; }}
      h2 {{ font-size: 20px !important; }}
      h3 {{ font-size: 16px !important; color: {MUTED} !important; font-weight: 600 !important; }}

      /* Cards: every framed block (theme.card) sits on the card layer */
      [class*="st-key-fbcard"] {{
        background: {SURFACE}; border-color: {LINE} !important; border-radius: 16px !important;
        box-shadow: {SHADOW}; padding: 20px !important;
      }}

      /* Metric cards */
      div[data-testid="stMetric"] {{
        background: {SURFACE}; border: 1px solid {LINE}; border-radius: 16px; padding: 18px 20px;
        box-shadow: {SHADOW};
      }}
      div[data-testid="stMetricLabel"] p {{
        color: {MUTED} !important; font-size: 13px !important; font-weight: 500 !important;
      }}
      div[data-testid="stMetricValue"] {{
        font-size: 28px !important; font-weight: 700 !important; letter-spacing: -0.02em;
      }}

      /* Sidebar: the open page in the accent tint */
      [data-testid="stSidebarNav"] a[aria-current="page"] {{ background: {ACCENT_BG}; }}
      [data-testid="stSidebarNav"] a[aria-current="page"] span {{ color: {ACCENT_TEXT}; }}

      /* Buttons */
      .stButton > button, .stDownloadButton > button {{ border-radius: 8px; font-weight: 500; }}
      .stButton > button:hover, .stDownloadButton > button:hover {{ border-color: {ACCENT}; }}

      /* Expanders, uploader, tables */
      details[data-testid="stExpander"] {{ border-radius: 12px !important; }}
      [data-testid="stFileUploader"] section {{ border: 1px dashed {BORDER}; border-radius: 12px; }}
      .stDataFrame, [data-testid="stTable"] {{ border-radius: 12px; }}
      [data-testid="stAlert"] > div {{ border-radius: 12px; }}

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] {{
        gap: 4px; background: {CARD}; border-radius: 12px; padding: 4px; border: 1px solid {BORDER};
      }}
      .stTabs [data-baseweb="tab"] {{
        background: transparent; color: {MUTED}; border-radius: 8px; padding: 8px 16px; font-weight: 500;
      }}
      .stTabs [aria-selected="true"] {{ background: {ACCENT_BG} !important; color: {ACCENT_TEXT} !important; }}

      hr {{ border-color: {BORDER} !important; }}
      .block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px; }}

      /* Finboard brand */
      .fb-brand {{
        display: flex; align-items: center; gap: 10px;
        padding: 8px 4px 16px 4px; border-bottom: 1px solid {BORDER}; margin-bottom: 12px;
      }}
      .fb-brand-dot {{
        width: 16px; height: 16px; border-radius: 4px;
        background: linear-gradient(135deg, {WB_ACCENT}, {INFO});
      }}
      .fb-brand-name {{ font-weight: 800; letter-spacing: 2px; font-size: 14px; }}

      /* KPI cards */
      .fb-kpi {{
        background: {SURFACE}; border: 1px solid {LINE}; border-radius: 16px; padding: 18px;
        min-height: 108px; margin-bottom: 8px; box-shadow: {SHADOW}; transition: border-color .2s, transform .2s;
      }}
      .fb-kpi:hover {{ border-color: {ACCENT}; transform: translateY(-1px); }}
      /* one line each, so cards in a row keep the same height; the full text is in the tooltip */
      .fb-kpi-label, .fb-kpi-delta {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .fb-kpi-label {{ font-size: 13px; color: {MUTED}; font-weight: 500; margin-bottom: 8px; line-height: 1.3; }}
      .fb-kpi-value {{
        font-size: clamp(22px, 2vw, 28px); font-weight: 700; letter-spacing: -0.02em; line-height: 1.1;
        white-space: nowrap;
      }}
      .fb-kpi-delta {{ font-size: 12px; font-weight: 500; margin-top: 6px; color: {MUTED}; }}
      .fb-kpi-delta.up {{ color: {SUCCESS}; }}
      .fb-kpi-delta.down {{ color: {DANGER}; }}


      /* «Финансовый результат»: the result panel, 100 ₽ of revenue, indicator strip, cabinets */
      .fb-top {{ display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 8px; }}
      .fb-hero {{
        flex: 2 1 520px; min-width: 0; background: var(--fb-hero); color: #F2F3F7; border-radius: 24px;
        padding: 28px 30px 16px; box-shadow: {SHADOW}; display: flex; flex-direction: column; gap: 16px;
      }}
      .fb-hero svg {{ width: 100%; height: auto; display: block; font-family: inherit; }}
      .fb-hero-top {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px; }}
      .fb-hero-label {{ font-size: 13px; font-weight: 500; color: #A7ADBA; }}
      .fb-hero-value {{
        font-size: clamp(36px, 4.2vw, 56px); line-height: 1.05; font-weight: 700; letter-spacing: -0.035em;
        margin-top: 6px; white-space: nowrap;
      }}
      .fb-hero-side {{ text-align: right; }}
      .fb-hero-rev {{ font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-top: 4px; white-space: nowrap; }}
      .fb-hero-delta {{ font-size: 13px; margin-top: 4px; }}
      .fb-hero-delta.up {{ color: #6EE7B7; }}
      .fb-hero-delta.down {{ color: #FFA48D; }}
      .fb-chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
      .fb-chip {{
        display: inline-block; padding: 5px 12px; border-radius: 999px; font-size: 13px; font-weight: 600;
        background: {CARD}; white-space: nowrap;
      }}
      .fb-chip.pos {{ background: var(--fb-posbg); color: var(--fb-pos); }}
      .fb-chip.neg {{ background: var(--fb-negbg); color: var(--fb-neg); }}
      .fb-chip.info {{ background: {ACCENT_BG}; color: {ACCENT_TEXT}; }}
      .fb-hero .fb-chip {{ background: rgba(255,255,255,0.09); color: #D5D9E2; font-weight: 500; }}
      .fb-hero .fb-chip.neg {{ background: #3A1D17; color: #FFA48D; font-weight: 600; }}
      .fb-hero .fb-chip.pos {{ background: #12332A; color: #6EE7B7; font-weight: 600; }}

      .fb-panel {{
        background: {SURFACE}; border: 1px solid {LINE}; border-radius: 20px; box-shadow: {SHADOW};
        padding: 24px 26px;
      }}
      .fb-panel h4 {{ margin: 0; padding: 0; font-size: 18px; line-height: 1.3; letter-spacing: -0.015em; }}
      .fb-sub {{ margin: 4px 0 0; font-size: 13px; color: {MUTED}; }}
      .fb-between {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px 20px; }}
      .fb-wrap {{ flex-wrap: wrap; margin-bottom: 14px; }}
      .fb-track {{ height: 8px; border-radius: 999px; background: var(--fb-soft); position: relative; }}
      .fb-track > i {{ display: block; height: 100%; border-radius: 999px; background: {ACCENT}; }}
      .fb-track.thin {{ height: 4px; margin-top: 6px; }}
      .fb-track.thin > i {{ background: {MUTED}; }}

      .fb-parts {{ flex: 1 1 300px; min-width: 0; border-radius: 24px; display: flex; flex-direction: column; gap: 16px; }}
      .fb-part-list {{ display: flex; flex-direction: column; gap: 14px; }}
      .fb-part-head {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; font-size: 14px; }}
      .fb-part-head span {{ color: {MUTED}; }}
      .fb-left {{
        margin-top: auto; display: flex; justify-content: space-between; align-items: center; gap: 12px;
        border-radius: 14px; padding: 12px 16px; font-weight: 600; font-size: 14px;
      }}
      .fb-left b {{ font-size: 20px; letter-spacing: -0.02em; white-space: nowrap; }}
      .fb-left.neg {{ background: var(--fb-negbg); color: var(--fb-neg); }}
      .fb-left.pos {{ background: var(--fb-posbg); color: var(--fb-pos); }}

      .fb-strip {{ padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); overflow: hidden; }}
      .fb-cell {{ padding: 20px 24px; box-shadow: 1px 0 0 {LINE}, 0 1px 0 {LINE}; }}
      .fb-cell-label {{ font-size: 13px; font-weight: 500; color: {MUTED}; }}
      .fb-cell-value {{ font-size: 26px; font-weight: 700; letter-spacing: -0.025em; margin-top: 4px; white-space: nowrap; }}
      .fb-cell-sub {{ font-size: 13px; color: {MUTED}; margin-top: 6px; }}
      .fb-meter {{ margin-top: 14px; }}
      .fb-meter > i.over {{ background: var(--fb-neg); }}
      .fb-meter > u, .fb-stack > u {{ position: absolute; top: -4px; bottom: -4px; width: 2px; background: currentColor; }}

      .fb-scroll {{ overflow-x: auto; }}
      .fb-cabs {{ min-width: 820px; font-size: 14px; }}
      .fb-cab {{
        display: grid; grid-template-columns: 1.5fr 1.3fr 1fr 2.4fr 0.8fr; gap: 20px; align-items: center;
        min-height: 64px; border-bottom: 1px solid {LINE};
      }}
      .fb-cab.head {{ min-height: 0; padding-bottom: 10px; font-size: 12px; font-weight: 500; color: {MUTED}; }}
      .fb-cab-name {{ display: flex; align-items: center; gap: 10px; min-width: 0; font-weight: 600; }}
      .fb-cab-name span:last-child {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
      .fb-mp {{
        width: 30px; height: 30px; border-radius: 9px; flex: none; display: flex; align-items: center;
        justify-content: center; font-size: 11px; font-weight: 700; color: #fff; background: #64748B;
      }}
      .fb-mp.ozon {{ background: {OZON_ACCENT}; }}
      .fb-mp.wb {{ background: #7C3AED; }}
      .fb-num {{ text-align: right; font-weight: 600; white-space: nowrap; }}
      .fb-num.pos {{ color: var(--fb-pos); }}
      .fb-num.neg {{ color: var(--fb-neg); }}
      .fb-stack {{ display: flex; height: 22px; border-radius: 7px; background: var(--fb-soft); position: relative; }}
      .fb-stack > i {{ display: block; height: 100%; box-shadow: inset -1px 0 0 {SURFACE}; }}
      .fb-stack > i:first-child {{ border-radius: 7px 0 0 7px; }}
      .fb-stack > u {{ top: -3px; bottom: -3px; }}
      .fb-legend {{ display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: {MUTED}; }}
      .fb-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
      .fb-legend i {{ width: 10px; height: 10px; border-radius: 3px; }}

      .fb-insight {{ display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }}
      .fb-insight b {{ font-size: 15px; line-height: 1.35; font-weight: 600; }}
      .fb-insight p {{ margin: 0; font-size: 13px; color: {MUTED}; }}

      /* Pills / status */
      .fb-pill {{
        display: inline-block; padding: 4px 10px; border-radius: 12px;
        font-size: 12px; font-weight: 600;
        background: rgba(79,70,229,0.12); color: {ACCENT_TEXT}; border: 1px solid rgba(79,70,229,0.25);
      }}
      .fb-pill-ozon {{ background: rgba(0,91,255,0.14); color: color-mix(in srgb, {OZON_ACCENT} 70%, currentColor); border-color: rgba(0,91,255,0.3); }}
      .fb-pill-ok   {{ background: rgba(16,185,129,0.12); color: {SUCCESS};     border-color: rgba(16,185,129,0.25); }}
      .fb-pill-err  {{ background: rgba(239,68,68,0.12);  color: {DANGER};      border-color: rgba(239,68,68,0.25); }}
      .fb-status {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }}

      /* Tree table: P&L lines that open into their accrual types */
      .fb-tree {{
        --fb-tree-label: 260px;
        overflow-x: auto; border: 1px solid {LINE}; border-radius: 16px; font-size: 14px;
        background: {SURFACE}; box-shadow: {SHADOW};
      }}
      @media (max-width: 640px) {{ .fb-tree {{ --fb-tree-label: 170px; font-size: 13px; }} }}
      .fb-tree details > summary {{ list-style: none; cursor: pointer; }}
      .fb-tree details > summary::-webkit-details-marker {{ display: none; }}
      .fb-tree details > summary::marker {{ content: ""; }}
      .fb-tree-row {{
        display: grid; grid-template-columns: var(--fb-tree-cols); align-items: center;
        border-bottom: 1px solid {LINE}; min-height: 40px;
      }}
      .fb-tree-row > div {{ padding: 7px 14px; }}
      .fb-tree-row > .num {{ text-align: right; white-space: nowrap; }}
      .fb-tree-note {{ display: block; font-size: 12px; color: {MUTED}; line-height: 1.2; }}
      .fb-tree-head {{ background: {CARD}; color: {MUTED}; font-size: 13px; font-weight: 500; }}
      .fb-tree summary.fb-tree-row:hover {{ background: {HOVER}; }}
      .fb-tree-row.strong {{ font-weight: 600; background: {CARD}; }}
      .fb-tree-row.sub {{ color: {MUTED}; font-size: 13px; }}
      .fb-tree-label {{ display: flex; align-items: center; gap: 6px; min-width: 0; overflow-wrap: break-word; }}
      .fb-tree-caret {{
        width: 14px; height: 14px; display: inline-flex; align-items: center; justify-content: center;
        flex: none; color: {MUTED}; transition: transform .15s;
      }}
      .fb-tree summary .fb-tree-caret::before {{
        content: ""; width: 6px; height: 6px; margin-left: -2px;
        border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(-45deg);
      }}
      .fb-tree details[open] > summary .fb-tree-caret {{ transform: rotate(90deg); }}
      .fb-status-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
      .fb-status-dot.ok  {{ background: {SUCCESS}; box-shadow: 0 0 8px {SUCCESS}; }}
      .fb-status-dot.err {{ background: {DANGER}; }}
      .fb-status-dot.off {{ background: {WARN}; }}
    </style>
    """)


def card(parent=st):
    """Framed block on the card layer (white in the light theme, a raised step in the dark one)."""
    n = st.session_state["_fb_cards"] = st.session_state.get("_fb_cards", 0) + 1
    return parent.container(border=True, key=f"fbcard{n}")


def brand_block():
    """Sidebar brand header — call inside st.sidebar."""
    st.markdown(
        '<div class="fb-brand">'
        '<div class="fb-brand-dot"></div>'
        '<div class="fb-brand-name">FINBOARD</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def tree_table(columns: list[str], rows: list[dict], label_title: str = "Показатель"):
    """Table whose rows open into nested rows (без JS: <details>).
    row = {"label": str, "values": [str | (str, note) per column], "children": [row, ...], "strong": bool};
    a note is drawn small under the value."""
    def cell(v) -> str:
        main, note = v if isinstance(v, tuple) else (v, "")
        note = f'<span class="fb-tree-note">{escape(note)}</span>' if note else ""
        return f'<div class="num">{escape(str(main))}{note}</div>'

    def render(r: dict, level: int) -> str:
        kids = r.get("children") or []
        cls = "fb-tree-row" + (" strong" if r.get("strong") else "") + (" sub" if level > 1 else "")
        caret = '<span class="fb-tree-caret"></span>'
        cells = "".join(cell(v) for v in r["values"])
        label = (f'<div class="fb-tree-label" style="padding-left:{12 + 20 * level}px">'
                 f'{caret}<span>{escape(r["label"])}</span></div>')
        if not kids:
            return f'<div class="{cls}">{label}{cells}</div>'
        inner = "".join(render(k, level + 1) for k in kids)
        return f'<details><summary class="{cls}">{label}{cells}</summary>{inner}</details>'

    head = "".join(f'<div class="num">{escape(c)}</div>' for c in columns)
    cols = f"minmax(var(--fb-tree-label), 2fr) repeat({len(columns)}, minmax(110px, 1fr))"
    body = "".join(render(r, 0) for r in rows)
    width = f"calc(var(--fb-tree-label) + {110 * len(columns)}px)"
    st.html(f'<div class="fb-tree" style="--fb-tree-cols:{cols}"><div style="min-width:{width}">'
            f'<div class="fb-tree-row fb-tree-head"><div>{escape(label_title)}</div>{head}</div>'
            f'{body}</div></div>')


def status_dot(ok: bool, label: str) -> str:
    cls = "ok" if ok else "err"
    return f'<span class="fb-status"><span class="fb-status-dot {cls}"></span>{label}</span>'


def sparkline(values, color=WB_ACCENT, height: int = 40):
    """Render a tiny sparkline chart suitable for KPI cards."""
    import plotly.graph_objects as go
    fig = go.Figure(go.Scatter(
        y=list(values), mode="lines",
        line=dict(color=color, width=2, shape="spline"),
        fill="tozeroy",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.12)",
        hoverinfo="skip",
    ))
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
        showlegend=False,
    )
    return fig


def kpi_card(label: str, value: str, delta: str = "", delta_color: str = "muted",
             trend: list | None = None, accent: str = WB_ACCENT, arrow: str | None = None):
    """KPI card with optional sparkline trend. delta_color: 'up' (green), 'down' (red), 'muted'.
    arrow: '▲ ' / '▼ ' when the direction differs from the colour (ДРР going down is good)."""
    if arrow is None:
        arrow = {"up": "▲ ", "down": "▼ "}.get(delta_color, "") if delta else ""
    spark = ""
    vals = [float(v) for v in trend or [] if v == v]          # NaN != NaN
    if len(vals) > 1:
        lo, hi = min(vals), max(vals)
        pts = " ".join(f"{i / (len(vals) - 1) * 120:.1f},{28 - (v - lo) / ((hi - lo) or 1) * 26:.1f}"
                       for i, v in enumerate(vals))
        # inside the card, as on the mockup; the line keeps its width whatever the card's width
        spark = (f'<svg class="fb-spark" viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true">'
                 f'<polyline points="{pts}" fill="none" stroke="{accent}" stroke-width="1.6" '
                 f'vector-effect="non-scaling-stroke"/></svg>')
    elif trend is not None:                                   # same height as its neighbours with a line
        spark = '<div class="fb-spark"></div>'
    st.markdown(f"""
    <div class="fb-kpi">
      <div class="fb-kpi-label" title="{escape(label)}">{label}</div>
      <div class="fb-kpi-value">{value}</div>
      <div class="fb-kpi-delta {delta_color}" title="{escape(delta)}">{arrow}{delta}&nbsp;</div>
      {spark}
    </div>
    """, unsafe_allow_html=True)
