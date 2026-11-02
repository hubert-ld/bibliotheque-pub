import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biblio import db, i18n, services
from biblio.classify import SYSTEMES
from biblio.traductions import EN

RACINE = Path(__file__).resolve().parent.parent / "biblio"


def cles_utilisees() -> dict[str, str]:
    """Toutes les phrases passées à tr()/_() dans le code, les gabarits et les scripts."""
    cles = {}
    for f in RACINE.rglob("*.py"):
        for c in re.findall(r'\btr\(\s*"((?:[^"\\]|\\.)*)"', f.read_text()):
            cles.setdefault(c, f.name)
    for f in (RACINE / "web" / "templates").glob("*.html"):
        texte = f.read_text()
        for c in re.findall(r'\b_\(\s*"((?:[^"\\]|\\.)*)"', texte) + re.findall(r"\b_\(\s*'((?:[^'\\]|\\.)*)'", texte):
            cles.setdefault(c, f.name)
    for c in i18n.cles_js():
        cles.setdefault(c, "js")
    return cles


def test_toutes_les_phrases_ont_leur_traduction():
    manquantes = {c: ou for c, ou in cles_utilisees().items() if c not in EN}
    assert not manquantes, f"Traductions anglaises manquantes : {manquantes}"


def test_noms_dynamiques_traduits():
    from biblio.export import COLONNES
    from biblio.web.app import STATUTS

    from biblio.services import NOMS_FORMES, NOMS_LANGUES

    for nom in [*SYSTEMES.values(), *STATUTS.values(), *(titre for _, titre in COLONNES),
                *NOMS_LANGUES.values(), *NOMS_FORMES.values(), "Inconnue", "Non précisée"]:
        assert nom in EN, nom


def test_memes_variables_dans_les_deux_langues():
    for fr, en in EN.items():
        assert set(re.findall(r"\{(\w+)\}", fr)) == set(re.findall(r"\{(\w+)\}", en)), fr


def test_tr_et_langue_par_defaut():
    i18n.utiliser("fr")
    assert i18n.tr("lieu inconnu : « {nom} »", nom="Salon") == "lieu inconnu : « Salon »"
    i18n.utiliser("en")
    assert i18n.tr("lieu inconnu : « {nom} »", nom="Salon") == "unknown place: “Salon”"
    i18n.utiliser("xx")                                   # langue inconnue -> français
    assert i18n.langue() == "fr"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIO_DB", str(tmp_path / "web.db"))
    conn = db.connect(tmp_path / "web.db")
    services.creer_lieu(conn, "Salon")
    conn.close()
    return TestClient(app_web(), client=("127.0.0.1", 1), base_url="http://localhost")


def app_web():
    from biblio.web.app import app
    return app


def test_interface_en_francais_par_defaut(client):
    page = client.get("/scan").text
    assert '<html lang="fr">' in page and "Poste de scan" in page
    assert '"I18N = {}' not in page and "window.I18N = {};" in page


@pytest.mark.parametrize("url", ["/scan", "/catalogue", "/lieux", "/a-traiter", "/prets", "/stats",
                                 "/reglages", "/manuel", "/telephone", "/lieux/1/rangement"])
def test_interface_en_anglais(client, url):
    r = client.post("/langue", data={"langue": "en", "suite": url}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == url
    page = client.get(url).text
    assert '<html lang="en">' in page
    for francais in ("Réglages", "Statistiques", "Catalogue des", "Non localisé", "Enregistrer", "Rechercher"):
        assert francais not in page, (url, francais)


def test_scripts_et_messages_en_anglais(client):
    client.post("/langue", data={"langue": "en"})
    page = client.get("/scan").text
    import json
    textes = json.loads(re.search(r"window\.I18N = (\{.*?\});", page).group(1))
    assert textes["Ajouté"] == "Added"                       # textes des scripts envoyés traduits
    res = client.post("/api/scan", json={"mode": "ajout", "code": "123"}).json()
    assert "ISBN" in res["message"] and "caractères" not in res["message"]
    r = client.post("/catalogue/lot", data={"action": "deplacer"}, follow_redirects=False)
    assert "no+book+selected" in r.headers["location"]
