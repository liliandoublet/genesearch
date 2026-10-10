"""Tests de la ligne de commande."""

import argparse
import shutil
from pathlib import Path

import polars as pl
import pytest

from doudoumil_search.cli import intervalle, main

FIXTURE = Path(__file__).parent / "fixtures" / "deces-extrait.txt"


@pytest.mark.parametrize(
    ("texte", "annees"),
    [("2020", [2020]), ("2020-", [2020]), ("1970-1972", [1970, 1971, 1972])],
)
def test_intervalle(texte: str, annees: list[int]) -> None:
    assert list(intervalle(texte)) == annees


@pytest.mark.parametrize("texte", ["1972-1970", "vingt", "-1970"])
def test_intervalle_invalide(texte: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        intervalle(texte)


def test_ingest_insee_fichier_explicite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--donnees", str(tmp_path), "ingest", "insee", str(FIXTURE), "--processus", "1"])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "deces-extrait.txt : 8 ingérées, 2 rejetées" in sortie
    mentions = pl.read_parquet(tmp_path / "bronze/insee_deces/deces-extrait/mentions-*.parquet")
    assert mentions.height == 8


def test_ingest_insee_fichiers_telecharges(tmp_path: Path) -> None:
    telechargements = tmp_path / "bronze/insee_deces/telechargements"
    telechargements.mkdir(parents=True)
    shutil.copy(FIXTURE, telechargements / "deces-2020.txt")
    shutil.copy(FIXTURE, telechargements / "deces-2021.txt")
    # deux fichiers et deux processus : passe par le pool de processus
    assert main(["--donnees", str(tmp_path), "ingest", "insee", "--processus", "2"]) == 0
    for annee in (2020, 2021):
        assert (tmp_path / f"bronze/insee_deces/deces-{annee}/rejets.csv").exists()


def test_ingest_insee_sans_fichier(tmp_path: Path) -> None:
    assert main(["--donnees", str(tmp_path), "ingest", "insee"]) == 1
