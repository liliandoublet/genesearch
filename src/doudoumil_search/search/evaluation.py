"""Évaluation de la recherche et ajustement de la calibration (règle R5 de PLAN.md).

Un *cas* est une requête dont on connaît la bonne réponse (la mention cherchée). Deux façons
de fabriquer des cas, à partir de notices réelles :

``requete``
    Les données sont intactes ; la requête est imprécise, comme celle d'un utilisateur : nom
    parfois mal orthographié, un seul prénom, année de naissance approximative, lieu de
    naissance ou de décès, ou pas de lieu. Convient aux sources fiables (INSEE).
``donnees``
    La requête est exacte ; ce sont les données qui sont bruitées, comme une transcription
    automatique (recensements) : un échantillon de la couche bronze est recopié avec des
    erreurs de lecture, puis repasse par silver et gold. Les identifiants ne changent pas,
    ce qui permet de retrouver la bonne réponse.

Mesures : rappel de la présélection (la bonne réponse figure parmi les candidats), rappel au
rang 1 et dans les 10 premiers, rang réciproque moyen, et score de Brier de la calibration
(ajustée sur la moitié des cas, mesurée sur l'autre moitié).
"""

import random
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import duckdb
import polars as pl

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.silver import construire_silver
from doudoumil_search.pivot import Sexe
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS
from doudoumil_search.search.calibration import ajuster_isotone, appliquer, brier
from doudoumil_search.search.gold import construire_gold
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import Lieu, Requete

# Lettres manuscrites que la lecture automatique confond couramment ; F et S pour le s long.
CONFUSIONS: Final = {
    "C": "GE",
    "G": "CQ",
    "U": "NV",
    "N": "UMR",
    "M": "NW",
    "E": "CI",
    "F": "S",
    "S": "F",
    "I": "LJ",
    "L": "IT",
    "A": "O",
    "O": "AC",
    "R": "N",
    "T": "FL",
    "B": "L",
    "V": "U",
}
RANG_CALIBRATION: Final = 20  # seuls les premiers résultats d'une requête servent à calibrer


def pourcent(valeur: float, decimales: int = 1) -> str:
    """Pourcentage à la française : 0,957 → « 95,7 % »."""
    return f"{valeur * 100:.{decimales}f} %".replace(".", ",")


def bruiter_texte(texte: str, rng: random.Random) -> str:
    """Introduit une erreur de lecture : lettres confondues, perdue, doublée ou inversée."""
    positions = [i for i, c in enumerate(texte) if c.isalpha()]
    if not positions:
        return texte
    i = rng.choice(positions)
    lettre = texte[i].upper()
    tirage = rng.random()
    if tirage < 0.5 and lettre in CONFUSIONS:
        remplacement = rng.choice(CONFUSIONS[lettre])
        return texte[:i] + remplacement + texte[i + 1 :]
    if tirage < 0.7 and len(positions) > 2:
        return texte[:i] + texte[i + 1 :]
    if tirage < 0.85:
        return texte[: i + 1] + texte[i] + texte[i + 1 :]
    if i + 1 < len(texte) and texte[i + 1].isalpha():
        return texte[:i] + texte[i + 1] + texte[i] + texte[i + 2 :]
    return texte[:i] + texte[i + 1 :] if len(positions) > 2 else texte


@dataclass(frozen=True)
class Cas:
    requete: Requete
    cible: str  # mention_id attendu


