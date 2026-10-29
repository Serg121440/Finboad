"""P&L calculation from stored data. Pure pandas, no Streamlit.

Main result is a fact table with one row per (cabinet, month, sku) and money
columns for every P&L line, from which every page aggregates what it needs:
по маркетплейсу, по кабинету, по месяцам, по товарам.

Signs: revenue > 0, all costs < 0, profit = sum of the row.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from pnl.categories import CATEGORIES, line_of
from pnl.wb import normalize_article
from pnl.tax import MonthInput, compute_entity_year

MONEY_LINES = ["revenue", "commission", "logistics", "storage", "penalties", "services",
               "other", "ads", "cogs", "vat", "tax"]

LINE_TITLES = {
    "revenue": "Выручка (цена продавца)",
    "commission": "Комиссия МП с эквайрингом",
    "logistics": "Логистика",
    "storage": "Хранение и склад",
    "penalties": "Штрафы и удержания",
    "services": "Подписки и сервисы",
    "other": "Компенсации и прочее",
    "ads": "Реклама",
    "cogs": "Себестоимость",
    "vat": "НДС",
    "tax": "Налог",
    "mp_result": "К перечислению после рекламы",
    "profit": "Прибыль до постоянных расходов",
}

OZON_CPC_TYPES = {"Оплата за клик"}
OZON_CPO_TYPES = {"Продвижение товара", "Продвижение с оплатой за заказ"}


@dataclass
class Data:
    """Frames loaded from the database (see pnl.data.load)."""
    cabinets: pd.DataFrame            # id, marketplace, name, entity_id
    entities: pd.DataFrame            # id, name, kind
    tax_settings: pd.DataFrame        # entity_id, valid_from, regime, usn_rate, vat_mode, ...
    ledger: pd.DataFrame              # cabinet_id, date, sku, category, amount, qty, posting, raw_type
    ads: pd.DataFrame                 # cabinet_id, date, sku, amount, kind, campaign_id
    campaigns: pd.DataFrame           # cabinet_id, campaign_id, type
    orders: pd.DataFrame              # cabinet_id, date, sku, qty, amount, cancelled
    products: pd.DataFrame            # cabinet_id, sku, article, name, category, vat10
    cogs: pd.DataFrame                # article, cabinet_id, valid_from, cost
    fixed: pd.DataFrame               # entity_id, cabinet_id, month, item, amount
    date_from: date = None
    date_to: date = None
    extra: dict = field(default_factory=dict)


NO_SKU = ""  # rows not tied to a product (общие расходы)


def _skus(df: pd.DataFrame) -> pd.DataFrame:
    if "sku" in df:
        df = df.copy()
        df["sku"] = df["sku"].map(lambda v: NO_SKU if v is None or (isinstance(v, float) and np.isnan(v))
                                  else str(v).split(".")[0] if isinstance(v, float) else str(v))
    return df


def normalize(d: "Data") -> "Data":
    """Same dtypes everywhere: sku as str ('' = no product), ids as int."""
    for name in ("ledger", "ads", "orders", "products"):
        setattr(d, name, _skus(getattr(d, name)))
    return d


def _month(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.to_period("M").dt.to_timestamp().dt.date


# ── ads ──────────────────────────────────────────────────────────────────────

def ads_by_sku(d: Data) -> pd.DataFrame:
    """Ad money per (cabinet_id, month, sku); sku None = общий расход кабинета.

    Ozon: the money is the ad lines of the accrual report; click money is split by
    the click statistics per SKU, «оплата за заказ: выбранные товары» by the
    orders report, everything else («все товары», brand shelf, …) stays common.
    WB: the ad cabinet spend (not in the realization report).
    """
    out = []
    led = d.ledger[d.ledger["category"] == "ads_mp"].copy()
    if not led.empty:
        led["month"] = _month(led["date"])
        camp_type = {}
        if not d.campaigns.empty:
            camp_type = {(r.cabinet_id, str(r.campaign_id)): r.type for r in d.campaigns.itertuples()}

        def pool(r):
            if r.sku != NO_SKU:
                return "direct"
            if r.raw_type in OZON_CPC_TYPES:
                return "cpc"
            if r.raw_type in OZON_CPO_TYPES and camp_type.get((r.cabinet_id, str(r.posting))) == "SEARCH_PROMO":
                return "cpo"
            return "common"

        led["pool"] = [pool(r) for r in led.itertuples()]
        alloc = d.ads[d.ads["kind"].isin(["alloc_cpc", "alloc_cpo"])].copy()
        if not alloc.empty:
            alloc["month"] = _month(alloc["date"])
            alloc["pool"] = alloc["kind"].str.replace("alloc_", "", regex=False)
            w = alloc.groupby(["cabinet_id", "month", "pool", "sku"], as_index=False)["amount"].sum()
            w["share"] = w["amount"] / w.groupby(["cabinet_id", "month", "pool"])["amount"].transform("sum")
        else:
            w = pd.DataFrame(columns=["cabinet_id", "month", "pool", "sku", "share"])

        money = led.groupby(["cabinet_id", "month", "pool", "sku"], dropna=False, as_index=False)["amount"].sum()
        direct = money[money["pool"] == "direct"][["cabinet_id", "month", "sku", "amount"]]
        out.append(direct)
        for p in ("cpc", "cpo"):
            m = money[money["pool"] == p].groupby(["cabinet_id", "month"], as_index=False)["amount"].sum()
            if m.empty:
                continue
            split = m.merge(w[w["pool"] == p][["cabinet_id", "month", "sku", "share"]],
                            on=["cabinet_id", "month"], how="left")
            has = split["share"].notna()
            split.loc[has, "amount"] = split.loc[has, "amount"] * split.loc[has, "share"]
            split.loc[~has, "sku"] = NO_SKU
            out.append(split[["cabinet_id", "month", "sku", "amount"]])
        common = money[money["pool"] == "common"].groupby(["cabinet_id", "month"], as_index=False)["amount"].sum()
        common["sku"] = NO_SKU
        out.append(common[["cabinet_id", "month", "sku", "amount"]])

    spend = d.ads[d.ads["kind"] == "spend"].copy()
    if not spend.empty:
        spend["month"] = _month(spend["date"])
        spend["amount"] = -spend["amount"]
        out.append(spend.groupby(["cabinet_id", "month", "sku"], dropna=False, as_index=False)["amount"].sum())

    if not out:
        return pd.DataFrame(columns=["cabinet_id", "month", "sku", "ads"])
    res = _skus(pd.concat(out, ignore_index=True))
    res = res.groupby(["cabinet_id", "month", "sku"], as_index=False)["amount"].sum()
    return res.rename(columns={"amount": "ads"})


# ── cost of goods ────────────────────────────────────────────────────────────

def cogs_lines(d: Data, sales: pd.DataFrame) -> pd.DataFrame:
    """−qty × cost at the sale date, per ledger sale/return row. Adds cost, cogs, has_cost.

    A cabinet-specific cost wins over the cost for all cabinets."""
    sales = sales.reset_index(drop=True).copy()
    sales["cost"] = np.nan
    if not d.cogs.empty and not sales.empty:
        cg = d.cogs.copy()
        # «00000002479» in one source and «2479» in another are the same article
        sales["article"] = sales["article"].map(normalize_article)
        cg["article"] = cg["article"].map(normalize_article)
        cg["valid_from"] = pd.to_datetime(cg["valid_from"])
        sales["_dt"] = pd.to_datetime(sales["date"])
        sales["_i"] = sales.index
        for scope in ("cabinet", "global"):
            part = cg[cg["cabinet_id"].notna()] if scope == "cabinet" else cg[cg["cabinet_id"].isna()]
            left = sales[sales["cost"].isna()].sort_values("_dt")
            if part.empty or left.empty:
                continue
            by = ["article", "cabinet_id"] if scope == "cabinet" else ["article"]
            right = part.sort_values("valid_from")[by + ["valid_from", "cost"]].rename(columns={"cost": "_c"})
            if scope == "cabinet":
                right["cabinet_id"] = right["cabinet_id"].astype(int)
                left = left.assign(cabinet_id=left["cabinet_id"].astype(int))
            m = pd.merge_asof(left, right, left_on="_dt", right_on="valid_from", by=by,
                              direction="backward")
            hit = m[m["_c"].notna()]
            sales.loc[hit["_i"].values, "cost"] = hit["_c"].values
        sales = sales.drop(columns=["_dt", "_i"])
    sales["has_cost"] = sales["cost"].notna()
    sales["cogs"] = -(sales["qty"] * sales["cost"].fillna(0))
    return sales


# ── fact table ───────────────────────────────────────────────────────────────

def fact_table(d: Data) -> pd.DataFrame:
    """Rows (cabinet_id, month, sku) with money lines, quantities and cost flags."""
    led = d.ledger.copy()
    if led.empty:
        led = pd.DataFrame(columns=["cabinet_id", "date", "sku", "category", "amount", "qty"])
    led["month"] = _month(led["date"]) if len(led) else []
    led["line"] = led["category"].map(line_of)
    led = led[~led["line"].isin(["ads", "excluded"])]

    keys = ["cabinet_id", "month", "sku"]
    money = led.pivot_table(index=keys, columns="line", values="amount", aggfunc="sum",
                            fill_value=0, dropna=False).reset_index() if len(led) else pd.DataFrame(columns=keys)
    money.columns.name = None

    # acquiring is part of commission but is charged per order, not per sale
    acq = led[led["category"] == "acquiring"].groupby(keys, dropna=False, as_index=False)["amount"].sum() \
        .rename(columns={"amount": "acquiring"})

    sales = led[led["category"].isin(["sale", "return"])].copy()
    sales = sales.merge(d.products[["cabinet_id", "sku", "article"]], on=["cabinet_id", "sku"], how="left")
    sales["article"] = sales["article"].fillna("")
    sales = cogs_lines(d, sales)
    sales["sold"] = sales["qty"].clip(lower=0)
    sales["returned"] = (-sales["qty"]).clip(lower=0)
    sales["sales_gross"] = sales["amount"].clip(lower=0)
    sales["cost_missing_qty"] = np.where(sales["has_cost"], 0, sales["qty"])
    q = sales.groupby(keys, dropna=False, as_index=False)[
        ["sold", "returned", "sales_gross", "cogs", "cost_missing_qty"]].sum()

    ads = ads_by_sku(d)
    f = money.merge(q, on=keys, how="outer").merge(ads, on=keys, how="outer").merge(acq, on=keys, how="outer")
    for c in MONEY_LINES + ["sold", "returned", "sales_gross", "cost_missing_qty", "acquiring"]:
        if c not in f:
            f[c] = 0.0
        f[c] = f[c].fillna(0.0)
    f["net_qty"] = f["sold"] - f["returned"]
    return f


def orders_table(d: Data) -> pd.DataFrame:
    o = d.orders.copy()
    if o.empty:
        return pd.DataFrame(columns=["cabinet_id", "month", "sku", "ordered_qty", "ordered_sum",
                                     "cancelled_qty", "cancelled_sum"])
    o["month"] = _month(o["date"])
    o["c_qty"] = np.where(o["cancelled"], o["qty"], 0)
    o["c_sum"] = np.where(o["cancelled"], o["amount"], 0)
    return o.groupby(["cabinet_id", "month", "sku"], as_index=False).agg(
        ordered_qty=("qty", "sum"), ordered_sum=("amount", "sum"),
        cancelled_qty=("c_qty", "sum"), cancelled_sum=("c_sum", "sum"))


# ── taxes ────────────────────────────────────────────────────────────────────

def _settings_for(d: Data, entity_id, month: date) -> dict | None:
    ts = d.tax_settings[d.tax_settings["entity_id"] == entity_id]
    ts = ts[pd.to_datetime(ts["valid_from"]) <= pd.Timestamp(month) + pd.offsets.MonthEnd(0)]
    if ts.empty:
        return None
    r = ts.sort_values("valid_from").iloc[-1]
    return {"regime": r["regime"], "usn_rate": r.get("usn_rate"), "vat_mode": r.get("vat_mode") or "auto",
            "has_employees": bool(r.get("has_employees")),
            "ip_contrib_monthly": float(r.get("ip_contrib_monthly") or 0),
            "prior_year_revenue": float(r.get("vat_vs_prior_year") or 0)}


def entity_month_taxes(d: Data, f_all: pd.DataFrame, fixed_em: pd.DataFrame) -> pd.DataFrame:
    """VAT and income tax per (entity_id, month) from year-to-date facts."""
    cab_entity = dict(zip(d.cabinets["id"], d.cabinets["entity_id"]))
    f = f_all.copy()
    f["entity_id"] = f["cabinet_id"].map(cab_entity)
    vat10 = set()
    if not d.products.empty:
        vat10 = {(r.cabinet_id, r.sku) for r in d.products[d.products["vat10"].fillna(False)].itertuples()}
    f["rev10"] = [rv if (c, s) in vat10 else 0.0 for c, s, rv in zip(f["cabinet_id"], f["sku"], f["revenue"])]
    cost_cols = ["commission", "logistics", "storage", "penalties", "services", "other", "ads"]

    rows = []
    for ent, fe in f[f["entity_id"].notna()].groupby("entity_id"):
        fe = fe.assign(year=pd.to_datetime(fe["month"]).dt.year)
        for year, fy in fe.groupby("year"):
            last = pd.Timestamp(max(fy["month"])).month
            full = [date(int(year), m, 1) for m in range(1, last + 1)]
            inputs, settings = [], {}
            for mo in full:
                fm = fy[fy["month"] == mo]
                fixed = 0.0
                if not fixed_em.empty:
                    fixed = float(fixed_em[(fixed_em["entity_id"] == ent) & (fixed_em["month"] == mo)]["amount"].sum())
                inputs.append(MonthInput(int(year), mo.month, float(fm["revenue"].sum()), float(fm["rev10"].sum()),
                                         float(-fm[cost_cols].sum().sum()), float(-fm["cogs"].sum()), fixed))
                st = _settings_for(d, ent, mo)
                settings[mo.month] = st or {"regime": "NONE"}
            if all(v["regime"] == "NONE" for v in settings.values()):
                continue
            res = compute_entity_year("NONE", inputs, settings_by_month=settings)
            for mo, mi, mt in zip(full, inputs, res):
                rows.append({"entity_id": ent, "month": mo, "vat_mode": mt.vat_mode, "vat": mt.vat,
                             "tax": mt.tax, "note": mt.note, "month_revenue": mi.revenue})
    return pd.DataFrame(rows, columns=["entity_id", "month", "vat_mode", "vat", "tax", "note", "month_revenue"])


def allocate_taxes(d: Data, f: pd.DataFrame, taxes: pd.DataFrame) -> pd.DataFrame:
    """Spread each entity-month VAT and tax over period rows by their share of the month revenue."""
    f = f.copy()
    f["vat"] = 0.0
    f["tax"] = 0.0
    if taxes.empty or f.empty:
        return f
    cab_entity = dict(zip(d.cabinets["id"], d.cabinets["entity_id"]))
    ent = f["cabinet_id"].map(cab_entity)
    t = taxes.set_index(["entity_id", "month"])
    for i, (e, mo, rev) in enumerate(zip(ent, f["month"], f["revenue"])):
        if pd.isna(e) or (e, mo) not in t.index:
            continue
        row = t.loc[(e, mo)]
        total = row["month_revenue"]
        if total > 0 and rev > 0:
            f.iat[i, f.columns.get_loc("vat")] = -row["vat"] * rev / total
            f.iat[i, f.columns.get_loc("tax")] = -row["tax"] * rev / total
    return f


# ── fixed costs ──────────────────────────────────────────────────────────────

def fixed_costs(d: Data) -> pd.DataFrame:
    """Fixed costs prorated to the selected period, per (entity_id, cabinet_id, month, item)."""
    fx = d.fixed.copy()
    if fx.empty:
        return pd.DataFrame(columns=["entity_id", "cabinet_id", "month", "item", "amount", "full_amount"])
    fx["month"] = pd.to_datetime(fx["month"]).dt.date
    shares = []
    for mo in fx["month"]:
        start, end = mo, (pd.Timestamp(mo) + pd.offsets.MonthEnd(0)).date()
        a, b = max(start, d.date_from), min(end, d.date_to)
        days = (end - start).days + 1
        shares.append(max(0, (b - a).days + 1) / days)
    fx["full_amount"] = fx["amount"]
    fx["amount"] = fx["amount"] * shares
    return fx[fx["amount"] != 0]


# ── public API ───────────────────────────────────────────────────────────────

@dataclass
class Result:
    facts: pd.DataFrame        # (cabinet_id, month, sku) rows inside the period
    orders: pd.DataFrame       # (cabinet_id, month, sku) orders inside the period
    fixed: pd.DataFrame        # fixed costs prorated to the period
    taxes: pd.DataFrame        # per entity/month
    cabinets: pd.DataFrame
    products: pd.DataFrame


def _in_period(df: pd.DataFrame, d: Data) -> pd.DataFrame:
    if df.empty:
        return df
    dt = pd.to_datetime(df["date"]).dt.date
    return df[(dt >= d.date_from) & (dt <= d.date_to)]


def compute(d: Data) -> Result:
    """d holds data from Jan 1 of date_from's year (YTD taxes need it); the result
    covers [d.date_from, d.date_to]."""
    d = normalize(d)
    f_all = fact_table(d)
    fx_all = d.fixed.copy()
    if not fx_all.empty:
        fx_all["month"] = pd.to_datetime(fx_all["month"]).dt.date
        cab_entity = dict(zip(d.cabinets["id"], d.cabinets["entity_id"]))
        fx_all["entity_id"] = fx_all["entity_id"].fillna(fx_all["cabinet_id"].map(cab_entity))
        fx_em = fx_all.groupby(["entity_id", "month"], as_index=False)["amount"].sum()
    else:
        fx_em = pd.DataFrame(columns=["entity_id", "month", "amount"])
    taxes = entity_month_taxes(d, f_all, fx_em)

    dp = Data(**{**d.__dict__, "ledger": _in_period(d.ledger, d), "ads": _in_period(d.ads, d),
                 "orders": _in_period(d.orders, d)})
    f = allocate_taxes(d, fact_table(dp), taxes)
    f["mp_result"] = f[["revenue", "commission", "logistics", "storage", "penalties",
                        "services", "other", "ads"]].sum(axis=1)
    f["profit"] = f["mp_result"] + f["cogs"] + f["vat"] + f["tax"]
    lo = d.date_from.replace(day=1)
    taxes = taxes[pd.to_datetime(taxes["month"]) >= pd.Timestamp(lo)] if not taxes.empty else taxes
    o = orders_table(dp)
    sel = d.extra.get("selected")
    if sel:
        f = f[f["cabinet_id"].isin(sel)]
        o = o[o["cabinet_id"].isin(sel)]
    return Result(f.reset_index(drop=True), o, fixed_costs(d), taxes, d.cabinets, d.products)


def summarize(facts: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    cols = MONEY_LINES + ["mp_result", "profit", "sold", "returned", "net_qty", "sales_gross",
                          "cost_missing_qty", "acquiring"]
    g = facts.groupby(by, dropna=False, as_index=False)[cols].sum()
    rev = g["revenue"].replace(0, np.nan)
    g["margin"] = g["profit"] / rev
    g["drr"] = -g["ads"] / rev
    g["roi"] = g["profit"] / (-g["cogs"]).replace(0, np.nan)
    return g
