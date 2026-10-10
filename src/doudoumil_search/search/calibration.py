"""Calibration du score en probabilité (règle R5 de PLAN.md).

Une régression isotone (algorithme PAV, *pool adjacent violators*) transforme le score de
classement en probabilité que le candidat soit la bonne personne. Elle est ajustée sur des
couples (score, bonne réponse ou non) tirés du jeu d'évaluation, une fois par source.

Le résultat est une fonction en escalier croissante, stockée comme une liste de paliers
``(score, probabilité)`` : la probabilité d'un score est celle du dernier palier dont le score
de départ est inférieur ou égal ; en dessous du premier palier, c'est la probabilité du premier.
"""

from bisect import bisect_right
from collections.abc import Sequence


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
