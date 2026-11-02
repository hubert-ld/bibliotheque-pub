"""Appli web locale : poste de scan, catalogue, fiches, lieux, inventaires."""

import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import segno
from markdown_it import MarkdownIt
from markupsafe import Markup

from .. import __version__, certs, covers, db, export, i18n, partage, resolver, services, telephone
from ..i18n import tr
from ..classify import SYSTEMES, systeme_courant
from ..classify.regles import options as options_regles
from ..services import Erreur
from ..sources import make_client
from ..worker import Worker

HERE = Path(__file__).parent
worker: Worker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    worker = Worker()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Bibliothèque", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(SYSTEMES=SYSTEMES, version=__version__, FORMES=services.FORMES,
                             PUBLICS=services.PUBLICS, NOMS_FORMES=services.NOMS_FORMES,
                             LECTURES=services.LECTURES, NOMS_LECTURES=services.NOMS_LECTURES,
                             ETATS=services.ETATS, NOMS_ETATS=services.NOMS_ETATS)
templates.env.filters["auteurs"] = lambda a: ", ".join(a or [])

# Notes des livres en Markdown. HTML brut désactivé : une note ne peut pas glisser de script.
_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def _lien_externe(self, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


_markdown.add_render_rule("link_open", _lien_externe)
templates.env.filters["markdown"] = lambda texte: Markup(_markdown.render(texte or ""))
STATUTS = {"en_attente": "en attente", "trouve": "trouvé", "introuvable": "introuvable",
           "erreur": "erreur", "manuel": "saisi à la main"}
templates.env.globals.update(_=tr, LANGUES=i18n.LANGUES, langue=i18n.langue,
                             nom_statut=lambda s: tr(STATUTS.get(s, s)))


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


# --- Langue de l'interface ---------------------------------------------------------

def _langue_choisie() -> str:
    conn = db.connect()
    try:
        return db.get_meta(conn, "langue", i18n.DEFAUT)
    finally:
        conn.close()


@app.post("/langue")
def changer_langue(request: Request, langue: str = Form(...), suite: str = Form("/scan"), conn=Depends(get_conn)):
    if langue in i18n.LANGUES:
        db.set_meta(conn, "langue", langue)
    return retour(suite)


# --- Accès depuis le réseau (téléphone) ----------------------------------------

LOCAL = {"127.0.0.1", "::1"}
LIBRE = ("/static/",)          # aucune donnée de la bibliothèque
# Réservé à l'ordinateur et à la clé admin : les téléphones ne changent pas les réglages
ADMIN_SEULEMENT = ("/reglages", "/telephone", "/partage.db", "/systeme", "/langue")


def _reserve_admin(chemin: str) -> bool:
    return any(chemin == p or chemin.startswith(p + "/") for p in ADMIN_SEULEMENT)


def _admin(request: Request) -> bool:
    """L'ordinateur lui-même, ou un appareil qui a présenté la clé admin (rôle posé par le middleware)."""
    return getattr(request.state, "role", None) == "admin"
NOMS_LOCAUX = {"localhost", "127.0.0.1", "::1"}


def _hote_connu(request: Request) -> bool:
    """L'adresse demandée est bien la nôtre : sinon, un site pourrait faire pointer son nom vers
    cet ordinateur et lire la bibliothèque depuis le navigateur (« rebinding DNS »)."""
    hote = (request.url.hostname or "").lower()
    noms = NOMS_LOCAUX | {n.lower() for n in (telephone.etat["ip"], telephone.etat["nom"]) if n}
    return hote in noms or hote.endswith(".localhost")


def _origine_valide(request: Request) -> bool:
    """Une écriture doit venir d'une page de cette appli : un autre site ouvert dans le navigateur
    peut envoyer des requêtes à localhost. Sans en-tête Origin, ce n'est pas un navigateur qui écrit."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    origine = request.headers.get("origin")
    return origine is None or urlsplit(origine).netloc.lower() == request.headers.get("host", "").lower()


@app.middleware("http")
async def acces_reseau(request: Request, call_next):
    """L'ordinateur lui-même passe librement ; tout autre appareil doit présenter une clé :
    celle du QR code (téléphones, sans les réglages) ou la clé admin (tout)."""
    i18n.utiliser(_langue_choisie())
    if request.url.path.startswith(LIBRE):
        return await call_next(request)
    client = request.client.host if request.client else ""
    if not _origine_valide(request) or (client in LOCAL and not _hote_connu(request)):
        return PlainTextResponse(tr("Requête refusée : elle ne vient pas de la bibliothèque."), status_code=403)
    if client in LOCAL:
        request.state.role = "admin"
        return await call_next(request)
    conn = db.connect()
    try:
        proposee = request.query_params.get("cle")
        if proposee and telephone.role(conn, proposee):
            # La clé passe dans un cookie et disparaît de l'adresse
            params = [(k, v) for k, v in request.query_params.multi_items() if k != "cle"]
            cible = request.url.path + ("?" + urlencode(params) if params else "")
            reponse = RedirectResponse(cible, status_code=303)
            reponse.set_cookie(telephone.COOKIE, proposee, max_age=365 * 86400, httponly=True,
                               samesite="lax", secure=request.url.scheme == "https")
            return reponse
        role = telephone.role(conn, request.cookies.get(telephone.COOKIE))
    finally:
        conn.close()
    if role is None:
        return HTMLResponse(page_refusee(), status_code=403)
    request.state.role = role
    if role != "admin" and _reserve_admin(request.url.path):
        if request.method in ("GET", "HEAD"):
            return RedirectResponse("/scan", status_code=303)
        return PlainTextResponse(tr("Réservé à l'administration de la bibliothèque."), status_code=403)
    return await call_next(request)


def page_refusee() -> str:
    return f"""<!doctype html><html lang="{i18n.langue()}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{tr("Accès refusé")}</title>
<script>/* Thème choisi sur cet appareil, posé avant l'affichage (sinon : celui du système) */
try {{ const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; }} catch (e) {{}}</script>
<link rel="stylesheet" href="/static/style.css"><main><div class="vide-etat carte">
<h1>{tr("Accès refusé")}</h1>
<p>{tr("Sur l'ordinateur, ouvrez la page « Téléphone » de la bibliothèque et scannez le QR code « Scanner » avec ce téléphone.")}</p>
<p class="doux">{tr("Depuis l'icône de l'écran d'accueil : supprimez l'icône, rouvrez le QR code « Scanner » dans Safari, puis Partager › « Sur l'écran d'accueil ».")}</p>
</div></main></html>"""


def _date_code() -> float:
    """Dernière modification du code Python (les gabarits, eux, se rechargent seuls)."""
    return max(p.stat().st_mtime for p in HERE.parent.rglob("*.py"))


CODE_AU_DEMARRAGE = _date_code()


def page(request: Request, conn, template: str, **ctx) -> HTMLResponse:
    ctx["code_modifie"] = _date_code() > CODE_AU_DEMARRAGE
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["systeme"] = ctx.get("systeme") or systeme_courant(conn)
    ctx["en_attente"] = conn.execute("SELECT count(*) FROM notices WHERE statut = 'en_attente'").fetchone()[0]
    ctx["nb_a_traiter"] = services.nb_a_traiter(conn)
    ctx["nb_prets"] = services.nb_prets(conn)
    ctx["chemin"] = request.url.path
    ctx["admin"] = _admin(request)
    ctx["textes_js"] = i18n.textes_js()
    return templates.TemplateResponse(request, template, ctx)


def _chemin_local(url: str) -> bool:
    """Une adresse de cette appli, et non d'un autre site (« //site », et « /\\site » pour les navigateurs)."""
    return url.startswith("/") and url[1:2] not in ("/", "\\") and not set(url) & set("\t\r\n")


def retour(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    url = url if _chemin_local(url) else "/catalogue"
    params = {k: v for k, v in (("msg", msg), ("err", err)) if v}
    url, diese, ancre = url.partition("#")               # le message va avant l'ancre (#note)
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url + (sep + urlencode(params) if params else "") + diese + ancre, status_code=303)


def _id(value) -> int | None:
    try:
        return int(value) if value not in (None, "", "aucun") else None
    except ValueError:
        return None


# --- Poste de scan -------------------------------------------------------------

@app.get("/", include_in_schema=False)
def accueil():
    return RedirectResponse("/scan")


@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, conn=Depends(get_conn)):
    return page(request, conn, "scan.html", lieux=services.lieux(conn))


