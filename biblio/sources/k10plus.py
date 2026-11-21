"""K10plus (bibliothèques allemandes, SWB et GBV) : SRU sans clé, en MARC21. Interrogé pour les livres introuvables ailleurs."""

import httpx

from . import RateLimiter
from . import loc

NAME = "k10plus"
URL = "https://sru.k10plus.de/opac-de-627"
limiter = RateLimiter(1.0)
parse = loc.parse


def fetch(client: httpx.Client, isbn13: str):
    return loc.interroger_sru(client, limiter, URL, {"version": "1.1", "query": f"pica.isb={isbn13}", "recordSchema": "marcxml"})
