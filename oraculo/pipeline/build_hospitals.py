"""
Derive the Medicina (ME03) clinical-practice HOSPITAL list from the official plan course
names. Clinical courses encode their rotation site as a ' - <SITE>' suffix (often messy:
accents, abbreviations, 'GRUPO A', 'URGENCIAS-', '(GRUPO B)', site '+' site). We map each
clinical course to one or more CANONICAL hospitals via keyword matching, then aggregate the
rotations (base course name) that happen at each.

Output: model/hospitals.json
  { program, hospitals:[{id, name, n_rotations, rotations:[base names], codes:[course codes]}] }

Also seeds model/hospital_reviews.json (empty, read-only) keyed by hospital id, ready to
receive curated star ratings + reviews later:
  { <id>: {"rating": null, "n": 0, "reviews": []} }
"""
import os, re, json, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
URL_CATALOG = os.path.join(os.path.dirname(ROOT), "data", "url_catalog.json")
OUT = os.path.join(ROOT, "model", "hospitals.json")
REVIEWS = os.path.join(ROOT, "model", "hospital_reviews.json")
PLAN = "ME03"

def _u(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "")
                  .encode("ascii", "ignore").decode().upper()).strip()

# canonical hospital -> distinctive keyword(s) that appear in the course-name suffix
# (normalized, accent-stripped, UPPER). A course can match several (e.g. 'A + B').
HOSPITALS = [
    ("hu-mayor",        "Hospital Universitario Mayor (Méderi)",        ["MAYOR", "MEDERI", "HUM"]),
    ("san-rafael",      "Hospital Universitario Clínica San Rafael",    ["SAN RAFAEL"]),
    ("cardioinfantil",  "Fundación Cardioinfantil",                     ["CARDIOINFANTIL", "CARDIO INFANTIL"]),
    ("bosa",            "Hospital de Bosa",                             ["BOSA"]),
    ("kennedy",         "Hospital de Kennedy",                          ["KENNEDY"]),
    ("centenario",      "Clínica Centenario",                           ["CENTENARIO"]),
    ("samaritana",      "Hospital Universitario de La Samaritana",      ["SAMARITANA"]),
    ("barrios-unidos",  "Hospital Universitario Barrios Unidos",        ["BARRIOS UNIDOS", "HUBU"]),
    ("paz",             "Clínica de Nuestra Señora de la Paz",          ["DE LA PAZ"]),
    ("clinica-colombia","Clínica Colombia",                             ["CLINICA COLOMBIA"]),
    ("meissen",         "Hospital de Meissen",                          ["MEISSEN"]),
    ("colsanitas",      "Clínica Pediátrica Colsanitas",                ["COLSANITAS"]),
    ("tintal",          "Hospital El Tintal",                           ["TINTAL"]),
    ("tunal",           "Hospital El Tunal",                            ["TUNAL"]),
    ("simon-bolivar",   "Hospital Simón Bolívar",                       ["SIMON BOLIVAR"]),
    ("santa-maria-lago","Clínica Santa María del Lago",                 ["SANTA MARIA DEL LAGO"]),
    ("inmaculada",      "Clínica La Inmaculada",                        ["LA INMACULADA"]),
    ("cisne",           "Clínicas CISNE (Campo Nuevo / Campo Victoria)",["CISNE", "CAMPO NUEVO", "CAMPO VICTORIA"]),
    ("cardiovascular-nino", "Hospital Cardiovascular del Niño de Cundinamarca", ["CARDIOVASCULAR DEL NINO"]),
    ("infantil-colsubsidio", "Clínica Infantil Colsubsidio",           ["INFANTIL COLSUBSIDIO"]),
    ("clinica-colsubsidio", "Clínica Colsubsidio",                      ["CLINICA COLSUBSIDIO"]),
    ("oftalmologica",   "Fundación Oftalmológica Nacional",             ["OFTALMOLOGICA NACIONAL"]),
    ("country",         "Centro Audiológico y Quirúrgico del Country",  ["COUNTRY"]),
]
_HKW = [(hid, [re.compile(r"\b" + re.escape(k) + r"\b") for k in kws]) for hid, _, kws in HOSPITALS]
_ALL_KW = [k for _, _, kws in HOSPITALS for k in kws]

