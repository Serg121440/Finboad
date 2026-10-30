"""Finboard design system — colors, CSS, custom components.

Light and dark themes are Streamlit's own (.streamlit/config.toml): the app follows
the device and the user switches in the ⋮ menu.
"""

import streamlit as st

# Page, sidebar, text, inputs and menus come from Streamlit's own light/dark theme
# (.streamlit/config.toml). Our CSS never names a background or text colour: cards and
# borders are tints of the current text colour, so they follow a theme switch in the
# ⋮ menu instantly, without a rerun.
CARD = "color-mix(in srgb, currentColor 4%, transparent)"
BORDER = "color-mix(in srgb, currentColor 14%, transparent)"
MUTED = "color-mix(in srgb, currentColor 62%, transparent)"
HOVER = "rgba(139,92,246,0.08)"
ACCENT_BG = "rgba(139,92,246,0.14)"

# Brand accents (одинаковы в обеих темах)
WB_ACCENT   = "#8B5CF6"
OZON_ACCENT = "#F59E0B"
SUCCESS     = "#10B981"
DANGER      = "#EF4444"
INFO        = "#3B82F6"

MP_COLORS = {"wb": WB_ACCENT, "ozon": OZON_ACCENT, "other": "#94A3B8"}
MP_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "other": "Прочие"}

PLOTLY_PALETTE = [WB_ACCENT, OZON_ACCENT, SUCCESS, INFO, DANGER, "#EC4899", "#14B8A6", "#A855F7"]

def theme_toggle_sidebar():
    with st.sidebar:
        st.caption("Тема следует за устройством (день/ночь); переключить — меню ⋮ справа сверху → "
                   "Light / Dark / System.")


def plotly_layout() -> dict:
    grid = "rgba(148,163,184,0.25)"
    return dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, -apple-system, sans-serif", color="#94A3B8", size=12),
        xaxis=dict(gridcolor=grid, zerolinecolor=grid, linecolor=grid),
        yaxis=dict(gridcolor=grid, zerolinecolor=grid, linecolor=grid),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=40, b=10),
    )


def apply_plotly_theme(fig):
    """Apply Finboard theme to a Plotly figure."""
    fig.update_layout(**plotly_layout())
    return fig


