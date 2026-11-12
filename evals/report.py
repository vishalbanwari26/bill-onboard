"""Turn evals/results/*.jsonl into the numbers in the README."""

import json
import re
import sys
from pathlib import Path
from statistics import mean, median

from bill_onboard.checks import check_bill
from bill_onboard.models import Bill
from run import TIERS, outcome, real_bill, wrong_fields

# USD per 1M tokens (input, output), standard paid tier, checked 2026-11-12.
# Groq lists Qwen3.8-27B as a preview model.
PRICES = {"gemini-3.5-flash-lite": (0.30, 2.50), "qwen/qwen3.8-27b": (0.80, 4.00)}


def cost(row: dict) -> float:
    """USD for one reading, from measured tokens and the published price."""
    price_in, price_out = PRICES[row["model"]]
    s = row["stats"]
    return (s["input_tokens"] * price_in + s["output_tokens"] * price_out) / 1_000_000


def summarise(rows: list[dict]) -> dict:
    """One model's headline numbers."""
    read = [r for r in rows if r["outcome"] != "failed"]
    faulty = [r for r in read if r["fault"]]
    outcomes = [r["outcome"] for r in read]
    return {
        "read": len(read),
        "correct": outcomes.count("correct"),
        "fixed_by_customer": outcomes.count("fixed_by_customer"),
        "needs_agent": outcomes.count("needs_agent"),
        "silent_errors": outcomes.count("SILENT_ERROR"),  # wrong data that would reach the account
        "faults_caught": sum(bool(r["flags"]) for r in faulty),
        "faulty_bills": len(faulty),
        "failed_calls": sum(r["outcome"] == "failed" for r in rows),
        "median_latency_s": median(r["stats"]["latency_s"] for r in read),
        "usd_per_1k_bills": round(1000 * mean(cost(r) for r in read), 2),
    } | covered_counts(read)


def covered_counts(read: list[dict]) -> dict:
    """Hard tier only: did the model leave a stained value null, as told, or fill it in?"""
    covered = [r for r in read if r.get("covered")]
    if not covered:
        return {}
    filled = [r for r in covered if r["read"][r["covered"]["field"]] is not None]
    return {"covered_bills": len(covered), "filled_covered": len(filled),
            "filled_with_hidden_value": sum(r["read"][r["covered"]["field"]] == r["covered"]["value"] for r in filled)}


def field_accuracy(rows: list[dict]) -> dict[str, float]:
    """Share of readings where each field was right, in form order."""
    read = [r for r in rows if r["outcome"] != "failed"]
    return {name: round(sum(name not in r["wrong"] for r in read) / len(read), 3)
            for name in Bill.model_fields}


def accuracy_by(rows: list[dict], key: str) -> dict[str, str]:
    """Bills fully correct per layout or per damage type, as 'right/total'."""
    groups: dict[str, list[bool]] = {}
    for r in rows:
        if r["outcome"] != "failed":
            groups.setdefault(r[key], []).append(not r["wrong"])
    return {k: f"{sum(v)}/{len(v)}" for k, v in sorted(groups.items())}


def rescore(row: dict, bills: Path) -> dict:
    """Score again from the saved reading, so a scoring fix needs no new API calls."""
    if row["outcome"] == "failed":
        return row
    record = json.loads((bills / f"{row['id']}.json").read_text())
    truth, read = Bill(**record["truth"]), Bill(**row["read"])
    return row | {"wrong": wrong_fields(read, truth), "flags": check_bill(read),
                  "outcome": outcome(read, truth, real_bill(record))}


def load(path: Path, bills: Path) -> list[dict]:
    return [rescore(json.loads(line), bills) for line in path.read_text().splitlines()]


def results_table(rows_by_model: dict[str, list[dict]], hard: bool) -> str:
    """One Markdown table, one row per model, straight from summarise()."""
    head = "| Model | Read | Correct | Fixed by customer | Needs agent | **Silent errors** | " + \
           ("Stained values left empty" if hard else "Planted errors caught") + " | Median latency | $ per 1,000 bills |"
    lines = [head, "|" + "---|" * 9]
    for model, rows in rows_by_model.items():
        s = summarise(rows)
        extra = (f"{s['covered_bills'] - s['filled_covered']}/{s['covered_bills']}" if hard
                 else f"{s['faults_caught']}/{s['faulty_bills']}")
        lines.append(f"| {model} | {s['read']} | {s['correct']} | {s['fixed_by_customer']} | {s['needs_agent']} | "
                     f"**{s['silent_errors']}** | {extra} | {s['median_latency_s']:.2f} s | {s['usd_per_1k_bills']:.2f} |")
    return "\n".join(lines)


def rows_by_model(tier: str) -> dict[str, list[dict]]:
    """Scored rows for every model that has readings in this tier."""
    bills, results = TIERS[tier]
    out = {}
    for path in sorted(results.glob("*.jsonl")):
        rows = load(path, bills)
        if any(r["outcome"] != "failed" for r in rows):
            out[rows[0]["model"]] = rows
    return out


def update_readme(readme: Path = Path("README.md")) -> None:
    """Rewrite the text between <!-- main-table --> and <!-- /main-table -->, and the same for hard-table."""
    text = readme.read_text()
    for tier, hard in (("main", False), ("hard", True)):
        table = results_table(rows_by_model(tier), hard)
        text, n = re.subn(rf"(<!-- {tier}-table -->\n).*?(\n<!-- /{tier}-table -->)",
                          lambda m: m.group(1) + table + m.group(2), text, flags=re.S)
        if n != 1:
            raise ValueError(f"README needs exactly one {tier}-table marker pair, found {n}")
    readme.write_text(text)


def print_report() -> None:
    for tier, (bills, results) in TIERS.items():
        for path in sorted(results.glob("*.jsonl")):
            rows = load(path, bills)
            if not any(r["outcome"] != "failed" for r in rows):
                continue
            print(f"[{tier}]", rows[0]["model"], summarise(rows))
            print("  fields:", field_accuracy(rows))
            print("  layout:", accuracy_by(rows, "layout"), " damage:", accuracy_by(rows, "damage"))


if __name__ == "__main__":
    update_readme() if "--readme" in sys.argv else print_report()
