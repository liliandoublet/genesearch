# Tests manuels — à faire sur ton ordinateur

Les tests automatiques (`uv run pytest`) tournent sur des données inventées, dans un
environnement où data.gouv.fr est bloqué. Ils ne peuvent donc pas vérifier quatre choses :

1. que le **catalogue data.gouv.fr** et le **format des fichiers INSEE** sont bien ceux que le
   code attend (écrits sans avoir pu lire la documentation officielle) ;
2. les **performances** réelles : durée du pipeline, place sur le disque, mémoire, temps de
   réponse sur environ 25 millions de décès ;
3. la **qualité des résultats** sur des personnes que tu connais (avec, pour comparaison,
   ce que Filae donne) ;
4. le **confort d'usage** de l'interface et de l'import de tes relevés.

Compte une demi-journée pour tout faire, ou procède par étapes : les étapes 1 à 4 suffisent
pour un premier retour. La [fiche de résultats](#fiche-de-résultats-à-me-renvoyer) en fin de
document liste ce qu'il faut me renvoyer.

> Les commandes sont écrites pour macOS et Linux. Sous Windows (PowerShell), elles sont
> identiques sauf les chemins, qui s'écrivent avec `\` : `data\releves\mon-releve.xlsx`.

---

## 0. À régler de ton côté avant de commencer

### Matériel

- [ ] **Place disque : environ 30 Go libres** pour la base complète. C'est une estimation
      extrapolée d'un essai sur 4 millions de décès inventés : 5 Go de fichiers INSEE bruts,
      12 Go environ pour la base de recherche, le reste pour les couches intermédiaires. Ta
      mesure (étape 5) la confirmera. Pour l'essai sur deux années (étape 2), 2 Go suffisent.
- [ ] **Mémoire : 8 Go au minimum, 16 Go conseillés** pour la base complète (estimation à
      confirmer, elle aussi).
- [ ] Données ailleurs que dans le dossier du projet (disque externe, par exemple) : ajoute
      `--donnees CHEMIN` juste après `doudoumil` dans chaque commande
      (`uv run doudoumil --donnees /Volumes/Externe/doudoumil pipeline`), ou définis une fois
      la variable `DOUDOUMIL_DATA` :
      - macOS / Linux : `export DOUDOUMIL_DATA=/Volumes/Externe/doudoumil`
      - Windows : `$env:DOUDOUMIL_DATA = "D:\doudoumil"`

### Réseau

- [ ] Accès sans blocage à **www.data.gouv.fr** et **static.data.gouv.fr** (fichiers INSEE),
      et à **registry.npmjs.org** (référentiel des communes). Sur un réseau d'entreprise avec
      proxy, fais l'essai depuis chez toi.

### Logiciels

- [ ] **git**.
- [ ] **uv** (il installe aussi Python 3.11) :
      - macOS / Linux : `curl -LsSf https://astral.sh/uv/install.sh | sh`
      - Windows : `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- [ ] **Le code de la bonne branche.** Le travail n'est pas encore sur `main`, il est sur la
      branche `claude/awesome-galileo-c8vjhv` :

      ```bash
      git clone https://github.com/liliandoublet/genesearch.git
      cd genesearch
      git checkout claude/awesome-galileo-c8vjhv
      uv sync
      ```

      Si le dépôt est déjà cloné : `git fetch origin`, puis
      `git checkout claude/awesome-galileo-c8vjhv`, `git pull` et `uv sync`.
- [ ] (Facultatif) Navigateur des tests automatiques : `uv run playwright install chromium`.
      Sans lui, les tests de navigateur sont simplement sautés.

### Ce qu'il faut avoir sous la main

- [ ] **Ton « jeu de vérité »** : 5 à 10 personnes que tu connais bien, **décédées en 1970 ou
      après** (le fichier INSEE commence en 1970), avec ce que tu sais d'elles : nom de
      naissance, prénoms, date et lieu de naissance, date et lieu de décès. Mets-y au moins
      une personne au nom souvent mal écrit, une femme mariée, une personne née à l'étranger ou
      outre-mer, et un nom très courant (MARTIN, BERNARD…).
- [ ] Pour chacune, si tu l'as, ce que Filae te donne (trouvée ou non, à quel rang) : pas
      pour remplacer Filae, mais pour savoir si l'atelier retrouve bien les décès qu'il
      contient.
- [ ] **Un vrai relevé** en CSV ou Excel (cercle généalogique, tes dépouillements).
- [ ] De quoi noter des durées (montre, ou la commande `time`, voir étape 5).

---

## 1. Installation (5 minutes)

```bash
uv run pytest
uv run doudoumil --help
```

- [ ] `pytest` se termine par `… passed` sans `failed` (quelques `skipped` si Chromium n'est
      pas installé : c'est normal).
- [ ] `doudoumil --help` liste les commandes `pipeline`, `cherche`, `serve`, `sauvegarde`…

**En cas d'échec** : renvoie-moi la fin de la sortie (les 30 dernières lignes).

---

## 2. Premier essai sur deux années de décès (le plus important)

```bash
uv run doudoumil pipeline --telecharge --annees 2019-2020
```

### Ce qui doit s'afficher

```
référentiel des communes 6.0.0 téléchargé
décès INSEE : 2 fichiers disponibles dans data/bronze/insee_deces/telechargements
deces-2019.txt : … ingérées, … rejetées (…)
deces-2020.txt : … ingérées, … rejetées (…)
décès INSEE : 2 fichiers convertis en …
normalisation insee_deces : … actes (… doublons écartés), … mentions, en …
base de recherche : … personnes, … noms distincts (insee_deces), en …
```

Des lignes `INFO …` s'intercalent : c'est le journal, il répète les mêmes informations.

### À vérifier

- [ ] **Le téléchargement aboutit.** S'il échoue, note le message exact :
      - `téléchargement impossible (HTTP Error 404 …)` : l'adresse du jeu de données a changé ;
      - `aucun fichier de décès reconnu dans le catalogue…` : les fichiers n'ont pas le nom
        attendu (`deces-2020.txt`).

      **Plan B** dans les deux cas : télécharge à la main le fichier 2020 depuis la page
      [Fichier des personnes décédées](https://www.data.gouv.fr/fr/datasets/fichier-des-personnes-decedees/)
      (décompresse-le si c'est un `.zip`). Dépose le `.txt` dans
      `data/bronze/insee_deces/telechargements/`, puis lance `uv run doudoumil pipeline`. Note
      le nom exact du fichier et l'adresse de la page : je corrigerai le téléchargement.
- [ ] **Nombre de lignes plausible** : de l'ordre de 600 000 à 700 000 décès par année.
- [ ] **Très peu de rejets** : moins de 0,1 % des lignes.
- [ ] **Anomalies raisonnables** entre parenthèses. Des « date de naissance incomplète » en
      petit nombre sont normales. Des « code du lieu de décès invalide » ou « sexe absent ou
      inconnu » par dizaines de milliers signalent un **format mal lu**.
- [ ] **Durées** affichées pour la conversion, la normalisation et la base, à noter.

### Contrôle du format sur quelques notices

```bash
uv run doudoumil cherche "MARTIN Jean" --annees 2020 --limite 5 --details
```

- [ ] Les noms et prénoms sont entiers, sans lettre coupée ni chiffre collé.
- [ ] Les dates de naissance et de décès sont plausibles, le sexe correspond au prénom.
- [ ] Les communes de naissance et de décès sont de vrais noms de communes.

**Si quelque chose semble décalé** (lettres coupées, dates absurdes, lieux vides), renvoie-moi
les 3 premières lignes brutes du fichier. Ce sont des données publiques.

- macOS / Linux : `head -3 data/bronze/insee_deces/telechargements/deces-2020.txt`
- Windows : `Get-Content data\bronze\insee_deces\telechargements\deces-2020.txt -TotalCount 3`

Renvoie aussi les 10 premières lignes de `data/bronze/insee_deces/deces-2020/rejets.csv` s'il
y a des rejets.

---

## 3. Interface web

```bash
uv run doudoumil serve
```

Le navigateur s'ouvre sur <http://127.0.0.1:8765> ; `Ctrl+C` dans le terminal arrête le
serveur. Essaie, et coche ce qui marche :

- [ ] **Recherche simple** : `NOM Prénom` dans le champ unique.
- [ ] **Recherche avancée** : année de naissance (ou intervalle `1930-1935`), sexe, années de
      l'acte, et un lieu. En tapant `quimp` dans le lieu, des communes et départements sont
      proposés.
- [ ] **Filtres de gauche** (source, département, décennie) avec leurs compteurs ; un clic
      filtre, un second clic retire le filtre.
- [ ] **Pagination** sur un nom courant.
- [ ] **Fiche** : un clic sur un nom ouvre l'acte, avec la provenance et une citation. Le
      bouton « Copier la citation » la place dans le presse-papiers.
- [ ] **Trouvailles** : ★ favori, ✓ / ✗ verdict, note sur la fiche ; tout se retrouve dans
      le dossier actif (lien « Dossier : … » en haut de page).
- [ ] **Dossiers** : dans « Tous les dossiers », crée un dossier d'essai ; ajoute une personne
      recherchée ; « Chercher » lance la recherche, et une notice marquée ★ apparaît sous
      cette personne dans le dossier. Saisis un acte trouvé sur Filae (« Saisir un acte
      trouvé ailleurs ») : sa citation reprend la cote et la vue. Supprime ensuite le dossier
      d'essai.
- [ ] **Exports** : le CSV des résultats et celui d'un dossier (« exporter en tableur »)
      s'ouvrent dans Excel ou LibreOffice avec les accents corrects.
- [ ] **Sauvegarde** : le lien « télécharger une sauvegarde » de la page d'un dossier donne un
      fichier `doudoumil-….zip`.
- [ ] **Rapidité** : note toute page qui met plus d'une seconde.
- [ ] **Ergonomie** : note ce qui est peu clair, ce qui manque par rapport à Filae, ce qui est
      mal affiché (sur téléphone aussi, si tu ouvres l'adresse sur l'ordinateur en fenêtre
      étroite).

---

## 4. Contrôle sur des personnes connues (jeu de vérité)

Avec la base de l'étape 2, seules les personnes décédées en 2019-2020 sont présentes. Fais
cette étape sur la base complète (étape 5) pour tout ton jeu de vérité.

Pour chaque personne, fais **trois recherches** dans l'interface :

1. **complète** : nom, prénoms, année de naissance, lieu ;
2. **imprécise** : une variante d'orthographe du nom (`LEGOF` pour `LE GOFF`), un seul prénom,
   naissance à ± 2 ans ;
3. **sans le nom** (champ « Nom » vide en recherche avancée) : prénom, année de naissance et
   département.

Remplis le tableau de la fiche de résultats : rang de la bonne notice (1 = en tête) et libellé
de confiance affiché.

---

## 5. Base complète et performances

```bash
time uv run doudoumil pipeline --telecharge
```

Sous Windows : `Measure-Command { uv run doudoumil pipeline --telecharge }`.

- [ ] **Durée totale**, et celle de chaque étape (affichée en fin de ligne : « converti en … »,
      « mentions, en … », « noms distincts (…), en … »).
- [ ] **Mémoire maximale** pendant la commande (Moniteur d'activité, ou Gestionnaire des
      tâches sous Windows).
- [ ] **Place occupée** par chaque dossier de `data/` :
      - macOS / Linux : `du -sh data/*` ;
      - Windows : clic droit → Propriétés sur chaque dossier de `data`.
- [ ] **Relance** : `uv run doudoumil pipeline` doit répondre en quelques secondes que tout est
      « à jour ».
- [ ] **Temps de réponse** d'une recherche, sur un nom courant et sur un nom rare :
      `time uv run doudoumil cherche "MARTIN Marie" --naissance 1930`. Ce temps comprend le
      démarrage de Python ; dans l'interface, note simplement si l'attente se sent.

---

## 6. Qualité mesurée et calibration

```bash
uv run doudoumil evalue
uv run doudoumil calibre
```

- [ ] Note la ligne de résultat de `evalue` (présélection, rang 1, 10 premiers, Brier).
- [ ] Après `calibre`, les résultats de l'interface affichent « très probable », « probable »…
      avec un pourcentage, au lieu de « non calibré ».
- [ ] Donne 10 à 20 verdicts ✓ / ✗ dans l'interface (étape 4), relance `calibre` : la sortie
      indique `… verdicts réels`.

---

## 7. Import d'un vrai relevé

Mode d'emploi complet : [`docs/releves.md`](releves.md).

```bash
# copie ton tableur dans data/releves/ (avec l'explorateur de fichiers, par exemple), puis :
uv run doudoumil ingest releve --modele data/releves/MON-RELEVE.xlsx
```

- [ ] Ouvre `data/releves/MON-RELEVE.toml` dans un éditeur de texte (Bloc-notes, TextEdit en
      mode texte brut) et note les colonnes **mal devinées** ou **non reprises** (listées en
      fin de fichier).
- [ ] Corrige le `titre`, le `type` d'acte, la `commune`, le `departement` et le `depot`, puis
      enregistre (en UTF-8, ce que font les éditeurs récents par défaut).
- [ ] `uv run doudoumil pipeline` : le bilan indique les lignes importées et rejetées. Ouvre
      `data/bronze/releve/MON-RELEVE/rejets.csv` s'il y a des rejets : les motifs sont-ils
      compréhensibles ?
- [ ] Dans l'interface, cherche une personne du relevé, filtre la source « Relevés », ouvre la
      fiche : le titre du relevé, la cote et la vue figurent dans la citation.
- [ ] Note tout message d'erreur obscur, avec le texte exact.

Ne m'envoie pas le relevé lui-même s'il n'est pas public : ses noms de colonnes et 2 ou 3
lignes anonymisées suffisent.

---

## 8. Sauvegarde et restauration (sans risque pour tes données)

```bash
uv run doudoumil sauvegarde
```

- [ ] La commande affiche le chemin d'une archive `data/sauvegardes/doudoumil-….zip`, avec le
      nombre de trouvailles et de fichiers de relevés.
- [ ] Restaure-la **dans un dossier d'essai**, pour ne pas toucher à tes vraies données (mets
      le chemin affiché par la commande précédente) :

      ```bash
      uv run doudoumil --donnees essai-restauration restaure data/sauvegardes/doudoumil-AAAAMMJJ-HHMMSS.zip
      ```

      Le dossier `essai-restauration` contient alors `perso/dossiers/` (un fichier par
      dossier de recherche) et `releves/`. Supprime-le ensuite.
- [ ] Copie une sauvegarde hors de l'ordinateur (clé USB, disque externe, nuage).

---

## 9. Mise à jour du mois suivant (plus tard)

Quand l'INSEE publie un nouveau fichier mensuel :

```bash
time uv run doudoumil pipeline --telecharge
```

- [ ] Seul le nouveau fichier est converti : les autres sont annoncés « déjà convertis ».
- [ ] Note la durée totale. La normalisation et la base sont encore refaites en entier : ta
      mesure dira s'il faut les rendre incrémentales.

---

## Limites connues (inutile de les signaler)

- Pas de recensements (Socface), d'images d'actes ni de Morts pour la France dans l'atelier :
  ils se consultent sur FranceArchives, Filae ou Mémoire des hommes. L'atelier est
  complémentaire de ces sites (voir `PLAN.md`).
- Le fichier INSEE ne couvre que les décès depuis 1970.
- Relevés : une ligne du tableur = un acte ; les dates républicaines ne sont pas converties.
- Sans `doudoumil calibre`, les résultats sont « non calibré » : c'est attendu.

---

## Fiche de résultats à me renvoyer

Copie cette partie dans ta réponse et remplis-la. Les sorties de commandes peuvent être
collées telles quelles.

```
Ordinateur : système …, mémoire … Go, disque libre … Go

Étape 1 — pytest : … passed, … skipped, … failed

Étape 2 — deux années
  téléchargement : OK / échec (message : …)
  deces-2019.txt : … ingérées, … rejetées (anomalies : …)
  deces-2020.txt : … ingérées, … rejetées (anomalies : …)
  contrôle du format (noms, dates, lieux) : OK / décalé (3 lignes brutes : …)
  durée : …

Étape 3 — interface : ce qui ne marche pas / ce qui est lent / ce qui manque : …

Étape 5 — base complète
  durée totale : …   (téléchargement … ; conversion … ; normalisation … ; base …)
  mémoire maximale : … Go
  place : bronze … Go, silver … Go, gold … Go
  relance « à jour » : … s
  recherche nom courant : … s ; nom rare : … s

Étape 6 — evalue : (ligne de résultat) …

Étape 7 — relevé : colonnes mal devinées : … ; lignes importées / rejetées : … ; messages obscurs : …

Étape 8 — sauvegarde et restauration : OK / problème : …
```

| Personne (initiales) | Ce que je sais | Filae : trouvée ? rang | doudoumil complète : rang, confiance | imprécise : rang | sans le nom : rang | Remarques |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |
