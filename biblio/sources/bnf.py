"""Catalogue général de la BnF (API SRU, format UNIMARC).

Source principale pour les livres publiés en France (dépôt légal).
La BnF fournit un indice Dewey (676) pour les documentaires, mais pas pour
la fiction : elle indique alors le « cadre de classement de la Bibliographie
nationale française » (686), ex. 803 = romans, 805 = BD, 809 = jeunesse.
"""

import re
import xml.etree.ElementTree as ET

import httpx

from . import (
    Fetched, RateLimiter, empty_record, get, openlibrary_cover, pages_of,
    tri_name, year_of, clean_dewey,
)
from ..isbn import IsbnError, hyphenless_variants, normalize

NAME = "bnf"
URL = "https://catalogue.bnf.fr/api/SRU"
limiter = RateLimiter(1.0)

NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "mxc": "info:lc/xmlns/marcxchange-v2",
}

# 105 $a position 11 : code de forme littéraire
FORMES_105 = {
    "a": "fiction", "b": "theatre", "c": "essai", "d": "humour", "e": "lettres",
    "f": "nouvelles", "g": "poesie", "h": "discours", "i": "livret",
    "y": "documentaire", "z": "mixte",
}
# 100 $a position 17 : public visé
PUBLIC_100 = {
    "a": "jeunesse", "b": "jeunesse", "c": "jeunesse", "d": "jeunesse",
    "e": "ado", "k": "adulte", "m": "adulte",
}
# Mentions de genre fréquentes en 200 $e, qui ne sont pas de vrais sous-titres
GENRES_200E = {
    "roman": "fiction", "romans": "fiction", "récit": "fiction", "récits": "fiction",
    "nouvelles": "nouvelles", "nouvelle": "nouvelles", "poèmes": "poesie",
    "poésie": "poesie", "poésies": "poesie", "théâtre": "theatre", "pièce": "theatre",
    "essai": "essai", "essais": "essai", "roman policier": "fiction",
    "roman graphique": "fiction", "conte": "fiction", "contes": "fiction",
}
NON_SORT = re.compile(r"[\x88\x89\x98\x9c]")
ET.register_namespace("srw", NS["srw"])
ET.register_namespace("mxc", NS["mxc"])


def fetch(client: httpx.Client, isbn13: str) -> Fetched:
    query = " or ".join(f'bib.isbn all "{v}"' for v in hyphenless_variants(isbn13))
    params = {
        "version": "1.2", "operation": "searchRetrieve", "query": query,
        "recordSchema": "unimarcxchange", "maximumRecords": "5",
    }
    try:
        r = get(client, limiter, URL, params)
    except httpx.HTTPError as exc:
        return Fetched("erreur", str(exc))
    if r.status_code != 200:
        return Fetched("erreur", f"HTTP {r.status_code}")
    m = re.search(r"<srw:numberOfRecords>(\d+)", r.text)
    if not m or m.group(1) == "0":
        return Fetched("absent", r.text)
    return Fetched("ok", r.text)


# --- lecture UNIMARC ------------------------------------------------------------

def _fields(record: ET.Element) -> list[tuple[str, list[tuple[str, str]]]]:
    out = []
    for df in record.findall("mxc:datafield", NS):
        subs = [(sf.get("code"), NON_SORT.sub("", sf.text or "").strip())
                for sf in df.findall("mxc:subfield", NS)]
        out.append((df.get("tag"), subs))
    return out


def _first(fields, tag: str, code: str) -> str | None:
    for t, subs in fields:
        if t == tag:
            for c, v in subs:
                if c == code and v:
                    return v
    return None


def _all(fields, tag: str):
    return [subs for t, subs in fields if t == tag]


def _sub(subs, code: str) -> str | None:
    for c, v in subs:
        if c == code and v:
            return v
    return None


def _subs(subs, code: str) -> list[str]:
    return [v for c, v in subs if c == code and v]


def _digits(text: str | None) -> str:
    return re.sub(r"[^0-9X]", "", (text or "").upper())


