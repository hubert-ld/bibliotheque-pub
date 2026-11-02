"""La CLI de bout en bout, sans réseau : chaque commande sur une base temporaire."""

import pytest
from typer.testing import CliRunner

from biblio import db, i18n, partage, services
from biblio.cli import app

from .conftest import charger

CHANSON = "9782070196678"
ASTERIX = "9782014001143"
VARGAS = "9782290382608"
runner = CliRunner()


@pytest.fixture(autouse=True)
def anglais(monkeypatch):
    i18n.utiliser("en")
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def conn():
    c = db.connect()
    salon = services.creer_lieu(c, "Salon")
    services.creer_etagere(c, salon, "É1")
    for isbn, fichier in ((CHANSON, "bnf_chanson_douce.xml"), (ASTERIX, "bnf_asterix.xml"), (VARGAS, "bnf_vargas.xml")):
        services.ajouter(c, isbn, salon)
        charger(c, isbn, bnf=fichier)
    yield c
    c.close()


def run(*args, input=None, code=0):
    r = runner.invoke(app, [str(a) for a in args], input=input)
    assert r.exit_code == code, (args, r.output, r.exception)
    return r.output


@pytest.mark.parametrize("args", [
    ["place", "list"], ["place", "add", "Cave"], ["place", "shelf", "Salon", "É2"], ["place", "rename", "Salon/É1", "É9"],
    ["show", CHANSON], ["where", CHANSON], ["where", "slimani"], ["search", "slimani"], ["search", "--owner", "all"],
    ["list", "-s", "rayon"], ["todo"], ["edit", CHANSON, "--form", "essai"], ["note", CHANSON, "--set", "**x**"],
    ["note", CHANSON], ["classify", CHANSON, "dewey", "843.92"], ["classify", CHANSON, "dewey"],
    ["move", CHANSON, "Salon/É1"], ["lend", CHANSON, "Marie"], ["loans"], ["owners"], ["give", ASTERIX, "Victor", "--yes"],
    ["system"], ["system", "rayon"], ["reclassify"], ["reclassify", "--reread"], ["config"], ["config", "langue", "en"],
    ["config", "proprietaire", "JD"], ["stats"], ["sql", "select count(*) from notices"], ["phone"],
    ["manual", "--title", "Vieux", "--authors", "Camille Dupont", "--no-search", "-p", "Salon"], ["remove", "1", "--yes"],
])
def test_commandes(conn, args):
    run(*args)


@pytest.mark.parametrize("args", [
    ["show", "9999"], ["search", "--since", "31/10"], ["search", "--system", "foo"], ["list", "--system", "foo"],
    ["search", "--sort", "foo"], ["export", "--system", "foo"], ["classify", CHANSON, "foo", "1"],
    ["edit", CHANSON, "--release", "nimportequoi"], ["config", "langue", "xx"], ["sql", "select * from nope"],
    ["remove", "999", "--yes"], ["merge", "/inexistant/x.db"], ["import", "/inexistant/x.txt"],
])
def test_erreurs_sans_trace_python(conn, args):
    r = runner.invoke(app, args)
    assert r.exit_code == 1 and isinstance(r.exception, SystemExit), (args, r.output, r.exception)
    assert "Traceback" not in r.output


def test_exports(conn, tmp_path):
    run("export", "-f", "csv", "-o", tmp_path / "a.csv")
    run("export", "-o", tmp_path / "a.xlsx")
    assert (tmp_path / "a.csv").stat().st_size and (tmp_path / "a.xlsx").stat().st_size


def test_import_compte_juste(conn, tmp_path):
    codes = tmp_path / "codes.txt"
    codes.write_text("# commentaire\n9782253140870\n9782253140870;x\nabc\n")
    sortie = run("import", codes, "--no-resolve")
    assert "2 cop(ies) imported" in sortie and "1 duplicate" in sortie and "1 error" in sortie
    assert len(services.exemplaires_de(conn, "9782253140870")) == 2


