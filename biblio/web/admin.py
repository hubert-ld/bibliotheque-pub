"""Page d'administration : santé, comptes, catalogues, accès réseau, journal, système.

Le middleware de app.py la réserve au rôle admin (voir auth.REGLES).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import auth, db, resolver, sante, sauvegarde, services, telephone
from ..i18n import pluriel, tr
from ..sources import registre
from .app import _ip, _qui, get_conn, page, retour
from . import app as appli

router = APIRouter(prefix="/admin")
ONGLETS = [("sante", "Santé"), ("comptes", "Comptes"), ("catalogues", "Catalogues"), ("acces", "Accès réseau"),
           ("journal", "Journal"), ("systeme", "Système")]
NOMS_ACTIONS = {
    "connexion": "Connexion", "echec": "Code ou identifiant faux", "blocage": "Blocage après trop d'essais",
    "code_change": "Code changé", "compte_cree": "Compte créé", "compte_modifie": "Compte modifié",
    "compte_supprime": "Compte supprimé", "code_reinitialise": "Nouveau code donné", "appareil_coupe": "Appareil coupé",
    "cle_qr_changee": "Clé des QR codes changée", "cle_qr_coupee": "Clé des QR codes coupée",
    "cle_qr_retablie": "Clé des QR codes rétablie", "cle_admin_changee": "Clé admin changée",
    "catalogue_modifie": "Catalogue modifié", "sauvegarde": "Sauvegarde créée",
}


def _page(request, conn, onglet: str, **ctx) -> HTMLResponse:
    return page(request, conn, "admin.html", onglet=onglet, onglets=ONGLETS, ROLES=auth.ROLES, NOMS_ROLES=auth.NOMS_ROLES,
                NOMS_ETATS=sante.NOMS_ETATS, NOMS_ACTIONS=NOMS_ACTIONS, octets=sante.octets, **ctx)


def _trace(conn, request, action: str, detail: str | None = None) -> None:
    auth.journaliser(conn, action, _qui(request), detail, _ip(request))


@router.get("", include_in_schema=False)
def accueil():
    return RedirectResponse("/admin/sante", status_code=303)


@router.get("/sante", response_class=HTMLResponse)
def onglet_sante(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "sante", g=sante.general(conn), cats=sante.catalogues(conn),
                 fil=bool(appli.worker and appli.worker.is_alive()))


# --- Comptes ----------------------------------------------------------------------

@router.get("/comptes", response_class=HTMLResponse)
def onglet_comptes(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "comptes", comptes=auth.comptes(conn), code_a_donner=_code_a_donner(request))


def _code_a_donner(request: Request) -> dict | None:
    """Le code vient d'être créé : montré une seule fois, par la réponse à la création (voir `_montrer_code`)."""
    return getattr(request.state, "code_a_donner", None)


def _montrer_code(request, conn, identifiant: str, code: str) -> HTMLResponse:
    """On répond directement, sans passer le code dans une adresse : il n'est dans aucun historique."""
    request.state.code_a_donner = {"identifiant": identifiant, "code": code}
    return onglet_comptes(request, conn)


@router.post("/comptes", response_class=HTMLResponse)
def comptes_creer(request: Request, identifiant: str = Form(""), nom: str = Form(""), role: str = Form("lecteur"),
                  code: str = Form(""), conn=Depends(get_conn)):
    try:
        donne = auth.creer_compte(conn, identifiant, role, nom, code)
    except auth.ErreurCompte as e:
        return retour("/admin/comptes", err=str(e))
    _trace(conn, request, "compte_cree", f"{identifiant.strip()} ({role})")
    return _montrer_code(request, conn, identifiant.strip(), donne)


@router.post("/comptes/{compte_id}")
def comptes_modifier(request: Request, compte_id: int, role: str = Form(...), nom: str = Form(""), actif: str = Form(""),
                     conn=Depends(get_conn)):
    try:
        auth.modifier_compte(conn, compte_id, role=role, nom=nom, actif=bool(actif))
    except auth.ErreurCompte as e:
        return retour("/admin/comptes", err=str(e))
    _trace(conn, request, "compte_modifie", f"{auth.compte(conn, compte_id)['identifiant']} ({role})")
    return retour("/admin/comptes", msg=tr("compte enregistré"))


@router.post("/comptes/{compte_id}/code", response_class=HTMLResponse)
def comptes_code(request: Request, compte_id: int, code: str = Form(""), conn=Depends(get_conn)):
    try:
        donne = auth.changer_code(conn, compte_id, code)
    except auth.ErreurCompte as e:
        return retour("/admin/comptes", err=str(e))
    identifiant = auth.compte(conn, compte_id)["identifiant"]
    _trace(conn, request, "code_reinitialise", identifiant)
    return _montrer_code(request, conn, identifiant, donne)


@router.post("/comptes/{compte_id}/supprimer")
def comptes_supprimer(request: Request, compte_id: int, conn=Depends(get_conn)):
    compte = auth.compte(conn, compte_id)
    try:
        auth.supprimer_compte(conn, compte_id)
    except auth.ErreurCompte as e:
        return retour("/admin/comptes", err=str(e))
    if compte:
        _trace(conn, request, "compte_supprime", compte["identifiant"])
    return retour("/admin/comptes", msg=tr("compte supprimé"))


