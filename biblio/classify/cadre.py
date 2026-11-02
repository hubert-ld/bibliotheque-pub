"""Cadre de classement de la Bibliographie nationale française."""

from . import rules


def depuis_dewey(dewey: str, f: dict) -> str | None:
    if not dewey:
        return None
    if dewey.startswith("741.5"):
        return "805"
    if f["public"] in ("jeunesse", "ado") and f["forme"] != "documentaire":
        return "809"
    if dewey.startswith("8"):
        return {"poesie": "801", "theatre": "802", "fiction": "803", "nouvelles": "803",
                "essai": "804"}.get(f["forme"], "800")
    codes = sorted(rules("cadre_bnf")["codes"])
    head = dewey[:3]
    candidats = [c for c in codes if c[0] == head[0] and c <= head]
    return candidats[-1] if candidats else None


def classer(notice: dict, f: dict) -> dict | None:
    if f["cadre_src"]:
        code, origine = f["cadre_src"], "source"
    else:
        code, origine = depuis_dewey(f["dewey"], f), "deduit"
    if not code:
        return None
    return {"code": code, "libelle": libelle(code), "origine": origine}


def libelle(code: str) -> str | None:
    return rules("cadre_bnf")["codes"].get(code)