@pytest.mark.parametrize("titre", ["Titre [/x] fermant", "L'[im]possible", "Le [sic] roman", "[VILLE] Salon"])
def test_crochets_affiches_tels_quels(conn, titre):
    res = services.creer_notice_manuelle(conn, titre, "Camille [dit] Dupont")
    isbn = res["reference"]
    assert titre in run("show", isbn)
    assert titre in run("search", titre.split()[-1].strip("[]/"), "-n", "50")
    assert titre in run("sql", f"select titre from notices where id = {res['notice_id']}")
    services.creer_lieu(conn, titre)
    assert titre in run("place", "list")
    run("note", isbn, "--set", "note")
    assert titre in run("note", isbn)
    services.preter(conn, isbn, "Marie")
    assert titre in run("loans")


def test_scan_et_inventaire_interactifs(conn):
    sortie = run("scan", "-p", "Salon", "--mode", "where", input=f"{CHANSON}\n:mode nope\n:mode move\n{CHANSON}\n:q\n")
    assert "Salon" in sortie
    sortie = run("inventory", "Salon", input=f"{CHANSON}\n9782070360024\n:done\nn\n")
    assert "Present: 1" in sortie and "Missing: 2" in sortie


def test_share_protege_les_autres_fichiers(conn, tmp_path):
    base = db.db_path()
    run("share", "-o", base, code=1)
    assert services.lieux(conn)
    autre = tmp_path / "pas-un-partage.txt"
    autre.write_text("important")
    run("share", "-o", autre, code=1)
    assert autre.read_text() == "important"


def test_share_confirme_avant_de_remplacer_un_partage(conn, tmp_path):
    fichier = tmp_path / "pour-victor.db"
    run("share", "-o", fichier)
    avant = fichier.stat().st_mtime_ns
    r = runner.invoke(app, ["share", "-o", str(fichier)], input="n\n")
    assert r.exit_code != 0 and fichier.stat().st_mtime_ns == avant
    run("share", "-o", fichier, "--force")


def test_merge_de_bout_en_bout(conn, tmp_path):
    fichier = tmp_path / "victor.db"
    victor = db.connect(fichier)
    db.set_meta(victor, "proprietaire", "Moi")
    services.ajouter(victor, "9782253140870")
    charger(victor, "9782253140870", bnf="bnf_pur_sang.xml")
    victor.close()
    assert "Dry run" in run("merge", fichier, "--as", "Victor", "--dry-run")
    assert not services.exemplaires_de(conn, "9782253140870")
    assert "merged" in run("merge", fichier, "--as", "Victor", "--yes")
    assert services.exemplaires_de(conn, "9782253140870")[0]["proprietaire"] == "Victor"
    assert partage.resume_source(fichier)["exemplaires"] == 1


def test_resolve_retry_garde_les_reponses_valides(conn, monkeypatch):
    from biblio import covers, resolver

    monkeypatch.setattr(covers, "telecharger", lambda *a, **kw: False)
    vargas = db.id_notice(conn, VARGAS)
    conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                 "VALUES (?, 'google', 'erreur', 'HTTP 500', '2026-01-01')", (vargas,))
    conn.commit()
    appels = []
    monkeypatch.setattr(resolver, "fetch_sources", lambda c, cl, i, refresh=False: appels.append((i, refresh)) or [])
    run("resolve", "--retry")
    assert appels == [(vargas, False)]
    assert services.notice(conn, VARGAS)["titre"]


def test_backup(conn, tmp_path):
    run("backup", "--dir", tmp_path / "s", "--keep", "2")
    assert len(list((tmp_path / "s").glob("*.db"))) == 1


def test_copie_automatique_au_lancement_du_serveur(conn, monkeypatch):
    from biblio import cli, sauvegarde

    cli._automatic_backup()
    assert len(list(sauvegarde.dossier_defaut(conn).glob("*.db"))) == 1
    def plein(_):
        raise OSError("disque plein")
    monkeypatch.setattr(sauvegarde, "automatique", plein)
    cli._automatic_backup()                                            # n'empêche pas l'appli de s'ouvrir


