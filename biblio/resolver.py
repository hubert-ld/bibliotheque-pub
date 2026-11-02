"""Interroge les catalogues, garde les réponses brutes, construit la notice.

Deux temps bien séparés :
  fetch_sources()  réseau  -> raw_responses
  rebuild()        local   -> notices + classifications + index
`rebuild` peut être rejoué à volonté sans aucune requête.
"""

import os
import sqlite3

import httpx

from . import covers, db
from .sources import bnf, googlebooks, loc, openlibrary

PARSERS = {
    bnf.NAME: bnf.parse,
    openlibrary.NAME: openlibrary.parse,
    googlebooks.NAME: googlebooks.parse,
    loc.NAME: loc.parse,
}
# Ordre de confiance pour les champs descriptifs
PRIORITE = [bnf.NAME, openlibrary.NAME, googlebooks.NAME, loc.NAME]
# Ordre de confiance pour chaque indice de classement
PRIORITE_CLASSES = {
    "dewey": [bnf.NAME, loc.NAME, openlibrary.NAME],
    "lcc": [loc.NAME, openlibrary.NAME, bnf.NAME],
    "cdu": [bnf.NAME],
    "cadre_bnf": [bnf.NAME],
}
# Couvertures, par ordre de préférence
PRIORITE_COUVERTURES = [openlibrary.NAME, googlebooks.NAME, bnf.NAME]
CHAMPS = ["titre", "sous_titre", "editeur", "collection", "annee", "pages", "langue",
          "langue_originale", "resume", "forme", "public"]


def google_key(conn: sqlite3.Connection) -> str | None:
    return os.environ.get("BIBLIO_GOOGLE_KEY") or db.get_meta(conn, "google_api_key")


def _raw(conn, notice_id: int, source: str):
    return conn.execute(
        "SELECT * FROM raw_responses WHERE notice_id = ? AND source = ?", (notice_id, source)
    ).fetchone()


def _store(conn, notice_id: int, source: str, fetched) -> None:
    """Garde la réponse d'un catalogue. Une panne ou un silence ne remplace jamais une réponse valide."""
    if fetched.statut != "ok":
        ancienne = _raw(conn, notice_id, source)
        if ancienne and ancienne["statut"] == "ok":
            return
    conn.execute(
        "INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(notice_id, source) DO UPDATE SET statut = excluded.statut, "
        "payload = excluded.payload, recu_le = excluded.recu_le",
        (notice_id, source, fetched.statut, fetched.payload, db.now()),
    )
    conn.commit()


def _needs(conn, notice_id: int, source: str, refresh: bool) -> bool:
    row = _raw(conn, notice_id, source)
    return refresh or row is None or row["statut"] == "erreur"


def parsed_records(conn, notice_id: int) -> dict[str, dict]:
    row = conn.execute("SELECT isbn13 FROM notices WHERE id = ?", (notice_id,)).fetchone()
    isbn13 = row["isbn13"] if row else None
    out = {}
    for row in conn.execute(
        "SELECT source, payload FROM raw_responses WHERE notice_id = ? AND statut = 'ok'", (notice_id,)
    ):
        parser = PARSERS.get(row["source"])
        rec = parser(row["payload"], isbn13) if parser else None
        if rec and (rec.get("titre") or rec.get("auteurs")):
            out[row["source"]] = rec
    return out


def fetch_sources(conn, client: httpx.Client, ref: int | str, refresh: bool = False) -> list[str]:
    """Interroge les catalogues ; renvoie ceux qui n'ont pas pu répondre."""
    notice_id = db.id_notice(conn, ref)
    isbn13 = conn.execute("SELECT isbn13 FROM notices WHERE id = ?", (notice_id,)).fetchone()["isbn13"]
    if not isbn13:
        return []                              # sans ISBN, les catalogues n'ont rien à répondre
    echecs = []

    def interroger(module, *args) -> None:
        fetched = module.fetch(client, isbn13, *args)
        _store(conn, notice_id, module.NAME, fetched)
        if fetched.statut == "erreur":
            echecs.append(module.NAME)

    for module in (bnf, openlibrary):
        if _needs(conn, notice_id, module.NAME, refresh):
            interroger(module)

    records = parsed_records(conn, notice_id)
    merged = merge(records)

    key = google_key(conn)
    if key and (not merged["titre"] or not merged["resume"]):
        if _needs(conn, notice_id, googlebooks.NAME, refresh):
            interroger(googlebooks, key)
            merged = merge(parsed_records(conn, notice_id))

    # LoC : pour les livres non français sans LCC, ou introuvables ailleurs
    if not merged["classes"].get("lcc") and (merged["langue"] not in ("fre",) or not merged["titre"]):
        if _needs(conn, notice_id, loc.NAME, refresh):
            interroger(loc)
    return echecs


