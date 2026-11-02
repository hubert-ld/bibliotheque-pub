"""Classification décimale universelle, fournie (rare) ou déduite du Dewey."""

from . import prefixe_cle, rules
from .dewey import _chiffre_genre


def depuis_dewey(dewey: str, f: dict) -> str | None:
    if not dewey:
        return None
    R = rules("cdu")
    if dewey.startswith("741.5"):
        return "741.5"
    if dewey.startswith("8") and len(dewey) >= 2 and dewey[1] != "0":
        langue = R["litterature"].get(f["langue"] or "") or R["litterature_dewey"].get(dewey[:2], "")
        genre = R["genres"].get(f["forme"] or "")
        if not genre:
            digit = _chiffre_genre(dewey)
            genre = R["genres_dewey"].get(digit or "", "")
        return f"821{langue}{genre}"
    key = prefixe_cle(dewey, R["correspondance"])
    return R["correspondance"][key] if key else None


def classer(notice: dict, f: dict) -> dict | None:
    src = f["classes"].get("cdu")
    if src:
        code, origine = src, "source"
    else:
        code, origine = depuis_dewey(f["dewey"], f), "deduit"
    if not code:
        return None
    return {"code": code, "libelle": libelle(code), "origine": origine}


def libelle(code: str) -> str | None:
    table = rules("cdu")["libelles"]
    base = code.split("-")[0]
    key = prefixe_cle(base, table)
    if not key:
        return None
    text = table[key]
    genre = code[len(base):]
    noms = {"-1": "Poésie", "-2": "Théâtre", "-3": "Prose", "-31": "Romans",
            "-32": "Nouvelles", "-4": "Essais", "-6": "Correspondance", "-7": "Humour"}
    return f"{text} — {noms[genre]}" if genre in noms else text
