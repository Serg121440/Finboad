"""Several table rows ticked with the checkboxes: their sum and what can be done with them —
open the one product, compare 2–4 side by side, download the ticked ones, clear the ticks.
A tick no longer opens a window by itself: the window opens only by its button."""

from typing import Callable

import pandas as pd
import streamlit as st

from dashboard.xlsx import MIME

COMPARE_MAX = 4


def table_key(name: str, state: tuple) -> str:
    """The table's widget key: a new filter, sort or view (state) and «Снять выбор» start with no ticks —
    the selection is row positions, it must not move onto other products."""
    return f"{name}_{abs(hash(state))}_{st.session_state.get(f'_clear_{name}', 0)}"


def _clear(name: str):
    st.session_state[f"_clear_{name}"] = st.session_state.get(f"_clear_{name}", 0) + 1


def _cell(x, row: str) -> str:
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return "—"
    if isinstance(x, (int, float)):
        if "%" in row:
            return f"{x + 0.0 if round(x, 1) else 0.0:.1f}".replace(".", ",")      # no «-0,0»
        return f"{x if round(x) else 0.0:,.0f}".replace(",", " ")
    return str(x)


def compare_frame(sel: pd.DataFrame, label: str = "Артикул") -> pd.DataFrame:
    """The ticked rows side by side: one column per product (its article), the table's columns as rows."""
    names = sel[label].fillna("—").astype(str).replace("", "—")
    if "Кабинет" in sel.columns and names.duplicated().any():      # one article in two cabinets
        names = names + " · " + sel["Кабинет"].astype(str)
    names = names.where(~names.duplicated(), names + " (" + pd.Series(range(len(names)), index=names.index)
                        .add(1).astype(str) + ")")
    t = sel.drop(columns=[label]).T
    t.columns = list(names)
    return pd.DataFrame({c: [_cell(x, r) for r, x in t[c].items()] for c in t.columns}, index=t.index)


@st.dialog("Сравнение товаров", width="large")
def compare_dialog(frame: pd.DataFrame):
    st.dataframe(frame, use_container_width=True, height=min(35 * (len(frame) + 1) + 3, 700))


def bar(slot, name: str, n: int, summary: str, what: str, excel: Callable[[], bytes], file_name: str) -> str | None:
    """The line above the table. name — the same as in table_key («Снять выбор» renews that key); n — ticked rows; what — the window of one row («карточку», «разбор»).
    Returns «open», «compare» or None."""
    with slot:
        if not n:
            st.caption(f"Отметьте товары галочками: появятся их сумма и кнопки «Открыть {what}», «Сравнить» "
                       f"(2–{COMPARE_MAX} товара) и «Excel выбранных».")
            return None
        with st.container(border=True):
            st.markdown(f"**Выбрано: {n}** · {summary}")
            row = st.container(horizontal=True, gap="small")
            opened = row.button(f"Открыть {what}", icon=":material/open_in_new:", type="primary", disabled=n != 1,
                                key=f"{name}_open", help=None if n == 1 else f"Открыть {what} — у одного товара")
            compared = row.button("Сравнить", icon=":material/compare_arrows:", disabled=not 2 <= n <= COMPARE_MAX,
                                  key=f"{name}_cmp",
                                  help=f"Сравнить 2–{COMPARE_MAX} товара: показатели рядом, по столбцу на товар")
            row.download_button("Excel выбранных", excel, file_name=file_name, mime=MIME, on_click="ignore",
                                icon=":material/download:", key=f"{name}_xlsx")
            row.button("Снять выбор", icon=":material/close:", type="tertiary", key=f"{name}_clear",
                       on_click=_clear, args=(name,))
    return "open" if opened else "compare" if compared else None