def _pick_record(records: list[ET.Element], isbn13: str) -> ET.Element | None:
    """Plusieurs notices peuvent répondre : on préfère l'ISBN exact en texte imprimé."""
    wanted = set(hyphenless_variants(isbn13))
    best, best_score = None, -1
    for rec in records:
        fields = _fields(rec)
        score = 0
        if any(_digits(_sub(s, "a")) in wanted for s in _all(fields, "010")):
            score += 2
        support = _first(fields, "200", "b") or ""
        if not support or "imprimé" in support.lower():
            score += 1
        if score > best_score:
            best, best_score = rec, score
    return best


def _subject(tag: str, subs) -> str | None:
    parts = []
    for c, v in subs:
        if c == "a":
            parts.append(v)
        elif c == "b" and tag == "600" and parts:
            parts[-1] = f"{parts[-1]}, {v}"
        elif c in ("x", "y", "z", "j", "t"):
            parts.append(v)
    return " -- ".join(parts) if parts else None


class RechercheImpossible(Exception):
    """La BnF n'a pas pu être interrogée (réseau, service indisponible)."""


def rechercher(client: httpx.Client, titre: str = "", auteur: str = "", annee: str | int | None = None,
               maximum: int = 10) -> list[dict]:
    """Recherche par titre et auteur, pour les livres sans code-barre (souvent sans ISBN).

    Chaque résultat : ark, isbn (ou None), titre, auteurs, editeur, annee, et la notice
    UNIMARC brute (`xml`), à ranger telle quelle pour décrire le livre sans autre requête.
    """
    parties = []
    for index, valeur in (("bib.title", titre), ("bib.author", auteur), ("bib.date", annee)):
        valeur = re.sub(r'["\\]', " ", str(valeur or "")).strip()
        if valeur:
            parties.append(f'{index} all "{valeur}"')
    if not parties:
        return []
    params = {
        "version": "1.2", "operation": "searchRetrieve", "query": " and ".join(parties),
        "recordSchema": "unimarcxchange", "maximumRecords": str(maximum),
    }
    try:
        r = get(client, limiter, URL, params)
    except httpx.HTTPError as exc:
        raise RechercheImpossible(str(exc)) from exc
    if r.status_code != 200:
        raise RechercheImpossible(f"HTTP {r.status_code}")
    return lire_resultats(r.text)


def lire_resultats(payload: str) -> list[dict]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RechercheImpossible(str(exc)) from exc
    out = []
    for rec in root.findall(".//mxc:record", NS):
        f = _fields(rec)
        isbn = None
        for subs in _all(f, "010"):
            try:
                isbn = normalize(_sub(subs, "a") or "")
                break
            except IsbnError:
                continue
        n = parse_record(rec, isbn)
        if not n.get("titre"):
            continue
        out.append({"ark": rec.get("id"), "isbn": isbn, "titre": n["titre"], "sous_titre": n["sous_titre"],
                    "auteurs": n["auteurs"], "editeur": n["editeur"], "annee": n["annee"],
                    "collection": n["collection"], "xml": ET.tostring(rec, encoding="unicode")})
    return out


def reponse_unique(xml_notice: str) -> str:
    """Enveloppe SRU autour d'une seule notice, lisible ensuite par parse()."""
    return (f'<srw:searchRetrieveResponse xmlns:srw="{NS["srw"]}"><srw:numberOfRecords>1</srw:numberOfRecords>'
            f"<srw:records><srw:record><srw:recordData>{xml_notice}</srw:recordData></srw:record></srw:records>"
            "</srw:searchRetrieveResponse>")


def parse(payload: str, isbn13: str | None) -> dict | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    records = root.findall(".//mxc:record", NS)
    rec = _pick_record(records, isbn13) if isbn13 else (records or [None])[0]
    if rec is None:
        return None
    return parse_record(rec, isbn13)


