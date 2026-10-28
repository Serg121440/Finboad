"""Себестоимость: цена за штуку по артикулу с датой начала действия."""

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from core.db import session
from core.crypto import decrypt
from core.models import Cabinet, CostOfGoods, LedgerEntry, Product
from dashboard.common import cabinets_df, cabinet_label, data_changed, sidebar_filters, result_for, with_names
from pnl.wb import normalize_article
from sources.ozon_api import SellerClient

ALL = "Все кабинеты"


def _load() -> pd.DataFrame:
    with session() as s:
        rows = [{"id": c.id, "article": c.article, "cabinet_id": c.cabinet_id, "valid_from": c.valid_from,
                 "cost": c.cost} for c in s.scalars(select(CostOfGoods).order_by(CostOfGoods.article,
                                                                                CostOfGoods.valid_from))]
    return pd.DataFrame(rows, columns=["id", "article", "cabinet_id", "valid_from", "cost"])


def _save(df: pd.DataFrame, cab_ids: dict[str, int | None]) -> int:
    rows = {}
    for _, r in df.iterrows():
        art = str(r["Артикул"] or "").strip()
        cost = r["Себестоимость, ₽/шт"]
        if not art or pd.isna(cost):
            continue
        d = r["Действует с"]
        d = date(2000, 1, 1) if d is None or pd.isna(d) else pd.to_datetime(d).date()
        rows[(art, cab_ids.get(r["Кабинет"]), d)] = float(cost)
    with session() as s:
        s.execute(delete(CostOfGoods))
        for (art, cab, d), cost in rows.items():
            s.add(CostOfGoods(article=art, cabinet_id=cab, valid_from=d, cost=cost))
    data_changed()
    return len(rows)


def _article(v) -> str:
    """Excel turns numeric articles into floats: 2479.0 -> '2479'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse_cost_file(raw: pd.DataFrame, cabinet_label: str) -> pd.DataFrame:
    """Rows for the cost editor from an uploaded table.

    Needs an article column and a cost column («Себестоимость», or failing that
    «Закупка»/«Цена»); «Действует с»/«Дата» is optional."""
    cols = {str(c).lower().strip(): c for c in raw.columns}
    art = next((cols[c] for c in cols if "артикул" in c), None)
    cost = (next((cols[c] for c in cols if "себесто" in c), None)
            or next((cols[c] for c in cols if "закуп" in c or "цена" in c), None))
    when = next((cols[c] for c in cols if "действ" in c or "дата" in c), None)
    if not art or not cost:
        raise ValueError("Не нашёл колонки «Артикул» и «Себестоимость».")
    out = pd.DataFrame({
        "Артикул": raw[art].map(_article),
        "Кабинет": cabinet_label,
        "Действует с": pd.to_datetime(raw[when], dayfirst=True, errors="coerce").dt.date if when
        else date(2000, 1, 1),
        "Себестоимость, ₽/шт": pd.to_numeric(raw[cost].astype(str).str.replace(",", ".")
                                             .str.replace("\xa0", "").str.replace(" ", ""), errors="coerce"),
    })
    out = out[(out["Артикул"] != "") & (out["Артикул"] != "nan") & out["Себестоимость, ₽/шт"].notna()]
    out["Действует с"] = out["Действует с"].fillna(date(2000, 1, 1))
    return out


def read_cost_xlsx(f) -> pd.DataFrame:
    """The «Себестоимость» sheet of our template (the first sheet is the instructions), else the first sheet."""
    sheets = pd.ExcelFile(f).sheet_names
    return pd.read_excel(f, sheet_name="Себестоимость" if "Себестоимость" in sheets else 0)


def _current_costs(df: pd.DataFrame) -> dict[tuple[int | None, str], tuple[float, date]]:
    """(cabinet_id or None for all cabinets, normalized article) -> (latest cost, valid_from)."""
    out = {}
    if df.empty:
        return out
    d = df.assign(key=df["article"].map(normalize_article)).sort_values("valid_from")
    for r in d.itertuples():
        cab = None if pd.isna(r.cabinet_id) else int(r.cabinet_id)
        out[(cab, r.key)] = (float(r.cost), r.valid_from)
    return out


def _cost_for(current: dict, cabinet_id: int, key: str):
    """As the P&L applies it: the cabinet's own cost beats the one for all cabinets."""
    return current.get((cabinet_id, key)) or current.get((None, key))


