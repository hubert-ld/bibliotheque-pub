from datetime import datetime, timedelta

import pytest

from biblio import db, export, resolver, services
from biblio.services import Erreur

from .conftest import charger

CHANSON = "9782070196678"
ASTERIX = "9782014001143"
VARGAS = "9782290382608"


@pytest.fixture
def biblio(conn):
    salon = services.creer_lieu(conn, "Salon")
    e1 = services.creer_etagere(conn, salon, "É1")
    chambre = services.creer_lieu(conn, "Chambre")
    for isbn in (CHANSON, ASTERIX, VARGAS):
        services.ajouter(conn, isbn, salon, e1)
    charger(conn, CHANSON, bnf="bnf_chanson_douce.xml")
    charger(conn, ASTERIX, bnf="bnf_asterix.xml")
    charger(conn, VARGAS, bnf="bnf_vargas.xml")
    return {"salon": salon, "e1": e1, "chambre": chambre}


def test_ajout_rebond_et_doublon(conn, biblio):
    r = services.ajouter(conn, CHANSON, biblio["salon"], biblio["e1"])
    assert r["statut"] == "rebond"                       # relu dans la foulée : ignoré
    r = services.ajouter(conn, CHANSON, biblio["chambre"])
    assert r["statut"] == "doublon" and r["autres"] == ["Salon › É1"]
    assert len(services.exemplaires_de(conn, CHANSON)) == 2


def test_emplacement_texte(conn, biblio):
    assert services.emplacement(conn, "salon/é1") == (biblio["salon"], biblio["e1"])
    with pytest.raises(Erreur):
        services.emplacement(conn, "Grenier")
    lieu, etagere = services.emplacement(conn, "Grenier > Carton 1", creer=True)
    assert services.nom_emplacement(conn, lieu, etagere) == "Grenier › Carton 1"


def test_recherche_sans_accents_et_prefixe(conn, biblio):
    rows, total = services.rechercher(conn, "leila slim")
    assert total == 1 and rows[0]["isbn13"] == CHANSON
    rows, _ = services.rechercher(conn, "environnement")   # sujet Rameau
    assert rows[0]["isbn13"] == VARGAS
    rows, _ = services.rechercher(conn, "978-2-01-400114-3")
    assert rows[0]["isbn13"] == ASTERIX


def test_tri_par_cote(conn, biblio):
    rows, _ = services.rechercher(conn, systeme="dewey")
    assert [r["cote"] for r in rows] == ["363.7 VAR", "741.5 GOS", "843 SLI"]
    rows, _ = services.rechercher(conn, systeme="rayon")
    assert [r["cote"] for r in rows] == ["BD GOS", "ROMF SLI", "SOC VAR"]


def test_deplacement_et_historique(conn, biblio):
    r = services.deplacer(conn, ASTERIX, biblio["chambre"], None)
    assert r["statut"] == "deplace"
    assert services.localiser(conn, ASTERIX)["emplacements"] == ["Chambre"]
    assert conn.execute("SELECT count(*) FROM mouvements").fetchone()[0] == 1
    assert services.deplacer(conn, ASTERIX, biblio["chambre"], None)["statut"] == "deja_la"


def test_inventaire(conn, biblio):
    services.deplacer(conn, ASTERIX, biblio["chambre"], None)
    inv = services.demarrer_inventaire(conn, biblio["salon"], biblio["e1"])
    assert services.scanner_inventaire(conn, inv, CHANSON)["statut"] == "present"
    assert services.scanner_inventaire(conn, inv, ASTERIX)["statut"] == "ailleurs"
    assert services.scanner_inventaire(conn, inv, "9782253140870")["statut"] == "inconnu"
    r = services.rapport_inventaire(conn, inv)
    assert [n["isbn13"] for n in r["manquants"]] == [VARGAS]
    assert r["inconnus"] == ["9782253140870"]
    services.cloturer_inventaire(conn, inv, ranger_ailleurs=True)
    assert services.localiser(conn, ASTERIX)["emplacements"] == ["Salon › É1"]


def test_correction_manuelle_protegee(conn, biblio):
    from biblio.resolver import rebuild

    services.modifier_notice(conn, CHANSON, {"titre": "Chanson douce (édition perso)", "forme": "essai"})
    rebuild(conn, CHANSON)                                # relecture des catalogues
    n = services.notice(conn, CHANSON)
    assert n["titre"] == "Chanson douce (édition perso)"
    assert set(n["champs_manuels"]) == {"titre", "forme"}


