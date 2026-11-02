import sqlite3

import pytest

from biblio import db, partage, services
from biblio.services import Erreur

from .conftest import charger

CHANSON = "9782070196678"
ASTERIX = "9782014001143"
VARGAS = "9782290382608"


@pytest.fixture
def jd(tmp_path):
    """Ma bibliothèque : deux livres au Salon, un prêt, une note, des clés à ne pas divulguer."""
    c = db.connect(tmp_path / "jd.db")
    services.renommer_proprietaire_local(c, "JD")
    db.set_meta(c, "google_api_key", "AIza-secret")
    db.set_meta(c, "cle_telephone", "cle-secrete")
    salon = services.creer_lieu(c, "Salon")
    e1 = services.creer_etagere(c, salon, "É1")
    for isbn, fichier in ((CHANSON, "bnf_chanson_douce.xml"), (ASTERIX, "bnf_asterix.xml")):
        services.ajouter(c, isbn, salon, e1)
        charger(c, isbn, bnf=fichier)
    services.modifier_notice(c, CHANSON, {"notes": "**Lu en 2024**, offert par Marie", "lecture": "lu", "etoiles": 5})
    ex = services.exemplaires_de(c, CHANSON)[0]["id"]
    services.modifier_exemplaire(c, ex, {"etat": "bon", "prix_achat": 12, "provenance": "Gibert", "dedicace": "Pour JD", "valeur": 40})
    services.preter(c, CHANSON, "Marie")
    services.creer_notice_manuelle(c, "Carnet de voyage", "Camille Dupont", lieu_id=salon)
    yield c
    c.close()


@pytest.fixture
def victor(tmp_path):
    c = db.connect(tmp_path / "victor.db")
    services.renommer_proprietaire_local(c, "Moi")          # Victor n'a pas réglé son nom
    services.ajouter(c, VARGAS)
    charger(c, VARGAS, bnf="bnf_vargas.xml")
    yield c
    c.close()


def test_partage_masque_lieux_et_donnees_personnelles(jd, tmp_path):
    fichier = tmp_path / "pour-victor.db"
    res = partage.exporter_partage(jd, fichier, masquer_lieux=True)
    assert res == {"exemplaires": 3, "notices": 3, "proprietaire": "JD", "prets": 0}
    f = sqlite3.connect(fichier)
    meta = dict(f.execute("SELECT cle, valeur FROM meta"))
    assert "google_api_key" not in meta and "cle_telephone" not in meta
    assert f.execute("SELECT nom FROM personnes WHERE uid = ?", (meta["moi_uid"],)).fetchone()[0] == "JD"
    assert f.execute("SELECT count(*) FROM personnes").fetchone()[0] == 1       # aucun emprunteur
    assert f.execute("SELECT count(*) FROM prets").fetchone()[0] == 0
    assert f.execute("SELECT count(*) FROM lieux").fetchone()[0] == 0
    assert f.execute("SELECT count(*) FROM notices WHERE notes IS NOT NULL OR lecture IS NOT NULL").fetchone()[0] == 0
    assert "notes" not in " ".join(r[0] for r in f.execute("SELECT corrections FROM notices"))
    assert f.execute("SELECT count(*) FROM exemplaires WHERE etat IS NOT NULL OR prix_achat IS NOT NULL OR "
                     "provenance IS NOT NULL OR dedicace IS NOT NULL OR valeur IS NOT NULL").fetchone()[0] == 0
    assert {r[0] for r in f.execute("SELECT lieu_texte FROM exemplaires")} == {None}
    assert f.execute("SELECT count(*) FROM raw_responses").fetchone()[0] == 2   # l'ami peut tout reclasser
    f.close()

    partage.exporter_partage(jd, fichier)                    # lieux visibles, en texte
    f = sqlite3.connect(fichier)
    assert {r[0] for r in f.execute("SELECT lieu_texte FROM exemplaires")} == {"Salon › É1", "Salon"}
    f.close()


