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

## Conception de la recherche

Règles qui s'imposent à toutes les étapes (ingestion, normalisation, index, recherche). Les
jalons y renvoient par leur numéro (R1 à R5).

### R1 — Présélection à plusieurs canaux

Une seule clé phonétique ferait perdre toute notice dont le nom a été mal transcrit au point
d'en changer la prononciation (`LE GOSS` pour `LE GOFF`, le *s long* des écritures anciennes
étant lu comme un *f* ; `NOREAU` pour `MOREAU`). La présélection réunit donc les candidats de
trois canaux indépendants, puis les classe tous avec le même score :

| canal | candidats retenus | rattrape |
|---|---|---|
| A — phonétique | même clé phonétique du nom | variantes orthographiques (`LEGOF`, `LE GOFF`) |
| B — noms proches | noms dont l'écriture est proche de celle de la requête (voir ci-dessous) | erreurs de lecture qui changent la prononciation (`LE GOSS`, `NOREAU`) |
| C — sans le nom | même clé phonétique d'un prénom + naissance compatible (R3) + même commune ou département, dans la limite d'un plafond de candidats | nom illisible ou absent, nom d'épouse (R2) |

- Canal B : la base gold tient la liste des noms normalisés distincts (de l'ordre du million
  au plus) avec leur nombre d'occurrences. Le nom de la requête est comparé à **tous** ces
  noms, pas aux mentions : distance d'édition ≤ 2 ou Jaro-Winkler ≥ 0,85 (valeurs de départ).
  Les mentions portant l'un des noms retenus deviennent candidates. Si cette comparaison
  complète est trop lente, un préfiltre par trigrammes communs la réduit, mais il ne doit pas
  faire baisser le rappel mesuré : les trigrammes seuls perdent les noms courts.
- Le canal C est lancé **à chaque requête** qui précise un prénom, une naissance et un lieu, et
  pas seulement quand les autres canaux ne trouvent rien. Une requête sur un nom courant
  remonte des homonymes et ne signale donc pas que la bonne notice a été manquée.
- Chaque résultat indique le ou les canaux qui l'ont trouvé.
- Le rappel de la présélection (part des bonnes notices qui atteignent le classement) est
  mesuré à part sur le jeu d'évaluation bruité (R5). Objectif de départ : au moins 95 %.

### R2 — Femmes mariées et nature du nom

- Chaque mention porte la **nature du nom** relevé : `naissance`, `marital` ou `inconnue`,
  renseignée à l'ingestion selon la source et le rôle. Dans les recensements, une épouse ou une
  veuve est classée `marital`. Pour INSEE décès, vérifier dans la documentation qu'il s'agit
  bien du nom de naissance.
- Quand la requête vise une femme (sexe ou prénom féminin) et qu'un candidat porte un nom
  `marital`, la ressemblance des noms ne compte ni pour ni contre : elle prend la valeur
  neutre (R5). Ce sont le prénom, la naissance et le lieu qui décident, et le canal C (R1)
  amène ces candidates.
- Option de requête `--conjoint NOM` : le nom du mari est comparé au nom `marital` du candidat
  et compte alors normalement.
- Le résultat signale « nom d'épouse probable » pour que l'utilisateur sache pourquoi le nom ne
  correspond pas.
- Au jalon 7, l'arbre GEDCOM fournit le nom de naissance et le conjoint : la recherche lance
  automatiquement les deux variantes.

### R3 — Dates en intervalles

