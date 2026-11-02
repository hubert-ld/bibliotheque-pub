"""Logique métier partagée par la CLI et l'appli web.

Vocabulaire :
  notice        description d'un livre (numéro propre ; ISBN s'il en a un)
  référence     ce qui désigne une notice pour l'utilisateur : son ISBN, ou L + son numéro (L12)
  exemplaire    objet physique, rangé dans un lieu (Salon) et une étagère (Étagère 3)
  personne      propriétaire, prêteur ou emprunteur ; moi = la personne qui possède cette base

Les fonctions acceptent le numéro d'une notice, ou sa référence.
"""

import re
import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from . import db
from .classify import SYSTEMES, classer_notice, libelle, norm, systeme_courant
from .i18n import tr
from .isbn import IsbnError, normalize

REBOND_SECONDES = 4          # deux lectures du même code en moins de 4 s = un seul livre
# Personnels : datés comme les corrections, mais jamais partagés ni protégés des catalogues
CHAMPS_PERSONNELS = {"notes", "lecture", "lecture_debut", "lecture_fin", "etoiles"}
CHAMPS_MODIFIABLES = {"titre", "sous_titre", "auteurs", "editeur", "collection", "annee",
                      "pages", "langue", "langue_originale", "resume", "sujets", "forme",
                      "public", "couverture_url"} | CHAMPS_PERSONNELS
CHAMPS_EXEMPLAIRE = {"etat", "prix_achat", "date_achat", "provenance", "dedicace", "valeur", "notes"}
FORMES = ["fiction", "nouvelles", "poesie", "theatre", "essai", "documentaire", "humour",
          "lettres", "mixte"]
PUBLICS = ["adulte", "ado", "jeunesse"]
LECTURES = ["a_lire", "en_cours", "lu", "abandonne"]
NOMS_LECTURES = {"a_lire": "À lire", "en_cours": "En cours", "lu": "Lu", "abandonne": "Abandonné"}
ETATS = ["neuf", "tres_bon", "bon", "moyen", "abime"]
NOMS_ETATS = {"neuf": "Neuf", "tres_bon": "Très bon", "bon": "Bon", "moyen": "Moyen", "abime": "Abîmé"}


class Erreur(Exception):
    """Erreur à afficher telle quelle à l'utilisateur."""


# --- Personnes --------------------------------------------------------------------

def personne_id(conn, nom: str, creer: bool = True) -> int | None:
    """La personne de ce nom (« marie » = « Marie ») ; créée si besoin, le nom écrit devient le sien."""
    nom = (nom or "").strip()
    cle = norm(nom).strip()
    if not cle:
        return None
    if cle == norm(proprietaire_local(conn)).strip():
        return db.moi_id(conn)
    row = conn.execute("SELECT id FROM personnes WHERE cle = ?", (cle,)).fetchone()
    if row:
        return row["id"]
    if not creer:
        return None
    return conn.execute("INSERT INTO personnes(uid, nom, cle, maj_le) VALUES (?, ?, ?, ?)",
                        (db.nouvel_uid(), nom, cle, db.horodatage())).lastrowid


def proprietaire_local(conn) -> str:
    """Nom sous lequel mes propres livres sont enregistrés."""
    return conn.execute("SELECT nom FROM personnes WHERE id = ?", (db.moi_id(conn),)).fetchone()["nom"]


def proprietaires(conn) -> list[dict]:
    """Propriétaires présents, moi d'abord, avec leur nombre d'exemplaires."""
    moi = db.moi_id(conn)
    out = [dict(nom=r["nom"], nb=r["nb"], local=r["id"] == moi) for r in conn.execute(
        "SELECT p.id, p.nom, count(*) AS nb FROM exemplaires e JOIN personnes p ON p.id = e.proprietaire_id "
        "GROUP BY p.id ORDER BY p.nom COLLATE NOCASE")]
    if not any(p["local"] for p in out):
        out.append(dict(nom=proprietaire_local(conn), nb=0, local=True))
    return sorted(out, key=lambda p: not p["local"])


def noms_personnes(conn) -> list[str]:
    """Toutes les personnes connues, pour proposer leur nom à la saisie."""
    return [r["nom"] for r in conn.execute("SELECT nom FROM personnes ORDER BY nom COLLATE NOCASE")]


def renommer_proprietaire_local(conn, nouveau: str) -> int:
    """Change mon nom. Mes exemplaires me désignent par mon identité : ils suivent d'eux-mêmes."""
    nouveau = (nouveau or "").strip()
    cle = norm(nouveau).strip()
    if not cle:
        raise Erreur(tr("indiquez un nom de propriétaire"))
    moi = db.moi_id(conn)
    autre = conn.execute("SELECT id FROM personnes WHERE cle = ? AND id != ?", (cle, moi)).fetchone()
    if autre:
        if conn.execute("SELECT 1 FROM exemplaires WHERE proprietaire_id = ?", (autre["id"],)).fetchone():
            raise Erreur(tr("« {nom} » possède déjà des livres dans cette base : choisissez un autre nom", nom=nouveau))
        # Un simple emprunteur de ce nom : c'était moi
        conn.execute("UPDATE prets SET emprunteur_id = ? WHERE emprunteur_id = ?", (moi, autre["id"]))
        conn.execute("UPDATE prets SET preteur_id = ? WHERE preteur_id = ?", (moi, autre["id"]))
        conn.execute("DELETE FROM personnes WHERE id = ?", (autre["id"],))
    conn.execute("UPDATE personnes SET nom = ?, cle = ?, maj_le = ? WHERE id = ?", (nouveau, cle, db.horodatage(), moi))
    n = conn.execute("SELECT count(*) FROM exemplaires WHERE proprietaire_id = ?", (moi,)).fetchone()[0]
    conn.commit()
    return n


def _proprio(conn, valeur: str | None) -> int | None:
    """Filtre propriétaire : vide = moi, « tous » = tout le monde (None), sinon cette personne."""
    if not valeur:
        return db.moi_id(conn)
    if valeur == "tous":
        return None
    return personne_id(conn, valeur, creer=False) or -1      # inconnu : aucun livre


# --- Lieux et étagères ------------------------------------------------------------

def lieux(conn) -> list[dict]:
    out = []
    for lieu in conn.execute("SELECT * FROM lieux ORDER BY ordre, nom"):
        d = dict(lieu)
        d["nb"] = conn.execute("SELECT count(*) FROM exemplaires WHERE lieu_id = ?",
                               (lieu["id"],)).fetchone()[0]
        d["etageres"] = [
            dict(e, nb=conn.execute("SELECT count(*) FROM exemplaires WHERE etagere_id = ?",
                                    (e["id"],)).fetchone()[0])
            for e in conn.execute("SELECT * FROM etageres WHERE lieu_id = ? ORDER BY ordre, nom",
                                  (lieu["id"],))
        ]
        out.append(d)
    return out


def tracer_suppression(conn, uid: str, genre: str) -> None:
    """Retient une suppression : la synchronisation ne doit pas faire revenir ce qui a été retiré."""
    conn.execute("INSERT OR REPLACE INTO suppressions(uid, genre, le) VALUES (?, ?, ?)", (uid, genre, db.horodatage()))


def creer_lieu(conn, nom: str, description: str | None = None) -> int:
    nom = nom.strip()
    if not nom:
        raise Erreur(tr("nom de lieu vide"))
    try:
        ordre = conn.execute("SELECT coalesce(max(ordre), 0) + 1 FROM lieux").fetchone()[0]
        cur = conn.execute("INSERT INTO lieux(uid, nom, description, ordre, maj_le) VALUES (?, ?, ?, ?, ?)",
                           (db.nouvel_uid(), nom, description, ordre, db.horodatage()))
    except sqlite3.IntegrityError:
        raise Erreur(tr("le lieu « {nom} » existe déjà", nom=nom))
    conn.commit()
    return cur.lastrowid


def renommer_lieu(conn, lieu_id: int, nom: str, description: str | None = None) -> None:
    nom = nom.strip()
    if not nom:
        raise Erreur(tr("nom de lieu vide"))
    try:
        conn.execute("UPDATE lieux SET nom = ?, description = ?, maj_le = ? WHERE id = ?",
                     (nom, description, db.horodatage(), lieu_id))
    except sqlite3.IntegrityError:
        raise Erreur(tr("le lieu « {nom} » existe déjà", nom=nom))
    conn.commit()


def supprimer_lieu(conn, lieu_id: int) -> int:
    """Supprime le lieu ; ses exemplaires deviennent « non localisés »."""
    n = conn.execute("SELECT count(*) FROM exemplaires WHERE lieu_id = ?", (lieu_id,)).fetchone()[0]
    for row in conn.execute("SELECT uid FROM etageres WHERE lieu_id = ?", (lieu_id,)).fetchall():
        tracer_suppression(conn, row["uid"], "etagere")
    lieu = conn.execute("SELECT uid FROM lieux WHERE id = ?", (lieu_id,)).fetchone()
    if lieu:
        tracer_suppression(conn, lieu["uid"], "lieu")
    conn.execute("UPDATE exemplaires SET lieu_id = NULL, etagere_id = NULL, maj_le = ? WHERE lieu_id = ?",
                 (db.horodatage(), lieu_id))
    conn.execute("DELETE FROM lieux WHERE id = ?", (lieu_id,))
    conn.commit()
    return n


def creer_etagere(conn, lieu_id: int, nom: str) -> int:
    nom = nom.strip()
    if not nom:
        raise Erreur(tr("nom d'étagère vide"))
    try:
        ordre = conn.execute("SELECT coalesce(max(ordre), 0) + 1 FROM etageres WHERE lieu_id = ?",
                             (lieu_id,)).fetchone()[0]
        cur = conn.execute("INSERT INTO etageres(uid, lieu_id, nom, ordre, maj_le) VALUES (?, ?, ?, ?, ?)",
                           (db.nouvel_uid(), lieu_id, nom, ordre, db.horodatage()))
    except sqlite3.IntegrityError:
        raise Erreur(tr("l'étagère « {nom} » existe déjà dans ce lieu", nom=nom))
    conn.commit()
    return cur.lastrowid


