# Oráculo — Universidad del Rosario

Personalized academic planner. Two parts live here:

1. **`index.html`** (repo root) — the original polished planner *demo* (scheduler with
   weekly calendar, conflict detection, profile). Client-only; risk numbers were mocked.
2. **`oraculo/`** — the real **risk + difficulty engine** built on the institutional panel.
   This is the active work. It parses a student's transcript, then predicts per-course
   **difficulty**, **expected grade**, and **fail probability**, and projects a planned
   semester's GPA + workload.

Default copy language is **Spanish**. Brand: white background, Rosario burgundy `#7A1F25`
+ slate, Inter typography. Sober/institutional — no dark/gold/serif. Frame data gaps as
visible empty states, not errors.

## Run the engine
```
cd oraculo
python app/server.py            # -> http://localhost:8000  (stdlib http.server, no deps)
python pipeline/run_all.py      # rebuild all model artifacts from the source panel
pip install -r requirements.txt # numpy pandas scikit-learn openpyxl joblib pypdf
```
The server loads only `model/*.json` + `model/*.joblib`; it does NOT need the panel/cache.

## Static build (`docs/`, deploys to GitHub Pages — no backend)
The whole app also runs **client-side**: `docs/oraculo.js` is a verified JS port of
`engine.py` + `scheduler.py` (HistGBM models exported to JSON via
`pipeline/export_web_models.py` + a JS tree-evaluator; PDF parsed in-browser with pdf.js
from CDN). `docs/index.html` loads `data/*.json` and calls `Oraculo.parseTranscript/eligible/
simulate` instead of the Python API. Rebuild data: re-run `export_web_models.py` and copy
`model/{catalog,course_stats,plans,schedules}.json` into `docs/data/`. Verified equal to the
Python engine (counts/grades/GPA/scheduler exact; risk within 2e-4) and the pdf.js parser
matches Python on all 5 test transcripts (Node + headless-Chrome tested). Asset paths are
relative so it works under a `/repo/` Pages subpath. Pages source = branch `main`, `/docs`.

## Layout
```
oraculo/
  app/
    engine.py        # inference: transcript parse, eligibility, difficulty, simulate
    scheduler.py     # schedule conflict solver (backtracking CSP over section time-slots)
    server.py        # stdlib JSON server: POST /api/analyze, POST /api/simulate (+schedule)
    static/index.html# difficulty-first UI (Disponibles/Electivas/Cursadas tabs, planner+calendar)
  pipeline/          # offline model build (run in this order; run_all.py does it)
    scrape_schedules.py  # (network) per-section horarios -> model/schedules.json (--sample to demo)
    scrape_catalog.py    # 0. (network, optional) scrape official course names ->
    #                          data/url_catalog.json — all 54 pregrado plans, 1288 codes
    build_and_train.py   # 1. fail classifier (HistGBM) -> model.joblib, course_stats.json
    build_difficulty.py  # 2. grade regressor + difficulty stars -> grade_model.joblib
    build_catalog.py     # 3. names/credits/prereqs (url_catalog + data/Cursos) -> catalog.json
    build_plans.py       # 4. per-program core/elective/typ_sem from panel -> plans.json
    experiments/         # exp_load_effect.py, exp_subject_aptitude.py (analysis, not shipped)
  model/             # build outputs the app loads (json + joblib)
  cache/             # panel.pkl — 92 MB intermediate, gitignored, rebuilt from .xlsx
```

## Data sources
- **Panel (training):** `~/Downloads/Syndp_VW_ORACULO_PANEL_EN.xlsx` — ~953k synthetic,
  pseudonymized enrollments (headerless `VW_ORACULO_PANEL_EN`). Columns by index in
  `build_and_train.NEEDED`. Course code = **`col1`** (8-digit `ID_Asignatura`).
- **Transcript (runtime):** Historia Académica PDF (UXXI). `engine.parse_transcript` is
  **layout-aware (pdfplumber)**: it reconstructs table rows from word x/y coords (code @
  x≈18, grade @ x≈266, credits @ 414/456) — robust to the column-shuffled text layer and
  the "SOLO INFORMATIVO" watermark. Plan is detected by **course overlap** with the official
  plans (picks the right version, e.g. PS04 vs PS03), not header text.
- **`data/Cursos/*.txt`:** JSON course catalogs (code→name→credits). ONLY 2 of 8 schools
  populated (Administración, Ciencias e Ingeniería) — see limitations.

**The join that makes it work:** the 8-digit course code is identical across panel ↔
transcript ↔ catalog. No cross-reference table needed.

## Models (temporal holdout, train < 2025-2S)
- Fail classifier — calibrated HistGBM, **AUC ~0.92**, well-calibrated.
- Grade regressor — HistGBM, **MAE 0.35** on 0–5 (beats course-mean & GPA-only baselines).
- Difficulty stars — from the grade distribution, ranked **within the student's major**.
- Features include subject-specific **`area_gpa`** (same code-prefix), which is as
  predictive as overall GPA — within a fixed GPA, in-area history swings fail rate ~10×.

## Key design decisions (don't silently undo these)
- **No data-driven load penalty.** Within-student, course load has ~no effect on GPA in
  this data (slope +0.002/credit). The naive between-student "heavy load = worse" is pure
  selection bias. So predicted GPA is NOT inflated by a load curve; semester workload is an
  explicit *convex effort* model + a feasibility guard (>24 cr / >7 courses flagged).
