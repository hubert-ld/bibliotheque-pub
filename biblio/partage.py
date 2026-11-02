"""Échanges entre bases : deux besoins distincts, deux opérations distinctes.

importer_ami()   ajoute le catalogue d'un ami à ma base. Ses livres restent les siens, ses données
                 personnelles restent chez lui, et rien de ce qui est à moi ne change.
synchroniser()   réunit deux bases qui sont toutes deux les miennes (deux ordinateurs) : ajouts,
                 modifications et suppressions se propagent, le plus récent l'emporte, champ par champ.

Chacune s'exécute dans une seule transaction : une erreur ne laisse rien à moitié fait, et une
simulation est la même opération, annulée à la fin.

exporter_partage() écrit une petite base avec mes livres (fiches, cotes, réponses des catalogues),
sans mes données personnelles, clés ni réglages ; les lieux en texte, ou masqués ;
mes prêts seulement si je le demande (ils contiennent le nom des emprunteurs).
"""

import sqlite3
from collections import Counter
from pathlib import Path

from . import db, resolver
from .classify import classer_notice
from .i18n import tr
from .services import CHAMPS_PERSONNELS, Erreur, _par_nom, nom_emplacement, proprietaire_local, retirer_exemplaire

CHAMPS_EXEMPLAIRE_PERSONNELS = ("etat", "prix_achat", "date_achat", "provenance", "dedicace", "valeur", "notes")


class PremiereSynchro(Erreur):
    """Cette base n'a jamais été synchronisée avec la mienne : à confirmer."""


