"""Single source of truth for the Notion database schema.

Both setup.py (which CREATES the property types via POST /v1/databases) and
notion_sync.create_page (which WRITES property values) reference the property
names here, so the two can never drift.
"""

DB_TITLE = "LeetCode Log"

# Property names (the dedupe key is NUMBER).
TITLE = "Problem"
NUMBER = "Number"
DIFFICULTY = "Difficulty"
TAGS = "Tags"
DATE_SOLVED = "Date Solved"
URL = "URL"
STATUS = "Status"
CONFIDENCE = "Confidence"
NEXT_REVIEW = "Next Review"
REVIEWS = "Reviews"

# Create-time type configs (classic Notion-Version 2022-06-28 shape: these go
# straight under "properties" in POST /v1/databases). Exactly one title.
# Status is a SELECT, not Notion's native "status" type, which the API cannot
# create. Tags options are left empty; Notion creates them on first write.
PROPERTY_SCHEMA = {
    TITLE: {"title": {}},
    NUMBER: {"number": {"format": "number"}},
    DIFFICULTY: {"select": {"options": [
        {"name": "Easy", "color": "green"},
        {"name": "Medium", "color": "yellow"},
        {"name": "Hard", "color": "red"},
    ]}},
    TAGS: {"multi_select": {"options": []}},
    DATE_SOLVED: {"date": {}},
    URL: {"url": {}},
    STATUS: {"select": {"options": [
        {"name": "New", "color": "default"},
        {"name": "Learning", "color": "blue"},
        {"name": "Mastered", "color": "green"},
    ]}},
    CONFIDENCE: {"number": {"format": "number"}},
    NEXT_REVIEW: {"date": {}},
    REVIEWS: {"number": {"format": "number"}},
}
