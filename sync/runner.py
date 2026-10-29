"""Load marketplace data for one cabinet into the database.

Each stream (accruals, orders, ads, products) is synced for a date window and
replaces what was stored for that window, so re-running a period is safe.
Incremental runs re-read the last days because marketplaces adjust them.
"""

import json
import logging
import threading
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import select

from core.crypto import decrypt
from core.db import session
from core.models import Cabinet, LegalEntity, SyncRun, now_msk
from pnl import ozon as ozon_pnl
from pnl import wb as wb_pnl
from sources.ozon_api import PerformanceClient, SellerClient
from sources.wb_api import WbClient
from sync import store

log = logging.getLogger("finboard.sync")

REFRESH_DAYS = 14          # re-read this many recent days on every incremental run
DEFAULT_HISTORY_DAYS = 90  # first load when the cabinet has no explicit start date
ORDER_STATUS_DAYS = 45     # orders are re-read this far back daily: delivered / cancelled come later
_LOCK = threading.Lock()
_running: set[int] = set()
_ENTITY_LOCK = threading.Lock()  # find-or-create by INN must not race between cabinets
_ctx = threading.local()  # .trigger: "auto" for the daily schedule, else "manual"


# ── helpers ──────────────────────────────────────────────────────────────────

def _msk_date(ts: str) -> date:
    """'2026-10-01T21:15:00Z' (UTC) -> MSK calendar date."""
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt + timedelta(hours=3)
    return dt.date()


def _months(date_from: date, date_to: date):
    start = date_from
    while start <= date_to:
        nxt = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
        end = min(date_to, nxt - timedelta(days=1))
        yield start, end
        start = end + timedelta(days=1)


class Run:
    """SyncRun row with progress updates."""

    def __init__(self, cabinet_id: int, stream: str, date_from: date, date_to: date):
        with session() as s:
            r = SyncRun(cabinet_id=cabinet_id, stream=stream, date_from=date_from, date_to=date_to,
                        trigger=getattr(_ctx, "trigger", "manual"))
            s.add(r)
            s.flush()
            self.id = r.id

    def update(self, **kw):
        with session() as s:
            r = s.get(SyncRun, self.id)
            for k, v in kw.items():
                setattr(r, k, v)

    def done(self, rows: int, message: str = ""):
        self.update(status="ok", rows=rows, message=message, finished_at=now_msk())

    def fail(self, message: str):
        self.update(status="error", message=message[-4000:], finished_at=now_msk())


# ── Ozon ─────────────────────────────────────────────────────────────────────

def ozon_orders_from_postings(postings: list[dict]) -> list[dict]:
    rows = []
    for p in postings:
        d = _msk_date(p.get("in_process_at") or p.get("created_at") or "")
        if d is None:
            continue
        cancelled = p.get("status") == "cancelled"
        for pr in p.get("products") or []:
            qty = int(pr.get("quantity") or 0)
            price = pr.get("price")
            price = float((price.get("amount") if isinstance(price, dict) else price) or 0)
            rows.append({
                "date": d, "sku": str(pr.get("sku")), "qty": qty,
                "amount": round(price * qty, 2),
                "cancelled": cancelled, "status": str(p.get("status") or ""),
                "posting": p.get("posting_number", ""),
                "source_key": f"{p.get('posting_number')}:{pr.get('sku')}",
            })
    return rows


