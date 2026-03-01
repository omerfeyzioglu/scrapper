"""
llm.py — LLM calls for spec generation and repair (gpt-4o-mini via OpenAI SDK).
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
load_dotenv() 

from openai import OpenAI

log = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You are a web-scraping configuration expert. "
    "Given a HTML snippet and a list of links from a page, output ONLY a JSON object "
    "that matches the exact schema provided. No prose, no markdown fences, only JSON."
)

_SCHEMA_REMINDER = """\
Required JSON schema (all keys mandatory, no extras):
{
  "domain": "<string>",
  "content_selectors": ["<css>", ...],
  "drop_selectors": ["<css>", ...],
  "fields": {
    "title_selector": "<css>",
    "date_selector": "<css or empty string>",
    "table_selector": "<css>"
  }
}"""


def _default_spec(domain: str) -> dict:
    return {
        "domain": domain,
        "content_selectors": [
            "article",
            "main",
            "[role='main']",
            "#content",
            ".content",
            ".post",
            ".entry",
        ],
        "drop_selectors": [
            "nav",
            "footer",
            "header",
            "aside",
            ".ads",
            ".advert",
            ".sponsored",
            ".cookie",
            ".newsletter",
            ".related",
            ".share",
            ".social",
            ".contact",
        ],
        "fields": {
            "title_selector": "h1::text",
            "date_selector": "",
            "table_selector": "table",
        },
    }


def _parse_llm_json(text: str, domain: str) -> dict:
    """Parse LLM text as JSON; fall back to default spec on any error."""
    try:
        raw = text.strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            )
        spec = json.loads(raw)
        # Minimal sanity check
        if not isinstance(spec.get("content_selectors"), list):
            raise ValueError("content_selectors missing or not a list")
        if not isinstance(spec.get("drop_selectors"), list):
            raise ValueError("drop_selectors missing or not a list")
        spec.setdefault("domain", domain)
        return spec
    except Exception as exc:
        log.warning("LLM JSON parse failed (%s); using default spec. raw=%r", exc, text[:200])
        return _default_spec(domain)


def _call(messages: list[dict]) -> str:
    """Call the OpenAI API; return empty string on any API error so callers fall back to default spec."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        log.warning("OPENAI_API_KEY not set — skipping LLM call, using default spec")
        return ""
    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            max_tokens=800,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        log.warning("LLM API call failed (%s) — falling back to default spec", exc)
        return ""


def generate_spec(
    domain: str,
    prefix: str,
    url: str,
    html_snippet: str,
    href_sample: list[str],
) -> dict:
    """Ask the LLM to produce a fresh extraction spec for this (domain, prefix)."""
    user_msg = (
        f"Domain: {domain}\n"
        f"Page type (URL path prefix): {prefix!r}\n"
        f"Sample URL: {url}\n\n"
        f"HTML snippet (~40 KB):\n{html_snippet}\n\n"
        f"Diverse same-domain hrefs (up to 300):\n"
        + "\n".join(href_sample[:300])
        + f"\n\n{_SCHEMA_REMINDER}"
    )
    log.info("Generating spec for %s [prefix=%r] via LLM", domain, prefix)
    text = _call([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    return _parse_llm_json(text, domain)


def repair_spec(
    domain: str,
    prefix: str,
    current_spec: dict,
    failure_reason: str,
    url: str,
    html_snippet: str,
    href_sample: list[str],
) -> dict:
    """Ask the LLM to repair a broken spec for (domain, prefix)."""
    user_msg = (
        f"Domain: {domain}\n"
        f"Page type (URL path prefix): {prefix!r}\n"
        f"Sample URL: {url}\n\n"
        f"Current spec that produced bad extraction:\n"
        f"{json.dumps(current_spec, indent=2)}\n\n"
        f"Failure reason: {failure_reason}\n\n"
        f"HTML snippet:\n{html_snippet}\n\n"
        f"Diverse same-domain hrefs:\n"
        + "\n".join(href_sample[:300])
        + f"\n\nFix the spec. {_SCHEMA_REMINDER}"
    )
    log.info(
        "Repairing spec for %s [prefix=%r] via LLM (reason: %s)",
        domain, prefix, failure_reason,
    )
    text = _call([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    return _parse_llm_json(text, domain)
