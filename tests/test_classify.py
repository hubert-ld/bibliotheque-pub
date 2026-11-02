from biblio.classify import calculer, code_auteur
from biblio.classify.dewey import court, libelle
from biblio.sources import bnf

from .conftest import fixture


def notice(fichier, isbn, **extra):
    r = bnf.parse(fixture(fichier), isbn)
    return {**r, "classes_source": r["classes"], "auteur_tri": (r["auteurs_tri"] or [None])[0], **extra}


def codes(n, manuels=None):
    return {s: (v or {}).get("code") for s, v in calculer(n, manuels).items()}


def test_roman_francais():
    c = codes(notice("bnf_chanson_douce.xml", "9782070196678"))
    assert c == {"dewey": "843", "cadre_bnf": "803", "cdu": "821.133.1-31", "lcc": "PQ",
                 "clil": "LG-ROMF", "thema": "FB", "rayon": "ROMF"}


def test_roman_traduit_classe_par_langue_d_origine():
    n = notice("bnf_chanson_douce.xml", "9782070196678", langue_originale="eng")
    c = codes(n)
    assert (c["dewey"], c["cdu"], c["rayon"], c["clil"]) == ("823", "821.111-31", "ROME", "LG-ROME")


def test_bd():
    c = codes(notice("bnf_asterix.xml", "9782014001143"))
    assert (c["dewey"], c["cadre_bnf"], c["thema"], c["rayon"]) == ("741.5", "805", "XAB", "BD")


def test_documentaire_garde_le_dewey_bnf():
    res = calculer(notice("bnf_sapiens.xml", "9782286123949"))
    assert res["dewey"]["code"] == "909" and res["dewey"]["origine"] == "source"
    assert res["rayon"]["code"] == "HIS"


def test_jeunesse():
    n = notice("bnf_chanson_douce.xml", "9782070196678", public="jeunesse")
    res = calculer(n)
    assert res["dewey"]["prefixe"] == "J"
    assert res["rayon"]["code"] == "JEU"
    assert res["thema"]["code"] == "YF"


def test_policier_par_collection():
    n = notice("bnf_chanson_douce.xml", "9782070196678", collection="Série noire")
    assert codes(n)["rayon"] == "POL"


def test_dewey_manuel_propage_aux_autres_systemes():
    n = notice("bnf_chanson_douce.xml", "9782070196678")
    c = codes(n, {"dewey": "944.03"})
    assert c["rayon"] == "HIS"
    assert c["cdu"] == "94(44)"


def test_cotes():
    assert code_auteur("SAINT-EXUPÉRY Antoine de", "Le petit prince") == "SAI"
    assert code_auteur("LE CLÉZIO J. M. G.", None) == "LEC"
    assert code_auteur(None, "Les Misérables") == "MIS"
    assert court("363.7009052") == "363.7"
    assert court("843.914") == "843.914"
    assert libelle("891.73") == "800-899"
    assert libelle("944.03") == "900-999"
    assert libelle("sans chiffre") is None


def test_intitules_dewey_personnels(monkeypatch):
    from biblio.classify import dewey
    monkeypatch.setattr(dewey, "rules", lambda nom: {"libelles": {"843": "Mes romans"}})
    assert dewey.libelle("843.914") == "Mes romans"
    assert dewey.libelle("944") == "900-999"


def test_ordre_de_rangement_classe_large_avant_classe_fine():
    from biblio.classify import cle_tri

    dewey = ["843.914", "843", "800", "843.1", "84"]
    assert sorted(dewey, key=lambda c: cle_tri("", c, "AUTEUR", "t")) == ["800", "84", "843", "843.1", "843.914"]


def test_ordre_lcc_numerique():
    from biblio.classify import coter

    def tri(code):
        return coter("lcc", {"code": code, "origine": "source"}, "", {"auteur_tri": "A", "titre": "t"})[1]

    assert sorted(["QA76.73", "QA9", "PQ2603", "PQ261"], key=tri) == ["PQ261", "PQ2603", "QA9", "QA76.73"]
