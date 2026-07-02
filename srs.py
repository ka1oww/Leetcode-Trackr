"""Spaced-repetition scheduling (simple Leitner intervals).

New problems get a first review tomorrow. A review flow (e.g. a Notion button
or a second scheduled job) can call next_review() with your recalled confidence
to push the date out.
"""
import datetime

# confidence (1 = hard, 5 = easy) -> days until next review
INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 15}


def first_review(today=None):
    today = today or datetime.date.today()
    return (today + datetime.timedelta(days=1)).isoformat()


def next_review(confidence, today=None):
    today = today or datetime.date.today()
    days = INTERVALS.get(int(confidence), 1)
    return (today + datetime.timedelta(days=days)).isoformat()
