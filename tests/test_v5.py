"""Schéma 5 : codes-barres, rangées, supports, catalogues."""

import pytest

from biblio import codes, db, etiquettes, export, partage, resolver, services
from biblio.classify import calculer
from biblio.isbn import IsbnError
from biblio.services import Erreur
from biblio.sources import deezer, discogs, dnb, itunes, k10plus, musicbrainz, omdb, sudoc, tmdb, upcitemdb

from .conftest import fixture

CHANSON = "9782070196678"
RAM = "0888837168625"


# --- Codes ------------------------------------------------------------------------

@pytest.mark.parametrize("brut,attendu", [
    ("9782070360024", ("isbn", "9782070360024")),
    ("2-07-036002-4", ("isbn", "9782070360024")),
    ("L12", ("reference", "L12")),
    (RAM, ("ean", RAM)),
    ("888837168625", ("ean", RAM)),                  # UPC à 12 chiffres
    ("3259130000000", None),                          # clé fausse
    ("9770000000000", None),                          # ISSN : une revue
    ("&é", None),
])
def test_analyser(brut, attendu):
    if attendu:
        assert codes.analyser(brut) == attendu
    else:
        with pytest.raises(IsbnError):
            codes.analyser(brut)


def test_ean_en_azerty():
    azerty = RAM.translate(str.maketrans("0123456789", "à&é\"'(§è!ç"))
    assert codes.analyser(azerty) == ("ean", RAM)


def test_etiquette_aller_retour(conn):
    lieu = services.creer_lieu(conn, "Salon")
    etagere = services.creer_etagere(conn, lieu, "É1")
    rangee = services.creer_rangee(conn, etagere, "Devant")
    numero = conn.execute("SELECT etiquette FROM rangees WHERE id = ?", (rangee,)).fetchone()[0]
    code = etiquettes.code_de("rangees", numero)
    assert codes.analyser(code) == ("etiquette", code)
    assert services.lire_etiquette(conn, code) == {"lieu_id": lieu, "etagere_id": etagere, "rangee_id": rangee, "nom": "Salon › É1 › Devant"}
    numero = conn.execute("SELECT etiquette FROM etageres WHERE id = ?", (etagere,)).fetchone()[0]
    assert services.lire_etiquette(conn, etiquettes.code_de("etageres", numero))["rangee_id"] is None
    with pytest.raises(Erreur):                       # une étiquette n'est pas un livre
        services.ajouter(conn, code)


def test_svg_de_l_etiquette():
    code = etiquettes.code_de("lieux", "123456789")
    svg = etiquettes.svg(code)
    assert svg.startswith("<svg") and code in svg
    assert len(etiquettes._modules(code)) == 95          # la longueur d'un EAN-13


# --- Rangées ----------------------------------------------------------------------

@pytest.fixture
def salon(conn):
    lieu = services.creer_lieu(conn, "Salon")
    etagere = services.creer_etagere(conn, lieu, "É1")
    return dict(lieu=lieu, etagere=etagere, devant=services.creer_rangee(conn, etagere, "Devant"),
                derriere=services.creer_rangee(conn, etagere, "Derrière"))


def test_rangee_facultative(conn, salon):
    assert services.ajouter(conn, CHANSON, salon["lieu"], salon["etagere"])["emplacement"] == "Salon › É1"
    r = services.ajouter(conn, "9782253140870", salon["lieu"], salon["etagere"], rangee_id=salon["devant"])
    assert r["emplacement"] == "Salon › É1 › Devant"
    rows, total = services.rechercher(conn, rangee_id=salon["devant"])
    assert total == 1 and rows[0]["emplacement"] == "Salon › É1 › Devant"


def test_rangee_d_une_autre_etagere_refusee(conn, salon):
    autre = services.creer_etagere(conn, salon["lieu"], "É2")
    with pytest.raises(Erreur):
        services.ajouter(conn, CHANSON, salon["lieu"], autre, rangee_id=salon["devant"])


def test_rangee_seule_complete_l_emplacement(conn, salon):
    assert services.ajouter(conn, CHANSON, rangee_id=salon["devant"])["emplacement"] == "Salon › É1 › Devant"


def test_emplacement_texte_a_trois_niveaux(conn, salon):
    assert services.emplacement(conn, "salon/é1/devant") == (salon["lieu"], salon["etagere"], salon["devant"])
    with pytest.raises(Erreur):
        services.emplacement(conn, "Salon/É1/Inconnue")
    _, _, nouvelle = services.emplacement(conn, "Salon/É1/Haut", creer=True)
    assert nouvelle


