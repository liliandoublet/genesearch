# Plan de développement — doudoumil-search

**But** : un moteur de recherche généalogique personnel, sur ton ordinateur, qui remplace Filae
pour les trois usages qui comptent : la **recherche nominative**, les **recensements
transcrits** et l'accès aux **images des actes**, sur toute la France.

Légende : `[x]` fait · `[~]` en cours · `[ ]` à faire · **Décision** = choix à trancher (et à
consigner dans CLAUDE.md une fois tranché).

---

## 1. Périmètre

**Dans le périmètre**
- Recherche approchée sur des notices nominatives venant de sources publiques françaises.
- Recensements 1836-1936, avec la vue du foyer complet.
- Lien vers l'image de l'acte original, ou affichage intégré quand l'archive le permet.
- Interface web locale (ouverte dans le navigateur, servie sur `127.0.0.1` uniquement).
- Notes et favoris personnels sur les notices trouvées.

**Hors périmètre**
- L'arbre généalogique : il est construit par ton propre code à partir du GEDCOM. Le
  rapprochement avec l'arbre reste une option en fin de plan (jalon 9).
- Toute mise en ligne ou republication des données : usage strictement personnel, dans le
  respect des conditions d'utilisation de chaque source.
- L'aspiration massive d'un site sans autorisation : on n'utilise que des exports officiels,
  des API documentées ou des requêtes ponctuelles autorisées.

---

## 2. Ce que Filae t'apporte et par quoi on le remplace

| Usage Filae | Remplacement | Source | Statut de l'accès | Jalon |
|---|---|---|---|---|
| Décès depuis 1970 | Fichier des personnes décédées (≈ 25 M) | INSEE, data.gouv.fr | ouvert, mis à jour chaque mois | 2 |
| Recensements 1836-1936 transcrits | Base Socface (291 M de personnes en mars 2026, ≈ 400 M annoncées) | FranceArchives, Base de noms | consultation gratuite ; **export en masse à vérifier** | 6 |
| Morts pour la France 1914-1918 | Base Mémoire des hommes (≈ 1,3 M) | ministère des Armées | téléchargeable ; licence à vérifier | 8 |
| Registres matricules | Index de la Base de noms (ex-Grand Mémorial, ≈ 40 AD) | FranceArchives | **accès en masse à vérifier** | 8 |
| Naissances, mariages, décès avant 1970 (index Filae) | Pas d'index national ouvert : localisateur de registres + import de tes relevés | inventaires FranceArchives (Licence Ouverte), relevés personnels | partiel | 7, 8 |
| Images des actes | Liens vers les visionneuses des AD, affichage IIIF intégré quand disponible | sites des AD, FranceArchives | variable selon l'AD | 7 |

**Le manque principal** : les index d'état civil d'avant 1970 que Filae a constitués
lui-même n'ont pas d'équivalent ouvert. Le plan le compense de trois façons :
1. Le **localisateur de registres** (jalon 7) : pour une personne trouvée dans un recensement
   ou un décès, il propose directement les registres de sa commune de naissance pour les années
   probables, avec le lien vers les images.
2. Un **connecteur de relevés** (jalon 8) importe tout relevé que tu obtiens légitimement
   (cercle généalogique, tes propres transcriptions, exports de ton arbre).
3. Les recensements couvrent un siècle de population et servent de pivot pour retrouver les
   actes.

---

## 3. Préalable P — Accès aux sources (en parallèle des jalons 2 à 5)

Ce travail d'enquête conditionne les jalons 6 à 8. Il se fait pendant qu'on construit la chaîne
sur INSEE, dont l'accès est certain. Les résultats sont consignés dans le tableau du §2 et dans
CLAUDE.md.

- [ ] **Socface** : vérifier s'il existe un export officiel, une API, ou si les notices sont
  dans le dump RDF (`data-dump.francearchives.gouv.fr/rdf/`) ou le point SPARQL
  (`sparql.francearchives.gouv.fr`) ; relever la licence. Si rien n'existe : écrire à
  FranceArchives et à l'INED pour demander un export (démarche à faire par toi, je prépare le
  message).
- [ ] **Registres matricules** (Base de noms) : mêmes vérifications.
- [ ] **Morts pour la France** : trouver la page de téléchargement actuelle, le format, la
  licence.
