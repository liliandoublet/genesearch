# Importer un relevé (CSV ou Excel)

Un **relevé** est un tableur de notices transcrites : relevés d'un cercle généalogique, tables
décennales recopiées, tes propres dépouillements. Le moteur l'importe grâce à un petit fichier
de **correspondance** (format TOML) qui dit, pour chaque information, dans quelle colonne la
trouver. Les notices importées sont cherchées comme les autres (source « Relevés »), et leurs
fiches citent l'intitulé du relevé.

## En trois commandes

```bash
# 1. ranger le tableur dans data/releves/
cp ~/Téléchargements/bms-landerneau.xlsx data/releves/

# 2. préparer la correspondance d'après les noms de colonnes
uv run doudoumil ingest releve --modele data/releves/bms-landerneau.xlsx
#    → data/releves/bms-landerneau.toml, à relire (titre, type d'acte, commune)

# 3. importer et mettre la base à jour
uv run doudoumil pipeline
```

`doudoumil pipeline` réimporte un relevé dès que son tableur ou sa correspondance change, et
ne refait rien d'autre que nécessaire. `doudoumil ingest releve` importe seulement les relevés,
sans mettre à jour la base (suivi de `doudoumil normalize releve` et `doudoumil index`).

`--feuille "Baptêmes"` choisit la feuille d'un classeur (la première par défaut). La commande
`--modele` ne remplace jamais une correspondance existante.

Le bilan indique les lignes importées et rejetées ; le détail des rejets, avec leur motif, est
dans `data/bronze/releve/<nom>/rejets.csv`. Corriger le tableur ou la correspondance, puis
relancer : l'import remplace le précédent et redonne les mêmes identifiants.

> Sauvegarde : `data/releves/` contient tes fichiers, que rien ne sait reconstruire.
> `doudoumil sauvegarde` l'archive avec `data/perso/` (tes trouvailles).

## Le fichier de correspondance

Exemple complet : [`tests/fixtures/releves/landerneau-bms.toml`](../tests/fixtures/releves/landerneau-bms.toml)
et son tableur `landerneau-bms.csv` (données inventées).

```toml
[releve]
titre = "Baptêmes et sépultures de Landerneau (1755-1762), relevé du cercle"
fichier = "landerneau-bms.csv"       # chemin relatif au fichier .toml
confiance = 0.95                     # fiabilité estimée de la transcription, 0 à 1
cle = ["Type", "Date", "Nom", "Prénoms"]

[acte]
type = { colonne = "Type", valeurs = { B = "bapteme", S = "deces" } }
date = { colonne = "Date", format = "%d/%m/%Y" }
commune = "Landerneau"
departement = "29"
depot = "AD 29"
cote = { colonne = "Cote" }
vue = { colonne = "Vue" }

[[personne]]
role = "sujet"
nom = { colonne = "Nom" }
prenoms = { colonne = "Prénoms" }
sexe = { colonne = "Sexe" }
age = { colonne = "Âge" }

[[personne]]
role = "pere"
nom = { colonne = "Nom" }            # même nom que l'enfant
prenoms = { colonne = "Père" }

[[personne]]
role = "mere"
nom = { colonne = "Nom mère" }
prenoms = { colonne = "Mère" }
nature_nom = "naissance"
```

### Constante ou colonne

Chaque information est soit une **constante**, la même pour toutes les lignes
(`departement = "29"`), soit une **colonne** du tableur :

| forme | effet |
|---|---|
| `{ colonne = "Cote" }` | valeur de la colonne « Cote » |
| `{ colonne = "Type", valeurs = { B = "bapteme" } }` | traduit les codes du relevé ; une valeur absente de la table est gardée telle quelle |
| `{ colonne = "Sexe", defaut = "M" }` | valeur utilisée quand la cellule est vide |
| `{ colonne = "Date", format = "%d/%m/%Y" }` | format d'une date ([codes `strftime`](https://docs.python.org/fr/3/library/datetime.html#strftime-and-strptime-format-codes)) |

Les noms de colonnes sont comparés sans tenir compte des majuscules, des accents ni des
espaces : `{ colonne = "prenoms" }` trouve la colonne « Prénoms ». Une colonne citée mais
absente arrête l'import avec la liste des colonnes du tableur.

### Section `[releve]`

