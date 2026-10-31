"""WB: weekly reports where they exist, daily reports for the days after — never both."""

from datetime import date

from sqlalchemy import delete, func, select

from core.db import init_db, session
from core.models import Cabinet, LedgerEntry, SyncCursor
from sync import runner, store


def _row(report, d0, d1, day, rrd, price):
    return {"reportId": report, "dateFrom": d0, "dateTo": d1, "rrdId": rrd, "rrDate": day,
            "sellerOperName": "Продажа", "docTypeName": "Продажа", "nmId": 1, "quantity": 1,
            "retailPriceWithDisc": price, "forPay": price * 0.8}


class FakeWb:
    reports: dict = {}

    def __init__(self, token):
        pass

    def report_detail(self, date_from, date_to, progress=None, period="weekly"):
        return [r for r in self.reports[period]
                if date_from.isoformat() <= r["dateTo"] and r["dateFrom"] <= date_to.isoformat()]


def _cabinet() -> Cabinet:
    init_db()
    with session() as s:
        for c in s.scalars(select(Cabinet).where(Cabinet.name == "wb-daily-test")):
            s.execute(delete(SyncCursor).where(SyncCursor.cabinet_id == c.id))
            s.execute(delete(LedgerEntry).where(LedgerEntry.cabinet_id == c.id))
            s.delete(c)
        c = Cabinet(marketplace="wb", name="wb-daily-test", secrets="")
        s.add(c)
        s.flush()
        s.expunge(c)
        return c


def _revenue(cab_id) -> dict[str, float]:
    with session() as s:
        rows = s.execute(select(LedgerEntry.date, func.sum(LedgerEntry.amount))
                         .where(LedgerEntry.cabinet_id == cab_id, LedgerEntry.category == "sale")
                         .group_by(LedgerEntry.date)).all()
    return {d.isoformat(): a for d, a in rows}


def test_daily_reports_fill_days_after_last_weekly(monkeypatch):
    monkeypatch.setattr(runner, "WbClient", FakeWb)
    cab = _cabinet()
    week = "2026-10-19", "2026-10-25"
    FakeWb.reports = {
        "weekly": [_row(1, *week, "2026-10-24", 1, 100), _row(1, *week, "2026-10-25", 2, 200)],
        "daily": [_row(10 + d, f"2026-10-{d}", f"2026-10-{d}", f"2026-10-{d}", 50 + d, d)
                  for d in range(24, 31)],
    }
    runner.sync_wb(cab, {"token": ""}, date(2026, 10, 24), date(2026, 10, 30), ("accruals",))
    # 24–25 from the weekly report only, 26–30 from daily ones
    assert _revenue(cab.id) == {"2026-10-24": 100, "2026-10-25": 200, "2026-10-26": 26, "2026-10-27": 27,
                                "2026-10-28": 28, "2026-10-29": 29, "2026-10-30": 30}
    assert store.get_cursor(cab.id, "wb_report_to") == "2026-10-30"

    # the next weekly report covers 26.10–01.11: its days replace the daily rows
    week2 = "2026-10-26", "2026-11-01"
    FakeWb.reports["weekly"] += [_row(2, *week2, "2026-10-26", 3, 1000), _row(2, *week2, "2026-10-30", 4, 3000)]
    FakeWb.reports["daily"].append(_row(40, "2026-11-01", "2026-11-01", "2026-11-01", 90, 7))
    runner.sync_wb(cab, {"token": ""}, date(2026, 10, 26), date(2026, 11, 1), ("accruals",))
    rev = _revenue(cab.id)
    assert rev == {"2026-10-24": 100, "2026-10-25": 200, "2026-10-26": 1000, "2026-10-30": 3000}
    assert store.get_cursor(cab.id, "wb_weekly_to") == "2026-11-01"
