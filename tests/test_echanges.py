"""Fichiers pour les applis de lecture : exports Goodreads et Babelio, import du CSV de Babelio."""

import base64
import csv
import io

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from biblio import babelio, db, export, services
from biblio.cli import app as cli
from biblio.services import Erreur
from biblio.web.app import app

from .conftest import charger

CHANSON = "9782070196678"
ASTERIX = "9782014001143"
AUTRE = "9782253140870"
ENTETE = '"ISBN";"Titre";"Auteur";"Editeur";"Date de publication";"Date d`entrée dans Babelio";"Statut";"Note"\r\n'


def livre(conn, isbn, titre, auteurs, **champs):
    services.ajouter(conn, isbn)
    services.modifier_notice(conn, isbn, {"titre": titre, "auteurs": auteurs, **champs})


def export_babelio(*lignes, encodage="cp1252") -> bytes:
    """Comme le vrai fichier : cp1252, points-virgules, tout entre guillemets, CRLF."""
    corps = "".join(";".join(f'"{c}"' for c in ligne) + "\r\n" for ligne in lignes)
    return (ENTETE + corps).encode(encodage)


def ligne(isbn, titre="Un titre", auteur="Quelqu'un", statut="Lu", note="0.0"):
    return [isbn, titre, auteur, "Gallimard", "2005-06-30", "2026-11-03 09:28:11", statut, note]


def lire_goodreads(conn, **kw):
    return list(csv.DictReader(io.StringIO(export.goodreads_csv(conn, **kw).decode("utf-8"))))


@pytest.fixture
def biblio(conn):
    livre(conn, CHANSON, "Chanson douce", "Leïla Slimani ; Autre Personne", editeur="Gallimard", pages=240, annee=2016,
          lecture="lu", lecture_fin="2024-03-09", etoiles=4, notes="secretnote")
    livre(conn, ASTERIX, "Astérix", "René Goscinny")
    return conn


# --- Export Goodreads ------------------------------------------------------------

def test_goodreads_comme_le_vrai_format(biblio):
    data = export.goodreads_csv(biblio)
    assert not data.startswith(b"\xef\xbb\xbf")                # les en-têtes doivent être exacts
    assert data.decode().splitlines()[0].startswith("Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,")
    lu, sans_statut = sorted(lire_goodreads(biblio), key=lambda r: r["Title"], reverse=True)
    assert lu["Title"] == "Chanson douce" and lu["Author"] == "Leïla Slimani" and lu["Author l-f"] == "Slimani, Leïla"
    assert lu["Additional Authors"] == "Autre Personne"
    assert lu["ISBN13"] == f'="{CHANSON}"' and lu["ISBN"] == '="2070196674"'
    assert (lu["My Rating"], lu["Exclusive Shelf"], lu["Read Count"], lu["Owned Copies"]) == ("4", "read", "1", "1")
    assert lu["Date Read"] == "2024/03/09" and lu["Date Added"].count("/") == 2 and lu["Book Id"] == ""
    assert (sans_statut["Exclusive Shelf"], sans_statut["My Rating"], sans_statut["Read Count"]) == ("to-read", "0", "0")
    assert (lu["Status"], sans_statut["Status"]) == ("read", "to-read")     # copie d'Exclusive Shelf, pour Hardcover


@pytest.mark.parametrize("lecture,etagere", [("a_lire", "to-read"), ("en_cours", "currently-reading"),
                                             ("abandonne", "did-not-finish")])
def test_goodreads_etageres(biblio, lecture, etagere):
    services.modifier_notice(biblio, ASTERIX, {"lecture": lecture})
    r = next(r for r in lire_goodreads(biblio) if r["Title"] == "Astérix")
    assert r["Exclusive Shelf"] == etagere and r["Status"] == etagere and r["Bookshelves"] == ""


def test_seulement_les_livres_avec_un_etat(biblio):
    assert [r["Title"] for r in lire_goodreads(biblio, avec_statut=True)] == ["Chanson douce"]
    assert export.babelio_csv(biblio, avec_statut=True).decode().count("\n") == 2


def test_rien_de_personnel_ne_part(biblio):
    salon = services.creer_lieu(biblio, "SalonSecret")
    services.ajouter(biblio, CHANSON, salon)
    for data in (export.goodreads_csv(biblio), export.babelio_csv(biblio)):
        assert b"secretnote" not in data
    assert b"salonsecret" not in export.babelio_csv(biblio).lower()


