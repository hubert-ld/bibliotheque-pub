"""Library of Congress : cote complète fournie, ou sous-classe déduite du Dewey."""

import re

from . import prefixe_cle, rules


def classer(notice: dict, f: dict) -> dict | None:
    src = f["classes"].get("lcc")
    if src:
        code, origine = src, "source"
    else:
        key = prefixe_cle(f["dewey"], rules("lcc")["correspondance"]) if f["dewey"] else None
        code, origine = (rules("lcc")["correspondance"][key] if key else None), "deduit"
    if not code:
        return None
    return {"code": code, "libelle": libelle(code), "origine": origine}


def libelle(code: str) -> str | None:
    table = rules("lcc")["libelles"]
    m = re.match(r"^([A-Z]{1,3})(\d+)?", code.upper())
    if not m:
        return None
    letters, number = m.group(1), m.group(2)
    if number and f"{letters}{number}" in table:
        return table[f"{letters}{number}"]
    while letters:
        if letters in table:
            return table[letters]
        letters = letters[:-1]
    return None
