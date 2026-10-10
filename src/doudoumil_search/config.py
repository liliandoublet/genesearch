"""Emplacement des données locales.

Toutes les couches vivent sous un même dossier racine, ``data/`` par défaut, que l'on peut
déplacer avec la variable d'environnement ``DOUDOUMIL_DATA`` (utile pour un disque externe).
"""

import os
from pathlib import Path

VARIABLE_DONNEES = "DOUDOUMIL_DATA"


def dossier_donnees() -> Path:
    """Dossier racine des données (``data/`` dans le dossier courant par défaut)."""
    return Path(os.environ.get(VARIABLE_DONNEES, "data"))


def dossier_bronze(racine: Path | None = None) -> Path:
    return (racine or dossier_donnees()) / "bronze"


def dossier_silver(racine: Path | None = None) -> Path:
    return (racine or dossier_donnees()) / "silver"


def dossier_gold(racine: Path | None = None) -> Path:
    return (racine or dossier_donnees()) / "gold"


def dossier_referentiels(racine: Path | None = None) -> Path:
    return (racine or dossier_donnees()) / "ref"


def dossier_perso(racine: Path | None = None) -> Path:
    """Données personnelles (trouvailles) : jamais reconstruites, à sauvegarder."""
    return (racine or dossier_donnees()) / "perso"
