from pathlib import Path

import pytest

from biblio import certs, covers, db, i18n

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    """Aucun test ne doit toucher les vraies données : base, couvertures, certificats."""
    monkeypatch.setenv("BIBLIO_DB", str(tmp_path / "defaut.db"))
    monkeypatch.setattr(covers, "DOSSIER", tmp_path / "covers")
    monkeypatch.setattr(certs, "DOSSIER", tmp_path / "certs")
    i18n.utiliser("fr")                 # importer la CLI passe le fil principal en anglais


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def charger(conn, isbn13: str, **raws):
    """Simule une résolution : notice en attente + réponses brutes enregistrées."""
    from biblio import resolver, services

    notice_id, _ = services.creer_notice_attente(conn, isbn13)
    for source, fichier in raws.items():
        conn.execute("INSERT OR REPLACE INTO raw_responses(notice_id, source, statut, payload, recu_le) "
                     "VALUES (?, ?, 'ok', ?, ?)", (notice_id, source, fixture(fichier), db.now()))
    conn.commit()
    return resolver.rebuild(conn, notice_id)
