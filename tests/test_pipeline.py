"""Tests de la commande unique : bronze → silver → gold, sans refaire ce qui est à jour."""

import os
import shutil
import time
from pathlib import Path
from urllib.error import URLError

import pytest

from doudoumil_search import pipeline
from doudoumil_search.cli import main
from doudoumil_search.config import dossier_telechargements_insee
from doudoumil_search.ingest import telechargement
from doudoumil_search.pipeline import executer_pipeline
from doudoumil_search.search.gold import chemin_base

FIXTURES = Path(__file__).parent / "fixtures"


def vieillir(chemin: Path, secondes: float = 60) -> None:
    """Recule la date d'un fichier ou d'un dossier et de son contenu."""
    instant = time.time() - secondes
    for element in [chemin, *chemin.rglob("*")] if chemin.is_dir() else [chemin]:
        os.utime(element, (instant, instant))


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    """Un fichier INSEE téléchargé, un relevé et le référentiel des communes."""
    telechargements = dossier_telechargements_insee(tmp_path)
    telechargements.mkdir(parents=True)
    shutil.copy(FIXTURES / "deces-extrait.txt", telechargements / "deces-2020.txt")
    shutil.copytree(FIXTURES / "releves", tmp_path / "releves")
    shutil.copytree(FIXTURES / "communes", tmp_path / "ref" / "communes")
    return tmp_path


def lancer(racine: Path, **options: object) -> tuple[pipeline.BilanPipeline, list[str]]:
    lignes: list[str] = []
    bilan = executer_pipeline(racine, afficher=lignes.append, **options)  # type: ignore[arg-type]
    return bilan, lignes


def test_premier_passage_construit_tout(racine: Path) -> None:
    bilan, lignes = lancer(racine)
    assert bilan.reussi, bilan.erreurs
    texte = "\n".join(lignes)
    assert "deces-2020.txt : 8 ingérées, 2 rejetées" in texte
    assert "landerneau-bms.csv : 7 ingérées, 3 rejetées" in texte
    assert "normalisation insee_deces : 7 actes (1 doublons écartés)" in texte
    assert "normalisation releve : 7 actes" in texte
    assert "base de recherche : 23 personnes" in texte
    assert "(insee_deces, releve)" in texte
    assert chemin_base(racine / "gold").exists()


def test_second_passage_ne_refait_rien(racine: Path) -> None:
    lancer(racine)
    vieillir(racine / "bronze")
    vieillir(racine / "silver")
    base = chemin_base(racine / "gold")
    date_base = base.stat().st_mtime
    bilan, lignes = lancer(racine)
    assert bilan.reussi
    assert lignes == [
        "décès INSEE : 1 fichier déjà converti",
        "relevé landerneau-bms : à jour",
        "normalisation insee_deces : à jour",
        "normalisation releve : à jour",
        "base de recherche : à jour",
    ]
    assert base.stat().st_mtime == date_base


def test_nouveau_mois_insee(racine: Path) -> None:
    """Seul le nouveau fichier est converti ; la source et la base sont refaites."""
    lancer(racine)
    vieillir(racine / "bronze")
    vieillir(racine / "silver")
    vieillir(racine / "gold")
    shutil.copy(
        FIXTURES / "deces-extrait.txt", dossier_telechargements_insee(racine) / "deces-2021-m01.txt"
    )
    _, lignes = lancer(racine)
    assert lignes[0].startswith("deces-2021-m01.txt : 8 ingérées")
    assert "décès INSEE : 1 fichier déjà converti" in lignes
    assert "relevé landerneau-bms : à jour" in lignes
    assert any(
        ligne.startswith("normalisation insee_deces : 7 actes (9 doublons") for ligne in lignes
    )
    assert "normalisation releve : à jour" in lignes
    assert lignes[-1].startswith("base de recherche : 23 personnes")


def test_releve_modifie(racine: Path) -> None:
    lancer(racine)
    vieillir(racine / "bronze")
    vieillir(racine / "silver")
    vieillir(racine / "gold")
    (racine / "releves" / "landerneau-bms.csv").touch()  # tableur complété
    _, lignes = lancer(racine)
    assert "landerneau-bms.csv : 7 ingérées, 3 rejetées" in "\n".join(lignes)
    assert "normalisation insee_deces : à jour" in lignes
    assert lignes[-1].startswith("base de recherche : 23 personnes")


def test_releve_retire(racine: Path) -> None:
    lancer(racine)
    (racine / "releves" / "landerneau-bms.toml").unlink()
    _, lignes = lancer(racine)
    assert any("relevé landerneau-bms : sans correspondance" in ligne for ligne in lignes)


def test_tout_refaire(racine: Path) -> None:
    lancer(racine)
    _, lignes = lancer(racine, forcer=True)
    assert not any("à jour" in ligne or "déjà converti" in ligne for ligne in lignes)


def test_releve_invalide_n_arrete_pas_le_reste(racine: Path) -> None:
    (racine / "releves" / "casse.toml").write_text("[releve]\n", encoding="utf-8")
    bilan, lignes = lancer(racine)
    assert not bilan.reussi
    assert bilan.erreurs[0].startswith("casse.toml : ")
    assert lignes[-1].startswith("base de recherche : 23 personnes")


def test_rien_a_indexer(tmp_path: Path) -> None:
    bilan, _ = lancer(tmp_path)
    assert not bilan.reussi
    assert "aucune donnée à indexer" in bilan.erreurs[0]


def test_telechargement_impossible(racine: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refus(annees: object = None) -> object:
        raise URLError("403 Forbidden")

    monkeypatch.setattr(telechargement, "lister_ressources_insee", refus)
    bilan, lignes = lancer(racine, telecharger=True)
    assert bilan.erreurs == [
        "téléchargement impossible (<urlopen error 403 Forbidden>) : données locales utilisées"
    ]
    assert lignes[-1].startswith("base de recherche : 23 personnes")


def test_commande_pipeline(racine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--donnees", str(racine), "pipeline", "--processus", "1"]) == 0
    assert "base de recherche : 23 personnes" in capsys.readouterr().out
    assert main(["--donnees", str(racine), "pipeline"]) == 0
    assert "base de recherche : à jour" in capsys.readouterr().out
    (racine / "releves" / "casse.toml").write_text("[releve]\n", encoding="utf-8")
    assert main(["--donnees", str(racine), "pipeline"]) == 1
