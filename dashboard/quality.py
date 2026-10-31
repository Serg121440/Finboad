"""Полнота расчёта: что не учтено в результате. Один блок над цифрами во всех отчётах."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core.db import session
from core.models import FixedCost, FixedMonth, LedgerEntry, SyncCursor

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
          "Ноябрь", "Декабрь"]


@dataclass
class Issue:
    text: str
    where: str = ""        # page that fixes it
    blocking: bool = True  # the profit is not final while it's open


def months_of(d0: date, d1: date) -> list[date]:
    out, m = [], d0.replace(day=1)
    while m <= d1:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def month_end(m: date) -> date:
    return (m + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def month_label(m: date, d0: date, d1: date) -> str:
    """«Октябрь 2026» or «Октябрь 2026 · 1–28 · неполный» when the period covers only part of it."""
    a, b = max(m, d0), min(month_end(m), d1)
    name = f"{MONTHS[m.month - 1]} {m.year}"
    if a == m and b == month_end(m):
        return name
    return f"{name} · {a.day}–{b.day} · неполный"


def find_issues(facts: pd.DataFrame, taxes: pd.DataFrame, cabinets: pd.DataFrame, d0: date, d1: date,
                filled_months: set[date], missing_by_cabinet: dict[str, int],
                ads_missing_by_cabinet: dict[str, int] | None = None,
                wb_report_to: dict[str, date | None] | None = None,
                data_until: date | None = None) -> list[Issue]:
    """cabinets: the selected ones (id, name, entity_id). ads_missing_by_cabinet: WB only — its ads
    come from the ad cabinet, not from accruals. wb_report_to: WB cabinet -> end of its latest
    realization report, weekly or daily (None = no report yet). data_until: last day data can exist (yesterday)."""
    out = []
    until = min(d1, data_until or d1)
    for name, last in (wb_report_to or {}).items():
        if until >= d0 and (last is None or last < until):
            since = max(d0, last + timedelta(days=1)) if last else d0
            out.append(Issue(f"{name}: отчёта WB о реализации за {since:%d.%m}–{until:%d.%m} ещё нет — продажи, "
                             "комиссия и логистика WB за эти дни не учтены",
                             "кнопка «Загрузить» выше (ежедневный отчёт WB выходит на следующий день)"))
    for name, miss in missing_by_cabinet.items():
        if miss:
            out.append(Issue(f"{name}: не загружено дней в периоде — {miss}", "кнопка «Загрузить» выше"))
    for name, miss in (ads_missing_by_cabinet or {}).items():
        if miss:
            out.append(Issue(f"{name}: реклама не загружена за дней — {miss}, расходы занижены",
                             "кнопка «Загрузить» выше"))
    if not facts.empty:
        m = facts[facts["cost_missing_qty"] != 0]
        if not m.empty:
            out.append(Issue(f"Нет себестоимости: {m['cost_missing_qty'].sum():.0f} шт., "
                             f"{m['sku'].nunique()} товаров — прибыль завышена", "«Себестоимость»"))
    with_tax = set(taxes["entity_id"]) if not taxes.empty else set()
    no_tax = cabinets[~cabinets["entity_id"].isin(with_tax)]
    if not no_tax.empty:
        out.append(Issue("Налог не считается: " + ", ".join(no_tax["name"]) +
                         " — нет юрлица или налогового режима", "«Кабинеты и налоги»"))
    if not taxes.empty:
        for _, r in taxes[taxes["note"].fillna("") != ""].iterrows():
            # a month before the entity's first tax setting: the tax is simply missing
            missing = "не считается" in r["note"]
            out.append(Issue(f"Налоги, {pd.Timestamp(r['month']):%m.%Y}: {r['note']}",
                             "«Кабинеты и налоги»" if missing else "", blocking=missing))
    empty = [m for m in months_of(d0, d1) if m not in filled_months]
    if empty:
        out.append(Issue("Постоянные расходы не заполнены: " + ", ".join(f"{m:%m.%Y}" for m in empty) +
                         " (если их нет — отметьте «расходов нет»)", "«Постоянные расходы»"))
    partial = [month_label(m, d0, d1) for m in months_of(d0, d1) if "неполный" in month_label(m, d0, d1)]
    if partial:
        out.append(Issue("Неполный месяц: " + ", ".join(partial) +
                         " — сравнивайте с другими месяцами осторожно", blocking=False))
    return out


def filled_fixed_months(d0: date, d1: date) -> set[date]:
    """Months with fixed cost lines or marked «no fixed costs»."""
    ms = months_of(d0, d1)
    with session() as s:
        have = {pd.Timestamp(m).date() for m in s.scalars(select(FixedCost.month).where(FixedCost.month.in_(ms)))}
        have |= {pd.Timestamp(m).date() for m in s.scalars(
            select(FixedMonth.month).where(FixedMonth.month.in_(ms), FixedMonth.no_costs.is_(True)))}
    return have


def wb_report_ends(cabinet_ids: list[int]) -> dict[int, date | None]:
    """WB cabinet -> end of its latest loaded report (weekly or daily); before the first sync that stores it,
    the latest sale date in the ledger."""
    if not cabinet_ids:
        return {}
    with session() as s:
        cur = dict(s.execute(select(SyncCursor.cabinet_id, SyncCursor.value).where(
            SyncCursor.cabinet_id.in_(cabinet_ids), SyncCursor.stream == "wb_report_to")).all())
        led = dict(s.execute(select(LedgerEntry.cabinet_id, func.max(LedgerEntry.date))
                             .where(LedgerEntry.cabinet_id.in_(cabinet_ids))
                             .group_by(LedgerEntry.cabinet_id)).all())
    out = {}
    for i in cabinet_ids:
        v = cur.get(i) or led.get(i)
        out[i] = date.fromisoformat(str(v)[:10]) if v else None
    return out


def issues_for(f, res) -> list[Issue]:
    from dashboard.common import _loaded_intervals, cabinet_label, missing_days
    cabs = f.cabinets[f.cabinets["id"].isin(f.cabinet_ids)]
    end = min(f.date_to, date.today() - timedelta(days=1))

    def missing(have, rows):
        return {cabinet_label(r): missing_days(have.get(int(r["id"]), []), f.date_from, end)
                if f.date_from <= end else 0 for _, r in rows.iterrows()}

    miss = missing(_loaded_intervals(), cabs)
    wb = cabs[cabs["marketplace"] == "wb"]
    ads_miss = missing(_loaded_intervals(("ads",)), wb)
    ends = wb_report_ends([int(i) for i in wb["id"]])
    wb_to = {cabinet_label(r): ends.get(int(r["id"])) for _, r in wb.iterrows()}
    return find_issues(res.facts, res.taxes, cabs, f.date_from, f.date_to,
                       filled_fixed_months(f.date_from, f.date_to), miss, ads_miss, wb_to, end)


def quality_block(f, res) -> list[Issue]:
    """Status above the numbers: final or preliminary, and what's missing."""
    issues = issues_for(f, res)
    blocking = [i for i in issues if i.blocking]
    lines = "\n".join(f"- {i.text}" + (f" → {i.where}" if i.where else "") for i in issues)
    if blocking:
        st.warning(f"**Предварительный результат** — не всё учтено:\n{lines}")
    elif issues:
        st.info(f"**Расчёт полный.** Обратите внимание:\n{lines}")
    else:
        st.success("**Расчёт полный**: себестоимость, налоги и постоянные расходы учтены, период загружен.")
    return issues


def status_line(issues: list[Issue]) -> str:
    """One line for exports."""
    blocking = [i.text for i in issues if i.blocking]
    return ("Предварительный результат: " + "; ".join(blocking)) if blocking else "Расчёт полный"
