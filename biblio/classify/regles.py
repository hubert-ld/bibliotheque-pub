"""Moteur de règles pour Clil, Thema et rayons perso (fichiers rules/*.toml)."""

import re

from . import norm, rules
from ..i18n import tr

CONDITIONS = {"bd", "fiction", "public", "forme", "dewey", "cadre", "langue", "langue_non", "mots"}
RESULTATS = {"abbr", "libelle", "code", "prefixe"}
FICHIERS = {"clil": "clil", "thema": "thema", "rayon": "rayons"}


class RegleInvalide(ValueError):
    pass


def _mots(valeurs: list[str]) -> list[str]:
    listes = rules("mots")
    out = []
    for v in valeurs:
        if v.startswith("@"):
            if v[1:] not in listes:
                raise RegleInvalide(tr("liste de mots inconnue : {liste} (voir rules/mots.toml)", liste=v))
            out.extend(listes[v[1:]])
        else:
            out.append(v)
    return [norm(w) for w in out]


def correspond(regle: dict, f: dict) -> bool:
    for cle, val in regle.items():
        if cle in RESULTATS:
            continue
        if cle not in CONDITIONS:
            raise RegleInvalide(tr("condition inconnue « {cle} » dans la règle {regle}", cle=cle, regle=repr(regle.get("libelle"))))
        if cle in ("bd", "fiction"):
            if bool(f[cle]) != bool(val):
                return False
        elif cle in ("public", "forme", "langue"):
            if f[cle] not in val:
                return False
        elif cle == "langue_non":
            if f["langue"] in val:
                return False
        elif cle in ("dewey", "cadre"):
            if not f[cle] or not any(f[cle].startswith(p) for p in val):
                return False
        elif cle == "mots":
            if not any(re.search(rf"\b{re.escape(w)}\b", f["texte"]) for w in _mots(val)):
                return False
    return True


def _cle(regle: dict) -> str:
    return regle.get("abbr") or regle.get("code") or regle["libelle"]


def _rangs(liste: list[dict]) -> dict[str, int]:
    """Rang de chaque valeur : celui de sa première règle."""
    premiers = {}
    for i, regle in enumerate(liste):
        premiers.setdefault(_cle(regle), i)
    return premiers


def place_du_code(systeme: str, code: str) -> dict:
    """Abréviation et rang d'une valeur choisie à la main ; rien si elle n'est dans aucune règle."""
    liste = rules(FICHIERS[systeme]).get("regle", [])
    premiers = _rangs(liste)
    for regle in liste:
        if code in (regle.get("code"), regle.get("abbr")):
            return {"abbr": regle.get("abbr"), "ordre": premiers[_cle(regle)]}
    return {}


def classer(systeme: str, notice: dict, f: dict) -> dict | None:
    liste = rules(FICHIERS[systeme]).get("regle", [])
    premiers = _rangs(liste)
    for regle in liste:
        if correspond(regle, f):
            cle = _cle(regle)
            return {
                "code": regle.get("code") or regle.get("abbr"),
                "abbr": regle.get("abbr"),
                "libelle": regle["libelle"],
                "origine": "deduit",
                "prefixe": regle.get("prefixe", ""),
                "ordre": premiers[cle],
            }
    return None


def options(systeme: str) -> list[dict]:
    """Valeurs possibles d'un système à règles (pour la saisie manuelle)."""
    vus, out = set(), []
    for regle in rules(FICHIERS[systeme]).get("regle", []):
        cle = regle.get("abbr") or regle.get("code")
        if cle not in vus:
            vus.add(cle)
            out.append({"code": regle.get("code") or regle.get("abbr"), "abbr": regle.get("abbr"),
                        "libelle": regle["libelle"]})
    return out
