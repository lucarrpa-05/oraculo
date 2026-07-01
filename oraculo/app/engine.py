"""
Oraculo Risk + Difficulty Engine — inference + transcript parsing.

Two trained models on the institutional panel:
  • fail classifier  (model.joblib)        -> P(fail | student, course)
  • grade regressor  (grade_model.joblib)  -> expected grade (0-5)
plus intrinsic course-difficulty stars from the grade distribution.

Honesty notes baked in:
  - The within-student analysis shows ~no load->GPA effect in this data, so the
    predicted semester GPA is NOT inflated by a fabricated load penalty.
  - Semester WORKLOAD (difficulty stars) is an explicit convex effort model, and
    structurally-infeasible loads are flagged by a feasibility rule, not stats.
"""
import os, re, json, unicodedata
import numpy as np
import joblib

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(os.path.dirname(HERE), "model")

_clf = joblib.load(os.path.join(MODEL_DIR, "model.joblib"))
CLF, CLF_FEATS, GLOBAL_FAIL = _clf["model"], _clf["features"], _clf["global_fail"]
_reg = joblib.load(os.path.join(MODEL_DIR, "grade_model.joblib"))
REG, REG_FEATS, RESID_STD, GMEAN = _reg["model"], _reg["features"], _reg["resid_std"], _reg["global_mean_grade"]

_cat = json.load(open(os.path.join(MODEL_DIR, "catalog.json"), encoding="utf-8"))
CATALOG, MACC_PLAN, MACC_PREREQS = _cat["catalog"], _cat["macc_plan"], _cat["macc_prereqs"]
PLAN_COURSES = _cat.get("plan_courses", {})   # official course membership per codPlan
POOL_CODES = [c for c, m in CATALOG.items() if m.get("pool")]   # GEN/HM elective pools
_mp = os.path.join(MODEL_DIR, "malla_plan.json")   # scraped plan filtered to the official malla
MALLA_PLAN = json.load(open(_mp, encoding="utf-8")) if os.path.exists(_mp) else {}
STATS = {r["crs"]: r for r in json.load(open(os.path.join(MODEL_DIR, "course_stats.json"), encoding="utf-8"))}
# data-derived study plans for all programs (core/elective/typ_sem/freq)
PLANS = json.load(open(os.path.join(MODEL_DIR, "plans.json"), encoding="utf-8"))
PLAN_NAMES = {"MA03": "MATEMATICAS APLICADAS Y CIENCIAS DE LA COMPUTACION"}

# official tipologia per (plan, course) scraped from the guia (build_tipologias.py). This is
# what distinguishes OBLIGATORIA from COMPLEMENTARIA / PROYECTO / ELECTIVA -- a classification
# the malla PDF (hence malla_plan.json) lacks, which is why complementarias were missing.
_tp = os.path.join(MODEL_DIR, "tipologias.json")
TIPOLOGIAS = json.load(open(_tp, encoding="utf-8")) if os.path.exists(_tp) else {}
_TIP_LABEL = {"T": "OBLIGATORIA", "C": "COMPLEMENTARIA", "P": "PROYECTO", "L": "ELECTIVA", "?": "OTRA"}
# the malla-only catalog names only obligatorias; let _cs name every tipologia course too,
# borrowing nombre/creditos from the scrape when the catalog is missing the code.
for _pl, _codes in TIPOLOGIAS.items():
    for _code, _info in _codes.items():
        if _code not in CATALOG and _info.get("nombre"):
            CATALOG[_code] = {"name": _info["nombre"], "credits": _info.get("creditos") or 3.0}

def _tipologia(plan, code):
    """Label OBLIGATORIA/COMPLEMENTARIA/PROYECTO/ELECTIVA for a (plan, course), or None."""
    info = TIPOLOGIAS.get(plan, {}).get(code)
    return _TIP_LABEL.get(info.get("t"), "OTRA") if info else None