def renommer_etagere(conn, etagere_id: int, nom: str) -> None:
    nom = nom.strip()
    if not nom:
        raise Erreur(tr("nom d'étagère vide"))
    try:
        conn.execute("UPDATE etageres SET nom = ?, maj_le = ? WHERE id = ?", (nom, db.horodatage(), etagere_id))
    except sqlite3.IntegrityError:
        raise Erreur(tr("l'étagère « {nom} » existe déjà dans ce lieu", nom=nom))
    conn.commit()


def supprimer_etagere(conn, etagere_id: int) -> None:
    etagere = conn.execute("SELECT uid FROM etageres WHERE id = ?", (etagere_id,)).fetchone()
    if etagere:
        tracer_suppression(conn, etagere["uid"], "etagere")
    conn.execute("UPDATE exemplaires SET etagere_id = NULL, maj_le = ? WHERE etagere_id = ?",
                 (db.horodatage(), etagere_id))
    conn.execute("DELETE FROM etageres WHERE id = ?", (etagere_id,))
    conn.commit()


def emplacement(conn, spec: str, creer: bool = False) -> tuple[int | None, int | None]:
    """'Salon' ou 'Salon/Étagère 3' (séparateurs / > ›) -> (lieu_id, etagere_id)."""
    if not spec:
        return None, None
    entier = _par_nom(conn.execute("SELECT id, nom FROM lieux"), spec)
    if entier is not None:                         # un lieu nommé « Bureau/Chambre »
        return entier, None
    parts = [p.strip() for p in re.split(r"\s*[/>›]\s*", spec, maxsplit=1)]
    lieu_id = _par_nom(conn.execute("SELECT id, nom FROM lieux"), parts[0])
    if lieu_id is None:
        if not creer:
            raise Erreur(tr("lieu inconnu : « {nom} »", nom=parts[0]))
        lieu_id = creer_lieu(conn, parts[0])
    if len(parts) == 1 or not parts[1]:
        return lieu_id, None
    etagere_id = _par_nom(conn.execute("SELECT id, nom FROM etageres WHERE lieu_id = ?", (lieu_id,)), parts[1])
    if etagere_id is not None:
        return lieu_id, etagere_id
    if creer:
        return lieu_id, creer_etagere(conn, lieu_id, parts[1])
    raise Erreur(tr("étagère inconnue : « {etagere} » dans « {lieu} »", etagere=parts[1], lieu=parts[0]))


def _par_nom(rows, nom: str) -> int | None:
    """Recherche par nom sans tenir compte des majuscules ni des accents (Étagère = etagere)."""
    cible = norm(nom).strip()
    for row in rows:
        if norm(row["nom"]).strip() == cible:
            return row["id"]
    return None


def nom_emplacement(conn, lieu_id: int | None, etagere_id: int | None) -> str:
    if not lieu_id:
        return tr("Non localisé")
    lieu = conn.execute("SELECT nom FROM lieux WHERE id = ?", (lieu_id,)).fetchone()
    nom = lieu["nom"] if lieu else "?"
    if etagere_id:
        et = conn.execute("SELECT nom FROM etageres WHERE id = ?", (etagere_id,)).fetchone()
        if et:
            nom += f" › {et['nom']}"
    return nom


def emplacement_exemplaire(conn, ex) -> str:
    """Emplacement lisible d'une ligne de exemplaires_v : « Salon › É2 », ou « chez Victor — Salon › É2 »."""
    if ex["proprietaire_id"] != db.moi_id(conn):
        chez = tr("chez {qui}", qui=ex["proprietaire"])
        return f"{chez} — {ex['lieu_texte']}" if ex["lieu_texte"] else chez
    return nom_emplacement(conn, ex["lieu_id"], ex["etagere_id"])


def _verifier_emplacement(conn, lieu_id, etagere_id):
    if etagere_id and not lieu_id:
        row = conn.execute("SELECT lieu_id FROM etageres WHERE id = ?", (etagere_id,)).fetchone()
        lieu_id = row["lieu_id"] if row else None
    if etagere_id:
        row = conn.execute("SELECT lieu_id FROM etageres WHERE id = ?", (etagere_id,)).fetchone()
        if not row or row["lieu_id"] != lieu_id:
            raise Erreur(tr("cette étagère n'appartient pas à ce lieu"))
    return lieu_id, etagere_id


# --- Notices ----------------------------------------------------------------------

def _code(raw: str) -> str:
    """Code tapé ou scanné -> ISBN-13, ou référence d'un livre sans ISBN (L12)."""
    m = re.fullmatch(r"[Ll](\d+)", raw.strip())
    if m:
        return f"L{int(m.group(1))}"
    try:
        return normalize(raw)
    except IsbnError as exc:
        raise Erreur(str(exc))


def _id(conn, ref: int | str) -> int:
    notice_id = db.id_notice(conn, ref)
    if notice_id is None or not conn.execute("SELECT 1 FROM notices WHERE id = ?", (notice_id,)).fetchone():
        raise Erreur(tr("notice inconnue : {isbn}", isbn=ref))
    return notice_id


def _nouvelle_notice(conn, isbn13: str | None, statut: str) -> int:
    now = db.now()
    return conn.execute("INSERT INTO notices(uid, isbn13, statut, cree_le, maj_le) VALUES (?, ?, ?, ?, ?)",
                        (db.nouvel_uid(), isbn13, statut, now, now)).lastrowid


def creer_notice_attente(conn, isbn13: str) -> tuple[int, bool]:
    """La notice de cet ISBN, créée en attente de description si besoin ; (numéro, nouvelle ?)."""
    existante = db.id_notice(conn, isbn13)
    if existante:
        return existante, False
    return _nouvelle_notice(conn, isbn13, "en_attente"), True


def resume_notice(conn, ref: int | str, systeme: str | None = None) -> dict | None:
    systeme = systeme or systeme_courant(conn)
    row = conn.execute(
        "SELECT n.id, n.isbn13, n.titre, n.auteurs, n.statut, n.couverture_url, n.annee, n.editeur, "
        "c.cote, c.libelle, c.code FROM notices n "
        "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? "
        "WHERE n.id = ?", (systeme, db.id_notice(conn, ref))).fetchone()
    if not row:
        return None
    d = dict(row)
    d["auteurs"] = db.jload(d["auteurs"], [])
    d["reference"] = db.reference(d)
    return d


def notice(conn, ref: int | str) -> dict | None:
    notice_id = db.id_notice(conn, ref)
    n = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    if not n:
        return None
    rows = {r["systeme"]: dict(r) for r in conn.execute(
        "SELECT * FROM classifications WHERE notice_id = ?", (notice_id,))}
    n["classifications"] = [dict(rows.get(s) or {"systeme": s}, nom=nom) for s, nom in SYSTEMES.items()]
    n["exemplaires"] = exemplaires_de(conn, notice_id)
    n["raw"] = [dict(r) for r in conn.execute(
        "SELECT source, statut, recu_le, length(payload) AS taille FROM raw_responses WHERE notice_id = ?",
        (notice_id,))]
    return n


def exemplaires_de(conn, ref: int | str, miens: bool = False) -> list[dict]:
    """Exemplaires d'une notice (les miens d'abord) ; `miens` exclut ceux des amis."""
    moi = db.moi_id(conn)
    out = []
    for e in conn.execute("SELECT * FROM exemplaires_v WHERE notice_id = ? ORDER BY proprietaire_id != ?, id",
                          (db.id_notice(conn, ref), moi)):
        if miens and e["proprietaire_id"] != moi:
            continue
        d = dict(e)
        d["a_moi"] = e["proprietaire_id"] == moi
        d["emplacement"] = emplacement_exemplaire(conn, e)
        pret = conn.execute("SELECT * FROM prets_v WHERE exemplaire_id = ? AND date_retour IS NULL",
                            (e["id"],)).fetchone()
        d["pret"] = dict(pret) if pret else None
        out.append(d)
    return out


def _entier(valeur, champ: str) -> int:
    try:
        return int(valeur)
    except (TypeError, ValueError):
        raise Erreur(tr("{champ} doit être un nombre", champ=champ))


def modifier_notice(conn, ref: int | str, champs: dict) -> None:
    """Corrige des champs ; les champs du catalogue sont alors protégés des mises à jour automatiques."""
    notice_id = _id(conn, ref)
    n = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    corrections = n["corrections"]
    quand = db.horodatage()
    values = {}
    for cle, val in champs.items():
        if cle not in CHAMPS_MODIFIABLES:
            raise Erreur(tr("champ non modifiable : {champ}", champ=cle))
        if isinstance(val, str):
            val = val.strip() or None
        if cle in ("auteurs", "sujets"):
            if isinstance(val, str):
                val = [a.strip() for a in re.split(r"\s*;\s*", val) if a.strip()]
            val = val or []
            if cle == "auteurs":
                values["auteur_tri"] = _tri_auteur(val[0]) if val else None
            val = db.jdump(val)
        if cle in ("annee", "pages", "etoiles") and val is not None:
            val = _entier(val, cle)
        if cle == "etoiles" and val is not None and not 1 <= val <= 5:
            raise Erreur(tr("la note va de 1 à 5 étoiles"))
        if cle == "lecture" and val is not None and val not in LECTURES:
            raise Erreur(tr("état de lecture inconnu : {valeur}", valeur=val))
        if cle in ("lecture_debut", "lecture_fin"):
            _date(val)
        values[cle] = val
        corrections[cle] = {"le": quand, "manuel": cle not in CHAMPS_PERSONNELS}
    if not values:
        return
    values["corrections"] = db.jdump(corrections)
    values["maj_le"] = db.now()
    if n["statut"] in ("introuvable", "erreur") and values.get("titre"):
        values["statut"] = "manuel"
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE notices SET {sets} WHERE id = ?", [*values.values(), notice_id])
    classer_notice(conn, notice_id)
    db.reindex_notice(conn, notice_id)
    conn.commit()
    if "couverture_url" in values:
        from . import covers
        covers.oublier(db.cle_couverture(n))


