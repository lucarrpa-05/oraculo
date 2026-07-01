"""
Scrape the official TIPOLOGIA of every (plan, course) from the Rosario academic guide and
write model/tipologias.json. This is what tells Obligatoria from Complementaria from
Proyecto Fin de Carrera / Electiva -- the classification the malla PDF (and therefore
malla_plan.json) does NOT carry, which is why complementarias were missing from Oraculo.

Source (same public API + self-refreshing tokenApiPublic as scrape_catalog):
  GET /asignaturas2?tipo=PSC&tipoElectiva=PLAN&planEstudio=<cod>         -> the plan's courses
  GET /asignaturaDetalle?codigo=<c>&planEstudio=<cod>&opcionDetalle=DetalleAsignatura
        -> {data:[{codAsignatura, creditos, tipologias:[{codTipologia, descripcion}], ...}]}
     tipologia is PLAN-SPECIFIC: the SAME code is Obligatoria in one plan, Complementaria in
     another. So we key by (plan, code), exactly like schedules.

Output:
  model/tipologias.json
    {plan: {code: {"t": "<codTipologia>", "label": "<descripcion>",
                   "nombre": <str>, "creditos": <float>}}}
  codTipologia seen: T OBLIGATORIA · C COMPLEMENTARIA · L ELECTIVA ·
                     P PROYECTO FIN DE CARRERA  (empty/None -> "?" OTRA)

Run:  python pipeline/build_tipologias.py            (full, all pregrado plans)
      python pipeline/build_tipologias.py --merge    (keep prior results, only fill gaps)
      python pipeline/build_tipologias.py EC04 FI01  (only these plans)
"""
import os, re, sys, json, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

SITE = "https://guiaacademica.urosario.edu.co"
API = "https://guiaacademicabackend.azurewebsites.net/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Oraculo-tipologias-sync"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "model", "tipologias.json")

class _Transient(Exception):
    pass

def _raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()

def _get(url, token, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": "Bearer " + token})
    for a in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(0.8 * (a + 1)); continue
            return None                       # 4xx -> no data, not transient
        except Exception:
            time.sleep(0.8 * (a + 1))
    raise _Transient(url)

def get_token():
    html = _raw(SITE + "/").decode("utf-8", "ignore")
    m = re.search(r'src="(/main\.[a-f0-9]+\.js)"', html)
    js = _raw(SITE + m.group(1)).decode("utf-8", "ignore")
    return re.search(r"tokenApiPublic:\s*'([^']+)'", js).group(1)

def plan_courses(token, plan):
    q = urllib.parse.urlencode({"tipo": "PSC", "tipoElectiva": "PLAN", "planEstudio": plan})
    d = _get(f"{API}/asignaturas2?{q}", token)
    return (d or {}).get("data") or []

def course_tipologia(token, plan, code):
    q = urllib.parse.urlencode({"codigo": code, "planEstudio": plan,
                                "opcionDetalle": "DetalleAsignatura"})
    d = _get(f"{API}/asignaturaDetalle?{q}", token)
    data = (d or {}).get("data") or []
    if not data:
        return None
    ts = data[0].get("tipologias") or []
    if not ts:
        return {"t": "?", "label": "OTRA"}
    t = ts[0]
    return {"t": t.get("codTipologia") or "?", "label": t.get("descripcion") or "OTRA"}

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    merge = "--merge" in sys.argv
    token = get_token()
    print("token acquired (%d chars)" % len(token))

    plans = [p["codPlan"] for p in _get(f"{API}/planes?tipo=PSC", token)["data"]]
    if args:
        plans = [p for p in plans if p in args]
    print(f"{len(plans)} plans to scrape")

    out = {}
    if merge and os.path.isfile(OUT):
        out = json.load(open(OUT, encoding="utf-8"))
        print(f"merge: {len(out)} plans already on disk")

    stat = {"ok": 0, "fail": 0}
    for i, plan in enumerate(plans, 1):
        try:
            courses = plan_courses(token, plan)
        except _Transient:
            print(f"  [{i:2d}/{len(plans)}] {plan}: list failed (kept existing)"); stat["fail"] += 1; continue
        recs = {}
        def work(c):
            code = str(c["codAsignatura"])
            try:
                tp = course_tipologia(token, plan, code)
            except _Transient:
                return code, None
            if tp is None:
                tp = {"t": "?", "label": "OTRA"}
            tp["nombre"] = c["nombre"]
            tp["creditos"] = c.get("creditos")
            return code, tp
        with ThreadPoolExecutor(8) as ex:
            for code, tp in ex.map(work, courses):
                if tp:
                    recs[code] = tp
        if recs:
            out[plan] = recs
            stat["ok"] += 1
        from collections import Counter
        dist = Counter(v["t"] for v in recs.values())
        print(f"  [{i:2d}/{len(plans)}] {plan:5s} {len(recs):3d} cursos  {dict(dist)}")
        time.sleep(0.2)

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ncomp = sum(1 for p in out.values() for v in p.values() if v["t"] == "C")
    print(f"\n-> {OUT}\n   {len(out)} plans · {ncomp} complementaria rows · ok={stat['ok']} fail={stat['fail']}")

if __name__ == "__main__":
    main()
