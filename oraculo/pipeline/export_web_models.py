"""
Export the trained HistGBM models to a compact JSON the browser can evaluate
(static GitHub Pages build, no Python at runtime). Includes a SELF-VERIFICATION
gate: a from-scratch reimplementation must match sklearn to < 1e-6 before writing,
so the JS port (which mirrors the same walk) is guaranteed faithful.
"""
import os, json, warnings
warnings.filterwarnings("ignore")
import numpy as np, joblib

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(os.path.dirname(HERE), "model")
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "data", "models.json")

def fin(x):  # clamp ±inf thresholds to a large finite value (valid JSON; x<=1e30 ~ x<=inf)
    x = float(x)
    return 1e30 if x == float("inf") else (-1e30 if x == float("-inf") else round(x, 6))

def extract(hgb):
    trees = []
    for it in hgb._predictors:
        nd = it[0].nodes
        trees.append({
            "f": nd["feature_idx"].astype(int).tolist(),
            "t": [fin(x) for x in nd["num_threshold"]],
            "l": nd["left"].astype(int).tolist(),
            "r": nd["right"].astype(int).tolist(),
            "leaf": nd["is_leaf"].astype(int).tolist(),
            "v": [round(float(x), 7) for x in nd["value"]],
            "m": nd["missing_go_to_left"].astype(int).tolist(),
        })
    return trees, float(np.ravel(hgb._baseline_prediction)[0])

def walk(t, x):
    i = 0
    while not t["leaf"][i]:
        xv = x[t["f"][i]]
        if np.isnan(xv):
            i = t["l"][i] if t["m"][i] else t["r"][i]
        else:
            i = t["l"][i] if xv <= t["t"][i] else t["r"][i]
    return t["v"][i]

def raw(trees, base, x):
    return base + sum(walk(t, x) for t in trees)

def isotonic(x, xs, ys):
    return float(np.interp(x, xs, ys, left=ys[0], right=ys[-1]))

def main():
    clf = joblib.load(os.path.join(MODEL, "model.joblib"))
    reg = joblib.load(os.path.join(MODEL, "grade_model.joblib"))
    m = clf["model"]

    folds = []
    for cc in m.calibrated_classifiers_:
        trees, base = extract(cc.estimator)
        cal = cc.calibrators[0]
        folds.append({"trees": trees, "baseline": base,
                      "cal_x": [round(float(x), 6) for x in cal.X_thresholds_],
                      "cal_y": [round(float(x), 6) for x in cal.y_thresholds_]})
    gtrees, gbase = extract(reg["model"])

    # ---- determine calibration input (proba vs raw) by matching sklearn ----
    rng = np.random.default_rng(0)
    nf = len(clf["features"])
    X = rng.normal(2.5, 1.5, size=(400, nf))
    X[rng.random(X.shape) < 0.15] = np.nan          # inference has NaNs (age/sexF)
    sk = m.predict_proba(X)[:, 1]

    def my_clf(x, cal_input):
        ps = []
        for fd in folds:
            r = raw(fd["trees"], fd["baseline"], x)
            inp = 1 / (1 + np.exp(-r)) if cal_input == "proba" else r
            ps.append(isotonic(inp, fd["cal_x"], fd["cal_y"]))
        return float(np.mean(ps))

    best = None
    for ci in ("proba", "raw"):
        mine = np.array([my_clf(x, ci) for x in X])
        err = np.max(np.abs(mine - sk))
        print(f"  classifier cal_input={ci}: max|diff|={err:.2e}")
        if best is None or err < best[1]:
            best = (ci, err)
    cal_input, clf_err = best
    assert clf_err < 1e-4, f"classifier mismatch {clf_err}"  # rounding loss only

    # ---- verify regressor ----
    Xg = rng.normal(2.5, 1.5, size=(400, len(reg["features"])))
    Xg[rng.random(Xg.shape) < 0.15] = np.nan
    sk_g = reg["model"].predict(Xg)
    mine_g = np.array([gbase + sum(walk(t, x) for t in gtrees) for x in Xg])
    g_err = float(np.max(np.abs(mine_g - sk_g)))
    print(f"  regressor: max|diff|={g_err:.2e}")
    assert g_err < 1e-4, f"regressor mismatch {g_err}"

    out = {
        "fail": {"features": clf["features"], "folds": folds, "cal_input": cal_input,
                 "global_fail": clf["global_fail"]},
        "grade": {"features": reg["features"], "trees": gtrees, "baseline": gbase,
                  "resid_std": reg["resid_std"], "global_mean_grade": reg["global_mean_grade"]},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"), allow_nan=False)  # strict valid JSON
    mb = os.path.getsize(OUT) / 1e6
    print(f"VERIFIED (clf {clf_err:.1e}, reg {g_err:.1e}). cal_input={cal_input}. "
          f"-> {OUT}  ({mb:.1f} MB, gzips to ~1/5)")

if __name__ == "__main__":
    main()
