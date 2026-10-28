"""Доступ по ссылке: просмотр дашборда без пароля, только чтение."""

import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.db import session
from core.models import ShareLink, now_msk
from dashboard.common import cabinets_df, cabinet_label, hash_token, new_share_token


def render():
    st.title("Доступ по ссылке")
    st.caption("Ссылка открывает «Финансовый результат», «ОПиУ», «Товары» и «Рекламу» только на чтение — без "
               "настроек, ключей и редактирования. Ссылку можно отозвать в любой момент.")
    cabs = cabinets_df()
    labels = {cabinet_label(r): int(r["id"]) for _, r in cabs.iterrows()}

    with st.form("new_link"):
        label = st.text_input("Для кого", placeholder="Менеджеры Perfetto Sport")
        sel = st.multiselect("Какие кабинеты видны (пусто = все)", list(labels))
        c1, c2 = st.columns(2)
        hide = c1.checkbox("Скрыть себестоимость и ROI")
        days = c2.number_input("Срок, дней (0 = бессрочно)", min_value=0, value=30, step=1)
        if st.form_submit_button("Создать ссылку", type="primary"):
            token = new_share_token()
            with session() as s:
                s.add(ShareLink(token_hash=hash_token(token), label=label.strip(),
                                cabinet_ids=json.dumps([labels[x] for x in sel]), hide_cogs=hide,
                                expires_at=now_msk() + timedelta(days=int(days)) if days else None))
            st.session_state["new_token"] = token

    if st.session_state.get("new_token"):
        st.success("Ссылка создана. Скопируйте её сейчас — потом показать её ещё раз нельзя (хранится только хеш).")
        h = st.context.headers
        host = h.get("X-Forwarded-Host") or h.get("Host") or "<адрес дашборда>"
        proto = h.get("X-Forwarded-Proto") or ("http" if host.startswith(("localhost", "127.")) else "https")
        st.code(f"{proto}://{host}/?share={st.session_state['new_token']}", language=None)

    with session() as s:
        links = s.scalars(select(ShareLink).order_by(ShareLink.id.desc())).all()
    if not links:
        return
    st.subheader("Выданные ссылки")
    names = {v: k for k, v in labels.items()}
    for l in links:
        ids = json.loads(l.cabinet_ids or "[]")
        state = ("отозвана" if l.revoked else "истекла" if l.expires_at and l.expires_at < now_msk() else "действует")
        c1, c2 = st.columns([5, 1])
        c1.markdown(
            f"**{l.label or 'без названия'}** · {state} · кабинеты: "
            f"{', '.join(names.get(i, str(i)) for i in ids) if ids else 'все'}"
            f"{' · без себестоимости' if l.hide_cogs else ''}  \n"
            f"создана {l.created_at:%d.%m.%Y}"
            f"{f', до {l.expires_at:%d.%m.%Y}' if l.expires_at else ''} · открывали {l.uses or 0} раз"
            f"{f', последний {l.last_used_at:%d.%m %H:%M}' if l.last_used_at else ''}")
        if not l.revoked and c2.button("Отозвать", key=f"rev_{l.id}"):
            with session() as s:
                s.get(ShareLink, l.id).revoked = True
            st.rerun()
