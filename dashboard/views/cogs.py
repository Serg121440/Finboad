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


def _current_costs(df: pd.DataFrame) -> dict[str, tuple[float, date]]:
    """article (normalized) -> (latest cost, valid_from); the «all cabinets» row wins."""
    out = {}
    if df.empty:
        return out
    d = df.assign(key=df["article"].map(normalize_article), glob=df["cabinet_id"].isna())
    d = d.sort_values(["glob", "valid_from"])
    for r in d.itertuples():
        out[r.key] = (float(r.cost), r.valid_from)
    return out


def _catalog() -> pd.DataFrame:
    """One row per article over all cabinets: name, cabinets, card cost (Ozon), sold in 90 days."""
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
    if prods.empty:
        return pd.DataFrame(columns=["key", "article", "name", "cabinets", "card_min", "card_max", "sold90"])
    if not sold.empty:
        sold = sold.groupby(["cabinet_id", "sku"], as_index=False)["qty"].sum()
        prods = prods.merge(sold, on=["cabinet_id", "sku"], how="left")
    else:
        prods["qty"] = 0
    prods = prods[prods["article"] != ""]
    prods["key"] = prods["article"].map(normalize_article)
    prods["cab"] = prods["cabinet_id"].map(names)
    g = prods.groupby("key").agg(
        article=("article", "first"), name=("name", lambda v: max(v, key=len)),
        cabinets=("cab", lambda v: ", ".join(sorted(set(v)))),
        card_min=("card_cost", "min"), card_max=("card_cost", "max"),
        sold90=("qty", "sum")).reset_index()
    return g


def _template_xlsx(cat: pd.DataFrame, current: dict) -> bytes:
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
        cost, since = current.get(r.key, (None, None))
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


def _card_block(cat: pd.DataFrame, current: dict, view: pd.DataFrame, labels: dict):
    st.subheader("Себестоимость в карточках Ozon")
    st.caption("Ozon хранит себестоимость в карточке товара (поле «Себестоимость» в ценах). Здесь видно, где она "
               "заполнена, а в Finboard нет или отличается. Обновляется при загрузке товаров кабинета.")
    c1, c2 = st.columns(2)
    if c1.button("Обновить из карточек Ozon сейчас"):
        with st.spinner("Читаю карточки…"):
            n = refresh_card_costs()
        st.session_state["cogs_msg"] = f"Карточек с себестоимостью: {n}"
        st.rerun()
    have = cat[cat["card_max"].fillna(0) > 0].copy()
    if have.empty:
        st.info("В карточках Ozon себестоимость не найдена (или товары ещё не загружены).")
        return
    have["ours"] = have["key"].map(lambda k: current.get(k, (None,))[0])
    have["status"] = [
        "нет в Finboard" if pd.isna(o) else ("совпадает" if abs(o - mx) < 0.01 and abs(o - mn) < 0.01 else "отличается")
        for o, mn, mx in zip(have["ours"], have["card_min"], have["card_max"])]
    counts = have["status"].value_counts()
    st.caption(" · ".join(f"{k}: {v}" for k, v in counts.items()))
    missing = have[have["status"] == "нет в Finboard"]
    if c2.button(f"Взять из карточек для {len(missing)} товаров без себестоимости", disabled=missing.empty,
                 type="primary"):
        add = pd.DataFrame({"Артикул": missing["article"], "Кабинет": ALL,
                            "Действует с": date(2000, 1, 1), "Себестоимость, ₽/шт": missing["card_max"]})
        # cabinets disagree: keep the card price per cabinet instead of one for all
        split = missing[missing["card_min"] != missing["card_max"]]
        if not split.empty:
            rows = []
            with session() as s:
                for p in s.scalars(select(Product).where(Product.card_cost.is_not(None))):
                    if normalize_article(p.article) in set(split["key"]):
                        c = s.get(Cabinet, p.cabinet_id)
                        rows.append({"Артикул": p.article, "Кабинет": cabinet_label(
                            {"marketplace": c.marketplace, "name": c.name}),
                            "Действует с": date(2000, 1, 1), "Себестоимость, ₽/шт": p.card_cost})
            add = pd.concat([add[~add["Артикул"].isin(split["article"])], pd.DataFrame(rows)])
        n = _save(pd.concat([view, add]), labels)
        st.session_state["cogs_msg"] = f"Добавлено из карточек: {len(add)}. Всего строк: {n}"
        st.rerun()
    show = have[have["status"] != "совпадает"].sort_values(["status", "sold90"], ascending=[True, False])
    if not show.empty:
        st.dataframe(pd.DataFrame({
            "Статус": show["status"], "Артикул": show["article"], "Товар": show["name"],
            "В карточке, ₽": show["card_max"], "В Finboard, ₽": show["ours"],
            "Продано за 90 дней": show["sold90"]}), use_container_width=True, hide_index=True, height=300)
        st.caption("«Отличается» не меняется автоматически: проверьте и поправьте в таблице выше, если нужно.")


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
            raw = pd.read_csv(up, sep=None, engine="python") if up.name.endswith(".csv") else pd.read_excel(up)
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

    cat = _catalog()
    current = _current_costs(df)
    st.subheader("Массовый ввод через шаблон")
    if cat.empty:
        st.caption("Шаблон появится после загрузки товаров хотя бы одного кабинета.")
    else:
        no_cost = int((~cat["key"].isin(current)).sum())
        st.caption(f"Артикулов в кабинетах: {len(cat)}, без себестоимости: {no_cost}. Скачайте шаблон — в нём все "
                   "артикулы, сначала самые продаваемые; заполните жёлтые колонки и загрузите файл выше.")
        st.download_button("Скачать шаблон xlsx", _template_xlsx(cat, current),
                           file_name=f"себестоимость_шаблон_{date.today():%Y%m%d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    _card_block(cat, current, view, labels)

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