def test_fusion_chez_un_ami_idempotente(jd, victor, tmp_path):
    fichier = tmp_path / "jd.db.partage"
    partage.exporter_partage(jd, fichier)
    r = partage.importer_ami(victor, fichier)
    assert r["source"] == "JD" and r["notices_ajoutees"] == 3 and r["exemplaires_ajoutes"] == 3
    again = partage.importer_ami(victor, fichier)
    assert not again.get("exemplaires_ajoutes") and not again.get("notices_ajoutees")
    assert services.proprietaires(victor) == [dict(nom="Moi", nb=1, local=True), dict(nom="JD", nb=3, local=False)]

    # Chez Victor : ses livres par défaut, ceux de JD sur demande, avec leur lieu en texte
    mes, _ = services.rechercher(victor)
    assert [r["isbn13"] for r in mes] == [VARGAS]
    chez_jd, total = services.rechercher(victor, "chanson", proprietaire="JD")
    assert total == 1 and chez_jd[0]["emplacement"] == "Salon › É1" and not chez_jd[0]["a_moi"]
    assert services.localiser(victor, CHANSON)["message"] == "chez JD — Salon › É1"
    assert victor.execute("SELECT notes, lecture FROM notices WHERE isbn13 = ?", (CHANSON,)).fetchone()[0:2] == (None, None)
    # Les livres de JD ne comptent pas dans les statistiques de Victor, ni dans ses lieux
    assert services.stats(victor)["exemplaires"] == 1
    assert victor.execute("SELECT count(*) FROM lieux").fetchone()[0] == 0
    # Le livre sans ISBN n'existe qu'une fois chez Victor, et garde son identité
    assert victor.execute("SELECT count(*) FROM notices WHERE titre = 'Carnet de voyage'").fetchone()[0] == 1


def test_fusion_renomme_et_remplace(jd, victor, tmp_path):
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    r = partage.importer_ami(jd, fichier, comme="Victor")
    assert r["source"] == "Victor" and r["exemplaires_ajoutes"] == 1
    assert services.rechercher(jd, proprietaire="Victor")[1] == 1

    # Victor donne son livre ; son nouveau fichier ne le contient plus
    ex = services.exemplaires_de(victor, VARGAS)[0]["id"]
    services.donner(victor, ex, "Claire")
    partage.exporter_partage(victor, fichier)
    sans = partage.importer_ami(jd, fichier, comme="Victor")
    assert not sans.get("exemplaires_retires")                      # sans --replace : rien n'est retiré
    avec = partage.importer_ami(jd, fichier, comme="Victor", remplacer=True)
    assert avec["exemplaires_retires"] == 1
    assert services.rechercher(jd, proprietaire="Victor")[1] == 0
    assert services.rechercher(jd, proprietaire="tous")[1] == 3    # mes livres sont intacts


def test_fusion_simulation_sans_effet(jd, victor, tmp_path):
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    avant = jd.execute("SELECT count(*) FROM exemplaires").fetchone()[0]
    r = partage.importer_ami(jd, fichier, comme="Victor", simulation=True)
    assert r["exemplaires_ajoutes"] == 1
    assert jd.execute("SELECT count(*) FROM exemplaires").fetchone()[0] == avant


def test_corrections_manuelles(jd, victor, tmp_path):
    fichier = tmp_path / "jd.db.partage"
    partage.exporter_partage(jd, fichier)
    partage.importer_ami(victor, fichier)
    # JD corrige le titre et fixe une cote ; Victor a déjà corrigé l'éditeur à sa façon
    services.modifier_notice(jd, ASTERIX, {"titre": "Astérix le Gaulois (éd. 1961)", "editeur": "Dargaud"})
    services.fixer_classification(jd, ASTERIX, "dewey", "741.5944")
    services.modifier_notice(victor, ASTERIX, {"editeur": "Hachette"})
    partage.exporter_partage(jd, fichier)
    r = partage.importer_ami(victor, fichier)
    assert r["notices_completees"] >= 1
    n = services.notice(victor, ASTERIX)
    assert n["titre"] == "Astérix le Gaulois (éd. 1961)" and n["editeur"] == "Hachette"
    dewey = next(c for c in n["classifications"] if c["systeme"] == "dewey")
    assert dewey["code"] == "741.5944" and dewey["origine"] == "manuel"


