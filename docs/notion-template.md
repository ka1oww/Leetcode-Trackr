# Notion setup

## Quick setup (recommended)

`setup.py` creates the database for you. You only link a page.

1. **Create an integration.** Go to <https://www.notion.so/my-integrations>, create
   a new internal integration, and copy the **Internal Integration Secret**. This is
   your `NOTION_TOKEN`.
2. **Connect it to a page.** Open the Notion page you want the tracker to live under,
   then **•••** menu, **Connections**, and add your integration. This step is the
   most common thing people miss: the integration can only create the database under
   a page it has been connected to.
3. **Run setup.**
   ```bash
   pip install -r requirements.txt
   export NOTION_TOKEN=...      # or let setup.py prompt for it
   python setup.py
   ```
   It lets you pick the page (or paste its URL), creates the **LeetCode Log**
   database with the correct schema, writes `.env`, and offers to push your three
   GitHub Actions secrets. Running it again reuses the existing database; it does not
   create a duplicate.

Tip: in the new database, add a board or calendar view filtered to
**Next Review is on or before today** to get a daily revision queue.

## Manual setup (fallback)

If you would rather build it by hand, make a full-page Notion database called
**LeetCode Log** with these properties (names must match exactly):

| Property      | Type         | Notes                                  |
| ------------- | ------------ | -------------------------------------- |
| `Problem`     | Title        | e.g. `1. Two Sum`                      |
| `Number`      | Number       | dedupe key                             |
| `Difficulty`  | Select       | Easy / Medium / Hard                   |
| `Tags`        | Multi-select | options auto-created on first use      |
| `Date Solved` | Date         |                                        |
| `URL`         | URL          |                                        |
| `Status`      | Select       | New / Learning / Mastered (a plain **Select**, not Notion's native "Status" type, which the API cannot create) |
| `Confidence`  | Number       | 1 (hard) to 5 (easy)                   |
| `Next Review` | Date         | spaced-repetition due date             |
| `Reviews`     | Number       | times reviewed                         |

Then create the integration and connect it to the database (steps 1 and 2 above), and
find the database ID in its URL:

```
https://www.notion.so/<workspace>/<DATABASE_ID>?v=<view_id>
```

The 32-character hex string is `NOTION_DATABASE_ID`.
