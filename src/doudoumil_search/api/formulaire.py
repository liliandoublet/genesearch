"""Lecture du formulaire de recherche, commune aux pages, à l'API JSON et à l'export CSV.

Les paramètres arrivent dans l'adresse (``GET``), ce qui rend une recherche partageable et
rejouable : ``/recherche?q=LE+GOFF+Marie&naissance=1930-1932&lieu=Quimper+(29)``.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import Final
from urllib.parse import urlencode

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.search.moteur import Resultat
from doudoumil_search.search.requete import (
    Lieu,
    LieuInconnu,
    Requete,
    lire_intervalle,
    resoudre_lieu,
    separer_nom_prenoms,
)

PAR_PAGE: Final = 20
SOURCES: Final = {"insee_deces": "Décès INSEE (depuis 1970)", "socface": "Recensements"}


class FormulaireInvalide(ValueError):
    """Le formulaire contient des erreurs ; ``erreurs`` les liste, champ par champ."""

    def __init__(self, erreurs: dict[str, str]) -> None:
        super().__init__("; ".join(erreurs.values()))
        self.erreurs = erreurs


@dataclass
class Formulaire:
    """Valeurs saisies, telles quelles : elles sont réaffichées dans le formulaire."""

    q: str = ""
    nom: str = ""
    prenoms: str = ""
    sexe: str = ""
    naissance: str = ""
    annees: str = ""
    lieu: str = ""
    conjoint: str = ""
    source: str = ""
    # filtres de la colonne de gauche, appliqués aux résultats déjà classés
    filtre_source: str = ""
    filtre_departement: str = ""
    filtre_decennie: str = ""
    page: int = 1
    avance: bool = field(default=False)

    @classmethod
    def depuis(cls, parametres: Mapping[str, str]) -> "Formulaire":
        valeurs = {}
        for champ in fields(cls):
            brute = (parametres.get(champ.name) or "").strip()
            if champ.name == "page":
                valeurs["page"] = max(1, int(brute)) if brute.isdigit() else 1
            elif champ.name == "avance":
                valeurs["avance"] = brute in ("1", "on", "oui")
            else:
                valeurs[champ.name] = brute
        formulaire = cls(**valeurs)
        # un champ avancé rempli ouvre la recherche avancée
        avances = (formulaire.nom, formulaire.prenoms, formulaire.sexe, formulaire.naissance)
        avances += (formulaire.annees, formulaire.lieu, formulaire.conjoint, formulaire.source)
        formulaire.avance = formulaire.avance or any(avances)
        return formulaire

    @property
    def vide(self) -> bool:
        return not (self.q or self.nom or self.prenoms)

    def parametres(self, **changements: str | int) -> dict[str, str]:
        """Paramètres non vides, avec des changements (filtre, page…), pour fabriquer un lien."""
        valeurs = {f.name: getattr(self, f.name) for f in fields(self)}
        valeurs.update(changements)
        resultat = {}
        for nom, valeur in valeurs.items():
            if nom == "avance":
                continue
            if nom == "page" and valeur == 1:
                continue
            if valeur not in ("", None):
                resultat[nom] = str(valeur)
        return resultat

    def adresse(self, chemin: str = "/recherche", **changements: str | int) -> str:
        parametres = self.parametres(**changements)
        return f"{chemin}?{urlencode(parametres)}" if parametres else chemin

    def requete(self, referentiel: Referentiel | None, limite: int = PAR_PAGE) -> Requete:
        """Requête du moteur ; lève ``FormulaireInvalide`` avec un message par champ fautif."""
        erreurs: dict[str, str] = {}
        nom, prenoms = separer_nom_prenoms(self.q)
        nom, prenoms = self.nom or nom, self.prenoms or prenoms
        naissance = annees = None
        for champ in ("naissance", "annees"):
            texte = getattr(self, champ)
            if texte:
                try:
                    valeur = lire_intervalle(texte)
                except ValueError as erreur:
                    erreurs[champ] = str(erreur)
                else:
                    if champ == "naissance":
                        naissance = valeur
                    else:
                        annees = valeur
        lieu = Lieu()
        if self.lieu:
            try:
                lieu = resoudre_lieu(self.lieu, referentiel)
            except LieuInconnu as erreur:
                erreurs["lieu"] = str(erreur)
        if self.sexe and self.sexe not in ("M", "F"):
            erreurs["sexe"] = "sexe attendu : M ou F"
        if self.source and self.source not in SOURCES:
            erreurs["source"] = f"source inconnue : « {self.source} »"
        if erreurs:
            raise FormulaireInvalide(erreurs)
        requete = Requete.creer(
            nom=nom,
            prenoms=prenoms,
            sexe=self.sexe or None,
            naissance=naissance,
            annees=annees,
            lieu=lieu,
            conjoint=self.conjoint or None,
            sources=(self.source,) if self.source else (),
            limite=limite,
        )
        if not requete.est_exploitable():
            raise FormulaireInvalide(
                {"q": "indiquez un nom, ou un prénom avec une année de naissance et un lieu"}
            )
        return requete


def decennie(resultat: Resultat) -> str:
    return f"{resultat.annee // 10 * 10}"


def filtrer(resultats: Sequence[Resultat], formulaire: Formulaire) -> list[Resultat]:
    """Applique les filtres de la colonne de gauche."""
    return [
        r
        for r in resultats
        if (not formulaire.filtre_source or r.source == formulaire.filtre_source)
        and (not formulaire.filtre_departement or r.departement == formulaire.filtre_departement)
        and (not formulaire.filtre_decennie or decennie(r) == formulaire.filtre_decennie)
    ]


@dataclass(frozen=True)
class Facettes:
    """Compteurs des filtres, calculés sur tous les résultats classés."""

    sources: list[tuple[str, int]]
    departements: list[tuple[str, int]]
    decennies: list[tuple[str, int]]


def facettes(resultats: Sequence[Resultat], maximum: int = 12) -> Facettes:
    sources = Counter(r.source for r in resultats)
    departements = Counter(r.departement for r in resultats if r.departement)
    decennies = Counter(decennie(r) for r in resultats)
    return Facettes(
        sources=sources.most_common(),
        departements=departements.most_common(maximum),
        decennies=sorted(decennies.items()),
    )
