"""Connecteur de relevés : un tableur (CSV ou Excel) décrit par un fichier de correspondance.

Relevés de cercles généalogiques, tables décennales recopiées, transcriptions personnelles :
plutôt qu'un connecteur par format, un petit fichier TOML (``releves/<nom>.toml``) dit où
trouver chaque information du pivot dans le tableur. ``docs/releves.md`` le décrit en détail ;
exemple ::

    [releve]
    titre = "Baptêmes de Plougastel-Daoulas (1700-1792), relevé du cercle"
    fichier = "plougastel.csv"
    confiance = 0.95
    cle = ["Date", "Nom", "Prénoms"]

    [acte]
    type = "bapteme"
    date = { colonne = "Date", format = "%d/%m/%Y" }
    commune = "Plougastel-Daoulas"
    departement = "29"
    cote = { colonne = "Cote" }

    [[personne]]
    role = "sujet"
    nom = { colonne = "Nom" }
    prenoms = { colonne = "Prénoms" }
    sexe = { colonne = "Sexe", valeurs = { G = "M" } }

    [[personne]]
    role = "pere"
    nom = { colonne = "Nom" }
    prenoms = { colonne = "Père" }

Chaque information est une **constante** (``departement = "29"``) ou une **colonne**
(``{ colonne = "Cote" }``), avec au besoin une table de ``valeurs`` qui traduit les codes du
relevé, une valeur ``defaut`` pour les cellules vides et le ``format`` d'une date. Les noms de
colonnes sont comparés sans tenir compte des majuscules, des accents ni des espaces de bord.

Chaque ligne du tableur donne un acte, et une mention par personne nommée. Une personne est
ignorée (père inconnu, témoin absent) si elle n'a ni nom ni prénoms, ou si seules sont remplies
des colonnes qu'elle partage avec une personne précédente : un père dont le nom est repris de
la colonne de l'enfant n'est retenu que si ses prénoms sont connus. Une ligne n'est rejetée que
si l'acte ne peut être ni typé ni daté, ou si personne n'y est nommé. Les cellules sont gardées
telles quelles, aux espaces de bord près.
"""

import csv
import io
import json
import logging
import re
import tomllib
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, TypeVar

import fastexcel
from pydantic import ValidationError

from doudoumil_search.ingest.commun import (
    MOTIF_CODE_LIEU,
    MOTIF_DEPARTEMENT,
    LigneRejetee,
    RapportIngestion,
    departement_de,
    motif_validation,
)
from doudoumil_search.ingest.ecriture import EcrivainPartition
from doudoumil_search.normalize.texte import majuscules_ascii, mots
from doudoumil_search.pivot import (
    Acte,
    Mention,
    NatureNom,
    Role,
    Sexe,
    Source,
    TypeActe,
    fabriquer_id,
)

journal = logging.getLogger(__name__)

E = TypeVar("E", bound=StrEnum)

CONFIANCE_PAR_DEFAUT: Final = 0.9
EXTENSIONS_CSV: Final = (".csv", ".tsv", ".txt")
EXTENSIONS_EXCEL: Final = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods")
SEPARATEURS_POSSIBLES: Final = (";", ",", "\t", "|")

CLES_RELEVE: Final = frozenset(
    {"titre", "fichier", "feuille", "separateur", "encodage", "entete", "confiance", "cle"}
)
CLES_ACTE: Final = frozenset(
    {
        "type",
        "date",
        "annee",
        "commune",
        "commune_code",
        "departement",
        "depot",
        "cote",
        "vue",
        "url_image",
    }
)
CLES_PERSONNE: Final = frozenset(
    {
        "role",
        "nom",
        "prenoms",
        "nature_nom",
        "sexe",
        "date_naissance",
        "age",
        "profession",
        "lieu_naissance",
        "lieu_naissance_code",
    }
)
CLES_CHAMP: Final = frozenset({"colonne", "valeurs", "defaut", "format"})

# Dates de la forme la plus courante dans les relevés, essayées après le format indiqué ; la
# dernière est celle que donne une cellule Excel de type date.
FORMATS_DATE: Final = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S")
ANNEE: Final = re.compile(r"(?<!\d)(\d{4})(?!\d)")
AGE_EN_ANNEES: Final = re.compile(r"(\d{1,3})(?:[.,]0+)?(?: ?ANS?)?")
AGE_EN_BAS_AGE: Final = re.compile(r"\b(MOIS|JOURS?|SEMAINES?|HEURES?)\b")