def _products() -> pd.DataFrame:
    """One row per (cabinet, article): name, card cost (Ozon), sold in 90 days."""
    cabs = cabinets_df()
    names = {int(r["id"]): cabinet_label(r) for _, r in cabs.iterrows()}
    since = date.today() - timedelta(days=90)
    with session() as s:
        prods = pd.DataFrame([{"cabinet_id": p.cabinet_id, "sku": p.sku, "article": p.article or "",
                               "name": p.name or "", "card_cost": p.card_cost}
                              for p in s.scalars(select(Product).where(Product.cabinet_id.in_(list(names))))],
                             columns=["cabinet_id", "sku", "article", "name", "card_cost"])
        sold = pd.DataFrame(s.execute(
            select(LedgerEntry.cabinet_id, LedgerEntry.sku, LedgerEntry.qty)
            .where(LedgerEntry.category.in_(["sale", "return"]), LedgerEntry.date >= since,
                   LedgerEntry.cabinet_id.in_(list(names)))).all(), columns=["cabinet_id", "sku", "qty"])
    if not sold.empty:
        sold = sold.groupby(["cabinet_id", "sku"], as_index=False)["qty"].sum()
        prods = prods.merge(sold, on=["cabinet_id", "sku"], how="left")
    else:
        prods["qty"] = 0
    prods = prods[prods["article"] != ""].copy()
    prods["key"] = prods["article"].map(normalize_article)
    prods["cab"] = prods["cabinet_id"].map(names)
    return prods.groupby(["cabinet_id", "key"], as_index=False).agg(
        article=("article", "first"), name=("name", lambda v: max(v, key=len)), cab=("cab", "first"),
        card_cost=("card_cost", "max"), qty=("qty", "sum"))


def _catalog(prods: pd.DataFrame, current: dict) -> pd.DataFrame:
    """One row per article over all cabinets; «missing» = some cabinet has no cost for it."""
    if prods.empty:
        return pd.DataFrame(columns=["key", "article", "name", "cabinets", "card_min", "card_max", "sold90",
                                     "cost", "since", "missing"])
    p = prods.assign(cur=[_cost_for(current, c, k) for c, k in zip(prods["cabinet_id"], prods["key"])])
    g = p.groupby("key").agg(
        article=("article", "first"), name=("name", lambda v: max(v, key=len)),
        cabinets=("cab", lambda v: ", ".join(sorted(set(v)))),
        card_min=("card_cost", "min"), card_max=("card_cost", "max"), sold90=("qty", "sum"),
        missing=("cur", lambda v: any(x is None for x in v)),
        # template prefill: the all-cabinets cost, or the cabinet's own when the article is in one cabinet
        cur=("cur", lambda v: v.iloc[0] if len(v) == 1 else None)).reset_index()
    pre = [current.get((None, k)) or c for k, c in zip(g["key"], g["cur"])]
    g["cost"] = [x[0] if x else None for x in pre]
    g["since"] = [x[1] if x else None for x in pre]
    return g.drop(columns="cur")


