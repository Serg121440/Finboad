"""Shared sidebar (filters), formatters, and data loading for all views."""

import streamlit as st
import pandas as pd
from datetime import timedelta
from dataclasses import dataclass

from analytics.metrics import load_data, load_cogs, get_all_categories, get_date_range
from dashboard.theme import MP_LABELS


# ── Formatters ────────────────────────────────────────────────────────────────

def rub(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ") + " ₽"


def pct(v: float) -> str:
    return f"{v:.1f}%"


def qty(v) -> str:
    return f"{int(round(v)):,}".replace(",", " ") + " шт."


def num(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


# ── Context shared across pages ───────────────────────────────────────────────

@dataclass
class ViewContext:
    df: pd.DataFrame
    all_data: pd.DataFrame
    cogs_map: dict
    has_cogs: bool
    date_from: object
    date_to: object


def render_filters_and_load() -> ViewContext | None:
    """Render filter widgets in the sidebar and return the filtered dataframe.

    Returns None if there is no data yet (caller should show an empty state).
    """
    all_data = load_data()
    if all_data.empty:
        return None

    st.sidebar.divider()
    st.sidebar.subheader("Фильтры")

    min_date, max_date = get_date_range(all_data)
    default_from = max(min_date, max_date - timedelta(days=30))

    date_from = st.sidebar.date_input("С даты", value=default_from,
                                      min_value=min_date, max_value=max_date,
                                      key="flt_from")
    date_to = st.sidebar.date_input("По дату", value=max_date,
                                    min_value=min_date, max_value=max_date,
                                    key="flt_to")

    avail_mp = sorted(all_data["marketplace"].unique())
    mp_sel = st.sidebar.multiselect(
        "Маркетплейс",
        ["Все"] + [MP_LABELS.get(m, m) for m in avail_mp],
        default=["Все"], key="flt_mp",
    )
    mp_filter = None if "Все" in mp_sel or not mp_sel else [
        {v: k for k, v in MP_LABELS.items()}.get(m, m) for m in mp_sel
    ]

    cats = get_all_categories(all_data)
    if cats:
        cat_sel = st.sidebar.multiselect(
            "Категория", ["Все"] + cats, default=["Все"], key="flt_cat",
        )
        cat_filter = None if "Все" in cat_sel or not cat_sel else cat_sel
    else:
        cat_filter = None

    df = load_data(date_from=date_from, date_to=date_to,
                   marketplaces=tuple(mp_filter) if mp_filter else None,
                   categories=tuple(cat_filter) if cat_filter else None)
    cogs_map = load_cogs()

    return ViewContext(
        df=df, all_data=all_data,
        cogs_map=cogs_map, has_cogs=bool(cogs_map),
        date_from=date_from, date_to=date_to,
    )


def render_sync_log_sidebar():
    """Render compact upload history in the sidebar."""
    from sqlalchemy import text as sqlt
    from database.db import engine, delete_sync_log

    with st.sidebar:
        st.divider()
        with st.expander("📋 История загрузок", expanded=False):
            try:
                with engine.connect() as conn:
                    logs = pd.read_sql_query(
                        sqlt("SELECT id, marketplace, sync_at, status, records_count, "
                             "filename, date_from, date_to, revenue FROM sync_log "
                             "ORDER BY sync_at DESC LIMIT 30"),
                        conn,
                    )
                if logs.empty:
                    st.caption("Загрузок пока нет")
                    return

                MP_ICON = {"wb": "🟣", "wb_ads": "📢", "ozon": "🟠",
                           "ozon_ads": "📣", "other": "⚪"}
                for _, row in logs.iterrows():
                    status_icon = "✅" if row["status"] == "ok" else "❌"
                    mp_icon = MP_ICON.get(str(row["marketplace"]), "⚪")
                    fname = str(row.get("filename") or "").strip()
                    d_from = str(row.get("date_from") or "")[:10]
                    d_to = str(row.get("date_to") or "")[:10]
                    rev = row.get("revenue") or 0
                    dt = str(row["sync_at"])[:16]
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        period = f"{d_from} — {d_to}" if d_from else dt
                        label = fname if fname else MP_LABELS.get(
                            str(row["marketplace"]), str(row["marketplace"]))
                        st.caption(
                            f"{status_icon} {mp_icon} **{label}**  \n"
                            f"{period}  \n"
                            f"{num(row['records_count'])} зап."
                            + (f" | {rub(rev)}" if rev else "")
                        )
                    with col2:
                        if st.button("🗑", key=f"del_log_{row['id']}",
                                     help="Удалить запись из истории"):
                            delete_sync_log(int(row["id"]))
                            st.rerun()
            except Exception:
                pass
