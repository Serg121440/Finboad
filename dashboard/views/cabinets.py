"""Кабинеты и налоги: юрлица с налоговым режимом, кабинеты с API-ключами, загрузка данных."""

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from core.crypto import SecretMissing, decrypt, encrypt, mask
from core.db import session
from core.models import Cabinet, LegalEntity, SyncRun, TaxSetting, now_msk
from dashboard.common import MP_NAMES, data_changed, show_period
from pnl.tax import REGIMES, VAT_MODES, regime_from_marketplace
from sync import runner

KIND = {"ip": "ИП", "ooo": "ООО"}
STREAM = {"products": "товары", "accruals": "начисления", "orders": "заказы", "ads": "реклама"}
NEW_ENTITY = "➕ Новое юрлицо…"
RUN_NAMES = STREAM | {"report": "отчёт xlsx", "wb_report": "отчёт WB xlsx"}


# ── legal entities and taxes ─────────────────────────────────────────────────

def _entities_block():
    st.subheader("Юрлица и налоги")
    st.caption("Налоги и пороги НДС считаются по юрлицу целиком, по всем его кабинетам. Режим действует с "
               "указанной даты до следующей строки — при смене режима прошлые периоды не пересчитываются.")
    with session() as s:
        ents = s.scalars(select(LegalEntity).order_by(LegalEntity.name)).all()
    with session() as s:
        taxed = set(s.scalars(select(TaxSetting.entity_id)).all())
    for e in ents:
        title = f"{KIND.get(e.kind, e.kind)} {e.name}" + (f" · ИНН {e.inn}" if e.inn else "")
        with st.expander(title + ("" if e.id in taxed else " · ⚠️ налоговый режим не задан"),
                         expanded=e.id not in taxed):
            _tax_editor(e)
    with st.form("new_entity", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 2])
        name = c1.text_input("Новое юрлицо: название", placeholder="Перфетто Спорт")
        kind = c2.selectbox("Тип", list(KIND), format_func=KIND.get)
        inn = c3.text_input("ИНН (необязательно)")
        if st.form_submit_button("Добавить юрлицо") and name.strip():
            with session() as s:
                s.add(LegalEntity(name=name.strip(), kind=kind, inn=inn.strip()))
            st.rerun()