async def _corps_json(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@app.post("/api/scan")
async def api_scan(request: Request, conn=Depends(get_conn)):
    data = await _corps_json(request)
    mode, code = data.get("mode", "ajout"), (data.get("code") or "").strip()
    lieu_id, etagere_id = _id(data.get("lieu_id")), _id(data.get("etagere_id"))
    # Scan gardé hors ligne : le téléphone a déjà écarté les doubles lectures, et le renvoi est rapide
    filtrer_rebond = not data.get("differe")
    try:
        if mode == "ajout":
            res = services.ajouter(conn, code, lieu_id, etagere_id, filtrer_rebond=filtrer_rebond)
            if worker:
                worker.wake()
        elif mode == "deplacement":
            res = services.deplacer(conn, code, lieu_id, etagere_id)
        elif mode == "ou":
            res = services.localiser(conn, code)
        elif mode == "inventaire":
            inv = _id(data.get("inventaire_id"))
            if not inv:
                raise Erreur(tr("démarrez d'abord l'inventaire"))
            res = services.scanner_inventaire(conn, inv, code, filtrer_rebond=filtrer_rebond)
        else:
            raise Erreur(tr("mode inconnu : {mode}", mode=mode))
    except Erreur as e:
        return JSONResponse({"ok": False, "statut": "erreur", "message": str(e), "code": code})
    return JSONResponse(res)


@app.post("/api/annuler/{exemplaire_id}")
def api_annuler(exemplaire_id: int, conn=Depends(get_conn)):
    try:
        services.annuler_exemplaire(conn, exemplaire_id)
    except Erreur as e:
        return JSONResponse({"ok": False, "message": str(e)})
    return JSONResponse({"ok": True})


@app.get("/api/notices")
def api_notices(id: list[int] = Query(default=[]), conn=Depends(get_conn)):
    return JSONResponse({i: services.resume_notice(conn, i) for i in id[:100]})


@app.get("/api/etat")
def api_etat(conn=Depends(get_conn)):
    return JSONResponse({
        "en_attente": conn.execute("SELECT count(*) FROM notices WHERE statut = 'en_attente'").fetchone()[0],
        "en_cours": worker.en_cours if worker else None,
    })


@app.post("/api/inventaire")
async def api_inventaire(request: Request, conn=Depends(get_conn)):
    data = await _corps_json(request)
    try:
        inv_id = services.demarrer_inventaire(conn, _id(data.get("lieu_id")), _id(data.get("etagere_id")))
    except Erreur as e:
        return JSONResponse({"ok": False, "message": str(e)})
    return JSONResponse({"ok": True, "id": inv_id, **services.inventaire(conn, inv_id)})


@app.get("/api/inventaire/{inv_id}")
def api_inventaire_etat(inv_id: int, conn=Depends(get_conn)):
    try:
        r = services.rapport_inventaire(conn, inv_id)
    except Erreur as e:
        return JSONResponse({"ok": False, "message": str(e)})
    return JSONResponse({"ok": True, "presents": len(r["presents"]), "manquants": len(r["manquants"]),
                         "ailleurs": len(r["ailleurs"]), "inconnus": len(r["inconnus"]),
                         "clos": bool(r["inventaire"]["fin"])})


@app.get("/couverture/{ref}")
def couverture(ref: str, conn=Depends(get_conn)):
    """Couverture servie depuis data/covers, téléchargée au premier affichage si besoin."""
    n = conn.execute("SELECT id, isbn13, uid FROM notices WHERE id = ?", (db.id_notice(conn, ref),)).fetchone()
    if not n:
        return Response(status_code=404)
    cle = db.cle_couverture(n)
    entetes = {"Cache-Control": "max-age=86400"}
    if covers.chemin(cle).exists():
        return FileResponse(covers.chemin(cle), media_type="image/jpeg", headers=entetes)
    if covers.absente(cle).exists():
        return Response(status_code=404)
    urls = resolver.urls_couverture(conn, n["id"])
    if urls:
        with make_client() as client:
            if covers.telecharger(client, cle, urls):
                return FileResponse(covers.chemin(cle), media_type="image/jpeg", headers=entetes)
    return Response(status_code=404)


# --- Catalogue -----------------------------------------------------------------

PAR_PAGE = 60


def _criteres(q, lieu, etagere, classe, statut, a_classer, du, au, proprio="", lecture="") -> dict:
    """Paramètres d'URL du catalogue -> filtres de services.rechercher / ids_exemplaires."""
    return dict(q=q, lieu_id=("aucun" if lieu == "aucun" else _id(lieu)), etagere_id=_id(etagere),
                statut=statut or None, classe=classe or None, a_classer=a_classer,
                ajout_du=du or None, ajout_au=au or None, proprietaire=proprio or None, lecture=lecture or None)


def _etagere_du_lieu(conn, lieu: str, etagere: str) -> str:
    """Une étagère d'un autre lieu est ignorée : elle reste dans le formulaire quand on change de lieu."""
    if not _id(etagere):
        return ""
    row = conn.execute("SELECT lieu_id FROM etageres WHERE id = ?", (_id(etagere),)).fetchone()
    return etagere if row and (not lieu or str(row["lieu_id"]) == lieu) else ""


@app.get("/catalogue", response_class=HTMLResponse)
def catalogue(request: Request, q: str = "", lieu: str = "", etagere: str = "", systeme: str = "",
              classe: str = "", tri: str = "cote", statut: str = "", a_classer: str = "",
              du: str = "", au: str = "", proprio: str = "", lecture: str = "", vue: str = "liste", p: str = "1",
              conn=Depends(get_conn)):
    systeme = systeme if systeme in SYSTEMES else systeme_courant(conn)
    p = max(_id(p) or 1, 1)
    a_classer = bool(a_classer)
    etagere = _etagere_du_lieu(conn, lieu, etagere)
    try:
        rows, total = services.rechercher(
            conn, systeme=systeme, tri=tri, limite=PAR_PAGE, decalage=(p - 1) * PAR_PAGE,
            **_criteres(q, lieu, etagere, classe, statut, a_classer, du, au, proprio, lecture))
    except Erreur as e:
        return retour("/catalogue", err=str(e))
    filtres = {k: v for k, v in dict(q=q, lieu=lieu, etagere=etagere, systeme=systeme, classe=classe,
                                    tri=tri, statut=statut, du=du, au=au, proprio=proprio, lecture=lecture,
                                    vue=vue).items() if v}
    if a_classer:
        filtres["a_classer"] = "1"
    return page(request, conn, "catalogue.html", rows=rows, total=total, p=p,
                pages=max(1, -(-total // PAR_PAGE)), q=q, lieu=lieu, etagere=etagere, classe=classe,
                tri=tri, statut=statut, du=du, au=au, vue=vue, a_classer=a_classer, systeme=systeme,
                proprio=proprio, lecture=lecture, proprietaires=services.proprietaires(conn),
                filtres=filtres, aujourdhui=date.today().isoformat(),
                lieux=services.lieux(conn),
                classes=services.classes_presentes(conn, systeme, _id(lieu), proprio),
                qs=lambda **kw: urlencode({k: v for k, v in {**filtres, **kw}.items() if v not in ("", None)}))


@app.post("/catalogue/lot")
async def catalogue_lot(request: Request, conn=Depends(get_conn)):
    """Opération sur plusieurs exemplaires : ceux cochés, ou tous les résultats des filtres."""
    form = await request.form()
    suite = form.get("suite") or "/catalogue"
    try:
        if form.get("tous"):
            ids = services.ids_exemplaires(conn, systeme=form.get("systeme") or None, **_criteres(
                form.get("q", ""), form.get("lieu", ""), form.get("etagere", ""), form.get("classe", ""),
                form.get("statut", ""), bool(form.get("a_classer")), form.get("du", ""), form.get("au", ""),
                form.get("proprio", ""), form.get("lecture", "")))
        else:
            ids = [int(i) for i in form.getlist("ex") if str(i).isdigit()]
        if not ids:
            raise Erreur(tr("aucun livre sélectionné"))
        action = form.get("action")
        if action == "deplacer":
            if not form.get("emplacement"):
                raise Erreur(tr("choisissez où ranger les livres"))
            lieu_id, _, etagere_id = form.get("emplacement").partition(":")
            n = services.deplacer_lot(conn, ids, _id(lieu_id), _id(etagere_id))
            cible = services.nom_emplacement(conn, _id(lieu_id), _id(etagere_id))
            msg = tr("{n} livre(s) rangé(s) dans « {ou} »", n=n, ou=cible)
            if n < len(ids):
                msg += tr(" ({n} y étaient déjà)", n=len(ids) - n)
        elif action == "retirer":
            n = services.retirer_lot(conn, ids)
            msg = tr("{n} exemplaire(s) retiré(s) de la collection", n=n)
        elif action == "donner":
            vers = (form.get("vers") or "").strip()
            n = services.donner_lot(conn, ids, vers)
            msg = tr("{n} livre(s) donné(s) à {qui}", n=n, qui=vers)
        else:
            raise Erreur(tr("choisissez une opération"))
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=msg)


@app.post("/systeme")
def changer_systeme(systeme: str = Form(...), suite: str = Form("/catalogue"), conn=Depends(get_conn)):
    try:
        services.choisir_systeme(conn, systeme)
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite)


# --- Fiche livre ---------------------------------------------------------------

@app.get("/livre/{ref}", response_class=HTMLResponse)
def livre(request: Request, ref: str, conn=Depends(get_conn)):
    n = services.notice(conn, ref)
    if not n:
        return retour("/catalogue", err=tr("livre inconnu : {isbn}", isbn=ref))
    opts = {s: options_regles(s) for s in ("clil", "thema", "rayon")}
    return page(request, conn, "livre.html", n=n, lieux=services.lieux(conn), options=opts,
                proprietaires=services.proprietaires(conn), personnes=services.noms_personnes(conn))


def _champs_changes(form, n: dict, cles) -> dict:
    """Champs d'un formulaire dont la valeur a changé : seuls ceux-là comptent comme corrigés."""
    champs = {}
    for cle in cles:
        if cle not in form:
            continue
        # Les navigateurs envoient les fins de ligne en CRLF et le formulaire peut avoir été retouché
        nouveau = (form.get(cle) or "").replace("\r\n", "\n").strip()
        actuel = n.get(cle)
        if cle in ("auteurs", "sujets"):
            actuel = " ; ".join(actuel or [])
        if nouveau != ("" if actuel is None else str(actuel).replace("\r\n", "\n").strip()):
            champs[cle] = nouveau
    return champs


@app.post("/livre/{ref}/modifier")
async def livre_modifier(request: Request, ref: str, conn=Depends(get_conn)):
    form = await request.form()
    n = services.notice(conn, ref)
    if not n:
        return retour("/catalogue", err=tr("livre inconnu"))
    champs = _champs_changes(form, n, services.CHAMPS_MODIFIABLES)
    try:
        services.modifier_notice(conn, ref, champs)
    except Erreur as e:
        return retour(f"/livre/{ref}", err=str(e))
    return retour(f"/livre/{ref}", msg=tr("{n} champ(s) modifié(s)", n=len(champs)) if champs else tr("aucun changement"))


@app.post("/livre/{ref}/lecture")
async def livre_lecture(request: Request, ref: str, conn=Depends(get_conn)):
    form = await request.form()
    n = services.notice(conn, ref)
    if not n:
        return retour("/catalogue", err=tr("livre inconnu"))
    champs = _champs_changes(form, n, ("lecture", "lecture_debut", "lecture_fin", "etoiles"))
    try:
        services.modifier_notice(conn, ref, champs)
    except Erreur as e:
        return retour(f"/livre/{ref}#lecture", err=str(e))
    return retour(f"/livre/{ref}#lecture", msg=tr("lecture enregistrée") if champs else tr("aucun changement"))


@app.post("/livre/{ref}/note")
def livre_note(ref: str, notes: str = Form(""), conn=Depends(get_conn)):
    try:
        services.modifier_notice(conn, ref, {"notes": notes})
    except Erreur as e:
        return retour(f"/livre/{ref}", err=str(e))
    return retour(f"/livre/{ref}#note", msg=tr("note enregistrée") if notes.strip() else tr("note effacée"))


@app.post("/livre/{ref}/liberer")
def livre_liberer(ref: str, champ: str = Form(...), conn=Depends(get_conn)):
    try:
        services.liberer_champ(conn, ref, champ)
    except Erreur as e:
        return retour(f"/livre/{ref}", err=str(e))
    return retour(f"/livre/{ref}", msg=tr("« {champ} » rendu aux catalogues", champ=champ))


@app.post("/livre/{ref}/classer")
def livre_classer(ref: str, systeme: str = Form(...), code: str = Form(""), libelle: str = Form(""),
                  conn=Depends(get_conn)):
    try:
        services.fixer_classification(conn, ref, systeme, code or None, libelle or None)
    except Erreur as e:
        return retour(f"/livre/{ref}", err=str(e))
    nom = tr(SYSTEMES[systeme])
    msg = tr("cote {systeme} fixée à la main", systeme=nom) if code else tr("cote {systeme} recalculée", systeme=nom)
    return retour(f"/livre/{ref}", msg=msg)


@app.post("/livre/{ref}/relancer")
def livre_relancer(ref: str, conn=Depends(get_conn)):
    n = services.notice(conn, ref)
    if not n:
        return retour("/catalogue", err=tr("livre inconnu"))
    if not n["isbn13"]:
        return retour(f"/livre/{ref}", err=tr("ce livre n'a pas d'ISBN : aucun catalogue à interroger"))
    with make_client() as client:
        echecs = resolver.fetch_sources(conn, client, n["id"], refresh=True)
        n = resolver.rebuild(conn, n["id"])
        if n and not echecs:
            resolver.telecharger_couverture(conn, client, n["id"], forcer=True)
    if echecs:
        return retour(f"/livre/{ref}", err=tr("catalogues injoignables ({sources}) : la fiche est conservée, réessayez plus tard",
                                              sources=", ".join(echecs)))
    return retour(f"/livre/{ref}", msg=tr("catalogues réinterrogés : {statut}", statut=n["statut"] if n else "?"))


@app.post("/exemplaire/{ex_id}/deplacer")
def ex_deplacer(ex_id: int, emplacement: str = Form(""), suite: str = Form("/catalogue"), conn=Depends(get_conn)):
    lieu_id, _, etagere_id = emplacement.partition(":")
    try:
        services.deplacer_exemplaire(conn, ex_id, _id(lieu_id), _id(etagere_id))
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=tr("exemplaire déplacé"))


