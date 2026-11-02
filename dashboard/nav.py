"""Pages by url_path (filled in app.py), so a report can open another one already filtered."""

import streamlit as st

PAGES: dict = {}


def go(url_path: str, **state) -> None:
    """Open a page with session values set first (e.g. a products quick filter)."""
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[url_path])


def can_go(url_path: str) -> bool:
    return url_path in PAGES
