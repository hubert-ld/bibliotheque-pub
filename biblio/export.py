"""Exports CSV et Excel : une ligne par exemplaire, toutes les cotes en colonnes."""

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db
from .classify import SYSTEMES, systeme_courant
from .i18n import tr
from .services import nom_emplacement

COLONNES = [
    ("isbn13", "ISBN"), ("titre", "Titre"), ("sous_titre", "Sous-titre"), ("auteurs", "Auteurs"),
    ("editeur", "Éditeur"), ("collection", "Collection"), ("annee", "Année"), ("pages", "Pages"),
    ("langue", "Langue"), ("forme", "Forme"), ("public", "Public"), ("lieu", "Lieu"),
    ("etagere", "Étagère"), ("proprietaire", "Propriétaire"), ("lecture", "Lecture"), ("lecture_fin", "Lu le"),
    ("etoiles", "Étoiles"), ("etat", "État du livre"), ("prix_achat", "Prix d'achat"), ("date_achat", "Date d'achat"),
    ("provenance", "Provenance"), ("dedicace", "Dédicace"), ("valeur", "Valeur"),
]


def lignes(conn, systeme: str | None = None, lieu_id: int | None = None) -> tuple[list[str], list[list]]:
    systeme = systeme or systeme_courant(conn)
    moi = db.moi_id(conn)
    entetes = [tr(titre) for _, titre in COLONNES]
    for s, nom in SYSTEMES.items():
        entetes += [tr("Cote {systeme}", systeme=tr(nom)), tr("Classe {systeme}", systeme=tr(nom))]
    entetes += [tr("Statut"), tr("Prêté à"), tr("Ajouté le"), tr("Notes")]

    sql = ("SELECT n.*, e.id AS exemplaire_id, e.proprietaire_id, e.lieu_texte, e.etat, e.prix_achat, e.date_achat, "
           "e.provenance, e.dedicace, e.valeur, e.ajoute_le, p.nom AS proprietaire, "
           "e.notes AS ex_notes, n.notes AS n_notes, l.nom AS lieu, et.nom AS etagere, "
           "c.tri AS tri FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
           "JOIN personnes p ON p.id = e.proprietaire_id "
           "LEFT JOIN lieux l ON l.id = e.lieu_id LEFT JOIN etageres et ON et.id = e.etagere_id "
           "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? ")
    params = [systeme]
    if lieu_id:
        sql += "WHERE e.lieu_id = ? "
        params.append(lieu_id)
    sql += "ORDER BY l.ordre, et.ordre, c.tri IS NULL, c.tri"
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
                v = db.reference(r)
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
        _, rows_lieu = lignes(conn, systeme=kw.get("systeme"), lieu_id=lieu["id"])
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


def rangement(conn, lieu_id: int, etagere_id: int | None = None, systeme: str | None = None) -> list[dict]:
    """Ordre de rangement d'un lieu (ou d'une étagère) : cote, titre, auteur."""
    systeme = systeme or systeme_courant(conn)
    sql = ("SELECT e.id, e.etagere_id, n.id AS notice_id, n.isbn13, n.titre, n.auteurs, n.annee, c.cote, c.libelle "
           "FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
           "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? "
           "LEFT JOIN etageres et ON et.id = e.etagere_id WHERE e.lieu_id = ? ")
    params = [systeme, lieu_id]
    if etagere_id:
        sql += "AND e.etagere_id = ? "
        params.append(etagere_id)
    sql += "ORDER BY et.ordre, c.tri IS NULL, c.tri, n.titre"
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["auteurs"] = db.jload(d["auteurs"], [])
        d["reference"] = d["isbn13"] or f"L{d['notice_id']}"
        d["emplacement"] = nom_emplacement(conn, lieu_id, r["etagere_id"])
        out.append(d)
    return out
