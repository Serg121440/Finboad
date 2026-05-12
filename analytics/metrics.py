"""Financial metrics calculation."""

import pandas as pd
import numpy as np
from sqlalchemy import text
from database.db import engine


def load_data(
    date_from=None,
    date_to=None,
    marketplaces: list[str] = None,
    categories: list[str] = None,
) -> pd.DataFrame:
    """Load sales data from DB with optional filters."""
    query = "SELECT * FROM sales WHERE 1=1"
    params = {}

    if date_from:
        query += " AND date >= :date_from"
        params["date_from"] = str(date_from)
    if date_to:
        query += " AND date <= :date_to"
        params["date_to"] = str(date_to)
    if marketplaces:
        placeholders = ", ".join(f":mp{i}" for i in range(len(marketplaces)))
        query += f" AND marketplace IN ({placeholders})"
        for i, mp in enumerate(marketplaces):
            params[f"mp{i}"] = mp
    if categories:
        placeholders = ", ".join(f":cat{i}" for i in range(len(categories)))
        query += f" AND category IN ({placeholders})"
        for i, cat in enumerate(categories):
            params[f"cat{i}"] = cat

    with engine.connect() as conn:
        df = pd.read_sql_query(text(query), conn, params=params)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    for col in ["revenue", "returns", "commission", "logistics", "net_profit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def gross_revenue(df: pd.DataFrame) -> float:
    return df["revenue"].sum()


def net_revenue(df: pd.DataFrame) -> float:
    return df["revenue"].sum() - df["returns"].sum()


def total_net_profit(df: pd.DataFrame) -> float:
    return df["net_profit"].sum()


def margin_by_sku(df: pd.DataFrame) -> pd.DataFrame:
    """Return margin % per SKU."""
    grouped = df.groupby(["sku", "product_name", "category", "marketplace"]).agg(
        revenue=("revenue", "sum"),
        returns=("returns", "sum"),
        commission=("commission", "sum"),
        logistics=("logistics", "sum"),
        net_profit=("net_profit", "sum"),
        quantity=("quantity", "sum"),
        return_quantity=("return_quantity", "sum"),
    ).reset_index()

    grouped["net_revenue"] = grouped["revenue"] - grouped["returns"]
    grouped["margin_pct"] = np.where(
        grouped["net_revenue"] > 0,
        grouped["net_profit"] / grouped["net_revenue"] * 100,
        0,
    ).round(2)
    grouped["return_rate_pct"] = np.where(
        grouped["quantity"] > 0,
        grouped["return_quantity"] / grouped["quantity"] * 100,
        0,
    ).round(2)
    grouped["commission_pct"] = np.where(
        grouped["revenue"] > 0,
        grouped["commission"] / grouped["revenue"] * 100,
        0,
    ).round(2)
    grouped["logistics_per_unit"] = np.where(
        grouped["quantity"] > 0,
        grouped["logistics"] / grouped["quantity"],
        0,
    ).round(2)

    return grouped.sort_values("net_profit", ascending=False)


def revenue_by_day(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby([df["date"].dt.date, "marketplace"])
        .agg(revenue=("revenue", "sum"), net_profit=("net_profit", "sum"))
        .reset_index()
        .rename(columns={"date": "day"})
    )


def marketplace_comparison(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("marketplace")
        .agg(
            revenue=("revenue", "sum"),
            returns=("returns", "sum"),
            commission=("commission", "sum"),
            logistics=("logistics", "sum"),
            net_profit=("net_profit", "sum"),
            quantity=("quantity", "sum"),
        )
        .reset_index()
        .assign(
            net_revenue=lambda x: x["revenue"] - x["returns"],
            margin_pct=lambda x: np.where(
                x["revenue"] > 0, x["net_profit"] / x["revenue"] * 100, 0
            ).round(2),
        )
    )


def cost_structure(df: pd.DataFrame) -> dict:
    totals = {
        "commission": df["commission"].sum(),
        "logistics": df["logistics"].sum(),
        "returns": df["returns"].sum(),
        "net_profit": df["net_profit"].sum(),
    }
    total_revenue = df["revenue"].sum()
    if total_revenue > 0:
        totals["commission_pct"] = totals["commission"] / total_revenue * 100
        totals["logistics_pct"] = totals["logistics"] / total_revenue * 100
        totals["returns_pct"] = totals["returns"] / total_revenue * 100
    return totals


def abc_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """ABC analysis by net profit contribution."""
    sku_df = margin_by_sku(df)[["sku", "product_name", "net_profit"]].copy()
    sku_df = sku_df[sku_df["net_profit"] > 0].sort_values("net_profit", ascending=False)

    total = sku_df["net_profit"].sum()
    sku_df["cumulative_pct"] = sku_df["net_profit"].cumsum() / total * 100

    def classify(pct):
        if pct <= 80:
            return "A"
        elif pct <= 95:
            return "B"
        return "C"

    sku_df["abc_class"] = sku_df["cumulative_pct"].apply(classify)
    return sku_df.reset_index(drop=True)


def top_skus_by_profit(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return margin_by_sku(df).head(n)


def get_all_categories(df: pd.DataFrame) -> list[str]:
    cats = df["category"].dropna().unique().tolist()
    return sorted(c for c in cats if c)


def get_date_range(df: pd.DataFrame) -> tuple:
    if df.empty:
        return None, None
    return df["date"].min().date(), df["date"].max().date()
