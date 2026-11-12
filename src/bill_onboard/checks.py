"""Code checks on fields a model read from an energy bill. No model is involved here."""

import re

from bill_onboard.models import Bill

MPAN_PRIMES = (3, 5, 7, 13, 17, 19, 23, 29, 31, 37, 41, 43)


def mpan_check_digit(first12: str) -> int:
    """Check digit for an MPAN core, from its first 12 digits (published mod-11 method)."""
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("expected exactly 12 digits")
    total = sum(int(d) * p for d, p in zip(first12, MPAN_PRIMES))
    return total % 11 % 10


def check_mpan(bill: Bill) -> list[str]:
    """Flag the MPAN if it is not 13 digits or its check digit is wrong."""
    if bill.mpan_core is None:
        return []  # missing fields are flagged by missing_fields()
    core = bill.mpan_core  # Bill already stores digits only
    if len(core) != 13 or not core.isdigit():
        return ["mpan_core"]
    if mpan_check_digit(core[:12]) != int(core[12]):
        return ["mpan_core"]
    return []


MAX_PERIOD_DAYS = 100  # UK bills are monthly or quarterly


def check_dates(bill: Bill) -> list[str]:
    """Flag both dates if the period runs backwards, has zero length, or is longer than a quarter."""
    if bill.period_start is None or bill.period_end is None:
        return []
    days = (bill.period_end - bill.period_start).days
    if days <= 0 or days > MAX_PERIOD_DAYS:
        return ["period_start", "period_end"]
    return []


PENNY = 0.01


def check_energy_charge(bill: Bill) -> list[str]:
    """Flag usage, rate and charge if usage x rate does not match the printed energy charge."""
    fields = (bill.usage_kwh, bill.unit_rate_p_per_kwh, bill.energy_charge_gbp)
    if None in fields:
        return []
    expected = bill.usage_kwh * bill.unit_rate_p_per_kwh / 100  # pence -> pounds
    if abs(expected - bill.energy_charge_gbp) > PENNY:
        return ["usage_kwh", "unit_rate_p_per_kwh", "energy_charge_gbp"]
    return []


VAT = 1.05
TWO_PENCE = 0.02  # two rounding steps: the subtotal and then the VAT


def billed_days(bill: Bill) -> int:
    """Days charged, counting both the first and the last day."""
    return (bill.period_end - bill.period_start).days + 1


def check_total(bill: Bill) -> list[str]:
    """Flag standing charge and total if (energy + standing x days) x VAT does not match the total."""
    needed = (bill.energy_charge_gbp, bill.standing_charge_p_per_day, bill.total_gbp,
              bill.period_start, bill.period_end)
    if None in needed:
        return []
    standing = bill.standing_charge_p_per_day * billed_days(bill) / 100
    expected = (bill.energy_charge_gbp + standing) * VAT
    if abs(expected - bill.total_gbp) > TWO_PENCE:
        return ["standing_charge_p_per_day", "total_gbp"]
    return []


# Invented suppliers, so one format. Real suppliers each have their own pattern.
ACCOUNT_FORMATS = {"northwind energy": r"A-\d{6}", "brightwater power": r"A-\d{6}",
                   "kestrel utilities": r"A-\d{6}"}


def known_supplier(bill: Bill) -> str | None:
    """The supplier's key in ACCOUNT_FORMATS, ignoring case and spaces; None if unknown."""
    if bill.supplier is None:
        return None
    key = " ".join(bill.supplier.split()).casefold()
    return key if key in ACCOUNT_FORMATS else None


def check_supplier_and_account(bill: Bill) -> list[str]:
    """Flag an unknown supplier, or an account number that does not match its supplier's format."""
    if bill.supplier is None:
        return []  # left to missing_fields
    key = known_supplier(bill)
    if key is None:
        return ["supplier"]
    if bill.account_number is not None and not re.fullmatch(ACCOUNT_FORMATS[key], bill.account_number):
        return ["account_number"]
    return []


# A one-digit slip in a valid-looking account number passes every check, so the customer
# always sees this field and may correct it, even when nothing was flagged.
ALWAYS_CONFIRM = ("account_number",)


def missing_fields(bill: Bill) -> list[str]:
    """Fields the reader left empty, in form order."""
    return [name for name, value in bill if value is None]


CHECKS = (check_supplier_and_account, check_mpan, check_dates, check_energy_charge, check_total)


def check_bill(bill: Bill) -> list[str]:
    """Every field the customer should confirm: unreadable ones first, then ones that failed a check."""
    flagged = missing_fields(bill) + [field for check in CHECKS for field in check(bill)]
    return list(dict.fromkeys(flagged))  # drop repeats, keep the order
