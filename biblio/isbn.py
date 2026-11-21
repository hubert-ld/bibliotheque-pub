"""Nettoyage et validation des codes lus par la douchette.

Une douchette envoie ce qu'elle lit : un EAN-13 (978/979…), parfois suivi
du code prix à 2 ou 5 chiffres, parfois un vieil ISBN-10 saisi à la main,
parfois un code-barres qui n'a rien d'un livre (magazine, produit).
"""

import re

from .i18n import tr


class IsbnError(ValueError):
    """Code illisible ou qui n'est pas un ISBN."""


def check13(digits: str) -> bool:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def _check10(chars: str) -> bool:
    total = 0
    for i, c in enumerate(chars):
        value = 10 if c == "X" else int(c)
        total += value * (10 - i)
    return total % 11 == 0


def to13(isbn10: str) -> str:
    core = "978" + isbn10[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def to10(isbn13: str) -> str | None:
    """ISBN-10 équivalent (seulement pour le préfixe 978)."""
    if not isbn13.startswith("978"):
        return None
    core = isbn13[3:12]
    total = sum(int(d) * (10 - i) for i, d in enumerate(core))
    check = (11 - total % 11) % 11
    return core + ("X" if check == 10 else str(check))


# Douchette réglée en QWERTY sur un Mac/PC AZERTY : la rangée des chiffres
# arrive sans Maj, soit « &é"'(§è!çà » (Mac, iPhone) ou « &é"'(-è_çà » (PC, Android).
# Un téléphone peut aussi retoucher la frappe : majuscule en début de champ (Ç), guillemets
# et apostrophes typographiques. Même table dans scan.js.
AZERTY = str.maketrans({"&": "1", "é": "2", "É": "2", '"': "3", "“": "3", "”": "3", "«": "3", "»": "3",
                        "'": "4", "’": "4", "‘": "4", "(": "5", "§": "6", "-": "6", "è": "7", "È": "7",
                        "!": "8", "_": "8", "ç": "9", "Ç": "9", "à": "0", "À": "0"})


def sans_azerty(raw: str) -> str:
    """Le code lu, avec des chiffres s'il vient d'une douchette en QWERTY ; sinon tel quel."""
    raw = raw or ""
    if not re.search(r"\d", raw) and re.search(r"[&éÉ\"“”«»'’‘(§èÈ!_çÇàÀ]", raw):
        return raw.translate(AZERTY)
    return raw


def caracteres(raw: str) -> str:
    """Les chiffres (et X) d'un code lu, après la correction de la douchette en QWERTY."""
    return re.sub(r"[^0-9Xx]", "", sans_azerty(raw)).upper()


def normalize(raw: str) -> str:
    """Renvoie l'ISBN-13 correspondant au code scanné, ou lève IsbnError."""
    raw = raw or ""
    chars = caracteres(raw)
    if not chars:
        raise IsbnError(tr("code vide"))

    # EAN-13 suivi d'un add-on prix (EAN-2 / EAN-5) : on garde les 13 premiers.
    if len(chars) in (15, 18) and chars[:3] in ("978", "979"):
        chars = chars[:13]

    if len(chars) == 13:
        if "X" in chars:
            raise IsbnError(tr("{code} : caractère X invalide dans un EAN-13", code=repr(raw)))
        if chars.startswith("977"):
            raise IsbnError(tr("{code} : code ISSN (revue ou magazine), pas un livre", code=chars))
        if not chars.startswith(("978", "979")):
            raise IsbnError(tr("{code} : code-barres produit, pas un ISBN", code=chars))
        if not check13(chars):
            raise IsbnError(tr("{code} : clé de contrôle fausse (mauvaise lecture ?)", code=chars))
        return chars

    if len(chars) == 10:
        if "X" in chars[:9]:
            raise IsbnError(tr("{code} : X n'est permis qu'en dernière position", code=repr(raw)))
        if not _check10(chars):
            raise IsbnError(tr("{code} : clé de contrôle ISBN-10 fausse", code=chars))
        return to13(chars)

    raise IsbnError(tr("{code} : {n} caractères, un ISBN en compte 10 ou 13", code=repr(raw), n=len(chars)))


def hyphenless_variants(isbn13: str) -> list[str]:
    """Formes à interroger dans les catalogues (13 puis 10 chiffres)."""
    variants = [isbn13]
    isbn10 = to10(isbn13)
    if isbn10:
        variants.append(isbn10)
    return variants
