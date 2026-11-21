"""Base SQLite : schéma, connexion, petits utilitaires.

Trois identités stables d'une base à l'autre, jamais déduites d'un nom :
  personnes.uid    une personne (moi, un ami, un emprunteur) ; son nom peut changer
  notices.uid      un livre, un disque ou un film décrit ; l'ISBN ou l'EAN n'en est qu'un champ, parfois absent
  exemplaires.uid  un objet physique
"""

import json
import logging
import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_DIR / "data" / "biblio.db"

SCHEMA_VERSION = 6
NOM_PAR_DEFAUT = "Moi"
# Auteur d'un scan fait avec la clé du QR code : n'importe qui peut l'utiliser. Un compte ne peut pas porter ce nom.
PAR_TELEPHONE = "*telephone"

log = logging.getLogger("biblio.db")

# Un passage sous la douchette. Par son nom en texte : `comptes` reste propre à chaque base.
TABLE_SCANS = """CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY,
    uid           TEXT NOT NULL UNIQUE,
    exemplaire_id INTEGER NOT NULL REFERENCES exemplaires(id) ON DELETE CASCADE,
    par           TEXT,
    le            TEXT NOT NULL,
    mode          TEXT NOT NULL                    -- ajout | deplacement | inventaire | ou
)"""
INDEX_SCANS = "CREATE INDEX IF NOT EXISTS scans_par ON scans(par)"
INDEX_SCANS_EXEMPLAIRE = "CREATE INDEX IF NOT EXISTS scans_exemplaire ON scans(exemplaire_id)"