# Écritures usuelles, comparées après passage en majuscules sans accents.
TYPES_USUELS: Final = {"SEPULTURE": TypeActe.DECES, "INHUMATION": TypeActe.DECES}
SEXES_USUELS: Final = {
    "M": Sexe.M,
    "H": Sexe.M,
    "G": Sexe.M,
    "1": Sexe.M,
    "HOMME": Sexe.M,
    "MASCULIN": Sexe.M,
    "GARCON": Sexe.M,
    "F": Sexe.F,
    "2": Sexe.F,
    "FEMME": Sexe.F,
    "FEMININ": Sexe.F,
    "FILLE": Sexe.F,
}
SEXE_DU_ROLE: Final = {
    Role.PERE: Sexe.M,
    Role.EPOUX: Sexe.M,
    Role.MERE: Sexe.F,
    Role.EPOUSE: Sexe.F,
}


class CorrespondanceInvalide(ValueError):
    """Fichier de correspondance ou tableur inutilisable ; le message dit quoi corriger."""


def cle_colonne(nom: str) -> str:
    """Forme de comparaison d'un nom de colonne : « Prénoms  » et « PRENOMS » se valent."""
    return " ".join(majuscules_ascii(nom).split())


@dataclass(frozen=True)
class Champ:
    """Où lire une information : une constante, ou une colonne du tableur."""

    constante: str | None = None
    colonne: str | None = None
    valeurs: Mapping[str, str] = field(default_factory=dict)  # clés en majuscules sans accents
    defaut: str | None = None
    format: str | None = None

    def lire(self, ligne: Mapping[str, str | None]) -> str | None:
        if self.colonne is None:
            return self.constante
        brute = ligne.get(cle_colonne(self.colonne))
        if brute is None:
            return self.defaut
        return self.valeurs.get(cle_colonne(brute), brute) if self.valeurs else brute


@dataclass(frozen=True)
class Personne:
    """Une personne citée dans chaque acte : son rôle et où lire ses informations."""

    role: Role
    champs: Mapping[str, Champ]
    # colonnes (forme cle_colonne) que n'utilise aucune personne précédente
    propres: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Correspondance:
    """Contenu d'un fichier de correspondance, vérifié."""

    nom: str  # nom du fichier de correspondance, sans extension : identifie le relevé
    titre: str
    fichier: Path
    feuille: str | None
    separateur: str | None
    encodage: str | None
    entete: int
    confiance: float
    cle: tuple[str, ...]
    acte: Mapping[str, Champ]
    personnes: tuple[Personne, ...]

    def colonnes(self) -> list[str]:
        """Colonnes utilisées, dans l'ordre où elles apparaissent dans la correspondance."""
        champs = [*self.acte.values(), *(c for p in self.personnes for c in p.champs.values())]
        noms = [*self.cle, *(c.colonne for c in champs if c.colonne is not None)]
        return list(dict.fromkeys(noms))


def _texte(valeur: Any, ou: str) -> str:
    if isinstance(valeur, bool) or not isinstance(valeur, str | int | float):
        raise CorrespondanceInvalide(f"{ou} : texte ou nombre attendu, pas {valeur!r}")
    return str(valeur)


def _verifier_cles(table: Mapping[str, Any], permises: frozenset[str], ou: str) -> None:
    if inconnues := sorted(set(table) - permises):
        raise CorrespondanceInvalide(
            f"{ou} : clé inconnue {', '.join(inconnues)} ; clés possibles : "
            + ", ".join(sorted(permises))
        )


def _champ(valeur: Any, ou: str) -> Champ:
    """``"29"`` → constante ; ``{ colonne = "Cote", … }`` → colonne."""
    if not isinstance(valeur, dict):
        return Champ(constante=_texte(valeur, ou))
    _verifier_cles(valeur, CLES_CHAMP, ou)
    if "colonne" not in valeur:
        raise CorrespondanceInvalide(f"{ou} : « colonne » manquante")
    valeurs = valeur.get("valeurs", {})
    if not isinstance(valeurs, dict):
        raise CorrespondanceInvalide(f"{ou} : « valeurs » doit être une table")
    return Champ(
        colonne=_texte(valeur["colonne"], f"{ou}.colonne"),
        valeurs={
            cle_colonne(cle): _texte(cible, f"{ou}.valeurs.{cle}") for cle, cible in valeurs.items()
        },
        defaut=_texte(valeur["defaut"], f"{ou}.defaut") if "defaut" in valeur else None,
        format=_texte(valeur["format"], f"{ou}.format") if "format" in valeur else None,
    )


