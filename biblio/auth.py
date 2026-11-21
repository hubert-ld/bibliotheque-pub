"""Comptes, rôles et connexion des personnes de la maison.

On tape son identifiant et son code une fois par appareil : un jeton aléatoire garde ensuite la
session dans un cookie, renouvelé à l'usage, jusqu'à ce que l'administrateur coupe cet appareil.

Ce module ne touche ni aux certificats ni aux clés du téléphone (telephone.py) : l'ordinateur lui-même
(localhost), la clé admin et la clé des QR codes continuent de fonctionner à côté des comptes.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from . import db
from .i18n import tr

COOKIE = "biblio_session"
DUREE_SOUVENIR = timedelta(days=365)
DUREE_SANS_SOUVENIR = timedelta(hours=24)     # le cookie, lui, disparaît à la fermeture du navigateur
RENOUVELER_APRES = timedelta(days=1)          # évite d'écrire dans la base à chaque page
ESSAIS_AVANT_BLOCAGE = 5
ESSAIS_PAR_ADRESSE = 20
BLOCAGE_MAX = 3600
OUBLI_DES_ESSAIS = timedelta(days=1)
GARDE_JOURNAL = timedelta(days=90)
CODE_MIN = 4
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
TOUS = "*"                                    # ligne de `tentatives` : tous les identifiants d'une adresse

ROLES = ["lecteur", "contributeur", "bibliothecaire", "admin"]
NOMS_ROLES = {"lecteur": "Lecteur", "contributeur": "Contributeur", "bibliothecaire": "Bibliothécaire", "admin": "Admin"}
DROITS = {
    "lecteur": {"consulter"},
    "contributeur": {"consulter", "scanner"},
    "bibliothecaire": {"consulter", "scanner", "modifier", "personnel"},
    "admin": {"consulter", "scanner", "modifier", "personnel", "admin"},
}
# La clé des QR codes donnait déjà tout sauf les réglages : c'est ce que fait un bibliothécaire
ROLE_DE_LA_CLE = {"telephone": "bibliothecaire", "admin": "admin"}

# Le droit demandé par chaque route, dans l'ordre : la première ligne qui correspond l'emporte.
# Une route absente est réservée à l'admin (voir droit_requis) ; un test vérifie qu'aucune n'est oubliée.
SANS_CONNEXION = ("/connexion", "/manifest.webmanifest")
REGLES = [
    (None, r"/(compte|deconnexion)(/.*)?", "connecte"),
    (None, r"/(admin|reglages|telephone|systeme|langue)(/.*)?", "admin"),
    (None, r"/partage\.db", "admin"),
    # Le mode du scan et l'opération groupée sont revérifiés dans leur route (« où est-il ? » : consulter)
    ("POST", r"/api/scan", "consulter"),
    ("POST", r"/catalogue/lot", "scanner"),
    ("POST", r"/api/annuler/.*", "scanner"),
    (None, r"/api/inventaire(/.*)?", "scanner"),
    (None, r"/inventaire/.*", "scanner"),
    ("POST", r"/exemplaire/\d+/deplacer", "scanner"),
    ("POST", r"/livre/[^/]+/exemplaire", "scanner"),
    (None, r"/manuel(/.*)?", "scanner"),
    ("GET", r"/a-traiter", "scanner"),
    ("GET", r"/(stats|prets)", "personnel"),
    (None, r"/echanges(/.*)?", "personnel"),
    ("GET", r"/export\.\w+", "modifier"),
    ("GET", r"/lieux/etiquettes", "modifier"),
    ("GET", r"/(|scan|catalogue|lieux|lieux/\d+/rangement|livre/[^/]+|couverture/[^/]+|api/notices|api/etat)", "consulter"),
    ("POST", r"/.*", "modifier"),
]
REGLES = [(m, re.compile(p), d) for m, p, d in REGLES]


class Refus(Exception):
    """Connexion refusée ; le message est à afficher tel quel."""


class ErreurCompte(Exception):
    """Opération sur un compte impossible ; le message est à afficher tel quel."""


def droit_requis(methode: str, chemin: str) -> str | None:
    """Le droit qu'il faut pour cette requête ; None : route non déclarée, donc réservée à l'admin."""
    methode = "GET" if methode == "HEAD" else methode
    for m, motif, droit in REGLES:
        if (m is None or m == methode) and motif.fullmatch(chemin):
            return droit
    return None


def peut(role: str | None, droit: str | None) -> bool:
    if role is None:
        return False
    return droit == "connecte" or (droit or "admin") in DROITS.get(role, ())


# --- Codes ------------------------------------------------------------------------

def hacher(code: str) -> str:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(code.encode(), salt=sel, **_SCRYPT)
    return f"scrypt${sel.hex()}${empreinte.hex()}"


def verifier_code(code: str, stocke: str) -> bool:
    try:
        _, sel, empreinte = stocke.split("$")
        calcul = hashlib.scrypt(code.encode(), salt=bytes.fromhex(sel), **_SCRYPT)
        return hmac.compare_digest(calcul, bytes.fromhex(empreinte))
    except ValueError:
        return False


_LEURRE = hacher("leurre")      # un identifiant inconnu prend le même temps : on ne peut pas les deviner


def generer_code() -> str:
    """Six chiffres : faciles à donner à quelqu'un ; le blocage après 5 essais les protège."""
    return f"{secrets.randbelow(10 ** 6):06d}"