def _nom_de_victor(victor):
    services.renommer_proprietaire_local(victor, "Victor")


def test_prets_d_un_ami_seulement_sur_son_accord(jd, victor, tmp_path):
    services.preter(victor, VARGAS, "Marie")
    _nom_de_victor(victor)
    victor_uid = "Victor"
    # Sa base complète, ou un fichier sans l'option : aucun prêt repris
    partage.importer_ami(jd, tmp_path / "victor.db")
    fichier = tmp_path / "de-victor.db"
    res = partage.exporter_partage(victor, fichier)
    assert res["prets"] == 0
    partage.importer_ami(jd, fichier)
    assert jd.execute("SELECT count(*) FROM prets_v WHERE preteur = ?", (victor_uid,)).fetchone()[0] == 0

    # Avec l'option : repris une seule fois, sans se mêler aux miens
    res = partage.exporter_partage(victor, fichier, avec_prets=True)
    assert res["prets"] == 1
    assert partage.importer_ami(jd, fichier)["prets_ajoutes"] == 1
    assert not partage.importer_ami(jd, fichier).get("prets_ajoutes")
    assert [p["emprunteur"] for p in services.prets(jd)] == ["Marie"] and services.prets(jd)[0]["preteur"] == "JD"
    assert services.nb_prets(jd) == 1 and services.stats(jd)["prets_total"] == 1
    assert services.exemplaires_de(jd, VARGAS)[0]["pret"]["emprunteur"] == "Marie"       # son livre est sorti
    ex = services.exemplaires_de(jd, VARGAS)[0]["id"]
    with pytest.raises(Erreur):
        services.rendre(jd, ex)                                       # ce n'est pas à moi de le clore

    # Réseau : JD et Victor ne sont pas liés, mais chacun l'est à Marie, qui n'est qu'une seule personne
    s = services.stats(jd)
    assert {(a["de"], a["vers"], a["nb"]) for a in s["reseau_aretes"]} == {("jd", "marie", 1), ("marie", "victor", 1)}
    assert jd.execute("SELECT count(*) FROM personnes WHERE cle = 'marie'").fetchone()[0] == 1

    # Victor rend le livre, puis ne partage plus ses prêts
    services.rendre(victor, VARGAS)
    partage.exporter_partage(victor, fichier, avec_prets=True)
    partage.importer_ami(jd, fichier)
    assert services.exemplaires_de(jd, VARGAS)[0]["pret"] is None
    partage.exporter_partage(victor, fichier)
    assert not partage.importer_ami(jd, fichier).get("prets_retires")  # sans --replace : rien n'est retiré
    assert partage.importer_ami(jd, fichier, remplacer=True)["prets_retires"] == 1
    assert jd.execute("SELECT count(*) FROM prets_v WHERE preteur = 'Victor'").fetchone()[0] == 0


def test_prets_du_nom_donne_par_as_et_lien_entre_nous(jd, victor, tmp_path):
    services.preter(victor, VARGAS, "jd")                               # Victor m'a prêté un livre
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier, avec_prets=True)
    partage.importer_ami(jd, fichier, comme="Victor")                   # son fichier dit « Moi »
    pret = jd.execute("SELECT preteur, emprunteur FROM prets_v WHERE preteur = 'Victor'").fetchone()
    assert tuple(pret) == ("Victor", "JD")                              # « jd » chez lui, c'est moi
    services.ajouter(jd, VARGAS)
    services.preter(jd, jd.execute("SELECT max(id) FROM exemplaires").fetchone()[0], "victor")
    aretes = services.stats(jd)["reseau_aretes"]                      # un seul lien, dans les deux sens
    assert {"de": "jd", "vers": "victor", "nb": 2, "en_cours": 2, "nom": "JD — Victor"} in aretes


# --- L'identité d'un ami ------------------------------------------------------------

