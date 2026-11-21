"""Le poste de scan dans un vrai navigateur (Chromium, via Playwright) : douchette, étiquettes, file hors ligne,
et sur un téléphone Android imité (écran, tactile et user agent d'un Pixel 7).

Un vrai serveur tourne sur un port libre, avec son fil de fond. Les catalogues sont simulés par les
fixtures : aucun test ne sort sur le réseau. Sans Chromium (`uv run playwright install chromium`),
ces tests sont sautés.
"""

import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from biblio import db, etiquettes, resolver, services  # noqa: E402

from .conftest import charger, fixture  # noqa: E402


def _chromium_installe() -> bool:
    try:
        with sync_api.sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = [pytest.mark.navigateur,
              pytest.mark.skipif(not _chromium_installe(), reason="Chromium absent : uv run playwright install chromium")]

CHANSON, ASTERIX = "9782070196678", "9782014001143"
FICHES_BNF = {CHANSON: "bnf_chanson_douce.xml", ASTERIX: "bnf_asterix.xml"}
# La douchette réglée en QWERTY sur un Mac en AZERTY : chaque chiffre arrive comme le caractère de sa touche
TOUCHES_AZERTY = dict(zip("1234567890", "&é\"'(§è!çà", strict=True))


def _catalogues_simules(conn, client, ref, refresh=False):
    """Remplace fetch_sources : la BnF « répond » avec la fixture du livre, rien pour les autres codes."""
    notice_id = db.id_notice(conn, ref)
    isbn = conn.execute("SELECT isbn13 FROM notices WHERE id = ?", (notice_id,)).fetchone()[0]
    if isbn in FICHES_BNF:
        conn.execute("INSERT OR REPLACE INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                     "VALUES (?, 'bnf', 'ok', ?, ?)", (notice_id, fixture(FICHES_BNF[isbn]), db.now()))
        conn.commit()
    return []


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serveur(tmp_path, monkeypatch):
    import uvicorn

    from biblio.web.app import app

    chemin = tmp_path / "navigateur.db"
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    monkeypatch.setattr(resolver, "fetch_sources", _catalogues_simules)
    monkeypatch.setattr(resolver, "telecharger_couverture", lambda *a, **kw: False)
    conn = db.connect(chemin)
    port = _port_libre()
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    limite = time.monotonic() + 10
    while not serveur.started:
        assert time.monotonic() < limite, "le serveur de test n'a pas démarré"
        time.sleep(0.05)
    yield SimpleNamespace(url=f"http://localhost:{port}", conn=conn)
    serveur.should_exit = True
    fil.join(timeout=10)
    conn.close()


def _nb_exemplaires(conn) -> int:
    return conn.execute("SELECT count(*) FROM exemplaires").fetchone()[0]


def _douchette(page, code: str) -> None:
    """Comme une douchette : les chiffres au clavier, très vite, puis Entrée."""
    page.keyboard.type(code, delay=5)
    page.keyboard.press("Enter")


def _dernier_scan(page):
    return page.locator("#flux .scan-item").first


def test_la_douchette_ajoute_le_livre_puis_la_fiche_arrive(page, serveur):
    page.goto(serveur.url + "/scan")
    _douchette(page, CHANSON)
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    expect(_dernier_scan(page)).to_contain_text("Chanson douce", timeout=10_000)   # complété par le fil de fond
    expect(page.locator("#nb-scans")).to_have_text("1")
    assert _nb_exemplaires(serveur.conn) == 1


@pytest.mark.parametrize("avec_code", [False, True], ids=["caractere-seul", "touche-physique"])
def test_la_douchette_en_azerty_donne_les_bons_chiffres(page, serveur, avec_code):
    """Sans `code`, la table AZERTY traduit « è » en 7 ; avec (`Digit7`, cas de l'iPhone), la touche physique l'emporte."""
    page.goto(serveur.url + "/scan")
    touches = [{"key": TOUCHES_AZERTY[c], "code": f"Digit{c}" if avec_code else ""} for c in ASTERIX]
    page.evaluate("""(touches) => {
        for (const t of touches) document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {...t, bubbles: true}));
    }""", touches)
    page.keyboard.press("Enter")
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    expect(_dernier_scan(page)).to_contain_text("Astérix", timeout=10_000)
    assert serveur.conn.execute("SELECT isbn13 FROM notices").fetchone()[0] == ASTERIX


def test_une_etiquette_choisit_l_emplacement_puis_le_livre_y_est_range(page, serveur):
    salon = services.creer_lieu(serveur.conn, "Salon")
    e1 = services.creer_etagere(serveur.conn, salon, "É1")
    numero = serveur.conn.execute("SELECT etiquette FROM etageres WHERE id = ?", (e1,)).fetchone()[0]
    page.goto(serveur.url + "/scan")

    _douchette(page, etiquettes.code_de("etageres", numero))
    expect(page.locator("#lieu")).to_have_value(str(salon))         # choisi dans la page, sans le serveur
    expect(page.locator("#etagere")).to_have_value(str(e1))
    expect(_dernier_scan(page)).to_contain_text("Salon › É1")

    _douchette(page, CHANSON)
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    expect(_dernier_scan(page)).to_contain_text("→ Salon › É1")
    lieu, etagere = serveur.conn.execute("SELECT lieu_id, etagere_id FROM exemplaires").fetchone()
    assert (lieu, etagere) == (salon, e1)

    page.reload()                                                     # l'emplacement est retenu par le navigateur
    expect(page.locator("#etagere")).to_have_value(str(e1))


def test_une_double_lecture_n_ajoute_qu_un_exemplaire(page, serveur):
    page.goto(serveur.url + "/scan")
    _douchette(page, CHANSON)
    _douchette(page, CHANSON)
    expect(page.locator("#flux .scan-item")).to_have_count(2)
    expect(_dernier_scan(page)).to_contain_text("Double lecture")
    assert _nb_exemplaires(serveur.conn) == 1


def test_annuler_retire_le_livre_ajoute(page, serveur):
    page.goto(serveur.url + "/scan")
    _douchette(page, CHANSON)
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    _dernier_scan(page).get_by_role("button", name="Annuler").click()
    expect(_dernier_scan(page)).to_have_class("scan-item ajoute annule")
    assert _nb_exemplaires(serveur.conn) == 0


def test_a_la_main_avec_le_bouton_valider(page, serveur):
    page.goto(serveur.url + "/scan")
    page.get_by_role("button", name="À la main").click()
    page.locator("#code").fill("978-2-07-019667-8")
    page.get_by_role("button", name="Valider").click()
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    assert serveur.conn.execute("SELECT isbn13 FROM notices").fetchone()[0] == CHANSON


def test_hors_ligne_les_scans_sont_gardes_puis_envoyes_dans_l_ordre(page, serveur):
    page.goto(serveur.url + "/scan")
    page.context.set_offline(True)
    _douchette(page, CHANSON)
    _douchette(page, ASTERIX)
    expect(page.locator("#file-scan")).to_contain_text("2 scans gardés sur cet appareil")
    expect(page.locator("#flux .badge.attente")).to_have_count(2)
    assert _nb_exemplaires(serveur.conn) == 0

    page.context.set_offline(False)                   # envoi au retour du réseau (« online », sinon toutes les 5 s)
    expect(page.locator("#file-scan")).to_be_hidden(timeout=10_000)
    expect(page.locator("#flux .badge.ajoute")).to_have_count(2)
    ordre = [r[0] for r in serveur.conn.execute(
        "SELECT n.isbn13 FROM exemplaires e JOIN notices n ON n.id = e.notice_id ORDER BY e.id")]
    assert ordre == [CHANSON, ASTERIX]


def test_un_autre_site_ne_peut_rien_ecrire(page, serveur):
    """Un vrai navigateur envoie Origin : une page d'une autre origine (ici 127.0.0.1 contre localhost)
    qui poste vers la bibliothèque, par fetch ou par formulaire, est refusée."""
    autre_origine = serveur.url.replace("localhost", "127.0.0.1")
    page.goto(autre_origine + "/scan")
    page.evaluate("""([cible, code]) => fetch(cible + "/api/scan", {method: "POST", mode: "no-cors", credentials: "include",
                       headers: {"Content-Type": "text/plain"}, body: JSON.stringify({mode: "ajout", code})})""",
                  [serveur.url, CHANSON])
    page.evaluate("""(cible) => {
        const f = Object.assign(document.createElement("form"), {method: "POST", action: cible + "/lieux/ajouter"});
        f.append(Object.assign(document.createElement("input"), {name: "nom", value: "Piège"}));
        document.body.append(f);
        f.submit();
    }""", serveur.url)
    expect(page.locator("body")).to_contain_text("Requête refusée")
    assert _nb_exemplaires(serveur.conn) == 0
    assert not serveur.conn.execute("SELECT 1 FROM lieux").fetchone()


# --- Téléphone Android (Pixel 7 imité : écran de 412 px, tactile, Chrome Android) ---------------------

@pytest.fixture
def telephone(browser, playwright):
    contexte = browser.new_context(**playwright.devices["Pixel 7"])
    yield contexte.new_page()
    contexte.close()


def _focus_dans_le_champ(page) -> bool:
    return page.evaluate("document.activeElement && document.activeElement.id === 'code'")


def test_au_telephone_on_tape_le_code_a_la_main_sans_clavier_surprise(telephone, serveur):
    page = telephone
    page.goto(serveur.url + "/scan")
    expect(page.locator('.saisies [data-saisie="main"]')).to_have_class("actif")    # pas de douchette par défaut
    expect(page.locator("#code")).to_have_attribute("placeholder", "Tapez l'ISBN ou le code-barres…")
    expect(page.locator("#camera-ouvrir")).to_be_visible()
    assert not _focus_dans_le_champ(page)                 # le clavier virtuel ne s'ouvre pas tout seul

    page.locator("#code").tap()
    page.locator("#code").fill(CHANSON)
    page.keyboard.press("Enter")                          # la touche « OK » du clavier virtuel
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    expect(_dernier_scan(page)).to_contain_text("Chanson douce", timeout=10_000)
    assert not _focus_dans_le_champ(page)                 # le clavier se referme après chaque livre

    page.locator("#code").tap()
    page.locator("#code").fill(ASTERIX)
    page.get_by_role("button", name="Valider").tap()      # ou le bouton, sous le champ
    expect(_dernier_scan(page)).to_contain_text("Astérix", timeout=10_000)
    assert _nb_exemplaires(serveur.conn) == 2


def test_au_telephone_une_douchette_bluetooth_scanne_sans_clavier(telephone, serveur):
    page = telephone
    page.goto(serveur.url + "/scan")
    page.locator('.saisies [data-saisie="douchette"]').tap()
    expect(page.locator("#code")).to_have_attribute("inputmode", "none")     # le clavier virtuel reste fermé
    _douchette(page, ASTERIX)
    expect(_dernier_scan(page)).to_contain_text("Ajouté")
    page.reload()                                         # le choix est retenu par le téléphone
    expect(page.locator('.saisies [data-saisie="douchette"]')).to_have_class("actif")


def test_au_telephone_le_menu_mene_aux_autres_pages(telephone, serveur):
    page = telephone
    page.goto(serveur.url + "/scan")
    expect(page.get_by_role("navigation").first.get_by_role("link", name="Statistiques")).to_be_hidden()
    page.locator("#ouvrir-menu").tap()
    menu = page.locator("#menu-lateral")
    expect(menu).to_be_visible()
    menu.get_by_role("link", name="Statistiques").tap()
    expect(page).to_have_url(serveur.url + "/stats")


def test_au_telephone_aucune_page_ne_deborde_en_largeur(telephone, serveur):
    salon = services.creer_lieu(serveur.conn, "Bibliothèque du salon")
    etagere = services.creer_etagere(serveur.conn, salon, "Étagère du haut, côté fenêtre")
    services.ajouter(serveur.conn, CHANSON, salon, etagere)
    notice_id = charger(serveur.conn, CHANSON, bnf=FICHES_BNF[CHANSON])["id"]
    services.ajouter(serveur.conn, "9780000000002")                    # introuvable : la page À traiter a une ligne
    page = telephone
    ecran = page.viewport_size["width"]       # sur mobile, Chrome dézoome une page trop large : innerWidth grandit avec
    trop_larges = {}
    for chemin in ("/scan", "/catalogue", f"/livre/{notice_id}", "/lieux", "/a-traiter", "/manuel", "/prets",
                   "/stats", "/reglages", "/telephone", "/admin", "/compte"):
        page.goto(serveur.url + chemin)
        contenu = page.evaluate("document.documentElement.scrollWidth")
        if contenu > ecran:
            trop_larges[chemin] = contenu
    assert not trop_larges, f"pages plus larges que l'écran de {ecran} px : {trop_larges}"

