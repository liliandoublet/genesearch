"""Connecteur du fichier des personnes décédées de l'INSEE (publié sur data.gouv.fr).

Chaque ligne décrit un décès, en champs à largeur fixe. Format retenu, **à revérifier sur un
fichier réel** (la documentation officielle n'était pas accessible lors de l'écriture) :

=================================================  ========  ========
champ                                              position  longueur
=================================================  ========  ========
nom et prénoms, sous la forme ``NOM*PRENOMS/``         1        80
sexe (``1`` masculin, ``2`` féminin)                  81         1
date de naissance ``AAAAMMJJ`` (``00`` si inconnu)    82         8
code du lieu de naissance                             90         5
commune de naissance en clair                         95        30
pays de naissance en clair                           125        30
date de décès ``AAAAMMJJ``                           155         8
code du lieu de décès                                163         5
numéro de l'acte de décès                            168         9
=================================================  ========  ========

Les codes de lieu suivent le Code officiel géographique ; une naissance à l'étranger est codée
``99`` suivi du code du pays.

Conversion vers le pivot (couche bronze, sans normalisation) : un acte ``deces`` et une mention
``sujet``. Une ligne n'est rejetée que si elle ne permet pas de dater le décès ; les autres
défauts (code de lieu invalide, date de naissance incomplète) sont tolérés et comptés.
"""

import logging
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from doudoumil_search.ingest.commun import (
    MOTIF_CODE_LIEU,
    LigneRejetee,
    RapportIngestion,
    departement_de,
    motif_validation,
)
from doudoumil_search.ingest.ecriture import EcrivainPartition
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

DEPOT: Final = "INSEE"
LONGUEUR_LIGNE: Final = 176

# (nom du champ, position de départ comptée à partir de 1, longueur)
CHAMPS: Final = (
    ("nom_prenoms", 1, 80),
    ("sexe", 81, 1),
    ("date_naissance", 82, 8),
    ("code_lieu_naissance", 90, 5),
    ("commune_naissance", 95, 30),
    ("pays_naissance", 125, 30),
    ("date_deces", 155, 8),
    ("code_lieu_deces", 163, 5),
    ("numero_acte", 168, 9),
)

SEXES: Final = {"1": Sexe.M, "2": Sexe.F}


def decouper_ligne(ligne: str) -> dict[str, str]:
    """Découpe une ligne en champs bruts, sans les espaces de remplissage.

    Une ligne plus courte que le format est complétée par des espaces : certains outils
    suppriment les espaces de fin de ligne.
    """
    ligne = ligne.rstrip("\r\n")
    if len(ligne) > LONGUEUR_LIGNE:
        raise LigneRejetee(f"ligne trop longue ({len(ligne)} caractères)")
    ligne = ligne.ljust(LONGUEUR_LIGNE)
    return {nom: ligne[debut - 1 : debut - 1 + longueur].strip() for nom, debut, longueur in CHAMPS}


def separer_nom_prenoms(nom_prenoms: str) -> tuple[str | None, str | None]:
    """Sépare ``NOM*PRENOMS/`` en nom et prénoms, sans autre transformation."""
    valeur = nom_prenoms.split("/", 1)[0]
    nom, separateur, prenoms = valeur.partition("*")
    if not separateur:
        return (nom.strip() or None), None
    return (nom.strip() or None), (prenoms.strip() or None)


def lire_date(brute: str) -> date | None:
    """Date complète ``AAAAMMJJ`` ou ``None`` si elle est incomplète ou impossible."""
    if len(brute) != 8 or not brute.isdigit():
        return None
    try:
        return date(int(brute[:4]), int(brute[4:6]), int(brute[6:]))
    except ValueError:
        return None


def lire_annee(brute: str) -> int | None:
    """Année d'une date ``AAAAMMJJ``, même si le mois ou le jour valent ``00``."""
    if len(brute) != 8 or not brute.isdigit() or brute[:4] == "0000":
        return None
    return int(brute[:4])


def cle_naturelle(champs: dict[str, str]) -> tuple[str, ...]:
    """Clé qui identifie un décès indépendamment du fichier qui le contient.

    Un même décès peut figurer dans un fichier mensuel et dans le fichier annuel : une clé de
    contenu lui donne le même identifiant dans les deux, ce qui permet de dédoublonner. La clé
    est la date de décès, la commune et le numéro d'acte ; à défaut de numéro ou de commune,
    on se rabat sur l'identité de la personne.
    """
    if champs["numero_acte"] and champs["code_lieu_deces"]:
        return ("acte", champs["date_deces"], champs["code_lieu_deces"], champs["numero_acte"])
    return (
        "personne",
        champs["nom_prenoms"],
        champs["date_naissance"],
        champs["date_deces"],
        champs["code_lieu_deces"],
    )


