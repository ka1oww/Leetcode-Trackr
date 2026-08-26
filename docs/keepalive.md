# Keep-alive: surviving GitHub's 60-day scheduled-workflow disable

## The problem

GitHub automatically disables any scheduled workflow in a repository once 60
days pass with no repository activity. The daily sync (`.github/workflows/sync.yml`)
runs on a `schedule` trigger, so it is subject to this rule. If the owner goes
two months without pushing anything, the sync silently stops running and no
one is notified — the job just never fires again.

## Why the keep-alive job commits instead of only calling the enable API

The original plan (and GitHub's own docs) suggested calling
`POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` from a
monthly job to keep the daily workflow alive. That call does undo an existing
disable, but there is no documentation stating that calling it *resets the
60-day inactivity clock itself* — and the clock is what actually causes the
disable in the first place. GitHub's docs
(https://docs.github.com/actions/managing-workflow-runs/disabling-and-enabling-a-workflow)
describe the 60-day disable but do not say what does or doesn't count as
"repository activity", and do not mention the enable API as a way to reset it.

Prior art backs this up: [`efrecon/gh-action-keepalive`](https://github.com/efrecon/gh-action-keepalive)
explicitly tried an API-only approach first ("toggling twice the activity
state of all workflows") and found it did **not** hold against GitHub's
enforcement, so it switched to generating an actual commit on the default
branch before the 60-day deadline instead. That is the same pattern this repo
uses.

So the keep-alive workflow's primary defense is a real commit — pushing a
one-line timestamp marker (`.github/keepalive/last-run.txt`) to the default
branch every month, well inside the 60-day window. That is unambiguous
repository activity and is the mechanism actually known to reset the clock.

Calling the enable API is kept as a *second*, redundant safety net in the
same job — it can't hurt, and it recovers from the unrelated case where
someone disabled the workflow by hand (a maintainer clicking "Disable
workflow" in the Actions tab) rather than GitHub's automatic 60-day rule.

## Failure behavior

Both steps run under `set -euo pipefail` (the push) and rely on `gh api`'s
non-zero exit on a non-2xx response (the enable call). If either fails, the
job fails, and GitHub's default workflow-failure notification emails the
repo owner — the same "honest failure" behavior as the daily sync (see the
"Failure behavior" section of the README).

## Schedule

`.github/workflows/keepalive.yml` runs monthly (`17 4 1 * *`, the 1st of each
month), leaving over 30 days of margin against the 60-day deadline even if a
run is skipped or delayed.