def liberer_champ(conn, ref: int | str, champ: str) -> None:
    """Rend un champ aux catalogues (annule la protection manuelle)."""
    from .resolver import rebuild

    if champ not in CHAMPS_MODIFIABLES - CHAMPS_PERSONNELS:
        raise Erreur(tr("champ non modifiable : {champ}", champ=champ))
    notice_id = _id(conn, ref)
    n = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    n["corrections"][champ] = {"le": db.horodatage(), "manuel": False}
    conn.execute("UPDATE notices SET corrections = ? WHERE id = ?", (db.jdump(n["corrections"]), notice_id))
    conn.commit()
    rebuild(conn, notice_id)


def _tri_auteur(nom_complet: str) -> str:
    from .sources import split_name, tri_name
    return tri_name(*split_name(nom_complet))


def creer_notice_manuelle(conn, titre: str, auteurs: str = "", isbn: str | None = None,
                          lieu_id=None, etagere_id=None, proprietaire: str | None = None, **champs) -> dict:
    """Livre décrit à la main.

    Sans ISBN (livres anciens, autoédités) : statut « manuel », désigné par sa référence (L12).
    Avec un ISBN : les champs saisis sont protégés et les catalogues complètent le reste
    (`recherche` vaut alors True : il faut réveiller la recherche en arrière-plan).
    """
    if not (titre or "").strip():
        raise Erreur(tr("le titre est obligatoire"))
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    if isbn and isbn.strip():
        code = _code(isbn)
        if code.startswith("L"):
            raise Erreur(tr("{code} : {n} caractères, un ISBN en compte 10 ou 13", code=repr(isbn), n=len(isbn)))
        notice_id, recherche = creer_notice_attente(conn, code)
    else:
        notice_id, recherche = _nouvelle_notice(conn, None, "manuel"), False
    # Seuls les champs remplis sont protégés : les catalogues complètent les autres
    champs = {k: v for k, v in {"auteurs": auteurs, **champs}.items() if v and str(v).strip()}
    modifier_notice(conn, notice_id, {"titre": titre, **champs})
    ex_id = _nouvel_exemplaire(conn, notice_id, lieu_id, etagere_id, proprietaire)
    db.reindex_notice(conn, notice_id)
    conn.commit()
    n = resume_notice(conn, notice_id)
    return {"notice_id": notice_id, "reference": n["reference"], "exemplaire_id": ex_id, "recherche": recherche}


def ajouter_depuis_bnf(conn, notice_bnf: dict, lieu_id=None, etagere_id=None,
                       proprietaire: str | None = None) -> dict:
    """Ajoute un livre trouvé par la recherche BnF titre/auteur (voir sources.bnf.rechercher).

    Avec un ISBN, c'est un scan comme un autre. Sans ISBN (livres anciens), la notice BnF est
    rangée comme réponse brute : la fiche est complète et cotée tout de suite.
    """
    from .resolver import rebuild
    from .sources import bnf

    if notice_bnf.get("isbn"):
        try:
            res = ajouter(conn, notice_bnf["isbn"], lieu_id, etagere_id, proprietaire)
            return {**res, "recherche": True}
        except Erreur:
            pass                                 # ISBN mal formé dans la notice : traité comme sans ISBN
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    notice_id = _nouvelle_notice(conn, None, "trouve")
    conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) VALUES (?, ?, 'ok', ?, ?)",
                 (notice_id, bnf.NAME, bnf.reponse_unique(notice_bnf["xml"]), db.now()))
    ex_id = _nouvel_exemplaire(conn, notice_id, lieu_id, etagere_id, proprietaire)
    rebuild(conn, notice_id)
    return {"notice_id": notice_id, "reference": f"L{notice_id}", "exemplaire_id": ex_id, "recherche": False}


def fixer_classification(conn, ref: int | str, systeme: str, code: str | None,
                         libelle_perso: str | None = None) -> None:
    """Cote choisie à la main (prioritaire), ou retour au calcul automatique si code vide."""
    if systeme not in SYSTEMES:
        raise Erreur(tr("système inconnu : {systeme} (choix : {choix})", systeme=systeme, choix=", ".join(SYSTEMES)))
    notice_id = _id(conn, ref)
    conn.execute("DELETE FROM classifications WHERE notice_id = ? AND systeme = ?", (notice_id, systeme))
    code = code.strip() if code else None
    if code:
        lib = libelle_perso or libelle(systeme, code)
        if systeme in ("rayon", "clil", "thema") and not lib:
            from .classify.regles import options
            match = next((o for o in options(systeme) if code in (o["code"], o["abbr"])), None)
            lib = match["libelle"] if match else None
        conn.execute(
            "INSERT INTO classifications(notice_id, systeme, code, libelle, origine) VALUES (?, ?, ?, ?, 'manuel')",
            (notice_id, systeme, code, lib))
    n = db.notice_dict(conn.execute("SELECT corrections FROM notices WHERE id = ?", (notice_id,)).fetchone())
    n["corrections"][f"cote:{systeme}"] = {"le": db.horodatage(), "manuel": bool(code)}
    conn.execute("UPDATE notices SET corrections = ? WHERE id = ?", (db.jdump(n["corrections"]), notice_id))
    classer_notice(conn, notice_id)
    conn.commit()


def supprimer_notice(conn, ref: int | str, valider: bool = True) -> None:
    """Supprime une fiche, avec ses réponses de catalogues, ses cotes et sa couverture si elle lui est propre."""
    from . import covers

    notice_id = db.id_notice(conn, ref)
    n = conn.execute("SELECT isbn13, uid FROM notices WHERE id = ?", (notice_id,)).fetchone()
    if not n:
        return
    conn.execute("DELETE FROM notices WHERE id = ?", (notice_id,))
    conn.execute("DELETE FROM notices_fts WHERE rowid = ?", (notice_id,))
    if valider:
        conn.commit()
        if not n["isbn13"]:
            covers.oublier(n["uid"])          # une couverture d'ISBN peut servir à une autre base


# --- Modes de scan ----------------------------------------------------------------

def _nouvel_exemplaire(conn, notice_id: int, lieu_id, etagere_id, proprietaire: str | None = None) -> int:
    now = db.now()
    cur = conn.execute(
        "INSERT INTO exemplaires(uid, notice_id, proprietaire_id, lieu_id, etagere_id, ajoute_le, maj_le) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (db.nouvel_uid(), notice_id, personne_id(conn, proprietaire) or db.moi_id(conn),
         lieu_id, etagere_id, now, db.horodatage()))
    return cur.lastrowid


def ajouter(conn, raw: str, lieu_id=None, etagere_id=None, proprietaire: str | None = None,
            filtrer_rebond: bool = True) -> dict:
    """Mode ajout : un scan = un exemplaire de plus à l'emplacement courant.

    `filtrer_rebond` ignore une double lecture ; un import de fichier le coupe, chaque ligne y étant voulue.
    """
    code = _code(raw)
    notice_id = db.id_notice(conn, code)
    if notice_id is None and code.startswith("L"):
        raise Erreur(tr("livre inconnu : {isbn}", isbn=code))
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    tous = exemplaires_de(conn, notice_id) if notice_id else []
    existants = [e for e in tous if e["a_moi"]]
    chez_amis = sorted({e["proprietaire"] for e in tous if not e["a_moi"]})
    if existants and filtrer_rebond:
        dernier = max(existants, key=lambda e: e["ajoute_le"])
        recent = datetime.fromisoformat(dernier["ajoute_le"]) > datetime.now() - timedelta(seconds=REBOND_SECONDES)
        if recent and dernier["lieu_id"] == lieu_id and dernier["etagere_id"] == etagere_id:
            return {"ok": True, "statut": "rebond", "code": code, "notice_id": notice_id,
                    "message": tr("lecture en double ignorée"), "notice": resume_notice(conn, notice_id)}
    nouveau = False
    if notice_id is None:
        notice_id, nouveau = creer_notice_attente(conn, code)
    ex_id = _nouvel_exemplaire(conn, notice_id, lieu_id, etagere_id, proprietaire)
    conn.commit()
    res = {
        "ok": True, "code": code, "notice_id": notice_id, "exemplaire_id": ex_id, "nouveau": nouveau,
        "emplacement": nom_emplacement(conn, lieu_id, etagere_id),
        "notice": resume_notice(conn, notice_id),
        "autres": [e["emplacement"] for e in existants],
    }
    if existants:
        res["statut"] = "doublon"
        res["message"] = tr("déjà {n} exemplaire(s) : {ou} — ajouté quand même",
                            n=len(existants), ou=", ".join(res["autres"]))
    else:
        res["statut"] = "ajoute"
        res["message"] = tr("ajouté")
    if chez_amis:
        res["message"] += tr(" ({qui} l'a aussi)", qui=", ".join(chez_amis))
    return res


def _verifier_a_moi(conn, ex) -> None:
    """`ex` : une ligne de exemplaires_v."""
    if ex["proprietaire_id"] != db.moi_id(conn):
        raise Erreur(tr("ce livre appartient à {qui}", qui=ex["proprietaire"]))


def retirer_exemplaire(conn, exemplaire_id: int) -> bool:
    """Supprime un exemplaire (et la notice si c'était le dernier), sans valider la transaction."""
    row = conn.execute("SELECT uid, notice_id FROM exemplaires WHERE id = ?", (exemplaire_id,)).fetchone()
    if not row:
        return False
    tracer_suppression(conn, row["uid"], "exemplaire")
    conn.execute("DELETE FROM exemplaires WHERE id = ?", (exemplaire_id,))
    if not conn.execute("SELECT 1 FROM exemplaires WHERE notice_id = ?", (row["notice_id"],)).fetchone():
        supprimer_notice(conn, row["notice_id"], valider=False)
    return True


def annuler_exemplaire(conn, exemplaire_id: int) -> None:
    """Supprime un exemplaire (et la notice si c'était le dernier)."""
    if not retirer_exemplaire(conn, exemplaire_id):
        raise Erreur(tr("exemplaire introuvable"))
    conn.commit()


