"""Exports CSV et Excel : une ligne par exemplaire, toutes les cotes en colonnes."""

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db
from .classify import SYSTEMES, systeme_courant
from .i18n import tr
from .isbn import to10
from .services import NOMS_SUPPORTS, nom_emplacement
from .sources import split_name

COLONNES = [
    ("isbn13", "ISBN"), ("titre", "Titre"), ("sous_titre", "Sous-titre"), ("auteurs", "Auteurs"),
    ("editeur", "Éditeur"), ("collection", "Collection"), ("annee", "Année"), ("pages", "Pages"),
    ("langue", "Langue"), ("forme", "Forme"), ("public", "Public"), ("support", "Support"), ("ean", "EAN"), ("lieu", "Lieu"),
    ("etagere", "Étagère"), ("rangee", "Rangée"), ("proprietaire", "Propriétaire"), ("lecture", "Lecture"), ("lecture_fin", "Lu le"),
    ("etoiles", "Étoiles"), ("etat", "État du livre"), ("prix_achat", "Prix d'achat"), ("date_achat", "Date d'achat"),
    ("provenance", "Provenance"), ("dedicace", "Dédicace"), ("valeur", "Valeur"),
]


def lignes(conn, systeme: str | None = None, lieux: list[int] | None = None) -> tuple[list[str], list[list]]:
    systeme = systeme or systeme_courant(conn)
    moi = db.moi_id(conn)
    entetes = [tr(titre) for _, titre in COLONNES]
    for s, nom in SYSTEMES.items():
        entetes += [tr("Cote {systeme}", systeme=tr(nom)), tr("Classe {systeme}", systeme=tr(nom))]
    entetes += [tr("Statut"), tr("Prêté à"), tr("Ajouté le"), tr("Notes")]

    sql = ("SELECT n.*, e.id AS exemplaire_id, e.proprietaire_id, e.lieu_texte, e.etat, e.prix_achat, e.date_achat, "
           "e.provenance, e.dedicace, e.valeur, e.ajoute_le, p.nom AS proprietaire, "
           "e.notes AS ex_notes, n.notes AS n_notes, l.nom AS lieu, et.nom AS etagere, ra.nom AS rangee, "
           "c.tri AS tri FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
           "JOIN personnes p ON p.id = e.proprietaire_id "
           "LEFT JOIN lieux l ON l.id = e.lieu_id LEFT JOIN etageres et ON et.id = e.etagere_id "
           "LEFT JOIN rangees ra ON ra.id = e.rangee_id "
           "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? ")
    params = [systeme]
    if lieux:
        sql += f"WHERE e.lieu_id IN ({','.join('?' * len(lieux))}) "
        params += lieux
    sql += "ORDER BY l.ordre, et.ordre, ra.ordre, c.tri IS NULL, c.tri"
    rows = []
    for r in conn.execute(sql, params):
        cls = {c["systeme"]: c for c in conn.execute(
            "SELECT * FROM classifications WHERE notice_id = ?", (r["id"],))}
        pret = conn.execute(
            "SELECT emprunteur FROM prets_v WHERE exemplaire_id = ? AND date_retour IS NULL",
            (r["exemplaire_id"],)).fetchone()
        ligne = []
        for cle, _ in COLONNES:
            v = r[cle]
            if cle == "auteurs":
                v = " ; ".join(db.jload(v, []))
            if cle == "lieu" and v is None:
                v = r["lieu_texte"] if r["proprietaire_id"] != moi else tr("Non localisé")
            if cle == "isbn13":
                v = r["isbn13"] or (None if r["ean"] else db.reference(r))
            if cle == "support":
                v = tr(NOMS_SUPPORTS.get(v, v))
            ligne.append(v)
        for s in SYSTEMES:
            c = cls.get(s)
            ligne += [c["cote"] if c else None, c["libelle"] if c else None]
        notes = " ".join(filter(None, [r["n_notes"], r["ex_notes"]])) or None
        ligne += [r["statut"], pret["emprunteur"] if pret else None, r["ajoute_le"], notes]
        rows.append(ligne)
    return entetes, rows


def csv_bytes(conn, **kw) -> bytes:
    entetes, rows = lignes(conn, **kw)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(entetes)
    writer.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM : Excel lit bien les accents


