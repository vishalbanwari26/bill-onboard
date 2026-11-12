"""Read a bill image with a vision model. One function for all models via OpenAI-compatible endpoints."""

import base64
import os
import time
from pathlib import Path

from openai import OpenAI

from bill_onboard.models import Bill

PROVIDERS = {"gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
             "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY")}
MODELS = {"gemini-3.8-flash": "gemini", "gemini-3.5-flash-lite": "gemini", "qwen/qwen3.8-27b": "groq"}

PROMPT = """Read this UK electricity bill. Return JSON with exactly these keys: {keys}.
- Copy values as printed. Do not calculate, fix or complete anything.
- Unit rate and standing charge in pence: if printed in pounds, convert (£0.2370 -> 23.70).
- Dates as YYYY-MM-DD. Money in pounds as a plain number. account_number and mpan_core as strings.
- total_gbp is the amount for this bill, not a previous bill.
- If a value is missing or unreadable, use null. Never guess."""


def image_data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def extract_bill(image: Path, model: str) -> tuple[Bill, dict]:
    """Ask one vision model to read the bill. Returns the Bill plus latency and token counts."""
    base_url, key_env = PROVIDERS[MODELS[model]]
    client = OpenAI(base_url=base_url, api_key=os.environ[key_env], timeout=60, max_retries=0)  # Temporal owns retries
    started = time.perf_counter()
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(keys=", ".join(Bill.model_fields))},
            {"type": "image_url", "image_url": {"url": image_data_url(image)}}]}])
    stats = {"latency_s": round(time.perf_counter() - started, 2),
             "input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens}
    return Bill.model_validate_json(resp.choices[0].message.content), stats
