"""MusicBrainz : la base ouverte de référence pour les disques (pistes, format, label). Sans clé, 1 requête/s.

Les pochettes viennent de Cover Art Archive. Un code-barres y est noté avec ou sans son 0 de tête : on
cherche les deux. Plusieurs éditions partagent souvent un code : on préfère l'édition française.
"""

import json

import httpx

from . import Fetched, RateLimiter, empty_record, formes_ean, get, split_name, support_du_format, tri_name, year_of

NAME = "musicbrainz"
URL = "https://musicbrainz.org/ws/2/release"
limiter = RateLimiter(1.1)


def _choisir(releases: list[dict]) -> dict | None:
    return min(releases, key=lambda r: (r.get("country") != "FR", -(r.get("score") or 0)), default=None)


def fetch(client: httpx.Client, ean: str) -> Fetched:
    requete = " OR ".join(f"barcode:{f}" for f in formes_ean(ean))
    try:
        r = get(client, limiter, URL, {"query": requete, "fmt": "json", "limit": "10"})
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        choix = _choisir(r.json().get("releases") or [])
        if not choix:
            return Fetched("absent", r.text)
        r = get(client, limiter, f"{URL}/{choix['id']}", {"fmt": "json", "inc": "recordings artist-credits labels genres"})
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))
    if r.status_code != 200:
        return Fetched("erreur", f"HTTP {r.status_code}")
    return Fetched("ok", r.text)


def parse(payload: str, code: str | None) -> dict | None:
    try:
        d = json.loads(payload)
    except ValueError:
        return None
    if not d.get("title") or "media" not in d:
        return None
    n = empty_record()
    n["titre"] = d["title"]
    for credit in d.get("artist-credit") or []:
        nom = credit.get("name") or (credit.get("artist") or {}).get("name")
        if nom:
            n["auteurs"].append(nom)
            tri = (credit.get("artist") or {}).get("sort-name") or nom
            n["auteurs_tri"].append(tri_name(*split_name(tri)) if "," in tri else tri.upper())
    labels = d.get("label-info") or []
    if labels:
        n["editeur"] = (labels[0].get("label") or {}).get("name")
        n["ref_catalogue"] = labels[0].get("catalog-number")
    n["annee"] = year_of(d.get("date"))
    n["langue"] = (d.get("text-representation") or {}).get("language")
    n["sujets"] = [g["name"] for g in sorted(d.get("genres") or [], key=lambda g: -g.get("count", 0))]
    medias = d["media"]
    n["support"] = next((s for s in map(support_du_format, (m.get("format") for m in medias)) if s), None)
    n["nb_disques"] = len(medias) or None
    for m in medias:
        for t in m.get("tracks") or []:
            n["pistes"].append({"titre": t.get("title"), "duree": round((t.get("length") or 0) / 1000) or None,
                                "disque": m.get("position") or 1})
    total = sum(p["duree"] or 0 for p in n["pistes"])
    n["duree"] = round(total / 60) or None
    if (d.get("cover-art-archive") or {}).get("front"):
        n["couverture_url"] = f"https://coverartarchive.org/release/{d['id']}/front-500"
    n["lien"] = f"https://musicbrainz.org/release/{d['id']}"
    return n
