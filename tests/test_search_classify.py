"""The kind classifier maps untyped search-result URLs (Exa, Tavily) onto the
app's resource kinds. Pure function — no network."""

import os

import pytest

from agent.search import ExaSearch, MockSearch, TavilySearch, classify_kind, get_search


@pytest.mark.parametrize("url,kind", [
    ("https://www.youtube.com/watch?v=abc", "video"),
    ("https://youtu.be/abc", "video"),
    ("https://vimeo.com/12345", "video"),
    ("https://www.coursera.org/learn/python", "course"),
    ("https://www.edx.org/course/x", "course"),
    ("https://podcasts.apple.com/us/podcast/x", "audio"),
    ("https://openlibrary.org/works/OL1W", "book"),
    ("https://github.com/user/repo", "practice"),
    ("https://leetcode.com/problems/two-sum/", "practice"),
    ("https://en.wikipedia.org/wiki/Arabic", "article"),   # fallback
    ("https://some-random-blog.dev/post", "article"),      # fallback
])
def test_classify_kind(url, kind):
    assert classify_kind(url) == kind


def test_classify_kind_matches_subdomains():
    assert classify_kind("https://gist.github.com/user/abc") == "practice"
    assert classify_kind("https://m.youtube.com/watch?v=abc") == "video"


def test_factory_selects_provider(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "exa")
    assert isinstance(get_search(), ExaSearch)
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    assert isinstance(get_search(), TavilySearch)
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    assert isinstance(get_search(), MockSearch)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    assert isinstance(get_search(), MockSearch)  # default


def test_exa_without_key_raises_cleanly(monkeypatch):
    """No key must fail with a clear message, never crash the runner."""
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ExaSearch(api_key="").search("arabic grammar", n=3)