def xlsx_bytes(conn, **kw) -> bytes:
    entetes, rows = lignes(conn, **kw)
    wb = Workbook()
    ws = wb.active
    ws.title = tr("Bibliothèque")
    ws.append(entetes)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="5B3A29")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    largeurs = {tr(k): v for k, v in {"Titre": 45, "Sous-titre": 30, "Auteurs": 30, "Éditeur": 22, "Collection": 25}.items()}
    for i, titre in enumerate(entetes, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largeurs.get(titre, 16)

    # Une feuille par lieu, dans l'ordre de rangement
    for lieu in conn.execute("SELECT * FROM lieux ORDER BY ordre, nom"):
        if kw.get("lieux") and lieu["id"] not in kw["lieux"]:
            continue
        _, rows_lieu = lignes(conn, systeme=kw.get("systeme"), lieux=[lieu["id"]])
        if not rows_lieu:
            continue
        feuille = wb.create_sheet(_nom_feuille(lieu["nom"]))
        feuille.append(entetes)
        for cell in feuille[1]:
            cell.font = Font(bold=True)
        for row in rows_lieu:
            feuille.append(row)
        feuille.freeze_panes = "C2"
        feuille.auto_filter.ref = feuille.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _nom_feuille(nom: str) -> str:
    for c in "[]:*?/\\":
        nom = nom.replace(c, " ")
    return nom[:31] or "Lieu"


# --- Applis de lecture ------------------------------------------------------------
# Ces fichiers partent chez un tiers : ni notes personnelles, ni prix, ni prêts. Seul le fichier Goodreads peut nommer les lieux.

COLONNES_GOODREADS = [
    "Book Id", "Title", "Author", "Author l-f", "Additional Authors", "ISBN", "ISBN13", "My Rating", "Average Rating",
    "Publisher", "Binding", "Number of Pages", "Year Published", "Original Publication Year", "Date Read", "Date Added",
    "Bookshelves", "Bookshelves with positions", "Exclusive Shelf", "My Review", "Spoiler", "Private Notes",
    "Read Count", "Owned Copies", "Status",
]
ETAGERES_GOODREADS = {"a_lire": "to-read", "en_cours": "currently-reading", "lu": "read", "abandonne": "did-not-finish"}

# Les en-têtes du modèle de Babelio (ModeleImportBabelio.csv), espace comprise.
COLONNES_BABELIO = ["EAN", " Statut (Lu/A lire/Wishlist/En cours)", "Possédé", "Ma note",
                    "Etagères séparées par virgules", "Critique", "Date de fin de lecture"]
# Le modèle n'a pas d'« abandonné » : le livre reste en cours, et une étagère garde l'information.
STATUTS_BABELIO = {"a_lire": "A lire", "en_cours": "En cours", "lu": "Lu", "abandonne": "En cours"}
LIMITE_BABELIO = 2500       # lignes par import, d'après le formulaire de Babelio


def _livres_pour_applis(conn, avec_statut: bool = False, lieux: list[int] | None = None) -> list[dict]:
    """Une ligne par livre : ceux que je possède, et ceux d'amis que j'ai lus ou que je compte lire.

    Avec `lieux`, seulement les livres qui y ont un exemplaire ; ils comptent quand même tous mes exemplaires.
    """
    lieux = lieux or []
    sql = ("SELECT n.*, count(e.id) AS mes_exemplaires, min(e.ajoute_le) AS ajoute_le FROM notices n "
           "LEFT JOIN exemplaires e ON e.notice_id = n.id AND e.proprietaire_id = ? WHERE n.support = 'livre' "
           + ("AND n.lecture IS NOT NULL " if avec_statut else "")
           + (f"AND EXISTS (SELECT 1 FROM exemplaires x WHERE x.notice_id = n.id AND x.lieu_id IN ({','.join('?' * len(lieux))})) "
              if lieux else "")
           + "GROUP BY n.id HAVING mes_exemplaires > 0 OR n.lecture IS NOT NULL "
           "ORDER BY n.auteur_tri IS NULL, n.auteur_tri, n.titre")
    return [db.notice_dict(r) for r in conn.execute(sql, (db.moi_id(conn), *lieux))]


def bilan_applis(conn, avec_statut: bool = False, lieux: list[int] | None = None) -> dict:
    """Combien de livres chaque fichier contiendra, et combien il laisse de côté."""
    livres = _livres_pour_applis(conn, avec_statut, lieux)
    goodreads = sum(1 for n in livres if n["titre"])
    babelio = sum(1 for n in livres if n["isbn13"] or n["ean"])
    return {"goodreads": goodreads, "sans_titre": len(livres) - goodreads, "babelio": babelio,
            "sans_code": len(livres) - babelio, "limite_babelio": LIMITE_BABELIO}


def _csv_appli(entetes: list[str], rows: list[list]) -> bytes:
    """Virgules, UTF-8 sans BOM : ces fichiers sont lus par des programmes, qui veulent des en-têtes exacts."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(entetes)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _date_goodreads(valeur: str | None) -> str | None:
    return valeur[:10].replace("-", "/") if valeur else None


def _emplacements_par_livre(conn) -> dict[int, list[str]]:
    """Où sont mes exemplaires, par livre, tels que l'app les écrit, moins les virgules : elles sépareraient la colonne."""
    emplacements: dict[int, list[str]] = {}
    for r in conn.execute("SELECT DISTINCT e.notice_id, e.lieu_id, e.etagere_id, e.rangee_id FROM exemplaires e "
                          "JOIN lieux l ON l.id = e.lieu_id LEFT JOIN etageres et ON et.id = e.etagere_id "
                          "LEFT JOIN rangees ra ON ra.id = e.rangee_id WHERE e.proprietaire_id = ? "
                          "ORDER BY l.nom, et.ordre, ra.ordre", (db.moi_id(conn),)):
        nom = nom_emplacement(conn, r["lieu_id"], r["etagere_id"], r["rangee_id"])
        emplacements.setdefault(r["notice_id"], []).append(" ".join(nom.replace(",", " ").split()))
    return emplacements


def goodreads_csv(conn, avec_statut: bool = False, lieux: list[int] | None = None, avec_lieux: bool = True) -> bytes:
    """Le format de l'export Goodreads, compris par la plupart des applis de lecture.

    Sans état de lecture, un livre part en « to-read » : le format exige une étagère, et c'est sa valeur par défaut.
    `Exclusive Shelf` porte l'état de lecture, et `Status` (absente chez Goodreads, demandée par Hardcover) le recopie.
    `Bookshelves` ne contient que les emplacements de mes exemplaires, et reste vide sans `avec_lieux`.
    """
    rows = []
    emplacements = _emplacements_par_livre(conn) if avec_lieux else {}
    for n in _livres_pour_applis(conn, avec_statut, lieux):
        if not n["titre"]:
            continue
        auteur = n["auteurs"][0] if n["auteurs"] else None
        etagere = ETAGERES_GOODREADS.get(n["lecture"], "to-read")
        isbn13 = n["isbn13"] or ""
        isbn10 = (to10(isbn13) or "") if isbn13 else ""
        rows.append([
            None, n["titre"], auteur, ", ".join(filter(None, split_name(auteur))) if auteur else None,
            ", ".join(n["auteurs"][1:]), f'="{isbn10}"', f'="{isbn13}"',    # ="…" : Excel n'abîme pas les ISBN
            n["etoiles"] or 0, None, n["editeur"], None, n["pages"], n["annee"], None,
            _date_goodreads(n["lecture_fin"]), _date_goodreads(n["ajoute_le"] or n["cree_le"]),
            ", ".join(emplacements.get(n["id"], [])), None, etagere, None, None, None,
            1 if n["lecture"] == "lu" else 0, n["mes_exemplaires"], etagere,
        ])
    return _csv_appli(COLONNES_GOODREADS, rows)


def babelio_csv(conn, avec_statut: bool = False, lieux: list[int] | None = None) -> bytes:
    """Le modèle d'import de Babelio, qui désigne un livre par son seul code-barres."""
    rows = []
    for n in _livres_pour_applis(conn, avec_statut, lieux):
        code = n["isbn13"] or n["ean"]
        if not code:
            continue
        fin = n["lecture_fin"]
        rows.append([
            code, STATUTS_BABELIO.get(n["lecture"], "A lire"), "Oui" if n["mes_exemplaires"] else "Non", n["etoiles"],
            "abandonné" if n["lecture"] == "abandonne" else None, None,
            f"{fin[8:10]}/{fin[5:7]}/{fin[:4]}" if fin else None,
        ])
    return _csv_appli(COLONNES_BABELIO, rows)


def rangement(conn, lieu_id: int, etagere_id: int | None = None, systeme: str | None = None) -> list[dict]:
    """Ordre de rangement d'un lieu (ou d'une étagère) : cote, titre, auteur."""
    systeme = systeme or systeme_courant(conn)
    sql = ("SELECT e.id, e.etagere_id, e.rangee_id, n.id AS notice_id, n.isbn13, n.ean, n.titre, n.auteurs, n.annee, c.cote, c.libelle "
           "FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
           "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? "
           "LEFT JOIN etageres et ON et.id = e.etagere_id LEFT JOIN rangees ra ON ra.id = e.rangee_id WHERE e.lieu_id = ? ")
    params = [systeme, lieu_id]
    if etagere_id:
        sql += "AND e.etagere_id = ? "
        params.append(etagere_id)
    sql += "ORDER BY et.ordre, ra.ordre, c.tri IS NULL, c.tri, n.titre"
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["auteurs"] = db.jload(d["auteurs"], [])
        d["reference"] = d["isbn13"] or d["ean"] or f"L{d['notice_id']}"
        d["emplacement"] = nom_emplacement(conn, lieu_id, r["etagere_id"], r["rangee_id"])
        out.append(d)
    return out
