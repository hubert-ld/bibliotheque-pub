import os
import sqlite3
import time

from biblio import db, sauvegarde, services

from .conftest import charger

CHANSON = "9782070196678"


def _base(tmp_path):
    conn = db.connect(tmp_path / "biblio.db")
    services.ajouter(conn, CHANSON)
    charger(conn, CHANSON, bnf="bnf_chanson_douce.xml")
    return conn


def test_copie_coherente_en_un_seul_fichier(tmp_path):
    conn = _base(tmp_path)
    services.modifier_notice(conn, CHANSON, {"notes": "à garder"})
    copie = sauvegarde.creer(conn)
    assert copie.parent == tmp_path / "sauvegardes" and copie.name.startswith("biblio-")
    assert [p.name for p in copie.parent.iterdir()] == [copie.name]          # ni -wal ni -shm
    c = sqlite3.connect(copie)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("SELECT notes FROM notices").fetchone()[0] == "à garder"
    c.close()
    conn.close()


def test_rotation_ne_touche_que_les_copies_de_cette_base(tmp_path):
    conn = _base(tmp_path)
    dossier = tmp_path / "ailleurs"
    dossier.mkdir()
    (dossier / "victor-2020-01-01-000000.db").write_text("copie de la base de Victor")
    (dossier / "notes.txt").write_text("autre")
    copies = [sauvegarde.creer(conn, dossier=dossier, garder=3) for _ in range(5)]
    restantes = sorted(p.name for p in dossier.glob("biblio-*.db"))
    assert len(restantes) == 3 and restantes == sorted(p.name for p in copies[-3:])
    assert (dossier / "victor-2020-01-01-000000.db").exists() and (dossier / "notes.txt").exists()
    conn.close()


def test_copie_automatique_une_fois_par_jour(tmp_path):
    conn = _base(tmp_path)
    premiere = sauvegarde.automatique(conn)
    assert premiere and sauvegarde.automatique(conn) is None
    vieux = time.time() - 2 * 86400
    os.utime(premiere, (vieux, vieux))
    assert sauvegarde.automatique(conn) not in (None, premiere)
    conn.close()


def test_pas_de_copie_automatique_d_une_base_vide(tmp_path):
    conn = db.connect(tmp_path / "vide.db")
    assert sauvegarde.automatique(conn) is None
    assert not (tmp_path / "sauvegardes").exists()
    conn.close()