def test_deplacer_entre_rangees(conn, salon):
    ex = services.ajouter(conn, CHANSON, salon["lieu"], salon["etagere"], rangee_id=salon["devant"])["exemplaire_id"]
    r = services.deplacer(conn, CHANSON, salon["lieu"], salon["etagere"], salon["derriere"])
    assert r["statut"] == "deplace" and r["message"].endswith("Derrière")
    m = conn.execute("SELECT de_rangee, vers_rangee FROM mouvements WHERE exemplaire_id = ?", (ex,)).fetchone()
    assert tuple(m) == (salon["devant"], salon["derriere"])
    assert services.deplacer(conn, CHANSON, salon["lieu"], salon["etagere"], salon["derriere"])["statut"] == "deja_la"


def test_supprimer_une_rangee_garde_le_livre_sur_l_etagere(conn, salon):
    services.ajouter(conn, CHANSON, salon["lieu"], salon["etagere"], rangee_id=salon["devant"])
    services.supprimer_rangee(conn, salon["devant"])
    ex = services.exemplaires_de(conn, CHANSON)[0]
    assert ex["emplacement"] == "Salon › É1" and ex["rangee_id"] is None
    assert conn.execute("SELECT genre FROM suppressions").fetchone()[0] == "rangee"


def test_inventaire_d_une_rangee(conn, salon):
    services.ajouter(conn, CHANSON, salon["lieu"], salon["etagere"], rangee_id=salon["devant"])
    services.ajouter(conn, "9782253140870", salon["lieu"], salon["etagere"], rangee_id=salon["derriere"])
    inv = services.demarrer_inventaire(conn, salon["lieu"], salon["etagere"], salon["devant"])
    assert services.inventaire(conn, inv)["emplacement"] == "Salon › É1 › Devant"
    assert services.scanner_inventaire(conn, inv, CHANSON)["statut"] == "present"
    assert services.scanner_inventaire(conn, inv, "9782253140870")["statut"] == "ailleurs"
    r = services.rapport_inventaire(conn, inv)
    assert not r["manquants"] and len(r["ailleurs"]) == 1


def test_synchro_des_rangees(tmp_path):
    a = db.connect(tmp_path / "a.db")
    b_chemin = tmp_path / "b.db"
    b = db.connect(b_chemin)
    b.execute("INSERT INTO meta(cle, valeur) VALUES ('moi_uid', ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
              (db.get_meta(a, "moi_uid") or a.execute("SELECT uid FROM personnes WHERE id = ?", (db.moi_id(a),)).fetchone()[0],))
    b.execute("INSERT OR IGNORE INTO personnes(uid, nom, cle, maj_le) SELECT uid, nom, cle, maj_le FROM (SELECT ? AS uid, 'Moi' AS nom, 'moi' AS cle, '2026' AS maj_le)",
              (db.get_meta(a, "moi_uid"),))
    b.commit()
    lieu = services.creer_lieu(b, "Salon")
    etagere = services.creer_etagere(b, lieu, "É1")
    rangee = services.creer_rangee(b, etagere, "Devant")
    services.ajouter(b, CHANSON, lieu, etagere, rangee_id=rangee)
    etiquette = b.execute("SELECT etiquette FROM rangees").fetchone()[0]
    b.close()
    partage.synchroniser(a, b_chemin)
    assert services.exemplaires_de(a, CHANSON)[0]["emplacement"] == "Salon › É1 › Devant"
    assert a.execute("SELECT etiquette FROM rangees").fetchone()[0] == etiquette       # la même étiquette partout
    a.close()


# --- Supports et catalogues --------------------------------------------------------

def test_ean_cree_une_notice_inconnue(conn):
    r = services.ajouter(conn, "888837168625")
    assert r["statut"] == "ajoute" and r["code"] == RAM
    n = services.notice(conn, RAM)
    assert n["support"] == "inconnu" and n["ean"] == RAM and n["isbn13"] is None and n["reference"] == RAM
    assert services.ajouter(conn, RAM, filtrer_rebond=False)["statut"] == "doublon"
    assert services.rechercher(conn, RAM)[1] == 2


def test_parser_musicbrainz():
    n = musicbrainz.parse(fixture("mb_release.json"), RAM)
    assert n["titre"] == "Random Access Memories" and n["auteurs"] == ["Daft Punk"]
    assert n["support"] == "cd" and n["editeur"] == "Columbia" and n["ref_catalogue"] == "88883716862"
    assert len(n["pistes"]) == 13 and n["pistes"][0]["titre"] == "Give Life Back to Music" and n["pistes"][0]["duree"] == 275
    assert n["duree"] == 75 and n["annee"] == 2013 and n["couverture_url"].startswith("https://coverartarchive.org/")