def _verifier_longueur(code: str) -> str:
    code = (code or "").strip()
    if len(code) < CODE_MIN:
        raise ErreurCompte(tr("le code doit faire au moins {n} caractères", n=CODE_MIN))
    return code


# --- Journal ----------------------------------------------------------------------

def journaliser(conn, action: str, acteur: str | None = None, detail: str | None = None, ip: str | None = None) -> None:
    conn.execute("INSERT INTO journal(le, acteur, action, detail, ip) VALUES (?, ?, ?, ?, ?)",
                 (db.now(), acteur, action, detail, ip))
    conn.execute("DELETE FROM journal WHERE le < ?", ((datetime.now() - GARDE_JOURNAL).isoformat(timespec="seconds"),))
    conn.commit()


def journal(conn, limite: int = 200) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,))]


# --- Essais de connexion ----------------------------------------------------------

def _duree_blocage(nb: int, seuil: int) -> int | None:
    if nb < seuil:
        return None
    return min(60 * 2 ** (nb - seuil), BLOCAGE_MAX)


def _essai_rate(conn, identifiant: str, ip: str, seuil: int) -> bool:
    """Compte un échec ; renvoie True s'il déclenche un blocage."""
    maintenant = datetime.now()
    row = conn.execute("SELECT nb, derniere FROM tentatives WHERE identifiant = ? AND ip = ?", (identifiant, ip)).fetchone()
    nb = 1
    if row and row["derniere"] and datetime.fromisoformat(row["derniere"]) > maintenant - OUBLI_DES_ESSAIS:
        nb = row["nb"] + 1
    duree = _duree_blocage(nb, seuil)
    jusqua = (maintenant + timedelta(seconds=duree)).isoformat(timespec="seconds") if duree else None
    conn.execute("INSERT INTO tentatives(identifiant, ip, nb, bloque_jusqua, derniere) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(identifiant, ip) DO UPDATE SET nb = excluded.nb, bloque_jusqua = excluded.bloque_jusqua, "
                 "derniere = excluded.derniere", (identifiant, ip, nb, jusqua, maintenant.isoformat(timespec="seconds")))
    return duree is not None


def _bloque(conn, identifiant: str, ip: str) -> int:
    """Secondes de blocage restantes pour cet identifiant depuis cette adresse (0 : libre)."""
    restant = 0
    for r in conn.execute("SELECT bloque_jusqua FROM tentatives WHERE ip = ? AND identifiant IN (?, ?) "
                          "AND bloque_jusqua IS NOT NULL", (ip, identifiant, TOUS)):
        restant = max(restant, int((datetime.fromisoformat(r["bloque_jusqua"]) - datetime.now()).total_seconds()))
    return restant


