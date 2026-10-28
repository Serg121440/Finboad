"""Idempotent writes: a re-sync of the same period replaces rows instead of duplicating them."""

from datetime import date

from sqlalchemy import and_, delete, select

from core.db import session
from core.models import (
    AdCampaign, AdSpend, LedgerEntry, OrderLine, Product, SyncCursor,
)

CHUNK = 2000


def _insert(model, cabinet_id: int, rows: list[dict]) -> int:
    seen, objs = set(), []
    for r in rows:
        if r["source_key"] in seen:
            continue
        seen.add(r["source_key"])
        objs.append(dict(r, cabinet_id=cabinet_id))
    with session() as s:
        for i in range(0, len(objs), CHUNK):
            s.bulk_insert_mappings(model, objs[i:i + CHUNK])
    return len(objs)


def replace_ledger_days(cabinet_id: int, date_from: date, date_to: date, rows: list[dict],
                        source: str = "api") -> int:
    with session() as s:
        s.execute(delete(LedgerEntry).where(and_(
            LedgerEntry.cabinet_id == cabinet_id, LedgerEntry.source == source,
            LedgerEntry.date >= date_from, LedgerEntry.date <= date_to)))
    return _insert(LedgerEntry, cabinet_id, [dict(r, source=source) for r in rows])


def replace_ledger_keys(cabinet_id: int, key_prefixes: list[str], rows: list[dict],
                        source: str = "api") -> int:
    """Replace rows of whole reports (WB): keys start with '<reportId>:'."""
    with session() as s:
        for p in key_prefixes:
            s.execute(delete(LedgerEntry).where(and_(
                LedgerEntry.cabinet_id == cabinet_id, LedgerEntry.source_key.like(f"{p}%"))))
    return _insert(LedgerEntry, cabinet_id, [dict(r, source=source) for r in rows])


def replace_orders(cabinet_id: int, date_from: date, date_to: date, rows: list[dict]) -> int:
    with session() as s:
        s.execute(delete(OrderLine).where(and_(
            OrderLine.cabinet_id == cabinet_id, OrderLine.date >= date_from, OrderLine.date <= date_to)))
    return _insert(OrderLine, cabinet_id, rows)


def replace_ads(cabinet_id: int, date_from: date, date_to: date, rows: list[dict],
                kinds: tuple[str, ...]) -> int:
    with session() as s:
        s.execute(delete(AdSpend).where(and_(
            AdSpend.cabinet_id == cabinet_id, AdSpend.kind.in_(kinds),
            AdSpend.date >= date_from, AdSpend.date <= date_to)))
    return _insert(AdSpend, cabinet_id, rows)


def upsert_products(cabinet_id: int, products: list[dict]) -> int:
    with session() as s:
        existing = {p.sku: p for p in s.scalars(select(Product).where(Product.cabinet_id == cabinet_id))}
        for p in products:
            obj = existing.get(p["sku"])
            if obj is None:
                obj = Product(cabinet_id=cabinet_id, sku=p["sku"])
                s.add(obj)
                existing[p["sku"]] = obj
            obj.article = p.get("offer_id") or obj.article or ""
            obj.name = p.get("name") or obj.name or ""
            obj.category = p.get("category") or obj.category or ""
    return len(products)


def upsert_campaigns(cabinet_id: int, campaigns: dict[str, dict]) -> None:
    with session() as s:
        existing = {c.campaign_id: c for c in s.scalars(
            select(AdCampaign).where(AdCampaign.cabinet_id == cabinet_id))}
        for cid, c in campaigns.items():
            obj = existing.get(cid) or AdCampaign(cabinet_id=cabinet_id, campaign_id=cid)
            obj.name = (c.get("title") or c.get("name") or "")[:300]
            obj.type = str(c.get("advObjectType") or c.get("type") or "")
            obj.state = str(c.get("state") or c.get("status") or "")
            s.merge(obj)


def get_cursor(cabinet_id: int, stream: str) -> str:
    with session() as s:
        c = s.get(SyncCursor, (cabinet_id, stream))
        return c.value if c else ""


def set_cursor(cabinet_id: int, stream: str, value: str) -> None:
    with session() as s:
        s.merge(SyncCursor(cabinet_id=cabinet_id, stream=stream, value=value))