def test_ami_reconnu_meme_s_il_change_de_nom(jd, victor, tmp_path):
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    partage.importer_ami(jd, fichier, comme="Victor")
    services.renommer_proprietaire_local(victor, "Victor Durand")
    partage.exporter_partage(victor, fichier)
    r = partage.importer_ami(jd, fichier)                             # plus besoin de --as
    assert r["source"] == "Victor" and not r.get("exemplaires_ajoutes")
    assert [p["nom"] for p in services.proprietaires(jd)] == ["JD", "Victor"]
    assert partage.importer_ami(jd, fichier, comme="Paulo")["source"] == "Paulo"     # c'est moi qui le nomme ici
    assert [p["nom"] for p in services.proprietaires(jd)] == ["JD", "Paulo"]


def test_deux_bases_au_meme_nom_ne_se_confondent_pas(tmp_path):
    a = db.connect(tmp_path / "a.db")
    b = db.connect(tmp_path / "b.db")                                 # chacun s'appelle « Moi »
    services.ajouter(b, VARGAS)
    charger(b, VARGAS, bnf="bnf_vargas.xml")
    partage.exporter_partage(b, tmp_path / "de-b.db")
    with pytest.raises(Erreur):
        partage.importer_ami(a, tmp_path / "de-b.db")                 # il faut dire qui c'est
    assert not services.exemplaires_de(a, VARGAS)
    assert partage.importer_ami(a, tmp_path / "de-b.db", comme="Victor")["exemplaires_ajoutes"] == 1
    assert not services.exemplaires_de(a, VARGAS)[0]["a_moi"]
    a.close()
    b.close()


def test_ami_a_qui_j_avais_donne_un_livre(jd, victor, tmp_path):
    ex = services.exemplaires_de(jd, ASTERIX)[0]["id"]
    services.donner(jd, ex, "Victor")                                   # « Victor » n'est encore qu'un nom chez moi
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    partage.importer_ami(jd, fichier, comme="victor")
    assert [p["nom"] for p in services.proprietaires(jd)] == ["JD", "Victor"]
    assert services.rechercher(jd, proprietaire="Victor")[1] == 2


def test_import_refuse_ma_propre_base(jd, tmp_path):
    copie = tmp_path / "copie.db"
    c = sqlite3.connect(copie)
    jd.backup(c)
    c.close()
    with pytest.raises(Erreur):
        partage.importer_ami(jd, copie)


def test_fichier_d_un_ami_ne_touche_pas_a_mes_livres(jd, victor, tmp_path):
    """Il m'a donné son livre, mais sa base dit encore qu'il l'a, avec une date plus récente."""
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    partage.importer_ami(jd, fichier, comme="Victor")
    ex = services.exemplaires_de(jd, VARGAS)[0]["id"]
    services.donner(jd, ex, "JD")
    autre = services.exemplaires_de(victor, VARGAS)[0]["id"]
    services.modifier_exemplaire(victor, autre, {"notes": "encore chez moi"})
    partage.exporter_partage(victor, fichier)
    partage.importer_ami(jd, fichier)
    assert services.exemplaires_de(jd, VARGAS)[0]["a_moi"]


# --- Livres sans ISBN d'une base à l'autre -------------------------------------------

def test_livre_sans_isbn_garde_son_identite(jd, victor, tmp_path):
    fichier = tmp_path / "jd.db.partage"
    partage.exporter_partage(jd, fichier)
    partage.importer_ami(victor, fichier)
    uid = jd.execute("SELECT uid FROM notices WHERE titre = 'Carnet de voyage'").fetchone()[0]
    assert victor.execute("SELECT uid, isbn13 FROM notices WHERE titre = 'Carnet de voyage'").fetchone()[0:2] == (uid, None)
    services.modifier_notice(jd, uid and jd.execute("SELECT id FROM notices WHERE uid = ?", (uid,)).fetchone()[0],
                             {"titre": "Carnet de voyage (1952)"})
    partage.exporter_partage(jd, fichier)
    partage.importer_ami(victor, fichier)
    assert victor.execute("SELECT titre FROM notices WHERE uid = ?", (uid,)).fetchone()[0] == "Carnet de voyage (1952)"
    assert victor.execute("SELECT count(*) FROM notices WHERE isbn13 IS NULL").fetchone()[0] == 1


