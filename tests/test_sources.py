import httpx
import pytest

from biblio import resolver
from biblio.resolver import merge
from biblio.sources import bnf, loc, openlibrary

from .conftest import charger, fixture


def test_bnf_roman():
    n = bnf.parse(fixture("bnf_chanson_douce.xml"), "9782070196678")
    assert n["titre"] == "Chanson douce"
    assert n["sous_titre"] is None                      # « roman » est un genre, pas un sous-titre
    assert n["auteurs"] == ["Leïla Slimani"]
    assert n["auteurs_tri"] == ["SLIMANI Leïla"]
    assert (n["editeur"], n["annee"], n["pages"]) == ("Gallimard", 2016, 226)
    assert n["forme"] == "fiction"
    assert n["public"] == "adulte"
    assert n["classes"] == {"cadre_bnf": "803"}          # pas de Dewey pour la fiction à la BnF


def test_bnf_documentaire_avec_dewey():
    n = bnf.parse(fixture("bnf_vargas.xml"), "9782290382608")
    assert n["classes"]["dewey"] == "363.7009052"
    assert n["classes"]["cadre_bnf"] == "360"
    assert n["forme"] == "documentaire"
    assert any("environnement" in s.lower() for s in n["sujets"])


def test_bnf_choisit_le_texte_imprime():
    n = bnf.parse(fixture("bnf_sapiens.xml"), "9782286123949")
    assert n["classes"]["dewey"] == "909"               # et non l'enregistrement sonore


def test_bnf_collections_multiples():
    n = bnf.parse(fixture("bnf_pur_sang.xml"), "9782253248545")
    assert n["collection"] == "La marche du rêveur ; tome 1 | Le livre de poche ; 37157"


def test_bnf_vieux_catalogage_public_corrige():
    n = bnf.parse(fixture("bnf_etranger.xml"), "9782070360024")
    assert n["public"] == "adulte"                      # codes d/e mais cadre ≠ 809


def test_openlibrary():
    n = openlibrary.parse(fixture("ol_algorithms.json"), "9780262033848")
    assert n["titre"] == "Introduction to Algorithms"
    assert n["auteurs_tri"][0] == "CORMEN Thomas H."
    assert n["classes"] == {"dewey": "005.1", "lcc": "QA76.6 .I5858 2009"}
    assert n["couverture_url"].startswith("https://covers.openlibrary.org/")


def test_loc():
    n = loc.parse(fixture("loc_algorithms.xml"), "9780262033848")
    assert n["langue"] == "eng"
    assert n["classes"]["dewey"] == "005.1"
    assert n["classes"]["lcc"].startswith("QA76.6")


def test_fusion_priorites():
    records = {
        "openlibrary": openlibrary.parse(fixture("ol_algorithms.json"), "9780262033848"),
        "loc": loc.parse(fixture("loc_algorithms.xml"), "9780262033848"),
    }
    m = merge(records)
    assert m["titre"] == "Introduction to Algorithms"   # Open Library passe avant la LoC
    assert m["classes"]["lcc"] == records["loc"]["classes"]["lcc"]   # LCC : la LoC fait foi
    assert m["langue"] == "eng"                         # complété par la LoC
    assert m["sources"] == ["openlibrary", "loc"]


def test_bnf_recherche_titre_auteur():
    from biblio.sources import bnf

    resultats = bnf.lire_resultats(fixture("bnf_recherche_meaulnes.xml"))
    assert len(resultats) == 4 and all(r["ark"].startswith("ark:/12148/") for r in resultats)
    assert all(r["auteurs"] == ["Alain-Fournier"] and r["annee"] == 1946 for r in resultats)
    n = bnf.parse(bnf.reponse_unique(resultats[0]["xml"]), None)
    assert n["titre"] == resultats[0]["titre"] and n["couverture_url"] is None


@pytest.mark.parametrize("texte, attendu", [
    ("345 p.", 345), ("345 pages", 345), ("xii, 345 pages ;", 345), ("1 vol. (345 p.)", 345), ("345p", 345),
    ("345 pp.", 345), ("[12] p.", 12), (345, 345), (None, None), ("illustrations", None),
])
def test_nombre_de_pages(texte, attendu):
    from biblio.sources import pages_of

    assert pages_of(texte) == attendu


