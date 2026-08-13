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
    @mock.patch("main._load_dotenv")
    def test_sync_retries_before_returning_when_there_are_no_new_submissions(
        self, load_dotenv, retry, recent_accepted
    ):
        main.main()

        retry.assert_called_once_with("notion-token", "database-id")
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


if __name__ == "__main__":
    unittest.main()