def lire_enumeration(
    classe: type[E], texte: str | None, usuels: Mapping[str, E] | None = None
) -> E | None:
    """Valeur d'une énumération écrite librement : « Baptême », « BAPTEME », « bapteme »."""
    if texte is None:
        return None
    cle = cle_colonne(texte)
    if usuels and cle in usuels:
        return usuels[cle]
    try:
        return classe(cle.lower().replace(" ", "_"))
    except ValueError:
        return None


def _verifier_constantes(
    classe: type[E], champ: Champ, ou: str, usuels: Mapping[str, E] | None = None
) -> None:
    """Une constante ou une valeur traduite doit appartenir à l'énumération."""
    cibles = [champ.constante] if champ.colonne is None else list(champ.valeurs.values())
    if champ.defaut is not None:
        cibles.append(champ.defaut)
    for cible in cibles:
        if lire_enumeration(classe, cible, usuels) is None:
            raise CorrespondanceInvalide(
                f"{ou} : « {cible} » inconnu ; valeurs possibles : "
                + ", ".join(e.value for e in classe)
            )


def lire_correspondance(chemin: Path) -> Correspondance:
    """Lit et vérifie un fichier de correspondance (sans ouvrir le tableur)."""
    try:
        contenu = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erreur:
        raise CorrespondanceInvalide(f"{chemin.name} : TOML invalide ({erreur})") from None
    _verifier_cles(contenu, frozenset({"releve", "acte", "personne"}), chemin.name)
    releve, acte, personnes = (contenu.get(k) for k in ("releve", "acte", "personne"))
    if not isinstance(releve, dict) or not isinstance(acte, dict):
        raise CorrespondanceInvalide(f"{chemin.name} : sections [releve] et [acte] obligatoires")
    if not isinstance(personnes, list) or not personnes:
        raise CorrespondanceInvalide(f"{chemin.name} : au moins une section [[personne]]")

    _verifier_cles(releve, CLES_RELEVE, "[releve]")
    for obligatoire in ("titre", "fichier"):
        if obligatoire not in releve:
            raise CorrespondanceInvalide(f"[releve] : « {obligatoire} » manquant")
    confiance = releve.get("confiance", CONFIANCE_PAR_DEFAUT)
    if isinstance(confiance, bool) or not isinstance(confiance, int | float):
        raise CorrespondanceInvalide("[releve] confiance : nombre entre 0 et 1 attendu")
    if not 0 <= confiance <= 1:
        raise CorrespondanceInvalide("[releve] confiance : nombre entre 0 et 1 attendu")
    entete = releve.get("entete", 1)
    if isinstance(entete, bool) or not isinstance(entete, int) or entete < 1:
        raise CorrespondanceInvalide("[releve] entete : numéro de ligne (1 ou plus) attendu")
    cle = releve.get("cle", [])
    if not isinstance(cle, list):
        raise CorrespondanceInvalide('[releve] cle : liste de colonnes attendue, ex. ["Date"]')

    _verifier_cles(acte, CLES_ACTE, "[acte]")
    if "type" not in acte:
        raise CorrespondanceInvalide("[acte] : « type » manquant")
    if "date" not in acte and "annee" not in acte:
        raise CorrespondanceInvalide("[acte] : « date » ou « annee » nécessaire pour dater l'acte")
    champs_acte = {nom: _champ(valeur, f"[acte] {nom}") for nom, valeur in acte.items()}
    _verifier_constantes(TypeActe, champs_acte["type"], "[acte] type", TYPES_USUELS)

    liste: list[Personne] = []
    deja_vues: set[str] = set()
    for rang, personne in enumerate(personnes, start=1):
        ou = f"[[personne]] n° {rang}"
        if not isinstance(personne, dict):
            raise CorrespondanceInvalide(f"{ou} : table attendue")
        _verifier_cles(personne, CLES_PERSONNE, ou)
        if "nom" not in personne and "prenoms" not in personne:
            raise CorrespondanceInvalide(f"{ou} : « nom » ou « prenoms » nécessaire")
        role = lire_enumeration(Role, _texte(personne.get("role", ""), f"{ou} role"))
        if role is None:
            raise CorrespondanceInvalide(
                f"{ou} : « role » manquant ou inconnu ; valeurs possibles : "
                + ", ".join(r.value for r in Role)
            )
        champs = {
            nom: _champ(valeur, f"{ou} {nom}") for nom, valeur in personne.items() if nom != "role"
        }
        if "sexe" in champs:
            _verifier_constantes(Sexe, champs["sexe"], f"{ou} sexe", SEXES_USUELS)
        if "nature_nom" in champs:
            _verifier_constantes(NatureNom, champs["nature_nom"], f"{ou} nature_nom")
        colonnes = {cle_colonne(c.colonne) for c in champs.values() if c.colonne is not None}
        liste.append(Personne(role=role, champs=champs, propres=frozenset(colonnes - deja_vues)))
        deja_vues |= colonnes

    return Correspondance(
        nom=chemin.stem,
        titre=_texte(releve["titre"], "[releve] titre"),
        fichier=chemin.parent / _texte(releve["fichier"], "[releve] fichier"),
        feuille=_texte(releve["feuille"], "[releve] feuille") if "feuille" in releve else None,
        separateur=(
            _texte(releve["separateur"], "[releve] separateur") if "separateur" in releve else None
        ),
        encodage=_texte(releve["encodage"], "[releve] encodage") if "encodage" in releve else None,
        entete=entete,
        confiance=float(confiance),
        cle=tuple(_texte(c, "[releve] cle") for c in cle),
        acte=champs_acte,
        personnes=tuple(liste),
    )


