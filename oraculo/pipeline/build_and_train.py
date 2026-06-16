"""
Oraculo Risk Engine - feature build + train.

Reads the synthetic institutional panel (VW_ORACULO_PANEL_EN), engineers
leakage-aware features, trains a calibrated fail-probability classifier, and
exports the model + course-difficulty table + metrics for the app to serve.

Run:  python build_and_train.py
"""
import os, sys, json, time, math
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # oraculo/
PANEL = r"C:\Users\lucas\Downloads\Syndp_VW_ORACULO_PANEL_EN.xlsx"
CACHE = os.path.join(ROOT, "cache", "panel.pkl")
MODEL_DIR = os.path.join(ROOT, "model")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CACHE), exist_ok=True)

# ---- column indices in the headerless EN view ----
C_STU, C_CRS, C_ATT, C_PER = 0, 1, 4, 2          # student, course, period, attempt(col2)
C_GRADE, C_PASS, C_STATUS, C_PROG = 5, 6, 7, 8
C_COHORT, C_SEM, C_CUMCRED, C_TERMCRED = 9, 10, 11, 12
C_CUMGPA, C_SEX, C_BIRTH = 13, 14, 15
# note: col2 is attempt#, col4 is period string -> indices per profiling

NEEDED = {
    "stu": 0, "crs": 1, "att": 2, "per": 4, "grade": 5, "pass": 6,
    "status": 7, "prog": 8, "cohort": 9, "sem": 10, "cumcred": 11,
    "termcred": 12, "cumgpa": 13, "sex": 14, "birth": 15,
}

def period_idx(p):
    """'2024-2S' -> sortable int (year*2 + sem)."""
    try:
        y, s = p.split("-")
        return int(y) * 2 + (1 if s.startswith("1") else 2)
    except Exception:
        return -1

def load_panel():
    if os.path.exists(CACHE):
        print("[cache] loading", CACHE)
        return pd.read_pickle(CACHE)
    print("[stream] reading panel (one pass)...", flush=True)
    import openpyxl
    wb = openpyxl.load_workbook(PANEL, read_only=True, data_only=True)
    ws = wb.active
    cols = {k: [] for k in NEEDED}
    t = time.time()
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        for k, idx in NEEDED.items():
            cols[k].append(row[idx])
        if i % 200000 == 0 and i:
            print(f"  {i:,} rows  ({time.time()-t:.0f}s)", flush=True)
    df = pd.DataFrame(cols)
    print(f"[stream] {len(df):,} rows in {time.time()-t:.0f}s")
    df.to_pickle(CACHE)
    return df

def to_num(s):
    return pd.to_numeric(s, errors="coerce")