def test_meme_livre_sans_isbn_saisi_des_deux_cotes(jd, victor, tmp_path):
    services.creer_notice_manuelle(victor, "CARNET DE VOYAGE", "Camille Dupont")
    fichier = tmp_path / "jd.db.partage"
    partage.exporter_partage(jd, fichier)
    r = partage.importer_ami(victor, fichier)
    assert victor.execute("SELECT count(*) FROM notices WHERE isbn13 IS NULL").fetchone()[0] == 1 and r["notices_ajoutees"] == 2


# --- Tout ou rien ---------------------------------------------------------------------

def test_erreur_en_cours_d_import_ne_laisse_rien(jd, victor, tmp_path, monkeypatch):
    fichier = tmp_path / "de-victor.db"
    services.ajouter(victor, ASTERIX)
    charger(victor, ASTERIX, bnf="bnf_asterix.xml")
    partage.exporter_partage(victor, fichier)
    avant = jd.execute("SELECT count(*) FROM personnes").fetchone()[0]
    def panne(*a, **kw):
        raise RuntimeError("panne")
    monkeypatch.setattr(partage, "_importer_exemplaire", panne)
    with pytest.raises(RuntimeError):
        partage.importer_ami(jd, fichier, comme="Victor")
    assert jd.execute("SELECT count(*) FROM personnes").fetchone()[0] == avant
    assert not jd.execute("SELECT 1 FROM notices WHERE isbn13 = ?", (VARGAS,)).fetchone()


# --- Synchronisation entre mes ordinateurs -------------------------------------------

@pytest.fixture
def portable(jd, tmp_path):
    """Ma base, copiée sur un second ordinateur."""
    c = sqlite3.connect(tmp_path / "portable.db")
    jd.backup(c)
    c.close()
    p = db.connect(tmp_path / "portable.db")
    yield p
    p.close()


def sync(jd, portable):
    """Dans les deux sens, comme le demande la documentation."""
    a = partage.synchroniser(jd, db.chemin_base(portable))
    b = partage.synchroniser(portable, db.chemin_base(jd))
    return a, b


def test_synchro_livres_lieux_prets(jd, portable):
    bureau = services.creer_lieu(portable, "Bureau")
    services.ajouter(portable, VARGAS, bureau)
    charger(portable, VARGAS, bnf="bnf_vargas.xml")
    services.deplacer_exemplaire(portable, services.exemplaires_de(portable, ASTERIX)[0]["id"], bureau, None)
    services.rendre(portable, CHANSON)
    a, _ = sync(jd, portable)
    assert a["exemplaires_ajoutes"] == 1 and a["exemplaires_mis_a_jour"] >= 2
    assert services.localiser(jd, VARGAS)["message"] == "Bureau"           # le lieu a suivi
    assert services.localiser(jd, ASTERIX)["message"] == "Bureau"          # le plus récent l'emporte
    assert services.prets(jd) == []                                        # le retour est reporté
    assert services.notice(jd, CHANSON)["notes"]
    assert jd.execute("SELECT count(*) FROM mouvements").fetchone()[0] == 1    # l'historique aussi
    again, _ = sync(jd, portable)
    assert set(again) == {"source"}                                        # plus rien à faire


def test_synchro_propage_les_retraits(jd, portable):
    ex = services.exemplaires_de(portable, ASTERIX)[0]["id"]
    services.annuler_exemplaire(portable, ex)
    a, _ = sync(jd, portable)
    assert a["exemplaires_retires"] == 1
    assert not services.notice(jd, ASTERIX) and not services.notice(portable, ASTERIX)    # il ne revient pas


