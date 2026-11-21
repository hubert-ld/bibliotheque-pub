"""Ce que désigne un code tapé ou scanné : ISBN, EAN d'un disque ou d'un film, étiquette, référence.

`isbn.normalize` reste le seul juge des ISBN ; ce module reprend les codes qu'il refuse et qui sont
pourtant de vrais codes-barres (EAN-13, UPC-A à 12 chiffres des disques américains).
"""

import re

from .i18n import tr
from .isbn import IsbnError, caracteres, check13, normalize

PREFIXE_ETIQUETTE = "29"         # préfixes 20 à 29 : réservés à l'usage interne, jamais sur un produit


def analyser(raw: str) -> tuple[str, str]:
    """(genre, code) : genre vaut « isbn », « ean », « etiquette » ou « reference » (L12). Lève IsbnError."""
    m = re.fullmatch(r"[Ll](\d+)", (raw or "").strip())
    if m:
        return "reference", f"L{int(m.group(1))}"
    try:
        return "isbn", normalize(raw)
    except IsbnError as erreur:
        chars = caracteres(raw)
        if len(chars) == 12:
            chars = "0" + chars                # UPC-A : un EAN-13 qui commence par 0
        elif len(chars) in (15, 18):
            chars = chars[:13]                 # code prix collé à la suite
        if len(chars) != 13 or not chars.isdigit() or chars.startswith(("977", "978", "979")):
            raise erreur
        if not check13(chars):
            raise IsbnError(tr("{code} : clé de contrôle fausse (mauvaise lecture ?)", code=chars))
        return ("etiquette" if chars.startswith(PREFIXE_ETIQUETTE) else "ean"), chars
