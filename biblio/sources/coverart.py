"""Cover Art Archive : les pochettes de MusicBrainz. Pas de notice : on le teste seulement dans l'administration."""

import httpx

from . import Fetched

NAME = "coverart"
URL = "https://coverartarchive.org/release"


def fetch(client: httpx.Client, mbid: str) -> Fetched:
    try:
        r = client.get(f"{URL}/{mbid}", timeout=15)
    except httpx.HTTPError as exc:
        return Fetched("erreur", str(exc))
    if r.status_code == 404:
        return Fetched("absent", None)
    return Fetched("ok", None) if r.status_code == 200 else Fetched("erreur", f"HTTP {r.status_code}")
