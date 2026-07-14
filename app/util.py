import hashlib
import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    """Canonical form used for dedup: lowercase scheme/host, no default port,
    no fragment, no tracking params, no trailing slash."""
    url = url.strip()
    # urlsplit needs a scheme to parse correctly — prepend // if missing
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.endswith(":80") and scheme == "http":
        host = host[:-3]
    if host.endswith(":443") and scheme == "https":
        host = host[:-4]
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k not in TRACKING_PARAMS])
    return urlunsplit((scheme, host, path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_weekdays(spec: str) -> set[int]:
    """'1,2,3,4,5' → {1..5} (ISO weekday numbers, Mon=1)."""
    days = {int(p) for p in spec.split(",") if p.strip()}
    return {d for d in days if 1 <= d <= 7} or {1, 2, 3, 4, 5}


def next_active_day(start: date, active: set[int]) -> date:
    d = start
    while d.isoweekday() not in active:
        d += timedelta(days=1)
    return d


def humanize_ago(d: date, today: date | None = None) -> str:
    today = today or date.today()
    n = (today - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"{n} days ago"


def humanize_minutes(total: int) -> str:
    h, m = divmod(max(total, 0), 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


def month_day(d: date) -> str:
    return f"{d:%b} {d.day}"


_CODE_STOPWORDS = {
    "learn", "learning", "master", "mastering", "study", "studying",
    "the", "a", "an", "for", "from", "to", "of", "in", "into", "with", "and",
}


def code_prefix(topic: str) -> str:
    """Module-code prefix from a topic: first meaningful word, two letters.
    'Learn Arabic' -> 'AR', 'Go for Backend' -> 'GO'."""
    words = [w for w in re.split(r"[^\w]+", topic, flags=re.UNICODE) if w]
    for w in words:
        if w.lower() not in _CODE_STOPWORDS:
            return w[:2].upper()
    return (words[0][:2] if words else "RM").upper()

