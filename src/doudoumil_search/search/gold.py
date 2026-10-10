"""Construction de la base gold : une base DuckDB prête pour la recherche.

Tables, construites depuis toutes les sources de la couche silver :

``actes``, ``mentions``
    Les tables pivot telles quelles, pour l'affichage des fiches.
``personnes``
    Une ligne par mention, avec les champs de l'acte utiles à la recherche et les codes de
    lieux ramenés à la commune actuelle. Triée par clé phonétique : DuckDB saute alors les
    blocs qui ne contiennent pas la clé cherchée (canal A).
``prenoms``
    Un prénom par ligne, avec son rang et sa clé phonétique (canal C).
``noms``
    Les noms normalisés distincts et leur nombre d'occurrences (canal B).
``calibration``
    Table de calibration du score, par source (règle R5), vide tant que
    ``doudoumil calibre`` n'a pas été lancé.
``meta``
    Date de construction, version du schéma, sources présentes.

La base est construite dans un fichier temporaire puis remplace l'ancienne d'un bloc ; la
calibration existante est conservée.
"""

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import duckdb
import polars as pl

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.phonetique import cle_phonetique

journal = logging.getLogger(__name__)

NOM_BASE: Final = "recherche.duckdb"
VERSION_SCHEMA: Final = "1"


@dataclass
class RapportGold:
    chemin: Path
    sources: list[str]
    personnes: int
    noms_distincts: int


def chemin_base(gold: Path) -> Path:
    return gold / NOM_BASE


def _sources_silver(silver: Path) -> list[str]:
    if not silver.exists():
        return []
    return sorted(
        d.name for d in silver.iterdir() if d.is_dir() and (d / "mentions.parquet").exists()
    )


def _correspondance(valeurs: list[str], fonction: Callable[[str], str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {"valeur": valeurs, "resultat": [fonction(v) for v in valeurs]},
        schema={"valeur": pl.String, "resultat": pl.String},
    )


def _creer_table(base: duckdb.DuckDBPyConnection, nom: str, table: pl.DataFrame) -> None:
    """Crée une table temporaire DuckDB depuis une table Polars, via un fichier Parquet.

    Passer par un fichier évite la dépendance à pyarrow qu'exigerait l'échange direct.
    """
    with tempfile.TemporaryDirectory(prefix="doudoumil-") as dossier:
        chemin = Path(dossier) / f"{nom}.parquet"
        table.write_parquet(chemin)
        base.execute(f"CREATE TEMP TABLE {nom} AS SELECT * FROM read_parquet(?)", [str(chemin)])


def construire_gold(
    silver: Path, gold: Path, referentiel: Referentiel | None = None
) -> RapportGold:
    """Construit ``gold/recherche.duckdb`` depuis toutes les sources silver."""
    sources = _sources_silver(silver)
    if not sources:
        raise FileNotFoundError(f"aucune source dans {silver} : lancez « doudoumil normalize »")
    gold.mkdir(parents=True, exist_ok=True)
    final = chemin_base(gold)
    temporaire = final.with_name(final.name + ".en-cours")
    temporaire.unlink(missing_ok=True)

    actes = [str(silver / s / "actes.parquet") for s in sources]
    mentions = [str(silver / s / "mentions.parquet") for s in sources]
    with duckdb.connect(str(temporaire)) as base:
        base.execute("CREATE TABLE actes AS SELECT * FROM read_parquet(?)", [actes])
        base.execute("CREATE TABLE mentions AS SELECT * FROM read_parquet(?)", [mentions])
        _table_lieux(base, referentiel)
        base.execute(_SQL_PERSONNES)
        _table_prenoms(base)
        base.execute(_SQL_NOMS)
        # lecture des fiches des résultats retenus sans parcourir les tables entières
        base.execute("CREATE INDEX index_mentions ON mentions (mention_id)")
        base.execute("CREATE INDEX index_actes ON actes (acte_id)")
        _copier_calibration(base, final)
        base.execute("CREATE TABLE meta (cle VARCHAR PRIMARY KEY, valeur VARCHAR)")
        base.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("version_schema", VERSION_SCHEMA),
                ("construite_le", datetime.now(UTC).isoformat(timespec="seconds")),
                ("sources", ",".join(sources)),
            ],
        )
        personnes = base.execute("SELECT count(*) FROM personnes").fetchone()
        noms = base.execute("SELECT count(*) FROM noms").fetchone()
    temporaire.replace(final)
    rapport = RapportGold(
        chemin=final,
        sources=sources,
        personnes=personnes[0] if personnes else 0,
        noms_distincts=noms[0] if noms else 0,
    )
    journal.info(
        "base gold : %d personnes, %d noms distincts", rapport.personnes, rapport.noms_distincts
    )
    return rapport


