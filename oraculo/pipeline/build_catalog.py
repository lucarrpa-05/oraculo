"""
Build catalog.json: per course -> name, credits, area, difficulty (from panel),
plus a MACC prerequisite graph (best-effort from the official malla, by name).
"""
import os, json, glob, unicodedata, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CURSOS = os.path.join(os.path.dirname(ROOT), "data", "Cursos")
MODEL_DIR = os.path.join(ROOT, "model")

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()

# ---- MACC malla: course name -> list of prerequisite names (from the malla) ----
# best-effort transcription of the prerequisite strips; verify against the PDF.
MACC_PREREQS = {
    "PRECALCULO": [],
    "PENSAMIENTO MATEMATICO": [],
    "PROGRAMACION DE COMPUTADORES": [],
    "LOGICA, TEORIA DE NUMEROS Y CONJUNTOS": [],
    "CALCULO 1": ["PRECALCULO"],
    "FISICA 1": ["PRECALCULO"],
    "ALGEBRA LINEAL": ["PRECALCULO"],
    "ALGORITMOS Y ESTRUCTURAS DE DATOS": ["PROGRAMACION DE COMPUTADORES"],
    "LOGICA PARA CIENCIAS DE LA COMPUTACION": ["LOGICA, TEORIA DE NUMEROS Y CONJUNTOS"],
    "CALCULO 2": ["CALCULO 1"],
    "ARQUITECTURA DEL COMPUTADOR": ["PROGRAMACION DE COMPUTADORES"],
    "TEORIA DE LA COMPUTACION": ["LOGICA PARA CIENCIAS DE LA COMPUTACION"],
    "CORNERSTONE PROJECT": ["CALCULO 1", "ALGORITMOS Y ESTRUCTURAS DE DATOS",
                            "LOGICA PARA CIENCIAS DE LA COMPUTACION"],
    "INGENIERIA DE DATOS": ["PROGRAMACION DE COMPUTADORES"],
    "CALCULO 3": ["CALCULO 2", "ALGEBRA LINEAL"],
    "OPTIMIZACION": ["CALCULO 2", "ALGEBRA LINEAL"],
    "ANALISIS Y DISENO DE ALGORITMOS": ["ALGORITMOS Y ESTRUCTURAS DE DATOS",
                                        "TEORIA DE LA COMPUTACION"],
    "PROBABILIDAD Y ESTADISTICA 1": ["CALCULO 2"],
    "TEORIA DE GRAFOS": ["ALGEBRA LINEAL"],
    "VARIABLE COMPLEJA": ["CALCULO 3"],
    "ECUACIONES DIFERENCIALES": ["ALGEBRA LINEAL", "CALCULO 3"],
    "ANALISIS REAL": ["PENSAMIENTO MATEMATICO", "LOGICA, TEORIA DE NUMEROS Y CONJUNTOS",
                      "CALCULO 2", "CALCULO 3"],
    "PROBABILIDAD Y ESTADISTICA 2": ["PROBABILIDAD Y ESTADISTICA 1"],
    "KEYSTONE PROJECT": ["CORNERSTONE PROJECT", "INGENIERIA DE DATOS",
                         "OPTIMIZACION", "PROBABILIDAD Y ESTADISTICA 1",
                         "TEORIA DE GRAFOS"],
    "TOPOLOGIA": ["ANALISIS REAL"],
    "ANALISIS NUMERICO Y COMPUTACION CIENTIFICA": ["ALGORITMOS Y ESTRUCTURAS DE DATOS",
                                                   "ALGEBRA LINEAL", "ECUACIONES DIFERENCIALES",
                                                   "PROGRAMACION DE COMPUTADORES"],
    "ANALISIS ESTADISTICO DE DATOS": ["INGENIERIA DE DATOS", "PROBABILIDAD Y ESTADISTICA 2"],
    "REDES DE COMPUTADORES": ["TEORIA DE GRAFOS"],
    "ALGEBRA ABSTRACTA Y CODIFICACION": ["LOGICA, TEORIA DE NUMEROS Y CONJUNTOS", "ALGEBRA LINEAL"],
    "MATHEMATICAL MODELING OF SYSTEMS IN NATURAL SCIENCES": ["PROGRAMACION DE COMPUTADORES",
                                                             "FISICA 1", "PROBABILIDAD Y ESTADISTICA 1",
                                                             "ANALISIS NUMERICO Y COMPUTACION CIENTIFICA"],
    "OPERATING SYSTEMS": ["ALGORITMOS Y ESTRUCTURAS DE DATOS", "ARQUITECTURA DEL COMPUTADOR"],
    "GEOMETRIA": ["ECUACIONES DIFERENCIALES", "ANALISIS REAL"],
    "CAPSTONE PROJECT": ["KEYSTONE PROJECT",
                         "MATHEMATICAL MODELING OF SYSTEMS IN NATURAL SCIENCES"],
}

