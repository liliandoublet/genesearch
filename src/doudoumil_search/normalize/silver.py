"""Étape silver : bronze → Parquet pivot dédoublonné et normalisé.

Pour chaque source présente en bronze (``bronze/<source>/<partition>/``) :

1. **Dédoublonnage** : un même acte peut figurer dans plusieurs partitions (fichier mensuel
   puis annuel). Pour chaque ``acte_id``, on garde la partition ingérée le plus récemment
   (à égalité, celle dont le nom est le plus grand), avec toutes ses mentions ; un doublon
   interne à une partition n'est gardé qu'une fois.
2. **Normalisation des mentions** : ``nom_norm``, ``nom_phonetique``, ``prenoms_norm`` et
   l'intervalle de naissance (règle R3). Les fonctions Python ne sont appelées qu'une fois par
   valeur distincte, puis le résultat est joint à la table : quelques millions de noms
   distincts au lieu de dizaines de millions de lignes.
3. **Lieux**, si le référentiel des communes est disponible : nom de la commune de l'acte, et
   code du lieu de naissance quand seul son nom est connu et qu'il désigne une seule commune.

Résultat : ``silver/<source>/actes.parquet`` et ``mentions.parquet``, écrits dans un dossier
temporaire puis publiés d'un bloc. La couche bronze n'est jamais modifiée.
"""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from doudoumil_search.normalize.dates import expressions_intervalle_naissance
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.noms import normaliser_nom
from doudoumil_search.normalize.phonetique import cle_phonetique
from doudoumil_search.normalize.prenoms import normaliser_prenoms
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS

journal = logging.getLogger(__name__)

PARTITION = "_partition"


@dataclass
class RapportSilver:
    source: str
    dossier: Path
    actes_bronze: int
    actes: int
    mentions: int

    @property
    def doublons(self) -> int:
        return self.actes_bronze - self.actes


def sources_bronze(bronze: Path) -> list[str]:
    """Sources qui ont au moins une partition ingérée."""
    if not bronze.exists():
        return []
    return sorted(
        dossier.name
        for dossier in bronze.iterdir()
        if dossier.is_dir() and any(dossier.glob("*/actes-*.parquet"))
    )


def _lire(dossier_source: Path, table: str, schema: pl.Schema) -> pl.LazyFrame:
    """Lit toutes les partitions d'une table, avec le nom de la partition de chaque ligne."""
    return (
        pl.scan_parquet(
            dossier_source / "*" / f"{table}-*.parquet",
            schema=schema,
            include_file_paths="_chemin",
        )
        .with_columns(pl.col("_chemin").str.extract(r"([^/\\]+)[/\\][^/\\]+$", 1).alias(PARTITION))
        .filter(
            # une ingestion tuée brutalement peut laisser une partition temporaire
            ~pl.col(PARTITION).str.ends_with(".en-cours")
        )
    )


def _table_de_correspondance(
    valeurs: pl.Series, fonctions: dict[str, Callable[[str], str | None]]
) -> pl.DataFrame:
    """Applique des fonctions à chaque valeur distincte ; une colonne par fonction."""
    distinctes = valeurs.drop_nulls().unique().to_list()
    colonnes: dict[str, list[str | None]] = {valeurs.name: distinctes}
    for nom, fonction in fonctions.items():
        colonnes[nom] = [fonction(v) for v in distinctes]
    return pl.DataFrame(
        colonnes, schema={valeurs.name: pl.String, **dict.fromkeys(fonctions, pl.String)}
    )


