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

import math
from collections import Counter
_DF, _N = Counter(), 1
def build_df(names):
    """document frequency of each token across ALL course names -> rarity weights."""
    global _DF, _N
    _DF, _N = Counter(), max(1, len(names))
    for nm in names:
        for t in set(toks(nm)):
            _DF[t] += 1
def _idf(t):
    return math.log((_N + 1) / (_DF.get(t, 0) + 1)) + 1.0

def present(t, mt):
    # exact, OR a malla token is an abbreviation/prefix of the catalog token (malla
    # 'MATH' -> catalog 'MATHEMATICAL'). DIRECTIONAL on purpose: 'GRAFOS' must not match
    # 'GRAFICOS' (neither is a prefix of the other), which was the contamination bug.
    if t in mt:
        return True
    return any(len(m) >= 4 and t.startswith(m) for m in mt)

def in_malla(name, mtxt, mt):
    """A course is in the malla iff its single RAREST (most identifying) token is present
    AND rarity-weighted recall is decent. Rare-token gate kills contamination ('Teoría de
    Grafos' needs GRAFOS, not just common TEORIA); the modest recall floor (0.45) tolerates
    the malla abbreviating away trailing descriptive tokens ('...Historia y Actualidad')."""
    n = norm(name)
    if n and n in mtxt:
        return True
    tk = toks(name)
    if not tk:
        return False
    tot = sum(_idf(t) for t in tk)
    if tot <= 0:
        return False
    pres = sum(_idf(t) for t in tk if present(t, mt))
    recall = pres / tot
    # distinctive tokens = appear in few course names overall (rare). A course is in the
    # malla only if >=1 of its distinctive tokens is present (kills contamination: 'Teoría
    # de Grafos' needs GRAFOS) AND recall>=0.45 (tolerates the malla dropping descriptive
    # tails like '...Historia y Actualidad'). Names with NO distinctive token need stricter
    # recall, since they can only be matched on common words.
    rare = [t for t in set(tk) if _DF.get(t, 0) <= max(3, 0.03 * _N)]
    if rare:
        return any(present(t, mt) for t in rare) and recall >= 0.45
    return recall >= 0.6

def malla_text(path):
    try:
        return norm("\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages))
    except Exception:
        return ""

_READER = None
def _reader():
    global _READER
    if _READER is None:
        import easyocr
        _READER = easyocr.Reader(["es", "en"], gpu=False)
    return _READER

def ocr_text(path):
    """OCR the malla (rendered PDF pages, or a PNG) for the image-only mallas."""
    import numpy as np
    try:
        chunks = []
        if path.lower().endswith((".png", ".jpg", ".jpeg")):
            from PIL import Image
            chunks += _reader().readtext(np.array(Image.open(path).convert("RGB")), detail=0)
        else:
            import fitz
            for page in fitz.open(path):
                pix = page.get_pixmap(dpi=200)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = img[:, :, :3]
                chunks += _reader().readtext(img, detail=0)
        return norm(" ".join(chunks))
    except Exception as e:
        print("  ocr failed:", e)
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
    # token rarity from ALL course names (dedup by code) -> distinctive-token weighting
    build_df(list({str(c["codAsignatura"]): c["nombre"]
                   for p in url.values() for c in p["courses"]}.values()))
    files = glob.glob(os.path.join(MALLA_DIR, "*.pdf")) + glob.glob(os.path.join(MALLA_DIR, "*.png"))
    mapping = map_plan_to_pdf(plan_names, files)
    print(f"{len(mapping)}/{len(plan_names)} plans mapped to a malla file")

    text_cache = {}   # path -> (text, used_ocr) ; OCR is slow, do each file once
    result, stats = {}, []
    for cod, path in sorted(mapping.items()):
        courses = url[cod]["courses"]
        if path not in text_cache:
            mtxt = malla_text(path); used_ocr = False
            if len(mtxt) < 800:                       # image-only malla -> OCR fallback
                print(f"  OCR {os.path.basename(path)} ...", flush=True)
                oc = ocr_text(path)
                if len(oc) > len(mtxt):
                    mtxt, used_ocr = oc, True
            text_cache[path] = (mtxt, used_ocr)
        mtxt, used_ocr = text_cache[path]
        mt = set(mtxt.split())
        kept = [str(c["codAsignatura"]) for c in courses if in_malla(c["nombre"], mtxt, mt)]
        frac = len(kept) / len(courses) if courses else 0
        # apply the filter whenever the malla yielded substantial text and matching did
        # not collapse (frac>=0.35 guards garbled OCR); else fall back to the full plan.
        applied = len(mtxt) >= 1000 and frac >= 0.35 and len(kept) >= 10
        stats.append((cod, os.path.basename(path)[:24], len(mtxt), len(courses), len(kept), applied, used_ocr))
        if applied:
            result[cod] = kept

    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n{'plan':5} {'malla':26} {'chars':>6} {'scrap':>5} {'kept':>4}  applied")
    for cod, pdf, ch, sc, kp, ap, ocr in stats:
        tag = ('FILTER' if ap else 'fallback') + (' [OCR]' if ocr else '')
        print(f"{cod:5} {pdf:26} {ch:6d} {sc:5d} {kp:4d}  {tag}")
    print(f"\n-> {OUT}  ({len(result)} programs filtered; rest use the full scraped plan)")

if __name__ == "__main__":
    main()
