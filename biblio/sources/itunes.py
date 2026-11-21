"""iTunes Search : complément pour les disques (pochette en grand, pistes, genre). Sans clé ; ne connaît que les albums vendus en ligne."""

import json

import httpx

from . import Fetched, RateLimiter, empty_record, get, year_of

NAME = "itunes"
URL = "https://itunes.apple.com/lookup"
limiter = RateLimiter(3.0)


def fetch(client: httpx.Client, ean: str) -> Fetched:
    try:
        r = get(client, limiter, URL, {"upc": ean, "country": "fr", "entity": "song"})
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        return Fetched("ok" if r.json().get("resultCount") else "absent", r.text)
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))


def parse(payload: str, code: str | None) -> dict | None:
    try:
        resultats = json.loads(payload).get("results") or []
    except ValueError:
        return None
    album = next((r for r in resultats if r.get("wrapperType") == "collection"), None)
    if not album:
        return None
    n = empty_record()
    n["titre"] = album.get("collectionName")
    if album.get("artistName"):
        n["auteurs"], n["auteurs_tri"] = [album["artistName"]], [album["artistName"].upper()]
    n["annee"] = year_of(album.get("releaseDate"))
    if album.get("primaryGenreName"):
        n["sujets"] = [album["primaryGenreName"]]
    for t in resultats:
        if t.get("wrapperType") == "track":
            n["pistes"].append({"titre": t.get("trackName"), "duree": round((t.get("trackTimeMillis") or 0) / 1000) or None,
                                "disque": t.get("discNumber") or 1})
    n["duree"] = round(sum(p["duree"] or 0 for p in n["pistes"]) / 60) or None
    if album.get("artworkUrl100"):
        n["couverture_url"] = album["artworkUrl100"].replace("100x100", "600x600")
    n["lien"] = album.get("collectionViewUrl")
    return n
