# Plan de développement — doudoumil-search

**But** : un **atelier de recherche généalogique** sur ton ordinateur, **complémentaire de
Filae** et des autres sites. Filae (et Geneanet, FamilySearch…) sert à **chercher** dans ses
index ; l'atelier sert à **travailler** : ranger ce que tu trouves par dossier (pour toi ou
pour un client), vérifier une liste entière d'un coup, ouvrir le bon registre aux archives,
citer les sources et rendre un travail propre.

> **Réorientation du 2026-10-11.** Le plan initial visait à remplacer Filae. Les index
> d'état civil d'avant 1970 que Filae a constitués (des dizaines de millions d'actes
> transcrits) n'ont pas d'équivalent ouvert et ne sont pas reconstituables à notre échelle :
> pour chercher, un abonnement reste le bon choix, y compris pour une activité commerciale.
> Tout ce qui est déjà fait (décès INSEE, relevés, interface, sauvegarde) sert le nouvel
> objectif ; les jalons qui visaient à remplacer les index de Filae passent en sommeil.

Légende : `[x]` fait · `[~]` en cours · `[ ]` à faire · **Décision** = choix à trancher (et à
consigner dans CLAUDE.md une fois tranché).

---

## 1. Périmètre

**Dans le périmètre**
- **Dossiers de recherche** : un par client ou par famille, avec les personnes recherchées,
  les notices retenues (trouvées dans l'atelier ou saisies depuis Filae et les autres sites),
  les notes, les verdicts et les citations de sources.
- **Recherche approchée** dans les sources ouvertes téléchargeables (décès INSEE) et dans tes
  sources privées (relevés de cercles, documents fournis par un client).
- **Vérification en lot** d'une liste ou d'un arbre (GEDCOM) contre les décès INSEE : qui est
  décédé, quand, où.
- **Passerelles** : liens de recherche pré-remplis vers Filae, Geneanet, FamilySearch,
  MatchID et FranceArchives, et ouverture du bon registre sur le site des archives
  départementales. Ce sont des liens que tu ouvres toi-même, jamais des requêtes
  automatiques.
- **Rendu** : export d'un dossier (tableur, rapport avec sources) pour toi ou pour un client.
- Interface web locale (ouverte dans le navigateur, servie sur `127.0.0.1` uniquement).

**Hors périmètre**
- Reconstituer les index de Filae ou d'un autre site, ou copier, extraire et revendre leurs
  données.
- Interroger automatiquement un site (Filae, archives…) : l'atelier ne fait que préparer des
  liens.
- L'arbre généalogique lui-même : il reste construit par ton propre code à partir du GEDCOM.
- Toute mise en ligne ou republication des données.

**Activité commerciale : précautions**
- **Données des clients** : la famille vivante d'un client relève de la protection des
  données personnelles. Tout reste sur ton ordinateur ; un dossier se supprime entièrement à
  la fin d'une mission ; une durée de conservation est à fixer.
- **Conditions d'utilisation** des sites payants : vérifier que l'usage professionnel est
  permis (ou s'il existe une offre dédiée).
- **Sources** : un rapport cite l'acte original (archives, cote, vue), pas l'index qui y a
  mené.

---

## 2. Qui fait quoi : les sites de recherche et l'atelier

| Besoin | Où le faire | Pourquoi |
|---|---|---|
| Trouver un acte d'état civil d'avant 1970 | Filae, Geneanet, FamilySearch | leurs index n'ont pas d'équivalent ouvert |
| Recensements 1836-1936 | FranceArchives (Socface) en ligne, Filae | pas d'export en masse connu ; import local seulement si un export est obtenu |
| Décès depuis 1970 | **l'atelier** (fichier INSEE), MatchID en ligne | l'atelier ajoute la vérification en lot et le rangement par dossier |
| Vérifier l'acte original | site des archives départementales, **ouvert depuis l'atelier** | le localisateur trouve le registre et la vue |
| Ranger, noter, citer, rendre le travail | **l'atelier** | ce que les sites font mal : dossiers par client, données gardées chez toi |
| Relevés privés, documents d'un client | **l'atelier** | sources que les sites n'ont pas |

---

## 3. Préalable P — Accès aux sources (en parallèle des jalons 2 à 5)

> **Depuis la réorientation**, seules restent prioritaires les vérifications de l'INSEE, des
> visionneuses des archives départementales et des adresses de recherche des sites (pour les
> passerelles du jalon 13). Socface, registres matricules et Morts pour la France sont en
> sommeil : à reprendre seulement si un export est obtenu.

- [ ] **Adresses de recherche des sites** (jalon 13) : pour Filae, Geneanet, FamilySearch,
  MatchID et FranceArchives, relever le format d'une adresse de recherche pré-remplie (nom,
  prénom, années, lieu) et vérifier que les conditions d'utilisation permettent ces liens.

Le reste de ce travail d'enquête conditionnait les jalons 6 à 8, désormais en sommeil (sauf
les inventaires d'archives et les visionneuses, utiles au localisateur du jalon 13). Les
résultats sont consignés dans le tableau du §2 et dans CLAUDE.md.

- [~] **Socface** : vérifier s'il existe un export officiel, une API, ou si les notices sont
  dans le dump RDF (`data-dump.francearchives.gouv.fr/rdf/`) ou le point SPARQL
  (`sparql.francearchives.gouv.fr`) ; relever la licence. Message de demande d'export rédigé
  (`docs/demande-export-socface.md`), **à envoyer par toi** à FranceArchives et à l'INED ; le
  dump RDF et le SPARQL restent à examiner (sites inaccessibles depuis l'environnement de
  développement).
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

**Faits** : socle et modèle pivot (0-1), chaîne INSEE (2-4), interface web (5), relevés
(jalon 8, partie relevés), commande unique et sauvegarde (jalon 10, en partie).

**Suite, depuis la réorientation** :
1. **Dossiers de recherche** (jalon 11) : le cœur de l'atelier ; les trouvailles actuelles
   deviennent un premier dossier.
2. **Vérification en lot** (jalon 12) : une liste ou un arbre contre les décès INSEE ; reprend
   la lecture GEDCOM de l'ancien jalon 9.
3. **Passerelles** (jalon 13) : liens pré-remplis vers les sites de recherche et localisateur
   de registres ; reprend la partie « liens » de l'ancien jalon 7.
4. **Rendu pour le client** (jalon 14).
5. **Finitions** (jalon 10) au fil de l'eau, en particulier d'après les tests manuels.

**En sommeil** (à reprendre seulement si une source devient accessible en masse) :
recensements Socface (jalon 6), visionneuse d'images intégrée (jalon 7), Morts pour la France
et registres matricules (jalon 8).

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
  - sujet d'un acte de naissance ou de baptême de l'année `Y` → `[Y, Y]`, ou `[Y − 1, Y]` si
    l'acte est de janvier ou sans date complète (enfant né fin décembre) ;
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
  La calibration est enregistrée dans `data/gold/calibration.json`, à côté de la base.
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

- [x] `Mention.date_naissance_brute: str | None` : date telle qu'écrite dans la source (R3)
- [x] `Mention.annee_naissance_min` / `annee_naissance_max: int | None` : remplis en silver,
  avec validation `min ≤ max` (R3)
- [x] Énumération `NatureNom` (`naissance`, `marital`, `inconnue`) et
  `Mention.nature_nom: NatureNom | None`, remplie à l'ingestion (R2)
- [x] Reporter ces champs dans `schemas.py` dans le même ordre et compléter les tests

Ingestion :

- [x] Nettoyage : supprimer le `main.py` généré par `uv init`
- [~] Documenter le format dans `ingest/insee_deces.py` : enregistrements à largeur fixe
  (nom*prénoms/ sur 80 caractères, sexe, date de naissance, code et libellé du lieu de
  naissance, pays, date de décès, code du lieu de décès, numéro d'acte). Documenté ; **reste à
  vérifier sur un fichier réel** (positions, encodage, largeurs en caractères ou en octets) :
  data.gouv.fr et insee.fr sont bloqués dans l'environnement de développement
- [x] Parseur ligne → `Acte` (type `deces`, `annee` = année du décès) + `Mention` (rôle `sujet`)
  - séparer `NOM*PRENOMS/` en `nom_brut` / `prenoms_bruts`
  - sexe `1`/`2` → `M`/`F`
  - lieu de décès → `commune_code_insee` et `departement` (2A/2B, 97x, 99 = étranger)
  - lieu de naissance → `lieu_naissance_brut` / `lieu_naissance_code_insee`
  - date de naissance : `date_naissance_brute` toujours ; `date_naissance` seulement si complète
  - `nature_nom = naissance` (à confirmer sur la documentation, R2) ; `confiance_source = 1.0`
- [x] Gestion des anomalies : codes lieux invalides, lignes tronquées → lignes rejetées
  comptées et journalisées, jamais d'arrêt sur une ligne
- [x] Lecture en flux et écriture Parquet par lots (les fichiers annuels font des centaines de
  Mo) ; partitionnement de `data/bronze/insee_deces/` par fichier source
- [x] Ingestion idempotente : réingérer un fichier redonne les mêmes identifiants
- [~] Téléchargement des fichiers depuis data.gouv.fr (`doudoumil telecharge insee`), avec
  reprise et somme de contrôle. Testé contre un serveur local qui imite l'API ; **reste à
  vérifier sur le vrai catalogue** (identifiant du jeu de données, noms des fichiers)
- [x] CLI minimale (`[project.scripts]`) : `doudoumil ingest insee <fichier>`
- [x] Fixture de quelques lignes (inventées ou anonymisées) dans `tests/fixtures/` et tests :
  découpage, dates partielles, anomalies, idempotence, conformité au schéma
- [x] CI GitHub Actions : `ruff check`, `ruff format --check`, `pytest`

**Décisions tranchées**
- Clé naturelle de l'`acte_id` : clé de contenu `(date de décès, code lieu de décès, n° d'acte)`,
  ou, sans numéro d'acte ni commune, `(nom et prénoms, date de naissance, date de décès,
  commune)`. Un décès présent dans un fichier mensuel et dans le fichier annuel garde ainsi le
  même identifiant ; `(fichier, ligne)` restent en provenance (`cote`, `vue`). Les doublons
  sont conservés en bronze et éliminés en silver.
- Bibliothèque de CLI : `argparse` (aucune dépendance).
- Départements : le pivot accepte aussi les collectivités d'outre-mer (975 à 978, 984 à 989),
  présentes dans les lieux de décès.
- Une ligne n'est rejetée que si l'année du décès est illisible ou improbable ; les autres
  défauts sont tolérés et comptés comme anomalies.
- Ingestion en parallèle par fichier (`--processus`), en démarrage *spawn* : environ
  12 000 lignes par seconde et par processus, mesurées sur des lignes générées.

**Démo** : `uv run doudoumil ingest insee tests/fixtures/deces-extrait.txt` puis lecture du
Parquet produit.

---

## Jalon 3 — Normalisation → silver

**Objectif** : produire `data/silver/` avec `nom_norm`, `prenoms_norm`, `nom_phonetique`,
les intervalles de naissance et des lieux ramenés au Code officiel géographique.

- [x] `normalize/noms.py` : majuscules, suppression des accents, des apostrophes et tirets
  normalisés, particules (`LE`, `DE`, `D'`, `DU`, `LA`…) conservées mais normalisées, espaces
  multiples ; tests sur des cas réels (« LE GOFF », « D'HERVÉ », « LE-GOFF »)
- [x] `normalize/prenoms.py` : découpage des composés et table d'équivalences (R4)
- [x] `normalize/phonetique.py` : code phonétique adapté au français, appliqué aux noms et
  aux prénoms (canaux A et C de R1)
- [x] `normalize/dates.py` : calcul de `annee_naissance_min/max` depuis une date complète, une
  date partielle ou un âge (R3)
- [~] `normalize/lieux.py` : référentiel des communes (communes actuelles, déléguées et
  associées, arrondissements, anciens codes) pour relier un code ou un libellé ancien à la
  commune actuelle. **Reste** : les fusions anciennes sans commune déléguée ni ancien code
  conservé, à compléter avec le fichier des mouvements de communes de l'INSEE (insee.fr
  inaccessible depuis l'environnement de développement)
- [x] Dédoublonnage en silver : la partition la plus récente l'emporte, doublons internes
  gardés une fois ; partitions temporaires d'une ingestion interrompue ignorées
- [x] Étape silver : lit bronze, écrit silver (nouveaux fichiers, bronze intact)
- [x] CLI : `doudoumil normalize`
- [x] Tests de propriétés : la normalisation est idempotente (`f(f(x)) == f(x)`)

**Décisions tranchées**
- Algorithme phonétique : adaptation de Soundex2 (F. Brouard), sans troncature à quatre
  caractères, `PH` → `F` partout, `Y` traité comme une voyelle, `H` muet supprimé avant les
  voyelles. Comparé sur des groupes de variantes connues (tests) ; le figer impose de
  reconstruire silver et gold à chaque changement. Les noms courts donnent des clés courtes
  (`MOREAU`, `MARIE` et `MEYER` → `MR`) : le canal A devra trier ses candidats par
  ressemblance avant de les plafonner (jalon 4).
- Référentiel des communes : paquet `@etalab/decoupage-administratif` 6.0.0 (licence MIT,
  données du COG), téléchargé à la demande depuis le registre npm dans `data/ref/communes/`
  (`doudoumil telecharge communes`). Un extrait sert de fixture aux tests.
- Lieux : un code ancien ou d'arrondissement renvoie la commune actuelle, mais garde son
  propre libellé (« Béon » pour 01039) ; un lieu de naissance sans code reçoit un code
  seulement si son nom désigne une seule commune.
- Normalisation calculée une fois par valeur distincte, puis jointe : environ 150 000 lignes
  par seconde, mesurées sur des données générées.

**Démo** : avant/après sur quelques noms (`LE GOFF` / `Legoff` / `LE-GOFF` → même clé) et
prénoms (`Jn Bte` → `JEAN BAPTISTE`) ; voir le README.

---

## Jalon 4 — Index et recherche → gold

**Objectif** : une base DuckDB dans `data/gold/` interrogeable avec tolérance aux variantes,
chaque résultat portant un score calibré et sa provenance (voir R1 à R5).

- [x] Ajouter `duckdb` aux dépendances (et `rapidfuzz` pour les ressemblances côté Python)
- [x] Construction de la base gold depuis silver : tables `actes` et `mentions` (index sur
  les identifiants pour lire les fiches), table `personnes` triée par clé phonétique (DuckDB
  saute les blocs inutiles), table `prenoms` (clés phonétiques, canal C), table `noms` des
  noms distincts avec leur nombre d'occurrences (canal B), table `lieux` (codes ramenés à la
  commune actuelle), `meta` ; la calibration vit à côté, dans `calibration.json`
- [x] Présélection à trois canaux A, B, C, plus un canal « conjoint » (R2), union et
  dédoublonnage des candidats, ordre déterministe (R1)
- [x] Composantes du score : nom (Jaro-Winkler), prénoms (R4), naissance (R3), lieu ; valeur
  neutre et pondération par `confiance_source` (R5)
- [x] Règle des noms `marital` et option `--conjoint` (R2)
- [x] Résultat : acte + mention + score + probabilité calibrée et libellé + canaux +
  provenance (`depot`, `cote`, `vue`, `url_image`)
- [x] CLI : `doudoumil index` et
  `doudoumil cherche "LE GOFF Marie" --naissance 1880-1885 --lieu 29 [--conjoint NOM]`,
  plus `--sexe`, `--annees`, `--source`, `--limite`, `--details`
- [x] Générateur d'erreurs de transcription et jeu d'évaluation synthétique (R5), en deux
  modes : requêtes imprécises (`requete`) et données bruitées repassées par silver et gold
  (`donnees`) ; commandes `doudoumil evalue` et `doudoumil calibre`
- [x] Mesures : rappel de la présélection, rappel au rang 1 et dans les 10 premiers, rang
  réciproque moyen, score de Brier (calibration ajustée sur une moitié des cas, contrôlée
  sur l'autre)
- [x] Calibration par source enregistrée dans gold ; test de non-régression en CI (R5),
  sur une population synthétique dense de 6 000 personnes
- [~] Mesure des performances sur le fichier INSEE complet (≈ 25 M), dont la durée du canal B
  (objectif : moins d'une seconde par requête). **Mesuré sur 4 millions de décès
  synthétiques** (4 cœurs, 15 Go de mémoire) : ingestion 59 s (4 processus), normalisation
  22 s, indexation 70 s, base de 1,73 Go ; requêtes en 40 à 120 ms en médiane, 0,3 s au pire
  (nom courant, nom mal orthographié, sans le nom, épouse avec conjoint). Extrapolation à
  25 M : base d'environ 11 Go, requêtes sous la seconde. **Reste** à mesurer sur les vrais
  fichiers

**Décisions tranchées**
- Base gold reconstruite entièrement à chaque `doudoumil index` (la calibration, rangée à
  côté, n'est pas touchée) ; la mise à jour incrémentale est reportée au jalon 10 si la durée le justifie.
- Régression isotone codée dans le projet (algorithme PAV), sans scikit-learn.
- Canal B : distance d'édition ≤ 2, ramenée à 1 pour les noms de 4 lettres ou moins (deux
  erreurs sur un nom court acceptent presque tout), ou Jaro-Winkler ≥ 0,85 ; longueur à ±3.
- Score des prénoms : 95 % pour la moyenne des meilleures ressemblances, 5 % pour un premier
  prénom identique (un bonus ajouté puis plafonné à 1 s'annulait).
- Naissance : le score s'annule une année après la limite de tolérance,
  `max(0, 1 − écart / (tolérance + 1))`.
- Les petites tables de correspondance passent par un Parquet temporaire pour éviter la
  dépendance à `pyarrow`.
- Table `prenoms` entièrement dénormalisée (toutes les colonnes de `personnes`) : relire des
  candidats par identifiant oblige DuckDB à parcourir toute la table ; le canal C passe de
  234 à 40 ms sur 4 M de personnes, pour une base 35 % plus grosse.
- Fiches lues en deux temps (mentions, puis leurs actes), sans jointure sur toute la table.

**Mesures sur données synthétiques** (40 % d'erreurs de lecture, mode `donnees`, 300 cas) :
avec la clé phonétique seule, 83,7 % des bonnes notices sont présélectionnées ; avec le
canal B, 100 %. Le canal C ne change rien sur ces données, qui ne contiennent ni nom absent
ni nom d'épouse : il est conçu pour les recensements.

**Démo** : recherche approchée en ligne de commande sur le fichier INSEE complet, dont une
notice volontairement mal orthographiée retrouvée par le canal B.

---

## Jalon 5 — Interface web locale

**Objectif** : une interface de recherche dans ton navigateur.
À la fin de ce jalon, le moteur sert au quotidien, au moins pour les décès depuis 1970.

- [x] Ajouter `fastapi`, `uvicorn` et `jinja2` ; serveur limité à `127.0.0.1`
- [x] `doudoumil serve` démarre le serveur et ouvre le navigateur
- [x] **Recherche simple** : un champ « nom prénom » ; **recherche avancée** : nom, prénoms,
  sexe, naissance (année ou intervalle), lieu (commune ou département, avec autocomplétion sur
  le référentiel COG), période de l'acte, type de source, nom du conjoint (R2)
- [x] **Résultats** : tableau trié par probabilité, avec libellé (R5), source, date, lieu, rôle,
  canaux de présélection (R1), lien vers l'image ; filtres latéraux avec compteurs (source,
  département, décennie) ; pagination
- [x] **Fiche notice** : l'acte, toutes les personnes qui y figurent, la provenance complète,
  le lien vers l'image et une citation de source prête à copier
- [x] **Mes trouvailles** : favoris, notes et verdict « c'est bien lui / ce n'est pas lui »,
  stockés dans une base personnelle séparée de gold. Les identifiants étant déterministes, une
  reconstruction de gold ne perd rien. Les verdicts alimentent la calibration (R5)
- [x] Export CSV des résultats et des trouvailles
- [x] API JSON sous-jacente (`/api/recherche`, `/api/actes/{acte_id}`), documentée par OpenAPI
- [x] Tests : `TestClient` pour l'API, Playwright (Chromium déjà installé) pour les parcours
  principaux (rechercher, ouvrir une fiche, marquer une trouvaille)
- [ ] (optionnel) Carte de répartition d'un nom par département et par décennie

**Décisions tranchées**
- Pages rendues côté serveur avec Jinja2, **sans htmx ni framework JavaScript** : de simples
  formulaires, et un petit script (`statique/doudoumil.js`) pour l'autocomplétion des lieux,
  la copie des citations et des adresses sans paramètres vides.
- Les recherches passent dans l'adresse (`GET`) : elles sont partageables et rejouables, et
  la même lecture du formulaire sert aux pages, à l'API JSON et à l'export CSV.
- « Mes trouvailles » dans une base SQLite séparée (`data/perso/trouvailles.sqlite`), avec la
  requête qui a fait apparaître chaque notice ; un verdict ✓ / ✗ y devient un exemple réel
  ajouté aux exemples synthétiques par `doudoumil calibre`.
- Calibration déplacée de la base gold vers `data/gold/calibration.json` : calibrer pendant
  que l'interface tient la base ouverte échouait (DuckDB refuse un écrivain quand la base est
  ouverte ailleurs). Le moteur relit ce fichier s'il change.
- Sécurité du serveur local : écoute sur `127.0.0.1`, hôtes autorisés `localhost` et
  `127.0.0.1` (rebond DNS), envois de formulaires d'une autre origine refusés, adresses de
  retour limitées aux chemins locaux.
- Filtres de la colonne de gauche calculés sur tous les candidats classés ; départements
  nommés ; lieux de naissance codés affichés avec le nom de la commune.
- Tests navigateur avec Playwright et le Chromium de l'environnement (installé par
  `playwright install chromium` dans la CI).

**Démo** : `uv run doudoumil serve`, recherche d'une personne décédée, fiche, trouvaille notée. Voir le README et `docs/captures/`.

---

## Jalon 6 — Recensements Socface

> **En sommeil depuis la réorientation (2026-10-11).** Les recensements se consultent sur
> FranceArchives ou Filae ; le jalon 13 y donne des liens pré-remplis. À reprendre seulement si
> la demande d'export (`docs/demande-export-socface.md`) aboutit.

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

> **En partie repris par le jalon 13 (2026-10-11).** Le référentiel des dépôts, le résolveur
> de liens et le localisateur de registres y passent ; la visionneuse intégrée (IIIF) et la
> copie d'images restent en sommeil.

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

> **Relevés faits ; le reste en sommeil depuis la réorientation (2026-10-11).** Morts pour la
> France et registres matricules se consultent en ligne (Mémoire des hommes, FranceArchives) ;
> connecteurs à reprendre seulement avec un export en masse.

**Objectif** : élargir la couverture aux sources ouvertes restantes et à tes propres relevés.

- [~] Évolution du pivot : nouvelles valeurs de `Source` (morts pour la France, registres
  matricules, relevé) et de `TypeActe` si nécessaire (fiche militaire, matricule) — fait pour
  les relevés (`Source.RELEVE`, `Acte.titre_source`)
- [ ] Connecteur **Morts pour la France 1914-1918** (Mémoire des hommes)
- [ ] Connecteur **registres matricules** (Base de noms), selon l'accès obtenu au préalable P
- [x] **Connecteur de relevés** : n'importe quel CSV ou tableur, avec un fichier de
  correspondance des colonnes (`releves/<nom>.toml`) vers le pivot ; provenance et
  `confiance_source` indiquées dans ce fichier (`ingest/releves.py`, `docs/releves.md`)
- [x] Calibration de chaque nouvelle source (R5) : tirage des cas d'évaluation **par source**
- [x] Filtres par source dans l'interface et dans la CLI (source « Relevés », `--source releve`)

**Décisions tranchées**
- Correspondance en TOML (lu par `tomllib`, sans dépendance) : chaque information est une
  constante ou une colonne, avec `valeurs` (codes du relevé), `defaut` et `format` de date.
  Noms de colonnes comparés sans casse, accents ni espaces ; clés inconnues refusées (fautes de
  frappe) ; colonnes absentes signalées avec la liste des colonnes du tableur.
- Tableurs : CSV (encodage UTF-8, sinon Windows-1252 ; séparateur deviné) avec le module `csv`,
  Excel et OpenDocument avec `fastexcel`, cellules lues en texte.
- Une ligne = un acte ; une mention par personne nommée. Une personne dont seules les colonnes
  partagées avec une personne précédente sont remplies (nom du père repris de l'enfant) est
  ignorée. Sexe déduit du rôle pour les parents et les époux.
- Identifiants : nom du fichier TOML + colonnes `cle` (défaut : numéro de ligne) ; une clé
  répétée reçoit un numéro d'ordre. Rangement : `data/releves/` (fichiers de l'utilisateur, à
  sauvegarder), partition bronze `releve/<nom>/`.
- Silver : code de la commune de l'acte déduit de son nom s'il est unique (dans le département
  s'il est connu) ; naissance du sujet d'un baptême ou d'une naissance déduite de l'année de
  l'acte (R3).
- `doudoumil ingest releve --modele TABLEUR` prépare la correspondance d'après les noms de
  colonnes ; elle ne remplace jamais un fichier existant.
- Évaluation et calibration : `--cas` compte désormais les cas **par source**, pour qu'un petit
  relevé ait ses propres exemples à côté de 25 M de décès.

**Démo** (relevés) : voir le README, « Jalon 8 — relevés en CSV ou Excel ».

---

## Jalon 9 — Rapprochement avec ton arbre GEDCOM (optionnel)

> **Repris par le jalon 12 (2026-10-11)** : la lecture GEDCOM et la recherche de chaque
> individu deviennent la vérification en lot. Le score de cohérence familiale et l'export vers
> ton code GEDCOM restent des options.

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

- [x] Commande unique `doudoumil pipeline` (téléchargement → bronze → silver → gold), relevés
  compris (`pipeline.py`)
- [~] Mise à jour mensuelle d'INSEE décès sans tout reconstruire : `doudoumil pipeline
  --telecharge` ne convertit que le nouveau fichier ; la normalisation de la source et la base
  de recherche sont encore refaites en entier (à mesurer sur les ≈ 25 M de décès)
- [x] Sauvegarde et restauration de « Mes trouvailles » et des relevés (`data/perso/`,
  `data/releves/`) : `doudoumil sauvegarde`, `doudoumil restaure`, lien dans « Mes
  trouvailles » (`sauvegarde.py`)
- [~] Tests manuels sur l'ordinateur de l'utilisateur (`docs/tests-manuels.md`) : vrais
  fichiers INSEE, performances sur la base complète, contrôle sur des personnes connues
  (avec, pour comparaison, ce que donne Filae), vrai relevé ; durée de chaque étape affichée
  par `doudoumil pipeline`
- [ ] README complet : installation, place disque nécessaire, ajout d'une source, exemples
- [ ] Journalisation homogène et messages d'erreur en français

**Décisions tranchées**
- `doudoumil pipeline` compare des dates de modification, à la manière de `make` : une
  partition bronze est refaite si son fichier source (ou la correspondance et le tableur d'un
  relevé) est plus récent ; une source silver si l'une de ses partitions ou le référentiel a
  changé (le dossier de la source compte, pour voir une partition supprimée) ; la base si une
  source silver a changé. `--tout` force tout. Une erreur sur un relevé n'arrête pas le reste ;
  le code de retour la signale. Les archives INSEE ne sont réextraites que si elles sont plus
  récentes que le fichier extrait.
- Sauvegarde = archive zip datée de `data/perso/` et `data/releves/` (le reste se
  reconstruit), avec un manifeste `sauvegarde.json` ; la base SQLite est copiée par l'API de
  sauvegarde de SQLite (cohérente même si l'interface écrit). Restauration : refuse une archive
  sans manifeste ou dont un chemin sortirait de ces dossiers, sauvegarde d'abord l'état
  actuel, ne remplace que les dossiers présents dans l'archive.

---

## Jalon 11 — Dossiers de recherche

**Objectif** : un classeur par client ou par famille, au cœur de l'atelier. Tout ce que tu
trouves, ici ou sur Filae, y est rangé avec sa source.

- [ ] **Dossier** : nom, client ou famille, description, dates d'ouverture et de clôture ;
  dossier actif choisi dans l'interface et dans la CLI
- [ ] Reprise sans perte des trouvailles existantes dans un premier dossier « Personnel »
- [ ] **Personnes recherchées** : pour chaque dossier, la liste des personnes visées, avec ce
  que l'on sait d'elles (nom, prénoms, naissance, lieux, conjoint) ; une recherche se lance
  d'un clic depuis une personne
- [ ] **Notices retenues** : favoris, notes et verdicts rangés dans le dossier actif et
  rattachés à une personne recherchée
- [ ] **Notice saisie à la main** : un acte trouvé sur Filae ou ailleurs (type, date, lieu,
  personnes, archives, cote, vue, lien, site où il a été trouvé), avec la même citation que les
  notices de l'atelier
- [ ] Page d'un dossier : personnes, notices, notes, citations ; export en tableur
- [ ] **Suppression complète** d'un dossier, avec confirmation (fin de mission, données d'un
  client) ; sauvegarde par dossier
- [ ] CLI : `doudoumil dossier liste|cree|active|exporte|supprime`
- [ ] Tests, dont la reprise des trouvailles existantes et la suppression complète

**Décisions**
- Une base SQLite par dossier (`data/perso/dossiers/<nom>.sqlite` : suppression et
  sauvegarde d'un client isolées) ou une base unique avec une table des dossiers.
- Une notice peut-elle appartenir à plusieurs dossiers (familles qui se croisent) ?

**Démo** : un dossier client, trois personnes recherchées, une notice de l'atelier et une
notice saisie depuis Filae, export du dossier.

---

## Jalon 12 — Vérification en lot

**Objectif** : soumettre une liste de personnes ou un arbre GEDCOM et savoir, pour chacune,
si un décès INSEE correspond, au lieu de les chercher une par une.

- [ ] Lecture d'une liste en CSV ou Excel (même lecture de tableur que les relevés ; colonnes
  nom, prénoms, sexe, naissance, lieu, conjoint)
- [ ] Lecture GEDCOM : individus, dates approximatives (« vers 1850 », « avant 1860 »,
  « entre 1850 et 1855 » → intervalles R3), lieux, conjoints ; réutiliser ton code de lecture
  s'il est en Python
- [ ] Recherche de chaque personne par le moteur ; pour une femme mariée, avec son nom de
  naissance **et** le nom de chaque conjoint (R2)
- [ ] Résultat par personne : décès probable, à vérifier ou non trouvé, avec la notice
  proposée et sa probabilité ; export en tableur
- [ ] Validation ✓ / ✗ dans l'interface : la notice validée entre dans le dossier (jalon 11),
  le verdict sert à la calibration (R5)
- [ ] Les personnes importées deviennent les personnes recherchées d'un dossier
- [ ] Performances : mesurer sur 1 000 personnes (une requête dure environ 0,1 s : quelques
  minutes attendues), en parallèle si besoin
- [ ] Rappel affiché : une personne née il y a moins d'un siècle et non trouvée est peut-être
  vivante (données personnelles)

**Décisions**
- Score de cohérence familiale (conjoint, parents) : plus tard, si les verdicts montrent des
  confusions entre homonymes.

**Démo** : l'arbre d'un client (GEDCOM), 200 personnes vérifiées en quelques minutes,
tableau des décès trouvés.

---

## Jalon 13 — Passerelles vers les sites de recherche et les archives

**Objectif** : depuis une personne ou une notice, ouvrir en un clic la bonne recherche sur
Filae et les autres sites, et le bon registre aux archives départementales. Uniquement des
liens que tu ouvres toi-même : aucune requête automatique.

- [ ] Liens de recherche pré-remplis (nom, prénoms, années, lieu) vers Filae, Geneanet,
  FamilySearch, MatchID et FranceArchives, selon les formats relevés au préalable P
- [ ] Référentiel des dépôts (`ref/depots.csv`) : pour chaque archive départementale, site,
  visionneuse, motif de lien vers une vue (repris du jalon 7)
- [ ] Résolveur de liens : provenance d'une notice (dépôt, cote, vue) → lien vers la vue
- [ ] **Localisateur de registres** : commune + type d'acte + années probables (R3) → registres
  disponibles et liens, construit depuis les inventaires de FranceArchives (Licence Ouverte) ;
  depuis une notice, « chercher l'acte de naissance » propose les registres de la commune de
  naissance pour les années probables
- [ ] Bouton « ajouter au dossier » au retour d'un site : ouvre la saisie à la main
  (jalon 11) préremplie avec la personne

**Démo** : depuis une personne d'un dossier, recherche ouverte sur Filae, acte trouvé, registre
ouvert aux archives pour vérifier, notice ajoutée au dossier avec sa cote.

---

## Jalon 14 — Rendu pour le client

**Objectif** : produire depuis un dossier un document propre, à remettre à un client ou à
garder.

- [ ] Rapport d'un dossier : personnes, événements, notes, et pour chaque information sa
  source (archives, cote, vue, lien)
- [ ] Formats : page imprimable (HTML) et document modifiable (Word ou PDF)
- [ ] Mention des sources utilisées et des conditions de réutilisation ; rien sur les
  personnes vivantes sans le choix explicite de les inclure
- [ ] Export de l'arbre validé vers un format que ton code GEDCOM peut relire (repris du
  jalon 9)

**Démo** : rapport d'un dossier client, imprimé ou envoyé en PDF.

---

## Transverse (à chaque jalon)

- Tests : chaque module a ses tests ; les fixtures restent petites et sans données réelles
  identifiantes.
- Vérifications vertes avant chaque commit : `uv run ruff check`, `uv run ruff format --check`,
  `uv run pytest`.
- Respect des conditions d'utilisation de chaque source ; licence notée dans le tableau du §2.
- Mettre à jour la section « Démonstration » du README, cocher ce plan et mettre à jour CLAUDE.md.
