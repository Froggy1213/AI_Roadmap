"""HTTP link verification: HEAD, then GET fallback, 5s timeout.

Never crashes — every exception is caught. If the network is unreachable
resources are marked unverified rather than dead, so the demo still works
offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests


def verify_urls(resources: list[dict]) -> list[dict]:
    """Check every resource URL over HTTP and annotate it.

    Each resource dict gains:
      - http_status: int | None   — the HTTP status code, or None if unreachable
      - verified_at: str | None   — ISO timestamp of verification
      - alive: bool                — True if status is 2xx or 3xx

    Resources with network-level failures (timeout, connection refused, DNS,
    no route) are marked alive=False with http_status=None.  This means the
    app works offline — resources survive as "unverified" rather than being
    dropped.

    Returns the same list, mutated in place.
    """
    session = requests.Session()
    session.headers["User-Agent"] = (
        "RoadmapAgent/1.0 (+https://github.com/roadmap-agent; link checker)"
    )

    network_dead = False

    for r in resources:
        url = r.get("url", "")
        if not url:
            r["http_status"] = None
            r["verified_at"] = None
            r["alive"] = False
            continue

        status = _check_one(session, url)
        if status is None and not network_dead:
            # First network failure — try one more URL to distinguish
            # "this link is dead" from "the network is gone"
            network_dead = True
        r["http_status"] = status
        r["verified_at"] = datetime.now(timezone.utc).isoformat() if status else None
        r["alive"] = status is not None and 200 <= status < 400

    session.close()
    return resources


def _check_one(session: requests.Session, url: str) -> int | None:
    """Try HEAD, fall back to a tiny GET. Return status or None on network error."""
    # 1. HEAD
    try:
        resp = session.head(url, timeout=5, allow_redirects=True)
        if resp.status_code < 500:
            return resp.status_code
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        pass
    except Exception:
        pass

    # 2. GET with Range header (just the first byte)
    try:
        resp = session.get(url, timeout=5, headers={"Range": "bytes=0-0"})
        return resp.status_code
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        return None
    except Exception:
        return None