# --- lecture du tableur ---------------------------------------------------------------------


@dataclass
class Tableur:
    """En-tête et lignes d'un tableur, cellules en texte (``None`` si vides)."""

    entete: list[str]
    lignes: Iterator[tuple[int, list[str | None]]]  # (numéro de ligne dans le fichier, cellules)


def _cellule(valeur: Any) -> str | None:
    if valeur is None:
        return None
    return str(valeur).strip() or None


def _decoder(octets: bytes, encodage: str | None, nom: str) -> str:
    if encodage is not None:
        try:
            return octets.decode(encodage)
        except (LookupError, UnicodeDecodeError) as erreur:
            raise CorrespondanceInvalide(
                f"{nom} : lecture en {encodage} impossible ({erreur})"
            ) from None
    try:
        return octets.decode("utf-8-sig")
    except UnicodeDecodeError:
        # tableurs enregistrés en CSV par Excel sous Windows
        journal.info("%s n'est pas en UTF-8 : lu en Windows-1252", nom)
        return octets.decode("cp1252")


def _lire_csv(chemin: Path, separateur: str | None, encodage: str | None, entete: int) -> Tableur:
    texte = _decoder(chemin.read_bytes(), encodage, chemin.name)
    if separateur is None:
        lignes = texte.splitlines()
        premiere = lignes[entete - 1] if len(lignes) >= entete else ""
        comptes = {s: premiere.count(s) for s in SEPARATEURS_POSSIBLES}
        separateur = max(comptes, key=lambda s: comptes[s]) if any(comptes.values()) else ","
    lecteur = csv.reader(io.StringIO(texte, newline=""), delimiter=separateur)
    for _ in range(entete - 1):
        next(lecteur, None)
    noms = [_cellule(n) or "" for n in next(lecteur, [])]

    def lignes_lues() -> Iterator[tuple[int, list[str | None]]]:
        for cellules in lecteur:
            yield lecteur.line_num, [_cellule(c) for c in cellules]

    return Tableur(noms, lignes_lues())


def _lire_excel(chemin: Path, feuille: str | None, entete: int) -> Tableur:
    try:
        classeur = fastexcel.read_excel(chemin)
    except Exception as erreur:  # fastexcel ne publie pas de hiérarchie d'erreurs stable
        raise CorrespondanceInvalide(f"{chemin.name} : classeur illisible ({erreur})") from None
    if feuille is not None and feuille not in classeur.sheet_names:
        raise CorrespondanceInvalide(
            f"{chemin.name} : feuille « {feuille} » absente ; feuilles : "
            + ", ".join(f"« {f} »" for f in classeur.sheet_names)
        )
    table = classeur.load_sheet(
        feuille if feuille is not None else 0, header_row=entete - 1, dtypes="string"
    ).to_polars()
    noms = [_cellule(n) or "" for n in table.columns]

    def lignes_lues() -> Iterator[tuple[int, list[str | None]]]:
        for position, cellules in enumerate(table.iter_rows(), start=entete + 1):
            yield position, [_cellule(c) for c in cellules]

    return Tableur(noms, lignes_lues())


def lire_tableur(correspondance: Correspondance) -> Tableur:
    """Ouvre le tableur décrit par la correspondance, sans encore lire ses lignes."""
    chemin = correspondance.fichier
    if not chemin.is_file():
        raise CorrespondanceInvalide(f"tableur introuvable : {chemin}")
    extension = chemin.suffix.lower()
    if extension in EXTENSIONS_CSV:
        separateur = correspondance.separateur
        if separateur is None and extension == ".tsv":
            separateur = "\t"
        return _lire_csv(chemin, separateur, correspondance.encodage, correspondance.entete)
    if extension in EXTENSIONS_EXCEL:
        return _lire_excel(chemin, correspondance.feuille, correspondance.entete)
    raise CorrespondanceInvalide(
        f"{chemin.name} : format non pris en charge ; formats possibles : "
        + ", ".join(EXTENSIONS_CSV + EXTENSIONS_EXCEL)
    )


