from sqlalchemy import (
    create_engine, Column, String, Float, Date, DateTime, Integer, text, func
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone, timedelta
from config import DATABASE_URL

Base = declarative_base()

_INVALID_PG_PARAMS = {"schema", "pgbouncer", "connect_timeout_ms"}


def _build_engine(raw_url: str):
    """Create SQLAlchemy engine, stripping psycopg2-incompatible URL params."""
    try:
        url = make_url(raw_url)
        if url.get_dialect().name in ("postgresql", "postgres") and url.query:
            clean_query = {k: v for k, v in url.query.items()
                           if k not in _INVALID_PG_PARAMS}
            url = url.set(query=clean_query)
        return create_engine(url, echo=False)
    except Exception:
        return create_engine(raw_url, echo=False)

_MSK = timezone(timedelta(hours=3))

def _now_msk():
    return datetime.now(_MSK).replace(tzinfo=None)


class SaleRecord(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    sku = Column(String(100), nullable=False)
    article = Column(String(200), default="")   # Артикул поставщика
    product_name = Column(String(500))
    category = Column(String(200))
    # Core financials
    revenue = Column(Float, default=0.0)
    returns = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    # Commission breakdown
    commission = Column(Float, default=0.0)       # ВВ без НДС
    vat_commission = Column(Float, default=0.0)   # НДС на комиссию
    acquiring = Column(Float, default=0.0)         # Эквайринг
    # Logistics breakdown
    logistics = Column(Float, default=0.0)           # Общая = прямая + ПВЗ обратная
    logistics_direct = Column(Float, default=0.0)    # Прямая доставка (AI)
    storage = Column(Float, default=0.0)             # Хранение + Приёмка + Возмещение издержек
    # Other deductions
    penalties = Column(Float, default=0.0)
    uderzhaniya = Column(Float, default=0.0)        # WB прочие удержания/выплаты
    cofinancing = Column(Float, default=0.0)       # скидки/лояльность/промо
    # Advertising (from separate report or API)
    ad_spend = Column(Float, default=0.0)
    # Quantities
    quantity = Column(Integer, default=0)
    return_quantity = Column(Integer, default=0)
    source = Column(String(20), default="api")
    created_at = Column(DateTime, default=_now_msk)


class CostOfGoods(Base):
    """Себестоимость товара по SKU."""
    __tablename__ = "cost_of_goods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(100), nullable=False, unique=True)
    product_name = Column(String(500))
    cost_per_unit = Column(Float, default=0.0)   # себестоимость за единицу
    updated_at = Column(DateTime, default=_now_msk, onupdate=_now_msk)


class AdSpend(Base):
    """Рекламные расходы по дате и кампании."""
    __tablename__ = "ad_spend"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace = Column(String(20), default="wb")
    date = Column(Date, nullable=False)
    campaign_id = Column(String(50))
    campaign_name = Column(String(500))
    campaign_type = Column(String(100))
    amount = Column(Float, default=0.0)
    sku = Column(String(100))     # null если не привязана к SKU
    source = Column(String(20), default="excel")
    created_at = Column(DateTime, default=_now_msk)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace = Column(String(20))
    sync_at = Column(DateTime, default=_now_msk)
    status = Column(String(20))
    records_count = Column(Integer, default=0)
    error_message = Column(String(1000))
    # Upload details
    filename = Column(String(500), default="")
    date_from = Column(Date, nullable=True)
    date_to = Column(Date, nullable=True)
    revenue = Column(Float, default=0.0)


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)
    _migrate()


def _migrate():
    """Add new columns to existing DB without dropping data. Works for both SQLite and PostgreSQL."""
    sales_cols = [
        ("vat_commission", "DOUBLE PRECISION DEFAULT 0.0"),
        ("acquiring",      "DOUBLE PRECISION DEFAULT 0.0"),
        ("penalties",      "DOUBLE PRECISION DEFAULT 0.0"),
        ("uderzhaniya",        "DOUBLE PRECISION DEFAULT 0.0"),
        ("logistics_direct",   "DOUBLE PRECISION DEFAULT 0.0"),
        ("storage",            "DOUBLE PRECISION DEFAULT 0.0"),
        ("cofinancing",    "DOUBLE PRECISION DEFAULT 0.0"),
        ("ad_spend",       "DOUBLE PRECISION DEFAULT 0.0"),
        ("article",        "TEXT DEFAULT ''"),
    ]
    sync_log_cols = [
        ("filename",  "TEXT DEFAULT ''"),
        ("date_from", "DATE"),
        ("date_to",   "DATE"),
        ("revenue",   "DOUBLE PRECISION DEFAULT 0.0"),
    ]
    try:
        with engine.connect() as conn:
            url = str(engine.url)
            if "sqlite" in url:
                result = conn.execute(text("PRAGMA table_info(sales)"))
                existing_sales = [row[1] for row in result.fetchall()]
                for col, typedef in sales_cols:
                    if col not in existing_sales:
                        conn.execute(text(f"ALTER TABLE sales ADD COLUMN {col} REAL DEFAULT 0.0"))
                result2 = conn.execute(text("PRAGMA table_info(sync_log)"))
                existing_log = [row[1] for row in result2.fetchall()]
                for col, typedef in sync_log_cols:
                    if col not in existing_log:
                        conn.execute(text(f"ALTER TABLE sync_log ADD COLUMN {col} TEXT"))
                conn.commit()
            else:
                for col, typedef in sales_cols:
                    conn.execute(text(f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name='sales' AND column_name='{col}'
                            ) THEN
                                ALTER TABLE sales ADD COLUMN {col} {typedef};
                            END IF;
                        END $$;
                    """))
                for col, typedef in sync_log_cols:
                    conn.execute(text(f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name='sync_log' AND column_name='{col}'
                            ) THEN
                                ALTER TABLE sync_log ADD COLUMN {col} {typedef};
                            END IF;
                        END $$;
                    """))
                conn.commit()
    except Exception:
        pass


