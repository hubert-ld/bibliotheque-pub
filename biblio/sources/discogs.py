"""Discogs : la plus grande base de disques, vinyles compris. Répond sans jeton à 25 requêtes/min, sans les pochettes.

Un jeton personnel gratuit (Discogs › Settings › Developers) les ajoute et double le quota.
"""

import json

import httpx

from . import Fetched, RateLimiter, empty_record, formes_ean, get, support_du_format, year_of

NAME = "discogs"
URL = "https://api.discogs.com/database/search"
limiter = RateLimiter(2.5)


def fetch(client: httpx.Client, ean: str, jeton: str | None = None) -> Fetched:
    params = {"type": "release", "per_page": "10"}
    if jeton:
        params["token"] = jeton
    try:
        for forme in formes_ean(ean):
            r = get(client, limiter, URL, {**params, "barcode": forme})
            if r.status_code in (401, 403):
                return Fetched("erreur", f"HTTP {r.status_code} : jeton refusé")
            if r.status_code != 200:
                return Fetched("erreur", f"HTTP {r.status_code}")
            if r.json().get("results"):
                return Fetched("ok", r.text)
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))
    return Fetched("absent", r.text)


def parse(payload: str, code: str | None) -> dict | None:
    try:
        resultats = json.loads(payload).get("results") or []
    except ValueError:
        return None
    if not resultats:
        return None
    d = min(resultats, key=lambda r: r.get("country") != "France")
    n = empty_record()
    artiste, separe, titre = (d.get("title") or "").partition(" - ")
    n["titre"] = titre if separe else artiste
    if separe:
        n["auteurs"], n["auteurs_tri"] = [artiste], [artiste.upper()]
    n["editeur"] = next(iter(d.get("label") or []), None)
    n["ref_catalogue"] = d.get("catno")
    n["annee"] = year_of(d.get("year"))
    n["sujets"] = list(dict.fromkeys([*(d.get("genre") or []), *(d.get("style") or [])]))
    formats = d.get("formats") or []
    if formats:
        n["support"] = support_du_format(formats[0].get("name"))
        qte = str(formats[0].get("qty") or "")
        n["nb_disques"] = int(qte) if qte.isdigit() else None
    n["couverture_url"] = d.get("cover_image") or d.get("thumb") or None
    if d.get("uri"):
        n["lien"] = f"https://www.discogs.com{d['uri']}"
    return n