@app.post("/exemplaire/{ex_id}/preter")
def ex_preter(ex_id: int, emprunteur: str = Form(...), suite: str = Form("/prets"), conn=Depends(get_conn)):
    try:
        services.preter(conn, ex_id, emprunteur)
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=tr("prêté à {qui}", qui=emprunteur))


@app.post("/exemplaire/{ex_id}/rendre")
def ex_rendre(ex_id: int, suite: str = Form("/prets"), conn=Depends(get_conn)):
    try:
        res = services.rendre(conn, ex_id)
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=tr("rendu par {qui}", qui=res["emprunteur"]))


@app.post("/exemplaire/{ex_id}/donner")
def ex_donner(ex_id: int, vers: str = Form(""), suite: str = Form("/catalogue"), conn=Depends(get_conn)):
    try:
        services.donner(conn, ex_id, vers)
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=tr("livre donné à {qui}", qui=vers.strip()))


@app.post("/exemplaire/{ex_id}/details")
async def ex_details(request: Request, ex_id: int, conn=Depends(get_conn)):
    form = await request.form()
    suite = form.get("suite") or "/catalogue"
    ex = conn.execute("SELECT * FROM exemplaires WHERE id = ?", (ex_id,)).fetchone()
    if not ex:
        return retour(suite, err=tr("exemplaire introuvable"))
    champs = _champs_changes(form, dict(ex), services.CHAMPS_EXEMPLAIRE)
    try:
        services.modifier_exemplaire(conn, ex_id, champs)
    except Erreur as e:
        return retour(suite, err=str(e))
    return retour(suite, msg=tr("exemplaire enregistré") if champs else tr("aucun changement"))


