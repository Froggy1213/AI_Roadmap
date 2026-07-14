"""Search provider interface and implementations.

MockSearch returns realistic-looking results for any query without API keys.
TavilySearch calls the Tavily API when TAVILY_API_KEY is set.
"""

from __future__ import annotations

import os
import random
from abc import ABC, abstractmethod


class SearchProvider(ABC):
    """Abstract interface for web search."""

    @abstractmethod
    def search(self, query: str, n: int = 5) -> list[dict]:
        """Return up to `n` results, each as {title, url, snippet, kind}."""


# ---------------------------------------------------------------------------
# Mock Search — plausible results without internet
# ---------------------------------------------------------------------------

# Per-topic-domain stub sites — use real, fast domains that respond to HEAD
# so the mock demo has a high alive/dead ratio.
_DOMAINS = {
    "video": [
        "youtube.com",
        "vimeo.com",
    ],
    "article": [
        "en.wikipedia.org",
        "github.com",
        "medium.com",
        "dev.to",
    ],
    "course": [
        "coursera.org",
        "udemy.com",
        "khanacademy.org",
    ],
    "book": [
        "en.wikipedia.org",
        "github.com",
    ],
    "audio": [
        "en.wikipedia.org",
    ],
    "practice": [
        "github.com",
        "en.wikipedia.org",
    ],
}

_RESULT_TEMPLATES = {
    "video": [
        ("{topic} — Full Course for Beginners", "Complete {topic} tutorial covering all the fundamentals in one video."),
        ("Learn {topic} in {n} Minutes", "Quick intro to {topic} — perfect for getting started fast."),
        ("{topic} Crash Course", "Intensive {topic} crash course with hands-on examples."),
        ("{topic} Deep Dive: {aspect}", "Advanced {topic} techniques explained with real-world examples."),
    ],
    "article": [
        ("The Complete Guide to {topic}", "Everything you need to know about {topic}, from basics to advanced patterns."),
        ("Getting Started with {topic} — A Beginner's Guide", "Step-by-step introduction to {topic} with code samples."),
        ("{topic} Best Practices in 2026", "Modern best practices and patterns for {topic}."),
        ("Understanding {topic}: Core Concepts", "Deep dive into the fundamental concepts behind {topic}."),
        ("How I Learned {topic} in 3 Months", "A personal learning journey with practical tips."),
    ],
    "course": [
        ("{topic} Masterclass — University-Level Course", "Structured curriculum with assignments and projects."),
        ("Interactive {topic} Course", "Learn {topic} by building real projects step by step."),
        ("{topic} Specialisation", "Multi-course specialisation covering {topic} from zero to production."),
    ],
    "book": [
        ("{topic} in Action", "Practical {topic} with real-world examples and exercises."),
        ("The {topic} Handbook", "Comprehensive reference covering everything in {topic}."),
    ],
    "audio": [
        ("The {topic} Podcast", "Weekly discussions about {topic} with industry experts."),
        ("{topic} Audio Course", "Learn {topic} on the go with structured audio lessons."),
    ],
    "practice": [
        ("{topic} Exercises & Challenges", "Practice {topic} with a collection of graded exercises."),
        ("{topic} Playground", "Interactive coding environment to experiment with {topic}."),
        ("Daily {topic} Challenge", "New {topic} problem every day to keep your skills sharp."),
    ],
}


def _make_result(query: str, kind: str, idx: int) -> dict:
    """Build one plausible search result for `query` of the given `kind`."""
    rng = random.Random(hash(f"{query}:{kind}:{idx}") & 0x7FFFFFFF)
    templates = _RESULT_TEMPLATES.get(kind, _RESULT_TEMPLATES["article"])
    tpl_title, tpl_snippet = templates[idx % len(templates)]
    # Extract a short topic name from the query
    topic_words = query.replace(" tutorial", "").replace(" course", "").replace(" guide", "").split()
    topic = " ".join(topic_words[:5]) if topic_words else query
    n = rng.randint(15, 120)
    aspect = rng.choice(["Core Patterns", "Performance", "Testing", "Architecture", "Best Practices"])

    title = tpl_title.replace("{topic}", topic).replace("{aspect}", aspect).replace("{n}", str(n))

    domain = rng.choice(_DOMAINS.get(kind, _DOMAINS["article"]))
    slug = title.lower().replace(" ", "-").replace("'", "").replace("—", "").replace(":", "")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    path = f"/{'learn' if kind == 'course' else 'blog'}/{slug}"
    url = f"https://www.{domain}{path}"

    return {
        "title": title,
        "url": url,
        "snippet": tpl_snippet.replace("{topic}", topic),
        "kind": kind,
    }


class MockSearch(SearchProvider):
    """Returns realistic-looking search results for any query, no API needed.

    Each query returns a mix of resource kinds (video, article, course, practice)
    with domain-appropriate URLs and plausible titles.
    """

    def search(self, query: str, n: int = 5) -> list[dict]:
        rng = random.Random(hash(query) & 0x7FFFFFFF)
        kinds = ["video", "article", "course", "practice"]
        # Shuffle kinds per query so the distribution varies
        rng.shuffle(kinds)
        results = []
        for i in range(min(n, 8)):
            kind = kinds[i % len(kinds)]
            # Every query gets exactly one "article" even if the shuffle
            # produces something else at that slot — ensures variety
            if i == 1:
                kind = "article"
            elif i == 3:
                kind = rng.choice(["book", "audio"])
            results.append(_make_result(query, kind, i))
        return results[:n]


# ---------------------------------------------------------------------------
# Tavily Search
# ---------------------------------------------------------------------------

class TavilySearch(SearchProvider):
    """Calls the Tavily Search API. Requires `pip install tavily-python` and
    TAVILY_API_KEY set in the environment."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    def search(self, query: str, n: int = 5) -> list[dict]:
        try:
            from tavily import TavilyClient
        except ImportError:
            raise RuntimeError(
                "tavily-python package is required for TavilySearch. "
                "Install it with: pip install tavily-python"
            )
        client = TavilyClient(api_key=self._api_key)
        response = client.search(query=query, max_results=n, search_depth="basic")
        results: list[dict] = []
        for r in response.get("results", [])[:n]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "kind": "article",  # Tavily doesn't classify — default to article
            })
        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_search() -> SearchProvider:
    """Return the configured search provider based on SEARCH_PROVIDER env var."""
    provider = os.environ.get("SEARCH_PROVIDER", "mock").lower()
    if provider == "tavily":
        return TavilySearch()
    # Default: mock
    return MockSearch()
