"""Calcul des cotes dans tous les systèmes de classement.

Toutes les cotes sont calculées et stockées pour chaque notice : changer de
système d'affichage ne demande ni re-scan ni requête. Les tables et règles
sont dans rules/*.toml ; après modification : `biblio reclassify`.
"""

import os
import re
import tomllib
from pathlib import Path

from .. import db

RULES_DIR = Path(os.environ.get("BIBLIO_RULES", db.PROJECT_DIR / "rules"))

# Ordre = ordre de calcul (le Dewey sert aux suivants) et d'affichage
SYSTEMES = {
    "dewey": "Dewey",
    "cadre_bnf": "Cadre BnF",
    "cdu": "CDU",
    "lcc": "Library of Congress",
    "clil": "Clil (libraires)",
    "thema": "Thema",
    "rayon": "Rayons perso",
}
SYSTEME_DEFAUT = "dewey"
# À changer quand la clé de tri change : les cotes sont alors recalculées une fois (db.init)
VERSION_COTES = 2
SEPARATEUR_TRI = "\x01"          # avant tout caractère : 843 se range avant 843.1
ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "the", "a", "an", "der", "die",
            "das", "el", "los", "las", "il", "lo", "gli"}

_cache: dict[str, tuple[float, dict]] = {}


def rules(name: str) -> dict:
    path = RULES_DIR / f"{name}.toml"
    mtime = path.stat().st_mtime
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    _cache[name] = (mtime, data)
    return data


norm = db.norm


def code_auteur(auteur_tri: str | None, titre: str | None) -> str:
    """3 lettres de cote : nom du premier auteur, sinon premier mot significatif du titre."""
    letters = ""
    if auteur_tri:
        tokens = auteur_tri.split()
        nom = []
        for t in tokens:
            if t != t.upper():
                break
            nom.append(t)
        letters = re.sub(r"[^a-z]", "", norm("".join(nom or tokens[:1])))
    if not letters and titre:
        words = re.findall(r"[a-z0-9]+", norm(titre))
        while len(words) > 1 and words[0] in ARTICLES:
            words.pop(0)
        letters = "".join(words)
    return letters[:3].upper()


def cle_tri(*parts) -> str:
    return SEPARATEUR_TRI.join(norm(str(p)) if p is not None else "" for p in parts)


def _tri_lcc(code: str) -> str:
    """La partie entière d'une cote LCC se compare comme un nombre : QA9 avant QA76."""
    m = re.match(r"([A-Za-z]{1,3})\s*(\d+)(.*)", code)
    return f"{m.group(1)}{int(m.group(2)):05d}{m.group(3)}" if m else code


def prefixe_cle(code: str, table: dict) -> str | None:
    """Clé la plus longue de `table` dont `code` commence."""
    best = None
    for key in table:
        if code.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return best


def faits(notice: dict, manuels: dict) -> dict:
    """Rassemble ce que les règles examinent pour une notice."""
    classes = notice.get("classes_source") or {}
    cadres = rules("cadre_bnf")["codes"]
    cadre_src = classes.get("cadre_bnf")
    if cadre_src not in cadres:
        cadre_src = None          # anciens codes BnF hors du cadre actuel
    forme = notice.get("forme")
    if forme == "mixte":
        forme = None
    dewey_src = manuels.get("dewey") or classes.get("dewey")
    if not forme and cadre_src:
        forme = {"801": "poesie", "802": "theatre", "803": "fiction", "804": "essai"}.get(cadre_src)
    if dewey_src and not dewey_src.startswith(("8", "741.5")):
        # Indice documentaire : fourni sans forme, ou imposé à la main (il prime alors)
        if not forme or manuels.get("dewey"):
            forme = "documentaire"
    public = notice.get("public")
    if public not in ("jeunesse", "ado"):
        public = "jeunesse" if cadre_src == "809" else "adulte"
    texte = " | ".join(norm(x) for x in [*(notice.get("sujets") or []),
                                          notice.get("collection"), notice.get("editeur")] if x)
    bd_mots = rules("mots").get("bd", [])
    bd = (cadre_src == "805" or (dewey_src or "").startswith("741.5")
          or any(re.search(rf"\b{re.escape(norm(w))}\b", texte) for w in bd_mots))
    return {
        "dewey_src": dewey_src,
        "cadre_src": manuels.get("cadre_bnf") or cadre_src,
        "forme": forme,
        "public": public,
        "langue": notice.get("langue_originale") or notice.get("langue"),
        "bd": bd,
        "texte": texte,
        "classes": classes,
        "manuels": manuels,
    }