- Toute naissance est représentée par un intervalle d'années `[annee_naissance_min,
  annee_naissance_max]`, calculé en silver :
  - date complète → min = max = l'année ;
  - date partielle INSEE (jour ou mois à `00`) → l'année est conservée ; la date brute est
    gardée telle quelle dans `date_naissance_brute` ;
  - âge révolu `A` dans un acte de l'année `Y` → `[Y − A − 1, Y − A]` ;
  - aucune information → intervalle vide (`None`).
- Une tolérance propre à chaque source s'ajoute à la comparaison : ±1 an pour INSEE, ±2 ans
  pour les recensements, dont les âges sont souvent arrondis ou estimés. Valeurs de départ à
  ajuster sur le jeu d'évaluation.
- Comparaison : 1 si les intervalles se chevauchent, puis décroissance linéaire jusqu'à 0 à la
  limite de la tolérance. La présélection filtre avec l'intervalle élargi de la tolérance, pour
  ne jamais exclure un candidat que le score aurait gardé.
- La requête distingue deux critères : `--naissance 1880-1885` (année de naissance de la
  personne) et `--annees 1920-1940` (année de l'acte).

### R4 — Prénoms multiples

- `prenoms_norm` : liste ordonnée de prénoms normalisés, séparés par des espaces. Les prénoms
  composés sont découpés (`Jean-Marie` et `Jean Marie` donnent `JEAN MARIE`).
- Table d'équivalences versionnée (`normalize/prenoms_equivalents.csv`) : abréviations des
  actes anciens (`Jn` → `JEAN`, `Fois` → `FRANCOIS`, `Mie` → `MARIE`, `Jph` → `JOSEPH`), formes
  latines (`JOANNES` → `JEAN`, `MARIA` → `MARIE`), graphies anciennes courantes.
- Score des prénoms, **indépendant de l'ordre** :
  - chaque prénom de la requête est comparé au prénom le plus proche du candidat ;
  - le score est la moyenne de ces meilleures ressemblances, si bien qu'un prénom demandé
    mais absent fait baisser le score ;
  - les prénoms du candidat absents de la requête ne pénalisent pas, car les sources listent
    tous les prénoms alors que la requête n'en donne souvent qu'un ;
  - un petit bonus est accordé si le premier prénom de la requête est aussi le premier du
    candidat (prénom usuel probable).
- Ainsi, « Marie » trouve « Marie Josèphe » (score maximal) et « Josèphe Marie » (presque
  maximal, sans le bonus). Le sexe départage « Marie » et « Jean Marie ».

### R5 — Score calibré

- Le score de classement est une somme pondérée de composantes comprises entre 0 et 1 : nom,
  prénoms (R4), naissance (R3), lieu. Poids de départ, à régler sur le jeu d'évaluation :
  0,35 / 0,30 / 0,20 / 0,15.
- Composante sans information, ou nom `marital` (R2) : valeur neutre 0,5, ni bonus ni
  pénalité.
- `confiance_source` rapproche les composantes transcrites de la valeur neutre :
  `s' = c × s + (1 − c) × 0,5`. Une transcription peu fiable pèse moins, dans un sens comme
  dans l'autre.
- **Calibration** : sur le jeu d'évaluation, les couples (score, bonne réponse ou non) servent
  à ajuster une régression isotone, une par source, qui transforme le score en probabilité.
  La table de calibration est enregistrée dans la base gold.
- Affichage : probabilité calibrée et libellé (« très probable » ≥ 0,9, « probable » ≥ 0,6,
  « à vérifier » en dessous). Tant qu'une source n'est pas calibrée, on n'affiche que le rang
  et la mention « non calibré », jamais un pourcentage.
- Jeu d'évaluation :
  - exemples **synthétiques** : notices INSEE dont on bruite les noms, prénoms et âges avec un
    générateur d'erreurs de transcription (lettres manuscrites confondues comme C/G, U/N, M/N
    ou E/C, lettres perdues ou ajoutées, âges arrondis), réglé sur un taux de 15 à 20 % ;
  - exemples **réels** : correspondances validées à la main, au jalon 7 notamment. La
    calibration s'améliore donc avec l'usage.
- Un test de non-régression fait échouer la CI si le rappel ou la qualité de calibration
  (score de Brier) se dégrade sur le jeu d'évaluation des fixtures.

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

Évolutions du pivot exigées par la conception de la recherche (à faire en premier) :

- [ ] `Mention.date_naissance_brute: str | None` : date telle qu'écrite dans la source (R3)
- [ ] `Mention.annee_naissance_min` / `annee_naissance_max: int | None` : remplis en silver,
  avec validation `min ≤ max` (R3)
- [ ] Énumération `NatureNom` (`naissance`, `marital`, `inconnue`) et
  `Mention.nature_nom: NatureNom | None`, remplie à l'ingestion (R2)
