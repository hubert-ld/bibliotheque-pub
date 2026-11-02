"""Catalogues interrogés pour décrire un livre à partir de son ISBN.

Chaque source expose :
  - NAME            identifiant court stocké dans raw_responses
  - fetch(client, isbn13) -> Fetched   (réseau, limité en débit)
  - parse(payload, isbn13) -> dict | None   (sans réseau, rejouable)

Le dict renvoyé par parse suit le format "notice normalisée" :
  titre, sous_titre, auteurs, auteurs_tri, editeur, collection, annee, pages,
  langue, langue_originale, resume, sujets, forme, public, couverture_url,
  classes = {dewey, cdu, lcc, cadre_bnf}
"""

import re
import threading
import time
from dataclasses import dataclass

import httpx

USER_AGENT = "biblio-perso/0.1 (catalogue de bibliotheque personnelle)"


@dataclass
class Fetched:
    statut: str            # ok | absent | erreur
    payload: str | None = None


class RateLimiter:
    """Impose un délai minimal entre deux requêtes vers un même service."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def get(client: httpx.Client, limiter: RateLimiter, url: str, params: dict) -> httpx.Response:
    """GET poli : respecte le limiteur et réessaie une fois après un 429/503."""
    for attempt in range(3):
        limiter.wait()
        response = client.get(url, params=params)
        if response.status_code in (429, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        return response
    return response


# --- utilitaires communs aux parseurs -------------------------------------------

LANG_2_TO_3 = {
    "fr": "fre", "en": "eng", "de": "ger", "it": "ita", "es": "spa", "pt": "por",
    "nl": "dut", "ru": "rus", "ja": "jpn", "zh": "chi", "ar": "ara", "la": "lat",
    "el": "gre", "pl": "pol", "sv": "swe", "no": "nor", "da": "dan", "he": "heb",
    "ko": "kor", "cs": "cze", "ca": "cat", "br": "bre",
}


def year_of(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(1[4-9]\d\d|20\d\d)", text)
    return int(m.group(1)) if m else None


def pages_of(text: str | int | None) -> int | None:
    """Nombre de pages : « 345 p. », « xii, 345 pages ; », « 1 vol. (345 p.) »."""
    if isinstance(text, int):
        return text
    if not text:
        return None
    m = re.search(r"(\d+)\]?\s*(?:pp?|pages?)\b", text, flags=re.I)
    return int(m.group(1)) if m else None


def split_name(full: str) -> tuple[str, str]:
    """'Thomas H. Cormen' -> ('Cormen', 'Thomas H.') ; 'Austen, Jane' -> ('Austen', 'Jane')."""
    full = full.strip().rstrip(",.")
    if "," in full:
        nom, prenom = full.split(",", 1)
        return nom.strip(), prenom.strip()
    parts = full.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def tri_name(nom: str, prenom: str) -> str:
    return f"{nom.upper()} {prenom}".strip()


def clean_dewey(code: str | None) -> str | None:
    """'363.700 9052' -> '363.7009052' ; rejette '[Fic]', 'B', etc."""
    if not code:
        return None
    code = code.replace(" ", "").replace("/", "").replace("'", "")
    m = re.match(r"^(\d{3})(\.\d+)?", code)
    return m.group(0) if m else None


def empty_record() -> dict:
    return {
        "titre": None, "sous_titre": None, "auteurs": [], "auteurs_tri": [],
        "editeur": None, "collection": None, "annee": None, "pages": None,
        "langue": None, "langue_originale": None, "resume": None, "sujets": [],
        "forme": None, "public": None, "couverture_url": None, "classes": {},
    }


def openlibrary_cover(isbn13: str) -> str:
    return f"https://covers.openlibrary.org/b/isbn/{isbn13}-M.jpg?default=false"