def verifier_colonnes(correspondance: Correspondance, entete: list[str]) -> None:
    """Toutes les colonnes citées existent dans le tableur, et une seule fois."""
    presentes = Counter(cle_colonne(nom) for nom in entete if nom)
    absentes = [c for c in correspondance.colonnes() if presentes[cle_colonne(c)] == 0]
    if absentes:
        raise CorrespondanceInvalide(
            f"colonnes absentes de {correspondance.fichier.name} : "
            + ", ".join(f"« {c} »" for c in absentes)
            + " ; colonnes du tableur : "
            + ", ".join(f"« {n} »" for n in entete if n)
        )
    if doubles := [c for c in correspondance.colonnes() if presentes[cle_colonne(c)] > 1]:
        raise CorrespondanceInvalide(
            f"colonnes présentes plusieurs fois dans {correspondance.fichier.name} : "
            + ", ".join(f"« {c} »" for c in doubles)
        )


# --- conversion d'une ligne -------------------------------------------------------------------


def lire_date(brute: str | None, format_: str | None = None) -> date | None:
    """Date complète, au format indiqué ou à l'un des formats usuels, sinon ``None``."""
    if brute is None:
        return None
    for essai in (format_, *FORMATS_DATE) if format_ else FORMATS_DATE:
        try:
            return datetime.strptime(brute, essai).date()
        except ValueError:
            continue
    return None


def lire_annee(brute: str | None) -> int | None:
    """Première année à quatre chiffres : « 1855 », « 02/03/1855 », « vers 1850 »."""
    if brute is None or (trouvee := ANNEE.search(brute)) is None:
        return None
    return int(trouvee.group(1))


def lire_age(brut: str | None, anomalies: Counter[str]) -> int | None:
    """Âge en années révolues : « 40 », « 40 ans » ; « 6 mois » → 0."""
    if brut is None:
        return None
    texte = cle_colonne(brut)
    if lu := AGE_EN_ANNEES.fullmatch(texte):
        age = int(lu.group(1))
        if age <= 130:
            return age
    elif AGE_EN_BAS_AGE.search(texte):
        return 0
    anomalies["âge illisible"] += 1
    return None


def _code(brut: str | None, libelle: str, anomalies: Counter[str]) -> str | None:
    if brut is None:
        return None
    if MOTIF_CODE_LIEU.fullmatch(brut):
        return brut
    anomalies[f"{libelle} invalide"] += 1
    return None


def _departement(brut: str | None, anomalies: Counter[str]) -> str | None:
    if brut is None:
        return None
    if MOTIF_DEPARTEMENT.fullmatch(brut):
        return brut
    if brut.isdigit() and len(brut) == 1:  # « 1 » pour l'Ain, perdu par un tableur
        return brut.zfill(2)
    anomalies["département invalide"] += 1
    return None


