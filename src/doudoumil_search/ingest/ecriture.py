"""Écriture d'une partition bronze : actes, mentions et lignes rejetées d'un fichier source.

Une partition correspond à un fichier source. Elle est d'abord écrite dans un dossier
temporaire voisin, puis remplace l'ancienne d'un seul coup : une ingestion interrompue ne
laisse jamais une partition à moitié écrite, et réingérer un fichier remplace sa partition au
lieu d'en ajouter une seconde.
"""

import csv
import shutil
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO

from doudoumil_search.pivot import Acte, Mention
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS, vers_dataframe

NOM_REJETS = "rejets.csv"


class EcrivainPartition:
    """Accumule actes et mentions et les écrit en fichiers Parquet par lots.

    S'utilise comme gestionnaire de contexte : la partition n'est publiée qu'en sortie sans
    erreur ; en cas d'exception, le dossier temporaire est supprimé et l'ancienne partition
    reste intacte.
    """

    def __init__(self, dossier: Path, taille_lot: int = 200_000) -> None:
        if taille_lot < 1:
            raise ValueError("la taille de lot doit être positive")
        self.dossier = dossier
        self.taille_lot = taille_lot
        self._temporaire = dossier.with_name(dossier.name + ".en-cours")
        self._actes: list[Acte] = []
        self._mentions: list[Mention] = []
        self._numero_lot = 0
        self._fichier_rejets: TextIO | None = None
        self._rejets: Any = None  # écrivain CSV, dont le type n'est pas public

    def __enter__(self) -> Self:
        if self._temporaire.exists():
            shutil.rmtree(self._temporaire)
        self._temporaire.mkdir(parents=True)
        self._fichier_rejets = (self._temporaire / NOM_REJETS).open(
            "w", encoding="utf-8", newline=""
        )
        self._rejets = csv.writer(self._fichier_rejets)
        self._rejets.writerow(["numero_ligne", "motif", "ligne"])
        return self

    def ajouter(self, acte: Acte, mentions: list[Mention]) -> None:
        self._actes.append(acte)
        self._mentions.extend(mentions)
        if len(self._actes) >= self.taille_lot:
            self._vider()

    def rejeter(self, numero_ligne: int, motif: str, ligne: str) -> None:
        assert self._rejets is not None, "à utiliser dans un bloc with"
        self._rejets.writerow([numero_ligne, motif, ligne])

    def _vider(self) -> None:
        if not self._actes:
            return
        suffixe = f"{self._numero_lot:05d}.parquet"
        vers_dataframe(self._actes, SCHEMA_ACTES).write_parquet(
            self._temporaire / f"actes-{suffixe}"
        )
        vers_dataframe(self._mentions, SCHEMA_MENTIONS).write_parquet(
            self._temporaire / f"mentions-{suffixe}"
        )
        self._actes.clear()
        self._mentions.clear()
        self._numero_lot += 1

    def __exit__(
        self,
        type_exc: type[BaseException] | None,
        exc: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._fichier_rejets is not None:
            self._fichier_rejets.close()
        if type_exc is not None:
            shutil.rmtree(self._temporaire, ignore_errors=True)
            return
        self._vider()
        if self.dossier.exists():
            shutil.rmtree(self.dossier)
        self._temporaire.rename(self.dossier)
