"""
Derive per-program study plans + prerequisite graphs from the panel itself
(generalizes to all 333 programs; no hand-coded mallas, no course names needed).

For each program (col8):
  - core (required) courses   = taken by >=40% of the program's students
  - elective courses          = taken by 5-40%
  - typical semester per course (median of the student's semester when taken)
  - prerequisites via PRECEDENCE inference: A is a prereq of B if students who
    enroll B have almost always PASSED A in an earlier period first.
Exports model/plans.json.
"""
import warnings; warnings.filterwarnings("ignore")
import os, json, numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_pickle(os.path.join(ROOT, "cache", "panel.pkl"))
def pidx(p):
    try: y, s = p.split("-"); return int(y)*2 + (1 if s.startswith("1") else 2)
    except: return -1
df["crs"] = df["crs"].astype(str); df["prog"] = df["prog"].astype(str)
df["status"] = df["status"].astype(str); df["sem"] = pd.to_numeric(df["sem"], errors="coerce")
df["pidx"] = df["per"].map(pidx)
df["passed"] = (df["status"] == "AP")

# first enrollment / first pass period per (student, course)
enr = df.groupby(["stu", "crs"])["pidx"].min().rename("enr")
pas = df[df["passed"]].groupby(["stu", "crs"])["pidx"].min().rename("pas")
sp = pd.concat([enr, pas], axis=1).reset_index()
# student's program (modal)
stu_prog = df.groupby("stu")["prog"].agg(lambda s: s.value_counts().index[0])
sp["prog"] = sp["stu"].map(stu_prog)

MIN_STUDENTS = 30          # ignore tiny programs
RATIO = 0.85               # precedence threshold for a prereq edge
SUPPORT = 20               # min co-enrollment support
plans = {}

for prog, pg in sp.groupby("prog"):
    students = pg["stu"].nunique()
    if students < MIN_STUDENTS:
        continue
    course_students = pg.groupby("crs")["stu"].nunique()
    freq = (course_students / students)
    typ_sem = df[df["prog"] == prog].groupby("crs")["sem"].median()
    core = sorted(freq[freq >= 0.40].index.tolist())
    elective = sorted(freq[(freq >= 0.05) & (freq < 0.40)].index.tolist())
    # NOTE: hard prereqs are NOT inferred from precedence (it cannot separate a true
    # prerequisite from "just taken earlier in the standard sequence" — e.g. it tagged
    # every semester-1 course as a prereq of Calculo 2). The engine hard-gates on
    # reliable signals only (name sequences + MACC official malla) and uses typ_sem
    # below for soft ordering.
    plans[prog] = {
        "n_students": int(students),
        "core": core,
        "elective": elective,
        "typ_sem": {c: (int(typ_sem[c]) if pd.notna(typ_sem.get(c)) else None) for c in core + elective},
        "freq": {c: round(float(freq[c]), 3) for c in core + elective},
    }

json.dump(plans, open(os.path.join(ROOT, "model", "plans.json"), "w", encoding="utf-8"),
          ensure_ascii=False)
print(f"plans.json: {len(plans)} programs")
for code in ["MA03", "PS04", "EN01", "JU03", "NI03"]:
    if code in plans:
        p = plans[code]
        print(f"  {code}: {p['n_students']} stu, core={len(p['core'])} elective={len(p['elective'])}")