def convertir(
    champs: dict[str, str],
    fichier: str,
    numero_ligne: int,
    ingested_at: datetime,
    anomalies: Counter[str],
) -> tuple[Acte, Mention]:
    """Convertit les champs bruts d'une ligne en acte et mention pivot."""
    annee = lire_annee(champs["date_deces"])
    if annee is None:
        raise LigneRejetee("date de décès illisible")
    if not 1500 <= annee <= 2100:
        raise LigneRejetee(f"année de décès improbable ({annee})")
    date_deces = lire_date(champs["date_deces"])
    if date_deces is None:
        anomalies["date de décès incomplète"] += 1

    code_deces = _code_valide(champs["code_lieu_deces"], "code du lieu de décès", anomalies)
    code_naissance = _code_valide(
        champs["code_lieu_naissance"], "code du lieu de naissance", anomalies
    )
    departement = departement_de(code_deces) if code_deces else None

    date_naissance = lire_date(champs["date_naissance"])
    if champs["date_naissance"] and date_naissance is None:
        anomalies["date de naissance incomplète"] += 1

    sexe = SEXES.get(champs["sexe"])
    if sexe is None:
        anomalies["sexe absent ou inconnu"] += 1

    nom, prenoms = separer_nom_prenoms(champs["nom_prenoms"])
    cle = cle_naturelle(champs)
    acte_id = fabriquer_id(Source.INSEE_DECES, *cle)

    acte = Acte(
        acte_id=acte_id,
        source=Source.INSEE_DECES,
        type=TypeActe.DECES,
        annee=annee,
        date_acte=date_deces,
        commune_code_insee=code_deces,
        departement=departement,
        depot=DEPOT,
        cote=fichier,
        vue=str(numero_ligne),
        ingested_at=ingested_at,
    )
    mention = Mention(
        mention_id=fabriquer_id(Source.INSEE_DECES, *cle, Role.SUJET.value),
        acte_id=acte_id,
        role=Role.SUJET,
        nom_brut=nom,
        prenoms_bruts=prenoms,
        # Le fichier est réputé donner le nom de naissance ; à confirmer sur la documentation.
        nature_nom=NatureNom.NAISSANCE,
        sexe=sexe,
        date_naissance_brute=champs["date_naissance"] or None,
        date_naissance=date_naissance,
        lieu_naissance_brut=champs["commune_naissance"] or None,
        lieu_naissance_code_insee=code_naissance,
        confiance_source=1.0,
    )
    return acte, mention


def _code_valide(code: str, libelle: str, anomalies: Counter[str]) -> str | None:
    """Garde un code de lieu bien formé ; un code absent ou invalide devient ``None``."""
    if not code:
        anomalies[f"{libelle} absent"] += 1
        return None
    if MOTIF_CODE_LIEU.fullmatch(code):
        return code
    anomalies[f"{libelle} invalide"] += 1
    return None


def lire_lignes(chemin: Path) -> Iterator[tuple[int, str]]:
    """Lit le fichier ligne à ligne, numérotées à partir de 1.

    Chaque ligne est décodée en UTF-8 ou, à défaut, en Latin-1 : les fichiers anciens ne sont
    pas forcément en UTF-8, et une ligne mal encodée ne doit pas bloquer tout le fichier.
    """
    with chemin.open("rb") as fichier:
        for numero, octets in enumerate(fichier, start=1):
            try:
                ligne = octets.decode("utf-8")
            except UnicodeDecodeError:
                ligne = octets.decode("latin-1")
            yield numero, ligne


def ingerer_fichier(
    chemin: Path,
    dossier_bronze: Path,
    ingested_at: datetime | None = None,
    taille_lot: int = 200_000,
) -> RapportIngestion:
    """Convertit un fichier INSEE en partition bronze ``insee_deces/<nom du fichier>/``.

    Réingérer le même fichier remplace sa partition et redonne les mêmes identifiants.
    """
    ingested_at = ingested_at or datetime.now(UTC)
    dossier = dossier_bronze / Source.INSEE_DECES.value / chemin.stem
    rapport = RapportIngestion(fichier=chemin.name, dossier=dossier)
    with EcrivainPartition(dossier, taille_lot=taille_lot) as ecrivain:
        for numero, ligne in lire_lignes(chemin):
            if not ligne.strip():
                continue
            rapport.lignes_lues += 1
            try:
                champs = decouper_ligne(ligne)
                acte, mention = convertir(
                    champs, chemin.name, numero, ingested_at, rapport.anomalies
                )
            except (LigneRejetee, ValidationError) as erreur:
                motif = (
                    str(erreur) if isinstance(erreur, LigneRejetee) else motif_validation(erreur)
                )
                ecrivain.rejeter(numero, motif, ligne.rstrip("\r\n"))
                rapport.lignes_rejetees += 1
                continue
            ecrivain.ajouter(acte, [mention])
            rapport.lignes_ingerees += 1
    journal.info(
        "%s : %d lignes ingérées, %d rejetées",
        chemin.name,
        rapport.lignes_ingerees,
        rapport.lignes_rejetees,
    )
    return rapport
