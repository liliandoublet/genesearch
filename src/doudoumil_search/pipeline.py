"""Chaîne complète : téléchargement (au choix) → bronze → silver → gold.

``doudoumil pipeline`` enchaîne les étapes en ne refaisant que celles dont les entrées ont
changé, à la manière de ``make`` : chaque résultat est comparé, par dates de modification, aux
fichiers dont il dépend.

- bronze : un fichier INSEE téléchargé, ou un relevé (fichier de correspondance et tableur),
  est converti si sa partition est absente ou plus ancienne que lui ;
- silver : une source est renormalisée si l'une de ses partitions bronze, ou le référentiel
  des communes, a changé (partition ajoutée, refaite ou supprimée) ;
- gold : la base de recherche est reconstruite si une source silver ou le référentiel a changé.

Ajouter le fichier INSEE d'un nouveau mois ne convertit donc que ce fichier ; la normalisation
de la source et la base de recherche sont, elles, refaites en entier.
"""

import logging
import multiprocessing
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError

from doudoumil_search.config import (
    dossier_bronze,
    dossier_communes,
    dossier_gold,
    dossier_releves,
    dossier_silver,
    dossier_telechargements_insee,
)
from doudoumil_search.ingest import insee_deces, releves, telechargement
from doudoumil_search.ingest.commun import RapportIngestion
from doudoumil_search.normalize import lieux, silver
from doudoumil_search.pivot import Source
from doudoumil_search.search import gold

journal = logging.getLogger(__name__)

Afficher = Callable[[str], None]


def charger_referentiel(racine: Path) -> lieux.Referentiel | None:
    """Référentiel des communes s'il a été téléchargé, sinon ``None`` (avec un avertissement)."""
    dossier = dossier_communes(racine)
    if not (dossier / "communes.json").exists():
        journal.warning(
            "référentiel des communes absent : lancez « doudoumil telecharge communes » "
            "pour compléter les lieux"
        )
        return None
    return lieux.Referentiel.depuis_dossier(dossier)


def resume_ingestion(rapport: RapportIngestion) -> str:
    """« deces-2020.txt : 8 ingérées, 2 rejetées (…) », et où trouver les rejets."""
    detail = ", ".join(f"{motif} : {n}" for motif, n in rapport.anomalies.most_common())
    texte = (
        f"{rapport.fichier} : {rapport.lignes_ingerees} ingérées, "
        f"{rapport.lignes_rejetees} rejetées" + (f" ({detail})" if detail else "")
    )
    if rapport.lignes_rejetees:
        texte += f"\n  lignes rejetées et motifs : {rapport.dossier / 'rejets.csv'}"
    return texte


def _ingerer_insee(chemin: Path, bronze: Path) -> RapportIngestion:
    return insee_deces.ingerer_fichier(chemin, bronze)


def ingerer_insee(
    fichiers: Sequence[Path], bronze: Path, processus: int | None = None
) -> list[RapportIngestion]:
    """Convertit des fichiers INSEE, en parallèle s'il y en a plusieurs."""
    if processus == 1 or len(fichiers) <= 1:
        return [_ingerer_insee(fichier, bronze) for fichier in fichiers]
    # « spawn » plutôt que « fork » : un processus copié par fork peut hériter d'un verrou
    # tenu par un autre fil d'exécution et rester bloqué.
    contexte = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=processus, mp_context=contexte) as executeur:
        return list(executeur.map(_ingerer_insee, fichiers, [bronze] * len(fichiers)))


# --- dates de modification --------------------------------------------------------------------


def date_de(chemin: Path) -> float:
    """Date de modification la plus récente d'un fichier, ou d'un dossier et de son contenu.

    Un chemin absent vaut 0 : il ne rend rien plus récent que lui.
    """
    if not chemin.exists():
        return 0.0
    if chemin.is_file():
        return chemin.stat().st_mtime
    return max([chemin.stat().st_mtime, *(p.stat().st_mtime for p in chemin.rglob("*"))])


def a_refaire(entrees: Iterable[Path], resultat: Path) -> bool:
    """Le résultat manque, ou l'une des entrées est plus récente que lui."""
    if not resultat.exists():
        return True
    return max((date_de(e) for e in entrees), default=0.0) > date_de(resultat)


def partitions_bronze(dossier_source: Path) -> list[Path]:
    """Partitions publiées d'une source (sans les téléchargements ni les partitions en cours)."""
    if not dossier_source.exists():
        return []
    return sorted(
        d
        for d in dossier_source.iterdir()
        if d.is_dir() and not d.name.endswith(".en-cours") and any(d.glob("actes-*.parquet"))
    )


def _date_propre(dossier: Path) -> float:
    """Date du dossier lui-même : elle change quand une entrée y est ajoutée ou supprimée."""
    return dossier.stat().st_mtime if dossier.exists() else 0.0


# --- étapes -----------------------------------------------------------------------------------


@dataclass
class BilanPipeline:
    """Erreurs rencontrées ; une erreur sur une source n'arrête pas les autres."""

    erreurs: list[str] = field(default_factory=list)

    @property
    def reussi(self) -> bool:
        return not self.erreurs


