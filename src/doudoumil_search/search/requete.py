"""Requête de recherche et interprétation du texte saisi.

Une requête porte sur une personne : nom, prénoms, sexe, intervalle de naissance, lieu,
période de l'acte, nom du conjoint (règle R2). Le lieu est résolu en codes de communes
actuelles et en départements à l'aide du référentiel des communes.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Final

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.noms import normaliser_nom
from doudoumil_search.normalize.prenoms import liste_prenoms
from doudoumil_search.pivot import Sexe

PARTICULES: Final = frozenset(
    {"LE", "LA", "LES", "DE", "DU", "DES", "D", "DA", "DI", "DOS", "VAN", "VON", "MAC", "MC"}
)
MOTIF_DEPARTEMENT: Final = re.compile(r"^(\d{2}|2[AB]|97\d|98\d)$", re.IGNORECASE)
MOTIF_CODE_COMMUNE: Final = re.compile(r"^\d[\dAB]\d{3}$", re.IGNORECASE)
MOTIF_COMMUNE_ET_DEPARTEMENT: Final = re.compile(r"^(.*?)\s*\((\w{2,3})\)\s*$")


class LieuInconnu(ValueError):
    """Le lieu demandé ne correspond à aucune commune ni à aucun département."""


def lire_intervalle(texte: str) -> tuple[int, int]:
    """« 1930-1932 » → (1930, 1932) ; « 1931 » ou « 1931- » → (1931, 1931).

    Lève ``ValueError`` avec un message en français si le texte n'est pas un intervalle.
    """
    debut, _, fin = texte.strip().partition("-")
    try:
        a, b = int(debut), int(fin or debut)
    except ValueError:
        raise ValueError(f"intervalle d'années invalide : « {texte} »") from None
    if a > b:
        raise ValueError(f"intervalle à l'envers : « {texte} »")
    return a, b


@dataclass(frozen=True)
class Lieu:
    """Lieu résolu.

    ``communes`` : codes des communes demandées ; ``departements`` : départements demandés,
    ou départements de ces communes (pour la règle « même département » du score et du
    canal C).
    """

    communes: frozenset[str] = frozenset()
    departements: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.communes or self.departements)


def _departement_du_code(code: str, referentiel: Referentiel | None) -> str:
    commune = referentiel.commune(code) if referentiel else None
    if commune:
        return commune.departement
    return code[:3] if code.startswith(("97", "98")) else code[:2]


def _lieu_des_communes(codes: set[str], referentiel: Referentiel | None) -> Lieu:
    return Lieu(
        communes=frozenset(codes),
        departements=frozenset(_departement_du_code(c, referentiel) for c in codes),
    )


@dataclass(frozen=True)
class Requete:
    nom: str | None = None
    prenoms: tuple[str, ...] = ()
    sexe: Sexe | None = None
    naissance: tuple[int, int] | None = None
    annees: tuple[int, int] | None = None
    lieu: Lieu = field(default_factory=Lieu)
    conjoint: str | None = None
    sources: tuple[str, ...] = ()
    limite: int = 20

    def vers_dict(self) -> dict[str, Any]:
        """Forme JSON de la requête, pour la conserver avec une trouvaille."""
        return {
            "nom": self.nom,
            "prenoms": list(self.prenoms),
            "sexe": self.sexe.value if self.sexe else None,
            "naissance": list(self.naissance) if self.naissance else None,
            "annees": list(self.annees) if self.annees else None,
            "lieu": {
                "communes": sorted(self.lieu.communes),
                "departements": sorted(self.lieu.departements),
            },
            "conjoint": self.conjoint,
            "sources": list(self.sources),
        }

    @classmethod
    def depuis_dict(cls, donnees: dict[str, Any]) -> "Requete":
        """Inverse de ``vers_dict`` : les valeurs sont déjà normalisées."""
        lieu = donnees.get("lieu") or {}
        naissance, annees = donnees.get("naissance"), donnees.get("annees")
        return cls(
            nom=donnees.get("nom"),
            prenoms=tuple(donnees.get("prenoms") or ()),
            sexe=Sexe(donnees["sexe"]) if donnees.get("sexe") else None,
            naissance=(naissance[0], naissance[1]) if naissance else None,
            annees=(annees[0], annees[1]) if annees else None,
            lieu=Lieu(
                frozenset(lieu.get("communes") or ()), frozenset(lieu.get("departements") or ())
            ),
            conjoint=donnees.get("conjoint"),
            sources=tuple(donnees.get("sources") or ()),
        )

    @classmethod
    def creer(
        cls,
        nom: str | None = None,
        prenoms: str | None = None,
        sexe: Sexe | str | None = None,
        naissance: tuple[int, int] | None = None,
        annees: tuple[int, int] | None = None,
        lieu: Lieu | None = None,
        conjoint: str | None = None,
        sources: tuple[str, ...] = (),
        limite: int = 20,
    ) -> "Requete":
        """Requête dont le nom, les prénoms et le conjoint sont normalisés comme en silver."""
        return cls(
            nom=normaliser_nom(nom),
            prenoms=tuple(liste_prenoms(prenoms)),
            sexe=Sexe(sexe) if sexe else None,
            naissance=naissance,
            annees=annees,
            lieu=lieu or Lieu(),
            conjoint=normaliser_nom(conjoint),
            sources=sources,
            limite=limite,
        )

    def est_exploitable(self) -> bool:
        """Il faut un nom, ou à défaut un prénom avec une naissance et un lieu (canal C)."""
        return bool(self.nom) or bool(self.prenoms and self.naissance and self.lieu)


def separer_nom_prenoms(texte: str) -> tuple[str | None, str | None]:
    """« LE GOFF Marie Josèphe » → (« LE GOFF », « Marie Josèphe »).

    Les mots entièrement en majuscules forment le nom. Si la casse ne permet pas de trancher,
    le premier mot est le nom, avec les particules qui le précèdent (« le goff marie »).
    """
    mots_saisis = texte.split()
    if not mots_saisis:
        return None, None
    majuscules = [m for m in mots_saisis if m.isupper() and len(m.strip(".-'")) > 0]
    if majuscules and len(majuscules) < len(mots_saisis):
        nom = [m for m in mots_saisis if m in majuscules]
        prenoms = [m for m in mots_saisis if m not in majuscules]
        return " ".join(nom), " ".join(prenoms) or None
    position = 0
    while (
        position < len(mots_saisis) - 1 and mots_saisis[position].upper().strip("'") in PARTICULES
    ):
        position += 1
    nom = mots_saisis[: position + 1]
    reste = mots_saisis[position + 1 :]
    return " ".join(nom), " ".join(reste) or None


def resoudre_lieu(texte: str, referentiel: Referentiel | None) -> Lieu:
    """« 29 » → département ; « 29232 » ou « Quimper » ou « Saint-Denis (974) » → commune."""
    texte = texte.strip()
    if MOTIF_DEPARTEMENT.match(texte):
        return Lieu(departements=frozenset({texte.upper()}))
    if MOTIF_CODE_COMMUNE.match(texte):
        code = texte.upper()
        actuel = referentiel.code_actuel(code) if referentiel else None
        return _lieu_des_communes({code, actuel or code}, referentiel)
    if referentiel is None:
        raise LieuInconnu(
            f"« {texte} » : le référentiel des communes est nécessaire pour un nom de lieu "
            "(doudoumil telecharge communes)"
        )
    departement = None
    if correspondance := MOTIF_COMMUNE_ET_DEPARTEMENT.match(texte):
        texte, departement = correspondance.group(1), correspondance.group(2).upper()
    codes = referentiel.codes_du_nom(texte, departement)
    if not codes:
        raise LieuInconnu(f"« {texte} » : commune inconnue")
    return _lieu_des_communes(codes, referentiel)
