"""
Rebuild every model artifact from scratch, in dependency order.

  build_and_train  -> cache/panel.pkl (first run, from the source .xlsx),
                      model/model.joblib, course_stats.json, metrics.json
  build_difficulty -> model/grade_model.joblib  (+ merges difficulty into course_stats)
  build_catalog    -> model/catalog.json        (names/credits/prereqs from data/Cursos)
  build_plans      -> model/plans.json          (per-program core/elective/typ_sem)

Course names come from data/url_catalog.json (scraped from the Rosario academic-guide
API). To refresh it first:  python pipeline/scrape_catalog.py   (network; optional —
build_catalog falls back to data/Cursos if the scrape file is absent).

Usage:  python pipeline/run_all.py
"""
import subprocess, sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ["build_and_train.py", "build_difficulty.py", "build_catalog.py", "build_plans.py"]

env = dict(os.environ, PYTHONIOENCODING="utf-8")
for s in STEPS:
    print(f"\n{'='*60}\n  {s}\n{'='*60}", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, s)], env=env)
    if r.returncode != 0:
        print(f"FAILED at {s}"); sys.exit(1)
    print(f"  ({time.time()-t:.0f}s)")
print("\nAll artifacts rebuilt. Start the app:  python app/server.py")