@app.post("/exemplaire/{ex_id}/supprimer")
def ex_supprimer(ex_id: int, conn=Depends(get_conn)):
    try:
        services.annuler_exemplaire(conn, ex_id)
    except Erreur as e:
        return retour("/catalogue", err=str(e))
    return retour("/catalogue", msg=tr("exemplaire retiré de la collection"))


@app.post("/livre/{ref}/exemplaire")
def livre_exemplaire(ref: str, emplacement: str = Form(""), conn=Depends(get_conn)):
    lieu_id, _, etagere_id = emplacement.partition(":")
    try:
        n = services.resume_notice(conn, ref)
        if not n:
            raise Erreur(tr("livre inconnu"))
        services.ajouter(conn, n["reference"], _id(lieu_id), _id(etagere_id))
    except Erreur as e:
        return retour(f"/livre/{ref}", err=str(e))
    return retour(f"/livre/{ref}", msg=tr("exemplaire ajouté"))


# --- Ajout manuel --------------------------------------------------------------

CHAMPS_MANUEL = ["sous_titre", "editeur", "collection", "annee", "pages", "langue", "langue_originale",
                 "forme", "public", "sujets", "resume", "couverture_url", "notes"]


def _recherche_bnf(titre: str, auteur: str, annee: str) -> list[dict]:
    """Recherche BnF titre/auteur ; une panne lève Erreur avec un message lisible."""
    from ..sources import bnf

    try:
        with make_client() as client:
            return bnf.rechercher(client, titre, auteur, annee)
    except bnf.RechercheImpossible as e:
        raise Erreur(tr("la BnF n'a pas pu être interrogée ({detail}) : saisissez le livre à la main ci-dessous",
                        detail=e))