@dataclass
class Mesures:
    cas: int = 0
    preselection: int = 0
    rang_1: int = 0
    rang_10: int = 0
    rang_reciproque: float = 0.0
    brier: float | None = None
    paliers: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    @property
    def rappel_preselection(self) -> float:
        return self.preselection / self.cas if self.cas else 0.0

    @property
    def rappel_1(self) -> float:
        return self.rang_1 / self.cas if self.cas else 0.0

    @property
    def rappel_10(self) -> float:
        return self.rang_10 / self.cas if self.cas else 0.0

    @property
    def rang_reciproque_moyen(self) -> float:
        return self.rang_reciproque / self.cas if self.cas else 0.0

    def resume(self) -> str:
        brier_texte = f"{self.brier:.3f}".replace(".", ",") if self.brier is not None else "—"
        rang_moyen = f"{self.rang_reciproque_moyen:.3f}".replace(".", ",")
        return (
            f"{self.cas} cas : présélection {pourcent(self.rappel_preselection)}, "
            f"rang 1 {pourcent(self.rappel_1)}, 10 premiers {pourcent(self.rappel_10)}, "
            f"rang réciproque moyen {rang_moyen}, Brier {brier_texte}"
        )


# --- tirage des notices ---------------------------------------------------------------------


def tirer_notices(chemin_gold: Path, nombre: int, graine: int) -> list[dict[str, Any]]:
    """Notices tirées au hasard (reproductible), parmi celles qui ont un nom et un prénom."""
    with duckdb.connect(str(chemin_gold), read_only=True) as base:
        base.execute("SET threads TO 1")  # tirage reproductible d'une exécution à l'autre
        curseur = base.execute(
            f"""
            SELECT * FROM (
                SELECT mention_id, source, nom_norm, prenoms_norm, sexe, annee,
                       annee_naissance_min, annee_naissance_max,
                       commune_actuelle, departement, naissance_actuelle, naissance_departement
                FROM personnes
                WHERE nom_norm IS NOT NULL AND prenoms_norm IS NOT NULL
                ORDER BY mention_id
            ) USING SAMPLE reservoir({int(nombre)} ROWS) REPEATABLE ({int(graine)})
            """
        )
        colonnes = [d[0] for d in curseur.description]
        lignes = [dict(zip(colonnes, ligne, strict=True)) for ligne in curseur.fetchall()]
    return sorted(lignes, key=lambda ligne: ligne["mention_id"])


def _naissance(notice: dict[str, Any]) -> tuple[int, int] | None:
    if notice["annee_naissance_min"] is None:
        return None
    return notice["annee_naissance_min"], notice["annee_naissance_max"]


def cas_imprecis(notice: dict[str, Any], taux: float, rng: random.Random) -> Cas:
    """Requête d'utilisateur imprécise sur une notice exacte (mode ``requete``)."""
    nom = notice["nom_norm"]
    if rng.random() < taux:
        nom = bruiter_texte(nom, rng)
    prenoms = notice["prenoms_norm"].split()
    prenoms = prenoms[:1] if rng.random() < 0.7 else prenoms
    if rng.random() < taux / 2:
        prenoms = [bruiter_texte(prenoms[0], rng), *prenoms[1:]]
    naissance = _naissance(notice)
    if naissance is not None:
        decalage = rng.choice((-1, 0, 0, 0, 1))
        marge = 2 if rng.random() < 0.3 else 0
        naissance = (naissance[0] + decalage - marge, naissance[1] + decalage + marge)
    lieu = Lieu()
    tirage = rng.random()
    if tirage < 0.4 and notice["naissance_actuelle"]:
        lieu = Lieu(
            frozenset({notice["naissance_actuelle"]}),
            frozenset({notice["naissance_departement"]}),
        )
    elif tirage < 0.7 and notice["departement"]:
        lieu = Lieu(departements=frozenset({notice["departement"]}))
    sexe = Sexe(notice["sexe"]) if notice["sexe"] and rng.random() < 0.5 else None
    requete = Requete(
        nom=nom, prenoms=tuple(prenoms), sexe=sexe, naissance=naissance, lieu=lieu, limite=10
    )
    return Cas(requete=requete, cible=notice["mention_id"])


