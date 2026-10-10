"""Tests de la sauvegarde et de la restauration des trouvailles et des relevés."""

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doudoumil_search.api.application import creer_application
from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.cli import main
from doudoumil_search.pivot import Source, fabriquer_id
from doudoumil_search.sauvegarde import (
    MANIFESTE,
    SauvegardeInvalide,
    restaurer,
    sauvegarder,
)

FIXTURES = Path(__file__).parent / "fixtures"


def carnet(racine: Path) -> Carnet:
    return Carnet(racine / "perso" / "trouvailles.sqlite")


def noter(racine: Path, *cles: str) -> None:
    for cle in cles:
        carnet(racine).enregistrer(
            fabriquer_id(Source.RELEVE, cle, "m"),
            fabriquer_id(Source.RELEVE, cle),
            f"notice {cle}",
            favori=True,
            note=f"note {cle}",
        )


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    racine = tmp_path / "donnees"
    noter(racine, "a", "b")
    shutil.copytree(FIXTURES / "releves", racine / "releves")
    return racine


def test_sauvegarde(racine: Path) -> None:
    chemin, contenu = sauvegarder(racine)
    assert chemin.parent == racine / "sauvegardes"
    assert chemin.name.startswith("doudoumil-") and chemin.suffix == ".zip"
    assert contenu.dossiers == ("perso", "releves")
    assert contenu.trouvailles == 2
    with zipfile.ZipFile(chemin) as archive:
        noms = set(archive.namelist())
        manifeste = json.loads(archive.read(MANIFESTE))
    assert noms == {
        MANIFESTE,
        "perso/trouvailles.sqlite",
        "releves/landerneau-bms.csv",
        "releves/landerneau-bms.toml",
    }
    assert manifeste["application"] == "doudoumil-search"
    assert manifeste["trouvailles"] == 2
    # deux sauvegardes dans la même seconde ne s'écrasent pas
    assert sauvegarder(racine)[0] != chemin


def test_restauration_dans_un_dossier_vide(racine: Path, tmp_path: Path) -> None:
    chemin, _ = sauvegarder(racine, tmp_path / "cle-usb")
    neuve = tmp_path / "nouvel-ordinateur"
    contenu, precedente = restaurer(neuve, chemin)
    assert precedente is None
    assert contenu.trouvailles == 2
    assert sorted(t.note for t in carnet(neuve).toutes()) == ["note a", "note b"]
    assert (neuve / "releves" / "landerneau-bms.toml").read_bytes() == (
        racine / "releves" / "landerneau-bms.toml"
    ).read_bytes()


def test_restauration_sauvegarde_l_etat_precedent(racine: Path, tmp_path: Path) -> None:
    chemin, _ = sauvegarder(racine, tmp_path / "cle-usb")
    noter(racine, "c")  # trouvaille ajoutée après la sauvegarde
    (racine / "releves" / "autre.csv").write_text("Nom\n", encoding="utf-8")

    contenu, precedente = restaurer(racine, chemin)
    assert contenu.dossiers == ("perso", "releves")
    assert len(carnet(racine).toutes()) == 2
    assert not (racine / "releves" / "autre.csv").exists()
    # l'état d'avant la restauration est récupérable
    assert precedente is not None
    restaurer(racine, precedente)
    assert len(carnet(racine).toutes()) == 3
    assert (racine / "releves" / "autre.csv").exists()


def test_dossier_absent_de_la_sauvegarde_intact(tmp_path: Path) -> None:
    sans_releves = tmp_path / "a"
    noter(sans_releves, "a")
    chemin, contenu = sauvegarder(sans_releves)
    assert contenu.dossiers == ("perso",)
    autre = tmp_path / "b"
    (autre / "releves").mkdir(parents=True)
    (autre / "releves" / "garde.csv").write_text("Nom\n", encoding="utf-8")
    restaurer(autre, chemin)
    assert (autre / "releves" / "garde.csv").exists()
    assert len(carnet(autre).toutes()) == 1


def test_archive_quelconque_refusee(tmp_path: Path) -> None:
    chemin = tmp_path / "photos.zip"
    with zipfile.ZipFile(chemin, "w") as archive:
        archive.writestr("perso/trouvailles.sqlite", b"")
    with pytest.raises(SauvegardeInvalide, match="pas une sauvegarde doudoumil"):
        restaurer(tmp_path / "donnees", chemin)


@pytest.mark.parametrize("nom", ["../evasion.txt", "perso/../../evasion.txt", "/tmp/x", "gold/a"])
def test_chemin_hors_des_dossiers_refuse(tmp_path: Path, nom: str) -> None:
    chemin = tmp_path / "piege.zip"
    with zipfile.ZipFile(chemin, "w") as archive:
        archive.writestr(MANIFESTE, json.dumps({"application": "doudoumil-search"}))
        archive.writestr(nom, b"x")
    with pytest.raises(SauvegardeInvalide, match="chemin refusé"):
        restaurer(tmp_path / "donnees", chemin)
    assert not (tmp_path / "evasion.txt").exists()
    assert not (tmp_path / "donnees").exists()


def test_commandes(racine: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cle = tmp_path / "cle-usb"
    assert main(["--donnees", str(racine), "sauvegarde", "--vers", str(cle)]) == 0
    sortie = capsys.readouterr().out
    assert "2 trouvailles, 3 fichiers de perso, releves" in sortie
    (archive,) = cle.glob("doudoumil-*.zip")

    neuve = tmp_path / "neuve"
    assert main(["--donnees", str(neuve), "restaure", str(archive)]) == 0
    sortie = capsys.readouterr().out
    assert "restauré : perso, releves (2 trouvailles, 3 fichiers)" in sortie
    assert "doudoumil pipeline" in sortie
    assert main(["--donnees", str(neuve), "restaure", str(FIXTURES / "deces-extrait.txt")]) == 1


def test_telechargement_depuis_l_interface(racine: Path) -> None:
    with TestClient(creer_application(racine)) as client:
        assert "/sauvegarde.zip" in client.get("/trouvailles").text
        reponse = client.get("/sauvegarde.zip")
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/zip"
    assert 'filename="doudoumil-' in reponse.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(reponse.content)) as archive:
        assert json.loads(archive.read(MANIFESTE))["trouvailles"] == 2
