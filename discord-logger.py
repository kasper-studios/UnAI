#!/usr/bin/env python3
"""UnAI Discord webhook logger — local replacement for GitHub Actions.

Sends a Discord embed to a webhook URL whenever a new commit lands on
origin/main.  Keeps track of the last-seen SHA so it never spams twice.

Configuration (not committed to the repo):
    ~/.config/unai/discord-webhook   — full webhook URL (one line)
    ~/.config/unai/discord-state.json — last-seen SHA + repo metadata

Usage:
    python3 discord-logger.py
    # or via cron:
    # */5 * * * * python3 ~/Programs/UnAI/discord-logger.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration paths (outside the repo, so webhook URL never leaks to git)
# ---------------------------------------------------------------------------
CONFIG_DIR = Path.home() / ".config" / "unai"
WEBHOOK_FILE = CONFIG_DIR / "discord-webhook"
STATE_FILE = CONFIG_DIR / "discord-state.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd or REPO, capture_output=True, text=True)


def _load_webhook() -> str | None:
    if WEBHOOK_FILE.exists():
        return WEBHOOK_FILE.read_text().strip() or None
    return None


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _get_remote_sha(remote: str = "origin", branch: str = "main") -> str | None:
    out = _run("git", "ls-remote", "--heads", remote, branch)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    # "abc123 refs/heads/main"
    return out.stdout.strip().split("\t")[0]


def _get_latest_commit_msg(sha: str, n: int = 1) -> str:
    out = _run("git", "log", "-n", str(n), "--format=%s", sha)
    return out.stdout.strip()


def _get_latest_author(sha: str, n: int = 1) -> str:
    out = _run("git", "log", "-n", str(n), "--format=%an", sha)
    return out.stdout.strip()


def _send_discord(webhook_url: str, title: str, description: str,
                  url: str, author: str, color: int = 3066993) -> bool:
    payload = json.dumps({
        "username": "UnAI GitHub",
        "embeds": [{
            "title": title,
            "description": description,
            "url": url,
            "color": color,
            "fields": [
                {"name": "Repo", "value": REPO_NAME, "inline": True},
                {"name": "Author", "value": author, "inline": True},
            ],
        }],
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            # Discord rejects the default "Python-urllib/x" UA with HTTP 403.
            "User-Agent": "UnAI-Logger/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            if resp.status in (200, 201, 204):
                return True
            print(f"Discord returned {resp.status}: {body}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Discord send failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent
REPO_NAME = "kasper-studios/UnAI"


def main() -> None:
    webhook_url = _load_webhook()
    if not webhook_url:
        print(f"Webhook URL not found at {WEBHOOK_FILE}", file=sys.stderr)
        print("Create it with: echo '<url>' > ~/.config/unai/discord-webhook", file=sys.stderr)
        sys.exit(1)

    remote_sha = _get_remote_sha()
    if not remote_sha:
        print("Could not resolve origin/main SHA", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    last_sha = state.get("sha")

    if last_sha == remote_sha:
        # Nothing new — nothing to do.
        return

    # New commit detected.
    msg = _get_latest_commit_msg(remote_sha, n=1) or "(no commit message)"
    author = _get_latest_author(remote_sha, n=1) or "unknown"

    title = f"Push to main"
    url = f"https://github.com/{REPO_NAME}/commit/{remote_sha}"
    description = f"{msg}\nby {author}"

    ok = _send_discord(webhook_url, title, description, url, author)
    if ok:
        _save_state({"sha": remote_sha, "repo": REPO_NAME})
        print(f"Sent commit {remote_sha[:8]} to Discord")
    else:
        print(f"Failed to send commit {remote_sha[:8]}", file=sys.stderr)


if __name__ == "__main__":
    main()