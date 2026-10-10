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

Tests : `tests/fabrique_insee.py` fabrique des lignes INSEE ; `python tests/fabrique_insee.py`
régénère `tests/fixtures/deces-extrait.txt`. Un test qui pend échoue au bout de 60 s
(`faulthandler_timeout`) ; lancer les commandes longues avec `timeout`.

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
├── config.py     # dossiers data/ (ou $DOUDOUMIL_DATA) : bronze, silver, gold, ref
├── cli.py        # commande `doudoumil` (argparse)
├── ingest/       # sources → bronze                (jalons 2, 6, 8)
│   ├── ecriture.py        # partition bronze écrite par lots, publiée d'un bloc
│   ├── insee_deces.py     # connecteur INSEE décès (largeur fixe)
│   └── telechargement.py  # catalogue data.gouv.fr, reprise, somme de contrôle
├── normalize/    # bronze → silver                 (jalon 3)
│   ├── texte.py           # majuscules ASCII, découpage en mots
│   ├── noms.py            # nom normalisé (particules gardées)
│   ├── prenoms.py         # prénoms + prenoms_equivalents.csv (abréviations, latin)
│   ├── phonetique.py      # clé phonétique (Soundex2 adapté, non tronqué)
│   ├── dates.py           # intervalle d'années de naissance (fonction + expression Polars)
│   ├── lieux.py           # référentiel des communes, codes anciens → commune actuelle
│   └── silver.py          # dédoublonnage et normalisation d'une source
├── search/       # silver → gold, recherche        (jalon 4)
│   ├── gold.py            # base DuckDB : personnes, prenoms, noms, lieux, calibration
│   ├── requete.py         # requête, « NOM Prénoms », résolution des lieux
│   ├── score.py           # composantes R2-R5 (fonctions pures)
│   ├── moteur.py          # canaux A/B/C + conjoint, score, fiches
│   ├── calibration.py     # régression isotone (PAV), Brier
│   ├── evaluation.py      # bruit de transcription, modes requete/donnees, calibration
│   └── affichage.py       # mise en forme pour la ligne de commande
├── api/          # FastAPI + interface web locale  (jalons 5 et 7)
└── linkage/      # rapprochement GEDCOM, optionnel (jalon 9)
```

## État du projet

> Section tenue à jour à la fin de chaque run (voir « Règle de mise à jour » ci-dessous).

- **Dernière mise à jour** : 2026-10-10
- **Jalons terminés** : 0 (socle), 1 (modèle pivot), 2 (ingestion INSEE décès), 3
  (normalisation → silver), 4 (base gold et recherche) : **l'étape 1 du plan (chaîne complète
  INSEE) est faite**, sous réserve de la vérification sur de vrais fichiers INSEE.
- **Jalon en cours** : aucun — prochain : **jalon 5, interface web locale**.
- **Prochaine action** : dès que data.gouv.fr est accessible, télécharger et ingérer les vrais
  fichiers INSEE pour vérifier le format, puis lancer `doudoumil calibre` et mesurer les
  performances sur les ≈ 25 M de décès. En parallèle : préalable P de PLAN.md (accès aux
  sources), en commençant par l'export en masse de Socface.
- **Accès réseau de l'environnement de développement** : data.gouv.fr et insee.fr sont
  bloqués (refus 403 du proxy) ; PyPI, GitHub et registry.npmjs.org passent. Le format INSEE
  et le catalogue data.gouv.fr restent donc à vérifier sur de vrais fichiers.
- **Décisions prises** :
  - Périmètre (PLAN.md §1) : recherche nominative, recensements, images ; toute la France ;
    uniquement sur l'ordinateur de l'utilisateur ; pas d'arbre (code GEDCOM de l'utilisateur).
  - Ordre : chaîne INSEE (jalons 2-4), interface web (5), recensements (6), images et
    localisateur de registres (7), autres sources (8), GEDCOM optionnel (9), finitions (10).
  - N'utiliser que des exports officiels, des API documentées ou des requêtes ponctuelles
    autorisées : jamais d'aspiration massive d'un site.
  - Polars pour les transformations, Parquet pour bronze/silver, DuckDB pour gold.
  - Énumérations stockées en `String` dans le Parquet ; la validation relève de Pydantic.
  - Identifiant INSEE : clé de contenu (date de décès, commune, n° d'acte), voir PLAN.md
    jalon 2 ; doublons gardés en bronze, éliminés en silver.
  - Clé phonétique : adaptation de Soundex2, non tronquée (`normalize/phonetique.py`) ;
    figée par des valeurs de référence dans les tests.
  - Référentiel des communes : `@etalab/decoupage-administratif` 6.0.0 depuis le registre npm,
    dans `data/ref/communes/`.
  - Recherche : canaux A (phonétique), B (noms proches dans la table `noms`), C (prénom +
    naissance + département), conjoint ; score en Python (`search/score.py`), poids
    0,35/0,30/0,20/0,15, neutre 0,5 ; calibration isotone par source dans la base gold.
  - Évaluation : `doudoumil evalue` (modes `requete` et `donnees`) ; non-régression en CI
    sur une population synthétique (`tests/population.py`), seuils dans
    `tests/test_evaluation.py`.
  - CLI `doudoumil` en `argparse` ; pools de processus en démarrage *spawn* (un *fork* après
    la création de fils d'exécution a bloqué les tests).
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
- **Dettes connues** : aucune pour l'instant.

## Journal des sessions

Une ligne par session de travail, la plus récente en haut.

- 2026-10-10 — Jalon 4 : base gold DuckDB, moteur à trois canaux plus conjoint, score R2-R5,
  calibration isotone, évaluation (bruit de transcription, modes requete/donnees),
  commandes `index`, `cherche`, `evalue`, `calibre`, non-régression en CI. Mesure : sur
  données bruitées à 40 %, le canal B porte la présélection de 83,7 % à 100 %.

- 2026-10-10 — Jalon 3 : normalisation des noms, prénoms (table d'équivalences), clé
  phonétique, intervalles de naissance, référentiel des communes (Etalab), étape silver avec
  dédoublonnage, `doudoumil telecharge communes` et `doudoumil normalize`.

- 2026-10-10 — Jalon 2 : évolution du pivot (`nature_nom`, `date_naissance_brute`,
  intervalle de naissance, outre-mer), connecteur INSEE décès vers bronze, téléchargement
  data.gouv.fr avec reprise, CLI `doudoumil telecharge|ingest insee`, CI GitHub Actions.

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
