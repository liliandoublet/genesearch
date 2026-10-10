"""Tests du score (R2 à R5), de la calibration et de l'interprétation des requêtes."""

from pathlib import Path

import pytest

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.search.calibration import ajuster_isotone, appliquer, brier
from doudoumil_search.search.requete import (
    Lieu,
    LieuInconnu,
    Requete,
    resoudre_lieu,
    separer_nom_prenoms,
)
from doudoumil_search.search.score import (
    NEUTRE,
    POIDS,
    Composantes,
    ecart_annees,
    libelle,
    score_lieu,
    score_naissance,
    score_nom,
    score_prenoms,
)

EXTRAIT_COMMUNES = Path(__file__).parent / "fixtures" / "communes"


# --- nom (R2) ------------------------------------------------------------------------------


def test_score_nom_identique_et_proche() -> None:
    assert score_nom("LE GOFF", "LE GOFF") == 1.0
    assert score_nom("LE GOFF", "LEGOFF") == 1.0  # espaces ignorés
    assert 0.85 < score_nom("LE GOFF", "LE GOSS") < 1.0  # type: ignore[operator]
    assert score_nom("LE GOFF", "DURAND") < 0.6  # type: ignore[operator]


def test_score_nom_sans_information() -> None:
    assert score_nom(None, "LE GOFF") is None
    assert score_nom("LE GOFF", None) is None


def test_score_nom_marital() -> None:
    """Nom d'épouse : neutre, sauf si le nom du conjoint est donné."""
    assert score_nom("LE GOFF", "MARTIN", nom_marital=True) is None
    assert score_nom("LE GOFF", "MARTIN", nom_marital=True, conjoint="MARTIN") == 1.0
    assert score_nom("LE GOFF", "MARTIN", nom_marital=True, conjoint="DURAND") < 0.6  # type: ignore[operator]


# --- prénoms (R4) --------------------------------------------------------------------------


def test_prenoms_independants_de_l_ordre() -> None:
    usuel = score_prenoms(["MARIE"], ["MARIE", "JOSEPHE"])
    second = score_prenoms(["MARIE"], ["JOSEPHE", "MARIE"])
    assert usuel == 1.0
    assert second is not None and 0.9 < second < 1.0  # sans le bonus du prénom usuel


def test_prenom_demande_absent_penalise() -> None:
    complet = score_prenoms(["MARIE", "JOSEPHE"], ["MARIE", "JOSEPHE"])
    partiel = score_prenoms(["MARIE", "LOUISE"], ["MARIE", "JOSEPHE"])
    assert complet == 1.0
    assert partiel is not None and partiel < 0.9


def test_prenoms_du_candidat_en_plus_non_penalises() -> None:
    assert score_prenoms(["JEAN"], ["JEAN", "MARIE", "LOUIS", "JOSEPH"]) == 1.0


def test_prenoms_sans_information() -> None:
    assert score_prenoms([], ["MARIE"]) is None
    assert score_prenoms(["MARIE"], []) is None


# --- naissance (R3) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "ecart"),
    [
        ((1931, 1931), (1931, 1931), 0),
        ((1930, 1932), (1931, 1931), 0),
        ((1931, 1931), (1934, 1935), 3),
    ],
)
def test_ecart_annees(a: tuple[int, int], b: tuple[int, int], ecart: int) -> None:
    assert ecart_annees(a, b) == ecart
    assert ecart_annees(b, a) == ecart


def test_score_naissance_decroit_avec_l_ecart() -> None:
    requete = (1931, 1931)
    scores = [score_naissance(requete, (1931 + e, 1931 + e), 2) for e in range(5)]
    assert scores[0] == 1.0
    assert scores == sorted(scores, reverse=True)
    assert scores[2] is not None and scores[2] > 0  # à la limite de tolérance : faible, non nul
    assert scores[3] == 0.0


def test_score_naissance_sans_information() -> None:
    assert score_naissance(None, (1931, 1931), 1) is None
    assert score_naissance((1931, 1931), None, 1) is None


# --- lieu -----------------------------------------------------------------------------------


def test_score_lieu() -> None:
    quimper = frozenset({"29232"}), frozenset({"29"})
    assert score_lieu(*quimper, ("35238", None, "29232", None), ("35", "29")) == 1.0
    assert score_lieu(*quimper, ("29019", None, None, None), ("29", None)) == 0.7
    assert score_lieu(*quimper, ("35238", None, None, None), ("35", None)) == 0.0
    # requête sur un département seulement
    assert score_lieu(frozenset(), frozenset({"29"}), ("29019",), ("29",)) == 1.0
    # sans lieu d'un côté ou de l'autre : neutre
    assert score_lieu(frozenset(), frozenset(), ("29019",), ("29",)) is None
    assert score_lieu(*quimper, (None, None), (None,)) is None


# --- combinaison (R5) -----------------------------------------------------------------------