class Panne:
    """Client HTTP dont toutes les requêtes échouent."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *a, **kw):
        raise httpx.ConnectError("réseau coupé")


def test_panne_pendant_une_relance_ne_vide_pas_la_fiche(conn):
    from biblio import services

    services.ajouter(conn, "9782070196678")
    charger(conn, "9782070196678", bnf="bnf_chanson_douce.xml")
    n = resolver.resolve(conn, Panne(), "9782070196678", refresh=True)
    assert n["titre"] == "Chanson douce" and n["statut"] == "trouve"
    assert services.notice(conn, "9782070196678")["classifications"][0]["cote"]
    statut = conn.execute("SELECT statut FROM raw_responses WHERE source = 'bnf'").fetchone()
    assert statut[0] == "ok"


def test_reponse_absente_n_efface_pas_une_reponse_valide(conn):
    from biblio import services
    from biblio.sources import Fetched

    notice_id, _ = services.creer_notice_attente(conn, "9782070196678")
    resolver._store(conn, notice_id, "bnf", Fetched("ok", "bon"))
    resolver._store(conn, notice_id, "bnf", Fetched("absent", "rien"))
    assert conn.execute("SELECT payload FROM raw_responses").fetchone()[0] == "bon"
    resolver._store(conn, notice_id, "bnf", Fetched("ok", "mieux"))
    assert conn.execute("SELECT payload FROM raw_responses").fetchone()[0] == "mieux"


def test_sans_isbn_jamais_envoye_aux_catalogues(conn):
    from biblio import services

    res = services.creer_notice_manuelle(conn, "Carnet", "Camille Dupont")
    assert resolver.fetch_sources(conn, Panne(), res["notice_id"], refresh=True) == []
    assert not conn.execute("SELECT 1 FROM raw_responses").fetchone()


class Reponse:
    def __init__(self, statut, contenu=b"", type_="image/jpeg"):
        self.status_code, self.content, self.headers = statut, contenu, {"content-type": type_}


class FauxClient:
    def __init__(self, reponses):
        self.reponses, self.demandes = reponses, []

    def get(self, url, **kw):
        self.demandes.append(url)
        reponse = self.reponses[url]
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


@pytest.fixture
def sans_attente(monkeypatch):
    from biblio import covers
    from biblio.sources import RateLimiter

    monkeypatch.setattr(covers, "limiter", RateLimiter(0))
    return covers


def test_couverture_essaie_l_url_suivante(sans_attente):
    covers = sans_attente
    client = FauxClient({"https://a/1.jpg": Reponse(404), "https://b/2.jpg": Reponse(200, b"x" * 2000)})
    assert covers.telecharger(client, "9782070196678", ["https://a/1.jpg", "https://b/2.jpg"])
    assert covers.chemin("9782070196678").exists() and not covers.absente("9782070196678").exists()
    client.demandes.clear()
    assert covers.telecharger(client, "9782070196678", ["https://a/1.jpg"])        # déjà là : aucune requête
    assert client.demandes == []


def test_couverture_absente_seulement_si_toutes_ont_repondu(sans_attente):
    covers = sans_attente
    client = FauxClient({"https://a/1.jpg": Reponse(404), "https://b/2.jpg": httpx.ConnectError("coupé")})
    assert not covers.telecharger(client, "9782070196678", ["https://a/1.jpg", "https://b/2.jpg"])
    assert not covers.absente("9782070196678").exists()                            # réessayée plus tard
    client = FauxClient({"https://a/1.jpg": Reponse(404), "https://b/2.jpg": Reponse(200, b"x", "text/html")})
    assert not covers.telecharger(client, "9782070196678", ["https://a/1.jpg", "https://b/2.jpg"])
    assert covers.absente("9782070196678").exists()


def test_couverture_url_mal_formee_ne_plante_pas(sans_attente):
    covers = sans_attente
    client = FauxClient({"http://[mauvaise": httpx.InvalidURL("mauvaise")})
    assert not covers.telecharger(client, "9782070196678", "http://[mauvaise")


def test_couverture_forcee_garde_l_image_si_le_catalogue_n_en_a_plus(sans_attente):
    covers = sans_attente
    covers.DOSSIER.mkdir(parents=True)
    covers.chemin("9782070196678").write_bytes(b"image")
    client = FauxClient({"https://a/1.jpg": Reponse(404)})
    assert covers.telecharger(client, "9782070196678", "https://a/1.jpg", forcer=True)
    assert covers.chemin("9782070196678").read_bytes() == b"image" and not covers.absente("9782070196678").exists()


def test_urls_de_couverture_par_ordre_de_preference(conn):
    import json

    from biblio import services

    isbn = "9782070196678"
    notice_id = services.ajouter(conn, isbn)["notice_id"]
    for source, payload in (("bnf", fixture("bnf_chanson_douce.xml")),
                            ("google", json.dumps({"items": [{"volumeInfo": {"title": "T", "imageLinks": {"thumbnail": "http://g/c.jpg"}}}]}))):
        conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                     "VALUES (?, ?, 'ok', ?, '2026-01-01')", (notice_id, source, payload))
    conn.commit()
    resolver.rebuild(conn, isbn)
    urls = resolver.urls_couverture(conn, isbn)
    assert urls[0] == "https://g/c.jpg" and urls[1].startswith("https://covers.openlibrary.org/")
    services.modifier_notice(conn, isbn, {"couverture_url": "https://perso/c.jpg"})
    assert resolver.urls_couverture(conn, isbn) == ["https://perso/c.jpg"]          # choisie à la main : elle seule
