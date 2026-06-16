"""
Experiment: does subject-specific prior performance add signal beyond overall GPA?
Compares temporal-holdout AUC of: course-only / +overall GPA / +same-area GPA,
and shows fail rate by area-GPA within fixed overall-GPA bands.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, os
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, log_loss

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # oraculo/
df = pd.read_pickle(os.path.join(ROOT, "cache", "panel.pkl"))

def pidx(p):
    try: y,s=p.split("-"); return int(y)*2+(1 if s.startswith("1") else 2)
    except: return -1
for c in ["grade","sem","cumcred","att"]:
    df[c]=pd.to_numeric(df[c],errors="coerce")
df["crs"]=df["crs"].astype(str); df["status"]=df["status"].astype(str)
df["pidx"]=df["per"].map(pidx); df["area"]=df["crs"].str[:4]
GRADED=df["status"].isin(["AP","RP","R"]); df["fail"]=df["status"].isin(["RP","R"]).astype(int)
CUT=pidx("2025-2S")
df=df.sort_values(["stu","pidx"]).reset_index(drop=True)

# course difficulty (train-only, shrunk)
tr0=GRADED&(df["pidx"]<CUT); g=df[tr0].groupby("crs")
gf=df[tr0]["fail"].mean()
cs=(g["fail"].sum()+25*gf)/(g.size()+25)
df["c_fail_rate"]=df["crs"].map(cs).fillna(gf)
df["c_mean_grade"]=df["crs"].map(g["grade"].mean())

# overall prior GPA (leakage-free)
gs=df.groupby("stu")
df["prior_gpa"]=(gs["grade"].transform(lambda s:s.shift().fillna(0).cumsum())/
                 gs["grade"].transform(lambda s:s.shift().notna().cumsum()).replace(0,np.nan))
# same-AREA prior GPA (leakage-free)
ga=df.groupby(["stu","area"])
df["area_gpa"]=(ga["grade"].transform(lambda s:s.shift().fillna(0).cumsum())/
                ga["grade"].transform(lambda s:s.shift().notna().cumsum()).replace(0,np.nan))
df["area_n"]=ga["grade"].transform(lambda s:s.shift().notna().cumsum())  # how many prior in-area

tr=GRADED&(df["pidx"]<CUT); te=GRADED&(df["pidx"]>=CUT)
def run(feats,label):
    m=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,min_samples_leaf=200,
        max_leaf_nodes=31,l2_regularization=1.0,early_stopping=True,random_state=0)
    m.fit(df.loc[tr,feats].astype(float),df.loc[tr,"fail"])
    p=m.predict_proba(df.loc[te,feats].astype(float))[:,1]
    auc=roc_auc_score(df.loc[te,"fail"],p); ll=log_loss(df.loc[te,"fail"],p)
    print(f"  {label:32s} AUC={auc:.4f}  logloss={ll:.4f}")
    return m,p

base=["c_fail_rate","c_mean_grade","sem","cumcred","att"]
print("Temporal holdout (test = 2025-2S+, n=%d):"%te.sum())
run(base,"course+demographics only")
run(base+["prior_gpa"],"+ overall GPA")
m3,p3=run(base+["area_gpa","area_n"],"+ same-area GPA (no overall)")
run(base+["prior_gpa","area_gpa","area_n"],"+ overall GPA + same-area GPA")

# permutation importance on the full model
from sklearn.inspection import permutation_importance
feats=base+["prior_gpa","area_gpa","area_n"]
mF=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,min_samples_leaf=200,
    max_leaf_nodes=31,l2_regularization=1.0,early_stopping=True,random_state=0).fit(
    df.loc[tr,feats].astype(float),df.loc[tr,"fail"])
samp=df.loc[te].sample(20000,random_state=1)
pi=permutation_importance(mF,samp[feats].astype(float),samp["fail"],n_repeats=4,
    scoring="neg_log_loss",random_state=0)
print("\nPermutation importance (drop in logloss):")
for f,v in sorted(zip(feats,pi.importances_mean),key=lambda x:-x[1]):
    print(f"  {f:16s} {v:.4f}")

# the decisive cut: within narrow overall-GPA bands, does area_gpa still separate?
print("\nFail rate by same-area GPA, WITHIN fixed overall-GPA bands (test set):")
d=df.loc[te & df["area_gpa"].notna() & df["prior_gpa"].notna()].copy()
d["gpa_band"]=pd.cut(d["prior_gpa"],[0,3.3,3.7,4.1,5.01],labels=["<3.3","3.3-3.7","3.7-4.1","4.1+"])
d["area_band"]=pd.cut(d["area_gpa"],[0,3.5,4.0,5.01],labels=["area<3.5","area3.5-4","area4+"])
piv=d.pivot_table(index="gpa_band",columns="area_band",values="fail",aggfunc="mean",observed=True)
print((piv*100).round(1).to_string())
print("\n(reading across each row: same overall GPA, lower in-area history -> higher fail %)")