def test_cote_manuelle(conn, biblio):
    services.fixer_classification(conn, CHANSON, "dewey", "843.92")
    c = {x["systeme"]: x for x in services.notice(conn, CHANSON)["classifications"]}
    assert c["dewey"]["cote"] == "843.92 SLI" and c["dewey"]["origine"] == "manuel"
    services.fixer_classification(conn, CHANSON, "dewey", None)
    c = {x["systeme"]: x for x in services.notice(conn, CHANSON)["classifications"]}
    assert c["dewey"]["code"] == "843" and c["dewey"]["origine"] == "deduit"


def test_prets(conn, biblio):
    services.preter(conn, CHANSON, "Marie")
    assert services.localiser(conn, CHANSON)["emplacements"] == ["Salon › É1 (prêté à Marie)"]
    with pytest.raises(Erreur):
        services.preter(conn, CHANSON, "Victor")
    assert services.rendre(conn, CHANSON)["emprunteur"] == "Marie"
    assert services.prets(conn) == []


def test_livre_sans_isbn(conn, biblio):
    r = services.creer_notice_manuelle(conn, "Mémoires de mon grand-père", "Camille Dupont",
                                       lieu_id=biblio["salon"], forme="fiction", langue="fre")
    assert services.notice(conn, r["notice_id"])["isbn13"] is None and r["reference"] == f"L{r['notice_id']}"
    rows, _ = services.rechercher(conn, "grand-pere")
    assert rows[0]["cote"] == "843 DUP"


def test_suppression_dernier_exemplaire(conn, biblio):
    ex = services.exemplaires_de(conn, VARGAS)[0]
    services.annuler_exemplaire(conn, ex["id"])
    assert services.notice(conn, VARGAS) is None
    assert services.rechercher(conn, "vargas")[1] == 0


def test_exports(conn, biblio):
    entetes, lignes = export.lignes(conn)
    assert "Cote Dewey" in entetes and len(lignes) == 3
    assert export.xlsx_bytes(conn)[:2] == b"PK"
    assert export.csv_bytes(conn).decode("utf-8-sig").startswith("ISBN;Titre")


def test_filtre_date_d_ajout(conn, biblio):
    conn.execute("UPDATE exemplaires SET ajoute_le = '2026-10-20T09:00:00' WHERE notice_id = ?", (db.id_notice(conn, VARGAS),))
    conn.execute("UPDATE exemplaires SET ajoute_le = '2026-10-31T23:59:59' WHERE notice_id = ?", (db.id_notice(conn, ASTERIX),))
    conn.execute("UPDATE exemplaires SET ajoute_le = '2026-10-25T12:00:00' WHERE notice_id = ?", (db.id_notice(conn, CHANSON),))
    conn.commit()
    _, total = services.rechercher(conn, ajout_du="2026-10-21")
    assert total == 2
    rows, _ = services.rechercher(conn, ajout_du="2026-10-31", ajout_au="2026-10-31")   # jour de fin inclus
    assert [r["isbn13"] for r in rows] == [ASTERIX]
    with pytest.raises(Erreur):
        services.rechercher(conn, ajout_du="31/10/2026")


def test_operations_groupees(conn, biblio):
    services.deplacer(conn, CHANSON, None, None)                  # oublié : non localisé
    services.deplacer(conn, ASTERIX, None, None)
    ids = services.ids_exemplaires(conn, lieu_id="aucun")
    assert len(ids) == 2
    assert services.deplacer_lot(conn, ids, biblio["chambre"], None) == 2
    assert services.deplacer_lot(conn, ids, biblio["chambre"], None) == 0    # déjà rangés
    assert services.localiser(conn, CHANSON)["emplacements"] == ["Chambre"]
    assert services.retirer_lot(conn, ids) == 2
    assert services.rechercher(conn)[1] == 1


def test_stats_pour_les_graphiques(conn, biblio):
    s = services.stats(conn)
    assert sum(s["activite"].values()) == 3                       # les 3 ajouts du jour
    assert {r["nom"] for r in s["par_langue"]} == {"Français"}
    assert {r["nom"] for r in s["par_forme"]} >= {"Roman, récit", "Documentaire"}
    assert [r["nom"] for r in s["par_decennie"]] == [2010, 2020]
    assert s["par_lieu"] == [{"nom": "Salon", "nb": 3}]


