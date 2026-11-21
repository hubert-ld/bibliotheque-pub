"""La liste des catalogues : ce qu'ils décrivent, la clé qu'ils demandent, comment les tester."""

import os
from dataclasses import dataclass

from . import (bnf, coverart, deezer, discogs, dnb, googlebooks, itunes, k10plus, loc, musicbrainz, omdb, openlibrary,
               sudoc, tmdb, upcitemdb)
from .. import db

# Codes connus de tous, pour vérifier qu'un catalogue répond : L'Étranger, Random Access Memories, Amélie
ISBN_TEST = "9782070360024"
EAN_TEST = "0888837168625"
RELEASE_TEST = "f6758afb-ecff-410e-8979-b131cfa3c6d3"
TITRE_TEST = "Amélie"


@dataclass(frozen=True)
class Catalogue:
    module: object
    nom: str
    famille: str                      # livres | musique | films
    test: str
    cle: str | None = None            # entrée de `meta`
    obligatoire: bool = False         # sans clé, le catalogue n'est pas interrogé
    aide: str = ""


CATALOGUES = [
    Catalogue(bnf, "BnF", "livres", ISBN_TEST),
    Catalogue(sudoc, "Sudoc", "livres", ISBN_TEST),
    Catalogue(openlibrary, "Open Library", "livres", ISBN_TEST),
    Catalogue(loc, "Library of Congress", "livres", ISBN_TEST),
    Catalogue(k10plus, "K10plus", "livres", ISBN_TEST),
    Catalogue(dnb, "DNB", "livres", ISBN_TEST),
    Catalogue(googlebooks, "Google Books", "livres", ISBN_TEST, "google_api_key", True,
              "Clé gratuite (1 000 requêtes/jour) sur la console Google Cloud, API « Books »."),
    Catalogue(musicbrainz, "MusicBrainz", "musique", EAN_TEST),
    Catalogue(coverart, "Cover Art Archive", "musique", RELEASE_TEST),
    Catalogue(discogs, "Discogs", "musique", EAN_TEST, "discogs_token", False,
              "Facultatif : jeton personnel gratuit (Discogs › Settings › Developers), pour les pochettes et un quota doublé."),
    Catalogue(deezer, "Deezer", "musique", EAN_TEST),
    Catalogue(itunes, "iTunes", "musique", EAN_TEST),
    Catalogue(upcitemdb, "UPCitemdb", "films", EAN_TEST),
    Catalogue(tmdb, "TMDb", "films", TITRE_TEST, "tmdb_api_key", True,
              "Clé gratuite sur themoviedb.org › Paramètres › API (la « clé API », v3)."),
    Catalogue(omdb, "OMDb", "films", TITRE_TEST, "omdb_api_key", True,
              "Clé gratuite sur omdbapi.com/apikey.aspx."),
]
PAR_NOM = {c.module.NAME: c for c in CATALOGUES}
ENV = {"google_api_key": "BIBLIO_GOOGLE_KEY"}


def cle_de(conn, cat: Catalogue) -> str | None:
    if not cat.cle:
        return None
    return os.environ.get(ENV.get(cat.cle, "")) or db.get_meta(conn, cat.cle)


def actif(conn, nom: str) -> bool:
    """Un catalogue désactivé dans l'administration n'est plus interrogé (par défaut, tous le sont)."""
    row = conn.execute("SELECT actif FROM sources_etat WHERE source = ?", (nom,)).fetchone()
    return not row or bool(row["actif"])


def disponible(conn, cat: Catalogue) -> bool:
    return actif(conn, cat.module.NAME) and (not cat.obligatoire or bool(cle_de(conn, cat)))


def arguments(conn, cat: Catalogue) -> tuple:
    """Ce que `fetch` attend après le code."""
    cle = cle_de(conn, cat)
    return (cle,) if cat.cle and (cle or not cat.obligatoire) else ()
