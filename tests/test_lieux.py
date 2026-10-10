"""Tests du référentiel des communes, sur un extrait du vrai référentiel."""

import io
import json
import tarfile
from pathlib import Path
from urllib.request import Request

import pytest

from doudoumil_search.normalize.lieux import (
    Referentiel,
    normaliser_lieu,
    telecharger_referentiel,
)

EXTRAIT = Path(__file__).parent / "fixtures" / "communes"


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT)


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("Saint-Malo", "SAINT MALO"),
        ("St Malo", "SAINT MALO"),
        ("ST-MALO", "SAINT MALO"),
        ("Ste-Anne-d'Auray", "SAINTE ANNE D AURAY"),
        ("Paris 15e Arrondissement", "PARIS 15E ARRONDISSEMENT"),
        ("", None),
        (None, None),
    ],
)
def test_normaliser_lieu(brut: str | None, attendu: str | None) -> None:
    assert normaliser_lieu(brut) == attendu


@pytest.mark.parametrize(
    ("code", "actuel"),
    [
        ("29232", "29232"),  # commune actuelle
        ("01039", "01138"),  # commune déléguée (Béon → Culoz-Béon)
        ("29050", "29232"),  # ancien code fusionné dans Quimper
        ("20004", "2A004"),  # code d'Ajaccio d'avant la Corse-du-Sud
        ("75115", "75056"),  # arrondissement de Paris
        ("13201", "13055"),  # arrondissement de Marseille
        ("99999", None),
        (None, None),
    ],
)
def test_code_actuel(referentiel: Referentiel, code: str | None, actuel: str | None) -> None:
    assert referentiel.code_actuel(code) == actuel


def test_nom_propre_au_code(referentiel: Referentiel) -> None:
    assert referentiel.nom("01039") == "Béon"
    assert referentiel.nom("01138") == "Culoz-Béon"
    assert referentiel.nom("75115") == "Paris 15e Arrondissement"
    assert referentiel.nom("99999") is None


def test_commune_actuelle(referentiel: Referentiel) -> None:
    commune = referentiel.commune("01039")
    assert commune is not None
    assert (commune.code, commune.nom, commune.departement) == ("01138", "Culoz-Béon", "01")


def test_codes_du_nom(referentiel: Referentiel) -> None:
    assert referentiel.codes_du_nom("Quimper") == {"29232"}
    assert referentiel.codes_du_nom("st malo") == {"35288"}
    # homonymes : Saint-Denis de La Réunion et de Seine-Saint-Denis
    assert referentiel.codes_du_nom("Saint-Denis") == {"97411", "93066"}
    assert referentiel.codes_du_nom("Saint-Denis", departement="974") == {"97411"}
    # une ancienne commune renvoie à la commune actuelle
    assert referentiel.codes_du_nom("Béon") == {"01138"}
    assert referentiel.codes_du_nom("Paris 15e Arrondissement") == {"75115"}
    assert referentiel.codes_du_nom("Nulle-Part") == set()


def test_noms_des_departements(referentiel: Referentiel) -> None:
    assert referentiel.departements["29"] == "Finistère"


class ReponseFactice(io.BytesIO):
    status = 200

    def __enter__(self) -> "ReponseFactice":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_telechargement_du_referentiel(tmp_path: Path) -> None:
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w:gz") as tar:
        for nom in ("communes.json", "departements.json"):
            contenu = (EXTRAIT / nom).read_bytes()
            info = tarfile.TarInfo(f"package/data/{nom}")
            info.size = len(contenu)
            tar.addfile(info, io.BytesIO(contenu))
    demandes: list[str] = []

    def ouvrir(requete: Request) -> ReponseFactice:
        demandes.append(requete.full_url)
        return ReponseFactice(tampon.getvalue())

    dossier = telecharger_referentiel(tmp_path / "communes", ouvrir=ouvrir)
    assert demandes and demandes[0].startswith("https://registry.npmjs.org/@etalab/")
    assert json.loads((dossier / "communes.json").read_text()) == json.loads(
        (EXTRAIT / "communes.json").read_text()
    )
    assert Referentiel.depuis_dossier(dossier).code_actuel("01039") == "01138"
