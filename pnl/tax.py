"""Taxes of a legal entity by month, as an accrual estimate (not payment schedule).

Rules follow «Налоги РФ 2026» (NK RF as of 04.08.2026, law 228-FZ):
- the tax base is the seller's sales revenue (incl. WB СПП / Ozon points), not the payout;
- VAT thresholds and taxes are counted per entity across all its cabinets;
- everything is cumulative from January, the monthly figure is the increment.
"""

from dataclasses import dataclass

REGIMES = {
    "USN_D": "УСН «Доходы»",
    "USN_DR": "УСН «Доходы минус расходы»",
    "OSNO_OOO": "ОСНО (ООО)",
    "OSNO_IP": "ОСНО (ИП, НДФЛ)",
    "AUSN_D": "АУСН «Доходы» 8 %",
    "AUSN_DR": "АУСН «Доходы минус расходы» 20 %",
    "NONE": "Без налога (не считать)",
}

VAT_MODES = {
    "auto": "Автоматически по порогам 2026 (УСН)",
    "exempt": "Освобождение от НДС",
    "5": "НДС 5 % без вычетов",
    "7": "НДС 7 % без вычетов",
    "22": "НДС 22 % (10 % для отмеченных товаров) с вычетами",
}

DEFAULT_USN_RATE = {"USN_D": 0.06, "USN_DR": 0.15}

# 2026 thresholds (rubles, revenue without VAT is not required by law: income is gross)
VAT_EXEMPT_LIMIT = {2025: 20e6, 2026: 20e6, 2027: 20e6, 2028: 20e6, 2029: 20e6, 2030: 15e6}
VAT_5_LIMIT = {2026: 272.5e6, 2027: 288.25e6}
VAT_7_LIMIT = {2026: 490.5e6, 2027: 518.85e6}
USN_LIMIT = {2026: 490.5e6, 2027: 518.85e6}
IP_CONTRIB_CAP_SHARE_EMPLOYER = 0.5

NDFL_SCALE = [(2.4e6, 0.13), (5e6, 0.15), (20e6, 0.18), (50e6, 0.20), (float("inf"), 0.22)]

# Share of marketplace service costs that carries input VAT (WB/Ozon invoices with 22 %).
MP_SERVICES_VAT = 0.22


@dataclass
class MonthInput:
    year: int
    month: int
    revenue: float          # sales minus returns, seller price, with VAT
    revenue_vat10: float    # part of revenue on 10 % goods
    mp_costs: float         # marketplace services incl. ads, positive, with VAT
    cogs: float             # cost of goods sold, positive
    fixed: float            # fixed costs, positive


@dataclass
class MonthTax:
    vat_mode: str
    vat: float              # VAT payable for the month (>= 0)
    tax: float              # income/profit tax for the month (increment of YTD)
    note: str = ""


def _ndfl(base: float) -> float:
    tax, prev = 0.0, 0.0
    for limit, rate in NDFL_SCALE:
        if base <= prev:
            break
        tax += (min(base, limit) - prev) * rate
        prev = limit
    return tax


def _auto_vat_mode(year: int, prior_year_revenue: float, ytd_before: float, ytd_after: float,
                   prev_mode: str) -> tuple[str, str]:
    """VAT mode for this month under USN when the setting is 'auto'."""
    limit = VAT_EXEMPT_LIMIT.get(year, 20e6)
    lim5 = VAT_5_LIMIT.get(year, 272.5e6)
    if prior_year_revenue <= limit and ytd_before <= limit:
        if ytd_after > limit:
            return "exempt", f"доход превысил {limit/1e6:.0f} млн — НДС со следующего месяца"
        return "exempt", ""
    if prev_mode in ("5", "7"):
        if prev_mode == "5" and ytd_before > lim5:
            return "7", "превышен порог 5 % — ставка 7 %"
        return prev_mode, ""
    return ("5" if ytd_before <= lim5 else "7"), ""


def compute_entity_year(regime: str, months: list[MonthInput], *, usn_rate: float | None = None,
                        vat_mode: str = "auto", has_employees: bool = False,
                        ip_contrib_monthly: float = 0.0, prior_year_revenue: float = 0.0,
                        settings_by_month: dict | None = None) -> list[MonthTax]:
    """Months of one calendar year in order. settings_by_month: {month: dict} overrides."""
    out = []
    ytd_rev = ytd_inc = ytd_exp = ytd_contrib = ytd_tax = 0.0
    prev_mode = "exempt"
    for m in months:
        st = (settings_by_month or {}).get(m.month, {})
        regime_m = st.get("regime", regime)
        rate = st.get("usn_rate", usn_rate) or DEFAULT_USN_RATE.get(regime_m, 0.0)
        vmode = st.get("vat_mode", vat_mode)
        employees = st.get("has_employees", has_employees)
        contrib = st.get("ip_contrib_monthly", ip_contrib_monthly) or 0.0
        prior = st.get("prior_year_revenue", prior_year_revenue) or 0.0
        note = ""

        if regime_m == "NONE":
            out.append(MonthTax("exempt", 0.0, 0.0, "налог не считается"))
            continue

        # VAT
        if regime_m in ("AUSN_D", "AUSN_DR"):
            mode = "exempt"
        elif regime_m in ("OSNO_OOO", "OSNO_IP"):
            mode = "22"
        elif vmode == "auto":
            mode, note = _auto_vat_mode(m.year, prior, ytd_rev, ytd_rev + m.revenue, prev_mode)
        else:
            mode = vmode
        prev_mode = mode

        if mode == "exempt":
            vat_out = vat_in = 0.0
        elif mode in ("5", "7"):
            r = int(mode) / 100
            vat_out, vat_in = m.revenue * r / (1 + r), 0.0
        else:
            base22 = m.revenue - m.revenue_vat10
            vat_out = base22 * 0.22 / 1.22 + m.revenue_vat10 * 0.10 / 1.10
            vat_in = m.mp_costs * MP_SERVICES_VAT / (1 + MP_SERVICES_VAT)
        vat = vat_out - vat_in

        income = m.revenue - vat_out
        # with deductible VAT the expense base is net of it; otherwise VAT stays in expenses
        expenses = m.mp_costs + m.cogs + m.fixed - vat_in
        ytd_rev += m.revenue
        ytd_inc += income
        ytd_exp += expenses
        ytd_contrib += contrib

        if regime_m == "USN_D":
            gross = ytd_inc * rate
            cap = gross if not employees else gross * IP_CONTRIB_CAP_SHARE_EMPLOYER
            tax_cum = max(0.0, gross - min(ytd_contrib, cap))
        elif regime_m == "USN_DR":
            tax_cum = max((ytd_inc - ytd_exp - ytd_contrib) * rate, ytd_inc * 0.01)
        elif regime_m == "OSNO_OOO":
            tax_cum = max(0.0, ytd_inc - ytd_exp) * 0.25
        elif regime_m == "OSNO_IP":
            tax_cum = _ndfl(max(0.0, ytd_inc - ytd_exp - ytd_contrib))
        elif regime_m == "AUSN_D":
            tax_cum = ytd_inc * 0.08
        elif regime_m == "AUSN_DR":
            tax_cum = max((ytd_inc - ytd_exp) * 0.20, ytd_inc * 0.03)
        else:
            tax_cum = 0.0

        if regime_m in ("USN_D", "USN_DR") and ytd_rev > USN_LIMIT.get(m.year, 490.5e6):
            note = (note + "; " if note else "") + "доход выше лимита УСН — право на УСН утрачено"

        out.append(MonthTax(mode, vat, tax_cum - ytd_tax, note))
        ytd_tax = tax_cum
    return out
