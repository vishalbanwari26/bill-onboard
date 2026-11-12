"""Temporal activities: the steps with side effects (model calls, account creation)."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from temporalio import activity

from bill_onboard.extract import extract_bill
from bill_onboard.models import Bill


@dataclass
class ReadInput:
    image_path: str
    model: str


@dataclass
class ReadResult:
    bill: Bill
    stats: dict


@activity.defn
async def read_bill(inp: ReadInput) -> ReadResult:
    """The model call. Temporal runs it once, saves the result, and retries it on errors."""
    bill, stats = await asyncio.to_thread(extract_bill, Path(inp.image_path), inp.model)
    return ReadResult(bill=bill, stats=stats)


@activity.defn
async def create_account(bill: Bill) -> str:
    """Stub for the real customer system: here it only returns an id."""
    activity.logger.info("creating account for %s", bill.account_number)
    return f"DEMO-{bill.account_number}"
