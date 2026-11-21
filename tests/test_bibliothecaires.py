"""Qui a introduit un livre, qui l'a scanné : attribution, partage et statistiques."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from biblio import auth, db, partage, services, telephone
from biblio.web.app import app

from .conftest import charger
from .test_auth import LOCAL, RESEAU, base, connecte  # noqa: F401  (base : fixture)

CHANSON = "9782070196678"
ASTERIX = "9782014001143"


def exemplaire(conn, isbn=CHANSON, rang=0):
    return services.exemplaires_de(conn, isbn)[rang]


def scans(conn, ex_id=None):
    sql, params = "SELECT par, mode FROM scans ORDER BY id", ()
    if ex_id:
        sql, params = "SELECT par, mode FROM scans WHERE exemplaire_id = ? ORDER BY id", (ex_id,)
    return [tuple(r) for r in conn.execute(sql, params)]


def poster_scan(client, mode, code=CHANSON, **autres):
    return client.post("/api/scan", json={"mode": mode, "code": code, **autres}).json()


# --- Services ---------------------------------------------------------------------

def test_ajout_garde_son_auteur_et_le_scan_met_a_jour(conn):
    services.ajouter(conn, CHANSON, par="claire")
    assert exemplaire(conn)["ajoute_par"] == "claire"
    assert exemplaire(conn)["dernier_scan_par"] is None           # l'ajout seul n'est pas un scan : c'est noter_scan qui compte
    res = services.localiser(conn, CHANSON)
    avant = exemplaire(conn)["maj_le"]
    services.noter_scan(conn, res, "louis", "ou")
    ex = exemplaire(conn)
    assert ex["ajoute_par"] == "claire" and ex["dernier_scan_par"] == "louis" and ex["dernier_scan_le"]
    assert ex["maj_le"] == avant                                  # un scan n'est pas une modification
    assert scans(conn) == [("louis", "ou")]


def test_sans_auteur_le_bibliothecaire_local(conn):
    db.set_meta(conn, "bibliothecaire", "alex")
    services.ajouter(conn, CHANSON)
    assert exemplaire(conn)["ajoute_par"] == "alex"


@pytest.mark.parametrize("statut", ["rebond", "inconnu"])
def test_scans_ignores(conn, statut):
    services.ajouter(conn, CHANSON, par="louis")
    services.noter_scan(conn, {"notice_id": exemplaire(conn)["notice_id"], "statut": statut}, "louis", "ajout")
    assert scans(conn) == []


def test_sans_notice_rien_a_noter(conn):
    services.noter_scan(conn, {"statut": "trouve"}, "louis", "ou")
    assert scans(conn) == []


def test_deux_scans_touchent_deux_exemplaires(conn):
    services.ajouter(conn, CHANSON, filtrer_rebond=False, par="louis")
    services.ajouter(conn, CHANSON, filtrer_rebond=False, par="louis")
    res = services.localiser(conn, CHANSON)
    services.noter_scan(conn, res, "claire", "ou")
    services.noter_scan(conn, res, "claire", "ou")
    assert scans(conn, exemplaire(conn, rang=0)["id"]) == [("claire", "ou")]
    assert scans(conn, exemplaire(conn, rang=1)["id"]) == [("claire", "ou")]


def test_inventaire_vise_l_exemplaire_de_la_zone(conn):
    salon = services.creer_lieu(conn, "Salon")
    chambre = services.creer_lieu(conn, "Chambre")
    services.ajouter(conn, CHANSON, chambre, filtrer_rebond=False, par="louis")
    services.ajouter(conn, CHANSON, salon, filtrer_rebond=False, par="louis")
    inv = services.demarrer_inventaire(conn, salon)
    res = services.scanner_inventaire(conn, inv, CHANSON)
    services.noter_scan(conn, res, "claire", "inventaire")
    au_salon = next(e for e in services.exemplaires_de(conn, CHANSON) if e["lieu_id"] == salon)
    assert scans(conn, au_salon["id"]) == [("claire", "inventaire")]


def test_deplacement_deja_la_vise_cet_exemplaire(conn):
    salon = services.creer_lieu(conn, "Salon")
    chambre = services.creer_lieu(conn, "Chambre")
    services.ajouter(conn, CHANSON, chambre, filtrer_rebond=False, par="louis")
    services.ajouter(conn, CHANSON, salon, filtrer_rebond=False, par="louis")
    res = services.deplacer(conn, CHANSON, salon, None)
    assert res["statut"] == "deja_la"
    services.noter_scan(conn, res, "claire", "deplacement")
    au_salon = next(e for e in services.exemplaires_de(conn, CHANSON) if e["lieu_id"] == salon)
    assert au_salon["dernier_scan_par"] == "claire"


def test_inconnu_ajoute_a_la_cloture_compte_comme_scan(conn):
    salon = services.creer_lieu(conn, "Salon")
    inv = services.demarrer_inventaire(conn, salon)
    services.scanner_inventaire(conn, inv, CHANSON)
    services.cloturer_inventaire(conn, inv, ajouter_inconnus=True, par="nina")
    assert exemplaire(conn)["ajoute_par"] == "nina"
    assert scans(conn) == [("nina", "inventaire")]


def test_annuler_un_ajout_retire_le_scan(conn):
    res = services.ajouter(conn, CHANSON, par="louis")
    services.noter_scan(conn, res, "louis", "ajout")
    services.annuler_exemplaire(conn, res["exemplaire_id"])
    assert scans(conn) == []


def test_saisie_manuelle_a_un_auteur_mais_pas_de_scan(conn):
    services.creer_notice_manuelle(conn, "Carnet", par="louis")
    ligne = conn.execute("SELECT ajoute_par, dernier_scan_par FROM exemplaires").fetchone()
    assert tuple(ligne) == ("louis", None)
    assert scans(conn) == []


def test_un_compte_ne_peut_pas_prendre_le_nom_du_telephone(conn):
    with pytest.raises(auth.ErreurCompte):
        auth.creer_compte(conn, db.PAR_TELEPHONE, "lecteur", code="1234")


# --- Attribution selon l'accès -----------------------------------------------------

def test_scan_avec_un_compte(base):
    client = connecte(base, "bibliothecaire", "claire")
    assert poster_scan(client, "ajout")["statut"] == "ajoute"
    ex = exemplaire(base)
    assert ex["ajoute_par"] == ex["dernier_scan_par"] == "claire"
    assert scans(base) == [("claire", "ajout")]


def test_scan_avec_le_qr_code(base):
    client = TestClient(app, client=RESEAU)
    client.get(f"/scan?cle={telephone.cle(base)}")
    assert poster_scan(client, "ajout")["statut"] == "ajoute"
    assert exemplaire(base)["ajoute_par"] == db.PAR_TELEPHONE
    assert scans(base) == [(db.PAR_TELEPHONE, "ajout")]
    assert services.stats(base)["par_scanneur"] == [{"nom": "Téléphone partagé", "nb": 1}]


def test_scan_avec_la_cle_admin(base):
    db.set_meta(base, "bibliothecaire", "alex")
    client = TestClient(app, client=RESEAU)
    client.get(f"/scan?cle={telephone.cle_admin(base)}")
    poster_scan(client, "ajout")
    assert scans(base) == [("alex", "ajout")]


def test_scan_depuis_cet_ordinateur(base):
    db.set_meta(base, "bibliothecaire", "alex")
    client = TestClient(app, client=LOCAL, base_url="http://localhost")
    poster_scan(client, "ajout")
    assert exemplaire(base)["ajoute_par"] == "alex"
    assert scans(base) == [("alex", "ajout")]


def test_tous_les_modes_comptent(base):
    db.set_meta(base, "bibliothecaire", "alex")
    client = TestClient(app, client=LOCAL, base_url="http://localhost")
    salon = services.creer_lieu(base, "Salon")
    poster_scan(client, "ajout")
    poster_scan(client, "ajout")                                  # rebond : ne compte pas
    poster_scan(client, "ou")
    poster_scan(client, "deplacement", lieu_id=salon)
    inv = client.post("/api/inventaire", json={"lieu_id": salon}).json()["id"]
    poster_scan(client, "inventaire", inventaire_id=inv)
    poster_scan(client, "ou", code=ASTERIX)                       # inconnu : ne compte pas
    assert [m for _, m in scans(base)] == ["ajout", "ou", "deplacement", "inventaire"]


def test_lecteur_ou_est_il_compte(base):
    services.ajouter(base, CHANSON, par="alex")
    client = connecte(base, "lecteur", "léonie")
    assert poster_scan(client, "ou")["statut"] == "trouve"
    assert exemplaire(base)["dernier_scan_par"] == "léonie"


def test_refuse_ne_compte_pas(base):
    client = connecte(base, "lecteur", "léonie")
    assert poster_scan(client, "ajout")["statut"] == "erreur"
    assert scans(base) == []


# --- Partage et synchronisation ------------------------------------------------------

def test_partage_sans_les_noms(conn, tmp_path):
    res = services.ajouter(conn, CHANSON, par="claire")
    services.noter_scan(conn, res, "claire", "ajout")
    fichier = tmp_path / "partage.db"
    partage.exporter_partage(conn, fichier)
    src = sqlite3.connect(fichier)
    assert src.execute("SELECT ajoute_par, dernier_scan_le, dernier_scan_par FROM exemplaires").fetchone() == (None, None, None)
    assert src.execute("SELECT count(*) FROM scans").fetchone()[0] == 0
    src.close()
    assert b"claire" not in fichier.read_bytes()


def test_synchronisation_dans_les_deux_sens(tmp_path):
    fixe = db.connect(tmp_path / "fixe.db")
    res = services.ajouter(fixe, CHANSON, par="alex")
    services.noter_scan(fixe, res, "alex", "ajout")
    portable = db.connect(tmp_path / "portable.db")
    db.ecrire_meta(portable, "moi_uid", db.get_meta(fixe, "moi_uid"))
    portable.execute("INSERT INTO personnes SELECT * FROM (SELECT 1, ?, 'Moi', 'moi', ?)",
                     (db.get_meta(fixe, "moi_uid"), db.horodatage()))
    portable.commit()

    partage.synchroniser(portable, db.chemin_base(fixe))
    ex = exemplaire(portable)
    assert ex["ajoute_par"] == "alex" and ex["dernier_scan_par"] == "alex"
    assert scans(portable) == [("alex", "ajout")]
    maj_avant = exemplaire(fixe)["maj_le"]

    # Un scan plus récent sur le portable gagne là-bas, sans compter comme une modification
    portable.execute("UPDATE exemplaires SET dernier_scan_le = '2099-01-01T00:00:00', dernier_scan_par = 'louis'")
    portable.execute("INSERT INTO scans(uid, exemplaire_id, par, le, mode) VALUES ('u2', ?, 'louis', '2099-01-01T00:00:00', 'ou')",
                     (ex["id"],))
    portable.commit()
    partage.synchroniser(fixe, db.chemin_base(portable))
    ex = exemplaire(fixe)
    assert ex["dernier_scan_par"] == "louis" and ex["maj_le"] == maj_avant
    assert scans(fixe) == [("alex", "ajout"), ("louis", "ou")]

    # Relancer ne double rien, et un scan plus ancien ne remplace pas le récent
    fixe.execute("UPDATE exemplaires SET dernier_scan_le = '2100-01-01T00:00:00', dernier_scan_par = 'claire'")
    fixe.commit()
    partage.synchroniser(fixe, db.chemin_base(portable))
    assert exemplaire(fixe)["dernier_scan_par"] == "claire"
    assert len(scans(fixe)) == 2
    fixe.close()
    portable.close()


# --- Statistiques ---------------------------------------------------------------------

def test_stats_des_bibliothecaires(conn):
    a = services.ajouter(conn, CHANSON, par="claire")
    services.noter_scan(conn, a, "claire", "ajout")
    b = services.ajouter(conn, ASTERIX, par="louis")
    services.noter_scan(conn, b, "louis", "ajout")
    services.noter_scan(conn, services.localiser(conn, ASTERIX), "claire", "ou")
    services.noter_scan(conn, services.localiser(conn, CHANSON), "claire", "ou")
    s = services.stats(conn)
    assert s["bibliothecaires"][0]["nom"] == "claire" and s["bibliothecaires"][0]["scans"] == 3
    assert s["bibliothecaires"][1] == {"nom": "louis", "introduits": 1, "scans": 1, "dernier_scan": db.now()[:10]}
    assert {r["nom"]: r["nb"] for r in s["par_introducteur"]} == {"claire": 1, "louis": 1}
    assert s["par_scanneur"][0] == {"nom": "claire", "nb": 3}
    assert len(s["scans_par_mois"]) == 12 and s["scans_par_mois"][-1] == {"mois": db.now()[:7], "nom": db.now()[:7], "nb": 4}


def test_stats_les_livres_des_amis_ne_comptent_pas(conn):
    res = services.ajouter(conn, CHANSON, proprietaire="Victor", par="victor")
    services.noter_scan(conn, res, "victor", "ajout")
    assert services.stats(conn)["bibliothecaires"] == []


def test_page_stats(base):
    client = TestClient(app, client=LOCAL, base_url="http://localhost")
    assert "Bibliothécaires" not in client.get("/stats").text        # aucun livre : pas de section
    charger(base, CHANSON, bnf="bnf_chanson_douce.xml")
    res = services.ajouter(base, CHANSON, par="claire")
    services.noter_scan(base, res, "claire", "ajout")
    page = client.get("/stats").text
    assert "Bibliothécaires" in page and "claire" in page and "Scans par mois" in page
