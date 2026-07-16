# Roadmap Agent

An agent that turns "I want to learn X" into a dependency graph of modules with
real, link-checked learning resources, paced into daily sessions — and that
reshapes the plan when you get stuck.

Flask + SQLAlchemy + SQLite backend, Vue 3 frontend (no build step), Nocturne
dark theme from the design bundle in `design-handoff/`.

## Run

### Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py            # http://localhost:5000
```

First start creates `instance/roadmap.sqlite3` and seeds the demo data
(the "Learn Arabic" and "Go for Backend" roadmaps from the design).
Re-seed from scratch any time:

```bash
flask --app run seed
```

### Docker

```bash
# Build the image
docker build -t roadmap-agent .

# Run (demo data auto-seeded on first start)
docker run -p 5000:5000 roadmap-agent

# Persist the SQLite database across container restarts
docker run -p 5000:5000 -v $(pwd)/data:/app/instance roadmap-agent

# With real providers
docker run -p 5000:5000 \
  -e LLM_PROVIDER=gemini \
  -e SEARCH_PROVIDER=exa \
  -e GEMINI_API_KEY=... \
  -e EXA_API_KEY=... \
  roadmap-agent

# Re-seed demo data inside a running container
docker exec <container-id> flask --app run seed
```

No API keys and no internet are required: LLM and search providers default to
mocks (`.env.example` shows how to switch to Anthropic / Tavily later).

## Switching to real providers

Copy `.env.example` to `.env` and fill in your API keys:

```env
LLM_PROVIDER=gemini          # or: anthropic
SEARCH_PROVIDER=exa          # or: tavily
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
EXA_API_KEY=...
```

Install the optional SDKs (only what you use):

```bash
pip install google-genai anthropic tavily-python exa-py
```

A natural setup is **Gemini as the planner + Exa as the sourcer**: Gemini
(`LLM_PROVIDER=gemini`) structures the modules and prerequisites, Exa
(`SEARCH_PROVIDER=exa`) finds real, current links, and `agent/verify.py`
HTTP-checks each one. The LLM never emits URLs — that separation is enforced in
the runner.

`SEARCH_PROVIDER=exa` uses [Exa](https://exa.ai) semantic web search — the same
engine [Agent-Reach](https://github.com/Panniantong/Agent-Reach) uses under the
hood — to source real, current resources. Results are untyped URLs that
`agent/verify.py` still HTTP-checks; the kind (video/course/…) is inferred from
the domain. Adding a provider is just a new `SearchProvider` subclass — the
runner is unchanged.

## Architecture

```
run.py
  └─ app/__init__.py          Flask factory
       ├─ app/db.py            SQLAlchemy engine (SQLite, thread-safe)
       ├─ app/models.py        7 models (Roadmap, Module, ModuleDep,
       │                        Resource, StudySession, AgentRun, Insight)
       ├─ app/graph.py         DAG engine (topo sort, validate, layout, states)
       ├─ app/scheduler.py     Session scheduler (pure Python, no LLM)
       ├─ app/seed.py          Demo data ("Learn Arabic" + "Go for Backend")
       ├─ app/api/             JSON API blueprint
       │    ├─ roadmaps.py     GET /api/roadmaps, POST /api/roadmaps
       │    ├─ modules.py      GET /api/modules/<id>, POST /api/modules/<id>/stuck
       │    ├─ sessions.py     POST /api/sessions/<id>/complete | /skip
       │    ├─ runs.py         GET /api/runs/<id>
       │    ├─ today.py        GET /api/today
       │    ├─ insights.py     POST /api/insights/<id>/apply
       │    └─ serializers.py  All response payload builders
       └─ agent/               Agent providers & 5-step runner
            ├─ llm.py          LLMProvider → MockLLM | AnthropicLLM | GeminiLLM
            ├─ search.py       SearchProvider → MockSearch | TavilySearch | ExaSearch
            ├─ verify.py       HTTP link verification (HEAD → GET, 5s timeout)
            └─ runner.py       run_generation + run_replan (background threads)
```

Agent flow (generation):

```
User POST /api/roadmaps {topic, ...}
  → Roadmap + AgentRun created in DB
  → Background thread spawned
    → Step 1: LLM plans modules + edges (JSON)
    → Step 2: Validate DAG (retry up to 2x with LLM feedback)
    → Step 3: Search for resources (dedup by url_hash)
    → Step 4: Verify all URLs over HTTP
    → Step 5: Create Module/ModuleDep/Resource records, recompute states, schedule
```

Agent flow (replan):

```
User POST /api/modules/<id>/stuck {reason}
  → Module.state = "stuck", stuck StudySession recorded
  → Background thread spawned
    → Step 1: Diagnose the block
    → Step 2: LLM proposes 2-4 gentler submodules
    → Step 3: Search for resources (prefer video + practice)
    → Step 4: Verify new URLs
    → Step 5: Create child modules, rewire DAG edges,
              recompute states, schedule, write Insight
```

## API

```
POST /api/roadmaps               {topic, level, minutes_per_day, weekdays} → 202 {roadmap_id, run_id}
GET  /api/runs/<id>              → {status, steps[]}          # frontend polls every 700ms
GET  /api/roadmaps               → cards: progress, streak, stuck flag
GET  /api/roadmaps/<id>          → {roadmap, modules[] (state, code, x, y), edges[], counts}
DELETE /api/roadmaps/<id>        → {ok, deleted}   # cascades: modules, deps, resources, sessions, runs, insights
GET  /api/modules/<id>           → module + resources[] (with verified_at)
GET  /api/today                  → today's sessions + all_done flag
POST /api/sessions/<id>/complete {actual_minutes, note?}
POST /api/sessions/<id>/skip
POST /api/modules/<id>/stuck     {reason, note?} → 202 {run_id}
GET  /api/roadmaps/<id>/stats    → metrics, stuck_modules[], insights[], heatmap[56]
POST /api/insights/<id>/apply    → 202 {run_id}
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Status

- [x] Stage 1 — models, graph engine (topo sort, states, layout), scheduler,
      seed, read-only JSON API
- [x] Stage 2 — the agent: LLM + search + link verification, 5-step runner
- [x] Stage 3 — sessions, stuck → replan, stats
- [x] Stage 4 — Vue frontend (4 screens), tests, README
