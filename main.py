"""Sync recent solved LeetCode problems into a Notion revision database.

Run locally (`python main.py`) or on a schedule via GitHub Actions. Reads
configuration from environment variables, loading a local .env file if present
(see .env.example).
"""
import datetime
import os
import sys

import enrich
import leetcode
import notion_sync
import schema
import srs


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"Missing required env var: {name}")
    return val


def _load_dotenv():
    """Load a local .env (written by setup.py) so `python main.py` works with no
    sourcing. Real environment variables (e.g. GitHub Actions secrets) take
    precedence, and the file is optional."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_limit():
    """SYNC_LIMIT, validated. LeetCode returns at most 20 recent submissions,
    so anything above that is clamped; empty or non-numeric falls back to 20."""
    raw = (os.environ.get("SYNC_LIMIT") or "").strip()
    if not raw:
        return 20
    try:
        n = int(raw)
    except ValueError:
        print(f"SYNC_LIMIT='{raw}' is not a number; using 20.")
        return 20
    capped = max(1, min(leetcode.MAX_RECENT, n))
    if capped != n:
        print(f"SYNC_LIMIT={n} out of range; LeetCode returns at most "
              f"{leetcode.MAX_RECENT} recent submissions. Using {capped}.")
    return capped


def main():
    """Run one sync. Every LeetCode API error, Notion API error or partial-sync
    failure is collected in `failures`; if any occurred the process exits
    non-zero so GitHub's workflow-failure notification reaches the owner."""
    _load_dotenv()
    notion_token = env("NOTION_TOKEN", required=True)
    database_id = env("NOTION_DATABASE_ID", required=True)
    username = env("LEETCODE_USERNAME", required=True)
    session = env("LEETCODE_SESSION")  # optional: unlocks submitted code
    limit = _parse_limit()

    failures = []
    _reschedule_reviews(notion_token, database_id, failures)
    _retry_missing_summaries(notion_token, database_id, failures)

    added = _log_new_problems(
        notion_token, database_id, username, session, limit, failures
    )

    if failures:
        print("\nThe sync finished with failures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. Logged {len(added)} new problem(s)." if added
          else "\nUp to date. Nothing new to log.")


def _log_new_problems(notion_token, database_id, username, session, limit,
                      failures):
    """Pull and log new solved problems, recording every failure instead of
    swallowing it. Returns the titles that were logged."""
    try:
        recent = leetcode.recent_accepted(username, limit)
    except Exception as exc:
        failures.append(
            f"LeetCode API: could not list recent accepted submissions for "
            f"'{username}': {exc}")
        return []

    if not recent:
        print("No recent accepted submissions found.")
        return []

    try:
        logged = notion_sync.logged_numbers(notion_token, database_id)
    except Exception as exc:
        # Without the logged set we cannot dedupe, so syncing on would risk
        # duplicate rows; bail out honestly instead.
        failures.append(f"Notion API: could not read logged problems: {exc}")
        return []

    added = []
    for sub in reversed(recent):  # oldest first, so dates read naturally
        slug = sub["titleSlug"]
        try:
            detail = leetcode.question_detail(slug)
            number = detail["number"]
        except Exception as exc:
            failures.append(
                f"LeetCode API: could not fetch details for {slug}: {exc}")
            continue
        if number is None or number in logged:
            continue

        solved = datetime.datetime.fromtimestamp(
            int(sub["timestamp"]), datetime.timezone.utc
        ).date().isoformat()

        entry = {
            "title": f"{number}. {sub['title']}",
            "number": number,
            "difficulty": detail["difficulty"],
            "tags": detail["tags"],
            "date": solved,
            "url": f"https://leetcode.com/problems/{slug}/",
            "status": "New",
            "next_review": srs.first_review(),
        }

        code = ""
        if session:
            try:
                code = leetcode.submission_detail(sub["id"], session)["code"]
            except Exception as exc:
                # Still log the entry without its code, but say so loudly.
                failures.append(
                    f"LeetCode API: could not fetch submitted code for {slug} "
                    f"(LEETCODE_SESSION may be missing or expired): {exc}")

        try:
            summary = enrich.summarize(entry, code)
            notion_sync.create_page(
                notion_token, database_id, entry, _content_blocks(summary, code)
            )
        except Exception as exc:
            failures.append(f"Notion API: failed to log {entry['title']}: {exc}")
            continue
        logged.add(number)
        added.append(entry["title"])
        print(f"Logged: {entry['title']}")

    return added


def _reschedule_reviews(notion_token, database_id, failures):
    """Close the review loop before logging anything new: entries that are due
    and rated get their next date. A failure here is recorded so the run exits
    non-zero, but new problems are still synced."""
    try:
        if notion_sync.ensure_confidence_property(notion_token, database_id):
            print(f"Upgraded the database: '{schema.CONFIDENCE}' is now a select.")
        n = notion_sync.reschedule_due(notion_token, database_id)
        if n:
            print(f"Rescheduled {n} reviewed problem(s).")
    except Exception as exc:
        failures.append(f"Notion API: review reschedule failed: {exc}")


def _retry_missing_summaries(notion_token, database_id, failures=None):
    """Retry summary enrichment for only the most recent Notion entries."""
    if not enrich.is_enabled():
        return 0
    failures = [] if failures is None else failures
    try:
        pending = notion_sync.recent_missing_summaries(notion_token, database_id)
    except Exception as exc:
        failures.append(f"Notion API: could not check summaries to retry: {exc}")
        return 0

    filled = 0
    for item in pending:
        summary = enrich.summarize(item["entry"], item.get("code", ""))
        if not summary:
            continue
        try:
            notion_sync.append_approach(
                notion_token, item["page_id"], summary
            )
        except Exception as exc:
            failures.append(
                f"Notion API: could not back-fill {item['entry']['title']}: {exc}")
            continue
        filled += 1
        print(f"Back-filled approach: {item['entry']['title']}")
    return filled


def _chunks(s, n=1900):
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


def _heading(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _paragraph(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]}}


def _code_block(code):
    # Notion caps a block's rich_text array at 100 elements (each <= 2000 chars).
    chunks = _chunks(code)[:100]
    return {"object": "block", "type": "code",
            "code": {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks],
                     "language": "python"}}


def _content_blocks(summary, code):
    blocks = []
    if summary:
        blocks += [_heading("Approach"), _paragraph(summary)]
    if code:
        blocks += [_heading("Submitted code"), _code_block(code)]
    blocks += [_heading("My notes"),
               _paragraph("First intuition when you saw it, why it was wrong, the correct "
                          "approach, and the optimisations you made.")]
    return blocks


if __name__ == "__main__":
    main()
