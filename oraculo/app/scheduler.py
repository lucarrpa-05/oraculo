"""
Schedule conflict solver — the "can I take these together?" engine.

Schedules are PLAN-SPECIFIC, so everything is keyed by the student's plan:
SCHEDULES[plan][code] = {period, grupos:[...]}. A student enrolls in one GRUPO per course;
a grupo bundles that group's weekly time SLOTS across all its activities (teórica +
práctica/laboratorio). Two grupos conflict if any of their slots overlap on the same day.
Picking one grupo per chosen course with no pairwise conflict is a small CSP — solved by
backtracking (and we report the exact blocking pair when infeasible). The caller may PIN a
course to a specific grupo number; the search respects pins.
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
SCHED_PATH = os.path.join(os.path.dirname(HERE), "model", "schedules.json")
SCHEDULES = json.load(open(SCHED_PATH, encoding="utf-8")) if os.path.exists(SCHED_PATH) else {}
# legacy/sample flag: real per-plan data has no "sample" marker
IS_SAMPLE = any(isinstance(v, dict) and v.get("sample") for v in SCHEDULES.values())

def _plan_sched(plan):
    return SCHEDULES.get(plan, {}) if plan else {}

def grupos(code, plan):
    return _plan_sched(plan).get(code, {}).get("grupos", [])

def has_schedule(code, plan):
    return bool(grupos(code, plan))

def _slots_overlap(a, b):
    return a["dia"] == b["dia"] and a["inicio"] < b["fin"] and b["inicio"] < a["fin"]

def grupos_conflict(ga, gb):
    return any(_slots_overlap(x, y) for x in ga["slots"] for y in gb["slots"])

def solve(codes, plan=None, pins=None):
    """Find one grupo per course with no time conflicts (respecting `pins`: {code: grupo#}).
    Returns {feasible, assignment:[{code,section}], conflicts:[{a,b,reason}], scheduled, unscheduled}."""
    pins = pins or {}
    scheduled = [c for c in codes if has_schedule(c, plan)]
    unscheduled = [c for c in codes if not has_schedule(c, plan)]

    def options(c):
        gs = grupos(c, plan)
        if c in pins:                                   # honor a user-pinned grupo
            pinned = [g for g in gs if g.get("grupo") == pins[c]]
            if pinned:
                return pinned
        return gs

    opts = {c: options(c) for c in scheduled}

    # hard-impossible pairs: every grupo of A conflicts with every grupo of B
    conflicts = []
    for i, a in enumerate(scheduled):
        for b in scheduled[i + 1:]:
            if opts[a] and opts[b] and all(grupos_conflict(ga, gb) for ga in opts[a] for gb in opts[b]):
                conflicts.append({"a": a, "b": b,
                                  "reason": "todas las secciones se cruzan en horario"})

    order = sorted(scheduled, key=lambda c: len(opts[c]))   # fewest options first
    chosen = {}

    def compatible(sec):
        return all(not grupos_conflict(sec, chosen[o]) for o in chosen)

    def bt(idx):
        if idx == len(order):
            return True
        c = order[idx]
        for sec in opts[c]:
            if compatible(sec):
                chosen[c] = sec
                if bt(idx + 1):
                    return True
                del chosen[c]
        return False

    feasible = bt(0)
    assignment = [{"code": c, "section": chosen[c]} for c in order] if feasible else []
    return {
        "feasible": feasible,
        "assignment": assignment,
        "conflicts": conflicts,
        "scheduled": scheduled,
        "unscheduled": unscheduled,
        # all grupos per scheduled course, so the UI can show alternatives the user can switch to
        "options": {c: opts[c] for c in scheduled},
        "is_sample": IS_SAMPLE,
        "have_schedules": bool(SCHEDULES),
    }

def pair_feasible(code_a, code_b, plan=None):
    """Can these two be taken together at all (some non-conflicting grupo pair)?"""
    if not (has_schedule(code_a, plan) and has_schedule(code_b, plan)):
        return True
    return any(not grupos_conflict(ga, gb)
               for ga in grupos(code_a, plan) for gb in grupos(code_b, plan))