def test_covers_missing_ne_retente_que_les_absentes(conn, monkeypatch):
    from biblio import covers

    covers.DOSSIER.mkdir(parents=True, exist_ok=True)
    covers.absente(CHANSON).touch()
    covers.chemin(ASTERIX).write_bytes(b"image")
    vus = []
    monkeypatch.setattr(covers, "telecharger", lambda cl, isbn, urls, forcer=False: vus.append((isbn, forcer)) or False)
    run("covers", "--missing")
    assert vus == [(CHANSON, True)]


def test_lecture_et_exemplaire_en_ligne_de_commande(conn):
    sortie = run("read", CHANSON, "--status", "read", "--rating", "4", "--finished", "2026-02-03")
    assert "finished 2026-02-03" in sortie and "★★★★" in sortie
    assert CHANSON in run("search", "--reading", "read")
    run("read", CHANSON, "--status", "maybe", code=1)
    run("read", CHANSON, "--rating", "9", code=1)
    run("read", CHANSON, "--status", "", "--rating", "0")
    assert services.notice(conn, CHANSON)["lecture"] is None and services.notice(conn, CHANSON)["etoiles"] is None
    ex = services.exemplaires_de(conn, CHANSON)[0]["id"]
    sortie = run("copy", ex, "--condition", "good", "--price", "12,5", "--from", "Gibert", "--bought", "2024-01-02")
    assert "good" in sortie and "12.5" in sortie and "Gibert" in sortie
    assert "Gibert" in run("show", CHANSON)
    run("copy", ex, "--condition", "wet", code=1)
    run("copy", 999, code=1)
    assert "Value" in run("stats") or "paid" in run("stats")


def test_reference_d_un_livre_sans_isbn(conn):
    ref = services.creer_notice_manuelle(conn, "Carnet", "Camille Dupont", lieu_id=services.emplacement(conn, "Salon")[0])["reference"]
    assert "Carnet" in run("show", ref) and ref in run("search", "carnet")
    assert "Salon" in run("where", ref)
    run("lend", ref, "Marie")
    run("return", ref)


def test_sync_entre_mes_bases(conn, tmp_path):
    """Une copie de ma base sur un autre ordinateur est reconnue d'emblée."""
    autre = tmp_path / "portable.db"
    copie = db.sqlite3.connect(autre)
    conn.backup(copie)
    copie.close()
    p = db.connect(autre)
    services.ajouter(p, "9782253140870", services.emplacement(p, "Salon")[0])
    p.close()
    assert "Dry run" in run("sync", autre, "--dry-run")
    assert "synced" in run("sync", autre, "--yes")
    assert services.exemplaires_de(conn, "9782253140870")
    assert "Already up to date" in run("sync", autre, "--yes")


def test_sync_confirme_une_base_inconnue_et_refuse_un_partage(conn, tmp_path):
    fichier = tmp_path / "autre.db"
    autre = db.connect(fichier)
    services.renommer_proprietaire_local(autre, "Portable")
    services.ajouter(autre, "9782253140870")
    autre.close()
    assert runner.invoke(app, ["sync", str(fichier)], input="n\n").exit_code != 0
    assert not services.exemplaires_de(conn, "9782253140870")
    run("sync", fichier, "--yes")
    assert services.exemplaires_de(conn, "9782253140870")[0]["a_moi"]
    partage_ = tmp_path / "partage.db"
    run("share", "-o", partage_)
    assert "biblio merge" in run("sync", partage_, "--yes", code=1)
    # Et l'inverse : ma propre base n'est pas le catalogue d'un ami
    assert "biblio sync" in run("merge", fichier, "--yes", code=1)


