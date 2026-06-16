"""
Schedule conflict solver — the "can I take these together?" engine.

Each course offers SECTIONS (grupos); a section is a set of weekly time SLOTS
(día + [inicio,fin) in minutes). Two sections conflict if any of their slots overlap
on the same day. Picking one section per chosen course with no pairwise conflict is a
small constraint-satisfaction problem — we solve it by backtracking (and report the
exact blocking pair when infeasible).
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
SCHED_PATH = os.path.join(os.path.dirname(HERE), "model", "schedules.json")
SCHEDULES = json.load(open(SCHED_PATH, encoding="utf-8")) if os.path.exists(SCHED_PATH) else {}
IS_SAMPLE = any(v.get("sample") for v in SCHEDULES.values())

def has_schedule(code):
    s = SCHEDULES.get(code)
    return bool(s and s.get("sections"))

def sections(code):
    return SCHEDULES.get(code, {}).get("sections", [])

def _slots_overlap(a, b):
    return a["dia"] == b["dia"] and a["inicio"] < b["fin"] and b["inicio"] < a["fin"]

def sections_conflict(sa, sb):
    return any(_slots_overlap(x, y) for x in sa["slots"] for y in sb["slots"])

def _pair_label(code, sec):
    g = sec.get("grupo")
    return f"{code} G{g}"

def solve(codes):
    """Find one section per course with no time conflicts.
    Returns {feasible, assignment:[{code,section}], conflicts:[{a,b,reason}], scheduled:[codes], unscheduled:[codes]}."""
    scheduled = [c for c in codes if has_schedule(c)]
    unscheduled = [c for c in codes if not has_schedule(c)]
    opts = {c: sections(c) for c in scheduled}

    # hard-impossible pairs: every section of A conflicts with every section of B
    conflicts = []
    for i, a in enumerate(scheduled):
        for b in scheduled[i + 1:]:
            if all(sections_conflict(sa, sb) for sa in opts[a] for sb in opts[b]):
                conflicts.append({"a": a, "b": b,
                                  "reason": "todas las secciones se cruzan en horario"})

    # backtracking search for a conflict-free assignment
    order = sorted(scheduled, key=lambda c: len(opts[c]))   # fewest options first
    chosen = {}

    def compatible(code, sec):
        return all(not sections_conflict(sec, chosen[o]) for o in chosen)

    def bt(idx):
        if idx == len(order):
            return True
        c = order[idx]
        for sec in opts[c]:
            if compatible(c, sec):
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
        "is_sample": IS_SAMPLE,
        "have_schedules": bool(SCHEDULES),
    }

def pair_feasible(code_a, code_b):
    """Can these two be taken together at all (some non-conflicting section pair)?"""
    if not (has_schedule(code_a) and has_schedule(code_b)):
        return True
    return any(not sections_conflict(sa, sb)
               for sa in sections(code_a) for sb in sections(code_b))
