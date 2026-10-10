"""Normalisation des noms de famille.

Le nom normalisé sert à comparer des écritures différentes d'un même nom : majuscules, sans
accents, apostrophes et tirets remplacés par des espaces. Les particules (``LE``, ``DE``,
``D``, ``DU``, ``LA``…) sont conservées, car elles distinguent des noms différents
(``LE GOFF`` et ``GOFF``) ; leur collage éventuel (``LEGOFF``) est absorbé par la clé
phonétique, calculée sur les lettres seules.
"""

from doudoumil_search.normalize.texte import mots


def normaliser_nom(brut: str | None) -> str | None:
    """« Le Goff » et « LE-GOFF » → « LE GOFF » ; « d'Hervé » → « D HERVE »."""
    if brut is None:
        return None
    return " ".join(mots(brut)) or None


def compacter(nom: str) -> str:
    """Lettres seules, sans espaces : « LE GOFF » → « LEGOFF »."""
    return nom.replace(" ", "")
