"""Finboard — Streamlit multi-page dashboard entry point.

Navigation between pages is handled by st.navigation (Streamlit 1.36+).
Each view module exposes a `render()` function called by st.Page.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from database.db import init_db
from dashboard.theme import inject_css, brand_block, theme_toggle_sidebar
from dashboard.views import overview, analytics, upload, settings as settings_view


st.set_page_config(
    page_title="Finboard — Маркетплейс Аналитика",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()
inject_css()

with st.sidebar:
    brand_block()
theme_toggle_sidebar()

# ── Multi-page navigation ─────────────────────────────────────────────────────

pages = [
    st.Page(overview.render,       title="Обзор",           icon="📊", default=True),
    st.Page(analytics.render,      title="Аналитика",       icon="📈"),
    st.Page(upload.render,         title="Загрузка данных", icon="📥"),
    st.Page(settings_view.render,  title="Настройки",       icon="⚙"),
]

nav = st.navigation(pages, position="sidebar")
nav.run()
