"""Tests du carnet de trouvailles (base SQLite personnelle)."""

from pathlib import Path

import pytest

from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.search.requete import Requete


@pytest.fixture
def carnet(tmp_path: Path) -> Carnet:
    return Carnet(tmp_path / "perso" / "trouvailles.sqlite")


def test_creation_puis_mises_a_jour_independantes(carnet: Carnet) -> None:
    carnet.enregistrer("m1", "a1", "LE GOFF Marie", source="insee_deces", favori=True)
    carnet.enregistrer("m1", "a1", "LE GOFF Marie", note="née à Quimper")
    trouvaille = carnet.lire("m1")
    assert trouvaille is not None
    assert (trouvaille.favori, trouvaille.note, trouvaille.verdict) == (True, "née à Quimper", None)
    assert trouvaille.source == "insee_deces"


def test_verdict_garde_la_requete(carnet: Carnet) -> None:
    requete = Requete.creer(nom="LE GOFF", prenoms="Marie", naissance=(1931, 1931))
    carnet.enregistrer("m1", "a1", "x", requete=requete, verdict="oui")
    assert carnet.verdicts()[0].requete == requete
    carnet.enregistrer("m1", "a1", "x", effacer_verdict=True)
    assert carnet.verdicts() == []


def test_verdict_inconnu(carnet: Carnet) -> None:
    with pytest.raises(ValueError, match="verdict"):
        carnet.enregistrer("m1", "a1", "x", verdict="peut-être")


def test_verdict_sans_requete_inutilisable_pour_calibrer(carnet: Carnet) -> None:
    carnet.enregistrer("m1", "a1", "x", verdict="non")
    assert carnet.lire("m1").verdict == "non"  # type: ignore[union-attr]
    assert carnet.verdicts() == []


def test_parmi_toutes_et_suppression(carnet: Carnet) -> None:
    carnet.enregistrer("m1", "a1", "un", favori=True)
    carnet.enregistrer("m2", "a2", "deux", note="n")
    assert set(carnet.parmi(["m1", "m3"])) == {"m1"}
    assert carnet.parmi([]) == {}
    assert [t.mention_id for t in carnet.toutes()] == ["m1", "m2"]  # favoris d'abord
    carnet.supprimer("m1")
    assert carnet.lire("m1") is None


def test_persistance(tmp_path: Path) -> None:
    chemin = tmp_path / "trouvailles.sqlite"
    Carnet(chemin).enregistrer("m1", "a1", "x", note="gardée")
    assert Carnet(chemin).lire("m1").note == "gardée"  # type: ignore[union-attr]
