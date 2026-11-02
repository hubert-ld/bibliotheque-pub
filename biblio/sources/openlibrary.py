"""Open Library (Internet Archive) : bonne couverture anglophone, couvertures, LCC."""

import json

import httpx

from . import (
    Fetched, RateLimiter, clean_dewey, empty_record, get, pages_of, split_name,
    tri_name, year_of,
)

NAME = "openlibrary"
URL = "https://openlibrary.org/api/books"
limiter = RateLimiter(1.0)


def fetch(client: httpx.Client, isbn13: str) -> Fetched:
    params = {"bibkeys": f"ISBN:{isbn13}", "format": "json", "jscmd": "data"}
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
    return Fetched("ok" if data else "absent", r.text)


def parse(payload: str, isbn13: str) -> dict | None:
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    book = data.get(f"ISBN:{isbn13}") or next(iter(data.values()), None)
    if not book:
        return None
    n = empty_record()
    n["titre"] = book.get("title")
    n["sous_titre"] = book.get("subtitle")
    for a in book.get("authors") or []:
        name = a.get("name")
        if name:
            n["auteurs"].append(name)
            n["auteurs_tri"].append(tri_name(*split_name(name)))
    pubs = book.get("publishers") or []
    n["editeur"] = pubs[0].get("name") if pubs else None
    n["annee"] = year_of(book.get("publish_date"))
    n["pages"] = book.get("number_of_pages") or pages_of(book.get("pagination"))
    n["sujets"] = [s["name"] for s in book.get("subjects") or [] if s.get("name")][:15]
    cover = book.get("cover") or {}
    n["couverture_url"] = cover.get("medium") or cover.get("large")
    excerpts = book.get("excerpts") or []
    if excerpts and excerpts[0].get("text"):
        n["resume"] = excerpts[0]["text"]

    classes = {}
    cls = book.get("classifications") or {}
    for code in cls.get("dewey_decimal_class") or []:
        if clean_dewey(code):
            classes["dewey"] = clean_dewey(code)
            break
    lcc = cls.get("lc_classifications") or []
    if lcc:
        classes["lcc"] = lcc[0].strip()
    n["classes"] = classes

    if any("juvenile" in s.lower() for s in n["sujets"]):
        n["public"] = "jeunesse"
    lowered = " ".join(n["sujets"]).lower()
    if "fiction" in lowered and "nonfiction" not in lowered.replace("non-fiction", "nonfiction"):
        n["forme"] = "fiction"
    if book.get("url"):
        n["lien"] = book["url"]
    return n