def deplacer_exemplaire(conn, exemplaire_id: int, lieu_id, etagere_id) -> None:
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    ex = conn.execute("SELECT * FROM exemplaires_v WHERE id = ?", (exemplaire_id,)).fetchone()
    if not ex:
        raise Erreur(tr("exemplaire introuvable"))
    _verifier_a_moi(conn, ex)
    if (ex["lieu_id"], ex["etagere_id"]) == (lieu_id, etagere_id):
        return
    conn.execute("UPDATE exemplaires SET lieu_id = ?, etagere_id = ?, maj_le = ? WHERE id = ?",
                 (lieu_id, etagere_id, db.horodatage(), exemplaire_id))
    conn.execute(
        "INSERT INTO mouvements(uid, exemplaire_id, de_lieu, de_etagere, vers_lieu, vers_etagere, date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (db.nouvel_uid(), exemplaire_id, ex["lieu_id"], ex["etagere_id"], lieu_id, etagere_id, db.now()))
    conn.commit()


def modifier_exemplaire(conn, exemplaire_id: int, champs: dict) -> None:
    """État, achat, provenance, dédicace, valeur, note d'un de mes exemplaires ; tout est facultatif."""
    ex = conn.execute("SELECT * FROM exemplaires_v WHERE id = ?", (exemplaire_id,)).fetchone()
    if not ex:
        raise Erreur(tr("exemplaire introuvable"))
    _verifier_a_moi(conn, ex)
    values = {}
    for cle, val in champs.items():
        if cle not in CHAMPS_EXEMPLAIRE:
            raise Erreur(tr("champ non modifiable : {champ}", champ=cle))
        if isinstance(val, str):
            val = val.strip() or None
        if cle == "etat" and val is not None and val not in ETATS:
            raise Erreur(tr("état inconnu : {valeur}", valeur=val))
        if cle == "date_achat":
            _date(val)
        if cle in ("prix_achat", "valeur") and val is not None:
            try:
                val = float(str(val).replace(",", "."))
            except ValueError:
                raise Erreur(tr("{champ} doit être un nombre", champ=cle))
            if val < 0:
                raise Erreur(tr("{champ} doit être un nombre", champ=cle))
        values[cle] = val
    if not values:
        return
    values["maj_le"] = db.horodatage()
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE exemplaires SET {sets} WHERE id = ?", [*values.values(), exemplaire_id])
    db.reindex_notice(conn, ex["notice_id"])
    conn.commit()


def deplacer(conn, raw: str, lieu_id, etagere_id) -> dict:
    """Mode déplacement : le livre scanné rejoint l'emplacement courant."""
    code = _code(raw)
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    notice_id = db.id_notice(conn, code)
    existants = exemplaires_de(conn, notice_id, miens=True) if notice_id else []
    cible = nom_emplacement(conn, lieu_id, etagere_id)
    if not existants:
        return {"ok": False, "statut": "inconnu", "code": code,
                "message": tr("ce livre n'est pas dans la collection (passez en mode ajout)")}
    if any((e["lieu_id"], e["etagere_id"]) == (lieu_id, etagere_id) for e in existants):
        return {"ok": True, "statut": "deja_la", "code": code, "notice_id": notice_id,
                "message": tr("déjà rangé : {ou}", ou=cible), "notice": resume_notice(conn, notice_id)}
    ex = existants[0]
    deplacer_exemplaire(conn, ex["id"], lieu_id, etagere_id)
    return {"ok": True, "statut": "deplace", "code": code, "notice_id": notice_id, "exemplaire_id": ex["id"],
            "message": f"{ex['emplacement']} → {cible}", "notice": resume_notice(conn, notice_id)}


def localiser(conn, raw: str) -> dict:
    """Mode « où est-il ? »."""
    code = _code(raw)
    notice_id = db.id_notice(conn, code)
    existants = exemplaires_de(conn, notice_id) if notice_id else []
    if not existants:
        return {"ok": False, "statut": "inconnu", "code": code,
                "message": tr("pas dans la collection")}
    places = []
    for e in existants:
        p = e["emplacement"]
        if e["pret"]:
            p += tr(" (prêté à {qui})", qui=e["pret"]["emprunteur"])
        places.append(p)
    return {"ok": True, "statut": "trouve", "code": code, "notice_id": notice_id, "message": " ; ".join(places),
            "emplacements": places, "notice": resume_notice(conn, notice_id)}


# --- Inventaire (récolement) ------------------------------------------------------

def demarrer_inventaire(conn, lieu_id: int, etagere_id: int | None = None) -> int:
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    if not lieu_id:
        raise Erreur(tr("choisissez un lieu à inventorier"))
    cur = conn.execute("INSERT INTO inventaires(lieu_id, etagere_id, debut) VALUES (?, ?, ?)",
                       (lieu_id, etagere_id, db.now()))
    conn.commit()
    return cur.lastrowid


def inventaire(conn, inv_id: int) -> dict:
    row = conn.execute("SELECT * FROM inventaires WHERE id = ?", (inv_id,)).fetchone()
    if not row:
        raise Erreur(tr("inventaire introuvable"))
    d = dict(row)
    d["emplacement"] = nom_emplacement(conn, row["lieu_id"], row["etagere_id"])
    return d


def _dans_zone(inv: dict, ex: dict) -> bool:
    if ex["lieu_id"] != inv["lieu_id"]:
        return False
    return inv["etagere_id"] is None or ex["etagere_id"] == inv["etagere_id"]


def scanner_inventaire(conn, inv_id: int, raw: str, filtrer_rebond: bool = True) -> dict:
    inv = inventaire(conn, inv_id)
    if inv["fin"]:
        raise Erreur(tr("cet inventaire est clôturé"))
    code = _code(raw)
    notice_id = db.id_notice(conn, code)
    if notice_id is None and code.startswith("L"):
        raise Erreur(tr("livre inconnu : {isbn}", isbn=code))
    res = {"code": code, "notice_id": notice_id, "notice": resume_notice(conn, notice_id) if notice_id else None}
    deja = conn.execute("SELECT scanne_le FROM inventaire_scans WHERE inventaire_id = ? AND code = ?",
                        (inv_id, code)).fetchone()
    if filtrer_rebond and deja and (datetime.fromisoformat(deja["scanne_le"])
                                    > datetime.now() - timedelta(seconds=REBOND_SECONDES)):
        return {**res, "ok": True, "statut": "rebond", "message": tr("lecture en double ignorée")}
    conn.execute("INSERT INTO inventaire_scans(inventaire_id, code, scanne_le) VALUES (?, ?, ?) "
                 "ON CONFLICT(inventaire_id, code) DO UPDATE SET nb = nb + 1, scanne_le = excluded.scanne_le",
                 (inv_id, code, db.now()))
    conn.commit()
    existants = exemplaires_de(conn, notice_id, miens=True) if notice_id else []
    if not existants:
        return {**res, "ok": False, "statut": "inconnu", "message": tr("pas dans la collection")}
    attendus = sum(_dans_zone(inv, e) for e in existants)
    if attendus:
        nb = conn.execute("SELECT nb FROM inventaire_scans WHERE inventaire_id = ? AND code = ?",
                          (inv_id, code)).fetchone()["nb"]
        message = tr("présent") if attendus == 1 else tr("présent ({n} sur {total})", n=min(nb, attendus), total=attendus)
        return {**res, "ok": True, "statut": "present", "message": message}
    return {**res, "ok": False, "statut": "ailleurs",
            "message": tr("devrait être : {ou}", ou=", ".join(e["emplacement"] for e in existants))}


def rapport_inventaire(conn, inv_id: int) -> dict:
    """Compare les scans aux exemplaires attendus, un par un : deux exemplaires demandent deux scans."""
    inv = inventaire(conn, inv_id)
    scans = {r["code"]: r["nb"] for r in conn.execute(
        "SELECT code, nb FROM inventaire_scans WHERE inventaire_id = ?", (inv_id,))}
    sql = ("SELECT e.id, n.id AS notice_id, n.isbn13 FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
           "WHERE e.lieu_id = ? AND e.proprietaire_id = ?")
    params = [inv["lieu_id"], db.moi_id(conn)]
    if inv["etagere_id"]:
        sql += " AND e.etagere_id = ?"
        params.append(inv["etagere_id"])
    attendus = {}
    for e in conn.execute(sql, params):
        attendus.setdefault(db.reference(dict(e, id=e["notice_id"])), []).append(e["id"])
    pretes = {r[0] for r in conn.execute("SELECT exemplaire_id FROM prets WHERE date_retour IS NULL")}
    presents, manquants = [], []
    for code, ids in sorted(attendus.items()):
        ids.sort(key=lambda i: i in pretes)        # un exemplaire non vu : d'abord celui qui est prêté
        nb = scans.get(code, 0)
        presents += [resume_notice(conn, code)] * min(nb, len(ids))
        manquants += [dict(resume_notice(conn, code), prete=i in pretes) for i in ids[nb:]]
    ailleurs, inconnus = [], []
    for code in sorted(set(scans) - set(attendus)):
        notice_id = db.id_notice(conn, code)
        ex = exemplaires_de(conn, notice_id, miens=True) if notice_id else []
        if ex:
            ailleurs.append(dict(resume_notice(conn, notice_id), code=code, emplacements=[e["emplacement"] for e in ex]))
        else:
            inconnus.append(code)
    return {"inventaire": inv, "presents": presents, "manquants": manquants,
            "ailleurs": ailleurs, "inconnus": inconnus}


def cloturer_inventaire(conn, inv_id: int, ranger_ailleurs: bool = False,
                        ajouter_inconnus: bool = False) -> dict:
    rapport = rapport_inventaire(conn, inv_id)
    inv = rapport["inventaire"]
    deplaces = ajoutes = 0
    if ranger_ailleurs:
        for a in rapport["ailleurs"]:
            ex = exemplaires_de(conn, a["id"], miens=True)
            if ex:
                deplacer_exemplaire(conn, ex[0]["id"], inv["lieu_id"], inv["etagere_id"])
                deplaces += 1
    if ajouter_inconnus:
        for code in rapport["inconnus"]:
            ajouter(conn, code, inv["lieu_id"], inv["etagere_id"])
            ajoutes += 1
    conn.execute("UPDATE inventaires SET fin = ? WHERE id = ?", (db.now(), inv_id))
    conn.commit()
    return {"deplaces": deplaces, "ajoutes": ajoutes}


def inventaires(conn, limite: int = 20) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM inventaires ORDER BY id DESC LIMIT ?", (limite,)):
        d = dict(r)
        d["emplacement"] = nom_emplacement(conn, r["lieu_id"], r["etagere_id"])
        d["nb_scans"] = conn.execute("SELECT count(*) FROM inventaire_scans WHERE inventaire_id = ?",
                                     (r["id"],)).fetchone()[0]
        out.append(d)
    return out


# --- Recherche et listes ----------------------------------------------------------

def _fts_query(q: str) -> str:
    mots = re.findall(r"\w+", q, flags=re.UNICODE)
    return " ".join(f'"{m}"*' for m in mots)


TRIS = {
    "cote": "c.tri IS NULL, c.tri, n.auteur_tri, n.titre",
    "titre": "n.titre COLLATE NOCASE",
    "auteur": "n.auteur_tri COLLATE NOCASE, n.titre COLLATE NOCASE",
    "annee": "n.annee DESC",
    "ajout": "e.ajoute_le DESC",
}


def _date(valeur: str | None) -> str | None:
    if not valeur:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
            raise ValueError
        date.fromisoformat(valeur)
    except ValueError:
        raise Erreur(tr("date invalide : {valeur} (attendu AAAA-MM-JJ)", valeur=valeur))
    return valeur


def _filtres(q: str = "", lieu_id=None, etagere_id=None, statut: str | None = None,
             classe: str | None = None, a_classer: bool = False,
             ajout_du: str | None = None, ajout_au: str | None = None,
             proprietaire: int | None = None, lecture: str | None = None) -> tuple[list[str], list]:
    """Conditions SQL communes à la liste du catalogue et aux opérations groupées.

    `proprietaire` est déjà résolu par `_proprio` (None = tout le monde).
    """
    where, params = ["1 = 1"], []
    if proprietaire:
        where.append("e.proprietaire_id = ?")
        params.append(proprietaire)
    if lecture == "aucune":
        where.append("n.lecture IS NULL")
    elif lecture:
        where.append("n.lecture = ?")
        params.append(lecture)
    q = (q or "").strip()
    if q:
        ref = re.fullmatch(r"[Ll](\d+)", q)
        if ref:
            where.append("n.id = ?")
            params.append(int(ref.group(1)))
        else:
            try:
                isbn13 = normalize(q)
                where.append("n.isbn13 = ?")
                params.append(isbn13)
            except IsbnError:
                fts = _fts_query(q)
                if fts:
                    where.append("n.id IN (SELECT rowid FROM notices_fts WHERE notices_fts MATCH ?)")
                    params.append(fts)
    if lieu_id == "aucun":
        where.append("e.lieu_id IS NULL")
    elif lieu_id:
        where.append("e.lieu_id = ?")
        params.append(int(lieu_id))
    if etagere_id:
        where.append("e.etagere_id = ?")
        params.append(int(etagere_id))
    if statut:
        where.append("n.statut = ?")
        params.append(statut)
    if classe:
        where.append("c.libelle = ?")
        params.append(classe)
    if a_classer:
        where.append("c.code IS NULL")
    if _date(ajout_du):
        where.append("e.ajoute_le >= ?")
        params.append(ajout_du)
    if _date(ajout_au):
        where.append("e.ajoute_le < date(?, '+1 day')")       # jour de fin inclus
        params.append(ajout_au)
    return where, params


def _base(where: list[str]) -> str:
    return (
        "FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
        "JOIN personnes p ON p.id = e.proprietaire_id "
        "LEFT JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? "
        "LEFT JOIN lieux l ON l.id = e.lieu_id LEFT JOIN etageres et ON et.id = e.etagere_id "
        "WHERE " + " AND ".join(where)
    )


def rechercher(conn, q: str = "", lieu_id=None, etagere_id=None, statut: str | None = None,
               systeme: str | None = None, classe: str | None = None, a_classer: bool = False,
               ajout_du: str | None = None, ajout_au: str | None = None, proprietaire: str | None = None,
               lecture: str | None = None, tri: str = "cote", limite: int = 50,
               decalage: int = 0) -> tuple[list[dict], int]:
    """Exemplaires correspondant aux filtres, avec la cote du système choisi.

    `proprietaire` : vide = mes livres, « tous », ou le nom d'un ami.
    """
    systeme = systeme or systeme_courant(conn)
    moi = db.moi_id(conn)
    where, params = _filtres(q, lieu_id, etagere_id, statut, classe, a_classer, ajout_du, ajout_au,
                             _proprio(conn, proprietaire), lecture)
    base = _base(where)
    total = conn.execute(f"SELECT count(*) {base}", [systeme, *params]).fetchone()[0]
    order = TRIS.get(tri, TRIS["cote"])
    rows = conn.execute(
        f"SELECT e.id AS exemplaire_id, e.lieu_id, e.etagere_id, e.ajoute_le, e.proprietaire_id, "
        f"p.nom AS proprietaire, e.lieu_texte, n.*, "
        f"c.code, c.cote, c.libelle, c.origine, l.nom AS lieu, et.nom AS etagere, "
        f"(SELECT emprunteur FROM prets_v pr WHERE pr.exemplaire_id = e.id AND pr.date_retour IS NULL) AS emprunteur "
        f"{base} ORDER BY {order} LIMIT ? OFFSET ?",
        [systeme, *params, limite, decalage]).fetchall()
    out = []
    for r in rows:
        d = db.notice_dict(r)
        d["a_moi"] = r["proprietaire_id"] == moi
        if d["a_moi"]:
            d["emplacement"] = (r["lieu"] or tr("Non localisé")) + (f" › {r['etagere']}" if r["etagere"] else "")
        else:
            d["emplacement"] = r["lieu_texte"] or ""
        out.append(d)
    return out, total


def ids_exemplaires(conn, systeme: str | None = None, proprietaire: str | None = None, **filtres) -> list[int]:
    """Tous les exemplaires qui correspondent aux filtres (« sélectionner tous les résultats »)."""
    systeme = systeme or systeme_courant(conn)
    where, params = _filtres(**filtres, proprietaire=_proprio(conn, proprietaire))
    return [r[0] for r in conn.execute(f"SELECT e.id {_base(where)}", [systeme, *params])]


def deplacer_lot(conn, exemplaire_ids: list[int], lieu_id, etagere_id) -> int:
    """Range plusieurs exemplaires au même endroit (historique conservé pour chacun)."""
    lieu_id, etagere_id = _verifier_emplacement(conn, lieu_id, etagere_id)
    moi = db.moi_id(conn)
    exemplaires = [conn.execute("SELECT * FROM exemplaires WHERE id = ?", (i,)).fetchone() for i in exemplaire_ids]
    exemplaires = [ex for ex in exemplaires if ex]
    autres = [ex for ex in exemplaires if ex["proprietaire_id"] != moi]
    if autres:
        raise Erreur(tr("{n} livre(s) sélectionné(s) appartiennent à d'autres que vous : on ne range que ses propres livres",
                        n=len(autres)))
    n = 0
    for ex in exemplaires:
        if (ex["lieu_id"], ex["etagere_id"]) != (lieu_id, etagere_id):
            deplacer_exemplaire(conn, ex["id"], lieu_id, etagere_id)
            n += 1
    return n


def donner(conn, exemplaire_id: int, vers: str) -> bool:
    """Don : l'exemplaire change de propriétaire.

    Un prêt en cours est clos (le livre n'est plus à moi). S'il quitte ma collection, il
    quitte aussi mes étagères ; s'il y entre, il arrive non localisé, prêt à être rangé.
    """
    if not (vers or "").strip():
        raise Erreur(tr("indiquez à qui donner le livre"))
    ex = conn.execute("SELECT * FROM exemplaires WHERE id = ?", (exemplaire_id,)).fetchone()
    if not ex:
        raise Erreur(tr("exemplaire introuvable"))
    vers_id = personne_id(conn, vers)
    if ex["proprietaire_id"] == vers_id:
        conn.commit()
        return False
    conn.execute("UPDATE prets SET date_retour = ?, maj_le = ? WHERE exemplaire_id = ? AND date_retour IS NULL",
                 (db.now(), db.horodatage(), exemplaire_id))
    conn.execute("UPDATE exemplaires SET proprietaire_id = ?, lieu_id = NULL, etagere_id = NULL, lieu_texte = NULL, "
                 "maj_le = ? WHERE id = ?", (vers_id, db.horodatage(), exemplaire_id))
    conn.commit()
    return True


def donner_lot(conn, exemplaire_ids: list[int], vers: str) -> int:
    return sum(donner(conn, ex_id, vers) for ex_id in exemplaire_ids)


def retirer_lot(conn, exemplaire_ids: list[int]) -> int:
    n = 0
    for ex_id in exemplaire_ids:
        if conn.execute("SELECT 1 FROM exemplaires WHERE id = ?", (ex_id,)).fetchone():
            annuler_exemplaire(conn, ex_id)
            n += 1
    return n


# --- Doublons ---------------------------------------------------------------------

def _exemplaires_de_trop(conn, exemplaires: list) -> dict:
    """Ceux à retirer parmi plusieurs exemplaires d'un même emplacement.

    Un exemplaire renseigné (état, note, prêt…) est un objet bien réel : il reste, et rien ne dit
    que les autres en sont des copies. Sinon on garde celui qui a un historique, ou le plus ancien.
    """
    def renseigne(ex):
        return (any(ex[c] not in (None, "") for c in CHAMPS_EXEMPLAIRE)
                or conn.execute("SELECT 1 FROM prets WHERE exemplaire_id = ?", (ex["id"],)).fetchone())

    def a_bouge(ex):
        return conn.execute("SELECT 1 FROM mouvements WHERE exemplaire_id = ?", (ex["id"],)).fetchone()

    gardes = [ex for ex in exemplaires if renseigne(ex)]
    gardes = gardes or [min(exemplaires, key=lambda ex: (not a_bouge(ex), ex["id"]))]
    return {"garder": [ex["id"] for ex in gardes],
            "retirer": [ex["id"] for ex in exemplaires if ex not in gardes]}


def doublons(conn) -> dict:
    """Mes livres en plusieurs exemplaires ; ne modifie rien.

    titres    : tous lieux confondus, même notice (donc même ISBN)
    de_trop   : même notice au même emplacement ; un livre non localisé n'est jamais retiré
    editions  : même titre et même premier auteur, autre notice (autre édition, ou un autre tome)
    """
    par_notice: dict[int, list] = {}
    for ex in conn.execute("SELECT * FROM exemplaires WHERE proprietaire_id = ? ORDER BY id", (db.moi_id(conn),)):
        par_notice.setdefault(ex["notice_id"], []).append(ex)
    titres, de_trop, par_titre = [], [], {}
    for notice_id, exemplaires in par_notice.items():
        n = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
        livre = {"notice_id": notice_id, "reference": n["reference"], "titre": n["titre"], "auteurs": n["auteurs"]}
        if n["titre"] and n["auteurs"]:
            par_titre.setdefault((db.norm(n["titre"]).strip(), db.norm(n["auteurs"][0]).strip()), []).append(
                {**livre, "sous_titre": n["sous_titre"], "editeur": n["editeur"], "annee": n["annee"]})
        if len(exemplaires) < 2:
            continue
        titres.append({**livre, "exemplaires": [
            {"id": ex["id"], "emplacement": nom_emplacement(conn, ex["lieu_id"], ex["etagere_id"])}
            for ex in exemplaires]})
        par_emplacement: dict[tuple, list] = {}
        for ex in exemplaires:
            if ex["lieu_id"]:
                par_emplacement.setdefault((ex["lieu_id"], ex["etagere_id"]), []).append(ex)
        for (lieu_id, etagere_id), memes in par_emplacement.items():
            tri = _exemplaires_de_trop(conn, memes)
            if tri["retirer"]:
                de_trop.append({**livre, **tri, "emplacement": nom_emplacement(conn, lieu_id, etagere_id)})
    return {"titres": titres, "de_trop": de_trop,
            "editions": [livres for livres in par_titre.values() if len(livres) > 1]}


def retirer_doublons(conn) -> int:
    """Retire les exemplaires de trop d'un même emplacement, tous ou aucun."""
    ids = [ex_id for groupe in doublons(conn)["de_trop"] for ex_id in groupe["retirer"]]
    for ex_id in ids:
        retirer_exemplaire(conn, ex_id)
    conn.commit()
    return len(ids)


def classes_presentes(conn, systeme: str | None = None, lieu_id=None, proprietaire: str | None = None) -> list[dict]:
    """Libellés du système avec leur nombre d'exemplaires (filtres du catalogue)."""
    systeme = systeme or systeme_courant(conn)
    sql = ("SELECT c.libelle, min(c.tri) AS tri, count(*) AS nb FROM exemplaires e "
           "JOIN classifications c ON c.notice_id = e.notice_id AND c.systeme = ? WHERE 1 = 1 ")
    params = [systeme]
    if lieu_id:
        sql += "AND e.lieu_id = ? "
        params.append(int(lieu_id))
    if (proprio := _proprio(conn, proprietaire)):
        sql += "AND e.proprietaire_id = ? "
        params.append(proprio)
    sql += "GROUP BY c.libelle ORDER BY tri"
    return [dict(r) for r in conn.execute(sql, params) if r["libelle"]]


# Notices dont j'ai au moins un exemplaire (« À traiter », statistiques)
A_MOI = "EXISTS (SELECT 1 FROM exemplaires m WHERE m.notice_id = n.id AND m.proprietaire_id = ?)"


def nb_a_traiter(conn) -> int:
    return conn.execute(f"SELECT count(*) FROM notices n WHERE statut IN ('erreur', 'introuvable') AND {A_MOI}",
                        (db.moi_id(conn),)).fetchone()[0]


def nb_non_localises(conn) -> int:
    """Mes livres sans lieu (ceux des amis n'ont jamais de lieu chez moi)."""
    return conn.execute("SELECT count(*) FROM exemplaires WHERE lieu_id IS NULL AND proprietaire_id = ?",
                        (db.moi_id(conn),)).fetchone()[0]


def relancer(conn) -> int:
    """Remet en recherche les fiches en échec : introuvables, erreurs, ou un catalogue qui n'a pas répondu.

    Seuls les échecs sont redemandés : les réponses valides restent, et la fiche ne se vide pas.
    """
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM notices WHERE statut IN ('erreur', 'introuvable') AND isbn13 IS NOT NULL "
        "UNION SELECT r.notice_id FROM raw_responses r JOIN notices n ON n.id = r.notice_id "
        "WHERE r.statut = 'erreur' AND n.isbn13 IS NOT NULL")]
    conn.executemany("DELETE FROM raw_responses WHERE notice_id = ? AND statut != 'ok'", [(i,) for i in ids])
    conn.executemany("UPDATE notices SET statut = 'en_attente' WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    return len(ids)


def a_traiter(conn) -> dict:
    systeme = systeme_courant(conn)
    moi = db.moi_id(conn)
    def liste(sql, params=()):
        return [db.notice_dict(r) for r in conn.execute(sql, params)]
    return {
        "en_attente": liste(f"SELECT * FROM notices n WHERE statut = 'en_attente' AND {A_MOI} ORDER BY cree_le", (moi,)),
        "erreur": liste(f"SELECT * FROM notices n WHERE statut = 'erreur' AND {A_MOI} ORDER BY cree_le", (moi,)),
        "introuvable": liste(f"SELECT * FROM notices n WHERE statut = 'introuvable' AND {A_MOI} ORDER BY cree_le",
                             (moi,)),
        "partiels": liste(
            f"SELECT DISTINCT n.* FROM notices n JOIN raw_responses r ON r.notice_id = n.id "
            f"WHERE r.statut = 'erreur' AND n.statut IN ('trouve', 'manuel') AND {A_MOI} ORDER BY n.titre", (moi,)),
        "sans_cote": liste(
            f"SELECT n.* FROM notices n WHERE n.statut IN ('trouve', 'manuel') AND {A_MOI} AND NOT EXISTS "
            "(SELECT 1 FROM classifications c WHERE c.notice_id = n.id AND c.systeme = ?) "
            "ORDER BY n.titre", (moi, systeme)),
        "non_localises": liste(
            "SELECT DISTINCT n.* FROM notices n JOIN exemplaires e ON e.notice_id = n.id "
            "WHERE e.lieu_id IS NULL AND e.proprietaire_id = ? ORDER BY n.titre", (moi,)),
    }


NOMS_LANGUES = {"fre": "Français", "eng": "Anglais", "ger": "Allemand", "ita": "Italien", "spa": "Espagnol",
                "por": "Portugais", "lat": "Latin", "grc": "Grec ancien", "gre": "Grec moderne",
                "dut": "Néerlandais", "rus": "Russe", "pol": "Polonais", "jpn": "Japonais", "chi": "Chinois",
                "kor": "Coréen", "ara": "Arabe", "heb": "Hébreu", "swe": "Suédois", "nor": "Norvégien",
                "dan": "Danois", "cat": "Catalan", "mul": "Plusieurs langues"}
NOMS_FORMES = {"fiction": "Roman, récit", "nouvelles": "Nouvelles", "poesie": "Poésie", "theatre": "Théâtre",
               "essai": "Essai", "documentaire": "Documentaire", "humour": "Humour", "lettres": "Correspondance",
               "mixte": "Mixte"}


def _compter(conn, sql: str, params=(), nom=None) -> list[dict]:
    """Lignes (nom, nb) triées par nombre décroissant ; `nom` traduit les codes."""
    out = [dict(nom=r[0], nb=r[1]) for r in conn.execute(sql, params)]
    if nom:
        for r in out:
            r["nom"] = nom(r["nom"])
    return out


def _stats_prets(conn) -> dict:
    """Mes prêts : ceux en cours (les plus anciens d'abord), l'historique et le rythme mensuel."""
    maintenant = datetime.now()
    moi = (db.moi_id(conn),)
    en_cours = []
    for r in conn.execute(
            "SELECT p.emprunteur, p.date_pret, n.id, n.isbn13, n.titre FROM prets_v p "
            "JOIN exemplaires e ON e.id = p.exemplaire_id JOIN notices n ON n.id = e.notice_id "
            "WHERE p.date_retour IS NULL AND p.preteur_id = ? ORDER BY p.date_pret", moi):
        en_cours.append(dict(nom=r["titre"] or db.reference(r), qui=r["emprunteur"], depuis=r["date_pret"][:10],
                             nb=(maintenant - datetime.fromisoformat(r["date_pret"])).days,
                             url=f"/livre/{r['id']}"))
    moyenne = conn.execute("SELECT avg(julianday(date_retour) - julianday(date_pret)) FROM prets "
                           "WHERE date_retour IS NOT NULL AND preteur_id = ?", moi).fetchone()[0]
    par_mois = {r[0]: r[1] for r in conn.execute(
        "SELECT substr(date_pret, 1, 7), count(*) FROM prets WHERE preteur_id = ? GROUP BY 1", moi)}
    an, mois = maintenant.year, maintenant.month
    cles = []
    for _ in range(12):                                 # les 12 derniers mois, même sans prêt
        cles.append(f"{an}-{mois:02d}")
        an, mois = (an - 1, 12) if mois == 1 else (an, mois - 1)
    return {
        "prets_en_cours": en_cours,
        "prets_total": conn.execute("SELECT count(*) FROM prets WHERE preteur_id = ?", moi).fetchone()[0],
        "prets_duree_moyenne": None if moyenne is None else round(moyenne),
        "prets_par_emprunteur": _compter(conn, "SELECT emprunteur, count(*) AS nb FROM prets_v WHERE preteur_id = ? "
                                         "AND date_retour IS NULL GROUP BY emprunteur_id ORDER BY nb DESC, emprunteur", moi),
        "prets_par_mois": [dict(mois=c, nom=c, nb=par_mois.get(c, 0)) for c in reversed(cles)],
        "emprunteurs": _compter(conn, "SELECT emprunteur, count(*) AS nb FROM prets_v WHERE preteur_id = ? "
                                "GROUP BY emprunteur_id ORDER BY nb DESC, emprunteur", moi),
        "plus_pretes": [dict(nom=r["titre"] or db.reference(r), nb=r["nb"], url=f"/livre/{r['id']}") for r in conn.execute(
            "SELECT n.id, n.isbn13, n.titre, count(*) AS nb FROM prets p JOIN exemplaires e ON e.id = p.exemplaire_id "
            "JOIN notices n ON n.id = e.notice_id WHERE p.preteur_id = ? GROUP BY n.id ORDER BY nb DESC, n.titre", moi)],
    }


def _reseau_prets(conn) -> dict:
    """Graphe des prêts : une personne par nœud, un lien par paire de personnes.

    `livres` vaut None quand la base ne connaît pas sa bibliothèque. Un lien additionne les prêts dans
    les deux sens. Il relie aussi deux amis quand l'un a partagé ses prêts (biblio share --with-loans).
    """
    moi = db.moi_id(conn)
    personnes = {r["id"]: r for r in conn.execute("SELECT id, nom, cle FROM personnes")}
    noeuds = {moi: dict(nom=personnes[moi]["nom"], livres=0, a_moi=True, url="/catalogue")}
    for r in conn.execute("SELECT proprietaire_id, count(*) FROM exemplaires GROUP BY proprietaire_id"):
        if r[0] == moi:
            noeuds[moi]["livres"] = r[1]
        else:
            nom = personnes[r[0]]["nom"]
            noeuds[r[0]] = dict(nom=nom, livres=r[1], a_moi=False, url=f"/catalogue?{urlencode({'proprio': nom})}")
    aretes = {}
    for r in conn.execute("SELECT preteur_id, emprunteur_id, count(*), sum(date_retour IS NULL) FROM prets "
                          "GROUP BY preteur_id, emprunteur_id"):
        if r[0] == r[1]:
            continue                                    # un prêt à soi-même n'est pas un lien
        for pid in r[:2]:
            noeuds.setdefault(pid, dict(nom=personnes[pid]["nom"], livres=None, a_moi=False, url=None))
        de, vers = sorted(r[:2], key=lambda i: (i != moi, personnes[i]["cle"]))     # moi d'abord
        a = aretes.setdefault((de, vers), dict(de=personnes[de]["cle"], vers=personnes[vers]["cle"], nb=0, en_cours=0,
                                               nom=f"{personnes[de]['nom']} — {personnes[vers]['nom']}"))
        a["nb"] += r[2]
        a["en_cours"] += r[3]
    return {
        "reseau_noeuds": [dict(n, id=personnes[pid]["cle"]) for pid, n in noeuds.items()],
        "reseau_aretes": sorted(aretes.values(), key=lambda a: (-a["nb"], a["nom"])),
    }


def _tranches_pages(conn, moi: tuple) -> list[dict]:
    """Nombre de livres par tranche de 100 pages ; toutes les tranches, pour une échelle régulière."""
    compte = {r[0]: r[1] for r in conn.execute(
        "SELECT min(n.pages / 100, 8), count(*) FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
        "WHERE e.proprietaire_id = ? AND n.pages > 0 GROUP BY 1", moi)}
    if not compte:
        return []
    out = []
    for t in range(9):
        if t == 0:
            nom, court = tr("moins de 100 pages"), "0"
        elif t == 8:
            nom, court = tr("800 pages et plus"), "800+"
        else:
            nom, court = tr("{a} à {b} pages", a=t * 100, b=t * 100 + 99), str(t * 100)
        out.append(dict(nom=nom, court=court, nb=compte.get(t, 0)))
    return out


def _par_collection(conn, moi: tuple) -> list[dict]:
    """Collections, sans numéro ni préfixe : « Folio ; 4082 » et « Gallimard | Collection Folio » comptent pour Folio."""
    noms, compte = {}, {}
    for (texte, nb) in conn.execute(
            "SELECT n.collection, count(*) FROM exemplaires e JOIN notices n ON n.id = e.notice_id "
            "WHERE e.proprietaire_id = ? AND n.collection IS NOT NULL GROUP BY n.collection", moi):
        nom = re.sub(r"^collection\s+", "", texte.split(" | ")[-1].split(" ; ")[0].strip(), flags=re.I)
        if nom:
            cle = norm(nom)
            if cle not in noms or (nom[0].isupper() and not noms[cle][0].isupper()):
                noms[cle] = nom                # « Folio » plutôt que « folio »
            compte[cle] = compte.get(cle, 0) + nb
    return sorted(({"nom": noms[c], "nb": n} for c, n in compte.items()), key=lambda r: (-r["nb"], r["nom"]))


def _par_etagere(conn, moi: tuple) -> list[dict]:
    out = []
    for r in conn.execute(
            "SELECT e.lieu_id, e.etagere_id, l.nom AS lieu, et.nom AS etagere, count(*) AS nb FROM exemplaires e "
            "JOIN lieux l ON l.id = e.lieu_id LEFT JOIN etageres et ON et.id = e.etagere_id "
            "WHERE e.proprietaire_id = ? GROUP BY e.lieu_id, e.etagere_id ORDER BY nb DESC, l.nom", moi):
        url = f"/catalogue?lieu={r['lieu_id']}" + (f"&etagere={r['etagere_id']}" if r["etagere_id"] else "")
        nom = f"{r['lieu']} › {r['etagere']}" if r["etagere"] else r["lieu"]
        out.append(dict(nom=nom, nb=r["nb"], url=url))
    return out


def _completude(conn, moi: tuple, systeme: str) -> list[dict]:
    """Part des fiches renseignées : ce qu'il reste à compléter."""
    from . import covers

    notices = conn.execute(f"SELECT n.isbn13, n.uid FROM notices n WHERE {A_MOI}", moi).fetchall()
    total = len(notices)
    if not total:
        return []
    def champ(condition):
        return conn.execute(f"SELECT count(*) FROM notices n WHERE {A_MOI} AND {condition}", moi).fetchone()[0]
    exemplaires = conn.execute("SELECT count(*) FROM exemplaires WHERE proprietaire_id = ?", moi).fetchone()[0]
    return [
        dict(nom=tr("Rangés dans un lieu"), total=exemplaires, nb=conn.execute(
            "SELECT count(*) FROM exemplaires WHERE proprietaire_id = ? AND lieu_id IS NOT NULL", moi).fetchone()[0]),
        dict(nom=tr("Forme connue"), total=total, nb=champ("n.forme IS NOT NULL")),
        dict(nom=tr("Année d'édition"), total=total, nb=champ("n.annee IS NOT NULL")),
        dict(nom=tr("Nombre de pages"), total=total, nb=champ("n.pages IS NOT NULL")),
        dict(nom=tr("Couverture"), total=total, nb=sum(covers.chemin(db.cle_couverture(n)).exists() for n in notices)),
        dict(nom=tr("Cote fournie par un catalogue"), total=total, nb=conn.execute(
            f"SELECT count(*) FROM notices n JOIN classifications c ON c.notice_id = n.id AND c.systeme = ? "
            f"WHERE {A_MOI} AND c.origine = 'source'", (systeme, *moi)).fetchone()[0]),
        dict(nom=tr("Résumé"), total=total, nb=champ("n.resume IS NOT NULL")),
        dict(nom=tr("Note personnelle"), total=total, nb=champ("n.notes IS NOT NULL")),
    ]


def _records(conn, moi: tuple) -> list[dict]:
    """Les livres extrêmes de la collection."""
    def premier(condition, ordre, valeur, libelle):
        r = conn.execute(f"SELECT n.id, n.isbn13, n.titre, n.annee, n.pages FROM notices n WHERE {A_MOI} AND {condition} "
                         f"ORDER BY {ordre}, n.titre LIMIT 1", moi).fetchone()
        return r and dict(libelle=libelle, titre=r["titre"] or db.reference(r), url=f"/livre/{r['id']}", valeur=valeur(r))
    pages = lambda r: tr("{n} pages", n=r["pages"])
    annee = lambda r: str(r["annee"])
    return [x for x in (
        premier("n.annee IS NOT NULL", "n.annee", annee, tr("Le plus ancien")),
        premier("n.annee IS NOT NULL", "n.annee DESC", annee, tr("Le plus récent")),
        premier("n.pages > 0", "n.pages DESC", pages, tr("Le plus long")),
        premier("n.pages > 0", "n.pages", pages, tr("Le plus court")),
    ) if x]


def _amis(conn, moi: tuple) -> list[dict]:
    """Pour chaque ami : ses livres, ceux que j'ai aussi, et ceux que je pourrais lui emprunter."""
    return [dict(r) for r in conn.execute(
        "SELECT p.nom, count(*) AS exemplaires, count(DISTINCT e.notice_id) AS titres, "
        "count(DISTINCT CASE WHEN m.notice_id IS NOT NULL THEN e.notice_id END) AS communs, "
        "count(DISTINCT CASE WHEN m.notice_id IS NULL THEN e.notice_id END) AS absents "
        "FROM exemplaires e JOIN personnes p ON p.id = e.proprietaire_id "
        "LEFT JOIN (SELECT DISTINCT notice_id FROM exemplaires WHERE proprietaire_id = ?) m "
        "ON m.notice_id = e.notice_id WHERE e.proprietaire_id != ? GROUP BY p.id ORDER BY exemplaires DESC, p.nom",
        (*moi, *moi))]


def _stats_lecture(conn) -> dict:
    """Ce que j'ai lu (fiches renseignées seulement : par défaut, l'état de lecture est vide)."""
    def un(sql):
        return conn.execute(sql).fetchone()[0]
    moyenne = un("SELECT avg(etoiles) FROM notices WHERE etoiles IS NOT NULL")
    return {
        "lecture_lus": un("SELECT count(*) FROM notices WHERE lecture = 'lu'"),
        "lecture_en_cours": un("SELECT count(*) FROM notices WHERE lecture = 'en_cours'"),
        "lecture_a_lire": un("SELECT count(*) FROM notices WHERE lecture = 'a_lire'"),
        "lecture_pages": un("SELECT coalesce(sum(pages), 0) FROM notices WHERE lecture = 'lu'"),
        "lecture_note_moyenne": None if moyenne is None else round(moyenne, 1),
        "par_lecture": _compter(conn, "SELECT lecture, count(*) AS nb FROM notices WHERE lecture IS NOT NULL "
                                "GROUP BY lecture ORDER BY nb DESC", nom=lambda v: tr(NOMS_LECTURES.get(v, v))),
        "lus_par_an": _compter(conn, "SELECT substr(lecture_fin, 1, 4) AS an, count(*) FROM notices "
                               "WHERE lecture = 'lu' AND lecture_fin IS NOT NULL GROUP BY an ORDER BY an"),
        "par_etoiles": _compter(conn, "SELECT etoiles, count(*) FROM notices WHERE etoiles IS NOT NULL "
                                "GROUP BY etoiles ORDER BY etoiles DESC", nom=lambda v: "★" * v),
    }


def _stats_valeur(conn, moi: tuple) -> dict:
    """Ce que valent mes exemplaires, d'après ce qui a été renseigné."""
    r = conn.execute("SELECT coalesce(sum(valeur), 0), count(valeur), coalesce(sum(prix_achat), 0), count(prix_achat) "
                     "FROM exemplaires WHERE proprietaire_id = ?", moi).fetchone()
    return {"valeur_totale": r[0], "valeur_renseignee": r[1], "prix_total": r[2], "prix_renseigne": r[3],
            "par_etat": _compter(conn, "SELECT etat, count(*) AS nb FROM exemplaires WHERE proprietaire_id = ? "
                                 "AND etat IS NOT NULL GROUP BY etat ORDER BY nb DESC", moi,
                                 nom=lambda v: tr(NOMS_ETATS.get(v, v)))}


def stats(conn) -> dict:
    """Chiffres de ma collection (les livres des amis ne comptent pas)."""
    systeme = systeme_courant(conn)
    moi = (db.moi_id(conn),)
    one = lambda sql, p=moi: conn.execute(sql, p).fetchone()[0]
    base = "FROM exemplaires e JOIN notices n ON n.id = e.notice_id WHERE e.proprietaire_id = ? "
    debut_activite = (datetime.now() - timedelta(days=371)).date().isoformat()
    return {
        "notices": one("SELECT count(DISTINCT n.id) " + base),
        "exemplaires": one("SELECT count(*) " + base),
        "auteurs": one("SELECT count(DISTINCT n.auteur_tri) " + base + "AND n.auteur_tri IS NOT NULL"),
        "pages": one("SELECT coalesce(sum(n.pages), 0) " + base),
        "pages_moyenne": round(one("SELECT coalesce(avg(n.pages), 0) " + base + "AND n.pages > 0")),
        "titres_multiples": one("SELECT count(*) FROM (SELECT n.id " + base + "GROUP BY n.id HAVING count(*) > 1)",
                                moi),
        "prets": nb_prets(conn),
        "statuts": {r[0]: r[1] for r in conn.execute(
            f"SELECT statut, count(*) FROM notices n WHERE {A_MOI} GROUP BY statut", moi)},
        # Listes complètes : la page montre les premiers, et regroupe le reste en « Autres »
        "par_lieu": _compter(conn, "SELECT l.nom, count(*) AS nb FROM exemplaires e "
                             "LEFT JOIN lieux l ON l.id = e.lieu_id WHERE e.proprietaire_id = ? "
                             "GROUP BY l.id ORDER BY nb DESC", moi,
                             nom=lambda v: v or tr("Non localisé")),
        "par_classe": _compter(conn, "SELECT c.libelle, count(*) AS nb FROM exemplaires e JOIN classifications c "
                               "ON c.notice_id = e.notice_id AND c.systeme = ? WHERE e.proprietaire_id = ? "
                               "GROUP BY c.libelle ORDER BY nb DESC", (systeme, *moi)),
        "par_auteur": _compter(conn, "SELECT n.auteur_tri, count(*) AS nb " + base +
                               "AND n.auteur_tri IS NOT NULL GROUP BY n.auteur_tri ORDER BY nb DESC", moi),
        "par_editeur": _compter(conn, "SELECT min(n.editeur), count(*) AS nb " + base +
                                "AND n.editeur IS NOT NULL GROUP BY lower(n.editeur) ORDER BY nb DESC", moi),
        "par_langue": _compter(conn, "SELECT coalesce(n.langue_originale, n.langue), count(*) AS nb " + base +
                               "GROUP BY 1 ORDER BY nb DESC", moi,
                               nom=lambda v: tr(NOMS_LANGUES.get(v, v)) if v else tr("Inconnue")),
        "par_forme": _compter(conn, "SELECT n.forme, count(*) AS nb " + base + "GROUP BY n.forme ORDER BY nb DESC",
                              moi, nom=lambda v: tr(NOMS_FORMES.get(v, v)) if v else tr("Non précisée")),
        "par_decennie": _compter(conn, "SELECT (n.annee / 10) * 10 AS d, count(*) " + base +
                                 "AND n.annee IS NOT NULL GROUP BY d ORDER BY d", moi),
        "par_public": _compter(conn, "SELECT n.public, count(*) AS nb " + base + "GROUP BY n.public ORDER BY nb DESC", moi,
                               nom=lambda v: tr(v) if v else tr("Non précisé")),
        "par_pages": _tranches_pages(conn, moi),
        "par_collection": _par_collection(conn, moi),
        "par_etagere": _par_etagere(conn, moi),
        "completude": _completude(conn, moi, systeme),
        "plusieurs_exemplaires": [dict(nom=r["titre"] or db.reference(r), nb=r["nb"], url=f"/livre/{r['id']}")
                                  for r in conn.execute(
            "SELECT n.id, n.isbn13, n.titre, count(*) AS nb " + base +
            "GROUP BY n.id HAVING nb > 1 ORDER BY nb DESC, n.titre", moi)],
        "records": _records(conn, moi),
        "amis": _amis(conn, moi),
        **_stats_prets(conn),
        **_reseau_prets(conn),
        **_stats_lecture(conn),
        **_stats_valeur(conn, moi),
        # Activité : livres ajoutés par jour, sur un peu plus d'un an
        "activite": {r[0]: r[1] for r in conn.execute(
            "SELECT date(ajoute_le) AS jour, count(*) FROM exemplaires WHERE ajoute_le >= ? AND proprietaire_id = ? "
            "GROUP BY jour", (debut_activite, *moi))},
        "systeme": systeme,
    }


# --- Prêts ------------------------------------------------------------------------

def preter(conn, raw_or_ex: str | int, emprunteur: str) -> dict:
    if not emprunteur or not emprunteur.strip():
        raise Erreur(tr("indiquez à qui le livre est prêté"))
    ex_id = _exemplaire_pour(conn, raw_or_ex, disponible=True)
    ex = conn.execute("SELECT * FROM exemplaires_v WHERE id = ?", (ex_id,)).fetchone()
    if not ex:
        raise Erreur(tr("exemplaire introuvable"))
    _verifier_a_moi(conn, ex)
    if conn.execute("SELECT 1 FROM prets WHERE exemplaire_id = ? AND date_retour IS NULL", (ex_id,)).fetchone():
        raise Erreur(tr("tous les exemplaires sont déjà prêtés"))
    quand = db.horodatage()
    conn.execute("INSERT INTO prets(uid, exemplaire_id, preteur_id, emprunteur_id, date_pret, maj_le) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (db.nouvel_uid(), ex_id, db.moi_id(conn), personne_id(conn, emprunteur), db.now(), quand))
    conn.execute("UPDATE exemplaires SET maj_le = ? WHERE id = ?", (quand, ex_id))
    conn.commit()
    return {"exemplaire_id": ex_id}


def rendre(conn, raw_or_ex: str | int) -> dict:
    ex_id = _exemplaire_pour(conn, raw_or_ex, disponible=False)
    pret = conn.execute("SELECT * FROM prets_v WHERE exemplaire_id = ? AND date_retour IS NULL", (ex_id,)).fetchone()
    if not pret:
        raise Erreur(tr("ce livre n'est pas prêté"))
    if pret["preteur_id"] != db.moi_id(conn):        # le prêt d'un ami : c'est à lui de le clore
        raise Erreur(tr("ce livre appartient à {qui}", qui=pret["preteur"]))
    quand = db.horodatage()
    conn.execute("UPDATE prets SET date_retour = ?, maj_le = ? WHERE id = ?", (db.now(), quand, pret["id"]))
    conn.execute("UPDATE exemplaires SET maj_le = ? WHERE id = ?", (quand, ex_id))
    conn.commit()
    return {"emprunteur": pret["emprunteur"], "exemplaire_id": ex_id}


def _exemplaire_pour(conn, raw_or_ex, disponible: bool) -> int:
    if isinstance(raw_or_ex, int) or str(raw_or_ex).isdigit() and len(str(raw_or_ex)) < 9:
        return int(raw_or_ex)
    notice_id = db.id_notice(conn, _code(str(raw_or_ex)))
    ex = exemplaires_de(conn, notice_id, miens=True) if notice_id else []
    if not ex:
        raise Erreur(tr("pas dans la collection"))
    choix = [e for e in ex if (e["pret"] is None) == disponible]
    if not choix:
        raise Erreur(tr("tous les exemplaires sont déjà prêtés") if disponible else tr("ce livre n'est pas prêté"))
    return choix[0]["id"]


def nb_prets(conn) -> int:
    """Mes prêts en cours."""
    return conn.execute("SELECT count(*) FROM prets WHERE date_retour IS NULL AND preteur_id = ?",
                        (db.moi_id(conn),)).fetchone()[0]


def prets(conn, en_cours: bool = True) -> list[dict]:
    """Mes prêts (ceux des amis ne servent qu'au réseau et à savoir si leur livre est disponible)."""
    sql = ("SELECT p.*, e.notice_id, n.isbn13, n.titre, n.auteurs FROM prets_v p "
           "JOIN exemplaires e ON e.id = p.exemplaire_id JOIN notices n ON n.id = e.notice_id WHERE p.preteur_id = ? ")
    sql += "AND p.date_retour IS NULL ORDER BY p.date_pret" if en_cours else "ORDER BY p.date_pret DESC"
    out = []
    for r in conn.execute(sql, (db.moi_id(conn),)):
        d = dict(r, auteurs=db.jload(r["auteurs"], []))
        d["reference"] = d["isbn13"] or f"L{d['notice_id']}"
        out.append(d)
    return out


# --- Réglages ---------------------------------------------------------------------

def choisir_systeme(conn, systeme: str) -> None:
    if systeme not in SYSTEMES:
        raise Erreur(tr("système inconnu : {systeme} (choix : {choix})", systeme=systeme, choix=", ".join(SYSTEMES)))
    db.set_meta(conn, "systeme", systeme)

