"""Import de l'export « Exporter ma bibliothèque » de Babelio : les statuts de lecture et les notes.

Le fichier arrive en cp1252, séparé par des points-virgules, avec ces colonnes :
ISBN ; Titre ; Auteur ; Editeur ; Date de publication ; Date d`entrée dans Babelio ; Statut ; Note
La note s'écrit « 3.5 », et « 0.0 » veut dire : pas de note.
"""

import csv
import html
import io
import math
import re

from . import db, services
from .i18n import tr
from .isbn import IsbnError, normalize
from .services import Erreur

STATUTS = {"lu": "lu", "en cours": "en_cours", "a lire": "a_lire", "abandonne": "abandonne",
           "pense-bete": "a_lire", "wishlist": "a_lire"}


def lire_csv(contenu: bytes) -> list[dict]:
    """Les lignes du fichier, avec les clés isbn, titre, auteur, statut, note."""
    try:
        texte = contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = contenu.decode("cp1252", errors="replace")
    if not texte.strip():
        raise Erreur(tr("le fichier est vide"))
    premiere = texte.lstrip().splitlines()[0]
    separateur = ";" if premiere.count(";") >= premiere.count(",") else ","
    try:
        rangs = list(csv.reader(io.StringIO(texte.lstrip(), newline=""), delimiter=separateur))
    except csv.Error:
        raise Erreur(tr("ce fichier n'est pas un export de bibliothèque Babelio : il manque les colonnes ISBN, Statut ou Note"))
    colonnes = {db.norm(titre).strip(): i for i, titre in enumerate(rangs[0])}
    if not {"isbn", "statut", "note"} <= colonnes.keys():
        raise Erreur(tr("ce fichier n'est pas un export de bibliothèque Babelio : il manque les colonnes ISBN, Statut ou Note"))

    def champ(rang: list[str], cle: str) -> str:
        i = colonnes.get(cle)
        return html.unescape(rang[i]).strip() if i is not None and i < len(rang) else ""

    return [{cle: champ(rang, cle) for cle in ("isbn", "titre", "auteur", "statut", "note")}
            for rang in rangs[1:] if any(c.strip() for c in rang)]


def _etoiles(note: str) -> tuple[int | None, bool]:
    """Le nombre d'étoiles, de 1 à 5, et s'il a fallu arrondir une demi-étoile (vers le haut)."""
    try:
        valeur = float(note.replace(",", "."))
    except ValueError:
        return None, False
    if not 0 < valeur <= 5:             # 0 : pas de note
        return None, False
    etoiles = max(1, math.floor(valeur + 0.5))
    return etoiles, etoiles != valeur


def _par_code(conn, isbn: str) -> int | None:
    try:
        code = normalize(isbn)
    except IsbnError:
        code = isbn if re.fullmatch(r"\d{13}", isbn) else None      # un code-barres de livre qui n'est pas un ISBN
    return db.id_notice(conn, code) if code else None


def _index_titres(conn) -> dict[tuple[str, str], list[int]]:
    """Pour retrouver une autre édition. Babelio écrit « Nerval Gérard de », comme auteur_tri sans la casse."""
    index = {}
    for r in conn.execute("SELECT id, titre, auteur_tri FROM notices WHERE support = 'livre' AND titre IS NOT NULL"):
        index.setdefault((db.norm(r["titre"]).strip(), db.norm(r["auteur_tri"]).strip()), []).append(r["id"])
    return index


def importer(conn, contenu: bytes, ecraser: bool = False, simulation: bool = False) -> dict:
    """Remplit ce qui est vide dans la base ; `ecraser` donne raison à Babelio en cas de désaccord.

    Un livre absent de la base est seulement signalé : Babelio contient aussi des livres lus mais pas possédés.
    """
    lignes = lire_csv(contenu)
    index = _index_titres(conn)
    rapport = {"lignes": len(lignes), "statuts": 0, "notes": 0, "arrondies": 0, "par_titre": 0, "a_jour": 0,
               "absents": [], "desaccords": [], "statuts_inconnus": []}
    vues = set()
    for ligne in lignes:
        notice_id = _par_code(conn, ligne["isbn"])
        if notice_id is None:
            memes = index.get((db.norm(ligne["titre"]), db.norm(ligne["auteur"])), [])
            if len(memes) != 1 or not ligne["titre"]:
                rapport["absents"].append({k: ligne[k] for k in ("isbn", "titre", "auteur")})
                continue
            notice_id = memes[0]
            rapport["par_titre"] += 1
        if notice_id in vues:           # deux éditions sur Babelio pour un seul livre ici : la première compte
            continue
        vues.add(notice_id)

        statut = STATUTS.get(db.norm(ligne["statut"]))
        if ligne["statut"] and not statut and ligne["statut"] not in rapport["statuts_inconnus"]:
            rapport["statuts_inconnus"].append(ligne["statut"])
        etoiles, arrondie = _etoiles(ligne["note"])
        n = conn.execute("SELECT id, isbn13, ean, titre, lecture, etoiles FROM notices WHERE id = ?",
                         (notice_id,)).fetchone()
        champs = {}
        desaccords_avant = len(rapport["desaccords"])
        for cle, valeur in (("lecture", statut), ("etoiles", etoiles)):
            if valeur is None or n[cle] == valeur:
                continue
            if n[cle] is not None and not ecraser:
                rapport["desaccords"].append({"reference": db.reference(n), "titre": n["titre"], "champ": cle,
                                              "ici": n[cle], "babelio": valeur})
                continue
            champs[cle] = valeur
        rapport["statuts"] += "lecture" in champs
        rapport["notes"] += "etoiles" in champs
        rapport["arrondies"] += arrondie and "etoiles" in champs
        if champs and not simulation:
            services.modifier_notice(conn, notice_id, champs)
        elif not champs and len(rapport["desaccords"]) == desaccords_avant:
            rapport["a_jour"] += 1
    return rapport