def construire_source(
    bronze: Path, silver: Path, source: str, referentiel: Referentiel | None = None
) -> RapportSilver:
    """Construit la couche silver d'une source."""
    actes = _lire(bronze / source, "actes", SCHEMA_ACTES)
    mentions = _lire(bronze / source, "mentions", SCHEMA_MENTIONS)

    # 1. dédoublonnage : la partition retenue pour chaque acte
    retenues = (
        actes.select("acte_id", "ingested_at", PARTITION)
        .sort(["ingested_at", PARTITION])
        .unique(subset="acte_id", keep="last")
        .select("acte_id", PARTITION)
    )
    # Un doublon peut aussi se trouver dans une même partition (ligne répétée dans un fichier) :
    # les deux lignes ne diffèrent alors que par leur position, et l'une ou l'autre convient.
    actes = actes.join(retenues, on=["acte_id", PARTITION], how="semi").unique(
        subset="acte_id", keep="any"
    )
    mentions = mentions.join(retenues, on=["acte_id", PARTITION], how="semi").unique(
        subset="mention_id", keep="any"
    )
    actes_bronze = _lire(bronze / source, "actes", SCHEMA_ACTES).select(pl.len())

    # 2. noms, prénoms et clés phonétiques, calculés une fois par valeur distincte
    noms = _table_de_correspondance(
        mentions.select("nom_brut").collect().to_series(), {"_nom_norm": normaliser_nom}
    )
    noms = noms.with_columns(
        pl.col("_nom_norm")
        .map_elements(cle_phonetique, return_dtype=pl.String, skip_nulls=True)
        .alias("_nom_phonetique")
    )
    prenoms = _table_de_correspondance(
        mentions.select("prenoms_bruts").collect().to_series(),
        {"_prenoms_norm": normaliser_prenoms},
    )
    annees_actes = actes.select("acte_id", pl.col("annee").alias("_annee_acte"))
    mini, maxi = expressions_intervalle_naissance(pl.col("_annee_acte"))
    mentions = (
        mentions.join(noms.lazy(), on="nom_brut", how="left")
        .join(prenoms.lazy(), on="prenoms_bruts", how="left")
        .join(annees_actes, on="acte_id", how="left")
        .with_columns(
            pl.col("_nom_norm").alias("nom_norm"),
            pl.col("_nom_phonetique").alias("nom_phonetique"),
            pl.col("_prenoms_norm").alias("prenoms_norm"),
            mini,
            maxi,
        )
    )

    # 3. lieux
    if referentiel is not None:
        actes, mentions = _completer_lieux(actes, mentions, referentiel)

    dossier = silver / source
    temporaire = dossier.with_name(dossier.name + ".en-cours")
    if temporaire.exists():
        shutil.rmtree(temporaire)
    temporaire.mkdir(parents=True)
    actes.select(SCHEMA_ACTES.names()).cast(dict(SCHEMA_ACTES)).sink_parquet(
        temporaire / "actes.parquet"
    )
    mentions.select(SCHEMA_MENTIONS.names()).cast(dict(SCHEMA_MENTIONS)).sink_parquet(
        temporaire / "mentions.parquet"
    )
    if dossier.exists():
        shutil.rmtree(dossier)
    temporaire.rename(dossier)

    rapport = RapportSilver(
        source=source,
        dossier=dossier,
        actes_bronze=actes_bronze.collect().item(),
        actes=pl.scan_parquet(dossier / "actes.parquet").select(pl.len()).collect().item(),
        mentions=pl.scan_parquet(dossier / "mentions.parquet").select(pl.len()).collect().item(),
    )
    journal.info(
        "%s : %d actes (%d doublons écartés), %d mentions",
        source,
        rapport.actes,
        rapport.doublons,
        rapport.mentions,
    )
    return rapport


def _completer_lieux(
    actes: pl.LazyFrame, mentions: pl.LazyFrame, referentiel: Referentiel
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Nom de la commune de l'acte ; code du lieu de naissance déduit d'un nom sans ambiguïté."""
    communes = _table_de_correspondance(
        actes.select("commune_code_insee").collect().to_series(), {"_libelle": referentiel.nom}
    )
    actes = actes.join(communes.lazy(), on="commune_code_insee", how="left").with_columns(
        pl.coalesce("commune_label", "_libelle").alias("commune_label")
    )

    def code_unique(nom: str) -> str | None:
        codes = referentiel.codes_du_nom(nom)
        return next(iter(codes)) if len(codes) == 1 else None

    sans_code = (
        mentions.filter(pl.col("lieu_naissance_code_insee").is_null())
        .select("lieu_naissance_brut")
        .collect()
        .to_series()
    )
    lieux = _table_de_correspondance(sans_code, {"_code_deduit": code_unique})
    mentions = mentions.join(lieux.lazy(), on="lieu_naissance_brut", how="left").with_columns(
        pl.coalesce("lieu_naissance_code_insee", "_code_deduit").alias("lieu_naissance_code_insee")
    )
    return actes, mentions


def construire_silver(
    bronze: Path,
    silver: Path,
    referentiel: Referentiel | None = None,
    sources: list[str] | None = None,
) -> list[RapportSilver]:
    """Construit la couche silver de toutes les sources (ou de celles demandées)."""
    return [
        construire_source(bronze, silver, source, referentiel)
        for source in (sources or sources_bronze(bronze))
    ]
