"""Finboard — Streamlit entry point.

Owner: all pages. Share link (?share=token): read-only result pages for the
cabinets the link allows.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from core.db import DatabaseUnavailable, init_db, is_sqlite
from core import config
from dashboard.common import logout, remember_login, require_access
from dashboard.nav import PAGES
from dashboard.theme import brand_block, inject_css, theme_toggle_sidebar
from dashboard.views import (
    access as access_view, ads, cabinets, cogs, fixed, pnl_months, products, summary, tools, uploads,
)

st.set_page_config(page_title="Finboard — финансы маркетплейсов", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")


@st.cache_resource
def _boot():
    """Once per server process: tables and the daily sync at SYNC_HOUR MSK."""
    init_db()
    from apscheduler.schedulers.background import BackgroundScheduler
    from sync.runner import sync_all
    sched = BackgroundScheduler(timezone=config.TIMEZONE)
    sched.add_job(sync_all, "cron", hour=config.SYNC_HOUR, minute=0, id="daily_sync",
                  max_instances=1, coalesce=True, misfire_grace_time=3600)
    sched.start()
    return sched


try:
    _boot()
except DatabaseUnavailable as e:
    st.error("База данных недоступна. Проверьте переменную DATABASE_URL в панели и что PostgreSQL запущен. "
             "Без SSL-параметров: база доступна только во внутренней сети.")
    st.caption(str(e)[:500])
    st.stop()

inject_css()
acc = require_access()
st.session_state["access"] = acc
remember_login()

with st.sidebar:
    brand_block()
    if acc.owner and is_sqlite():
        st.caption("⚠️ Локальная база SQLite (DATABASE_URL не задан)")
    if not acc.owner:
        st.caption(f"Просмотр по ссылке{': ' + acc.label if acc.label else ''}")
    elif config.OWNER_PASSWORD and st.button("Выйти", key="logout"):
        logout()
        st.info("Вы вышли. Обновите страницу, чтобы войти снова.")
        st.stop()
theme_toggle_sidebar()

PAGES.clear()


def _page(fn, **kw):
    """st.Page that other reports can open by its url_path (dashboard.nav.go)."""
    PAGES[kw["url_path"]] = p = st.Page(fn, **kw)
    return p


pages = {
    "Отчёты": [
        _page(summary.render, title="Финансовый результат", icon=":material/monitoring:",
              url_path="summary", default=True),
        _page(pnl_months.render, title="ОПиУ по месяцам", icon=":material/table_chart:", url_path="pnl"),
        _page(products.render, title="Товары", icon=":material/inventory_2:", url_path="products"),
        _page(ads.render, title="Реклама", icon=":material/campaign:", url_path="ads"),
    ],
}
if acc.owner:
    pages["Данные"] = [
        _page(cogs.render, title="Себестоимость", icon=":material/sell:", url_path="cogs"),
        _page(fixed.render, title="Постоянные расходы", icon=":material/receipt_long:", url_path="fixed"),
        _page(cabinets.render, title="Кабинеты и налоги", icon=":material/storefront:", url_path="cabinets"),
        _page(uploads.render, title="Загрузка отчётов", icon=":material/upload_file:", url_path="uploads"),
        _page(access_view.render, title="Доступ по ссылке", icon=":material/share:", url_path="access"),
    ]
    pages["Доп. инструменты"] = [
        _page(tools.render, title="Инструменты", icon=":material/construction:", url_path="tools"),
    ]

st.navigation(pages, position="sidebar").run()
