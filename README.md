# doudoumil-search

Moteur de recherche généalogique personnel, fonctionnant entièrement en local. Il indexe des
notices nominatives issues d'archives françaises et les interroge avec tolérance aux variantes
orthographiques. En option, il les rapproche des individus d'un arbre GEDCOM.

La recherche approchée est le cas nominal : les sources transcrites automatiquement (par
exemple les recensements Socface) ont un taux d'erreur de 15 à 20 %. Chaque résultat porte un
niveau de confiance, et chaque notice garde sa provenance (cote, vue, URL).

Objectif : remplacer Filae pour un usage personnel (recherche nominative, recensements
transcrits, images des actes). La feuille de route est dans [`PLAN.md`](PLAN.md).

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

## Démonstration

### Jalon 2 — ingestion INSEE décès

```bash
uv run doudoumil telecharge insee --annees 2019-2020   # fichiers dans data/bronze/insee_deces/telechargements/
uv run doudoumil ingest insee --processus 4            # Parquet pivot dans data/bronze/insee_deces/<fichier>/

# sans téléchargement, sur le fichier d'exemple (personnes inventées) :
uv run doudoumil ingest insee tests/fixtures/deces-extrait.txt
uv run python -c "import polars as pl; print(pl.read_parquet('data/bronze/insee_deces/deces-extrait/mentions-*.parquet'))"
```

Chaque partition contient aussi `rejets.csv`, la liste des lignes écartées et leur motif.

### Jalon 3 — normalisation (couche silver)

```bash
uv run doudoumil telecharge communes   # référentiel des communes dans data/ref/communes/
uv run doudoumil normalize             # Parquet normalisé et dédoublonné dans data/silver/<source>/
```

| brut | `nom_norm` | `nom_phonetique` |
|---|---|---|
| `Le Goff`, `LE-GOFF` | `LE GOFF` | `LKF` |
| `LEGOF`, `Le Goffe` | `LEGOF`, `LE GOFFE` | `LKF` |
| `d'Hervé` | `D HERVE` | `DRV` |

Prénoms : `Jn-Bte Marie` → `JEAN BAPTISTE MARIE`, `Joannes` → `JEAN`. Naissance : une date
incomplète `19310300` donne l'intervalle `[1931, 1931]`, un âge de 40 ans dans un recensement
de 1906 donne `[1865, 1866]`.

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