def _colonnes(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _inserer(conn, table: str, ligne: dict, ou: str = "INSERT") -> int:
    """Insère un dict en ne gardant que les colonnes que la table connaît."""
    cols = [c for c in _colonnes(conn, table) if c in ligne]
    return conn.execute(f"{ou} INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [ligne[c] for c in cols]).lastrowid


def sauvegarder(conn, suffixe: str) -> Path:
    """Copie cohérente de la base à côté d'elle (ex. biblio-avant-fusion.db)."""
    chemin = db.chemin_base(conn)
    copie = chemin.with_name(f"{chemin.stem}-{suffixe}.db")
    dest = sqlite3.connect(copie)
    conn.backup(dest)
    dest.close()
    return copie


# --- Partage ----------------------------------------------------------------------

def est_fichier_de_partage(chemin: Path | str) -> bool:
    try:
        src = sqlite3.connect(f"{Path(chemin).resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        return src.execute("SELECT 1 FROM meta WHERE cle = 'partage'").fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        src.close()


def _verifier_cible(conn, chemin: Path) -> None:
    """Le fichier créé remplace la cible : seul un ancien fichier de partage peut l'être."""
    if not chemin.exists():
        return
    if chemin.resolve() == db.chemin_base(conn).resolve():
        raise Erreur(tr("« {chemin} » est la base ouverte : choisissez un autre nom de fichier", chemin=chemin))
    if not est_fichier_de_partage(chemin):
        raise Erreur(tr("« {chemin} » existe et n'est pas un fichier de partage : choisissez un autre nom", chemin=chemin))


def _sans_donnees_personnelles(notice: dict) -> dict:
    """Une notice telle qu'un ami peut la recevoir."""
    corrections = {c: v for c, v in db.jload(notice["corrections"], {}).items() if c not in CHAMPS_PERSONNELS}
    return dict(notice, corrections=db.jdump(corrections), **dict.fromkeys(CHAMPS_PERSONNELS))


def exporter_partage(conn, chemin: Path | str, lieux: list[int] | None = None,
                     masquer_lieux: bool = False, avec_prets: bool = False) -> dict:
    """Écrit dans `chemin` une base contenant mes exemplaires (éventuellement de certains lieux)."""
    chemin = Path(chemin)
    _verifier_cible(conn, chemin)
    for f in (chemin, chemin.with_name(chemin.name + "-wal"), chemin.with_name(chemin.name + "-shm")):
        f.unlink(missing_ok=True)
    moi = db.moi_id(conn)
    sql = "SELECT * FROM exemplaires WHERE proprietaire_id = ?"
    params: list = [moi]
    if lieux:
        sql += f" AND lieu_id IN ({', '.join('?' * len(lieux))})"
        params += [int(i) for i in lieux]
    exemplaires = [dict(r) for r in conn.execute(sql + " ORDER BY id", params)]
    notices = sorted({e["notice_id"] for e in exemplaires})

    nb_prets = 0
    dest = db.connect(chemin)
    db.init(dest)                  # fichier recréé : le schéma doit l'être aussi, même déjà vu
    try:
        def personne(pid: int) -> None:
            ligne = dict(conn.execute("SELECT * FROM personnes WHERE id = ?", (pid,)).fetchone())
            _inserer(dest, "personnes", ligne, "INSERT OR IGNORE")

        personne(moi)
        db.ecrire_meta(dest, "moi_uid", conn.execute("SELECT uid FROM personnes WHERE id = ?", (moi,)).fetchone()["uid"])
        for notice_id in notices:
            n = dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
            _inserer(dest, "notices", _sans_donnees_personnelles(n))
            for table in ("classifications", "raw_responses"):
                for r in conn.execute(f"SELECT * FROM {table} WHERE notice_id = ?", (notice_id,)):
                    _inserer(dest, table, dict(r))
        for e in exemplaires:
            texte = None
            if not masquer_lieux and e["lieu_id"]:
                texte = nom_emplacement(conn, e["lieu_id"], e["etagere_id"])
            _inserer(dest, "exemplaires", dict(e, lieu_id=None, etagere_id=None, lieu_texte=texte,
                                               **dict.fromkeys(CHAMPS_EXEMPLAIRE_PERSONNELS)))
            if avec_prets:
                for p in conn.execute("SELECT * FROM prets WHERE exemplaire_id = ? AND preteur_id = ?", (e["id"], moi)):
                    personne(p["emprunteur_id"])
                    _inserer(dest, "prets", dict(p))
                    nb_prets += 1
        db.ecrire_meta(dest, "partage", db.now())
        if avec_prets:
            db.ecrire_meta(dest, "partage_prets", "1")     # l'accord explicite de celui qui partage
        for notice_id in notices:
            db.reindex_notice(dest, notice_id)
        dest.commit()
        dest.execute("PRAGMA journal_mode = DELETE")             # un seul fichier à envoyer
    finally:
        dest.close()
    return {"exemplaires": len(exemplaires), "notices": len(notices),
            "proprietaire": proprietaire_local(conn), "prets": nb_prets}


# --- Lecture d'une autre base -----------------------------------------------------

def ouvrir_source(chemin: Path | str) -> sqlite3.Connection:
    chemin = Path(chemin)
    if not chemin.exists():
        raise Erreur(tr("fichier introuvable : {chemin}", chemin=chemin))
    try:
        src = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        version = src.execute("SELECT valeur FROM meta WHERE cle = 'schema_version'").fetchone()
    except sqlite3.DatabaseError:
        raise Erreur(tr("ce fichier n'est pas une base de la bibliothèque : {chemin}", chemin=chemin))
    if not version or int(version[0]) != db.SCHEMA_VERSION:
        src.close()
        raise Erreur(tr("base d'une autre version du programme (schéma {v}, attendu {attendu}) : mettez à jour les deux",
                        v=version[0] if version else "?", attendu=db.SCHEMA_VERSION))
    return src


def _moi_source(src) -> sqlite3.Row | None:
    uid = src.execute("SELECT valeur FROM meta WHERE cle = 'moi_uid'").fetchone()
    return src.execute("SELECT * FROM personnes WHERE uid = ?", (uid[0],)).fetchone() if uid else None


def _a_meta(src, cle: str) -> bool:
    return src.execute("SELECT 1 FROM meta WHERE cle = ?", (cle,)).fetchone() is not None


def resume_source(chemin: Path | str) -> dict:
    """Ce que contient un fichier, avant de l'importer."""
    src = ouvrir_source(chemin)
    try:
        moi = _moi_source(src)
        return {
            "proprietaire": moi["nom"] if moi else db.NOM_PAR_DEFAUT,
            "uid": moi["uid"] if moi else None,
            "partage": _a_meta(src, "partage"),
            "prets": _a_meta(src, "partage_prets"),
            "exemplaires": src.execute("SELECT count(*) FROM exemplaires").fetchone()[0],
        }
    finally:
        src.close()


def _mes_uids(conn) -> set[str]:
    """Mon identité dans cette base, et celles des autres bases que j'ai déclarées miennes."""
    moi = conn.execute("SELECT uid FROM personnes WHERE id = ?", (db.moi_id(conn),)).fetchone()["uid"]
    return {moi, *db.jload(db.get_meta(conn, "moi_autres_bases"), [])}


def est_ma_base(conn, chemin: Path | str) -> bool:
    return resume_source(chemin)["uid"] in _mes_uids(conn)


def _personne(conn, p, mes_uids: set[str]) -> int:
    """La personne locale d'après celle d'une autre base : par son identité, sinon par son nom."""
    if p["uid"] in mes_uids or db.norm(p["nom"]).strip() == db.norm(proprietaire_local(conn)).strip():
        return db.moi_id(conn)
    row = conn.execute("SELECT id FROM personnes WHERE uid = ?", (p["uid"],)).fetchone() or conn.execute(
        "SELECT id FROM personnes WHERE cle = ?", (p["cle"],)).fetchone()
    return row["id"] if row else _inserer(conn, "personnes", dict(p, id=None))


def _executer(conn, fonction, simulation: bool) -> dict:
    """Une seule transaction : tout est appliqué, ou rien."""
    conn.commit()
    try:
        rapport = fonction()
    except BaseException:
        conn.rollback()
        raise
    if simulation:
        conn.rollback()
    else:
        conn.commit()
    return dict(rapport)


# --- Notices ----------------------------------------------------------------------

def _notice_locale(conn, n: sqlite3.Row, uids_exemplaires: list[str]) -> int | None:
    """La même notice chez moi : par ISBN ; sans ISBN, par identité, exemplaire, titre et auteur."""
    if n["isbn13"]:
        row = conn.execute("SELECT id FROM notices WHERE isbn13 = ?", (n["isbn13"],)).fetchone()
        return row["id"] if row else None
    row = conn.execute("SELECT id FROM notices WHERE uid = ?", (n["uid"],)).fetchone()
    if row:
        return row["id"]
    for uid in uids_exemplaires:
        row = conn.execute("SELECT notice_id FROM exemplaires WHERE uid = ?", (uid,)).fetchone()
        if row:
            return row["notice_id"]
    cle = (db.norm(n["titre"]).strip(), db.norm(n["auteur_tri"]).strip())
    if cle[0]:
        for r in conn.execute("SELECT id, titre, auteur_tri FROM notices WHERE isbn13 IS NULL"):
            if (db.norm(r["titre"]).strip(), db.norm(r["auteur_tri"]).strip()) == cle:
                return r["id"]
    return None


def _fusionner_notice(conn, src, n: sqlite3.Row, uids_exemplaires: list[str], synchro: bool, rapport) -> int:
    """Reprend une notice. Pour un ami : ses corrections là où je n'ai pas fait les miennes, rien de personnel.
    Pour mes bases : la correction la plus récente, champ par champ, données personnelles comprises."""
    theirs = db.notice_dict(n)
    raws = [dict(r) for r in src.execute("SELECT * FROM raw_responses WHERE notice_id = ?", (n["id"],))]
    classes = [dict(r) for r in src.execute("SELECT * FROM classifications WHERE notice_id = ?", (n["id"],))]
    local = _notice_locale(conn, n, uids_exemplaires)

    if local is None:
        ligne = dict(n) if synchro else _sans_donnees_personnelles(dict(n))
        ligne.pop("id")
        if not synchro:
            ligne["corrections"] = db.jdump({c: dict(v, ami=True) for c, v in db.jload(ligne["corrections"], {}).items()})
        if conn.execute("SELECT 1 FROM notices WHERE uid = ?", (ligne["uid"],)).fetchone():
            ligne["uid"] = db.nouvel_uid()
        local = _inserer(conn, "notices", ligne)
        for r in raws:
            _inserer(conn, "raw_responses", dict(r, notice_id=local))
        for c in classes:
            _inserer(conn, "classifications", dict(c, notice_id=local))
        classer_notice(conn, local)
        db.reindex_notice(conn, local)
        rapport["notices_ajoutees"] += 1
        return local

    change = False
    for r in raws:
        mien = conn.execute("SELECT statut FROM raw_responses WHERE notice_id = ? AND source = ?",
                            (local, r["source"])).fetchone()
        if mien is None or (r["statut"] == "ok" and mien["statut"] != "ok"):
            _inserer(conn, "raw_responses", dict(r, notice_id=local), "INSERT OR REPLACE")
            change = True

    mine = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (local,)).fetchone())
    corrections = mine["corrections"]
    adoptes = {}
    for champ, v in theirs["corrections"].items():
        if not synchro and champ in CHAMPS_PERSONNELS:
            continue
        mienne = corrections.get(champ)
        if mienne and mienne["le"] >= v["le"]:
            continue
        if mienne and not synchro and not mienne.get("ami"):
            continue                                 # une correction à moi n'est jamais écrasée par un ami
        corrections[champ] = dict(v, ami=True) if not synchro else v
        change = True
        if champ.startswith("cote:"):
            systeme = champ[5:]
            conn.execute("DELETE FROM classifications WHERE notice_id = ? AND systeme = ?", (local, systeme))
            for c in classes:
                if v["manuel"] and c["systeme"] == systeme and c["origine"] == "manuel":
                    _inserer(conn, "classifications", dict(c, notice_id=local))
        elif v["manuel"] or champ in CHAMPS_PERSONNELS:
            adoptes[champ] = n[champ]
            if champ == "auteurs":
                adoptes["auteur_tri"] = n["auteur_tri"]
    if change:
        adoptes["corrections"] = db.jdump(corrections)
        sets = ", ".join(f"{k} = ?" for k in adoptes)
        conn.execute(f"UPDATE notices SET {sets} WHERE id = ?", [*adoptes.values(), local])
        resolver.rebuild(conn, local, valider=False)
        rapport["notices_completees"] += 1
    return local


def _fusionner_notices(conn, src, exemplaires: list[dict], synchro: bool, rapport) -> dict[int, int]:
    """Notices des exemplaires retenus : numéro dans la source -> numéro local."""
    correspondance = {}
    for notice_id in sorted({e["notice_id"] for e in exemplaires}):
        n = src.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
        uids = [e["uid"] for e in exemplaires if e["notice_id"] == notice_id]
        correspondance[notice_id] = _fusionner_notice(conn, src, n, uids, synchro, rapport)
    return correspondance


# --- Le catalogue d'un ami --------------------------------------------------------

def _ami(conn, moi_src: sqlite3.Row | None, comme: str | None) -> int:
    """La personne locale qui correspond au propriétaire du fichier ; `comme` choisit son nom chez moi."""
    if moi_src is None:
        raise Erreur(tr("ce fichier ne contient aucun livre"))
    if moi_src["uid"] in _mes_uids(conn):
        raise Erreur(tr("ce fichier vient de votre propre base : utilisez biblio sync"))
    nom = (comme or "").strip() or moi_src["nom"]
    cle = db.norm(nom).strip()
    if cle == db.norm(proprietaire_local(conn)).strip():
        raise Erreur(tr("ce fichier porte le même nom que vous (« {nom} ») : indiquez sous quel nom ajouter ses livres (--as)", nom=nom))
    connu = conn.execute("SELECT id, nom FROM personnes WHERE uid = ?", (moi_src["uid"],)).fetchone()
    homonyme = conn.execute("SELECT id FROM personnes WHERE cle = ?", (cle,)).fetchone()
    if connu:
        if comme and connu["nom"] != nom:
            if homonyme and homonyme["id"] != connu["id"]:
                raise Erreur(tr("« {nom} » existe déjà : choisissez un autre nom", nom=nom))
            conn.execute("UPDATE personnes SET nom = ?, cle = ?, maj_le = ? WHERE id = ?",
                         (nom, cle, db.horodatage(), connu["id"]))
        return connu["id"]
    if homonyme:                                       # je lui avais donné ou prêté un livre : c'est lui
        conn.execute("UPDATE personnes SET uid = ? WHERE id = ?", (moi_src["uid"], homonyme["id"]))
        return homonyme["id"]
    return _inserer(conn, "personnes", dict(uid=moi_src["uid"], nom=nom, cle=cle, maj_le=moi_src["maj_le"]))


def importer_ami(conn, chemin: Path | str, comme: str | None = None, remplacer: bool = False,
                 simulation: bool = False) -> dict:
    """Ajoute à ma base le catalogue d'un ami. Renvoie un rapport (compteurs).

    comme       nom à donner à l'ami chez moi ; il est ensuite reconnu à son identité, même s'il change de nom
    remplacer   retire ses exemplaires et ses prêts qui ne sont plus dans le fichier
    simulation  calcule le rapport sans rien garder
    """
    src = ouvrir_source(chemin)
    try:
        return _executer(conn, lambda: _importer_ami(conn, src, comme, remplacer), simulation)
    finally:
        src.close()


def _importer_ami(conn, src, comme, remplacer) -> Counter:
    moi = db.moi_id(conn)
    moi_src = _moi_source(src)
    ami = _ami(conn, moi_src, comme)
    mes_uids = _mes_uids(conn)
    rapport = Counter()
    rapport["source"] = conn.execute("SELECT nom FROM personnes WHERE id = ?", (ami,)).fetchone()["nom"]
    prets_partages = _a_meta(src, "partage_prets")   # sa base complète, reçue autrement, n'en dit rien

    exemplaires = []
    for e in src.execute("SELECT * FROM exemplaires ORDER BY id"):
        if e["proprietaire_id"] == moi_src["id"]:
            exemplaires.append(dict(e))
        else:                                        # les miens, ou ceux de tiers : pas son catalogue
            rapport["exemplaires_ignores"] += 1
    notices = _fusionner_notices(conn, src, exemplaires, False, rapport)

    prets_du_fichier = set()
    for e in exemplaires:
        ex_id = _importer_exemplaire(conn, src, e, notices[e["notice_id"]], ami, moi, rapport)
        if ex_id is None:
            continue
        if prets_partages:
            for p in src.execute("SELECT * FROM prets WHERE exemplaire_id = ?", (e["id"],)):
                prets_du_fichier.add(p["uid"])
                _reprendre_pret(conn, p, ex_id, ami, _personne_source(conn, src, p["emprunteur_id"], mes_uids), rapport)

    if remplacer:
        presents = {e["uid"] for e in exemplaires}
        for r in conn.execute("SELECT id, uid FROM exemplaires WHERE proprietaire_id = ?", (ami,)).fetchall():
            if r["uid"] not in presents:
                retirer_exemplaire(conn, r["id"])
                rapport["exemplaires_retires"] += 1
        for r in conn.execute("SELECT id, uid FROM prets WHERE preteur_id = ?", (ami,)).fetchall():
            if r["uid"] not in prets_du_fichier:         # il ne les partage plus : on les oublie
                conn.execute("DELETE FROM prets WHERE id = ?", (r["id"],))
                rapport["prets_retires"] += 1
    return rapport


def _personne_source(conn, src, personne_id: int, mes_uids: set[str]) -> int:
    return _personne(conn, src.execute("SELECT * FROM personnes WHERE id = ?", (personne_id,)).fetchone(), mes_uids)


def _lieu_en_texte(src, e: dict) -> str | None:
    """Son lieu tel qu'il l'a nommé : déjà en texte dans un fichier de partage."""
    if e["lieu_texte"] or not e["lieu_id"]:
        return e["lieu_texte"]
    lieu = src.execute("SELECT nom FROM lieux WHERE id = ?", (e["lieu_id"],)).fetchone()
    etagere = src.execute("SELECT nom FROM etageres WHERE id = ?", (e["etagere_id"],)).fetchone()
    return f"{lieu['nom']} › {etagere['nom']}" if lieu and etagere else (lieu["nom"] if lieu else None)


def _importer_exemplaire(conn, src, e: dict, notice_id: int, ami: int, moi: int, rapport) -> int | None:
    local = conn.execute("SELECT * FROM exemplaires WHERE uid = ?", (e["uid"],)).fetchone()
    if local and local["proprietaire_id"] == moi:    # il me l'a donné : le fichier d'un ami ne touche pas à mes livres
        rapport["exemplaires_ignores"] += 1
        return None
    texte = _lieu_en_texte(src, e)
    if local is None:
        conn.execute("DELETE FROM suppressions WHERE uid = ?", (e["uid"],))
        rapport["exemplaires_ajoutes"] += 1
        return _inserer(conn, "exemplaires", dict(uid=e["uid"], notice_id=notice_id, proprietaire_id=ami, lieu_texte=texte,
                                                  ajoute_le=e["ajoute_le"], maj_le=e["maj_le"]))
    if e["maj_le"] > local["maj_le"]:
        conn.execute("UPDATE exemplaires SET proprietaire_id = ?, lieu_texte = ?, maj_le = ? WHERE id = ?",
                     (ami, texte, e["maj_le"], local["id"]))
        rapport["exemplaires_mis_a_jour"] += 1
    return local["id"]


def _reprendre_pret(conn, p, ex_id: int, preteur: int, emprunteur: int, rapport) -> None:
    local = conn.execute("SELECT * FROM prets WHERE uid = ?", (p["uid"],)).fetchone()
    if local is None:
        _inserer(conn, "prets", dict(uid=p["uid"], exemplaire_id=ex_id, preteur_id=preteur, emprunteur_id=emprunteur,
                                     date_pret=p["date_pret"], date_retour=p["date_retour"], maj_le=p["maj_le"]))
        rapport["prets_ajoutes"] += 1
    elif p["maj_le"] > local["maj_le"]:
        conn.execute("UPDATE prets SET preteur_id = ?, emprunteur_id = ?, date_retour = ?, maj_le = ? WHERE id = ?",
                     (preteur, emprunteur, p["date_retour"], p["maj_le"], local["id"]))
        rapport["prets_ajoutes"] += 1


# --- Mes propres bases ------------------------------------------------------------

def synchroniser(conn, chemin: Path | str, appairer: bool = False, simulation: bool = False) -> dict:
    """Reprend dans ma base ce qui a changé dans une autre de mes bases. Lancer dans les deux sens.

    appairer    accepte une base jamais synchronisée avec celle-ci : je déclare qu'elle est à moi
    simulation  calcule le rapport sans rien garder
    """
    src = ouvrir_source(chemin)
    try:
        if _a_meta(src, "partage"):
            raise Erreur(tr("c'est un fichier de partage : pour le catalogue d'un ami, utilisez biblio merge"))
        moi_src = _moi_source(src)
        if moi_src is None:
            raise Erreur(tr("ce fichier ne contient aucun livre"))
        if moi_src["uid"] not in _mes_uids(conn) and not appairer:
            raise PremiereSynchro(tr("« {nom} » n'a jamais été synchronisée avec votre base : confirmez qu'elle est bien à vous",
                                     nom=moi_src["nom"]))
        return _executer(conn, lambda: _synchroniser(conn, src, moi_src), simulation)
    finally:
        src.close()


def _plus_recente_suppression(conn, uid: str) -> str | None:
    row = conn.execute("SELECT le FROM suppressions WHERE uid = ?", (uid,)).fetchone()
    return row["le"] if row else None


def _appliquer_suppressions(conn, src, rapport) -> None:
    """Ce qui a été supprimé là-bas l'est ici, sauf si je l'ai modifié depuis."""
    for s in src.execute("SELECT * FROM suppressions"):
        table = {"exemplaire": "exemplaires", "lieu": "lieux", "etagere": "etageres"}[s["genre"]]
        row = conn.execute(f"SELECT id, maj_le FROM {table} WHERE uid = ?", (s["uid"],)).fetchone()
        if row and row["maj_le"] > s["le"]:
            continue
        if row and s["genre"] == "exemplaire":
            retirer_exemplaire(conn, row["id"])
            rapport["exemplaires_retires"] += 1
        elif row:
            colonne = "lieu_id" if s["genre"] == "lieu" else "etagere_id"
            effacer = "lieu_id = NULL, etagere_id = NULL" if s["genre"] == "lieu" else "etagere_id = NULL"
            conn.execute(f"UPDATE exemplaires SET {effacer}, maj_le = ? WHERE {colonne} = ?", (s["le"], row["id"]))
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))
            rapport["lieux_retires"] += 1
        if (_plus_recente_suppression(conn, s["uid"]) or "") < s["le"]:
            conn.execute("INSERT OR REPLACE INTO suppressions(uid, genre, le) VALUES (?, ?, ?)",
                         (s["uid"], s["genre"], s["le"]))


