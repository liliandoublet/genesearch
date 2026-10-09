# CLAUDE.md — doudoumil-search

Moteur de recherche généalogique personnel, 100 % local : il indexe des notices d'archives
françaises (INSEE décès, recensements Socface), les interroge avec tolérance aux variantes
orthographiques et les rapproche d'un arbre GEDCOM. La recherche approchée est le cas nominal.

- Feuille de route détaillée : `PLAN.md` (à lire avant de commencer un jalon)
- Présentation et démonstrations : `README.md`

## Commandes

```bash
uv sync                    # installer
uv run ruff check          # lint
uv run ruff format --check # format (uv run ruff format pour corriger)
uv run pytest              # tests
```

Les trois vérifications doivent être vertes avant tout commit.

## Conventions

- **Tout en français** : identifiants, docstrings, commentaires, messages d'erreur, messages de
  commit (verbe au présent, ex. « Ajoute le parseur INSEE décès »).
- Python 3.11, ruff (lignes de 100 caractères), annotations de type partout.
- Modèles Pydantic immuables (`frozen=True`, `extra="forbid"`), sans transformation implicite.
- Les champs `*_brut(s)` conservent la valeur source **sans aucune** transformation ; la
  normalisation remplit les champs `*_norm` / `nom_phonetique` en couche silver uniquement.
- Couches `data/bronze` → `data/silver` → `data/gold` : une couche ne modifie jamais la
  précédente. `data/` n'est jamais versionné.
- Identifiants via `fabriquer_id()` (`pivot.py`) : déterministes, l'ingestion est idempotente.
- Toute notice garde sa provenance (`depot`, `cote`, `vue`, `url_image`).
- Ajouter un champ au pivot = le modifier dans `pivot.py` **et** `schemas.py` (même ordre) ;
  `test_colonnes_identiques_au_modele` le vérifie.
- Tests : fixtures partagées dans `tests/conftest.py`, fichiers d'exemple dans
  `tests/fixtures/`, petits et sans données réelles identifiantes.

## Architecture

```
src/doudoumil_search/
├── pivot.py      # Acte, Mention, énumérations, fabriquer_id()
├── schemas.py    # SCHEMA_ACTES, SCHEMA_MENTIONS, vers_dataframe()
├── ingest/       # sources → bronze           (jalons 2 et 5)
├── normalize/    # bronze → silver            (jalon 3)
├── search/       # silver → gold, recherche   (jalon 4)
├── api/          # FastAPI                    (jalon 6)
└── linkage/      # rapprochement GEDCOM       (jalon 7)
```

## État du projet

> Section tenue à jour à la fin de chaque run (voir « Règle de mise à jour » ci-dessous).

- **Dernière mise à jour** : 2026-10-09
- **Jalons terminés** : 0 (socle), 1 (modèle pivot)
- **Jalon en cours** : aucun — prochain : **jalon 2, ingestion INSEE décès → bronze**
- **Prochaine action** : trancher la clé naturelle de l'`acte_id` INSEE et le traitement des
  dates partielles (voir PLAN.md, jalon 2), puis écrire le parseur et sa fixture.
- **Décisions prises** :
  - Polars pour les transformations, Parquet pour bronze/silver, DuckDB pour gold.
  - Énumérations stockées en `String` dans le Parquet ; la validation relève de Pydantic.
- **Points ouverts** : voir les blocs « Décisions » de PLAN.md.
- **Dettes connues** : `main.py` est le fichier par défaut de `uv init`, à supprimer au jalon 2.

## Journal des sessions

Une ligne par session de travail, la plus récente en haut.

- 2026-10-09 — Création de PLAN.md, de ce CLAUDE.md et du hook de fin de run qui en impose la
  mise à jour.
- (avant) — Socle du dépôt et modèle pivot (jalons 0 et 1).

## Règle de mise à jour

À la fin de chaque run qui a changé quelque chose dans le projet :

1. Mettre à jour « État du projet » (date, jalon, prochaine action, décisions, dettes).
2. Ajouter une ligne en haut du « Journal des sessions ».
3. Cocher dans `PLAN.md` les tâches terminées (`[x]`, ou `[~]` si en cours) et y reporter
   toute décision tranchée.
4. Si un jalon est terminé, mettre à jour la section « Démonstration » du README.
5. Commiter ces fichiers avec le travail qu'ils décrivent.

Un hook `Stop` (`.claude/hooks/rappel-claude-md.sh`, déclaré dans `.claude/settings.json`)
bloque une fois la fin du run si des fichiers de `src/`, `tests/`, `notebooks/`,
`pyproject.toml` ou `main.py` ont changé depuis le dernier commit touchant CLAUDE.md.
