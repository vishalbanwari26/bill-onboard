from bill_onboard.checks import (check_bill, check_dates, check_energy_charge, check_mpan,
                                 check_supplier_and_account, check_total, mpan_check_digit)
from bill_onboard.models import Bill


def bill(**fields) -> Bill:
    """A Bill with every field empty except the ones given."""
    return Bill(**{**dict.fromkeys(Bill.model_fields), **fields})


def test_mpan_check_digit_known_examples():
    assert mpan_check_digit("190000000001") == 3   # 1*3 + 9*5 + 1*43 = 91 -> 91 % 11 = 3
    assert mpan_check_digit("190000000002") == 2   # 3 + 45 + 2*43 = 134 -> 134 % 11 = 2


def test_check_mpan():
    assert check_mpan(bill(mpan_core="1900000000013")) == []             # valid
    assert check_mpan(bill(mpan_core="19 0000 0000 013")) == []          # spaces as printed
    assert check_mpan(bill(mpan_core="1900000000014")) == ["mpan_core"]  # wrong check digit
    assert check_mpan(bill(mpan_core="190000000001")) == ["mpan_core"]   # 12 digits
    assert check_mpan(bill(mpan_core=None)) == []                        # left to missing_fields


def test_check_dates():
    both = ["period_start", "period_end"]
    assert check_dates(bill(period_start="2026-09-01", period_end="2026-09-30")) == []
    assert check_dates(bill(period_start="2026-09-30", period_end="2026-09-01")) == both  # backwards
    assert check_dates(bill(period_start="2026-01-01", period_end="2026-09-30")) == both  # 9 months
    assert check_dates(bill(period_start="2026-09-01", period_end=None)) == []


def test_check_energy_charge():
    trio = ["usage_kwh", "unit_rate_p_per_kwh", "energy_charge_gbp"]
    assert check_energy_charge(bill(usage_kwh=342, unit_rate_p_per_kwh=24.5, energy_charge_gbp=83.79)) == []     # exact
    assert check_energy_charge(bill(usage_kwh=342.5, unit_rate_p_per_kwh=24.5, energy_charge_gbp=83.91)) == []   # 83.9125 rounded
    assert check_energy_charge(bill(usage_kwh=432, unit_rate_p_per_kwh=24.5, energy_charge_gbp=83.79)) == trio   # digits swapped
    assert check_energy_charge(bill(usage_kwh=342, unit_rate_p_per_kwh=None, energy_charge_gbp=83.79)) == []


def test_check_total():
    sep = dict(period_start="2026-09-01", period_end="2026-09-30", energy_charge_gbp=83.79, standing_charge_p_per_day=60)
    assert check_total(bill(**sep, total_gbp=106.88)) == []  # (83.79 + 30 x 0.60) x 1.05 = 106.8795
    assert check_total(bill(**sep, total_gbp=116.88)) == ["standing_charge_p_per_day", "total_gbp"]
    assert check_total(bill(**sep, total_gbp=None)) == []


GOOD = dict(supplier="Northwind Energy", account_number="A-104233", mpan_core="1900000000013",
            period_start="2026-09-01", period_end="2026-09-30", usage_kwh=342, unit_rate_p_per_kwh=24.5,
            energy_charge_gbp=83.79, standing_charge_p_per_day=60, total_gbp=106.88)


def test_check_bill_clean():
    assert check_bill(Bill(**GOOD)) == []


def test_check_bill_collects_missing_and_failed():
    b = Bill(**{**GOOD, "account_number": None, "usage_kwh": 432})
    assert check_bill(b) == ["account_number", "usage_kwh", "unit_rate_p_per_kwh", "energy_charge_gbp"]


def test_check_supplier_and_account():
    assert check_supplier_and_account(bill(supplier="BRIGHTWATER  POWER", account_number="A-309999")) == []  # case, spaces
    assert check_supplier_and_account(bill(supplier="Octopus", account_number="A-309999")) == ["supplier"]    # unknown
    assert check_supplier_and_account(bill(supplier="Northwind Energy", account_number="4-309999")) == ["account_number"]  # A read as 4
    assert check_supplier_and_account(bill(supplier="Northwind Energy", account_number="A-30999")) == ["account_number"]   # digit lost
    assert check_supplier_and_account(bill(supplier=None, account_number="4-309999")) == []  # left to missing_fields
