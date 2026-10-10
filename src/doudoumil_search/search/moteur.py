"""Moteur de recherche sur la base gold (règles R1 à R5 de PLAN.md).

Déroulement d'une recherche :

1. **Présélection** par trois canaux indépendants (R1), chacun plafonné :
   A, même clé phonétique du nom ; B, noms proches dans la liste des noms distincts ;
   C, sans le nom, par prénom, naissance et département. Un canal « conjoint » cherche en
   plus les femmes inscrites sous le nom de leur mari quand celui-ci est donné (R2).
2. **Score** de chaque candidat (``score.py``), puis probabilité si la source est calibrée.
3. **Fiches** : les champs d'affichage (valeurs brutes, provenance) ne sont lus que pour les
   résultats retenus.

Les filtres communs à tous les canaux : sexe (une notice sans sexe n'est pas exclue), années
de l'acte, sources, et naissance compatible à la tolérance de la source près (une notice sans
naissance n'est pas exclue). Le lieu ne filtre que le canal C ; ailleurs, il pèse sur le score.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import duckdb

from doudoumil_search.normalize.phonetique import cle_phonetique
from doudoumil_search.pivot import Sexe
from doudoumil_search.search.calibration import appliquer
from doudoumil_search.search.requete import Requete
from doudoumil_search.search.score import (
    TOLERANCE_NAISSANCE,
    TOLERANCE_PAR_DEFAUT,
    Composantes,
    libelle,
    score_lieu,
    score_naissance,
    score_nom,
    score_prenoms,
    tolerance,
)

PLAFOND_PAR_CANAL: Final = 2000
ECART_LONGUEUR_CANAL_B: Final = 3
DISTANCE_CANAL_B: Final = 2
DISTANCE_CANAL_B_NOM_COURT: Final = 1  # deux erreurs sur un nom de 4 lettres : presque tout passe
LONGUEUR_NOM_COURT: Final = 4
RESSEMBLANCE_CANAL_B: Final = 0.85

COLONNES_PERSONNES: Final = (
    "mention_id",
    "acte_id",
    "source",
    "type",
    "annee",
    "date_acte",
    "role",
    "nom_norm",
    "prenoms_norm",
    "nature_nom",
    "sexe",
    "annee_naissance_min",
    "annee_naissance_max",
    "commune_code_insee",
    "commune_actuelle",
    "departement",
    "lieu_naissance_code_insee",
    "naissance_actuelle",
    "naissance_departement",
    "confiance_source",
)
SELECTION: Final = ", ".join(f"p.{c}" for c in COLONNES_PERSONNES)

# Tolérance de naissance par source, en SQL ; les valeurs viennent du code, pas de l'utilisateur.
_TOLERANCE_SQL: Final = (
    "CASE p.source "
    + " ".join(f"WHEN '{source}' THEN {annees}" for source, annees in TOLERANCE_NAISSANCE.items())
    + f" ELSE {TOLERANCE_PAR_DEFAUT} END"
)


@dataclass(frozen=True)
class Candidat:
    """Ligne de la table ``personnes`` et canaux qui l'ont trouvée."""

    donnees: dict[str, Any]
    canaux: frozenset[str]


@dataclass(frozen=True)
class Resultat:
    mention_id: str
    acte_id: str
    source: str
    type: str
    role: str
    annee: int
    canaux: tuple[str, ...]
    composantes: Composantes
    score: float
    probabilite: float | None
    libelle: str
    nom_epouse_probable: bool
    fiche: dict[str, Any] = field(default_factory=dict)

    @property
    def cle_de_tri(self) -> float:
        return self.probabilite if self.probabilite is not None else self.score