def test_musicbrainz_prefere_l_edition_francaise():
    import json
    releases = json.loads(fixture("mb_recherche.json"))["releases"]
    assert musicbrainz._choisir(releases)["country"] == "FR"


def test_parser_discogs():
    n = discogs.parse(fixture("discogs_recherche.json"), RAM)
    assert n["titre"] == "Random Access Memories" and n["auteurs"] == ["Daft Punk"] and n["support"] == "cd"
    assert n["annee"] == 2013 and "Disco" in n["sujets"] and n["lien"].startswith("https://www.discogs.com/")


def test_parser_deezer():
    n = deezer.parse(fixture("deezer_album.json"), "0724384960650")
    assert n["titre"] == "Discovery" and n["auteurs"] == ["Daft Punk"] and n["sujets"] == ["Electro"]
    assert n["pistes"][0] == {"titre": "One More Time", "duree": 320, "disque": 1} and n["annee"] == 2001
    assert deezer.parse('{"error": {"code": 800}}', RAM) is None


def test_parser_itunes():
    n = itunes.parse(fixture("itunes_album.json"), RAM)
    assert n["titre"] == "Random Access Memories" and len(n["pistes"]) == 13
    assert "600x600" in n["couverture_url"] and n["support"] is None


def test_parser_upcitemdb_nettoie_le_titre():
    n = upcitemdb.parse(fixture("upcitemdb.json"), "5050582721478")
    assert n["titre"] == "Fast And Furious 2" and n["support"] == "dvd"
    assert upcitemdb.titre_propre("Amélie [Blu-ray] (2001)") == "Amélie"


def test_parser_sudoc_donne_le_dewey_de_la_fiction():
    n = sudoc.parse(fixture("sudoc_notice.xml"), "9782070360024")
    assert n["titre"] == "L'étranger" and n["auteurs"] == ["Albert Camus"] and n["classes"]["dewey"] == "843"
    assert n["forme"] == "fiction" and n["lien"] == "https://www.sudoc.fr/001896431"
    assert sudoc.parse("pas du xml", None) is None


@pytest.mark.parametrize("module,fichier", [(k10plus, "k10plus.xml"), (dnb, "dnb.xml")])
def test_parser_marc_allemand(module, fichier):
    n = module.parse(fixture(fichier), "9783518368459")
    assert n["titre"] and n["auteurs"] and n["langue"] == "ger"


def test_parsers_films_sur_le_format_documente():
    """Sans clé ici : ces deux réponses suivent la documentation de TMDb et d'OMDb, ce ne sont pas de vraies réponses."""
    t = tmdb.parse('{"id": 194, "title": "Le Fabuleux Destin d\'Amélie Poulain", "original_title": "Le Fabuleux Destin d\'Amélie Poulain", '
                   '"release_date": "2001-04-25", "runtime": 122, "overview": "Amélie…", "original_language": "fr", "poster_path": "/a.jpg", '
                   '"genres": [{"name": "Comédie"}], "credits": {"crew": [{"job": "Director", "name": "Jean-Pierre Jeunet"}]}}', None)
    assert t["auteurs"] == ["Jean-Pierre Jeunet"] and t["duree"] == 122 and t["annee"] == 2001 and t["langue"] == "fre"
    assert t["couverture_url"].endswith("/a.jpg") and t["support"] == "dvd"
    o = omdb.parse('{"Response": "True", "Title": "Amelie", "Year": "2001", "Runtime": "122 min", "Director": "Jean-Pierre Jeunet", '
                   '"Plot": "Amelie…", "Genre": "Comedy, Romance", "Poster": "N/A", "imdbID": "tt0211915"}', None)
    assert o["titre"] == "Amelie" and o["duree"] == 122 and o["sujets"] == ["Comedy", "Romance"] and o["couverture_url"] is None
    assert omdb.parse('{"Response": "False", "Error": "Movie not found!"}', None) is None


def _reponse(conn, notice_id, source, fichier):
    conn.execute("INSERT OR REPLACE INTO raw_responses(notice_id, source, statut, payload, recu_le) VALUES (?, ?, 'ok', ?, ?)",
                 (notice_id, source, fixture(fichier), db.now()))
    conn.commit()


