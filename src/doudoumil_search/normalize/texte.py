"""Opérations de base sur le texte, communes aux noms, prénoms et lieux."""

import re
import unicodedata
from typing import Final

# Ligatures et lettres que la décomposition Unicode ne ramène pas à l'alphabet latin simple.
LIGATURES: Final = str.maketrans({"Œ": "OE", "œ": "oe", "Æ": "AE", "æ": "ae", "ß": "ss"})

# Apostrophes, tirets et ponctuation qui séparent les mots d'un nom.
SEPARATEURS: Final = re.compile(r"[\s'’‘`´ʼ\-‐‑–—_.,;:/()]+")
HORS_ALPHABET: Final = re.compile(r"[^A-Z ]+")
ESPACES: Final = re.compile(r" {2,}")


def majuscules_ascii(texte: str) -> str:
    """Majuscules sans accents ni ligatures : « Lœtitia Bézier » → « LOETITIA BEZIER »."""
    decompose = unicodedata.normalize("NFKD", texte.translate(LIGATURES))
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return sans_accents.upper()


def mots(texte: str) -> list[str]:
    """Mots en majuscules ASCII, séparés par les espaces, apostrophes, tirets et points.

    Tout caractère hors de l'alphabet est supprimé : « D'Hervé-Le Goff » → D, HERVE, LE, GOFF.
    """
    separe = SEPARATEURS.sub(" ", majuscules_ascii(texte))
    return HORS_ALPHABET.sub("", separe).split()
