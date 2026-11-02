"""Library of Congress (SRU, MARC21) : indices LCC et Dewey des livres anglophones.

Interrogée seulement en complément, quand un livre n'a pas encore de LCC.
"""

import re
import xml.etree.ElementTree as ET

import httpx

from . import (
    Fetched, RateLimiter, clean_dewey, empty_record, get, pages_of, split_name,
    tri_name, year_of,
)

NAME = "loc"
URL = "http://lx2.loc.gov:210/LCDB"
limiter = RateLimiter(2.0)
NS = {"m": "http://www.loc.gov/MARC21/slim"}


def fetch(client: httpx.Client, isbn13: str) -> Fetched:
    params = {
        "operation": "searchRetrieve", "version": "1.1", "query": f"bath.isbn={isbn13}",
        "maximumRecords": "1", "recordSchema": "marcxml",
    }
    try:
        r = get(client, limiter, URL, params)
    except httpx.HTTPError as exc:
        return Fetched("erreur", str(exc))
    if r.status_code != 200:
        return Fetched("erreur", f"HTTP {r.status_code}")
    m = re.search(r"numberOfRecords>(\d+)", r.text)
    if not m or m.group(1) == "0":
        return Fetched("absent", r.text)
    return Fetched("ok", r.text)


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    return text.strip().rstrip(" /:;,.").strip() or None


def parse(payload: str, isbn13: str) -> dict | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    rec = root.find(".//m:record", NS)
    if rec is None:
        return None

    def subs(tag):
        out = []
        for df in rec.findall(f"m:datafield[@tag='{tag}']", NS):
            out.append([(sf.get("code"), sf.text or "") for sf in df.findall("m:subfield", NS)])
        return out

    def first(tag, code):
        for s in subs(tag):
            for c, v in s:
                if c == code and v.strip():
                    return v
        return None

    n = empty_record()
    n["titre"] = _clean(first("245", "a"))
    n["sous_titre"] = _clean(first("245", "b"))
    for tag in ("100", "700"):
        for s in subs(tag):
            name = next((v for c, v in s if c == "a"), None)
            roles = [v for c, v in s if c in ("e", "4")]
            if name and not any("transl" in r or r == "trl" for r in roles):
                nom, prenom = split_name(name)
                n["auteurs"].append(f"{prenom} {nom}".strip())
                n["auteurs_tri"].append(tri_name(nom, prenom))
    for tag in ("264", "260"):
        n["editeur"] = n["editeur"] or _clean(first(tag, "b"))
        n["annee"] = n["annee"] or year_of(first(tag, "c"))
    n["pages"] = pages_of(first("300", "a"))
    n["sujets"] = [
        " -- ".join(_clean(v) for c, v in s if c in ("a", "x", "y", "z") and _clean(v))
        for s in subs("650") + subs("651")
    ]
    n["resume"] = first("520", "a")
    cf008 = rec.find("m:controlfield[@tag='008']", NS)
    if cf008 is not None and cf008.text and len(cf008.text) >= 38:
        n["langue"] = cf008.text[35:38].strip() or None
        if cf008.text[22] in "abcj":
            n["public"] = "jeunesse"
        if cf008.text[33] in "1fjdp":
            n["forme"] = {"1": "fiction", "f": "fiction", "j": "nouvelles",
                          "d": "theatre", "p": "poesie"}[cf008.text[33]]
    classes = {}
    for s in subs("050"):
        lcc = " ".join(v.strip() for c, v in s if c in ("a", "b"))
        if lcc:
            classes["lcc"] = lcc
            break
    dewey = clean_dewey(first("082", "a"))
    if dewey:
        classes["dewey"] = dewey
    n["classes"] = classes
    return n
