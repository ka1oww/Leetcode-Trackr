import unittest
from unittest import mock

import notion_sync
import schema


def response(data, status_code=200):
    resp = mock.Mock(status_code=status_code, text="error")
    resp.json.return_value = data
    return resp


def heading(text):
    return {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"plain_text": text}]},
    }


def paragraph(text):
    return {
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": text}]},
    }


class NotionRetryTests(unittest.TestCase):
    @mock.patch("notion_sync.requests.get")
    @mock.patch("notion_sync.requests.post")
    def test_recent_query_is_bounded_and_returns_only_missing_approaches(self, post, get):
        missing_page = {
            "id": "missing-page",
            "properties": {
                schema.TITLE: {"title": [{"plain_text": "1. Two Sum"}]},
                schema.DIFFICULTY: {"select": {"name": "Easy"}},
                schema.TAGS: {"multi_select": [{"name": "Array"}]},
            },
        }
        complete_page = {
            "id": "complete-page",
            "properties": {
                schema.TITLE: {"title": [{"plain_text": "2. Add Two Numbers"}]},
                schema.DIFFICULTY: {"select": {"name": "Medium"}},
                schema.TAGS: {"multi_select": []},
            },
        }
        post.return_value = response({"results": [missing_page, complete_page]})
        get.side_effect = [
            response({
                "results": [
                    heading("Submitted code"),
                    {"type": "code", "code": {"rich_text": [{"plain_text": "print(1)"}]}},
                    heading("My notes"),
                ],
                "has_more": False,
            }),
            response({
                "results": [heading("Approach"), paragraph("Already summarised")],
                "has_more": False,
            }),
        ]

        missing = notion_sync.recent_missing_summaries("token", "database", limit=999)

        self.assertEqual(post.call_args.kwargs["json"]["page_size"], 20)
        self.assertEqual(post.call_args.kwargs["json"]["sorts"][0]["direction"], "descending")
        self.assertEqual(missing, [{
            "page_id": "missing-page",
            "entry": {
                "title": "1. Two Sum",
                "difficulty": "Easy",
                "tags": ["Array"],
            },
            "code": "print(1)",
        }])

    @mock.patch("notion_sync.requests.get")
    def test_page_scan_stops_once_an_approach_is_found(self, get):
        get.return_value = response({
            "results": [heading("Approach"), paragraph("Already summarised")],
            "has_more": True,
            "next_cursor": "cursor-2",
        })

        has_approach, code = notion_sync._page_content("token", "page-1")

        self.assertTrue(has_approach)
        self.assertEqual(code, "")
        self.assertEqual(get.call_count, 1)

    @mock.patch("notion_sync.requests.get")
    def test_page_scan_paginates_while_the_approach_is_still_missing(self, get):
        get.side_effect = [
            response({
                "results": [
                    heading("Submitted code"),
                    {"type": "code", "code": {"rich_text": [{"plain_text": "print(1)"}]}},
                ],
                "has_more": True,
                "next_cursor": "cursor-2",
            }),
            response({"results": [heading("My notes")], "has_more": False}),
        ]

        self.assertEqual(notion_sync._page_content("token", "page-1"), (False, "print(1)"))
        self.assertEqual(get.call_count, 2)

    @mock.patch("notion_sync.requests.patch")
    def test_append_approach_writes_recovered_summary(self, patch):
        patch.return_value = response({})

        notion_sync.append_approach("token", "page-1", "Recovered summary")

        body = patch.call_args.kwargs["json"]
        self.assertEqual(body["children"][0]["heading_2"]["rich_text"][0]["text"]["content"], "Approach")
        self.assertEqual(body["children"][1]["paragraph"]["rich_text"][0]["text"]["content"], "Recovered summary")


class LoggedNumbersTests(unittest.TestCase):
    """logged_numbers is the dedupe key main() relies on before syncing on, so
    both its pagination and its Notion-API-error contract are covered here
    with stubbed HTTP responses (no real network, no secrets)."""

    @mock.patch("notion_sync.requests.post")
    def test_paginates_and_collects_every_number(self, post):
        post.side_effect = [
            response({
                "results": [
                    {"properties": {schema.NUMBER: {"number": 1}}},
                    {"properties": {schema.NUMBER: {"number": 2}}},
                ],
                "has_more": True,
                "next_cursor": "cursor-2",
            }),
            response({
                "results": [{"properties": {schema.NUMBER: {"number": 3}}}],
                "has_more": False,
            }),
        ]

        self.assertEqual(notion_sync.logged_numbers("token", "db-1"), {1, 2, 3})
        self.assertEqual(post.call_count, 2)

    @mock.patch("notion_sync.requests.post")
    def test_raises_on_notion_api_error(self, post):
        post.return_value = response({}, status_code=401)

        with self.assertRaises(RuntimeError):
            notion_sync.logged_numbers("token", "db-1")


class CreatePageTests(unittest.TestCase):
    """create_page is the write side of the sync; verify both the payload it
    sends and that a Notion API error surfaces as a RuntimeError main() can
    record instead of swallowing."""

    @mock.patch("notion_sync.requests.post")
    def test_sends_the_entry_as_notion_properties(self, post):
        post.return_value = response({"id": "new-page"})
        entry = {
            "title": "1. Two Sum", "number": 1, "tags": ["Array", "Hash Table"],
            "date": "2026-08-26", "url": "https://leetcode.com/problems/two-sum/",
            "difficulty": "Easy", "next_review": "2026-08-27",
        }

        result = notion_sync.create_page("token", "db-1", entry)

        self.assertEqual(result, {"id": "new-page"})
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["parent"], {"database_id": "db-1"})
        props = body["properties"]
        self.assertEqual(props[schema.NUMBER]["number"], 1)
        self.assertEqual(props[schema.NEXT_REVIEW]["date"]["start"], "2026-08-27")
        self.assertEqual(props[schema.DIFFICULTY]["select"]["name"], "Easy")

    @mock.patch("notion_sync.requests.post")
    def test_raises_on_notion_api_error(self, post):
        post.return_value = response({}, status_code=400)
        entry = {
            "title": "1. Two Sum", "number": 1, "tags": [], "date": "2026-08-26",
            "url": "https://leetcode.com/problems/two-sum/", "next_review": "2026-08-27",
        }

        with self.assertRaises(RuntimeError):
            notion_sync.create_page("token", "db-1", entry)


if __name__ == "__main__":
    unittest.main()