def test_base_d_une_autre_version_refusee_et_intacte(tmp_path, monkeypatch):
    chemin = tmp_path / "autre.db"
    autre = db.sqlite3.connect(chemin)
    autre.executescript("CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT); INSERT INTO meta VALUES ('schema_version', '3');")
    autre.close()
    avant = chemin.read_bytes()
    monkeypatch.setenv("BIBLIO_DB", str(chemin))
    assert "another version" in run("stats", code=1)
    assert chemin.read_bytes() == avant


def test_export_par_defaut_a_cote_de_la_base(conn, tmp_path, monkeypatch):
    """Sur un serveur, le dossier du code est en lecture seule : l'export va à côté de la base."""
    monkeypatch.setenv("BIBLIO_DB", str(tmp_path / "ailleurs" / "biblio.db"))
    sortie = run("export", "-f", "csv")
    assert list((tmp_path / "ailleurs" / "exports").glob("library-*.csv")), sortie


def test_ports_du_telephone_reglables(conn, monkeypatch):
    """Sur un Raspberry Pi, un autre service peut occuper 8080 et 8443 : les ports du mode téléphone se choisissent."""
    from biblio import certs, cli, telephone

    lances = []
    monkeypatch.setattr(telephone, "PORT_HTTPS", 8443)
    monkeypatch.setattr(telephone, "PORT_INSTALLATION", 8080)
    monkeypatch.setattr(telephone, "etat", dict(telephone.etat))
    monkeypatch.setattr(cli, "_port_free", lambda h, p: True)
    monkeypatch.setattr(cli, "_automatic_backup", lambda: None)
    monkeypatch.setattr(certs, "serveur", lambda noms, ips: ("c.pem", "k.pem"))
    monkeypatch.setattr(cli, "_serve_together", lambda serveurs: lances.extend(s.config.port for s in serveurs))
    run("serve", "--phone", "--no-open", "--phone-port", "8444", "--install-port", "8081")
    assert lances == [8000, 8444, 8081]
    assert telephone.urls(conn)["scan_court"].endswith(":8444/scan")
    run("serve", "--phone", "--no-open", "--phone-port", "8000", code=1)      # deux fois le même port


def test_phone_admin(conn):
    from biblio import telephone

    sortie = run("phone", "--admin")
    cle = telephone.cle_admin(conn)
    assert f"cle={cle}" in sortie.replace("\n", "")
    run("phone", "--admin", "--new-key")
    assert telephone.cle_admin(conn) != cle


def test_duplicates_liste_puis_retire_apres_copie(conn):
    premier = services.exemplaires_de(conn, CHANSON)[0]["id"]
    salon = services.exemplaires_de(conn, CHANSON)[0]["lieu_id"]
    services.ajouter(conn, CHANSON, salon, filtrer_rebond=False)
    services.ajouter(conn, ASTERIX, None, filtrer_rebond=False)

    sortie = run("duplicates")
    assert "Extra copies on the same shelf: 1" in sortie and "--remove" in sortie and "Chanson douce" in sortie
    assert len(services.exemplaires_de(conn, CHANSON)) == 2              # la liste ne touche à rien

    run("duplicates", "--remove", input="n\n", code=1)
    assert len(services.exemplaires_de(conn, CHANSON)) == 2

    assert "1 extra copies removed" in run("duplicates", "--remove", "--yes")
    assert [e["id"] for e in services.exemplaires_de(conn, CHANSON)] == [premier]
    assert len(services.exemplaires_de(conn, ASTERIX)) == 2              # l'autre n'est pas au même endroit
    assert list((db.chemin_base(conn).parent / "sauvegardes").glob("*.db"))
    assert "Extra copies on the same shelf: 0" in run("duplicates")


def test_duplicates_crochets_affiches_tels_quels(conn):
    lieu = services.creer_lieu(conn, "[VILLE] - Salon")
    for _ in range(2):
        services.ajouter(conn, CHANSON, lieu, filtrer_rebond=False)
    assert "[VILLE] - Salon" in run("duplicates")
