"""
Scrape REAL per-section class schedules from the Rosario guide API (2026-2S, live).

Chain per course (Bearer tokenApiPublic, self-refreshed):
  asignaturaDetalle?codigo=C&opcionDetalle=DetalleActividad&planEstudio=P  -> actividades (codActividad)
  ...&opcionDetalle=DetalleFecha&codActividad=A                            -> offering period (fechaInicio/Fin)
  ...&opcionDetalle=DetalleGrupo&codActividad=A                            -> grupos (codGrupo, grupo#, modalidad)
  ...&opcionDetalle=DetalleHorario&codActividad=A&codGrupo=G&fechaIni=..&fechaFin=..
        -> the schedule: dia/horaInicio/horaFin/sede/aula/profesor/capacidad   (needs the date range!)

Output: model/schedules.json
  { code: {plan, period, sections:[{grupo,codGrupo,actividad,profesor,modalidad,capacidad,slots:[{dia,inicio,fin,sede,aula,profesor}]}]} }

Usage:  python scrape_schedules.py            # all current-plan courses (url_catalog)
        python scrape_schedules.py MA03 PS04  # only these plans
"""
import os, sys, json, time, urllib.request, urllib.parse
import scrape_catalog as cat

API = "https://guiaacademicabackend.azurewebsites.net/api"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_CATALOG = os.path.join(os.path.dirname(ROOT), "data", "url_catalog.json")
OUT = os.path.join(ROOT, "model", "schedules.json")

def _get(tok, **kw):
    q = urllib.parse.urlencode(kw)
    req = urllib.request.Request(f"{API}/asignaturaDetalle?{q}", headers={"Authorization": "Bearer " + tok})
    for _ in range(2):                                   # one retry on transient failure
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r).get("data")
        except urllib.error.HTTPError:
            return None
        except Exception:
            time.sleep(0.5)
    return None

def _hhmm(s):
    try:
        h, m = str(s).split(":")[:2]; return int(h) * 60 + int(m)
    except Exception:
        return None

def scrape_course(tok, code, plan):
    acts = _get(tok, codigo=code, opcionDetalle="DetalleActividad", planEstudio=plan) or []
    sections, period = [], None
    for a in acts:
        ca = a.get("codActividad")
        fecha = _get(tok, codigo=code, opcionDetalle="DetalleFecha", planEstudio=plan, codActividad=ca) or []
        if not fecha:
            continue
        fi, ff = fecha[0].get("fechaInicio"), fecha[0].get("fechaFin")
        period = {"inicio": fi, "fin": ff}
        grupos = _get(tok, codigo=code, opcionDetalle="DetalleGrupo", planEstudio=plan, codActividad=ca) or []
        for g in grupos:
            cg = g.get("codGrupo")
            hor = _get(tok, codigo=code, opcionDetalle="DetalleHorario", planEstudio=plan,
                       codActividad=ca, codGrupo=cg, fechaIni=fi, fechaFin=ff) or []
            slots = [{"dia": h.get("dia"), "inicio": _hhmm(h.get("horaInicio")), "fin": _hhmm(h.get("horaFin")),
                      "sede": h.get("sede"), "aula": None if h.get("aula") in (None, "N/A") else h.get("aula"),
                      "profesor": None if h.get("profesor") in (None, "N/A") else h.get("profesor")}
                     for h in hor if h.get("dia") and _hhmm(h.get("horaInicio")) is not None]
            if not slots:
                continue
            prof = next((s["profesor"] for s in slots if s["profesor"]), None)
            mod = g.get("modalidad")
            sections.append({
                "grupo": g.get("grupo"), "codGrupo": cg, "actividad": a.get("claseActividad"),
                "profesor": prof, "capacidad": (hor[0].get("capacidad") if hor else None),
                "modalidad": mod.get("descCorta") if isinstance(mod, dict) else mod,
                "idioma": g.get("idioma"), "slots": slots})
        time.sleep(0.1)
    return {"plan": plan, "period": period, "sections": sections}

def main():
    import concurrent.futures as cf, threading
    plans = [a for a in sys.argv[1:] if not a.startswith("--")]
    tok = cat.get_token()
    url = json.load(open(URL_CATALOG, encoding="utf-8"))
    if not plans:
        plans = [p for p in url if not p.startswith("__POOL_")]
    code_plan = {}
    for p in plans:
        for c in url.get(p, {}).get("courses", []):
            code_plan.setdefault(str(c["codAsignatura"]), p)
    items = list(code_plan.items())
    n = len(items)
    out, lock, done = {}, threading.Lock(), [0]
    print(f"scraping {n} courses across {len(plans)} plans (concurrent) ...", flush=True)

    def work(cp):
        code, plan = cp
        sc = scrape_course(tok, code, plan)
        with lock:
            done[0] += 1
            if any(s["slots"] for s in sc["sections"]):
                out[code] = sc
            if done[0] % 100 == 0:
                print(f"  {done[0]}/{n}  ({len(out)} with schedules)", flush=True)

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(work, items))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"-> {OUT}\n   {len(out)}/{n} courses have published 2026-2S schedules")

if __name__ == "__main__":
    main()