def inject_css():
    """Global CSS; colours that differ between themes are left to Streamlit."""
    st.html(f"""
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      html, body, [class*="css"], .stApp {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
      }}

      /* Headings */
      h1, h2, h3, h4 {{ letter-spacing: -0.01em; font-weight: 700 !important; }}
      h1 {{ font-size: 28px !important; }}
      h2 {{ font-size: 20px !important; }}
      h3 {{ font-size: 16px !important; color: {MUTED} !important; font-weight: 600 !important; }}

      /* Metric cards */
      div[data-testid="stMetric"] {{
        background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px 18px;
        transition: border-color 0.2s;
      }}
      div[data-testid="stMetric"]:hover {{ border-color: {WB_ACCENT}; }}
      div[data-testid="stMetricLabel"] p {{
        color: {MUTED} !important; font-size: 10px !important; font-weight: 600 !important;
        text-transform: uppercase; letter-spacing: 0.6px;
      }}
      div[data-testid="stMetricValue"] {{
        font-size: 22px !important; font-weight: 700 !important; font-variant-numeric: tabular-nums;
      }}

      /* Buttons */
      .stButton > button, .stDownloadButton > button {{ border-radius: 8px; font-weight: 500; }}
      .stButton > button:hover, .stDownloadButton > button:hover {{ border-color: {WB_ACCENT}; }}

      /* Expanders, uploader, tables */
      details[data-testid="stExpander"] {{ border-radius: 10px !important; }}
      [data-testid="stFileUploader"] section {{ border: 1px dashed {BORDER}; border-radius: 10px; }}
      .stDataFrame, [data-testid="stTable"] {{ border-radius: 10px; }}

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] {{
        gap: 4px; background: {CARD}; border-radius: 10px; padding: 4px; border: 1px solid {BORDER};
      }}
      .stTabs [data-baseweb="tab"] {{
        background: transparent; color: {MUTED}; border-radius: 8px; padding: 8px 16px; font-weight: 500;
      }}
      .stTabs [aria-selected="true"] {{ background: {ACCENT_BG} !important; color: {WB_ACCENT} !important; }}

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
        background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 16px 18px;
        min-height: 90px; transition: border-color .2s;
      }}
      .fb-kpi:hover {{ border-color: {WB_ACCENT}; }}
      .fb-kpi-label {{
        font-size: 10px; color: {MUTED}; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.6px; margin-bottom: 8px;
      }}
      .fb-kpi-value {{ font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }}
      .fb-kpi-delta {{ font-size: 11px; font-weight: 600; margin-top: 4px; color: {MUTED}; }}
      .fb-kpi-delta.up {{ color: {SUCCESS}; }}
      .fb-kpi-delta.down {{ color: {DANGER}; }}

      /* Pills / status */
      .fb-pill {{
        display: inline-block; padding: 4px 10px; border-radius: 12px;
        font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
        background: rgba(139,92,246,0.12); color: {WB_ACCENT}; border: 1px solid rgba(139,92,246,0.25);
      }}
      .fb-pill-ozon {{ background: rgba(245,158,11,0.12); color: {OZON_ACCENT}; border-color: rgba(245,158,11,0.25); }}
      .fb-pill-ok   {{ background: rgba(16,185,129,0.12); color: {SUCCESS};     border-color: rgba(16,185,129,0.25); }}
      .fb-pill-err  {{ background: rgba(239,68,68,0.12);  color: {DANGER};      border-color: rgba(239,68,68,0.25); }}
      .fb-status {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }}

      /* Tree table: P&L lines that open into their accrual types */
      .fb-tree {{
        --fb-tree-label: 260px;
        overflow-x: auto; border: 1px solid {BORDER}; border-radius: 10px; font-size: 14px;
      }}
      @media (max-width: 640px) {{ .fb-tree {{ --fb-tree-label: 170px; font-size: 13px; }} }}
      .fb-tree details > summary {{ list-style: none; cursor: pointer; }}
      .fb-tree details > summary::-webkit-details-marker {{ display: none; }}
      .fb-tree details > summary::marker {{ content: ""; }}
      .fb-tree-row {{
        display: grid; grid-template-columns: var(--fb-tree-cols); align-items: center;
        border-bottom: 1px solid {BORDER}; min-height: 36px;
      }}
      .fb-tree-row > div {{ padding: 6px 12px; }}
      .fb-tree-row > .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
      .fb-tree-head {{ background: {CARD}; color: {MUTED}; font-size: 13px; }}
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
    </style>
    """)


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
    row = {"label": str, "values": [str per column], "children": [row, ...], "strong": bool}."""
    from html import escape

    def render(r: dict, level: int) -> str:
        kids = r.get("children") or []
        cls = "fb-tree-row" + (" strong" if r.get("strong") else "") + (" sub" if level > 1 else "")
        caret = '<span class="fb-tree-caret"></span>'
        cells = "".join(f'<div class="num">{escape(str(v))}</div>' for v in r["values"])
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
             trend: list | None = None, accent: str = WB_ACCENT):
    """KPI card with optional sparkline trend. delta_color: 'up' (green), 'down' (red), 'muted'."""
    arrow = {"up": "▲ ", "down": "▼ "}.get(delta_color, "") if delta else ""
    st.markdown(f"""
    <div class="fb-kpi">
      <div class="fb-kpi-label">{label}</div>
      <div class="fb-kpi-value">{value}</div>
      <div class="fb-kpi-delta {delta_color}">{arrow}{delta}&nbsp;</div>
    </div>
    """, unsafe_allow_html=True)

    if trend and len(trend) > 1:
        st.plotly_chart(sparkline(trend, color=accent, height=36),
                        use_container_width=True, config={"displayModeBar": False},
                        key=f"spark_{label.replace(' ', '_').replace('(', '').replace(')', '')}")
