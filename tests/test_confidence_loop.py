"""Tests for the Confidence review loop. All Notion HTTP is mocked; nothing
here talks to a live API."""
import datetime
import unittest
from unittest import mock

import notion_sync
import schema
import setup as setup_script
import srs

TODAY = datetime.date(2026, 8, 1)

# Pinned expectations for TODAY, so a regression in the option-to-interval
# mapping fails loudly instead of being re-derived from the code under test.
EXPECTED_DATE = {
    "Again": "2026-08-02",  # 1 day
    "Hard": "2026-08-03",   # 2 days
    "Good": "2026-08-08",   # 7 days
    "Easy": "2026-08-16",   # 15 days
}


def fake_response(body=None, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    resp.text = ""
    return resp


def due_page(pid="page-1", label=None, reviews=0, number=1):
    return {
        "id": pid,
        "properties": {
            schema.CONFIDENCE: {"select": {"name": label} if label else None},
            schema.REVIEWS: {"number": reviews},
            schema.NUMBER: {"number": number},
        },
    }


class TestSchemaSetup(unittest.TestCase):
    def test_create_database_posts_confidence_select(self):
        with mock.patch("setup.requests.post") as post:
            post.return_value = fake_response({"id": "db-1"})
            db_id = setup_script.create_database("token", "parent-page")
        self.assertEqual(db_id, "db-1")
        conf = post.call_args.kwargs["json"]["properties"][schema.CONFIDENCE]
        names = [o["name"] for o in conf["select"]["options"]]
        self.assertEqual(names, list(srs.CONFIDENCE_OPTIONS))

    def test_option_scores_are_leitner_rungs(self):
        for label, score in srs.CONFIDENCE_OPTIONS.items():
            self.assertIn(score, srs.INTERVALS, label)


class TestEnsureConfidenceProperty(unittest.TestCase):
    def _ensure(self, properties, status=200, leftover=()):
        with mock.patch("notion_sync.requests.get") as get, \
                mock.patch("notion_sync.requests.post") as post, \
                mock.patch("notion_sync.requests.patch") as patch_:
            get.return_value = fake_response({"properties": properties}, status=status)
            post.return_value = fake_response(
                {"results": list(leftover), "has_more": False})
            patch_.return_value = fake_response({})
            changed = notion_sync.ensure_confidence_property("token", "db-1")
        return changed, post, patch_

    def test_converts_number_property_to_select(self):
        changed, _, patch_ = self._ensure({schema.CONFIDENCE: {"type": "number"}})
        self.assertTrue(changed)
        body = patch_.call_args.kwargs["json"]
        self.assertEqual(body["properties"][schema.CONFIDENCE],
                         schema.PROPERTY_SCHEMA[schema.CONFIDENCE])

    def test_adds_property_when_missing(self):
        changed, _, patch_ = self._ensure({})
        self.assertTrue(changed)
        patch_.assert_called_once()

    def test_noop_when_already_select(self):
        changed, post, patch_ = self._ensure({schema.CONFIDENCE: {"type": "select"}})
        self.assertFalse(changed)
        patch_.assert_not_called()
        post.assert_not_called()

    def test_conversion_clears_leftover_numeric_ratings(self):
        # Old versions seeded Confidence = 1 on every page, so a converted
        # database can carry ratings the user never gave. Clear those, and only
        # those, without touching the schedule.
        changed, post, patch_ = self._ensure(
            {schema.CONFIDENCE: {"type": "number"}},
            leftover=[due_page("page-1", label="1"), due_page("page-2", label="Good")])
        self.assertTrue(changed)
        self.assertEqual(post.call_args.kwargs["json"]["filter"],
                         {"property": schema.CONFIDENCE, "select": {"is_not_empty": True}})
        page_patches = [c for c in patch_.call_args_list if "/pages/" in c.args[0]]
        self.assertEqual(len(page_patches), 1)
        self.assertIn("page-1", page_patches[0].args[0])
        props = page_patches[0].kwargs["json"]["properties"]
        self.assertEqual(props, {schema.CONFIDENCE: {"select": None}})
        self.assertNotIn(schema.NEXT_REVIEW, props)
        self.assertNotIn(schema.REVIEWS, props)

    def test_raises_on_http_error(self):
        with self.assertRaises(RuntimeError):
            self._ensure({}, status=500)


class TestRescheduleDue(unittest.TestCase):
    def _reschedule(self, query_results):
        with mock.patch("notion_sync.requests.post") as post, \
                mock.patch("notion_sync.requests.patch") as patch_:
            post.return_value = fake_response(
                {"results": query_results, "has_more": False})
            patch_.return_value = fake_response({})
            n = notion_sync.reschedule_due("token", "db-1", today=TODAY)
        return n, post, patch_

    def test_each_confidence_value_gets_its_interval(self):
        for label, expected in EXPECTED_DATE.items():
            with self.subTest(label=label):
                n, _, patch_ = self._reschedule([due_page(label=label, reviews=2)])
                self.assertEqual(n, 1)
                self.assertIn("page-1", patch_.call_args.args[0])
                props = patch_.call_args.kwargs["json"]["properties"]
                self.assertEqual(props[schema.NEXT_REVIEW]["date"]["start"], expected)
                self.assertIsNone(props[schema.CONFIDENCE]["select"])
                self.assertEqual(props[schema.REVIEWS]["number"], 3)

    def test_reschedule_and_clear_are_one_update(self):
        # Idempotency hinges on the date change and the marker clear landing in
        # the same PATCH: there is no window where one applied without the other.
        n, _, patch_ = self._reschedule([due_page(label="Good")])
        self.assertEqual(n, 1)
        self.assertEqual(patch_.call_count, 1)
        props = patch_.call_args.kwargs["json"]["properties"]
        self.assertIn(schema.NEXT_REVIEW, props)
        self.assertIsNone(props[schema.CONFIDENCE]["select"])

    def test_query_asks_only_for_due_and_rated(self):
        _, post, _ = self._reschedule([])
        conds = post.call_args.kwargs["json"]["filter"]["and"]
        self.assertIn({"property": schema.NEXT_REVIEW,
                       "date": {"on_or_before": "2026-08-01"}}, conds)
        self.assertIn({"property": schema.CONFIDENCE,
                       "select": {"is_not_empty": True}}, conds)

    def test_second_sync_is_noop(self):
        # After a reschedule the rating is cleared, so the filtered query comes
        # back empty and nothing is patched.
        n, _, patch_ = self._reschedule([])
        self.assertEqual(n, 0)
        patch_.assert_not_called()

    def test_entry_without_confidence_is_untouched(self):
        n, _, patch_ = self._reschedule([due_page(label=None)])
        self.assertEqual(n, 0)
        patch_.assert_not_called()

    def test_unrecognised_label_is_left_for_the_user(self):
        with mock.patch("builtins.print") as told:
            n, _, patch_ = self._reschedule([due_page(label="Meh")])
        self.assertEqual(n, 0)
        patch_.assert_not_called()
        told.assert_called_once()

    def test_legacy_numeric_label_is_cleared_not_rescheduled(self):
        # A numeric option is an artefact of the old number property, not a
        # rating: it must never move a review date, but it is blanked here so
        # the loop self-heals even if the conversion sweep was interrupted.
        n, _, patch_ = self._reschedule([due_page(label="3")])
        self.assertEqual(n, 0)
        self.assertEqual(patch_.call_count, 1)
        self.assertIn("page-1", patch_.call_args.args[0])
        self.assertEqual(patch_.call_args.kwargs["json"]["properties"],
                         {schema.CONFIDENCE: {"select": None}})

    def test_paginates_and_reschedules_every_page(self):
        responses = [
            fake_response({"results": [due_page("page-1", label="Good")],
                           "has_more": True, "next_cursor": "c2"}),
            fake_response({"results": [due_page("page-2", label="Easy")],
                           "has_more": False}),
        ]
        with mock.patch("notion_sync.requests.post", side_effect=responses) as post, \
                mock.patch("notion_sync.requests.patch",
                           return_value=fake_response({})) as patch_:
            n = notion_sync.reschedule_due("token", "db-1", today=TODAY)
        self.assertEqual(n, 2)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[1].kwargs["json"]["start_cursor"], "c2")
        self.assertEqual(patch_.call_count, 2)


class TestCreatePage(unittest.TestCase):
    def test_new_page_leaves_confidence_empty(self):
        entry = {"title": "1. Two Sum", "number": 1, "tags": ["Array"],
                 "date": "2026-08-01", "url": "https://leetcode.com/problems/two-sum/",
                 "next_review": "2026-08-02"}
        with mock.patch("notion_sync.requests.post") as post:
            post.return_value = fake_response({"id": "p"})
            notion_sync.create_page("token", "db-1", entry)
        props = post.call_args.kwargs["json"]["properties"]
        self.assertNotIn(schema.CONFIDENCE, props)
        self.assertEqual(props[schema.REVIEWS]["number"], 0)


if __name__ == "__main__":
    unittest.main()
