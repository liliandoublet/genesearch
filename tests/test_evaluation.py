"""Tests de l'évaluation : générateur d'erreurs, copie bruitée, et non-régression (R5).

Les seuils de non-régression portent sur une population synthétique dense (beaucoup
d'homonymes). Ils sont fixés un peu sous les valeurs mesurées à leur introduction
(présélection 100 %, rang 1 : 95,7 % en mode requête et 97,7 % en mode données, Brier ≤ 0,03)
et ne disent rien de la qualité sur de vraies données.
"""

import random
from pathlib import Path

import polars as pl
import pytest
from rapidfuzz.distance import Levenshtein

from doudoumil_search.ingest.insee_deces import ingerer_fichier
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.silver import construire_silver
from doudoumil_search.search.calibration import chemin_calibration, lire_calibration
from doudoumil_search.search.evaluation import (
    bruiter_texte,
    copier_bronze,
    enregistrer_calibration,
    evaluer_donnees,
    evaluer_requetes,
    tirer_notices,
)
from doudoumil_search.search.gold import construire_gold
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import Requete
from population import ecrire_population

EXTRAIT_COMMUNES = Path(__file__).parent / "fixtures" / "communes"


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT_COMMUNES)


@pytest.fixture(scope="module")
def population(tmp_path_factory: pytest.TempPathFactory, referentiel: Referentiel) -> Path:
    """Racine des données d'une population de 6 000 personnes, jusqu'à la base gold."""
    racine = tmp_path_factory.mktemp("population")
    ecrire_population(racine / "deces-2020.txt", 6000, noms_fabriques=0)
    ingerer_fichier(racine / "deces-2020.txt", racine / "bronze")
    construire_silver(racine / "bronze", racine / "silver", referentiel)
    construire_gold(racine / "silver", racine / "gold", referentiel)
    return racine


def test_bruiter_texte_une_seule_erreur() -> None:
    rng = random.Random(3)
    for nom in ("LE GOFF", "MARTIN", "KERGOAT", "DUPONT"):
        for _ in range(50):
            bruite = bruiter_texte(nom, rng)
            # une confusion, une perte ou un doublement : distance 1 ; une inversion : 2
            assert 0 <= Levenshtein.distance(nom, bruite) <= 2


def test_bruiter_texte_reproductible_et_sans_lettre() -> None:
    assert bruiter_texte("MOREAU", random.Random(1)) == bruiter_texte("MOREAU", random.Random(1))
    assert bruiter_texte("--", random.Random(1)) == "--"


def test_tirage_reproductible(population: Path) -> None:
    chemin = population / "gold" / "recherche.duckdb"
    premier = tirer_notices(chemin, 20, graine=5)
    assert len(premier) == 20
    assert premier == tirer_notices(chemin, 20, graine=5)
    assert premier != tirer_notices(chemin, 20, graine=6)


def test_copie_bruitee_garde_les_identifiants(population: Path, tmp_path: Path) -> None:
    copier_bronze(population / "bronze", tmp_path / "bruite", taux=0.5, graine=1, actes_max=500)
    copier_bronze(population / "bronze", tmp_path / "propre", taux=0.0, graine=1, actes_max=500)
    bruite = pl.read_parquet(tmp_path / "bruite" / "insee_deces" / "*" / "mentions-*.parquet")
    propre = pl.read_parquet(tmp_path / "propre" / "insee_deces" / "*" / "mentions-*.parquet")
    assert bruite.height == propre.height == 500
    assert bruite["mention_id"].sort().to_list() == propre["mention_id"].sort().to_list()
    jointes = propre.join(bruite, on="mention_id", suffix="_b")
    part_modifiee = (jointes["nom_brut"] != jointes["nom_brut_b"]).mean()
    assert 0.35 < part_modifiee < 0.65  # type: ignore[operator]
    assert set(bruite["confiance_source"]) == {0.5}


def test_non_regression_mode_requete(population: Path) -> None:
    mesures = evaluer_requetes(population / "gold" / "recherche.duckdb", 200, taux=0.2, graine=1)
    assert mesures.cas == 200
    assert mesures.rappel_preselection >= 0.97, mesures.resume()
    assert mesures.rappel_10 >= 0.97, mesures.resume()
    assert mesures.rappel_1 >= 0.88, mesures.resume()
    assert mesures.brier is not None and mesures.brier <= 0.06, mesures.resume()


def test_non_regression_mode_donnees(population: Path, referentiel: Referentiel) -> None:
    mesures = evaluer_donnees(population / "bronze", referentiel, 200, taux=0.2, graine=1)
    assert mesures.rappel_preselection >= 0.97, mesures.resume()
    assert mesures.rappel_10 >= 0.97, mesures.resume()
    assert mesures.rappel_1 >= 0.90, mesures.resume()
    assert mesures.brier is not None and mesures.brier <= 0.06, mesures.resume()


def test_calibration_enregistree(population: Path, tmp_path: Path) -> None:
    chemin = tmp_path / "recherche.duckdb"
    chemin.write_bytes((population / "gold" / "recherche.duckdb").read_bytes())
    mesures = evaluer_requetes(chemin, 100, taux=0.2, graine=2)
    assert set(mesures.paliers) == {"insee_deces"}
    enregistrer_calibration(chemin, mesures.paliers)
    enregistrer_calibration(chemin, {"socface": [(0.0, 0.2)]})  # une autre source s'ajoute
    enregistrer_calibration(chemin, mesures.paliers)  # remplace, n'ajoute pas
    paliers = lire_calibration(chemin_calibration(chemin))
    assert paliers["insee_deces"] == mesures.paliers["insee_deces"]
    assert paliers["socface"] == [(0.0, 0.2)]
    with Moteur(chemin) as moteur:
        notice = tirer_notices(chemin, 1, graine=3)[0]
        requete = Requete(nom=notice["nom_norm"], prenoms=tuple(notice["prenoms_norm"].split()))
        resultat = moteur.rechercher(requete)[0]
        assert resultat.probabilite is not None
        assert resultat.libelle != "non calibré"