def test_goodreads_lieux_en_etageres(biblio):
    """L'état de lecture reste dans Exclusive Shelf ; Bookshelves ne contient que les lieux, sous leur nom exact."""
    chambre = services.creer_lieu(biblio, "[Maison] - Entrée, haut")
    salon = services.creer_lieu(biblio, "Salon")
    services.ajouter(biblio, CHANSON, chambre)
    services.ajouter(biblio, CHANSON, salon)
    services.ajouter(biblio, CHANSON, salon)                   # deux exemplaires, une seule étagère
    services.ajouter(biblio, ASTERIX, salon)
    lignes = {r["Title"]: r for r in lire_goodreads(biblio)}
    lu, a_lire = lignes["Chanson douce"], lignes["Astérix"]
    assert lu["Bookshelves"] == "[Maison] - Entrée haut, Salon" and lu["Exclusive Shelf"] == "read"
    assert a_lire["Bookshelves"] == "Salon" and a_lire["Exclusive Shelf"] == "to-read"
    sans_lieux = {r["Title"]: r for r in lire_goodreads(biblio, avec_lieux=False)}
    assert sans_lieux["Chanson douce"]["Bookshelves"] == "" and sans_lieux["Chanson douce"]["Exclusive Shelf"] == "read"


def test_goodreads_chemin_complet(biblio):
    """Lieu, étagère et rangée, comme dans l'app ; un exemplaire par emplacement différent."""
    salon = services.creer_lieu(biblio, "[Maison] - Salon")
    bas = services.creer_etagere(biblio, salon, "Bas")
    haut = services.creer_etagere(biblio, salon, "Haut, gauche")
    devant = services.creer_rangee(biblio, bas, "Devant")
    services.ajouter(biblio, CHANSON, salon, bas, rangee_id=devant, filtrer_rebond=False)
    services.ajouter(biblio, CHANSON, salon, haut, filtrer_rebond=False)
    services.ajouter(biblio, CHANSON, salon, filtrer_rebond=False)
    services.ajouter(biblio, ASTERIX, salon, bas, filtrer_rebond=False)
    lignes = {r["Title"]: r for r in lire_goodreads(biblio)}
    assert set(lignes["Chanson douce"]["Bookshelves"].split(", ")) == {
        "[Maison] - Salon", "[Maison] - Salon › Bas › Devant", "[Maison] - Salon › Haut gauche"}
    assert lignes["Astérix"]["Bookshelves"] == "[Maison] - Salon › Bas"


def test_goodreads_tous_mes_lieux_mais_pas_ceux_des_autres(biblio):
    salon = services.creer_lieu(biblio, "Salon")
    chambre = services.creer_lieu(biblio, "Chambre")
    services.ajouter(biblio, CHANSON, salon)
    services.ajouter(biblio, CHANSON, chambre)
    services.ajouter(biblio, AUTRE, salon)
    services.modifier_notice(biblio, AUTRE, {"titre": "Chez un ami", "auteurs": "Un Ami", "lecture": "lu"})
    biblio.execute("INSERT INTO personnes(uid, nom, cle, maj_le) VALUES ('p', 'Victor', 'victor', ?)", (db.now(),))
    biblio.execute("UPDATE exemplaires SET proprietaire_id = (SELECT id FROM personnes WHERE uid = 'p') "
                   "WHERE notice_id = (SELECT id FROM notices WHERE isbn13 = ?)", (AUTRE,))
    lignes = {r["Title"]: r for r in lire_goodreads(biblio, lieux=[salon])}
    assert lignes["Chanson douce"]["Bookshelves"] == "Chambre, Salon"     # le filtre choisit les livres, pas leurs lieux
    assert lignes["Chez un ami"]["Bookshelves"] == ""


def test_selection_des_livres(biblio):
    """Ni disques, ni livres d'un ami que je n'ai pas lus ; un livre d'ami que j'ai lu, si, sans exemplaire à moi."""
    services.modifier_notice(biblio, ASTERIX, {"support": "cd"})
    livre(biblio, AUTRE, "Chez un ami", "Un Ami")
    biblio.execute("INSERT INTO personnes(uid, nom, cle, maj_le) VALUES ('p', 'Victor', 'victor', ?)", (db.now(),))
    biblio.execute("UPDATE exemplaires SET proprietaire_id = (SELECT id FROM personnes WHERE uid = 'p') "
                   "WHERE notice_id = (SELECT id FROM notices WHERE isbn13 = ?)", (AUTRE,))
    assert [r["Title"] for r in lire_goodreads(biblio)] == ["Chanson douce"]
    services.modifier_notice(biblio, AUTRE, {"lecture": "lu"})
    r = next(r for r in lire_goodreads(biblio) if r["Title"] == "Chez un ami")
    assert r["Owned Copies"] == "0"