def _table_lieux(base: duckdb.DuckDBPyConnection, referentiel: Referentiel | None) -> None:
    """Table ``lieux`` : code présent dans les données → commune actuelle et département."""
    codes = base.execute(
        """
        SELECT DISTINCT code FROM (
            SELECT commune_code_insee AS code FROM actes
            UNION ALL SELECT lieu_naissance_code_insee FROM mentions
        ) WHERE code IS NOT NULL
        """
    ).fetchall()
    valeurs = [c[0] for c in codes]

    def actuel(code: str) -> str | None:
        return referentiel.code_actuel(code) if referentiel else None

    def departement(code: str) -> str | None:
        commune = referentiel.commune(code) if referentiel else None
        if commune:
            return commune.departement
        return code[:3] if code.startswith(("97", "98")) else code[:2]

    lieux = _correspondance(valeurs, actuel).rename({"valeur": "code", "resultat": "actuel"})
    lieux = lieux.with_columns(
        pl.Series("departement", [departement(c) for c in valeurs], dtype=pl.String)
    )
    _creer_table(base, "lieux_calcules", lieux)
    base.execute(
        """
        CREATE TABLE lieux AS
        SELECT code, coalesce(actuel, code) AS actuel, departement FROM lieux_calcules
        """
    )


_SQL_PERSONNES: Final = """
CREATE TABLE personnes AS
SELECT
    m.mention_id, m.acte_id, a.source, a.type, a.annee, a.date_acte, m.role,
    m.nom_norm, m.nom_phonetique, m.prenoms_norm, m.nature_nom, m.sexe,
    m.annee_naissance_min, m.annee_naissance_max,
    a.commune_code_insee,
    ld.actuel AS commune_actuelle,
    coalesce(ld.departement, a.departement) AS departement,
    m.lieu_naissance_code_insee,
    ln.actuel AS naissance_actuelle,
    ln.departement AS naissance_departement,
    coalesce(m.confiance_source, 1.0) AS confiance_source
FROM mentions m
JOIN actes a USING (acte_id)
LEFT JOIN lieux ld ON ld.code = a.commune_code_insee
LEFT JOIN lieux ln ON ln.code = m.lieu_naissance_code_insee
ORDER BY m.nom_phonetique, m.nom_norm
"""

_SQL_NOMS: Final = """
CREATE TABLE noms AS
SELECT nom_norm, length(nom_norm) AS longueur, count(*) AS occurrences
FROM personnes
WHERE nom_norm IS NOT NULL
GROUP BY nom_norm
ORDER BY longueur, nom_norm
"""


def _table_prenoms(base: duckdb.DuckDBPyConnection) -> None:
    """Un prénom par ligne et sa clé phonétique, calculée une fois par prénom distinct."""
    base.execute(
        """
        CREATE TEMP TABLE prenoms_eclates AS
        SELECT mention_id, rang::SMALLINT AS rang, prenom
        FROM (
            SELECT mention_id, unnest(string_split(prenoms_norm, ' ')) AS prenom,
                   generate_subscripts(string_split(prenoms_norm, ' '), 1) AS rang
            FROM personnes
            WHERE prenoms_norm IS NOT NULL
        )
        """
    )
    distincts = [
        r[0] for r in base.execute("SELECT DISTINCT prenom FROM prenoms_eclates").fetchall()
    ]
    cles = _correspondance(distincts, cle_phonetique)
    _creer_table(base, "cles_prenoms", cles)
    base.execute(
        """
        CREATE TABLE prenoms AS
        SELECT e.mention_id, e.rang, e.prenom, c.resultat AS cle
        FROM prenoms_eclates e JOIN cles_prenoms c ON c.valeur = e.prenom
        ORDER BY cle
        """
    )


def _copier_calibration(base: duckdb.DuckDBPyConnection, ancienne: Path) -> None:
    """Crée la table de calibration, en reprenant celle de l'ancienne base si elle existe."""
    base.execute("CREATE TABLE calibration (source VARCHAR, score DOUBLE, probabilite DOUBLE)")
    if not ancienne.exists():
        return
    try:
        chemin = str(ancienne).replace("'", "''")
        base.execute(f"ATTACH '{chemin}' AS ancienne (READ_ONLY)")
        base.execute("INSERT INTO calibration SELECT * FROM ancienne.calibration")
        base.execute("DETACH ancienne")
    except duckdb.Error as erreur:
        journal.warning("calibration précédente non reprise : %s", erreur)
