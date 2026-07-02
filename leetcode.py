"""LeetCode GraphQL client.

Username-only by default (public data: recent accepted submissions + problem
metadata). An optional LEETCODE_SESSION cookie unlocks your submitted code,
runtime, and memory.
"""
import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - urllib3 ships with requests
    Retry = None

GRAPHQL = "https://leetcode.com/graphql/"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (leetcode-notion-revision)",
    "Referer": "https://leetcode.com",
}

# recentAcSubmissionList is hard-capped server-side at 20 items.
MAX_RECENT = 20


def _new_session():
    """A session with retry/backoff on transient failures (429, 5xx, dropped
    connections), so a blip does not abort the daily run."""
    s = requests.Session()
    s.headers.update(HEADERS)
    if Retry is not None:
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


_SESSION = _new_session()


def _post(query, variables, session=None, headers=None):
    resp = (session or _SESSION).post(
        GRAPHQL,
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"LeetCode GraphQL error: {data['errors']}")
    return data["data"]


def recent_accepted(username, limit=20):
    """Public: the most recent accepted submissions for a user (max 20)."""
    q = """query recentAc($username: String!, $limit: Int!) {
      recentAcSubmissionList(username: $username, limit: $limit) {
        id title titleSlug timestamp
      }
    }"""
    data = _post(q, {"username": username, "limit": min(limit, MAX_RECENT)})
    return data.get("recentAcSubmissionList") or []


def question_detail(slug):
    """Public: difficulty + official topic tags for a problem."""
    q = """query q($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionFrontendId difficulty topicTags { name }
      }
    }"""
    qd = _post(q, {"titleSlug": slug}).get("question") or {}
    fid = qd.get("questionFrontendId")
    return {
        "number": int(fid) if fid else None,
        "difficulty": qd.get("difficulty") or "",
        "tags": [t["name"] for t in (qd.get("topicTags") or [])],
    }


def submission_detail(submission_id, leetcode_session):
    """Authed: requires a valid LEETCODE_SESSION cookie.

    Returns the submitted code, runtime, memory and language. Raises on failure
    (bad/expired cookie, missing csrftoken, null result) so the caller can fall
    back to metadata only and the user sees a clear reason.
    """
    s = _new_session()
    s.cookies.set("LEETCODE_SESSION", leetcode_session, domain=".leetcode.com")
    # Mint the csrftoken from the GraphQL endpoint. The homepage is
    # Cloudflare-gated and returns no csrftoken for non-browser clients.
    s.get(GRAPHQL, timeout=20)
    csrf = s.cookies.get("csrftoken", "")
    if not csrf:
        raise RuntimeError("could not obtain a csrftoken (LeetCode may be blocking the request)")

    q = """query sub($id: Int!) {
      submissionDetails(submissionId: $id) {
        code runtimeDisplay memoryDisplay lang { name }
      }
    }"""
    data = _post(
        q, {"id": int(submission_id)},
        session=s,
        headers={"x-csrftoken": csrf, "Referer": "https://leetcode.com"},
    )
    sd = data.get("submissionDetails")
    if not sd:
        raise RuntimeError("submissionDetails is null (LEETCODE_SESSION likely expired or invalid)")
    return {
        "code": sd.get("code") or "",
        "runtime": sd.get("runtimeDisplay") or "",
        "memory": sd.get("memoryDisplay") or "",
        "lang": (sd.get("lang") or {}).get("name") or "",
    }
