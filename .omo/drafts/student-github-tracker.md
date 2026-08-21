# student-github-tracker - Planning Draft

> Durable resume point for the ulw-plan session. Intent, decisions, and the
> approval gate are recorded here so a later turn resumes from these fields,
> not from memory.

## Intent
- `intent: clear` — concrete feature set: spreadsheet imports, GitHub sync,
  fully automatic AI scoring (volume/quality/match/schedule) with NO teacher
  review step, teacher-configurable weights, automatic daily encouraging email,
  LLM failure retry/defer, **developed via spec-coding (SDD + TDD)**, all docs
  in Chinese.
- `review_required: false` — no explicit high-accuracy modifier requested;
  CLEAR route => dual high-accuracy review is optional, offered at delivery.

## Classification
- Architecture-scale (new project, 9 components, long-term shape). CLEAR route
  => mandatory high-accuracy review NOT triggered.

## Decisions (owner-decisions + adopted defaults)
| # | Fork | Chosen | Why / evidence |
|---|------|--------|----------------|
| D1 | GitHub usage | **Live GitHub API** | User chose. Fetch per-repo activity per day. Needs `GITHUB_TOKEN` in `.env`. |
| D2 | App form | **Local web app** | User chose. Single admin, runs on teacher's machine. |
| D3 | Storage | **Database (SQLite)** | User chose. System of record; import/export are I/O edges. |
| D4 | Language | **Python (FastAPI)** | User chose. |
| D5 | Frontend (default) | **Jinja2 + HTMX, no build step** | Reversible internal default. Python-only toolchain for a local single-admin tool. |
| D6 | Auth (default) | **Optional `ADMIN_PASSWORD`** | Reversible default. Unset => open on localhost; set => simple login. |
| D7 | Test strategy | **TDD: pytest, write failing test (RED) before code (GREEN); GitHub + LLM + SMTP mocked** | Per spec-coding convention; agent-executed QA always included; fixture xlsx + simulated LLM failures for retry. |
| D8 | xlsx engine | **pandas + openpyxl** | Standard Python xlsx read/write. |
| D9 | Import headers | **Alias map: Chinese + English** | Serves a Chinese-speaking teacher (`学生姓名`/`student_name`, `GitHub仓库`/`github_repo`, `邮箱`/`email`, etc.). |
| D10 | GitHub metrics (base) | **commits (count+list+diffs), PRs opened/merged** | Fed to AI scoring as context. |
| D11 | DailyPlan granularity | **per project per date; `student_id` nullable** | Null = whole project that day; set = assigned to a student. |
| D12 | Code volume metric | **LOC = additions + deletions per day** | From GitHub commit stats. Captured into the activity snapshot. |
| D13 | Quality metric | **AI auto-generated; fully automatic (failure policy D22)** | LLM judges code quality from diffs/commits/PRs. |
| D14 | Task-match metric | **AI auto-generated; fully automatic (failure policy D22)** | LLM compares commits/PRs against the daily-plan text. |
| D15 | Schedule / completion | **AI auto-determines plan completion + ahead/behind (failure policy D22)** | LLM sets completion + schedule status; config drives bonus/penalty. |
| D16 | Teacher scoring options | **scoring config: weights w1/w2/w3, LOC threshold, schedule bonus/penalty amounts** | Set-up-time config in `ScoringConfig` table (editable UI); not per-day review. |
| D17 | Email delivery | **smtplib + teacher SMTP config in `.env`; student `email` required** | Sent automatically after AI evaluation; no teacher trigger. |
| D18 | Comment (评语) | **AI auto-generates four-part encouraging comment; auto-sent, no teacher edit** | LLM draft MUST contain: (1) encouraging opening (premise, tone stays encouraging), (2) today's achievements, (3) today's problems/shortcomings, (4) concrete improvement suggestions. |
| D19 | Documentation language | **All saved documents in Chinese** | Plan file, `AGENTS.md`, `README.md`, and the spec-coding `SPEC.md`/`PLAN.md`/`AGENT.md` in Chinese; UI labels and emails already Chinese. |
| D20 | LLM provider | **OpenAI-compatible API, configurable; recommended default Volcengine Ark (Doubao)** | `.env`: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Provider-agnostic. |
| D21 | Run trigger | **one-click "今日评测" runs sync→AI→email automatically; optional `AUTO_RUN_TIME` for scheduled daily run** | No review gate. Teacher sets up once, then daily run is one click or scheduled. |
| D22 | LLM failure policy | **auto-retry: short backoff up to 3 immediate attempts; if still failing, persist the evaluation data (context saved) with status=failed + `next_retry_at = now+2h`; a background reaper retries due items, looping the same policy** | No human gate. Failed-then-deferred items retried 2h later automatically; never silently dropped. |
| D23 | Dev methodology | **Spec-coding: SDD + TDD (aligned with /data/disk/spec-coding convention)** | Project ships its own `SPEC.md` (GWT scenarios + per-iter interface contract + acceptance table), `PLAN.md` (Iter 0 foundation, then Iters each = SPEC→RED→GREEN), `AGENT.md` (Python naming + layering config→utils→models→services→api→app + prohibitions + iter rules). TDD: failing test before code; gate next Iter on all-green; 1-3 files per Iter. All in Chinese (D19). |
| D24 | Date window timezone | **teacher-local timezone, default `Asia/Shanghai`; convert to UTC for GitHub queries** | "当天" is teacher-local; GitHub `since`/`until` are UTC. Store/compare in configured TZ, query GitHub in UTC. |
| D25 | Student-project membership & Assessment key | **DailyPlan applies to ALL students when `student_id` is null, else only that student; Assessment keyed `(student_id, project_id, date)`; email aggregates per student per day** | No separate enrollment model. For each student+date, score against every plan that day matching them; one email per student/day sums all their project assessments. |
| D26 | LLM context budget | **truncate/summarize diffs exceeding `LLM_CONTEXT_MAX_CHARS` (default ~12000) before sending** | Avoid blowing LLM context / cost on huge commit days; preserve commit messages + totals. |

