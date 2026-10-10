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

### Jalon 4 — base de recherche et recherche approchée

```bash
uv run doudoumil index                 # base DuckDB dans data/gold/recherche.duckdb
uv run doudoumil cherche "LEGOF Marie" --naissance 1931 --lieu Quimper --details
```

```
  1. non calibré (score 0,99) — LE GOFF MARIE JOSEPHE (F), née le 02/03/1931 à QUIMPER, décès le 15/01/2020 à Rennes (35)
     INSEE · deces-extrait.txt · vue 1   [noms proches, phonétique, sans le nom]
     nom 0,97, prénoms 1,00, naissance 1,00, lieu 1,00
```

Sans le nom, avec un prénom, une année approximative et un département :

```bash
uv run doudoumil cherche --prenoms Yves --naissance 1920 --lieu 29
```

Options : `--sexe`, `--annees` (année de l'acte), `--conjoint` (nom du mari, pour une femme
inscrite sous son nom d'épouse), `--source`, `--limite`. Le lieu accepte un département
(`29`), un code INSEE (`29232`) ou un nom de commune (`Saint-Denis (974)` pour lever une
homonymie).

Qualité et calibration :

```bash
uv run doudoumil evalue                 # requêtes imprécises sur la base telle quelle
uv run doudoumil evalue --mode donnees  # requêtes exactes sur une copie bruitée des données
uv run doudoumil calibre                # le score devient une probabilité (« très probable »…)
```

## Arborescence

```
src/doudoumil_search/
├── pivot.py        # modèle pivot (Acte, Mention) et fabriquer_id()
├── schemas.py      # schémas Parquet
├── cli.py          # commande doudoumil
├── ingest/         # connecteurs (INSEE décès) et téléchargement
├── normalize/      # noms, prénoms, clé phonétique, dates, lieux, étape silver
├── search/         # base gold, moteur, score, calibration, évaluation
├── api/            # interface web locale (jalon 5)
└── linkage/        # rapprochement avec un arbre GEDCOM (jalon 9, optionnel)
tests/              # tests, fichiers d'exemple et population synthétique
notebooks/          # exploration de la qualité des sources
```
