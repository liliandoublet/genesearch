"""Tests de bout en bout : bronze → silver → gold → recherche (règles R1 à R5)."""

from pathlib import Path

import duckdb
import pytest

from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.search.calibration import (
    chemin_calibration,
    ecrire_calibration,
    lire_calibration,
)
from doudoumil_search.search.gold import construire_gold
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import Lieu, Requete, resoudre_lieu
from jeu_recherche import EXTRAIT_COMMUNES, construire_racine


@pytest.fixture(scope="module")
def referentiel() -> Referentiel:
    return Referentiel.depuis_dossier(EXTRAIT_COMMUNES)


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return construire_racine(tmp_path_factory.mktemp("donnees"))


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


def test_calibration_appliquee_relue_et_conservee(base: Path, tmp_path: Path) -> None:
    """Calibration lue dans gold/calibration.json, relue si elle change, gardée ensuite."""
    copie = tmp_path / "gold" / "recherche.duckdb"
    copie.parent.mkdir()
    copie.write_bytes(base.read_bytes())
    requete = Requete.creer(nom="LE GOFF", prenoms="Marie Josèphe")
    with Moteur(copie) as m:
        assert m.rechercher(requete)[0].probabilite is None
        # la base reste ouverte pendant qu'une autre commande calibre
        ecrire_calibration(chemin_calibration(copie), {"insee_deces": [(0.0, 0.1), (0.8, 0.95)]})
        premier = m.rechercher(requete)[0]
        assert premier.probabilite == 0.95
        assert premier.libelle == "très probable"
    racine = base.parent.parent
    construire_gold(racine / "silver", tmp_path / "gold")
    assert lire_calibration(chemin_calibration(copie)) == {"insee_deces": [(0.0, 0.1), (0.8, 0.95)]}
