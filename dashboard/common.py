"""Access control, sidebar filters, cached calculation and formatting shared by all pages."""

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core import config
from core.db import session
from core.models import Cabinet, LegalEntity, ShareLink, now_msk
from pnl.engine import compute, summarize, NO_SKU

MP_NAMES = {"ozon": "Ozon", "wb": "Wildberries"}


# ── formatting ───────────────────────────────────────────────────────────────

def rub(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    v = round(float(v))
    return f"{v + 0:,.0f}".replace(",", " ") + " ₽"


def pct(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:.1f} %".replace(".", ",")


def num(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.0f}".replace(",", " ")


# ── access ───────────────────────────────────────────────────────────────────

@dataclass
class Access:
    owner: bool
    cabinet_ids: list[int] = field(default_factory=list)   # [] = all
    hide_cogs: bool = False
    label: str = ""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_share_token() -> str:
    return secrets.token_urlsafe(24)


def _share_access(token: str) -> Access | None:
    with session() as s:
        link = s.scalars(select(ShareLink).where(ShareLink.token_hash == hash_token(token))).first()
        if not link or link.revoked or (link.expires_at and link.expires_at < now_msk()):
            return None
        if "share_seen" not in st.session_state:
            link.uses = (link.uses or 0) + 1
            link.last_used_at = now_msk()
            st.session_state["share_seen"] = True
        return Access(owner=False, cabinet_ids=json.loads(link.cabinet_ids or "[]"),
                      hide_cogs=bool(link.hide_cogs), label=link.label or "")


OWNER_COOKIE = "fb_owner"
COOKIE_DAYS = 30


def _owner_token() -> str:
    """Signed owner token for the login cookie; changes when the password changes."""
    key = (config.APP_SECRET or config.OWNER_PASSWORD).encode()
    return hmac.new(key, ("finboard-owner:" + config.OWNER_PASSWORD).encode(), hashlib.sha256).hexdigest()


def _cookie_script(value: str, days: int) -> None:
    """Set a cookie on the app's own origin (component iframes share the origin)."""
    import streamlit.components.v1 as components
    secure = "; Secure" if (st.context.headers.get("X-Forwarded-Proto") == "https") else ""
    components.html(
        f"<script>window.parent.document.cookie = '{OWNER_COOKIE}={value}; path=/; "
        f"max-age={days * 86400}; SameSite=Lax{secure}';</script>", height=0)


def remember_login() -> None:
    """Call once per page run: writes the login cookie right after a password login."""
    if st.session_state.pop("set_owner_cookie", False):
        _cookie_script(_owner_token(), COOKIE_DAYS)


def logout() -> None:
    _cookie_script("", 0)
    st.session_state.pop("owner_ok", None)
    st.session_state["logged_out"] = True


def require_access() -> Access:
    """Owner login by password (remembered in a cookie for 30 days),
    or read-only access by ?share=<token>."""
    token = st.query_params.get("share") or st.session_state.get("share_token")
    if token:
        st.session_state["share_token"] = token
        acc = _share_access(token)
        if acc is None:
            st.error("Ссылка недействительна: срок истёк или доступ отозван.")
            st.stop()
        return acc
    if not config.OWNER_PASSWORD or st.session_state.get("owner_ok"):
        return Access(owner=True)
    cookie = st.context.cookies.get(OWNER_COOKIE, "")
    if cookie and not st.session_state.get("logged_out") and hmac.compare_digest(cookie, _owner_token()):
        st.session_state["owner_ok"] = True
        return Access(owner=True)
    st.title("Finboard")
    with st.form("login"):
        pwd = st.text_input("Пароль владельца", type="password")
        if st.form_submit_button("Войти", type="primary"):
            if hmac.compare_digest(pwd, config.OWNER_PASSWORD):
                st.session_state["owner_ok"] = True
                st.session_state["set_owner_cookie"] = True
                st.session_state.pop("logged_out", None)
                st.rerun()
            st.error("Неверный пароль")
    st.stop()


def access() -> Access:
    return st.session_state["access"]


# ── reference data ───────────────────────────────────────────────────────────

def cabinets_df(include_inactive: bool = False) -> pd.DataFrame:
    with session() as s:
        cabs = s.scalars(select(Cabinet).order_by(Cabinet.marketplace, Cabinet.name)).all()
        ents = {e.id: e.name for e in s.scalars(select(LegalEntity))}
        rows = [{"id": c.id, "name": c.name, "marketplace": c.marketplace, "entity_id": c.entity_id,
                 "entity": ents.get(c.entity_id, "—"), "active": c.active,
                 "last_sync_at": c.last_sync_at} for c in cabs if include_inactive or c.active]
    df = pd.DataFrame(rows, columns=["id", "name", "marketplace", "entity_id", "entity", "active", "last_sync_at"])
    acc = st.session_state.get("access")
    if acc and acc.cabinet_ids:
        df = df[df["id"].isin(acc.cabinet_ids)]
    return df


def cabinet_label(row) -> str:
    return f"{MP_NAMES.get(row['marketplace'], row['marketplace'])} · {row['name']}"


# ── filters ──────────────────────────────────────────────────────────────────

PERIODS = ["Этот месяц", "Прошлый месяц", "Последние 7 дней", "Последние 30 дней",
           "С начала года", "Свой период"]


def _period(choice: str) -> tuple[date, date]:
    today = date.today()
    y = today - timedelta(days=1)
    if choice == "Этот месяц":
        return today.replace(day=1), max(today.replace(day=1), y)
    if choice == "Прошлый месяц":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if choice == "Последние 7 дней":
        return y - timedelta(days=6), y
    if choice == "Последние 30 дней":
        return y - timedelta(days=29), y
    if choice == "С начала года":
        return date(today.year, 1, 1), y
    return None, None


@dataclass
class Filters:
    date_from: date
    date_to: date
    cabinet_ids: list[int]
    cabinets: pd.DataFrame


def sidebar_filters(key: str = "flt") -> Filters | None:
    cabs = cabinets_df()
    if cabs.empty:
        return None
    with st.sidebar:
        st.subheader("Период и кабинеты")
        choice = st.selectbox("Период", PERIODS, index=1, key=f"{key}_period")
        d0, d1 = _period(choice)
        if d0 is None:
            rng = st.date_input("Даты", value=(date.today().replace(day=1), date.today() - timedelta(days=1)),
                                format="DD.MM.YYYY", key=f"{key}_range")
            if isinstance(rng, tuple) and len(rng) == 2:
                d0, d1 = rng
            else:
                st.stop()
        else:
            st.caption(f"{d0:%d.%m.%Y} — {d1:%d.%m.%Y}")
        labels = {cabinet_label(r): r["id"] for _, r in cabs.iterrows()}
        sel = st.multiselect("Кабинеты", list(labels), default=list(labels), key=f"{key}_cabs")
        ids = [labels[x] for x in sel] or list(labels.values())
    return Filters(d0, d1, ids, cabs)


# ── calculation (cached) ─────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Считаю…")
def calc(date_from: date, date_to: date, cabinet_ids: tuple[int, ...], _version: int = 0):
    from pnl.data import load
    return compute(load(date_from, date_to, list(cabinet_ids)))


def data_changed():
    """Call after edits (cost, fixed costs, settings) so pages recalculate."""
    calc.clear()


def result_for(f: Filters):
    return calc(f.date_from, f.date_to, tuple(sorted(f.cabinet_ids)))


def with_names(facts: pd.DataFrame, cabinets: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    df = facts.merge(cabinets[["id", "name", "marketplace"]].rename(columns={"id": "cabinet_id", "name": "cabinet"}),
                     on="cabinet_id", how="left")
    if not products.empty:
        p = products.copy()
        p["sku"] = p["sku"].astype(str)
        df = df.merge(p[["cabinet_id", "sku", "article", "name"]], on=["cabinet_id", "sku"], how="left")
    else:
        df["article"], df["name"] = "", ""
    df["article"] = df["article"].fillna("")
    df["name"] = df["name"].fillna("")
    df.loc[df["sku"] == NO_SKU, "name"] = "Без привязки к товару (общие расходы МП)"
    return df


def hide_cogs_columns(df: pd.DataFrame) -> pd.DataFrame:
    acc = st.session_state.get("access")
    if acc and acc.hide_cogs:
        drop = [c for c in df.columns if "ебестоим" in str(c) or c in ("cogs", "cost", "roi", "ROI")]
        return df.drop(columns=drop)
    return df


__all__ = ["rub", "pct", "num", "require_access", "access", "sidebar_filters", "result_for",
           "with_names", "summarize", "data_changed", "cabinets_df", "cabinet_label", "MP_NAMES",
           "hide_cogs_columns", "new_share_token", "hash_token", "Filters"]