def main():
    df = load_panel()
    # --- types ---
    df["crs"] = df["crs"].astype(str)
    df["prog"] = df["prog"].astype(str)
    df["status"] = df["status"].astype(str)
    df["grade"] = to_num(df["grade"])
    df["pass"] = to_num(df["pass"])
    df["att"] = to_num(df["att"]).fillna(1)
    df["sem"] = to_num(df["sem"])
    df["cumcred"] = to_num(df["cumcred"])
    df["termcred"] = to_num(df["termcred"])
    df["cumgpa"] = to_num(df["cumgpa"])
    df["cohort"] = to_num(df["cohort"])
    df["birth"] = to_num(df["birth"])
    df["pidx"] = df["per"].map(period_idx)
    df["year"] = df["per"].str.slice(0, 4).pipe(to_num)
    df["age"] = (df["year"] - df["birth"]).where(lambda s: (s > 10) & (s < 80))
    df["sexF"] = (df["sex"] == "F").astype(int)
    df["area"] = df["crs"].str[:4]

    # IMPORTANT: sort + reindex BEFORE deriving any masks/cumulative features, so
    # boolean masks stay aligned to the (reordered) frame. (Deriving masks first
    # then re-sorting would scramble the temporal split by index label.)
    df = df.sort_values(["stu", "pidx"]).reset_index(drop=True)

    # --- target: graded attempts only (AP pass / RP,R fail) ---
    GRADED = df["status"].isin(["AP", "RP", "R"])
    df["fail"] = df["status"].isin(["RP", "R"]).astype(int)

    # --- temporal split cutoff ---
    CUT = period_idx("2025-2S")          # train < 2025-2S, test >= 2025-2S
    train_mask = GRADED & (df["pidx"] < CUT)
    test_mask = GRADED & (df["pidx"] >= CUT)
    print(f"graded={GRADED.sum():,}  train={train_mask.sum():,}  test={test_mask.sum():,}")

    # --- course difficulty stats from TRAIN ONLY (Bayesian shrink) ---
    g = df[train_mask].groupby("crs")
    cs = pd.DataFrame({
        "n": g.size(),
        "fail_rate_raw": g["fail"].mean(),
        "mean_grade": g["grade"].mean(),
    })
    # withdrawal rate uses all statuses for the course (A = retiro)
    allc = df.groupby("crs")
    cs["withdraw_rate"] = (df.assign(w=(df["status"] == "A").astype(int))
                             .groupby("crs")["w"].mean())
    GLOBAL_FAIL = df.loc[train_mask, "fail"].mean()
    A = 25.0                                   # shrink strength
    cs["fail_rate"] = (g["fail"].sum() + A * GLOBAL_FAIL) / (cs["n"] + A)
    cs["mean_grade"] = cs["mean_grade"].fillna(df.loc[train_mask, "grade"].mean())
    cs["withdraw_rate"] = cs["withdraw_rate"].fillna(0)
    cs = cs.fillna({"fail_rate": GLOBAL_FAIL})
    print(f"global fail rate (train) = {GLOBAL_FAIL:.3f};  {len(cs)} courses scored")

    # map difficulty back to every row
    df["c_fail_rate"] = df["crs"].map(cs["fail_rate"]).fillna(GLOBAL_FAIL)
    df["c_mean_grade"] = df["crs"].map(cs["mean_grade"])
    df["c_withdraw"] = df["crs"].map(cs["withdraw_rate"]).fillna(0)
    df["c_n"] = df["crs"].map(cs["n"]).fillna(0)

    # NOTE: raw co-load features (term credits / #co-enrolled) are intentionally
    # NOT used as model inputs. In the history, stronger students self-select into
    # heavier loads, so the observed load effect is negatively confounded
    # (heavy load -> *lower* observed fail). Using it would invert the product's
    # combination logic. The base model is purely P(fail | student, course); the
    # combination effect is applied as an explicit, correctly-signed adjustment
    # layer in the app (see engine.simulate).

    # --- leakage-free student history (matches what the transcript provides) ---
    gstu = df.groupby("stu")
    # overall prior GPA = expanding mean of strictly-earlier grades
    df["prior_gpa"] = (gstu["grade"].transform(lambda s: s.shift().fillna(0).cumsum()) /
                       gstu["grade"].transform(lambda s: s.shift().notna().cumsum()).replace(0, np.nan))
    df["prior_fail"] = gstu["fail"].transform(lambda s: s.shift().fillna(0).cumsum())
    df["is_retake"] = (df["att"] > 1).astype(int)
    # subject-specific prior performance (same course-code area = same subject family).
    # Evidence: within a fixed overall GPA, in-area history swings fail rate ~10x;
    # same-area GPA is individually as predictive as overall GPA (see exp_subject_aptitude).
    garea = df.groupby(["stu", "area"])
    df["area_gpa"] = (garea["grade"].transform(lambda s: s.shift().fillna(0).cumsum()) /
                      garea["grade"].transform(lambda s: s.shift().notna().cumsum()).replace(0, np.nan))
    df["area_n"] = garea["grade"].transform(lambda s: s.shift().notna().cumsum())  # how much in-area history exists

    FEATURES = [
        "c_fail_rate", "c_mean_grade", "c_n",
        "prior_gpa", "area_gpa", "area_n",
        "cumcred", "sem", "age", "sexF",
        "att", "is_retake", "prior_fail",
    ]

    Xtr = df.loc[train_mask, FEATURES].astype(float)
    ytr = df.loc[train_mask, "fail"].astype(int)
    Xte = df.loc[test_mask, FEATURES].astype(float)
    yte = df.loc[test_mask, "fail"].astype(int)

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

    base = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.1, random_state=42)
    clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
    print("[train] fitting calibrated HistGBM ...", flush=True)
    t = time.time()
    clf.fit(Xtr, ytr)
    print(f"[train] done in {time.time()-t:.0f}s")

    p = clf.predict_proba(Xte)[:, 1]
    base_rate = ytr.mean()
    metrics = {
        "auc": float(roc_auc_score(yte, p)),
        "brier": float(brier_score_loss(yte, p)),
        "brier_baseline": float(brier_score_loss(yte, np.full_like(p, base_rate))),
        "logloss": float(log_loss(yte, p)),
        "base_rate_train": float(base_rate),
        "base_rate_test": float(yte.mean()),
        "n_train": int(len(ytr)), "n_test": int(len(yte)),
        "features": FEATURES,
    }
    # calibration table (deciles)
    dfc = pd.DataFrame({"p": p, "y": yte.values})
    dfc["bin"] = pd.qcut(dfc["p"], 10, duplicates="drop")
    cal = dfc.groupby("bin", observed=True).agg(pred=("p", "mean"),
                                                obs=("y", "mean"),
                                                n=("y", "size"))
    metrics["calibration"] = [
        {"pred": round(r.pred, 3), "obs": round(r.obs, 3), "n": int(r.n)}
        for r in cal.itertuples()
    ]
    print("\n=== METRICS ===")
    print(f"AUC            {metrics['auc']:.4f}")
    print(f"Brier model    {metrics['brier']:.4f}  vs baseline {metrics['brier_baseline']:.4f}")
    print(f"LogLoss        {metrics['logloss']:.4f}")
    print(f"base rate      train {base_rate:.3f} / test {yte.mean():.3f}")
    print("calibration (pred -> obs):")
    for c in metrics["calibration"]:
        print(f"   {c['pred']:.3f} -> {c['obs']:.3f}  (n={c['n']})")

    # --- export ---
    import joblib
    joblib.dump({"model": clf, "features": FEATURES,
                 "global_fail": float(GLOBAL_FAIL)},
                os.path.join(MODEL_DIR, "model.joblib"))
    cs_out = cs.reset_index().rename(columns={"index": "crs"})
    cs_out.to_json(os.path.join(MODEL_DIR, "course_stats.json"),
                   orient="records")
    with open(os.path.join(MODEL_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    print("\n[export] model.joblib, course_stats.json, metrics.json ->", MODEL_DIR)

if __name__ == "__main__":
    main()
