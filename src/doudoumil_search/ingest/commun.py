"""Éléments communs aux connecteurs : rejets, bilan d'ingestion, codes géographiques."""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pydantic import ValidationError

# Même motif que le type CodeInsee du pivot.
MOTIF_CODE_LIEU: Final = re.compile(r"\d[\dAB]\d{3}")
# Même motif que le type Departement du pivot.
MOTIF_DEPARTEMENT: Final = re.compile(r"\d{2}|2[AB]|97[1-8]|98[4-9]")


class LigneRejetee(ValueError):
    """Ligne inexploitable ; le message est le motif enregistré dans ``rejets.csv``."""


@dataclass
class RapportIngestion:
    """Bilan de l'ingestion d'un fichier."""

    fichier: str
    dossier: Path
    lignes_lues: int = 0
    lignes_ingerees: int = 0
    lignes_rejetees: int = 0
    anomalies: Counter[str] = field(default_factory=Counter)


def departement_de(code_lieu: str) -> str:
    """Département d'un code de lieu : 3 caractères outre-mer, ``99`` pour l'étranger."""
    if code_lieu.startswith(("97", "98")):
        return code_lieu[:3]
    return code_lieu[:2]


def motif_validation(erreur: ValidationError) -> str:
    """Motif court d'un refus de validation : le premier champ en cause."""
    premiere = erreur.errors()[0]
    champ = ".".join(str(partie) for partie in premiere["loc"]) or "modèle"
    return f"validation : {champ} ({premiere['msg']})"
