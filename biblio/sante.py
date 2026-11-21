"""Tests des catalogues et état général, pour la page d'administration.

Un test demande un code connu de tous : une réponse, même « absent », prouve que le catalogue répond.
Rien ne tourne en permanence, pour ménager un petit serveur : on teste à la demande.
"""

import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__, certs, db, sauvegarde, telephone
from .i18n import tr
from .sources import make_client, registre

LENT_MS = 3000
PERIME = timedelta(minutes=5)
NOMS_ETATS = {"ok": "Répond", "lent": "Lent", "panne": "En panne", "sans_cle": "Clé manquante",
              "cle_refusee": "Clé refusée", "desactive": "Désactivé", "jamais": "Pas encore testé"}


def _tester(cat: registre.Catalogue, cle: str | None) -> dict:
    res = {"source": cat.module.NAME, "latence": None, "message": None}
    if cat.obligatoire and not cle:
        return {**res, "etat": "sans_cle"}
    debut = time.monotonic()
    try:
        with make_client() as client:              # les mêmes délais que pour une vraie recherche
            fetched = cat.module.fetch(client, cat.test, *((cle,) if cat.cle else ()))
    except Exception as e:                     # un catalogue qui répond n'importe quoi ne doit pas tout arrêter
        return {**res, "etat": "panne", "message": str(e)[:200]}
    latence = round((time.monotonic() - debut) * 1000)
    if fetched.statut == "erreur":
        message = str(fetched.payload or "")[:200]
        refus = any(m in message for m in ("401", "403", "refus"))
        return {**res, "etat": "cle_refusee" if cat.cle and refus else "panne", "latence": latence, "message": message}
    return {**res, "etat": "lent" if latence > LENT_MS else "ok", "latence": latence}


def tester(conn, noms: list[str] | None = None) -> list[dict]:
    """Teste les catalogues en parallèle et garde le résultat dans `sources_etat`."""
    choisis = [c for c in registre.CATALOGUES if not noms or c.module.NAME in noms]
    cles = [registre.cle_de(conn, c) for c in choisis]
    with ThreadPoolExecutor(max_workers=len(choisis) or 1) as pool:
        resultats = list(pool.map(_tester, choisis, cles))
    quand = db.now()
    for r in resultats:
        conn.execute("INSERT INTO sources_etat(source, etat, latence, message, teste_le) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT(source) DO UPDATE SET etat = excluded.etat, latence = excluded.latence, "
                     "message = excluded.message, teste_le = excluded.teste_le",
                     (r["source"], r["etat"], r["latence"], r["message"], quand))
    conn.commit()
    return resultats


def activer(conn, nom: str, actif: bool) -> None:
    conn.execute("INSERT INTO sources_etat(source, actif) VALUES (?, ?) "
                 "ON CONFLICT(source) DO UPDATE SET actif = excluded.actif", (nom, int(actif)))
    conn.commit()


def catalogues(conn) -> list[dict]:
    """Une ligne par catalogue : dernier test, réponses gardées, clé."""
    etats = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM sources_etat")}
    compteurs: dict[str, dict] = {}
    for r in conn.execute("SELECT source, statut, count(*) AS nb, max(recu_le) AS le FROM raw_responses GROUP BY source, statut"):
        c = compteurs.setdefault(r["source"], {"ok": 0, "absent": 0, "erreur": 0, "dernier": None})
        c[r["statut"]] = r["nb"]
        c["dernier"] = max(filter(None, [c["dernier"], r["le"]]))
    out = []
    for cat in registre.CATALOGUES:
        nom = cat.module.NAME
        e = etats.get(nom, {})
        actif = bool(e.get("actif", 1))
        etat = e.get("etat") or "jamais"
        cle = registre.cle_de(conn, cat)
        if cat.obligatoire and not cle:
            etat = "sans_cle"
        out.append({
            "source": nom, "nom": cat.nom, "famille": cat.famille, "actif": actif, "etat": etat if actif else "desactive",
            "latence": e.get("latence"), "message": e.get("message"), "teste_le": e.get("teste_le"),
            "cle_nom": cat.cle, "cle_presente": bool(cle), "obligatoire": cat.obligatoire, "aide": cat.aide,
            **compteurs.get(nom, {"ok": 0, "absent": 0, "erreur": 0, "dernier": None}),
        })
    return out


def test_perime(conn) -> bool:
    row = conn.execute("SELECT max(teste_le) AS le FROM sources_etat").fetchone()
    return not row["le"] or datetime.fromisoformat(row["le"]) < datetime.now() - PERIME


def _taille(chemin: Path) -> int:
    return sum(p.stat().st_size for p in (chemin, Path(f"{chemin}-wal"), Path(f"{chemin}-shm")) if p.exists())


def sauvegardes(conn) -> list[dict]:
    """Les copies de sécurité, de la plus récente à la plus ancienne."""
    dossier = sauvegarde.dossier_defaut(conn)
    copies = sauvegarde._copies(dossier, db.chemin_base(conn).stem)
    return [{"nom": p.name, "taille": p.stat().st_size,
             "le": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")} for p in reversed(copies)]


def general(conn) -> dict:
    chemin = db.chemin_base(conn)
    copies = sauvegardes(conn)
    disque = shutil.disk_usage(chemin.parent)
    support = {r[0]: r[1] for r in conn.execute("SELECT support, count(*) FROM notices GROUP BY support")}
    def nb(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "version": __version__, "schema": db.SCHEMA_VERSION, "base": str(chemin), "taille_base": _taille(chemin),
        "disque_libre": disque.free, "disque_total": disque.total,
        "livres": support.get("livre", 0),
        "disques": sum(support.get(s, 0) for s in ("cd", "vinyle", "cassette")),
        "films": sum(support.get(s, 0) for s in ("dvd", "bluray")),
        "inconnus": support.get("inconnu", 0),
        "exemplaires": nb("SELECT count(*) FROM exemplaires"),
        "lieux": nb("SELECT count(*) FROM lieux"),
        "etageres": nb("SELECT count(*) FROM etageres"),
        "rangees": nb("SELECT count(*) FROM rangees"),
        "prets": nb("SELECT count(*) FROM prets WHERE date_retour IS NULL"),
        "en_attente": nb("SELECT count(*) FROM notices WHERE statut = 'en_attente'"),
        "en_echec": nb("SELECT count(*) FROM notices WHERE statut IN ('erreur', 'introuvable')"),
        "comptes": nb("SELECT count(*) FROM comptes WHERE actif = 1"),
        "appareils": nb("SELECT count(*) FROM sessions"),
        "derniere_sauvegarde": copies[0]["le"] if copies else None,
        "nb_sauvegardes": len(copies),
        "telephone_actif": telephone.etat["actif"], "nom_reseau": telephone.etat["nom"] or telephone.nom_local(),
        "ip": telephone.etat["ip"] or telephone.ip_locale(),
        "certificats": certs.etat(),
    }


def octets(n: float | None) -> str:
    n = float(n or 0)
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unite == "To":
            return f"{n:.0f} {tr(unite)}" if unite == "o" else f"{n:.1f} {tr(unite)}"
        n /= 1024