def test_stats_prets(conn, biblio):
    s = services.stats(conn)
    assert s["prets"] == 0 and s["prets_en_cours"] == [] and s["prets_duree_moyenne"] is None
    assert len(s["prets_par_mois"]) == 12 and sum(m["nb"] for m in s["prets_par_mois"]) == 0

    services.preter(conn, CHANSON, "Marie")
    services.preter(conn, ASTERIX, "Marie")
    services.preter(conn, VARGAS, "Victor")
    services.rendre(conn, VARGAS)
    il_y_a = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")   # sorti depuis un mois
    conn.execute("UPDATE prets SET date_pret = ? WHERE exemplaire_id = "
                 "(SELECT id FROM exemplaires WHERE notice_id = ?)", (il_y_a, db.id_notice(conn, ASTERIX)))
    conn.execute("UPDATE prets SET date_pret = ?, date_retour = ? WHERE emprunteur_id = ?",
                 (il_y_a, (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds"), services.personne_id(conn, "Victor")))
    conn.commit()
    s = services.stats(conn)
    assert s["prets_total"] == 3 and s["prets_duree_moyenne"] == 10
    assert [(p["qui"], p["nb"]) for p in s["prets_en_cours"]] == [("Marie", 30), ("Marie", 0)]   # plus ancien d'abord
    assert s["prets_en_cours"][0]["url"] == f"/livre/{db.id_notice(conn, ASTERIX)}"
    assert s["prets_par_emprunteur"] == [{"nom": "Marie", "nb": 2}]
    assert s["emprunteurs"] == [{"nom": "Marie", "nb": 2}, {"nom": "Victor", "nb": 1}]
    assert sum(m["nb"] for m in s["prets_par_mois"]) == 3
    assert s["prets_par_mois"][-1]["mois"] == datetime.now().strftime("%Y-%m")     # du plus ancien au mois en cours
    assert len(s["plus_pretes"]) == 3 and all(r["nb"] == 1 for r in s["plus_pretes"])


def test_reseau_des_prets(conn, biblio):
    services.renommer_proprietaire_local(conn, "JD")
    s = services.stats(conn)
    assert s["reseau_aretes"] == [] and [n["nom"] for n in s["reseau_noeuds"]] == ["JD"]

    services.ajouter(conn, ASTERIX, proprietaire="Victor")               # Victor a une bibliothèque, connue
    services.preter(conn, CHANSON, "Marie")
    services.rendre(conn, CHANSON)
    services.preter(conn, CHANSON, "marie")                            # même personne, écrite autrement
    services.preter(conn, ASTERIX, "Victor")
    services.preter(conn, VARGAS, "JD")                                # à soi-même : pas de lien
    s = services.stats(conn)
    noeuds = {n["id"]: n for n in s["reseau_noeuds"]}
    assert noeuds["jd"]["livres"] == 3 and noeuds["jd"]["a_moi"] and noeuds["jd"]["url"] == "/catalogue"
    assert noeuds["victor"]["livres"] == 1 and noeuds["victor"]["url"] == "/catalogue?proprio=Victor"
    assert noeuds["marie"]["livres"] is None and noeuds["marie"]["url"] is None
    assert s["reseau_aretes"] == [
        {"de": "jd", "vers": "marie", "nb": 2, "en_cours": 1, "nom": "JD — Marie"},
        {"de": "jd", "vers": "victor", "nb": 1, "en_cours": 1, "nom": "JD — Victor"},
    ]


def test_stats_collection(conn, biblio):
    services.modifier_notice(conn, CHANSON, {"collection": "Gallimard | Folio ; 4082", "pages": 250, "annee": 1950,
                                             "public": "adulte", "notes": "Lu"})
    services.modifier_notice(conn, ASTERIX, {"collection": "Collection folio ; 12", "pages": 1200, "annee": 2020})
    services.modifier_notice(conn, VARGAS, {"pages": 40, "annee": 2021})
    services.ajouter(conn, CHANSON, biblio["chambre"])
    s = services.stats(conn)
    assert s["par_collection"][0] == {"nom": "Folio", "nb": 3}         # numéros et casse ignorés
    assert s["titres_multiples"] == 1 and s["pages_moyenne"] == 435
    assert s["plusieurs_exemplaires"][0]["nb"] == 2 and s["plusieurs_exemplaires"][0]["url"] == f"/livre/{db.id_notice(conn, CHANSON)}"
    tranches = {t["court"]: t["nb"] for t in s["par_pages"]}
    assert len(s["par_pages"]) == 9 and tranches["0"] == 1 and tranches["200"] == 2 and tranches["800+"] == 1
    assert s["par_etagere"][0]["nom"] == "Salon › É1" and s["par_etagere"][0]["nb"] == 3
    assert f"lieu={biblio['salon']}" in s["par_etagere"][0]["url"]
    records = {r["libelle"]: r for r in s["records"]}
    assert records["Le plus ancien"]["valeur"] == "1950" and records["Le plus long"]["valeur"] == "1200 pages"
    jauges = {j["nom"]: j for j in s["completude"]}
    assert jauges["Note personnelle"]["nb"] == 1 and jauges["Note personnelle"]["total"] == 3
    assert jauges["Rangés dans un lieu"] == {"nom": "Rangés dans un lieu", "total": 4, "nb": 4}


def test_stats_amis(conn, biblio):
    services.ajouter(conn, CHANSON, proprietaire="Victor")               # un livre que j'ai aussi
    res = services.creer_notice_manuelle(conn, "Inédit", "", proprietaire="Victor")   # et un que je n'ai pas
    s = services.stats(conn)
    assert s["amis"] == [{"nom": "Victor", "exemplaires": 2, "titres": 2, "communs": 1, "absents": 1}]
    assert s["exemplaires"] == 3                                        # ses livres ne comptent pas dans les miens
    assert all(r["nom"] != "Inédit" for r in s["plusieurs_exemplaires"]) and res["notice_id"]


def test_don_change_seulement_le_proprietaire(conn, biblio):
    services.renommer_proprietaire_local(conn, "JD")
    ex = services.exemplaires_de(conn, CHANSON)[0]["id"]
    services.preter(conn, CHANSON, "Marie")
    assert services.donner(conn, ex, "Marie") is True
    e = services.exemplaires_de(conn, CHANSON)[0]
    assert e["proprietaire"] == "Marie" and e["lieu_id"] is None and not e["a_moi"]
    assert services.prets(conn) == []                         # le prêt est clos : le livre n'est plus à moi
    assert e["emplacement"] == "chez Marie"
    assert services.donner(conn, ex, "Marie") is False         # déjà à elle : rien ne change
    with pytest.raises(Erreur):
        services.donner(conn, ex, "  ")
    # Le livre de Marie ne se range pas chez moi, ne se prête pas, ne compte pas dans mes stats
    with pytest.raises(Erreur):
        services.deplacer_lot(conn, [ex], biblio["chambre"], None)
    with pytest.raises(Erreur):
        services.preter(conn, ex, "Victor")
    assert services.stats(conn)["exemplaires"] == 2
    assert services.deplacer(conn, CHANSON, biblio["chambre"], None)["statut"] == "inconnu"
    # Elle me le rend en cadeau : il revient, non localisé
    services.donner(conn, ex, "JD")
    assert services.exemplaires_de(conn, CHANSON)[0]["a_moi"]
    assert CHANSON in {n["isbn13"] for n in services.a_traiter(conn)["non_localises"]}


def test_filtre_proprietaire_et_doublon_chez_un_ami(conn, biblio):
    ex = services.exemplaires_de(conn, VARGAS)[0]["id"]
    services.donner(conn, ex, "Victor")
    assert services.rechercher(conn)[1] == 2
    assert services.rechercher(conn, proprietaire="Victor")[1] == 1
    assert services.rechercher(conn, proprietaire="tous")[1] == 3
    assert len(services.ids_exemplaires(conn, proprietaire="Victor")) == 1
    r = services.ajouter(conn, VARGAS, biblio["chambre"])
    assert r["statut"] == "ajoute" and "Victor" in r["message"]
    assert [p["nom"] for p in services.proprietaires(conn)] == [services.proprietaire_local(conn), "Victor"]
    n = services.renommer_proprietaire_local(conn, "Alex")
    assert n == 3 and services.rechercher(conn, proprietaire="Alex")[1] == 3


def test_livre_sans_code_barre(conn, biblio):
    res = services.creer_notice_manuelle(conn, "Mémoires", "Camille Dupont", lieu_id=biblio["salon"],
                                         forme="essai", annee="1932", proprietaire="Victor", notes="# Trouvé au grenier")
    n = services.notice(conn, res["notice_id"])
    assert n["isbn13"] is None and not res["recherche"]
    assert n["statut"] == "manuel" and n["annee"] == 1932 and n["forme"] == "essai"
    assert n["exemplaires"][0]["proprietaire"] == "Victor" and n["notes"] == "# Trouvé au grenier"
    assert services.creer_notice_manuelle(conn, "Autre", "")["notice_id"] != res["notice_id"]
    with pytest.raises(Erreur):
        services.creer_notice_manuelle(conn, "  ")
    # Avec un ISBN : les champs tapés sont protégés, les catalogues compléteront le reste
    res = services.creer_notice_manuelle(conn, "Mon titre", "", isbn="978-2-07-036002-4")
    assert res["recherche"] and services.notice(conn, res["notice_id"])["champs_manuels"] == ["titre"]


def test_manuel_avec_isbn_les_catalogues_completent_les_champs_vides(conn):
    services.creer_notice_manuelle(conn, "Mon titre", "", isbn=CHANSON)
    n = charger(conn, CHANSON, bnf="bnf_chanson_douce.xml")
    assert n["titre"] == "Mon titre" and n["auteurs"] == ["Leïla Slimani"]


def _ajouter_depuis_bnf_sans_isbn(conn):
    from biblio.sources import bnf

    from .conftest import fixture

    choix = next(r for r in bnf.lire_resultats(fixture("bnf_recherche_meaulnes.xml")) if not r["isbn"])
    return services.ajouter_depuis_bnf(conn, choix)


def test_livres_sans_isbn_ne_se_melangent_jamais(conn):
    premier = _ajouter_depuis_bnf_sans_isbn(conn)
    uid = services.notice(conn, premier["notice_id"])["uid"]
    services.annuler_exemplaire(conn, premier["exemplaire_id"])
    assert not conn.execute("SELECT 1 FROM raw_responses").fetchone()    # tout part avec la fiche
    deuxieme = _ajouter_depuis_bnf_sans_isbn(conn)                       # ne plante pas
    assert services.notice(conn, deuxieme["notice_id"])["uid"] != uid
    services.annuler_exemplaire(conn, deuxieme["exemplaire_id"])
    autre = services.creer_notice_manuelle(conn, "Tout autre livre", "Camille Dupont")
    services.liberer_champ(conn, autre["notice_id"], "auteurs")
    assert services.notice(conn, autre["notice_id"])["titre"] == "Tout autre livre"


def test_reference_d_un_livre_sans_isbn(conn, biblio):
    res = services.creer_notice_manuelle(conn, "Carnet", "", lieu_id=biblio["chambre"])
    ref = res["reference"]
    assert services.localiser(conn, ref)["message"] == "Chambre"
    assert services.localiser(conn, ref.lower())["notice_id"] == res["notice_id"]
    assert services.rechercher(conn, ref)[0][0]["titre"] == "Carnet"
    conn.execute("UPDATE exemplaires SET ajoute_le = '2020-01-01T00:00:00'")
    conn.commit()
    assert services.ajouter(conn, ref)["statut"] == "doublon"            # un second exemplaire
    inv = services.demarrer_inventaire(conn, biblio["chambre"])
    assert services.scanner_inventaire(conn, inv, ref)["statut"] == "present"


def test_reference_inconnue_refusee(conn, biblio):
    with pytest.raises(Erreur):
        services.ajouter(conn, "L99999")
    inv = services.demarrer_inventaire(conn, biblio["salon"])
    with pytest.raises(Erreur):
        services.scanner_inventaire(conn, inv, "L99999")


def test_personnes_une_seule_identite(conn, biblio):
    services.renommer_proprietaire_local(conn, "JD")
    services.ajouter(conn, CHANSON, proprietaire="Victor")
    ex = services.exemplaires_de(conn, ASTERIX)[0]["id"]
    assert services.donner(conn, ex, "victor")                             # « victor » = « Victor »
    assert [p["nom"] for p in services.proprietaires(conn)] == ["JD", "Victor"]
    services.preter(conn, VARGAS, "VICTOR")
    assert services.prets(conn)[0]["emprunteur"] == "Victor"               # le nom d'origine reste
    n = services.renommer_proprietaire_local(conn, "Alex")
    assert n == 2 and services.rechercher(conn, proprietaire="Alex")[1] == 2
    with pytest.raises(Erreur):
        services.renommer_proprietaire_local(conn, "victor")               # il a déjà des livres
    assert services.personne_id(conn, "alex") == db.moi_id(conn)
    # Un personnage nommé « tous » reste une personne : le filtre spécial ne le masque pas
    assert services.noms_personnes(conn) == ["Alex", "Victor"]


def test_devenir_un_simple_emprunteur(conn, biblio):
    services.preter(conn, CHANSON, "Alex")
    services.renommer_proprietaire_local(conn, "Alex")                 # c'était moi
    assert services.noms_personnes(conn) == ["Alex"]
    assert services.prets(conn)[0]["emprunteur"] == "Alex"


def test_inventaire_compte_les_exemplaires(conn, biblio):
    conn.execute("UPDATE exemplaires SET ajoute_le = '2020-01-01T00:00:00'")
    conn.commit()
    services.ajouter(conn, CHANSON, biblio["salon"], biblio["e1"])      # deux exemplaires sur l'étagère
    inv = services.demarrer_inventaire(conn, biblio["salon"], biblio["e1"])
    res = services.scanner_inventaire(conn, inv, CHANSON)
    assert res["statut"] == "present" and "1" in res["message"] and "2" in res["message"]
    r = services.rapport_inventaire(conn, inv)
    assert [n["isbn13"] for n in r["presents"]] == [CHANSON]
    assert sorted(n["isbn13"] for n in r["manquants"]) == sorted([CHANSON, ASTERIX, VARGAS])
    assert services.scanner_inventaire(conn, inv, CHANSON)["statut"] == "rebond"    # relu dans la foulée
    assert len(services.rapport_inventaire(conn, inv)["presents"]) == 1
    conn.execute("UPDATE inventaire_scans SET scanne_le = '2020-01-01T00:00:00'")
    conn.commit()
    services.scanner_inventaire(conn, inv, CHANSON)
    r = services.rapport_inventaire(conn, inv)
    assert [n["isbn13"] for n in r["presents"]] == [CHANSON, CHANSON]
    assert CHANSON not in [n["isbn13"] for n in r["manquants"]]


def test_inventaire_signale_seulement_l_exemplaire_prete(conn, biblio):
    conn.execute("UPDATE exemplaires SET ajoute_le = '2020-01-01T00:00:00'")
    conn.commit()
    services.ajouter(conn, CHANSON, biblio["salon"], biblio["e1"])
    services.preter(conn, CHANSON, "Marie")
    inv = services.demarrer_inventaire(conn, biblio["salon"], biblio["e1"])
    services.scanner_inventaire(conn, inv, CHANSON)
    manquants = [n for n in services.rapport_inventaire(conn, inv)["manquants"] if n["isbn13"] == CHANSON]
    assert len(manquants) == 1 and manquants[0]["prete"]


def test_import_ne_filtre_pas_les_doublons_voulus(conn):
    assert services.ajouter(conn, CHANSON, filtrer_rebond=False)["statut"] == "ajoute"
    assert services.ajouter(conn, CHANSON, filtrer_rebond=False)["statut"] == "doublon"
    assert len(services.exemplaires_de(conn, CHANSON)) == 2


def test_cote_manuelle_garde_sa_place_dans_le_rayon(conn, biblio):
    avant = [r["isbn13"] for r in services.rechercher(conn, systeme="rayon")[0]]
    services.fixer_classification(conn, ASTERIX, "rayon", "BD")
    assert [r["isbn13"] for r in services.rechercher(conn, systeme="rayon")[0]] == avant


def test_noms_de_lieux_vides_refuses(conn, biblio):
    with pytest.raises(Erreur):
        services.renommer_lieu(conn, biblio["salon"], "   ")
    with pytest.raises(Erreur):
        services.renommer_etagere(conn, biblio["e1"], "   ")


def test_lieu_dont_le_nom_contient_un_separateur(conn):
    lieu = services.creer_lieu(conn, "Bureau/Chambre")
    assert services.emplacement(conn, "Bureau/Chambre") == (lieu, None)


def test_dates_impossibles_refusees(conn, biblio):
    with pytest.raises(Erreur):
        services.rechercher(conn, ajout_du="2026-13-45")


def test_rendre_un_champ_inconnu_refuse(conn, biblio):
    with pytest.raises(Erreur):
        services.liberer_champ(conn, CHANSON, "nimportequoi")


def test_relancer_une_seule_regle(conn, biblio):
    # Échec partiel : la fiche est décrite, mais une source n'a pas répondu
    conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                 "VALUES (?, 'google', 'erreur', 'HTTP 500', '2026-01-01')", (db.id_notice(conn, VARGAS),))
    conn.commit()
    assert [n["isbn13"] for n in services.a_traiter(conn)["partiels"]] == [VARGAS]
    manuel = services.creer_notice_manuelle(conn, "Carnet", "")
    assert services.relancer(conn) == 1
    assert services.notice(conn, VARGAS)["statut"] == "en_attente"
    assert services.notice(conn, VARGAS)["titre"]                        # rien n'est perdu pendant l'attente
    statuts = {r["source"]: r["statut"] for r in conn.execute(
        "SELECT source, statut FROM raw_responses WHERE notice_id = ?", (db.id_notice(conn, VARGAS),))}
    assert statuts == {"bnf": "ok"}                                      # l'échec est oublié, la réponse valide reste
    assert services.notice(conn, manuel["notice_id"])["statut"] == "manuel"  # pas d'ISBN, rien à redemander


def test_non_localises_compte_seulement_mes_livres(conn, biblio):
    services.ajouter(conn, CHANSON, proprietaire="Victor")
    assert services.nb_non_localises(conn) == 0
    services.deplacer(conn, CHANSON, None, None)
    assert services.nb_non_localises(conn) == 1


def test_ajout_depuis_la_recherche_bnf(conn, biblio):
    from biblio.sources import bnf

    from .conftest import fixture

    resultats = bnf.lire_resultats(fixture("bnf_recherche_meaulnes.xml"))
    choix = resultats[1]
    assert choix["isbn"] is None and "Meaulnes" in choix["titre"]
    res = services.ajouter_depuis_bnf(conn, choix, biblio["salon"])
    n = services.notice(conn, res["notice_id"])
    assert n["isbn13"] is None and n["statut"] == "trouve"
    assert n["auteurs"] == ["Alain-Fournier"] and n["annee"] == 1946 and n["couverture_url"] is None
    assert any(c.get("cote") for c in n["classifications"])            # coté sans autre requête
    resolver.rebuild(conn, res["notice_id"])                           # relu à volonté depuis la réponse gardée
    assert services.notice(conn, res["notice_id"])["titre"] == n["titre"]


def test_lecture_vide_par_defaut_puis_renseignee(conn, biblio):
    n = services.notice(conn, CHANSON)
    assert (n["lecture"], n["lecture_debut"], n["lecture_fin"], n["etoiles"]) == (None, None, None, None)
    services.modifier_notice(conn, CHANSON, {"lecture": "lu", "lecture_fin": "2026-03-01", "etoiles": "4"})
    services.modifier_notice(conn, ASTERIX, {"lecture": "a_lire"})
    n = services.notice(conn, CHANSON)
    assert n["lecture"] == "lu" and n["etoiles"] == 4 and n["champs_manuels"] == []     # pas une correction de fiche
    assert [r["isbn13"] for r in services.rechercher(conn, lecture="a_lire")[0]] == [ASTERIX]
    assert services.rechercher(conn, lecture="aucune")[1] == 1
    s = services.stats(conn)
    assert s["lecture_lus"] == 1 and s["lecture_a_lire"] == 1 and s["lecture_note_moyenne"] == 4
    assert s["lus_par_an"] == [{"nom": "2026", "nb": 1}]
    resolver.rebuild(conn, CHANSON)                                      # les catalogues n'y touchent pas
    assert services.notice(conn, CHANSON)["lecture"] == "lu"
    services.modifier_notice(conn, CHANSON, {"lecture": "", "etoiles": ""})
    assert services.notice(conn, CHANSON)["lecture"] is None


@pytest.mark.parametrize("champs", [{"lecture": "peut-etre"}, {"etoiles": 6}, {"etoiles": "x"}, {"lecture_fin": "hier"}])
def test_lecture_valeurs_refusees(conn, biblio, champs):
    with pytest.raises(Erreur):
        services.modifier_notice(conn, CHANSON, champs)


def test_exemplaire_enrichi_vide_par_defaut(conn, biblio):
    ex = services.exemplaires_de(conn, CHANSON)[0]
    assert all(ex[c] is None for c in services.CHAMPS_EXEMPLAIRE)
    services.modifier_exemplaire(conn, ex["id"], {"etat": "bon", "prix_achat": "12,50", "date_achat": "2024-05-01",
                                                  "provenance": "Gibert", "dedicace": "Pour Alex", "valeur": 30, "notes": "taché"})
    ex = services.exemplaires_de(conn, CHANSON)[0]
    assert ex["prix_achat"] == 12.5 and ex["valeur"] == 30 and ex["etat"] == "bon"
    assert services.rechercher(conn, "taché")[1] == 1                    # la note d'exemplaire est cherchable
    s = services.stats(conn)
    assert s["valeur_totale"] == 30 and s["prix_total"] == 12.5 and s["par_etat"] == [{"nom": "Bon", "nb": 1}]
    services.modifier_exemplaire(conn, ex["id"], {"provenance": ""})
    assert services.exemplaires_de(conn, CHANSON)[0]["provenance"] is None


@pytest.mark.parametrize("champs", [{"etat": "?"}, {"prix_achat": "cher"}, {"valeur": -1}, {"date_achat": "2024-13-01"}, {"uid": "x"}])
def test_exemplaire_valeurs_refusees(conn, biblio, champs):
    ex = services.exemplaires_de(conn, CHANSON)[0]["id"]
    with pytest.raises(Erreur):
        services.modifier_exemplaire(conn, ex, champs)


def test_exemplaire_d_un_ami_non_modifiable(conn, biblio):
    ex = services.exemplaires_de(conn, CHANSON)[0]["id"]
    services.donner(conn, ex, "Victor")
    with pytest.raises(Erreur):
        services.modifier_exemplaire(conn, ex, {"etat": "bon"})


def test_suppressions_tracees(conn, biblio):
    ex = services.exemplaires_de(conn, CHANSON)[0]
    services.annuler_exemplaire(conn, ex["id"])
    assert conn.execute("SELECT genre FROM suppressions WHERE uid = ?", (ex["uid"],)).fetchone()[0] == "exemplaire"
    maj = conn.execute("SELECT maj_le FROM exemplaires WHERE notice_id = ?", (db.id_notice(conn, ASTERIX),)).fetchone()[0]
    services.supprimer_etagere(conn, biblio["e1"])
    services.supprimer_lieu(conn, biblio["salon"])
    assert conn.execute("SELECT count(*) FROM suppressions").fetchone()[0] == 3
    assert conn.execute("SELECT maj_le FROM exemplaires WHERE notice_id = ?", (db.id_notice(conn, ASTERIX),)).fetchone()[0] > maj


def _salon(conn):
    salon = services.creer_lieu(conn, "Salon")
    return salon, services.creer_etagere(conn, salon, "É1"), services.creer_etagere(conn, salon, "É2")


def _exemplaires(conn, n, lieu=None, etagere=None, proprietaire=None):
    return [services.ajouter(conn, CHANSON, lieu, etagere, proprietaire, filtrer_rebond=False)["exemplaire_id"]
            for _ in range(n)]


def test_doublons_garde_le_plus_ancien_du_meme_emplacement(conn):
    salon, e1, _ = _salon(conn)
    a, b, c = _exemplaires(conn, 3, salon, e1)
    groupe, = services.doublons(conn)["de_trop"]
    assert (groupe["garder"], groupe["retirer"], groupe["emplacement"]) == ([a], [b, c], "Salon › É1")
    assert services.retirer_doublons(conn) == 2
    assert [e["id"] for e in services.exemplaires_de(conn, CHANSON)] == [a]
    assert services.doublons(conn) == {"titres": [], "de_trop": [], "editions": []}
    # La synchronisation ne doit pas les faire revenir
    assert conn.execute("SELECT count(*) FROM suppressions WHERE genre = 'exemplaire'").fetchone()[0] == 2


def test_doublons_autres_emplacements_listes_mais_jamais_retires(conn):
    salon, e1, e2 = _salon(conn)
    chambre = services.creer_lieu(conn, "Chambre")
    ids = _exemplaires(conn, 1, salon, e1) + _exemplaires(conn, 1, salon, e2) + _exemplaires(conn, 1, chambre)
    ids += _exemplaires(conn, 2)                                          # deux non localisés
    d = services.doublons(conn)
    assert [e["id"] for e in d["titres"][0]["exemplaires"]] == ids and d["de_trop"] == []
    assert services.retirer_doublons(conn) == 0


def test_doublons_garde_les_exemplaires_renseignes_et_preferes(conn):
    salon, e1, e2 = _salon(conn)
    nu, note, prete, dedicace = _exemplaires(conn, 4, salon, e1)
    services.modifier_exemplaire(conn, note, {"notes": "second exemplaire"})
    services.modifier_exemplaire(conn, dedicace, {"dedicace": "à Victor"})
    services.preter(conn, prete, "Marie")
    groupe, = services.doublons(conn)["de_trop"]
    assert groupe["garder"] == [note, prete, dedicace] and groupe["retirer"] == [nu]


def test_doublons_garde_l_exemplaire_qui_a_un_historique(conn):
    salon, e1, e2 = _salon(conn)
    ancien, recent = _exemplaires(conn, 1, salon, e1) + _exemplaires(conn, 1, salon, e2)
    services.deplacer_exemplaire(conn, recent, salon, e1)
    groupe, = services.doublons(conn)["de_trop"]
    assert groupe["garder"] == [recent] and groupe["retirer"] == [ancien]


def test_doublons_ignore_les_livres_des_amis(conn):
    salon, e1, _ = _salon(conn)
    _exemplaires(conn, 2, salon, e1, "Victor")
    _exemplaires(conn, 1, salon, e1)
    assert services.doublons(conn) == {"titres": [], "de_trop": [], "editions": []}
    assert services.retirer_doublons(conn) == 0
    assert len(services.exemplaires_de(conn, CHANSON)) == 3


def test_doublons_autres_editions_listees_sans_rien_retirer(conn):
    salon, e1, _ = _salon(conn)
    for titre, isbn in (("Les Fleurs du mal", "9782253007104"), ("les fleurs du mal ", "9782035861566")):
        services.ajouter(conn, isbn, salon, e1)
        services.modifier_notice(conn, isbn, {"titre": titre, "auteurs": "Charles Baudelaire"})
    d = services.doublons(conn)
    assert [b["reference"] for b in d["editions"][0]] == ["9782253007104", "9782035861566"]
    assert d["titres"] == [] and d["de_trop"] == []
