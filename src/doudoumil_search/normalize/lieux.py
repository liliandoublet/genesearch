"""Référentiel des communes et rattachement des lieux au Code officiel géographique.

Source : le paquet ``@etalab/decoupage-administratif`` (licence MIT, données issues du COG de
l'INSEE), téléchargé à la demande depuis le registre npm dans ``data/ref/communes/``. Il
décrit les communes actuelles, les communes déléguées et associées (rattachées à leur
chef-lieu), les arrondissements municipaux de Paris, Lyon et Marseille, et les anciens codes
des communes fusionnées.

Le référentiel sert à :

- ramener un code ancien au code de la commune actuelle (un décès de 1975 porte le code de la
  commune d'alors, qui a pu fusionner depuis) ;
- donner le nom d'une commune à partir de son code ;
- retrouver le ou les codes d'un nom de lieu (requêtes, sources sans codes).

Limite connue : les fusions anciennes sans commune déléguée ni ancien code conservé ne sont
pas couvertes ; le fichier des mouvements de communes de l'INSEE les complétera.
"""

import io
import json
import re
import tarfile
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.request import Request, urlopen

from doudoumil_search.normalize.texte import SEPARATEURS, majuscules_ascii

VERSION_REFERENTIEL: Final = "6.0.0"
URL_REFERENTIEL: Final = (
    "https://registry.npmjs.org/@etalab/decoupage-administratif/-/"
    f"decoupage-administratif-{VERSION_REFERENTIEL}.tgz"
)
FICHIERS: Final = ("communes.json", "departements.json")

# Abréviations courantes des noms de lieux, une fois les mots séparés.
ABREVIATIONS: Final = {"ST": "SAINT", "STE": "SAINTE", "STS": "SAINTS", "STES": "SAINTES"}
HORS_ALPHANUMERIQUE: Final = re.compile(r"[^A-Z0-9 ]+")


def normaliser_lieu(brut: str | None) -> str | None:
    """« St-Malo » et « Saint-Malo » → « SAINT MALO » ; les chiffres sont gardés (« PARIS 15E »)."""
    if brut is None:
        return None
    separe = HORS_ALPHANUMERIQUE.sub("", SEPARATEURS.sub(" ", majuscules_ascii(brut)))
    return " ".join(ABREVIATIONS.get(mot, mot) for mot in separe.split()) or None


@dataclass(frozen=True)
class Commune:
    code: str
    nom: str
    departement: str
    type: str


@dataclass(frozen=True)
class Suggestion:
    """Proposition d'autocomplétion : texte affiché et valeur à placer dans le champ lieu."""

    libelle: str
    valeur: str


