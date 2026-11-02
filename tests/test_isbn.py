import pytest

from biblio.isbn import IsbnError, normalize, to10, to13


def test_isbn13_valide():
    assert normalize("9782070360024") == "9782070360024"


def test_tirets_et_espaces():
    assert normalize("978-2-07-036002-4") == "9782070360024"
    assert normalize(" 978 2 07 036002 4 ") == "9782070360024"


def test_isbn10_converti():
    assert normalize("2070360024") == "9782070360024"
    assert normalize("2-07-036002-4") == "9782070360024"
    assert normalize("080442957X") == "9780804429573"


def test_addon_prix_ignore():
    assert normalize("978207036002451234") == "9782070360024"
    assert normalize("978207036002412") == "9782070360024"


def test_douchette_en_qwerty_sur_azerty():
    assert normalize("çè!éàèà\"§ààé'") == "9782070360024"   # Mac
    assert normalize("çè_éàèà\"-ààé'") == "9782070360024"   # PC


@pytest.mark.parametrize("code, message", [
    ("9782070360025", "clé de contrôle"),
    ("1234567890128", "produit"),
    ("9771234567003", "ISSN"),
    ("12345", "caractères"),
    ("", "vide"),
])
def test_codes_refuses(code, message):
    with pytest.raises(IsbnError, match=message):
        normalize(code)


def test_conversions():
    assert to13("2070360024") == "9782070360024"
    assert to10("9782070360024") == "2070360024"
    assert to10("9791032305935") is None