def convertir_ligne(
    correspondance: Correspondance,
    ligne: Mapping[str, str | None],
    numero: int,
    occurrences: Counter[tuple[str, ...]],
    ingested_at: datetime,
    anomalies: Counter[str],
) -> tuple[Acte, list[Mention]]:
    """Convertit une ligne du tableur (cellules indexées par ``cle_colonne``) en acte et mentions.

    ``occurrences`` compte les clés déjà vues : une clé répétée reçoit un numéro d'ordre, pour
    que deux actes distincts ne partagent jamais un identifiant.
    """
    champs = correspondance.acte
    a = {nom: champ.lire(ligne) for nom, champ in champs.items()}
    type_ = lire_enumeration(TypeActe, a["type"], TYPES_USUELS)
    if type_ is None:
        raise LigneRejetee(f"type d'acte inconnu ({a['type']})" if a["type"] else "type absent")
    format_date = champs["date"].format if "date" in champs else None
    date_acte = lire_date(a.get("date"), format_date)
    annee = lire_annee(a.get("annee")) or (date_acte.year if date_acte else None)
    annee = annee or lire_annee(a.get("date"))
    if annee is None:
        raise LigneRejetee("année de l'acte illisible")
    if not 1500 <= annee <= 2100:
        raise LigneRejetee(f"année de l'acte improbable ({annee})")
    if a.get("date") and date_acte is None:
        anomalies["date de l'acte incomplète"] += 1

    code = _code(a.get("commune_code"), "code de la commune", anomalies)
    departement = _departement(a.get("departement"), anomalies)
    if departement is None and code is not None:
        departement = departement_de(code)

    cle = tuple(ligne.get(cle_colonne(c)) or "" for c in correspondance.cle) or (str(numero),)
    occurrences[cle] += 1
    if occurrences[cle] > 1:
        anomalies["clé en double (numéro d'ordre ajouté)"] += 1
        cle = (*cle, f"#{occurrences[cle]}")
    acte_id = fabriquer_id(Source.RELEVE, correspondance.nom, *cle)

    mentions: list[Mention] = []
    for rang, personne in enumerate(correspondance.personnes, start=1):
        p = {nom: champ.lire(ligne) for nom, champ in personne.champs.items()}
        if not p.get("nom") and not p.get("prenoms"):
            continue
        if not any(ligne.get(colonne) for colonne in personne.propres):
            continue  # seulement des colonnes d'une autre personne : le nom de l'enfant
        sexe = SEXE_DU_ROLE.get(personne.role)
        if p.get("sexe"):
            sexe = lire_enumeration(Sexe, p["sexe"], SEXES_USUELS)
            if sexe is None:
                anomalies["sexe inconnu"] += 1
        nature_nom = lire_enumeration(NatureNom, p.get("nature_nom"))
        if p.get("nature_nom") and nature_nom is None:
            anomalies["nature du nom inconnue"] += 1
        format_naissance = (
            personne.champs["date_naissance"].format
            if "date_naissance" in personne.champs
            else None
        )
        mentions.append(
            Mention(
                mention_id=fabriquer_id(
                    Source.RELEVE, correspondance.nom, *cle, str(rang), personne.role.value
                ),
                acte_id=acte_id,
                role=personne.role,
                nom_brut=p.get("nom"),
                prenoms_bruts=p.get("prenoms"),
                nature_nom=nature_nom,
                sexe=sexe,
                date_naissance_brute=p.get("date_naissance"),
                date_naissance=lire_date(p.get("date_naissance"), format_naissance),
                age=lire_age(p.get("age"), anomalies),
                profession=p.get("profession"),
                lieu_naissance_brut=p.get("lieu_naissance"),
                lieu_naissance_code_insee=_code(
                    p.get("lieu_naissance_code"), "code du lieu de naissance", anomalies
                ),
                confiance_source=correspondance.confiance,
            )
        )
    if not mentions:
        raise LigneRejetee("personne n'est nommé")

    acte = Acte(
        acte_id=acte_id,
        source=Source.RELEVE,
        type=type_,
        annee=annee,
        date_acte=date_acte,
        commune_code_insee=code,
        commune_label=a.get("commune"),
        departement=departement,
        depot=a.get("depot"),
        cote=a.get("cote"),
        vue=a.get("vue"),
        url_image=a.get("url_image"),
        titre_source=correspondance.titre,
        ingested_at=ingested_at,
    )
    return acte, mentions


def ingerer_releve(
    chemin: Path,
    dossier_bronze: Path,
    ingested_at: datetime | None = None,
    taille_lot: int = 200_000,
) -> RapportIngestion:
    """Convertit le relevé décrit par ``chemin`` (fichier TOML) en partition bronze
    ``releve/<nom du fichier TOML>/``.

    Réingérer le même relevé remplace sa partition et redonne les mêmes identifiants, tant que
    la clé (``cle``, ou à défaut le numéro de ligne) et le nom du fichier TOML ne changent pas.
    """
    ingested_at = ingested_at or datetime.now(UTC)
    correspondance = lire_correspondance(chemin)
    tableur = lire_tableur(correspondance)
    verifier_colonnes(correspondance, tableur.entete)
    cles = [cle_colonne(nom) for nom in tableur.entete]

    dossier = dossier_bronze / Source.RELEVE.value / correspondance.nom
    rapport = RapportIngestion(fichier=correspondance.fichier.name, dossier=dossier)
    occurrences: Counter[tuple[str, ...]] = Counter()
    with EcrivainPartition(dossier, taille_lot=taille_lot) as ecrivain:
        for numero, cellules in tableur.lignes:
            if not any(cellules):
                continue
            rapport.lignes_lues += 1
            if len(cellules) > len(cles) and any(cellules[len(cles) :]):
                rapport.anomalies["cellules au-delà de l'en-tête ignorées"] += 1
            ligne = {cle: valeur for cle, valeur in zip(cles, cellules, strict=False) if cle}
            try:
                acte, mentions = convertir_ligne(
                    correspondance, ligne, numero, occurrences, ingested_at, rapport.anomalies
                )
            except (LigneRejetee, ValidationError) as erreur:
                motif = (
                    str(erreur) if isinstance(erreur, LigneRejetee) else motif_validation(erreur)
                )
                ecrivain.rejeter(numero, motif, json.dumps(cellules, ensure_ascii=False))
                rapport.lignes_rejetees += 1
                continue
            ecrivain.ajouter(acte, mentions)
            rapport.lignes_ingerees += 1
    journal.info(
        "%s : %d lignes ingérées, %d rejetées",
        correspondance.nom,
        rapport.lignes_ingerees,
        rapport.lignes_rejetees,
    )
    return rapport