# workload model (explicit, not learned): harder courses cost superlinearly more effort
STAR_EFFORT = {1: 1.0, 2: 1.3, 3: 1.65, 4: 2.05, 5: 2.5}
SEM_STAR_CUT = [16, 24, 33, 43]          # effort thresholds -> 1..5 semester stars
MAX_FEASIBLE_CREDITS = 24
MAX_FEASIBLE_COURSES = 7

def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()

# ----------------------------------------------------------------------------
def _detect_plan(text, passed=None):
    # primary: the official plan whose course set best matches what the student took
    # (robust to PDF text layout, and disambiguates plan VERSIONS, e.g. PS04 vs PS03)
    if passed:
        scored = sorted(((len(set(passed) & set(cs)), p) for p, cs in PLAN_COURSES.items()),
                        reverse=True)
        if scored and scored[0][0] >= 5:
            return scored[0][1]
    nt = norm(text)
    seg = nt.split("DNI")[0]
    cands = re.findall(r"[A-Z]{2}\d{2}", seg[-120:])
    return cands[-1] if cands else None

_NUMWORD = {"cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
            "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}

def _paren_grade(text):
    """The canonical grade is the spelled-out form '(cuatro,dos)' = 4.2 — present for
    every graded course. Strip watermark capitals ('(cuaAtro,dos)' -> cuatro,dos)."""
    t = re.sub(r"[A-Z]", "", text)
    m = re.search(r"\(([a-z]+),([a-z]+)\)", t)
    if m and m.group(1) in _NUMWORD and m.group(2) in _NUMWORD:
        return round(_NUMWORD[m.group(1)] + _NUMWORD[m.group(2)] / 10, 2)
    return None

def _num_grade(text):
    m = re.search(r"(\d)[,.](\d)", re.sub(r"[A-Za-z]", "", text))
    return float(f"{m.group(1)}.{m.group(2)}") if m else None

def parse_transcript(pdf_bytes):
    """Layout-aware parse of the UXXI 'Historia Académica' PDF. The text layer is
    column-shuffled and a 'SOLO INFORMATIVO' watermark splits rows and injects stray
    letters, so we anchor on the 8-digit code (x~18) and attach each other cell to the
    NEAREST code by vertical position (not exact row): grade word-form (x~285), numeric
    grade (x~266), credits (x~414/456), name (x~60-255)."""
    import pdfplumber, io
    courses = {}
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pg in pdf.pages:
            text_parts.append(pg.extract_text() or "")
            words = pg.extract_words()
            anchors = [(w["top"], w["text"]) for w in words
                       if 13 <= w["x0"] <= 26 and re.fullmatch(r"\d{8}", w["text"])]
            if not anchors:
                continue
            def nearest(top):                       # code anchor closest in y (<= 14px)
                best = min(anchors, key=lambda a: abs(a[0] - top))
                return best[1] if abs(best[0] - top) <= 14 else None
            acc = {a[1]: {"paren": None, "num": None, "cr": 0, "name": [],
                          "appr": None, "passfail": False} for a in anchors}
            for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
                code = nearest(w["top"]); x = w["x0"]; t = w["text"]
                if not code:
                    continue
                if 266 <= x <= 308 and "(" in t:           # word-form '(cinco,cero)' x~275-285
                    acc[code]["paren"] = acc[code]["paren"] or _paren_grade(t)
                elif 228 <= x <= 308 and "APROBAD" in t.upper():   # pass/fail, no number
                    acc[code]["passfail"] = True
                elif 250 <= x <= 278:                       # numeric '4,2' x~266
                    acc[code]["num"] = acc[code]["num"] or _num_grade(t)
                elif (405 <= x <= 422 or 448 <= x <= 466) and t.strip().isdigit():
                    acc[code]["cr"] += int(t)
                elif 58 <= x <= 255:
                    acc[code]["name"].append((x, t))
                elif 370 <= x <= 386 and t in ("S", "N"):
                    acc[code]["appr"] = t
            for code, a in acc.items():
                if code in courses:
                    continue
                nm = " ".join(t for _, t in sorted(a["name"]))
                courses[code] = {"grade": a["paren"] if a["paren"] is not None else a["num"],
                                 "credits": a["cr"] or None, "name": nm or None,
                                 "approved": a["appr"], "passfail": a["passfail"]}
    text = "\n".join(text_parts)

    plan = _detect_plan(text, set(courses))
    grades = {c: v["grade"] for c, v in courses.items() if v["grade"] is not None}
    pdf_names = {c: v["name"] for c, v in courses.items() if v["name"]}
    passed = set(courses)

    mg = re.search(r"[Pp]romedio acumulado\s*:?\s*([\d]+[.,][\d]+)", text)
    cumgpa = float(mg.group(1).replace(",", ".")) if mg else (
        round(sum(grades.values()) / len(grades), 2) if grades else None)
    mp = re.search(r"[Pp]eriodos aprobados\s*:?\s*(\d+)", text)
    periods = int(mp.group(1)) if mp else None
    cumcred = sum(courses[c]["credits"] or (CATALOG[c]["credits"] if c in CATALOG else 3)
                  for c in passed)
    name = None
    mn = re.search(r"Alumno\s*:?\s*([A-ZÁÉÍÓÚÑ ]{4,})", text)
    if mn:
        name = mn.group(1).strip().title()

    passfail = sorted(c for c, v in courses.items() if v["passfail"] and v["grade"] is None)
    return {"name": name, "plan": plan, "passed": sorted(passed), "grades": grades,
            "pdf_names": pdf_names, "passfail": passfail, "cumgpa": cumgpa,
            "cumcred": round(cumcred, 1), "periods": periods,
            "sem_next": (periods + 1) if periods else None}

# ----------------------------------------------------------------------------
# whole-token abbreviation expansions, applied to BOTH sides of the name match so an
# abbreviated plan name lines up with its spelled-out parent (e.g. 'BLQ. CLÍNICO I' ==
# 'BLOQUE CLÍNICO I'). Keep these unambiguous; when unsure, prefer an empty state to a guess.
_ABBR = {"BLQ": "BLOQUE"}
def _match_key(name):
    """Canonical name with abbreviations expanded, for the borrow-from-parent lookup."""
    c = _canon(name)
    if not c:
        return c
    return " ".join(_ABBR.get(t.rstrip("."), t.rstrip(".")) for t in c.split())

_NAME_STATS = None
def _name_stats_index():
    """match-key -> panel-stats code (highest n). Lets a code that the panel never recorded
    borrow the history of a SAME-NAMED course. The official plans list many per-site /
    per-group variants of one course (e.g. 'Bloque Clínico I - Hospital X - Grupo A') that
    the panel only ever stored under a single parent code ('Bloque Clínico I')."""
    global _NAME_STATS
    if _NAME_STATS is None:
        _NAME_STATS = {}
        for code, s in STATS.items():
            if s.get("n", 0) < 25:
                continue
            k = _match_key(CATALOG.get(code, {}).get("name"))
            if k and (k not in _NAME_STATS or s["n"] > STATS[_NAME_STATS[k]]["n"]):
                _NAME_STATS[k] = code
    return _NAME_STATS

def _stats_for(code):
    """Panel stats for a code; if the code itself isn't in the panel, fall back to a
    same-named parent course (returns (stats_dict, borrowed?))."""
    if code in STATS:
        return STATS[code], False
    nm = CATALOG.get(code, {}).get("name")
    if nm:
        idx = _name_stats_index()
        base = nm.split(" - ")[0]                      # strip site/group suffix
        for key in (_match_key(nm), _match_key(base)):
            pc = key and idx.get(key)
            if pc:
                return STATS[pc], True
    return {}, False

def _cs(code):
    s, borrowed = _stats_for(code)
    c = CATALOG.get(code, {})
    return {
        "name": c.get("name"), "credits": c.get("credits", 3.0),
        "fail_rate": s.get("fail_rate", GLOBAL_FAIL),
        "mean_grade": s.get("mean_grade", GMEAN),
        "std_grade": s.get("std_grade", 0.5),
        "stars_global": int(s.get("stars", 3)),
        "difficulty_raw": float(s.get("difficulty_raw", 0.0)),
        "n": int(s.get("n", 0)),
        "borrowed": borrowed,
        "has_data": bool(s),
    }

def _plan_star_cuts(plan_codes):
    """Quintile cutoffs of intrinsic difficulty WITHIN the student's major, so stars
    rank a course against its own program (not all 3700 university courses)."""
    raws = [STATS[c]["difficulty_raw"] for c in plan_codes
            if c in STATS and STATS[c].get("n", 0) >= 25 and "difficulty_raw" in STATS[c]]
    if len(raws) < 10:
        return None
    # round to 6 dp so the JS port's quantile interpolation (identical formula, but ULP-level
    # float noise) lands stars identically on exact percentile boundaries.
    return [round(float(x), 6) for x in np.quantile(raws, [0.2, 0.4, 0.6, 0.8])]

def _intrinsic_stars(code, cuts):
    cs = _cs(code)
    if cuts is None:
        return cs["stars_global"]
    return int(1 + np.digitize(cs["difficulty_raw"], cuts))

def _area_hist(area, state):
    """student's prior grades in the same subject area (from the transcript)."""
    gs = [g for c, g in state.get("grades", {}).items() if c[:4] == area]
    return (float(np.mean(gs)) if gs else np.nan), len(gs)

def _feat(code, state, feats):
    cs = _cs(code); area = code[:4]
    area_gpa, area_n = _area_hist(area, state)
    nv = lambda v: v if v is not None else np.nan
    F = {
        "c_fail_rate": cs["fail_rate"], "c_mean_grade": cs["mean_grade"],
        "c_std_grade": cs["std_grade"], "c_n": cs["n"],
        "prior_gpa": nv(state.get("cumgpa")), "area_gpa": area_gpa, "area_n": area_n,
        "cumcred": nv(state.get("cumcred")), "sem": nv(state.get("sem_next")),
        "age": np.nan, "sexF": np.nan,
        "att": 1.0, "is_retake": 0.0, "prior_fail": 0.0,
    }
    return [F[k] for k in feats]

def _predict_fail(codes, state):
    if not codes: return []
    return CLF.predict_proba(np.array([_feat(c, state, CLF_FEATS) for c in codes], float))[:, 1].tolist()

def _predict_grade(codes, state):
    if not codes: return []
    g = REG.predict(np.array([_feat(c, state, REG_FEATS) for c in codes], float))
    return np.clip(g, 0, 5).tolist()

def _shortfall_stars(gpa, exp_grade):
    sf = gpa - exp_grade
    if sf <= 0.05: return 1
    if sf <= 0.20: return 2
    if sf <= 0.40: return 3
    if sf <= 0.70: return 4
    return 5

def _personal_stars(intrinsic, state, exp_grade):
    """Difficulty for THIS student: equal blend of the course's (plan-relative)
    intrinsic difficulty and how far it is predicted to fall below the student's own
    average (relative effort)."""
    gpa = state.get("cumgpa") or GMEAN
    blended = 0.5 * intrinsic + 0.5 * _shortfall_stars(gpa, exp_grade)
    return int(min(5, max(1, round(blended))))

def _confidence(code, state):
    """How much to trust this course's grade/difficulty estimate."""
    cs = _cs(code)
    if not cs["has_data"]:
        return "none"                       # no panel history (nor a same-named parent)
    if cs["borrowed"]:
        return "med"                        # inferred from a same-named parent course
    if cs["n"] < 25 or cs["std_grade"] > 1.4:
        return "low"
    if cs["n"] < 80:
        return "med"
    return "high"

# ---- prerequisites -----------------------------------------------------------
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}

