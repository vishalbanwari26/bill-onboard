from datetime import date

from pydantic import BaseModel, field_validator


class Bill(BaseModel):
    """Fields read from one UK electricity bill. None means the reader could not read it."""

    supplier: str | None
    account_number: str | None
    mpan_core: str | None  # 13 digits, last one is the check digit
    period_start: date | None
    period_end: date | None
    usage_kwh: float | None
    unit_rate_p_per_kwh: float | None
    energy_charge_gbp: float | None  # should equal usage_kwh * unit_rate / 100
    standing_charge_p_per_day: float | None
    total_gbp: float | None  # (energy + standing * days) * 1.05 VAT

    @field_validator("mpan_core")
    @classmethod
    def digits_only(cls, v: str | None) -> str | None:
        """Bills print the MPAN in groups; store digits only so '19 0000 0000 013' == '1900000000013'."""
        return v.replace(" ", "") if v is not None else None
