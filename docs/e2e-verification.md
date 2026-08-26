# End-to-end verification (throwaway test database)

Ran the real job against a throwaway Notion test database, using a scoped
integration token provided out-of-band for this purpose only. The token was
never committed, printed, or logged anywhere in this repo, its history, or
this document -- every command below redacts it before being recorded.

**Database:** created fresh under the page the test integration ("LT TEST")
was shared with, via `setup.py`'s own `find_existing_db` / `create_database`
functions (the same code path `python setup.py` runs interactively) -- so
this is the real setup flow, not a bypass.

**Profile used:** `lee215`, a public LeetCode profile with plenty of solved
problems (the repo owner's own LeetCode username could not be determined
from the repo or its config, so the brief's fallback applies -- any public
profile with solved problems).

## 1. Discover the test database

```
$ python3 -c "import setup; print(len(setup.search_pages(TOKEN)))"
pages visible: 1
 - 3c8aeec8-4b7c-8084-9d92-ffc5564e0532 '(untitled)'
```

One page was visible to the integration -- the page it had been shared with.
No child "LeetCode Log" database existed yet under it, so one was created via
`setup.create_database`, exactly as `python setup.py` would on a first run.

## 2. Run the real job

```
$ NOTION_TOKEN=***REDACTED*** NOTION_DATABASE_ID=<test-db-id> \
  LEETCODE_USERNAME=lee215 SYNC_LIMIT=20 python main.py

Logged: 3993. Maximum Value of an Alternating Sequence
Logged: 3994. Minimum Adjacent Swaps to Partition Array
... (20 lines total)
Logged: 4032. Longest Subarray With at Most K Distinct Prime Factors

Done. Logged 20 new problem(s).
$ echo $?
0
```

## 3. Verify rows landed with correct review dates

Queried the test database directly:

```
$ python3 -c "... POST /v1/databases/<id>/query ..."
row count: 20
  #4032 'Longest Subarray...' | Date Solved=2026-08-23 | Next Review=2026-08-27
  #4026 'Maximum Gap Between Stations' | Date Solved=2026-08-16 | Next Review=2026-08-27
  #4022 'K-th Digit in Infinite String' | Date Solved=2026-08-15 | Next Review=2026-08-27
  ... (20 rows total)
```

20 rows, one per logged problem. Every row's `Next Review` is today
(2026-08-26) + 1 day, matching the first Leitner interval in `srs.py` for a
newly logged, un-rated entry.

## 4. Dedupe / idempotency

Ran `main.py` again with the same environment, no code changes:

```
Up to date. Nothing new to log.
$ echo $?
0
```

Zero new rows created on the second run -- `logged_numbers` correctly
deduped against the 20 already-logged problem numbers.

## 5. Mock-based CI coverage (no secrets)

Separate from this live run, `tests/test_main.py` (`HonestFailureTests`),
`tests/test_notion_sync.py`, and `tests/test_leetcode.py` cover the sync
logic and every new error path (LeetCode transport/GraphQL errors, Notion
API errors, partial-sync failures) with stubbed HTTP responses -- no network
calls, no secrets, runs green in `.github/workflows/tests.yml` on every push.