def _split_level(name):
    """('CÁLCULO 2') -> ('CALCULO', 2); ('ESTADÍSTICA I') -> ('ESTADISTICA', 1)."""
    toks = norm(name).split()
    if not toks: return None, None
    last = toks[-1]
    if last in _ROMAN: return " ".join(toks[:-1]), _ROMAN[last]
    if last.isdigit() and len(last) <= 2: return " ".join(toks[:-1]), int(last)
    return None, None

def _name_seq_prereqs(codes):
    """Reliable prereqs from numbered course sequences (Cálculo 1->2->3, Estadística
    I->II). Grouped by (base name, code family) so look-alike sequences from different
    programs don't cross-link (e.g. arabic 'FÍSICA 1/2', code 732…, vs roman
    'FÍSICA I/II', code 182…). One code per level; only STRICTLY INCREASING distinct
    levels link, so '1' and 'I' (both level 1) never require each other."""
    groups = {}
    for c in codes:
        nm = _cs(c)["name"]
        if not nm: continue
        base, lvl = _split_level(nm)
        if not (base and lvl): continue
        groups.setdefault((base, c[:3]), {}).setdefault(lvl, c)   # one code per level
    pre = {}
    for bylvl in groups.values():
        levels = sorted(bylvl)
        for i in range(1, len(levels)):
            pre[bylvl[levels[i]]] = [bylvl[levels[i - 1]]]
    return pre

