"""Upload page — card-style grid layout matching the design mockup."""

import pandas as pd
import streamlit as st
from datetime import date

from analytics.metrics import load_data, load_cogs
from dashboard.shared import rub, num, render_sync_log_sidebar
from dashboard.theme import status_dot


def _last_sync_status(marketplace: str) -> tuple[bool | None, str]:
    """Return (ok, label) for the latest sync entry of given marketplace."""
    from sqlalchemy import text as sqlt
    from database.db import engine
    try:
        with engine.connect() as conn:
            row = conn.execute(sqlt(
                "SELECT status, sync_at, records_count FROM sync_log "
                "WHERE marketplace = :mp ORDER BY sync_at DESC LIMIT 1"
            ), {"mp": marketplace}).fetchone()
        if not row:
            return None, "ещё не загружалось"
        status, dt, n = row[0], str(row[1])[:16], int(row[2] or 0)
        ok = status == "ok"
        return ok, f"{dt} · {num(n)} зап." if ok else f"{dt} · ошибка"
    except Exception:
        return None, ""


def _status_line(marketplace: str):
    ok, label = _last_sync_status(marketplace)
    if ok is None:
        st.caption(f"○ {label}")
    elif ok:
        st.markdown(status_dot(True, label), unsafe_allow_html=True)
    else:
        st.markdown(status_dot(False, label), unsafe_allow_html=True)


def _wb_sales_card():
    with st.container(border=True):
        st.markdown("##### 🟣 Отчёт WB — реализация")
        st.caption("ЛК WB → Аналитика → Финансы → Отчёт о реализации")
        files = st.file_uploader("xlsx-файлы", type=["xlsx"],
                                 accept_multiple_files=True, key="wb_sales",
                                 label_visibility="collapsed")
        _status_line("wb")
        if files and st.button("Загрузить", key="btn_wb_sales", type="primary",
                               use_container_width=True):
            from connectors.wb_excel_parser import parse_wb_excel
            from database.db import upsert_records, log_sync
            total = 0
            for f in files:
                try:
                    with st.spinner(f"{f.name}…"):
                        records, stats = parse_wb_excel(f)
                        upsert_records(records)
                        total += len(records)
                    log_sync("wb", "ok", len(records), filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("revenue", 0))
                    st.success(f"{f.name}: {num(len(records))} записей · {rub(stats['revenue'])}")
                except Exception as e:
                    log_sync("wb", "error", error=str(e), filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                load_data.clear()
                load_cogs.clear()
                st.rerun()


def _ozon_sales_card():
    with st.container(border=True):
        st.markdown("##### 🟠 Отчёт Ozon — начисления")
        st.caption("ЛК Ozon → Финансы → Начисления (xlsx, 25 колонок)")
        files = st.file_uploader("xlsx-файлы", type=["xlsx"],
                                 accept_multiple_files=True, key="ozon_sales",
                                 label_visibility="collapsed")
        _status_line("ozon")
        if files and st.button("Загрузить", key="btn_ozon_sales", type="primary",
                               use_container_width=True):
            from connectors.ozon_excel_parser import parse_ozon_excel
            from database.db import upsert_records, log_sync
            total = 0
            for f in files:
                try:
                    with st.spinner(f"{f.name}…"):
                        records, stats = parse_ozon_excel(f)
                        upsert_records(records)
                        total += len(records)
                    log_sync("ozon", "ok", len(records), filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("revenue", 0))
                    st.success(f"{f.name}: {num(len(records))} записей · {rub(stats['revenue'])}")
                except Exception as e:
                    log_sync("ozon", "error", error=str(e), filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                load_data.clear()
                load_cogs.clear()
                st.rerun()


def _cogs_card():
    with st.container(border=True):
        st.markdown("##### 💰 Себестоимость (COGS)")
        from connectors.cogs_parser import generate_cogs_template, parse_cogs_excel
        from database.db import upsert_cogs, engine
        from sqlalchemy import text as sqlt

        try:
            with engine.connect() as conn:
                existing = pd.read_sql_query(
                    sqlt("SELECT sku, product_name, cost_per_unit FROM cost_of_goods"),
                    conn,
                ).to_dict("records")
                if not existing:
                    sales_skus = pd.read_sql_query(
                        sqlt("SELECT DISTINCT sku, article, product_name FROM sales "
                             "ORDER BY product_name"), conn,
                    ).to_dict("records")
                    existing = [{
                        "sku": r["article"] if r.get("article") else r["sku"],
                        "product_name": r["product_name"],
                        "cost_per_unit": 0,
                    } for r in sales_skus]
        except Exception:
            existing = []

        n_existing = len([e for e in existing if e.get("cost_per_unit", 0) > 0])
        if n_existing:
            st.markdown(status_dot(True, f"{n_existing} SKU с себестоимостью"),
                        unsafe_allow_html=True)
        else:
            st.caption("○ не задана")

        tmpl_bytes = generate_cogs_template(existing or None)
        st.download_button(
            "⬇ Скачать шаблон", data=tmpl_bytes,
            file_name="cogs_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_cogs", use_container_width=True,
        )
        cogs_file = st.file_uploader("Заполненный шаблон", type=["xlsx"],
                                     key="cogs_upload",
                                     label_visibility="collapsed")
        if cogs_file and st.button("Сохранить", key="btn_cogs", type="primary",
                                   use_container_width=True):
            try:
                records, n = parse_cogs_excel(cogs_file)
                upsert_cogs(records)
                st.success(f"Сохранено {n} SKU")
                load_cogs.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))