def merge(records: dict[str, dict]) -> dict:
    ordered = [records[s] for s in PRIORITE if s in records]
    m = {c: None for c in CHAMPS}
    for champ in CHAMPS:
        for rec in ordered:
            if rec.get(champ):
                m[champ] = rec[champ]
                break
    m["auteurs"], m["auteurs_tri"] = [], []
    for rec in ordered:
        if rec.get("auteurs"):
            m["auteurs"], m["auteurs_tri"] = rec["auteurs"], rec["auteurs_tri"]
            break
    sujets = []
    for rec in ordered:
        for s in rec.get("sujets") or []:
            if s not in sujets:
                sujets.append(s)
    m["sujets"] = sujets[:30]
    classes = {}
    for cle, sources in PRIORITE_CLASSES.items():
        for s in sources:
            value = (records.get(s) or {}).get("classes", {}).get(cle)
            if value:
                classes[cle] = value
                break
    m["classes"] = classes
    m["couverture_url"] = None
    for s in PRIORITE_COUVERTURES:
        cover = (records.get(s) or {}).get("couverture_url")
        if cover:
            m["couverture_url"] = cover
            break
    m["liens"] = {s: r["lien"] for s, r in records.items() if r.get("lien")}
    m["sources"] = [s for s in PRIORITE if s in records]
    return m


def urls_couverture(conn, ref: int | str) -> list[str]:
    """Adresses à essayer pour la couverture ; celle choisie à la main est la seule retenue."""
    notice_id = db.id_notice(conn, ref)
    notice = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    if notice is None:
        return []
    choisie = notice["couverture_url"]
    if "couverture_url" in notice["champs_manuels"]:
        return [choisie] if choisie else []
    records = parsed_records(conn, notice_id)
    autres = [(records.get(s) or {}).get("couverture_url") for s in PRIORITE_COUVERTURES]
    return list(dict.fromkeys(u for u in [choisie, *autres] if u))


def telecharger_couverture(conn, client: httpx.Client, ref: int | str, forcer: bool = False) -> bool:
    notice_id = db.id_notice(conn, ref)
    notice = conn.execute("SELECT isbn13, uid FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return covers.telecharger(client, db.cle_couverture(notice), urls_couverture(conn, notice_id), forcer=forcer)


def rebuild(conn, ref: int | str, valider: bool = True) -> dict | None:
    """Reconstruit notice, cotes et index depuis les réponses brutes stockées.

    `valider=False` reste dans la transaction en cours (fusion d'une autre base).
    """
    from .classify import classer_notice

    notice_id = db.id_notice(conn, ref)
    notice = db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())
    if notice is None:
        return None
    records = parsed_records(conn, notice_id)
    merged = merge(records)
    manuels = set(notice["champs_manuels"])

    values = {}
    for champ in CHAMPS + ["couverture_url"]:
        if champ not in manuels:
            values[champ] = merged[champ]
    if "auteurs" not in manuels:
        values["auteurs"] = db.jdump(merged["auteurs"])
        values["auteur_tri"] = merged["auteurs_tri"][0] if merged["auteurs_tri"] else None
    if "sujets" not in manuels:
        values["sujets"] = db.jdump(merged["sujets"])
    classes = dict(merged["classes"])
    classes["liens"] = merged["liens"]
    values["classes_source"] = db.jdump(classes)
    values["sources"] = db.jdump(merged["sources"])

    if notice["statut"] != "manuel":
        statuts = {r["statut"] for r in conn.execute(
            "SELECT statut FROM raw_responses WHERE notice_id = ?", (notice_id,))}
        if merged["titre"]:
            values["statut"] = "trouve"
        elif "titre" in manuels and notice["titre"]:
            values["statut"] = "manuel"          # inconnu des catalogues, mais décrit à la main
        elif "erreur" in statuts:
            values["statut"] = "erreur"
        elif statuts or not notice["isbn13"]:
            values["statut"] = "introuvable"
    values["maj_le"] = db.now()

    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE notices SET {sets} WHERE id = ?", [*values.values(), notice_id])
    classer_notice(conn, notice_id)
    db.reindex_notice(conn, notice_id)
    if valider:
        conn.commit()
    return db.notice_dict(conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone())


def resolve(conn, client: httpx.Client, ref: int | str, refresh: bool = False) -> dict | None:
    notice_id = db.id_notice(conn, ref)
    fetch_sources(conn, client, notice_id, refresh=refresh)
    return rebuild(conn, notice_id)