def _has_name(code):
    return bool(_cs(code)["name"])

def _canon(name):
    """Canonical course identity = normalized name. The SAME course gets different
    8-digit codes across plan versions (e.g. Cálculo 3 is 11320003 in your transcript
    but appears under other codes in the panel), so code alone can't dedupe or detect
    'already taken' — the name can."""
    return norm(name) if name else None

def _passed_identity(state):
    """codes the student passed + the canonical names of those courses."""
    pc = set(state.get("passed", []))
    pdf = state.get("pdf_names", {})
    pn = {n for c in pc for n in [_canon(_cs(c)["name"] or pdf.get(c))] if n}
    return pc, pn

def _is_passed(code, pc, pn):
    if code in pc:
        return True
    nm = _cs(code)["name"]
    return bool(nm and _canon(nm) in pn)

def _plan_context(state):
    plan = state.get("plan")
    entry = PLANS.get(plan, {})
    typ_sem = entry.get("typ_sem", {})
    # Universe = the OFFICIAL scraped plan ONLY (no panel codes, which carry old plan-
    # version duplicates). Dedupe by canonical name so a course listed twice (e.g. two
    # Capstone entries) shows once. Electives = the official GEN/HM pools, never panel.
    seen_names = set()
    def take(codes, dst):
        for c in codes:
            if not _has_name(c):
                continue
            nm = _canon(_cs(c)["name"])
            if nm in seen_names:
                continue
            seen_names.add(nm); dst.append(c)
    core, comp, elective = [], [], []
    # prefer the malla-filtered plan (junk removed); fall back to the full scraped plan
    # where the malla is an image-only PDF, then to the panel core.
    plan_src = MALLA_PLAN.get(plan) or PLAN_COURSES.get(plan) or [c for c in entry.get("core", []) if _has_name(c)]
    take(plan_src, core)
    # complementarias / proyecto fin de carrera / electivas de plan: the malla diagram omits
    # these, so malla_plan drops them. Recover them from the official tipologia scrape. (take()
    # dedupes by name, so a course already counted as obligatoria won't be double-listed.)
    for c, info in TIPOLOGIAS.get(plan, {}).items():
        if info.get("t") in ("C", "P", "L"):
            take([c], comp)
    take(POOL_CODES, elective)
    prereqs = {}
    if plan == "MA03":
        prereqs.update(MACC_PREREQS)                       # official malla
    for b, ps in _name_seq_prereqs(core + comp + elective).items():  # numbered sequences
        prereqs.setdefault(b, [])
        prereqs[b] = list(dict.fromkeys(prereqs[b] + ps))
    return {"plan": plan, "core": core, "comp": comp, "elective": elective,
            "typ_sem": typ_sem, "prereqs": prereqs, "has_plan": bool(core or comp or elective)}