def _tax_editor(e: LegalEntity):
    with session() as s:
        rows = s.scalars(select(TaxSetting).where(TaxSetting.entity_id == e.id)
                         .order_by(TaxSetting.valid_from)).all()
        df = pd.DataFrame([{
            "Действует с": r.valid_from, "Режим": r.regime,
            "Ставка УСН, %": (r.usn_rate or 0) * 100 if r.usn_rate else None,
            "НДС": r.vat_mode or "auto", "Есть работники": bool(r.has_employees),
            "Взносы ИП в месяц, ₽": r.ip_contrib_monthly or 0.0,
            "Доход за прошлый год, ₽": r.vat_vs_prior_year or 0.0} for r in rows],
            columns=["Действует с", "Режим", "Ставка УСН, %", "НДС", "Есть работники",
                     "Взносы ИП в месяц, ₽", "Доход за прошлый год, ₽"])
    hint = regime_from_marketplace(e.mp_tax_system, e.kind)
    if df.empty and e.mp_tax_system:
        if hint:
            st.info(f"В кабинете Ozon у юрлица указан режим {e.mp_tax_system} — это «{REGIMES[hint]}». "
                    "Проверьте и примените, или задайте режим в таблице ниже.")
            if st.button(f"Применить «{REGIMES[hint]}» с 01.01.{date.today().year}", key=f"hint_{e.id}"):
                with session() as s:
                    s.add(TaxSetting(entity_id=e.id, valid_from=date(date.today().year, 1, 1), regime=hint,
                                     vat_mode="auto"))
                data_changed()
                st.rerun()
        else:
            st.info(f"В кабинете Ozon у юрлица указан режим {e.mp_tax_system}. Задайте его в таблице ниже.")
    regimes = [k for k in REGIMES if k != "NONE"]
    if e.kind == "ooo":
        regimes = [k for k in regimes if k != "OSNO_IP"]
    else:
        regimes = [k for k in regimes if k != "OSNO_OOO"]
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, use_container_width=True, key=f"tax_{e.id}",
        column_config={
            "Действует с": st.column_config.DateColumn(format="DD.MM.YYYY", required=True,
                                                       default=date(date.today().year, 1, 1)),
            "Режим": st.column_config.SelectboxColumn(options=regimes, required=True, default=regimes[0],
                                                      help=" · ".join(f"{k} — {REGIMES[k]}" for k in regimes)),
            "Ставка УСН, %": st.column_config.NumberColumn(
                min_value=0, max_value=15, format="%.1f",
                help="Пусто = 6 % для «Доходы», 15 % для «Доходы минус расходы». Региональную ставку укажите явно."),
            "НДС": st.column_config.SelectboxColumn(options=list(VAT_MODES), default="auto",
                                                    help=" · ".join(f"{k} — {v}" for k, v in VAT_MODES.items())),
            "Взносы ИП в месяц, ₽": st.column_config.NumberColumn(
                min_value=0, format="%.0f", help="Уменьшают налог на УСН «Доходы». 2026: 57 390 ₽ в год + 1 % свыше 300 тыс."),
            "Доход за прошлый год, ₽": st.column_config.NumberColumn(
                min_value=0, format="%.0f", help="Для порога освобождения от НДС (20 млн)"),
        })
    st.caption("НДС: auto — освобождение до 20 млн дохода за год, затем 5 % (до 272,5 млн) или 7 %. "
               "ОСНО и АУСН задают НДС сами. Ставка 10 % отмечается у товаров.")
    c1, c2 = st.columns([1, 4])
    if c1.button("Сохранить налоги", key=f"save_tax_{e.id}", type="primary"):
        with session() as s:
            s.execute(delete(TaxSetting).where(TaxSetting.entity_id == e.id))
            seen = set()
            for _, r in edited.iterrows():
                if pd.isna(r["Действует с"]) or not r["Режим"]:
                    continue
                d = pd.to_datetime(r["Действует с"]).date()
                if d in seen:
                    continue
                seen.add(d)
                rate = r["Ставка УСН, %"]
                s.add(TaxSetting(entity_id=e.id, valid_from=d, regime=r["Режим"],
                                 usn_rate=None if pd.isna(rate) or not rate else float(rate) / 100,
                                 vat_mode=r["НДС"] or "auto", has_employees=bool(r["Есть работники"]),
                                 ip_contrib_monthly=float(r["Взносы ИП в месяц, ₽"] or 0),
                                 vat_vs_prior_year=float(r["Доход за прошлый год, ₽"] or 0)))
        data_changed()
        st.success("Сохранено")
    with c2.popover("Удалить юрлицо"):
        st.write("Кабинеты останутся, но без налогов.")
        if st.button("Удалить", key=f"del_ent_{e.id}"):
            with session() as s:
                s.execute(delete(TaxSetting).where(TaxSetting.entity_id == e.id))
                for c in s.scalars(select(Cabinet).where(Cabinet.entity_id == e.id)):
                    c.entity_id = None
                s.execute(delete(LegalEntity).where(LegalEntity.id == e.id))
            data_changed()
            st.rerun()


# ── cabinets ─────────────────────────────────────────────────────────────────

def _key_fields(mp: str, prefix: str, current: dict | None = None) -> dict:
    current = current or {}
    ph = (lambda k: mask(current.get(k, "")) if current.get(k) else "")
    if mp == "ozon":
        c1, c2 = st.columns(2)
        keys = {"client_id": c1.text_input("Client-Id", value=current.get("client_id", ""), key=f"{prefix}_cid"),
                "api_key": c2.text_input("API-ключ Seller API", type="password", placeholder=ph("api_key"),
                                         key=f"{prefix}_key")}
        st.caption("Performance API (реклама по товарам) — необязательно, но без него реклама будет одной "
                   "суммой. Ключ создаётся в кабинете Ozon → Продвижение → API.")
        c3, c4 = st.columns(2)
        keys["perf_client_id"] = c3.text_input("Performance client_id", value=current.get("perf_client_id", ""),
                                               key=f"{prefix}_pcid")
        keys["perf_client_secret"] = c4.text_input("Performance client_secret", type="password",
                                                   placeholder=ph("perf_client_secret"), key=f"{prefix}_psec")
    else:
        keys = {"token": st.text_input("API-токен WB (категории: Статистика, Финансы, Продвижение, Контент; "
                                       "только чтение)", type="password", placeholder=ph("token"),
                                       key=f"{prefix}_tok")}
    # keep stored secrets when the field is left empty
    return {k: (v.strip() if v and v.strip() else current.get(k, "")) for k, v in keys.items()}