def _synchroniser_lieu(conn, table: str, ligne: sqlite3.Row, candidats, valeurs: dict, rapport) -> int | None:
    """Un lieu ou une étagère : même identité, sinon même nom. Renvoie son numéro local (None : supprimé)."""
    suppression = _plus_recente_suppression(conn, ligne["uid"])
    if suppression and suppression >= ligne["maj_le"]:
        return None
    local = conn.execute(f"SELECT * FROM {table} WHERE uid = ?", (ligne["uid"],)).fetchone()
    if local is None:
        meme_nom = _par_nom(candidats(), ligne["nom"])
        if meme_nom is None:
            conn.execute("DELETE FROM suppressions WHERE uid = ?", (ligne["uid"],))
            rapport["lieux_ajoutes"] += 1
            return _inserer(conn, table, dict(ligne, **valeurs, id=None))
        uid = conn.execute(f"SELECT uid FROM {table} WHERE id = ?", (meme_nom,)).fetchone()["uid"]
        # Deux noms identiques créés chacun de son côté : les deux bases gardent le même identifiant
        conn.execute(f"UPDATE {table} SET uid = ? WHERE id = ?", (min(uid, ligne["uid"]), meme_nom))
        return meme_nom
    if ligne["maj_le"] > local["maj_le"]:
        autre = _par_nom(candidats(), ligne["nom"])
        if autre in (None, local["id"]):             # sinon le nom est pris : on garde le mien
            colonnes = {"nom": ligne["nom"], "ordre": ligne["ordre"], "maj_le": ligne["maj_le"], **valeurs}
            if table == "lieux":
                colonnes["description"] = ligne["description"]
            sets = ", ".join(f"{k} = ?" for k in colonnes)
            conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*colonnes.values(), local["id"]])
            rapport["lieux_mis_a_jour"] += 1
    return local["id"]


