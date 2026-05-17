"""Upload page — WB / Ozon reports, ads, COGS templates."""

import pandas as pd
import streamlit as st
from datetime import date

from analytics.metrics import load_data
from dashboard.shared import rub, num, render_sync_log_sidebar


def render():
    render_sync_log_sidebar()

    st.title("Загрузка данных")
    st.caption("Загрузи отчёты маркетплейсов, рекламы и себестоимости. Файлы можно перезаливать — данные будут обновлены.")

    tab_wb, tab_ozon, tab_ads, tab_cogs = st.tabs([
        "📦 Отчёты WB", "📦 Отчёты Ozon", "📢 Реклама", "💰 Себестоимость"
    ])

    # ── WB ────────────────────────────────────────────────────────────────────
    with tab_wb:
        st.subheader("Отчёт о реализации WB")
        st.caption("ЛК WB → Аналитика → Финансы → Отчёт о реализации → Скачать xlsx")
        wb_files = st.file_uploader(
            "Выбери .xlsx файлы (можно несколько)",
            type=["xlsx"], accept_multiple_files=True, key="wb_sales",
        )
        if wb_files and st.button("Загрузить отчёт WB", key="btn_wb_sales", type="primary"):
            from connectors.wb_excel_parser import parse_wb_excel
            from database.db import upsert_records, log_sync
            total = 0
            for f in wb_files:
                try:
                    with st.spinner(f"Обрабатываю {f.name}…"):
                        records, stats = parse_wb_excel(f)
                        upsert_records(records)
                        total += len(records)
                    log_sync("wb", "ok", len(records), filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("revenue", 0))
                    st.success(
                        f"**{f.name}**  \n"
                        f"{num(stats['total_rows'])} строк → {num(len(records))} записей "
                        f"| {num(stats['skus'])} SKU  \n"
                        f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                        f"Выручка: **{rub(stats['revenue'])}** | "
                        f"К перечислению: **{rub(stats['net_profit'])}**"
                    )
                except Exception as e:
                    log_sync("wb", "error", error=str(e), filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                st.rerun()

    # ── Ozon ──────────────────────────────────────────────────────────────────
    with tab_ozon:
        st.subheader("Отчёт начислений Ozon")
        st.caption("ЛК Ozon → Финансы → Начисления → Скачать xlsx (широкий формат, 25 колонок)")
        ozon_files = st.file_uploader(
            "Выбери .xlsx файлы",
            type=["xlsx"], accept_multiple_files=True, key="ozon_sales",
        )
        if ozon_files and st.button("Загрузить отчёт Ozon", key="btn_ozon_sales", type="primary"):
            from connectors.ozon_excel_parser import parse_ozon_excel
            from database.db import upsert_records, log_sync
            total = 0
            for f in ozon_files:
                try:
                    with st.spinner(f"Обрабатываю {f.name}…"):
                        records, stats = parse_ozon_excel(f)
                        upsert_records(records)
                        total += len(records)
                    log_sync("ozon", "ok", len(records), filename=f.name,
                             date_from=stats.get("date_from"),
                             date_to=stats.get("date_to"),
                             revenue=stats.get("revenue", 0))
                    st.success(
                        f"**{f.name}**  \n"
                        f"{num(stats['total_rows'])} строк → {num(len(records))} записей "
                        f"| {num(stats['skus'])} SKU  \n"
                        f"Период: {stats['date_from']} — {stats['date_to']}  \n"
                        f"Выручка: **{rub(stats['revenue'])}** | "
                        f"К перечислению: **{rub(stats['net_profit'])}**"
                    )
                except Exception as e:
                    log_sync("ozon", "error", error=str(e), filename=f.name)
                    st.error(f"{f.name}: {e}")
            if total:
                st.rerun()

    # ── Ads (WB + Ozon) ───────────────────────────────────────────────────────
    with tab_ads:
        col_wb, col_oz = st.columns(2)

        with col_wb:
            st.subheader("Реклама WB")
            st.caption("ЛК WB → Реклама → История затрат → Скачать xlsx")
            ads_files = st.file_uploader(
                "Файлы рекламы WB", type=["xlsx"],
                accept_multiple_files=True, key="wb_ads",
            )
            ads_method = st.radio(
                "Метод распределения",
                ["Пропорционально выручке", "Без привязки к SKU"],
                key="ads_method",
            )
            if ads_files and st.button("Загрузить рекламу WB", key="btn_wb_ads",
                                       type="primary"):
                from connectors.wb_ads_parser import (
                    parse_wb_ads_excel, distribute_ad_spend_by_revenue,
                )
                from database.db import insert_ad_spend, log_sync
                total = 0
                for f in ads_files:
                    try:
                        with st.spinner(f"Обрабатываю {f.name}…"):
                            records, stats = parse_wb_ads_excel(f)
                            if ads_method == "Пропорционально выручке":
                                records = distribute_ad_spend_by_revenue(
                                    records, load_data())
                            n = insert_ad_spend(records)
                            total += n
                        log_sync("wb_ads", "ok", n, filename=f.name,
                                 date_from=stats.get("date_from"),
                                 date_to=stats.get("date_to"),
                                 revenue=stats.get("total_spend", 0))
                        st.success(
                            f"**{f.name}**  \n"
                            f"{num(stats['campaigns'])} кампаний  \n"
                            f"Расходы: **{rub(stats['total_spend'])}**"
                        )
                    except Exception as e:
                        log_sync("wb_ads", "error", error=str(e), filename=f.name)
                        st.error(f"{f.name}: {e}")
                if total:
                    st.rerun()

        with col_oz:
            st.subheader("Реклама Ozon")
            st.caption("ЛК Ozon → Продвижение → Статистика → Скачать xlsx")
            ozon_ads_files = st.file_uploader(
                "Файлы рекламы Ozon", type=["xlsx"],
                accept_multiple_files=True, key="ozon_ads",
            )
            ozon_ads_date = st.date_input(
                "Дата начала периода отчёта",
                value=date.today().replace(day=1),
                key="ozon_ads_date",
            )
            if ozon_ads_files and st.button("Загрузить рекламу Ozon",
                                            key="btn_ozon_ads", type="primary"):
                from connectors.ozon_ads_parser import parse_ozon_ads_excel
                from database.db import insert_ad_spend, log_sync
                total = 0
                for f in ozon_ads_files:
                    try:
                        with st.spinner(f"Обрабатываю {f.name}…"):
                            records, stats = parse_ozon_ads_excel(f, ozon_ads_date)
                            n = insert_ad_spend(records)
                            total += n
                        log_sync("ozon_ads", "ok", n, filename=f.name,
                                 date_from=stats.get("date_from"),
                                 date_to=stats.get("date_to"),
                                 revenue=stats.get("total_spend", 0))
                        st.success(
                            f"**{f.name}**  \n"
                            f"{num(stats['campaigns'])} кампаний | "
                            f"{num(stats['skus'])} SKU  \n"
                            f"Расходы: **{rub(stats['total_spend'])}**"
                        )
                    except Exception as e:
                        log_sync("ozon_ads", "error", error=str(e),
                                 filename=f.name)
                        st.error(f"{f.name}: {e}")
                if total:
                    st.rerun()

    # ── COGS ──────────────────────────────────────────────────────────────────
    with tab_cogs:
        st.subheader("Себестоимость (COGS)")
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

        st.caption("Скачай шаблон, заполни себестоимость по каждому SKU и загрузи обратно")
        col_dl, col_up = st.columns(2)
        with col_dl:
            tmpl_bytes = generate_cogs_template(existing or None)
            st.download_button(
                "⬇ Скачать шаблон Excel", data=tmpl_bytes,
                file_name="cogs_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_cogs", use_container_width=True,
            )
        with col_up:
            cogs_file = st.file_uploader(
                "Загрузить заполненный шаблон", type=["xlsx"], key="cogs_upload",
            )
            if cogs_file and st.button("Сохранить себестоимость",
                                       key="btn_cogs", type="primary"):
                try:
                    records, n = parse_cogs_excel(cogs_file)
                    upsert_cogs(records)
                    st.success(f"Сохранено {n} записей себестоимости")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
