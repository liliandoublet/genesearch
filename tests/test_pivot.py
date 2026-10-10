"""Tests du modèle pivot : validation des champs et identifiants déterministes."""

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from doudoumil_search.pivot import (
    Acte,
    Mention,
    NatureNom,
    Role,
    Source,
    TypeActe,
    fabriquer_id,
)


def test_acte_valide(acte_valide: dict[str, Any]) -> None:
    acte = Acte(**acte_valide)
    assert acte.type is TypeActe.DECES
    assert acte.source is Source.INSEE_DECES


def test_mention_valide(mention_valide: dict[str, Any]) -> None:
    mention = Mention(**mention_valide)
    assert mention.role is Role.SUJET


def test_mention_minimale() -> None:
    """Seuls l'identifiant, l'acte et le rôle sont obligatoires."""
    id_ = fabriquer_id(Source.SOCFACE, "x")
    mention = Mention(mention_id=id_, acte_id=id_, role="temoin")
    assert mention.nom_brut is None


def test_enumerations_depuis_chaines(acte_valide: dict[str, Any]) -> None:
    acte = Acte(**{**acte_valide, "type": "recensement", "source": "socface"})
    assert acte.type is TypeActe.RECENSEMENT
    assert acte.source is Source.SOCFACE


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [("type", "divorce"), ("source", "filae")],
)
def test_enumeration_inconnue_rejetee(acte_valide: dict[str, Any], champ: str, valeur: str) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, champ: valeur})


def test_role_inconnu_rejete(mention_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Mention(**{**mention_valide, "role": "parrain"})


@pytest.mark.parametrize("annee", [1500, 1836, 2100])
def test_annee_bornes_acceptees(acte_valide: dict[str, Any], annee: int) -> None:
    assert Acte(**{**acte_valide, "annee": annee}).annee == annee


@pytest.mark.parametrize("annee", [1499, 2101])
def test_annee_hors_bornes(acte_valide: dict[str, Any], annee: int) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, "annee": annee})


@pytest.mark.parametrize(("champ", "valeur"), [("age", -1), ("age", 131)])
def test_age_hors_bornes(mention_valide: dict[str, Any], champ: str, valeur: int) -> None:
    with pytest.raises(ValidationError):
        Mention(**{**mention_valide, champ: valeur})


@pytest.mark.parametrize("valeur", [-0.01, 1.01])
def test_confiance_hors_bornes(mention_valide: dict[str, Any], valeur: float) -> None:
    with pytest.raises(ValidationError):
        Mention(**{**mention_valide, "confiance_source": valeur})


@pytest.mark.parametrize("code", ["35238", "2A004", "2B033", "97411", "99100", "01001"])
def test_code_insee_valide(acte_valide: dict[str, Any], code: str) -> None:
    assert Acte(**{**acte_valide, "commune_code_insee": code}).commune_code_insee == code


@pytest.mark.parametrize("code", ["3523", "352380", "2C004", "AB123", "35 238", "2a004"])
def test_code_insee_invalide(acte_valide: dict[str, Any], code: str) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, "commune_code_insee": code})


def test_code_insee_lieu_naissance_invalide(mention_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Mention(**{**mention_valide, "lieu_naissance_code_insee": "2C004"})


@pytest.mark.parametrize("dep", ["01", "35", "2A", "2B", "971", "976", "977", "988", "99"])
def test_departement_valide(acte_valide: dict[str, Any], dep: str) -> None:
    assert Acte(**{**acte_valide, "departement": dep}).departement == dep


@pytest.mark.parametrize("dep", ["1", "979", "983", "2C", "350"])
def test_departement_invalide(acte_valide: dict[str, Any], dep: str) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, "departement": dep})


def test_ingested_at_naif_rejete(acte_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="fuseau"):
        Acte(**{**acte_valide, "ingested_at": datetime(2026, 9, 24, 12, 0)})


def test_identifiant_mal_forme_rejete(acte_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, "acte_id": "pas-un-hash"})


def test_champ_inconnu_rejete(acte_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Acte(**{**acte_valide, "adresse": "12 rue de la Paix"})


def test_modele_immuable(acte_valide: dict[str, Any]) -> None:
    acte = Acte(**acte_valide)
    with pytest.raises(ValidationError):
        acte.annee = 1900  # type: ignore[misc]


def test_champs_bruts_non_transformes(mention_valide: dict[str, Any]) -> None:
    """Les valeurs brutes, espaces et casse compris, sont conservées à l'identique."""
    brut = "  de LA  Tour-d'Auvergne "
    assert Mention(**{**mention_valide, "nom_brut": brut}).nom_brut == brut


def test_fabriquer_id_stable() -> None:
    a = fabriquer_id(Source.INSEE_DECES, "fichier.txt", "1")
    b = fabriquer_id(Source.INSEE_DECES, "fichier.txt", "1")
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_fabriquer_id_valeur_de_reference() -> None:
    """Fige l'algorithme : un changement casserait tous les identifiants déjà produits."""
    assert fabriquer_id(Source.INSEE_DECES, "fichier.txt", "1") == (
        "876b6b27ade5e9615f1ce8e44d7676c8"
    )


def test_fabriquer_id_distingue_les_cles() -> None:
    ids = {
        fabriquer_id(Source.INSEE_DECES, "fichier.txt", "1"),
        fabriquer_id(Source.INSEE_DECES, "fichier.txt", "2"),
        fabriquer_id(Source.SOCFACE, "fichier.txt", "1"),
        # même concaténation naïve que ("ab", "c") : le séparateur doit les distinguer
        fabriquer_id(Source.INSEE_DECES, "a", "bc"),
        fabriquer_id(Source.INSEE_DECES, "ab", "c"),
    }
    assert len(ids) == 5


def test_fabriquer_id_cle_vide() -> None:
    with pytest.raises(ValueError, match="vide"):
        fabriquer_id(Source.INSEE_DECES)


def test_nature_nom(mention_valide: dict[str, Any]) -> None:
    mention = Mention(**{**mention_valide, "nature_nom": "marital"})
    assert mention.nature_nom is NatureNom.MARITAL


def test_nature_nom_inconnue_rejetee(mention_valide: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Mention(**{**mention_valide, "nature_nom": "usage"})


def test_date_naissance_brute_conservee(mention_valide: dict[str, Any]) -> None:
    """Une date partielle reste lisible telle quelle, sans date complète associée."""
    mention = Mention(
        **{**mention_valide, "date_naissance_brute": "19310300", "date_naissance": None}
    )
    assert mention.date_naissance_brute == "19310300"
    assert mention.date_naissance is None


@pytest.mark.parametrize(("mini", "maxi"), [(1931, 1931), (1880, 1881), (1300, 2100)])
def test_intervalle_naissance_valide(mention_valide: dict[str, Any], mini: int, maxi: int) -> None:
    champs = {"annee_naissance_min": mini, "annee_naissance_max": maxi}
    mention = Mention(**{**mention_valide, **champs})
    assert (mention.annee_naissance_min, mention.annee_naissance_max) == (mini, maxi)


@pytest.mark.parametrize(
    ("mini", "maxi", "message"),
    [
        (1882, 1881, "inférieure"),
        (1880, None, "ensemble"),
        (None, 1880, "ensemble"),
        (1299, 1300, None),
        (2100, 2101, None),
    ],
)
def test_intervalle_naissance_invalide(
    mention_valide: dict[str, Any], mini: int | None, maxi: int | None, message: str | None
) -> None:
    champs = {"annee_naissance_min": mini, "annee_naissance_max": maxi}
    with pytest.raises(ValidationError, match=message):
        Mention(**{**mention_valide, **champs})
