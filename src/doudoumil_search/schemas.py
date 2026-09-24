"""Schémas Parquet des tables pivot ``actes`` et ``mentions``.

Les énumérations sont stockées en ``String`` plutôt qu'en ``pl.Enum`` : le Parquet reste
lisible tel quel par DuckDB et par tout autre outil, et la validation des valeurs relève du
modèle Pydantic (voir :mod:`doudoumil_search.pivot`).
"""

from collections.abc import Iterable

import polars as pl
from pydantic import BaseModel

SCHEMA_ACTES = pl.Schema(
    {
        "acte_id": pl.String,
        "source": pl.String,
        "type": pl.String,
        "annee": pl.Int16,
        "date_acte": pl.Date,
        "commune_code_insee": pl.String,
        "commune_label": pl.String,
        "departement": pl.String,
        "depot": pl.String,
        "cote": pl.String,
        "vue": pl.String,
        "url_image": pl.String,
        "ingested_at": pl.Datetime("us", "UTC"),
    }
)

SCHEMA_MENTIONS = pl.Schema(
    {
        "mention_id": pl.String,
        "acte_id": pl.String,
        "role": pl.String,
        "nom_brut": pl.String,
        "prenoms_bruts": pl.String,
        "nom_norm": pl.String,
        "nom_phonetique": pl.String,
        "prenoms_norm": pl.String,
        "sexe": pl.String,
        "date_naissance": pl.Date,
        "age": pl.Int16,
        "profession": pl.String,
        "lieu_naissance_brut": pl.String,
        "lieu_naissance_code_insee": pl.String,
        "confiance_source": pl.Float32,
    }
)


def vers_dataframe(modeles: Iterable[BaseModel], schema: pl.Schema) -> pl.DataFrame:
    """Convertit des modèles pivot en DataFrame conforme au schéma Parquet.

    Les ``StrEnum`` héritant de ``str``, elles passent telles quelles en colonnes ``String``.
    """
    return pl.DataFrame([m.model_dump() for m in modeles], schema=schema)
