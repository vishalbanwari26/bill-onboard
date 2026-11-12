"""Run a worker that executes OnboardBill workflows and their activities."""

import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from bill_onboard.activities import create_account, read_bill
from bill_onboard.workflow import OnboardBill

TASK_QUEUE = "bill-onboard"


async def main() -> None:
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    await Worker(client, task_queue=TASK_QUEUE, workflows=[OnboardBill],
                 activities=[read_bill, create_account]).run()


if __name__ == "__main__":
    asyncio.run(main())