def cas_exact(notice: dict[str, Any]) -> Cas:
    """Requête exacte : nom, premier prénom, naissance et lieu de la notice (mode ``donnees``)."""
    lieu = Lieu()
    if notice["naissance_actuelle"]:
        lieu = Lieu(
            frozenset({notice["naissance_actuelle"]}),
            frozenset({notice["naissance_departement"]}),
        )
    elif notice["departement"]:
        lieu = Lieu(departements=frozenset({notice["departement"]}))
    requete = Requete(
        nom=notice["nom_norm"],
        prenoms=tuple(notice["prenoms_norm"].split()[:1]),
        naissance=_naissance(notice),
        lieu=lieu,
        limite=10,
    )
    return Cas(requete=requete, cible=notice["mention_id"])


# --- évaluation -----------------------------------------------------------------------------


def evaluer(moteur: Moteur, cas: Sequence[Cas]) -> Mesures:
    """Mesure la recherche sur des cas ; ajuste et contrôle la calibration au passage."""
    mesures = Mesures(cas=len(cas))
    couples: list[list[tuple[str, float, bool]]] = []
    for un_cas in cas:
        resultats = moteur.classer(un_cas.requete)
        rangs = [i for i, r in enumerate(resultats, start=1) if r.mention_id == un_cas.cible]
        if rangs:
            mesures.preselection += 1
            mesures.rang_1 += rangs[0] == 1
            mesures.rang_10 += rangs[0] <= 10
            mesures.rang_reciproque += 1 / rangs[0]
        couples.append(
            [
                (r.source, r.score, r.mention_id == un_cas.cible)
                for r in resultats[:RANG_CALIBRATION]
            ]
        )
    # calibration ajustée sur les cas pairs, contrôlée sur les cas impairs
    apprentissage = _paliers_par_source([c for i, c in enumerate(couples) if i % 2 == 0])
    controle = [couple for i, c in enumerate(couples) if i % 2 == 1 for couple in c]
    probabilites, etiquettes = [], []
    for source, score, etiquette in controle:
        probabilite = appliquer(apprentissage.get(source, []), score)
        if probabilite is not None:
            probabilites.append(probabilite)
            etiquettes.append(etiquette)
    if probabilites:
        mesures.brier = brier(probabilites, etiquettes)
    mesures.paliers = _paliers_par_source(couples)
    return mesures


def _paliers_par_source(
    couples: Sequence[Sequence[tuple[str, float, bool]]],
) -> dict[str, list[tuple[float, float]]]:
    par_source: dict[str, tuple[list[float], list[bool]]] = defaultdict(lambda: ([], []))
    for liste in couples:
        for source, score, etiquette in liste:
            par_source[source][0].append(score)
            par_source[source][1].append(etiquette)
    return {source: ajuster_isotone(s, e) for source, (s, e) in par_source.items()}


def evaluer_requetes(
    chemin_gold: Path, nombre: int = 300, taux: float = 0.2, graine: int = 1
) -> Mesures:
    """Mode ``requete`` : requêtes imprécises sur la base telle qu'elle est."""
    rng = random.Random(graine)
    cas = [cas_imprecis(n, taux, rng) for n in tirer_notices(chemin_gold, nombre, graine)]
    with Moteur(chemin_gold) as moteur:
        return evaluer(moteur, cas)


# --- mode données : bronze bruité ---------------------------------------------------------


