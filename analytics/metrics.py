"""Financial metrics calculation."""

import pandas as pd
import numpy as np
import streamlit as st
from sqlalchemy import text
from database.db import engine


@st.cache_data(ttl=300, show_spinner=False)
def load_data(
    date_from=None,
    date_to=None,
    marketplaces: tuple[str, ...] | None = None,
    categories: tuple[str, ...] | None = None,
) -> pd.DataFrame:
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
    for col in ["revenue", "returns", "commission", "vat_commission", "acquiring",
                "logistics", "logistics_direct", "storage",
                "penalties", "uderzhaniya", "cofinancing", "ad_spend", "net_profit"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_cogs() -> dict[str, float]:
    """Return {wb_numeric_sku: cost_per_unit}.

    COGS keys are vendor articles (e.g. "СГ000005550") stored in uppercase.
    Cross-references them to WB numeric SKUs via sales.article (also uppercase).
    """
    try:
        with engine.connect() as conn:
            cogs = pd.read_sql_query(
                text("SELECT sku, cost_per_unit FROM cost_of_goods"), conn
            )
            # Normalize stored keys to uppercase (handles legacy lowercase entries)
            result: dict[str, float] = {
                str(r["sku"]).strip().upper(): r["cost_per_unit"]
                for _, r in cogs.iterrows()
            }

            # Cross-reference vendor article → WB numeric SKU via sales.article
            try:
                sales = pd.read_sql_query(
                    text("SELECT DISTINCT sku, article FROM sales "
                         "WHERE article IS NOT NULL AND article != ''"), conn
                )
                for _, row in sales.iterrows():
                    wb_sku = str(row["sku"]).strip()
                    if wb_sku in result:
                        continue
                    article_upper = str(row.get("article") or "").strip().upper()
                    if article_upper and article_upper in result:
                        result[wb_sku] = result[article_upper]
            except Exception:
                pass

            return result
    except Exception:
        return {}


def load_ad_spend(date_from=None, date_to=None) -> pd.DataFrame:
    query = "SELECT * FROM ad_spend WHERE 1=1"
    params = {}
    if date_from:
        query += " AND date >= :date_from"
        params["date_from"] = str(date_from)
    if date_to:
        query += " AND date <= :date_to"
        params["date_to"] = str(date_to)
    try:
        with engine.connect() as conn:
            return pd.read_sql_query(text(query), conn, params=params)
    except Exception:
        return pd.DataFrame()


def gross_revenue(df: pd.DataFrame) -> float:
    return df["revenue"].sum()


def net_revenue(df: pd.DataFrame) -> float:
    return df["revenue"].sum() - df["returns"].sum()


def total_net_profit(df: pd.DataFrame) -> float:
    return df["net_profit"].sum()


def total_ad_spend(df: pd.DataFrame) -> float:
    return df["ad_spend"].sum()


def total_cogs(df: pd.DataFrame, cogs_map: dict) -> float:
    total = 0.0
    for _, row in df.iterrows():
        cost = cogs_map.get(str(row["sku"]), 0.0)
        total += cost * int(row.get("quantity", 0))
    return total


def gross_profit(df: pd.DataFrame, cogs_map: dict) -> float:
    """Валовая прибыль = нетто-выручка - себестоимость."""
    return net_revenue(df) - total_cogs(df, cogs_map)


def real_profit(df: pd.DataFrame, cogs_map: dict) -> float:
    """Реальная прибыль = К перечислению - себестоимость - реклама."""
    return total_net_profit(df) - total_cogs(df, cogs_map) - total_ad_spend(df)


def drr(df: pd.DataFrame) -> float:
    """ДРР = рекламные расходы / выручка × 100."""
    rev = gross_revenue(df)
    ads = total_ad_spend(df)
    return ads / rev * 100 if rev > 0 else 0.0


def margin_by_sku(df: pd.DataFrame, cogs_map: dict = None) -> pd.DataFrame:
    cogs_map = cogs_map or {}

    grouped = df.groupby(["sku", "product_name", "category", "marketplace"]).agg(
        revenue=("revenue", "sum"),
        returns=("returns", "sum"),
        commission=("commission", "sum"),
        vat_commission=("vat_commission", "sum"),
        acquiring=("acquiring", "sum"),
        logistics=("logistics", "sum"),
        logistics_direct=("logistics_direct", "sum"),
        storage=("storage", "sum"),
        penalties=("penalties", "sum"),
        uderzhaniya=("uderzhaniya", "sum"),
        cofinancing=("cofinancing", "sum"),
        ad_spend=("ad_spend", "sum"),
        net_profit=("net_profit", "sum"),
        quantity=("quantity", "sum"),
        return_quantity=("return_quantity", "sum"),
    ).reset_index()

    grouped["net_revenue"] = grouped["revenue"] - grouped["returns"]
    grouped["cogs_total"] = grouped.apply(
        lambda r: cogs_map.get(str(r["sku"]), 0.0) * r["quantity"], axis=1
    )
    grouped["real_profit"] = grouped["net_profit"] - grouped["cogs_total"] - grouped["ad_spend"]

    grouped["margin_pct"] = np.where(
        grouped["net_revenue"] > 0,
        grouped["net_profit"] / grouped["net_revenue"] * 100,
        0,
    ).round(2)
    grouped["real_margin_pct"] = np.where(
        grouped["net_revenue"] > 0,
        grouped["real_profit"] / grouped["net_revenue"] * 100,
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
    grouped["drr_pct"] = np.where(
        grouped["revenue"] > 0,
        grouped["ad_spend"] / grouped["revenue"] * 100,
        0,
    ).round(2)

    return grouped.sort_values("real_profit", ascending=False)


def revenue_by_day(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby([df["date"].dt.date, "marketplace"])
        .agg(revenue=("revenue", "sum"), net_profit=("net_profit", "sum"))
        .reset_index()
        .rename(columns={"date": "day"})
    )


def marketplace_comparison(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby("marketplace")
        .agg(
            revenue=("revenue", "sum"),
            returns=("returns", "sum"),
            commission=("commission", "sum"),
            vat_commission=("vat_commission", "sum"),
            acquiring=("acquiring", "sum"),
            logistics=("logistics", "sum"),
            storage=("storage", "sum"),
            penalties=("penalties", "sum"),
            uderzhaniya=("uderzhaniya", "sum"),
            ad_spend=("ad_spend", "sum"),
            net_profit=("net_profit", "sum"),
            quantity=("quantity", "sum"),
        )
        .reset_index()
    )
    agg["net_revenue"] = agg["revenue"] - agg["returns"]
    agg["margin_pct"] = np.where(
        agg["net_revenue"] > 0,
        agg["net_profit"] / agg["net_revenue"] * 100,
        0,
    ).round(2)
    agg["total_costs"] = agg["commission"] + agg["vat_commission"] + agg["acquiring"] + agg["logistics"] + agg["storage"] + agg["penalties"] + agg["uderzhaniya"]
    return agg


def cost_structure(df: pd.DataFrame) -> dict:
    total_revenue = df["revenue"].sum()
    d = {
        "commission":    df["commission"].sum(),
        "vat_commission": df["vat_commission"].sum(),
        "acquiring":     df["acquiring"].sum(),
        "logistics":          df["logistics"].sum(),
        "logistics_direct":   df["logistics_direct"].sum(),
        "storage":            df["storage"].sum(),
        "penalties":     df["penalties"].sum(),
        "uderzhaniya":   df["uderzhaniya"].sum(),
        "cofinancing":   df["cofinancing"].sum(),
        "ad_spend":      df["ad_spend"].sum(),
        "returns":       df["returns"].sum(),
        "net_profit":    df["net_profit"].sum(),
    }
    if total_revenue > 0:
        for k in ["commission", "vat_commission", "acquiring",
                  "logistics", "logistics_direct", "storage",
                  "penalties", "uderzhaniya", "cofinancing", "ad_spend", "returns", "net_profit"]:
            d[f"{k}_pct"] = d[k] / total_revenue * 100
    return d


def abc_analysis(df: pd.DataFrame, cogs_map: dict = None) -> pd.DataFrame:
    cogs_map = cogs_map or {}
    profit_col = "real_profit" if cogs_map else "net_profit"
    margin = margin_by_sku(df, cogs_map)
    sku_df = margin[["sku", "product_name", profit_col]].copy()
    if profit_col != "net_profit":
        sku_df = sku_df.rename(columns={profit_col: "net_profit"})
    sku_df = sku_df[sku_df["net_profit"] > 0].sort_values("net_profit", ascending=False)

    if sku_df.empty:
        return sku_df

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


def top_skus_by_profit(df: pd.DataFrame, cogs_map: dict = None, n: int = 20) -> pd.DataFrame:
    return margin_by_sku(df, cogs_map).head(n)


def get_all_categories(df: pd.DataFrame) -> list[str]:
    cats = df["category"].dropna().unique().tolist()
    return sorted(c for c in cats if c)


def get_date_range(df: pd.DataFrame) -> tuple:
    if df.empty:
        return None, None
    return df["date"].min().date(), df["date"].max().date()