@app.get("/manuel", response_class=HTMLResponse)
def manuel_page(request: Request, titre: str = "", auteur: str = "", annee: str = "", chercher: str = "",
                emplacement: str = "", proprio: str = "", conn=Depends(get_conn)):
    """Livres sans code-barre : recherche BnF (facultative) puis saisie complète."""
    resultats, err, deja = None, None, []
    if chercher and (titre.strip() or auteur.strip()):
        try:
            resultats = _recherche_bnf(titre, auteur, annee)
        except Erreur as e:
            err = str(e)
        deja, _ = services.rechercher(conn, " ".join([titre, auteur]), proprietaire="tous", limite=5)
    return page(request, conn, "manuel.html", lieux=services.lieux(conn), resultats=resultats, deja=deja,
                titre=titre, auteur=auteur, annee=annee, emplacement=emplacement,
                proprio=proprio or services.proprietaire_local(conn), proprietaires=services.proprietaires(conn),
                valeurs={"titre": titre, "auteurs": auteur, "annee": annee}, **({"err": err} if err else {}))


@app.post("/manuel/bnf")
def manuel_bnf(ark: str = Form(...), titre: str = Form(""), auteur: str = Form(""), annee: str = Form(""),
               emplacement: str = Form(""), proprio: str = Form(""), conn=Depends(get_conn)):
    lieu_id, _, etagere_id = emplacement.partition(":")
    suite = "/manuel?" + urlencode(dict(titre=titre, auteur=auteur, annee=annee, chercher=1,
                                        emplacement=emplacement, proprio=proprio))
    try:
        choix = next((r for r in _recherche_bnf(titre, auteur, annee) if r["ark"] == ark), None)
        if not choix:
            raise Erreur(tr("cette notice n'est plus proposée par la BnF : saisissez le livre à la main"))
        res = services.ajouter_depuis_bnf(conn, choix, _id(lieu_id), _id(etagere_id), proprio or None)
    except Erreur as e:
        return retour(suite, err=str(e))
    if res.get("recherche") and worker:
        worker.wake()
    return retour(f"/livre/{res['notice_id']}", msg=tr("livre ajouté"))


