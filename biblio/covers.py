"""Couvertures téléchargées une fois pour toutes dans data/covers/.

Open Library limite les couvertures demandées par ISBN (~100 par 5 min) :
les garder localement rend le catalogue rapide, et utilisable hors ligne.
"""

import os
from pathlib import Path

import httpx

from . import db
from .sources import RateLimiter

DOSSIER = Path(os.environ.get("BIBLIO_COVERS", db.PROJECT_DIR / "data" / "covers"))
limiter = RateLimiter(1.0)
TAILLE_MIN = 1000            # en dessous : image vide renvoyée faute de couverture


def chemin(isbn13: str) -> Path:
    return DOSSIER / f"{isbn13}.jpg"


def absente(isbn13: str) -> Path:
    return DOSSIER / f"{isbn13}.absente"


def connue(isbn13: str) -> bool:
    return chemin(isbn13).exists() or absente(isbn13).exists()


def telecharger(client: httpx.Client, isbn13: str, urls: str | list[str] | None, forcer: bool = False) -> bool:
    """Essaie chaque adresse jusqu'à obtenir une image. `urls` : une adresse, ou plusieurs par préférence.

    Le livre n'est noté sans couverture que si toutes ont répondu. Avec `forcer`, l'image
    déjà présente n'est remplacée que par une nouvelle : elle n'est jamais perdue.
    """
    urls = [u for u in ([urls] if isinstance(urls, str) else urls or []) if u]
    if not urls:
        return False
    if not forcer and connue(isbn13):
        return chemin(isbn13).exists()
    DOSSIER.mkdir(parents=True, exist_ok=True)
    toutes_ont_repondu = True
    for url in urls:
        limiter.wait()
        try:
            r = client.get(url, timeout=30)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol):
            continue                    # adresse inutilisable : autant dire pas d'image
        except httpx.HTTPError:
            toutes_ont_repondu = False  # réseau : on réessaiera plus tard
            continue
        if r.status_code == 200 and len(r.content) >= TAILLE_MIN and r.headers.get("content-type", "").startswith("image"):
            chemin(isbn13).write_bytes(r.content)
            absente(isbn13).unlink(missing_ok=True)
            return True
        if r.status_code not in (200, 404):
            toutes_ont_repondu = False
    if chemin(isbn13).exists():
        return True
    if toutes_ont_repondu:
        absente(isbn13).touch()
    return False


def oublier(isbn13: str) -> None:
    chemin(isbn13).unlink(missing_ok=True)
    absente(isbn13).unlink(missing_ok=True)
