"""
Filter each program's scraped PLAN course list down to the courses actually drawn in
its official malla (Planes de Estudio/*.pdf), removing cross-program junk (e.g. energy
/logistics electives that the API cross-lists into MA03).

Method: extract the malla text, then keep a scraped-plan course if its name appears in
the malla (exact substring, OR >=2 prefix-matched distinctive tokens, OR a single-token
name present). The filter is applied ONLY when the malla yields enough text AND keeps a
sane fraction of the plan; otherwise the program falls back to the full scraped list
(many mallas are image-only PDFs with 0 extractable text). Output: model/malla_plan.json
= { codPlan: [kept codes] } for the programs where the filter applied.
"""
import os, re, json, unicodedata, glob
import pypdf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
URL_CATALOG = os.path.join(os.path.dirname(ROOT), "data", "url_catalog.json")
MALLA_DIR = next((d for d in [
    os.path.expanduser(r"~\OneDrive\Desktop\Planes de Estudio"),
    os.path.expanduser(r"~\Desktop\Planes de Estudio")] if os.path.isdir(d)), "")
OUT = os.path.join(ROOT, "model", "malla_plan.json")

STOP = {"DE", "Y", "LA", "EL", "EN", "A", "LAS", "LOS", "DEL", "PARA", "CON", "POR",
        "E", "O", "U", "I", "II", "III", "IV", "V", "1", "2", "3", "4", "5"}

def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "")
                  .encode("ascii", "ignore").decode().upper()).strip()

def toks(name):
    return [t for t in norm(name).split() if len(t) > 2 and t not in STOP]

def present(t, mt):
    for m in mt:
        if t == m or (len(t) >= 4 and len(m) >= 4 and (m.startswith(t[:4]) or t.startswith(m[:4]))):
            return True
    return False

def in_malla(name, mtxt, mt):
    n = norm(name)
    if n and n in mtxt:
        return True
    tk = toks(name)
    if not tk:
        return False
    p = sum(1 for t in tk if present(t, mt))
    return p >= 1 if len(tk) == 1 else p >= 2

def malla_text(path):
    try:
        return norm("\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages))
    except Exception:
        return ""

def map_plan_to_pdf(plan_names, pdfs):
    """match codPlan -> malla pdf by normalized program-name containment."""
    npdfs = {f: norm(os.path.splitext(os.path.basename(f))[0]) for f in pdfs}
    # hand aliases where the file name differs from the plan name
    ALIAS = {"MATEMATICAS APLICADAS Y CIENCIAS DE LA COMPUTACION": "MACC",
             "ENFERMERIA": "ENFEMERIA", "ADMINISTRACION DE NEGOCIOS INTERNACIONALES": "NEGOCIOS INTERNACIONALES"}
    out = {}
    for cod, name in plan_names.items():
        key = ALIAS.get(norm(name), norm(name))
        best = None
        for f, fn in npdfs.items():
            if key == fn or key in fn or fn in key:
                if best is None or abs(len(fn) - len(key)) < best[1]:
                    best = (f, abs(len(fn) - len(key)))
        if best:
            out[cod] = best[0]
    return out

def main():
    url = json.load(open(URL_CATALOG, encoding="utf-8"))
    plan_names = {cp: p["nombrePlan"] for cp, p in url.items() if not cp.startswith("__POOL_")}
    pdfs = glob.glob(os.path.join(MALLA_DIR, "*.pdf"))
    mapping = map_plan_to_pdf(plan_names, pdfs)
    print(f"{len(mapping)}/{len(plan_names)} plans mapped to a malla PDF")

    result, stats = {}, []
    for cod, pdf in sorted(mapping.items()):
        courses = url[cod]["courses"]
        mtxt = malla_text(pdf)
        mt = set(mtxt.split())
        kept = [str(c["codAsignatura"]) for c in courses if in_malla(c["nombre"], mtxt, mt)]
        frac = len(kept) / len(courses) if courses else 0
        applied = len(mtxt) >= 800 and frac >= 0.55 and len(kept) >= 12
        stats.append((cod, os.path.basename(pdf)[:24], len(mtxt), len(courses), len(kept), applied))
        if applied:
            result[cod] = kept

    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n{'plan':5} {'malla':26} {'chars':>6} {'scrap':>5} {'kept':>4}  applied")
    for cod, pdf, ch, sc, kp, ap in stats:
        print(f"{cod:5} {pdf:26} {ch:6d} {sc:5d} {kp:4d}  {'FILTER' if ap else 'fallback(scraped)'}")
    print(f"\n-> {OUT}  ({len(result)} programs filtered; rest use the full scraped plan)")

if __name__ == "__main__":
    main()
