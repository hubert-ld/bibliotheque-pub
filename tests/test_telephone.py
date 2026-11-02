import ipaddress

import pytest
from cryptography import x509
from fastapi.testclient import TestClient

from biblio import certs, db, telephone
from biblio.web.app import app, installation

TELEPHONE = ("192.168.1.42", 50000)


@pytest.fixture
def dossier_certs(tmp_path, monkeypatch):
    monkeypatch.setattr(certs, "DOSSIER", tmp_path / "certs")
    return tmp_path / "certs"


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "web.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    conn = db.connect(chemin)
    yield conn
    conn.close()


def charger(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_certificat_serveur_signe_par_la_ca(dossier_certs):
    cert_path, cle_path = certs.serveur(["localhost", "mac.local"], ["127.0.0.1", "192.168.1.10"])
    cert, (ca, _) = charger(cert_path), certs.ca()
    cert.verify_directly_issued_by(ca)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(san.get_values_for_type(x509.DNSName)) == {"localhost", "mac.local"}
    assert ipaddress.ip_address("192.168.1.10") in san.get_values_for_type(x509.IPAddress)
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= 398       # exigence iOS
    assert oct(cle_path.stat().st_mode)[-3:] == "600"


def test_certificat_reutilise_ou_regenere(dossier_certs):
    premier = charger(certs.serveur(["localhost"], ["192.168.1.10"])[0]).serial_number
    assert charger(certs.serveur(["localhost"], ["192.168.1.10"])[0]).serial_number == premier
    nouveau = charger(certs.serveur(["localhost"], ["10.0.0.5"])[0])       # l'IP a changé
    assert nouveau.serial_number != premier
    nouveau.verify_directly_issued_by(certs.ca()[0])                      # même CA : rien à réinstaller


def test_mac_local_sans_cle(base):
    r = TestClient(app, client=("127.0.0.1", 50000), base_url="http://localhost").get("/catalogue")
    assert r.status_code == 200


def test_telephone_sans_cle_refuse(base):
    client = TestClient(app, client=TELEPHONE)
    assert client.get("/catalogue").status_code == 403
    assert client.get("/catalogue?cle=mauvaise").status_code == 403
    assert client.get("/api/etat").status_code == 403
    assert client.get("/static/style.css").status_code == 200               # pas de données


def test_cle_du_qr_code_devient_cookie(base):
    cle = telephone.cle(base)
    client = TestClient(app, client=TELEPHONE)
    r = client.get(f"/scan?camera=1&cle={cle}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/scan?camera=1"
    assert client.cookies.get(telephone.COOKIE) == cle
    assert client.get("/catalogue").status_code == 200
    assert client.get("/telephone", follow_redirects=False).status_code == 303   # QR codes : Mac seulement


def test_manifest_ecran_d_accueil(base):
    cle = telephone.cle(base)
    local = TestClient(app, client=("127.0.0.1", 50000), base_url="http://localhost").get("/manifest.webmanifest").json()
    assert local["display"] == "standalone" and local["start_url"] == "/scan?camera=1"
    client = TestClient(app, client=TELEPHONE)
    assert client.get("/manifest.webmanifest").status_code == 403          # pas sans la clé
    client.get(f"/scan?cle={cle}")
    # L'appli d'écran d'accueil iOS a ses propres cookies : elle se reconnecte avec la clé
    assert client.get("/manifest.webmanifest").json()["start_url"] == f"/scan?camera=1&cle={cle}"


def test_nouvelle_cle_coupe_l_acces(base):
    cle = telephone.cle(base)
    client = TestClient(app, client=TELEPHONE)
    client.get(f"/scan?cle={cle}")
    telephone.nouvelle_cle(base)
    assert client.get("/catalogue").status_code == 403


def test_serveur_d_installation(dossier_certs):
    client = TestClient(installation, client=TELEPHONE)
    assert "Installer le certificat" in client.get("/").text
    r = client.get("/bibliotheque-ca.crt")
    assert r.headers["content-type"] == "application/x-x509-ca-cert"
    assert x509.load_der_x509_certificate(r.content) == certs.ca()[0]
    r = client.get("/bibliotheque-ca.crt?fichier=1")                      # Android / Firefox
    assert r.headers["content-type"] == "application/octet-stream"
    assert x509.load_der_x509_certificate(r.content) == certs.ca()[0]
    assert client.get("/catalogue").status_code == 404
    assert client.get("/api/etat").status_code == 404


def _verifier(cert, ca, nom):
    from cryptography.x509 import verification

    magasin = verification.Store([ca])
    verification.PolicyBuilder().store(magasin).build_server_verifier(nom).verify(cert, [])


def test_nouvelle_autorite_limitee_au_reseau_local(dossier_certs):
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.verification import VerificationError

    ca, cle = certs.ca()
    contraintes = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert contraintes.critical
    cert = charger(certs.serveur(["localhost", "mac.local"], ["127.0.0.1", "192.168.1.10"])[0])
    _verifier(cert, ca, x509.DNSName("mac.local"))
    _verifier(cert, ca, x509.IPAddress(ipaddress.ip_address("192.168.1.10")))
    # Même signé par cette autorité, un certificat pour un vrai site n'est pas accepté
    faux = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "banque.example")]))
            .issuer_name(ca.subject).public_key(cle.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(cert.not_valid_before_utc).not_valid_after(cert.not_valid_after_utc)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("banque.example")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(cle.public_key()), critical=False)
            .sign(cle, hashes.SHA256()))
    with pytest.raises(VerificationError):
        _verifier(faux, ca, x509.DNSName("banque.example"))


