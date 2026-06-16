"""
Scrape per-section class schedules from the Rosario guide API.

Chain (reverse-engineered; uses the public tokenApiPublic, self-refreshed):
  asignaturaDetalle?codigo=C&opcionDetalle=DetalleActividad&planEstudio=P  -> actividades (TEORICA/PRACTICA + codActividad)
  ...&opcionDetalle=DetalleGrupo&codActividad=A                            -> grupos (codGrupo, grupo#, modalidad, idioma)
  ...&opcionDetalle=DetalleHorario&codActividad=A                          -> dia/hora/profesor/sede/aula  (null until term is published)
  ...&opcionDetalle=DetalleFecha&codActividad=A                            -> offering period (fechaInicio/Fin)

Output: model/schedules.json  { code: {plan, period, sections:[{grupo,codGrupo,actividad,profesor,modalidad,slots:[{dia,inicio,fin,sede,aula}]}]} }

NOTE (2026-06): 2026-2S timetables are NOT published yet (horarios=null). This pulls the
real section/group skeleton now; rerun once the term publishes to fill slots. Pass
--sample to synthesize representative slots so the planner is demoable in the meantime.
"""
import os, sys, json, time, urllib.request, urllib.parse
import scrape_catalog as cat   # reuse get_token()

API = "https://guiaacademicabackend.azurewebsites.net/api"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_CATALOG = os.path.join(os.path.dirname(ROOT), "data", "url_catalog.json")
OUT = os.path.join(ROOT, "model", "schedules.json")
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

def _get(tok, **kw):
    q = urllib.parse.urlencode(kw)
    req = urllib.request.Request(f"{API}/asignaturaDetalle?{q}",
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("data")
    except Exception:
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
        grupos = _get(tok, codigo=code, opcionDetalle="DetalleGrupo",
                      planEstudio=plan, codActividad=ca) or []
        hor = _get(tok, codigo=code, opcionDetalle="DetalleHorario",
                   planEstudio=plan, codActividad=ca) or []
        fecha = _get(tok, codigo=code, opcionDetalle="DetalleFecha",
                     planEstudio=plan, codActividad=ca) or []
        if fecha and isinstance(fecha, list):
            period = {"inicio": fecha[0].get("fechaInicio"), "fin": fecha[0].get("fechaFin")}
        by_grp = {}
        for h in hor:                                   # group slots by codGrupo
            g = h.get("codGrupo")
            by_grp.setdefault(g, []).append({
                "dia": h.get("diaSemana") or h.get("nombreDia"),
                "inicio": _hhmm(h.get("horaInicio")), "fin": _hhmm(h.get("horaFin")),
                "sede": h.get("edificio") or h.get("sede"), "aula": h.get("aula"),
                "profesor": h.get("profesor")})
        for g in grupos:
            cg = g.get("codGrupo")
            sections.append({
                "grupo": g.get("grupo"), "codGrupo": cg,
                "actividad": a.get("claseActividad"),
                "modalidad": (g.get("modalidad") or {}).get("descCorta") if isinstance(g.get("modalidad"), dict) else g.get("modalidad"),
                "idioma": g.get("idioma"),
                "slots": by_grp.get(cg, [])})
        time.sleep(0.2)
    return {"plan": plan, "period": period, "sections": sections}

def synth_slots(code, n_sections=3):
    """representative weekly slots when real horarios aren't published (demo only).
    Spread across many day-pairs/time-blocks so realistic conflict-free combos exist."""
    blocks = [("Lunes", "Miércoles", 7 * 60, 9 * 60), ("Martes", "Jueves", 7 * 60, 9 * 60),
              ("Lunes", "Miércoles", 9 * 60, 11 * 60), ("Martes", "Jueves", 9 * 60, 11 * 60),
              ("Lunes", "Miércoles", 11 * 60, 13 * 60), ("Martes", "Jueves", 11 * 60, 13 * 60),
              ("Lunes", "Miércoles", 14 * 60, 16 * 60), ("Martes", "Jueves", 14 * 60, 16 * 60),
              ("Lunes", "Miércoles", 16 * 60, 18 * 60), ("Martes", "Jueves", 16 * 60, 18 * 60),
              ("Viernes", None, 7 * 60, 10 * 60), ("Viernes", None, 14 * 60, 17 * 60)]
    h = int(code[-5:]) if code[-5:].isdigit() else abs(hash(code))
    out = []
    for s in range(n_sections):
        d1, d2, i, f = blocks[(h * 7 + s * 5) % len(blocks)]   # spread sections apart
        aula = f"{100 + (h % 40)}"
        slots = [{"dia": d1, "inicio": i, "fin": f, "sede": "SEDE CLAUSTRO", "aula": aula, "profesor": None}]
        if d2:
            slots.append({"dia": d2, "inicio": i, "fin": f, "sede": "SEDE CLAUSTRO", "aula": aula, "profesor": None})
        out.append({"grupo": s + 1, "codGrupo": f"S{code}{s+1}", "actividad": "TEORICA",
                    "modalidad": "Presencial", "idioma": "Español", "slots": slots, "sample": True})
    return out

def main():
    sample = "--sample" in sys.argv
    plans = [a for a in sys.argv[1:] if not a.startswith("--")] or ["MA03"]
    tok = cat.get_token()
    url = json.load(open(URL_CATALOG, encoding="utf-8"))
    out = {}
    real_slots = 0
    for plan in plans:
        courses = url.get(plan, {}).get("courses", [])
        print(f"[{plan}] {len(courses)} courses")
        for i, c in enumerate(courses, 1):
            code = str(c["codAsignatura"])
            sc = scrape_course(tok, code, plan)
            if any(s["slots"] for s in sc["sections"]):
                real_slots += 1
            elif sample:                                 # fill demo slots
                sc["sections"] = synth_slots(code)
                sc["sample"] = True
            out[code] = sc
            if i % 10 == 0:
                print(f"  {i}/{len(courses)}", flush=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"-> {OUT}\n   {len(out)} courses, {real_slots} with REAL published times"
          + ("  (rest synthesized: sample)" if sample else "  (times publish ~Jul for 2026-2S)"))

if __name__ == "__main__":
    main()
