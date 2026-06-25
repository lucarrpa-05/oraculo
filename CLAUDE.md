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
    scrape_schedules.py  # (network) real 2026-2S horarios per (plan,course) -> model/schedules.json (plan-keyed)
    scrape_catalog.py    # 0. (network, optional) scrape official course names ->
    #                          data/url_catalog.json — all 54 pregrado plans, 1288 codes
    build_and_train.py   # 1. fail classifier (HistGBM) -> model.joblib, course_stats.json
    build_difficulty.py  # 2. grade regressor + difficulty stars -> grade_model.joblib
    build_catalog.py     # 3. names/credits/prereqs (url_catalog + data/Cursos) -> catalog.json
    build_plans.py       # 4. per-program core/elective/typ_sem from panel -> plans.json
    build_hospitals.py   # 5. Medicina (ME03) clinical SITES from plan name suffixes ->
    #                          model/hospitals.json (+seeds empty model/hospital_reviews.json)
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

## Schedule data — REAL 2026-2S, PLAN-SPECIFIC (`pipeline/scrape_schedules.py`)
Per-section class times come from a 4-call chain (Bearer `tokenApiPublic`):
`asignaturaDetalle?codigo=C&opcionDetalle=DetalleActividad&planEstudio=P` → actividades
(+`codActividad`) → `&opcionDetalle=DetalleFecha&codActividad=A` → offering period
(fechaInicio/Fin, Jul 27–Nov 28) → `&opcionDetalle=DetalleGrupo&codActividad=A` → grupos
(codGrupo, grupo#, modalidad) → `&opcionDetalle=DetalleHorario&codActividad=A&codGrupo=G&fechaIni=..&fechaFin=..`
→ día/hora/profesor/sede/aula. **DetalleHorario 500s unless you pass `codGrupo` + the date
range** (`fechaIni`/`fechaFin` from DetalleFecha) — that was the bug that made it look like
times weren't published.
- **Schedules are PLAN-SPECIFIC**: the SAME 8-digit code returns DIFFERENT horarios per
  `planEstudio` (e.g. `11310003` has 3 sessions under MA03, 0 under ADM1). So the scraper
  iterates every **(plan, course)** pair and `schedules.json` is keyed by plan:
  `{plan: {code: {period, grupos:[{grupo,modalidad,idioma,capacidad,profesores,slots:[{dia,inicio,fin,sede,aula,profesor,actividad}]}]}}}`.
  Do NOT key schedules by code alone (that showed students another program's times).
- A student enrolls in one **grupo**, which bundles that group's weekly slots across all its
  activities (teórica + práctica/lab/monitoría); each slot is tagged with its `actividad`.
  Slots are grouped by grupo NUMBER. 2015 course-schedules across 52 plans, 7682 grupos, ~90%
  with a named professor (rest = "Profesor por asignar" pre-term). Re-run to refresh as more fill in.
`scheduler.solve(codes, plan, pins)` is the conflict CSP (one grupo per course, no slot overlap,
via backtracking) keyed by the student's plan; `pins={code: grupo#}` honors a user-chosen grupo;
returns `options` (all grupos per course) so the UI can switch. Reports the blocking pair when
infeasible. Wired into `/api/simulate`. The static UI shows each course's grupos under the
calendar with the chosen one marked and the rest tappable to switch (re-solves live).
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
- **Disponibles** = the plan course set (deduped by name) minus passed minus prereq-locked.
  The plan set is `malla_plan[codPlan]` when available (the scraped plan filtered to courses
  actually drawn in the official malla PDF, via `pipeline/build_malla_plans.py` — drops
  cross-program junk like energy/logistics electives the API cross-lists into MA03), else the
  full `plan_courses[codPlan]` (fallback for image-only mallas: Enfermería, Negocios Int, etc.).
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
- **Courses with no panel history** (e.g. Medicina's per-hospital/per-group clinical
  variants, many GEN/HM electives): `_cs` no longer fabricates a generic prior (the bug that
  made every Medicina hospital practice show ~4.3). Two-step handling in `engine.py` +
  `oraculo.js` (kept in parity): (1) **canonical-name fallback** (`_stats_for`/`statsFor`) —
  a code missing from the panel borrows the stats of a SAME-NAMED parent course (full name,
  then name with the `" - <site/group>"` suffix stripped; whole-token abbreviations expanded
  on both sides via `_ABBR`/`matchKey`, e.g. `BLQ.`→`BLOQUE`), flagged `borrowed`/confidence
  `"med"`; (2) if still no match, the course is `has_data=False` → grade/stars are `None`
  (`confidence="none"`), shown as an empty state ("sin histórico" / "·"), excluded from the
  projected GPA (separate `gpa_cr`/`gpa_w` denominator) but still counted toward credits/load
  (neutral 3-star effort), with a semester warning. Low-n (n<25) still flags `confidence` low.

## Medicina (ME03) — hospital reviews + med-student mode (IN PROGRESS)
Goal: when a **Medicina transcript (plan `ME03`)** is detected, unlock med-student-specific
functionality and "improve the tool as much as possible for medicine students." The first
piece is **hospital reviews**: students give the rotation hospitals a star rating + written
reviews; the app shows them.
- **Hospital entities are derived, not invented.** `pipeline/build_hospitals.py` parses the
  ME03 plan course names (clinical courses encode their site as a `" - <SITE>"` suffix) and
  maps each to a CANONICAL hospital by keyword (`HOSPITALS` list; handles accents, abbrevs
  like `HUM`/`HUBU`, `CARDIO INFANTIL` vs `CARDIOINFANTIL`, `A + B` multi-site). Output
  `model/hospitals.json` = **23 hospitals** (Cardioinfantil, HU Mayor/Méderi, San Rafael,
  Centenario, Kennedy, Bosa, Barrios Unidos, Samaritana, …) each with `{id,name,n_rotations,
  rotations:[specialty/block labels],codes:[course codes]}`. Only 3 non-hospital mentions
  correctly excluded (international-exchange rotations, generic "Especialidad Clínica").
- **DECISIONS (don't silently change):** reviews are **seeded, read-only** — curated review
  data shipped as static JSON (`model/hospital_reviews.json`, keyed by hospital `id`,
  currently EMPTY: `{rating:null,n:0,reviews:[]}`), so the app stays 100% client-side (no
  backend, fits GitHub Pages + the "nothing leaves your browser" line). **Review granularity
  (per-hospital overall vs per-rotation/specialty) is DEFERRED** until Lucas has real reviews
  in hand — the JSON schema must stay flexible to switch later. Gate the UI on `state.plan ===
  "ME03"`. Frame the no-reviews state as a visible empty state, never fabricate reviews.
- **NEXT (pending input):** Lucas will drop a FOLDER of real review material. Inspect it,
  fit it to `hospital_reviews.json` (match to hospital ids; settle granularity then), build
  the Medicina-gated **"Hospitales" UI** (read-only cards: hospital · rotations · avg stars ·
  reviews, empty-state when none) in `docs/index.html` (+ copy `hospitals.json`/
  `hospital_reviews.json` into `docs/data/` and load them in the bootstrap), and look for
  other high-value med-student improvements. Keep the Spanish/sober/Inter/no-em-dash brand.

## Related docs
- `Oraculo-Solicitud-Panel.tex/.pdf` — the formal data-access request to the institution.
- Background/decisions also captured in `.claude/.../memory/project_oraculo*.md`.
