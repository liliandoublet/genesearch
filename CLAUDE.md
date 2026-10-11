# CLAUDE.md — doudoumil-search

Atelier de recherche généalogique, 100 % local, **complémentaire de Filae** (réorientation du
2026-10-11 : le projet visait d'abord à remplacer Filae). Filae et les autres sites servent à
chercher dans leurs index ; l'atelier sert à travailler, pour l'utilisateur ou pour des
clients (activité commerciale possible) : dossiers de recherche, vérification en lot d'une
liste ou d'un arbre contre les décès INSEE, recherche approchée dans les sources ouvertes
téléchargeables et les relevés privés, liens vers les sites et les registres des archives,
citations et rendu. La recherche approchée reste le cas nominal. L'arbre généalogique est hors
périmètre : l'utilisateur le gère avec son propre code à partir du GEDCOM.

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
├── config.py     # dossiers data/ (ou $DOUDOUMIL_DATA) : bronze, silver, gold, ref, perso, releves
├── cli.py        # commande `doudoumil` (argparse)
├── pipeline.py   # `doudoumil pipeline` : bronze → silver → gold selon les dates (façon make)
├── dossiers.py   # dossiers de recherche : un SQLite par dossier, personnes, notices, export
├── sauvegarde.py # archive zip de data/perso et data/releves, restauration vérifiée
├── ingest/       # sources → bronze                (jalons 2, 6, 8)
│   ├── commun.py          # rejets, bilan d'ingestion, motifs de codes géographiques
│   ├── ecriture.py        # partition bronze écrite par lots, publiée d'un bloc
│   ├── insee_deces.py     # connecteur INSEE décès (largeur fixe)
│   ├── releves.py         # relevés CSV/Excel + correspondance TOML, modèle prérempli
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
│   ├── gold.py            # base DuckDB : personnes, prenoms, noms, lieux
│   ├── requete.py         # requête, « NOM Prénoms », résolution des lieux
│   ├── score.py           # composantes R2-R5 (fonctions pures)
│   ├── moteur.py          # canaux A/B/C + conjoint, score, fiches
│   ├── calibration.py     # régression isotone (PAV), Brier, gold/calibration.json
│   ├── evaluation.py      # bruit de transcription, modes requete/donnees, calibration
│   └── affichage.py       # mise en forme pour la ligne de commande
├── api/          # interface web locale            (jalons 5 et 7)
│   ├── application.py     # FastAPI : pages, fiches, trouvailles, CSV, API JSON, sécurité
│   ├── formulaire.py      # paramètres d'adresse → requête ; filtres et compteurs
│   ├── trouvailles.py     # carnet de trouvailles (favori, note, verdict, requête, personne)
│   ├── gabarits/          # pages Jinja2
│   └── statique/          # style.css, doudoumil.js (autocomplétion, copie), icône
└── linkage/      # rapprochement GEDCOM, optionnel (jalon 9)
```

## État du projet

> Section tenue à jour à la fin de chaque run (voir « Règle de mise à jour » ci-dessous).

- **Dernière mise à jour** : 2026-10-11
- **Jalons terminés** : 0 (socle), 1 (modèle pivot), 2 (ingestion INSEE décès), 3
  (normalisation → silver), 4 (base gold et recherche), 5 (interface web locale), sous réserve
  de la vérification sur de vrais fichiers INSEE ; 11 (dossiers de recherche).
- **Jalons en partie** : 8 (relevés faits ; Morts pour la France et registres matricules en
  sommeil) et 10 (`doudoumil pipeline`, sauvegarde et restauration faits ; restent la mise à
  jour vraiment incrémentale, le README complet, l'homogénéité des journaux).
- **Suite, depuis la réorientation** (PLAN.md §4) : jalon 11 dossiers de recherche (fait),
  12 **vérification en lot** (le prochain : liste ou GEDCOM contre les décès INSEE), 13 passerelles
  (liens pré-remplis vers Filae, Geneanet, FamilySearch, MatchID, FranceArchives ;
  localisateur de registres), 14 rendu pour le client. **En sommeil** : 6 (Socface), 7
  (visionneuse intégrée), 8 (Morts pour la France, registres matricules) ; 9 est repris par
  12.
- **Prochaine action** : côté code, jalon 12 (vérification en lot : liste ou GEDCOM contre les
  décès INSEE, les personnes importées devenant les personnes recherchées d'un dossier). Côté
  utilisateur : dérouler `docs/tests-manuels.md` (vrais fichiers INSEE,
  performances sur ≈ 25 M de décès, personnes connues, vrai relevé, sauvegarde) et renvoyer
  sa « fiche de résultats » ; la demande d'export Socface n'est plus prioritaire.
- **Accès réseau de l'environnement de développement** : data.gouv.fr et insee.fr sont
  bloqués (refus 403 du proxy) ; PyPI, GitHub et registry.npmjs.org passent. Le format INSEE
  et le catalogue data.gouv.fr restent donc à vérifier sur de vrais fichiers.
- **Décisions prises** :
  - **Réorientation (2026-10-11)** : atelier complémentaire de Filae, et non plus
    remplacement. Raison : les index d'état civil d'avant 1970 de Filae n'ont pas d'équivalent
    ouvert ni reconstituable ; pour chercher, un abonnement reste le bon choix, y compris pour
    une activité commerciale. Hors périmètre : reconstituer ou extraire les index d'un site,
    interroger automatiquement un site (seulement des liens ouverts par l'utilisateur).
  - Périmètre (PLAN.md §1) : dossiers de recherche, recherche approchée (décès INSEE, relevés
    privés), vérification en lot, passerelles vers les sites et les archives, rendu ;
    uniquement sur l'ordinateur de l'utilisateur ; pas d'arbre (code GEDCOM de l'utilisateur).
  - Activité commerciale : données des clients (famille vivante) gardées en local, dossier
    supprimable entièrement, durée de conservation à fixer ; conditions d'utilisation des
    sites payants à vérifier ; un rendu cite l'acte original (archives, cote, vue).
  - Ordre : faits 0-5, relevés (8), pipeline et sauvegarde (10) ; puis dossiers (11),
    vérification en lot (12), passerelles (13), rendu (14), finitions (10) au fil de l'eau.
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
    0,35/0,30/0,20/0,15, neutre 0,5 ; calibration isotone par source dans
    `data/gold/calibration.json` (jamais dans la base : elle peut rester ouverte ailleurs).
  - Performances (4 M de décès synthétiques) : requêtes en 40 à 120 ms en médiane ; table
    `prenoms` dénormalisée pour le canal C. Ne pas relire `personnes` par listes
    d'identifiants : DuckDB parcourt alors toute la table.
  - Évaluation : `doudoumil evalue` (modes `requete` et `donnees`) ; non-régression en CI
    sur une population synthétique (`tests/population.py`), seuils dans
    `tests/test_evaluation.py`.
  - Relevés (jalon 8, `docs/releves.md`) : tableur CSV/Excel décrit par `releves/<nom>.toml`
    (constante ou `{ colonne, valeurs, defaut, format }`), une ligne = un acte ; identifiants
    = nom du TOML + colonnes `cle` (défaut : n° de ligne) ; `Acte.titre_source` cité dans les
    fiches ; en silver, code de commune déduit d'un nom unique et naissance du sujet d'un
    baptême / d'une naissance déduite de l'année de l'acte (R3). `--cas` de `evalue` et
    `calibre` compte les cas **par source** (calibration des petites sources).
  - `doudoumil pipeline` (jalon 10) : refait une étape si une entrée est plus récente que son
    résultat (dates de modification) ; `--tout` force ; une erreur de relevé n'arrête pas le
    reste. Sauvegarde : zip de `data/perso/` + `data/releves/` avec manifeste, SQLite copiée par
    l'API de sauvegarde ; restauration vérifiée (manifeste, chemins), précédée d'une
    sauvegarde de l'état actuel.
  - Dossiers (jalon 11, `dossiers.py`) : un SQLite par dossier dans `data/perso/dossiers/`
    (identifiant tiré du nom, puis fixe) ; une notice dans plusieurs dossiers par copie ;
    `personne=<dossier>:<numéro>` dans l'adresse d'une recherche range les notices retenues
    chez cette personne quel que soit le dossier actif ; dossier actif dans
    `data/perso/dossier-actif` (interface et CLI) ; ancien `trouvailles.sqlite` repris en
    « Personnel » ; suppression confirmée par l'identifiant ; `calibre` lit tous les dossiers.
  - Interface web : Jinja2 rendu serveur sans framework JS, recherches dans l'adresse (GET),
    `127.0.0.1` seulement, hôtes et origines vérifiés ; trouvailles rangées dans les dossiers
    de recherche, à sauvegarder (jamais reconstruits) ; leurs verdicts complètent la
    calibration. Tests navigateur : Playwright + Chromium (`navigateur`).
  - CLI `doudoumil` en `argparse` ; pools de processus en démarrage *spawn* (un *fork* après
    la création de fils d'exécution a bloqué les tests).
  - Conception de la recherche fixée dans PLAN.md, règles R1 à R5 :
    - R1 : présélection à trois canaux (phonétique, noms proches, prénom + naissance + lieu) ;
    - R2 : nature du nom (`naissance` / `marital` / `inconnue`) et option `--conjoint` ;
    - R3 : naissances en intervalles d'années, avec une tolérance par source ;
    - R4 : prénoms comparés sans tenir compte de l'ordre, avec une table d'équivalences ;
    - R5 : score pondéré, puis calibré en probabilité par source.
- **Points ouverts** : voir les blocs « Décisions » de PLAN.md ; format des adresses de recherche des sites et conditions d'utilisation de ces
  liens (préalable P, pour le jalon 13).
- **Manque assumé** : pas d'index national ouvert des naissances et mariages d'avant 1970 ;
  c'est le rôle de Filae et des autres sites, que l'atelier complète (dossiers, passerelles,
  relevés, localisateur de registres).
- **Dettes connues** : aucune pour l'instant.

## Journal des sessions

Une ligne par session de travail, la plus récente en haut.

- 2026-10-11 — Jalon 11 : dossiers de recherche (`dossiers.py`), un fichier SQLite par
  dossier ; personnes recherchées, recherche lancée depuis une personne (`personne=` dans
  l'adresse), trouvailles rattachées, notices saisies à la main avec citation, export CSV et
  copie réimportable, suppression confirmée ; pages `/dossiers` et `/dossiers/<id>`, dossier
  actif dans l'en-tête ; CLI `doudoumil dossier` ; reprise de l'ancien carnet en
  « Personnel » ; calibration sur tous les dossiers ; tests (module, CLI, web, navigateur) et
  captures.

- 2026-10-11 — **Réorientation** : le projet devient un atelier complémentaire de Filae
  (décision de l'utilisateur). PLAN.md réécrit (but, périmètre, précautions pour une activité
  commerciale, « qui fait quoi », ordre) ; nouveaux jalons 11 (dossiers de recherche), 12
  (vérification en lot), 13 (passerelles vers les sites et les archives), 14 (rendu pour le
  client) ; jalons 6, 7 (visionneuse) et 8 (Morts pour la France, matricules) en sommeil,
  jalon 9 repris par 12. README, CLAUDE.md et `docs/tests-manuels.md` alignés. Aucun
  changement de code.

- 2026-10-10 — Correction de la CI : les tests de `pipeline` échouaient sur GitHub (3 tests,
  verts en local) car les fixtures fraîchement extraites par git portent la date du jour, plus
  récente que les résultats « vieillis » du test. Les tests datent désormais toutes les
  entrées et tous les résultats du même instant (`tests/test_pipeline.py`). Aucun changement
  du code de `pipeline.py`. Leçon : un test fondé sur des dates de fichiers ne doit jamais
  dépendre de l'ancienneté des fixtures ni de l'ordre de parcours des dossiers.

- 2026-10-10 — `docs/tests-manuels.md` : préparatifs côté utilisateur et tests manuels (vrais
  fichiers INSEE, interface, comparaison avec Filae, performances, calibration, relevé,
  sauvegarde) avec fiche de résultats ; `doudoumil pipeline` affiche la durée de chaque étape
  et signale un catalogue data.gouv.fr sans fichier reconnu.

- 2026-10-10 — Jalon 10 (en partie) : `doudoumil pipeline` (téléchargement au choix, puis
  bronze, silver et gold refaits seulement si leurs entrées ont changé), `doudoumil
  sauvegarde` / `restaure` et téléchargement de la sauvegarde depuis « Mes trouvailles » ;
  archives INSEE réextraites seulement si elles sont plus récentes.

- 2026-10-10 — Jalon 8 (relevés) : `Source.RELEVE`, `Acte.titre_source`, connecteur
  `ingest/releves.py` (CSV et Excel, correspondance TOML vérifiée, modèle prérempli par
  `doudoumil ingest releve --modele`), commune déduite de son nom et naissance déduite du
  baptême en silver, libellés et citations dans l'interface, tirage d'évaluation par source,
  `docs/releves.md`.

- 2026-10-10 — Jalon 5 : interface web locale (`doudoumil serve`) : recherche simple et
  avancée, autocomplétion des lieux, filtres à compteurs, fiches d'actes avec citation,
  « Mes trouvailles » (favoris, notes, verdicts), exports CSV, API JSON ; verdicts intégrés à
  `doudoumil calibre` ; calibration déplacée dans `gold/calibration.json` ; tests Playwright
  dans la CI ; demande d'export Socface rédigée (`docs/demande-export-socface.md`).

- 2026-10-10 — Jalon 4 : base gold DuckDB, moteur à trois canaux plus conjoint, score R2-R5,
  calibration isotone, évaluation (bruit de transcription, modes requete/donnees),
  commandes `index`, `cherche`, `evalue`, `calibre`, non-régression en CI. Mesures : sur
  données bruitées à 40 %, le canal B porte la présélection de 83,7 % à 100 % ; sur 4 M de
  décès synthétiques, requêtes en 40 à 120 ms après dénormalisation de `prenoms`.

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
