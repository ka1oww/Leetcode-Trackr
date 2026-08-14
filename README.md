# leetcode-notion-revision

A daily job that logs my solved LeetCode problems into Notion and schedules each one for spaced-repetition review.

Technical interviews are heavily DSA-based, so revising DSA well matters, and re-solving every problem from scratch is too slow. This logs each solved problem into a Notion tracker with a record of how I approached it: my first intuition when I saw the problem, why that intuition was wrong, the correct method, and the optimisations I made. It then schedules each problem for spaced-repetition review, so the ones I am about to forget come back first.

It runs itself on **GitHub Actions**, needs only a LeetCode username to start, and can optionally use **Claude or an OpenAI model** to draft the approach summary for each solution with your own API key.

<!-- Add a screenshot of your Notion database here:  ![demo](docs/demo.png) -->

## What it does

- **Runs daily, unattended.** A GitHub Actions cron pulls the latest accepted submissions. No server to host.
- **Schedules revision.** Each problem gets a `Next Review` date (Leitner intervals). Filter a Notion view to "due today" and that view is the day's revision queue.
- **Reschedules from your rating.** After you revise a due problem, set its `Confidence` on the row (Again, Hard, Good or Easy). The next sync pushes `Next Review` out by the matching Leitner interval and clears the rating, so each rating reschedules exactly once.
- **Summarises the approach (optional).** Bring your own Anthropic or OpenAI API key and Claude or an OpenAI model writes two or three sentences on the method and complexity for each problem. Anthropic is preferred when both keys are set. Without a key no summary is written automatically: the entry is still created and you write the approach yourself in the `My notes` section.
- **Zero-config capture.** Works from a public LeetCode username. Add a session cookie to also pull the submitted code, runtime, and memory.
- **No heavy dependencies.** Plain `requests`; the Notion, LeetCode and AI provider calls are all raw HTTP.

## How it works

```
GitHub Actions (cron, daily)
      |
      |-- leetcode.py     pull recent accepted submissions + problem metadata (GraphQL)
      |-- enrich.py       optional: Claude or OpenAI summarises the approach
      |-- srs.py          compute first and follow-up review dates (Leitner)
      `-- notion_sync.py  write into the Notion database (dedupe by problem number)
```

## Quickstart (local)

1. Create a Notion integration and connect it to a page (two short steps in
   [`docs/notion-template.md`](docs/notion-template.md)).
2. Get the code: clone this repo (or "Use this template" / fork first, then clone).
3. Set up and sync:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python setup.py     # creates the "LeetCode Log" database, writes .env
   python main.py      # pulls your recent solves into Notion
   ```
   `setup.py` asks for your integration token (hidden), lets you pick or paste the
   page, and asks your LeetCode username. It also offers hidden, skippable prompts
   for the LeetCode session cookie and your own Anthropic and OpenAI API keys. The
   cookie unlocks submitted code, runtime and memory. Either API key enables drafted
   approach summaries. `main.py` reads `.env` automatically, so to sync again later
   just run `python main.py`.

That is the whole tool. Open the database (the link `setup.py` prints) and add a view
filtered to **Next Review on or before today** as your daily revision queue.

When you have revised a problem from that queue, set its **Confidence** on the row:
Again, Hard, Good or Easy. The next sync (the daily run, or `python main.py`)
reschedules `Next Review` with the matching Leitner interval and clears the rating,
ready for the next pass. Databases created before `Confidence` existed gain the
property automatically on their first sync.

## Run it daily on autopilot (optional)

To sync every day with no machine of yours running, use GitHub Actions:

1. Push your copy to GitHub.
2. Add three required repository secrets: `NOTION_TOKEN`, `NOTION_DATABASE_ID`,
   `LEETCODE_USERNAME` (`setup.py` prints the `gh secret set` commands, or add them
   under Settings, then Secrets and variables, then Actions). The wizard also offers
   to set `LEETCODE_SESSION`, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` when provided.
3. Enable Actions on your repo, then run the **LeetCode to Notion sync** workflow once.
   It runs daily at 01:00 UTC after that.

Optional extras, as secrets or lines in `.env`: `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` (Claude or OpenAI approach summaries) and `LEETCODE_SESSION`
(pulls your submitted code, runtime and memory). Bring your own provider key.

## Configuration

All configuration is through environment variables. See [`.env.example`](.env.example).

| Variable             | Required | Purpose                                          |
| -------------------- | :------: | ------------------------------------------------ |
| `NOTION_TOKEN`       |   yes    | Notion internal integration secret               |
| `NOTION_DATABASE_ID` |   yes    | Target database                                  |
| `LEETCODE_USERNAME`  |   yes    | Whose accepted submissions to pull               |
| `ANTHROPIC_API_KEY`  |    no    | Enables Claude approach summaries                |
| `ANTHROPIC_MODEL`    |    no    | Defaults to `claude-haiku-4-5`                   |
| `OPENAI_API_KEY`     |    no    | Enables OpenAI approach summaries                |
| `OPENAI_MODEL`       |    no    | Defaults to `gpt-5.4-nano`                       |
| `LEETCODE_SESSION`   |    no    | Cookie to also fetch your code, runtime, memory  |
| `SYNC_LIMIT`         |    no    | Recent submissions to scan, 1 to 20 (default 20) |

## Notes

- Dedupe is by problem **number**, so re-solving a problem never creates a duplicate.
- The `LEETCODE_SESSION` cookie expires periodically. Re-paste it when code stops syncing; everything else keeps working from the public username.
- Failed or previously skipped summaries are retried across the 20 most recently solved entries when a provider key is available.
- `SYNC_LIMIT` is capped at 20 because LeetCode returns only the 20 most recent accepted submissions. The daily run keeps you current from there; it does not backfill older history.

## Licence

[MIT](LICENSE)