def test_un_disque_complet(conn):
    services.ajouter(conn, RAM)
    notice_id = db.id_notice(conn, RAM)
    _reponse(conn, notice_id, "musicbrainz", "mb_release.json")
    _reponse(conn, notice_id, "discogs", "discogs_recherche.json")
    n = resolver.rebuild(conn, notice_id)
    assert n["statut"] == "trouve" and n["support"] == "cd" and n["titre"] == "Random Access Memories"
    assert n["sources"] == ["musicbrainz", "discogs"] and len(n["pistes"]) == 13
    assert services.rechercher(conn, "Give Life Back")[1] == 1           # les pistes sont cherchables
    assert services.rechercher(conn, support="musique")[1] == 1 and services.rechercher(conn, support="livre")[1] == 0


def test_boutique_seule_vaut_un_cd(conn):
    services.ajouter(conn, RAM)
    notice_id = db.id_notice(conn, RAM)
    _reponse(conn, notice_id, "itunes", "itunes_album.json")
    assert resolver.rebuild(conn, notice_id)["support"] == "cd"


def test_cotes_de_la_musique_et_des_films():
    musique = calculer({"support": "cd", "sujets": ["Jazz"], "titre": "x"})
    assert musique["dewey"]["code"] == "781.65" and musique["lcc"]["code"] == "M" and musique["rayon"]["abbr"] == "MUS"
    assert musique["clil"] is None and musique["thema"] is None and musique["cadre_bnf"] is None
    film = calculer({"support": "bluray", "sujets": [], "titre": "x"})
    assert film["dewey"]["code"] == "791.43" and film["rayon"]["abbr"] == "FILM"
    assert calculer({"support": "inconnu", "sujets": [], "titre": "x"})["dewey"] is None


def test_chaine_d_un_disque_s_arrete_au_premier_titre(conn, monkeypatch):
    from biblio.sources import Fetched

    services.ajouter(conn, RAM)
    appels = []
    def faux(module, fichier=None):
        def fetch(client, code, *args):
            appels.append(module.NAME)
            return Fetched("ok", fixture(fichier)) if fichier else Fetched("absent", "{}")
        monkeypatch.setattr(module, "fetch", fetch)
    faux(musicbrainz, "mb_release.json")
    for m in (discogs, deezer, itunes, upcitemdb, tmdb, omdb):
        faux(m)
    assert resolver.fetch_sources(conn, None, RAM) == []
    assert appels == ["musicbrainz"]                     # tout est là : ni Discogs, ni Deezer, ni iTunes, ni films


def test_chaine_sans_cle_ne_demande_pas_les_films(conn, monkeypatch):
    from biblio.sources import Fetched

    services.ajouter(conn, "5050582721478")
    appels = []
    def faux(module, fichier=None):
        def fetch(client, code, *args):
            appels.append((module.NAME, code))
            return Fetched("ok", fixture(fichier)) if fichier else Fetched("absent", "{}")
        monkeypatch.setattr(module, "fetch", fetch)
    for m in (musicbrainz, discogs, deezer, itunes):
        faux(m)
    faux(upcitemdb, "upcitemdb.json")
    faux(tmdb)
    resolver.fetch_sources(conn, None, "5050582721478")
    assert ("upcitemdb", "5050582721478") in appels and not any(n == "tmdb" for n, _ in appels)
    db.set_meta(conn, "tmdb_api_key", "cle")
    resolver.fetch_sources(conn, None, "5050582721478")
    assert ("tmdb", "Fast And Furious 2") in appels


def test_catalogue_desactive_jamais_interroge(conn, monkeypatch):
    from biblio import sante
    from biblio.sources import Fetched

    services.ajouter(conn, RAM)
    sante.activer(conn, "musicbrainz", False)
    appels = []
    monkeypatch.setattr(musicbrainz, "fetch", lambda *a: appels.append("mb") or Fetched("absent"))
    for m in (discogs, deezer, itunes, upcitemdb):
        monkeypatch.setattr(m, "fetch", lambda *a: Fetched("absent", "{}"))
    resolver.fetch_sources(conn, None, RAM)
    assert not appels


def test_export_et_partage_d_un_disque(conn, tmp_path):
    services.ajouter(conn, RAM)
    notice_id = db.id_notice(conn, RAM)
    _reponse(conn, notice_id, "musicbrainz", "mb_release.json")
    resolver.rebuild(conn, notice_id)
    entetes, lignes = export.lignes(conn)
    ligne = dict(zip(entetes, lignes[0]))
    assert ligne["EAN"] == RAM and ligne["Support"] == "CD" and ligne["ISBN"] is None
    fichier = tmp_path / "partage.db"
    partage.exporter_partage(conn, fichier)
    ami = db.connect(tmp_path / "ami.db")
    partage.importer_ami(ami, fichier, comme="Victor")
    n = services.notice(ami, RAM)
    assert n["support"] == "cd" and len(n["pistes"]) == 13
    ami.close()
