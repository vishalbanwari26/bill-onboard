"""OnboardBill: read the bill, check it, wait for the customer if needed, then create the account."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():  # our modules are safe to share with the replay sandbox
    from bill_onboard.activities import ReadInput, create_account, read_bill
    from bill_onboard.checks import ALWAYS_CONFIRM, check_bill
    from bill_onboard.models import Bill

READ_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0,
                         maximum_interval=timedelta(seconds=30), maximum_attempts=6)


@dataclass
class OnboardInput:
    image_path: str
    model: str
    customer_window_s: int = 7 * 24 * 3600  # how long to wait for the customer to confirm


@dataclass
class OnboardResult:
    status: str  # onboarded | needs_agent | expired
    bill: Bill
    flagged_by_checks: list[str]
    account_id: str | None = None


@workflow.defn
class OnboardBill:
    def __init__(self) -> None:
        self.status = "reading"
        self.flagged: list[str] = []
        self.confirmed: dict | None = None
        self.bill: Bill | None = None

    @workflow.run
    async def run(self, inp: OnboardInput) -> OnboardResult:
        read = await workflow.execute_activity(read_bill, ReadInput(inp.image_path, inp.model),
                                               start_to_close_timeout=timedelta(seconds=90),
                                               retry_policy=READ_RETRY)
        bill = self.bill = read.bill
        self.flagged = first_flags = check_bill(bill)  # pure code, safe in a workflow
        if self.flagged:
            self.status = "waiting_for_customer"
            try:
                await workflow.wait_condition(lambda: self.confirmed is not None, timeout=timedelta(seconds=inp.customer_window_s))
            except asyncio.TimeoutError:
                self.status = "expired"
                return OnboardResult("expired", bill, first_flags)
            bill = self.bill = Bill(**{**bill.model_dump(), **self.confirmed})
            self.flagged = check_bill(bill)  # re-check what the customer typed
            if self.flagged:
                self.status = "needs_agent"
                return OnboardResult("needs_agent", bill, first_flags)
        self.status = "creating_account"
        account = await workflow.execute_activity(create_account, bill,
                                                  start_to_close_timeout=timedelta(seconds=30))
        self.status = "onboarded"
        return OnboardResult("onboarded", bill, first_flags, account)

    @workflow.signal
    def confirm_fields(self, values: dict) -> None:
        """The customer's values, accepted only for flagged fields and fields always shown for confirmation."""
        self.confirmed = {k: v for k, v in values.items() if k in self.flagged or k in ALWAYS_CONFIRM}

    @workflow.query
    def progress(self) -> dict:
        return {"status": self.status, "flagged": self.flagged}

    @workflow.query
    def bill_as_read(self) -> Bill | None:
        """The values the customer is asked to check, so a screen can show them."""
        return self.bill