def _new_cabinet_form(entities: dict):
    with st.expander("➕ Подключить кабинет", expanded=False):
        mp = st.radio("Маркетплейс", ["ozon", "wb"], format_func=MP_NAMES.get, horizontal=True, key="new_mp")
        c1, c2, c3 = st.columns([2, 2, 1])
        name = c1.text_input("Название кабинета", placeholder="Perfetto ООО", key="new_name")
        ent = c2.selectbox("Юрлицо", ["—"] + list(entities), key="new_ent")
        hist = c3.date_input("Загрузить с", value=date.today() - timedelta(days=90), format="DD.MM.YYYY",
                             key="new_hist", help="Первая загрузка. WB отдаёт отчёт 1 раз в минуту — год истории "
                                                   "грузится долго.")
        keys = _key_fields(mp, "new")
        if st.button("Проверить и подключить", type="primary"):
            need = ["client_id", "api_key"] if mp == "ozon" else ["token"]
            if not name.strip() or not all(keys.get(k) for k in need):
                st.error("Заполните название и ключи.")
                return
            with st.spinner("Проверяю ключи…"):
                report = runner.check_keys(mp, keys)
            try:
                secret = encrypt(keys)
            except SecretMissing as e:
                st.error(str(e))
                return
            with session() as s:
                cab = Cabinet(marketplace=mp, name=name.strip(), entity_id=entities.get(ent),
                              external_id=keys.get("client_id", ""), secrets=secret,
                              key_status=runner.key_status(report), key_report=runner.report_json(report),
                              checked_at=now_msk(), history_from=hist)
                s.add(cab)
                s.flush()
                cid = cab.id
            _show_report(report)
            if runner.key_status(report) != "error":
                runner.start_background(cid)
                st.success("Кабинет подключён, загрузка данных началась в фоне.")
            st.rerun()


def _show_report(report: dict):
    for k, v in report.items():
        (st.success if v == "ok" else st.warning)(f"{k}: {'доступ есть' if v == 'ok' else v}")


def _auto(r: SyncRun) -> bool:
    # runs recorded before the trigger column existed: the daily schedule starts at 06:00
    if r.trigger is None and r.started_at:
        return r.started_at.hour == 6 and r.started_at.minute < 10
    return r.trigger == "auto"


def _runs(cab_id: int) -> pd.DataFrame:
    with session() as s:
        rows = s.scalars(select(SyncRun).where(SyncRun.cabinet_id == cab_id)
                         .order_by(SyncRun.id.desc()).limit(12)).all()
        return pd.DataFrame([{
            "Начало": r.started_at.strftime("%d.%m %H:%M") if r.started_at else "",
            "Запуск": "авто" if _auto(r) else "вручную",
            "Данные": RUN_NAMES.get(r.stream, r.stream),
            "Период": f"{r.date_from:%d.%m.%y}–{r.date_to:%d.%m.%y}" if r.date_from else "",
            "Статус": {"ok": "✅", "error": "❌", "running": "⏳"}.get(r.status, r.status),
            "Строк": r.rows, "Сообщение": (r.message or "").split("\n")[0][:160]} for r in rows])


