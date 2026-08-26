import datetime
import os
import unittest
from unittest import mock

import main


class RetryEnrichmentTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {
        "NOTION_TOKEN": "notion-token",
        "NOTION_DATABASE_ID": "database-id",
        "LEETCODE_USERNAME": "alice",
        "OPENAI_API_KEY": "key",
    }, clear=True)
    @mock.patch("main.leetcode.recent_accepted", return_value=[])
    @mock.patch("main._retry_missing_summaries", return_value=1)
    @mock.patch("main._reschedule_reviews")
    @mock.patch("main._load_dotenv")
    def test_sync_retries_before_returning_when_there_are_no_new_submissions(
        self, load_dotenv, reschedule, retry, recent_accepted
    ):
        main.main()

        retry.assert_called_once_with("notion-token", "database-id", mock.ANY)
        recent_accepted.assert_called_once_with("alice", 20)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("main.notion_sync.append_approach")
    @mock.patch("main.enrich.summarize", return_value="Recovered summary")
    @mock.patch("main.notion_sync.recent_missing_summaries")
    def test_next_sync_fills_a_previously_skipped_entry(
        self, recent_missing, summarize, append_approach
    ):
        recent_missing.return_value = [{
            "page_id": "page-1",
            "entry": {
                "title": "1. Two Sum",
                "difficulty": "Easy",
                "tags": ["Array"],
            },
            "code": "def two_sum(): pass",
        }]

        filled = main._retry_missing_summaries("notion-token", "database-id")

        self.assertEqual(filled, 1)
        summarize.assert_called_once_with(
            recent_missing.return_value[0]["entry"], "def two_sum(): pass"
        )
        append_approach.assert_called_once_with(
            "notion-token", "page-1", "Recovered summary"
        )

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("main.notion_sync.recent_missing_summaries")
    def test_retry_query_is_skipped_without_a_provider_key(self, recent_missing):
        self.assertEqual(main._retry_missing_summaries("token", "database"), 0)
        recent_missing.assert_not_called()

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @mock.patch("main.notion_sync.append_approach")
    @mock.patch("main.enrich.summarize", return_value="")
    @mock.patch("main.notion_sync.recent_missing_summaries")
    def test_failed_retry_remains_pending(self, recent_missing, summarize, append_approach):
        recent_missing.return_value = [{
            "page_id": "page-1",
            "entry": {"title": "1. Two Sum", "difficulty": "Easy", "tags": []},
            "code": "",
        }]

        self.assertEqual(main._retry_missing_summaries("token", "database"), 0)
        append_approach.assert_not_called()


