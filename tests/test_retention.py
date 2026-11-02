"""L'archive des copies sur le disque externe du Raspberry Pi (deploy/retention.py)."""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "retention.py"
spec = importlib.util.spec_from_file_location("retention", SCRIPT)
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


def nom(d: datetime) -> str:
    return f"biblio-{d:%Y-%m-%d-%H%M%S}.db"


@pytest.fixture
def dossiers(tmp_path):
    sd, disque = tmp_path / "sd", tmp_path / "disque"
    sd.mkdir()
    return sd, disque


def nuit(sd, disque, d: datetime, garder_sd: int = 3, **options):
    """Comme biblio-backup.service : `biblio backup --keep 3`, puis l'archive."""
    (sd / nom(d)).write_bytes(f"{d}".encode())
    for ancienne in sorted(sd.glob("biblio-*.db"))[:-garder_sd]:
        ancienne.unlink()
    args = ["--sd", str(sd), "--disque", str(disque)]
    for cle, val in options.items():
        args += [f"--{cle}", str(val)]
    retention.main(args)


def dates(dossier: Path) -> list[datetime]:
    return sorted(retention.copies(dossier).values())


def test_deux_ans_de_copies(dossiers):
    sd, disque = dossiers
    debut = datetime(2026, 1, 1, 4, 20)
    for i in range(800):
        nuit(sd, disque, debut + timedelta(days=i, minutes=i % 20))       # l'heure varie un peu
    fin = max(dates(disque))
    archive = dates(disque)
    assert len([d for d in archive if fin - d < timedelta(days=7)]) == 7  # toute la semaine
    semaines = {d.isocalendar()[:2] for d in archive if timedelta(days=7) <= fin - d < timedelta(days=31)}
    assert len(semaines) >= 3                                             # une par semaine sur le mois
    mois = {(d.year, d.month) for d in archive if timedelta(days=31) <= fin - d < timedelta(days=366)}
    assert len(mois) >= 11                                                # une par mois sur l'année
    assert {d.year for d in archive} == {2026, 2027, 2028}                # une par an, sans limite
    assert len(archive) < 30                                              # et pas plus
    assert len(dates(sd)) == 3


def test_copies_a_la_main_archivees(dossiers):
    sd, disque = dossiers
    debut = datetime(2026, 11, 1, 4, 20)
    for i in range(3):
        nuit(sd, disque, debut + timedelta(days=i))
    (sd / nom(debut + timedelta(days=2, hours=10))).write_bytes(b"main")  # biblio backup dans la journée
    nuit(sd, disque, debut + timedelta(days=3))
    assert nom(debut + timedelta(days=2, hours=10)) in retention.copies(disque)
    assert len(dates(disque)) == 5


def test_copie_intacte_et_privee(dossiers):
    sd, disque = dossiers
    d = datetime(2026, 11, 1, 4, 20)
    nuit(sd, disque, d)
    copie = disque / nom(d)
    assert copie.read_bytes() == (sd / nom(d)).read_bytes()
    assert oct(copie.stat().st_mode)[-3:] == "600"
    assert not list(disque.glob("*.tmp"))


def test_rien_ne_vieillit_sans_nouvelles_copies(dossiers):
    sd, disque = dossiers
    debut = datetime(2026, 11, 1, 4, 20)
    for i in range(7):
        nuit(sd, disque, debut + timedelta(days=i))
    retention.main(["--sd", str(sd), "--disque", str(disque)])           # des mois plus tard, sans copie
    assert len(dates(disque)) == 7


def test_disque_non_monte_sous_mnt(tmp_path):
    """/mnt/disque/… sur la carte SD (disque pas monté) : surtout ne rien y créer."""
    assert retention.disponible(tmp_path / "ailleurs")                    # hors /mnt : créé
    assert (tmp_path / "ailleurs").is_dir()
    assert not retention.disponible(Path("/mnt/disque-qui-n-existe-pas/backups/biblio"))
    assert not Path("/mnt/disque-qui-n-existe-pas").exists()


def test_disque_absent_rien_ne_bouge(dossiers, monkeypatch):
    sd, disque = dossiers
    nuit(sd, disque, datetime(2026, 11, 1, 4, 20))
    monkeypatch.setattr(retention, "disponible", lambda d: False)
    nuit(sd, disque, datetime(2026, 11, 2, 4, 20))
    assert len(dates(disque)) == 1


def test_couvertures_et_simulation(dossiers, tmp_path):
    sd, disque = dossiers
    couv = tmp_path / "covers"
    couv.mkdir()
    (couv / "978.jpg").write_bytes(b"img")
    nuit(sd, disque, datetime(2026, 11, 1, 4, 20), couvertures=couv)
    assert (disque / "covers" / "978.jpg").read_bytes() == b"img"
    (sd / nom(datetime(2026, 11, 2, 4, 20))).write_bytes(b"x")
    avant = sorted(p.name for p in disque.iterdir())
    retention.main(["--sd", str(sd), "--disque", str(disque), "--simulation"])
    assert sorted(p.name for p in disque.iterdir()) == avant