def calculer(notice: dict, manuels: dict | None = None) -> dict[str, dict | None]:
    """Calcule toutes les classifications d'une notice (sans toucher la base)."""
    from . import cadre, cdu, dewey, lcc, regles

    manuels = manuels or {}
    f = faits(notice, manuels)
    out = {}
    out["dewey"] = dewey.classer(notice, f)
    f["dewey"] = (out["dewey"] or {}).get("code") or ""
    if f["dewey"].startswith("8") and not f["forme"]:
        f["forme"] = dewey.forme_depuis_indice(f["dewey"])
    f["fiction"] = f["forme"] in ("fiction", "nouvelles")
    out["cadre_bnf"] = cadre.classer(notice, f)
    f["cadre"] = (out["cadre_bnf"] or {}).get("code") or ""
    out["cdu"] = cdu.classer(notice, f)
    out["lcc"] = lcc.classer(notice, f)
    for systeme in ("clil", "thema", "rayon"):
        out[systeme] = regles.classer(systeme, notice, f)
    return out


def classer_notice(conn, notice_id: int) -> None:
    from . import regles

    notice = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    if notice is None:
        return
    manuel_rows = {r["systeme"]: dict(r) for r in conn.execute(
        "SELECT * FROM classifications WHERE notice_id = ? AND origine = 'manuel'", (notice_id,))}
    resultats = calculer(notice, {s: r["code"] for s, r in manuel_rows.items()})
    conn.execute("DELETE FROM classifications WHERE notice_id = ? AND origine != 'manuel'", (notice_id,))
    auteur = code_auteur(notice["auteur_tri"], notice["titre"])
    for systeme, res in resultats.items():
        if systeme in manuel_rows:
            row = manuel_rows[systeme]
            res = {"code": row["code"], "libelle": row["libelle"], "origine": "manuel",
                   "prefixe": (res or {}).get("prefixe", "")}
            if systeme in regles.FICHIERS:                # se range avec les livres de la même règle
                res.update(regles.place_du_code(systeme, row["code"]))
            if not res["libelle"]:
                res["libelle"] = libelle(systeme, row["code"])
        if not res:
            continue
        cote, tri = coter(systeme, res, auteur, notice)
        conn.execute(
            "INSERT OR REPLACE INTO classifications(notice_id, systeme, code, libelle, cote, tri, origine) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (notice_id, systeme, res.get("code"), res.get("libelle"), cote, tri, res["origine"]),
        )


def libelle(systeme: str, code: str | None) -> str | None:
    from . import cadre, cdu, dewey, lcc

    if not code:
        return None
    fn = {"dewey": dewey.libelle, "cdu": cdu.libelle, "lcc": lcc.libelle,
          "cadre_bnf": cadre.libelle}.get(systeme)
    return fn(code) if fn else None


def coter(systeme: str, res: dict, auteur: str, notice: dict) -> tuple[str, str]:
    """Cote affichée sur le dos du livre, et clé de tri."""
    from . import dewey

    prefixe = res.get("prefixe") or ""
    code = res.get("code") or ""
    if systeme == "dewey":
        affiche = dewey.court(code)
    elif systeme == "lcc" and res.get("origine") == "source":
        affiche = code
        auteur = ""            # la cote LCC complète contient déjà l'auteur (cutter)
    elif systeme in ("rayon", "clil"):
        affiche = res.get("abbr") or code
    else:
        affiche = code
    cote = " ".join(p for p in (prefixe, affiche, auteur) if p)
    ordre = res.get("ordre")
    tri_code = f"{ordre:03d}" if ordre is not None else (_tri_lcc(code) if systeme == "lcc" else code)
    tri = cle_tri(prefixe, tri_code, notice.get("auteur_tri"), notice.get("titre"))
    return cote, tri


def systeme_courant(conn) -> str:
    s = db.get_meta(conn, "systeme", SYSTEME_DEFAUT)
    return s if s in SYSTEMES else SYSTEME_DEFAUT


def reclasser_tout(conn) -> int:
    ids = [r["id"] for r in conn.execute("SELECT id FROM notices")]
    for notice_id in ids:
        classer_notice(conn, notice_id)
    conn.commit()
    return len(ids)