@app.post("/manuel", response_class=HTMLResponse)
async def manuel_post(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    valeurs = {k: (form.get(k) or "").strip() for k in ["titre", "auteurs", "isbn", *CHAMPS_MANUEL]}
    emplacement, proprio = form.get("emplacement") or "", (form.get("proprio") or "").strip()
    lieu_id, _, etagere_id = emplacement.partition(":")
    try:
        res = services.creer_notice_manuelle(
            conn, valeurs["titre"], valeurs["auteurs"], isbn=valeurs["isbn"] or None,
            lieu_id=_id(lieu_id), etagere_id=_id(etagere_id), proprietaire=proprio or None,
            **{k: valeurs[k] for k in CHAMPS_MANUEL})
    except Erreur as e:
        # On réaffiche le formulaire tel quel : rien de ce qui a été tapé n'est perdu
        return page(request, conn, "manuel.html", lieux=services.lieux(conn), resultats=None, deja=[],
                    titre=valeurs["titre"], auteur=valeurs["auteurs"], annee=valeurs["annee"],
                    emplacement=emplacement, proprio=proprio, proprietaires=services.proprietaires(conn),
                    valeurs=valeurs, err=str(e))
    if res["recherche"] and worker:
        worker.wake()
    if form.get("encore"):
        return retour("/manuel?" + urlencode(dict(emplacement=emplacement, proprio=proprio)),
                      msg=tr("« {titre} » ajouté ; livre suivant", titre=valeurs["titre"]))
    return retour(f"/livre/{res['notice_id']}", msg=tr("livre ajouté"))


# --- Lieux ---------------------------------------------------------------------

@app.get("/lieux", response_class=HTMLResponse)
def lieux_page(request: Request, conn=Depends(get_conn)):
    return page(request, conn, "lieux.html", lieux=services.lieux(conn),
                non_localises=services.nb_non_localises(conn),
                inventaires=services.inventaires(conn))


@app.post("/lieux/ajouter")
def lieu_ajouter(nom: str = Form(...), description: str = Form(""), conn=Depends(get_conn)):
    try:
        services.creer_lieu(conn, nom, description or None)
    except Erreur as e:
        return retour("/lieux", err=str(e))
    return retour("/lieux", msg=tr("lieu « {nom} » créé", nom=nom))


@app.post("/lieux/{lieu_id}/etagere")
def lieu_etagere(lieu_id: int, nom: str = Form(...), conn=Depends(get_conn)):
    try:
        for n in [x.strip() for x in nom.split(",") if x.strip()]:
            services.creer_etagere(conn, lieu_id, n)
    except Erreur as e:
        return retour("/lieux", err=str(e))
    return retour("/lieux", msg=tr("étagère(s) ajoutée(s)"))


@app.post("/lieux/{lieu_id}/renommer")
def lieu_renommer(lieu_id: int, nom: str = Form(...), description: str = Form(""), conn=Depends(get_conn)):
    try:
        services.renommer_lieu(conn, lieu_id, nom, description or None)
    except Erreur as e:
        return retour("/lieux", err=str(e))
    return retour("/lieux", msg=tr("lieu renommé"))


@app.post("/lieux/{lieu_id}/supprimer")
def lieu_supprimer(lieu_id: int, conn=Depends(get_conn)):
    n = services.supprimer_lieu(conn, lieu_id)
    return retour("/lieux", msg=tr("lieu supprimé ; {n} livre(s) désormais non localisé(s)", n=n))


@app.post("/etageres/{etagere_id}/renommer")
def etagere_renommer(etagere_id: int, nom: str = Form(...), conn=Depends(get_conn)):
    try:
        services.renommer_etagere(conn, etagere_id, nom)
    except Erreur as e:
        return retour("/lieux", err=str(e))
    return retour("/lieux", msg=tr("étagère renommée"))


@app.post("/etageres/{etagere_id}/supprimer")
def etagere_supprimer(etagere_id: int, conn=Depends(get_conn)):
    services.supprimer_etagere(conn, etagere_id)
    return retour("/lieux", msg=tr("étagère supprimée"))


@app.get("/lieux/{lieu_id}/rangement", response_class=HTMLResponse)
def rangement(request: Request, lieu_id: int, etagere: str = "", systeme: str = "", conn=Depends(get_conn)):
    systeme = systeme if systeme in SYSTEMES else systeme_courant(conn)
    lieu = conn.execute("SELECT * FROM lieux WHERE id = ?", (lieu_id,)).fetchone()
    if not lieu:
        return retour("/lieux", err=tr("lieu inconnu"))
    rows = export.rangement(conn, lieu_id, _id(etagere), systeme)
    return page(request, conn, "rangement.html", lieu=dict(lieu), rows=rows, systeme=systeme,
                etagere=etagere, etageres=[dict(e) for e in conn.execute(
                    "SELECT * FROM etageres WHERE lieu_id = ? ORDER BY ordre, nom", (lieu_id,))])


@app.get("/inventaire/{inv_id}", response_class=HTMLResponse)
def inventaire_page(request: Request, inv_id: int, conn=Depends(get_conn)):
    try:
        r = services.rapport_inventaire(conn, inv_id)
    except Erreur as e:
        return retour("/lieux", err=str(e))
    return page(request, conn, "inventaire.html", r=r)


@app.post("/inventaire/{inv_id}/cloturer")
def inventaire_cloturer(inv_id: int, ranger: str = Form(""), ajouter: str = Form(""), conn=Depends(get_conn)):
    try:
        res = services.cloturer_inventaire(conn, inv_id, ranger_ailleurs=bool(ranger), ajouter_inconnus=bool(ajouter))
    except Erreur as e:
        return retour(f"/inventaire/{inv_id}", err=str(e))
    if res["ajoutes"] and worker:
        worker.wake()
    return retour(f"/inventaire/{inv_id}",
                  msg=tr("inventaire clôturé : {d} remis en place, {a} ajouté(s)", d=res["deplaces"], a=res["ajoutes"]))


# --- À traiter, prêts, stats, réglages, exports --------------------------------

@app.get("/a-traiter", response_class=HTMLResponse)
def a_traiter(request: Request, conn=Depends(get_conn)):
    return page(request, conn, "a_traiter.html", data=services.a_traiter(conn))


@app.post("/a-traiter/relancer")
def a_traiter_relancer(conn=Depends(get_conn)):
    n = services.relancer(conn)
    if worker:
        worker.wake()
    return retour("/a-traiter", msg=tr("{n} livre(s) remis en recherche", n=n))


@app.get("/prets", response_class=HTMLResponse)
def prets_page(request: Request, conn=Depends(get_conn)):
    return page(request, conn, "prets.html", prets=services.prets(conn),
                historique=services.prets(conn, en_cours=False)[:50])


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, conn=Depends(get_conn)):
    return page(request, conn, "stats.html", s=services.stats(conn))


