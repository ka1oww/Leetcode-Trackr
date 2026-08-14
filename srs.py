"""Spaced-repetition scheduling (simple Leitner intervals).

New problems get a first review tomorrow. When you revise a due problem, set
its Confidence in Notion; the next sync feeds that rating to next_review() to
push the date out (see notion_sync.reschedule_due).
"""
import datetime

# confidence (1 = hard, 5 = easy) -> days until next review
INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 15}

# Confidence select option -> the score fed to next_review(). Four ratings
# spread over the five rungs: Again repeats tomorrow, Easy jumps straight to
# the longest interval.
CONFIDENCE_OPTIONS = {"Again": 1, "Hard": 2, "Good": 4, "Easy": 5}


def first_review(today=None):
    today = today or datetime.date.today()
    return (today + datetime.timedelta(days=1)).isoformat()


def next_review(confidence, today=None):
    today = today or datetime.date.today()
    days = INTERVALS.get(int(confidence), 1)
    return (today + datetime.timedelta(days=days)).isoformat()