- [ ] Reporter ces champs dans `schemas.py` dans le même ordre et compléter les tests

Ingestion :

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
  - date de naissance : `date_naissance_brute` toujours ; `date_naissance` seulement si complète
  - `nature_nom = naissance` (après vérification, R2) ; `confiance_source = 1.0`
- [ ] Gestion des anomalies : codes lieux invalides, lignes tronquées → lignes rejetées
  comptées et journalisées, jamais d'arrêt sur une ligne
- [ ] Lecture en flux et écriture Parquet par lots (les fichiers annuels font des centaines de
  Mo) ; partitionnement de `data/bronze/insee_deces/` par fichier source
- [ ] Ingestion idempotente : réingérer un fichier redonne les mêmes identifiants
- [ ] CLI minimale (`[project.scripts]`) : `doudoumil ingest insee <fichier>`
- [ ] Fixture de quelques lignes (inventées ou anonymisées) dans `tests/fixtures/` et tests :
  découpage, dates partielles, anomalies, idempotence, conformité au schéma
- [ ] CI GitHub Actions : `ruff check`, `ruff format --check`, `pytest`

**Décisions**
- Clé naturelle de l'`acte_id` : `(fichier, n° de ligne)` ne dédoublonne pas les
  recouvrements entre fichiers mensuels et annuels. Option proposée : clé de contenu
  `(date de décès, code lieu de décès, n° d'acte)`, avec `(fichier, ligne)` gardés en provenance
  (`cote`, `vue`).
- Bibliothèque de CLI : `argparse` (aucune dépendance) ou `typer`.

**Démo** : `uv run doudoumil ingest insee tests/fixtures/deces-extrait.txt` puis lecture du
Parquet produit.

---

## Jalon 3 — Normalisation → silver

**Objectif** : produire `data/silver/` avec `nom_norm`, `prenoms_norm`, `nom_phonetique`,
les intervalles de naissance et des lieux ramenés au Code officiel géographique.

