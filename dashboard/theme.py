"""Finboard design system — colors, CSS, custom components.

Theme auto-switches between dark and light based on Moscow time:
- 08:00–19:59 MSK → light
- 20:00–07:59 MSK → dark

Users can override via the sidebar toggle (stored in session_state).
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

# ── Palettes ──────────────────────────────────────────────────────────────────

DARK = {
    "bg":         "#0B0E14",
    "card":       "#151A26",
    "sidebar":    "#0D111C",
    "border":     "#1E2435",
    "text":       "#E6EDF3",
    "muted":      "#8B949E",
    "hover_bg":   "rgba(139,92,246,0.08)",
    "accent_bg":  "rgba(139,92,246,0.15)",
}

LIGHT = {
    "bg":         "#F8FAFC",
    "card":       "#FFFFFF",
    "sidebar":    "#F1F4F9",
    "border":     "#E2E8F0",
    "text":       "#0F172A",
    "muted":      "#64748B",
    "hover_bg":   "rgba(139,92,246,0.06)",
    "accent_bg":  "rgba(139,92,246,0.12)",
}

# Brand accents (одинаковы в обеих темах)
WB_ACCENT   = "#8B5CF6"
OZON_ACCENT = "#F59E0B"
SUCCESS     = "#10B981"
DANGER      = "#EF4444"
INFO        = "#3B82F6"

MP_COLORS = {"wb": WB_ACCENT, "ozon": OZON_ACCENT, "other": "#94A3B8"}
MP_LABELS = {"wb": "Wildberries", "ozon": "Ozon", "other": "Прочие"}

PLOTLY_PALETTE = [WB_ACCENT, OZON_ACCENT, SUCCESS, INFO, DANGER, "#EC4899", "#14B8A6", "#A855F7"]

_MSK = timezone(timedelta(hours=3))


def auto_mode() -> str:
    """Return 'dark' or 'light' based on Moscow time."""
    h = datetime.now(_MSK).hour
    return "light" if 8 <= h < 20 else "dark"


def current_mode() -> str:
    """Return active mode (session override or time-based auto)."""
    override = st.session_state.get("theme_override")
    if override in ("dark", "light"):
        return override
    return auto_mode()


def palette() -> dict:
    return DARK if current_mode() == "dark" else LIGHT


def theme_toggle_sidebar():
    """Render a small mode toggle in the sidebar."""
    auto = auto_mode()
    current = current_mode()
    label = "🌙 Тёмная" if current == "dark" else "☀ Светлая"
    hint = f"Авто: {('тёмная' if auto == 'dark' else 'светлая')} (МСК)"

    with st.sidebar:
        col1, col2 = st.columns([3, 1])
        col1.caption(f"Тема: **{label}** · {hint}")
        if col2.button("⇄", key="theme_toggle", help="Переключить тёмную/светлую"):
            st.session_state["theme_override"] = "light" if current == "dark" else "dark"
            st.rerun()


def plotly_layout() -> dict:
    p = palette()
    return dict(
        paper_bgcolor=p["card"],
        plot_bgcolor=p["card"],
        font=dict(family="Inter, -apple-system, sans-serif", color=p["text"], size=12),
        xaxis=dict(gridcolor=p["border"], zerolinecolor=p["border"], linecolor=p["border"],
                   tickfont=dict(color=p["muted"])),
        yaxis=dict(gridcolor=p["border"], zerolinecolor=p["border"], linecolor=p["border"],
                   tickfont=dict(color=p["muted"])),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=p["text"])),
        margin=dict(l=10, r=10, t=40, b=10),
    )


def apply_plotly_theme(fig):
    """Apply Finboard theme to a Plotly figure."""
    fig.update_layout(**plotly_layout())
    return fig


def inject_css():
    """Inject global CSS into the Streamlit app (mode-aware)."""
    p = palette()
    is_dark = current_mode() == "dark"

    st.markdown(f"""
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      html, body, [class*="css"], .stApp {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
      }}
      .stApp {{ background: {p["bg"]} !important; color: {p["text"]} !important; }}

      /* Sidebar */
      section[data-testid="stSidebar"] {{
        background: {p["sidebar"]} !important;
        border-right: 1px solid {p["border"]};
      }}
      section[data-testid="stSidebar"] * {{ color: {p["text"]}; }}

      /* Headings */
      h1, h2, h3, h4 {{ color: {p["text"]} !important; letter-spacing: -0.01em; font-weight: 700 !important; }}
      h1 {{ font-size: 28px !important; }}
      h2 {{ font-size: 20px !important; }}
      h3 {{ font-size: 16px !important; color: {p["muted"]} !important; font-weight: 600 !important; }}

      p, div, span, label {{ color: {p["text"]}; }}

      /* Metric cards */
      div[data-testid="stMetric"] {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 12px;
        padding: 16px 18px;
        transition: border-color 0.2s;
      }}
      div[data-testid="stMetric"]:hover {{ border-color: {WB_ACCENT}; }}
      div[data-testid="stMetricLabel"] p {{
        color: {p["muted"]} !important;
        font-size: 10px !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.6px;
      }}
      div[data-testid="stMetricValue"] {{
        color: {p["text"]} !important;
        font-size: 22px !important;
        font-weight: 700 !important;
        font-variant-numeric: tabular-nums;
      }}
      div[data-testid="stMetricDelta"] {{ font-weight: 600 !important; }}

      /* Buttons */
      .stButton > button, .stDownloadButton > button {{
        background: {p["card"]};
        color: {p["text"]};
        border: 1px solid {p["border"]};
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s;
      }}
      .stButton > button:hover, .stDownloadButton > button:hover {{
        border-color: {WB_ACCENT};
        background: {p["hover_bg"]};
      }}
      .stButton > button[kind="primary"] {{
        background: {WB_ACCENT}; border-color: {WB_ACCENT}; color: white;
      }}

      /* Inputs */
      .stTextInput input, .stNumberInput input, .stDateInput input,
      .stSelectbox > div > div, .stMultiSelect > div > div {{
        background: {p["card"]} !important;
        border: 1px solid {p["border"]} !important;
        color: {p["text"]} !important;
      }}

      /* File uploader */
      [data-testid="stFileUploader"] section {{
        background: {p["card"]};
        border: 1px dashed {p["border"]};
        border-radius: 10px;
      }}
      [data-testid="stFileUploader"] section * {{ color: {p["text"]}; }}

      /* Expanders */
      details[data-testid="stExpander"] {{
        background: {p["card"]};
        border: 1px solid {p["border"]} !important;
        border-radius: 10px !important;
      }}
      details[data-testid="stExpander"] summary {{ color: {p["text"]} !important; }}

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        background: {p["card"]};
        border-radius: 10px;
        padding: 4px;
        border: 1px solid {p["border"]};
      }}
      .stTabs [data-baseweb="tab"] {{
        background: transparent;
        color: {p["muted"]};
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 500;
      }}
      .stTabs [aria-selected="true"] {{
        background: {p["accent_bg"]} !important;
        color: {WB_ACCENT} !important;
      }}

      /* Tables */
      .stDataFrame, [data-testid="stTable"] {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 10px;
      }}

      /* Dividers */
      hr {{ border-color: {p["border"]} !important; opacity: 0.6; }}

      /* Plotly chart container */
      .js-plotly-plot, .plotly {{
        background: {p["card"]} !important;
        border-radius: 12px;
        border: 1px solid {p["border"]};
      }}

      /* App padding */
      .block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px; }}

      /* Captions */
      .stCaption, small, [data-testid="stCaptionContainer"] {{ color: {p["muted"]} !important; }}

      /* Finboard brand */
      .fb-brand {{
        display: flex; align-items: center; gap: 10px;
        padding: 8px 4px 16px 4px;
        border-bottom: 1px solid {p["border"]};
        margin-bottom: 12px;
      }}
      .fb-brand-dot {{
        width: 16px; height: 16px;
        background: linear-gradient(135deg, {WB_ACCENT}, {INFO});
        border-radius: 4px;
      }}
      .fb-brand-name {{
        font-weight: 800; letter-spacing: 2px; font-size: 14px;
        color: {p["text"]};
      }}

      /* Pills / tags */
      .fb-pill {{
        display: inline-block; padding: 4px 10px; border-radius: 12px;
        font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
        background: rgba(139,92,246,0.12); color: {WB_ACCENT};
        border: 1px solid rgba(139,92,246,0.25);
      }}
      .fb-pill-ozon {{ background: rgba(245,158,11,0.12); color: {OZON_ACCENT}; border-color: rgba(245,158,11,0.25); }}
      .fb-pill-ok   {{ background: rgba(16,185,129,0.12); color: {SUCCESS};     border-color: rgba(16,185,129,0.25); }}
      .fb-pill-err  {{ background: rgba(239,68,68,0.12);  color: {DANGER};      border-color: rgba(239,68,68,0.25); }}

      .fb-status {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }}
      .fb-status-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
      .fb-status-dot.ok  {{ background: {SUCCESS}; box-shadow: 0 0 8px {SUCCESS}; }}
      .fb-status-dot.err {{ background: {DANGER}; }}
    </style>
    """, unsafe_allow_html=True)


def brand_block():
    """Sidebar brand header — call inside st.sidebar."""
    st.markdown(
        '<div class="fb-brand">'
        '<div class="fb-brand-dot"></div>'
        '<div class="fb-brand-name">FINBOARD</div>'
        '</div>',
        unsafe_allow_html=True,
    )


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
    """Render a KPI card with optional sparkline trend.

    delta_color: 'up' (green), 'down' (red), 'muted' (gray)
    """
    p = palette()
    color_map = {"up": SUCCESS, "down": DANGER, "muted": p["muted"]}
    delta_col = color_map.get(delta_color, p["muted"])

    arrow = ""
    if delta and delta_color == "up": arrow = "▲ "
    elif delta and delta_color == "down": arrow = "▼ "

    st.markdown(f"""
    <div style="
      background: {p['card']}; border: 1px solid {p['border']};
      border-radius: 12px; padding: 16px 18px; transition: border-color .2s;
      min-height: {110 if trend else 90}px;
    ">
      <div style="font-size:10px; color:{p['muted']}; font-weight:600;
                  text-transform:uppercase; letter-spacing:0.6px; margin-bottom:8px;">
        {label}
      </div>
      <div style="font-size:22px; color:{p['text']}; font-weight:700;
                  font-variant-numeric: tabular-nums; line-height:1.1;">
        {value}
      </div>
      <div style="font-size:11px; color:{delta_col}; font-weight:600; margin-top:4px;">
        {arrow}{delta}&nbsp;
      </div>
    </div>
    """, unsafe_allow_html=True)

    if trend and len(trend) > 1:
        st.plotly_chart(sparkline(trend, color=accent, height=36),
                        use_container_width=True, config={"displayModeBar": False})
