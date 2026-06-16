"""
Difficulty + expected-grade model.

For a top student "will I fail" is uninformative; "how hard / how will it dent my
GPA" is. We build:
  1) intrinsic course difficulty (1-5) from the grade distribution
  2) a personalized expected-GRADE regressor  -> predicted grade for THIS student
  3) per-course difficulty = expected shortfall vs the student's own GPA + risk
  4) export grade_model.joblib + difficulty fields merged into course_stats.json
"""
import warnings; warnings.filterwarnings("ignore")
import os, json, numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "model")
df = pd.read_pickle(os.path.join(ROOT, "cache", "panel.pkl"))

def pidx(p):
    try: y, s = p.split("-"); return int(y)*2 + (1 if s.startswith("1") else 2)
    except: return -1

for c in ["grade", "sem", "cumcred", "att"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["crs"] = df["crs"].astype(str); df["status"] = df["status"].astype(str)
df["pidx"] = df["per"].map(pidx); df["area"] = df["crs"].str[:4]
df = df.sort_values(["stu", "pidx"]).reset_index(drop=True)
GRADED = df["status"].isin(["AP", "RP", "R"])
df["fail"] = df["status"].isin(["RP", "R"]).astype(int)
df["withdraw"] = (df["status"] == "A").astype(int)
CUT = pidx("2025-2S")
tr = GRADED & (df["pidx"] < CUT); te = GRADED & (df["pidx"] >= CUT)

# ---- course grade distribution (train only) ----
g = df[tr].groupby("crs")
cstat = pd.DataFrame({
    "n": g.size(),
    "mean_grade": g["grade"].mean(),
    "std_grade": g["grade"].std(),
    "p25_grade": g["grade"].quantile(0.25),
    "fail_rate": g["fail"].mean(),
})
wd = df.groupby("crs")["withdraw"].mean()
cstat["withdraw_rate"] = wd
GMEAN = df.loc[tr, "grade"].mean()
cstat["mean_grade"] = cstat["mean_grade"].fillna(GMEAN)
cstat["std_grade"] = cstat["std_grade"].fillna(df.loc[tr, "grade"].std())
cstat = cstat.fillna(0)

# intrinsic difficulty score: harder = lower mean grade, more fails/withdraws, more spread
def z(s): return (s - s[cstat["n"] >= 30].mean()) / (s[cstat["n"] >= 30].std() + 1e-9)
cstat["difficulty_raw"] = (-1.1 * z(cstat["mean_grade"])
                           + 0.7 * z(cstat["fail_rate"])
                           + 0.3 * z(cstat["withdraw_rate"])
                           + 0.3 * z(cstat["std_grade"]))
# map to 1..5 stars by percentile among real (n>=30) courses
ref = cstat.loc[cstat["n"] >= 30, "difficulty_raw"]
qs = ref.quantile([0.2, 0.4, 0.6, 0.8]).values
cstat["stars"] = 1 + np.digitize(cstat["difficulty_raw"], qs)

# ---- features for the grade regressor (leakage-free, same as classifier) ----
df["c_mean_grade"] = df["crs"].map(cstat["mean_grade"]).fillna(GMEAN)
df["c_std_grade"] = df["crs"].map(cstat["std_grade"])
df["c_fail_rate"] = df["crs"].map(cstat["fail_rate"]).fillna(df.loc[tr, "fail"].mean())
df["c_n"] = df["crs"].map(cstat["n"]).fillna(0)
gstu = df.groupby("stu")
df["prior_gpa"] = (gstu["grade"].transform(lambda s: s.shift().fillna(0).cumsum()) /
                   gstu["grade"].transform(lambda s: s.shift().notna().cumsum()).replace(0, np.nan))
ga = df.groupby(["stu", "area"])
df["area_gpa"] = (ga["grade"].transform(lambda s: s.shift().fillna(0).cumsum()) /
                  ga["grade"].transform(lambda s: s.shift().notna().cumsum()).replace(0, np.nan))
df["area_n"] = ga["grade"].transform(lambda s: s.shift().notna().cumsum())
df["is_retake"] = (df["att"] > 1).astype(int)

FEATS = ["c_mean_grade", "c_std_grade", "c_fail_rate", "c_n",
         "prior_gpa", "area_gpa", "area_n", "cumcred", "sem", "att", "is_retake"]

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
reg = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0, early_stopping=True, random_state=0)
reg.fit(df.loc[tr, FEATS].astype(float), df.loc[tr, "grade"])
pred = reg.predict(df.loc[te, FEATS].astype(float))
mae = mean_absolute_error(df.loc[te, "grade"], pred)
# naive baselines
naive_course = df.loc[te, "c_mean_grade"]
naive_gpa = df.loc[te, "prior_gpa"].fillna(GMEAN)
print(f"Grade regressor (predict 0-5 grade), temporal holdout n={te.sum():,}")
print(f"  MAE model         {mae:.3f}")
print(f"  MAE course-mean   {mean_absolute_error(df.loc[te,'grade'], naive_course):.3f}")
print(f"  MAE prior-GPA     {mean_absolute_error(df.loc[te,'grade'], naive_gpa):.3f}")
print(f"  R2  model         {r2_score(df.loc[te,'grade'], pred):.3f}")

# residual std (uncertainty of a predicted grade) -> for difficulty/uncertainty bands
resid = df.loc[tr, "grade"] - reg.predict(df.loc[tr, FEATS].astype(float))
print(f"  residual std      {resid.std():.3f}")

# show intrinsic difficulty examples
print("\nIntrinsic difficulty (stars) examples:")
ex = cstat[cstat["n"] >= 50].copy()
for code in ["11310010", "11310003", "11310031", "11310032", "11310030", "11320003"]:
    if code in cstat.index:
        r = cstat.loc[code]
        print(f"  {code}: {'★'*int(r['stars'])}{'☆'*(5-int(r['stars']))} mean={r['mean_grade']:.2f} fail={r['fail_rate']*100:.0f}% n={int(r['n'])}")

# ---- export ----
import joblib
joblib.dump({"model": reg, "features": FEATS, "resid_std": float(resid.std()),
             "global_mean_grade": float(GMEAN)},
            os.path.join(MODEL_DIR, "grade_model.joblib"))
# merge difficulty into course_stats.json (keep classifier's fail_rate)
existing = {r["crs"]: r for r in json.load(open(os.path.join(MODEL_DIR, "course_stats.json"), encoding="utf-8"))}
out = []
for code, r in cstat.iterrows():
    e = existing.get(code, {})
    e.update({"crs": code, "mean_grade": round(r["mean_grade"], 3),
              "std_grade": round(r["std_grade"], 3), "p25_grade": round(r["p25_grade"], 3),
              "withdraw_rate": round(r["withdraw_rate"], 4), "stars": int(r["stars"]),
              "difficulty_raw": round(float(r["difficulty_raw"]), 3), "n": int(r["n"])})
    out.append(e)
json.dump(out, open(os.path.join(MODEL_DIR, "course_stats.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n[export] grade_model.joblib + difficulty merged into course_stats.json ({len(out)} courses)")
print("star distribution:", cstat[cstat["n"]>=30]["stars"].value_counts().sort_index().to_dict())
