"""Tests de l'interface web : pages, filtres, fiches, trouvailles, exports, API et sécurité."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doudoumil_search.api.application import creer_application
from doudoumil_search.api.formulaire import Formulaire, FormulaireInvalide
from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.cli import main
from doudoumil_search.search.requete import Lieu, Requete
from jeu_recherche import construire_racine


@pytest.fixture(scope="module")
def racine_commune(tmp_path_factory: pytest.TempPathFactory) -> Path:
    racine = tmp_path_factory.mktemp("web")
    construire_racine(racine)
    return racine


@pytest.fixture
def racine(racine_commune: Path, tmp_path: Path) -> Path:
    """Copie légère : la base est partagée, le carnet de trouvailles est propre à chaque test."""
    copie = tmp_path / "donnees"
    (copie / "gold").mkdir(parents=True)
    (copie / "gold" / "recherche.duckdb").symlink_to(racine_commune / "gold" / "recherche.duckdb")
    (copie / "ref").symlink_to(racine_commune / "ref")
    return copie


@pytest.fixture
def client(racine: Path) -> Iterator[TestClient]:
    with TestClient(creer_application(racine)) as c:
        yield c


def _liens_fiches(html: str) -> list[str]:
    return [lien.replace("&amp;", "&") for lien in re.findall(r'class="nom" href="([^"]+)"', html)]


def _texte(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# --- formulaire -----------------------------------------------------------------------------


def test_formulaire_lu_et_reecrit() -> None:
    formulaire = Formulaire.depuis({"q": " LE GOFF Marie ", "naissance": "1931", "page": "2"})
    assert (formulaire.q, formulaire.naissance, formulaire.page) == ("LE GOFF Marie", "1931", 2)
    assert formulaire.avance  # un champ avancé rempli ouvre la recherche avancée
    assert formulaire.adresse(page=1) == "/recherche?q=LE+GOFF+Marie&naissance=1931"
    assert Formulaire.depuis({"page": "-3"}).page == 1


def test_formulaire_vers_requete() -> None:
    requete = Formulaire.depuis({"q": "LE GOFF Marie", "nom": "Le Gof", "sexe": "F"}).requete(None)
    assert (requete.nom, requete.prenoms, requete.sexe) == ("LE GOF", ("MARIE",), "F")


@pytest.mark.parametrize(
    ("parametres", "champ"),
    [
        ({"q": "DUPONT", "naissance": "vers 1900"}, "naissance"),
        ({"q": "DUPONT", "annees": "1990-1980"}, "annees"),
        ({"q": "DUPONT", "lieu": "Quimper"}, "lieu"),  # sans référentiel
        ({"q": "DUPONT", "sexe": "X"}, "sexe"),
        ({"q": "DUPONT", "source": "filae"}, "source"),
        ({"prenoms": "Marie"}, "q"),
    ],
)
def test_formulaire_invalide(parametres: dict[str, str], champ: str) -> None:
    with pytest.raises(FormulaireInvalide) as erreur:
        Formulaire.depuis(parametres).requete(None)
    assert champ in erreur.value.erreurs


def test_requete_serialisee_aller_retour() -> None:
    requete = Requete.creer(
        nom="Le Goff",
        prenoms="Marie",
        sexe="F",
        naissance=(1930, 1932),
        annees=(2020, 2020),
        lieu=Lieu(frozenset({"29232"}), frozenset({"29"})),
        conjoint="Martin",
        sources=("insee_deces",),
    )
    copie = Requete.depuis_dict(json.loads(json.dumps(requete.vers_dict())))
    assert copie == requete


# --- pages ----------------------------------------------------------------------------------


def test_accueil(client: TestClient) -> None:
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert 'name="q"' in reponse.text
    assert "base de recherche n'existe pas" not in reponse.text


def test_recherche_et_filtres(client: TestClient) -> None:
    reponse = client.get("/recherche", params={"q": "LE GOFF Marie", "naissance": "1931"})
    assert reponse.status_code == 200
    texte = _texte(reponse.text)
    assert texte.index("LE GOFF MARIE JOSEPHE") < texte.index("LEGOF MARIE")
    assert "35 Ille-et-Vilaine" in texte  # département nommé dans les filtres
    assert "exporter en CSV" in texte

    filtre = client.get("/recherche", params={"q": "LE GOFF", "filtre_departement": "29"})
    assert "LE GOFF MARIE JOSEPHE" not in filtre.text  # décédée en Ille-et-Vilaine
    assert "(filtres actifs)" in filtre.text


def test_recherche_vide_renvoie_au_formulaire(client: TestClient) -> None:
    reponse = client.get("/recherche")
    assert reponse.status_code == 200
    assert "Retrouver une personne" in reponse.text


def test_erreur_de_saisie(client: TestClient) -> None:
    reponse = client.get("/recherche", params={"q": "LE GOFF", "naissance": "vers 1900"})
    assert reponse.status_code == 422
    assert "intervalle d&#39;années invalide" in reponse.text


def test_lieu_par_nom_et_epouse(client: TestClient) -> None:
    parametres = {
        "q": "LE GOFF Marie Josèphe",
        "sexe": "F",
        "naissance": "1865-1866",
        "lieu": "Quimper (29)",
        "source": "socface",
    }
    texte = _texte(client.get("/recherche", params=parametres).text)
    assert "MARTIN Marie Josèphe" in texte
    assert "nom d'épouse probable" in texte or "nom d&#39;épouse probable" in texte


def test_fiche_d_un_menage(client: TestClient) -> None:
    resultats = client.get("/recherche", params={"q": "MARTIN Pierre", "source": "socface"})
    lien = _liens_fiches(resultats.text)[0]
    fiche = client.get(lien)
    assert fiche.status_code == 200
    texte = _texte(fiche.text)
    assert "Recensement 1906 à Quimper (29)" in texte
    assert "Personnes citées (3)" in texte
    # dans l'ordre de la feuille de recensement
    assert texte.index("chef de ménage") < texte.index("épouse") < texte.index("enfant")
    assert "AD 29, 6 M 123, vue 45" in texte  # citation
    assert "← retour aux résultats" in texte


def test_fiche_introuvable(client: TestClient) -> None:
    assert client.get("/actes/inexistant").status_code == 404


def test_sans_base(tmp_path: Path) -> None:
    with TestClient(creer_application(tmp_path)) as c:
        assert "doudoumil index" in c.get("/").text
        reponse = c.get("/recherche", params={"q": "DUPONT"})
        assert reponse.status_code == 503
        assert c.get("/api/lieux", params={"q": "quimp"}).json() == []


# --- trouvailles ----------------------------------------------------------------------------


def _envoyer(client: TestClient, mention_id: str, action: str, **champs: str) -> int:
    donnees = {"action": action, "acte_id": "a1", "libelle": "LE GOFF Marie, décès 2020"}
    donnees.update(champs)
    return client.post(
        f"/trouvailles/{mention_id}", data=donnees, follow_redirects=False
    ).status_code


def test_favori_note_verdict(client: TestClient, racine: Path) -> None:
    requete = json.dumps(Requete.creer(nom="LE GOFF").vers_dict())
    assert _envoyer(client, "m1", "favori", requete=requete) == 303
    carnet = Carnet(racine / "perso" / "trouvailles.sqlite")
    assert carnet.lire("m1").favori  # type: ignore[union-attr]
    _envoyer(client, "m1", "note", note="vérifier l'acte de naissance")
    _envoyer(client, "m1", "oui", requete=requete)
    trouvaille = carnet.lire("m1")
    assert trouvaille is not None
    assert (trouvaille.favori, trouvaille.note, trouvaille.verdict) == (
        True,
        "vérifier l'acte de naissance",
        "oui",
    )
    assert trouvaille.requete == Requete.creer(nom="LE GOFF")
    _envoyer(client, "m1", "favori")  # bascule
    _envoyer(client, "m1", "effacer")
    trouvaille = carnet.lire("m1")
    assert trouvaille is not None and not trouvaille.favori and trouvaille.verdict is None
    assert "vérifier l&#39;acte de naissance" in client.get("/trouvailles").text
    _envoyer(client, "m1", "supprimer")
    assert carnet.lire("m1") is None


def test_action_inconnue(client: TestClient) -> None:
    assert _envoyer(client, "m1", "pirater") == 400


@pytest.mark.parametrize(
    ("retour", "attendu"),
    [
        ("/recherche?q=X", "/recherche?q=X"),
        ("//pirate.example", "/trouvailles"),
        ("https://x", "/trouvailles"),
    ],
)
def test_retour_local_seulement(client: TestClient, retour: str, attendu: str) -> None:
    reponse = client.post(
        "/trouvailles/m1",
        data={"action": "favori", "acte_id": "a1", "libelle": "x", "retour": retour},
        follow_redirects=False,
    )
    assert reponse.headers["location"] == attendu


def test_badges_dans_les_resultats(client: TestClient) -> None:
    page = client.get("/recherche", params={"q": "MOREAU Jean"})
    lien = _liens_fiches(page.text)[0]
    mention = re.search(r"mention=([0-9a-f]{32})", lien).group(1)  # type: ignore[union-attr]
    _envoyer(client, mention, "favori")
    page = client.get("/recherche", params={"q": "MOREAU Jean"})
    assert 'aria-pressed="true"' in page.text


# --- sécurité -------------------------------------------------------------------------------


def test_envoi_depuis_un_autre_site_refuse(client: TestClient) -> None:
    reponse = client.post(
        "/trouvailles/m1",
        data={"action": "favori", "acte_id": "a1", "libelle": "x"},
        headers={"Origin": "https://pirate.example"},
        follow_redirects=False,
    )
    assert reponse.status_code == 403


def test_hote_inconnu_refuse(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "pirate.example"}).status_code == 400


# --- exports et API -------------------------------------------------------------------------


def test_export_csv_des_resultats(client: TestClient) -> None:
    reponse = client.get("/recherche.csv", params={"q": "LE GOFF"})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/csv")
    assert reponse.text.startswith("﻿rang;confiance;probabilité;score;personne")
    lignes = reponse.text.strip().splitlines()
    assert len(lignes) > 2
    assert "LE GOFF" in lignes[1]


def test_export_csv_des_trouvailles(client: TestClient) -> None:
    _envoyer(client, "m1", "note", note="à voir")
    lignes = client.get("/trouvailles.csv").text.strip().splitlines()
    assert lignes[0].startswith("﻿notice;favori;verdict;note")
    assert "à voir" in lignes[1]


def test_api_recherche(client: TestClient) -> None:
    donnees = client.get(
        "/api/recherche", params={"q": "LE GOFF Marie", "naissance": "1931"}
    ).json()
    assert donnees["total"] >= 2
    premier = donnees["resultats"][0]
    assert premier["fiche"]["nom_brut"] == "LE GOFF"
    assert premier["libelle"] == "non calibré"
    assert {"phonétique", "noms proches"} <= set(premier["canaux"])
    assert donnees["facettes"]["sources"] == [["insee_deces", donnees["total"]]]
    erreur = client.get("/api/recherche", params={"q": "LE GOFF", "naissance": "xx"})
    assert erreur.status_code == 422
    assert "naissance" in erreur.json()["erreurs"]


def test_api_acte_et_lieux(client: TestClient) -> None:
    acte_id = client.get("/api/recherche", params={"q": "KERGOAT"}).json()["resultats"][0][
        "acte_id"
    ]
    acte = client.get(f"/api/actes/{acte_id}").json()
    assert acte["acte"]["type"] == "deces"
    assert acte["mentions"][0]["nom_brut"] == "KERGOAT"
    assert client.get("/api/actes/inexistant").status_code == 404
    assert client.get("/api/lieux", params={"q": "quimp"}).json() == [
        {"libelle": "Quimper (29)", "valeur": "Quimper (29)"}
    ]
    assert client.get("/api/openapi.json").status_code == 200


# --- base reconstruite et calibration par les verdicts ---------------------------------------


def test_base_reconstruite_rouverte(client: TestClient, racine: Path) -> None:
    assert client.get("/recherche", params={"q": "DUPONT"}).status_code == 200
    base = racine / "gold" / "recherche.duckdb"
    base.touch()  # comme après un « doudoumil index »
    assert client.get("/recherche", params={"q": "MOREAU"}).status_code == 200


def test_calibre_avec_les_verdicts(
    racine_commune: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    racine = tmp_path / "donnees"
    construire_racine(racine)
    with TestClient(creer_application(racine)) as client:
        page = client.get("/recherche", params={"q": "MOREAU Jean"})
        mention = re.search(r"mention=([0-9a-f]{32})", page.text).group(1)  # type: ignore[union-attr]
        requete = json.dumps(Requete.creer(nom="MOREAU", prenoms="Jean").vers_dict())
        _envoyer(client, mention, "oui", requete=requete)
    capsys.readouterr()
    assert main(["--donnees", str(racine), "calibre", "--cas", "6"]) == 0
    assert "6 synthétiques, 1 verdicts réels" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("adresse", "attendue"),
    [
        ("https://archives.example/vue/45", "https://archives.example/vue/45"),
        ("http://archives.example/v", "http://archives.example/v"),
        ("javascript:alert(1)", None),
        ("data:text/html,x", None),
        ("", None),
        (None, None),
    ],
)
def test_lien_d_image_sur(adresse: str | None, attendue: str | None) -> None:
    from doudoumil_search.api.application import lien_sur

    assert lien_sur(adresse) == attendue


@pytest.mark.parametrize("requete", ["{pas du json", "[1, 2]", '{"naissance": [1931]}'])
def test_requete_transmise_mal_formee_ignoree(
    client: TestClient, racine: Path, requete: str
) -> None:
    assert _envoyer(client, "m1", "oui", requete=requete) == 303
    trouvaille = Carnet(racine / "perso" / "trouvailles.sqlite").lire("m1")
    assert trouvaille is not None and trouvaille.verdict == "oui" and trouvaille.requete is None