def test_livre_sans_titre_laisse_de_cote(conn):
    services.ajouter(conn, AUTRE)                  # encore en attente de description
    assert lire_goodreads(conn) == []
    bilan = export.bilan_applis(conn)
    assert (bilan["goodreads"], bilan["sans_titre"], bilan["babelio"]) == (0, 1, 1)


# --- Export Babelio --------------------------------------------------------------

def test_babelio_suit_le_modele(biblio):
    texte = export.babelio_csv(biblio).decode("utf-8")
    assert texte.splitlines()[0] == ("EAN, Statut (Lu/A lire/Wishlist/En cours),Possédé,Ma note,"
                                     "Etagères séparées par virgules,Critique,Date de fin de lecture")
    assert f"{CHANSON},Lu,Oui,4,,,09/03/2024" in texte
    assert f"{ASTERIX},A lire,Oui,,,," in texte


def test_babelio_abandonne_sur_une_etagere(biblio):
    services.modifier_notice(biblio, ASTERIX, {"lecture": "abandonne"})
    assert f"{ASTERIX},En cours,Oui,,abandonné,," in export.babelio_csv(biblio).decode("utf-8")


def test_babelio_sans_code_laisse_de_cote(conn):
    services.creer_notice_manuelle(conn, "Sans code", "Une Personne")
    assert export.babelio_csv(conn).decode().count("\n") == 1
    assert export.bilan_applis(conn)["sans_code"] == 1


# --- Import Babelio --------------------------------------------------------------

def test_lit_le_vrai_format(conn):
    lignes = babelio.lire_csv(export_babelio(ligne(CHANSON, "Les Éléments", "Nerval Gérard de", "En cours", "0.0")))
    assert lignes == [{"isbn": CHANSON, "titre": "Les Éléments", "auteur": "Nerval Gérard de",
                       "statut": "En cours", "note": "0.0"}]


def test_lit_aussi_utf8_virgules_et_entites():
    contenu = 'ISBN,Titre,Auteur,Statut,Note\n123,Caf&eacute; é,X,Lu,3\n'.encode("utf-8-sig")
    assert babelio.lire_csv(contenu)[0]["titre"] == "Café é"


@pytest.mark.parametrize("contenu", [b"", b"  \r\n", b'"Livre";"Critique"\r\n"a";"b"\r\n'])
def test_fichier_refuse(conn, contenu):
    with pytest.raises(Erreur):
        babelio.importer(conn, contenu)


def test_import_remplit_le_vide(biblio):
    r = babelio.importer(biblio, export_babelio(ligne(ASTERIX, statut="En cours", note="4.0")))
    n = services.notice(biblio, ASTERIX)
    assert (n["lecture"], n["etoiles"]) == ("en_cours", 4) and (r["statuts"], r["notes"]) == (1, 1)
    assert not n["corrections"]["lecture"]["manuel"] and "le" in n["corrections"]["etoiles"]   # la synchronisation suit


@pytest.mark.parametrize("statut,attendu", [("Lu", "lu"), ("En cours", "en_cours"), ("À lire", "a_lire"), ("A lire", "a_lire"),
                                            ("Abandonné", "abandonne"), ("Pense-bête", "a_lire"), ("Wishlist", "a_lire")])
def test_statuts(biblio, statut, attendu):
    babelio.importer(biblio, export_babelio(ligne(ASTERIX, statut=statut)))
    assert services.notice(biblio, ASTERIX)["lecture"] == attendu


def test_statut_inconnu_signale(biblio):
    r = babelio.importer(biblio, export_babelio(ligne(ASTERIX, statut="Bizarre")))
    assert r["statuts_inconnus"] == ["Bizarre"] and services.notice(biblio, ASTERIX)["lecture"] is None


@pytest.mark.parametrize("note,etoiles,arrondie", [("0.0", None, 0), ("", None, 0), ("abc", None, 0), ("7", None, 0),
                                                   ("3.5", 4, 1), ("3,5", 4, 1), ("0.5", 1, 1), ("5.0", 5, 0)])