def ensure_entity(cabinet_id: int, seller: SellerClient, relink: bool = False) -> int | None:
    """Link an Ozon cabinet to its company from seller info (found by INN or created).

    Loads only fill a missing link; relink=True (the user asked) replaces an existing one.
    Returns the entity id."""
    with session() as s:
        current = s.get(Cabinet, cabinet_id).entity_id
    if current and not relink:
        return current
    co = seller.seller_info()
    inn = str(co.get("inn") or "").strip()
    if not inn:
        return None
    with _ENTITY_LOCK, session() as s:
        cab = s.get(Cabinet, cabinet_id)
        if cab.entity_id and not relink:  # the user picked one while seller info was loading
            return cab.entity_id
        ent = s.scalars(select(LegalEntity).where(LegalEntity.inn == inn)).first()
        if ent is None:
            ent = LegalEntity(name=co.get("legal_name") or co.get("name") or inn, inn=inn,
                              kind="ooo" if co.get("ownership_form") == "ООО" or len(inn) == 10 else "ip",
                              mp_tax_system=co.get("tax_system") or None)
            s.add(ent)
            s.flush()
        cab.entity_id = ent.id
        return ent.id


def sync_ozon(cab: Cabinet, keys: dict, date_from: date, date_to: date, streams) -> dict:
    seller = SellerClient(keys["client_id"], keys["api_key"])
    result = {}
    try:
        ensure_entity(cab.id, seller)
    except Exception:
        log.exception("seller info for cabinet %s", cab.id)

    if "products" in streams:
        run = Run(cab.id, "products", date_from, date_to)
        try:
            products = seller.products()
            try:
                costs = seller.net_prices()
            except Exception:
                log.exception("net_price for cabinet %s", cab.id)
                costs = {}
            for p in products:
                p["card_cost"] = costs.get(p["offer_id"], 0.0)
            n = store.upsert_products(cab.id, products)
            run.done(n)
            result["products"] = n
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise

    if "accruals" in streams:
        run = Run(cab.id, "accruals", date_from, date_to)
        try:
            types = ozon_pnl.load_types(seller.accrual_types())
            total, day = 0, date_from
            while day <= date_to:
                rows = ozon_pnl.accruals_to_ledger(seller.accruals_by_day(day), types)
                total += store.replace_ledger_days(cab.id, day, day, rows)
                run.update(rows=total, message=f"загружено по {day:%d.%m.%Y}")
                store.set_cursor(cab.id, "accruals", day.isoformat())
                day += timedelta(days=1)
            run.done(total)
            result["accruals"] = total
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise

    if "orders" in streams:
        run = Run(cab.id, "orders", date_from, date_to)
        try:
            total = 0
            for a, b in _months(date_from, date_to):
                rows = ozon_orders_from_postings(seller.postings(a, b))
                rows = [r for r in rows if a <= r["date"] <= b]
                total += store.replace_orders(cab.id, a, b, rows)
                run.update(rows=total, message=f"загружено по {b:%d.%m.%Y}")
            run.done(total)
            result["orders"] = total
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise

    try:
        unknown = store.unknown_skus(cab.id)
        if unknown:
            store.upsert_products(cab.id, [p for p in seller.products_by_sku(unknown) if p["sku"] in unknown])
        for sku in store.unknown_skus(cab.id)[:50]:
            posting = store.posting_of(cab.id, sku)
            if posting:
                store.upsert_products(cab.id, [p for p in seller.posting_products(posting) if p["sku"] == sku])
    except Exception:
        log.exception("cards for unknown SKUs of cabinet %s", cab.id)

    if "ads" in streams and keys.get("perf_client_id") and keys.get("perf_client_secret"):
        run = Run(cab.id, "ads", date_from, date_to)
        try:
            perf = PerformanceClient(keys["perf_client_id"], keys["perf_client_secret"])
            camps = perf.campaigns()
            store.upsert_campaigns(cab.id, camps)
            total = 0
            for a, b in _months(date_from, date_to):
                spent = {}
                for x in perf.daily_spend(a, b):
                    spent[x["campaign_id"]] = spent.get(x["campaign_id"], 0) + x["money_spent"]
                cpc_ids = [cid for cid, v in spent.items() if v > 0
                           and camps.get(cid, {}).get("advObjectType") in ("SKU", "BRAND_SHELF")]
                rows = []
                for r in perf.cpc_sku_daily(cpc_ids, a, b):
                    rows.append({"date": r["date"], "campaign_id": r["campaign_id"], "sku": r["sku"],
                                 "amount": r["amount"], "kind": "alloc_cpc", "campaign_type": "cpc",
                                 "source_key": f"cpc:{r['campaign_id']}:{r['date']}:{r['sku']}"})
                if any(camps.get(cid, {}).get("advObjectType") == "SEARCH_PROMO" and v > 0
                       for cid, v in spent.items()):
                    agg = {}
                    for r in perf.cpo_orders(a, b):
                        k = (r["date"], r["sku"])
                        agg[k] = agg.get(k, 0) + r["amount"]
                    for (d, sku), amount in agg.items():
                        rows.append({"date": d, "campaign_id": "", "sku": sku, "amount": amount,
                                     "kind": "alloc_cpo", "campaign_type": "cpo",
                                     "source_key": f"cpo:{d}:{sku}"})
                total += store.replace_ads(cab.id, a, b, rows, ("alloc_cpc", "alloc_cpo"))
                run.update(rows=total, message=f"загружено по {b:%d.%m.%Y}")
            run.done(total)
            result["ads"] = total
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise
    return result


