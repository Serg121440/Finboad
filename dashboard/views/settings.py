"""Settings page — API sync, data management."""

import streamlit as st

from config import WB_API_TOKEN, OZON_CLIENT_ID, OZON_API_KEY
from dashboard.shared import render_sync_log_sidebar
from dashboard.theme import status_dot


def render():
    render_sync_log_sidebar()

    st.title("Настройки")

    # ── API Status ────────────────────────────────────────────────────────────
    st.subheader("API подключения")

    wb_ok = bool(WB_API_TOKEN)
    oz_ok = bool(OZON_CLIENT_ID and OZON_API_KEY)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(status_dot(wb_ok, "Wildberries API"), unsafe_allow_html=True)
        if not wb_ok:
            st.caption("Задай переменную окружения `WB_API_TOKEN`")
    with col2:
        st.markdown(status_dot(oz_ok, "Ozon API"), unsafe_allow_html=True)
        if not oz_ok:
            st.caption("Задай `OZON_CLIENT_ID` и `OZON_API_KEY`")

    if wb_ok or oz_ok:
        st.divider()
        st.subheader("Синхронизация через API")
        days_back = st.number_input("Глубина (дней)", min_value=7,
                                    max_value=365, value=90)
        if st.button("Синхронизировать WB / Ozon", type="primary"):
            from normalizer import full_sync
            with st.spinner("Синхронизация…"):
                results = full_sync(days_back=int(days_back))
            st.success(f"WB: {results['wb']} зап. | Ozon: {results['ozon']} зап.")
            st.rerun()

    st.divider()

    # ── Data Management ───────────────────────────────────────────────────────
    st.subheader("Управление данными")

    src_options = [
        "Отчёт WB (продажи)",
        "Рекламные расходы",
        "Себестоимость (COGS)",
        "Все продажи и реклама",
    ]
    clear_target = st.selectbox("Что удалить", src_options, key="clear_target")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🗑 Очистить", key="btn_clear", type="secondary"):
            st.session_state["confirm_clear"] = True
    with col_info:
        st.caption("⚠ Удаление необратимо. Подтверждение появится ниже.")

    if st.session_state.get("confirm_clear"):
        st.warning(f"Удалить «{clear_target}»?")
        col_yes, col_no, _ = st.columns([1, 1, 4])
        with col_yes:
            if st.button("✅ Да, удалить", key="btn_yes"):
                try:
                    from sqlalchemy import text as sqlt
                    from database.db import engine
                    with engine.connect() as conn:
                        if clear_target == "Отчёт WB (продажи)":
                            conn.execute(sqlt("DELETE FROM sales"))
                        elif clear_target == "Рекламные расходы":
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                            conn.execute(sqlt("UPDATE sales SET ad_spend = 0.0"))
                        elif clear_target == "Себестоимость (COGS)":
                            conn.execute(sqlt("DELETE FROM cost_of_goods"))
                        elif clear_target == "Все продажи и реклама":
                            conn.execute(sqlt("DELETE FROM sales"))
                            conn.execute(sqlt("DELETE FROM ad_spend"))
                        conn.commit()
                    st.session_state["confirm_clear"] = False
                    st.success("Данные удалены")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with col_no:
            if st.button("❌ Отмена", key="btn_no"):
                st.session_state["confirm_clear"] = False
                st.rerun()
