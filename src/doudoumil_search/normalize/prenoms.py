"""Normalisation des prénoms (règle R4 de PLAN.md).

Les prénoms normalisés forment une liste ordonnée, séparée par des espaces. Les prénoms
composés sont découpés (``Jean-Marie`` et ``Jean Marie`` donnent ``JEAN MARIE``) et chaque
prénom passe par une table d'équivalences versionnée (``prenoms_equivalents.csv``) :
abréviations des actes anciens (``Jn`` → ``JEAN``), formes latines (``JOANNES`` → ``JEAN``)
et graphies anciennes (``JEHAN`` → ``JEAN``).
"""

import csv
from functools import cache
from importlib.resources import files

from doudoumil_search.normalize.texte import mots


@cache
def equivalences() -> dict[str, str]:
    """Table forme → prénom de référence, lue une fois depuis le fichier du paquet."""
    contenu = files(__package__).joinpath("prenoms_equivalents.csv").read_text(encoding="utf-8")
    return {ligne["forme"]: ligne["prenom"] for ligne in csv.DictReader(contenu.splitlines())}


def liste_prenoms(brut: str | None) -> list[str]:
    """Prénoms normalisés, dans l'ordre : « Jn-Bte Marie » → JEAN, BAPTISTE, MARIE."""
    if brut is None:
        return []
    table = equivalences()
    return [table.get(prenom, prenom) for prenom in mots(brut)]


def normaliser_prenoms(brut: str | None) -> str | None:
    return " ".join(liste_prenoms(brut)) or None
