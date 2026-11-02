from fastapi.testclient import TestClient

from biblio import db, services
from biblio.web.app import app

from .conftest import charger


def test_catalogue_operations_groupees(tmp_path, monkeypatch):
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    salon = services.creer_lieu(conn, "Salon")
    e1 = services.creer_etagere(conn, salon, "É1")
    for isbn, fichier in (("9782070196678", "bnf_chanson_douce.xml"), ("9782014001143", "bnf_asterix.xml")):
        services.ajouter(conn, isbn)                               # scannés sans lieu
        charger(conn, isbn, bnf=fichier)
    client = TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost")

    page = client.get("/catalogue?lieu=aucun").text
    assert page.count('name="ex"') == 2 and 'id="lot"' in page

    # Sans emplacement choisi : refusé, rien ne bouge
    r = client.post("/catalogue/lot", data={"tous": "1", "lieu": "aucun", "action": "deplacer"}, follow_redirects=False)
    assert "err=" in r.headers["location"]

    # « Sélectionner tous les résultats » des non localisés -> Salon › É1
    r = client.post("/catalogue/lot", data={"tous": "1", "lieu": "aucun", "action": "deplacer",
                                           "emplacement": f"{salon}:{e1}", "suite": "/catalogue?lieu=aucun"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/catalogue?lieu=aucun&msg=")
    assert services.ids_exemplaires(conn, lieu_id="aucun") == []
    assert len(services.ids_exemplaires(conn, etagere_id=e1)) == 2

    # Cases cochées une par une -> retirées
    ex = services.ids_exemplaires(conn)[:1]
    client.post("/catalogue/lot", data={"ex": ex, "action": "retirer"})
    assert len(services.ids_exemplaires(conn)) == 1
    conn.close()


def test_bandeau_redemarrage(tmp_path, monkeypatch):
    from biblio.web import app as module

    monkeypatch.setenv("BIBLIO_DB", str(tmp_path / "web.db"))
    client = TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost")
    assert "redémarrez-le" not in client.get("/lieux").text
    monkeypatch.setattr(module, "CODE_AU_DEMARRAGE", 0)          # code modifié après le lancement
    assert "redémarrez-le" in client.get("/lieux").text


def _client(tmp_path, monkeypatch):
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    services.renommer_proprietaire_local(conn, "JD")
    return conn, TestClient(app, client=("127.0.0.1", 1), base_url="http://localhost")


def test_page_statistiques(tmp_path, monkeypatch):
    import json
    import re

    conn, client = _client(tmp_path, monkeypatch)
    assert 'data-vide="Aucun prêt en cours."' in client.get("/stats").text          # base vide : la page s'affiche
    services.ajouter(conn, "9782070196678")
    charger(conn, "9782070196678", bnf="bnf_chanson_douce.xml")
    services.preter(conn, "9782070196678", "Marie <b>")
    services.ajouter(conn, "9782014001143", proprietaire="Victor")
    page = client.get("/stats").text
    donnees = json.loads(re.search(r'id="stats-donnees"[^>]*>(.*?)</script>', page, re.S).group(1))
    assert donnees["prets_en_cours"][0]["qui"] == "Marie <b>" and "<b>Marie" not in page
    assert 'data-serie="prets_en_cours"' in page and "Chez les amis" in page and "proprio=Victor" in page
    assert 'data-serie="reseau_aretes"' in page and donnees["reseau_aretes"][0]["nb"] == 1
    assert {n["nom"] for n in donnees["reseau_noeuds"]} == {"JD", "Victor", "Marie <b>"}
    conn.close()


def test_bascule_de_theme(tmp_path, monkeypatch):
    conn, client = _client(tmp_path, monkeypatch)
    page = client.get("/catalogue").text
    for theme in ("auto", "light", "dark"):
        assert f'data-theme-choix="{theme}"' in page
    assert page.index('localStorage.getItem("theme")') < page.index("style.css")   # posé avant l'affichage
    conn.close()


def test_catalogue_proprietaires_et_don(tmp_path, monkeypatch):
    conn, client = _client(tmp_path, monkeypatch)
    for isbn, fichier in (("9782070196678", "bnf_chanson_douce.xml"), ("9782014001143", "bnf_asterix.xml")):
        services.ajouter(conn, isbn)
        charger(conn, isbn, bnf=fichier)
    page = client.get("/catalogue").text                                # seul : le filtre dit comment ajouter un ami
    assert "Mes livres" in page and "biblio merge" in page and "Tout le monde" not in page

    ex = services.ids_exemplaires(conn)[:1]
    r = client.post("/catalogue/lot", data={"ex": ex, "action": "donner", "vers": "Victor"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    page = client.get("/catalogue").text
    assert page.count('name="ex"') == 1 and "proprio=Victor" in page and "Tout le monde" in page
    assert "biblio merge" not in page
    page = client.get("/catalogue?proprio=Victor").text
    assert page.count('name="ex"') == 1 and "chez Victor" in page
    r = client.post("/catalogue/lot", data={"ex": ex, "action": "donner", "vers": ""}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    conn.close()


def test_catalogue_filtres_derriere_un_bouton(tmp_path, monkeypatch):
    conn, client = _client(tmp_path, monkeypatch)
    services.creer_lieu(conn, "Salon")
    page = client.get("/catalogue").text
    assert 'id="ouvrir-filtres"' in page and 'id="panneau-filtres"' in page
    assert '<span class="pastille">' not in page.split('id="ouvrir-filtres"')[1].split("</button>")[0]
    assert "Effacer les filtres" not in page
    # Lieu et dates sont hors du formulaire, mais toujours envoyés avec la recherche
    assert '<select name="lieu" form="form-recherche"' in page
    assert '<input type="date" name="du" form="form-recherche"' in page

    page = client.get("/catalogue?lieu=aucun&lecture=lu&q=zola").text
    assert '<span class="pastille">2</span>' in page.split('id="ouvrir-filtres"')[1].split("</button>")[0]
    effacer = page.split("Effacer les filtres")[0].rsplit('href="', 1)[1]    # garde la recherche, retire les filtres
    assert "q=zola" in effacer and "lieu=" not in effacer and "lecture=" not in effacer
    conn.close()


def test_manuel_enregistre_meme_si_la_bnf_echoue(tmp_path, monkeypatch):
    from biblio.sources import bnf
    from biblio.web import app as module

    conn, client = _client(tmp_path, monkeypatch)
    def panne(*a, **kw):
        raise bnf.RechercheImpossible("réseau coupé")
    monkeypatch.setattr(bnf, "rechercher", panne)
    page = client.get("/manuel?chercher=1&titre=Vieux+livre&auteur=Camille+Dupont").text
    assert "BnF n&#39;a pas pu être interrogée" in page or "BnF n'a pas pu être interrogée" in page
    assert 'value="Vieux livre"' in page and 'value="Camille Dupont"' in page   # recopiés dans le formulaire

    r = client.post("/manuel", data={"titre": "Vieux livre", "auteurs": "Camille Dupont", "annee": "1921",
                                     "forme": "fiction", "notes": "Trouvé **au grenier**"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/livre/")
    n = services.notice(conn, r.headers["location"].split("/")[2].split("?")[0])
    assert n["titre"] == "Vieux livre" and n["annee"] == 1921 and n["statut"] == "manuel"

    # Erreur de saisie : le formulaire revient avec ce qui a été tapé
    page = client.post("/manuel", data={"titre": "Autre", "annee": "mille"}).text
    assert 'value="Autre"' in page and "doit être un nombre" in page
    assert module.CHAMPS_MANUEL
    conn.close()


def test_note_markdown_sans_script(tmp_path, monkeypatch):
    conn, client = _client(tmp_path, monkeypatch)
    res = services.creer_notice_manuelle(conn, "Carnet", "")
    client.post(f"/livre/{res['notice_id']}/note",
                data={"notes": "# Avis\n\n**Superbe** [lien](https://example.org)\n\n<script>alert(1)</script>"})
    page = client.get(f"/livre/{res['notice_id']}").text
    assert "<h1>Avis</h1>" in page and "<strong>Superbe</strong>" in page
    assert 'target="_blank"' in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert services.rechercher(conn, "superbe")[1] == 1                 # la note est cherchable
    conn.close()


def test_telechargement_partage(tmp_path, monkeypatch):
    import sqlite3

    conn, client = _client(tmp_path, monkeypatch)
    salon = services.creer_lieu(conn, "Salon")
    services.ajouter(conn, "9782070196678", salon)
    charger(conn, "9782070196678", bnf="bnf_chanson_douce.xml")
    r = client.get("/partage.db?masquer=1")
    assert r.status_code == 200 and "bibliotheque-JD-" in r.headers["content-disposition"]
    (tmp_path / "recu.db").write_bytes(r.content)
    f = sqlite3.connect(tmp_path / "recu.db")
    assert f.execute("SELECT p.nom, e.lieu_texte FROM exemplaires e JOIN personnes p ON p.id = e.proprietaire_id").fetchall() == [("JD", None)]
    f.close()
    conn.close()


def _bibliotheque(tmp_path, monkeypatch):
    conn, client = _client(tmp_path, monkeypatch)
    salon = services.creer_lieu(conn, "Salon")
    e1 = services.creer_etagere(conn, salon, "É1")
    chambre = services.creer_lieu(conn, "Chambre")
    for isbn, fichier in (("9782070196678", "bnf_chanson_douce.xml"), ("9782014001143", "bnf_asterix.xml"),
                          ("9782290382608", "bnf_vargas.xml")):
        services.ajouter(conn, isbn, salon, e1)
        charger(conn, isbn, bnf=fichier)
    services.preter(conn, "9782070196678", "Marie")
    services.ajouter(conn, "9782290382608", proprietaire="Victor")
    services.creer_notice_manuelle(conn, "Carnet", "Camille Dupont", lieu_id=chambre)
    services.demarrer_inventaire(conn, salon, e1)
    return conn, client, salon, e1, chambre


def test_tous_les_liens_repondent(tmp_path, monkeypatch):
    """Parcourt l'appli depuis chaque page : aucun lien ne doit mener à une erreur."""
    import html
    import re
    from urllib.parse import urljoin

    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    a_voir = ["/scan", "/catalogue", "/lieux", "/a-traiter", "/prets", "/stats", "/telephone", "/reglages", "/manuel"]
    vues, erreurs = set(), []
    while a_voir and len(vues) < 400:
        url = a_voir.pop()
        if url in vues:
            continue
        vues.add(url)
        r = client.get(url)
        if r.status_code >= 400:
            erreurs.append((url, r.status_code))
            continue
        if "text/html" not in r.headers.get("content-type", ""):
            continue
        for lien in re.findall(r'href="([^"#]*)', r.text):
            lien = html.unescape(lien)
            if not lien or lien.startswith(("http", "javascript", "/static", "/export", "/partage", "/manifest")):
                continue
            a_voir.append(urljoin(url, lien))
    assert not erreurs, erreurs
    assert any("classe=" in u for u in vues) and len(vues) > 20
    conn.close()


def test_filtre_de_classe_du_catalogue(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    for url in ("/catalogue?a_classer=", "/catalogue?classe=&a_classer=&p=1", "/catalogue?p=abc", "/manuel?chercher="):
        assert client.get(url).status_code == 200, url
    assert 'a_classer=&' not in client.get("/catalogue").text              # les liens ne portent plus de paramètre vide
    assert client.get("/catalogue?a_classer=1").status_code == 200
    conn.close()


def test_changer_de_lieu_oublie_l_etagere(tmp_path, monkeypatch):
    conn, client, salon, e1, chambre = _bibliotheque(tmp_path, monkeypatch)
    page = client.get(f"/catalogue?lieu={chambre}&etagere={e1}").text
    assert page.count('name="ex"') == 1 and "Carnet" in page
    assert client.get(f"/catalogue?lieu={salon}&etagere={e1}").text.count('name="ex"') == 3
    conn.close()


def test_compteur_non_localises_de_la_page_lieux(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    assert "non localisé" not in client.get("/lieux").text.split("</h1>")[1].split('class="lieux"')[0]
    conn.close()


def test_enregistrer_une_fiche_sans_y_toucher_ne_change_rien(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    isbn = "9782290382608"
    conn.execute("UPDATE notices SET forme = 'discours', resume = ? WHERE isbn13 = ?", ("ligne 1\nligne 2", isbn))
    conn.execute("UPDATE notices SET corrections = '{}' WHERE isbn13 = ?", (isbn,))
    conn.commit()
    page = client.get(f"/livre/{isbn}").text
    assert '<option value="discours" selected' in page                  # valeur courante proposée
    r = client.post(f"/livre/{isbn}/modifier", data={"forme": "discours", "resume": "ligne 1\r\nligne 2"})
    assert r.status_code == 200
    n = services.notice(conn, isbn)
    assert n["forme"] == "discours" and n["champs_manuels"] == []       # les navigateurs envoient des CRLF
    conn.close()


class _Panne:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *a, **kw):
        import httpx
        raise httpx.ConnectError("réseau coupé")


def test_reinterroger_pendant_une_panne_garde_la_fiche_et_la_couverture(tmp_path, monkeypatch):
    from biblio import covers
    from biblio.web import app as module

    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "make_client", _Panne)
    isbn = "9782014001143"                                     # les couvertures gardent l'ISBN pour nom
    covers.DOSSIER.mkdir(parents=True, exist_ok=True)
    covers.chemin(isbn).write_bytes(b"image")
    r = client.post(f"/livre/{isbn}/relancer", follow_redirects=False)
    assert "err=" in r.headers["location"]                              # la panne est annoncée
    assert services.notice(conn, isbn)["titre"] and services.notice(conn, isbn)["statut"] == "trouve"
    assert covers.chemin(isbn).exists()
    conn.close()


def test_reinterroger_refuse_sans_isbn(tmp_path, monkeypatch):
    from biblio.web import app as module

    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "make_client", _Panne)
    notice_id = conn.execute("SELECT id FROM notices WHERE isbn13 IS NULL").fetchone()[0]
    r = client.post(f"/livre/{notice_id}/relancer", follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert services.notice(conn, notice_id)["titre"] == "Carnet"
    conn.close()


def test_a_traiter_propose_de_relancer_un_echec_partiel(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    assert 'action="/a-traiter/relancer"' not in client.get("/a-traiter").text
    conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                 "VALUES (?, 'google', 'erreur', 'HTTP 500', '2026-01-01')", (db.id_notice(conn, "9782290382608"),))
    conn.commit()
    assert 'action="/a-traiter/relancer"' in client.get("/a-traiter").text
    r = client.post("/a-traiter/relancer", follow_redirects=False)
    assert r.status_code == 303 and services.notice(conn, "9782290382608")["statut"] == "en_attente"
    conn.close()


def test_requetes_venues_d_un_autre_site_refusees(tmp_path, monkeypatch):
    conn, client, salon, *_ = _bibliotheque(tmp_path, monkeypatch)
    for origine in ("https://evil.example", "null", "http://localhost.evil.example"):
        r = client.post("/lieux/ajouter", data={"nom": "Piège"}, headers={"Origin": origine})
        assert r.status_code == 403, origine
    assert client.post(f"/lieux/{salon}/supprimer", headers={"Origin": "https://evil.example"}).status_code == 403
    r = client.post("/api/scan", content='{"mode":"ajout","code":"9782070360024"}',
                    headers={"Origin": "https://evil.example", "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert not any(l["nom"] == "Piège" for l in services.lieux(conn))
    # La page elle-même, et la ligne de commande (sans Origin), passent
    assert client.post("/lieux/ajouter", data={"nom": "Bureau"}, headers={"Origin": "http://localhost"},
                       follow_redirects=False).status_code == 303
    assert client.post("/lieux/ajouter", data={"nom": "Cave"}, follow_redirects=False).status_code == 303
    conn.close()


def test_rebinding_dns_refuse(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    assert client.get("/export.csv", headers={"Host": "evil.example"}).status_code == 403
    for hote in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
        assert client.get("/export.csv", headers={"Host": hote}).status_code == 200, hote
    conn.close()


def test_adresse_du_telephone_acceptee_depuis_l_ordinateur(tmp_path, monkeypatch):
    from biblio import telephone

    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    monkeypatch.setitem(telephone.etat, "ip", "192.168.1.10")
    monkeypatch.setitem(telephone.etat, "nom", "Mac.local")
    assert client.get("/catalogue", headers={"Host": "192.168.1.10:8443"}).status_code == 200
    assert client.get("/catalogue", headers={"Host": "mac.local:8443"}).status_code == 200
    conn.close()


def test_telephone_autorise_depuis_sa_propre_page(tmp_path, monkeypatch):
    from biblio import telephone

    conn, _, *_ = _bibliotheque(tmp_path, monkeypatch)
    cle = telephone.cle(conn)
    tel = TestClient(app, client=("192.168.1.42", 1), base_url="https://192.168.1.10:8443")
    tel.get(f"/scan?cle={cle}")
    r = tel.post("/api/scan", json={"mode": "ou", "code": "9782070196678"},
                 headers={"Origin": "https://192.168.1.10:8443"})
    assert r.status_code == 200 and r.json()["statut"] == "trouve"
    assert tel.post("/api/scan", json={"mode": "ou", "code": "9782070196678"},
                    headers={"Origin": "https://evil.example"}).status_code == 403
    conn.close()


def test_redirections_limitees_a_l_appli(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    ex = services.exemplaires_de(conn, "9782014001143")[0]["id"]
    for url, data in (("/systeme", {"systeme": "dewey", "suite": "//evil.example"}),
                      ("/langue", {"langue": "fr", "suite": "/\\evil.example"}),
                      (f"/exemplaire/{ex}/preter", {"emprunteur": "x", "suite": "https://evil.example"})):
        r = client.post(url, data=data, follow_redirects=False)
        lieu = r.headers["location"]
        assert lieu.startswith("/") and not lieu.startswith(("//", "/\\")), (url, lieu)
    r = client.post("/systeme", data={"systeme": "dewey", "suite": "/lieux"}, follow_redirects=False)
    assert r.headers["location"] == "/lieux"
    conn.close()


def test_json_invalide(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    for url in ("/api/scan", "/api/inventaire"):
        for corps in ("pas du json", "[1, 2]"):
            r = client.post(url, content=corps)
            assert r.status_code == 200 and r.json()["ok"] is False, (url, corps)
    conn.close()


def test_fiche_accessible_par_numero_reference_ou_isbn(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    notice_id = db.id_notice(conn, "9782070196678")
    for ref in (notice_id, f"L{notice_id}", "9782070196678"):
        assert "Chanson douce" in client.get(f"/livre/{ref}").text, ref
    carnet = conn.execute("SELECT id FROM notices WHERE isbn13 IS NULL").fetchone()[0]
    assert f"L{carnet}" in client.get(f"/livre/{carnet}").text
    assert client.get("/couverture/inconnu").status_code == 404
    conn.close()


def test_couverture_d_un_livre_sans_isbn_propre_a_ce_livre(tmp_path, monkeypatch):
    from biblio import covers

    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    n = services.notice(conn, conn.execute("SELECT id FROM notices WHERE isbn13 IS NULL").fetchone()[0])
    covers.DOSSIER.mkdir(parents=True, exist_ok=True)
    covers.chemin(n["uid"]).write_bytes(b"image")
    assert client.get(f"/couverture/{n['id']}").content == b"image"
    conn.close()


def test_scan_differe_garde_chaque_exemplaire(tmp_path, monkeypatch):
    """Des scans gardés hors ligne arrivent d'un coup : ce ne sont pas des doubles lectures."""
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    code = "9782253140870"
    corps = {"mode": "ajout", "code": code, "lieu_id": "", "etagere_id": ""}
    assert client.post("/api/scan", json=corps).json()["statut"] == "ajoute"
    assert client.post("/api/scan", json=corps).json()["statut"] == "rebond"
    assert client.post("/api/scan", json={**corps, "differe": True}).json()["statut"] == "doublon"
    assert len(services.exemplaires_de(conn, code)) == 2
    conn.close()


def test_formulaires_lecture_et_exemplaire(tmp_path, monkeypatch):
    conn, client, *_ = _bibliotheque(tmp_path, monkeypatch)
    isbn = "9782014001143"
    page = client.get(f"/livre/{isbn}").text
    assert 'id="lecture"' in page and "Détails de l&#39;exemplaire" in page
    client.post(f"/livre/{isbn}/lecture", data={"lecture": "lu", "lecture_debut": "", "lecture_fin": "2026-02-03", "etoiles": "5"})
    n = services.notice(conn, isbn)
    assert (n["lecture"], n["lecture_fin"], n["etoiles"]) == ("lu", "2026-02-03", 5)
    assert "lecture_debut" not in n["corrections"]                       # seul ce qui change est daté
    r = client.post(f"/livre/{isbn}/lecture", data={"etoiles": "9"}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    ex = n["exemplaires"][0]["id"]
    r = client.post(f"/exemplaire/{ex}/details", data={"etat": "bon", "prix_achat": "3,5", "suite": f"/livre/{isbn}"},
                    follow_redirects=False)
    assert "msg=" in r.headers["location"] and services.exemplaires_de(conn, isbn)[0]["prix_achat"] == 3.5
    assert client.get("/catalogue?lecture=lu").text.count('name="ex"') == 1
    assert "Valeur de la collection" in client.get("/stats").text
    conn.close()
