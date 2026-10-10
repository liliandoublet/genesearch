"""Score de classement d'un candidat (règles R2 à R5 de PLAN.md).

Le score est une somme pondérée de quatre composantes comprises entre 0 et 1 : nom, prénoms,
naissance et lieu. Une composante sans information prend la valeur neutre ``NEUTRE``, ni bonus
ni pénalité. La fiabilité de la transcription rapproche les composantes de cette valeur
neutre : ``s' = c × s + (1 − c) × NEUTRE``.

Les poids, tolérances et seuils sont des valeurs de départ, à régler sur le jeu d'évaluation.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from rapidfuzz.distance import JaroWinkler

from doudoumil_search.normalize.noms import compacter

NEUTRE: Final = 0.5
POIDS: Final = {"nom": 0.35, "prenoms": 0.30, "naissance": 0.20, "lieu": 0.15}
BONUS_PRENOM_USUEL: Final = 0.05
# Tolérance sur l'année de naissance, en années, selon la source (R3).
TOLERANCE_NAISSANCE: Final = {"insee_deces": 1, "socface": 2}
TOLERANCE_PAR_DEFAUT: Final = 2
SCORE_LIEU_DEPARTEMENT: Final = 0.7
SEUILS_LIBELLES: Final = ((0.9, "très probable"), (0.6, "probable"))
LIBELLE_FAIBLE: Final = "à vérifier"
LIBELLE_NON_CALIBRE: Final = "non calibré"


def tolerance(source: str) -> int:
    return TOLERANCE_NAISSANCE.get(source, TOLERANCE_PAR_DEFAUT)


def ressemblance(a: str, b: str) -> float:
    """Jaro-Winkler, en ignorant les espaces si cela rapproche (``LE GOFF`` / ``LEGOFF``)."""
    return max(JaroWinkler.similarity(a, b), JaroWinkler.similarity(compacter(a), compacter(b)))


def score_nom(
    nom_requete: str | None,
    nom_candidat: str | None,
    nom_marital: bool = False,
    conjoint: str | None = None,
) -> float | None:
    """Ressemblance des noms ; ``None`` (neutre) faute d'information.

    Pour un nom ``marital`` (règle R2), le nom de la requête, qui est le nom de naissance, ne
    peut pas être comparé : on compare le nom du conjoint s'il est donné, sinon c'est neutre.
    """
    if nom_candidat is None:
        return None
    if nom_marital:
        return ressemblance(conjoint, nom_candidat) if conjoint else None
    if nom_requete is None:
        return None
    return ressemblance(nom_requete, nom_candidat)


def score_prenoms(prenoms_requete: Sequence[str], prenoms_candidat: Sequence[str]) -> float | None:
    """Score des prénoms, indépendant de leur ordre (règle R4).

    Chaque prénom demandé est comparé au prénom le plus proche du candidat ; la moyenne de ces
    meilleures ressemblances compte pour 95 % du score. Les 5 % restants récompensent un
    premier prénom identique (prénom usuel probable) : « Marie » vaut 1 contre « Marie
    Josèphe » et 0,95 contre « Josèphe Marie ». Les prénoms du candidat absents de la requête
    ne pénalisent pas.
    """
    if not prenoms_requete or not prenoms_candidat:
        return None
    meilleures = [
        max(JaroWinkler.similarity(demande, prenom) for prenom in prenoms_candidat)
        for demande in prenoms_requete
    ]
    moyenne = sum(meilleures) / len(meilleures)
    usuel = 1.0 if prenoms_requete[0] == prenoms_candidat[0] else 0.0
    return (1.0 - BONUS_PRENOM_USUEL) * moyenne + BONUS_PRENOM_USUEL * usuel


def ecart_annees(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Nombre d'années entre deux intervalles (0 s'ils se chevauchent)."""
    return max(0, b[0] - a[1], a[0] - b[1])


def score_naissance(
    requete: tuple[int, int] | None, candidat: tuple[int, int] | None, tolerance_annees: int
) -> float | None:
    """1 si les intervalles se chevauchent, puis décroissance linéaire avec l'écart (R3).

    Le score devient nul une année après la limite de tolérance : un candidat à la limite garde
    un score faible mais non nul, ce qui le distingue d'un candidat franchement trop vieux.
    """
    if requete is None or candidat is None:
        return None
    return max(0.0, 1.0 - ecart_annees(requete, candidat) / (tolerance_annees + 1))


def score_lieu(
    communes_requete: frozenset[str],
    departements_requete: frozenset[str],
    communes_candidat: Sequence[str | None],
    departements_candidat: Sequence[str | None],
) -> float | None:
    """Même commune : 1 ; même département : 0,7 (ou 1 si la requête ne vise qu'un département)."""
    if not communes_requete and not departements_requete:
        return None
    communes = {c for c in communes_candidat if c}
    departements = {d for d in departements_candidat if d}
    if not communes and not departements:
        return None
    if communes_requete & communes:
        return 1.0
    if departements_requete & departements:
        return SCORE_LIEU_DEPARTEMENT if communes_requete else 1.0
    return 0.0


@dataclass(frozen=True)
class Composantes:
    """Composantes brutes du score ; ``None`` signifie « sans information »."""

    nom: float | None
    prenoms: float | None
    naissance: float | None
    lieu: float | None

    def score(self, confiance: float = 1.0) -> float:
        """Somme pondérée, composantes rapprochées du neutre selon la fiabilité (R5)."""
        total = 0.0
        for nom, poids in POIDS.items():
            valeur = getattr(self, nom)
            brute = NEUTRE if valeur is None else valeur
            total += poids * (confiance * brute + (1.0 - confiance) * NEUTRE)
        return total


def libelle(probabilite: float | None) -> str:
    if probabilite is None:
        return LIBELLE_NON_CALIBRE
    for seuil, texte in SEUILS_LIBELLES:
        if probabilite >= seuil:
            return texte
    return LIBELLE_FAIBLE