# --- modèle de correspondance -----------------------------------------------------------------

# Mots d'un nom de colonne qui désignent une personne, par ordre de priorité : « Nom père
# époux » est le père de l'époux.
MOTS_ROLES: Final = {
    "PERE": Role.PERE,
    "MERE": Role.MERE,
    "EPOUX": Role.EPOUX,
    "MARI": Role.EPOUX,
    "EPOUSE": Role.EPOUSE,
}
MOTS_IGNORES: Final = frozenset({"PARRAIN", "MARRAINE", "TEMOIN", "TEMOINS", "OBSERVATIONS"})
TYPES_DEVINES: Final = (
    ("BAPTEME", TypeActe.BAPTEME),
    ("MARIAGE", TypeActe.MARIAGE),
    ("EPOUX", TypeActe.MARIAGE),
    ("DECES", TypeActe.DECES),
    ("SEPULTURE", TypeActe.DECES),
    ("INHUMATION", TypeActe.DECES),
    ("RECENSEMENT", TypeActe.RECENSEMENT),
    ("NAISSANCE", TypeActe.NAISSANCE),
)


def _champ_personne(mots_colonne: list[str]) -> str | None:
    """Information de personne désignée par un nom de colonne, ou ``None``."""
    if any(m.startswith("PRENOM") for m in mots_colonne):
        return "prenoms"
    if "NAISSANCE" in mots_colonne or "NE" in mots_colonne or "NEE" in mots_colonne:
        return "lieu_naissance" if {"LIEU", "A"} & set(mots_colonne) else "date_naissance"
    for mot, champ in (
        ("NOM", "nom"),
        ("SEXE", "sexe"),
        ("AGE", "age"),
        ("PROFESSION", "profession"),
        ("METIER", "profession"),
    ):
        if mot in mots_colonne:
            return champ
    return None


def _champ_acte(mots_colonne: list[str]) -> str | None:
    """Information d'acte désignée par un nom de colonne, ou ``None``."""
    if "NAISSANCE" in mots_colonne:
        return None
    for mot, champ in (
        ("TYPE", "type"),
        ("NATURE", "type"),
        ("DATE", "date"),
        ("ANNEE", "annee"),
        ("COMMUNE", "commune"),
        ("PAROISSE", "commune"),
        ("LIEU", "commune"),
        ("DEPARTEMENT", "departement"),
        ("COTE", "cote"),
        ("VUE", "vue"),
        ("PAGE", "vue"),
        ("LIEN", "url_image"),
        ("URL", "url_image"),
        ("IMAGE", "url_image"),
    ):
        if mot in mots_colonne:
            return champ
    return None


def _toml(texte: str) -> str:
    """Chaîne TOML ; l'échappement JSON en est un sous-ensemble valide."""
    return json.dumps(texte, ensure_ascii=False)


