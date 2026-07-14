# Промпт для Claude Code

Положи рядом с проектом распакованный дизайн-бандл (`roadmap-agent-saas-design/`) и вставь текст ниже.

---

Build a working MVP web app called **Roadmap Agent**. The design bundle is in `./roadmap-agent-saas-design/` — read `project/Roadmap Agent App.dc.html`, `project/assets/*.css` and `project/_ds/nocturne-*/styles.css` first. Those are HTML prototypes, not production code: reproduce the **visual result** (Nocturne dark theme, `--color-bg:#161826`, `--color-surface:#232532`, `--color-accent:#9184d9`, Inter, the node/edge/popover styling), not the prototype's internals.

## What the product does

The user types a topic ("Arabic, from zero to conversation") and how much time they have per day. An agent breaks the topic into a **DAG of modules** with prerequisites, **searches the web for real learning resources** for each module, **verifies every link is alive over HTTP**, and then **schedules the modules into daily sessions**. As the user works, they mark sessions done / skipped / stuck. When a module is marked stuck, the agent **splits it into smaller submodules, finds gentler resources, rewires the graph and reschedules**.

## Stack (do not substitute)

- Backend: **Python 3.11+, Flask** (app factory + blueprints), SQLAlchemy 2.0, **SQLite**
- Frontend: **Vue 3** (Composition API) — no build step, no npm. Load Vue from a locally vendored `vue.esm-browser.prod.js` in `static/vendor/`, use ES modules and a tiny hash router you write yourself. Flask serves one `index.html`.
- Background work: a plain Python **thread** writing progress into the DB. No Redis, no Celery.
- No Docker, no Telegram, no auth. Single hardcoded demo user.

## Hard requirements

1. **The app must run with zero API keys and zero internet.** `agent/llm.py` and `agent/search.py` expose interfaces with two implementations each: `MockLLM` / `AnthropicLLM` and `MockSearch` / `TavilySearch`, selected by `LLM_PROVIDER` and `SEARCH_PROVIDER` in `.env`. Defaults are the mocks. The mocks must be good enough that every screen looks real in a demo.
2. **The LLM never produces URLs.** URLs come only from the search provider and must pass an HTTP check (`agent/verify.py`: HEAD, fall back to GET with a Range header, 5s timeout). Store `http_status` and `verified_at`. Dead links are dropped and counted. If the network is unreachable, mark resources `unverified` — never crash.
3. **The graph is validated, not trusted.** After the LLM proposes modules + prerequisites, run a topological sort. On a cycle or a dangling prerequisite, send the error text back to the LLM and retry (max 2). Enforce 8–24 modules, exactly one root, one capstone leaf.
4. **The scheduler is pure Python, no LLM.** Topological order → split `est_minutes` into sessions of `minutes_per_day` → place them on the user's active weekdays. Return the projected finish date.
5. **The backend computes everything the UI displays.** Module `state` (`locked` / `available` / `inprogress` / `completed` / `stuck`), module codes (`AR-09`), node `x`/`y` coordinates (layered layout: layer = longest path from root; nodes 170px wide, 208px horizontal pitch, spread vertically), percentages, "stuck for N days". The Vue app renders and never derives.

## Data model

`Roadmap(id, topic, goal, level, color, status[building|ready|failed], minutes_per_day, weekdays, target_date, created_at)`
`Module(id, roadmap_id, code, title, title_native, summary, est_sessions, est_minutes, state, parent_module_id, layout_x, layout_y)`
`ModuleDep(module_id, prereq_module_id)`
`Resource(id, module_id, title, url, url_hash, kind[video|article|course|book|audio|practice], source_domain, duration_min, is_paid, http_status, verified_at, relevance)`
`StudySession(id, module_id, planned_date, planned_minutes, actual_minutes, status[planned|done|skipped|stuck], started_at, completed_at, note)`
`AgentRun(id, roadmap_id, kind[generate|replan], status, steps JSON, error, started_at, finished_at)`
`Insight(id, roadmap_id, kind, text, action_kind, payload JSON, created_at)`