class HonestFailureTests(unittest.TestCase):
    """Every LeetCode API error, Notion API error and partial-sync failure must
    make main() exit non-zero so GitHub emails the owner. Nothing is swallowed."""

    SUB = {"id": 111, "title": "Two Sum", "titleSlug": "two-sum",
           "timestamp": "1756000000"}
    DETAIL = {"number": 1, "difficulty": "Easy", "tags": ["Array"]}
    ENV = {
        "NOTION_TOKEN": "notion-token",
        "NOTION_DATABASE_ID": "database-id",
        "LEETCODE_USERNAME": "alice",
    }

    def run_main(self, env=None, **patches):
        """Patch main.<target> with each kwarg, run main.main(), and return the
        exit code (None when it completed without SystemExit) plus the mocks,
        keyed by their attribute name on main."""
        entered, mocks = [], {}
        try:
            for target, spec in patches.items():
                m = mock.patch(f"main.{target}", **spec)
                mocks[target.split(".")[-1]] = m.__enter__()
                entered.append(m)
            with mock.patch.dict(os.environ, env or self.ENV, clear=True):
                try:
                    main.main()
                    return None, mocks
                except SystemExit as e:
                    return e.code, mocks
        finally:
            for m in reversed(entered):
                m.__exit__(None, None, None)

    def test_notion_reschedule_failure_exits_non_zero(self):
        # The review-reschedule stage failing is a Notion API error: loud run,
        # even though the rest of the sync still proceeds.
        code, _ = self.run_main(
            **{"notion_sync.ensure_confidence_property":
               {"side_effect": RuntimeError("401 unauthorized")},
               "leetcode.recent_accepted": {"return_value": []}})
        self.assertEqual(code, 1)

    def test_leetcode_listing_failure_exits_non_zero(self):
        code, _ = self.run_main(
            **{"leetcode.recent_accepted":
               {"side_effect": RuntimeError("503 Service Unavailable")},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertEqual(code, 1)

    def test_logged_numbers_failure_blocks_sync_and_exits_non_zero(self):
        # Without the dedupe set, syncing on would duplicate rows: bail out.
        code, mocks = self.run_main(
            **{"leetcode.recent_accepted": {"return_value": [self.SUB]},
               "notion_sync.logged_numbers":
                   {"side_effect": RuntimeError("500")},
               "notion_sync.create_page": {"return_value": {}},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertEqual(code, 1)
        mocks["create_page"].assert_not_called()

    def test_question_detail_failure_is_recorded_and_sync_continues(self):
        second = dict(self.SUB, id=222, title="Add Two Numbers",
                      titleSlug="add-two-numbers")
        code, mocks = self.run_main(
            **{"leetcode.recent_accepted":
                   {"return_value": [self.SUB, second]},
               "leetcode.question_detail":
                   {"side_effect": [RuntimeError("429"), self.DETAIL]},
               "notion_sync.logged_numbers": {"return_value": set()},
               "notion_sync.create_page": {"return_value": {}},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertEqual(code, 1)
        mocks["create_page"].assert_called_once()  # the healthy problem landed

    def test_partial_create_page_failure_exits_non_zero(self):
        # A row that fails to land is a failed run, not a silent skip.
        code, _ = self.run_main(
            **{"leetcode.recent_accepted": {"return_value": [self.SUB]},
               "notion_sync.logged_numbers": {"return_value": set()},
               "notion_sync.create_page": {"side_effect": RuntimeError("validation error")},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertEqual(code, 1)

    def test_code_fetch_failure_is_loud_but_entry_still_logs(self):
        code, mocks = self.run_main(
            env=dict(self.ENV, LEETCODE_SESSION="stale-cookie"),
            **{"leetcode.recent_accepted": {"return_value": [self.SUB]},
               "leetcode.question_detail": {"return_value": self.DETAIL},
               "leetcode.submission_detail":
                   {"side_effect": RuntimeError("submissionDetails is null")},
               "notion_sync.logged_numbers": {"return_value": set()},
               "notion_sync.create_page": {"return_value": {}},
               "enrich.summarize": {"return_value": ""},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertEqual(code, 1)
        mocks["create_page"].assert_called_once()

    def test_code_fetch_is_skipped_without_a_session(self):
        code, mocks = self.run_main(
            **{"leetcode.recent_accepted": {"return_value": [self.SUB]},
               "leetcode.question_detail": {"return_value": self.DETAIL},
               "leetcode.submission_detail": {"return_value": {"code": ""}},
               "notion_sync.logged_numbers": {"return_value": set()},
               "notion_sync.create_page": {"return_value": {}},
               "enrich.summarize": {"return_value": ""},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertIsNone(code)
        mocks["submission_detail"].assert_not_called()

    def test_retry_backfill_notion_failure_exits_non_zero(self):
        code, _ = self.run_main(
            env=dict(self.ENV, OPENAI_API_KEY="key"),
            **{"notion_sync.recent_missing_summaries":
               {"side_effect": RuntimeError("429 rate limited")},
               "leetcode.recent_accepted": {"return_value": []}})
        self.assertEqual(code, 1)

    def test_retry_backfill_append_failure_exits_non_zero(self):
        code, mocks = self.run_main(
            env=dict(self.ENV, OPENAI_API_KEY="key"),
            **{"notion_sync.recent_missing_summaries": {"return_value": [{
                "page_id": "page-1",
                "entry": {"title": "1. Two Sum", "difficulty": "Easy",
                          "tags": ["Array"]},
                "code": "",
            }]},
               "enrich.summarize": {"return_value": "Recovered"},
               "notion_sync.append_approach":
                   {"side_effect": RuntimeError("500")},
               "leetcode.recent_accepted": {"return_value": []}})
        self.assertEqual(code, 1)
        mocks["append_approach"].assert_called_once()

    def test_clean_run_exits_without_error(self):
        code, mocks = self.run_main(
            **{"leetcode.recent_accepted": {"return_value": [self.SUB]},
               "leetcode.question_detail": {"return_value": self.DETAIL},
               "notion_sync.logged_numbers": {"return_value": set()},
               "notion_sync.create_page": {"return_value": {}},
               "enrich.summarize": {"return_value": "Summary"},
               "_reschedule_reviews": {},
               "_retry_missing_summaries": {"return_value": 0}})
        self.assertIsNone(code)
        entry = mocks["create_page"].call_args.args[2]
        self.assertEqual(entry["number"], 1)
        self.assertEqual(entry["next_review"],
                         (datetime.date.today()
                          + datetime.timedelta(days=1)).isoformat())


if __name__ == "__main__":
    unittest.main()