def _cabinet_card(c: Cabinet, entities: dict):
    status = {"ok": "🟢", "partial": "🟡", "error": "🔴"}.get(c.key_status, "⚪")
    running = runner.is_running(c.id)
    title = f"{status} {MP_NAMES[c.marketplace]} · {c.name}" + (" · загрузка…" if running else "")
    with st.expander(title, expanded=running):
        c1, c2, c3 = st.columns(3)
        c1.caption(f"Последняя загрузка: {c.last_sync_at:%d.%m.%Y %H:%M}" if c.last_sync_at else "Ещё не загружался")
        ent_names = {v: k for k, v in entities.items()}
        opts = ["—"] + list(entities) + [NEW_ENTITY]
        new_ent = c2.selectbox("Юрлицо", opts, key=f"ent_{c.id}",
                               index=opts.index(ent_names.get(c.entity_id, "—")),
                               help="Налоги считаются по юрлицу, по всем его кабинетам.")
        active = c3.toggle("Активен (ежедневная загрузка)", value=c.active, key=f"act_{c.id}")
        if new_ent == NEW_ENTITY:
            with c2.container(border=True):
                if c.marketplace == "ozon" and c2.button("Взять из кабинета Ozon", key=f"ozent_{c.id}",
                                                        type="primary"):
                    try:
                        keys = decrypt(c.secrets)
                        runner.ensure_entity(c.id, runner.SellerClient(keys["client_id"], keys["api_key"]),
                                            relink=True)
                    except Exception as ex:
                        st.error(f"Ozon не отдал реквизиты: {ex}")
                    else:
                        st.session_state.pop(f"ent_{c.id}", None)
                        data_changed()
                        st.rerun()
                name = st.text_input("Название", key=f"nename_{c.id}", placeholder="ООО «Перфетто Спорт»")
                k1, k2 = st.columns(2)
                kind = k1.selectbox("Тип", list(KIND), format_func=KIND.get, key=f"nekind_{c.id}")
                inn = k2.text_input("ИНН", key=f"neinn_{c.id}")
                if st.button("Создать и привязать", key=f"necreate_{c.id}") and name.strip():
                    with session() as s:
                        ent = LegalEntity(name=name.strip(), kind=kind, inn=inn.strip())
                        s.add(ent)
                        s.flush()
                        s.get(Cabinet, c.id).entity_id = ent.id
                    st.session_state.pop(f"ent_{c.id}", None)
                    data_changed()
                    st.rerun()
        target = c.entity_id if new_ent == NEW_ENTITY else entities.get(new_ent)
        if target != c.entity_id or active != c.active:
            with session() as s:
                obj = s.get(Cabinet, c.id)
                obj.entity_id, obj.active = target, active
            data_changed()
            st.rerun()

        if c.key_report:
            with st.popover("Права ключей"):
                _show_report(json.loads(c.key_report))

        st.markdown("**Загрузить историю**")
        st.caption("Обычно не нужно: новые дни грузятся каждое утро, а нужный период загружается кнопкой "
                   "«Загрузить» над любым отчётом. Здесь — первая загрузка или перезагрузка отдельных данных.")
        d1, d2, d3, d4 = st.columns([1, 1, 2, 1])
        f0 = d1.date_input("с", value=date.today() - timedelta(days=30), format="DD.MM.YYYY", key=f"f0_{c.id}")
        f1 = d2.date_input("по", value=date.today() - timedelta(days=1), format="DD.MM.YYYY", key=f"f1_{c.id}",
                           max_value=date.today())
        streams = d3.multiselect("Что", list(STREAM), default=list(STREAM), format_func=STREAM.get,
                                 key=f"st_{c.id}")
        if d4.button("Загрузить", key=f"sync_{c.id}", disabled=running, type="primary"):
            runner.start_background(c.id, f0, f1, tuple(streams))
            show_period(f0, f1)
            st.toast(f"Загрузка {f0:%d.%m.%Y} — {f1:%d.%m.%Y} запущена; отчёты откроются на этом периоде")
            st.rerun()
        runs = _runs(c.id)
        if not runs.empty:
            st.dataframe(runs, hide_index=True, use_container_width=True)
        if running:
            st.button("Обновить статус", key=f"refresh_{c.id}")

        with st.popover("Обновить ключи"):
            try:
                current = decrypt(c.secrets)
            except SecretMissing as e:
                st.error(str(e))
                current = {}
            keys = _key_fields(c.marketplace, f"edit{c.id}", current)
            if st.button("Проверить и сохранить", key=f"savekeys_{c.id}"):
                report = runner.check_keys(c.marketplace, keys)
                with session() as s:
                    obj = s.get(Cabinet, c.id)
                    obj.secrets = encrypt(keys)
                    obj.key_status, obj.key_report = runner.key_status(report), runner.report_json(report)
                    obj.checked_at = now_msk()
                _show_report(report)
        with st.popover("Удалить кабинет"):
            st.warning("Удалятся кабинет, его ключи и все загруженные данные.")
            if st.checkbox("Понимаю", key=f"delok_{c.id}") and st.button("Удалить навсегда", key=f"del_{c.id}"):
                from core.models import (AdCampaign, AdSpend, LedgerEntry, OrderLine, Product, SyncCursor)
                with session() as s:
                    for m in (LedgerEntry, OrderLine, AdSpend, AdCampaign, Product, SyncRun, SyncCursor):
                        s.execute(delete(m).where(m.cabinet_id == c.id))
                    s.execute(delete(Cabinet).where(Cabinet.id == c.id))
                data_changed()
                st.rerun()


def render():
    st.title("Кабинеты и налоги")
    with session() as s:
        entities = {e.name: e.id for e in s.scalars(select(LegalEntity).order_by(LegalEntity.name))}
        cabs = s.scalars(select(Cabinet).order_by(Cabinet.marketplace, Cabinet.name)).all()

    _entities_block()
    st.divider()
    st.subheader("Кабинеты")
    st.caption("Ключи хранятся в базе в зашифрованном виде и нигде не показываются. Достаточно ключей только "
               "на чтение. Каждый день в 06:00 МСК загрузка идёт сама («авто» в таблице загрузок): последние "
               "14 дней перечитываются, потому что маркетплейс задним числом поправляет начисления.")
    for c in cabs:
        _cabinet_card(c, entities)
    _new_cabinet_form(entities)