def parse_record(rec: ET.Element, isbn13: str | None) -> dict:
    """Une notice UNIMARC -> champs de la bibliothèque."""
    f = _fields(rec)
    n = empty_record()

    # Titre (200) : $a titre propre, $h/$i numéro et titre de partie, $e complément
    t200 = (_all(f, "200") or [[]])[0]
    titre = _sub(t200, "a")
    h, i = _sub(t200, "h"), _sub(t200, "i")
    if titre and (h or i):
        titre = titre + ". " + ", ".join(filter(None, [h, i]))
    elif not titre and i:
        titre = i
    n["titre"] = titre
    forme_hint = None
    for e in _subs(t200, "e"):
        genre = GENRES_200E.get(e.lower().strip())
        if genre:
            forme_hint = forme_hint or genre
        elif not n["sous_titre"]:
            n["sous_titre"] = e

    # Auteurs : 700 (principal), 701 (co-auteurs), 710/711 (collectivités)
    for tag in ("700", "701"):
        for subs in _all(f, tag):
            nom, prenom = _sub(subs, "a"), _sub(subs, "b") or ""
            if not nom or "730" in _subs(subs, "4"):        # 730 = traducteur
                continue
            n["auteurs"].append(f"{prenom} {nom}".strip())
            n["auteurs_tri"].append(tri_name(nom, prenom))
    for tag in ("710", "711"):
        for subs in _all(f, tag):
            nom = _sub(subs, "a")
            if nom:
                n["auteurs"].append(nom)
                n["auteurs_tri"].append(nom.upper())

    # Publication : 214 (format récent) ou 210
    for tag in ("214", "210"):
        for subs in _all(f, tag):
            n["editeur"] = n["editeur"] or _sub(subs, "c")
            n["annee"] = n["annee"] or year_of(_sub(subs, "d"))
    c100 = _first(f, "100", "a") or ""
    if not n["annee"]:
        n["annee"] = year_of(c100[9:13])
    # Positions 17-19 : jusqu'à trois codes de public ; un code adulte l'emporte.
    publics = {PUBLIC_100.get(c) for c in c100[17:20]} - {None}
    for p in ("adulte", "ado", "jeunesse"):
        if p in publics:
            n["public"] = p
            break

    n["pages"] = pages_of(_first(f, "215", "a"))

    collections = []
    for subs in _all(f, "225"):
        a = _sub(subs, "a")
        if a:
            v = _sub(subs, "v")
            collections.append(f"{a} ; {v}" if v else a)
    n["collection"] = " | ".join(collections) or None

    n["langue"] = _first(f, "101", "a")
    n["langue_originale"] = _first(f, "101", "c")
    n["resume"] = _first(f, "330", "a")

    for tag in ("600", "601", "602", "604", "605", "606", "607", "608"):
        for subs in _all(f, tag):
            s = _subject(tag, subs)
            if s and s not in n["sujets"]:
                n["sujets"].append(s)

    c105 = _first(f, "105", "a") or ""
    n["forme"] = FORMES_105.get(c105[11]) if len(c105) > 11 else None
    if n["forme"] in (None, "mixte"):
        n["forme"] = forme_hint or n["forme"]

    classes = {}
    dewey = clean_dewey(_first(f, "676", "a"))
    if dewey:
        classes["dewey"] = dewey
    cdu = _first(f, "675", "a")
    if cdu:
        classes["cdu"] = cdu.strip()
    for subs in _all(f, "680"):
        lcc = " ".join(filter(None, [_sub(subs, "a"), _sub(subs, "b")]))
        if lcc:
            classes["lcc"] = lcc
            break
    for subs in _all(f, "686"):
        if "cadre de classement" in (_sub(subs, "2") or "").lower():
            classes["cadre_bnf"] = _sub(subs, "a")
            break
    n["classes"] = classes

    # La BnF range la littérature jeunesse en 809. Un autre cadre avec un public
    # "9-14 ans / jeunes adultes" (codes d, e) vient souvent d'un vieux catalogage
    # de classiques de poche étudiés en classe : on suit alors le cadre.
    cadre = classes.get("cadre_bnf")
    if (n["public"] in ("jeunesse", "ado") and cadre and cadre != "809"
            and not set(c100[17:20]) & set("abc")):
        n["public"] = "adulte"

    ark = rec.get("id")
    if ark:
        n["lien"] = f"https://catalogue.bnf.fr/{ark}"
    n["couverture_url"] = openlibrary_cover(isbn13) if isbn13 else None
    return n
