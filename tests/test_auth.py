"""Comptes, rôles, connexion : la matrice d'accès, le blocage, et ce qui ne doit pas bouger."""

import re
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from biblio import auth, certs, db, partage, sante, services, telephone
from biblio.web.app import app

RESEAU = ("192.168.1.42", 50000)
LOCAL = ("127.0.0.1", 50000)
CHANSON = "9782070196678"


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    yield conn
    conn.close()


def connecte(base, role, identifiant=None, souvenir="1"):
    identifiant = identifiant or role
    auth.creer_compte(base, identifiant, role, code="1234")
    client = TestClient(app, client=RESEAU, base_url="https://192.168.1.10:8443", follow_redirects=False)
    r = client.post("/connexion", data={"identifiant": identifiant, "code": "1234", "souvenir": souvenir, "suite": "/catalogue"},
                    headers={"Origin": "https://192.168.1.10:8443"})
    assert r.status_code == 303 and r.headers["location"] == "/catalogue", r.text
    return client


# --- Connexion --------------------------------------------------------------------

def test_le_code_est_tape_une_fois(base):
    client = connecte(base, "lecteur")
    assert client.get("/catalogue").status_code == 200
    autre_page = TestClient(app, client=RESEAU, base_url="https://192.168.1.10:8443", cookies=dict(client.cookies), follow_redirects=False)
    assert autre_page.get("/catalogue").status_code == 200       # réouverture : aucun code redemandé


