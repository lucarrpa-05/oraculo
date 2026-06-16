"""
Scrape the official course catalog from the Universidad del Rosario academic guide
(guiaacademica.urosario.edu.co) public API. Fills the código->nombre gap that
data/Cursos only covered for 11 programs.

Flow (reverse-engineered from the SPA bundle):
  GET  /                      -> find main.<hash>.js
  (regex tokenApiPublic)      -> public Bearer JWT (self-refreshes if rotated)
  GET  api/planes?tipo=PSC                                  -> 54 pregrado plans
  GET  api/asignaturas2?tipo=PSC&tipoElectiva=PLAN&planEstudio=<codPlan> -> courses

Output (UTF-8):
  data/url_catalog.json   {codPlan: {nombrePlan, courses:[{codAsignatura,nombre,creditos,tipoElectiva}]}}
"""
import os, re, json, time, urllib.request, urllib.parse

SITE = "https://guiaacademica.urosario.edu.co"
API = "https://guiaacademicabackend.azurewebsites.net/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Oraculo-catalog-sync"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Webpage/
OUT = os.path.join(ROOT, "data", "url_catalog.json")

def _get(url, token=None, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        b = r.read()
    return b if raw else json.loads(b.decode("utf-8"))

def get_token():
    html = _get(SITE + "/", raw=True).decode("utf-8", "ignore")
    m = re.search(r'src="(/main\.[a-f0-9]+\.js)"', html)
    js = _get(SITE + m.group(1), raw=True).decode("utf-8", "ignore")
    return re.search(r"tokenApiPublic:\s*'([^']+)'", js).group(1)

def main():
    token = get_token()
    print("token acquired (%d chars)" % len(token))
    plans = _get(f"{API}/planes?tipo=PSC", token)["data"]
    print(f"{len(plans)} pregrado plans")

    catalog = {}
    for i, p in enumerate(plans, 1):
        cod = p["codPlan"]
        q = urllib.parse.urlencode({"tipo": "PSC", "tipoElectiva": "PLAN", "planEstudio": cod})
        try:
            courses = _get(f"{API}/asignaturas2?{q}", token).get("data") or []
        except Exception as e:
            print(f"  ! {cod} failed: {e}"); courses = []
        catalog[cod] = {
            "nombrePlan": p["nombrePlan"],
            "courses": [{"codAsignatura": str(c["codAsignatura"]), "nombre": c["nombre"],
                         "creditos": c.get("creditos"), "tipoElectiva": c.get("tipoElectiva")}
                        for c in courses],
        }
        print(f"  [{i:2d}/{len(plans)}] {cod:5s} {p['nombrePlan'][:38]:38s} {len(courses)} cursos")
        time.sleep(0.25)   # be polite

    # university-wide elective pools (named courses outside any single plan)
    for pool, label in [("GEN", "ELECTIVAS GENERALES"), ("HM", "ELECTIVAS HM")]:
        q = urllib.parse.urlencode({"tipo": "PSC", "tipoElectiva": pool})
        try:
            courses = _get(f"{API}/asignaturas2?{q}", token).get("data") or []
        except Exception as e:
            print(f"  ! pool {pool} failed: {e}"); courses = []
        catalog[f"__POOL_{pool}__"] = {
            "nombrePlan": label,
            "courses": [{"codAsignatura": str(c["codAsignatura"]), "nombre": c["nombre"],
                         "creditos": c.get("creditos"), "tipoElectiva": pool} for c in courses],
        }
        print(f"  [pool] {pool:5s} {label:38s} {len(courses)} cursos")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(catalog, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_codes = len({c["codAsignatura"] for p in catalog.values() for c in p["courses"]})
    print(f"\n-> {OUT}\n   {len(catalog)} plans, {n_codes} distinct course codes")

if __name__ == "__main__":
    main()