- **Prereqs hard-gate only on reliable signals:** the MACC official malla (`build_catalog`)
  + numbered name-sequences (Cálculo 1→2→3, Estadística I→II). Precedence inference from
  the panel OVER-GENERATES (tags every semester-1 course as a Calc-2 prereq) — do not gate
  on it. `typ_sem` gives soft ordering elsewhere.
- Fail probability is secondary; **difficulty + expected grade + projected GPA** lead,
  because strong students don't fail — they want effort/GPA impact.

## Course names — RESOLVED via scrape (`pipeline/scrape_catalog.py`)
The Rosario academic guide (guiaacademica.urosario.edu.co) is a SPA over a public Spring
API on `https://guiaacademicabackend.azurewebsites.net/api`. Auth = a public JWT
(`tokenApiPublic`) embedded in the JS bundle; the scraper self-refreshes it from the live
bundle. Key endpoints (Bearer token):
- `GET /facultades?tipo=PSC` — faculties
- `GET /planes?tipo=PSC` — all 54 pregrado plans (`codPlan`, `nombrePlan`)
- `GET /asignaturas2?tipo=PSC&tipoElectiva=PLAN&planEstudio=<codPlan>` — a plan's courses
  (`codAsignatura, nombre, creditos`) — same shape as the legacy `data/Cursos/*.txt`.
- `GET /asignaturas2?tipo=PSC&tipoElectiva=GEN` (and `=HM`) — university-wide elective pools.

## Schedule data — API mapped, times publish ~July (`pipeline/scrape_schedules.py`)
Per-section class times come from a 3-call chain (Bearer `tokenApiPublic`):
`asignaturaDetalle?codigo=C&opcionDetalle=DetalleActividad&planEstudio=P` → actividades
(+`codActividad`) → `&opcionDetalle=DetalleGrupo&codActividad=A` → grupos (codGrupo, grupo#,
modalidad) → `&opcionDetalle=DetalleHorario&codActividad=A` → día/hora/profesor/sede/aula.
**As of 2026-06 the offering rolled to 2026-2S (Jul 27–Nov 28) with `horarios: null`** — next
term's timetables aren't loaded yet (DetalleHorario 500s; verified 0/20 courses have times).
So `schedules.json` is currently filled with `--sample` representative slots (clearly flagged
`is_sample`); rerun the scraper without `--sample` once the term publishes to get real times.
`scheduler.solve(codes)` is the conflict CSP (one section per course, no slot overlap, via
backtracking); it reports the blocking pair when infeasible. Wired into `/api/simulate`.
- (`/agrupaciones` 500s for the public token — the semester/tipology structure isn't
  reachable; we get the flat plan + pool course lists, enough for names + name-sequences.)
The scrape yields **1545 named current codes** (54 plans + GEN + HM pools) → names render for
every program and name-sequence prereqs (X I→II) fire everywhere. Re-run to refresh.

## Eligibility — official plan + CANONICAL-NAME matching (panel codes NOT used for lists)
The same course has DIFFERENT 8-digit codes across plan versions (e.g. Cálculo 3 is
`11320003` in a transcript but other codes appear in the panel). So lists are built from the
**official scraped plan only**, and course identity = **canonical normalized name**
(`engine._canon`), not code. Key functions: `_passed_identity` (passed codes + their names),
`_is_passed(code)` = code-match OR name-match → a course you took under any code is filtered
out; plans are deduped by name (e.g. two Capstone entries → one).
- **Disponibles** = `plan_courses[codPlan]` (deduped by name) minus passed minus prereq-locked.
- **Locked** = plan courses whose known prereqs aren't met (prereqs also name-matched).
- **Electivas** = the official GEN/HM pools (`catalog` `pool` field, ~1000), deduped vs plan
  & passed; capped to 200 A–Z in the response (`n_electives_total` has the real count).
- **Cursadas** = parsed transcript (grades; `in_plan` flag by name).
Do NOT reintroduce panel-derived (`plans.json`) codes into the lists — that was the bug that
showed already-passed Cálculo 3 / Lógica CC as electives (old-version duplicate codes).
`plans.json` is still used for `typ_sem` ordering only.

## Prerequisites — what's reliable and what isn't
Hard-gated on: MACC official malla + **name-sequences** (Cálculo 1→2→3, Estadística I→II,
Derecho Internacional Público I→II…) which now fire for all programs (names complete).
NOT available: the full malla/prereq graph. The API `/agrupaciones` (semester structure)
and `/asignaturaDetalle` (prereqs) need student auth — public token gets 500/null. The
`Planes de Estudio/*.pdf` mallas are **graphics**: 0 course codes, prereq arrows aren't in
the text layer — not parseable. Courses with no known prereq are shown as available (no
false locks), which is the safe default.
- **Grade parsing is best-effort:** code↔grade alignment from the column-shuffled PDF text
  breaks on ~1 in 5 files; needs layout-aware extraction (pdfplumber, not installed). When
  it fails, `area_gpa` falls back to overall GPA (model handles NaN).
- **Professor signal unusable** — constant hash in the panel (`col3`).
- **Low-n / seminar courses** give shaky grade predictions (flagged via `confidence`);
  recommended fix = shrink predictions toward `area_gpa` for low-n courses.

## Related docs
- `Oraculo-Solicitud-Panel.tex/.pdf` — the formal data-access request to the institution.
- Background/decisions also captured in `.claude/.../memory/project_oraculo*.md`.
