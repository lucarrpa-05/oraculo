"""
Does course load actually hurt performance? The naive (between-student) view is
confounded: stronger students take heavier loads. We isolate the causal-ish
WITHIN-student effect (each student as their own control) and fit its shape.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # oraculo/
df = pd.read_pickle(os.path.join(ROOT, "cache", "panel.pkl"))
df["grade"] = pd.to_numeric(df["grade"], errors="coerce")
df["termcred"] = pd.to_numeric(df["termcred"], errors="coerce")
df["status"] = df["status"].astype(str)
G = df[df["status"].isin(["AP", "RP", "R"])].copy()

# term-level table: one row per (student, period)
term = (G.groupby(["stu", "per"])
          .agg(term_gpa=("grade", "mean"),
               n_courses=("grade", "size"),
               credits=("termcred", "median")).reset_index())
term = term[(term["credits"] > 0) & (term["credits"] <= 30) & (term["n_courses"] >= 1)]
print(f"{len(term):,} student-terms; {term['stu'].nunique():,} students")

# --- BETWEEN (naive, confounded): correlate credits vs term GPA across all terms
print("\nNAIVE between-student (confounded by ability):")
for lo, hi in [(0, 9), (9, 13), (13, 16), (16, 19), (19, 30)]:
    sub = term[(term["credits"] >= lo) & (term["credits"] < hi)]
    print(f"  {lo:2d}-{hi:2d} cr: term GPA {sub['term_gpa'].mean():.3f}  (n={len(sub):,})")

# --- WITHIN-student: subtract each student's own mean (removes ability)
g = term.groupby("stu")
term["gpa_dev"] = term["term_gpa"] - g["term_gpa"].transform("mean")
term["cred_dev"] = term["credits"] - g["credits"].transform("mean")
term["cred_c"] = term["credits"] - 15  # centered for the fit
multi = term[g["per"].transform("size") >= 2]  # students with >=2 terms
print(f"\nWITHIN-student (n={len(multi):,} terms from students with >=2 terms):")
print("  credits vs OWN-average GPA deviation:")
for lo, hi in [(0, 9), (9, 13), (13, 16), (16, 19), (19, 30)]:
    sub = multi[(multi["credits"] >= lo) & (multi["credits"] < hi)]
    if len(sub):
        print(f"   {lo:2d}-{hi:2d} cr: GPA dev {sub['gpa_dev'].mean():+.3f}  (n={len(sub):,})")

# --- fit shape: linear vs quadratic (convex?) on within-student deviations
import numpy.polynomial.polynomial as P
x = multi["cred_dev"].values; y = multi["gpa_dev"].values
b1 = np.polyfit(x, y, 1)
b2 = np.polyfit(x, y, 2)
print(f"\n  linear within-fit:    dGPA = {b1[0]:+.4f} * (credits - own_mean)")
print(f"  quadratic within-fit: dGPA = {b2[0]:+.5f}*x^2 {b2[1]:+.4f}*x   (x = credits-own_mean)")
print(f"  -> per +3 credits over your norm: ~{b1[0]*3:+.3f} GPA")
print(f"  -> per +9 credits over your norm: ~{b1[0]*9:+.3f} GPA (linear) "
      f"vs {b2[0]*81 + b2[1]*9:+.3f} (quadratic, convex)")

# absolute predicted term GPA vs total credits, holding student ability fixed at 4.0
print("\n  Implied term GPA for a 4.0-baseline student by load (quadratic within-fit):")
base = 4.0
for cr in [9, 12, 15, 18, 21, 24, 30]:
    xc = cr - term.groupby('stu')['credits'].mean().mean()  # dev from avg student's mean
    dev = b2[0]*xc*xc + b2[1]*xc
    print(f"   {cr:2d} cr: ~{base+dev:.2f}")
