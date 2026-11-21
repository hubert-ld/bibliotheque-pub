"""Cotes des disques et des films : pas de Clil, de Thema ni de Cadre BnF, qui ne décrivent que des livres.

Le genre donne l'indice, d'après rules/media.toml ; les rayons perso suivent les règles habituelles.
"""

import re

from . import norm, rules

MUSIQUE = ("cd", "vinyle", "cassette")
FILMS = ("dvd", "bluray")


def _indice(famille: dict, texte: str) -> dict:
    for genre in famille.get("genre", []):
        if any(re.search(rf"\b{re.escape(norm(m))}\b", texte) for m in genre["mots"]):
            return genre
    return famille["defaut"]


def calculer(notice: dict, f: dict) -> dict[str, dict | None]:
    from . import regles

    out = dict.fromkeys(("dewey", "cadre_bnf", "cdu", "lcc", "clil", "thema", "rayon"))
    f.update(dewey="", cadre="", bd=False, fiction=False)
    table = rules("media")
    famille = table["musique"] if f["support"] in MUSIQUE else table["films"] if f["support"] in FILMS else None
    if famille:
        indice = _indice(famille, f["texte"])
        for systeme in ("dewey", "cdu", "lcc"):
            out[systeme] = {"code": indice[systeme], "libelle": indice["libelle"], "origine": "deduit", "prefixe": ""}
        f["dewey"] = indice["dewey"]
    out["rayon"] = regles.classer("rayon", notice, f)
    return out