@router.post("/appareils/{session_id}/couper")
def appareil_couper(request: Request, session_id: int, conn=Depends(get_conn)):
    auth.couper_appareil(conn, session_id)
    _trace(conn, request, "appareil_coupe", str(session_id))
    return retour("/admin/comptes", msg=tr("appareil déconnecté"))


# --- Catalogues -------------------------------------------------------------------

@router.get("/catalogues", response_class=HTMLResponse)
def onglet_catalogues(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "catalogues", cats=sante.catalogues(conn), a_tester=sante.test_perime(conn))


@router.post("/catalogues/tester")
def catalogues_tester(conn=Depends(get_conn)):
    sante.tester(conn)
    return JSONResponse({"ok": True})


@router.post("/catalogues/{nom}")
def catalogues_modifier(request: Request, nom: str, actif: str = Form(""), cle: str = Form(""), effacer: str = Form(""),
                        conn=Depends(get_conn)):
    cat = registre.PAR_NOM.get(nom)
    if not cat:
        return retour("/admin/catalogues", err=tr("catalogue inconnu"))
    sante.activer(conn, nom, bool(actif))
    if cat.cle and effacer:
        db.set_meta(conn, cat.cle, None)
    elif cat.cle and cle.strip():
        db.set_meta(conn, cat.cle, cle.strip())
    _trace(conn, request, "catalogue_modifie", cat.nom)        # jamais la clé elle-même
    return retour("/admin/catalogues", msg=tr("catalogue {nom} enregistré", nom=cat.nom))


# --- Accès réseau -----------------------------------------------------------------

@router.get("/acces", response_class=HTMLResponse)
def onglet_acces(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "acces", g=sante.general(conn), qr_coupe=telephone.qr_coupe(conn),
                 cle_admin_existe=bool(db.get_meta(conn, "cle_admin")),
                 nb_comptes_admin=conn.execute("SELECT count(*) FROM comptes WHERE role = 'admin' AND actif = 1").fetchone()[0])


@router.post("/acces/qr")
def acces_qr(request: Request, action: str = Form(...), conn=Depends(get_conn)):
    if action == "couper":
        telephone.couper_qr(conn, True)
        _trace(conn, request, "cle_qr_coupee")
        return retour("/admin/acces", msg=tr("clé des QR codes coupée : seuls les comptes peuvent entrer"))
    if action == "retablir":
        telephone.couper_qr(conn, False)
        _trace(conn, request, "cle_qr_retablie")
        return retour("/admin/acces", msg=tr("clé des QR codes rétablie"))
    telephone.nouvelle_cle(conn)
    _trace(conn, request, "cle_qr_changee")
    return retour("/admin/acces", msg=tr("nouvelle clé : les téléphones déjà connectés doivent rescanner le QR code"))


@router.post("/acces/cle-admin")
def acces_cle_admin(request: Request, conn=Depends(get_conn)):
    telephone.nouvelle_cle_admin(conn)
    _trace(conn, request, "cle_admin_changee")
    return retour("/admin/acces", msg=tr("nouvelle clé admin : les navigateurs qui l'avaient doivent rouvrir le lien de « biblio phone --admin »"))


# --- Journal et système -----------------------------------------------------------

@router.get("/journal", response_class=HTMLResponse)
def onglet_journal(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "journal", lignes=auth.journal(conn))


@router.get("/systeme", response_class=HTMLResponse)
def onglet_systeme(request: Request, conn=Depends(get_conn)):
    return _page(request, conn, "systeme", copies=sante.sauvegardes(conn),
                 nb_raw=conn.execute("SELECT count(*) FROM raw_responses").fetchone()[0],
                 nb_echecs=conn.execute("SELECT count(*) FROM notices WHERE statut IN ('erreur', 'introuvable')").fetchone()[0])


@router.post("/systeme/sauvegarder")
def systeme_sauvegarder(request: Request, conn=Depends(get_conn)):
    copie = sauvegarde.creer(conn)
    _trace(conn, request, "sauvegarde", copie.name)
    return retour("/admin/systeme", msg=tr("sauvegarde créée : {nom}", nom=copie.name))


@router.get("/systeme/sauvegardes/{nom}")
def systeme_telecharger(nom: str, conn=Depends(get_conn)):
    """Seules les copies de la liste : un nom tapé à la main ne sort pas de ce dossier."""
    if nom not in {c["nom"] for c in sante.sauvegardes(conn)}:
        return Response(status_code=404)
    return FileResponse(Path(sauvegarde.dossier_defaut(conn)) / nom, media_type="application/vnd.sqlite3", filename=nom)


@router.post("/systeme/reclasser")
def systeme_reclasser(conn=Depends(get_conn)):
    ids = [r["id"] for r in conn.execute("SELECT id FROM notices WHERE statut != 'en_attente'")]
    for notice_id in ids:
        resolver.rebuild(conn, notice_id)
    return retour("/admin/systeme", msg=tr("{n} notices reconstruites et reclassées, sans requête réseau", n=len(ids)))


@router.post("/systeme/relancer")
def systeme_relancer(conn=Depends(get_conn)):
    n = services.relancer(conn)
    if appli.worker:
        appli.worker.wake()
    return retour("/admin/systeme", msg=pluriel(n, "{n} livre remis en recherche", "{n} livres remis en recherche"))