def telecharger_sources(
    racine: Path, annees: range | None, afficher: Afficher, bilan: BilanPipeline
) -> None:
    """Référentiel des communes s'il manque, puis fichiers INSEE (déjà présents : ignorés)."""
    try:
        if not (dossier_communes(racine) / "communes.json").exists():
            lieux.telecharger_referentiel(dossier_communes(racine))
            afficher(f"référentiel des communes {lieux.VERSION_REFERENTIEL} téléchargé")
        dossier = dossier_telechargements_insee(racine)
        ressources = telechargement.lister_ressources_insee(annees=annees)
        for ressource in ressources:
            chemin = telechargement.telecharger(ressource, dossier)
            telechargement.extraire_si_archive(chemin)
        afficher(f"décès INSEE : {len(ressources)} fichiers disponibles dans {dossier}")
    except (OSError, URLError, ValueError) as erreur:
        bilan.erreurs.append(f"téléchargement impossible ({erreur}) : données locales utilisées")
        afficher(bilan.erreurs[-1])


def mettre_a_jour_bronze(
    racine: Path,
    forcer: bool,
    processus: int | None,
    afficher: Afficher,
    bilan: BilanPipeline,
) -> None:
    bronze = dossier_bronze(racine)
    fichiers = sorted(dossier_telechargements_insee(racine).glob("*.txt"))
    dossier_insee = bronze / Source.INSEE_DECES.value
    a_convertir = [f for f in fichiers if forcer or a_refaire([f], dossier_insee / f.stem)]
    for rapport in ingerer_insee(a_convertir, bronze, processus):
        afficher(resume_ingestion(rapport))
    if deja := len(fichiers) - len(a_convertir):
        afficher(f"décès INSEE : {deja} fichier{'s' * (deja > 1)} déjà converti{'s' * (deja > 1)}")

    for correspondance in sorted(dossier_releves(racine).glob("*.toml")):
        try:
            tableur = releves.lire_correspondance(correspondance).fichier
            partition = bronze / Source.RELEVE.value / correspondance.stem
            if forcer or a_refaire([correspondance, tableur], partition):
                afficher(resume_ingestion(releves.ingerer_releve(correspondance, bronze)))
            else:
                afficher(f"relevé {correspondance.stem} : à jour")
        except (releves.CorrespondanceInvalide, OSError) as erreur:
            bilan.erreurs.append(f"{correspondance.name} : {erreur}")
            afficher(bilan.erreurs[-1])
    decrits = {c.stem for c in dossier_releves(racine).glob("*.toml")}
    for partition in partitions_bronze(bronze / Source.RELEVE.value):
        if partition.name not in decrits:
            afficher(
                f"relevé {partition.name} : sans correspondance dans {dossier_releves(racine)}, "
                f"gardé dans la base (supprimez {partition} pour le retirer)"
            )


def mettre_a_jour_silver(
    racine: Path, referentiel: lieux.Referentiel | None, forcer: bool, afficher: Afficher
) -> None:
    bronze, dossier = dossier_bronze(racine), dossier_silver(racine)
    for source in silver.sources_bronze(bronze):
        partitions = partitions_bronze(bronze / source)
        derniere = max(
            [_date_propre(bronze / source), date_de(dossier_communes(racine))]
            + [date_de(p) for p in partitions]
        )
        if not forcer and (dossier / source).exists() and derniere <= date_de(dossier / source):
            afficher(f"normalisation {source} : à jour")
            continue
        rapport = silver.construire_source(bronze, dossier, source, referentiel)
        afficher(
            f"normalisation {source} : {rapport.actes} actes ({rapport.doublons} doublons "
            f"écartés), {rapport.mentions} mentions"
        )


def mettre_a_jour_gold(
    racine: Path,
    referentiel: lieux.Referentiel | None,
    forcer: bool,
    afficher: Afficher,
    bilan: BilanPipeline,
) -> None:
    dossier = dossier_silver(racine)
    sources = [dossier / s for s in gold.sources_silver(dossier)]
    if not sources:
        bilan.erreurs.append(
            "aucune donnée à indexer : téléchargez les décès INSEE (--telecharge) ou ajoutez un "
            "relevé dans data/releves/"
        )
        afficher(bilan.erreurs[-1])
        return
    chemin = gold.chemin_base(dossier_gold(racine))
    derniere = max(
        [_date_propre(dossier), date_de(dossier_communes(racine))] + [date_de(s) for s in sources]
    )
    if not forcer and chemin.exists() and derniere <= date_de(chemin):
        afficher("base de recherche : à jour")
        return
    rapport = gold.construire_gold(dossier, dossier_gold(racine), referentiel)
    afficher(
        f"base de recherche : {rapport.personnes} personnes, {rapport.noms_distincts} noms "
        f"distincts ({', '.join(rapport.sources)})"
    )


def executer_pipeline(
    racine: Path,
    *,
    telecharger: bool = False,
    annees: range | None = None,
    forcer: bool = False,
    processus: int | None = None,
    afficher: Afficher = print,
) -> BilanPipeline:
    """Met à jour bronze, silver et gold ; ``forcer`` refait tout, même ce qui est à jour."""
    bilan = BilanPipeline()
    if telecharger:
        telecharger_sources(racine, annees, afficher, bilan)
    referentiel = charger_referentiel(racine)
    mettre_a_jour_bronze(racine, forcer, processus, afficher, bilan)
    mettre_a_jour_silver(racine, referentiel, forcer, afficher)
    mettre_a_jour_gold(racine, referentiel, forcer, afficher, bilan)
    return bilan