# ── WB ───────────────────────────────────────────────────────────────────────

def wb_orders(rows: list[dict], date_from: date, date_to: date) -> list[dict]:
    out = []
    for r in rows:
        d = date.fromisoformat(str(r.get("date"))[:10])
        if not (date_from <= d <= date_to):
            continue
        out.append({
            "date": d, "sku": str(r.get("nmId")), "qty": 1,
            "amount": round(float(r.get("priceWithDisc") or 0), 2),
            "cancelled": bool(r.get("isCancel")), "status": "cancelled" if r.get("isCancel") else "",
            "posting": r.get("srid", ""),
            "source_key": str(r.get("srid") or f"{r.get('gNumber')}:{r.get('nmId')}"),
        })
    return out


def sync_wb(cab: Cabinet, keys: dict, date_from: date, date_to: date, streams) -> dict:
    client = WbClient(keys["token"])
    result = {}

    if "accruals" in streams:
        run = Run(cab.id, "accruals", date_from, date_to)
        try:
            rows = client.report_detail(date_from, date_to,
                                        progress=lambda n: run.update(rows=n, message="загрузка отчёта"))
            ledger = wb_pnl.rows_to_ledger(rows)
            reports = sorted({f"{r.get('reportId') or r.get('realizationreport_id')}:" for r in rows})
            n = store.replace_ledger_keys(cab.id, reports, ledger)
            store.upsert_products(cab.id, list(wb_pnl.products_from_rows(rows).values()))
            store.set_cursor(cab.id, "accruals", date_to.isoformat())
            run.done(n, f"отчётов: {len(reports)}")
            result["accruals"] = n
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise

    if "orders" in streams:
        run = Run(cab.id, "orders", date_from, date_to)
        try:
            rows = wb_orders(client.orders(date_from), date_from, date_to)
            n = store.replace_orders(cab.id, date_from, date_to, rows)
            run.done(n)
            result["orders"] = n
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise

    if "ads" in streams:
        run = Run(cab.id, "ads", date_from, date_to)
        try:
            camps = client.campaigns()
            store.upsert_campaigns(cab.id, camps)
            spend = client.ad_spend(list(camps), date_from, date_to)
            rows = [{"date": r["date"], "campaign_id": r["campaign_id"], "sku": r["sku"],
                     "amount": round(r["amount"], 2), "kind": "spend", "campaign_type": "wb",
                     "source_key": f"wb:{r['campaign_id']}:{r['date']}:{r['sku']}"} for r in spend]
            n = store.replace_ads(cab.id, date_from, date_to, rows, ("spend",))
            run.done(n)
            result["ads"] = n
        except Exception as e:
            run.fail(f"{e}\n{traceback.format_exc()}")
            raise
    return result


# ── entry points ─────────────────────────────────────────────────────────────