def connecter(conn, identifiant: str, code: str, ip: str) -> dict:
    """Vérifie l'identifiant et le code ; renvoie le compte, ou lève Refus."""
    identifiant = (identifiant or "").strip()
    cle = db.norm(identifiant)
    restant = _bloque(conn, cle, ip)
    if restant > 0:
        raise Refus(tr("Trop d'essais : réessayez dans {n} min.", n=restant // 60 + 1))
    compte = conn.execute("SELECT * FROM comptes WHERE identifiant = ?", (identifiant,)).fetchone()
    bon = verifier_code(code or "", compte["code_hash"] if compte else _LEURRE)
    if compte and bon and compte["actif"]:
        conn.execute("DELETE FROM tentatives WHERE ip = ? AND identifiant IN (?, ?)", (ip, cle, TOUS))
        conn.execute("UPDATE comptes SET derniere_connexion = ? WHERE id = ?", (db.now(), compte["id"]))
        conn.commit()
        journaliser(conn, "connexion", compte["identifiant"], ip=ip)
        return dict(compte)
    bloque = _essai_rate(conn, cle, ip, ESSAIS_AVANT_BLOCAGE)
    bloque = _essai_rate(conn, TOUS, ip, ESSAIS_PAR_ADRESSE) or bloque
    conn.commit()
    journaliser(conn, "blocage" if bloque else "echec", identifiant[:60], ip=ip)
    raise Refus(tr("Identifiant ou code incorrect."))


# --- Sessions ---------------------------------------------------------------------

def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def ouvrir_session(conn, compte_id: int, appareil: str | None, ip: str | None, souvenir: bool = True) -> str:
    jeton = secrets.token_urlsafe(32)
    maintenant = datetime.now()
    expire = maintenant + (DUREE_SOUVENIR if souvenir else DUREE_SANS_SOUVENIR)
    conn.execute("DELETE FROM sessions WHERE expire_le < ?", (maintenant.isoformat(timespec="seconds"),))
    conn.execute("INSERT INTO sessions(jeton_hash, compte_id, appareil, ip, souvenir, cree_le, vu_le, expire_le) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (_empreinte(jeton), compte_id, resume_appareil(appareil), ip, int(souvenir), db.now(), db.now(),
                  expire.isoformat(timespec="seconds")))
    conn.commit()
    return jeton


def session(conn, jeton: str | None) -> dict | None:
    """Compte et session de ce jeton, s'il est encore valable. `renouvele` : le cookie est à reposer."""
    if not jeton:
        return None
    row = conn.execute(
        "SELECT s.id AS session_id, s.souvenir, s.vu_le, s.expire_le, c.id, c.identifiant, c.nom, c.role, c.actif "
        "FROM sessions s JOIN comptes c ON c.id = s.compte_id WHERE s.jeton_hash = ?", (_empreinte(jeton),)).fetchone()
    maintenant = datetime.now()
    if not row or not row["actif"] or datetime.fromisoformat(row["expire_le"]) < maintenant:
        return None
    d = dict(row, renouvele=False)
    if datetime.fromisoformat(row["vu_le"]) < maintenant - RENOUVELER_APRES:
        duree = DUREE_SOUVENIR if row["souvenir"] else DUREE_SANS_SOUVENIR
        conn.execute("UPDATE sessions SET vu_le = ?, expire_le = ? WHERE id = ?",
                     (maintenant.isoformat(timespec="seconds"), (maintenant + duree).isoformat(timespec="seconds"), row["session_id"]))
        conn.commit()
        d["renouvele"] = bool(row["souvenir"])
    return d


def fermer_session(conn, jeton: str | None) -> None:
    if jeton:
        conn.execute("DELETE FROM sessions WHERE jeton_hash = ?", (_empreinte(jeton),))
        conn.commit()


def couper_appareil(conn, session_id: int, compte_id: int | None = None) -> None:
    """`compte_id` : limite à ses propres appareils (page Mon compte)."""
    sql, params = "DELETE FROM sessions WHERE id = ?", [session_id]
    if compte_id is not None:
        sql += " AND compte_id = ?"
        params.append(compte_id)
    conn.execute(sql, params)
    conn.commit()


def appareils(conn, compte_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM sessions WHERE compte_id = ? ORDER BY vu_le DESC", (compte_id,))]


def resume_appareil(agent: str | None) -> str:
    """« iPhone · Safari » : de quoi reconnaître un appareil dans la liste, sans garder tout l'en-tête."""
    a = agent or ""
    systeme = next((nom for motif, nom in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                           ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")) if motif in a), None)
    navigateur = next((nom for motif, nom in (("Firefox", "Firefox"), ("FxiOS", "Firefox"), ("Edg", "Edge"), ("Chrome", "Chrome"),
                                              ("CriOS", "Chrome"), ("Safari", "Safari")) if motif in a), None)
    return " · ".join(filter(None, [systeme, navigateur])) or tr("Appareil inconnu")


# --- Comptes ----------------------------------------------------------------------

def comptes(conn) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM comptes ORDER BY identifiant COLLATE NOCASE"):
        out.append(dict(r, appareils=appareils(conn, r["id"])))
    return out


def compte(conn, compte_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM comptes WHERE id = ?", (compte_id,)).fetchone()
    return dict(row) if row else None


def par_identifiant(conn, identifiant: str) -> dict | None:
    row = conn.execute("SELECT * FROM comptes WHERE identifiant = ?", ((identifiant or "").strip(),)).fetchone()
    return dict(row) if row else None


def _verifier_role(role: str) -> None:
    if role not in ROLES:
        raise ErreurCompte(tr("rôle inconnu : {role}", role=role))


def _dernier_admin(conn, compte_id: int) -> bool:
    """Ce compte est-il le dernier admin encore actif ?"""
    autres = conn.execute("SELECT count(*) FROM comptes WHERE role = 'admin' AND actif = 1 AND id != ?", (compte_id,)).fetchone()[0]
    row = conn.execute("SELECT role, actif FROM comptes WHERE id = ?", (compte_id,)).fetchone()
    return bool(row and row["role"] == "admin" and row["actif"] and autres == 0)


def creer_compte(conn, identifiant: str, role: str, nom: str | None = None, code: str | None = None) -> str:
    """Crée le compte et renvoie son code : il ne pourra plus être relu ensuite."""
    identifiant = (identifiant or "").strip()
    if not identifiant:
        raise ErreurCompte(tr("indiquez un identifiant"))
    if identifiant.lower() in (TOUS, db.PAR_TELEPHONE):
        raise ErreurCompte(tr("cet identifiant n'est pas permis"))
    _verifier_role(role)
    code = _verifier_longueur(code) if (code or "").strip() else generer_code()
    if par_identifiant(conn, identifiant):
        raise ErreurCompte(tr("l'identifiant « {identifiant} » existe déjà", identifiant=identifiant))
    conn.execute("INSERT INTO comptes(identifiant, nom, role, code_hash, cree_le) VALUES (?, ?, ?, ?, ?)",
                 (identifiant, (nom or "").strip() or None, role, hacher(code), db.now()))
    conn.commit()
    return code


def modifier_compte(conn, compte_id: int, role: str | None = None, nom: str | None = None, actif: bool | None = None) -> None:
    ancien = compte(conn, compte_id)
    if not ancien:
        raise ErreurCompte(tr("compte introuvable"))
    if role is not None:
        _verifier_role(role)
    perd_l_admin = (role not in (None, "admin")) or actif is False
    if perd_l_admin and _dernier_admin(conn, compte_id):
        raise ErreurCompte(tr("c'est le dernier administrateur : créez-en un autre avant"))
    conn.execute("UPDATE comptes SET role = ?, nom = ?, actif = ? WHERE id = ?",
                 (role or ancien["role"], ancien["nom"] if nom is None else (nom.strip() or None),
                  ancien["actif"] if actif is None else int(actif), compte_id))
    if actif is False:
        conn.execute("DELETE FROM sessions WHERE compte_id = ?", (compte_id,))
    conn.commit()


def changer_code(conn, compte_id: int, code: str | None = None, garder_session: int | None = None) -> str:
    """Change le code et coupe les appareils déjà connectés (sauf `garder_session`). Renvoie le code."""
    if not compte(conn, compte_id):
        raise ErreurCompte(tr("compte introuvable"))
    code = _verifier_longueur(code) if (code or "").strip() else generer_code()
    conn.execute("UPDATE comptes SET code_hash = ? WHERE id = ?", (hacher(code), compte_id))
    conn.execute("DELETE FROM sessions WHERE compte_id = ? AND id IS NOT ?", (compte_id, garder_session))
    conn.commit()
    return code


def supprimer_compte(conn, compte_id: int) -> None:
    if _dernier_admin(conn, compte_id):
        raise ErreurCompte(tr("c'est le dernier administrateur : créez-en un autre avant"))
    conn.execute("DELETE FROM comptes WHERE id = ?", (compte_id,))
    conn.commit()