def _build_item(code, ctx, state, cuts, pc, pn):
    cs = _cs(code)
    missing = [p for p in ctx["prereqs"].get(code, []) if not _is_passed(p, pc, pn)]
    return {
        "code": code, "name": cs["name"], "credits": cs["credits"],
        "stars": _intrinsic_stars(code, cuts),
        "fail_rate_hist": cs["fail_rate"], "n_hist": cs["n"],
        "typ_sem": ctx["typ_sem"].get(code),
        "prereqs_met": not missing,
        "missing": [{"code": p, "name": _cs(p)["name"]} for p in missing],
    }

def _score_items(items, state):
    codes = [i["code"] for i in items]
    fails = _predict_fail(codes, state)
    grades = _predict_grade(codes, state)
    for it, p, g in zip(items, fails, grades):
        it["confidence"] = _confidence(it["code"], state)
        if _cs(it["code"])["has_data"]:
            it["risk"] = round(p, 4)
            it["exp_grade"] = round(g, 2)
            it["stars_personal"] = _personal_stars(it["stars"], state, g)
        else:
            # no panel history (nor a same-named parent): don't fabricate a grade/difficulty
            it["risk"] = None
            it["exp_grade"] = None
            it["stars"] = None
            it["stars_personal"] = None
    return items

def eligible(state):
    ctx = _plan_context(state)
    plan = state.get("plan")
    pc, pn = _passed_identity(state)
    cuts = _plan_star_cuts(ctx["core"] + ctx["comp"] + ctx["elective"]) if ctx["has_plan"] else None

    core_set = set(ctx["core"])
    required, locked, electives = [], [], []
    # Disponibles = obligatorias (core) + complementarias/proyecto/electivas de plan (comp),
    # each tagged with its tipologia so the UI can sub-filter (Obligatoria/Complementaria/...).
    for code in ctx["core"] + ctx["comp"]:
        if _is_passed(code, pc, pn): continue        # already taken (by code OR name)
        it = _build_item(code, ctx, state, cuts, pc, pn)
        it["tipologia"] = _tipologia(plan, code) or ("OBLIGATORIA" if code in core_set else "COMPLEMENTARIA")
        (required if it["prereqs_met"] else locked).append(it)
    for code in ctx["elective"]:
        if _is_passed(code, pc, pn): continue
        it = _build_item(code, ctx, state, cuts, pc, pn)
        if it["prereqs_met"]:
            it["tipologia"] = "ELECTIVA HM"
            electives.append(it)
    # the GEN/HM pool is ~1000 courses (university-wide); return all (sorted A-Z) so the
    # client search covers the whole pool. The UI caps how many it renders at once.
    electives.sort(key=lambda x: norm(x["name"] or x["code"]))
    n_electives_total = len(electives)
    _score_items(required + locked + electives, state)
    required.sort(key=lambda x: ((x["typ_sem"] or 99), -(x["stars"] or 0)))
    locked.sort(key=lambda x: (x["typ_sem"] or 99))

    # the student's parsed transcript: passed courses with grades (name from catalog,
    # else the name read off the PDF, else the code)
    pdf_names = state.get("pdf_names", {}); grades = state.get("grades", {})
    passfail = set(state.get("passfail", []))
    plan_names = {_canon(_cs(c)["name"]) for c in ctx["core"] + ctx["comp"] + ctx["elective"]}
    transcript = sorted(
        ({"code": c, "name": _cs(c)["name"] or pdf_names.get(c), "grade": grades.get(c),
          "passfail": c in passfail, "credits": _cs(c)["credits"],
          "in_plan": _canon(_cs(c)["name"] or pdf_names.get(c)) in plan_names}
         for c in pc),
        key=lambda x: (x["grade"] is None, -(x["grade"] or 0)))
    return {"required": required, "locked": locked, "electives": electives,
            "n_electives_total": n_electives_total,
            "transcript": transcript, "has_plan": ctx["has_plan"], "plan": ctx["plan"]}

