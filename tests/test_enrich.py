import os
import unittest
from unittest import mock

import requests

import enrich


ENTRY = {
    "title": "1. Two Sum",
    "difficulty": "Easy",
    "tags": ["Array", "Hash Table"],
}


def response(data):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def error_response(status_code, message):
    resp = mock.Mock(status_code=status_code, text=message)
    resp.json.return_value = {"error": {"message": message}}
    resp.raise_for_status.side_effect = requests.HTTPError(message)
    return resp


class EnrichTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "anthropic-key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_anthropic_key_uses_raw_messages_api(self, post):
        post.return_value = response({
            "content": [{"type": "text", "text": "Use a hash map. O(n) time."}],
        })

        summary = enrich.summarize(ENTRY, "def two_sum(): pass")

        self.assertEqual(summary, "Use a hash map. O(n) time.")
        self.assertEqual(post.call_args.args[0], enrich.ANTHROPIC_API)
        self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "anthropic-key")
        self.assertIn("accepted solution", post.call_args.kwargs["json"]["messages"][0]["content"])

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_key_uses_raw_responses_api(self, post):
        post.return_value = response({
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "Use two pointers. O(n) time."}],
            }],
        })

        summary = enrich.summarize(ENTRY)

        self.assertEqual(summary, "Use two pointers. O(n) time.")
        self.assertEqual(post.call_args.args[0], enrich.OPENAI_API)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], "Bearer openai-key"
        )
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-5.4-nano")

    @mock.patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "anthropic-key", "OPENAI_API_KEY": "openai-key"},
        clear=True,
    )
    @mock.patch("enrich.requests.post")
    def test_anthropic_is_preferred_when_both_keys_are_set(self, post):
        post.return_value = response({
            "content": [{"type": "text", "text": "Anthropic summary"}],
        })

        self.assertEqual(enrich.summarize(ENTRY), "Anthropic summary")
        self.assertEqual(post.call_args.args[0], enrich.ANTHROPIC_API)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_no_key_skips_without_an_http_call(self, post):
        self.assertEqual(enrich.summarize(ENTRY), "")
        post.assert_not_called()

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "bad-key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_anthropic_http_failure_is_graceful(self, post):
        post.side_effect = requests.RequestException("service unavailable")

        with mock.patch("builtins.print") as output:
            self.assertEqual(enrich.summarize(ENTRY), "")

        output.assert_called_once()
        self.assertIn("enrichment skipped", output.call_args.args[0])

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_empty_response_is_graceful(self, post):
        post.return_value = response({"output": []})

        with mock.patch("builtins.print") as output:
            self.assertEqual(enrich.summarize(ENTRY), "")

        self.assertIn("OpenAI returned no summary text", output.call_args.args[0])

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_budgets_for_reasoning_tokens(self, post):
        post.return_value = response({
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "Summary."}],
            }],
        })

        enrich.summarize(ENTRY)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertGreaterEqual(body["max_output_tokens"], 1200)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_retries_once_without_reasoning_when_it_is_rejected(self, post):
        post.side_effect = [
            error_response(400, "Unsupported parameter: 'reasoning' for this model."),
            response({
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Plain summary."}],
                }],
            }),
        ]

        self.assertEqual(enrich.summarize(ENTRY), "Plain summary.")
        self.assertEqual(post.call_count, 2)
        first, second = post.call_args_list
        self.assertIn("reasoning", first.kwargs["json"])
        self.assertNotIn("reasoning", second.kwargs["json"])
        self.assertEqual(second.kwargs["json"]["model"], "gpt-5.4-nano")

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_retry_failure_still_degrades_gracefully(self, post):
        post.side_effect = [
            error_response(400, "Unsupported parameter: 'reasoning' for this model."),
            error_response(400, "Unknown model."),
        ]

        with mock.patch("builtins.print") as output:
            self.assertEqual(enrich.summarize(ENTRY), "")

        self.assertEqual(post.call_count, 2)
        self.assertIn("enrichment skipped", output.call_args.args[0])

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_400_unrelated_to_reasoning_is_not_retried(self, post):
        post.return_value = error_response(400, "Invalid API key provided.")

        with mock.patch("builtins.print"):
            self.assertEqual(enrich.summarize(ENTRY), "")

        self.assertEqual(post.call_count, 1)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True)
    @mock.patch("enrich.requests.post")
    def test_openai_incomplete_response_reports_the_status(self, post):
        post.return_value = response({
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning", "summary": []}],
        })

        with mock.patch("builtins.print") as output:
            self.assertEqual(enrich.summarize(ENTRY), "")

        message = output.call_args.args[0]
        self.assertIn("status=incomplete", message)
        self.assertIn("max_output_tokens", message)


if __name__ == "__main__":
    unittest.main()
