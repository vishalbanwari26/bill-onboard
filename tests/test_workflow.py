"""Run OnboardBill end to end on a local Temporal dev server, with a fake reader instead of a model."""

import asyncio
import shutil
import uuid

from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from bill_onboard.activities import ReadInput, ReadResult, create_account
from bill_onboard.models import Bill
from bill_onboard.workflow import OnboardBill, OnboardInput

GOOD = dict(supplier="Northwind Energy", account_number="A-104233", mpan_core="1900000000013",
            period_start="2026-09-01", period_end="2026-09-30", usage_kwh=342, unit_rate_p_per_kwh=24.5,
            energy_charge_gbp=83.79, standing_charge_p_per_day=60, total_gbp=106.88)
MISREAD = {**GOOD, "usage_kwh": 432}


def fake_reader(fields: dict):
    """A read_bill activity that returns a bill we choose instead of calling a model."""
    @activity.defn(name="read_bill")
    async def read_bill(inp: ReadInput) -> ReadResult:
        return ReadResult(bill=Bill(**fields), stats={})
    return read_bill


async def onboard(fields: dict, signal: dict | None = None, window_s: int = 60):
    """Start one workflow, optionally answer as the customer, return (result, progress seen while waiting)."""
    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter,
                                                     dev_server_existing_path=shutil.which("temporal")) as env:
        queue = f"test-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=queue, workflows=[OnboardBill],
                          activities=[fake_reader(fields), create_account]):
            handle = await env.client.start_workflow(
                OnboardBill.run, OnboardInput("unused.png", "fake", customer_window_s=window_s),
                id=f"wf-{uuid.uuid4()}", task_queue=queue)
            seen = None
            if signal is not None or fields != GOOD:
                for _ in range(50):  # wait until the workflow is waiting for the customer
                    seen = await handle.query(OnboardBill.progress)
                    if seen["status"] != "reading":
                        break
                    await asyncio.sleep(0.1)
            if signal is not None:
                await handle.signal(OnboardBill.confirm_fields, signal)
            return await handle.result(), seen


def test_clean_bill_is_onboarded():
    result, _ = asyncio.run(onboard(GOOD))
    assert result.status == "onboarded" and result.account_id == "DEMO-A-104233"


def test_customer_fixes_flagged_field():
    result, seen = asyncio.run(onboard(MISREAD, signal={"usage_kwh": 342}))
    assert seen == {"status": "waiting_for_customer",
                    "flagged": ["usage_kwh", "unit_rate_p_per_kwh", "energy_charge_gbp"]}
    assert result.status == "onboarded" and result.bill.usage_kwh == 342


def test_no_answer_expires():
    result, _ = asyncio.run(onboard(MISREAD, window_s=2))
    assert result.status == "expired"


def test_unflagged_field_cannot_be_changed():
    result, _ = asyncio.run(onboard(MISREAD, signal={"usage_kwh": 342, "mpan_core": "9999999999999"}))
    assert result.status == "onboarded" and result.bill.mpan_core == "1900000000013"


def test_account_number_can_always_be_corrected():
    result, _ = asyncio.run(onboard(MISREAD, signal={"usage_kwh": 342, "account_number": "A-104234"}))
    assert result.status == "onboarded" and result.bill.account_number == "A-104234"


def test_wrong_correction_goes_to_agent():
    result, _ = asyncio.run(onboard(MISREAD, signal={"usage_kwh": 999}))
    assert result.status == "needs_agent"
