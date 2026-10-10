"""Ligne de commande ``doudoumil``.

Exemples ::

    doudoumil telecharge insee --annees 2019-2020
    doudoumil telecharge communes          # référentiel des communes
    doudoumil ingest insee                 # tous les fichiers téléchargés
    doudoumil ingest insee deces-2020.txt  # un fichier précis
    doudoumil normalize                    # bronze → silver

Les données sont rangées sous ``data/`` (ou sous ``$DOUDOUMIL_DATA``).
"""

import argparse
import logging
import multiprocessing
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from doudoumil_search.config import (
    dossier_bronze,
    dossier_donnees,
    dossier_referentiels,
    dossier_silver,
)
from doudoumil_search.ingest import insee_deces, telechargement
from doudoumil_search.normalize import lieux, silver
from doudoumil_search.pivot import Source

journal = logging.getLogger("doudoumil_search")


def dossier_telechargements_insee(racine: Path) -> Path:
    return dossier_bronze(racine) / Source.INSEE_DECES.value / "telechargements"


def dossier_communes(racine: Path) -> Path:
    return dossier_referentiels(racine) / "communes"


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


def intervalle(texte: str) -> range:
    """``1970-1975`` → années 1970 à 1975 incluses ; ``2020`` → la seule année 2020."""
    debut, _, fin = texte.partition("-")
    try:
        a, b = int(debut), int(fin or debut)
    except ValueError:
        raise argparse.ArgumentTypeError(f"intervalle d'années invalide : {texte!r}") from None
    if a > b:
        raise argparse.ArgumentTypeError(f"intervalle à l'envers : {texte!r}")
    return range(a, b + 1)


def commande_telecharge_insee(args: argparse.Namespace) -> int:
    dossier = dossier_telechargements_insee(args.donnees)
    ressources = telechargement.lister_ressources_insee(annees=args.annees)
    if not ressources:
        journal.error("aucun fichier de décès trouvé pour ces années")
        return 1
    for ressource in ressources:
        chemin = telechargement.telecharger(ressource, dossier)
        telechargement.extraire_si_archive(chemin)
    return 0


def commande_telecharge_communes(args: argparse.Namespace) -> int:
    dossier = lieux.telecharger_referentiel(dossier_communes(args.donnees))
    print(f"référentiel des communes {lieux.VERSION_REFERENTIEL} dans {dossier}")
    return 0


def commande_normalize(args: argparse.Namespace) -> int:
    bronze = dossier_bronze(args.donnees)
    sources = args.sources or silver.sources_bronze(bronze)
    if not sources:
        journal.error("rien à normaliser : la couche bronze est vide")
        return 1
    referentiel = charger_referentiel(args.donnees)
    for rapport in silver.construire_silver(
        bronze, dossier_silver(args.donnees), referentiel, sources
    ):
        print(
            f"{rapport.source} : {rapport.actes} actes ({rapport.doublons} doublons écartés), "
            f"{rapport.mentions} mentions"
        )
    return 0


def _ingerer(chemin: Path, bronze: Path) -> insee_deces.RapportIngestion:
    return insee_deces.ingerer_fichier(chemin, bronze)


def commande_ingest_insee(args: argparse.Namespace) -> int:
    fichiers: list[Path] = args.fichiers or sorted(
        dossier_telechargements_insee(args.donnees).glob("*.txt")
    )
    if not fichiers:
        journal.error("aucun fichier à ingérer : lancez d'abord « doudoumil telecharge insee »")
        return 1
    bronze = dossier_bronze(args.donnees)
    if args.processus == 1 or len(fichiers) == 1:
        rapports = [_ingerer(fichier, bronze) for fichier in fichiers]
    else:
        # « spawn » plutôt que « fork » : un processus copié par fork peut hériter d'un verrou
        # tenu par un autre fil d'exécution et rester bloqué.
        contexte = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=args.processus, mp_context=contexte) as executeur:
            rapports = list(executeur.map(_ingerer, fichiers, [bronze] * len(fichiers)))
    for rapport in rapports:
        detail = ", ".join(f"{motif} : {n}" for motif, n in rapport.anomalies.most_common())
        print(
            f"{rapport.fichier} : {rapport.lignes_ingerees} ingérées, "
            f"{rapport.lignes_rejetees} rejetées" + (f" ({detail})" if detail else "")
        )
    return 0


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="doudoumil", description="Moteur de recherche généalogique personnel."
    )
    analyseur.add_argument(
        "--donnees",
        type=Path,
        default=None,
        help="dossier racine des données (défaut : $DOUDOUMIL_DATA ou ./data)",
    )
    analyseur.add_argument("-v", "--bavard", action="store_true", help="journal détaillé")
    commandes = analyseur.add_subparsers(dest="commande", required=True)

    telecharge = commandes.add_parser("telecharge", help="télécharger une source")
    sources_telecharge = telecharge.add_subparsers(dest="source", required=True)
    t_insee = sources_telecharge.add_parser("insee", help="fichier des décès de l'INSEE")
    t_insee.add_argument("--annees", type=intervalle, help="ex. 1970-1975 (défaut : toutes)")
    t_insee.set_defaults(fonction=commande_telecharge_insee)
    t_communes = sources_telecharge.add_parser(
        "communes", help="référentiel des communes (Code officiel géographique)"
    )
    t_communes.set_defaults(fonction=commande_telecharge_communes)

    ingest = commandes.add_parser("ingest", help="convertir une source en couche bronze")
    sources_ingest = ingest.add_subparsers(dest="source", required=True)
    i_insee = sources_ingest.add_parser("insee", help="fichier des décès de l'INSEE")
    i_insee.add_argument("fichiers", nargs="*", type=Path, help="défaut : fichiers téléchargés")
    i_insee.add_argument(
        "--processus", type=int, default=None, help="fichiers traités en parallèle"
    )
    i_insee.set_defaults(fonction=commande_ingest_insee)

    normalize = commandes.add_parser("normalize", help="construire la couche silver")
    normalize.add_argument(
        "sources", nargs="*", help="sources à normaliser (défaut : toutes celles de bronze)"
    )
    normalize.set_defaults(fonction=commande_normalize)
    return analyseur


def main(argv: Sequence[str] | None = None) -> int:
    args = construire_analyseur().parse_args(argv)
    args.donnees = args.donnees or dossier_donnees()
    logging.basicConfig(
        level=logging.DEBUG if args.bavard else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    return int(args.fonction(args))


if __name__ == "__main__":
    sys.exit(main())