`AgentRun.steps` is the source of truth for the build screen: a list of `{key, label, status[pending|running|done|failed], detail}` where `detail` carries live counters.

## API

```
POST /api/roadmaps               {topic, level, minutes_per_day, weekdays} → 202 {roadmap_id, run_id}
GET  /api/runs/<id>              → {status, steps[]}          # frontend polls every 700ms
GET  /api/roadmaps               → cards: progress, streak, stuck flag
GET  /api/roadmaps/<id>          → {roadmap, modules[] (state, code, x, y), edges[], counts}
GET  /api/modules/<id>           → module + resources[] (with verified_at)
GET  /api/today                  → today's sessions + all_done flag
POST /api/sessions/<id>/complete {actual_minutes, note?}
POST /api/sessions/<id>/skip
POST /api/modules/<id>/stuck     {reason, note?} → 202 {run_id}
GET  /api/roadmaps/<id>/stats    → metrics, stuck_modules[], insights[], heatmap[56]
POST /api/insights/<id>/apply    → 202 {run_id}
```

Every long operation returns `202 + run_id` and is polled through `/api/runs/<id>` — one pattern for generation and replanning, reused by the frontend.

## Screens (Vue)

1. **Home** — two states. *First visit:* one big input "What do you want to learn?", 4 example chips, one line explaining how the agent works. Nothing else — it is not a landing page. *Working:* "Today" block first (session rows: line color, module code, title, minutes, **Start** / **Push back**; when finished → "That's everything for today" + **Pull a module forward**), then "My roadmaps" cards (name, progress bar, pace, last session, stuck badge).
2. **Build** — shown while the agent works. Not a spinner: a vertical list of the five agent steps with live counters (`plan → validate graph → sourcing (12 queries · 41 found) → verify (34 alive · 5 dead) → schedule (ready by Mar 12)`). Finished steps collapse to one line with a check. On failure: "Couldn't find enough resources for this topic — try narrowing it" with an editable field, no apology.
3. **Roadmap** — the module graph: absolutely-positioned node cards over an SVG layer of Bézier edges, edge style per state (done / active / stuck / locked-dashed), "You are here" pin on the in-progress node, resource popover with **Verified** badges, and the **Plan adapted** panel next to a stuck module listing the submodules it was split into. Legend at the bottom. Clicking a node opens its module panel with resources and **Mark done** / **I'm stuck** actions.
4. **Stats** — a thin metrics strip (streak, hours this week, modules done, projected finish), then "Where you get stuck" (module, estimate vs actual, **Split into smaller steps** button), then agent insights each with an action button, then an 8-week activity heatmap.

UI language: **English**, sentence case, active verbs, no exclamation marks. Empty states are invitations to act. Responsive down to mobile, visible focus rings, respect `prefers-reduced-motion`.

## Deliver in stages, stopping for review after each

- **Stage 1** — project skeleton, models, `graph.py` (topo sort, `recompute_states`, layout), `scheduler.py`, `seed.py` reproducing the exact "Learn Arabic" roadmap from the design (10 modules, `Core 300 Words` in progress, `Root & Pattern System` stuck), all GET endpoints serving real DB data. No LLM calls at all. Show me `curl` output for `/api/roadmaps/1`.
- **Stage 2** — the agent: LLM + search + verify providers, the five-step runner, DAG validation with retries, resource dedup, `POST /api/roadmaps`, `GET /api/runs/<id>`.
- **Stage 3** — sessions, stuck → replanner (split module, rewire edges, reschedule, write an Insight), stats endpoint.
- **Stage 4** — the Vue frontend, all four screens, then `README.md` and tests for topo sort, `recompute_states`, scheduler and dedup.

Do not skip the link verification or the graph validation to save time — they are the point of the project, not decoration.