- [ ] `normalize/noms.py` : majuscules, suppression des accents, des apostrophes et tirets
  normalisés, particules (`LE`, `DE`, `D'`, `DU`, `LA`…) conservées mais normalisées, espaces
  multiples ; tests sur des cas réels (« LE GOFF », « D'HERVÉ », « LE-GOFF »)
- [ ] `normalize/prenoms.py` : découpage des composés et table d'équivalences (R4)
- [ ] `normalize/phonetique.py` : code phonétique adapté au français, appliqué aux noms et
  aux prénoms (canaux A et C de R1)
- [ ] `normalize/dates.py` : calcul de `annee_naissance_min/max` depuis une date complète, une
  date partielle ou un âge (R3)
- [ ] `normalize/lieux.py` : référentiel COG INSEE (communes actuelles + historique des
  fusions et changements de nom) pour relier un libellé ancien à un code
- [ ] Étape silver : lit bronze, écrit silver (nouveaux fichiers, bronze intact)
- [ ] CLI : `doudoumil normalize`
- [ ] Tests de propriétés : la normalisation est idempotente (`f(f(x)) == f(x)`)

**Décisions**
- Algorithme phonétique : Soundex français, Phonex, FONEM (pensé pour les patronymes
  français) ou Beider-Morse ; à comparer sur un échantillon de variantes connues.
- Livraison du référentiel COG : téléchargé à la demande dans `data/ref/` ou extrait versionné.

**Démo** : avant/après sur quelques noms (`LE GOFF` / `Legoff` / `LE-GOFF` → même clé) et
prénoms (`Jn Bte` → `JEAN BAPTISTE`).

---

## Jalon 4 — Index et recherche → gold

**Objectif** : une base DuckDB dans `data/gold/` interrogeable avec tolérance aux variantes,
chaque résultat portant un score calibré et sa provenance (voir R1 à R5).

- [ ] Ajouter `duckdb` aux dépendances
- [ ] Construction de la base gold depuis silver : tables `actes` et `mentions`, index sur
  `nom_phonetique`, `nom_norm`, `annee`, `departement`, `annee_naissance_min/max` ; table
  des clés phonétiques des prénoms ; table des noms distincts avec leur nombre d'occurrences
  (canal B)
- [ ] Présélection à trois canaux A, B, C, union et dédoublonnage des candidats (R1)
- [ ] Composantes du score : nom (Jaro-Winkler / Levenshtein intégrés à DuckDB), prénoms
  (R4), naissance (R3), lieu ; valeur neutre et pondération par `confiance_source` (R5)
- [ ] Règle des noms `marital` et option `--conjoint` (R2)
- [ ] Résultat : acte + mention + score + probabilité calibrée et libellé + canaux +
  provenance (`depot`, `cote`, `vue`, `url_image`)
- [ ] CLI : `doudoumil index` et
  `doudoumil cherche "LE GOFF Marie" --naissance 1880-1885 --lieu 29 [--conjoint NOM]`
- [ ] Générateur d'erreurs de transcription et jeu d'évaluation synthétique (R5)
- [ ] Mesures : rappel de la présélection, précision et rappel du classement, score de Brier
- [ ] Calibration par source enregistrée dans gold ; test de non-régression en CI (R5)
- [ ] Mesure des performances sur un fichier annuel complet, dont la durée du canal B
  (objectif : moins d'une seconde par requête)

**Décisions**
- Base gold reconstruite entièrement ou mise à jour incrémentale.
- Régression isotone codée dans le projet (algorithme PAV, quelques dizaines de lignes) ou
  dépendance à scikit-learn.

**Démo** : recherche approchée en ligne de commande sur un fichier INSEE réel, dont une
notice volontairement mal orthographiée retrouvée par le canal B.

---

## Jalon 5 — Ingestion Socface (recensements) → bronze/silver

**Objectif** : ajouter les recensements transcrits automatiquement, source bruitée qui
justifie la recherche approchée.

- [ ] Étudier l'accès et le format des données Socface (export, champs, structure ménage /
  individu, score de transcription disponible ou non) et le consigner dans
  `notebooks/` + CLAUDE.md
- [ ] Parseur : un acte `recensement` par feuillet ou ménage, une mention par individu
  (`chef_menage`, `epouse`, `enfant`, `autre`…), âge, profession, lieu de naissance brut
- [ ] `nature_nom` : `marital` pour les épouses et veuves, `naissance` pour les enfants du
  chef de ménage, `inconnue` sinon (R2)
- [ ] Âge → intervalle de naissance avec la tolérance des recensements (R3)
- [ ] `confiance_source` dérivée du score de transcription s'il existe, sinon valeur fixe
  mesurée sur un échantillon
- [ ] Réutiliser intégralement les étapes silver et gold existantes
- [ ] Notebook d'exploration de la qualité (taux d'erreur, champs vides, distribution des âges
  et part des âges ronds)
- [ ] Calibration propre à Socface et réévaluation sur le jeu d'évaluation enrichi (R5)

**Décisions**
- Granularité de l'acte (feuillet, ménage ou maison).
- Noms laissés vides ou remplacés par « id. » sur la feuille : reprendre le nom du chef de
  ménage en le signalant comme déduit, ou laisser vide et compter sur le canal C.

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

**Objectif** : proposer, pour chaque individu de l'arbre, les notices candidates avec une
probabilité calibrée.

- [ ] Lecture GEDCOM (5.5.1, et 7 si besoin) : individus, noms, dates et lieux de naissance et
  décès, filiations, conjoints
- [ ] Normalisation des individus avec les mêmes fonctions que silver (dates en intervalles :
  « vers 1850 », « avant 1860 »…)
- [ ] Recherche de chaque individu par le moteur du jalon 4 ; pour une femme mariée, requête
  avec son nom de naissance **et** avec le nom de chaque conjoint (R2)
- [ ] Score de rapprochement enrichi de la cohérence familiale (parents, conjoint, enfants
  présents dans le même ménage) ; seuils « certain / probable / à vérifier »
- [ ] Export des candidats (CSV ou table DuckDB) avec provenance, pour validation manuelle
- [ ] Mémorisation des validations et rejets manuels, qui ne sont pas reproposés et
  alimentent le jeu d'évaluation réel (R5)
- [ ] `GET /individus/{id}/candidats` dans l'API

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
