from sqlalchemy import (
    create_engine, Column, String, Float, Date, DateTime, Integer, text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import DATABASE_URL

Base = declarative_base()


class SaleRecord(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    sku = Column(String(100), nullable=False)
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
    # Logistics (total)
    logistics = Column(Float, default=0.0)
    # Other deductions
    penalties = Column(Float, default=0.0)
    cofinancing = Column(Float, default=0.0)       # скидки/лояльность/промо
    # Advertising (from separate report or API)
    ad_spend = Column(Float, default=0.0)
    # Quantities
    quantity = Column(Integer, default=0)
    return_quantity = Column(Integer, default=0)
    source = Column(String(20), default="api")
    created_at = Column(DateTime, default=datetime.utcnow)


class CostOfGoods(Base):
    """Себестоимость товара по SKU."""
    __tablename__ = "cost_of_goods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(100), nullable=False, unique=True)
    product_name = Column(String(500))
    cost_per_unit = Column(Float, default=0.0)   # себестоимость за единицу
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace = Column(String(20))
    sync_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20))
    records_count = Column(Integer, default=0)
    error_message = Column(String(1000))


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)
    _migrate()


def _migrate():
    """Add new columns to existing DB without dropping data. Works for both SQLite and PostgreSQL."""
    new_cols = [
        ("vat_commission", "DOUBLE PRECISION DEFAULT 0.0"),
        ("acquiring",      "DOUBLE PRECISION DEFAULT 0.0"),
        ("penalties",      "DOUBLE PRECISION DEFAULT 0.0"),
        ("cofinancing",    "DOUBLE PRECISION DEFAULT 0.0"),
        ("ad_spend",       "DOUBLE PRECISION DEFAULT 0.0"),
    ]
    try:
        with engine.connect() as conn:
            url = str(engine.url)
            if "sqlite" in url:
                result = conn.execute(text("PRAGMA table_info(sales)"))
                existing = [row[1] for row in result.fetchall()]
                for col, typedef in new_cols:
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE sales ADD COLUMN {col} REAL DEFAULT 0.0"))
                conn.commit()
            else:
                # PostgreSQL — use IF NOT EXISTS via DO block
                for col, typedef in new_cols:
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
        return count
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def insert_ad_spend(records: list[dict]) -> int:
    """
    Save ad spend records and update ad_spend column in sales table
    for SKU-linked records.
    """
    session = get_session()
    try:
        count = 0
        for rec in records:
            session.add(AdSpend(
                marketplace=rec.get("marketplace", "wb"),
                date=rec["date"],
                campaign_id=str(rec.get("campaign_id", "")),
                campaign_name=rec.get("campaign_name", ""),
                campaign_type=rec.get("campaign_type", ""),
                amount=float(rec.get("amount", 0)),
                sku=rec.get("sku"),
                source=rec.get("source", "excel"),
            ))
            count += 1

            # Update ad_spend on the matching sales row when SKU is known
            sku = rec.get("sku")
            if sku:
                rows = (
                    session.query(SaleRecord)
                    .filter_by(marketplace=rec.get("marketplace", "wb"), sku=sku)
                    .all()
                )
                spend_per_row = float(rec.get("amount", 0)) / len(rows) if rows else 0
                for row in rows:
                    row.ad_spend = (row.ad_spend or 0) + spend_per_row

        session.commit()
        return count
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def log_sync(marketplace: str, status: str, records_count: int = 0, error: str = None):
    session = get_session()
    try:
        entry = SyncLog(
            marketplace=marketplace,
            status=status,
            records_count=records_count,
            error_message=error,
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()
