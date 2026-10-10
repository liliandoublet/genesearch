"""Tests de bout en bout : bronze → silver → gold → recherche (règles R1 à R5)."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

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
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import Lieu, Requete, resoudre_lieu
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


def _partition_recensement(bronze: Path) -> None:
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


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT_COMMUNES)


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory, referentiel: Referentiel) -> Path:
    racine = tmp_path_factory.mktemp("donnees")
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
    _partition_recensement(racine / "bronze")
    construire_silver(racine / "bronze", racine / "silver", referentiel)
    return construire_gold(racine / "silver", racine / "gold", referentiel).chemin


@pytest.fixture
def moteur(base: Path) -> Moteur:
    with Moteur(base) as m:
        yield m  # type: ignore[misc]


def _noms(resultats: list) -> list[str]:  # type: ignore[type-arg]
    return [f"{r.fiche['nom_brut']} {r.fiche['prenoms_bruts']}" for r in resultats]


# --- base gold ------------------------------------------------------------------------------


def test_contenu_de_la_base(base: Path) -> None:
    with duckdb.connect(str(base), read_only=True) as connexion:
        assert connexion.execute("SELECT count(*) FROM personnes").fetchone() == (12,)
        sources = connexion.execute("SELECT valeur FROM meta WHERE cle = 'sources'").fetchone()
        assert sources == ("insee_deces,socface",)
        # arrondissement de Paris ramené à la commune actuelle
        paris = connexion.execute(
            "SELECT DISTINCT commune_actuelle FROM personnes WHERE commune_code_insee = '75115'"
        ).fetchall()
        assert paris == [("75056",)]
        assert connexion.execute(
            "SELECT occurrences FROM noms WHERE nom_norm = 'LE GOFF'"
        ).fetchone() == (3,)
        prenoms = connexion.execute(
            "SELECT rang, prenom, cle, departement, naissance_departement FROM prenoms "
            "WHERE mention_id IN (SELECT mention_id FROM personnes WHERE nom_norm = 'MARTIN') "
            "AND annee_naissance_min = 1925 ORDER BY rang"
        ).fetchall()
        # champs de filtrage du canal C recopiés dans la table des prénoms
        assert prenoms == [
            (1, "JEAN", "JN", "13", "2A"),
            (2, "PIERRE", "PR", "13", "2A"),
            (3, "LOUIS", "L", "13", "2A"),
        ]


def test_base_absente(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="doudoumil index"):
        Moteur(tmp_path / "absente.duckdb")


# --- présélection (R1) ----------------------------------------------------------------------


def test_meilleur_resultat_et_canaux(moteur: Moteur) -> None:
    requete = Requete.creer(nom="Le Goff", prenoms="Marie", naissance=(1931, 1931))
    resultats = moteur.rechercher(requete)
    assert _noms(resultats)[0] == "LE GOFF MARIE JOSEPHE"
    premier = resultats[0]
    assert set(premier.canaux) == {"phonétique", "noms proches"}
    assert premier.fiche["cote"] == "deces-2020.txt"
    assert premier.fiche["commune_label"] == "Rennes"
    # variante phonétique trouvée par le canal A
    legof = next(r for r in resultats if r.fiche["nom_brut"] == "LEGOF")
    assert "phonétique" in legof.canaux


def test_erreur_de_lecture_rattrapee_par_le_canal_b(moteur: Moteur) -> None:
    resultats = moteur.rechercher(Requete.creer(nom="LE GOFF", prenoms="Anne"))
    le_goss = next(r for r in resultats if r.fiche["nom_brut"] == "LE GOSS")
    assert le_goss.canaux == ("noms proches",)


def test_moreau_trouve_noreau(moteur: Moteur) -> None:
    resultats = moteur.rechercher(Requete.creer(nom="MOREAU", prenoms="Jean"))
    assert _noms(resultats)[:2] == ["MOREAU JEAN", "NOREAU JEAN"]
    assert resultats[1].canaux == ("noms proches",)


def test_filtre_de_naissance_avec_tolerance(moteur: Moteur) -> None:
    requete = Requete.creer(nom="LE GOFF", prenoms="Marie", naissance=(1932, 1932))
    naissances = {r.fiche["annee_naissance_min"] for r in moteur.rechercher(requete)}
    assert 1931 in naissances  # tolérance d'un an pour INSEE
    assert 1950 not in naissances


def test_filtre_de_sexe(moteur: Moteur) -> None:
    resultats = moteur.rechercher(Requete.creer(nom="LE GOFF", sexe="M"))
    assert _noms(resultats) == ["LE GOFF JEAN"]


def test_le_lieu_departage_les_homonymes(moteur: Moteur, referentiel: Referentiel) -> None:
    requete = Requete.creer(
        nom="LE GOFF", prenoms="Marie", lieu=resoudre_lieu("Brest", referentiel)
    )
    premier = moteur.rechercher(requete)[0]
    assert premier.fiche["annee_naissance_min"] == 1950  # née et décédée à Brest


# --- femmes mariées (R2) --------------------------------------------------------------------


def test_epouse_trouvee_sans_le_nom(moteur: Moteur, referentiel: Referentiel) -> None:
    requete = Requete.creer(
        nom="LE GOFF",
        prenoms="Marie Josèphe",
        sexe="F",
        naissance=(1865, 1866),
        lieu=resoudre_lieu("Quimper", referentiel),
        sources=("socface",),
    )
    resultats = moteur.rechercher(requete)
    epouse = next(r for r in resultats if r.fiche["nom_brut"] == "MARTIN")
    assert epouse.canaux == ("sans le nom",)
    assert epouse.nom_epouse_probable
    assert epouse.composantes.nom is None  # ni bonus ni pénalité sur le nom
    assert epouse.composantes.naissance == 1.0
    assert epouse.composantes.lieu == 1.0


def test_conjoint_donne(moteur: Moteur, referentiel: Referentiel) -> None:
    commun = {
        "nom": "LE GOFF",
        "prenoms": "Marie Josèphe",
        "sexe": "F",
        "naissance": (1865, 1866),
        "lieu": resoudre_lieu("Quimper", referentiel),
        "sources": ("socface",),
    }
    sans = moteur.rechercher(Requete.creer(**commun))[0]
    avec = moteur.rechercher(Requete.creer(**commun, conjoint="Martin"))[0]
    assert avec.mention_id == sans.mention_id
    assert "conjoint" in avec.canaux
    assert avec.composantes.nom == 1.0
    assert avec.score > sans.score


def test_un_homme_n_est_pas_traite_comme_une_epouse(moteur: Moteur) -> None:
    requete = Requete.creer(nom="MARTIN", prenoms="Pierre", sources=("socface",))
    chef = moteur.rechercher(requete)[0]
    assert not chef.nom_epouse_probable
    assert chef.composantes.nom == 1.0


# --- recherche sans nom, calibration, erreurs -----------------------------------------------


def test_recherche_sans_nom(moteur: Moteur) -> None:
    requete = Requete.creer(
        prenoms="Yves", naissance=(1919, 1919), lieu=Lieu(departements=frozenset({"29"}))
    )
    assert _noms(moteur.rechercher(requete))[0] == "KERGOAT YVES MARIE"


def test_requete_inexploitable(moteur: Moteur) -> None:
    with pytest.raises(ValueError, match="il faut un nom"):
        moteur.rechercher(Requete.creer(prenoms="Marie"))


def test_resultats_non_calibres(moteur: Moteur) -> None:
    resultat = moteur.rechercher(Requete.creer(nom="LE GOFF"))[0]
    assert resultat.probabilite is None
    assert resultat.libelle == "non calibré"


def test_calibration_appliquee_et_conservee(base: Path, tmp_path: Path) -> None:
    copie = tmp_path / "gold" / "recherche.duckdb"
    copie.parent.mkdir()
    copie.write_bytes(base.read_bytes())
    with duckdb.connect(str(copie)) as connexion:
        connexion.execute(
            "INSERT INTO calibration VALUES ('insee_deces', 0.0, 0.1), ('insee_deces', 0.8, 0.95)"
        )
    with Moteur(copie) as m:
        premier = m.rechercher(Requete.creer(nom="LE GOFF", prenoms="Marie Josèphe"))[0]
        assert premier.probabilite == 0.95
        assert premier.libelle == "très probable"
