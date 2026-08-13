"""Optional approach-summary enrichment via Anthropic or OpenAI.

No-op unless ANTHROPIC_API_KEY or OPENAI_API_KEY is set. Anthropic is
preferred when both are configured. Both providers use their raw HTTP APIs so
requests remains the project's only runtime dependency.
"""
import os

import requests


ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
OPENAI_API = "https://api.openai.com/v1/responses"


def provider():
    """Return the configured provider name, preferring Anthropic."""
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "anthropic"
    if (os.environ.get("OPENAI_API_KEY") or "").strip():
        return "openai"
    return ""


def is_enabled():
    return bool(provider())


def _prompt(entry, code):
    tags = ", ".join(entry.get("tags", [])) or "unknown"
    if code:
        return (
            f"LeetCode problem: {entry['title']} "
            f"(difficulty: {entry['difficulty']}; topics: {tags}).\n"
            f"My accepted solution:\n```\n{code[:6000]}\n```\n"
            "In 2-3 sentences, summarise the core approach and the time/space "
            "complexity. Plain text, no preamble."
        )
    return (
        f"LeetCode problem: {entry['title']} "
        f"(difficulty: {entry['difficulty']}; topics: {tags}).\n"
        "In 2-3 sentences, describe the canonical approach/pattern for this "
        "problem and a one-line 'what to remember' for revision. "
        "Plain text, no preamble."
    )


def _anthropic_summary(prompt):
    resp = requests.post(
        ANTHROPIC_API,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    text = next(
        (block.get("text", "") for block in data.get("content", [])
         if block.get("type") == "text"),
        "",
    ).strip()
    if not text:
        raise RuntimeError("Anthropic returned no summary text")
    return text


def _openai_post(payload):
    return requests.post(
        OPENAI_API,
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY'].strip()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )


def _rejects_reasoning(resp):
    try:
        message = (resp.json().get("error") or {}).get("message") or ""
    except ValueError:
        message = resp.text or ""
    return "reasoning" in str(message).lower()


def _openai_summary(prompt):
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"),
        "input": prompt,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 2000,
    }
    resp = _openai_post(payload)
    if resp.status_code == 400 and _rejects_reasoning(resp):
        resp = _openai_post({k: v for k, v in payload.items() if k != "reasoning"})
    resp.raise_for_status()
    data = resp.json()
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for block in item.get("content", []):
            if block.get("type") == "output_text" and block.get("text"):
                return block["text"].strip()
    status = data.get("status") or "unknown"
    reason = ((data.get("incomplete_details") or {}).get("reason")
              or (data.get("error") or {}).get("message") or "")
    detail = f"status={status}" + (f", reason={reason}" if reason else "")
    raise RuntimeError(f"OpenAI returned no summary text ({detail})")


def summarize(entry, code=""):
    """Return a short approach / key-idea summary, or "" if disabled/failed."""
    selected = provider()
    if not selected:
        return ""

    prompt = _prompt(entry, code)
    try:
        if selected == "anthropic":
            return _anthropic_summary(prompt)
        return _openai_summary(prompt)
    except Exception as exc:  # never let enrichment break the sync
        print(f"  (enrichment skipped: {exc})")
        return ""
