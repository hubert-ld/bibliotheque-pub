"""Deezer : complément pour les disques français récents (pochette, pistes, genre). Sans clé."""

import json

import httpx

from . import Fetched, RateLimiter, empty_record, formes_ean, get, year_of

NAME = "deezer"
URL = "https://api.deezer.com/album/upc:"
limiter = RateLimiter(0.5)
PAS_DE_DONNEES = 800


def fetch(client: httpx.Client, ean: str) -> Fetched:
    try:
        for forme in formes_ean(ean):
            r = get(client, limiter, URL + forme, {})
            if r.status_code != 200:
                return Fetched("erreur", f"HTTP {r.status_code}")
            erreur = r.json().get("error")
            if not erreur:
                return Fetched("ok", r.text)
            if erreur.get("code") != PAS_DE_DONNEES:           # quota dépassé, par exemple
                return Fetched("erreur", str(erreur.get("message")))
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))
    return Fetched("absent", r.text)


def parse(payload: str, code: str | None) -> dict | None:
    try:
        d = json.loads(payload)
    except ValueError:
        return None
    if not d.get("title") or d.get("error"):
        return None
    n = empty_record()
    n["titre"] = d["title"]
    artiste = (d.get("artist") or {}).get("name")
    if artiste:
        n["auteurs"], n["auteurs_tri"] = [artiste], [artiste.upper()]
    n["editeur"] = d.get("label")
    n["annee"] = year_of(d.get("release_date"))
    n["sujets"] = [g["name"] for g in (d.get("genres") or {}).get("data") or []]
    n["pistes"] = [{"titre": t.get("title"), "duree": t.get("duration"), "disque": 1}
                   for t in (d.get("tracks") or {}).get("data") or []]
    n["duree"] = round((d.get("duration") or 0) / 60) or None
    n["couverture_url"] = d.get("cover_big") or d.get("cover_medium")
    n["lien"] = d.get("link")
    return n
