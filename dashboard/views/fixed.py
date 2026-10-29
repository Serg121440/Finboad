"""Постоянные расходы: вводятся вручную по месяцам."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import and_, delete, select

from core.db import session
from core.models import FixedCost, FixedMonth, LegalEntity
from dashboard.common import cabinets_df, cabinet_label, data_changed, rub

NOBODY = "—"


def _month_options() -> list[date]:
    today = date.today().replace(day=1)
    out, m = [], today
    for _ in range(24):
        out.append(m)
        m = (m - timedelta(days=1)).replace(day=1)
    return out


def _rows(month: date) -> pd.DataFrame:
    with session() as s:
        rows = [{"entity_id": r.entity_id, "cabinet_id": r.cabinet_id, "item": r.item, "amount": r.amount,
                 "comment": r.comment} for r in s.scalars(select(FixedCost).where(FixedCost.month == month)
                                                         .order_by(FixedCost.id))]
    return pd.DataFrame(rows, columns=["entity_id", "cabinet_id", "item", "amount", "comment"])


def render():
    st.title("Постоянные расходы")
    st.caption("Аренда, зарплаты, бухгалтерия, сервисы, взносы ИП — всё, что не начисляет маркетплейс. Сумма "
               "за месяц, положительным числом. Привяжите статью к юрлицу или к кабинету, иначе она войдёт "
               "только в общий итог. В отчётах за неполный месяц сумма берётся пропорционально дням.")

    with session() as s:
        ents = {e.name: e.id for e in s.scalars(select(LegalEntity).order_by(LegalEntity.name))}
    cabs = cabinets_df()
    cab_labels = {cabinet_label(r): int(r["id"]) for _, r in cabs.iterrows()}
    ent_back = {v: k for k, v in ents.items()}
    cab_back = {v: k for k, v in cab_labels.items()}

    month = st.selectbox("Месяц", _month_options(), index=0, format_func=lambda d: d.strftime("%m.%Y"))
    df = _rows(month)
    view = pd.DataFrame({
        "Статья": df["item"],
        "Сумма, ₽": df["amount"],
        "Юрлицо": df["entity_id"].map(lambda v: ent_back.get(v, NOBODY) if pd.notna(v) else NOBODY),
        "Кабинет": df["cabinet_id"].map(lambda v: cab_back.get(int(v), NOBODY) if pd.notna(v) else NOBODY),
        "Комментарий": df["comment"],
    })
    edited = st.data_editor(
        view, num_rows="dynamic", use_container_width=True, hide_index=True, key=f"fixed_{month}",
        column_config={
            "Статья": st.column_config.TextColumn(required=True),
            "Сумма, ₽": st.column_config.NumberColumn(min_value=0, format="%.2f", required=True),
            "Юрлицо": st.column_config.SelectboxColumn(options=[NOBODY] + list(ents), default=NOBODY),
            "Кабинет": st.column_config.SelectboxColumn(options=[NOBODY] + list(cab_labels), default=NOBODY),
        })
    st.metric("Итого за месяц", rub(pd.to_numeric(edited["Сумма, ₽"], errors="coerce").fillna(0).sum()))
    with session() as s:
        marked = s.scalars(select(FixedMonth).where(FixedMonth.month == month)).first()
        none_now = bool(marked and marked.no_costs)
    none = st.checkbox(f"В {month:%m.%Y} постоянных расходов нет", value=none_now, disabled=not df.empty,
                       key=f"fixed_none_{month}",
                       help="Без статей и без этой отметки отчёты пишут «постоянные расходы не заполнены» "
                            "и показывают результат как предварительный.")
    if none != none_now:
        with session() as s:
            m = s.scalars(select(FixedMonth).where(FixedMonth.month == month)).first() or FixedMonth(month=month)
            m.no_costs = none
            s.add(m)
        data_changed()
        st.rerun()

    c1, c2 = st.columns(2)
    if c1.button("Сохранить", type="primary"):
        with session() as s:
            s.execute(delete(FixedCost).where(FixedCost.month == month))
            for _, r in edited.iterrows():
                if not str(r["Статья"] or "").strip() or pd.isna(r["Сумма, ₽"]):
                    continue
                s.add(FixedCost(month=month, item=str(r["Статья"]).strip(), amount=float(r["Сумма, ₽"]),
                                entity_id=ents.get(r["Юрлицо"]), cabinet_id=cab_labels.get(r["Кабинет"]),
                                comment=str(r["Комментарий"] or "") if pd.notna(r["Комментарий"]) else ""))
        data_changed()
        st.success("Сохранено")
        st.rerun()
    prev = (month - timedelta(days=1)).replace(day=1)
    if c2.button(f"Скопировать статьи из {prev:%m.%Y}", disabled=not df.empty,
                 help="Доступно, пока в выбранном месяце нет статей"):
        src = _rows(prev)
        if src.empty:
            st.warning(f"В {prev:%m.%Y} статей нет.")
        else:
            with session() as s:
                for _, r in src.iterrows():
                    s.add(FixedCost(month=month, item=r["item"], amount=r["amount"],
                                    entity_id=None if pd.isna(r["entity_id"]) else int(r["entity_id"]),
                                    cabinet_id=None if pd.isna(r["cabinet_id"]) else int(r["cabinet_id"]),
                                    comment=r["comment"] or ""))
            data_changed()
            st.rerun()

    with st.expander("Все месяцы"):
        with session() as s:
            allr = pd.DataFrame([{"Месяц": r.month, "Сумма": r.amount} for r in s.scalars(select(FixedCost))])
        if allr.empty:
            st.caption("Пока пусто.")
        else:
            t = allr.groupby("Месяц", as_index=False)["Сумма"].sum().sort_values("Месяц", ascending=False)
            t["Месяц"] = pd.to_datetime(t["Месяц"]).dt.strftime("%m.%Y")
            t["Сумма"] = t["Сумма"].map(rub)
            st.dataframe(t, hide_index=True, use_container_width=True)