def _sem_stars(effort):
    return 1 + sum(1 for c in SEM_STAR_CUT if effort >= c)

def simulate(state, basket):
    basket = [c for c in basket if c in STATS or c in CATALOG]
    if not basket:
        return {"courses": [], "n_courses": 0, "total_credits": 0,
                "sem_stars": 0, "pred_gpa": None, "gpa_delta": None,
                "p_any_fail": 0.0, "effort": 0, "feasible": True, "warnings": [], "drivers": []}
    ctx = _plan_context(state)
    cuts = _plan_star_cuts(ctx["core"] + ctx["comp"] + ctx["elective"]) if ctx["has_plan"] else None
    fails = _predict_fail(basket, state)
    grades = _predict_grade(basket, state)
    items, effort, cr_sum, gpa_cr, gpa_w = [], 0.0, 0.0, 0.0, 0.0
    gpa = state.get("cumgpa") or GMEAN
    for code, p, g in zip(basket, fails, grades):
        cs = _cs(code)
        cr_sum += cs["credits"]
        if cs["has_data"]:
            intr = _intrinsic_stars(code, cuts); sp = _personal_stars(intr, state, g)
            effort += cs["credits"] * STAR_EFFORT[sp]
            gpa_cr += cs["credits"]; gpa_w += cs["credits"] * g
            items.append({"code": code, "name": cs["name"], "credits": cs["credits"],
                          "stars": sp, "stars_intrinsic": intr,
                          "exp_grade": round(g, 2), "grade_band": round(RESID_STD, 2),
                          "gpa_delta": round(g - gpa, 2), "risk": round(p, 4),
                          "confidence": _confidence(code, state)})
        else:
            # no panel history: count its credits/load but don't fabricate a grade or GPA impact
            effort += cs["credits"] * STAR_EFFORT[3]   # neutral effort for an unknown course
            items.append({"code": code, "name": cs["name"], "credits": cs["credits"],
                          "stars": None, "stars_intrinsic": None,
                          "exp_grade": None, "grade_band": round(RESID_STD, 2),
                          "gpa_delta": None, "risk": None, "confidence": "none"})
    items.sort(key=lambda x: (-(x["stars"] or 0), x["exp_grade"] if x["exp_grade"] is not None else 9))
    pred_gpa = gpa_w / gpa_cr if gpa_cr else None
    sem_stars = _sem_stars(effort)
    risks = [i["risk"] for i in items if i["risk"] is not None]
    p_any = 1 - float(np.prod([1 - r for r in risks])) if risks else 0.0

    warnings = []
    n = len(items)
    n_nodata = sum(1 for i in items if i["exp_grade"] is None)
    if n_nodata:
        warnings.append(f"{n_nodata} asignatura(s) sin histórico en la base: se muestran sin "
                        f"nota ni dificultad estimadas y no afectan el promedio proyectado.")
    if cr_sum > MAX_FEASIBLE_CREDITS or n > MAX_FEASIBLE_COURSES:
        warnings.append(f"Carga no viable: {n} asignaturas / {cr_sum:.0f} créditos "
                        f"exceden el máximo registrable (~{MAX_FEASIBLE_CREDITS} créditos).")
    hard = [i for i in items if i["stars"] and i["stars"] >= 4]
    if len(hard) >= 3:
        warnings.append(f"{len(hard)} asignaturas de alta dificultad en simultáneo — "
                        f"semestre muy exigente en tiempo de estudio.")

    return {
        "courses": items, "n_courses": n, "total_credits": round(cr_sum, 1),
        "sem_stars": sem_stars, "effort": round(effort, 1),
        "pred_gpa": round(pred_gpa, 2) if pred_gpa else None,
        "gpa_delta": round(pred_gpa - gpa, 2) if pred_gpa else None,
        "cum_gpa": gpa,
        "p_any_fail": round(p_any, 4),
        "feasible": not any("no viable" in w for w in warnings),
        "warnings": warnings,
        "drivers": [i["name"] for i in items[:2] if i["stars"] and i["stars"] >= 4],
    }
