# CLAUDE.md — doudoumil-search

Moteur de recherche généalogique personnel, 100 % local, destiné à **remplacer Filae** pour
trois usages : la recherche nominative, les recensements transcrits et l'accès aux images des
actes, sur toute la France. Il indexe des notices de sources publiques (INSEE décès,
recensements Socface, Morts pour la France, registres matricules, relevés personnels) et les
interroge avec tolérance aux variantes orthographiques. La recherche approchée est le cas
nominal. L'arbre généalogique est hors périmètre : l'utilisateur le gère avec son propre code
à partir du GEDCOM.

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
├── ingest/       # sources → bronze                (jalons 2, 6, 8)
├── normalize/    # bronze → silver                 (jalon 3)
├── search/       # silver → gold, recherche        (jalon 4)
├── api/          # FastAPI + interface web locale  (jalons 5 et 7)
└── linkage/      # rapprochement GEDCOM, optionnel (jalon 9)
```

## État du projet

> Section tenue à jour à la fin de chaque run (voir « Règle de mise à jour » ci-dessous).

- **Dernière mise à jour** : 2026-10-09
- **Jalons terminés** : 0 (socle), 1 (modèle pivot)
- **Jalon en cours** : aucun — prochain : **jalon 2, ingestion INSEE décès → bronze**
- **Prochaine action** : trancher la clé naturelle de l'`acte_id` INSEE (PLAN.md, jalon 2),
  puis faire évoluer le pivot (`date_naissance_brute`, `annee_naissance_min/max`,
  `nature_nom`) avant d'écrire le parseur et sa fixture. En parallèle : préalable P de
  PLAN.md (accès aux sources), en commençant par l'export en masse de Socface.
- **Décisions prises** :
  - Périmètre (PLAN.md §1) : recherche nominative, recensements, images ; toute la France ;
    uniquement sur l'ordinateur de l'utilisateur ; pas d'arbre (code GEDCOM de l'utilisateur).
  - Ordre : chaîne INSEE (jalons 2-4), interface web (5), recensements (6), images et
    localisateur de registres (7), autres sources (8), GEDCOM optionnel (9), finitions (10).
  - N'utiliser que des exports officiels, des API documentées ou des requêtes ponctuelles
    autorisées : jamais d'aspiration massive d'un site.
  - Polars pour les transformations, Parquet pour bronze/silver, DuckDB pour gold.
  - Énumérations stockées en `String` dans le Parquet ; la validation relève de Pydantic.
  - Conception de la recherche fixée dans PLAN.md, règles R1 à R5 :
    - R1 : présélection à trois canaux (phonétique, noms proches, prénom + naissance + lieu) ;
    - R2 : nature du nom (`naissance` / `marital` / `inconnue`) et option `--conjoint` ;
    - R3 : naissances en intervalles d'années, avec une tolérance par source ;
    - R4 : prénoms comparés sans tenir compte de l'ordre, avec une table d'équivalences ;
    - R5 : score pondéré, puis calibré en probabilité par source.
- **Points ouverts** : voir les blocs « Décisions » de PLAN.md. Le plus structurant : aucun
  export en masse de Socface ni des registres matricules n'a encore été trouvé (consultation
  gratuite sur FranceArchives seulement) ; pistes à vérifier : dump RDF et point SPARQL de
  FranceArchives, demande d'export à FranceArchives et à l'INED.
- **Manque assumé** : pas d'index national ouvert des naissances et mariages d'avant 1970 ;
  compensé par le localisateur de registres (jalon 7) et le connecteur de relevés (jalon 8).
- **Dettes connues** : `main.py` est le fichier par défaut de `uv init`, à supprimer au jalon 2.

## Journal des sessions

Une ligne par session de travail, la plus récente en haut.

- 2026-10-09 — Plan produit « remplacer Filae » (PLAN.md réécrit) : périmètre, tableau de
  correspondance Filae → sources ouvertes, préalable P sur l'accès aux sources, nouveaux
  jalons (interface web 5, recensements 6, images et localisateur 7, autres sources 8,
  GEDCOM optionnel 9, finitions 10).
- 2026-10-09 — Conception de la recherche (PLAN.md, R1 à R5) : corrige les limites
  identifiées (rappel de la présélection, femmes mariées, dates approximatives, prénoms
  multiples, score non calibré) ; tâches réparties dans les jalons 2 à 7.
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
