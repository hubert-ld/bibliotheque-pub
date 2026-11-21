"""Étiquettes d'emplacement : un code-barres par lieu, étagère ou rangée.

C'est un EAN-13 à usage interne : préfixe 29, un chiffre pour le genre, le numéro à 9 chiffres de
l'emplacement, la clé. Rien que des chiffres : une douchette en QWERTY sur un Mac AZERTY les envoie
comme les autres codes (voir isbn.AZERTY), et la caméra les lit sans réglage particulier.
"""

from .codes import PREFIXE_ETIQUETTE
from .i18n import tr
from .isbn import IsbnError

GENRES = {"lieux": "1", "etageres": "2", "rangees": "3"}
TABLES = {v: k for k, v in GENRES.items()}

# Motifs EAN-13, pour un chiffre : L, G et R (7 modules chacun)
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
# Le premier chiffre n'est pas imprimé en barres : il choisit L ou G pour les six suivants
_PARITE = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def _cle(chiffres: str) -> str:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(chiffres))
    return str((10 - total % 10) % 10)


def code_de(table: str, numero: str) -> str:
    """Le code à 13 chiffres de l'étiquette d'une ligne de lieux, etageres ou rangees."""
    debut = PREFIXE_ETIQUETTE + GENRES[table] + numero
    return debut + _cle(debut)


def decoder(code: str) -> tuple[str, str]:
    """(table, numéro) d'un code d'étiquette."""
    table = TABLES.get(code[2:3]) if len(code) == 13 and code.startswith(PREFIXE_ETIQUETTE) else None
    if not table:
        raise IsbnError(tr("{code} : code interne (d'un magasin, par exemple), ni un ISBN ni une étiquette d'emplacement", code=code))
    return table, code[3:12]


def _modules(code: str) -> str:
    gauche = "".join((_L if p == "L" else _G)[int(c)] for c, p in zip(code[1:7], _PARITE[int(code[0])]))
    droite = "".join(_R[int(c)] for c in code[7:13])
    return "101" + gauche + "01010" + droite + "101"


def svg(code: str, module: float = 3.0, hauteur: float = 80.0) -> str:
    """Le code-barres en SVG, à imprimer : marges blanches comprises, sans lesquelles il ne se lit pas."""
    marge = 11 * module
    barres = []
    x = marge
    modules = _modules(code)
    i = 0
    while i < len(modules):
        j = i
        while j < len(modules) and modules[j] == modules[i]:
            j += 1
        if modules[i] == "1":
            barres.append(f'<rect x="{x:g}" y="0" width="{(j - i) * module:g}" height="{hauteur:g}"/>')
        x += (j - i) * module
        i = j
    largeur = 2 * marge + len(modules) * module
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur:g} {hauteur + 18:g}" role="img" '
            f'aria-label="{code}"><rect width="100%" height="100%" fill="#fff"/><g fill="#000">{"".join(barres)}</g>'
            f'<text x="{largeur / 2:g}" y="{hauteur + 14:g}" text-anchor="middle" font-family="monospace" '
            f'font-size="14" fill="#000">{code}</text></svg>')