def test_composantes_neutres() -> None:
    assert Composantes(None, None, None, None).score() == pytest.approx(NEUTRE)
    assert sum(POIDS.values()) == pytest.approx(1.0)


def test_confiance_rapproche_du_neutre() -> None:
    parfaite = Composantes(1.0, 1.0, 1.0, 1.0)
    nulle = Composantes(0.0, 0.0, 0.0, 0.0)
    assert parfaite.score(1.0) == pytest.approx(1.0)
    assert parfaite.score(0.6) == pytest.approx(0.8)
    assert nulle.score(0.6) == pytest.approx(0.2)
    assert parfaite.score(0.0) == pytest.approx(NEUTRE)


@pytest.mark.parametrize(
    ("probabilite", "texte"),
    [
        (0.95, "très probable"),
        (0.9, "très probable"),
        (0.7, "probable"),
        (0.2, "à vérifier"),
        (None, "non calibré"),
    ],
)
def test_libelle(probabilite: float | None, texte: str) -> None:
    assert libelle(probabilite) == texte


# --- calibration ----------------------------------------------------------------------------


def test_isotone_croissante_et_moyennes() -> None:
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    etiquettes = [False, True, False, False, True, True]
    paliers = ajuster_isotone(scores, etiquettes)
    probabilites = [p for _, p in paliers]
    assert probabilites == sorted(probabilites)
    # le violateur (0,2 vrai puis 0,3 et 0,4 faux) est fusionné en un bloc de moyenne 1/3
    assert paliers == [(0.1, 0.0), (0.2, pytest.approx(1 / 3)), (0.5, 1.0)]


def test_appliquer() -> None:
    paliers = [(0.1, 0.0), (0.2, 1 / 3), (0.5, 1.0)]
    assert appliquer(paliers, 0.05) == 0.0
    assert appliquer(paliers, 0.25) == pytest.approx(1 / 3)
    assert appliquer(paliers, 0.5) == 1.0
    assert appliquer([], 0.5) is None


def test_isotone_scores_egaux_regroupes() -> None:
    assert ajuster_isotone([0.5, 0.5, 0.5, 0.5], [True, False, True, True]) == [(0.5, 0.75)]


def test_isotone_vide_et_incoherent() -> None:
    assert ajuster_isotone([], []) == []
    with pytest.raises(ValueError, match="autant"):
        ajuster_isotone([0.1], [])


def test_brier() -> None:
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5, 0.5], [True, False]) == 0.25


# --- requête --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("LE GOFF Marie Josèphe", ("LE GOFF", "Marie Josèphe")),
        ("Marie LE GOFF", ("LE GOFF", "Marie")),
        ("le goff marie", ("le goff", "marie")),
        ("Dupont Anne", ("Dupont", "Anne")),
        ("DUPONT", ("DUPONT", None)),
        ("de la tour jean", ("de la tour", "jean")),
        ("", (None, None)),
    ],
)
def test_separer_nom_prenoms(texte: str, attendu: tuple[str | None, str | None]) -> None:
    assert separer_nom_prenoms(texte) == attendu


def test_requete_normalisee() -> None:
    requete = Requete.creer(nom="Le-Goff", prenoms="Jn Bte", sexe="M", conjoint="d'Hervé")
    assert requete.nom == "LE GOFF"
    assert requete.prenoms == ("JEAN", "BAPTISTE")
    assert requete.conjoint == "D HERVE"
    assert requete.est_exploitable()


def test_requete_sans_nom_exige_prenom_naissance_et_lieu() -> None:
    assert not Requete.creer(prenoms="Marie").est_exploitable()
    complete = Requete.creer(
        prenoms="Marie", naissance=(1931, 1931), lieu=Lieu(departements=frozenset({"29"}))
    )
    assert complete.est_exploitable()


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT_COMMUNES)


def test_resoudre_lieu(referentiel: Referentiel) -> None:
    assert resoudre_lieu("29", referentiel) == Lieu(departements=frozenset({"29"}))
    assert resoudre_lieu("2a", referentiel) == Lieu(departements=frozenset({"2A"}))
    assert resoudre_lieu("Quimper", referentiel) == Lieu(frozenset({"29232"}), frozenset({"29"}))
    assert resoudre_lieu("01039", referentiel) == Lieu(
        frozenset({"01039", "01138"}), frozenset({"01"})
    )
    assert resoudre_lieu("Saint-Denis (974)", referentiel) == Lieu(
        frozenset({"97411"}), frozenset({"974"})
    )
    assert resoudre_lieu("Saint-Denis", referentiel).communes == {"97411", "93066"}


def test_lieu_inconnu(referentiel: Referentiel) -> None:
    with pytest.raises(LieuInconnu, match="inconnue"):
        resoudre_lieu("Nulle-Part", referentiel)
    with pytest.raises(LieuInconnu, match="référentiel"):
        resoudre_lieu("Quimper", None)
    # un code se passe du référentiel
    assert resoudre_lieu("29232", None) == Lieu(frozenset({"29232"}), frozenset({"29"}))
