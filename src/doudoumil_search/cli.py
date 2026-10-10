"""Ligne de commande ``doudoumil``.

Exemples ::

    doudoumil telecharge insee --annees 2019-2020
    doudoumil telecharge communes          # référentiel des communes
    doudoumil ingest insee                 # tous les fichiers téléchargés
    doudoumil ingest insee deces-2020.txt  # un fichier précis
    doudoumil normalize                    # bronze → silver
    doudoumil index                        # silver → gold (base de recherche)
    doudoumil cherche "LE GOFF Marie" --naissance 1930-1932 --lieu Quimper
    doudoumil evalue                       # mesure la qualité de la recherche
    doudoumil calibre                      # transforme le score en probabilité
    doudoumil serve                        # interface web sur http://127.0.0.1:8765

Les données sont rangées sous ``data/`` (ou sous ``$DOUDOUMIL_DATA``).
"""

import argparse
import logging
import multiprocessing
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.config import (
    dossier_bronze,
    dossier_donnees,
    dossier_gold,
    dossier_perso,
    dossier_referentiels,
    dossier_silver,
)
from doudoumil_search.ingest import insee_deces, telechargement
from doudoumil_search.normalize import lieux, silver
from doudoumil_search.pivot import Source
from doudoumil_search.search import evaluation, gold
from doudoumil_search.search.affichage import formater
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import (
    Lieu,
    LieuInconnu,
    Requete,
    lire_intervalle,
    resoudre_lieu,
    separer_nom_prenoms,
)

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
    try:
        a, b = lire_intervalle(texte)
    except ValueError as erreur:
        raise argparse.ArgumentTypeError(str(erreur)) from None
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


def commande_index(args: argparse.Namespace) -> int:
    referentiel = charger_referentiel(args.donnees)
    try:
        rapport = gold.construire_gold(
            dossier_silver(args.donnees), dossier_gold(args.donnees), referentiel
        )
    except FileNotFoundError as erreur:
        journal.error("%s", erreur)
        return 1
    print(
        f"base de recherche : {rapport.personnes} personnes, {rapport.noms_distincts} noms "
        f"distincts ({', '.join(rapport.sources)}) dans {rapport.chemin}"
    )
    return 0


def commande_cherche(args: argparse.Namespace) -> int:
    nom, prenoms = separer_nom_prenoms(args.texte or "")
    nom, prenoms = args.nom or nom, args.prenoms or prenoms
    lieu = Lieu()
    if args.lieu:
        try:
            lieu = resoudre_lieu(args.lieu, charger_referentiel(args.donnees))
        except LieuInconnu as erreur:
            journal.error("%s", erreur)
            return 1
    naissance = (args.naissance.start, args.naissance.stop - 1) if args.naissance else None
    annees = (args.annees.start, args.annees.stop - 1) if args.annees else None
    requete = Requete.creer(
        nom=nom,
        prenoms=prenoms,
        sexe=args.sexe,
        naissance=naissance,
        annees=annees,
        lieu=lieu,
        conjoint=args.conjoint,
        sources=tuple(args.source or ()),
        limite=args.limite,
    )
    if not requete.est_exploitable():
        journal.error("précisez un nom, ou un prénom avec --naissance et --lieu")
        return 1
    try:
        moteur = Moteur(gold.chemin_base(dossier_gold(args.donnees)))
    except FileNotFoundError as erreur:
        journal.error("%s", erreur)
        return 1
    with moteur:
        resultats = moteur.rechercher(requete)
    if not resultats:
        print("aucun résultat")
        return 0
    for rang, resultat in enumerate(resultats, start=1):
        print(formater(rang, resultat, details=args.details))
    return 0


def commande_evalue(args: argparse.Namespace) -> int:
    if args.mode == "donnees":
        mesures = evaluation.evaluer_donnees(
            dossier_bronze(args.donnees),
            charger_referentiel(args.donnees),
            args.cas,
            args.taux,
            args.graine,
            args.actes_max,
        )
    else:
        chemin = gold.chemin_base(dossier_gold(args.donnees))
        if not chemin.exists():
            journal.error("base de recherche absente : lancez « doudoumil index »")
            return 1
        mesures = evaluation.evaluer_requetes(chemin, args.cas, args.taux, args.graine)
    taux = evaluation.pourcent(args.taux, 0)
    print(f"mode {args.mode}, taux d'erreur {taux} : {mesures.resume()}")
    return 0