class Moteur:
    """Recherche dans une base gold, ouverte en lecture seule."""

    def __init__(self, chemin: Path, plafond: int = PLAFOND_PAR_CANAL) -> None:
        if not chemin.exists():
            raise FileNotFoundError(f"{chemin} absente : lancez « doudoumil index »")
        self.base = duckdb.connect(str(chemin), read_only=True)
        self.plafond = plafond
        self.calibration: dict[str, list[tuple[float, float]]] = {}
        for source, score, probabilite in self.base.execute(
            "SELECT source, score, probabilite FROM calibration ORDER BY source, score"
        ).fetchall():
            self.calibration.setdefault(source, []).append((score, probabilite))

    def fermer(self) -> None:
        self.base.close()

    def __enter__(self) -> "Moteur":
        return self

    def __exit__(self, *args: object) -> None:
        self.fermer()

    # --- présélection -------------------------------------------------------------------

    def _filtres(self, requete: Requete) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        parametres: list[Any] = []
        if requete.sexe is not None:
            conditions.append("(p.sexe = ? OR p.sexe IS NULL)")
            parametres.append(requete.sexe.value)
        if requete.annees is not None:
            conditions.append("p.annee BETWEEN ? AND ?")
            parametres.extend(requete.annees)
        if requete.sources:
            conditions.append(f"p.source IN ({', '.join('?' * len(requete.sources))})")
            parametres.extend(requete.sources)
        if requete.naissance is not None:
            conditions.append(
                "(p.annee_naissance_min IS NULL OR "
                f"(p.annee_naissance_min <= ? + {_TOLERANCE_SQL} "
                f"AND p.annee_naissance_max >= ? - {_TOLERANCE_SQL}))"
            )
            parametres.extend([requete.naissance[1], requete.naissance[0]])
        return conditions, parametres

    def _executer(self, sql: str, parametres: list[Any]) -> list[dict[str, Any]]:
        curseur = self.base.execute(sql, parametres)
        colonnes = [d[0] for d in curseur.description]
        return [dict(zip(colonnes, ligne, strict=True)) for ligne in curseur.fetchall()]

    def _canal_phonetique(
        self, requete: Requete, nom: str, marital_seulement: bool = False
    ) -> list[dict[str, Any]]:
        cle = cle_phonetique(nom)
        if cle is None:
            return []
        conditions, parametres = self._filtres(requete)
        conditions.insert(0, "p.nom_phonetique = ?")
        parametres.insert(0, cle)
        if marital_seulement:
            conditions.append("p.nature_nom = 'marital'")
        sql = (
            f"SELECT {SELECTION} FROM personnes p WHERE {' AND '.join(conditions)} "
            "ORDER BY jaro_winkler_similarity(p.nom_norm, ?) DESC, p.mention_id LIMIT ?"
        )
        return self._executer(sql, [*parametres, nom, self.plafond])

    def _canal_noms_proches(self, requete: Requete, nom: str) -> list[dict[str, Any]]:
        conditions, parametres = self._filtres(requete)
        filtres = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        longueur = len(nom)
        distance = (
            DISTANCE_CANAL_B_NOM_COURT if longueur <= LONGUEUR_NOM_COURT else DISTANCE_CANAL_B
        )
        sql = f"""
            WITH proches AS (
                SELECT nom_norm FROM noms
                WHERE longueur BETWEEN ? AND ?
                  AND (levenshtein(nom_norm, ?) <= {distance}
                       OR jaro_winkler_similarity(nom_norm, ?) >= {RESSEMBLANCE_CANAL_B})
            )
            SELECT {SELECTION} FROM personnes p JOIN proches USING (nom_norm)
            {filtres}
            ORDER BY jaro_winkler_similarity(p.nom_norm, ?) DESC, p.mention_id LIMIT ?
        """
        return self._executer(
            sql,
            [
                longueur - ECART_LONGUEUR_CANAL_B,
                longueur + ECART_LONGUEUR_CANAL_B,
                nom,
                nom,
                *parametres,
                nom,
                self.plafond,
            ],
        )

    def _canal_sans_nom(self, requete: Requete) -> list[dict[str, Any]]:
        if not (requete.prenoms and requete.naissance and requete.lieu.departements):
            return []
        cles = sorted({c for p in requete.prenoms if (c := cle_phonetique(p))})
        if not cles:
            return []
        conditions, parametres = self._filtres(requete)
        departements = sorted(requete.lieu.departements)
        marques = ", ".join("?" * len(departements))
        conditions += [
            f"p.mention_id IN (SELECT mention_id FROM prenoms WHERE cle IN "
            f"({', '.join('?' * len(cles))}))",
            "p.annee_naissance_min IS NOT NULL",
            f"(p.departement IN ({marques}) OR p.naissance_departement IN ({marques}))",
        ]
        parametres += [*cles, *departements, *departements]
        milieu = sum(requete.naissance) / 2
        sql = (
            f"SELECT {SELECTION} FROM personnes p WHERE {' AND '.join(conditions)} "
            "ORDER BY abs((p.annee_naissance_min + p.annee_naissance_max) / 2 - ?), p.mention_id "
            "LIMIT ?"
        )
        return self._executer(sql, [*parametres, milieu, self.plafond])

    def candidats(self, requete: Requete) -> list[Candidat]:
        """Union des canaux de présélection, chaque candidat avec ses canaux."""
        trouves: dict[str, dict[str, Any]] = {}
        canaux: dict[str, set[str]] = {}

        def ajouter(nom_canal: str, lignes: list[dict[str, Any]]) -> None:
            for ligne in lignes:
                trouves.setdefault(ligne["mention_id"], ligne)
                canaux.setdefault(ligne["mention_id"], set()).add(nom_canal)

        if requete.nom:
            ajouter("phonétique", self._canal_phonetique(requete, requete.nom))
            ajouter("noms proches", self._canal_noms_proches(requete, requete.nom))
        if requete.conjoint:
            ajouter(
                "conjoint",
                self._canal_phonetique(requete, requete.conjoint, marital_seulement=True),
            )
        ajouter("sans le nom", self._canal_sans_nom(requete))
        return [Candidat(trouves[m], frozenset(canaux[m])) for m in trouves]

    # --- score et résultats -------------------------------------------------------------

    def noter(self, requete: Requete, candidat: Candidat) -> Resultat:
        d = candidat.donnees
        # R2 : nom d'épouse, sauf si la notice ou la requête visent un homme
        nom_marital = (
            d["nature_nom"] == "marital" and d["sexe"] != "M" and requete.sexe is not Sexe.M
        )
        naissance = (
            (d["annee_naissance_min"], d["annee_naissance_max"])
            if d["annee_naissance_min"] is not None
            else None
        )
        composantes = Composantes(
            nom=score_nom(requete.nom, d["nom_norm"], nom_marital, requete.conjoint),
            prenoms=score_prenoms(requete.prenoms, (d["prenoms_norm"] or "").split()),
            naissance=score_naissance(requete.naissance, naissance, tolerance(d["source"])),
            lieu=score_lieu(
                requete.lieu.communes,
                requete.lieu.departements,
                (
                    d["commune_code_insee"],
                    d["commune_actuelle"],
                    d["lieu_naissance_code_insee"],
                    d["naissance_actuelle"],
                ),
                (d["departement"], d["naissance_departement"]),
            ),
        )
        score = composantes.score(d["confiance_source"])
        probabilite = appliquer(self.calibration.get(d["source"], []), score)
        return Resultat(
            mention_id=d["mention_id"],
            acte_id=d["acte_id"],
            source=d["source"],
            type=d["type"],
            role=d["role"],
            annee=d["annee"],
            canaux=tuple(sorted(candidat.canaux)),
            composantes=composantes,
            score=score,
            probabilite=probabilite,
            libelle=libelle(probabilite),
            nom_epouse_probable=nom_marital,
        )

    def classer(self, requete: Requete) -> list[Resultat]:
        """Tous les candidats notés, du plus probable au moins probable, sans les fiches."""
        resultats = [self.noter(requete, c) for c in self.candidats(requete)]
        return sorted(resultats, key=lambda r: (-r.cle_de_tri, r.mention_id))

    def rechercher(self, requete: Requete) -> list[Resultat]:
        """Les meilleurs résultats, avec leurs fiches."""
        if not requete.est_exploitable():
            raise ValueError("il faut un nom, ou un prénom avec une naissance et un lieu")
        meilleurs = self.classer(requete)[: requete.limite]
        fiches = self.fiches([r.mention_id for r in meilleurs])
        return [
            Resultat(**{**r.__dict__, "fiche": fiches.get(r.mention_id, {})}) for r in meilleurs
        ]

    def fiches(self, mention_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Champs d'affichage des mentions demandées : valeurs brutes et provenance."""
        if not mention_ids:
            return {}
        lignes = self._executer(
            """
            SELECT m.mention_id, m.nom_brut, m.prenoms_bruts, m.sexe, m.date_naissance,
                   m.date_naissance_brute, m.annee_naissance_min, m.annee_naissance_max,
                   m.lieu_naissance_brut, m.lieu_naissance_code_insee, m.age, m.profession,
                   a.type, a.annee, a.date_acte, a.commune_code_insee, a.commune_label,
                   a.departement, a.depot, a.cote, a.vue, a.url_image
            FROM mentions m JOIN actes a USING (acte_id)
            WHERE m.mention_id IN (SELECT unnest(?::VARCHAR[]))
            """,
            [mention_ids],
        )
        return {ligne["mention_id"]: ligne for ligne in lignes}
