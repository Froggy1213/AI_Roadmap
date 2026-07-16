"""LLM provider interface and implementations.

MockLLM produces structured JSON for any topic without API keys.
AnthropicLLM calls the Claude API when ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import json
import os
import random
import re
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str:
        """Return raw text from the model."""

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        """Call generate and parse JSON from the response."""
        raw = self.generate(prompt, system)
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to find a JSON object in the text
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"LLM did not return valid JSON: {raw[:200]}")


# ---------------------------------------------------------------------------
# Mock LLM — realistic structured output for any topic
# ---------------------------------------------------------------------------

# Topic-category templates: each maps a topic keyword to a specialised
# module list.  The fallback generator handles anything else.
_CATEGORY_TEMPLATES: dict[str, list[dict]] = {
    "arabic": [
        {"title": "Arabic Script & Sounds", "summary": "Letters, sounds and how they connect.", "est_sessions": 12},
        {"title": "Reading Voweled Text", "summary": "Decode fully-voweled text out loud.", "est_sessions": 8},
        {"title": "Core 300 Words", "summary": "High-frequency words with spaced repetition.", "est_sessions": 10},
        {"title": "Present-Tense Verbs", "summary": "Conjugation for everyday actions.", "est_sessions": 7},
        {"title": "Nominal Sentences", "summary": "Equational sentences without a verb.", "est_sessions": 5},
        {"title": "Listening: Slow MSA", "summary": "Daily slow-MSA input.", "est_sessions": 8},
        {"title": "Root & Pattern System", "summary": "How roots and patterns generate vocabulary.", "est_sessions": 6},
        {"title": "Past Tense & Narration", "summary": "Past tense and telling what happened.", "est_sessions": 6},
        {"title": "Levantine Dialect Basics", "summary": "Bridge from MSA to spoken Levantine.", "est_sessions": 5},
        {"title": "Hold a 5-Minute Conversation", "summary": "Capstone: real conversation with a native speaker.", "est_sessions": 3},
    ],
    "go": [
        {"title": "Go Syntax & Tooling", "summary": "Packages, imports, and the Go toolchain.", "est_sessions": 4},
        {"title": "Types, Structs & Methods", "summary": "The Go type system and value receivers.", "est_sessions": 4},
        {"title": "Slices, Maps & Strings", "summary": "Core collection types.", "est_sessions": 4},
        {"title": "Errors & Panics", "summary": "Error values, panic, and recover.", "est_sessions": 3},
        {"title": "Interfaces in Practice", "summary": "Implicit interfaces and real-world patterns.", "est_sessions": 4},
        {"title": "Testing & Benchmarks", "summary": "Table-driven tests and benchmarks.", "est_sessions": 3},
        {"title": "Goroutines & Channels", "summary": "Concurrency primitives.", "est_sessions": 5},
        {"title": "Concurrency Patterns", "summary": "Worker pools, pipelines, select.", "est_sessions": 4},
        {"title": "HTTP Servers & Routing", "summary": "net/http, ServeMux, middleware.", "est_sessions": 5},
        {"title": "JSON APIs & Middleware", "summary": "REST APIs with encoding/json.", "est_sessions": 4},
        {"title": "PostgreSQL with database/sql", "summary": "SQL databases in Go.", "est_sessions": 5},
        {"title": "Migrations & Transactions", "summary": "Schema changes and ACID.", "est_sessions": 4},
        {"title": "Auth, Sessions & JWT", "summary": "Authentication patterns.", "est_sessions": 5},
        {"title": "Configuration & Logging", "summary": "Structured logging with slog.", "est_sessions": 3},
        {"title": "Docker for Go Services", "summary": "Containerising Go apps.", "est_sessions": 4},
        {"title": "CI & Deployment", "summary": "GitHub Actions and deployment.", "est_sessions": 4},
        {"title": "Observability: Metrics & Tracing", "summary": "Prometheus, OpenTelemetry.", "est_sessions": 4},
        {"title": "Caching & Message Queues", "summary": "Redis, message queues.", "est_sessions": 5},
        {"title": "System Design for APIs", "summary": "Designing production APIs.", "est_sessions": 5},
        {"title": "Capstone: Ship a Production API", "summary": "End-to-end production service.", "est_sessions": 6},
    ],
    "rust": [
        {"title": "Rust Tooling & Cargo", "summary": "rustup, cargo, and the build system.", "est_sessions": 3},
        {"title": "Ownership & Borrowing", "summary": "The core memory model.", "est_sessions": 6},
        {"title": "Structs, Enums & Pattern Matching", "summary": "Algebraic data types.", "est_sessions": 5},
        {"title": "Traits & Generics", "summary": "Polymorphism without inheritance.", "est_sessions": 5},
        {"title": "Error Handling with Result", "summary": "Result, Option, and the ? operator.", "est_sessions": 4},
        {"title": "Collections & Iterators", "summary": "Vec, HashMap, and iterator combinators.", "est_sessions": 4},
        {"title": "Lifetimes & References", "summary": "Explicit lifetime annotations.", "est_sessions": 5},
        {"title": "Testing & Documentation", "summary": "Unit tests, doc tests, integration tests.", "est_sessions": 3},
        {"title": "Async Rust with Tokio", "summary": "Async/await and the Tokio runtime.", "est_sessions": 6},
        {"title": "Building a CLI App", "summary": "clap, anyhow, and a real CLI.", "est_sessions": 5},
        {"title": "Building a Web API with Axum", "summary": "HTTP servers with Axum.", "est_sessions": 6},
        {"title": "SQLx & Database Access", "summary": "Compile-time checked SQL.", "est_sessions": 5},
        {"title": "Capstone: Full-Stack Rust App", "summary": "End-to-end project.", "est_sessions": 6},
    ],
    "python": [
        {"title": "Python Setup & Ecosystem", "summary": "pyenv, pip, venv, and project structure.", "est_sessions": 3},
        {"title": "Core Syntax & Data Types", "summary": "Variables, types, control flow.", "est_sessions": 5},
        {"title": "Functions & Scoping", "summary": "Def, args, kwargs, closures.", "est_sessions": 4},
        {"title": "Collections: Lists, Dicts, Sets", "summary": "Built-in data structures.", "est_sessions": 4},
        {"title": "Comprehensions & Generators", "summary": "List/dict comprehensions, yield.", "est_sessions": 3},
        {"title": "Classes & OOP", "summary": "Class syntax, inheritance, dataclasses.", "est_sessions": 5},
        {"title": "Modules, Packages & Imports", "summary": "Package structure and absolute/relative imports.", "est_sessions": 3},
        {"title": "File I/O & Context Managers", "summary": "Reading, writing, and with statements.", "est_sessions": 3},
        {"title": "Error Handling & Exceptions", "summary": "try/except, custom exceptions.", "est_sessions": 3},
        {"title": "Testing with pytest", "summary": "Fixtures, parametrization, mocking.", "est_sessions": 4},
        {"title": "Type Hints & Static Analysis", "summary": "mypy, pylance, and type safety.", "est_sessions": 3},
        {"title": "Async Python", "summary": "asyncio, async/await, aiohttp.", "est_sessions": 5},
        {"title": "Web APIs with FastAPI", "summary": "Building REST APIs.", "est_sessions": 5},
        {"title": "SQLAlchemy & Databases", "summary": "ORM patterns and migrations.", "est_sessions": 5},
        {"title": "Deployment & Docker", "summary": "Containerising and deploying.", "est_sessions": 4},
        {"title": "Capstone: Production Service", "summary": "End-to-end API service.", "est_sessions": 5},
    ],
    "javascript": [
        {"title": "JS Runtime & Dev Tools", "summary": "Node.js, npm, and the ecosystem.", "est_sessions": 3},
        {"title": "Variables, Types & Coercion", "summary": "var/let/const, type coercion rules.", "est_sessions": 4},
        {"title": "Functions & Closures", "summary": "Function declarations, arrow functions, closures.", "est_sessions": 4},
        {"title": "Objects & Prototypes", "summary": "Object literals, prototype chain.", "est_sessions": 3},
        {"title": "Arrays & Higher-Order Functions", "summary": "map, filter, reduce, and friends.", "est_sessions": 4},
        {"title": "Async JS: Promises & async/await", "summary": "The event loop and async patterns.", "est_sessions": 5},
        {"title": "DOM Manipulation", "summary": "Selecting, creating, and modifying DOM nodes.", "est_sessions": 4},
        {"title": "ES Modules & Bundlers", "summary": "import/export, Vite, esbuild.", "est_sessions": 3},
        {"title": "React Fundamentals", "summary": "Components, hooks, state management.", "est_sessions": 6},
        {"title": "Node.js & Express Backend", "summary": "Server-side JS.", "est_sessions": 5},
        {"title": "TypeScript Essentials", "summary": "Types, interfaces, generics.", "est_sessions": 5},
        {"title": "Testing: Vitest & Playwright", "summary": "Unit and e2e testing.", "est_sessions": 4},
        {"title": "Capstone: Full-Stack App", "summary": "End-to-end project.", "est_sessions": 6},
    ],
}

# Standard progression titles used as fallback for any topic
_FALLBACK_PATTERNS = [
    ("{topic} Fundamentals", "Core concepts, syntax, and tooling setup.", 4, 6),
    ("Setting Up Your {topic} Environment", "Installation, configuration, and first project.", 2, 4),
    ("{topic} Core Building Blocks", "The essential constructs you use every day.", 4, 6),
    ("Data & State in {topic}", "How data flows through a {topic} program.", 3, 5),
    ("Control Flow & Logic in {topic}", "Conditionals, loops, and decision-making.", 3, 5),
    ("Functions & Modular Code", "Writing reusable, testable units.", 3, 5),
    ("Error Handling & Debugging", "How to find and fix problems.", 3, 6),
    ("Testing Your {topic} Code", "Unit tests, integration tests, and TDD.", 3, 5),
    ("{topic} in Practice: Real-World Patterns", "Idiomatic patterns from production codebases.", 4, 6),
    ("Building a Real Project with {topic}", "Apply everything in a guided project.", 4, 7),
    ("Advanced {topic}: Performance & Best Practices", "Deepen your skills with advanced techniques.", 3, 6),
    ("Capstone: Ship Your {topic} Project", "End-to-end: from idea to deployed.", 3, 5),
]


def _match_category(topic: str) -> str | None:
    """Return the template key if `topic` matches a known category, else None."""
    t = topic.lower()
    for key in _CATEGORY_TEMPLATES:
        if key in t:
            return key
    return None


def _make_edges(modules: list[dict]) -> list[list[str]]:
    """Build a valid DAG (1 root, 1 capstone, no cycles) from a module list.
    Strategy: linear chain with a few fork-join diamonds for realism."""
    titles = [m["title"] for m in modules]
    n = len(titles)
    if n <= 1:
        return []
    edges: list[list[str]] = []

    # Every adjacent pair gets an edge (guarantees connectivity)
    for i in range(n - 1):
        edges.append([titles[i], titles[i + 1]])

    # Add a couple of extra edges to create diamonds (non-linear structure)
    # Skip the first 2 (to keep the root simple) and the last (capstone)
    if n >= 7:
        # Add a second dependency path for variety
        for src_idx in [2, n // 2]:
            dst_idx = min(src_idx + 2, n - 1)
            if dst_idx > src_idx + 1:
                edges.append([titles[src_idx], titles[dst_idx]])

    return edges


class MockLLM(LLMProvider):
    """Returns structured JSON for any topic without API calls.

    Matches known topic categories for maximum realism; falls back to a
    generic curriculum generator for unrecognised topics.
    """

    def generate(self, prompt: str, system: str | None = None) -> str:
        # generate_json handles everything — generate is a pass-through for
        # the ABC, but we implement it for completeness.
        result = self.generate_json(prompt, system)
        return json.dumps(result, indent=2)

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        topic, level, mpd = _extract_params(prompt)

        # 1. Check for exact category match
        cat = _match_category(topic)
        if cat is not None and cat in _CATEGORY_TEMPLATES:
            modules = [dict(m) for m in _CATEGORY_TEMPLATES[cat]]
            # Adjust est_minutes to match the user's minutes_per_day
            for m in modules:
                m["est_minutes"] = m["est_sessions"] * mpd
            edges = _make_edges(modules)
            return {"modules": modules, "edges": edges}

        # 2. Fallback: generate a generic curriculum
        rng = random.Random(hash(topic) & 0x7FFFFFFF)  # deterministic per topic
        n = rng.randint(8, 12)
        modules: list[dict] = []
        used_patterns = set()

        for i in range(min(n, len(_FALLBACK_PATTERNS))):
            pat_title, pat_summary, lo, hi = _FALLBACK_PATTERNS[i]
            est = rng.randint(lo, hi)
            modules.append({
                "title": pat_title.replace("{topic}", topic),
                "summary": pat_summary.replace("{topic}", topic),
                "est_sessions": est,
                "est_minutes": est * mpd,
            })

        # If we need more modules beyond the patterns, interleave topic-specific ones
        while len(modules) < n:
            insert_at = rng.randint(1, max(len(modules) - 1, 1))
            specifics = [
                f"Hands-On {topic} Exercises",
                f"{topic} Best Practices",
                f"Common {topic} Pitfalls",
                f"{topic} Tooling Deep Dive",
            ]
            title = specifics[len(modules) % len(specifics)]
            if title not in used_patterns:
                used_patterns.add(title)
                est = rng.randint(3, 6)
                modules.insert(insert_at, {
                    "title": title,
                    "summary": f"Practical exercises and patterns for {topic}.",
                    "est_sessions": est,
                    "est_minutes": est * mpd,
                })

        # Final module is always a capstone
        last = modules[-1]
        if "capstone" not in last["title"].lower() and "ship" not in last["title"].lower():
            last["title"] = f"{topic} Capstone Project"
            last["summary"] = f"Put everything together in a complete {topic} project."
            last["est_sessions"] = max(last["est_sessions"], 4)
            last["est_minutes"] = last["est_sessions"] * mpd

        edges = _make_edges(modules)
        return {"modules": modules, "edges": edges}


def _extract_params(prompt: str) -> tuple[str, str, int]:
    """Extract topic, level, and minutes_per_day from the prompt text."""
    topic = "Unknown Topic"
    level = "beginner"
    mpd = 30

    # Try to find topic in quotes or after "for" / "topic:"
    m = re.search(r'"([^"]+)"', prompt)
    if m:
        topic = m.group(1)
    else:
        m = re.search(r'(?:for|topic|learn)\s+["\']?([^"\'",\n]+)', prompt, re.IGNORECASE)
        if m:
            topic = m.group(1).strip()

    m = re.search(r'(?:level|at)\s+["\']?(beginner|intermediate|advanced)', prompt, re.IGNORECASE)
    if m:
        level = m.group(1).lower()

    m = re.search(r'(\d+)\s*minutes?(?:\s*per\s*day)?', prompt, re.IGNORECASE)
    if m:
        mpd = int(m.group(1))

    return topic, level, mpd


# ---------------------------------------------------------------------------
# Anthropic LLM
# ---------------------------------------------------------------------------

class AnthropicLLM(LLMProvider):
    """Calls the Anthropic Claude API. Requires `pip install anthropic` and
    ANTHROPIC_API_KEY set in the environment."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    def generate(self, prompt: str, system: str | None = None) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package is required for AnthropicLLM. "
                "Install it with: pip install anthropic"
            )
        client = anthropic.Anthropic(api_key=self._api_key)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        # response.content is a list of blocks; take the first text block
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        json_system = (system or "") + "\nRespond ONLY with valid JSON. No markdown fences, no explanation."
        return super().generate_json(prompt, json_system)