class Referentiel:
    """Communes indexées par code et par nom normalisé."""

    def __init__(self, communes: list[dict[str, Any]], departements: list[dict[str, Any]]):
        self._actuelles: dict[str, Commune] = {}
        self._rattachement: dict[str, str] = {}
        self._libelles: dict[str, str] = {}
        self._par_nom: dict[str, set[str]] = defaultdict(set)
        self.departements: dict[str, str] = {d["code"]: d["nom"] for d in departements}

        for brute in communes:
            if brute["type"] == "commune-actuelle":
                commune = Commune(brute["code"], brute["nom"], brute["departement"], brute["type"])
                self._actuelles[commune.code] = commune
                self._libelles[commune.code] = commune.nom
                for ancien in brute.get("anciensCodes", []):
                    self._rattachement.setdefault(ancien, commune.code)
        for brute in communes:
            code, type_ = brute["code"], brute["type"]
            if type_ == "commune-actuelle":
                cible = code
            elif type_ == "arrondissement-municipal":
                cible = brute["commune"]
            else:  # commune déléguée ou associée
                cible = brute.get("chefLieu", code)
            if code not in self._actuelles:
                self._rattachement[code] = cible
                self._libelles.setdefault(code, brute["nom"])
            nom = normaliser_lieu(brute["nom"])
            if nom:
                self._par_nom[nom].add(code if type_ == "arrondissement-municipal" else cible)
        self._suggestions = self._preparer_suggestions(communes)

    def _preparer_suggestions(
        self, communes: list[dict[str, Any]]
    ) -> list[tuple[str, int, Suggestion]]:
        """Entrées triées par nom normalisé : (clé, rang de priorité, suggestion)."""
        entrees: list[tuple[str, int, Suggestion]] = []
        for code, nom in self.departements.items():
            if cle := normaliser_lieu(nom):
                entrees.append((cle, 0, Suggestion(f"{nom} (département {code})", code)))
        for brute in communes:
            cle = normaliser_lieu(brute["nom"])
            commune = self.commune(brute["code"])
            if not cle or commune is None:
                continue
            valeur = f"{brute['nom']} ({commune.departement})"
            libelle = valeur
            if brute["type"] in ("commune-deleguee", "commune-associee"):
                libelle = f"{valeur}, aujourd'hui {commune.nom}"
            rang = 1 if brute["type"] == "commune-actuelle" else 2
            entrees.append((cle, rang, Suggestion(libelle, valeur)))
        return sorted(entrees, key=lambda e: (e[0], e[1], e[2].libelle))

    def suggerer(self, texte: str, limite: int = 10) -> list[Suggestion]:
        """Communes et départements dont le nom commence par ``texte`` (« quimp », « st malo »)."""
        cle = normaliser_lieu(texte)
        if not cle:
            return []
        trouvees: list[tuple[int, int, int, Suggestion]] = []
        debut = bisect_left(self._suggestions, (cle,))
        for position in range(debut, len(self._suggestions)):
            nom, rang, suggestion = self._suggestions[position]
            if not nom.startswith(cle):
                break
            # le nom exact d'abord, puis les départements, puis les noms les plus courts
            trouvees.append((nom != cle, rang, len(nom), suggestion))
        uniques: dict[str, Suggestion] = {}
        for *_, suggestion in sorted(trouvees, key=lambda e: e[:3]):
            uniques.setdefault(suggestion.valeur, suggestion)
        return list(uniques.values())[:limite]

    @classmethod
    def depuis_dossier(cls, dossier: Path) -> "Referentiel":
        def lire(nom: str) -> list[dict[str, Any]]:
            return json.loads((dossier / nom).read_text(encoding="utf-8"))  # type: ignore[no-any-return]

        return cls(lire("communes.json"), lire("departements.json"))

    def code_actuel(self, code: str | None) -> str | None:
        """Code de la commune actuelle qui correspond à ``code`` (lui-même s'il est actuel).

        Une commune déléguée ou associée, un ancien code ou un arrondissement municipal
        renvoient la commune actuelle : 01039 (Béon) → 01138, 75115 → 75056 (Paris).
        """
        if code is None:
            return None
        if code in self._actuelles:
            return code
        return self._rattachement.get(code)

    def commune(self, code: str | None) -> Commune | None:
        actuel = self.code_actuel(code)
        return self._actuelles.get(actuel) if actuel else None

    def nom(self, code: str | None) -> str | None:
        """Nom propre au code : « Béon » pour 01039, même si la commune actuelle est Culoz-Béon."""
        return self._libelles.get(code) if code else None

    def codes_du_nom(self, nom: str, departement: str | None = None) -> set[str]:
        """Codes des communes qui portent (ou ont porté) ce nom, dans un département si précisé."""
        cle = normaliser_lieu(nom)
        codes = self._par_nom.get(cle, set()) if cle else set()
        if departement is None:
            return set(codes)
        return {c for c in codes if (self.commune(c) or _vide).departement == departement}


_vide = Commune("", "", "", "")


def telecharger_referentiel(
    dossier: Path, ouvrir: Callable[[Request], Any] = lambda r: urlopen(r, timeout=60)
) -> Path:
    """Télécharge le référentiel et en extrait les fichiers utiles dans ``dossier``."""
    requete = Request(URL_REFERENTIEL, headers={"User-Agent": "doudoumil-search"})
    with ouvrir(requete) as reponse:
        archive = reponse.read()
    dossier.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for nom in FICHIERS:
            membre = tar.extractfile(f"package/data/{nom}")
            if membre is None:
                raise FileNotFoundError(f"{nom} absent de l'archive du référentiel")
            (dossier / nom).write_bytes(membre.read())
    (dossier / "VERSION").write_text(VERSION_REFERENTIEL + "\n", encoding="utf-8")
    return dossier