## Components ledger (topology lock)
| id | component | one-line outcome | status | evidence |
|----|-----------|------------------|--------|----------|
| C1 | Data model + DB | SQLModel models + SQLite: Student(+email), Project, DailyPlan, GithubActivity, PlanCompletion, ScoringConfig, **Assessment (status/attempts/next_retry_at/saved_context_json)** | planned | D3,D4,D9,D11,D12,D15,D16,D22 |
| C2 | Spreadsheet I/O | Import students(+email)/projects/plans from xlsx; export daily score+comment xlsx | planned | D8,D9 |
| C3 | GitHub integration | PyGithub wrapper: commits+PRs+LOC+diffs per repo per date -> snapshot | planned | D1,D10,D12 |
| C4 | Web UI/API | FastAPI routes + Jinja2/HTMX: dashboard, lists, config, results view, export, "今日评测" button | planned | D2,D5,D21 |
| C5 | Automated scoring pipeline | GitHub sync -> AI scoring -> scoring engine -> Assessment persisted -> trigger email. NO teacher review; results read-only. | planned | D13,D14,D15,D18,D21 |
| C6 | Config & bootstrap | `.env`/`.env.example` (GITHUB_TOKEN, LLM_*, SMTP_*, ADMIN_PASSWORD, AUTO_RUN_TIME), venv+requirements, seed sample xlsx, run cmd | planned | D6,D17,D20,D21 |
| C7 | Scoring engine | Apply `ScoringConfig` weights + schedule adjustment to AI sub-scores; pure function, TDD. | planned | D13,D14,D15,D16 |
| C8 | Email delivery | Auto-send daily comment per student after AI evaluation; encouraging template; SMTP with retry | planned | D17,D18 |
| C9 | AI scoring service + retry | Call OpenAI-compatible LLM (structured JSON). Retry per D22: 3 immediate w/ backoff, then persist + defer 2h; background reaper retries due items | planned | D13,D14,D15,D18,D20,D22 |
| C10 | Spec-coding docs | Project `SPEC.md` / `PLAN.md` / `AGENT.md` (Chinese) defining scenarios, iterations, layering & prohibitions | planned | D19,D23 |

## Approach (to be planned in detail after approval)
FastAPI + SQLite local web app, built with the **spec-coding method (SDD + TDD)**.
Three spreadsheet imports and one-time config (GitHub token, LLM key, SMTP,
weights) are the only teacher setup. A single "今日评测" action (or scheduled
`AUTO_RUN_TIME`) runs the whole pipeline with no human review: GitHub sync
snapshots each student's repo activity for the day (commits/PRs/LOC/diffs); the
AI scoring service reads the day's plan + GitHub context and automatically
produces quality, task-match, plan-completion, schedule status, and a four-part
encouraging comment; the scoring engine computes the final score from configured
weights plus schedule bonus/penalty; the result is persisted and an encouraging
email is sent to each student automatically. LLM failures retry 3x then persist
+ defer 2h (D22). Export produces the daily score+comment xlsx. UI is
server-rendered Jinja2 + HTMX (read-only results).

**Development flow (D23):** ship `SPEC.md` (Given/When/Then scenarios + per-iter
interface contract + acceptance table), `PLAN.md` (Iter 0 = engineering
foundation with no code: SPEC/PLAN/AGENT + scaffold; then Iters each following
SPEC → RED (failing pytest) → GREEN (implementation) → verify all-green), and
`AGENT.md` (Python naming: snake_case functions/vars, PascalCase classes,
kebab-case dirs; layering config→utils→models→services→api→app; prohibitions
such as no swallowed exceptions, secrets only from `.env`; iter rule: previous
Iter must be all-green before the next, 1-3 files per Iter). All docs in Chinese.

## Approval gate
- `status: approved` (user replied "批准" then chose A: start execution)
- Plan written: `.omo/plans/student-github-tracker.md` (template-compliant; 20 impl todos + 4 final-verifier rows; manual gap pass added D24-D26).
- Mandated dual high-accuracy review (momus + Oracle) COULD NOT run: this environment has no subagent API access ("Cannot connect to API"). Manual gap analysis substituted. User accepted plan as-is (chose A).
- Next workflow action: execution belongs to a SEPARATE worker session (e.g. `/start-work`); the planner does NOT implement. Worker starts at Iter 0 and follows SDD+TDD per the plan.
- Approvals so far: explicit user approval granted.