@app.get("/reglages", response_class=HTMLResponse)
def reglages(request: Request, conn=Depends(get_conn)):
    key = db.get_meta(conn, "google_api_key")
    return page(request, conn, "reglages.html", google=bool(key), db_path=db.db_path(),
                nb_raw=conn.execute("SELECT count(*) FROM raw_responses").fetchone()[0],
                proprietaire=services.proprietaire_local(conn), lieux=services.lieux(conn))


@app.post("/reglages")
def reglages_post(systeme: str = Form(...), google_api_key: str = Form(""), effacer_google: str = Form(""),
                  langue: str = Form(""), proprietaire: str = Form(""), conn=Depends(get_conn)):
    try:
        services.choisir_systeme(conn, systeme)
        if proprietaire.strip():
            services.renommer_proprietaire_local(conn, proprietaire)
    except Erreur as e:
        return retour("/reglages", err=str(e))
    if langue in i18n.LANGUES:
        db.set_meta(conn, "langue", langue)
        i18n.utiliser(langue)
    if effacer_google:
        db.set_meta(conn, "google_api_key", None)
    elif google_api_key.strip():
        db.set_meta(conn, "google_api_key", google_api_key.strip())
    return retour("/reglages", msg=tr("réglages enregistrés"))


@app.post("/reglages/reclasser")
def reglages_reclasser(conn=Depends(get_conn)):
    ids = [r["id"] for r in conn.execute("SELECT id FROM notices WHERE statut != 'en_attente'")]
    for notice_id in ids:
        resolver.rebuild(conn, notice_id)
    return retour("/reglages", msg=tr("{n} notices reconstruites et reclassées, sans requête réseau", n=len(ids)))