def test_notes(biblio, note, etoiles, arrondie):
    r = babelio.importer(biblio, export_babelio(ligne(ASTERIX, note=note)))
    assert services.notice(biblio, ASTERIX)["etoiles"] == etoiles and r["arrondies"] == arrondie


def test_note_zero_n_efface_rien(biblio):
    babelio.importer(biblio, export_babelio(ligne(CHANSON, note="0.0")), ecraser=True)
    assert services.notice(biblio, CHANSON)["etoiles"] == 4


def test_desaccord_garde_ma_base_sauf_si_on_ecrase(biblio):
    contenu = export_babelio(ligne(CHANSON, statut="En cours", note="2.0"))
    r = babelio.importer(biblio, contenu)
    n = services.notice(biblio, CHANSON)
    assert (n["lecture"], n["etoiles"]) == ("lu", 4) and {d["champ"] for d in r["desaccords"]} == {"lecture", "etoiles"}
    assert (r["statuts"], r["notes"], r["a_jour"]) == (0, 0, 0)
    r = babelio.importer(biblio, contenu, ecraser=True)
    n = services.notice(biblio, CHANSON)
    assert (n["lecture"], n["etoiles"]) == ("en_cours", 2) and not r["desaccords"] and (r["statuts"], r["notes"]) == (1, 1)


def test_simulation_n_ecrit_rien_et_relance_sans_effet(biblio):
    contenu = export_babelio(ligne(ASTERIX, statut="Lu", note="3.0"))
    apercu = babelio.importer(biblio, contenu, simulation=True)
    assert (apercu["statuts"], apercu["notes"]) == (1, 1) and services.notice(biblio, ASTERIX)["lecture"] is None
    assert babelio.importer(biblio, contenu)["statuts"] == 1
    r = babelio.importer(biblio, contenu)
    assert (r["statuts"], r["notes"], r["a_jour"], r["desaccords"]) == (0, 0, 1, [])


def test_livre_absent_ignore_et_liste(biblio):
    avant = biblio.execute("SELECT count(*) FROM notices").fetchone()[0]
    r = babelio.importer(biblio, export_babelio(ligne(AUTRE, "Pas ici", "Personne")))
    assert r["absents"] == [{"isbn": AUTRE, "titre": "Pas ici", "auteur": "Personne"}]
    assert biblio.execute("SELECT count(*) FROM notices").fetchone()[0] == avant


def test_un_numero_de_notice_ne_passe_pas_pour_un_isbn(biblio):
    """db.id_notice prend aussi les petits numéros : un ISBN de Babelio mal formé ne doit pas tomber sur la notice 1."""
    r = babelio.importer(biblio, export_babelio(ligne("1", "Pas ici", "Personne", statut="En cours")))
    assert len(r["absents"]) == 1 and services.notice(biblio, CHANSON)["lecture"] == "lu"


def test_isbn10_reconnu(biblio):
    babelio.importer(biblio, export_babelio(ligne("2014001143"[:9] + "X", statut="Lu")))     # clé fausse : absent
    assert services.notice(biblio, ASTERIX)["lecture"] is None
    babelio.importer(biblio, export_babelio(ligne("2070196674", statut="Lu", note="4.0")), ecraser=True)
    assert services.notice(biblio, CHANSON)["etoiles"] == 4


def test_autre_edition_par_titre_et_auteur(biblio):
    """Babelio écrit l'auteur « Nom Prénom » ; un seul livre doit correspondre."""
    livre(biblio, AUTRE, "Les Filles du feu", "Gérard de Nerval")
    r = babelio.importer(biblio, export_babelio(ligne("9782070314799", "Les filles du feu", "Nerval Gérard de", "En cours")))
    assert r["par_titre"] == 1 and services.notice(biblio, AUTRE)["lecture"] == "en_cours"


def test_titre_ambigu_reste_absent(biblio):
    livre(biblio, AUTRE, "Astérix", "René Goscinny")
    r = babelio.importer(biblio, export_babelio(ligne("9782070314799", "Astérix", "Goscinny René")))
    assert r["par_titre"] == 0 and len(r["absents"]) == 1