URL_CATALOG = os.path.join(os.path.dirname(ROOT), "data", "url_catalog.json")

def load_catalog():
    """Primary source: scraped official catalog (data/url_catalog.json, all 54 plans).
    Falls back to data/Cursos/*.txt for any code it doesn't cover."""
    cat, plan_courses, plan_names = {}, {}, {}
    if os.path.exists(URL_CATALOG):
        url = json.load(open(URL_CATALOG, encoding="utf-8"))
        for codPlan, p in url.items():
            is_pool = codPlan.startswith("__POOL_")   # GEN / HM elective pools, not a plan
            if not is_pool:
                plan_names[codPlan] = p["nombrePlan"]
                plan_courses[codPlan] = [str(c["codAsignatura"]) for c in p["courses"]]
            for c in p["courses"]:
                code = str(c["codAsignatura"])
                cat.setdefault(code, {
                    "code": code, "name": c["nombre"],
                    "credits": float(c.get("creditos") or 3),
                    "area": code[:4], "plans": [], "pool": None,
                })
                if is_pool:
                    cat[code]["pool"] = c.get("tipoElectiva")   # GEN / HM
                else:
                    cat[code]["plans"].append(codPlan)
    # fallback: legacy data/Cursos files for any codes not in the scrape
    for fp in glob.glob(os.path.join(CURSOS, "**", "*.txt"), recursive=True):
        for c in json.load(open(fp, encoding="utf-8"))["data"]:
            code = str(c["codAsignatura"])
            cat.setdefault(code, {"code": code, "name": c["nombre"],
                                  "credits": float(c.get("creditos") or 3),
                                  "area": code[:4], "plans": []})
    return cat, plan_courses, plan_names

def main():
    cat, plan_courses, plan_names = load_catalog()
    # attach difficulty from panel course_stats
    stats = {r["crs"]: r for r in json.load(open(os.path.join(MODEL_DIR, "course_stats.json"), encoding="utf-8"))}
    for code, c in cat.items():
        s = stats.get(code)
        c["fail_rate"] = round(s["fail_rate"], 4) if s else None
        c["mean_grade"] = round(s["mean_grade"], 3) if s and s.get("mean_grade") else None
        c["n_hist"] = int(s["n"]) if s else 0

    # resolve MACC prereq names -> codes (MA03 plan subset, then global fallback)
    macc_set = set(plan_courses.get("MA03", []))
    macc_codes = {norm(cat[c]["name"]): c for c in macc_set if c in cat}
    global_names = {norm(c["name"]): code for code, c in cat.items()}

    def resolve(name):
        n = norm(name)
        return macc_codes.get(n) or global_names.get(n)

    prereq_by_code, unresolved = {}, []
    for name, prereqs in MACC_PREREQS.items():
        code = resolve(name)
        if not code:
            unresolved.append(name); continue
        prereq_by_code[code] = [resolve(p) for p in prereqs if resolve(p)]

    macc_plan = sorted(macc_set) if macc_set else sorted(
        [c for c in cat if "matematicas" in norm(plan_names.get("", ""))])

    out = {
        "catalog": cat,
        "macc_plan": macc_plan,
        "macc_prereqs": prereq_by_code,
        "plan_courses": plan_courses,   # official membership per codPlan (all 54 plans)
        "plan_names": plan_names,
    }
    json.dump(out, open(os.path.join(MODEL_DIR, "catalog.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n_named = sum(1 for c in cat.values() if c.get("name"))
    print(f"catalog: {len(cat)} codes ({n_named} named); {len(plan_courses)} official plans; "
          f"MACC plan {len(macc_plan)} courses; prereqs resolved for {len(prereq_by_code)}")
    if unresolved:
        print("UNRESOLVED (verify names):", sorted(set(unresolved)))

if __name__ == "__main__":
    main()