def _match(site_text):
    u = _u(site_text)
    return [hid for hid, pats in _HKW if any(p.search(u) for p in pats)]

_GENERIC = {"ESPECIALIDAD CLINICA", "BLOQUE CLINICO I", "BLOQUE CLINICO II",
            "BLOQUE QUIRURGICO", "INTERNADO", "MEDICINA SOCIAL Y PREVENTIVA"}

def _rotation(name, suffix):
    """A useful rotation/specialty label. Base name unless it's generic (e.g. 'Especialidad
    Clínica'), in which case use the specialty named in the suffix (with the hospital stripped)."""
    base = re.sub(r"\s*\(grupo [ab]\)", "", name.split(" - ")[0], flags=re.I).strip()
    base = re.sub(r"\b(BLQ\.?)\b", "Bloque", base, flags=re.I).strip()
    if _u(base) in _GENERIC:
        spec = _u(suffix)
        for k in sorted(_ALL_KW, key=len, reverse=True):       # drop the hospital name
            spec = re.sub(r"\b" + re.escape(k) + r"\b", "", spec)
        spec = re.sub(r"\b(HOSPITAL|UNIVERSITARIO|CLINICA|FUNDACION|GRUPO [AB]|MSP I+|"
                      r"HOSPITALIZACION [AB]?|FACULTAD)\b", "", spec)
        spec = re.sub(r"[^A-Z ]", " ", spec); spec = re.sub(r"\s+", " ", spec).strip().title()
        if len(spec) >= 4:
            return spec
    return base

def main():
    url = json.load(open(URL_CATALOG, encoding="utf-8"))
    courses = url[PLAN]["courses"]
    agg = {hid: {"id": hid, "name": nm, "rotations": {}, "codes": set()}
           for hid, nm, _ in HOSPITALS}
    matched = 0
    for c in courses:
        nm, code = c["nombre"], str(c["codAsignatura"])
        # only clinical courses carry a site suffix
        suffix = " - ".join(nm.split(" - ")[1:])
        if not suffix:
            continue
        ids = _match(suffix)
        if not ids:
            continue
        matched += 1
        rot = _rotation(nm, suffix)
        for hid in ids:
            agg[hid]["rotations"].setdefault(_u(rot), rot)
            agg[hid]["codes"].add(code)

    hospitals = []
    for hid, nm, _ in HOSPITALS:
        a = agg[hid]
        if not a["codes"]:
            continue
        rots = sorted(a["rotations"].values(), key=lambda r: _u(r))
        hospitals.append({"id": hid, "name": nm, "n_rotations": len(rots),
                          "rotations": rots, "codes": sorted(a["codes"])})
    hospitals.sort(key=lambda h: -h["n_rotations"])

    json.dump({"program": PLAN, "hospitals": hospitals},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # seed an EMPTY read-only reviews file (only if absent, so curated data is never clobbered)
    if not os.path.exists(REVIEWS):
        json.dump({h["id"]: {"rating": None, "n": 0, "reviews": []} for h in hospitals},
                  open(REVIEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"{len(courses)} ME03 courses, {matched} clinical-site mentions -> {len(hospitals)} hospitals")
    for h in hospitals:
        print(f"  {h['n_rotations']:3} rot · {h['name']}")
    unmatched = set()
    for c in courses:
        suf = " - ".join(c["nombre"].split(" - ")[1:])
        if suf and not _match(suf):
            for p in suf.split(" - "):
                if any(w in _u(p) for w in ("HOSPITAL", "CLINIC", "FUNDACI", "IPS", "CENTRO", "UNIDAD")):
                    unmatched.add(p.strip())
    if unmatched:
        print(f"\n  unmatched site mentions ({len(unmatched)}): {sorted(unmatched)}")

if __name__ == "__main__":
    main()
