"""Fabrique de lignes au format du fichier INSEE des décès, pour les tests.

Les personnes sont inventées. ``python tests/fabrique_insee.py`` régénère la fixture
``tests/fixtures/deces-extrait.txt``.
"""

from pathlib import Path

LARGEURS = {
    "nom_prenoms": 80,
    "sexe": 1,
    "date_naissance": 8,
    "code_lieu_naissance": 5,
    "commune_naissance": 30,
    "pays_naissance": 30,
    "date_deces": 8,
    "code_lieu_deces": 5,
    "numero_acte": 9,
}


def ligne_insee(
    nom_prenoms: str = "LE GOFF*MARIE JOSEPHE/",
    sexe: str = "2",
    date_naissance: str = "19310302",
    code_lieu_naissance: str = "29232",
    commune_naissance: str = "QUIMPER",
    pays_naissance: str = "",
    date_deces: str = "20200115",
    code_lieu_deces: str = "35238",
    numero_acte: str = "42",
) -> str:
    """Ligne de 176 caractères, sans fin de ligne."""
    valeurs = locals()
    return "".join(valeurs[nom].ljust(largeur)[:largeur] for nom, largeur in LARGEURS.items())


LIGNES_FIXTURE = [
    # 1. cas complet, femme, née et décédée en Bretagne
    ligne_insee(),
    # 2. homme, prénoms composés, né en Corse-du-Sud
    ligne_insee(
        nom_prenoms="MARTIN*JEAN PIERRE LOUIS/",
        sexe="1",
        date_naissance="19250817",
        code_lieu_naissance="2A004",
        commune_naissance="AJACCIO",
        date_deces="20200203",
        code_lieu_deces="13055",
        numero_acte="1187",
    ),
    # 3. jour de naissance inconnu
    ligne_insee(
        nom_prenoms="KERGOAT*YVES MARIE/",
        sexe="1",
        date_naissance="19190500",
        code_lieu_naissance="29103",
        commune_naissance="LANDERNEAU",
        date_deces="20200321",
        code_lieu_deces="29019",
        numero_acte="377",
    ),
    # 4. mois et jour de naissance inconnus, né à l'étranger
    ligne_insee(
        nom_prenoms="DA SILVA*MANUEL/",
        sexe="1",
        date_naissance="19400000",
        code_lieu_naissance="99139",
        commune_naissance="BRAGA",
        pays_naissance="PORTUGAL",
        date_deces="20200402",
        code_lieu_deces="75115",
        numero_acte="905",
    ),
    # 5. décès à La Réunion, commune de naissance accentuée
    ligne_insee(
        nom_prenoms="PAYET*LOUISE ANDRÉE/",
        date_naissance="19330611",
        code_lieu_naissance="97411",
        commune_naissance="SAINT-DENIS",
        date_deces="20200519",
        code_lieu_deces="97411",
        numero_acte="611",
    ),
    # 6. sans numéro d'acte : clé de repli sur l'identité de la personne
    ligne_insee(
        nom_prenoms="DUPONT*ANNE/",
        date_naissance="19280101",
        code_lieu_naissance="59350",
        commune_naissance="LILLE",
        date_deces="20200607",
        code_lieu_deces="59350",
        numero_acte="",
    ),
    # 7. code de lieu de naissance invalide : toléré, compté en anomalie
    ligne_insee(
        nom_prenoms="PETIT*JULES/",
        sexe="1",
        date_naissance="19300909",
        code_lieu_naissance="ABCDE",
        commune_naissance="INCONNUE",
        date_deces="20200712",
        code_lieu_deces="69123",
        numero_acte="2044",
    ),
    # 8. date de décès illisible : rejetée
    ligne_insee(nom_prenoms="BERNARD*PAUL/", sexe="1", date_deces="2020XX01"),
    # 9. ligne tronquée par erreur de copie : la date de décès manque, rejetée
    ligne_insee(nom_prenoms="ROUX*CLAIRE/")[:120],
    # 10. même décès que la ligne 1 (recouvrement de fichiers) : même identifiant
    ligne_insee(),
]


def ecrire_fixture(chemin: Path) -> None:
    chemin.write_text("\n".join(LIGNES_FIXTURE) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ecrire_fixture(Path(__file__).parent / "fixtures" / "deces-extrait.txt")