def test_deux_editions_babelio_pour_un_livre(biblio):
    r = babelio.importer(biblio, export_babelio(ligne(ASTERIX, "Astérix", "Goscinny René", "En cours"),
                                                ligne("9782070314799", "Astérix", "Goscinny René", "Lu")))
    assert services.notice(biblio, ASTERIX)["lecture"] == "en_cours" and r["statuts"] == 1 and not r["desaccords"]


# --- Ligne de commande ------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def base_cli(tmp_path, monkeypatch):
    chemin = tmp_path / "cli.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    livre(conn, ASTERIX, "Astérix", "René Goscinny")
    yield conn
    conn.close()


def test_cli_exports(base_cli, tmp_path):
    for format, debut in (("goodreads", b"Book Id,"), ("babelio", b"EAN, Statut")):
        fichier = tmp_path / f"{format}.csv"
        r = runner.invoke(cli, ["export", "-f", format, "-o", str(fichier)])
        assert r.exit_code == 0 and "1 book(s)" in r.output, r.output
        assert fichier.read_bytes().startswith(debut)
    assert "2 book" not in runner.invoke(cli, ["export", "-f", "babelio", "--only-with-status", "-o", str(fichier)]).output


def test_cli_export_nom_par_defaut(base_cli, tmp_path):
    runner.invoke(cli, ["export", "-f", "goodreads"])
    assert list((tmp_path / "exports").glob("library-*-goodreads.csv"))


def test_cli_only_with_status_refuse_ailleurs(base_cli, tmp_path):
    assert runner.invoke(cli, ["export", "-f", "csv", "--only-with-status", "-o", str(tmp_path / "a.csv")]).exit_code == 1


def test_cli_import_babelio(base_cli, tmp_path):
    fichier = tmp_path / "babelio.csv"
    fichier.write_bytes(export_babelio(ligne(ASTERIX, statut="Lu", note="3.5"), ligne(AUTRE, "Pas ici", "Personne")))

    r = runner.invoke(cli, ["import-babelio", str(fichier), "--dry-run"])
    assert r.exit_code == 0 and "Dry run" in r.output and "Pas ici" in r.output and "not in this library" in r.output
    assert services.notice(base_cli, ASTERIX)["lecture"] is None

    r = runner.invoke(cli, ["import-babelio", str(fichier), "--yes"])
    assert r.exit_code == 0 and "imported" in r.output, r.output
    n = services.notice(base_cli, ASTERIX)
    assert (n["lecture"], n["etoiles"]) == ("lu", 4) and (tmp_path / "cli-avant-babelio.db").exists()

    r = runner.invoke(cli, ["import-babelio", str(fichier), "--yes"])
    assert "Nothing to import" in r.output


def test_cli_import_babelio_erreurs(base_cli, tmp_path):
    assert runner.invoke(cli, ["import-babelio", str(tmp_path / "absent.csv")]).exit_code == 1
    vide = tmp_path / "Critiques_export.csv"
    vide.write_bytes(b"")
    r = runner.invoke(cli, ["import-babelio", str(vide)])
    assert r.exit_code == 1 and "Traceback" not in r.output and "vide" in r.output


# --- Site -------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    livre(conn, ASTERIX, "Astérix", "René Goscinny")
    c = TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost", follow_redirects=False)
    c.conn = conn
    yield c
    conn.close()


def envoyer(client, contenu, **data):
    return client.post("/echanges/babelio", files={"fichier": ("biblio.csv", contenu, "text/csv")}, data=data)


def test_site_telecharge_les_exports(client):
    for fmt, debut in (("goodreads", b"Book Id,"), ("babelio", b"EAN, Statut")):
        r = client.get(f"/export.{fmt}")
        assert r.status_code == 200 and r.content.startswith(debut) and f"-{fmt}.csv" in r.headers["content-disposition"]
    assert client.get("/export.goodreads?statut=1").content.count(b"\n") == 1
    assert client.get("/export.inconnu").status_code == 404


def test_site_page_et_liens(client):
    page = client.get("/echanges").text
    assert 'action="/echanges/babelio"' in page and 'formaction="/export.goodreads"' in page
    assert 'href="/echanges"' in client.get("/catalogue").text and 'href="/echanges"' in client.get("/reglages").text


