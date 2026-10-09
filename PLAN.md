# Plan de développement — doudoumil-search

Feuille de route du projet, jalon par jalon. Chaque jalon livre une tranche utilisable et se
termine par une commande de démonstration ajoutée au README.

Légende : `[x]` fait · `[~]` en cours · `[ ]` à faire · **Décision** = choix à trancher (et à
consigner dans CLAUDE.md une fois tranché).

Ordre retenu : on construit d'abord une chaîne complète sur une seule source fiable (INSEE
décès : ingestion → normalisation → recherche), puis on ajoute la source bruitée (Socface), puis
l'API et le rapprochement GEDCOM. Ainsi, chaque couche est validée de bout en bout avant d'être
généralisée.

---

## Jalon 0 — Socle du dépôt ✅

- [x] Projet uv, Python 3.11, paquet `src/doudoumil_search`
- [x] ruff (lint + format) et pytest configurés
- [x] Arborescence des sous-paquets (`ingest`, `normalize`, `search`, `api`, `linkage`)
- [x] `.gitignore` excluant `data/` et les bases DuckDB

## Jalon 1 — Modèle pivot ✅

- [x] `Acte` et `Mention` (Pydantic, immuables, `extra="forbid"`)
- [x] Énumérations `Source`, `TypeActe`, `Role`, `Sexe` et types contraints (code INSEE, département)
- [x] `fabriquer_id()` : identifiants déterministes BLAKE2b
- [x] Schémas Parquet `SCHEMA_ACTES`, `SCHEMA_MENTIONS` et `vers_dataframe()`
- [x] Tests : validation, bornes, aller-retour Parquet, cohérence modèle/schéma

---

## Jalon 2 — Ingestion INSEE décès → bronze

**Objectif** : convertir les fichiers INSEE des personnes décédées (data.gouv.fr) en Parquet
pivot dans `data/bronze/`, sans aucune normalisation.

- [ ] Nettoyage : supprimer le `main.py` généré par `uv init`
- [ ] Documenter le format dans `ingest/insee_deces.py` : enregistrements à largeur fixe
  (nom*prénoms/ sur 80 caractères, sexe, date de naissance, code et libellé du lieu de
  naissance, pays, date de décès, code du lieu de décès, numéro d'acte), à revérifier sur la
  documentation officielle avant d'écrire le parseur
- [ ] Parseur ligne → `Acte` (type `deces`, `annee` = année du décès) + `Mention` (rôle `sujet`)
  - séparer `NOM*PRENOMS/` en `nom_brut` / `prenoms_bruts`
  - sexe `1`/`2` → `M`/`F`
  - lieu de décès → `commune_code_insee` et `departement` (2A/2B, 97x, 99 = étranger)
  - lieu de naissance → `lieu_naissance_brut` / `lieu_naissance_code_insee`
  - `confiance_source = 1.0` (saisie administrative)
- [ ] Gestion des anomalies : dates partielles (mois ou jour à `00`), codes lieux invalides,
  lignes tronquées → lignes rejetées comptées et journalisées, jamais d'arrêt sur une ligne
- [ ] Lecture en flux et écriture Parquet par lots (les fichiers annuels font des centaines de
  Mo) ; partitionnement de `data/bronze/insee_deces/` par fichier source
- [ ] Ingestion idempotente : réingérer un fichier redonne les mêmes identifiants
- [ ] CLI minimale (`[project.scripts]`) : `doudoumil ingest insee <fichier>`
- [ ] Fixture de quelques lignes (inventées ou anonymisées) dans `tests/fixtures/` et tests :
  découpage, anomalies, idempotence, conformité au schéma
- [ ] CI GitHub Actions : `ruff check`, `ruff format --check`, `pytest`

**Décisions**
- Clé naturelle de l'`acte_id` : `(fichier, n° de ligne)` ne dédoublonne pas les
  recouvrements entre fichiers mensuels et annuels. Option proposée : clé de contenu
  `(date de décès, code lieu de décès, n° d'acte)`, avec `(fichier, ligne)` gardés en provenance
  (`cote`, `vue`).
- Dates partielles : le pivot n'a que `date_naissance: date | None`. Faut-il ajouter
  `annee_naissance` (ou une date brute) au pivot pour ne pas perdre l'année quand le jour vaut 00 ?
- Bibliothèque de CLI : `argparse` (aucune dépendance) ou `typer`.

**Démo** : `uv run doudoumil ingest insee tests/fixtures/deces-extrait.txt` puis lecture du
Parquet produit.

---

## Jalon 3 — Normalisation → silver

**Objectif** : produire `data/silver/` avec `nom_norm`, `prenoms_norm`, `nom_phonetique`, et
des lieux ramenés au Code officiel géographique.

- [ ] `normalize/noms.py` : majuscules, suppression des accents, des apostrophes et tirets
  normalisés, particules (`LE`, `DE`, `D'`, `DU`, `LA`…) conservées mais normalisées, espaces
  multiples ; tests sur des cas réels (« LE GOFF », « D'HERVÉ », « LE-GOFF »)
- [ ] `normalize/prenoms.py` : premier prénom usuel, liste ordonnée des prénoms, variantes
  courantes (Jean-Marie / Jean Marie)
- [ ] `normalize/phonetique.py` : code phonétique adapté au français
- [ ] `normalize/lieux.py` : référentiel COG INSEE (communes actuelles + historique des
  fusions et changements de nom) pour relier un libellé ancien à un code
- [ ] Étape silver : lit bronze, écrit silver (nouveaux fichiers, bronze intact)
- [ ] CLI : `doudoumil normalize`
- [ ] Tests de propriétés : la normalisation est idempotente (`f(f(x)) == f(x)`)

**Décisions**
- Algorithme phonétique : Soundex français, Phonex, FONEM (pensé pour les patronymes
  français) ou Beider-Morse ; à comparer sur un échantillon de variantes connues.
- Livraison du référentiel COG : téléchargé à la demande dans `data/ref/` ou extrait versionné.

**Démo** : avant/après sur quelques noms (`LE GOFF` / `Legoff` / `LE-GOFF` → même clé).

---

## Jalon 4 — Index et recherche → gold

**Objectif** : une base DuckDB dans `data/gold/` interrogeable avec tolérance aux variantes,
chaque résultat portant un score de confiance et sa provenance.

- [ ] Ajouter `duckdb` aux dépendances
- [ ] Construction de la base gold depuis silver (tables `actes`, `mentions`, index sur
  `nom_phonetique`, `nom_norm`, `annee`, `departement`)
- [ ] `search/` : requête par nom, prénom, intervalle d'années, lieu, rôle
  1. présélection par clé phonétique et filtres
  2. tri par similarité (Jaro-Winkler / Levenshtein intégrés à DuckDB) sur nom et prénom
  3. score final combinant similarité, concordance des dates et lieux, et `confiance_source`
- [ ] Résultat : acte + mention + score + provenance (`depot`, `cote`, `vue`, `url_image`)
- [ ] CLI : `doudoumil index` et `doudoumil cherche "LE GOFF Marie" --annees 1920-1940`
- [ ] Jeu d'évaluation annoté (requêtes + résultats attendus) et mesure de précision et de rappel,
  pour régler les seuils sur des chiffres plutôt qu'à l'œil
- [ ] Mesure des performances sur un fichier annuel complet

**Décisions**
- Pondération du score et seuil d'affichage (à régler avec le jeu d'évaluation).
- Base gold reconstruite entièrement ou mise à jour incrémentale.

**Démo** : recherche approchée en ligne de commande sur un fichier INSEE réel.

---

## Jalon 5 — Ingestion Socface (recensements) → bronze/silver

**Objectif** : ajouter les recensements transcrits automatiquement, source bruitée qui
justifie la recherche approchée.

- [ ] Étudier l'accès et le format des données Socface (export, champs, structure ménage /
  individu, score de transcription disponible ou non) et le consigner dans
  `notebooks/` + CLAUDE.md
