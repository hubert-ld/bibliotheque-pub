"""HTTPS sur le réseau local, pour que le téléphone ait le droit d'ouvrir sa caméra.

Une petite autorité de certification (CA) propre à cette bibliothèque signe le
certificat du serveur. On installe la CA une fois sur le téléphone ; ensuite
le certificat du serveur peut être régénéré (changement d'IP, expiration)
sans rien réinstaller.

Les clés privées restent hors du dossier du projet, qui peut être synchronisé.
"""

import ipaddress
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

def dossier_donnees() -> Path:
    """Dossier des données propres à cet ordinateur (hors du dossier du projet), selon le système."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "biblio"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "biblio"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "biblio"


DOSSIER = Path(os.environ.get("BIBLIO_CERTS") or dossier_donnees() / "certs")
NOM_CA = "Bibliothèque perso — autorité locale"
DUREE_CA = timedelta(days=3650)
DUREE_SERVEUR = timedelta(days=397)        # iOS refuse les certificats valables plus de 398 jours
MARGE = timedelta(days=30)                 # renouvelé un mois avant expiration
# Une autorité installée sur un téléphone serait crue pour tous les sites : celle-ci ne vaut que
# pour le réseau local, même si sa clé privée fuitait. Une autorité déjà installée n'est pas remplacée.
RESEAU_LOCAL = x509.NameConstraints(
    permitted_subtrees=[x509.DNSName("localhost"), x509.DNSName("local"),
                        *(x509.IPAddress(ipaddress.ip_network(r)) for r in
                          ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"))],
    excluded_subtrees=None)


def _chemins():
    return {
        "ca": DOSSIER / "ca.pem", "ca_cle": DOSSIER / "ca-cle.pem",
        "serveur": DOSSIER / "serveur.pem", "serveur_cle": DOSSIER / "serveur-cle.pem",
    }


def _ecrire_cle(path: Path, cle) -> None:
    path.write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def _maintenant():
    return datetime.now(timezone.utc)


def ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """Charge la CA locale, ou la crée la première fois."""
    p = _chemins()
    if p["ca"].exists() and p["ca_cle"].exists():
        cert = x509.load_pem_x509_certificate(p["ca"].read_bytes())
        cle = serialization.load_pem_private_key(p["ca_cle"].read_bytes(), password=None)
        if cert.not_valid_after_utc > _maintenant() + MARGE:
            return cert, cle
    DOSSIER.mkdir(parents=True, exist_ok=True)
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NOM_CA),
                     x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Bibliothèque perso")])
    debut = _maintenant() - timedelta(minutes=5)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nom).issuer_name(nom).public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(debut).not_valid_after(debut + DUREE_CA)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()), critical=False)
        .add_extension(RESEAU_LOCAL, critical=True)
        .sign(cle, hashes.SHA256())
    )
    _ecrire_cle(p["ca_cle"], cle)
    p["ca"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    for k in ("serveur", "serveur_cle"):          # l'ancien certificat serveur n'est plus valable
        p[k].unlink(missing_ok=True)
    return cert, cle


def ca_der() -> bytes:
    """La CA au format DER, celui qu'iOS et Android installent le plus facilement."""
    cert, _ = ca()
    return cert.public_bytes(serialization.Encoding.DER)


def empreinte_ca() -> str:
    cert, _ = ca()
    h = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _couvre(cert: x509.Certificate, noms: list[str], ips: list[str]) -> bool:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    dns = set(san.get_values_for_type(x509.DNSName))
    adresses = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    return set(noms) <= dns and set(ips) <= adresses


def serveur(noms: list[str], ips: list[str]) -> tuple[Path, Path]:
    """Certificat du serveur couvrant ces noms et IP ; régénéré seulement si nécessaire."""
    ca_cert, ca_cle = ca()
    p = _chemins()
    if p["serveur"].exists() and p["serveur_cle"].exists():
        cert = x509.load_pem_x509_certificate(p["serveur"].read_bytes())
        if (cert.issuer == ca_cert.subject and _couvre(cert, noms, ips)
                and cert.not_valid_after_utc > _maintenant() + MARGE):
            return p["serveur"], p["serveur_cle"]
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    debut = _maintenant() - timedelta(minutes=5)
    san = [x509.DNSName(n) for n in dict.fromkeys(noms)]
    san += [x509.IPAddress(ipaddress.ip_address(i)) for i in dict.fromkeys(ips)]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, noms[0] if noms else ips[0])]))
        .issuer_name(ca_cert.subject).public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(debut).not_valid_after(debut + DUREE_SERVEUR)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
                                     content_commitment=False, data_encipherment=False,
                                     key_agreement=False, key_cert_sign=False, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cle.public_key()), critical=False)
        .sign(ca_cle, hashes.SHA256())
    )
    _ecrire_cle(p["serveur_cle"], cle)
    p["serveur"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return p["serveur"], p["serveur_cle"]