- [ ] **Inventaires d'archives** (data.gouv.fr, XML APE-EAD, Licence Ouverte) : vérifier que les
  registres d'état civil y sont décrits par commune, type et période, avec le lien vers les
  images numérisées.
- [ ] **Images** : pour les AD partenaires de Socface, relever le logiciel de visionneuse, le
  motif des liens vers une vue, et la présence de manifestes IIIF.
- [ ] **INSEE décès** : confirmer la licence et le format exact.
- [ ] **Volume** : mesurer sur un département pilote la place disque et la mémoire
  nécessaires, et extrapoler à la France entière (Socface seul représente plusieurs centaines
  de millions de lignes).

**Plans de repli pour une source sans export** (par ordre de préférence) :
1. export obtenu sur demande ;
2. connecteur « à la demande » qui interroge la source pour une commune ou un nom précis, si
   ses conditions d'utilisation le permettent, avec un cache local et un débit limité ;
3. lien de recherche pré-rempli vers le site de la source depuis notre interface.

---

## 4. Ordre des jalons

1. Une chaîne complète sur INSEE décès (jalons 2 à 4), source fiable et accessible.
2. L'interface web (jalon 5) : dès ce stade, le moteur est utilisable au quotidien.
3. Les recensements (jalon 6), la plus grosse valeur, selon le résultat du préalable P.
4. Les images et le localisateur de registres (jalon 7).
5. Les autres sources nationales et tes relevés (jalon 8).
6. En option, le rapprochement avec ton arbre (jalon 9), puis les finitions (jalon 10).

---

## 5. Conception de la recherche

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

- Canal B : la base gold tient la liste des noms normalisés distincts avec leur nombre
  d'occurrences. Le nom de la requête est comparé à **tous** ces noms, pas aux mentions :
  distance d'édition ≤ 2 ou Jaro-Winkler ≥ 0,85 (valeurs de départ). Les mentions portant l'un
  des noms retenus deviennent candidates. Les erreurs de transcription multiplient les noms
  distincts : si la comparaison complète est trop lente, un préfiltre (trigrammes communs,
  département de la requête) la réduit, mais il ne doit pas faire baisser le rappel mesuré.
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
- Option de requête `--conjoint NOM` (champ « nom du conjoint » dans l'interface) : le nom du
  mari est comparé au nom `marital` du candidat et compte alors normalement.
- Le résultat signale « nom d'épouse probable » pour que l'utilisateur sache pourquoi le nom ne
  correspond pas.
- Au jalon 9 (optionnel), l'arbre GEDCOM fournit le nom de naissance et le conjoint : la
  recherche lance automatiquement les deux variantes.

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
    générateur d'erreurs de transcription (lettres manuscrites confondues comme C/G, U/N, M/N,
    E/C ou f/s long, lettres perdues ou ajoutées, âges arrondis), réglé sur un taux de 15 à
    20 % ;
  - exemples **réels** : résultats que tu marques « c'est bien lui / ce n'est pas lui » dans
    l'interface (jalon 5). La calibration s'améliore donc avec l'usage.
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
- [ ] Téléchargement des fichiers depuis data.gouv.fr (`doudoumil telecharge insee`), avec
  reprise et somme de contrôle
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
- [ ] Mesure des performances sur le fichier INSEE complet (≈ 25 M), dont la durée du canal B
  (objectif : moins d'une seconde par requête)

**Décisions**
- Base gold reconstruite entièrement ou mise à jour incrémentale.
- Régression isotone codée dans le projet (algorithme PAV, quelques dizaines de lignes) ou
  dépendance à scikit-learn.

**Démo** : recherche approchée en ligne de commande sur le fichier INSEE complet, dont une
notice volontairement mal orthographiée retrouvée par le canal B.

---

## Jalon 5 — Interface web locale

**Objectif** : remplacer l'écran de recherche de Filae par une interface dans ton navigateur.
À la fin de ce jalon, le moteur sert au quotidien, au moins pour les décès depuis 1970.

- [ ] Ajouter `fastapi`, `uvicorn` et `jinja2` ; serveur limité à `127.0.0.1`
- [ ] `doudoumil serve` démarre le serveur et ouvre le navigateur
- [ ] **Recherche simple** : un champ « nom prénom » ; **recherche avancée** : nom, prénoms,
  sexe, naissance (année ou intervalle), lieu (commune ou département, avec autocomplétion sur
  le référentiel COG), période de l'acte, type de source, nom du conjoint (R2)
- [ ] **Résultats** : tableau trié par probabilité, avec libellé (R5), source, date, lieu, rôle,
  canaux de présélection (R1), lien vers l'image ; filtres latéraux avec compteurs (source,
  département, décennie) ; pagination
