from datetime import date

from bill_onboard.models import Bill

UNREADABLE = dict.fromkeys(Bill.model_fields)  # every field None


def test_bill_accepts_unreadable_fields():
    bill = Bill(**UNREADABLE)
    assert bill.mpan_core is None


def test_bill_parses_model_output_strings():
    bill = Bill(**{**UNREADABLE, "period_start": "2026-09-01", "usage_kwh": "342.5"})
    assert bill.period_start == date(2026, 9, 1)
    assert bill.usage_kwh == 342.5


def test_mpan_spaces_are_removed():
    assert Bill(**{**UNREADABLE, "mpan_core": "19 0000 0000 013"}).mpan_core == "1900000000013"
