"""UPCitemdb (essai gratuit, sans clé) : la seule source ouverte qui relie un code-barres de DVD à un titre.

Quota réduit, données de commerce : le titre est bruité (« Film [regio Free (0)] - Acteur »), et il sert
surtout à interroger TMDb et OMDb, qui ne cherchent que par titre.
"""

import json
import re

import httpx

from . import Fetched, RateLimiter, empty_record, get

NAME = "upcitemdb"
URL = "https://api.upcitemdb.com/prod/trial/lookup"
limiter = RateLimiter(10.0)


def fetch(client: httpx.Client, ean: str) -> Fetched:
    try:
        r = get(client, limiter, URL, {"upc": ean})
        if r.status_code == 429:
            return Fetched("erreur", "quota dépassé")
        if r.status_code == 400 or r.status_code == 404:
            return Fetched("absent", r.text)
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        return Fetched("ok" if r.json().get("items") else "absent", r.text)
    except (httpx.HTTPError, ValueError) as exc:
        return Fetched("erreur", str(exc))


def titre_propre(titre: str | None) -> str | None:
    """« Fast And Furious 2 [regio Free (0)] - Paul Walker… » -> « Fast And Furious 2 »."""
    if not titre:
        return None
    titre = re.split(r"\s+[-–—]\s+", titre)[0]
    titre = re.sub(r"\[[^\]]*\]?|\([^)]*\)?", " ", titre)
    titre = re.sub(r"\b(dvd|blu-?ray|bluray|4k|uhd|edition|édition|import|region\s*\w+|regio\s*\w+)\b", " ", titre, flags=re.I)
    return re.sub(r"\s+", " ", titre).strip(" -–—,:") or None


def parse(payload: str, code: str | None) -> dict | None:
    try:
        items = json.loads(payload).get("items") or []
    except ValueError:
        return None
    if not items:
        return None
    d = items[0]
    n = empty_record()
    n["titre"] = titre_propre(d.get("title"))
    n["editeur"] = d.get("brand") or None
    texte = f"{d.get('title')} {d.get('category')}".lower()
    musique = "music" in texte or re.search(r"\b(cd|vinyl)\b", texte)
    if re.search(r"blu-?ray", d.get("title") or "", flags=re.I):
        n["support"] = "bluray"
    else:
        n["support"] = "cd" if musique else "dvd"
    n["couverture_url"] = next(iter(d.get("images") or []), None)
    return n