def commande_calibre(args: argparse.Namespace) -> int:
    chemin = gold.chemin_base(dossier_gold(args.donnees))
    if not chemin.exists():
        journal.error("base de recherche absente : lancez « doudoumil index »")
        return 1
    mesures = evaluation.evaluer_requetes(chemin, args.cas, args.taux, args.graine)
    # verdicts donnés dans l'interface web : des exemples réels, ajoutés aux synthétiques
    carnet = Carnet(dossier_perso(args.donnees) / "trouvailles.sqlite")
    verdicts = [
        (t.requete, t.mention_id, t.verdict == "oui")
        for t in carnet.verdicts()
        if t.requete is not None
    ]
    with Moteur(chemin) as moteur:
        reels = evaluation.couples_des_verdicts(moteur, verdicts)
    paliers = evaluation.paliers_par_source([*mesures.couples, *reels])
    evaluation.enregistrer_calibration(chemin, paliers)
    for source, liste in sorted(paliers.items()):
        print(f"{source} : calibration en {len(liste)} paliers")
    print(f"exemples : {mesures.cas} synthétiques, {len(reels)} verdicts réels")
    print(mesures.resume())
    return 0


def commande_serve(args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from doudoumil_search.api.application import creer_application

    adresse = f"http://127.0.0.1:{args.port}/"
    print(f"interface web : {adresse} (Ctrl+C pour arrêter)")
    if not args.sans_navigateur:
        threading.Timer(1.0, webbrowser.open, [adresse]).start()
    # 127.0.0.1 seulement : l'interface n'est pas accessible depuis le réseau
    uvicorn.run(
        creer_application(args.donnees), host="127.0.0.1", port=args.port, log_level="warning"
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

    index = commandes.add_parser("index", help="construire la base de recherche (gold)")
    index.set_defaults(fonction=commande_index)

    cherche = commandes.add_parser("cherche", help="chercher une personne")
    cherche.add_argument("texte", nargs="?", help="« NOM Prénoms », ex. « LE GOFF Marie »")
    cherche.add_argument("--nom")
    cherche.add_argument("--prenoms")
    cherche.add_argument("--sexe", choices=("M", "F"))
    cherche.add_argument("--naissance", type=intervalle, help="année ou intervalle de naissance")
    cherche.add_argument("--annees", type=intervalle, help="année ou intervalle de l'acte")
    cherche.add_argument("--lieu", help="commune, code INSEE ou département (ex. 29)")
    cherche.add_argument("--conjoint", help="nom du conjoint, pour une femme mariée")
    cherche.add_argument("--source", action="append", help="limiter à une source (répétable)")
    cherche.add_argument("--limite", type=int, default=20)
    cherche.add_argument("--details", action="store_true", help="composantes du score")
    cherche.set_defaults(fonction=commande_cherche)

    evalue = commandes.add_parser("evalue", help="mesurer la qualité de la recherche")
    calibre = commandes.add_parser("calibre", help="calibrer le score en probabilité")
    for sous in (evalue, calibre):
        sous.add_argument("--cas", type=int, default=300, help="nombre de requêtes de test")
        sous.add_argument("--taux", type=float, default=0.2, help="taux d'erreurs simulées")
        sous.add_argument("--graine", type=int, default=1, help="graine du tirage au hasard")
    evalue.add_argument("--mode", choices=("requete", "donnees"), default="requete")
    evalue.add_argument(
        "--actes-max", type=int, default=None, help="mode données : actes par partition"
    )
    evalue.set_defaults(fonction=commande_evalue)
    calibre.set_defaults(fonction=commande_calibre)

    serve = commandes.add_parser("serve", help="ouvrir l'interface web locale")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    serve.set_defaults(fonction=commande_serve)
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
