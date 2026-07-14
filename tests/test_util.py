"""Tests for URL helpers and utility functions."""

import pytest

from app.util import (
    code_prefix,
    humanize_ago,
    humanize_minutes,
    normalize_url,
    parse_weekdays,
    url_hash,
)


class TestNormalizeUrl:
    def test_default_scheme(self):
        assert normalize_url("example.com").startswith("https://")

    def test_lowercase_host(self):
        assert "example.com" in normalize_url("HTTPS://EXAMPLE.COM/page")

    def test_strips_fragment(self):
        assert "#" not in normalize_url("https://example.com/page#section")

    def test_strips_tracking_params(self):
        n = normalize_url("https://example.com/page?utm_source=x&id=1")
        assert "utm_source" not in n
        assert "id=1" in n

    def test_strips_www_prefix(self):
        n = normalize_url("https://www.example.com/page")
        assert "www." not in n

    def test_strips_trailing_slash(self):
        n = normalize_url("https://example.com/page/")
        assert not n.endswith("/")

    def test_removes_default_ports(self):
        n = normalize_url("http://example.com:80/page")
        assert ":80" not in n


class TestUrlHash:
    def test_same_url_same_hash(self):
        assert url_hash("https://example.com/a") == url_hash("https://example.com/a")

    def test_normalized_urls_match(self):
        assert url_hash("https://www.EXAMPLE.com/a/") == url_hash("https://example.com/a")

    def test_different_urls_different_hash(self):
        assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


class TestParseWeekdays:
    def test_standard_weekdays(self):
        assert parse_weekdays("1,2,3,4,5") == {1, 2, 3, 4, 5}

    def test_custom_days(self):
        assert parse_weekdays("2,4") == {2, 4}

    def test_empty_defaults_to_mon_fri(self):
        assert parse_weekdays("") == {1, 2, 3, 4, 5}

    def test_out_of_range_filtered(self):
        assert 8 not in parse_weekdays("1,8")


class TestHumanizeAgo:
    def test_today(self):
        from datetime import date
        assert humanize_ago(date.today(), date.today()) == "today"

    def test_yesterday(self):
        from datetime import date, timedelta
        today = date.today()
        assert humanize_ago(today - timedelta(days=1), today) == "yesterday"

    def test_days_ago(self):
        from datetime import date, timedelta
        today = date.today()
        assert humanize_ago(today - timedelta(days=5), today) == "5 days ago"


class TestHumanizeMinutes:
    def test_minutes_only(self):
        assert "45 min" in humanize_minutes(45)

    def test_hours_only(self):
        assert humanize_minutes(120) == "2 h"

    def test_hours_and_minutes(self):
        assert humanize_minutes(95) == "1 h 35 min"


class TestCodePrefix:
    def test_simple_topic(self):
        assert code_prefix("Learn Arabic") == "AR"

    def test_stopwords_skipped(self):
        assert code_prefix("learning the go") == "GO"

    def test_fallback_first_letters(self):
        assert code_prefix("For") == "FO"

    def test_go_topic(self):
        assert code_prefix("Go for Backend") == "GO"