ALL_STREAMS = ("products", "accruals", "orders", "ads")


def default_window(cab: Cabinet) -> tuple[date, date]:
    today = date.today()
    cursor = store.get_cursor(cab.id, "accruals")
    if cursor:
        start = date.fromisoformat(cursor) - timedelta(days=REFRESH_DAYS)
    else:
        start = cab.history_from or (today - timedelta(days=DEFAULT_HISTORY_DAYS))
    return start, today - timedelta(days=1)


def sync_cabinet(cabinet_id: int, date_from: date | None = None, date_to: date | None = None,
                 streams=ALL_STREAMS) -> dict:
    with _LOCK:
        if cabinet_id in _running:
            return {"skipped": "уже идёт загрузка"}
        _running.add(cabinet_id)
    try:
        with session() as s:
            cab = s.get(Cabinet, cabinet_id)
        keys = decrypt(cab.secrets)
        if date_from is None or date_to is None:
            date_from, date_to = default_window(cab)
        if cab.marketplace == "ozon":
            res = sync_ozon(cab, keys, date_from, date_to, streams)
        else:
            res = sync_wb(cab, keys, date_from, date_to, streams)
        with session() as s:
            s.get(Cabinet, cabinet_id).last_sync_at = now_msk()
        return res
    finally:
        with _LOCK:
            _running.discard(cabinet_id)


def start_background(cabinet_id: int, date_from=None, date_to=None, streams=ALL_STREAMS) -> bool:
    if is_running(cabinet_id):
        return False

    def work():
        try:
            sync_cabinet(cabinet_id, date_from, date_to, streams)
        except Exception:
            log.exception("sync cabinet %s failed", cabinet_id)

    threading.Thread(target=work, daemon=True, name=f"sync-{cabinet_id}").start()
    return True


def is_running(cabinet_id: int) -> bool:
    with _LOCK:
        return cabinet_id in _running


def sync_all() -> None:
    with session() as s:
        ids = [c.id for c in s.scalars(select(Cabinet).where(Cabinet.active.is_(True), Cabinet.secrets != ""))]
    _ctx.trigger = "auto"
    try:
        for cid in ids:
            try:
                sync_cabinet(cid)
                today = date.today()
                sync_cabinet(cid, today - timedelta(days=ORDER_STATUS_DAYS), today - timedelta(days=1),
                             streams=("orders",))
            except Exception:
                log.exception("scheduled sync of cabinet %s failed", cid)
    finally:
        _ctx.trigger = "manual"


def check_keys(marketplace: str, keys: dict) -> dict[str, str]:
    """Probe each API the cabinet needs: {name: 'ok' | error text}."""
    out = {}
    if marketplace == "ozon":
        try:
            SellerClient(keys["client_id"], keys["api_key"]).accrual_types()
            out["Seller API: начисления"] = "ok"
        except Exception as e:
            out["Seller API: начисления"] = str(e)[:200]
        try:
            SellerClient(keys["client_id"], keys["api_key"]).post(
                "/v2/posting/fbo/list", {"filter": {"since": "2026-01-01T00:00:00Z",
                                                    "to": "2026-01-02T00:00:00Z"}, "limit": 1})
            out["Seller API: заказы"] = "ok"
        except Exception as e:
            out["Seller API: заказы"] = str(e)[:200]
        if keys.get("perf_client_id"):
            try:
                PerformanceClient(keys["perf_client_id"], keys["perf_client_secret"])._headers()
                out["Performance API: реклама"] = "ok"
            except Exception as e:
                out["Performance API: реклама"] = str(e)[:200]
        else:
            out["Performance API: реклама"] = "ключ не задан — реклама будет одной суммой без разбивки по товарам"
    else:
        out = WbClient(keys["token"]).check()
    return out


def key_status(report: dict[str, str]) -> str:
    oks = [v == "ok" for v in report.values()]
    return "ok" if all(oks) else ("partial" if any(oks) else "error")


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False)
