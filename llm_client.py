"""Local LLM client (LM Studio) - turns scraped price + news data into a
short, plain-language summary. No cloud AI call, no API key: everything
runs on your own machine through LM Studio's local OpenAI-compatible
server (its "Developer" tab -> Start Server; default
http://localhost:1234).
"""

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

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

FILING_SYSTEM_PROMPT = """\
You are a plain-language financial summarizer for a personal stock research \
tool. You're given extracted sections of a company's SEC filing (10-K annual \
report or 10-Q quarterly report) - its Management's Discussion and Analysis, \
and where available, its Risk Factors. Write a short, neutral summary - 4 to \
8 sentences - covering how the business performed and why, per management's \
own discussion, and the most significant risks the company itself flagged, if \
risk factors were given. Ground your summary ONLY in the text given to you \
below. Do not invent facts, figures, or forward-looking claims beyond what's \
stated, and do not use any outside knowledge about the company. If a section \
is missing, summarize from what was given and don't mention the absence.

Respond with ONE JSON object only - no prose before or after it, no \
markdown code fences, no explanation. It must have exactly this key:

{"summary": "<4-8 sentence plain-language summary>"}
"""

# A full MD&A + Risk Factors pair can still be large enough to blow past a
# local model's context window even after section extraction - this is a
# blunt safety cap, not a smart summarization step, so truncation (when it
# happens) is from the end of each section and clearly marked, not silently
# dropped.
MAX_SECTION_CHARS = int(os.environ.get("LMSTUDIO_MAX_SECTION_CHARS", "16000"))


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


def _chat_completion(system_prompt: str, user_content: str) -> dict:
    """POSTs one chat completion to LM Studio and returns the parsed JSON
    object from the model's response content. Raises on any failure
    (connection, bad JSON, missing field) - callers wrap this in their
    own LlmError with context-specific messaging."""
    base_url = os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL)
    timeout = float(os.environ.get("LMSTUDIO_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    json_mode = os.environ.get("LMSTUDIO_JSON_MODE", "1") != "0"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # requests' default message is just "400 Bad Request for url: ..." -
        # LM Studio/llama.cpp server errors (wrong context length, bad
        # request shape, etc.) explain the real cause in the response body,
        # which is worth surfacing rather than guessing at.
        raise requests.HTTPError(f"{exc} - response body: {response.text[:2000]}", response=response) from exc
    content = response.json()["choices"][0]["message"]["content"]
    return _extract_json_object(content)


def summarize(ticker: str, price: dict, news: list[dict]) -> str:
    """Returns a short plain-language summary string. Raises LlmError if
    LM Studio isn't reachable or returns something unusable - callers
    should degrade gracefully (show the raw price/news without a
    summary), never let this one step crash the whole lookup."""
    headlines = "\n".join(f"- {n['title']}" for n in news if n.get("title")) or "(no recent headlines found)"
    user_content = f"Ticker: {ticker}\n\n{_format_price_line(price)}\n\nRecent headlines:\n{headlines}"

    try:
        parsed = _chat_completion(SYSTEM_PROMPT, user_content)
        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("model response had no usable 'summary' field")
        return summary.strip()
    except Exception as exc:  # noqa: BLE001 - connection error, bad JSON, missing field, ...
        raise LlmError(f"Local LLM summary failed for {ticker}: {exc}") from exc


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated for length]"


# Floor for the adaptive-shrink retry below - under this, there's not
# enough text left for a meaningful summary, so it's better to fail
# clearly than keep retrying forever.
_MIN_SECTION_CHARS = 1000


def _is_context_length_error(exc: Exception) -> bool:
    # LM Studio/llama.cpp server errors say this almost verbatim
    # ("...is greater than the context length...") - a plain substring
    # check is more robust than trying to parse a specific JSON shape
    # that could differ across server versions/backends.
    return "context length" in str(exc).lower()


def summarize_filing(ticker: str, form: str, sections: dict[str, str]) -> str:
    """sections is e.g. {"Management's Discussion and Analysis": "...",
    "Risk Factors": "..."} - whichever filing_text.py could extract.
    Raises LlmError the same way summarize() does.

    MAX_SECTION_CHARS is a starting point, not a guarantee - models have
    wildly different context windows, and there's no reliable way to know
    the loaded model's limit in advance. If the server reports a context-
    length error, this halves the per-section budget and retries, down to
    _MIN_SECTION_CHARS, rather than failing on the first filing that
    happens to be larger than whatever fixed cap was guessed up front."""
    if not sections:
        raise LlmError(f"No extractable sections for {ticker} {form} - nothing to summarize")

    max_chars = MAX_SECTION_CHARS
    last_exc: Exception | None = None
    while True:
        body = "\n\n".join(f"=== {title} ===\n{_truncate(text, max_chars)}" for title, text in sections.items())
        user_content = f"Ticker: {ticker}\nForm: {form}\n\n{body}"
        try:
            parsed = _chat_completion(FILING_SYSTEM_PROMPT, user_content)
            summary = parsed.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("model response had no usable 'summary' field")
            return summary.strip()
        except Exception as exc:  # noqa: BLE001 - connection error, bad JSON, missing field, ...
            last_exc = exc
            if _is_context_length_error(exc) and max_chars > _MIN_SECTION_CHARS:
                max_chars = max(max_chars // 2, _MIN_SECTION_CHARS)
                logger.info("Context length exceeded for %s %s - retrying with max_chars=%d", ticker, form, max_chars)
                continue
            raise LlmError(f"Local LLM filing summary failed for {ticker} {form}: {exc}") from exc
