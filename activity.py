"""Activity log stored in the Supabase server_activity table."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE_URL = f"{SUPABASE_URL}/rest/v1/server_activity"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    headers.update(extra or {})
    return headers


def _insert(action: str, detail: str) -> None:
    body = json.dumps({"action": action, "detail": detail}).encode()
    request = urllib.request.Request(TABLE_URL, data=body, headers=_headers({"Prefer": "return=minimal"}), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=8):
            pass
    except (OSError, urllib.error.URLError) as exc:
        print(f"[activity] could not save log entry: {exc}", file=sys.stderr, flush=True)


def record(action: str, detail: str) -> None:
    if not (SUPABASE_URL and SERVICE_KEY):
        return
    threading.Thread(target=_insert, args=(action[:80], detail[:500]), daemon=True).start()


def recent(limit: int = 50) -> list[dict]:
    if not (SUPABASE_URL and SERVICE_KEY):
        raise RuntimeError("Activity history is unavailable: Supabase is not configured for the panel.")
    query = urllib.parse.urlencode({
        "select": "created_at,action,detail",
        "order": "created_at.desc",
        "limit": str(limit),
    })
    request = urllib.request.Request(f"{TABLE_URL}?{query}", headers=_headers(), method="GET")
    with urllib.request.urlopen(request, timeout=8) as response:
        rows = json.loads(response.read(1_000_000))
    if not isinstance(rows, list):
        raise RuntimeError("Activity history returned an unexpected response.")
    return rows