def test_cookie_sur_et_durable(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    client = TestClient(app, client=RESEAU, base_url="https://192.168.1.10:8443", follow_redirects=False)
    r = client.post("/connexion", data={"identifiant": "marie", "code": "1234", "souvenir": "1"})
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Max-Age=31536000" in cookie


def test_sans_se_souvenir_le_cookie_ne_dure_pas(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    client = TestClient(app, client=RESEAU, base_url="https://192.168.1.10:8443", follow_redirects=False)
    r = client.post("/connexion", data={"identifiant": "marie", "code": "1234"})
    assert "Max-Age" not in r.headers["set-cookie"]


def test_la_base_ne_contient_ni_code_ni_jeton(base):
    client = connecte(base, "lecteur")
    jeton = client.cookies.get(auth.COOKIE)
    ligne = base.execute("SELECT jeton_hash FROM sessions").fetchone()[0]
    assert jeton and ligne != jeton
    assert "1234" not in base.execute("SELECT code_hash FROM comptes").fetchone()[0]


def test_mauvais_code_message_generique(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    client = TestClient(app, client=RESEAU, follow_redirects=False)
    faux = client.post("/connexion", data={"identifiant": "marie", "code": "0000"})
    inconnu = client.post("/connexion", data={"identifiant": "personne", "code": "0000"})
    assert faux.status_code == inconnu.status_code == 403
    assert "Identifiant ou code incorrect" in faux.text and "Identifiant ou code incorrect" in inconnu.text
    assert auth.COOKIE not in client.cookies


def test_blocage_apres_cinq_essais(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    for _ in range(5):
        with pytest.raises(auth.Refus, match="incorrect"):
            auth.connecter(base, "marie", "0000", "1.2.3.4")
    with pytest.raises(auth.Refus, match="Trop d'essais"):        # même avec le bon code
        auth.connecter(base, "marie", "1234", "1.2.3.4")
    assert auth.connecter(base, "marie", "1234", "5.6.7.8")["identifiant"] == "marie"     # une autre adresse passe
    actions = [l["action"] for l in auth.journal(base)]
    assert "blocage" in actions and "echec" in actions


def test_blocage_de_duree_croissante_et_plafonnee():
    assert auth._duree_blocage(4, 5) is None
    assert auth._duree_blocage(5, 5) == 60
    assert auth._duree_blocage(6, 5) == 120
    assert auth._duree_blocage(40, 5) == auth.BLOCAGE_MAX


def test_blocage_expire(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    for _ in range(5):
        with pytest.raises(auth.Refus):
            auth.connecter(base, "marie", "0000", "1.2.3.4")
    passe = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    base.execute("UPDATE tentatives SET bloque_jusqua = ?", (passe,))
    base.commit()
    assert auth.connecter(base, "marie", "1234", "1.2.3.4")
    assert not base.execute("SELECT 1 FROM tentatives WHERE identifiant = 'marie'").fetchone()


def test_trop_d_identifiants_depuis_une_adresse(base):
    for i in range(auth.ESSAIS_PAR_ADRESSE):
        with pytest.raises(auth.Refus):
            auth.connecter(base, f"inconnu{i}", "0000", "1.2.3.4")
    with pytest.raises(auth.Refus, match="Trop d'essais"):
        auth.connecter(base, "encore", "0000", "1.2.3.4")


def test_session_expiree_et_renouvellement(base):
    client = connecte(base, "lecteur")
    jeton = client.cookies.get(auth.COOKIE)
    hier = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    base.execute("UPDATE sessions SET vu_le = ?", (hier,))
    base.commit()
    assert auth.session(base, jeton)["renouvele"] is True
    assert auth.session(base, jeton)["renouvele"] is False       # une fois par jour au plus
    base.execute("UPDATE sessions SET expire_le = ?", (hier,))
    base.commit()
    assert auth.session(base, jeton) is None
    assert client.get("/catalogue").status_code == 303


def test_redirection_de_connexion_reste_dans_l_appli(base):
    auth.creer_compte(base, "marie", "lecteur", code="1234")
    client = TestClient(app, client=RESEAU, follow_redirects=False)
    r = client.post("/connexion", data={"identifiant": "marie", "code": "1234", "suite": "https://evil.example/"})
    assert r.headers["location"] == "/scan"


def test_page_demandee_retrouvee_apres_connexion(base):
    client = TestClient(app, client=RESEAU, follow_redirects=False)
    r = client.get("/catalogue?q=camus")
    assert r.headers["location"] == "/connexion?suite=%2Fcatalogue%3Fq%3Dcamus"
    assert 'value="/catalogue?q=camus"' in client.get(r.headers["location"]).text


def test_deconnexion(base):
    client = connecte(base, "lecteur")
    assert client.post("/deconnexion").status_code == 303
    assert not base.execute("SELECT 1 FROM sessions").fetchone()
    assert client.get("/catalogue").status_code == 303


# --- Matrice des rôles ------------------------------------------------------------

def _chemin_de(route) -> str:
    return re.sub(r"\{[^}]+\}", "1", route.path)


def test_aucune_route_n_echappe_au_controle():
    """Toute route de l'appli est déclarée dans auth.REGLES, ou publique par choix."""
    oubliees = []
    for route in app.routes:
        for methode in getattr(route, "methods", None) or []:
            if methode in ("HEAD", "OPTIONS") or route.path.startswith(("/openapi", "/docs", "/redoc", "/static")):
                continue
            chemin = _chemin_de(route)
            if chemin not in auth.SANS_CONNEXION and auth.droit_requis(methode, chemin) is None:
                oubliees.append((methode, route.path))
    assert not oubliees, oubliees


@pytest.mark.parametrize("methode,chemin,droit", [
    ("GET", "/catalogue", "consulter"), ("GET", "/livre/12", "consulter"), ("GET", "/scan", "consulter"),
    ("GET", "/couverture/12", "consulter"), ("GET", "/lieux", "consulter"), ("POST", "/api/scan", "consulter"),
    ("POST", "/api/annuler/3", "scanner"), ("POST", "/exemplaire/3/deplacer", "scanner"), ("POST", "/api/inventaire", "scanner"),
    ("GET", "/manuel", "scanner"), ("POST", "/livre/3/exemplaire", "scanner"),
    ("POST", "/livre/3/modifier", "modifier"), ("POST", "/lieux/ajouter", "modifier"), ("POST", "/exemplaire/3/preter", "modifier"),
    ("POST", "/exemplaire/3/supprimer", "modifier"), ("GET", "/export.csv", "modifier"), ("GET", "/lieux/etiquettes", "modifier"),
    ("GET", "/stats", "personnel"), ("GET", "/prets", "personnel"),
    ("GET", "/echanges", "personnel"), ("POST", "/echanges/babelio", "personnel"), ("POST", "/echanges/babelio/appliquer", "personnel"),
    ("GET", "/export.goodreads", "modifier"), ("GET", "/export.babelio", "modifier"),
    ("GET", "/admin", "admin"), ("POST", "/admin/comptes", "admin"), ("GET", "/reglages", "admin"), ("GET", "/telephone", "admin"),
    ("GET", "/partage.db", "admin"), ("POST", "/systeme", "admin"), ("POST", "/langue", "admin"),
    ("GET", "/compte", "connecte"), ("POST", "/deconnexion", "connecte"),
    ("GET", "/route-inconnue", None),                                # non déclarée : réservée à l'admin
])
def test_droit_de_chaque_route(methode, chemin, droit):
    assert auth.droit_requis(methode, chemin) == droit


ATTENDU = {
    # chemin à lire : rôles qui y ont accès
    "/catalogue": {"lecteur", "contributeur", "bibliothecaire", "admin"},
    "/scan": {"lecteur", "contributeur", "bibliothecaire", "admin"},
    "/manuel": {"contributeur", "bibliothecaire", "admin"},
    "/a-traiter": {"contributeur", "bibliothecaire", "admin"},
    "/stats": {"bibliothecaire", "admin"},
    "/prets": {"bibliothecaire", "admin"},
    "/export.csv": {"bibliothecaire", "admin"},
    "/export.goodreads": {"bibliothecaire", "admin"},
    "/echanges": {"bibliothecaire", "admin"},
    "/lieux/etiquettes": {"bibliothecaire", "admin"},
    "/reglages": {"admin"},
    "/telephone": {"admin"},
    "/partage.db": {"admin"},
    "/admin/sante": {"admin"},
    "/admin/comptes": {"admin"},
    "/admin/catalogues": {"admin"},
    "/admin/acces": {"admin"},
    "/admin/journal": {"admin"},
    "/admin/systeme": {"admin"},
}


@pytest.mark.parametrize("role", auth.ROLES)
def test_matrice_de_lecture(base, role):
    client = connecte(base, role)
    for chemin, roles in ATTENDU.items():
        r = client.get(chemin)
        if role in roles:
            assert r.status_code == 200, (role, chemin)
        else:
            assert r.status_code == 303 and r.headers["location"] == "/scan", (role, chemin)


@pytest.mark.parametrize("role,permis", [("lecteur", False), ("contributeur", False), ("bibliothecaire", True), ("admin", True)])
def test_ecriture_des_fiches(base, role, permis):
    services.ajouter(base, CHANSON)
    client = connecte(base, role)
    r = client.post("/lieux/ajouter", data={"nom": "Cave"})
    assert (r.status_code == 303) is permis and (r.status_code == 403) is not permis
    assert bool(base.execute("SELECT 1 FROM lieux WHERE nom = 'Cave'").fetchone()) is permis
    avant = base.execute("SELECT count(*) FROM exemplaires").fetchone()[0]
    r = client.post(f"/exemplaire/{services.exemplaires_de(base, CHANSON)[0]['id']}/supprimer")
    assert (base.execute("SELECT count(*) FROM exemplaires").fetchone()[0] < avant) is permis


@pytest.mark.parametrize("role,ajoute,ou", [("lecteur", False, True), ("contributeur", True, True), ("bibliothecaire", True, True)])
def test_scan_selon_le_role(base, role, ajoute, ou):
    client = connecte(base, role)
    services.ajouter(base, "9782253140870")
    r = client.post("/api/scan", json={"mode": "ajout", "code": CHANSON}).json()
    assert r["ok"] is ajoute
    assert bool(db.id_notice(base, CHANSON)) is ajoute
    assert client.post("/api/scan", json={"mode": "ou", "code": "9782253140870"}).json()["ok"] is ou


def test_lot_contributeur_range_mais_ne_retire_pas(base):
    lieu = services.creer_lieu(base, "Salon")
    ex = services.ajouter(base, CHANSON)["exemplaire_id"]
    client = connecte(base, "contributeur")
    r = client.post("/catalogue/lot", data={"ex": ex, "action": "deplacer", "emplacement": f"{lieu}:"})
    assert r.status_code == 303 and "err" not in r.headers["location"]
    assert services.exemplaires_de(base, CHANSON)[0]["lieu_id"] == lieu
    r = client.post("/catalogue/lot", data={"ex": ex, "action": "retirer"})
    assert "err" in r.headers["location"] and services.exemplaires_de(base, CHANSON)


def test_le_lecteur_ne_voit_rien_de_personnel(base):
    services.ajouter(base, CHANSON)
    services.modifier_notice(base, CHANSON, {"titre": "Chanson douce", "notes": "secretnote"})
    ex = services.exemplaires_de(base, CHANSON)[0]["id"]
    services.modifier_exemplaire(base, ex, {"prix_achat": "7,50", "dedicace": "pour Marie"})
    services.preter(base, ex, "Gaspard")
    client = connecte(base, "lecteur")
    page = client.get(f"/livre/{db.id_notice(base, CHANSON)}").text
    for secret in ("secretnote", "Gaspard", "7.5", "pour Marie", 'id="lecture"'):
        assert secret not in page, secret
    assert "Gaspard" not in client.get("/catalogue").text
    assert "Chanson douce" not in client.get("/catalogue?q=secretnote").text      # pas de sondage des notes
    assert "Chanson douce" in client.get("/catalogue?q=chanson").text
    res = client.post("/api/scan", json={"mode": "ou", "code": CHANSON}).json()
    assert "Gaspard" not in res["message"] and "prêté" in res["message"]
    # Le bibliothécaire, lui, voit tout
    biblio = connecte(base, "bibliothecaire")
    page = biblio.get(f"/livre/{db.id_notice(base, CHANSON)}").text
    assert "secretnote" in page and "Gaspard" in page
    assert "Gaspard" in biblio.post("/api/scan", json={"mode": "ou", "code": CHANSON}).json()["message"]
    assert "Chanson douce" in biblio.get("/catalogue?q=secretnote").text


def test_menus_selon_le_role(base):
    page = connecte(base, "lecteur").get("/catalogue").text
    for lien in ('href="/admin"', 'href="/reglages"', 'href="/stats"', 'href="/prets"', 'href="/a-traiter"', "/export.csv", "/manuel"):
        assert lien not in page, lien
    page = connecte(base, "admin").get("/catalogue").text
    for lien in ('href="/admin"', 'href="/reglages"', 'href="/stats"', "/export.csv"):
        assert lien in page, lien


# --- Clés, ordinateur, certificats : rien ne change --------------------------------

def test_cle_des_qr_codes_vaut_bibliothecaire(base):
    services.ajouter(base, CHANSON)
    client = TestClient(app, client=RESEAU, follow_redirects=False)
    client.get(f"/scan?cle={telephone.cle(base)}")
    assert client.get("/stats").status_code == 200
    assert client.post("/lieux/ajouter", data={"nom": "Cave"}).status_code == 303
    assert client.get("/admin/comptes").status_code == 303 and client.get("/reglages").status_code == 303


def test_couper_la_cle_des_qr_codes(base):
    cle = telephone.cle(base)
    client = TestClient(app, client=RESEAU, follow_redirects=False)
    client.get(f"/scan?cle={cle}")
    assert client.get("/catalogue").status_code == 200
    telephone.couper_qr(base, True)
    assert client.get("/catalogue").status_code == 303
    assert telephone.cle(base) == cle                            # rétablie, la même clé remarche
    telephone.couper_qr(base, False)
    assert client.get("/catalogue").status_code == 200


def test_ordinateur_local_toujours_admin_sans_connexion(base):
    client = TestClient(app, client=LOCAL, base_url="http://localhost", follow_redirects=False)
    for chemin in ("/catalogue", "/admin/sante", "/admin/comptes", "/reglages"):
        assert client.get(chemin).status_code == 200, chemin


def test_cle_admin_ouvre_l_administration(base):
    mac = TestClient(app, client=RESEAU, follow_redirects=False)
    mac.get(f"/catalogue?cle={telephone.cle_admin(base)}")
    assert mac.get("/admin/comptes").status_code == 200


def test_session_prime_sur_une_cle_plus_large(base):
    client = connecte(base, "lecteur")
    client.cookies.set(telephone.COOKIE, telephone.cle_admin(base))
    assert client.get("/reglages").status_code == 303


def test_certificats_ni_crees_ni_touches_par_l_admin(base):
    client = TestClient(app, client=LOCAL, base_url="http://localhost", follow_redirects=False)
    assert client.get("/admin/sante").status_code == 200
    assert not certs.DOSSIER.exists()                            # lire leur état ne crée rien
    certs.serveur(["localhost"], ["192.168.1.10"])
    avant = {f.name: f.read_bytes() for f in certs.DOSSIER.iterdir()}
    for chemin in ("/admin/sante", "/admin/acces"):
        assert client.get(chemin).status_code == 200
    auth.creer_compte(base, "marie", "admin", code="1234")
    assert {f.name: f.read_bytes() for f in certs.DOSSIER.iterdir()} == avant


def test_nom_force_par_la_configuration(monkeypatch, base):
    monkeypatch.setenv("BIBLIO_NOM", "mon-serveur")
    assert telephone.nom_local() == "mon-serveur"
    monkeypatch.setitem(telephone.etat, "nom", None)
    assert telephone.url_admin(base).startswith(f"https://mon-serveur:{telephone.PORT_HTTPS}/")


def test_autorite_sans_limite_signe_le_nom_court(tmp_path, monkeypatch):
    """Comme l'autorité déjà installée sur les téléphones : certificat régénéré, autorité inchangée."""
    from cryptography import x509

    ca = certs.ca()[0]
    monkeypatch.setattr(certs, "_nom_permis", lambda cert, nom: True)
    chemin, _ = certs.serveur(["localhost", "mon-serveur", "mon-serveur.local"], ["127.0.0.1", "192.168.1.20"])
    cert = x509.load_pem_x509_certificate(chemin.read_bytes())
    noms = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert "mon-serveur" in noms and "mon-serveur.local" in noms
    cert.verify_directly_issued_by(ca)
    assert certs.ca()[0].serial_number == ca.serial_number


def test_autorite_limitee_au_nom_du_serveur(monkeypatch, caplog):
    from cryptography import x509
    from cryptography.x509 import verification

    monkeypatch.setenv("BIBLIO_NOM", "mon-serveur")
    chemin, _ = certs.serveur(["localhost", "mon-serveur", "autre.local"], ["127.0.0.1", "192.168.1.20"])
    cert = x509.load_pem_x509_certificate(chemin.read_bytes())
    noms = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert set(noms) == {"localhost", "mon-serveur"}
    assert "autre.local" in caplog.text
    verificateur = verification.PolicyBuilder().store(verification.Store([certs.ca()[0]]))
    verificateur.build_server_verifier(x509.DNSName("mon-serveur")).verify(cert, [])


# --- Page d'administration ----------------------------------------------------------

@pytest.fixture
def admin(base):
    return TestClient(app, client=LOCAL, base_url="http://localhost", follow_redirects=False)


def test_creer_un_compte_montre_le_code_une_seule_fois(base, admin):
    r = admin.post("/admin/comptes", data={"identifiant": "marie", "nom": "Marie", "role": "contributeur"})
    assert r.status_code == 200 and "À donner à la personne" in r.text
    code = re.search(r'<code class="grand">(\d{6})</code>', r.text).group(1)
    assert auth.connecter(base, "marie", code, "1.2.3.4")["role"] == "contributeur"
    assert code not in admin.get("/admin/comptes").text
    assert code not in str(auth.journal(base))


def test_identifiant_sans_casse_et_doublon_refuse(base, admin):
    auth.creer_compte(base, "Marie", "lecteur", code="1234")
    assert auth.connecter(base, "marie", "1234", "1.2.3.4")
    r = admin.post("/admin/comptes", data={"identifiant": "marie", "role": "lecteur"})
    assert "err=" in r.headers["location"]
    with pytest.raises(auth.ErreurCompte):
        auth.creer_compte(base, "victor", "lecteur", code="12")      # trop court
    with pytest.raises(auth.ErreurCompte):
        auth.creer_compte(base, "victor", "pirate")


def test_changer_le_role_s_applique_tout_de_suite(base, admin):
    client = connecte(base, "bibliothecaire", "marie")
    assert client.get("/stats").status_code == 200
    compte = auth.par_identifiant(base, "marie")
    admin.post(f"/admin/comptes/{compte['id']}", data={"role": "lecteur", "actif": "1"})
    assert client.get("/stats").status_code == 303


def test_desactiver_coupe_les_appareils(base, admin):
    client = connecte(base, "lecteur", "marie")
    compte = auth.par_identifiant(base, "marie")
    admin.post(f"/admin/comptes/{compte['id']}", data={"role": "lecteur"})       # case « actif » décochée
    assert client.get("/catalogue").status_code == 303
    with pytest.raises(auth.Refus):
        auth.connecter(base, "marie", "1234", "1.2.3.4")


def test_couper_un_appareil_seulement(base, admin):
    un = connecte(base, "lecteur", "marie")
    deux = TestClient(app, client=RESEAU, base_url="https://192.168.1.10:8443", follow_redirects=False)
    deux.post("/connexion", data={"identifiant": "marie", "code": "1234", "souvenir": "1"})
    compte = auth.par_identifiant(base, "marie")
    assert len(auth.appareils(base, compte["id"])) == 2
    premiere = auth.appareils(base, compte["id"])[0]["id"]
    admin.post(f"/admin/appareils/{premiere}/couper")
    assert sorted([un.get("/catalogue").status_code, deux.get("/catalogue").status_code]) == [200, 303]


def test_nouveau_code_coupe_les_appareils(base, admin):
    client = connecte(base, "lecteur", "marie")
    compte = auth.par_identifiant(base, "marie")
    r = admin.post(f"/admin/comptes/{compte['id']}/code", data={"code": "9999"})
    assert r.status_code == 200 and ">9999<" in r.text
    assert client.get("/catalogue").status_code == 303
    assert auth.connecter(base, "marie", "9999", "1.2.3.4")


def test_dernier_admin_protege(base, admin):
    auth.creer_compte(base, "moi", "admin", code="1234")
    compte = auth.par_identifiant(base, "moi")["id"]
    for r in (admin.post(f"/admin/comptes/{compte}", data={"role": "lecteur", "actif": "1"}),
              admin.post(f"/admin/comptes/{compte}", data={"role": "admin"}),
              admin.post(f"/admin/comptes/{compte}/supprimer")):
        assert "err=" in r.headers["location"]
    assert auth.compte(base, compte)["actif"] and auth.compte(base, compte)["role"] == "admin"
    auth.creer_compte(base, "autre", "admin", code="1234")
    r = admin.post(f"/admin/comptes/{compte}/supprimer")
    assert "msg=" in r.headers["location"] and not auth.compte(base, compte)


def test_mon_compte_changer_son_code(base):
    client = connecte(base, "lecteur", "marie")
    assert client.get("/compte").status_code == 200
    assert "err=" in client.post("/compte/code", data={"actuel": "faux", "nouveau": "5678"}).headers["location"]
    assert "err=" in client.post("/compte/code", data={"actuel": "1234", "nouveau": "  "}).headers["location"]
    assert "msg=" in client.post("/compte/code", data={"actuel": "1234", "nouveau": "5678"}).headers["location"]
    assert client.get("/catalogue").status_code == 200           # cet appareil reste connecté
    assert auth.connecter(base, "marie", "5678", "1.2.3.4")


def test_on_ne_coupe_que_ses_propres_appareils(base):
    marie = connecte(base, "lecteur", "marie")
    victor = connecte(base, "lecteur", "victor")
    session_victor = auth.appareils(base, auth.par_identifiant(base, "victor")["id"])[0]["id"]
    marie.post(f"/compte/appareil/{session_victor}/couper")
    assert victor.get("/catalogue").status_code == 200


def test_cles_de_catalogue(base, admin):
    r = admin.post("/admin/catalogues/tmdb", data={"actif": "1", "cle": "maclef-secrete"})
    assert r.status_code == 303 and db.get_meta(base, "tmdb_api_key") == "maclef-secrete"
    page = admin.get("/admin/catalogues").text
    assert "maclef-secrete" not in page and "clé enregistrée" in page
    assert "maclef-secrete" not in str(auth.journal(base))
    admin.post("/admin/catalogues/tmdb", data={"actif": "1", "effacer": "1"})
    assert db.get_meta(base, "tmdb_api_key") is None
    admin.post("/admin/catalogues/deezer", data={})
    assert not next(c for c in sante.catalogues(base) if c["source"] == "deezer")["actif"]
    assert next(c for c in sante.catalogues(base) if c["source"] == "deezer")["etat"] == "desactive"


def test_cle_google_reprise_a_son_ancien_nom(base):
    db.set_meta(base, "google_api_key", "AIza")
    assert next(c for c in sante.catalogues(base) if c["source"] == "google")["cle_presente"]


def test_test_des_catalogues_sans_reseau(base, admin, monkeypatch):
    from biblio.sources import Fetched, bnf, deezer, omdb, sudoc

    monkeypatch.setattr(sante.registre, "CATALOGUES", [c for c in sante.registre.CATALOGUES if c.module in (bnf, sudoc, deezer, omdb)])
    monkeypatch.setattr(bnf, "fetch", lambda *a: Fetched("ok"))
    monkeypatch.setattr(sudoc, "fetch", lambda *a: Fetched("erreur", "HTTP 500"))
    monkeypatch.setattr(deezer, "fetch", lambda *a: Fetched("absent", "{}"))
    r = admin.post("/admin/catalogues/tester")
    assert r.json() == {"ok": True}
    etats = {c["source"]: c for c in sante.catalogues(base)}
    assert etats["bnf"]["etat"] == "ok" and etats["bnf"]["latence"] is not None
    assert etats["sudoc"]["etat"] == "panne" and "500" in etats["sudoc"]["message"]
    assert etats["deezer"]["etat"] == "ok"                       # « absent » prouve qu'il répond
    assert etats["omdb"]["etat"] == "sans_cle"
    assert not sante.test_perime(base)


def test_cle_refusee_reconnue(base, monkeypatch):
    from biblio.sources import Fetched, omdb

    monkeypatch.setattr(sante.registre, "CATALOGUES", [c for c in sante.registre.CATALOGUES if c.module is omdb])
    monkeypatch.setattr(omdb, "fetch", lambda *a: Fetched("erreur", "HTTP 401 : clé refusée"))
    db.set_meta(base, "omdb_api_key", "mauvaise")
    assert sante.tester(base)[0]["etat"] == "cle_refusee"


def test_sauvegardes_depuis_l_admin(base, admin):
    assert "msg=" in admin.post("/admin/systeme/sauvegarder").headers["location"]
    copie = sante.sauvegardes(base)[0]["nom"]
    assert copie in admin.get("/admin/systeme").text
    r = admin.get(f"/admin/systeme/sauvegardes/{copie}")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"
    assert admin.get("/admin/systeme/sauvegardes/..%2F..%2Fweb.db").status_code == 404


def test_rien_des_comptes_dans_un_fichier_de_partage(base, tmp_path):
    auth.creer_compte(base, "marie", "admin", code="1234")
    auth.journaliser(base, "connexion", "marie")
    db.set_meta(base, "tmdb_api_key", "secret")
    services.ajouter(base, CHANSON)
    fichier = tmp_path / "partage.db"
    partage.exporter_partage(base, fichier)
    f = sqlite3.connect(fichier)
    for table in ("comptes", "sessions", "tentatives", "journal", "sources_etat"):
        assert f.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert not f.execute("SELECT 1 FROM meta WHERE cle = 'tmdb_api_key'").fetchone()
    f.close()


def test_les_comptes_ne_se_synchronisent_pas(tmp_path):
    a = db.connect(tmp_path / "a.db")
    b = db.connect(tmp_path / "b.db")
    moi = a.execute("SELECT uid FROM personnes WHERE id = ?", (db.moi_id(a),)).fetchone()[0]
    db.moi_id(b)
    b.execute("UPDATE personnes SET uid = ? WHERE id = ?", (moi, db.moi_id(b)))
    db.set_meta(b, "moi_uid", moi)
    auth.creer_compte(b, "marie", "admin", code="1234")
    services.ajouter(b, CHANSON)
    b.close()
    partage.synchroniser(a, tmp_path / "b.db")
    assert a.execute("SELECT count(*) FROM comptes").fetchone()[0] == 0
    a.close()


def test_scan_d_une_etiquette_par_l_api(base):
    from biblio import etiquettes

    lieu = services.creer_lieu(base, "Salon")
    numero = base.execute("SELECT etiquette FROM lieux WHERE id = ?", (lieu,)).fetchone()[0]
    client = TestClient(app, client=LOCAL, base_url="http://localhost")
    r = client.post("/api/scan", json={"mode": "ajout", "code": etiquettes.code_de("lieux", numero)}).json()
    assert r["statut"] == "emplacement" and r["lieu_id"] == lieu and r["nom"] == "Salon"
    assert not base.execute("SELECT 1 FROM notices").fetchone()


def test_page_des_etiquettes(base):
    lieu = services.creer_lieu(base, "Salon")
    etagere = services.creer_etagere(base, lieu, "É1")
    services.creer_rangee(base, etagere, "Devant")
    client = TestClient(app, client=LOCAL, base_url="http://localhost")
    page = client.get("/lieux/etiquettes").text
    assert page.count("<svg") >= 3 and "Salon › É1 › Devant" in page


def test_rangee_par_le_web(base):
    lieu = services.creer_lieu(base, "Salon")
    etagere = services.creer_etagere(base, lieu, "É1")
    client = TestClient(app, client=LOCAL, base_url="http://localhost", follow_redirects=False)
    assert client.post(f"/etageres/{etagere}/rangee", data={"nom": "Devant, Derrière"}).status_code == 303
    rangee = services.lieux(base)[0]["etageres"][0]["rangees"][0]
    assert "Derrière" in client.get("/lieux").text
    r = client.post("/api/scan", json={"mode": "ajout", "code": CHANSON, "lieu_id": lieu, "etagere_id": etagere, "rangee_id": rangee["id"]}).json()
    assert r["emplacement"].endswith(rangee["nom"])
    ex = r["exemplaire_id"]
    client.post(f"/exemplaire/{ex}/deplacer", data={"emplacement": f"{lieu}:{etagere}", "suite": "/lieux"})
    assert services.exemplaires_de(base, CHANSON)[0]["rangee_id"] is None
    assert client.get(f"/catalogue?lieu={lieu}&etagere={etagere}&rangee={rangee['id']}").status_code == 200
    assert client.get("/catalogue?support=musique").status_code == 200


def test_menu_lateral_du_lecteur(base):
    """Le menu du téléphone suit les droits : un lecteur n'y voit ni réglages ni administration."""
    menu = connecte(base, "lecteur").get("/catalogue").text.split('id="menu-lateral"')[1].split("</dialog>")[0]
    assert 'href="/compte"' in menu and "data-theme-choix" in menu
    for page in ("/prets", "/stats", "/reglages", "/admin"):
        assert f'href="{page}"' not in menu
    assert 'action="/langue"' not in menu
