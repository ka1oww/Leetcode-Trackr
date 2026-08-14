"""Minimal Notion REST client (no SDK dependency).

Uses the stable 2022-06-28 database API. New multi-select tag options are
created automatically when a page references them; the one deliberate schema
mutation is ensure_confidence_property(), which upgrades databases created
before Confidence became a select. Property names come from schema.py so they
cannot drift from setup.py.
"""
import datetime

import requests

import schema
import srs

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
        # Confidence stays empty until the user rates a review; see reschedule_due.
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


def _clear_legacy_numeric_confidence(token, database_id):
    """Blank out Confidence values whose option name is purely numeric.

    Older versions seeded every page with the number 1, so a converted database
    can arrive carrying ratings the user never gave. Those are artefacts, not
    reviews: clear them (and only them) so they never trigger a reschedule. If
    Notion drops the values during conversion this finds nothing and is a no-op.
    """
    url = f"{API}/databases/{database_id}/query"
    payload = {
        "page_size": 100,
        "filter": {"property": schema.CONFIDENCE, "select": {"is_not_empty": True}},
    }
    pages = []
    while True:
        resp = requests.post(url, headers=headers(token), json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion query failed: {resp.status_code} {resp.text}")
        data = resp.json()
        pages.extend(data.get("results", []))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break

    cleared = 0
    for page in pages:
        props = page.get("properties", {})
        label = ((props.get(schema.CONFIDENCE) or {}).get("select") or {}).get("name")
        if not label or not label.isdecimal():
            continue
        resp = requests.patch(
            f"{API}/pages/{page['id']}", headers=headers(token),
            json={"properties": {schema.CONFIDENCE: {"select": None}}}, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion clear failed: {resp.status_code} {resp.text}")
        cleared += 1
    return cleared


def ensure_confidence_property(token, database_id):
    """Make sure Confidence exists as a select on the database.

    Databases created by older versions of setup.py have it as a number (or not
    at all); patching the schema converts it in place. Any numeric values left
    over from that number property are cleared in the same pass. Returns True if
    the database was changed, False if it already matched.
    """
    url = f"{API}/databases/{database_id}"
    resp = requests.get(url, headers=headers(token), timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion get database failed: {resp.status_code} {resp.text}")
    prop = resp.json().get("properties", {}).get(schema.CONFIDENCE)
    if prop and prop.get("type") == "select":
        return False
    body = {"properties": {schema.CONFIDENCE: schema.PROPERTY_SCHEMA[schema.CONFIDENCE]}}
    resp = requests.patch(url, headers=headers(token), json=body, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion update database failed: {resp.status_code} {resp.text}")
    _clear_legacy_numeric_confidence(token, database_id)
    return True


def reschedule_due(token, database_id, today=None):
    """Reschedule every entry whose review is due and rated.

    Matches pages where Next Review has passed AND the user has set Confidence.
    Each match gets a new Next Review from srs.next_review(); the same page
    update clears Confidence and bumps the Reviews counter, so a rating
    reschedules exactly once and re-running the sync is a no-op. Numeric labels
    left over from the old number property are cleared without rescheduling;
    other unrecognised labels are left for the user.
    """
    today = today or datetime.date.today()
    url = f"{API}/databases/{database_id}/query"
    payload = {
        "page_size": 100,
        "filter": {"and": [
            {"property": schema.NEXT_REVIEW, "date": {"on_or_before": today.isoformat()}},
            {"property": schema.CONFIDENCE, "select": {"is_not_empty": True}},
        ]},
    }
    due = []
    while True:
        resp = requests.post(url, headers=headers(token), json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion query failed: {resp.status_code} {resp.text}")
        data = resp.json()
        due.extend(data.get("results", []))
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break

    rescheduled = 0
    for page in due:
        props = page.get("properties", {})
        label = ((props.get(schema.CONFIDENCE) or {}).get("select") or {}).get("name")
        if not label:
            continue  # nothing rated; leave it in the queue
        confidence = srs.CONFIDENCE_OPTIONS.get(label)
        if confidence is None:
            if label.isdecimal():
                # Artefact of the old number property, not a rating: blank it
                # without touching the schedule, in case the conversion-pass
                # sweep was interrupted before it finished.
                resp = requests.patch(
                    f"{API}/pages/{page['id']}", headers=headers(token),
                    json={"properties": {schema.CONFIDENCE: {"select": None}}}, timeout=30)
                if resp.status_code >= 400:
                    raise RuntimeError(f"Notion clear failed: {resp.status_code} {resp.text}")
            else:
                num = (props.get(schema.NUMBER) or {}).get("number")
                print(f"  (unrecognised Confidence '{label}' on problem {num}; not rescheduling it)")
            continue
        reviews = (props.get(schema.REVIEWS) or {}).get("number") or 0
        update = {
            schema.NEXT_REVIEW: {"date": {"start": srs.next_review(confidence, today)}},
            schema.CONFIDENCE: {"select": None},
            schema.REVIEWS: {"number": reviews + 1},
        }
        resp = requests.patch(f"{API}/pages/{page['id']}", headers=headers(token),
                              json={"properties": update}, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion reschedule failed: {resp.status_code} {resp.text}")
        rescheduled += 1
    return rescheduled
