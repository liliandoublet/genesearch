"""Jeu de données de recherche partagé : décès INSEE inventés et un ménage de recensement.

Il exerce chaque règle de la recherche : variantes phonétiques (``LEGOF``), erreur de lecture
(``LE GOSS``), homonyme plus jeune, ``MOREAU`` / ``NOREAU``, et une épouse inscrite sous le nom
de son mari dans un recensement.
"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from doudoumil_search.ingest.ecriture import EcrivainPartition
from doudoumil_search.ingest.insee_deces import ingerer_fichier
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.silver import construire_silver
from doudoumil_search.pivot import (
    Acte,
    Mention,
    NatureNom,
    Role,
    Sexe,
    Source,
    TypeActe,
    fabriquer_id,
)
from doudoumil_search.search.gold import construire_gold
from fabrique_insee import ligne_insee

INGESTION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
EXTRAIT_COMMUNES = Path(__file__).parent / "fixtures" / "communes"

PERSONNES_INSEE = [
    # nom*prénoms, sexe, naissance, lieu de naissance, décès, lieu de décès
    ("LE GOFF*MARIE JOSEPHE/", "2", "19310302", "29232", "20200115", "35238"),
    ("LEGOF*MARIE/", "2", "19310711", "29232", "20200301", "29232"),
    ("LE GOSS*ANNE/", "2", "19400101", "29019", "20200401", "29019"),
    ("LE GOFF*MARIE/", "2", "19500505", "29019", "20200501", "29019"),
    ("LE GOFF*JEAN/", "1", "19310101", "29232", "20200601", "29232"),
    ("MOREAU*JEAN/", "1", "19250101", "75115", "20200701", "75115"),
    ("NOREAU*JEAN/", "1", "19250202", "75115", "20200801", "75115"),
    ("MARTIN*JEAN PIERRE LOUIS/", "1", "19250817", "2A004", "20200203", "13055"),
    ("KERGOAT*YVES MARIE/", "1", "19190500", "29103", "20200321", "29019"),
]


def partition_recensement(bronze: Path) -> None:
    """Un ménage du recensement de 1906 à Quimper, l'épouse sous le nom de son mari."""
    acte_id = fabriquer_id(Source.SOCFACE, "29232", "1906", "menage-12")
    acte = Acte(
        acte_id=acte_id,
        source=Source.SOCFACE,
        type=TypeActe.RECENSEMENT,
        annee=1906,
        commune_code_insee="29232",
        departement="29",
        depot="AD 29",
        cote="6 M 123",
        vue="45",
        ingested_at=INGESTION,
    )
    membres = [
        ("chef", Role.CHEF_MENAGE, "MARTIN", "Pierre", Sexe.M, 45, NatureNom.NAISSANCE),
        ("epouse", Role.EPOUSE, "MARTIN", "Marie Josèphe", Sexe.F, 40, NatureNom.MARITAL),
        ("enfant", Role.ENFANT, "MARTIN", "Yves", Sexe.M, 10, NatureNom.NAISSANCE),
    ]
    mentions = [
        Mention(
            mention_id=fabriquer_id(Source.SOCFACE, "29232", "1906", "menage-12", cle),
            acte_id=acte_id,
            role=role,
            nom_brut=nom,
            prenoms_bruts=prenoms,
            nature_nom=nature,
            sexe=sexe,
            age=age,
            confiance_source=0.8,
        )
        for cle, role, nom, prenoms, sexe, age, nature in membres
    ]
    with EcrivainPartition(bronze / "socface" / "rp1906-29") as ecrivain:
        ecrivain.ajouter(acte, mentions)


def construire_racine(racine: Path) -> Path:
    """Données complètes sous ``racine`` (bronze, silver, gold, référentiel) ; renvoie la base."""
    shutil.copytree(EXTRAIT_COMMUNES, racine / "ref" / "communes")
    referentiel = Referentiel.depuis_dossier(racine / "ref" / "communes")
    fichier = racine / "deces-2020.txt"
    lignes = [
        ligne_insee(
            nom_prenoms=nom,
            sexe=sexe,
            date_naissance=naissance,
            code_lieu_naissance=lieu_naissance,
            commune_naissance="",
            date_deces=deces,
            code_lieu_deces=lieu_deces,
            numero_acte=str(numero),
        )
        for numero, (nom, sexe, naissance, lieu_naissance, deces, lieu_deces) in enumerate(
            PERSONNES_INSEE, start=1
        )
    ]
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    ingerer_fichier(fichier, racine / "bronze", ingested_at=INGESTION)
    partition_recensement(racine / "bronze")
    construire_silver(racine / "bronze", racine / "silver", referentiel)
    return construire_gold(racine / "silver", racine / "gold", referentiel).chemin
