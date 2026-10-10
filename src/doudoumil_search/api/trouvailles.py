"""« Mes trouvailles » : favoris, notes et verdicts, dans une base personnelle séparée.

La base SQLite ``data/perso/trouvailles.sqlite`` n'est jamais reconstruite : les identifiants
des notices étant déterministes, une trouvaille reste valable après un ``doudoumil index``.
Chaque trouvaille garde la requête qui l'a fait apparaître ; un verdict (« c'est bien lui »
ou « ce n'est pas lui ») devient alors un exemple réel pour la calibration (règle R5).
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from doudoumil_search.search.requete import Requete

VERDICTS: Final = ("oui", "non")

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS trouvailles (
    mention_id TEXT PRIMARY KEY,
    acte_id TEXT NOT NULL,
    source TEXT,
    libelle TEXT NOT NULL,
    favori INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    verdict TEXT CHECK (verdict IN ('oui', 'non')),
    requete TEXT,
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class Trouvaille:
    mention_id: str
    acte_id: str
    source: str | None
    libelle: str
    favori: bool
    note: str
    verdict: str | None
    requete: Requete | None
    cree_le: str
    modifie_le: str


class Carnet:
    """Accès à la base des trouvailles ; une connexion par opération, sûre entre fils."""

    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as connexion:
            connexion.execute(_SCHEMA)

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        connexion = sqlite3.connect(self.chemin)
        connexion.row_factory = sqlite3.Row
        try:
            with connexion:
                yield connexion
        finally:
            connexion.close()

    def enregistrer(
        self,
        mention_id: str,
        acte_id: str,
        libelle: str,
        source: str | None = None,
        requete: Requete | None = None,
        favori: bool | None = None,
        note: str | None = None,
        verdict: str | None = None,
        effacer_verdict: bool = False,
    ) -> Trouvaille:
        """Crée ou met à jour une trouvaille ; seuls les champs donnés changent."""
        if verdict is not None and verdict not in VERDICTS:
            raise ValueError(f"verdict inconnu : « {verdict} »")
        maintenant = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connexion() as connexion:
            connexion.execute(
                """
                INSERT INTO trouvailles (mention_id, acte_id, source, libelle, requete, cree_le,
                                         modifie_le)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (mention_id) DO NOTHING
                """,
                (
                    mention_id,
                    acte_id,
                    source,
                    libelle,
                    json.dumps(requete.vers_dict(), ensure_ascii=False) if requete else None,
                    maintenant,
                    maintenant,
                ),
            )
            changements: dict[str, Any] = {"modifie_le": maintenant}
            if favori is not None:
                changements["favori"] = int(favori)
            if note is not None:
                changements["note"] = note
            if verdict is not None or effacer_verdict:
                changements["verdict"] = verdict
                if requete is not None:  # le verdict porte sur la requête qui l'a fait voir
                    changements["requete"] = json.dumps(requete.vers_dict(), ensure_ascii=False)
            affectations = ", ".join(f"{colonne} = ?" for colonne in changements)
            connexion.execute(
                f"UPDATE trouvailles SET {affectations} WHERE mention_id = ?",
                (*changements.values(), mention_id),
            )
        trouvaille = self.lire(mention_id)
        assert trouvaille is not None
        return trouvaille

    def supprimer(self, mention_id: str) -> None:
        with self._connexion() as connexion:
            connexion.execute("DELETE FROM trouvailles WHERE mention_id = ?", (mention_id,))

    def lire(self, mention_id: str) -> Trouvaille | None:
        with self._connexion() as connexion:
            ligne = connexion.execute(
                "SELECT * FROM trouvailles WHERE mention_id = ?", (mention_id,)
            ).fetchone()
        return _trouvaille(ligne) if ligne else None

    def toutes(self) -> list[Trouvaille]:
        with self._connexion() as connexion:
            lignes = connexion.execute(
                "SELECT * FROM trouvailles ORDER BY favori DESC, modifie_le DESC"
            ).fetchall()
        return [_trouvaille(ligne) for ligne in lignes]

    def parmi(self, mention_ids: list[str]) -> dict[str, Trouvaille]:
        """Trouvailles connues parmi des résultats affichés (badges ★, ✓, ✗)."""
        if not mention_ids:
            return {}
        marques = ", ".join("?" * len(mention_ids))
        with self._connexion() as connexion:
            lignes = connexion.execute(
                f"SELECT * FROM trouvailles WHERE mention_id IN ({marques})", mention_ids
            ).fetchall()
        return {ligne["mention_id"]: _trouvaille(ligne) for ligne in lignes}

    def verdicts(self) -> list[Trouvaille]:
        """Trouvailles jugées dont on connaît la requête : les exemples réels de calibration."""
        return [t for t in self.toutes() if t.verdict and t.requete is not None]


def _trouvaille(ligne: sqlite3.Row) -> Trouvaille:
    requete = Requete.depuis_dict(json.loads(ligne["requete"])) if ligne["requete"] else None
    return Trouvaille(
        mention_id=ligne["mention_id"],
        acte_id=ligne["acte_id"],
        source=ligne["source"],
        libelle=ligne["libelle"],
        favori=bool(ligne["favori"]),
        note=ligne["note"],
        verdict=ligne["verdict"],
        requete=requete,
        cree_le=ligne["cree_le"],
        modifie_le=ligne["modifie_le"],
    )
