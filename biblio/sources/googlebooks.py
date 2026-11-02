"""Google Books : résumés et couvertures.

Sans clé, le quota anonyme est partagé par tout le monde et souvent épuisé.
Cette source n'est donc utilisée que si une clé API (gratuite, 1 000 req/jour)
est configurée : `biblio config google_api_key <clé>`.
"""

import json

import httpx

from . import (
    LANG_2_TO_3, Fetched, RateLimiter, empty_record, get, split_name, tri_name, year_of,
)

NAME = "google"
URL = "https://www.googleapis.com/books/v1/volumes"
limiter = RateLimiter(1.0)


def fetch(client: httpx.Client, isbn13: str, api_key: str) -> Fetched:
    params = {"q": f"isbn:{isbn13}", "key": api_key}
    try:
        r = get(client, limiter, URL, params)
    except httpx.HTTPError as exc:
        return Fetched("erreur", str(exc))
    if r.status_code != 200:
        return Fetched("erreur", f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        return Fetched("erreur", "réponse non JSON")
    return Fetched("ok" if data.get("totalItems") else "absent", r.text)


def parse(payload: str, isbn13: str) -> dict | None:
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    items = data.get("items") or []
    if not items:
        return None
    v = items[0].get("volumeInfo", {})
    n = empty_record()
    n["titre"] = v.get("title")
    n["sous_titre"] = v.get("subtitle")
    for name in v.get("authors") or []:
        n["auteurs"].append(name)
        n["auteurs_tri"].append(tri_name(*split_name(name)))
    n["editeur"] = v.get("publisher")
    n["annee"] = year_of(v.get("publishedDate"))
    n["pages"] = v.get("pageCount")
    n["langue"] = LANG_2_TO_3.get(v.get("language"), v.get("language"))
    n["resume"] = v.get("description")
    n["sujets"] = v.get("categories") or []
    images = v.get("imageLinks") or {}
    cover = images.get("thumbnail") or images.get("smallThumbnail")
    if cover:
        n["couverture_url"] = cover.replace("http://", "https://")
    cats = " ".join(n["sujets"]).lower()
    if "juvenile" in cats:
        n["public"] = "jeunesse"
    if "fiction" in cats and "nonfiction" not in cats:
        n["forme"] = "fiction"
    if v.get("infoLink"):
        n["lien"] = v["infoLink"]
    return n