@app.get("/manifest.webmanifest")
def manifest(request: Request, conn=Depends(get_conn)):
    """Pour « Ajouter à l'écran d'accueil » : l'appli s'ouvre alors sans barres, en plein écran.

    Sur le téléphone, l'adresse de départ porte la clé : une appli d'écran d'accueil iOS a
    ses propres cookies et doit pouvoir se reconnecter seule.
    """
    depart = "/scan?camera=1"
    if request.client and request.client.host not in LOCAL:
        depart += "&cle=" + (telephone.cle_admin(conn) if _admin(request) else telephone.cle(conn))
    return JSONResponse({
        "name": "Bibliothèque", "short_name": "Bibliothèque", "id": "/scan",
        "start_url": depart, "scope": "/", "display": "standalone", "orientation": "portrait",
        "background_color": "#000000", "theme_color": "#7a2a1c", "lang": "fr",
        "icons": [{"src": "/static/icone-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icone-512.png", "sizes": "512x512", "type": "image/png"}],
    }, media_type="application/manifest+json")


@app.get("/telephone", response_class=HTMLResponse)
def telephone_page(request: Request, conn=Depends(get_conn)):
    if not _admin(request):
        return retour("/scan")            # les QR codes ne s'affichent que sur l'ordinateur
    urls = telephone.urls(conn)
    # omitsize : viewBox au lieu d'une taille fixe, pour que le CSS mette les deux QR à la même taille
    qr = {k: segno.make(urls[k], error="m").svg_inline(scale=5, dark="#2a2018", light="#ffffff", border=2,
                                                        omitsize=True)
          for k in ("installation", "scan")}
    return page(request, conn, "telephone.html", actif=telephone.etat["actif"], urls=urls, qr=qr,
                ip=telephone.etat["ip"] or telephone.ip_locale(), empreinte=certs.empreinte_ca(),
                lanceur="biblio.cmd" if sys.platform == "win32" else "./biblio.sh",
                ports=(telephone.PORT_HTTPS, telephone.PORT_INSTALLATION))


@app.post("/telephone/nouvelle-cle")
def telephone_nouvelle_cle(request: Request, conn=Depends(get_conn)):
    if not _admin(request):
        return Response(status_code=403)
    telephone.nouvelle_cle(conn)
    return retour("/telephone", msg=tr("nouvelle clé : les téléphones déjà connectés doivent rescanner le QR code"))


@app.get("/export.{fmt}")
def exporter(fmt: str, systeme: str = "", conn=Depends(get_conn)):
    systeme = systeme if systeme in SYSTEMES else None
    nom = f"bibliotheque-{date.today()}.{fmt}"
    if fmt == "xlsx":
        data = export.xlsx_bytes(conn, systeme=systeme)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        data = export.csv_bytes(conn, systeme=systeme)
        media = "text/csv; charset=utf-8"
    else:
        return Response(status_code=404)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.get("/partage.db")
def partage_db(lieu: list[str] = Query(default=[]), masquer: bool = False, prets: bool = False,
               conn=Depends(get_conn)):
    """Fichier de partage pour un ami (voir partage.exporter_partage)."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier) / "partage.db"
        partage.exporter_partage(conn, chemin, lieux=[i for i in map(_id, lieu) if i], masquer_lieux=masquer,
                                 avec_prets=prets)
        data = chemin.read_bytes()
    nom = f"bibliotheque-{services.proprietaire_local(conn)}-{date.today()}.db"
    nom = "".join(c if c.isalnum() or c in "-_." else "_" for c in nom)
    return Response(data, media_type="application/vnd.sqlite3",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


# --- Mini-serveur d'installation (HTTP, réseau local) ----------------------------
# Seule page servie sans chiffrement : de quoi installer le certificat sur le
# téléphone. Aucune donnée de la bibliothèque n'y est accessible.

installation = FastAPI(title="Installation", docs_url=None, redoc_url=None, openapi_url=None)


@installation.get("/", response_class=HTMLResponse)
def installation_page(request: Request):
    i18n.utiliser(_langue_choisie())
    return templates.TemplateResponse(request, "installation.html", {
        "empreinte": certs.empreinte_ca(), "port_https": telephone.PORT_HTTPS,
        "ip": telephone.etat["ip"] or request.url.hostname})


@installation.get("/bibliotheque-ca.crt")
def installation_ca(fichier: bool = False):
    # Type « certificat » : Safari propose d'installer le profil. Firefox, lui, veut le
    # gérer lui-même et annule sur Android : « ?fichier=1 » le livre en simple fichier.
    media = "application/octet-stream" if fichier else "application/x-x509-ca-cert"
    return Response(certs.ca_der(), media_type=media,
                    headers={"Content-Disposition": 'attachment; filename="bibliotheque-ca.crt"'})