SCHEMA = f"""{TABLE_SCANS};
{INDEX_SCANS};
{INDEX_SCANS_EXEMPLAIRE};
""" + """
CREATE TABLE IF NOT EXISTS meta (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);

-- Une personne : propriétaire, prêteur ou emprunteur. `cle` (nom sans casse ni accents) évite les doublons.
CREATE TABLE IF NOT EXISTS personnes (
    id     INTEGER PRIMARY KEY,
    uid    TEXT NOT NULL UNIQUE,
    nom    TEXT NOT NULL,
    cle    TEXT NOT NULL UNIQUE,
    maj_le TEXT NOT NULL
);

-- La notice décrit un livre, un disque ou un film. isbn13 est vide pour les livres anciens ou autoédités,
-- et pour les autres supports, désignés par leur ean. Disques et films reprennent les colonnes des livres :
-- auteurs = artistes ou réalisateur, editeur = label ou studio, sujets = genres.
CREATE TABLE IF NOT EXISTS notices (
    id               INTEGER PRIMARY KEY,
    uid              TEXT NOT NULL UNIQUE,
    isbn13           TEXT UNIQUE,
    support          TEXT NOT NULL DEFAULT 'livre',  -- livre | cd | vinyle | cassette | dvd | bluray | inconnu
    ean              TEXT,                         -- code-barres hors ISBN, sur 13 chiffres
    ref_catalogue    TEXT,                         -- numéro de catalogue du label
    pistes           TEXT NOT NULL DEFAULT '[]',   -- JSON : [{"titre", "duree" (s), "disque"}, ...]
    duree            INTEGER,                      -- minutes
    nb_disques       INTEGER,
    titre            TEXT,
    sous_titre       TEXT,
    auteurs          TEXT NOT NULL DEFAULT '[]',   -- JSON : ["Prénom Nom", ...]
    auteur_tri       TEXT,                         -- "NOM Prénom" du premier auteur
    editeur          TEXT,
    collection       TEXT,
    annee            INTEGER,
    pages            INTEGER,
    langue           TEXT,
    langue_originale TEXT,
    resume           TEXT,
    sujets           TEXT NOT NULL DEFAULT '[]',   -- JSON
    forme            TEXT,                         -- fiction, poesie, theatre, essai, documentaire...
    public           TEXT,                         -- jeunesse, ado, adulte, general
    couverture_url   TEXT,
    classes_source   TEXT NOT NULL DEFAULT '{}',   -- JSON : indices fournis par les catalogues
    sources          TEXT NOT NULL DEFAULT '[]',   -- JSON : catalogues ayant répondu
    statut           TEXT NOT NULL DEFAULT 'en_attente', -- en_attente | trouve | introuvable | erreur | manuel
    -- JSON : {champ: {"le": date, "manuel": bool}} ; "manuel" protège le champ des catalogues.
    -- La date départage deux bases, champ par champ ; « cote:dewey » suit une cote fixée à la main.
    corrections      TEXT NOT NULL DEFAULT '{}',
    -- Personnel : jamais dans un fichier de partage
    notes            TEXT,
    lecture          TEXT,                         -- a_lire | en_cours | lu | abandonne
    lecture_debut    TEXT,
    lecture_fin      TEXT,
    etoiles          INTEGER,                      -- de 1 à 5
    cree_le          TEXT NOT NULL,
    maj_le           TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS notices_ean ON notices(ean);
CREATE INDEX IF NOT EXISTS notices_statut ON notices(statut);
CREATE INDEX IF NOT EXISTS notices_lecture ON notices(lecture);

-- Réponses brutes des catalogues : on peut relire ces données pour un nouveau système de classement.
CREATE TABLE IF NOT EXISTS raw_responses (
    notice_id  INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,
    statut     TEXT NOT NULL,          -- ok | absent | erreur
    payload    TEXT,
    recu_le    TEXT NOT NULL,
    PRIMARY KEY (notice_id, source)
);

-- Une cote par système de classement et par notice.
CREATE TABLE IF NOT EXISTS classifications (
    notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    systeme   TEXT NOT NULL,
    code      TEXT,
    libelle   TEXT,
    cote      TEXT,
    tri       TEXT,                    -- clé de tri propre au système
    origine   TEXT NOT NULL,           -- source | deduit | manuel
    PRIMARY KEY (notice_id, systeme)
);

CREATE TABLE IF NOT EXISTS lieux (
    id          INTEGER PRIMARY KEY,
    uid         TEXT NOT NULL UNIQUE,
    nom         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    ordre       INTEGER NOT NULL DEFAULT 0,
    etiquette   TEXT,                              -- 9 chiffres : le code-barres imprimé, le même dans toutes mes bases
    maj_le      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS lieux_etiquette ON lieux(etiquette);

CREATE TABLE IF NOT EXISTS etageres (
    id      INTEGER PRIMARY KEY,
    uid     TEXT NOT NULL UNIQUE,
    lieu_id INTEGER NOT NULL REFERENCES lieux(id) ON DELETE CASCADE,
    nom     TEXT NOT NULL COLLATE NOCASE,
    ordre   INTEGER NOT NULL DEFAULT 0,
    etiquette TEXT,
    maj_le  TEXT NOT NULL,
    UNIQUE (lieu_id, nom)
);
CREATE UNIQUE INDEX IF NOT EXISTS etageres_etiquette ON etageres(etiquette);

CREATE TABLE IF NOT EXISTS rangees (
    id         INTEGER PRIMARY KEY,
    uid        TEXT NOT NULL UNIQUE,
    etagere_id INTEGER NOT NULL REFERENCES etageres(id) ON DELETE CASCADE,
    nom        TEXT NOT NULL COLLATE NOCASE,
    ordre      INTEGER NOT NULL DEFAULT 0,
    etiquette  TEXT,
    maj_le     TEXT NOT NULL,
    UNIQUE (etagere_id, nom)
);
CREATE UNIQUE INDEX IF NOT EXISTS rangees_etiquette ON rangees(etiquette);

-- L'exemplaire est l'objet physique, rangé quelque part, et appartient à quelqu'un.
-- lieu_texte : lieu d'un livre qui n'est pas chez moi (« Salon › É2 » chez Victor).
CREATE TABLE IF NOT EXISTS exemplaires (
    id              INTEGER PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,
    notice_id       INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    proprietaire_id INTEGER NOT NULL REFERENCES personnes(id),
    lieu_id         INTEGER REFERENCES lieux(id) ON DELETE SET NULL,
    etagere_id      INTEGER REFERENCES etageres(id) ON DELETE SET NULL,
    rangee_id       INTEGER REFERENCES rangees(id) ON DELETE SET NULL,
    lieu_texte      TEXT,
    -- Personnel : jamais dans un fichier de partage
    etat            TEXT,                          -- neuf | tres_bon | bon | moyen | abime
    prix_achat      REAL,
    date_achat      TEXT,
    provenance      TEXT,
    dedicace        TEXT,
    valeur          REAL,
    notes           TEXT,
    ajoute_le       TEXT NOT NULL,
    maj_le          TEXT NOT NULL,
    -- Qui a scanné : jamais dans un fichier de partage. Un scan ne change pas maj_le.
    ajoute_par       TEXT,
    dernier_scan_le  TEXT,
    dernier_scan_par TEXT
);
CREATE INDEX IF NOT EXISTS exemplaires_notice ON exemplaires(notice_id);
CREATE INDEX IF NOT EXISTS exemplaires_lieu ON exemplaires(lieu_id, etagere_id);
CREATE INDEX IF NOT EXISTS exemplaires_proprio ON exemplaires(proprietaire_id);

CREATE TABLE IF NOT EXISTS mouvements (
    id            INTEGER PRIMARY KEY,
    uid           TEXT NOT NULL UNIQUE,
    exemplaire_id INTEGER NOT NULL REFERENCES exemplaires(id) ON DELETE CASCADE,
    de_lieu       INTEGER,
    de_etagere    INTEGER,
    de_rangee     INTEGER,
    vers_lieu     INTEGER,
    vers_etagere  INTEGER,
    vers_rangee   INTEGER,
    date          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventaires (
    id         INTEGER PRIMARY KEY,
    lieu_id    INTEGER NOT NULL REFERENCES lieux(id) ON DELETE CASCADE,
    etagere_id INTEGER REFERENCES etageres(id) ON DELETE CASCADE,
    rangee_id  INTEGER REFERENCES rangees(id) ON DELETE CASCADE,
    debut      TEXT NOT NULL,
    fin        TEXT
);

-- code : ISBN-13, EAN ou référence (L12). Un scan peut porter sur un livre absent de la base.
CREATE TABLE IF NOT EXISTS inventaire_scans (
    inventaire_id INTEGER NOT NULL REFERENCES inventaires(id) ON DELETE CASCADE,
    code          TEXT NOT NULL,
    scanne_le     TEXT NOT NULL,
    nb            INTEGER NOT NULL DEFAULT 1,      -- nombre d'exemplaires scannés
    PRIMARY KEY (inventaire_id, code)
);

CREATE TABLE IF NOT EXISTS prets (
    id            INTEGER PRIMARY KEY,
    uid           TEXT NOT NULL UNIQUE,
    exemplaire_id INTEGER NOT NULL REFERENCES exemplaires(id) ON DELETE CASCADE,
    preteur_id    INTEGER NOT NULL REFERENCES personnes(id),   -- moi, ou un ami qui a partagé ses prêts
    emprunteur_id INTEGER NOT NULL REFERENCES personnes(id),
    date_pret     TEXT NOT NULL,
    date_retour   TEXT,
    maj_le        TEXT NOT NULL
);

-- Ce qui a été supprimé : la synchronisation ne doit pas le faire revenir.
CREATE TABLE IF NOT EXISTS suppressions (
    uid   TEXT PRIMARY KEY,
    genre TEXT NOT NULL,                           -- exemplaire | lieu | etagere | rangee
    le    TEXT NOT NULL
);

-- Comptes et suivi : propres à cette base, jamais dans un fichier de partage ni une synchronisation.
CREATE TABLE IF NOT EXISTS comptes (
    id                 INTEGER PRIMARY KEY,
    identifiant        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nom                TEXT,
    role               TEXT NOT NULL,                  -- lecteur | contributeur | bibliothecaire | admin
    code_hash          TEXT NOT NULL,
    actif              INTEGER NOT NULL DEFAULT 1,
    cree_le            TEXT NOT NULL,
    derniere_connexion TEXT
);

-- Un appareil connecté. Seule l'empreinte du jeton est gardée : lire la base ne permet pas d'entrer.
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    jeton_hash TEXT NOT NULL UNIQUE,
    compte_id  INTEGER NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
    appareil   TEXT,
    ip         TEXT,
    souvenir   INTEGER NOT NULL DEFAULT 1,
    cree_le    TEXT NOT NULL,
    vu_le      TEXT NOT NULL,
    expire_le  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_compte ON sessions(compte_id);

CREATE TABLE IF NOT EXISTS tentatives (
    identifiant   TEXT NOT NULL,
    ip            TEXT NOT NULL,
    nb            INTEGER NOT NULL DEFAULT 0,
    bloque_jusqua TEXT,
    derniere      TEXT,
    PRIMARY KEY (identifiant, ip)
);

CREATE TABLE IF NOT EXISTS journal (
    id     INTEGER PRIMARY KEY,
    le     TEXT NOT NULL,
    acteur TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    ip     TEXT
);

-- État des catalogues, tel que vu par le dernier test de la page d'administration
CREATE TABLE IF NOT EXISTS sources_etat (
    source   TEXT PRIMARY KEY,
    actif    INTEGER NOT NULL DEFAULT 1,
    etat     TEXT,                                     -- ok | lent | panne | sans_cle | cle_refusee
    latence  INTEGER,                                  -- millisecondes
    message  TEXT,
    teste_le TEXT
);

CREATE VIEW IF NOT EXISTS exemplaires_v AS
    SELECT e.*, p.nom AS proprietaire FROM exemplaires e JOIN personnes p ON p.id = e.proprietaire_id;
CREATE VIEW IF NOT EXISTS prets_v AS
    SELECT pr.*, a.nom AS preteur, b.nom AS emprunteur FROM prets pr
    JOIN personnes a ON a.id = pr.preteur_id JOIN personnes b ON b.id = pr.emprunteur_id;

CREATE VIRTUAL TABLE IF NOT EXISTS notices_fts USING fts5(
    titre, auteurs, editeur, collection, sujets, resume, notes,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


class AutreVersion(Exception):
    """La base a été créée par une autre version du programme : elle n'est pas ouverte, donc pas modifiée."""


