"""Tests de la normalisation : texte, noms, clé phonétique, prénoms, intervalles de naissance."""

from datetime import date

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from doudoumil_search.normalize.dates import (
    expressions_intervalle_naissance,
    intervalle_naissance,
)
from doudoumil_search.normalize.noms import compacter, normaliser_nom
from doudoumil_search.normalize.phonetique import cle_phonetique
from doudoumil_search.normalize.prenoms import equivalences, liste_prenoms, normaliser_prenoms
from doudoumil_search.normalize.texte import majuscules_ascii, mots

# Textes arbitraires, y compris accents, ligatures, apostrophes typographiques et chiffres.
textes = st.text(
    alphabet=st.characters(codec="utf-8", categories=("L", "M", "N", "P", "Zs")), max_size=40
)


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [("Lœtitia Bézier", "LOETITIA BEZIER"), ("Ægidius", "AEGIDIUS"), ("çà", "CA")],
)
def test_majuscules_ascii(brut: str, attendu: str) -> None:
    assert majuscules_ascii(brut) == attendu


def test_mots() -> None:
    assert mots("D'Hervé-Le  Goff (dit Yann)") == ["D", "HERVE", "LE", "GOFF", "DIT", "YANN"]


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("Le Goff", "LE GOFF"),
        ("LE-GOFF", "LE GOFF"),
        ("  le   goff ", "LE GOFF"),
        ("d'Hervé", "D HERVE"),
        ("D’HERVÉ", "D HERVE"),
        ("de La Tour d'Auvergne", "DE LA TOUR D AUVERGNE"),
        ("Müller", "MULLER"),
        ("O'Neill", "O NEILL"),
        ("", None),
        ("  - ' ", None),
        (None, None),
    ],
)
def test_normaliser_nom(brut: str | None, attendu: str | None) -> None:
    assert normaliser_nom(brut) == attendu


def test_compacter() -> None:
    assert compacter("LE GOFF") == "LEGOFF"


@given(textes)
def test_normaliser_nom_idempotent(texte: str) -> None:
    une_fois = normaliser_nom(texte)
    assert normaliser_nom(une_fois) == une_fois


@pytest.mark.parametrize(
    "groupe",
    [
        ["LE GOFF", "LEGOF", "LE GOFFE", "Le Goff", "LEGOFF"],
        ["DUPONT", "DUPOND", "DUPONTS"],
        ["PHILIPPE", "FILIPE", "PHILIPE"],
        ["THOMAS", "TOMAS"],
        ["KERGOAT", "QUERGOAT"],
        ["MEYER", "MAIER", "MAYER"],
        ["HENRI", "ENRI", "HENRY"],
        ["JEAN", "JEHAN"],
        ["CATHERINE", "KATHERINE"],
        ["JOSEPH", "JOSEF"],
        ["FRANÇOIS", "FRANCOIS"],
        ["ANNE", "ANNIE"],
    ],
)
def test_cle_phonetique_rapproche_les_variantes(groupe: list[str]) -> None:
    assert len({cle_phonetique(nom) for nom in groupe}) == 1, groupe


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # erreurs de lecture qui changent la prononciation : rattrapées par le canal B
        ("LE GOFF", "LE GOSS"),
        ("MOREAU", "NOREAU"),
        ("MARTIN", "MARTINEZ"),
        ("DUPONT", "DURAND"),
    ],
)
def test_cle_phonetique_distingue(a: str, b: str) -> None:
    assert cle_phonetique(a) != cle_phonetique(b)


@pytest.mark.parametrize(("brut", "cle"), [("LE GOFF", "LKF"), ("KERGOAT", "KRK"), ("A", "A")])
def test_cle_phonetique_valeurs_de_reference(brut: str, cle: str) -> None:
    """Fige l'algorithme : le changer impose de reconstruire les couches silver et gold."""
    assert cle_phonetique(brut) == cle


@pytest.mark.parametrize("vide", [None, "", "123", "-'"])
def test_cle_phonetique_sans_lettre(vide: str | None) -> None:
    assert cle_phonetique(vide) is None


@given(textes)
def test_cle_phonetique_ne_plante_jamais(texte: str) -> None:
    cle = cle_phonetique(texte)
    assert cle is None or (cle.isascii() and cle.isalpha() and cle.isupper())


@pytest.mark.parametrize(
    ("brut", "attendus"),
    [
        ("Marie Josèphe", ["MARIE", "JOSEPHE"]),
        ("Jean-Marie", ["JEAN", "MARIE"]),
        ("Jean Marie", ["JEAN", "MARIE"]),
        ("Jn Bte", ["JEAN", "BAPTISTE"]),
        ("Jn. Bte.", ["JEAN", "BAPTISTE"]),
        ("Fois Mie", ["FRANCOIS", "MARIE"]),
        ("Joannes Petrus", ["JEAN", "PIERRE"]),
        ("Jehan", ["JEAN"]),
        ("Hélène, Louise", ["HELENE", "LOUISE"]),
        ("", []),
        (None, []),
    ],
)
def test_liste_prenoms(brut: str | None, attendus: list[str]) -> None:
    assert liste_prenoms(brut) == attendus


def test_normaliser_prenoms() -> None:
    assert normaliser_prenoms("Jn-Bte Marie") == "JEAN BAPTISTE MARIE"
    assert normaliser_prenoms(" ") is None


@given(textes)
def test_normaliser_prenoms_idempotent(texte: str) -> None:
    une_fois = normaliser_prenoms(texte)
    assert normaliser_prenoms(une_fois) == une_fois


def test_table_d_equivalences_coherente() -> None:
    """Les formes sont déjà normalisées et ne renvoient pas vers une autre forme de la table."""
    table = equivalences()
    assert len(table) > 50
    for forme, prenom in table.items():
        assert mots(forme) == [forme], forme
        assert mots(prenom) == [prenom], prenom
        assert prenom not in table, f"{forme} → {prenom} → {table.get(prenom)}"


CAS_NAISSANCE = [
    # (date complète, date brute, âge, année de l'acte) → intervalle
    (date(1931, 3, 2), "19310302", None, 2020, (1931, 1931)),
    (None, "19310300", None, 2020, (1931, 1931)),
    (None, "19310000", None, 2020, (1931, 1931)),
    (None, "00000000", None, 2020, None),
    (None, None, 40, 1906, (1865, 1866)),
    (None, "00000000", 40, 1906, (1865, 1866)),
    (date(1931, 3, 2), None, 40, 1906, (1931, 1931)),
    (None, None, 40, None, None),
    (None, None, None, 1906, None),
    (None, "12990101", None, 1350, None),
    (None, None, None, None, None),
]


@pytest.mark.parametrize(("naissance", "brute", "age", "annee", "attendu"), CAS_NAISSANCE)
def test_intervalle_naissance(
    naissance: date | None,
    brute: str | None,
    age: int | None,
    annee: int | None,
    attendu: tuple[int, int] | None,
) -> None:
    assert intervalle_naissance(naissance, brute, age, annee) == attendu


def test_expressions_et_fonction_concordent() -> None:
    table = pl.DataFrame(
        [(n, b, a, y) for n, b, a, y, _ in CAS_NAISSANCE],
        schema={
            "date_naissance": pl.Date,
            "date_naissance_brute": pl.String,
            "age": pl.Int16,
            "annee": pl.Int16,
        },
        orient="row",
    )
    mini, maxi = expressions_intervalle_naissance(pl.col("annee"))
    resultat = table.select(mini, maxi).rows()
    attendus = [attendu or (None, None) for *_, attendu in CAS_NAISSANCE]
    assert resultat == attendus
