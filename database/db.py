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
    revenue = Column(Float, default=0.0)
    returns = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    logistics = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    quantity = Column(Integer, default=0)
    return_quantity = Column(Integer, default=0)
    source = Column(String(20), default="api")
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


def get_session():
    return SessionLocal()


def upsert_records(records: list[dict]):
    """Insert or replace sales records (deduplicate by marketplace+date+sku)."""
    if not records:
        return 0

    session = get_session()
    try:
        count = 0
        for rec in records:
            existing = (
                session.query(SaleRecord)
                .filter_by(
                    marketplace=rec["marketplace"],
                    date=rec["date"],
                    sku=rec["sku"],
                )
                .first()
            )
            if existing:
                for k, v in rec.items():
                    setattr(existing, k, v)
            else:
                session.add(SaleRecord(**rec))
                count += 1
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