def _wb_ads_card():
    with st.container(border=True):
        st.markdown("##### 📢 Реклама WB")
        st.caption("ЛК WB → Реклама → История затрат")
        files = st.file_uploader("xlsx-файлы", type=["xlsx"],
                                 accept_multiple_files=True, key="wb_ads",
                                 label_visibility="collapsed")
        method = st.radio("Распределение",
                          ["Пропорционально выручке", "Без привязки к SKU"],
                          key="ads_method", horizontal=False)
        _status_line("wb_ads")
        if files and st.button("Загрузить", key="btn_wb_ads", type="primary",
                               use_container_width=True):
            from connectors.wb_ads_parser import (
                parse_wb_ads_excel, distribute_ad_spend_by_revenue,
            )
            from database.db import insert_ad_spend, log_sync
            total = 0
            for f in files:
                try:
                    with st.spinner(f"{f.name}…"):
                        records, stats = parse_wb_ads_excel(f)
                        if method == "Пропорционально выручке":
                            records = distribute_ad_spend_by_revenue(
                                records, load_data())
                        n = insert_ad_spend(records)
                        total += n
                    log_sync("wb_ads", "ok", n, filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("total_spend", 0))
                    st.success(f"{f.name}: {num(stats['campaigns'])} кампаний · {rub(stats['total_spend'])}")
                except Exception as e:
                    log_sync("wb_ads", "error", error=str(e), filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                load_data.clear()
                st.rerun()


def _ozon_ads_card():
    with st.container(border=True):
        st.markdown("##### 📣 Реклама Ozon")
        st.caption("ЛК Ozon → Продвижение → Статистика")
        files = st.file_uploader("xlsx-файлы", type=["xlsx"],
                                 accept_multiple_files=True, key="ozon_ads",
                                 label_visibility="collapsed")
        ds = st.date_input("Дата начала периода",
                           value=date.today().replace(day=1),
                           key="ozon_ads_date")
        _status_line("ozon_ads")
        if files and st.button("Загрузить", key="btn_ozon_ads", type="primary",
                               use_container_width=True):
            from connectors.ozon_ads_parser import parse_ozon_ads_excel
            from database.db import insert_ad_spend, log_sync
            total = 0
            for f in files:
                try:
                    with st.spinner(f"{f.name}…"):
                        records, stats = parse_ozon_ads_excel(f, ds)
                        n = insert_ad_spend(records)
                        total += n
                    log_sync("ozon_ads", "ok", n, filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("total_spend", 0))
                    st.success(f"{f.name}: {num(stats['campaigns'])} кампаний · {rub(stats['total_spend'])}")
                except Exception as e:
                    log_sync("ozon_ads", "error", error=str(e),
                             filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                load_data.clear()
                st.rerun()


def render():
    render_sync_log_sidebar()

    st.title("Загрузка данных")
    st.caption("Карточки источников — нажми «Загрузить» в нужной, файлы можно перезаливать.")

    # Row 1: sales reports + COGS
    c1, c2, c3 = st.columns(3)
    with c1: _wb_sales_card()
    with c2: _ozon_sales_card()
    with c3: _cogs_card()

    # Row 2: ads
    c4, c5, _ = st.columns(3)
    with c4: _wb_ads_card()
    with c5: _ozon_ads_card()