def modele_correspondance(tableur: Path, feuille: str | None = None, entete: int = 1) -> str:
    """Fichier de correspondance prérempli d'après les noms de colonnes du tableur.

    Les colonnes reconnues (« Nom », « Prénoms », « Date », « Prénom du père »…) sont
    reprises ; les autres sont listées en commentaire. Le résultat est à relire : le type
    d'acte et le titre, en particulier, sont devinés.
    """
    extension = tableur.suffix.lower()
    if extension in EXTENSIONS_EXCEL and feuille is None:
        try:
            feuille = fastexcel.read_excel(tableur).sheet_names[0]
        except Exception as erreur:  # voir _lire_excel
            raise CorrespondanceInvalide(
                f"{tableur.name} : classeur illisible ({erreur})"
            ) from None
    provisoire = Correspondance(
        nom=tableur.stem,
        titre=tableur.stem,
        fichier=tableur,
        feuille=feuille,
        separateur=None,
        encodage=None,
        entete=entete,
        confiance=CONFIANCE_PAR_DEFAUT,
        cle=(),
        acte={},
        personnes=(),
    )
    colonnes = [nom for nom in lire_tableur(provisoire).entete if nom]

    acte: dict[str, str] = {}
    # personnes, repérées par les mots de rôle de leurs colonnes : () pour le sujet
    personnes: dict[tuple[str, ...], dict[str, str]] = {}
    reprises: set[str] = set()
    for colonne in colonnes:
        mots_colonne = mots(colonne)
        if MOTS_IGNORES & set(mots_colonne):
            continue
        roles = tuple(m for m in MOTS_ROLES if m in mots_colonne)
        champ_acte = None if roles else _champ_acte(mots_colonne)
        champ_personne = _champ_personne(mots_colonne)
        if champ_acte and champ_acte not in ("type", "date", "annee"):
            acte.setdefault(champ_acte, colonne)  # « Commune », « Cote »…
        elif champ_personne:
            personnes.setdefault(roles, {}).setdefault(champ_personne, colonne)
        elif champ_acte:
            acte.setdefault(champ_acte, colonne)  # « Type », « Date », « Année »
        elif roles:
            personnes.setdefault(roles, {}).setdefault("prenoms", colonne)  # « Père »
        else:
            continue
        reprises.add(colonne)

    # un parent sans colonne de nom porte en général celui de son enfant
    for roles, champs in personnes.items():
        if roles and roles[0] == "PERE" and "nom" not in champs:
            enfant = personnes.get(roles[1:], {})
            if "nom" in enfant:
                champs["nom"] = enfant["nom"]

    indices = " ".join([tableur.stem.upper(), *(majuscules_ascii(c) for c in colonnes)])
    type_ = next((t for mot, t in TYPES_DEVINES if mot in indices), TypeActe.AUTRE)

    lignes = [
        f"# Correspondance du relevé « {tableur.name} », préparée d'après ses colonnes :",
        "# à relire et compléter (voir docs/releves.md), puis « doudoumil ingest releve ».",
        "# Colonnes du tableur : " + ", ".join(f"« {c} »" for c in colonnes),
        "",
        "[releve]",
        f"titre = {_toml(tableur.stem)}  # intitulé cité dans les fiches, à préciser",
        f"fichier = {_toml(tableur.name)}",
    ]
    if feuille is not None:
        lignes.append(f"feuille = {_toml(feuille)}")
    if entete != 1:
        lignes.append(f"entete = {entete}")
    lignes += [
        f"confiance = {CONFIANCE_PAR_DEFAUT}  # fiabilité estimée de la transcription (0 à 1)",
        '# cle = ["Date", "Nom"]  # colonnes qui identifient une ligne (défaut : son numéro)',
        "",
        "[acte]",
    ]
    types = ", ".join(t.value for t in TypeActe)
    if "type" in acte:
        lignes += [
            f"type = {{ colonne = {_toml(acte['type'])}, "
            'valeurs = { B = "bapteme", M = "mariage", S = "deces" } }',
            f"# codes du relevé à vérifier ; types : {types}",
        ]
    else:
        precision = "deviné" if type_ is not TypeActe.AUTRE else "à préciser"
        lignes.append(f"type = {_toml(type_.value)}  # {precision} ; types : {types}")
    for champ in ("date", "annee", "commune", "departement", "cote", "vue", "url_image"):
        if champ in acte:
            lignes.append(f"{champ} = {{ colonne = {_toml(acte[champ])} }}")
    if "date" not in acte and "annee" not in acte:
        lignes.append('# date = { colonne = "…", format = "%d/%m/%Y" }  # ou annee : nécessaire')
    if "commune" not in acte:
        lignes.append('# commune = "…"  # nom de la commune ou de la paroisse')
    if "departement" not in acte:
        lignes.append('# departement = "29"')
    lignes.append('# depot = "AD 29"  # service d\'archives')

    ordre = ("nom", "prenoms", "sexe", "date_naissance", "age", "profession", "lieu_naissance")
    priorite = list(MOTS_ROLES)
    for roles, champs in sorted(
        personnes.items(), key=lambda e: (len(e[0]), [priorite.index(m) for m in e[0]])
    ):
        if "nom" not in champs and "prenoms" not in champs:
            continue
        role = MOTS_ROLES[roles[0]] if roles else Role.SUJET
        precision = f"  # {' de '.join(m.lower() for m in roles)}" if len(roles) > 1 else ""
        lignes += ["", "[[personne]]", f"role = {_toml(role.value)}{precision}"]
        for champ in ordre:
            if champ in champs:
                lignes.append(f"{champ} = {{ colonne = {_toml(champs[champ])} }}")
    if non_reprises := [c for c in colonnes if c not in reprises]:
        lignes += ["", "# Colonnes non reprises : " + ", ".join(f"« {c} »" for c in non_reprises)]
    return "\n".join(lignes) + "\n"
