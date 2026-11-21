"""Sudoc (ABES) : le catalogue des bibliothèques universitaires françaises, en UNIMARC.

Sans clé. Contrairement à la BnF, il donne souvent un indice Dewey pour la fiction : il complète donc
ses notices, et décrit des livres qu'elle n'a pas (éditions étrangères, thèses, ouvrages savants).
"""

import json
import xml.etree.ElementTree as ET

import httpx

from . import Fetched, RateLimiter, get
from . import bnf

NAME = "sudoc"
URL = "https://www.sudoc.fr"
limiter = RateLimiter(1.0)


def fetch(client: httpx.Client, isbn13: str) -> Fetched:
    """Deux temps : le numéro de notice (PPN) de cet ISBN, puis la notice elle-même."""
    try:
        r = get(client, limiter, f"{URL}/services/isbn2ppn/{isbn13}&format=text/json", {})
        if r.status_code == 404:
            return Fetched("absent", r.text)
        if r.status_code != 200:
            return Fetched("erreur", f"HTTP {r.status_code}")
        try:
            resultat = json.loads(r.text)["sudoc"]["query"]["result"]
        except (ValueError, KeyError, TypeError):
            return Fetched("absent", r.text)
        ppn = (resultat if isinstance(resultat, list) else [resultat])[0]["ppn"]
        r = get(client, limiter, f"{URL}/{ppn}.xml", {})
    except httpx.HTTPError as exc:
        return Fetched("erreur", str(exc))
    if r.status_code != 200:
        return Fetched("erreur", f"HTTP {r.status_code}")
    return Fetched("ok", r.text)


def parse(payload: str, isbn13: str | None) -> dict | None:
    try:
        rec = ET.fromstring(payload)
    except ET.ParseError:
        return None
    if rec.tag != "record":
        return None
    n = bnf.parse_record(rec, isbn13)
    ppn = rec.find("controlfield[@tag='001']")
    if ppn is not None and ppn.text:
        n["lien"] = f"{URL}/{ppn.text}"
    n["couverture_url"] = None
    return n
