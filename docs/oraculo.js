/* Oráculo client-side engine — a faithful JS port of engine.py + scheduler.py.
   Runs entirely in the browser: model inference (exported HistGBM trees), eligibility,
   difficulty, simulate, schedule conflict solver. Data is injected via O.setData(). */
(function (global) {
  "use strict";
  const O = {};
  let CATALOG = {}, STATS = {}, PLAN_COURSES = {}, POOL_CODES = [], MACC_PLAN = [],
      MACC_PREREQS = {}, PLANS = {}, SCHEDULES = {}, MODELS = null, MALLA_PLAN = {},
      GLOBAL_FAIL = 0.04, GMEAN = 4.0;

  O.setData = function (d) {
    CATALOG = d.catalog.catalog;
    PLAN_COURSES = d.catalog.plan_courses || {};
    MALLA_PLAN = d.malla || {};
    MACC_PLAN = d.catalog.macc_plan || [];
    MACC_PREREQS = d.catalog.macc_prereqs || {};
    POOL_CODES = Object.keys(CATALOG).filter(c => CATALOG[c].pool);
    STATS = {};
    for (const r of d.stats) STATS[r.crs] = r;
    PLANS = d.plans;
    SCHEDULES = d.schedules || {};
    NAME_STATS = null;                 // rebuild the name->stats index for the new data
    MODELS = d.models;
    GLOBAL_FAIL = MODELS.fail.global_fail;
    GMEAN = MODELS.grade.global_mean_grade;
  };

  // ---------- helpers ----------
  function norm(s) {
    if (!s) return "";
    return s.normalize("NFKD").replace(/[̀-ͯ]/g, "")
            .replace(/[^\x00-\x7F]/g, "").toUpperCase().replace(/\s+/g, " ").trim();
  }
  const canon = norm;
  const PLAN_NAMES = { MA03: "MATEMATICAS APLICADAS Y CIENCIAS DE LA COMPUTACION" };

  // match-key -> panel-stats code (highest n): lets a code the panel never recorded borrow
  // a SAME-NAMED course's history (official plans list per-site/group variants like
  // 'Bloque Clínico I - Hospital X' that the panel stored under one parent). Whole-token
  // abbreviations are expanded on both sides so 'BLQ. Clínico I' == 'Bloque Clínico I'.
  const ABBR = { BLQ: "BLOQUE" };
  function matchKey(name) {
    const c = norm(name); if (!c) return c;
    return c.split(" ").map(t => { const u = t.replace(/\.+$/, ""); return ABBR[u] || u; }).join(" ");
  }
  let NAME_STATS = null;
  function nameStatsIndex() {
    if (NAME_STATS === null) {
      NAME_STATS = {};
      for (const code in STATS) {
        const s = STATS[code]; if ((s.n || 0) < 25) continue;
        const k = matchKey((CATALOG[code] || {}).name);
        if (k && (!(k in NAME_STATS) || s.n > STATS[NAME_STATS[k]].n)) NAME_STATS[k] = code;
      }
    }
    return NAME_STATS;
  }
  function statsFor(code) {
    if (STATS[code]) return { s: STATS[code], borrowed: false };
    const nm = (CATALOG[code] || {}).name;
    if (nm) {
      const idx = nameStatsIndex(), base = nm.split(" - ")[0];
      for (const key of [matchKey(nm), matchKey(base)]) {
        const pc = key && idx[key];
        if (pc) return { s: STATS[pc], borrowed: true };
      }
    }
    return { s: {}, borrowed: false };
  }
  function cs(code) {
    const c = CATALOG[code] || {}, { s, borrowed } = statsFor(code);
    return {
      name: c.name || null,
      credits: c.credits != null ? c.credits : 3.0,
      fail_rate: s.fail_rate != null ? s.fail_rate : GLOBAL_FAIL,
      mean_grade: s.mean_grade != null ? s.mean_grade : GMEAN,
      std_grade: s.std_grade != null ? s.std_grade : 0.5,
      stars_global: s.stars != null ? s.stars : 3,
      difficulty_raw: s.difficulty_raw != null ? s.difficulty_raw : 0.0,
      n: s.n != null ? s.n : 0,
      borrowed, has_data: Object.keys(s).length > 0,
    };
  }
  const hasName = c => !!cs(c).name;

  // ---------- model inference (exported HistGBM) ----------
  function walk(t, x) {
    let i = 0;
    while (!t.leaf[i]) {
      const xv = x[t.f[i]];
      if (Number.isNaN(xv)) i = t.m[i] ? t.l[i] : t.r[i];
      else i = (xv <= t.t[i]) ? t.l[i] : t.r[i];
    }
    return t.v[i];
  }
  function rawPred(trees, base, x) { let s = base; for (const t of trees) s += walk(t, x); return s; }
  function interp(x, xs, ys) {
    const n = xs.length;
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= x) lo = m; else hi = m; }
    const t = (x - xs[lo]) / (xs[hi] - xs[lo]);
    return ys[lo] + t * (ys[hi] - ys[lo]);
  }
  function evalFail(x) {
    const F = MODELS.fail; let p = 0;
    for (const fd of F.folds) p += interp(rawPred(fd.trees, fd.baseline, x), fd.cal_x, fd.cal_y);
    return p / F.folds.length;
  }
  function evalGrade(x) {
    const G = MODELS.grade; let g = G.baseline;
    for (const t of G.trees) g += walk(t, x);
    return Math.min(5, Math.max(0, g));
  }
  function areaHist(area, state) {
    const gs = [];
    const grades = state.grades || {};
    for (const c in grades) if (c.slice(0, 4) === area) gs.push(grades[c]);
    if (!gs.length) return [NaN, 0];
    return [gs.reduce((a, b) => a + b, 0) / gs.length, gs.length];
  }
  function feat(code, state, feats) {
    const d = cs(code), area = code.slice(0, 4);
    const [area_gpa, area_n] = areaHist(area, state);
    const nv = v => (v == null ? NaN : v);
    const F = {
      c_fail_rate: d.fail_rate, c_mean_grade: d.mean_grade, c_std_grade: d.std_grade, c_n: d.n,
      prior_gpa: nv(state.cumgpa), area_gpa: area_gpa, area_n: area_n,
      cumcred: nv(state.cumcred), sem: nv(state.sem_next), age: NaN, sexF: NaN,
      att: 1.0, is_retake: 0.0, prior_fail: 0.0,
    };
    return feats.map(k => F[k]);
  }
  const predFail = (code, state) => evalFail(feat(code, state, MODELS.fail.features));
  const predGrade = (code, state) => evalGrade(feat(code, state, MODELS.grade.features));

  // ---------- difficulty ----------
  function quantile(sorted, q) {
    const n = sorted.length; if (n === 1) return sorted[0];
    const h = (n - 1) * q, lo = Math.floor(h);
    return sorted[lo] + (h - lo) * (sorted[Math.min(lo + 1, n - 1)] - sorted[lo]);
  }
  function planStarCuts(planCodes) {
    const raws = planCodes.filter(c => STATS[c] && (STATS[c].n || 0) >= 25 && STATS[c].difficulty_raw != null)
                          .map(c => STATS[c].difficulty_raw).sort((a, b) => a - b);
    if (raws.length < 10) return null;
    return [0.2, 0.4, 0.6, 0.8].map(q => quantile(raws, q));
  }
  function intrinsicStars(code, cuts) {
    const d = cs(code);
    if (!cuts) return d.stars_global;
    return 1 + cuts.filter(c => c <= d.difficulty_raw).length;
  }
  function shortfallStars(gpa, exp) {
    const sf = gpa - exp;
    if (sf <= 0.05) return 1; if (sf <= 0.20) return 2; if (sf <= 0.40) return 3;
    if (sf <= 0.70) return 4; return 5;
  }
  function pyRound(x) {  // round half to even, to match Python's round()
    const f = Math.floor(x), d = x - f;
    if (d < 0.5) return f; if (d > 0.5) return f + 1;
    return (f % 2 === 0) ? f : f + 1;
  }
  function personalStars(intrinsic, state, exp) {
    const gpa = state.cumgpa || GMEAN;
    return Math.min(5, Math.max(1, pyRound(0.5 * intrinsic + 0.5 * shortfallStars(gpa, exp))));
  }
  function confidence(code) {
    const d = cs(code);
    if (!d.has_data) return "none";       // no panel history (nor a same-named parent)
    if (d.borrowed) return "med";         // inferred from a same-named parent course
    if (d.n < 25 || d.std_grade > 1.4) return "low";
    if (d.n < 80) return "med";
    return "high";
  }

  // ---------- prerequisites ----------
  const ROMAN = { I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6, VII: 7, VIII: 8 };
  function splitLevel(name) {
    const toks = norm(name).split(" ");
    if (!toks.length) return [null, null];
    const last = toks[toks.length - 1];
    if (last in ROMAN) return [toks.slice(0, -1).join(" "), ROMAN[last]];
    if (/^\d{1,2}$/.test(last)) return [toks.slice(0, -1).join(" "), parseInt(last)];
    return [null, null];
  }
  function nameSeqPrereqs(codes) {
    const groups = {};
    for (const c of codes) {
      const nm = cs(c).name; if (!nm) continue;
      const [base, lvl] = splitLevel(nm); if (!base || !lvl) continue;
      const key = base + "|" + c.slice(0, 3);
      (groups[key] = groups[key] || {});
      if (!(lvl in groups[key])) groups[key][lvl] = c;
    }
    const pre = {};
    for (const k in groups) {
      const levels = Object.keys(groups[k]).map(Number).sort((a, b) => a - b);
      for (let i = 1; i < levels.length; i++) pre[groups[k][levels[i]]] = [groups[k][levels[i - 1]]];
    }
    return pre;
  }

  // ---------- eligibility ----------
  function passedIdentity(state) {
    const pc = new Set(state.passed || []);
    const pdf = state.pdf_names || {};
    const pn = new Set();
    for (const c of pc) { const n = canon(cs(c).name || pdf[c]); if (n) pn.add(n); }
    return [pc, pn];
  }
  function isPassed(code, pc, pn) {
    if (pc.has(code)) return true;
    const nm = cs(code).name;
    return !!(nm && pn.has(canon(nm)));
  }
  function planContext(state) {
    const plan = state.plan, entry = PLANS[plan] || {};
    const typ_sem = entry.typ_sem || {};
    const seen = new Set();
    const core = [], elective = [];
    const take = (codes, dst) => {
      for (const c of codes) {
        if (!hasName(c)) continue;
        const nm = canon(cs(c).name);
        if (seen.has(nm)) continue;
        seen.add(nm); dst.push(c);
      }
    };
    take(MALLA_PLAN[plan] || PLAN_COURSES[plan] || (entry.core || []).filter(hasName), core);
    take(POOL_CODES, elective);
    const prereqs = {};
    if (plan === "MA03") for (const k in MACC_PREREQS) prereqs[k] = MACC_PREREQS[k].slice();
    const seq = nameSeqPrereqs(core.concat(elective));
    for (const b in seq) { prereqs[b] = Array.from(new Set((prereqs[b] || []).concat(seq[b]))); }
    return { plan, core, elective, typ_sem, prereqs, has_plan: !!(core.length || elective.length) };
  }
  function buildItem(code, ctx, state, cuts, pc, pn) {
    const c = cs(code);
    const missing = (ctx.prereqs[code] || []).filter(p => !isPassed(p, pc, pn));
    return {
      code, name: c.name, credits: c.credits, stars: intrinsicStars(code, cuts),
      fail_rate_hist: c.fail_rate, n_hist: c.n, typ_sem: ctx.typ_sem[code] != null ? ctx.typ_sem[code] : null,
      prereqs_met: missing.length === 0,
      missing: missing.map(p => ({ code: p, name: cs(p).name })),
    };
  }
  function scoreItems(items, state) {
    for (const it of items) {
      it.confidence = confidence(it.code);
      if (cs(it.code).has_data) {
        it.risk = round(predFail(it.code, state), 4);
        it.exp_grade = round(predGrade(it.code, state), 2);
        it.stars_personal = personalStars(it.stars, state, it.exp_grade);
      } else {                            // no history: don't fabricate a grade/difficulty
        it.risk = null; it.exp_grade = null; it.stars = null; it.stars_personal = null;
      }
    }
  }
  const round = (x, d = 0) => { const m = Math.pow(10, d); return Math.round(x * m) / m; };

  O.eligible = function (state) {
    const ctx = planContext(state);
    const [pc, pn] = passedIdentity(state);
    const cuts = ctx.has_plan ? planStarCuts(ctx.core.concat(ctx.elective)) : null;
    const required = [], locked = [], electives = [];
    for (const code of ctx.core) {
      if (isPassed(code, pc, pn)) continue;
      const it = buildItem(code, ctx, state, cuts, pc, pn);
      (it.prereqs_met ? required : locked).push(it);
    }
    for (const code of ctx.elective) {
      if (isPassed(code, pc, pn)) continue;
      const it = buildItem(code, ctx, state, cuts, pc, pn);
      if (it.prereqs_met) electives.push(it);
    }
    electives.sort((a, b) => norm(a.name || a.code) < norm(b.name || b.code) ? -1 : 1);
    const n_electives_total = electives.length;
    scoreItems(required.concat(locked).concat(electives), state);
    required.sort((a, b) => (a.typ_sem || 99) - (b.typ_sem || 99) || (b.stars || 0) - (a.stars || 0));
    locked.sort((a, b) => (a.typ_sem || 99) - (b.typ_sem || 99));

    const pdf_names = state.pdf_names || {}, grades = state.grades || {}, passfail = new Set(state.passfail || []);
    const planNames = new Set(ctx.core.concat(ctx.elective).map(c => canon(cs(c).name)));
    const transcript = [...pc].map(c => ({
      code: c, name: cs(c).name || pdf_names[c] || null,
      grade: grades[c] != null ? grades[c] : null, passfail: passfail.has(c),
      credits: cs(c).credits, in_plan: planNames.has(canon(cs(c).name || pdf_names[c])),
    })).sort((a, b) => (a.grade == null) - (b.grade == null) || (b.grade || 0) - (a.grade || 0));

    return { required, locked, electives, n_electives_total, transcript,
             has_plan: ctx.has_plan, plan: ctx.plan };
  };

  // ---------- simulate ----------
  const STAR_EFFORT = { 1: 1.0, 2: 1.3, 3: 1.65, 4: 2.05, 5: 2.5 };
  const SEM_STAR_CUT = [16, 24, 33, 43];
  const HARD_THRESHOLD = 0.15, NOMINAL_CREDITS = 18, OVERLOAD_PER_3CR = 0.05, CONCURRENCY_PER_HARD = 0.07;
  const MAX_FEASIBLE_CREDITS = 24, MAX_FEASIBLE_COURSES = 7;
  const semStars = effort => 1 + SEM_STAR_CUT.filter(c => effort >= c).length;

  O.simulate = function (state, basket, pins) {
    state = state || {};
    basket = basket.filter(c => STATS[c] || CATALOG[c]);
    if (!basket.length) return { courses: [], n_courses: 0, total_credits: 0, sem_stars: 0,
      pred_gpa: null, gpa_delta: null, p_any_fail: 0, effort: 0, feasible: true, warnings: [], drivers: [],
      schedule: O.schedule(basket, state.plan, pins) };
    const ctx = planContext(state);
    const cuts = ctx.has_plan ? planStarCuts(ctx.core.concat(ctx.elective)) : null;
    const gpa = state.cumgpa || GMEAN;
    let effort = 0, crSum = 0, gpaCr = 0, gpaW = 0;
    const items = [];
    for (const code of basket) {
      const d = cs(code);
      crSum += d.credits;
      if (d.has_data) {
        const g = predGrade(code, state), intr = intrinsicStars(code, cuts);
        const sp = personalStars(intr, state, g);
        effort += d.credits * STAR_EFFORT[sp]; gpaCr += d.credits; gpaW += d.credits * g;
        items.push({ code, name: d.name, credits: d.credits, stars: sp, stars_intrinsic: intr,
          exp_grade: round(g, 2), grade_band: round(MODELS.grade.resid_std, 2),
          gpa_delta: round(g - gpa, 2), risk: round(predFail(code, state), 4), confidence: confidence(code) });
      } else {                            // no history: count load, but no fabricated grade/GPA impact
        effort += d.credits * STAR_EFFORT[3];
        items.push({ code, name: d.name, credits: d.credits, stars: null, stars_intrinsic: null,
          exp_grade: null, grade_band: round(MODELS.grade.resid_std, 2),
          gpa_delta: null, risk: null, confidence: "none" });
      }
    }
    items.sort((a, b) => (b.stars || 0) - (a.stars || 0) || (a.exp_grade != null ? a.exp_grade : 9) - (b.exp_grade != null ? b.exp_grade : 9));
    const predGpa = gpaCr ? gpaW / gpaCr : null;
    const risks = items.filter(i => i.risk != null);
    const pAny = risks.length ? 1 - risks.reduce((acc, i) => acc * (1 - i.risk), 1) : 0;
    const warnings = [];
    const nNoData = items.filter(i => i.exp_grade == null).length;
    if (nNoData) warnings.push(`${nNoData} asignatura(s) sin histórico en la base: se muestran sin nota ni dificultad estimadas y no afectan el promedio proyectado.`);
    if (crSum > MAX_FEASIBLE_CREDITS || items.length > MAX_FEASIBLE_COURSES)
      warnings.push(`Carga no viable: ${items.length} asignaturas / ${Math.round(crSum)} créditos exceden el máximo registrable (~${MAX_FEASIBLE_CREDITS} créditos).`);
    const hard = items.filter(i => i.stars && i.stars >= 4);
    if (hard.length >= 3) warnings.push(`${hard.length} asignaturas de alta dificultad en simultáneo, semestre muy exigente en tiempo de estudio.`);
    return {
      courses: items, n_courses: items.length, total_credits: round(crSum, 1),
      sem_stars: semStars(effort), effort: round(effort, 1),
      pred_gpa: predGpa != null ? round(predGpa, 2) : null,
      gpa_delta: predGpa != null ? round(predGpa - gpa, 2) : null, cum_gpa: gpa,
      p_any_fail: round(pAny, 4), feasible: !warnings.some(w => w.includes("no viable")),
      warnings, drivers: items.filter(i => i.stars && i.stars >= 4).slice(0, 2).map(i => i.name),
      schedule: O.schedule(basket, state.plan, pins),
    };
  };

  // ---------- schedule conflict solver (scheduler.py) ----------
  // Schedules are plan-specific: SCHEDULES[plan][code].grupos. A student picks one GRUPO
  // per course (bundling its weekly slots across activities); the caller may PIN a grupo.
  const planSched = plan => (plan && SCHEDULES[plan]) || {};
  const gruposOf = (c, plan) => (planSched(plan)[c] || {}).grupos || [];
  const hasSched = (c, plan) => gruposOf(c, plan).length > 0;
  function slotsOverlap(a, b) { return a.dia === b.dia && a.inicio < b.fin && b.inicio < a.fin; }
  function grConflict(ga, gb) {
    for (const x of ga.slots) for (const y of gb.slots) if (slotsOverlap(x, y)) return true;
    return false;
  }
  O.scheduleIsSample = function () { return false; };
  O.schedule = function (codes, plan, pins) {
    pins = pins || {};
    const scheduled = codes.filter(c => hasSched(c, plan)), unscheduled = codes.filter(c => !hasSched(c, plan));
    const opts = {};
    for (const c of scheduled) {
      const gs = gruposOf(c, plan);
      const pinned = (c in pins) ? gs.filter(g => g.grupo === pins[c]) : [];
      opts[c] = pinned.length ? pinned : gs;
    }
    const conflicts = [];
    for (let i = 0; i < scheduled.length; i++) for (let j = i + 1; j < scheduled.length; j++) {
      const a = scheduled[i], b = scheduled[j];
      if (opts[a].length && opts[b].length && opts[a].every(ga => opts[b].every(gb => grConflict(ga, gb))))
        conflicts.push({ a, b, reason: "todas las secciones se cruzan en horario" });
    }
    const order = scheduled.slice().sort((a, b) => opts[a].length - opts[b].length);
    const chosen = {};
    const compatible = sec => order.every(o => !(o in chosen) || !grConflict(sec, chosen[o]));
    function bt(idx) {
      if (idx === order.length) return true;
      const c = order[idx];
      for (const sec of opts[c]) if (compatible(sec)) { chosen[c] = sec; if (bt(idx + 1)) return true; delete chosen[c]; }
      return false;
    }
    const feasible = bt(0);
    const assignment = feasible ? order.map(c => ({ code: c, section: chosen[c] })) : [];
    const options = {}; for (const c of scheduled) options[c] = gruposOf(c, plan);  // all grupos, for the UI switcher
    return { feasible, assignment, conflicts, scheduled, unscheduled, options,
             is_sample: false, have_schedules: Object.keys(SCHEDULES).length > 0 };
  };

  // ---------- transcript parser (mirrors engine.parse_transcript) ----------
  const NUMWORD = { cero: 0, uno: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9, diez: 10 };
  function parenGrade(text) {
    const t = text.replace(/[A-Z]/g, "");
    const m = t.match(/\(([a-z]+),([a-z]+)\)/);
    if (m && m[1] in NUMWORD && m[2] in NUMWORD) return Math.round((NUMWORD[m[1]] + NUMWORD[m[2]] / 10) * 100) / 100;
    return null;
  }
  function numGrade(text) {
    const m = text.replace(/[A-Za-z]/g, "").match(/(\d)[,.](\d)/);
    return m ? parseFloat(m[1] + "." + m[2]) : null;
  }
  // pages = [ [ {str, x, top}, ... ], ... ]  (x = transform[4], top = -transform[5])
  O.parseItems = function (pages) {
    const courses = {}; const order = [];
    let allText = [];
    for (const words of pages) {
      const anchors = words.filter(w => w.x >= 13 && w.x <= 26 && /^\d{8}$/.test(w.str)).map(w => [w.top, w.str]);
      const sorted = words.slice().sort((a, b) => a.top - b.top || a.x - b.x);
      allText.push(sorted.map(w => w.str).join(" "));
      if (!anchors.length) continue;
      const nearest = top => {
        let best = null;
        for (const a of anchors) { const d = Math.abs(a[0] - top); if (best === null || d < best[1]) best = [a[1], d]; }
        return best && best[1] <= 14 ? best[0] : null;
      };
      const acc = {};
      for (const a of anchors) acc[a[1]] = acc[a[1]] || { paren: null, num: null, cr: 0, name: [], appr: null, passfail: false };
      for (const w of sorted) {
        const code = nearest(w.top); if (!code) continue;
        const x = w.x, t = w.str;
        if (x >= 266 && x <= 308 && t.includes("(")) { if (acc[code].paren == null) acc[code].paren = parenGrade(t); }
        else if (x >= 228 && x <= 308 && t.toUpperCase().includes("APROBAD")) acc[code].passfail = true;
        else if (x >= 250 && x <= 278) { if (acc[code].num == null) acc[code].num = numGrade(t); }
        else if ((x >= 405 && x <= 422 || x >= 448 && x <= 466) && /^\d+$/.test(t.trim())) acc[code].cr += parseInt(t.trim());
        else if (x >= 58 && x <= 255) acc[code].name.push([x, t]);
        else if (x >= 370 && x <= 386 && (t === "S" || t === "N")) acc[code].appr = t;
      }
      for (const code in acc) {
        if (code in courses) continue;
        const a = acc[code]; order.push(code);
        const nm = a.name.sort((p, q) => p[0] - q[0]).map(p => p[1]).join(" ").trim();
        courses[code] = { grade: a.paren != null ? a.paren : a.num, credits: a.cr || null,
                          name: nm || null, passfail: a.passfail };
      }
    }
    const text = allText.join("\n");
    const passed = Object.keys(courses);
    const grades = {}, pdf_names = {}, passfail = [];
    for (const c of passed) {
      if (courses[c].grade != null) grades[c] = courses[c].grade;
      if (courses[c].name) pdf_names[c] = courses[c].name;
      if (courses[c].passfail && courses[c].grade == null) passfail.push(c);
    }
    let plan = O._detectPlanByOverlap(new Set(passed));
    if (!plan) { const seg = norm(text).split("DNI")[0]; const cands = seg.slice(-120).match(/[A-Z]{2}\d{2}/g); plan = cands ? cands[cands.length - 1] : null; }
    const mg = text.match(/[Pp]romedio acumulado\s*:?\s*([\d]+[.,][\d]+)/);
    let cumgpa = mg ? parseFloat(mg[1].replace(",", ".")) : null;
    const gvals = Object.values(grades);
    if (cumgpa == null && gvals.length) cumgpa = round(gvals.reduce((a, b) => a + b, 0) / gvals.length, 2);
    const mp = text.match(/[Pp]eriodos aprobados\s*:?\s*(\d+)/);
    const periods = mp ? parseInt(mp[1]) : null;
    const cumcred = passed.reduce((s, c) => s + (courses[c].credits || (CATALOG[c] ? CATALOG[c].credits : 3)), 0);
    const mn = text.match(/Alumno\s*:?\s*([A-ZÁÉÍÓÚÑ ]{4,})/);
    const name = mn ? mn[1].trim().replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()) : null;
    return { name, plan, passed: passed.slice().sort(), grades, pdf_names, passfail,
             cumgpa, cumcred: round(cumcred, 1), periods, sem_next: periods ? periods + 1 : null };
  };

  // browser entry: uses global pdfjsLib (loaded from CDN)
  O.parseTranscript = async function (arrayBuffer) {
    const pdfjsLib = global.pdfjsLib;
    const doc = await pdfjsLib.getDocument({ data: new Uint8Array(arrayBuffer) }).promise;
    const pages = [];
    for (let p = 1; p <= doc.numPages; p++) {
      const page = await doc.getPage(p);
      const tc = await page.getTextContent();
      pages.push(tc.items.filter(i => i.str && i.str.trim())
        .map(i => ({ str: i.str, x: i.transform[4], top: -i.transform[5] })));
    }
    return O.parseItems(pages);
  };

  // expose internals needed by the PDF parser
  O._detectPlanByOverlap = function (passed) {
    let best = null;
    for (const p in PLAN_COURSES) {
      const ov = PLAN_COURSES[p].filter(c => passed.has(c)).length;
      if (!best || ov > best[1]) best = [p, ov];
    }
    return best && best[1] >= 5 ? best[0] : null;
  };
  O._planNames = PLAN_NAMES; O._norm = norm; O._cs = cs;

  global.Oraculo = O;
})(typeof window !== "undefined" ? window : globalThis);
