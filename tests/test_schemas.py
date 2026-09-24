"""Tests des schémas Parquet : cohérence avec le modèle pivot et aller-retour sur disque."""

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from pydantic import BaseModel

from doudoumil_search.pivot import Acte, Mention
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS, vers_dataframe


@pytest.mark.parametrize(("modele", "schema"), [(Acte, SCHEMA_ACTES), (Mention, SCHEMA_MENTIONS)])
def test_colonnes_identiques_au_modele(modele: type[BaseModel], schema: pl.Schema) -> None:
    """Même noms, même ordre : un champ ajouté d'un côté seulement doit faire échouer."""
    assert list(modele.model_fields) == schema.names()


def test_aller_retour_parquet(
    tmp_path: Path, acte_valide: dict[str, Any], mention_valide: dict[str, Any]
) -> None:
    acte = Acte(**acte_valide)
    mention = Mention(**mention_valide)
    for modele, schema, nom in [
        (acte, SCHEMA_ACTES, "actes.parquet"),
        (mention, SCHEMA_MENTIONS, "mentions.parquet"),
    ]:
        chemin = tmp_path / nom
        vers_dataframe([modele], schema).write_parquet(chemin)
        relu = pl.read_parquet(chemin)
        assert relu.schema == schema
        # Le modèle reconstruit depuis le Parquet est identique à l'original.
        assert type(modele).model_validate(relu.row(0, named=True)) == modele


def test_dataframe_vide_garde_le_schema() -> None:
    assert vers_dataframe([], SCHEMA_ACTES).schema == SCHEMA_ACTES