def _synchroniser_personnes(conn, src, moi_src, mes_uids: set[str]) -> dict[int, int]:
    correspondance = {}
    moi = db.moi_id(conn)
    for p in src.execute("SELECT * FROM personnes"):
        local_id = moi if p["uid"] == moi_src["uid"] else _personne(conn, p, mes_uids)
        correspondance[p["id"]] = local_id
        local = conn.execute("SELECT * FROM personnes WHERE id = ?", (local_id,)).fetchone()
        if p["uid"] in (local["uid"], moi_src["uid"]) and p["maj_le"] > local["maj_le"] and p["nom"] != local["nom"]:
            pris = conn.execute("SELECT 1 FROM personnes WHERE cle = ? AND id != ?", (p["cle"], local_id)).fetchone()
            if not pris:                                 # un changement de nom fait sur l'autre machine
                conn.execute("UPDATE personnes SET nom = ?, cle = ?, maj_le = ? WHERE id = ?",
                             (p["nom"], p["cle"], p["maj_le"], local_id))
    return correspondance


def _synchroniser(conn, src, moi_src) -> Counter:
    rapport = Counter()
    mes_uids = _mes_uids(conn)
    rapport["source"] = moi_src["nom"]
    _appliquer_suppressions(conn, src, rapport)
    personnes = _synchroniser_personnes(conn, src, moi_src, mes_uids)

    lieux = {}
    for l in src.execute("SELECT * FROM lieux ORDER BY id"):
        lieux[l["id"]] = _synchroniser_lieu(conn, "lieux", l, lambda: conn.execute("SELECT id, nom FROM lieux"), {}, rapport)
    etageres = {}
    for e in src.execute("SELECT * FROM etageres ORDER BY id"):
        lieu_id = lieux.get(e["lieu_id"])
        if lieu_id:
            etageres[e["id"]] = _synchroniser_lieu(
                conn, "etageres", e, lambda: conn.execute("SELECT id, nom FROM etageres WHERE lieu_id = ?", (lieu_id,)),
                {"lieu_id": lieu_id}, rapport)

    exemplaires = []
    for e in src.execute("SELECT * FROM exemplaires ORDER BY id"):
        suppression = _plus_recente_suppression(conn, e["uid"])
        if suppression and suppression >= e["maj_le"]:
            continue                                     # retiré ici après sa dernière modification là-bas
        exemplaires.append(dict(e))
    notices = _fusionner_notices(conn, src, exemplaires, True, rapport)

    ids = {}
    for e in exemplaires:
        valeurs = {c: e[c] for c in CHAMPS_EXEMPLAIRE_PERSONNELS}
        valeurs.update(proprietaire_id=personnes[e["proprietaire_id"]], lieu_id=lieux.get(e["lieu_id"]),
                       etagere_id=etageres.get(e["etagere_id"]), lieu_texte=e["lieu_texte"], maj_le=e["maj_le"])
        local = conn.execute("SELECT id, maj_le FROM exemplaires WHERE uid = ?", (e["uid"],)).fetchone()
        if local is None:
            conn.execute("DELETE FROM suppressions WHERE uid = ?", (e["uid"],))
            ids[e["id"]] = _inserer(conn, "exemplaires", dict(valeurs, uid=e["uid"], notice_id=notices[e["notice_id"]],
                                                              ajoute_le=e["ajoute_le"]))
            rapport["exemplaires_ajoutes"] += 1
        else:
            ids[e["id"]] = local["id"]
            if e["maj_le"] > local["maj_le"]:
                sets = ", ".join(f"{k} = ?" for k in valeurs)
                conn.execute(f"UPDATE exemplaires SET {sets} WHERE id = ?", [*valeurs.values(), local["id"]])
                rapport["exemplaires_mis_a_jour"] += 1
        db.reindex_notice(conn, notices[e["notice_id"]])

    for p in src.execute("SELECT * FROM prets"):
        if p["exemplaire_id"] in ids:
            _reprendre_pret(conn, p, ids[p["exemplaire_id"]], personnes[p["preteur_id"]],
                            personnes[p["emprunteur_id"]], rapport)
    for m in src.execute("SELECT * FROM mouvements"):
        if m["exemplaire_id"] in ids and not conn.execute("SELECT 1 FROM mouvements WHERE uid = ?", (m["uid"],)).fetchone():
            _inserer(conn, "mouvements", dict(uid=m["uid"], exemplaire_id=ids[m["exemplaire_id"]], date=m["date"],
                                              de_lieu=lieux.get(m["de_lieu"]), de_etagere=etageres.get(m["de_etagere"]),
                                              vers_lieu=lieux.get(m["vers_lieu"]), vers_etagere=etageres.get(m["vers_etagere"])))

    if moi_src["uid"] not in mes_uids:                   # cette base est désormais reconnue comme mienne
        autres = db.jload(db.get_meta(conn, "moi_autres_bases"), [])
        db.ecrire_meta(conn, "moi_autres_bases", db.jdump([*autres, moi_src["uid"]]))
    return rapport