def test_autorite_existante_conservee(dossier_certs):
    premiere = certs.ca()[0]
    assert certs.ca()[0].serial_number == premiere.serial_number



def test_cle_telephone_sans_les_reglages(base):
    """La clé des QR codes : tout, sauf les réglages communs et la page Téléphone."""
    client = TestClient(app, client=TELEPHONE)
    client.get(f"/scan?cle={telephone.cle(base)}")
    assert client.get("/catalogue").status_code == 200
    for chemin in ("/reglages", "/telephone"):
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/scan", chemin
    assert client.get("/partage.db", follow_redirects=False).status_code == 303
    for chemin, donnees in (("/reglages", {"proprietaire": "Pirate"}), ("/reglages/reclasser", {}),
                            ("/telephone/nouvelle-cle", {}), ("/systeme", {"systeme": "lcc"}),
                            ("/langue", {"langue": "en"})):
        assert client.post(chemin, data=donnees, follow_redirects=False).status_code == 403, chemin
    assert db.get_meta(base, "langue") != "en"
    page = client.get("/catalogue").text
    assert 'href="/reglages"' not in page and 'action="/langue"' not in page


def test_cle_admin_pour_le_mac(base):
    """Sur le Pi, le Mac passe par le réseau avec la clé admin : il a tout, page Téléphone comprise."""
    cle_tel, cle_admin = telephone.cle(base), telephone.cle_admin(base)
    assert cle_admin != cle_tel
    mac = TestClient(app, client=("192.168.1.30", 50000))
    mac.get(f"/catalogue?cle={cle_admin}")
    assert mac.get("/telephone", follow_redirects=False).status_code == 200
    assert mac.get("/reglages", follow_redirects=False).status_code == 200
    assert 'href="/reglages"' in mac.get("/catalogue").text
    assert mac.get("/manifest.webmanifest").json()["start_url"].endswith(f"cle={cle_admin}")
    # Changer la clé des téléphones coupe les téléphones, pas le Mac
    tel = TestClient(app, client=TELEPHONE)
    tel.get(f"/scan?cle={cle_tel}")
    assert mac.post("/telephone/nouvelle-cle", follow_redirects=False).status_code == 303
    assert tel.get("/catalogue").status_code == 403
    assert mac.get("/catalogue").status_code == 200
    # Et une nouvelle clé admin coupe l'ancienne
    telephone.nouvelle_cle_admin(base)
    assert mac.get("/catalogue").status_code == 403


def test_pas_de_cle_admin_sans_la_demander(base):
    telephone.cle(base)
    TestClient(app, client=("127.0.0.1", 50000), base_url="http://localhost").get("/telephone")
    assert db.get_meta(base, "cle_admin") is None
