# doudoumil-search

Moteur de recherche généalogique personnel, fonctionnant entièrement en local. Il indexe des
notices nominatives issues d'archives françaises et les interroge avec tolérance aux variantes
orthographiques. Il les rapproche ensuite des individus d'un arbre GEDCOM.

La recherche approchée est le cas nominal : les sources transcrites automatiquement (par
exemple les recensements Socface) ont un taux d'erreur de 15 à 20 %. Chaque résultat porte un
niveau de confiance, et chaque notice garde sa provenance (cote, vue, URL).

La feuille de route est dans [`PLAN.md`](PLAN.md).

## Prérequis

- [uv](https://docs.astral.sh/uv/) ≥ 0.4
- Python 3.11 (uv l'installe si besoin : `uv python install 3.11`)

## Installation

```bash
uv sync
```

## Vérifications

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

## Modèle pivot

Toutes les sources sont ramenées à deux tables, définies dans
`src/doudoumil_search/pivot.py` (validation Pydantic) et `src/doudoumil_search/schemas.py`
(schémas Parquet) :

- `actes` : le document d'archive et sa provenance (`source`, `depot`, `cote`, `vue`,
  `url_image`) ;
- `mentions` : les personnes citées dans l'acte avec leur rôle (sujet, père, mère, témoin…).

Les identifiants `acte_id` et `mention_id` sont des empreintes déterministes de la source et
de la ligne d'origine. Réingérer un fichier redonne donc les mêmes identifiants.

## Couches de données

Tout est écrit sous `data/`, qui n'est pas versionné :

| couche | contenu |
|---|---|
| `data/bronze/` | fichiers sources tels que téléchargés, et leur conversion au format pivot sans normalisation |
| `data/silver/` | Parquet pivot avec les champs normalisés (`nom_norm`, `nom_phonetique`…) |
| `data/gold/` | base DuckDB indexée pour la recherche |

Une couche ne modifie jamais la précédente : chaque étape produit de nouveaux fichiers.

## Démonstration (jalon 1)

```bash
uv run python -c "from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS; print(SCHEMA_ACTES); print(SCHEMA_MENTIONS)"
```

## Arborescence

```
src/doudoumil_search/
├── pivot.py        # modèle pivot (Acte, Mention) et fabriquer_id()
├── schemas.py      # schémas Parquet
├── ingest/         # connecteurs INSEE décès, Socface
├── normalize/      # normalisation des noms et des lieux
├── search/         # moteur de recherche DuckDB
├── api/            # API FastAPI
└── linkage/        # rapprochement avec l'arbre GEDCOM
tests/
notebooks/          # exploration de la qualité des sources
```
