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


def test_normalize(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    racine = str(tmp_path)
    assert main(["--donnees", racine, "ingest", "insee", str(FIXTURE)]) == 0
    referentiel = tmp_path / "ref" / "communes"
    shutil.copytree(Path(__file__).parent / "fixtures" / "communes", referentiel)
    capsys.readouterr()
    assert main(["--donnees", racine, "normalize"]) == 0
    assert "insee_deces : 7 actes (1 doublons écartés), 7 mentions" in capsys.readouterr().out
    actes = pl.read_parquet(tmp_path / "silver/insee_deces/actes.parquet")
    assert "Rennes" in actes["commune_label"].to_list()


def test_normalize_sans_referentiel(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    racine = str(tmp_path)
    main(["--donnees", racine, "ingest", "insee", str(FIXTURE)])
    assert main(["--donnees", racine, "normalize"]) == 0
    assert "référentiel des communes absent" in caplog.text


def test_normalize_bronze_vide(tmp_path: Path) -> None:
    assert main(["--donnees", str(tmp_path), "normalize"]) == 1


def _chaine_complete(racine: Path) -> None:
    main(["--donnees", str(racine), "ingest", "insee", str(FIXTURE)])
    shutil.copytree(Path(__file__).parent / "fixtures" / "communes", racine / "ref" / "communes")
    main(["--donnees", str(racine), "normalize"])


def test_index_et_cherche(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _chaine_complete(tmp_path)
    racine = str(tmp_path)
    assert main(["--donnees", racine, "index"]) == 0
    assert "base de recherche : 7 personnes" in capsys.readouterr().out

    code = main(
        ["--donnees", racine, "cherche", "LE GOFF Marie", "--naissance", "1931", "--details"]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    premiere = sortie.splitlines()[0]
    assert "LE GOFF MARIE JOSEPHE (F)" in premiere
    assert "née le 02/03/1931 à QUIMPER" in premiere
    assert "décès le 15/01/2020 à Rennes (35)" in premiere
    assert "INSEE · deces-extrait.txt · vue 1" in sortie
    assert "nom 1,00" in sortie


def test_cherche_par_lieu_et_sans_nom(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _chaine_complete(tmp_path)
    racine = str(tmp_path)
    main(["--donnees", racine, "index"])
    capsys.readouterr()
    args = ["--donnees", racine, "cherche", "--prenoms", "Yves", "--naissance", "1919"]
    assert main([*args, "--lieu", "Landerneau"]) == 0
    assert "KERGOAT YVES MARIE" in capsys.readouterr().out.splitlines()[0]
    assert main([*args, "--lieu", "Nulle-Part"]) == 1
    assert main(["--donnees", racine, "cherche", "--prenoms", "Yves"]) == 1


def test_cherche_sans_base(tmp_path: Path) -> None:
    assert main(["--donnees", str(tmp_path), "cherche", "DUPONT"]) == 1
    assert main(["--donnees", str(tmp_path), "index"]) == 1


def test_evalue_et_calibre(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _chaine_complete(tmp_path)
    racine = str(tmp_path)
    main(["--donnees", racine, "index"])
    capsys.readouterr()
    assert main(["--donnees", racine, "evalue", "--cas", "5"]) == 0
    assert "mode requete, taux d'erreur 20 % : 5 cas" in capsys.readouterr().out
    assert main(["--donnees", racine, "evalue", "--mode", "donnees", "--cas", "5"]) == 0
    assert main(["--donnees", racine, "calibre", "--cas", "7"]) == 0
    assert "insee_deces : calibration en" in capsys.readouterr().out
    main(["--donnees", racine, "cherche", "LE GOFF"])
    assert "non calibré" not in capsys.readouterr().out
