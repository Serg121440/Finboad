import pytest

from pnl.tax import MonthInput, compute_entity_year


def months(revenues, mp_costs=0.0, cogs=0.0):
    return [MonthInput(2026, i + 1, r, 0.0, mp_costs, cogs, 0.0) for i, r in enumerate(revenues)]


def test_usn_income_6_percent_with_ip_contributions():
    res = compute_entity_year("USN_D", months([1_000_000, 1_000_000]), ip_contrib_monthly=10_000)
    assert res[0].vat == 0
    assert res[0].tax == pytest.approx(60_000 - 10_000)
    assert sum(r.tax for r in res) == pytest.approx(120_000 - 20_000)


def test_usn_income_employer_cap_50_percent():
    res = compute_entity_year("USN_D", months([100_000]), ip_contrib_monthly=10_000, has_employees=True)
    assert res[0].tax == pytest.approx(6_000 - 3_000)


def test_usn_income_minus_expenses_minimum_tax():
    res = compute_entity_year("USN_DR", months([1_000_000], mp_costs=600_000, cogs=500_000))
    assert res[0].tax == pytest.approx(10_000)  # 1 % of income, profit is negative


def test_vat_exemption_ends_month_after_20m():
    res = compute_entity_year("USN_D", months([12e6, 12e6, 12e6]))
    assert [r.vat_mode for r in res] == ["exempt", "exempt", "5"]
    assert res[2].vat == pytest.approx(12e6 * 5 / 105)
    # income for USN is revenue without the VAT charged
    assert res[2].tax == pytest.approx((12e6 - 12e6 * 5 / 105) * 0.06)


def test_osno_ooo_vat_with_deductions_and_profit_tax():
    res = compute_entity_year("OSNO_OOO", months([1_220_000], mp_costs=244_000, cogs=500_000))
    vat_out, vat_in = 220_000, 44_000
    assert res[0].vat == pytest.approx(vat_out - vat_in)
    income, expenses = 1_000_000, 244_000 - vat_in + 500_000
    assert res[0].tax == pytest.approx((income - expenses) * 0.25)


def test_ausn_income_minus_expenses_minimum_3_percent():
    res = compute_entity_year("AUSN_DR", months([1_000_000], mp_costs=990_000))
    assert res[0].tax == pytest.approx(30_000)


def test_regime_from_marketplace():
    from pnl.tax import regime_from_marketplace
    assert regime_from_marketplace("OSNO", "ooo") == "OSNO_OOO"
    assert regime_from_marketplace("OSNO", "ip") == "OSNO_IP"
    assert regime_from_marketplace("USN_INCOME", "ip") == "USN_D"
    assert regime_from_marketplace("USN_INCOME_MINUS_EXPENSES", "ooo") == "USN_DR"
    assert regime_from_marketplace("", "ooo") is None
