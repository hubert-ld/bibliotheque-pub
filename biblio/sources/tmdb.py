"""The Movie Database : description et affiche d'un film, en français. Clé gratuite ; recherche par titre seulement."""

import json

import httpx

from . import Fetched, LANG_2_TO_3, RateLimiter, empty_record, get, year_of

NAME = "tmdb"
URL = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/w500"
limiter = RateLimiter(0.3)


def fetch(client: httpx.Client, titre: str, cle: str) -> Fetched:
    base = {"api_key": cle, "language": "fr-FR"}
    try:
        r = get(client, limiter, f"{URL}/search/movie", {**base, "query": titre})
        if r.status_code == 401:
            return Fetched("erreur", "HTTP 401 : clé refusée")
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        resultats = r.json().get("results") or []
        if not resultats:
            return Fetched("absent", r.text)
        r = get(client, limiter, f"{URL}/movie/{resultats[0]['id']}", {**base, "append_to_response": "credits"})
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))
    return Fetched("ok", r.text) if r.status_code == 200 else Fetched("erreur", f"HTTP {r.status_code}")


def parse(payload: str, code: str | None) -> dict | None:
    try:
        d = json.loads(payload)
    except ValueError:
        return None
    if not d.get("title"):
        return None
    n = empty_record()
    n["titre"] = d["title"]
    if d.get("original_title") != d["title"]:
        n["sous_titre"] = d.get("original_title")
    for p in (d.get("credits") or {}).get("crew") or []:
        if p.get("job") == "Director" and p.get("name"):
            n["auteurs"].append(p["name"])
            n["auteurs_tri"].append(p["name"].upper())
    societes = d.get("production_companies") or []
    n["editeur"] = societes[0].get("name") if societes else None
    n["annee"] = year_of(d.get("release_date"))
    n["duree"] = d.get("runtime") or None
    n["langue"] = LANG_2_TO_3.get(d.get("original_language"), d.get("original_language"))
    n["resume"] = d.get("overview") or None
    n["sujets"] = [g["name"] for g in d.get("genres") or []]
    n["support"] = "dvd"
    if d.get("poster_path"):
        n["couverture_url"] = IMAGES + d["poster_path"]
    if d.get("id"):
        n["lien"] = f"https://www.themoviedb.org/movie/{d['id']}"
    return n
