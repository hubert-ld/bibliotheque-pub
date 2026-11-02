"""Accès depuis le téléphone : adresse locale, clé d'accès, URL des QR codes."""

import os
import secrets
import socket
import subprocess
import sys

from . import db

# Changeables (ex. sur un Raspberry Pi où un autre service occupe déjà 8080 et 8443) :
# variables BIBLIO_PORT_HTTPS / BIBLIO_PORT_INSTALLATION, ou `biblio serve --phone-port/--install-port`.
PORT_HTTPS = int(os.environ.get("BIBLIO_PORT_HTTPS") or 8443)
PORT_INSTALLATION = int(os.environ.get("BIBLIO_PORT_INSTALLATION") or 8080)
COOKIE = "biblio_cle"

# Renseigné par `biblio serve --telephone` avant le démarrage des serveurs
etat: dict = {"actif": False, "ip": None, "nom": None}


def ip_locale() -> str:
    """Adresse de l'ordinateur sur le réseau local (aucun paquet n'est envoyé)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def nom_local() -> str:
    """Nom de l'ordinateur sur le réseau local (ex. mon-ordinateur.local).

    macOS : nom Bonjour ; Linux (Avahi) et Windows 10+ répondent aussi au nom de la machine + .local.
    """
    nom = ""
    if sys.platform == "darwin":
        try:
            nom = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    nom = nom or socket.gethostname().split(".")[0]
    return f"{nom}.local"


def cle(conn) -> str:
    valeur = db.get_meta(conn, "cle_telephone")
    if not valeur:
        valeur = nouvelle_cle(conn)
    return valeur


def nouvelle_cle(conn) -> str:
    """Change la clé : les téléphones déjà connectés devront rescanner le QR code."""
    valeur = secrets.token_urlsafe(24)
    db.set_meta(conn, "cle_telephone", valeur)
    return valeur


# Deux clés, deux rôles, pour les appareils du réseau (l'ordinateur lui-même, en localhost, est admin) :
#   « telephone » : la clé des QR codes. Scanner, consulter, ranger, prêter… mais pas les réglages.
#   « admin »     : pour son propre ordinateur quand la bibliothèque tourne sur un serveur sans écran
#                   (Raspberry Pi) : tout, réglages et page Téléphone compris. Créée à la demande
#                   (`biblio phone --admin`), jamais affichée en QR code.
ROLES = (("admin", "cle_admin"), ("telephone", "cle_telephone"))


def cle_admin(conn) -> str:
    return db.get_meta(conn, "cle_admin") or nouvelle_cle_admin(conn)


def nouvelle_cle_admin(conn) -> str:
    """Change la clé admin : les navigateurs qui l'avaient doivent rouvrir la nouvelle adresse."""
    valeur = secrets.token_urlsafe(24)
    db.set_meta(conn, "cle_admin", valeur)
    return valeur


def role(conn, proposee: str | None) -> str | None:
    """« admin », « telephone », ou None si la clé n'est pas bonne."""
    if not proposee:
        return None
    for nom, meta in ROLES:
        attendue = db.get_meta(conn, meta)
        if attendue and secrets.compare_digest(proposee, attendue):
            return nom
    return None


def cle_valide(conn, proposee: str | None) -> bool:
    return role(conn, proposee) is not None


def activer(ip: str, nom: str) -> None:
    etat.update(actif=True, ip=ip, nom=nom)


def urls(conn, ip: str | None = None) -> dict:
    ip = ip or etat["ip"] or ip_locale()
    return {
        "installation": f"http://{ip}:{PORT_INSTALLATION}/",
        "scan": f"https://{ip}:{PORT_HTTPS}/scan?camera=1&cle={cle(conn)}",
        "scan_court": f"https://{ip}:{PORT_HTTPS}/scan",
    }


def url_admin(conn) -> str:
    """Par le nom (.local) plutôt que l'IP : il survit à un changement d'adresse, et c'est l'adresse
    à mettre en favori (le cookie de la clé est propre à chaque adresse)."""
    return f"https://{etat['nom'] or nom_local()}:{PORT_HTTPS}/catalogue?cle={cle_admin(conn)}"
