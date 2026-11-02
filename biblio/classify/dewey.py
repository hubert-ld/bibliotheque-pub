"""Dewey : indice fourni par un catalogue, ou déduit pour la fiction et la BD."""

from . import prefixe_cle, rules

GENRE_PAR_CADRE = {"801": "poesie", "802": "theatre", "803": "fiction", "804": "essai"}


def _litterature(langue: str | None, forme: str | None) -> str | None:
    R = rules("dewey")
    chiffre = R["genres"].get(forme or "")
    if not chiffre:
        return None
    lit = R["litterature"].get(langue or "")
    if not lit:
        return "800"            # langue inconnue : littérature, généralités
    return lit["base"] + chiffre


def deduire(f: dict) -> str | None:
    cadre = f["cadre_src"]
    if f["bd"]:
        return "741.5"
    if cadre in GENRE_PAR_CADRE:
        return _litterature(f["langue"], f["forme"] if f["forme"] in rules("dewey")["genres"]
                            else GENRE_PAR_CADRE[cadre])
    if cadre == "800":
        lit = rules("dewey")["litterature"].get(f["langue"] or "")
        return (lit["base"] + "0") if lit and len(lit["base"]) == 2 else "809"
    if cadre and not cadre.startswith("80"):
        return cadre           # le cadre BnF suit les centaines/dizaines Dewey
    if cadre == "809" or f["public"] in ("jeunesse", "ado"):
        if f["forme"] == "documentaire":
            return None
        return _litterature(f["langue"], f["forme"] or "fiction")
    if f["forme"] in rules("dewey")["genres"]:
        return _litterature(f["langue"], f["forme"])
    return None


def classer(notice: dict, f: dict) -> dict | None:
    R = rules("dewey")
    prefixe = R["prefixes"].get(f["public"], "")
    if f["dewey_src"]:
        code, origine = f["dewey_src"], "source"
    else:
        code, origine = deduire(f), "deduit"
    if not code:
        return None
    return {"code": code, "libelle": libelle(code), "origine": origine, "prefixe": prefixe}


def forme_depuis_indice(code: str) -> str | None:
    """843 -> fiction, 841 -> poesie (pour les indices de littérature)."""
    R = rules("dewey")
    digit = _chiffre_genre(code)
    if not digit:
        return None
    for forme, chiffre in R["genres"].items():
        if chiffre == digit:
            return forme
    return None


def _chiffre_genre(code: str) -> str | None:
    R = rules("dewey")
    bases = sorted((v["base"] for v in R["litterature"].values()), key=len, reverse=True)
    for base in bases:
        if code.startswith(base) and len(code) > len(base) and code[len(base)] in "12345678":
            return code[len(base)]
    if len(code) >= 3 and code[0] == "8" and code[1] in "12345678" and code[2] in "12345678":
        return code[2]
    return None


def libelle(code: str) -> str | None:
    """Intitulé de la table [libelles] facultative, sinon la tranche de centaines : 843 -> 800-899."""
    table = rules("dewey").get("libelles", {})
    if code in table:
        return table[code]
    key = prefixe_cle(code, table)
    if key and len(key) >= 3:
        return table[key]
    for candidate in (code[:2] + "0", code[:1] + "00"):
        if candidate in table:
            return table[candidate]
    return f"{code[0]}00-{code[0]}99" if code[:1].isdigit() else None


def court(code: str) -> str:
    """Indice raccourci pour la cote : 363.7009052 -> 363.7 (3 décimales max)."""
    if not code or "." not in code:
        return code or ""
    entier, decimales = code.split(".", 1)
    decimales = decimales[: rules("dewey").get("decimales_cote", 3)].rstrip("0")
    return f"{entier}.{decimales}" if decimales else entier
