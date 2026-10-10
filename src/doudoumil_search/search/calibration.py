"""Calibration du score en probabilité (règle R5 de PLAN.md).

Une régression isotone (algorithme PAV, *pool adjacent violators*) transforme le score de
classement en probabilité que le candidat soit la bonne personne. Elle est ajustée sur des
couples (score, bonne réponse ou non) tirés du jeu d'évaluation, une fois par source.

Le résultat est une fonction en escalier croissante, stockée comme une liste de paliers
``(score, probabilité)`` : la probabilité d'un score est celle du dernier palier dont le score
de départ est inférieur ou égal ; en dessous du premier palier, c'est la probabilité du premier.

Les paliers sont rangés dans ``gold/calibration.json``, à côté de la base de recherche et non
dedans : calibrer n'écrit jamais dans la base, qui peut donc rester ouverte (interface web) ;
et une reconstruction de la base ne touche pas à la calibration.
"""

import json
from bisect import bisect_right
from collections.abc import Sequence
from pathlib import Path
from typing import Final

NOM_FICHIER: Final = "calibration.json"
Paliers = dict[str, list[tuple[float, float]]]


def chemin_calibration(chemin_base: Path) -> Path:
    """Fichier de calibration associé à une base de recherche."""
    return chemin_base.with_name(NOM_FICHIER)


def lire_calibration(chemin: Path) -> Paliers:
    """Paliers par source ; vide si le fichier n'existe pas encore."""
    if not chemin.exists():
        return {}
    brute = json.loads(chemin.read_text(encoding="utf-8"))
    return {source: [(s, p) for s, p in paliers] for source, paliers in brute.items()}


def ecrire_calibration(chemin: Path, paliers: Paliers) -> None:
    """Remplace les paliers des sources données, garde les autres ; écriture d'un bloc."""
    toutes = {**lire_calibration(chemin), **paliers}
    temporaire = chemin.with_name(chemin.name + ".en-cours")
    temporaire.write_text(
        json.dumps({s: [list(p) for p in liste] for s, liste in sorted(toutes.items())}, indent=1),
        encoding="utf-8",
    )
    temporaire.replace(chemin)


def ajuster_isotone(
    scores: Sequence[float], etiquettes: Sequence[bool]
) -> list[tuple[float, float]]:
    """Paliers ``(score de départ, probabilité)`` de la régression isotone croissante."""
    if len(scores) != len(etiquettes):
        raise ValueError("autant de scores que d'étiquettes sont nécessaires")
    if not scores:
        return []
    couples = sorted(zip(scores, etiquettes, strict=True))
    # blocs : [score de départ, somme des étiquettes, effectif]
    blocs: list[list[float]] = []
    for score, etiquette in couples:
        if blocs and blocs[-1][0] == score:
            blocs[-1][1] += float(etiquette)
            blocs[-1][2] += 1
        else:
            blocs.append([score, float(etiquette), 1.0])
        # fusion tant que la moyenne du dernier bloc est inférieure à celle du précédent
        while len(blocs) > 1 and blocs[-1][1] / blocs[-1][2] < blocs[-2][1] / blocs[-2][2]:
            dernier = blocs.pop()
            blocs[-1][1] += dernier[1]
            blocs[-1][2] += dernier[2]
    paliers: list[tuple[float, float]] = []
    for debut, somme, effectif in blocs:
        probabilite = somme / effectif
        if not paliers or paliers[-1][1] != probabilite:  # paliers égaux voisins : un seul
            paliers.append((debut, probabilite))
    return paliers


def appliquer(paliers: Sequence[tuple[float, float]], score: float) -> float | None:
    """Probabilité d'un score selon les paliers ; ``None`` sans calibration."""
    if not paliers:
        return None
    position = bisect_right([debut for debut, _ in paliers], score) - 1
    return paliers[max(position, 0)][1]


def brier(probabilites: Sequence[float], etiquettes: Sequence[bool]) -> float:
    """Score de Brier : erreur quadratique moyenne des probabilités (0 = parfait)."""
    if not probabilites:
        raise ValueError("aucune probabilité à évaluer")
    return sum((p - float(y)) ** 2 for p, y in zip(probabilites, etiquettes, strict=True)) / len(
        probabilites
    )
