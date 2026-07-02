"""Optional LLM enrichment via Claude.

No-op unless ANTHROPIC_API_KEY is set and the `anthropic` package is installed,
so the tool works out of the box without an API key.
"""
import os


def summarize(entry, code=""):
    """Return a short approach / key-idea summary, or "" if disabled."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ""
    try:
        import anthropic
    except ImportError:
        return ""

    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    client = anthropic.Anthropic(api_key=api_key)
    tags = ", ".join(entry.get("tags", [])) or "unknown"

    if code:
        prompt = (
            f"LeetCode problem: {entry['title']} "
            f"(difficulty: {entry['difficulty']}; topics: {tags}).\n"
            f"My accepted solution:\n```\n{code[:6000]}\n```\n"
            "In 2-3 sentences, summarize the core approach and the time/space "
            "complexity. Plain text, no preamble."
        )
    else:
        prompt = (
            f"LeetCode problem: {entry['title']} "
            f"(difficulty: {entry['difficulty']}; topics: {tags}).\n"
            "In 2-3 sentences, describe the canonical approach/pattern for this "
            "problem and a one-line 'what to remember' for revision. "
            "Plain text, no preamble."
        )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return next((b.text for b in resp.content if b.type == "text"), "").strip()
    except Exception as e:  # never let enrichment break the sync
        print(f"  (enrichment skipped: {e})")
        return ""
