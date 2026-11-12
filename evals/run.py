"""Run every model over every bill and save one JSON line per reading.

Calls extract_bill directly, not through Temporal: this measures the reader.
The workflow logic is covered by tests/test_workflow.py.
Resumable: bills already in a model's results file are skipped.
"""

import json
import sys
import time
from pathlib import Path

from bill_onboard.checks import ALWAYS_CONFIRM, check_bill
from bill_onboard.extract import MODELS, extract_bill
from bill_onboard.models import Bill

# tier -> (bills folder, results folder). Results hold raw readings; evals/report.py re-scores them.
TIERS = {"main": (Path("bills"), Path("evals/results")),
         "hard": (Path("bills_hard"), Path("evals/results/hard"))}
MONEY_TOL = 0.005  # floats compared to half a penny; strings and dates exactly
ATTEMPTS = 3
# gemini-3.8-flash is left out: its free tier allows 20 requests a day, and on 2026-11-12
# it returned 503s and timeouts before that limit. extract_bill still supports it.
EVAL_MODELS = ("gemini-3.5-flash-lite", "qwen/qwen3.8-27b")
PAUSE_S = {"gemini": 6, "groq": 20}  # free tiers: Groq allows 7,000 input tokens/min, a bill is ~2,000


def same_text(got: str | None, want: str) -> bool:
    """Names compare ignoring case and spaces: 'BRIGHTWATER POWER' is the same supplier."""
    return got is not None and " ".join(got.split()).casefold() == " ".join(want.split()).casefold()


def wrong_fields(read: Bill, truth: Bill) -> list[str]:
    """Fields where the model's reading differs from what is printed on the bill."""
    wrong = []
    for name in Bill.model_fields:
        got, want = getattr(read, name), getattr(truth, name)
        if name == "supplier":
            if not same_text(got, want):
                wrong.append(name)
        elif isinstance(want, float) and got is not None:
            if abs(got - want) > MONEY_TOL:
                wrong.append(name)
        elif got != want:
            wrong.append(name)
    return wrong


def real_bill(record: dict) -> Bill:
    """What the customer knows: the printed values, plus any value hidden under a stain."""
    truth = Bill(**record["truth"])
    covered = record.get("covered")
    return truth.model_copy(update={covered["field"]: covered["value"]}) if covered else truth


def outcome(read: Bill, truth: Bill, real: Bill) -> str:
    """Play the workflow: an honest customer corrects the flagged fields and the always-shown ones, then we re-check."""
    if not wrong_fields(read, truth):
        return "correct"
    flags = check_bill(read)
    shown = list(dict.fromkeys(flags + list(ALWAYS_CONFIRM)))
    fixed = read.model_copy(update={f: getattr(real, f) for f in shown})
    if check_bill(fixed):
        return "needs_agent"  # still does not add up, a human looks
    return "fixed_by_customer" if not wrong_fields(fixed, real) else "SILENT_ERROR"


def read_with_retries(image: Path, model: str) -> tuple[Bill | None, dict | None, list[str]]:
    """Up to ATTEMPTS tries; every failure is kept as data, not raised."""
    errors = []
    for attempt in range(ATTEMPTS):
        try:
            bill, stats = extract_bill(image, model)
            return bill, stats, errors
        except Exception as e:  # 503s, timeouts, bad JSON: all count as reliability results
            errors.append(f"{type(e).__name__}: {str(e)[:200]}")
            time.sleep(5 * 2 ** attempt)
    return None, None, errors


def eval_one(record: dict, model: str, bills: Path) -> dict:
    """Read one bill with one model and score it against the printed truth."""
    truth = Bill(**record["truth"])
    read, stats, errors = read_with_retries(bills / f"{record['id']}.png", model)
    row = {k: record.get(k) for k in ("id", "layout", "fault", "damage", "covered")} | {"model": model, "errors": errors}
    if read is None:
        return row | {"outcome": "failed"}
    return row | {"stats": stats, "read": read.model_dump(mode="json"),
                  "wrong": wrong_fields(read, truth), "flags": check_bill(read),
                  "outcome": outcome(read, truth, real_bill(record))}


def run_model(model: str, bills: Path, results: Path) -> None:
    out = results / (model.replace("/", "_") + ".jsonl")
    done = {json.loads(line)["id"] for line in out.read_text().splitlines()} if out.exists() else set()
    for path in sorted(bills.glob("*.json")):
        record = json.loads(path.read_text())
        if record["id"] in done:
            continue
        row = eval_one(record, model, bills)
        with out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(model, row["id"], row["outcome"], row.get("stats", {}).get("latency_s"), flush=True)
        time.sleep(PAUSE_S[MODELS[model]])


if __name__ == "__main__":
    args = sys.argv[1:]
    tier = "hard" if "--hard" in args else "main"
    bills, results = TIERS[tier]
    results.mkdir(parents=True, exist_ok=True)
    for model in [a for a in args if a != "--hard"] or EVAL_MODELS:
        run_model(model, bills, results)
