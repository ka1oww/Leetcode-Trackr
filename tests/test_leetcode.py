import unittest
from unittest import mock

import requests

import leetcode


def response(data, status_code=200):
    resp = mock.Mock(status_code=status_code)
    resp.json.return_value = data
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class RecentAcceptedTests(unittest.TestCase):
    """Public GraphQL call main() uses to list new solves. Both the happy path
    and its two failure shapes (transport error, GraphQL error) are covered
    with stubbed HTTP -- no real network, no secrets."""

    @mock.patch.object(leetcode._SESSION, "post")
    def test_returns_the_submission_list(self, post):
        post.return_value = response({
            "data": {"recentAcSubmissionList": [
                {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1"},
            ]}
        })

        result = leetcode.recent_accepted("alice", 20)

        self.assertEqual(result, [
            {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1"}
        ])

    @mock.patch.object(leetcode._SESSION, "post")
    def test_raises_on_transport_error(self, post):
        post.return_value = response({}, status_code=503)

        with self.assertRaises(requests.HTTPError):
            leetcode.recent_accepted("alice", 20)

    @mock.patch.object(leetcode._SESSION, "post")
    def test_raises_on_graphql_error(self, post):
        post.return_value = response({"errors": [{"message": "user not found"}]})

        with self.assertRaises(RuntimeError):
            leetcode.recent_accepted("alice", 20)


class QuestionDetailTests(unittest.TestCase):
    @mock.patch.object(leetcode._SESSION, "post")
    def test_returns_number_difficulty_and_tags(self, post):
        post.return_value = response({
            "data": {"question": {
                "questionFrontendId": "1", "difficulty": "Easy",
                "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
            }}
        })

        detail = leetcode.question_detail("two-sum")

        self.assertEqual(detail, {
            "number": 1, "difficulty": "Easy", "tags": ["Array", "Hash Table"]
        })

    @mock.patch.object(leetcode._SESSION, "post")
    def test_raises_on_transport_error(self, post):
        post.return_value = response({}, status_code=500)

        with self.assertRaises(requests.HTTPError):
            leetcode.question_detail("two-sum")


if __name__ == "__main__":
    unittest.main()
