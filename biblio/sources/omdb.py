"""OMDb : description d'un film, en anglais, quand TMDb ne répond pas. Clé gratuite ; recherche par titre seulement."""

import json
import re

import httpx

from . import Fetched, RateLimiter, empty_record, get, year_of

NAME = "omdb"
URL = "https://www.omdbapi.com/"
limiter = RateLimiter(1.0)


def fetch(client: httpx.Client, titre: str, cle: str) -> Fetched:
    try:
        r = get(client, limiter, URL, {"t": titre, "apikey": cle})
        if r.status_code == 401:
            return Fetched("erreur", "HTTP 401 : clé refusée")
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        return Fetched("ok" if r.json().get("Response") == "True" else "absent", r.text)
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))


def _valeur(d: dict, cle: str) -> str | None:
    v = d.get(cle)
    return None if v in (None, "", "N/A") else v


def parse(payload: str, code: str | None) -> dict | None:
    try:
        d = json.loads(payload)
    except ValueError:
        return None
    if d.get("Response") != "True" or not d.get("Title"):
        return None
    n = empty_record()
    n["titre"] = d["Title"]
    for nom in re.split(r",\s*", _valeur(d, "Director") or ""):
        if nom:
            n["auteurs"].append(nom)
            n["auteurs_tri"].append(nom.upper())
    n["annee"] = year_of(_valeur(d, "Year"))
    duree = re.match(r"\d+", _valeur(d, "Runtime") or "")
    n["duree"] = int(duree.group()) if duree else None
    n["resume"] = _valeur(d, "Plot")
    n["sujets"] = re.split(r",\s*", _valeur(d, "Genre") or "") if _valeur(d, "Genre") else []
    n["editeur"] = _valeur(d, "Production")
    n["support"] = "dvd"
    n["couverture_url"] = _valeur(d, "Poster")
    if _valeur(d, "imdbID"):
        n["lien"] = f"https://www.imdb.com/title/{d['imdbID']}/"
    return n
