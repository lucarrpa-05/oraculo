"""
Scrape REAL per-section class schedules from the Rosario guide API (2026-2S, live).

Schedules are PLAN-SPECIFIC: the SAME 8-digit code returns DIFFERENT horarios depending
on the planEstudio queried (e.g. 11310003 has 3 slots under MA03 but 0 under ADM1). So we
scrape every (plan, course) pair and key the output by plan. The runtime then looks up a
course's schedule under the STUDENT'S plan.

Chain per (course, plan) (Bearer tokenApiPublic, self-refreshed):
  asignaturaDetalle?codigo=C&opcionDetalle=DetalleActividad&planEstudio=P  -> actividades (codActividad)
  ...&opcionDetalle=DetalleFecha&codActividad=A                            -> offering period (fechaInicio/Fin)
  ...&opcionDetalle=DetalleGrupo&codActividad=A                            -> grupos (codGrupo, grupo#, modalidad)
  ...&opcionDetalle=DetalleHorario&codActividad=A&codGrupo=G&fechaIni=..&fechaFin=..
        -> the schedule: dia/horaInicio/horaFin/sede/aula/profesor/capacidad   (needs the date range!)

A student enrolls in a GRUPO, which bundles that group's weekly sessions across all its
activities (teórica + práctica/laboratorio). So we group the horario slots by grupo number,
tagging each slot with its actividad.

Output: model/schedules.json
  { plan: { code: {period, grupos:[
       {grupo, modalidad, idioma, capacidad, profesores:[...],
        slots:[{dia,inicio,fin,sede,aula,profesor,actividad}]} ]} } }

Usage:  python scrape_schedules.py            # all plans in url_catalog
        python scrape_schedules.py MA03 PS04  # only these plans
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
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

def _clean(v):
    return None if v in (None, "N/A", "") else v

def scrape_course(tok, code, plan):
    """Return {period, grupos:[...]} for one (course, plan), or None if no published times."""
    acts = _get(tok, codigo=code, opcionDetalle="DetalleActividad", planEstudio=plan) or []
    period, by_grupo = None, {}        # grupo number -> bundled section
    for a in acts:
        ca = a.get("codActividad")
        act = a.get("claseActividad")
        fecha = _get(tok, codigo=code, opcionDetalle="DetalleFecha", planEstudio=plan, codActividad=ca) or []
        if not fecha:
            continue
        fi, ff = fecha[0].get("fechaInicio"), fecha[0].get("fechaFin")
        period = {"inicio": fi, "fin": ff}
        grupos = _get(tok, codigo=code, opcionDetalle="DetalleGrupo", planEstudio=plan, codActividad=ca) or []
        for g in grupos:
            cg, gnum = g.get("codGrupo"), g.get("grupo")
            hor = _get(tok, codigo=code, opcionDetalle="DetalleHorario", planEstudio=plan,
                       codActividad=ca, codGrupo=cg, fechaIni=fi, fechaFin=ff) or []
            slots = [{"dia": h.get("dia"), "inicio": _hhmm(h.get("horaInicio")), "fin": _hhmm(h.get("horaFin")),
                      "sede": _clean(h.get("sede")), "aula": _clean(h.get("aula")),
                      "profesor": _clean(h.get("profesor")), "actividad": act}
                     for h in hor if h.get("dia") and _hhmm(h.get("horaInicio")) is not None]
            if not slots:
                continue
            mod = g.get("modalidad")
            sec = by_grupo.setdefault(gnum, {
                "grupo": gnum, "modalidad": mod.get("descCorta") if isinstance(mod, dict) else mod,
                "idioma": g.get("idioma"), "capacidad": (hor[0].get("capacidad") if hor else None),
                "profesores": [], "slots": []})
            sec["slots"].extend(slots)
            for s in slots:
                if s["profesor"] and s["profesor"] not in sec["profesores"]:
                    sec["profesores"].append(s["profesor"])
        time.sleep(0.05)
    grupos = sorted(by_grupo.values(), key=lambda s: (s["grupo"] is None, s["grupo"]))
    if not grupos:
        return None
    return {"period": period, "grupos": grupos}

def main():
    import concurrent.futures as cf, threading
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    tok = cat.get_token()
    url = json.load(open(URL_CATALOG, encoding="utf-8"))
    plans = only or [p for p in url if not p.startswith("__POOL_")]
    pairs = [(str(c["codAsignatura"]), p) for p in plans for c in url.get(p, {}).get("courses", [])]
    # de-dup identical (code, plan) pairs (a plan can list a code twice)
    seen = set(); pairs = [x for x in pairs if not (x in seen or seen.add(x))]
    n = len(pairs)
    out, lock, done = {}, threading.Lock(), [0]
    print(f"scraping {n} (course,plan) pairs across {len(plans)} plans (concurrent) ...", flush=True)

    def work(cp):
        code, plan = cp
        sc = scrape_course(tok, code, plan)
        with lock:
            done[0] += 1
            if sc:
                out.setdefault(plan, {})[code] = sc
            if done[0] % 200 == 0:
                tot = sum(len(v) for v in out.values())
                print(f"  {done[0]}/{n}  ({tot} course-schedules in {len(out)} plans)", flush=True)

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(work, pairs))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    tot = sum(len(v) for v in out.values())
    print(f"-> {OUT}\n   {tot} course-schedules across {len(out)} plans (2026-2S)")

if __name__ == "__main__":
    main()