- [ ] **Fiche notice** : l'acte, toutes les personnes qui y figurent, la provenance complète,
  le lien vers l'image et une citation de source prête à copier
- [ ] **Mes trouvailles** : favoris, notes et verdict « c'est bien lui / ce n'est pas lui »,
  stockés dans une base personnelle séparée de gold. Les identifiants étant déterministes, une
  reconstruction de gold ne perd rien. Les verdicts alimentent la calibration (R5)
- [ ] Export CSV des résultats et des trouvailles
- [ ] API JSON sous-jacente (`/api/recherche`, `/api/actes/{acte_id}`), documentée par OpenAPI
- [ ] Tests : `TestClient` pour l'API, Playwright (Chromium déjà installé) pour les parcours
  principaux (rechercher, ouvrir une fiche, marquer une trouvaille)
- [ ] (optionnel) Carte de répartition d'un nom par département et par décennie

**Décisions**
- Pages rendues côté serveur (Jinja2, avec un peu de htmx) ou application JavaScript séparée.
  Proposition : rendu serveur, pour éviter toute chaîne de compilation JavaScript.

**Démo** : `uv run doudoumil serve`, recherche d'une personne décédée, fiche, trouvaille notée.

---

## Jalon 6 — Recensements Socface

**Objectif** : retrouver un foyer dans les recensements 1836-1936, source bruitée qui justifie
la recherche approchée. Le mode d'accès dépend du préalable P.

- [ ] Connecteur selon l'accès obtenu : import de l'export officiel, ou connecteur à la demande
  avec cache (plan de repli du préalable P)
- [ ] Parseur : un acte `recensement` par ménage, une mention par individu (`chef_menage`,
  `epouse`, `enfant`, `autre`…), âge, profession, lieu de naissance brut, page et position de la
  ligne pour retrouver l'image
- [ ] `nature_nom` : `marital` pour les épouses et veuves, `naissance` pour les enfants du chef de
  ménage, `inconnue` sinon (R2)
- [ ] Âge → intervalle de naissance avec la tolérance des recensements (R3)
- [ ] `confiance_source` dérivée du score de transcription s'il existe, sinon valeur fixe
  mesurée sur un échantillon
- [ ] Ingestion par département (`doudoumil ingest socface --departement 29`) et partitions
  Parquet par département, pour importer la France progressivement
- [ ] Réutiliser intégralement les étapes silver et gold existantes
- [ ] **Vue du foyer** : depuis un résultat, le ménage complet ; navigation d'un recensement à
  l'autre pour la même commune
- [ ] **Recherche par composition du foyer** : retrouver un ménage où vivent ensemble deux
  personnes données (par exemple un couple), ce qui compense fortement les erreurs de
  transcription sur un seul nom
- [ ] Notebook d'exploration de la qualité (taux d'erreur, champs vides, part des âges ronds)
- [ ] Calibration propre à Socface et réévaluation sur le jeu d'évaluation enrichi (R5)
- [ ] Mesure des performances à l'échelle de plusieurs départements, puis de la France entière

**Décisions**
- Granularité de l'acte (feuillet, ménage ou maison).
- Noms laissés vides ou remplacés par « id. » sur la feuille : reprendre le nom du chef de
  ménage en le signalant comme déduit, ou laisser vide et compter sur le canal C.

**Démo** : recherche d'un ancêtre dans un recensement, vue de son foyer, ouverture de la page
du registre.

---

## Jalon 7 — Images des actes et localisateur de registres

**Objectif** : de chaque résultat, aller à l'image du document ; et pour l'état civil non
indexé, savoir dans quel registre chercher.

- [ ] Référentiel versionné des dépôts (`ref/depots.csv`) : pour chaque AD, logiciel de
  visionneuse, motif de lien vers une vue, support IIIF (résultats du préalable P)
