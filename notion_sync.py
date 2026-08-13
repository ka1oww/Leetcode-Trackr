"""Minimal Notion REST client (no SDK dependency).

Uses the stable 2022-06-28 database API. New multi-select tag options are
created automatically when a page references them, so no schema mutation needed.
Property names come from schema.py so they cannot drift from setup.py.
"""
import requests

import schema

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
ENRICH_RETRY_LIMIT = 20


def headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }


def logged_numbers(token, database_id):
    """Return the set of problem numbers already in the database (dedupe key)."""
    nums = set()
    url = f"{API}/databases/{database_id}/query"
    payload = {"page_size": 100}
    while True:
        resp = requests.post(url, headers=headers(token), json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion query failed: {resp.status_code} {resp.text}")
        data = resp.json()
        for page in data.get("results", []):
            val = page.get("properties", {}).get(schema.NUMBER, {}).get("number")
            if val is not None:
                nums.add(int(val))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return nums


def _rich_text(parts):
    return "".join(
        part.get("plain_text") or part.get("text", {}).get("content", "")
        for part in (parts or [])
    )


def _entry_from_page(page):
    props = page.get("properties", {})
    difficulty = props.get(schema.DIFFICULTY, {}).get("select") or {}
    return {
        "title": _rich_text(props.get(schema.TITLE, {}).get("title")) or "Untitled problem",
        "difficulty": difficulty.get("name", ""),
        "tags": [
            tag.get("name", "")
            for tag in props.get(schema.TAGS, {}).get("multi_select", [])
            if tag.get("name")
        ],
    }


def _page_content(token, page_id):
    """Return whether Approach has text, and any stored submitted code.

    The scan stops at the first non-empty Approach block, so the returned code
    is empty for pages that already have a summary and need no enrichment.
    """
    url = f"{API}/blocks/{page_id}/children"
    params = {"page_size": 100}
    in_approach = False
    in_code = False
    code_chunks = []
    while True:
        resp = requests.get(url, headers=headers(token), params=params, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion block query failed: {resp.status_code} {resp.text}")
        data = resp.json()
        for block in data.get("results", []):
            block_type = block.get("type", "")
            body = block.get(block_type, {})
            text = _rich_text(body.get("rich_text"))
            if block_type == "heading_2":
                in_approach = text.strip().lower() == "approach"
                in_code = text.strip().lower() == "submitted code"
                continue
            if in_approach and text.strip():
                return True, ""
            if in_code and block_type == "code":
                code_chunks.append(text)
        if not data.get("has_more"):
            break
        params["start_cursor"] = data["next_cursor"]
    return False, "".join(code_chunks)


def recent_missing_summaries(token, database_id, limit=ENRICH_RETRY_LIMIT):
    """Inspect a bounded recent window and return pages missing an Approach."""
    limit = max(1, min(ENRICH_RETRY_LIMIT, int(limit)))
    payload = {
        "page_size": limit,
        "sorts": [{"property": schema.DATE_SOLVED, "direction": "descending"}],
    }
    resp = requests.post(
        f"{API}/databases/{database_id}/query",
        headers=headers(token),
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion retry query failed: {resp.status_code} {resp.text}")

    missing = []
    for page in resp.json().get("results", [])[:limit]:
        has_approach, code = _page_content(token, page["id"])
        if not has_approach:
            missing.append({
                "page_id": page["id"],
                "entry": _entry_from_page(page),
                "code": code,
            })
    return missing


def append_approach(token, page_id, summary):
    """Append a recovered Approach section to an existing page."""
    # Back-filled entries get Approach at the end of the page, not at the top as create_page does.
    children = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Approach"}}]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary[:1900]}}]}},
    ]
    resp = requests.patch(
        f"{API}/blocks/{page_id}/children",
        headers=headers(token),
        json={"children": children},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion append summary failed: {resp.status_code} {resp.text}")


def create_page(token, database_id, entry, content_blocks=None):
    props = {
        schema.TITLE: {"title": [{"text": {"content": entry["title"]}}]},
        schema.NUMBER: {"number": entry["number"]},
        schema.TAGS: {"multi_select": [{"name": t} for t in entry.get("tags", [])]},
        schema.DATE_SOLVED: {"date": {"start": entry["date"]}},
        schema.URL: {"url": entry["url"]},
        schema.STATUS: {"select": {"name": entry.get("status", "New")}},
        schema.CONFIDENCE: {"number": entry.get("confidence", 1)},
        schema.NEXT_REVIEW: {"date": {"start": entry["next_review"]}},
        schema.REVIEWS: {"number": 0},
    }
    if entry.get("difficulty"):
        props[schema.DIFFICULTY] = {"select": {"name": entry["difficulty"]}}

    body = {"parent": {"database_id": database_id}, "properties": props}
    if content_blocks:
        body["children"] = content_blocks

    resp = requests.post(f"{API}/pages", headers=headers(token), json=body, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion create_page failed: {resp.status_code} {resp.text}")
    return resp.json()