def db_path() -> Path:
    return Path(os.environ.get("BIBLIO_DB", DEFAULT_DB))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def horodatage() -> str:
    """Date d'une modification, précise : départage deux bases à la synchronisation."""
    return datetime.now().isoformat(timespec="microseconds")


def nouvel_uid() -> str:
    return uuid.uuid4().hex


def norm(text: str | None) -> str:
    """Sans casse ni accents."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


_initialisees: set[str] = set()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        if str(path) not in _initialisees:
            init(conn)
            _initialisees.add(str(path))
    except AutreVersion:
        conn.close()
        raise
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def version_schema(conn: sqlite3.Connection) -> int | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta'").fetchone():
        return None
    row = conn.execute("SELECT valeur FROM meta WHERE cle = 'schema_version'").fetchone()
    return int(row[0]) if row else None


def init(conn: sqlite3.Connection) -> None:
    version = version_schema(conn)
    if version is not None and version != SCHEMA_VERSION:
        raise AutreVersion(str(chemin_base(conn)))
    conn.executescript(SCHEMA)
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    _recalculer_les_cotes_si_besoin(conn)


def _recalculer_les_cotes_si_besoin(conn: sqlite3.Connection) -> None:
    """Une fois après un changement de la clé de tri ; sans réseau, les cotes manuelles restent."""
    from .classify import VERSION_COTES, reclasser_tout

    if get_meta(conn, "version_cotes") == str(VERSION_COTES):
        return
    try:
        reclasser_tout(conn)
    except Exception:                      # règle invalide, par exemple : la base reste utilisable
        conn.rollback()
        log.exception("recalcul des cotes impossible : nouvel essai au prochain lancement")
        return
    set_meta(conn, "version_cotes", str(VERSION_COTES))


def chemin_base(conn: sqlite3.Connection) -> Path:
    return Path(conn.execute("PRAGMA database_list").fetchone()["file"])


def get_meta(conn: sqlite3.Connection, cle: str, defaut: str | None = None) -> str | None:
    row = conn.execute("SELECT valeur FROM meta WHERE cle = ?", (cle,)).fetchone()
    return row["valeur"] if row else defaut


def ecrire_meta(conn: sqlite3.Connection, cle: str, valeur: str | None) -> None:
    """Comme set_meta, sans valider : pour rester dans la transaction en cours."""
    if valeur is None:
        conn.execute("DELETE FROM meta WHERE cle = ?", (cle,))
    else:
        conn.execute(
            "INSERT INTO meta(cle, valeur) VALUES (?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, valeur),
        )


def set_meta(conn: sqlite3.Connection, cle: str, valeur: str | None) -> None:
    ecrire_meta(conn, cle, valeur)
    conn.commit()


def jload(text: str | None, defaut=None):
    if not text:
        return defaut
    return json.loads(text)


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def nouvelle_etiquette(conn: sqlite3.Connection, table: str) -> str:
    """Numéro imprimé sur l'étiquette d'un lieu, d'une étagère ou d'une rangée (voir etiquettes.py)."""
    while True:
        valeur = f"{secrets.randbelow(10**9):09d}"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE etiquette = ?", (valeur,)).fetchone():
            return valeur


# --- Moi --------------------------------------------------------------------------

def moi_id(conn: sqlite3.Connection) -> int:
    """La personne qui possède cette base ; créée au premier besoin."""
    uid = get_meta(conn, "moi_uid")
    row = conn.execute("SELECT id FROM personnes WHERE uid = ?", (uid,)).fetchone() if uid else None
    if row:
        return row["id"]
    uid = nouvel_uid()
    cur = conn.execute("INSERT INTO personnes(uid, nom, cle, maj_le) VALUES (?, ?, ?, ?)",
                       (uid, NOM_PAR_DEFAUT, norm(NOM_PAR_DEFAUT), horodatage()))
    set_meta(conn, "moi_uid", uid)
    return cur.lastrowid


# --- Notices ----------------------------------------------------------------------

def reference(notice) -> str:
    """Ce qui désigne une notice pour l'utilisateur : son ISBN ou son EAN, sinon L + son numéro (L12)."""
    return notice["isbn13"] or notice["ean"] or f"L{notice['id']}"


