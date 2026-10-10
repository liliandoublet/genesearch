"""Modèle pivot commun à toutes les sources : actes et mentions nominatives.

Un *acte* est un document d'archive (acte d'état civil, feuillet de recensement,
enregistrement INSEE). Une *mention* est une personne citée dans cet acte avec un rôle.

Principes :
- les champs ``*_brut(s)`` conservent la valeur de la source sans aucune transformation ;
- les champs ``*_norm``, ``nom_phonetique`` et ``annee_naissance_min/max`` sont vides en
  couche bronze et remplis en couche silver par la normalisation ;
- la provenance (``source``, ``depot``, ``cote``, ``vue``, ``url_image``) permet toujours le
  retour au document original.
"""

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


class Source(StrEnum):
    """Sources de données prises en charge."""

    INSEE_DECES = "insee_deces"
    SOCFACE = "socface"
    RELEVE = "releve"  # relevé fourni par l'utilisateur (cercle généalogique, transcription)


class TypeActe(StrEnum):
    """Nature de l'acte."""

    NAISSANCE = "naissance"
    MARIAGE = "mariage"
    DECES = "deces"
    BAPTEME = "bapteme"
    RECENSEMENT = "recensement"
    AUTRE = "autre"


class Role(StrEnum):
    """Rôle d'une personne dans l'acte."""

    SUJET = "sujet"
    PERE = "pere"
    MERE = "mere"
    EPOUX = "epoux"
    EPOUSE = "epouse"
    ENFANT = "enfant"
    TEMOIN = "temoin"
    CHEF_MENAGE = "chef_menage"
    AUTRE = "autre"


class Sexe(StrEnum):
    """Sexe déclaré dans la source."""

    M = "M"
    F = "F"


class NatureNom(StrEnum):
    """Nature du nom relevé : celui de naissance, ou celui du mari pour une femme mariée.

    Dans les recensements, une épouse ou une veuve est en général inscrite sous le nom de son
    mari : la recherche ne doit alors pas la pénaliser sur le nom (règle R2 de PLAN.md).
    """

    NAISSANCE = "naissance"
    MARITAL = "marital"
    INCONNUE = "inconnue"


# Code du Code Officiel Géographique : 5 caractères, le deuxième peut valoir A ou B pour la
# Corse (2A004 = Ajaccio). Les pays étrangers sont codés 99xxx dans les fichiers INSEE.
CodeInsee = Annotated[str, StringConstraints(pattern=r"^\d[\dAB]\d{3}$")]

# Départements métropolitains (01-95, 2A, 2B), départements et collectivités d'outre-mer
# (971 à 978, 984 à 989) et étranger (99).
Departement = Annotated[str, StringConstraints(pattern=r"^(\d{2}|2[AB]|97[1-8]|98[4-9])$")]

# Années de naissance : une personne citée en 1500 a pu naître bien avant.
AnneeNaissance = Annotated[int, Field(ge=1300, le=2100)]

# Identifiant hexadécimal de 128 bits produit par fabriquer_id().
Identifiant = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


def _exiger_fuseau(valeur: datetime) -> datetime:
    """Refuse les dates-heures naïves : l'horodatage d'ingestion doit être non ambigu."""
    if valeur.tzinfo is None:
        raise ValueError("ingested_at doit porter un fuseau horaire (UTC attendu)")
    return valeur


def fabriquer_id(source: Source, *cle_naturelle: str) -> str:
    """Calcule un identifiant déterministe à partir de la source et d'une clé naturelle.

    Réingérer la même ligne source redonne le même identifiant, ce qui rend l'ingestion
    idempotente et permet de dédoublonner les recouvrements entre fichiers.

    Le séparateur ``\\x1f`` (Unit Separator ASCII) ne peut pas apparaître dans les données
    textuelles des sources, ce qui évite qu'on obtienne la même concaténation à partir de
    clés différentes (``("ab", "c")`` et ``("a", "bc")``).

    Args:
        source: source de la donnée.
        cle_naturelle: éléments qui identifient la ligne de façon unique dans la source
            (par exemple nom du fichier et position de l'enregistrement).

    Returns:
        Empreinte BLAKE2b de 128 bits en hexadécimal (32 caractères).
    """
    if not cle_naturelle:
        raise ValueError("la clé naturelle ne peut pas être vide")
    contenu = "\x1f".join((source.value, *cle_naturelle))
    return hashlib.blake2b(contenu.encode("utf-8"), digest_size=16).hexdigest()


class _ModelePivot(BaseModel):
    """Configuration commune : immuable, aucun champ inconnu, aucune transformation."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Acte(_ModelePivot):
    """Document d'archive et sa provenance."""

    acte_id: Identifiant
    source: Source
    type: TypeActe
    annee: int = Field(ge=1500, le=2100)
    date_acte: date | None = None
    commune_code_insee: CodeInsee | None = None
    commune_label: str | None = None
    departement: Departement | None = None
    depot: str | None = Field(default=None, description="Service détenteur, ex. « AD 35 »")
    cote: str | None = None
    vue: str | None = None
    url_image: str | None = None
    titre_source: str | None = Field(
        default=None, description="Intitulé de la source, ex. « Baptêmes de Plougastel, relevé »"
    )
    ingested_at: Annotated[datetime, AfterValidator(_exiger_fuseau)]


class Mention(_ModelePivot):
    """Personne citée dans un acte."""

    mention_id: Identifiant
    acte_id: Identifiant
    role: Role
    nom_brut: str | None = None
    prenoms_bruts: str | None = None
    nature_nom: NatureNom | None = None
    nom_norm: str | None = None
    nom_phonetique: str | None = None
    prenoms_norm: str | None = None
    sexe: Sexe | None = None
    date_naissance_brute: str | None = Field(
        default=None, description="Date telle qu'écrite dans la source, même incomplète"
    )
    date_naissance: date | None = Field(default=None, description="Seulement si complète")
    annee_naissance_min: AnneeNaissance | None = None
    annee_naissance_max: AnneeNaissance | None = None
    age: int | None = Field(default=None, ge=0, le=130, description="Âge en années révolues")
    profession: str | None = None
    lieu_naissance_brut: str | None = None
    lieu_naissance_code_insee: CodeInsee | None = None
    confiance_source: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fiabilité estimée de la transcription (1 = saisie certaine)",
    )

    @model_validator(mode="after")
    def _verifier_intervalle_naissance(self) -> Self:
        """L'intervalle de naissance est entier (deux bornes ordonnées) ou absent."""
        bornes = (self.annee_naissance_min, self.annee_naissance_max)
        if (bornes[0] is None) != (bornes[1] is None):
            raise ValueError("annee_naissance_min et annee_naissance_max vont ensemble")
        if bornes[0] is not None and bornes[1] is not None and bornes[0] > bornes[1]:
            raise ValueError("annee_naissance_min doit être inférieure ou égale à max")
        return self