def test_site_apercu_puis_application(client, tmp_path):
    r = envoyer(client, export_babelio(ligne(ASTERIX, statut="Lu", note="3.5"), ligne(AUTRE, "Pas ici", "Personne")))
    assert r.status_code == 200 and "Pas ici" in r.text and 'name="contenu"' in r.text
    assert services.notice(client.conn, ASTERIX)["lecture"] is None      # l'aperçu n'écrit rien

    contenu = base64.b64encode(export_babelio(ligne(ASTERIX, statut="Lu", note="3.5"))).decode()
    r = client.post("/echanges/babelio/appliquer", data={"contenu": contenu})
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    n = services.notice(client.conn, ASTERIX)
    assert (n["lecture"], n["etoiles"]) == ("lu", 4) and (tmp_path / "web-avant-babelio.db").exists()
    assert client.conn.execute("SELECT 1 FROM journal WHERE action = 'import_babelio'").fetchone()


def test_site_desaccord_et_case_a_cocher(client):
    services.modifier_notice(client.conn, ASTERIX, {"lecture": "lu"})
    fichier = export_babelio(ligne(ASTERIX, statut="En cours"))
    r = envoyer(client, fichier)
    assert "Rien à importer" in r.text and "Désaccords (1)" in r.text and "Appliquer" not in r.text
    r = envoyer(client, fichier, ecraser="1")
    assert 'name="ecraser"' in r.text and "Appliquer" in r.text
    client.post("/echanges/babelio/appliquer", data={"contenu": base64.b64encode(fichier).decode(), "ecraser": "1"})
    assert services.notice(client.conn, ASTERIX)["lecture"] == "en_cours"


def test_site_refuse_les_mauvais_fichiers(client):
    for contenu in (b"", b'"Livre"\r\n"a"\r\n', b"x" * (5 * 1024 * 1024 + 1)):
        r = envoyer(client, contenu)
        assert r.status_code == 303 and "err=" in r.headers["location"]
    r = client.post("/echanges/babelio/appliquer", data={"contenu": "pas du base64 !"})
    assert r.status_code == 303 and "err=" in r.headers["location"]


def test_site_gros_fichier_jusqu_au_bout(client):
    """Starlette plafonne les champs texte à 1 Mo : le fichier qui revient de l'aperçu peut dépasser."""
    gros = export_babelio(ligne(ASTERIX, statut="Lu"), *[ligne(AUTRE, "Pas ici " + "x" * 300, "Personne")] * 8000)
    assert 1024 * 1024 < len(base64.b64encode(gros)) and len(gros) < 5 * 1024 * 1024
    assert envoyer(client, gros).status_code == 200
    r = client.post("/echanges/babelio/appliquer", data={"contenu": base64.b64encode(gros).decode()})
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert services.notice(client.conn, ASTERIX)["lecture"] == "lu"


def test_site_en_anglais(client):
    client.post("/langue", data={"langue": "en"})
    page = client.get("/echanges").text
    assert "Reading apps" in page and "Applis de lecture" not in page and "Télécharger" not in page


def test_site_case_des_lieux(tmp_path, monkeypatch):
    """Cochée d'origine ; décochée, le navigateur n'envoie rien et Bookshelves reste vide."""
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    livre(conn, CHANSON, "Chanson douce", "Leïla Slimani")
    services.ajouter(conn, CHANSON, services.creer_lieu(conn, "Salon"))
    client = TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost")
    page = client.get("/echanges").text
    assert 'name="avec_lieux" value="1" checked>' in page
    assert page.index('name="avec_lieux"') < page.index("/export.goodreads")   # l'option précède le bouton
    assert b"Salon" in client.get("/export.goodreads?avec_lieux=1").content
    assert b"Salon" not in client.get("/export.goodreads").content
    assert b"Salon" not in client.get("/export.babelio?avec_lieux=1").content
    conn.close()


def test_page_applis_annonce_l_effet_de_l_option(tmp_path, monkeypatch):
    """Sans aucun état de lecture, l'option donnerait un fichier vide : la page le sait et peut le dire."""
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    services.ajouter(conn, "9782070196678")
    charger(conn, "9782070196678", bnf="bnf_chanson_douce.xml")
    page = TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost").get("/echanges").text
    assert "(0 sur 1)" in page and "1 livre." in page and "(s)" not in page
    assert 'name="statut" value="1" id="option-statut">' in page            # la case reste cochable
    assert 'formaction="/export.goodreads" data-nb-statut="0"' in page
    assert 'data-statut="0 livre."' in page and 'data-tous="1 livre."' in page
    assert page.index('name="statut"') < page.index("/export.goodreads")   # l'option précède les boutons
    conn.close()