def _template_xlsx(cat: pd.DataFrame) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ins = wb.active
    ins.title = "Инструкция"
    ins.sheet_properties.tabColor = "94A3B8"
    for row in [
        ("Лист", "Тип", "Кто заполняет", "Что смотреть"),
        ("Себестоимость", "Ввод", "Вы — жёлтые колонки «Себестоимость» и «Действует с»",
         "Все артикулы ваших кабинетов. Уже введённые цены подставлены; пустые строки при загрузке пропускаются."),
        ("", "", "", "«Действует с» — с какой даты продажи применять цену. Пусто = для всех продаж."),
        ("", "", "", "«В карточке Ozon» и «Продано за 90 дней» — подсказка, при загрузке не используются."),
        ("Загрузка", "", "", "Finboard → Себестоимость → «Загрузить из файла» → этот файл."),
    ]:
        ins.append(row)
    ins["A1"].font = ins["B1"].font = ins["C1"].font = ins["D1"].font = Font(bold=True)
    ins.column_dimensions["A"].width, ins.column_dimensions["C"].width, ins.column_dimensions["D"].width = 18, 45, 90

    ws = wb.create_sheet("Себестоимость")
    ws.sheet_properties.tabColor = "FACC15"
    ws.append(["Артикул", "Товар", "Кабинеты", "Себестоимость, ₽/шт", "Действует с",
               "В карточке Ozon, ₽", "Продано за 90 дней, шт"])
    yellow = PatternFill("solid", fgColor="FFF3B0")
    cat = cat.sort_values(["sold90", "article"], ascending=[False, True])
    for r in cat.itertuples():
        cost, since = (None, None) if pd.isna(r.cost) else (r.cost, r.since)
        card = None if pd.isna(r.card_max) or not r.card_max else (
            r.card_max if r.card_min == r.card_max else f"{r.card_min:.0f}–{r.card_max:.0f}")
        ws.append([r.article, r.name, r.cabinets, cost,
                   since if since and since != date(2000, 1, 1) else None, card, int(r.sold90 or 0)])
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=5):
        for c in row:
            c.fill = yellow
        row[1].number_format = "DD.MM.YYYY"
    for col, w in zip("ABCDEFG", (18, 70, 30, 20, 14, 18, 14)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def refresh_card_costs() -> int:
    """Read net_price from Ozon cards of every Ozon cabinet into Product.card_cost."""
    n = 0
    with session() as s:
        cabs = s.scalars(select(Cabinet).where(Cabinet.marketplace == "ozon", Cabinet.secrets != "")).all()
        for c in cabs:
            keys = decrypt(c.secrets)
            costs = SellerClient(keys["client_id"], keys["api_key"]).net_prices()
            for p in s.scalars(select(Product).where(Product.cabinet_id == c.id)):
                p.card_cost = costs.get(p.article) or None
                n += p.card_cost is not None
    return n


def _card_block(prods: pd.DataFrame, current: dict, view: pd.DataFrame, labels: dict):
    st.subheader("Себестоимость в карточках Ozon")
    st.caption("Ozon хранит себестоимость в карточке товара (поле «Себестоимость» в ценах). Здесь видно, где она "
               "заполнена, а в Finboard нет или отличается. Обновляется при загрузке товаров кабинета.")
    c1, c2 = st.columns(2)
    if c1.button("Обновить из карточек Ozon сейчас"):
        with st.spinner("Читаю карточки…"):
            n = refresh_card_costs()
        st.session_state["cogs_msg"] = f"Карточек с себестоимостью: {n}"
        st.rerun()
    have = prods[prods["card_cost"].fillna(0) > 0].copy()
    if have.empty:
        st.info("В карточках Ozon себестоимость не найдена (или товары ещё не загружены).")
        return
    have["ours"] = [(_cost_for(current, c, k) or (None,))[0] for c, k in zip(have["cabinet_id"], have["key"])]
    have["status"] = ["нет в Finboard" if o is None else ("совпадает" if abs(o - c) < 0.01 else "отличается")
                      for o, c in zip(have["ours"], have["card_cost"])]
    counts = have["status"].value_counts()
    st.caption(" · ".join(f"{k}: {v}" for k, v in counts.items()))
    missing = have[have["status"] == "нет в Finboard"]
    if c2.button(f"Взять из карточек для {len(missing)} товаров без себестоимости", disabled=missing.empty,
                 type="primary"):
        add = card_cost_rows(have, missing, current)
        n = _save(pd.concat([view, add]), labels)
        st.session_state["cogs_msg"] = f"Добавлено из карточек: {len(add)}. Всего строк: {n}"
        st.rerun()
    show = have[have["status"] != "совпадает"].sort_values(["status", "qty"], ascending=[True, False])
    if not show.empty:
        st.dataframe(pd.DataFrame({
            "Статус": show["status"], "Кабинет": show["cab"], "Артикул": show["article"], "Товар": show["name"],
            "В карточке, ₽": show["card_cost"], "В Finboard, ₽": show["ours"],
            "Продано за 90 дней": show["qty"]}), use_container_width=True, hide_index=True, height=300)
        st.caption("«Отличается» не меняется автоматически: проверьте и поправьте в таблице выше, если нужно.")


def card_cost_rows(have: pd.DataFrame, missing: pd.DataFrame, current: dict) -> pd.DataFrame:
    """Editor rows for (cabinet, article) pairs without a cost.

    One row for all cabinets (covers WB too) when there is none yet and the cards agree;
    otherwise a row for each cabinet that lacks a cost. A cabinet's own cost still wins."""
    cards = have.groupby("key")["card_cost"].agg(["min", "max"])
    rows = []
    for key, m in missing.groupby("key"):
        lo, hi = cards.loc[key]
        if (None, key) not in current and lo == hi:
            rows.append({"Артикул": m["article"].iloc[0], "Кабинет": ALL, "Себестоимость, ₽/шт": hi})
        else:
            rows += [{"Артикул": r.article, "Кабинет": r.cab, "Себестоимость, ₽/шт": r.card_cost}
                     for r in m.itertuples()]
    return pd.DataFrame(rows, columns=["Артикул", "Кабинет", "Себестоимость, ₽/шт"]).assign(
        **{"Действует с": date(2000, 1, 1)})


def render():
    st.title("Себестоимость")
    st.caption("Цена закупки за штуку. «Действует с» — с какой даты продажи применять цену; для старых "
               "продаж остаётся прежняя. Цена для конкретного кабинета важнее цены для всех кабинетов.")
    cabs = cabinets_df()
    labels = {ALL: None} | {cabinet_label(r): int(r["id"]) for _, r in cabs.iterrows()}
    back = {v: k for k, v in labels.items()}

    df = _load()
    view = pd.DataFrame({
        "Артикул": df["article"], "Кабинет": df["cabinet_id"].map(lambda v: back.get(None if pd.isna(v) else int(v), ALL)),
        "Действует с": pd.to_datetime(df["valid_from"]).dt.date, "Себестоимость, ₽/шт": df["cost"]})
    edited = st.data_editor(
        view, num_rows="dynamic", use_container_width=True, hide_index=True, height=420, key="cogs_editor",
        column_config={
            "Кабинет": st.column_config.SelectboxColumn(options=list(labels), default=ALL, required=True),
            "Действует с": st.column_config.DateColumn(format="DD.MM.YYYY", default=date(2000, 1, 1)),
            "Себестоимость, ₽/шт": st.column_config.NumberColumn(min_value=0, format="%.2f", required=True),
        })
    if st.button("Сохранить", type="primary"):
        n = _save(edited, labels)
        st.success(f"Сохранено строк: {n}")

    with st.expander("Загрузить из файла (xlsx или csv)"):
        st.caption("Колонки: «Артикул», «Себестоимость»; необязательно — «Действует с» (дата). "
                   "Строки добавляются к таблице; совпадающие артикул + дата заменяются.")
        up = st.file_uploader("Файл", type=["xlsx", "csv"], key="cogs_file")
        cab = st.selectbox("Для кабинета", list(labels), key="cogs_file_cab")
        if up is not None and st.button("Загрузить файл"):
            raw = pd.read_csv(up, sep=None, engine="python") if up.name.endswith(".csv") else read_cost_xlsx(up)
            try:
                add = parse_cost_file(raw, cab)
            except ValueError as e:
                st.error(str(e))
            else:
                n = _save(pd.concat([view, add]), labels)
                st.session_state["cogs_msg"] = f"Из файла взято строк: {len(add)}. Всего в таблице: {n}"
                st.rerun()
    if st.session_state.get("cogs_msg"):
        st.success(st.session_state.pop("cogs_msg"))

    current = _current_costs(df)
    prods = _products()
    cat = _catalog(prods, current)
    st.subheader("Массовый ввод через шаблон")
    if cat.empty:
        st.caption("Шаблон появится после загрузки товаров хотя бы одного кабинета.")
    else:
        no_cost = int(cat["missing"].sum())
        st.caption(f"Артикулов в кабинетах: {len(cat)}, без себестоимости: {no_cost}. Скачайте шаблон — в нём все "
                   "артикулы, сначала самые продаваемые; заполните жёлтые колонки и загрузите файл выше.")
        st.download_button("Скачать шаблон xlsx", _template_xlsx(cat),
                           file_name=f"себестоимость_шаблон_{date.today():%Y%m%d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    _card_block(prods, current, view, labels)

    st.subheader("Продавались без себестоимости")
    f = sidebar_filters()
    if f is None:
        return
    res = result_for(f)
    miss = res.facts[res.facts["cost_missing_qty"] != 0]
    if miss.empty:
        st.success("За выбранный период у всех проданных товаров есть себестоимость.")
        return
    g = miss.groupby(["cabinet_id", "sku"], as_index=False)[["cost_missing_qty", "revenue"]].sum()
    g = with_names(g, f.cabinets, res.products)
    st.dataframe(pd.DataFrame({"Кабинет": g["cabinet"], "Артикул": g["article"], "Товар": g["name"],
                               "Штук без себестоимости": g["cost_missing_qty"], "Выручка, ₽": g["revenue"]})
                 .sort_values("Выручка, ₽", ascending=False),
                 use_container_width=True, hide_index=True)
    if (g["article"] == "").any():
        st.caption("Пустой артикул — товара ещё нет в каталоге кабинета; он появится после загрузки товаров.")