def test_synchro_retrait_contre_modification_plus_recente(jd, portable):
    ex = services.exemplaires_de(portable, ASTERIX)[0]
    services.annuler_exemplaire(portable, ex["id"])
    services.modifier_exemplaire(jd, services.exemplaires_de(jd, ASTERIX)[0]["id"], {"notes": "je l'ai encore"})
    sync(jd, portable)
    assert services.exemplaires_de(jd, ASTERIX) and services.exemplaires_de(portable, ASTERIX)   # la modification gagne


def test_synchro_notes_et_corrections_la_plus_recente_gagne(jd, portable):
    services.modifier_notice(jd, CHANSON, {"notes": "v1", "titre": "T1", "lecture": "a_lire"})
    sync(jd, portable)
    services.modifier_notice(portable, CHANSON, {"notes": "v2", "titre": "T2", "lecture": "lu", "etoiles": 4})
    sync(jd, portable)
    for base in (jd, portable):
        n = services.notice(base, CHANSON)
        assert (n["notes"], n["titre"], n["lecture"], n["etoiles"]) == ("v2", "T2", "lu", 4)
    # Champ par champ : chacun garde ce qu'il a changé en dernier
    services.modifier_notice(jd, CHANSON, {"annee": 1999})
    services.modifier_notice(portable, CHANSON, {"pages": 111})
    sync(jd, portable)
    for base in (jd, portable):
        n = services.notice(base, CHANSON)
        assert (n["annee"], n["pages"]) == (1999, 111)


def test_synchro_rendre_un_champ_aux_catalogues(jd, portable):
    services.modifier_notice(jd, ASTERIX, {"titre": "Mon titre"})
    sync(jd, portable)
    services.liberer_champ(portable, ASTERIX, "titre")
    sync(jd, portable)
    assert services.notice(jd, ASTERIX)["titre"] != "Mon titre" and "titre" not in services.notice(jd, ASTERIX)["champs_manuels"]


def test_synchro_cotes_manuelles(jd, portable):
    services.fixer_classification(jd, ASTERIX, "dewey", "741.5944")
    sync(jd, portable)
    cote = lambda b: next(c for c in services.notice(b, ASTERIX)["classifications"] if c["systeme"] == "dewey")
    assert cote(portable)["code"] == "741.5944"
    services.fixer_classification(portable, ASTERIX, "dewey", None)        # retour à l'automatique
    sync(jd, portable)
    assert cote(jd)["origine"] != "manuel"


def test_synchro_lieu_renomme_et_supprime(jd, portable):
    salon = services.emplacement(portable, "Salon")[0]
    services.renommer_lieu(portable, salon, "Séjour")
    a, _ = sync(jd, portable)
    assert a["lieux_mis_a_jour"] == 1
    assert sorted(l["nom"] for l in services.lieux(jd)) == ["Séjour"]      # pas de « Salon » fantôme
    assert services.localiser(jd, CHANSON)["message"].startswith("Séjour")
    services.supprimer_lieu(jd, services.emplacement(jd, "Séjour")[0])
    sync(jd, portable)
    assert services.lieux(portable) == []
    assert services.localiser(portable, CHANSON)["message"].startswith("Non localisé")
    sync(jd, portable)
    assert services.lieux(jd) == [] and services.lieux(portable) == []     # il ne revient pas


def test_synchro_details_d_exemplaire_et_mon_nom(jd, portable):
    ex = services.exemplaires_de(portable, CHANSON)[0]["id"]
    services.modifier_exemplaire(portable, ex, {"prix_achat": 7, "provenance": "Brocante"})
    services.renommer_proprietaire_local(portable, "Alex")
    sync(jd, portable)
    assert services.exemplaires_de(jd, CHANSON)[0]["provenance"] == "Brocante"
    assert services.proprietaire_local(jd) == "Alex" and services.exemplaires_de(jd, CHANSON)[0]["a_moi"]


def test_synchro_catalogue_d_ami_sur_les_deux_machines(jd, portable, victor, tmp_path):
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    partage.importer_ami(jd, fichier, comme="Victor")
    sync(jd, portable)
    assert services.rechercher(portable, proprietaire="Victor")[1] == 1
    assert services.exemplaires_de(portable, VARGAS)[0]["emplacement"] == "chez Victor"


