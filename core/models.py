"""Finboard v2 data model.

Money flows are stored once, in `ledger`, exactly as the marketplace reports them
(one row per accrual line, signed: income > 0, expense < 0). Everything the
dashboard shows is derived from the ledger plus orders, ad spend, cost of goods,
fixed costs and tax settings.
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index,
)

from core.db import Base

_MSK = timezone(timedelta(hours=3))


def now_msk():
    return datetime.now(_MSK).replace(tzinfo=None)


class LegalEntity(Base):
    """ИП or ООО. VAT thresholds and taxes are computed per entity, across its cabinets."""
    __tablename__ = "fb_legal_entity"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(10), nullable=False, default="ip")  # ip | ooo
    inn = Column(String(20), default="")
    mp_tax_system = Column(String(40))   # regime the marketplace has on file (Ozon seller info), a hint
    created_at = Column(DateTime, default=now_msk)


class TaxSetting(Base):
    """Tax regime of an entity, valid from a date until the next setting."""
    __tablename__ = "fb_tax_setting"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("fb_legal_entity.id", ondelete="CASCADE"), nullable=False)
    valid_from = Column(Date, nullable=False)
    regime = Column(String(20), nullable=False)          # see pnl.tax.REGIMES
    usn_rate = Column(Float, default=None)               # 0.06, 0.15, regional rate
    vat_mode = Column(String(10), default="auto")        # auto | exempt | 5 | 7 | 22
    has_employees = Column(Boolean, default=False)
    ip_contrib_monthly = Column(Float, default=0.0)      # ИП: страховые взносы в месяц
    vat_vs_prior_year = Column(Float, default=0.0)       # доход за прошлый год (для порога НДС)

    __table_args__ = (UniqueConstraint("entity_id", "valid_from"),)


class Cabinet(Base):
    __tablename__ = "fb_cabinet"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("fb_legal_entity.id", ondelete="SET NULL"))
    marketplace = Column(String(10), nullable=False)      # ozon | wb
    name = Column(String(200), nullable=False)
    external_id = Column(String(50), default="")          # Ozon Client-Id / WB supplier id
    secrets = Column(Text, default="")                    # encrypted JSON with API keys
    key_status = Column(String(20), default="unchecked")  # ok | partial | error | unchecked
    key_report = Column(Text, default="")                 # JSON: scope -> ok/error text
    checked_at = Column(DateTime)
    history_from = Column(Date)                           # how far back to load
    last_sync_at = Column(DateTime)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_msk)


class Product(Base):
    __tablename__ = "fb_product"

    id = Column(Integer, primary_key=True)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), nullable=False)
    sku = Column(String(50), nullable=False)       # Ozon SKU / WB nmId
    article = Column(String(200), default="")      # offer_id / vendorCode (normalized)
    name = Column(String(500), default="")
    category = Column(String(200), default="")
    vat10 = Column(Boolean, default=False)         # товар облагается НДС 10 %
    card_cost = Column(Float)                      # себестоимость из карточки маркетплейса (Ozon net_price)

    __table_args__ = (UniqueConstraint("cabinet_id", "sku"),)


class LedgerEntry(Base):
    __tablename__ = "fb_ledger"

    id = Column(Integer, primary_key=True)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)            # дата начисления (дата операции в отчёте)
    sku = Column(String(50))                       # None = не привязано к товару
    category = Column(String(40), nullable=False)  # see pnl.categories
    amount = Column(Float, nullable=False, default=0.0)
    qty = Column(Integer, default=0)               # штуки для продаж (+) и возвратов (−)
    posting = Column(String(80), default="")
    raw_type = Column(String(200), default="")     # исходное название начисления
    source = Column(String(10), default="api")     # api | xlsx
    source_key = Column(String(120), nullable=False)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "source_key"),
        Index("ix_fb_ledger_cab_date", "cabinet_id", "date"),
    )


class OrderLine(Base):
    """Orders by order date (base «заказы» and cancellations for base «сделки»)."""
    __tablename__ = "fb_order"

    id = Column(Integer, primary_key=True)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    sku = Column(String(50), nullable=False)
    qty = Column(Integer, default=0)
    amount = Column(Float, default=0.0)            # по цене продавца
    cancelled = Column(Boolean, default=False)
    status = Column(String(40), default="")        # Ozon posting status; "" — неизвестно (WB, старые строки)
    posting = Column(String(80), default="")
    source_key = Column(String(120), nullable=False)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "source_key"),
        Index("ix_fb_order_cab_date", "cabinet_id", "date"),
    )


class AdSpend(Base):
    """Ad spend from the ad cabinet API, per campaign/day/SKU. sku None = общий расход
    (e.g. Ozon «Оплата за заказ — все товары»)."""
    __tablename__ = "fb_ad_spend"

    id = Column(Integer, primary_key=True)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    campaign_id = Column(String(50), default="")
    campaign_name = Column(String(300), default="")
    campaign_type = Column(String(50), default="")
    sku = Column(String(50))
    amount = Column(Float, default=0.0)            # положительное число — расход
    # spend: real money not present in the marketplace report (WB ad cabinet);
    # alloc_cpc / alloc_cpo: Ozon ad statistics used only as weights to split the
    # ad money from the accrual report between SKUs.
    kind = Column(String(20), default="spend")
    source_key = Column(String(160), nullable=False)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "source_key"),
        Index("ix_fb_ad_cab_date", "cabinet_id", "date"),
    )


class AdCampaign(Base):
    __tablename__ = "fb_ad_campaign"

    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), primary_key=True)
    campaign_id = Column(String(50), primary_key=True)
    name = Column(String(300), default="")
    type = Column(String(50), default="")          # Ozon advObjectType / WB type
    state = Column(String(50), default="")


class CostOfGoods(Base):
    """Себестоимость за штуку по артикулу, действует с даты. cabinet_id None = для всех кабинетов."""
    __tablename__ = "fb_cogs"

    id = Column(Integer, primary_key=True)
    article = Column(String(200), nullable=False)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"))
    valid_from = Column(Date, nullable=False)
    cost = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("article", "cabinet_id", "valid_from"),)


class FixedCost(Base):
    """Постоянные расходы, вводятся вручную: статья, месяц, сумма."""
    __tablename__ = "fb_fixed_cost"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("fb_legal_entity.id", ondelete="CASCADE"))
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"))
    month = Column(Date, nullable=False)           # первое число месяца
    item = Column(String(200), nullable=False)
    amount = Column(Float, nullable=False)         # положительное число — расход
    comment = Column(String(500), default="")


class FixedMonth(Base):
    """Месяц, в котором постоянных расходов нет: отличает «0 ₽» от «не заполнено»."""
    __tablename__ = "fb_fixed_month"

    id = Column(Integer, primary_key=True)
    month = Column(Date, nullable=False, unique=True)
    no_costs = Column(Boolean, default=True)


class ShareLink(Base):
    __tablename__ = "fb_share_link"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(200), default="")
    cabinet_ids = Column(Text, default="[]")       # JSON list; [] = все
    hide_cogs = Column(Boolean, default=False)
    expires_at = Column(DateTime)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_msk)
    last_used_at = Column(DateTime)
    uses = Column(Integer, default=0)


class SyncRun(Base):
    __tablename__ = "fb_sync_run"

    id = Column(Integer, primary_key=True)
    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"))
    stream = Column(String(30), default="")        # accruals | orders | ads | products | report
    started_at = Column(DateTime, default=now_msk)
    finished_at = Column(DateTime)
    status = Column(String(10), default="running") # running | ok | error
    trigger = Column(String(10), default="manual") # auto (daily schedule) | manual
    rows = Column(Integer, default=0)
    date_from = Column(Date)
    date_to = Column(Date)
    message = Column(Text, default="")


class SyncCursor(Base):
    """Last fully loaded date per cabinet and stream (incremental sync)."""
    __tablename__ = "fb_sync_cursor"

    cabinet_id = Column(Integer, ForeignKey("fb_cabinet.id", ondelete="CASCADE"), primary_key=True)
    stream = Column(String(30), primary_key=True)
    value = Column(String(60), default="")
