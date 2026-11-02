"""Langue de l'interface : français (par défaut) ou anglais.

Le texte français sert de clé ; `tr()` renvoie sa traduction anglaise quand la
langue courante est l'anglais. La langue est propre à chaque requête web
(réglage `langue` de la base) ; la CLI est toujours en anglais.

Les scripts de la page utilisent la même convention avec `tr("…")` (commun.js) :
leurs textes sont repérés dans les fichiers .js et envoyés traduits à la page.

Toute nouvelle phrase affichée doit avoir son entrée dans `traductions.EN` :
le test tests/test_i18n.py le vérifie.
"""

import re
from contextvars import ContextVar
from functools import cache
from pathlib import Path

from .traductions import EN

LANGUES = {"fr": "Français", "en": "English"}
DEFAUT = "fr"
SCRIPTS = Path(__file__).parent / "web" / "static"
_langue: ContextVar[str] = ContextVar("langue", default=DEFAUT)


def langue() -> str:
    return _langue.get()


def utiliser(code: str) -> None:
    _langue.set(code if code in LANGUES else DEFAUT)


def tr(texte: str, **valeurs) -> str:
    """Traduit `texte` (écrit en français) dans la langue courante, puis le complète."""
    if _langue.get() == "en":
        texte = EN.get(texte, texte)
    return texte.format(**valeurs) if valeurs else texte


@cache
def cles_js() -> tuple[str, ...]:
    """Textes passés à tr("…") dans les scripts de la page."""
    cles = set()
    for fichier in SCRIPTS.glob("*.js"):
        cles.update(re.findall(r'\btr\("([^"\\]*)"', fichier.read_text(encoding="utf-8")))
    return tuple(sorted(cles))


def textes_js() -> dict:
    """Dictionnaire des textes des scripts pour la langue courante (vide en français)."""
    if _langue.get() == "en":
        return {fr: EN.get(fr, fr) for fr in cles_js()}
    return {}
