"""Deutsche Nationalbibliothek : SRU sans clé, en MARC21. Interrogée pour les livres introuvables ailleurs."""

import httpx

from . import RateLimiter
from . import loc

NAME = "dnb"
URL = "https://services.dnb.de/sru/dnb"
limiter = RateLimiter(1.0)
parse = loc.parse


def fetch(client: httpx.Client, isbn13: str):
    return loc.interroger_sru(client, limiter, URL, {"version": "1.1", "query": f"num={isbn13}", "recordSchema": "MARC21-xml"})