- [ ] Parseur : un acte `recensement` par feuillet ou ménage, une mention par individu
  (`chef_menage`, `enfant`, `autre`…), âge, profession, lieu de naissance brut
- [ ] `confiance_source` dérivée du score de transcription s'il existe
- [ ] Réutiliser intégralement les étapes silver et gold existantes
- [ ] Notebook d'exploration de la qualité (taux d'erreur, champs vides, distribution des âges)
- [ ] Réévaluer la recherche sur le jeu d'évaluation enrichi de cas Socface

**Décisions**
- Granularité de l'acte (feuillet, ménage ou maison).
- Déduction d'une année de naissance approchée à partir de l'âge (± 1 an) pour la recherche.

---

## Jalon 6 — API FastAPI

**Objectif** : exposer la recherche en HTTP local.

- [ ] Ajouter `fastapi` et `uvicorn`
- [ ] `GET /recherche` (mêmes critères que la CLI, pagination)
- [ ] `GET /actes/{acte_id}` (acte + toutes ses mentions + provenance)
- [ ] Schémas de réponse Pydantic, documentation OpenAPI
- [ ] Tests avec `TestClient` sur une base gold construite depuis les fixtures
- [ ] CLI : `doudoumil serve`
- [ ] (optionnel) Petite page HTML de recherche servie par l'API

**Démo** : `uv run doudoumil serve` puis requête sur `/recherche`.

---

## Jalon 7 — Rapprochement avec l'arbre GEDCOM

**Objectif** : proposer, pour chaque individu de l'arbre, les notices candidates avec un score.

- [ ] Lecture GEDCOM (5.5.1, et 7 si besoin) : individus, noms, dates et lieux de naissance et
  décès, filiations
- [ ] Normalisation des individus avec les mêmes fonctions que silver
- [ ] Présélection (*blocking*) : clé phonétique + année de naissance ± tolérance
- [ ] Score de rapprochement : nom, prénoms, dates, lieux, cohérence familiale (parents,
  conjoint) ; seuils « certain / probable / à vérifier »
- [ ] Export des candidats (CSV ou table DuckDB) avec provenance, pour validation manuelle
- [ ] Mémorisation des validations et rejets manuels pour ne pas reproposer un rejet
- [ ] `GET /individus/{id}/candidats` dans l'API
- [ ] Jeu d'évaluation : individus de l'arbre dont la notice est connue

**Décisions**
- Bibliothèque GEDCOM (`python-gedcom`, `ged4py`) ou parseur maison minimal.
- Score de rapprochement fait main ou appui sur `splink` (rapprochement probabiliste sur DuckDB).

---

## Jalon 8 — Finitions

- [ ] Commande unique `doudoumil pipeline` (bronze → silver → gold)
- [ ] README complet : installation, téléchargement des sources, exemples
- [ ] Journalisation homogène et messages d'erreur en français
- [ ] Sources supplémentaires (relevés d'associations, autres archives départementales) : le
  modèle pivot doit les accueillir sans changement de schéma, sinon consigner l'évolution

---

## Transverse (à chaque jalon)

- Tests : chaque module a ses tests ; les fixtures restent petites et sans données réelles
  identifiantes.
- Vérifications vertes avant chaque commit : `uv run ruff check`, `uv run ruff format --check`,
  `uv run pytest`.
- Mettre à jour la section « Démonstration » du README, cocher ce plan et mettre à jour CLAUDE.md.
