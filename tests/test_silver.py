"""Tests de l'étape silver : dédoublonnage, normalisation, lieux, conformité au pivot."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from doudoumil_search.ingest.insee_deces import ingerer_fichier
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.silver import construire_silver, sources_bronze
from doudoumil_search.pivot import Acte, Mention
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS
from fabrique_insee import ligne_insee

FIXTURE = Path(__file__).parent / "fixtures" / "deces-extrait.txt"
EXTRAIT_COMMUNES = Path(__file__).parent / "fixtures" / "communes"
INGESTION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def bronze(tmp_path: Path) -> Path:
    dossier = tmp_path / "bronze"
    ingerer_fichier(FIXTURE, dossier, ingested_at=INGESTION)
    return dossier


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT_COMMUNES)


def _lire(silver: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    return (
        pl.read_parquet(silver / "insee_deces" / "actes.parquet"),
        pl.read_parquet(silver / "insee_deces" / "mentions.parquet"),
    )


def test_sources_bronze(bronze: Path) -> None:
    (bronze / "insee_deces" / "telechargements").mkdir()
    assert sources_bronze(bronze) == ["insee_deces"]
    assert sources_bronze(bronze.parent / "absent") == []


def test_silver_dedoublonne_et_normalise(bronze: Path, tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    (rapport,) = construire_silver(bronze, silver)
    assert (rapport.actes_bronze, rapport.actes, rapport.doublons) == (8, 7, 1)
    assert rapport.mentions == 7

    actes, mentions = _lire(silver)
    assert actes.schema == SCHEMA_ACTES
    assert mentions.schema == SCHEMA_MENTIONS
    assert actes["acte_id"].is_unique().all()
    assert mentions["mention_id"].is_unique().all()

    le_goff = mentions.filter(pl.col("nom_brut") == "LE GOFF").row(0, named=True)
    assert le_goff["nom_norm"] == "LE GOFF"
    assert le_goff["nom_phonetique"] == "LKF"
    assert le_goff["prenoms_norm"] == "MARIE JOSEPHE"
    assert (le_goff["annee_naissance_min"], le_goff["annee_naissance_max"]) == (1931, 1931)

    # date de naissance partielle : l'année est retrouvée depuis la date brute
    kergoat = mentions.filter(pl.col("nom_brut") == "KERGOAT").row(0, named=True)
    assert kergoat["date_naissance"] is None
    assert (kergoat["annee_naissance_min"], kergoat["annee_naissance_max"]) == (1919, 1919)

    payet = mentions.filter(pl.col("nom_brut") == "PAYET").row(0, named=True)
    assert payet["prenoms_norm"] == "LOUISE ANDREE"
    # sans référentiel, les lieux restent tels quels
    assert actes["commune_label"].null_count() == actes.height


def test_silver_conforme_au_modele_pivot(bronze: Path, tmp_path: Path) -> None:
    construire_silver(bronze, tmp_path / "silver")
    actes, mentions = _lire(tmp_path / "silver")
    for ligne in actes.iter_rows(named=True):
        Acte.model_validate(ligne)
    for ligne in mentions.iter_rows(named=True):
        Mention.model_validate(ligne)


def test_silver_avec_referentiel(bronze: Path, tmp_path: Path, referentiel: Referentiel) -> None:
    construire_silver(bronze, tmp_path / "silver", referentiel)
    actes, mentions = _lire(tmp_path / "silver")
    libelles = dict(actes.select("commune_code_insee", "commune_label").iter_rows())
    assert libelles["35238"] == "Rennes"
    assert libelles["75115"] == "Paris 15e Arrondissement"
    # PETIT : code de naissance invalide et lieu « INCONNUE » introuvable → reste vide
    petit = mentions.filter(pl.col("nom_brut") == "PETIT").row(0, named=True)
    assert petit["lieu_naissance_code_insee"] is None


def test_code_de_naissance_deduit_d_un_nom_unique(tmp_path: Path, referentiel: Referentiel) -> None:
    fichier = tmp_path / "deces-2021.txt"
    fichier.write_text(
        "\n".join(
            [
                ligne_insee(code_lieu_naissance="", commune_naissance="QUIMPER", numero_acte="1"),
                # Saint-Denis : deux communes homonymes, aucun code déduit
                ligne_insee(
                    code_lieu_naissance="", commune_naissance="SAINT-DENIS", numero_acte="2"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ingerer_fichier(fichier, tmp_path / "bronze", ingested_at=INGESTION)
    construire_silver(tmp_path / "bronze", tmp_path / "silver", referentiel)
    _, mentions = _lire(tmp_path / "silver")
    codes = dict(mentions.select("lieu_naissance_brut", "lieu_naissance_code_insee").iter_rows())
    assert codes == {"QUIMPER": "29232", "SAINT-DENIS": None}


def test_le_fichier_le_plus_recent_l_emporte(tmp_path: Path) -> None:
    """Un décès corrigé dans un fichier plus récent remplace l'ancienne version."""
    bronze = tmp_path / "bronze"
    ancien = tmp_path / "deces-2020-m01.txt"
    ancien.write_text(ligne_insee(nom_prenoms="LE GOF*MARIE/") + "\n", encoding="utf-8")
    recent = tmp_path / "deces-2020.txt"
    recent.write_text(ligne_insee(nom_prenoms="LE GOFF*MARIE/") + "\n", encoding="utf-8")
    ingerer_fichier(ancien, bronze, ingested_at=datetime(2020, 2, 1, tzinfo=UTC))
    ingerer_fichier(recent, bronze, ingested_at=datetime(2021, 1, 15, tzinfo=UTC))

    (rapport,) = construire_silver(bronze, tmp_path / "silver")
    assert (rapport.actes, rapport.doublons) == (1, 1)
    actes, mentions = _lire(tmp_path / "silver")
    assert actes["cote"].item() == "deces-2020.txt"
    assert mentions["nom_brut"].item() == "LE GOFF"


def test_partition_temporaire_ignoree(bronze: Path, tmp_path: Path) -> None:
    """Une ingestion tuée en cours de route ne doit pas polluer silver."""
    restes = bronze / "insee_deces" / "deces-extrait.en-cours"
    restes.mkdir()
    for table in ("actes", "mentions"):
        source = next((bronze / "insee_deces" / "deces-extrait").glob(f"{table}-*.parquet"))
        (restes / source.name).write_bytes(source.read_bytes())
    (rapport,) = construire_silver(bronze, tmp_path / "silver")
    assert rapport.actes_bronze == 8


def test_bronze_intact(bronze: Path, tmp_path: Path) -> None:
    avant = {p: p.read_bytes() for p in bronze.rglob("*") if p.is_file()}
    construire_silver(bronze, tmp_path / "silver")
    apres = {p: p.read_bytes() for p in bronze.rglob("*") if p.is_file()}
    assert avant == apres