# ---------------------------------------------------------------------------
# Gemini LLM
# ---------------------------------------------------------------------------

class GeminiLLM(LLMProvider):
    """Calls Google's Gemini API — the "brain" that plans the roadmap. Requires
    `pip install google-genai` and GEMINI_API_KEY. Gemini structures the modules
    and prerequisites; it never produces URLs — those come only from the search
    provider and pass agent/verify.py's HTTP check."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        self._max_retries = 3

    def generate(self, prompt: str, system: str | None = None) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise RuntimeError(
                "google-genai package is required for GeminiLLM. "
                "Install it with: pip install google-genai"
            )
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not set — cannot use GeminiLLM.")

        import time

        client = genai.Client(api_key=self._api_key)
        config = types.GenerateContentConfig(
            # Ask Gemini for raw JSON so the planning steps parse cleanly.
            response_mime_type="application/json",
            system_instruction=system or None,
        )

        last_exc = None
        for attempt in range(self._max_retries):
            try:
                response = client.models.generate_content(
                    model=self._model, contents=prompt, config=config
                )
                return response.text or ""
            except Exception as exc:
                last_exc = exc
                # 429 RESOURCE_EXHAUSTED — wait and retry with backoff
                if not self._is_retryable(exc):
                    raise
                delay = min(2 ** attempt, 30)
                time.sleep(delay)

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return True for 429 quota errors that should be retried."""
        msg = str(exc).lower()
        return any(
            keyword in msg
            for keyword in ("429", "resource_exhausted", "quota", "rate")
        )

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        json_system = (system or "") + "\nRespond ONLY with valid JSON. No markdown fences, no explanation."
        return super().generate_json(prompt, json_system)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm() -> LLMProvider:
    """Return the configured LLM provider based on LLM_PROVIDER env var."""
    provider = os.environ.get("LLM_PROVIDER", "mock").lower()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "gemini":
        return GeminiLLM()
    # Default: mock
    return MockLLM()
