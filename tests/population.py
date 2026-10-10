"""Population synthétique au format INSEE, pour mesurer la recherche dans les tests.

Les personnes sont inventées : noms et prénoms courants tirés au hasard, complétés de noms
fabriqués pour varier les distracteurs. Les lieux sont ceux de l'extrait du référentiel.
"""

import random
from pathlib import Path

from fabrique_insee import ligne_insee

NOMS = [
    "MARTIN",
    "BERNARD",
    "THOMAS",
    "PETIT",
    "ROBERT",
    "RICHARD",
    "DURAND",
    "DUBOIS",
    "MOREAU",
    "LAURENT",
    "SIMON",
    "MICHEL",
    "LEFEBVRE",
    "LEROY",
    "ROUX",
    "DAVID",
    "BERTRAND",
    "MOREL",
    "FOURNIER",
    "GIRARD",
    "BONNET",
    "DUPONT",
    "LAMBERT",
    "FONTAINE",
    "ROUSSEAU",
    "VINCENT",
    "MULLER",
    "LEFEVRE",
    "FAURE",
    "ANDRE",
    "MERCIER",
    "BLANC",
    "GUERIN",
    "BOYER",
    "GARNIER",
    "CHEVALIER",
    "LEGRAND",
    "GAUTHIER",
    "PERRIN",
    "ROBIN",
    "CLEMENT",
    "MORIN",
    "NICOLAS",
    "HENRY",
    "ROUSSEL",
    "MATHIEU",
    "MASSON",
    "KERGOAT",
    "TANGUY",
    "GUILLOU",
    "MADEC",
    "JEZEQUEL",
    "LE GOFF",
    "LE GALL",
    "LE ROUX",
    "LE BRIS",
    "LE COZ",
    "DA SILVA",
]
SYLLABES = [
    "BER",
    "CAR",
    "DOU",
    "FAL",
    "GAN",
    "KER",
    "LAN",
    "MAR",
    "NOU",
    "PEL",
    "QUE",
    "RIV",
    "SAL",
    "TOU",
    "VAL",
    "BRI",
    "CHA",
    "DRE",
    "FLO",
    "GRO",
]
PRENOMS = {
    "1": [
        "JEAN",
        "PIERRE",
        "LOUIS",
        "JOSEPH",
        "FRANCOIS",
        "ANDRE",
        "MARCEL",
        "RENE",
        "YVES",
        "HENRI",
        "GEORGES",
        "PAUL",
        "ROGER",
        "ROBERT",
        "JACQUES",
        "MICHEL",
        "ALBERT",
        "LUCIEN",
        "EMILE",
        "MAURICE",
    ],
    "2": [
        "MARIE",
        "JEANNE",
        "MARGUERITE",
        "LOUISE",
        "GERMAINE",
        "ANNE",
        "YVONNE",
        "MADELEINE",
        "SUZANNE",
        "MARCELLE",
        "ANDREE",
        "SIMONE",
        "RENEE",
        "HELENE",
        "ODETTE",
        "LUCIENNE",
        "PAULETTE",
        "DENISE",
        "JOSEPHINE",
        "ALICE",
    ],
}
COMMUNES = [
    "29232",
    "35238",
    "29103",
    "29019",
    "2A004",
    "13055",
    "75115",
    "69123",
    "59350",
    "35288",
    "97411",
    "93066",
]


def ecrire_population(
    chemin: Path, nombre: int, graine: int = 7, noms_fabriques: int = 300
) -> None:
    rng = random.Random(graine)
    noms = [
        *NOMS,
        *("".join(rng.choices(SYLLABES, k=rng.randint(2, 3))) for _ in range(noms_fabriques)),
    ]
    lignes = []
    for numero in range(1, nombre + 1):
        sexe = rng.choice("12")
        prenoms = " ".join(rng.sample(PRENOMS[sexe], k=rng.choice((1, 1, 2, 2, 3))))
        annee = rng.randint(1900, 1960)
        mois, jour = rng.randint(1, 12), rng.randint(1, 28)
        naissance = f"{annee}{mois:02d}{jour:02d}" if rng.random() > 0.1 else f"{annee}0000"
        lignes.append(
            ligne_insee(
                nom_prenoms=f"{rng.choice(noms)}*{prenoms}/",
                sexe=sexe,
                date_naissance=naissance,
                code_lieu_naissance=rng.choice(COMMUNES),
                commune_naissance="",
                date_deces=f"2020{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}",
                code_lieu_deces=rng.choice(COMMUNES),
                numero_acte=str(numero),
            )
        )
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