def get_session():
    return SessionLocal()


def upsert_records(records: list[dict]):
    if not records:
        return 0

    SALE_FIELDS = {c.key for c in SaleRecord.__table__.columns} - {"id", "created_at"}

    session = get_session()
    try:
        count = 0
        for rec in records:
            clean = {k: v for k, v in rec.items() if k in SALE_FIELDS}
            existing = (
                session.query(SaleRecord)
                .filter_by(
                    marketplace=clean.get("marketplace"),
                    date=clean.get("date"),
                    sku=clean.get("sku"),
                )
                .first()
            )
            if existing:
                for k, v in clean.items():
                    setattr(existing, k, v)
            else:
                session.add(SaleRecord(**clean))
                count += 1
        session.commit()

        # Cross-reference: for each sale with an article, if COGS has that article as key,
        # add the WB numeric sku as an additional COGS entry so matching works by sku too.
        try:
            article_to_sku: dict[str, str] = {}
            for rec in records:
                article = str(rec.get("article") or "").strip()
                sku = str(rec.get("sku") or "").strip()
                if article and sku and article != sku:
                    article_to_sku[article] = sku

            if article_to_sku:
                for article, wb_sku in article_to_sku.items():
                    cogs_src = session.query(CostOfGoods).filter_by(sku=article).first()
                    if cogs_src and cogs_src.cost_per_unit > 0:
                        existing_wb = session.query(CostOfGoods).filter_by(sku=wb_sku).first()
                        if existing_wb:
                            existing_wb.cost_per_unit = cogs_src.cost_per_unit
                        else:
                            session.add(CostOfGoods(
                                sku=wb_sku,
                                product_name=cogs_src.product_name,
                                cost_per_unit=cogs_src.cost_per_unit,
                            ))
                session.commit()
        except Exception:
            session.rollback()

        return count
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def upsert_cogs(records: list[dict]) -> int:
    session = get_session()
    try:
        count = 0
        for rec in records:
            sku = str(rec.get("sku", "")).strip()
            if not sku:
                continue
            existing = session.query(CostOfGoods).filter_by(sku=sku).first()
            if existing:
                existing.cost_per_unit = float(rec.get("cost_per_unit", 0))
                existing.product_name = rec.get("product_name", existing.product_name)
            else:
                session.add(CostOfGoods(
                    sku=sku,
                    product_name=rec.get("product_name", ""),
                    cost_per_unit=float(rec.get("cost_per_unit", 0)),
                ))
                count += 1
        session.commit()

        # Cross-reference: find WB numeric SKUs in sales where article matches COGS key,
        # then add duplicate COGS entries keyed by WB numeric SKU.
        # This works regardless of whether sales.article column exists.
        try:
            with engine.connect() as conn:
                # Try with article column first (new schema)
                try:
                    rows = conn.execute(text(
                        "SELECT DISTINCT sku, article FROM sales "
                        "WHERE article IS NOT NULL AND article != ''"
                    )).fetchall()
                    article_to_wb = {str(r[1]): str(r[0]) for r in rows if r[1] != r[0]}
                except Exception:
                    article_to_wb = {}

                if article_to_wb:
                    for article_key, wb_sku in article_to_wb.items():
                        cog = session.query(CostOfGoods).filter_by(sku=article_key).first()
                        if cog and cog.cost_per_unit > 0:
                            wb_entry = session.query(CostOfGoods).filter_by(sku=wb_sku).first()
                            if wb_entry:
                                wb_entry.cost_per_unit = cog.cost_per_unit
                            else:
                                session.add(CostOfGoods(
                                    sku=wb_sku,
                                    product_name=cog.product_name,
                                    cost_per_unit=cog.cost_per_unit,
                                ))
                    session.commit()
        except Exception:
            pass

        return count
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def insert_ad_spend(records: list[dict]) -> int:
    """
    Upsert ad spend records: delete existing records for the same date range
    and marketplace, then insert fresh ones and recalculate sales.ad_spend.
    Re-uploading the same file is safe — no double-counting.
    """
    if not records:
        return 0

    session = get_session()
    try:
        marketplace = records[0].get("marketplace", "wb")
        dates = [r["date"] for r in records]
        date_from = min(dates)
        date_to = max(dates)

        # Remove old records covering this period to allow re-upload
        session.query(AdSpend).filter(
            AdSpend.marketplace == marketplace,
            AdSpend.date >= date_from,
            AdSpend.date <= date_to,
        ).delete(synchronize_session=False)

        # Reset ad_spend on all sales rows for this marketplace
        session.query(SaleRecord).filter_by(marketplace=marketplace).update(
            {"ad_spend": 0.0}, synchronize_session=False
        )

        # Insert fresh records
        for rec in records:
            session.add(AdSpend(
                marketplace=marketplace,
                date=rec["date"],
                campaign_id=str(rec.get("campaign_id", "")),
                campaign_name=rec.get("campaign_name", ""),
                campaign_type=rec.get("campaign_type", ""),
                amount=float(rec.get("amount", 0)),
                sku=rec.get("sku"),
                source=rec.get("source", "excel"),
            ))

        session.flush()

        # Re-aggregate ad spend per SKU from the whole ad_spend table
        sku_totals = (
            session.query(AdSpend.sku, func.sum(AdSpend.amount).label("total"))
            .filter(AdSpend.marketplace == marketplace, AdSpend.sku.isnot(None))
            .group_by(AdSpend.sku)
            .all()
        )
        for sku, total in sku_totals:
            sale_rows = (
                session.query(SaleRecord)
                .filter_by(marketplace=marketplace, sku=sku)
                .all()
            )
            if sale_rows:
                per_row = total / len(sale_rows)
                for row in sale_rows:
                    row.ad_spend = per_row

        session.commit()
        return len(records)
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def log_sync(
    marketplace: str,
    status: str,
    records_count: int = 0,
    error: str = None,
    filename: str = "",
    date_from=None,
    date_to=None,
    revenue: float = 0.0,
):
    session = get_session()
    try:
        entry = SyncLog(
            marketplace=marketplace,
            status=status,
            records_count=records_count,
            error_message=error,
            filename=filename or "",
            date_from=date_from,
            date_to=date_to,
            revenue=revenue,
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()


def delete_sync_log(log_id: int):
    session = get_session()
    try:
        session.query(SyncLog).filter_by(id=log_id).delete()
        session.commit()
    finally:
        session.close()
