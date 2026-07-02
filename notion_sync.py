"""Minimal Notion REST client (no SDK dependency).

Uses the stable 2022-06-28 database API. New multi-select tag options are
created automatically when a page references them, so no schema mutation needed.
Property names come from schema.py so they cannot drift from setup.py.
"""
import requests

import schema

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"


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