def copier_bronze(
    bronze: Path,
    destination: Path,
    taux: float = 0.0,
    graine: int = 1,
    actes_max: int | None = None,
) -> None:
    """Recopie la couche bronze, éventuellement échantillonnée et bruitée.

    Bruit : nom et prénoms reçoivent chacun une erreur de lecture avec la probabilité ``taux`` ;
    la date de naissance perd son jour et son mois, ou son année glisse d'un an, avec la même
    probabilité ; la fiabilité de la transcription est fixée à ``1 − taux``. L'échantillon
    (``actes_max``) est le même quel que soit le taux, pour comparer les deux copies.
    """
    rng = random.Random(graine)
    for partition in sorted(p for p in bronze.glob("*/*") if any(p.glob("actes-*.parquet"))):
        if partition.name.endswith(".en-cours"):
            continue
        actes = pl.read_parquet(partition / "actes-*.parquet", schema=SCHEMA_ACTES)
        mentions = pl.read_parquet(partition / "mentions-*.parquet", schema=SCHEMA_MENTIONS)
        if actes_max is not None and actes.height > actes_max:
            actes = actes.sort("acte_id").sample(actes_max, seed=graine)
            mentions = mentions.join(actes.select("acte_id"), on="acte_id", how="semi")
        if taux > 0:
            mentions = _bruiter_mentions(mentions, taux, rng)
        cible = destination / partition.parent.name / partition.name
        cible.mkdir(parents=True, exist_ok=True)
        actes.write_parquet(cible / "actes-00000.parquet")
        mentions.write_parquet(cible / "mentions-00000.parquet")


def _bruiter_mentions(mentions: pl.DataFrame, taux: float, rng: random.Random) -> pl.DataFrame:
    def bruiter(valeur: str | None) -> str | None:
        if valeur is None or rng.random() >= taux:
            return valeur
        return bruiter_texte(valeur, rng)

    def bruiter_date(valeur: str | None) -> str | None:
        if valeur is None or len(valeur) != 8 or rng.random() >= taux:
            return valeur
        if rng.random() < 0.5:
            return valeur[:4] + "0000"
        return f"{int(valeur[:4]) + rng.choice((-1, 1)):04d}{valeur[4:]}"

    colonnes: dict[str, Callable[[str | None], str | None]] = {
        "nom_brut": bruiter,
        "prenoms_bruts": bruiter,
        "date_naissance_brute": bruiter_date,
    }
    lignes = mentions.to_dicts()
    for ligne in lignes:
        for colonne, fonction in colonnes.items():
            ligne[colonne] = fonction(ligne[colonne])
        if ligne["date_naissance_brute"] != (
            ligne["date_naissance"].strftime("%Y%m%d") if ligne["date_naissance"] else None
        ):
            ligne["date_naissance"] = None
        ligne["confiance_source"] = round(1.0 - taux, 3)
    return pl.DataFrame(lignes, schema=SCHEMA_MENTIONS)


def evaluer_donnees(
    bronze: Path,
    referentiel: Referentiel | None = None,
    nombre: int = 300,
    taux: float = 0.2,
    graine: int = 1,
    actes_max: int | None = None,
) -> Mesures:
    """Mode ``donnees`` : requêtes exactes sur une copie bruitée de la couche bronze."""
    with tempfile.TemporaryDirectory(prefix="doudoumil-evaluation-") as travail:
        racine = Path(travail)
        for nom, bruit in (("propre", 0.0), ("bruite", taux)):
            copier_bronze(bronze, racine / nom / "bronze", bruit, graine, actes_max)
            construire_silver(racine / nom / "bronze", racine / nom / "silver", referentiel)
            construire_gold(racine / nom / "silver", racine / nom / "gold", referentiel)
        notices = tirer_notices(racine / "propre" / "gold" / "recherche.duckdb", nombre, graine)
        cas = [cas_exact(n) for n in notices]
        with Moteur(racine / "bruite" / "gold" / "recherche.duckdb") as moteur:
            return evaluer(moteur, cas)


def enregistrer_calibration(
    chemin_gold: Path, paliers: dict[str, list[tuple[float, float]]]
) -> None:
    """Remplace la calibration des sources concernées dans la base gold."""
    with duckdb.connect(str(chemin_gold)) as base:
        for source, liste in paliers.items():
            base.execute("DELETE FROM calibration WHERE source = ?", [source])
            base.executemany(
                "INSERT INTO calibration VALUES (?, ?, ?)",
                [(source, score, probabilite) for score, probabilite in liste],
            )
