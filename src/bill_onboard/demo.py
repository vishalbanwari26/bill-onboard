"""Run one bill through OnboardBill on a local Temporal server.

Needs `make server` and `make worker` running in two other terminals. Then:
    make demo BILL=bills_hard/hb01.png
While it waits for your answer, stop the worker (Ctrl-C), start it again, then answer:
the bill was waiting on the server, not in this script or the worker, so it finishes.
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from bill_onboard.checks import ALWAYS_CONFIRM
from bill_onboard.models import Bill
from bill_onboard.worker import TASK_QUEUE
from bill_onboard.workflow import OnboardBill, OnboardInput


def ask_customer(fields: list[str], bill: Bill) -> dict:
    """Play the customer in the terminal: check each flagged field and the account number."""
    print("Please check these fields (Enter keeps the value as read):")
    answers = {f: input(f"  {f} [{getattr(bill, f)}]: ").strip() for f in dict.fromkeys(fields + list(ALWAYS_CONFIRM))}
    return {f: v for f, v in answers.items() if v}


async def main(image: str, model: str) -> None:
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    handle = await client.start_workflow(OnboardBill.run, OnboardInput(image, model),
                                         id=f"onboard-{Path(image).stem}-{uuid4().hex[:6]}",
                                         task_queue=TASK_QUEUE)
    print(f"Started {handle.id}  (history: http://localhost:8233)")
    while (p := await handle.query(OnboardBill.progress))["status"] == "reading":
        await asyncio.sleep(0.5)
    print("status:", p["status"], "| flagged:", p["flagged"])
    if p["status"] == "waiting_for_customer":
        bill = await handle.query(OnboardBill.bill_as_read)
        await handle.signal(OnboardBill.confirm_fields, ask_customer(p["flagged"], bill))
    result = await handle.result()
    print("result:", result.status, "| account:", result.account_id)
    print(result.bill.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "gemini-3.5-flash-lite"))