def test_premiere_synchro_a_confirmer(tmp_path):
    a = db.connect(tmp_path / "a.db")
    b = db.connect(tmp_path / "b.db")
    for base, nom in ((a, "JD"), (b, "Alex")):
        services.renommer_proprietaire_local(base, nom)
    salon_a = services.creer_lieu(a, "Salon")
    salon_b = services.creer_lieu(b, "salon")                         # le même lieu, créé des deux côtés
    services.ajouter(a, CHANSON, salon_a)
    services.ajouter(b, ASTERIX, salon_b)
    with pytest.raises(partage.PremiereSynchro):
        partage.synchroniser(a, tmp_path / "b.db")
    assert not services.exemplaires_de(a, ASTERIX)
    assert partage.synchroniser(a, tmp_path / "b.db", appairer=True, simulation=True)["exemplaires_ajoutes"] == 1
    assert not services.exemplaires_de(a, ASTERIX)                    # simulation : rien n'est gardé
    partage.synchroniser(a, tmp_path / "b.db", appairer=True)
    assert services.exemplaires_de(a, ASTERIX)[0]["a_moi"]
    assert [l["nom"] for l in services.lieux(a)] == ["Salon"]         # un seul lieu
    # Ensuite, elle est reconnue, et ses livres sont les miens
    assert partage.est_ma_base(a, tmp_path / "b.db")
    partage.synchroniser(a, tmp_path / "b.db")
    partage.synchroniser(b, tmp_path / "a.db", appairer=True)
    assert services.exemplaires_de(b, CHANSON)[0]["a_moi"]
    assert a.execute("SELECT uid FROM lieux").fetchone()[0] == b.execute("SELECT uid FROM lieux").fetchone()[0]
    a.close()
    b.close()


def test_synchro_refuse_un_fichier_de_partage(jd, victor, tmp_path):
    fichier = tmp_path / "de-victor.db"
    partage.exporter_partage(victor, fichier)
    with pytest.raises(Erreur):
        partage.synchroniser(jd, fichier, appairer=True)


def test_erreur_en_cours_de_synchro_ne_laisse_rien(jd, portable, tmp_path, monkeypatch):
    services.ajouter(portable, VARGAS)
    services.creer_lieu(portable, "Bureau")
    monkeypatch.setattr(partage, "_reprendre_pret", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("panne")))
    with pytest.raises(RuntimeError):
        partage.synchroniser(jd, tmp_path / "portable.db")
    assert not services.exemplaires_de(jd, VARGAS) and len(services.lieux(jd)) == 1


def test_fichier_refuse(jd, tmp_path):
    autre = tmp_path / "texte.db"
    autre.write_text("pas une base")
    with pytest.raises(Erreur):
        partage.importer_ami(jd, autre)
    with pytest.raises(Erreur):
        partage.importer_ami(jd, tmp_path / "absent.db")


def test_partage_refuse_d_ecraser_la_base_ouverte(jd, tmp_path):
    with pytest.raises(Erreur):
        partage.exporter_partage(jd, tmp_path / "jd.db")
    assert services.notice(jd, CHANSON)["notes"]                        # la base est intacte
    assert services.lieux(jd)


def test_partage_refuse_d_ecraser_un_autre_fichier(jd, victor, tmp_path):
    with pytest.raises(Erreur):                                          # la base d'un ami
        partage.exporter_partage(jd, tmp_path / "victor.db")
    assert services.notice(victor, VARGAS)
    autre = tmp_path / "rapport.txt"
    autre.write_text("important")
    with pytest.raises(Erreur):
        partage.exporter_partage(jd, autre)
    assert autre.read_text() == "important"


def test_partage_remplace_un_ancien_fichier_de_partage(jd, tmp_path):
    fichier = tmp_path / "pour-victor.db"
    partage.exporter_partage(jd, fichier)
    assert partage.exporter_partage(jd, fichier)["exemplaires"] == 3