def id_notice(conn: sqlite3.Connection, ref: int | str) -> int | None:
    """Numéro d'une notice d'après son numéro, sa référence (L12), son ISBN-13 ou son EAN."""
    if isinstance(ref, int):
        return ref
    ref = ref.strip()
    m = re.fullmatch(r"[Ll]?(\d{1,9})", ref)      # un ISBN a 13 chiffres : pas de confusion avec un numéro
    row = (conn.execute("SELECT id FROM notices WHERE id = ?", (int(m.group(1)),)) if m
           else conn.execute("SELECT id FROM notices WHERE isbn13 = ? OR ean = ?", (ref, ref))).fetchone()
    return row["id"] if row else None


def notice_dict(row: sqlite3.Row | None) -> dict | None:
    """Ligne `notices` -> dict avec les champs JSON décodés."""
    if row is None:
        return None
    d = dict(row)
    for key, defaut in (("auteurs", []), ("sujets", []), ("classes_source", {}),
                        ("sources", []), ("corrections", {}), ("pistes", [])):
        if key in d:
            d[key] = jload(d[key], defaut)
    if "corrections" in d:
        d["champs_manuels"] = sorted(c for c, v in d["corrections"].items()
                                     if v["manuel"] and not c.startswith("cote:"))
    if "id" in d and "isbn13" in d:
        d["reference"] = reference(d)
    return d


def cle_couverture(notice) -> str:
    """Nom du fichier de couverture : l'ISBN ou l'EAN (communs à toutes les bases), sinon l'uid, unique partout."""
    return notice["isbn13"] or notice["ean"] or notice["uid"]


def reindex_notice(conn: sqlite3.Connection, notice_id: int) -> None:
    """Met à jour l'index plein texte d'une notice."""
    conn.execute("DELETE FROM notices_fts WHERE rowid = ?", (notice_id,))
    n = notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    if n is None:
        return
    notes_ex = conn.execute(
        "SELECT group_concat(notes, ' ') AS n FROM exemplaires WHERE notice_id = ?", (notice_id,)
    ).fetchone()["n"]
    conn.execute(
        "INSERT INTO notices_fts(rowid, titre, auteurs, editeur, collection, sujets, resume, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            notice_id,
            " ".join(filter(None, [n["titre"], n["sous_titre"]])),
            " ".join(n["auteurs"]),
            n["editeur"],
            n["collection"],
            " ; ".join(n["sujets"]),
            " ".join(filter(None, [n["resume"], *(p.get("titre") for p in n["pistes"])])),
            " ".join(filter(None, [n["notes"], notes_ex])),
        ),
    )
