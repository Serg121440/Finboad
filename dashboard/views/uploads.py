"""Загрузка отчётов вручную — запасной путь, если API недоступен, и для сверки."""

import re

import pandas as pd
import streamlit as st

from dashboard.common import MP_NAMES, cabinets_df, cabinet_label, data_changed, rub
from pnl import ozon as ozon_pnl
from pnl import wb as wb_pnl
from sync import store
from sync.runner import Run


def render():
    st.title("Загрузка отчётов")
    st.caption("Обычно данные приходят по API. Файл заменяет данные кабинета за те же дни (Ozon) или тот же "
               "отчёт (WB), поэтому повторная загрузка не задваивает суммы.")
    cabs = cabinets_df()
    if cabs.empty:
        st.info("Сначала добавьте кабинет.")
        return
    labels = {cabinet_label(r): r for _, r in cabs.iterrows()}
    cab = labels[st.selectbox("Кабинет", list(labels))]
    if cab["marketplace"] == "ozon":
        st.markdown("**Ozon: «Отчёт по начислениям»** (Финансы → Начисления → Скачать отчёт, xlsx)")
        up = st.file_uploader("Файл xlsx", type=["xlsx"], key="oz_up")
        if up and st.button("Загрузить", type="primary"):
            df = ozon_pnl.read_report(up)
            rows = ozon_pnl.report_to_ledger(df)
            if not rows:
                st.error("В файле нет строк начислений.")
                return
            d0, d1 = min(r["date"] for r in rows), max(r["date"] for r in rows)
            n = store.replace_ledger_days(int(cab["id"]), d0, d1, rows, source="xlsx")
            Run(int(cab["id"]), "report", d0, d1).done(n, "отчёт xlsx")
            prods = (df[df["SKU"].notna()][["SKU", "Артикул", "Название товара"]].drop_duplicates("SKU"))
            store.upsert_products(int(cab["id"]), [
                {"sku": str(r["SKU"]).split(".")[0], "offer_id": str(r["Артикул"]), "name": str(r["Название товара"])}
                for _, r in prods.iterrows()])
            data_changed()
            st.success(f"Загружено строк: {n}, период {d0:%d.%m.%Y}–{d1:%d.%m.%Y}, "
                       f"итог {rub(sum(r['amount'] for r in rows))}")
    else:
        st.markdown("**WB: «Еженедельный детализированный отчёт»** (Финансовые отчёты → Детализация, xlsx). "
                    "Загружайте оба отчёта недели — по России и по СНГ.")
        ups = st.file_uploader("Файлы xlsx", type=["xlsx"], accept_multiple_files=True, key="wb_up")
        if ups and st.button("Загрузить", type="primary"):
            for up in ups:
                m = re.search(r"№\s*(\d+)", up.name)
                if not m:
                    st.error(f"{up.name}: в имени файла нет номера отчёта (№…) — переименуйте как скачано из WB.")
                    continue
                no = m.group(1)
                rows = wb_pnl.read_report(up)
                for r in rows:
                    r["Номер отчёта"] = no
                ledger = wb_pnl.rows_to_ledger(rows)
                n = store.replace_ledger_keys(int(cab["id"]), [f"{no}:"], ledger, source="xlsx")
                if ledger:
                    # one of the week's reports (Russia or CIS): logged, but not counted as full coverage
                    days = [r["date"] for r in ledger]
                    Run(int(cab["id"]), "wb_report", min(days), max(days)).done(n, f"отчёт №{no}")
                store.upsert_products(int(cab["id"]), list(wb_pnl.products_from_rows(rows).values()))
                st.success(f"Отчёт №{no}: строк {n}, итог {rub(sum(r['amount'] for r in ledger))}")
            data_changed()