- [ ] Résolveur de liens : provenance d'une notice (dépôt, cote, vue) → lien direct vers la
  vue sur le site de l'AD
- [ ] Visionneuse intégrée pour les AD qui exposent des manifestes IIIF (OpenSeadragon ou
  Mirador embarqué dans le projet), avec zoom sur la ligne quand la position est connue ;
  sinon, ouverture de la page de l'AD dans un nouvel onglet
- [ ] **Localisateur de registres** : index (commune, type de registre, période, cote, lien)
  construit depuis les inventaires FranceArchives (APE-EAD, Licence Ouverte)
  - depuis une notice : « chercher l'acte de naissance » propose les registres de la commune de
    naissance pour l'intervalle d'années probable (R3) ; idem pour le mariage et le décès ;
  - page autonome : commune + année → registres disponibles et liens
- [ ] Enregistrement d'une image dans « Mes trouvailles » (copie locale personnelle,
  à l'unité, jamais en masse)

**Décisions**
- Visionneuse IIIF : OpenSeadragon (léger) ou Mirador (complet).

**Démo** : depuis une personne trouvée dans un recensement, ouverture du registre de
naissances de sa commune pour l'année probable.

---

## Jalon 8 — Autres sources nationales et relevés personnels

**Objectif** : élargir la couverture aux sources ouvertes restantes et à tes propres relevés.

- [ ] Évolution du pivot : nouvelles valeurs de `Source` (morts pour la France, registres
  matricules, relevé) et de `TypeActe` si nécessaire (fiche militaire, matricule)
- [ ] Connecteur **Morts pour la France 1914-1918** (Mémoire des hommes)
- [ ] Connecteur **registres matricules** (Base de noms), selon l'accès obtenu au préalable P
- [ ] **Connecteur de relevés** : n'importe quel CSV ou tableur, avec un fichier de
  correspondance des colonnes (`releves/<nom>.toml`) vers le pivot ; provenance et
  `confiance_source` indiquées dans ce fichier
- [ ] Calibration de chaque nouvelle source (R5)
- [ ] Filtres par source dans l'interface et dans la CLI

**Démo** : un poilu retrouvé dans la base des Morts pour la France, puis dans le recensement
de 1911 de sa commune.

---

## Jalon 9 — Rapprochement avec ton arbre GEDCOM (optionnel)

**Objectif** : signaler les notices qui concernent un individu de ton arbre et proposer des
candidats pour chacun. Ton arbre lui-même reste géré par ton code.

- [ ] Lecture GEDCOM (réutiliser ton code de lecture s'il est en Python, sinon une
  bibliothèque comme `python-gedcom` ou `ged4py`)
- [ ] Normalisation des individus avec les mêmes fonctions que silver (« vers 1850 »,
  « avant 1860 » → intervalles R3)
- [ ] Recherche de chaque individu par le moteur ; pour une femme mariée, avec son nom de
  naissance **et** le nom de chaque conjoint (R2)
- [ ] Score enrichi de la cohérence familiale (parents, conjoint, enfants dans le même foyer)
- [ ] Dans l'interface : badge « dans mon arbre » sur les résultats, page des candidats par
  individu, verdicts réutilisés pour la calibration (R5)
- [ ] Export des candidats validés vers un format que ton code GEDCOM peut relire

**Décisions**
- Score de rapprochement fait main ou appui sur `splink` (rapprochement probabiliste sur
  DuckDB).

---

## Jalon 10 — Finitions

- [ ] Commande unique `doudoumil pipeline` (téléchargement → bronze → silver → gold)
- [ ] Mise à jour mensuelle d'INSEE décès sans tout reconstruire
- [ ] Sauvegarde et restauration de « Mes trouvailles »
- [ ] README complet : installation, place disque nécessaire, ajout d'une source, exemples
- [ ] Journalisation homogène et messages d'erreur en français

---

## Transverse (à chaque jalon)

- Tests : chaque module a ses tests ; les fixtures restent petites et sans données réelles
  identifiantes.
- Vérifications vertes avant chaque commit : `uv run ruff check`, `uv run ruff format --check`,
  `uv run pytest`.
- Respect des conditions d'utilisation de chaque source ; licence notée dans le tableau du §2.
- Mettre à jour la section « Démonstration » du README, cocher ce plan et mettre à jour CLAUDE.md.