| clé | rôle |
|---|---|
| `titre` (obligatoire) | intitulé cité dans les fiches et les citations de source |
| `fichier` (obligatoire) | tableur : `.csv`, `.tsv`, `.txt`, `.xlsx`, `.xls`, `.xlsm`, `.xlsb`, `.ods` |
| `feuille` | feuille du classeur (défaut : la première) |
| `entete` | numéro de la ligne des noms de colonnes (défaut : 1), s'il y a un titre au-dessus |
| `separateur` | séparateur d'un CSV (défaut : deviné parmi `;` `,` tabulation `\|`) |
| `encodage` | encodage d'un CSV (défaut : UTF-8, sinon Windows-1252) |
| `confiance` | fiabilité de la transcription, de 0 à 1 (défaut : 0,9) ; elle pondère le score |
| `cle` | colonnes qui identifient une ligne (défaut : son numéro de ligne) |

**La clé** donne à chaque notice un identifiant stable, auquel se rattachent tes trouvailles
(favoris, notes, verdicts). Sans clé, c'est le numéro de ligne : trier ou compléter le tableur
change alors les identifiants. Avec `cle = ["Date", "Nom", "Prénoms"]`, l'ordre des lignes
n'importe plus ; deux lignes de même clé reçoivent un numéro d'ordre (signalé dans le bilan).
Pour la même raison, ne renomme pas le fichier `.toml` une fois des trouvailles enregistrées :
son nom fait partie des identifiants.

### Section `[acte]`

| clé | contenu |
|---|---|
| `type` (obligatoire) | `naissance`, `bapteme`, `mariage`, `deces`, `recensement`, `autre` ; « Baptême », « Décès », « Sépulture », « Inhumation » sont aussi compris |
| `date` | date de l'acte ; formats reconnus sans `format` : `02/03/1755`, `1755-03-02`, `02-03-1755`, `02.03.1755`, date Excel |
| `annee` | année de l'acte, si elle est dans une colonne à part ; sinon tirée de la date, même incomplète (`../03/1755`) |
| `commune` | nom de la commune ou de la paroisse ; son code INSEE est déduit à la normalisation s'il est unique (dans le département s'il est donné) |
| `commune_code` | code INSEE de la commune, s'il figure dans le relevé |
| `departement` | numéro du département (`29`, `2A`, `974`) |
| `depot`, `cote`, `vue`, `url_image` | provenance : service d'archives, cote, vue ou page, lien vers l'image |

Il faut `date` ou `annee`. Une ligne sans année lisible, ou dont le type est inconnu, est
rejetée.

### Sections `[[personne]]`

Une section par personne citée dans chaque acte, dans l'ordre : sujet, parents, conjoints,
témoins…

| clé | contenu |
|---|---|
| `role` (obligatoire, constante) | `sujet`, `pere`, `mere`, `epoux`, `epouse`, `enfant`, `temoin`, `chef_menage`, `autre` |
| `nom`, `prenoms` | au moins l'un des deux |
| `sexe` | `M` ou `F` ; « H », « G », « Homme », « Garçon », « Femme », « Fille » sont aussi compris ; déduit du rôle pour le père, la mère, l'époux et l'épouse |
| `nature_nom` | `naissance`, `marital` (nom du mari) ou `inconnue` ; une femme inscrite sous le nom de son mari ne doit pas être pénalisée sur son nom de naissance |
| `date_naissance` | date ou année de naissance, même incomplète (`vers 1850`) |
| `age` | âge : « 40 », « 40 ans » ; « 6 mois », « 3 jours » donnent 0 |
| `profession`, `lieu_naissance` | texte libre |
| `lieu_naissance_code` | code INSEE du lieu de naissance |

Une personne est ignorée pour une ligne si elle n'y a ni nom ni prénoms, ou si seules sont
remplies des colonnes qu'elle partage avec une personne précédente : le père dont le nom est
repris de la colonne de l'enfant n'est créé que si ses prénoms sont connus. Une ligne où
personne n'est nommé est rejetée.

## Ce que le moteur en fait

- Les cellules sont gardées telles quelles (aux espaces de bord près) : la normalisation des
  noms, prénoms et lieux se fait ensuite, comme pour les autres sources.
- Chaque personne nommée devient une notice cherchable ; la fiche de l'acte réunit toutes les
  personnes de la ligne.
- La citation de source reprend le titre du relevé, le dépôt, la cote et la vue.
- Tes verdicts (« c'est bien elle », « ce n'est pas elle ») sur ces notices servent à calibrer
  la source « Relevés » avec `doudoumil calibre`.

## Limites

- Une ligne = un acte. Les relevés « une ligne par personne » (plusieurs lignes pour un même
  acte) sont importés, mais chaque ligne y forme un acte distinct.
- Les dates du calendrier républicain (« 12 floréal an XII ») ne sont pas converties : ajoute
  une colonne avec l'année grégorienne et indique-la dans `annee`.
