"""Local LLM client (LM Studio) - turns scraped price + news data into a
short, plain-language summary. No cloud AI call, no API key: everything
runs on your own machine through LM Studio's local OpenAI-compatible
server (its "Developer" tab -> Start Server; default
http://localhost:1234).
"""

import json
import os

import requests

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "local-model"
DEFAULT_TIMEOUT_SECONDS = 120

# Local models don't get any structured-output enforcement, so the exact
# JSON shape has to be spelled out in the prompt itself, and the response
# is parsed/validated by hand below rather than trusted as-is.
SYSTEM_PROMPT = """\
You are a plain-language financial summarizer for a personal stock research \
tool. You're given a ticker's latest price data and a handful of real news \
headlines about the company. Write a short, neutral summary - 2 to 4 \
sentences - of what's going on, grounded ONLY in the data and headlines \
given to you below. Do not invent facts, price targets, or recommendations, \
and do not use any outside knowledge about the company. If the headlines \
don't clearly explain the price move, say so rather than guessing.

Respond with ONE JSON object only - no prose before or after it, no \
markdown code fences, no explanation. It must have exactly this key:

{"summary": "<2-4 sentence plain-language summary>"}
"""


class LlmError(Exception):
    pass


def _extract_json_object(text: str) -> dict:
    """Local models routinely wrap JSON in markdown fences, or add a
    stray sentence before/after it despite being told not to - try a
    direct parse first, then fall back to slicing out the outermost
    {...} span before giving up."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        return json.loads(text[start : end + 1])


def _format_price_line(price: dict) -> str:
    if price.get("close") is None:
        return "(no price data available)"
    line = f"Latest close: ${price['close']:.2f} as of {price.get('as_of')}"
    if price.get("change_pct") is not None:
        line += f" ({price['change_pct']:+.1f}% vs the previous close)"
    return line


def summarize(ticker: str, price: dict, news: list[dict]) -> str:
    """Returns a short plain-language summary string. Raises LlmError if
    LM Studio isn't reachable or returns something unusable - callers
    should degrade gracefully (show the raw price/news without a
    summary), never let this one step crash the whole lookup."""
    base_url = os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL)
    timeout = float(os.environ.get("LMSTUDIO_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    json_mode = os.environ.get("LMSTUDIO_JSON_MODE", "1") != "0"

    headlines = "\n".join(f"- {n['title']}" for n in news if n.get("title")) or "(no recent headlines found)"
    user_content = f"Ticker: {ticker}\n\n{_format_price_line(price)}\n\nRecent headlines:\n{headlines}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("model response had no usable 'summary' field")
        return summary.strip()
    except Exception as exc:  # noqa: BLE001 - connection error, bad JSON, missing field, ...
        raise LlmError(f"Local LLM summary failed for {ticker}: {exc}") from exc
