"""Interroge les catalogues, garde les réponses brutes, construit la notice.

Deux temps bien séparés :
  fetch_sources()  réseau  -> raw_responses
  rebuild()        local   -> notices + classifications + index
`rebuild` peut être rejoué à volonté sans aucune requête.
"""

import httpx

from . import covers, db
from .sources import (bnf, deezer, discogs, dnb, googlebooks, itunes, k10plus, loc, musicbrainz, omdb, openlibrary,
                      registre, sudoc, tmdb, upcitemdb)

PARSERS = {m.NAME: m.parse for m in (bnf, sudoc, openlibrary, googlebooks, loc, k10plus, dnb,
                                     musicbrainz, discogs, deezer, itunes, tmdb, omdb, upcitemdb)}
# Ordre de confiance pour les champs descriptifs. Une notice n'a de réponses que d'une famille.
PRIORITE = [bnf.NAME, sudoc.NAME, openlibrary.NAME, googlebooks.NAME, loc.NAME, k10plus.NAME, dnb.NAME,
            musicbrainz.NAME, discogs.NAME, deezer.NAME, itunes.NAME, tmdb.NAME, omdb.NAME, upcitemdb.NAME]
# Ordre de confiance pour chaque indice de classement
PRIORITE_CLASSES = {
    "dewey": [bnf.NAME, sudoc.NAME, loc.NAME, openlibrary.NAME, k10plus.NAME, dnb.NAME],
    "lcc": [loc.NAME, openlibrary.NAME, bnf.NAME, k10plus.NAME],
    "cdu": [bnf.NAME, sudoc.NAME],
    "cadre_bnf": [bnf.NAME],
}
# Couvertures, par ordre de préférence
PRIORITE_COUVERTURES = [openlibrary.NAME, googlebooks.NAME, bnf.NAME, musicbrainz.NAME, itunes.NAME, deezer.NAME,
                        discogs.NAME, tmdb.NAME, omdb.NAME, upcitemdb.NAME]
CHAMPS = ["titre", "sous_titre", "editeur", "collection", "annee", "pages", "langue",
          "langue_originale", "resume", "forme", "public", "ref_catalogue", "duree", "nb_disques"]
FAMILLE_DES_SOURCES = {c.module.NAME: c.famille for c in registre.CATALOGUES}


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
    row = conn.execute("SELECT isbn13, ean FROM notices WHERE id = ?", (notice_id,)).fetchone()
    isbn13 = (row["isbn13"] or row["ean"]) if row else None
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
    n = conn.execute("SELECT isbn13, ean, support, titre FROM notices WHERE id = ?", (notice_id,)).fetchone()
    echecs = []

    def interroger(module, code: str | None = None) -> dict:
        """Interroge ce catalogue si besoin (activé, clé présente, pas encore de réponse) ; renvoie la fiche à jour."""
        cat = registre.PAR_NOM[module.NAME]
        if registre.disponible(conn, cat) and _needs(conn, notice_id, module.NAME, refresh):
            fetched = module.fetch(client, code or n["isbn13"] or n["ean"], *registre.arguments(conn, cat))
            _store(conn, notice_id, module.NAME, fetched)
            if fetched.statut == "erreur":
                echecs.append(module.NAME)
        return merge(parsed_records(conn, notice_id))

    if n["isbn13"]:
        _chercher_un_livre(interroger)
    elif n["ean"] or n["support"] in ("dvd", "bluray"):
        _chercher_un_disque_ou_film(interroger, n)
    return echecs                              # sans code ni titre de film, les catalogues n'ont rien à répondre


def _chercher_un_livre(interroger) -> None:
    interroger(bnf)
    merged = interroger(openlibrary)
    if not merged["titre"] or not merged["resume"]:
        merged = interroger(googlebooks)
    # Sudoc : un indice Dewey même pour la fiction, et ce que la BnF n'a pas
    if not merged["titre"] or not merged["classes"].get("dewey"):
        merged = interroger(sudoc)
    # LoC : pour les livres non français sans LCC, ou introuvables ailleurs
    if not merged["classes"].get("lcc") and (merged["langue"] not in ("fre",) or not merged["titre"]):
        merged = interroger(loc)
    if not merged["titre"]:
        merged = interroger(k10plus)
    if not merged["titre"]:
        interroger(dnb)


def _chercher_un_disque_ou_film(interroger, n) -> None:
    """Un code-barres ne dit pas ce qu'il désigne : la musique d'abord, ses catalogues le lisent directement."""
    films = n["support"] in ("dvd", "bluray")
    merged = merge({})
    if n["ean"] and not films:
        merged = interroger(musicbrainz)
        if not merged["titre"] or not merged["editeur"]:
            merged = interroger(discogs)
        if not merged["pistes"] or not merged["couverture_url"]:
            merged = interroger(deezer)
        if not merged["pistes"] or not merged["couverture_url"]:
            merged = interroger(itunes)
    if merged["titre"] and not films and FAMILLE_DES_SOURCES[merged["sources"][0]] == "musique":
        return
    # UPCitemdb donne le titre que TMDb et OMDb demandent
    if n["ean"]:
        merged = interroger(upcitemdb)
    titre = n["titre"] or merged["titre"]         # un titre corrigé à la main relance la recherche
    if titre and (films or merged["support"] in ("dvd", "bluray")):
        merged = interroger(tmdb, titre)
        if not merged["resume"]:
            interroger(omdb, titre)


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
    m["pistes"] = next((rec["pistes"] for rec in ordered if rec.get("pistes")), [])
    m["support"] = next((rec["support"] for rec in ordered if rec.get("support")), None)
    if not m["support"] and m["titre"]:             # les boutiques en ligne ne disent pas le format
        famille = FAMILLE_DES_SOURCES.get(next(s for s in PRIORITE if s in records))
        m["support"] = {"musique": "cd", "films": "dvd"}.get(famille)
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
    notice = conn.execute("SELECT isbn13, ean, uid FROM notices WHERE id = ?", (notice_id,)).fetchone()
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
    values["pistes"] = db.jdump(merged["pistes"])
    if "support" not in manuels and notice["ean"] and merged["support"]:
        values["support"] = merged["support"]
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
        elif statuts or not (notice["isbn13"] or notice["ean"]):
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
