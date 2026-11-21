#!/usr/bin/env python3
"""Archive des copies de la bibliothèque, de préférence sur un autre disque. Lancé chaque nuit par
biblio-backup.service (en root), juste après la copie du jour. Bibliothèque standard seulement.

1. Les nouvelles copies du jour sont recopiées dans l'archive (le dossier des données n'en garde que 3 :
   `biblio backup --keep 3`).
2. L'archive garde, de la plus récente à la plus ancienne :
   - toutes les copies des 7 derniers jours ;
   - puis la plus récente de chaque semaine, sur un mois ;
   - puis la plus récente de chaque mois, sur un an ;
   - puis la plus récente de chaque année, sans limite.
3. Les couvertures nouvelles sont ajoutées à l'archive.

Les durées se comptent depuis la copie la plus récente, pas depuis l'heure qu'il est : si les copies
s'arrêtent (serveur éteint, panne), rien ne vieillit et rien de plus n'est supprimé.
Disque de l'archive absent (pas monté) : rien n'est écrit, l'archive reprend à son retour.

  retention.py --copies /var/lib/biblio/sauvegardes --archive /mnt/disque/backups/biblio \
               [--couvertures /var/lib/biblio/covers] [--simulation]
"""

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

MOTIF = re.compile(r"(?P<base>.+)-(?P<date>\d{4}-\d{2}-\d{2}-\d{6})(?:-\d+)?\.db")
TOUTES = timedelta(days=7)          # toutes les copies
SEMAINES = timedelta(days=31)       # puis une par semaine
MOIS = timedelta(days=366)          # puis une par mois ; au-delà, une par an


def copies(dossier: Path) -> dict[str, datetime]:
    """Les copies d'un dossier : nom -> date (lue dans le nom, qui ne bouge pas, contrairement à mtime)."""
    trouvees = {}
    if dossier.is_dir():
        for p in dossier.iterdir():
            m = MOTIF.fullmatch(p.name)
            if m and p.is_file():
                trouvees[p.name] = datetime.strptime(m["date"], "%Y-%m-%d-%H%M%S")
    return trouvees


def base(nom: str) -> str:
    return MOTIF.fullmatch(nom)["base"]


def par_base(liste: dict[str, datetime]) -> dict[str, dict[str, datetime]]:
    groupes: dict[str, dict[str, datetime]] = {}
    for nom, date in liste.items():
        groupes.setdefault(base(nom), {})[nom] = date
    return groupes


def a_garder_archive(liste: dict[str, datetime]) -> set[str]:
    """Le tri de l'archive. Appliqué chaque nuit aux copies restantes : chaque semaine, mois ou année
    garde toujours au moins une copie, la plus récente qui reste."""
    garder = set()
    for groupe in par_base(liste).values():
        reference = max(groupe.values())
        vus = set()
        for nom in sorted(groupe, key=groupe.get, reverse=True):
            date = groupe[nom]
            age = reference - date
            if age < TOUTES:
                garder.add(nom)
                continue
            if age < SEMAINES:
                periode = ("semaine", *date.isocalendar()[:2])
            elif age < MOIS:
                periode = ("mois", date.year, date.month)
            else:
                periode = ("année", date.year)
            if periode not in vus:
                vus.add(periode)
                garder.add(nom)
    return garder


def disponible(dossier: Path) -> bool:
    """Le disque de l'archive est-il là ? Sous /mnt ou /media, un dossier sur le disque système veut dire
    « pas monté » : on n'y écrit rien (sinon les copies rempliraient le disque système en silence)."""
    p = dossier
    while not p.exists():
        p = p.parent
    if str(dossier).startswith(("/mnt/", "/media/")) and os.stat(p).st_dev == os.stat("/").st_dev:
        return False
    dossier.mkdir(parents=True, exist_ok=True)
    return True


def copier(source: Path, dest: Path) -> None:
    """Copie complète puis renommage : jamais de copie à moitié écrite. Date d'origine conservée."""
    temporaire = dest.with_name(dest.name + ".tmp")
    shutil.copy2(source, temporaire)
    os.chmod(temporaire, 0o600)
    os.replace(temporaire, dest)


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    a.add_argument("--copies", type=Path, required=True, help="les copies du jour (dossier des données)")
    a.add_argument("--archive", type=Path, required=True, help="l'archive (de préférence un autre disque)")
    a.add_argument("--couvertures", type=Path)
    a.add_argument("--simulation", action="store_true", help="affiche sans rien changer")
    args = a.parse_args(argv)
    agir = not args.simulation

    if not (disponible(args.archive) if agir else args.archive.is_dir()):
        print(f"ATTENTION : disque de l'archive absent ({args.archive}) : archive non mise à jour.", file=sys.stderr)
        return 0
    du_jour, archive = copies(args.copies), copies(args.archive)
    journal = []

    # 1. Les copies du jour pas encore dans l'archive
    nouvelles = sorted(set(du_jour) - set(archive))
    for nom in nouvelles:
        if agir:
            copier(args.copies / nom, args.archive / nom)
        archive[nom] = du_jour[nom]
    journal.append(f"{len(nouvelles)} nouvelle(s) copie(s)")

    # 2. Le tri
    garder = a_garder_archive(archive)
    enlever = sorted(set(archive) - garder)
    if agir:
        for nom in enlever:
            (args.archive / nom).unlink(missing_ok=True)
    journal.append(f"{len(garder)} gardée(s), {len(enlever)} supprimée(s)")

    # 3. Les couvertures (ajouts seulement)
    if args.couvertures and args.couvertures.is_dir():
        dest = args.archive / "covers"
        n = 0
        for p in args.couvertures.iterdir():
            cible = dest / p.name
            if p.is_file() and (not cible.exists() or cible.stat().st_size != p.stat().st_size):
                if agir:
                    dest.mkdir(exist_ok=True)
                    shutil.copy2(p, cible)
                n += 1
        journal.append(f"{n} nouvelle(s) couverture(s)")

    print(("[simulation] " if not agir else "") + "Archive : " + " · ".join(journal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
