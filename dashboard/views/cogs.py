"""Себестоимость: цена за штуку по артикулу с датой начала действия."""

from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from core.db import session
from core.models import CostOfGoods, Product
from dashboard.common import cabinets_df, cabinet_label, data_changed, sidebar_filters, result_for, with_names
from pnl.wb import normalize_article

ALL = "Все кабинеты"


def _load() -> pd.DataFrame:
    with session() as s:
        rows = [{"id": c.id, "article": c.article, "cabinet_id": c.cabinet_id, "valid_from": c.valid_from,
                 "cost": c.cost} for c in s.scalars(select(CostOfGoods).order_by(CostOfGoods.article,
                                                                                CostOfGoods.valid_from))]
    return pd.DataFrame(rows, columns=["id", "article", "cabinet_id", "valid_from", "cost"])


def _save(df: pd.DataFrame, cab_ids: dict[str, int | None]) -> int:
    rows = {}
    for _, r in df.iterrows():
        art = str(r["Артикул"] or "").strip()
        cost = r["Себестоимость, ₽/шт"]
        if not art or pd.isna(cost):
            continue
        d = r["Действует с"]
        d = date(2000, 1, 1) if d is None or pd.isna(d) else pd.to_datetime(d).date()
        rows[(art, cab_ids.get(r["Кабинет"]), d)] = float(cost)
    with session() as s:
        s.execute(delete(CostOfGoods))
        for (art, cab, d), cost in rows.items():
            s.add(CostOfGoods(article=art, cabinet_id=cab, valid_from=d, cost=cost))
    data_changed()
    return len(rows)


def render():
    st.title("Себестоимость")
    st.caption("Цена закупки за штуку. «Действует с» — с какой даты продажи применять цену; для старых "
               "продаж остаётся прежняя. Цена для конкретного кабинета важнее цены для всех кабинетов.")
    cabs = cabinets_df()
    labels = {ALL: None} | {cabinet_label(r): int(r["id"]) for _, r in cabs.iterrows()}
    back = {v: k for k, v in labels.items()}

    df = _load()
    view = pd.DataFrame({
        "Артикул": df["article"], "Кабинет": df["cabinet_id"].map(lambda v: back.get(None if pd.isna(v) else int(v), ALL)),
        "Действует с": pd.to_datetime(df["valid_from"]).dt.date, "Себестоимость, ₽/шт": df["cost"]})
    edited = st.data_editor(
        view, num_rows="dynamic", use_container_width=True, hide_index=True, height=420, key="cogs_editor",
        column_config={
            "Кабинет": st.column_config.SelectboxColumn(options=list(labels), default=ALL, required=True),
            "Действует с": st.column_config.DateColumn(format="DD.MM.YYYY", default=date(2000, 1, 1)),
            "Себестоимость, ₽/шт": st.column_config.NumberColumn(min_value=0, format="%.2f", required=True),
        })
    if st.button("Сохранить", type="primary"):
        n = _save(edited, labels)
        st.success(f"Сохранено строк: {n}")

    with st.expander("Загрузить из файла (xlsx или csv)"):
        st.caption("Колонки: «Артикул», «Себестоимость»; необязательно — «Действует с» (дата). "
                   "Строки добавляются к таблице; совпадающие артикул + дата заменяются.")
        up = st.file_uploader("Файл", type=["xlsx", "csv"], key="cogs_file")
        cab = st.selectbox("Для кабинета", list(labels), key="cogs_file_cab")
        if up is not None and st.button("Загрузить файл"):
            raw = pd.read_csv(up, sep=None, engine="python") if up.name.endswith(".csv") else pd.read_excel(up)
            cols = {c.lower().strip(): c for c in raw.columns}
            a = next((cols[c] for c in cols if "артикул" in c), None)
            c = next((cols[c] for c in cols if "себесто" in c or "цена" in c), None)
            dcol = next((cols[c] for c in cols if "действ" in c or "дата" in c), None)
            if not a or not c:
                st.error("Не нашёл колонки «Артикул» и «Себестоимость».")
            else:
                add = pd.DataFrame({
                    "Артикул": raw[a].map(normalize_article), "Кабинет": cab,
                    "Действует с": pd.to_datetime(raw[dcol]).dt.date if dcol else date(2000, 1, 1),
                    "Себестоимость, ₽/шт": pd.to_numeric(raw[c], errors="coerce")})
                n = _save(pd.concat([view, add.dropna(subset=["Себестоимость, ₽/шт"])]), labels)
                st.success(f"Готово, строк в таблице: {n}")
                st.rerun()

    st.subheader("Продавались без себестоимости")
    f = sidebar_filters()
    if f is None:
        return
    res = result_for(f)
    miss = res.facts[res.facts["cost_missing_qty"] != 0]
    if miss.empty:
        st.success("За выбранный период у всех проданных товаров есть себестоимость.")
        return
    g = miss.groupby(["cabinet_id", "sku"], as_index=False)[["cost_missing_qty", "revenue"]].sum()
    g = with_names(g, f.cabinets, res.products)
    st.dataframe(pd.DataFrame({"Кабинет": g["cabinet"], "Артикул": g["article"], "Товар": g["name"],
                               "Штук без себестоимости": g["cost_missing_qty"], "Выручка, ₽": g["revenue"]})
                 .sort_values("Выручка, ₽", ascending=False),
                 use_container_width=True, hide_index=True)
    if (g["article"] == "").any():
        st.caption("Пустой артикул — товара ещё нет в каталоге кабинета; он появится после загрузки товаров.")
