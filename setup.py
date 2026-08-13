"""One-time setup: create the LeetCode revision database in Notion.

You do two things in Notion first (see docs/notion-template.md):
  1. Create an internal integration and copy its secret.
  2. Connect that integration to the page you want the tracker under.

Then run `python setup.py`. It finds/links that page, creates the database with
the correct schema, writes .env, and offers to push your GitHub Actions secrets.
"""
import getpass
import os
import re
import shutil
import subprocess
import sys

import requests

import notion_sync
import schema
from main import _load_dotenv

API = notion_sync.API
SECRET_NAMES = (
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
    "LEETCODE_USERNAME",
    "LEETCODE_SESSION",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


# ---------------- Notion helpers ----------------

def _prompt_token():
    token = getpass.getpass("Paste your Notion internal integration secret (hidden): ").strip()
    if not token:
        sys.exit("No token provided. Create one at https://www.notion.so/my-integrations")
    return token


def _check_token(token):
    return requests.get(f"{API}/users/me", headers=notion_sync.headers(token), timeout=30)


def read_token():
    """Validate NOTION_TOKEN, prompting for a fresh one if the stored one is stale."""
    token = (os.environ.get("NOTION_TOKEN") or "").strip()
    from_env = bool(token)
    if not token:
        token = _prompt_token()

    resp = _check_token(token)
    if resp.status_code == 401 and from_env:
        print("The stored NOTION_TOKEN was rejected (401); it may have been rotated.")
        token = _prompt_token()
        resp = _check_token(token)

    if resp.status_code == 401:
        sys.exit("Notion rejected this token (401). Re-copy the Internal Integration Secret "
                 "from https://www.notion.so/my-integrations")
    if resp.status_code >= 400:
        sys.exit(f"Could not validate the token: {resp.status_code} {resp.text}")
    return token


def read_username():
    existing = (os.environ.get("LEETCODE_USERNAME") or "").strip()
    prompt = f"Your LeetCode username{f' [{existing}]' if existing else ''}: "
    return input(prompt).strip() or existing


def read_optional_secret(name, explanation):
    """Prompt for a secret without echoing it; Enter keeps/skips the value."""
    existing = (os.environ.get(name) or "").strip()
    print(f"\nOptional: {explanation}")
    action = "keep the existing value" if existing else "skip"
    value = getpass.getpass(
        f"Paste {name} (hidden, Enter to {action}): "
    ).strip()
    return value or existing


def parse_page_id(raw):
    """Pull a 32-char id out of a bare id, a dashed UUID, or a Notion URL.

    A Notion id is the trailing 32 hex chars of the path, so anchor to the end
    (this avoids grabbing the wrong run when a page slug ends in a hex letter).
    """
    cleaned = raw.strip().split("?")[0].rstrip("/").replace("-", "")
    candidate = cleaned[-32:]
    if re.fullmatch(r"[0-9a-fA-F]{32}", candidate):
        return candidate
    ids = re.findall(r"[0-9a-fA-F]{32}", cleaned)  # fallback: last run anywhere
    if ids:
        return ids[-1]
    raise ValueError(f"Could not find a 32-character page id in: {raw}")


def _plain_title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            text = "".join(p.get("plain_text") or p.get("text", {}).get("content", "") for p in parts)
            return text or "(untitled)"
    return "(untitled)"


def search_pages(token):
    pages, payload = [], {"filter": {"property": "object", "value": "page"}, "page_size": 100}
    while True:
        resp = requests.post(f"{API}/search", headers=notion_sync.headers(token), json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion search failed: {resp.status_code} {resp.text}")
        data = resp.json()
        for r in data.get("results", []):
            pages.append({"id": r["id"], "title": _plain_title(r)})
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return pages


def page_reachable(token, page_id):
    resp = requests.get(f"{API}/pages/{page_id}", headers=notion_sync.headers(token), timeout=30)
    return resp.status_code < 400


def existing_env_db(token):
    """If NOTION_DATABASE_ID is set and still resolves, reuse it (idempotency)."""
    db_id = (os.environ.get("NOTION_DATABASE_ID") or "").strip()
    if not db_id:
        return None
    resp = requests.get(f"{API}/databases/{db_id}", headers=notion_sync.headers(token), timeout=30)
    return db_id if resp.status_code < 400 else None


def find_existing_db(token, parent_id):
    """Reuse a child database titled DB_TITLE already under the page, if any."""
    url, params = f"{API}/blocks/{parent_id}/children", {"page_size": 100}
    while True:
        resp = requests.get(url, headers=notion_sync.headers(token), params=params, timeout=30)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        for b in data.get("results", []):
            if b.get("type") == "child_database" and b.get("child_database", {}).get("title") == schema.DB_TITLE:
                return b["id"]
        if data.get("has_more"):
            params["start_cursor"] = data["next_cursor"]
        else:
            break
    return None


def build_create_body(parent_id):
    return {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": schema.DB_TITLE}}],
        "properties": dict(schema.PROPERTY_SCHEMA),
    }


def create_database(token, parent_id):
    resp = requests.post(f"{API}/databases", headers=notion_sync.headers(token),
                         json=build_create_body(parent_id), timeout=30)
    if resp.status_code == 404:
        raise RuntimeError("Notion returned 404. The integration is probably not connected to that "
                           "page. Open the page, '...' menu, Connections, add your integration, then re-run.")
    if resp.status_code >= 400:
        raise RuntimeError(f"Create database failed: {resp.status_code} {resp.text}")
    return resp.json()["id"]


# ---------------- Local wiring ----------------

def write_env(updates, defaults=None, path=None):
    """Merge updates into .env, preserving existing key=value lines."""
    defaults = defaults or {}
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    env[k.strip()] = v.strip()
    for k, v in defaults.items():
        env.setdefault(k, v)
    env.update(updates)
    with open(path, "w") as f:
        for k, v in env.items():
            f.write(f"{k}={v}\n")
    return path


def _gh_target_repo():
    try:
        r = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def push_or_print_secrets(secrets):
    manual = "set -a && source .env && set +a\n" + "\n".join(
        f'printf %s "${name}" | gh secret set {name}' for name in SECRET_NAMES
    )

    if not shutil.which("gh"):
        print("\nAdd these as GitHub Actions secrets. Install the GitHub CLI "
              "(https://cli.github.com) then run from the repo:")
        print(manual)
        print("(Or add them in the repo: Settings, Secrets and variables, Actions.)")
        return

    target = _gh_target_repo()
    print(f"\nGitHub CLI detected. Detected target repo: {target or '(none)'}")
    if input("Push the configured secrets to GitHub now? [y/N] ").strip().lower() != "y":
        print("Skipped. To do it yourself, run from the repo:")
        print(manual)
        return
    repo = input(f"Repo to set secrets on [{target or 'owner/name'}]: ").strip() or target
    if not repo:
        print("No target repo given. Skipping; run manually:")
        print(manual)
        return
    for name in SECRET_NAMES:
        value = secrets.get(name, "")
        if not value:
            print(f"  skip {name} (empty)")
            continue
        r = subprocess.run(["gh", "secret", "set", name, "--repo", repo],
                           input=value, capture_output=True, text=True)
        print(f"  set {name}: {'OK' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}")


def choose_parent_page(token):
    print("\nWhere should the database live?")
    print("  1) Pick from pages your integration can access")
    print("  2) Paste a Notion page URL or ID")
    if input("> ").strip() == "1":
        pages = search_pages(token)
        if not pages:
            print("\nYour integration cannot see any pages yet. Open the page you want, "
                  "'...' menu, Connections, add your integration, then paste its URL below.")
            return _ask_page_id(token)
        print("\nPages your integration can access:")
        for i, p in enumerate(pages):
            print(f"  [{i}] {p['title']}")
        while True:
            sel = input("Pick a number: ").strip()
            if sel.isdigit() and 0 <= int(sel) < len(pages):
                return pages[int(sel)]["id"]
            print("Enter one of the numbers shown.")
    return _ask_page_id(token)


def _ask_page_id(token):
    page_id = parse_page_id(input("Notion page URL or ID: ").strip())
    if not page_reachable(token, page_id):
        sys.exit("The integration can't see that page. Open it, '...' menu, Connections, "
                 "add your integration, then re-run.")
    return page_id


def main():
    print("Setup: create your LeetCode revision database in Notion.")
    _load_dotenv()
    token = read_token()

    db_id = existing_env_db(token)
    if db_id:
        print(f"Reusing existing database from NOTION_DATABASE_ID: {db_id}")
    else:
        parent_id = choose_parent_page(token)
        db_id = find_existing_db(token, parent_id)
        if db_id:
            print(f"Found an existing '{schema.DB_TITLE}' under that page; reusing {db_id}.")
        else:
            print(f"Creating '{schema.DB_TITLE}'...")
            db_id = create_database(token, parent_id)
            print(f"Created database: {db_id}")

    print(f"Open it: https://www.notion.so/{db_id.replace('-', '')}")

    username = read_username()
    session = read_optional_secret(
        "LEETCODE_SESSION",
        "your LeetCode session cookie pulls submitted code, runtime and memory. "
        "Find it in your browser's cookies for leetcode.com.",
    )
    anthropic_key = read_optional_secret(
        "ANTHROPIC_API_KEY",
        "an Anthropic API key lets Claude draft approach summaries. Bring your own key.",
    )
    openai_key = read_optional_secret(
        "OPENAI_API_KEY",
        "an OpenAI API key lets an OpenAI model draft approach summaries. "
        "It is used only when no Anthropic key is set.",
    )
    secrets = {
        "NOTION_TOKEN": token,
        "NOTION_DATABASE_ID": db_id,
        "LEETCODE_USERNAME": username,
        "LEETCODE_SESSION": session,
        "ANTHROPIC_API_KEY": anthropic_key,
        "OPENAI_API_KEY": openai_key,
    }
    updates = {name: value for name, value in secrets.items() if value}
    defaults = {name: "" for name, value in secrets.items() if not value}
    path = write_env(updates, defaults=defaults)
    print(f"Wrote {path}")
    push_or_print_secrets(secrets)

    print("\n" + ("Done. Run 'python main.py' or trigger the GitHub Action."
                  if username else
                  "Done. Set LEETCODE_USERNAME (in .env and your GitHub secrets), then run 'python main.py'."))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
    except (RuntimeError, ValueError) as e:
        sys.exit(f"Error: {e}")
