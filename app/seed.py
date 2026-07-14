"""Demo fixture. Reproduces the exact state shown in the design bundle:

* "Learn Arabic" — 10 modules, `Core 300 Words` in progress (session 6 of 10,
  two sessions planned today), `Root & Pattern System` stuck for 3 days and
  already split by the replanner into 3 submodules (the "Plan adapted" panel).
* "Go for Backend" — 20 modules, 6 complete, `Concurrency Patterns` stuck for
  6 days, one session planned today (the second card + third Today row).

All dates are relative to date.today() so the demo never goes stale.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from . import db
from .db import Base, db_session
from .graph import recompute_roadmap, topo_sort
from .models import AgentRun, Insight, Module, ModuleDep, Resource, Roadmap, StudySession
from .scheduler import schedule_roadmap
from .util import code_prefix, domain_of, month_day, url_hash

ACCENT = "#9184d9"      # --color-accent (Nocturne)
NEUTRAL = "#9397ab"     # --color-neutral-500 (Nocturne)

# --- Learn Arabic -----------------------------------------------------------
# (key, title, native title, summary, est_sessions) — 40-minute sessions
ARABIC_MODULES = [
    ("script", "Arabic Script & Sounds", "الأبجدية",
     "Letters, sounds and how they connect — the mechanical foundation.", 12),
    ("read", "Reading Voweled Text", "التشكيل",
     "Decode fully-voweled text out loud without translating.", 8),
    ("core", "Core 300 Words", "٣٠٠ كلمة",
     "The 300 highest-frequency words, spaced repetition first.", 10),
    ("verbs", "Present-Tense Verbs", "المضارع",
     "Present-tense conjugation for everyday actions.", 7),
    ("nominal", "Nominal Sentences", "الجملة الاسمية",
     "Equational sentences — say who is what without a verb.", 5),
    ("listen", "Listening: Slow MSA", "الاستماع",
     "Daily slow-MSA input to train your ear alongside the graph.", 0),
    ("root", "Root & Pattern System", "الجذر والوزن",
     "How three-letter roots and patterns generate the vocabulary.", 6),
    ("past", "Past Tense & Narration", "الماضي",
     "Past tense and telling what happened.", 6),
    ("levant", "Levantine Dialect Basics", "اللهجة الشامية",
     "Bridge from Modern Standard into spoken Levantine.", 5),
    ("conv", "Hold a 5-Minute Conversation", "محادثة",
     "Capstone: a real five-minute conversation with a native speaker.", 3),
]

ARABIC_DEPS = [
    ("script", "read"), ("read", "core"),
    ("core", "verbs"), ("core", "nominal"), ("core", "listen"),
    ("verbs", "root"), ("nominal", "root"),
    ("root", "past"), ("listen", "past"),
    ("past", "levant"), ("levant", "conv"),
]

# The replanner's split of Root & Pattern System (the "Plan adapted" panel).
ROOT_SPLIT = [
    "Recognise 5 common roots by shape",
    "One pattern only — فَاعِل (the doer)",
    "Map 10 words you already know",
]

# (title, url, kind, duration_min, is_paid, http_status); status None = unverified
ARABIC_RESOURCES = {
    "script": [
        ("Arabic Alphabet Made Easy — full playlist",
         "https://www.youtube.com/playlist?list=PLDcnymzs18LVXfO_x0Ei0R0zSk3T7Cs3G", "video", 96, False, 200),
        ("Madinah Arabic — reading course, lessons 1–8",
         "https://www.madinaharabic.com/arabic-reading-course/", "course", None, False, 200),
    ],
    "read": [
        ("Harakat: how vowel marks work",
         "https://arabic.desert-sky.net/g_vowels.html", "article", 12, False, 200),
        ("Slow voweled reading drills",
         "https://www.arabicreadingcourse.com/voweled-drills", "practice", 20, False, 200),
    ],
    "core": [
        ("Mastering Arabic 1 — Chapter 4",
         "https://www.bloomsbury.com/uk/mastering-arabic-1-9781352007268/", "book", None, True, 200),
        ("Anki — Core 300 deck, cards 121–160",
         "https://ankiweb.net/shared/info/1416344062", "practice", 15, False, None),
        ("ArabicPod101 — Everyday Nouns",
         "https://www.arabicpod101.com/lesson/absolute-beginner-s1-5-everyday-nouns", "audio", 9, False, 200),
    ],
    "verbs": [
        ("Present tense, form I — grammar series",
         "https://www.arabicpod101.com/lesson/beginner-s2-12-present-tense", "video", 14, False, 200),
        ("Conjugation drills: 20 everyday verbs",
         "https://conjugator.reverso.net/conjugation-arabic.html", "practice", 25, False, 200),
    ],
    "nominal": [
        ("The nominal sentence, explained",
         "https://arabic.fi/grammar/nominal-sentences", "article", 15, False, 200),
        ("Build 20 nominal sentences — guided",
         "https://www.madinaharabic.com/arabic-language-course/lessons/L003_001.html", "practice", 30, False, 200),
    ],
    "listen": [
        ("Slow Arabic podcast — beginner feed",
         "https://podcasts.apple.com/us/podcast/simple-stories-in-arabic/id1573900909", "audio", 10, False, 200),
        ("Al Jazeera Learning — graded listening",
         "https://learning.aljazeera.net/en/tolearnarabic", "course", None, False, 200),
    ],
    "root": [
        ("The root system — overview",
         "https://arabic.desert-sky.net/g_roots.html", "article", 18, False, 200),
        ("Grammar drills: roots & patterns",
         "https://allthearabicyouneverlearnedthefirsttimearound.com/p1/p1-ch2/roots-and-patterns/", "practice", 40, False, 200),
    ],
    "past": [
        ("Past tense & narration — lesson",
         "https://www.arabicpod101.com/lesson/beginner-s3-4-past-tense", "video", 16, False, 200),
        ("Narrate your day — guided practice",
         "https://www.italki.com/en/community/exercise", "practice", 20, False, 200),
    ],
    "levant": [
        ("Levantine crash course — first 10 phrases",
         "https://www.youtube.com/watch?v=2rDzUtUYo4Y", "video", 22, False, 200),
        ("Shami dialect notes",
         "https://www.livingarabic.com/levantine-dictionary", "article", None, False, 200),
    ],
    "conv": [
        ("italki — book a 15-minute tutor call",
         "https://www.italki.com/en/teachers/arabic", "course", 15, True, 200),
        ("Self-recording rubric: the 5-minute talk",
         "https://www.fluentin3months.com/speak-from-day-one/", "article", 8, False, 200),
    ],
}

# Gentler resources the replanner attached to the split steps, one per step.
ROOT_SPLIT_RESOURCES = [
    ("Arabic roots explained visually — 5 common roots",
     "https://www.youtube.com/watch?v=9Zv7rUxxCMA", "video", 12, False, 200),
    ("One pattern: فاعل (the doer) — short lesson",
     "https://arabic.fi/grammar/faail-pattern", "video", 8, False, 200),
    ("Map 10 familiar words to their roots — worksheet",
     "https://www.arabicworksheets.com/roots-mapping", "practice", 15, False, 200),
]

# --- Go for Backend ---------------------------------------------------------
# (title, est_sessions, resource_title, resource_url, kind) — 30-minute sessions
GO_MODULES = [
    ("Go Syntax & Tooling", 4, "A Tour of Go", "https://go.dev/tour/welcome/1", "course"),
    ("Types, Structs & Methods", 4, "Go by Example: Structs", "https://gobyexample.com/structs", "practice"),
    ("Slices, Maps & Strings", 4, "Go Slices: usage and internals", "https://go.dev/blog/slices-intro", "article"),
    ("Errors & Panics", 3, "Error handling and Go", "https://go.dev/blog/error-handling-and-go", "article"),
    ("Interfaces in Practice", 4, "Effective Go — interfaces", "https://go.dev/doc/effective_go#interfaces", "article"),
    ("Testing & Benchmarks", 3, "The testing package", "https://pkg.go.dev/testing", "article"),
    ("Goroutines & Channels", 5, "A Tour of Go — Concurrency", "https://go.dev/tour/concurrency/1", "course"),
    ("Concurrency Patterns", 4, "Go by Example: Worker Pools", "https://gobyexample.com/worker-pools", "practice"),
    ("HTTP Servers & Routing", 5, "Writing web applications", "https://go.dev/doc/articles/wiki/", "article"),
    ("JSON APIs & Middleware", 4, "Making and using HTTP middleware", "https://www.alexedwards.net/blog/making-and-using-middleware", "article"),
    ("PostgreSQL with database/sql", 5, "Go database/sql tutorial", "http://go-database-sql.org/", "course"),
    ("Migrations & Transactions", 4, "golang-migrate — getting started", "https://github.com/golang-migrate/migrate", "article"),
    ("Auth, Sessions & JWT", 5, "JWT authentication in Go", "https://www.sohamkamani.com/golang/jwt-authentication/", "article"),
    ("Configuration & Logging", 3, "Structured logging with slog", "https://go.dev/blog/slog", "article"),
    ("Docker for Go Services", 4, "Build your Go image", "https://docs.docker.com/language/golang/build-images/", "article"),
    ("CI & Deployment", 4, "GitHub Actions for Go projects", "https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-go", "article"),
    ("Observability: Metrics & Tracing", 4, "Instrumenting a Go application", "https://prometheus.io/docs/guides/go-application/", "article"),
    ("Caching & Message Queues", 5, "Go and Redis — getting started", "https://redis.io/docs/latest/develop/clients/go/", "article"),
    ("System Design for APIs", 5, "The System Design Primer", "https://github.com/donnemartin/system-design-primer", "article"),
    ("Capstone: Ship a Production API", 6, "The Twelve-Factor App", "https://12factor.net/", "article"),
]

GO_DONE_SESSIONS = [4, 4, 4, 3, 4, 3, 2]  # GO-01..GO-06 complete, GO-07 started


def _mk_resource(module, spec, verified_at):
    title, url, kind, duration, paid, status = spec
    return Resource(
        module_id=module.id,
        title=title,
        url=url,
        url_hash=url_hash(url),
        kind=kind,
        source_domain=domain_of(url),
        duration_min=duration,
        is_paid=paid,
        http_status=status,
        verified_at=verified_at if status else None,
        relevance=0.9,
    )


def _steps_done(*triples):
    return [{"key": k, "label": l, "status": "done", "detail": d} for k, l, d in triples]


def _assert_states(sa, roadmap_id, expected):
    rows = sa.execute(select(Module).where(Module.roadmap_id == roadmap_id)).scalars()
    actual = {m.title: m.state for m in rows}
    drift = {t: (s, actual[t]) for t, s in expected.items() if actual.get(t) != s}
    if drift:
        raise RuntimeError(f"seed fixture drifted from the design: {drift}")


def _seed_arabic(sa, today: date) -> Roadmap:
    created = datetime.combine(today - timedelta(days=35), time(20, 11))
    rm = Roadmap(
        topic="Learn Arabic",
        goal="Modern Standard → Levantine",
        level="beginner",
        color=ACCENT,
        status="ready",
        minutes_per_day=40,
        weekdays="1,2,3,4,5",
        created_at=created,
    )
    sa.add(rm)
    sa.flush()

    mods = {}
    for key, title, native, summary, est in ARABIC_MODULES:
        m = Module(
            roadmap_id=rm.id, title=title, title_native=native, summary=summary,
            est_sessions=est, est_minutes=est * rm.minutes_per_day,
        )
        sa.add(m)
        mods[key] = m
    sa.flush()

    for prereq, dep in ARABIC_DEPS:
        sa.add(ModuleDep(module_id=mods[dep].id, prereq_module_id=mods[prereq].id))

    # Codes follow topological order: AR-01 … AR-10.
    prefix = code_prefix(rm.topic)
    ids = [mods[k].id for k, *_ in ARABIC_MODULES]
    edges = [(mods[a].id, mods[b].id) for a, b in ARABIC_DEPS]
    by_id = {m.id: m for m in mods.values()}
    for i, mid in enumerate(topo_sort(ids, edges), start=1):
        by_id[mid].code = f"{prefix}-{i:02d}"

    # Root & Pattern System was split 3 days ago: three gentler submodules,
    # wired root's prerequisites -> step 1 -> step 2 -> step 3.
    root = mods["root"]
    subs = []
    for j, title in enumerate(ROOT_SPLIT, start=1):
        s = Module(
            roadmap_id=rm.id, parent_module_id=root.id, title=title,
            code=f"{root.code}.{j}", est_sessions=2, est_minutes=2 * rm.minutes_per_day,
        )
        sa.add(s)
        subs.append(s)
    sa.flush()
    sa.add(ModuleDep(module_id=subs[0].id, prereq_module_id=mods["verbs"].id))
    sa.add(ModuleDep(module_id=subs[0].id, prereq_module_id=mods["nominal"].id))
    sa.add(ModuleDep(module_id=subs[1].id, prereq_module_id=subs[0].id))
    sa.add(ModuleDep(module_id=subs[2].id, prereq_module_id=subs[1].id))

    # Resources. Core's set matches the design popover; core links were
    # re-verified two days ago, the rest at build time.
    build_check = created + timedelta(minutes=1)
    recheck = datetime.combine(today - timedelta(days=2), time(7, 30))
    for key, specs in ARABIC_RESOURCES.items():
        when = recheck if key == "core" else build_check
        for spec in specs:
            sa.add(_mk_resource(mods[key], spec, when))
    replan_check = datetime.combine(today - timedelta(days=3), time(21, 4))
    for s, spec in zip(subs, ROOT_SPLIT_RESOURCES):
        sa.add(_mk_resource(s, spec, replan_check))

    # History: a daily streak of done sessions ending yesterday —
    # script (12), then read (8), then core (5). 40 minutes each.
    history = [mods["script"]] * 12 + [mods["read"]] * 8 + [mods["core"]] * 5
    start_day = today - timedelta(days=len(history))
    for i, m in enumerate(history):
        d = start_day + timedelta(days=i)
        sa.add(StudySession(
            module_id=m.id, planned_date=d, planned_minutes=40, actual_minutes=40,
            status="done",
            started_at=datetime.combine(d, time(19, 0)),
            completed_at=datetime.combine(d, time(19, 40)),
        ))

    # The stuck marker: poked at Root & Pattern three days ago and bailed.
    stuck_day = today - timedelta(days=3)
    sa.add(StudySession(
        module_id=root.id, planned_date=stuck_day, planned_minutes=40,
        actual_minutes=25, status="stuck",
        started_at=datetime.combine(stuck_day, time(20, 15)),
        note="Patterns feel abstract — I can't see the system yet.",
    ))
    root.state = "stuck"  # sticky until its split steps are completed

    # Today: the two Core 300 Words rows from the design.
    sa.add(StudySession(
        module_id=mods["core"].id, planned_date=today, planned_minutes=25,
        status="planned", note="Mastering Arabic 1 — Chapter 4, pp. 48–61",
    ))
    sa.add(StudySession(
        module_id=mods["core"].id, planned_date=today, planned_minutes=15,
        status="planned", note="Anki — Core 300 deck, cards 121–160",
    ))
    sa.flush()

    recompute_roadmap(sa, rm)
    target = schedule_roadmap(sa, rm, start=today + timedelta(days=1))

    run = AgentRun(
        roadmap_id=rm.id, kind="generate", status="done",
        started_at=created, finished_at=created + timedelta(seconds=47),
        steps=_steps_done(
            ("plan", "Plan the roadmap", "10 modules · 11 prerequisites"),
            ("validate", "Validate the graph", "no cycles · 1 root · 1 capstone"),
            ("sourcing", "Source resources", "12 queries · 41 found"),
            ("verify", "Verify links", "34 alive · 5 dead"),
            ("schedule", "Schedule sessions", f"ready by {month_day(target)}"),
        ),
    )
    replanned_at = datetime.combine(today - timedelta(days=3), time(21, 3))
    replan = AgentRun(
        roadmap_id=rm.id, kind="replan", status="done",
        started_at=replanned_at, finished_at=replanned_at + timedelta(seconds=31),
        steps=_steps_done(
            ("diagnose", "Diagnose the block", "stuck 3 days · grammar-heavy module"),
            ("split", "Split the module", "3 smaller steps"),
            ("sourcing", "Source gentler resources", "4 queries · 9 found"),
            ("verify", "Verify links", "7 alive · 2 dead"),
            ("schedule", "Reschedule the plan", "re-opens after 2 prerequisite sessions"),
        ),
    )
    sa.add_all([run, replan])

    sa.add_all([
        Insight(
            roadmap_id=rm.id, kind="replan",
            text="Split into 3 smaller steps and swapped the grammar drills for a "
                 "gentler resource. Two prerequisite sessions were slotted in before "
                 "it re-opens.",
            action_kind=None,
            payload={"module_id": root.id, "steps": ROOT_SPLIT},
            created_at=replanned_at,
        ),
        Insight(
            roadmap_id=rm.id, kind="format",
            text="Audio sessions get finished about twice as often as reading here. "
                 "New modules now lead with podcasts and video.",
            action_kind="prefer_format",
            payload={"format": "audio", "action_label": "Prefer audio in new modules"},
            created_at=datetime.combine(today - timedelta(days=8), time(7, 2)),
        ),
        Insight(
            roadmap_id=rm.id, kind="pace",
            text="Morning sessions finish 9 times out of 10; late-evening ones about "
                 "half the time. Shifting the daily slot earlier would protect the streak.",
            action_kind="shift_slot",
            payload={"action_label": "Shift sessions earlier"},
            created_at=datetime.combine(today - timedelta(days=14), time(7, 5)),
        ),
    ])

    _assert_states(sa, rm.id, {
        "Arabic Script & Sounds": "completed",
        "Reading Voweled Text": "completed",
        "Core 300 Words": "inprogress",
        "Present-Tense Verbs": "available",
        "Nominal Sentences": "available",
        "Listening: Slow MSA": "available",
        "Root & Pattern System": "stuck",
        "Past Tense & Narration": "locked",
        "Levantine Dialect Basics": "locked",
        "Hold a 5-Minute Conversation": "locked",
    })
    return rm


def _seed_go(sa, today: date) -> Roadmap:
    created = datetime.combine(today - timedelta(days=45), time(9, 40))
    rm = Roadmap(
        topic="Go for Backend",
        goal="Job-ready backend development",
        level="intermediate",
        color=NEUTRAL,
        status="ready",
        minutes_per_day=30,
        weekdays="1,2,3,4,5",
        created_at=created,
    )
    sa.add(rm)
    sa.flush()

    prefix = code_prefix(rm.topic)
    mods = []
    for i, (title, est, *_res) in enumerate(GO_MODULES, start=1):
        m = Module(
            roadmap_id=rm.id, code=f"{prefix}-{i:02d}", title=title,
            summary=None, est_sessions=est, est_minutes=est * rm.minutes_per_day,
        )
        sa.add(m)
        mods.append(m)
    sa.flush()
    for a, b in zip(mods, mods[1:]):  # a linear chain: one root, one capstone
        sa.add(ModuleDep(module_id=b.id, prereq_module_id=a.id))

    build_check = created + timedelta(minutes=1)
    for m, (_t, _e, res_title, res_url, res_kind) in zip(mods, GO_MODULES):
        sa.add(_mk_resource(m, (res_title, res_url, res_kind, None, False, 200), build_check))
    sa.add(_mk_resource(
        mods[6],
        ("Concurrency is not parallelism — Rob Pike",
         "https://www.youtube.com/watch?v=oV9rvDllKEg", "video", 31, False, 200),
        build_check,
    ))
    sa.add(_mk_resource(
        mods[7],
        ("Go Concurrency Patterns — Google I/O talk",
         "https://www.youtube.com/watch?v=f6kdp27TYZs", "video", 51, False, 200),
        build_check,
    ))

    # History: weekday sessions ending 6 days ago, then silence (the stuck story).
    history: list[Module] = []
    for m, n in zip(mods, GO_DONE_SESSIONS):
        history.extend([m] * n)
    days: list[date] = []
    d = today - timedelta(days=6)
    while len(days) < len(history):
        if d.isoweekday() <= 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    for d, m in zip(days, history):
        sa.add(StudySession(
            module_id=m.id, planned_date=d, planned_minutes=30, actual_minutes=30,
            status="done",
            started_at=datetime.combine(d, time(8, 0)),
            completed_at=datetime.combine(d, time(8, 30)),
        ))

    # Stuck on Concurrency Patterns the same evening the streak stopped.
    stuck_day = today - timedelta(days=6)
    go8 = mods[7]
    sa.add(StudySession(
        module_id=go8.id, planned_date=stuck_day, planned_minutes=30,
        actual_minutes=35, status="stuck",
        started_at=datetime.combine(stuck_day, time(20, 40)),
        note="Deadlocks everywhere — worker pools aren't clicking.",
    ))
    go8.state = "stuck"

    # Today's row from the design: GO-07, 30 min.
    sa.add(StudySession(
        module_id=mods[6].id, planned_date=today, planned_minutes=30,
        status="planned", note="Goroutines & channels: the basics",
    ))
    sa.flush()

    recompute_roadmap(sa, rm)
    target = schedule_roadmap(sa, rm, start=today + timedelta(days=1))

    sa.add(AgentRun(
        roadmap_id=rm.id, kind="generate", status="done",
        started_at=created, finished_at=created + timedelta(seconds=52),
        steps=_steps_done(
            ("plan", "Plan the roadmap", "20 modules · 19 prerequisites"),
            ("validate", "Validate the graph", "no cycles · 1 root · 1 capstone"),
            ("sourcing", "Source resources", "14 queries · 52 found"),
            ("verify", "Verify links", "44 alive · 8 dead"),
            ("schedule", "Schedule sessions", f"ready by {month_day(target)}"),
        ),
    ))
    sa.add(Insight(
        roadmap_id=rm.id, kind="stuck",
        text="Concurrency Patterns has been stuck for 6 days. Splitting it into "
             "smaller steps usually reopens a module within 2–3 days.",
        action_kind="split_module",
        payload={"module_id": go8.id, "action_label": "Split into smaller steps"},
        created_at=datetime.combine(today - timedelta(days=3), time(7, 0)),
    ))

    expected = {title: "completed" for title, *_ in GO_MODULES[:6]}
    expected["Goroutines & Channels"] = "inprogress"
    expected["Concurrency Patterns"] = "stuck"
    expected.update({title: "locked" for title, *_ in GO_MODULES[8:]})
    _assert_states(sa, rm.id, expected)
    return rm


def seed(reset: bool = True) -> None:
    if reset:
        Base.metadata.drop_all(bind=db.engine)
    Base.metadata.create_all(bind=db.engine)

    sa = db_session
    if sa.execute(select(func.count(Roadmap.id))).scalar():
        print("Database already has data — run with reset to rebuild.")
        return

    today = date.today()
    arabic = _seed_arabic(sa, today)
    go = _seed_go(sa, today)
    sa.commit()
    print(
        f"Seeded roadmap {arabic.id} “{arabic.topic}” (10 modules + 3 split steps, "
        f"finish {arabic.target_date}) and roadmap {go.id} “{go.topic}” "
        f"(20 modules, finish {go.target_date})."
    )
