# AGENTS.md

Project-level notes for agents working in this repo. For what the code does,
read `README.md` and the module docstrings in `main.py`, `leetcode.py`,
`notion_sync.py`, `srs.py`, `schema.py` first — this file only covers what
isn't obvious from reading them.

## Failure model

`main.py`'s `main()` collects every LeetCode/Notion API error and
partial-sync failure into a `failures` list as it runs, and exits non-zero at
the end if that list is non-empty — even though it still syncs everything it
can along the way. This is deliberate: GitHub's default workflow-failure
email is the alerting mechanism, so a swallowed exception here is a silent
outage for the repo owner. When touching `main.py`, keep that contract: never
add a bare `except: pass`/`print(...)`-and-continue around a LeetCode or
Notion call without also appending to `failures`. The one deliberate
exception is the optional code fetch behind `LEETCODE_SESSION`: that cookie
expires routinely and the entry still lands without its code, so the failure
is printed but deliberately kept out of `failures`.

`tests/test_main.py`'s `HonestFailureTests` exercises this by patching
`main.<name>` targets directly with `unittest.mock.patch`. A patch target
must match how `main.py` actually calls the dependency (e.g.
`"notion_sync.create_page"`, not `"create_page"`, since `main.py` calls
`notion_sync.create_page(...)` and never imports the name into its own
namespace) — a mismatched target silently makes the real network call
instead of raising `AttributeError` from a nonexistent mock in some cases, so
a red test there can mean "wrong patch target", not "logic bug". Run
`pytest` locally before trusting a green result on these tests.

## Keep-alive workflow

`.github/workflows/keepalive.yml` exists because GitHub auto-disables any
scheduled workflow (`.github/workflows/sync.yml` included) after 60 days
with no repository activity. It pushes a small commit to the default branch
every month — that is the documented-to-work mechanism for resetting the
inactivity clock, not the enable API — and also re-enables the daily
workflow via the API as a secondary safety net. Full rationale and sources:
[`docs/keepalive.md`](docs/keepalive.md).

## Maintaining this file

Keep this file proportionate: add an entry only for project knowledge that
isn't obvious from reading the code, and that most future sessions in this
repo would benefit from. Prefer a pointer to the authoritative file/doc over
duplicating detail. Remove or update entries that go stale.
