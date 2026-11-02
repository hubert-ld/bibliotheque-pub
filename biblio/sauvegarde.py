"""Copies de sécurité de la base : un seul fichier cohérent, même serveur en marche.

Une base en cours d'utilisation vit dans trois fichiers (.db, -wal, -shm), que OneDrive
copie chacun à son rythme. Ces copies-ci sont faites par SQLite et tiennent en un fichier :
ce sont elles qu'il faut restaurer en cas de problème.
"""

import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import db

GARDER = 14                  # copies conservées par base
INTERVALLE = 86400           # une copie automatique par jour au plus


def dossier_defaut(conn) -> Path:
    return db.chemin_base(conn).parent / "sauvegardes"


def _copies(dossier: Path, nom_base: str) -> list[Path]:
    """Les copies de cette base, de la plus ancienne à la plus récente."""
    if not dossier.is_dir():
        return []
    motif = re.compile(rf"{re.escape(nom_base)}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}(-\d+)?\.db")
    trouvees = [p for p in dossier.iterdir() if motif.fullmatch(p.name)]
    return sorted(trouvees, key=lambda p: (p.stat().st_mtime_ns, p.name))


def creer(conn, dossier: Path | str | None = None, garder: int = GARDER) -> Path:
    """Copie la base, puis supprime les copies les plus anciennes au-delà de `garder`."""
    nom_base = db.chemin_base(conn).stem
    dossier = Path(dossier) if dossier else dossier_defaut(conn)
    dossier.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    copie = dossier / f"{nom_base}-{date}.db"
    n = 0
    while copie.exists():
        n += 1
        copie = dossier / f"{nom_base}-{date}-{n}.db"
    temporaire = copie.with_suffix(".tmp")
    dest = sqlite3.connect(temporaire)
    try:
        conn.backup(dest)
        dest.execute("PRAGMA journal_mode = DELETE")     # un seul fichier, facile à synchroniser
    finally:
        dest.close()
    temporaire.replace(copie)                            # jamais de copie à moitié écrite
    for ancienne in _copies(dossier, nom_base)[:-max(garder, 1)]:
        ancienne.unlink()
    return copie


def automatique(conn) -> Path | None:
    """Copie au lancement du serveur, si la dernière date de plus d'un jour. Renvoie la copie créée."""
    if not conn.execute("SELECT 1 FROM exemplaires LIMIT 1").fetchone():
        return None
    copies = _copies(dossier_defaut(conn), db.chemin_base(conn).stem)
    if copies and time.time() - copies[-1].stat().st_mtime < INTERVALLE:
        return None
    return creer(conn)
