import time

from biblio import covers, db, services
from biblio import worker as module
from biblio.worker import Worker

from .conftest import fixture

CHANSON = "9782070196678"
VARGAS = "9782290382608"


def _preparer(conn, isbn, fichier):
    notice_id = services.ajouter(conn, isbn)["notice_id"]
    for source, statut, payload in (("bnf", "ok", fixture(fichier)), ("openlibrary", "absent", "{}"), ("loc", "absent", "")):
        conn.execute("INSERT INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                     "VALUES (?, ?, ?, ?, '2026-01-01')", (notice_id, source, statut, payload))
    conn.commit()


def _attendre(condition, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return False


def _en_attente(conn):
    return conn.execute("SELECT count(*) FROM notices WHERE statut = 'en_attente'").fetchone()[0]


def test_fil_de_fond_survit_a_une_panne_de_couverture(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "w.db")
    _preparer(conn, CHANSON, "bnf_chanson_douce.xml")
    def boum(*a, **kw):
        raise RuntimeError("panne imprévue")
    monkeypatch.setattr(covers, "telecharger", boum)
    monkeypatch.setattr(module, "PAUSE_APRES_ERREUR", 0.01)
    worker = Worker(db_path=tmp_path / "w.db")
    worker.start()
    try:
        assert _attendre(lambda: _en_attente(conn) == 0)
        _preparer(conn, VARGAS, "bnf_vargas.xml")                     # le suivant est quand même traité
        worker.wake()
        assert _attendre(lambda: _en_attente(conn) == 0)
        assert worker.is_alive()
    finally:
        worker.stop()
        worker.join(5)
    assert not worker.is_alive()
    conn.close()


def test_fil_de_fond_survit_a_une_base_indisponible(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "w.db")
    appels = []
    vraie = module.prochaine
    def prochaine(c):
        appels.append(1)
        if len(appels) == 1:
            raise db.sqlite3.OperationalError("database is locked")
        return vraie(c)
    monkeypatch.setattr(module, "prochaine", prochaine)
    monkeypatch.setattr(module, "PAUSE_APRES_ERREUR", 0.01)
    worker = Worker(db_path=tmp_path / "w.db")
    worker.start()
    try:
        assert _attendre(lambda: len(appels) >= 2)
        assert worker.is_alive()
    finally:
        worker.stop()
        worker.join(5)
    conn.close()


def test_notice_sans_isbn_en_attente_ne_boucle_pas(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "w.db")
    monkeypatch.setattr(covers, "telecharger", lambda *a, **kw: False)
    conn.execute("INSERT INTO notices(uid, statut, cree_le, maj_le) VALUES ('u', 'en_attente', 'x', 'x')")
    conn.commit()
    worker = Worker(db_path=tmp_path / "w.db")
    worker.start()
    try:
        assert _attendre(lambda: _en_attente(conn) == 0)
    finally:
        worker.stop()
        worker.join(5)
    conn.close()
