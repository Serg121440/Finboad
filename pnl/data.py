"""Load engine input frames from the database."""

from datetime import date

import pandas as pd
from sqlalchemy import select

from core.db import engine as db_engine
from core.models import (
    AdCampaign, AdSpend, Cabinet, CostOfGoods, FixedCost, LedgerEntry, LegalEntity,
    OrderLine, Product, TaxSetting,
)
from pnl.engine import Data


def _frame(stmt, columns: list[str]) -> pd.DataFrame:
    with db_engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
    for c in columns:
        if c not in df:
            df[c] = None
    return df


def load(date_from: date, date_to: date, cabinet_ids: list[int] | None = None) -> Data:
    """Data for [date_from, date_to] plus everything since Jan 1 of date_from's year."""
    start = date(date_from.year, 1, 1)

    cabs = _frame(select(Cabinet.id, Cabinet.marketplace, Cabinet.name, Cabinet.entity_id,
                         Cabinet.active), ["id"])
    ents = _frame(select(LegalEntity.id, LegalEntity.name, LegalEntity.kind), ["id"])
    ids = list(cabs["id"]) if not cabinet_ids else list(cabinet_ids)
    # taxes are per entity: always load all cabinets of the selected entities
    ent_ids = set(cabs[cabs["id"].isin(ids)]["entity_id"].dropna())
    tax_ids = list(set(ids) | set(cabs[cabs["entity_id"].isin(ent_ids)]["id"]))

    led = _frame(select(LedgerEntry.cabinet_id, LedgerEntry.date, LedgerEntry.sku, LedgerEntry.category,
                        LedgerEntry.amount, LedgerEntry.qty, LedgerEntry.posting, LedgerEntry.raw_type)
                 .where(LedgerEntry.cabinet_id.in_(tax_ids), LedgerEntry.date >= start,
                        LedgerEntry.date <= date_to),
                 ["cabinet_id", "date", "sku", "category", "amount", "qty", "posting", "raw_type"])
    ads = _frame(select(AdSpend.cabinet_id, AdSpend.date, AdSpend.sku, AdSpend.amount, AdSpend.kind,
                        AdSpend.campaign_id)
                 .where(AdSpend.cabinet_id.in_(tax_ids), AdSpend.date >= start, AdSpend.date <= date_to),
                 ["cabinet_id", "date", "sku", "amount", "kind", "campaign_id"])
    camps = _frame(select(AdCampaign.cabinet_id, AdCampaign.campaign_id, AdCampaign.type, AdCampaign.name)
                   .where(AdCampaign.cabinet_id.in_(tax_ids)), ["cabinet_id", "campaign_id", "type"])
    orders = _frame(select(OrderLine.cabinet_id, OrderLine.date, OrderLine.sku, OrderLine.qty,
                           OrderLine.amount, OrderLine.cancelled, OrderLine.status)
                    .where(OrderLine.cabinet_id.in_(tax_ids), OrderLine.date >= start,
                           OrderLine.date <= date_to),
                    ["cabinet_id", "date", "sku", "qty", "amount", "cancelled", "status"])
    prods = _frame(select(Product.cabinet_id, Product.sku, Product.article, Product.name, Product.category,
                          Product.vat10).where(Product.cabinet_id.in_(tax_ids)),
                   ["cabinet_id", "sku", "article", "name", "category", "vat10"])
    cogs = _frame(select(CostOfGoods.article, CostOfGoods.cabinet_id, CostOfGoods.valid_from,
                         CostOfGoods.cost), ["article", "cabinet_id", "valid_from", "cost"])
    fixed = _frame(select(FixedCost.entity_id, FixedCost.cabinet_id, FixedCost.month, FixedCost.item,
                          FixedCost.amount), ["entity_id", "cabinet_id", "month", "item", "amount"])
    taxes = _frame(select(TaxSetting.entity_id, TaxSetting.valid_from, TaxSetting.regime, TaxSetting.usn_rate,
                          TaxSetting.vat_mode, TaxSetting.has_employees, TaxSetting.ip_contrib_monthly,
                          TaxSetting.vat_vs_prior_year),
                   ["entity_id", "valid_from", "regime"])

    # fixed costs of the selected scope only
    if not fixed.empty:
        keep = fixed["cabinet_id"].isin(ids) | (fixed["cabinet_id"].isna() & fixed["entity_id"].isin(ent_ids))
        if not cabinet_ids:
            keep = keep | (fixed["cabinet_id"].isna() & fixed["entity_id"].isna())
        fixed = fixed[keep]

    for df in (led, ads, orders):
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
    led["sku"] = led["sku"].where(led["sku"].notna(), None)
    return Data(cabinets=cabs, entities=ents, tax_settings=taxes, ledger=led, ads=ads, campaigns=camps,
                orders=orders, products=prods, cogs=cogs, fixed=fixed, date_from=date_from,
                date_to=date_to, extra={"selected": ids})
