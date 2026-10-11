"""Tests de l'interface web : pages, filtres, fiches, trouvailles, exports, API et sécurité."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doudoumil_search.api.application import creer_application
from doudoumil_search.api.formulaire import Formulaire, FormulaireInvalide
from doudoumil_search.cli import main
from doudoumil_search.dossiers import Registre
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
    carnet = Registre(racine / "perso").actif()
    assert carnet.identifiant == "personnel"
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
    """Ancienne adresse : export du dossier actif."""
    _envoyer(client, "m1", "note", note="à voir")
    lignes = client.get("/trouvailles.csv").text.strip().splitlines()
    assert lignes[0].startswith("﻿personne recherchée;nature;notice;citation")
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
    # 6 cas par source : 6 décès, et les 3 personnes nommées du ménage recensé
    assert "9 synthétiques, 1 verdicts réels" in capsys.readouterr().out


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
    trouvaille = Registre(racine / "perso").actif().lire("m1")
    assert trouvaille is not None and trouvaille.verdict == "oui" and trouvaille.requete is None


# --- dossiers de recherche ------------------------------------------------------------------


def _creer_dossier(client: TestClient, nom: str = "Famille Le Goff") -> str:
    reponse = client.post(
        "/dossiers", data={"nom": nom, "client": "M. Martin"}, follow_redirects=False
    )
    assert reponse.status_code == 303
    return reponse.headers["location"].removeprefix("/dossiers/")


def test_liste_et_creation_de_dossiers(client: TestClient) -> None:
    assert "Personnel" in client.get("/dossiers").text
    identifiant = _creer_dossier(client)
    assert identifiant == "famille-le-goff"
    page = client.get("/dossiers").text
    assert "Famille Le Goff" in page and "M. Martin" in page
    # le nouveau dossier devient le dossier actif, affiché dans l'en-tête
    assert "Dossier : Famille Le Goff" in client.get("/").text
    assert client.get("/trouvailles", follow_redirects=False).headers["location"] == (
        "/dossiers/famille-le-goff"
    )
    reponse = client.post("/dossiers/personnel/activer", data={"retour": "/dossiers"})
    assert "Dossier : Personnel" in reponse.text


@pytest.mark.parametrize(
    ("nom", "message"), [("", "au moins une lettre"), ("Personnel", "existe déjà")]
)
def test_creation_de_dossier_refusee(client: TestClient, nom: str, message: str) -> None:
    client.get("/dossiers")  # crée « Personnel »
    reponse = client.post("/dossiers", data={"nom": nom})
    assert reponse.status_code == 422
    assert message in reponse.text


def test_recherche_depuis_une_personne_et_rattachement(client: TestClient, racine: Path) -> None:
    client.get("/dossiers")  # crée « Personnel »
    identifiant = _creer_dossier(client)
    reponse = client.post(
        f"/dossiers/{identifiant}/personnes",
        data={"nom": "MOREAU", "prenoms": "Jean", "naissance": "1925", "sexe": "M"},
        follow_redirects=False,
    )
    assert reponse.headers["location"] == f"/dossiers/{identifiant}#p-1"
    page = client.get(f"/dossiers/{identifiant}").text
    adresse = re.search(r'href="(/recherche\?[^"]+)"', page).group(1).replace("&amp;", "&")  # type: ignore[union-attr]
    assert "personne=famille-le-goff%3A1" in adresse

    # le dossier actif change entre-temps : la notice va quand même à la personne visée
    client.post("/dossiers/personnel/activer")
    resultats = client.get(adresse).text
    assert "Recherche pour" in _texte(resultats) and "MOREAU Jean" in _texte(resultats)
    assert '<input type="hidden" name="dossier" value="famille-le-goff">' in resultats
    assert '<input type="hidden" name="personne" value="1">' in resultats
    lien = _liens_fiches(resultats)[0]
    assert "personne=famille-le-goff%3A1" in lien
    mention = re.search(r"mention=([0-9a-f]{32})", lien).group(1)  # type: ignore[union-attr]
    _envoyer(client, mention, "favori", dossier="famille-le-goff", personne="1")

    registre = Registre(racine / "perso")
    famille = registre.ouvrir("famille-le-goff")
    assert [(t.mention_id, t.personne_id) for t in famille.toutes()] == [(mention, 1)]
    assert registre.ouvrir("personnel").toutes() == []
    # la fiche ouverte depuis ces résultats range aussi dans le bon dossier
    fiche = client.get(lien).text
    assert "Notices retenues rangées pour" in _texte(fiche)
    # sur la page du dossier, la notice est sous la personne, pas parmi les non rattachées
    page = _texte(client.get(f"/dossiers/{identifiant}").text)
    assert "Notices non rattachées" not in page
    assert "MOREAU JEAN" in page.split("MOREAU Jean", 1)[1].upper()


def test_personne_inconnue_ignoree(client: TestClient, racine: Path) -> None:
    _creer_dossier(client)
    _envoyer(client, "m1", "favori", dossier="famille-le-goff", personne="42")
    assert Registre(racine / "perso").ouvrir("famille-le-goff").lire("m1").personne_id is None  # type: ignore[union-attr]
    assert (
        "Recherche pour"
        not in client.get("/recherche", params={"q": "MOREAU", "personne": "x:1"}).text
    )


def test_modifier_et_supprimer_une_personne(client: TestClient, racine: Path) -> None:
    identifiant = _creer_dossier(client)
    client.post(f"/dossiers/{identifiant}/personnes", data={"nom": "LE GOFF", "prenoms": "Marie"})
    reponse = client.post(f"/dossiers/{identifiant}/personnes", data={"lieu": "Brest"})
    assert reponse.status_code == 422 and "au moins un nom" in reponse.text
    client.post(
        f"/dossiers/{identifiant}/personnes/1",
        data={"action": "modifier", "nom": "LE GOFF", "prenoms": "Marie", "conjoint": "MARTIN"},
    )
    dossier = Registre(racine / "perso").ouvrir(identifiant)
    assert dossier.personne(1).conjoint == "MARTIN"  # type: ignore[union-attr]
    reponse = client.post(
        f"/dossiers/{identifiant}/personnes/1", data={"action": "modifier", "sexe": "X"}
    )
    assert reponse.status_code == 422
    client.post(f"/dossiers/{identifiant}/personnes/1", data={"action": "supprimer"})
    assert dossier.personnes() == []


def test_notice_saisie_rattachement_et_export(client: TestClient, racine: Path) -> None:
    identifiant = _creer_dossier(client)
    client.post(f"/dossiers/{identifiant}/personnes", data={"nom": "LE GOFF", "prenoms": "Marie"})
    reponse = client.post(
        f"/dossiers/{identifiant}/notices",
        data={
            "type": "bapteme",
            "date": "02/03/1755",
            "lieu": "Plougastel-Daoulas (29)",
            "personnes": "LE GOFF Marie",
            "depot": "AD 29",
            "cote": "3 E 158/2",
            "vue": "12",
            "site": "Filae",
            "personne": "",
        },
        follow_redirects=False,
    )
    assert reponse.status_code == 303
    dossier = Registre(racine / "perso").ouvrir(identifiant)
    (notice,) = dossier.notices()
    assert notice.personne_id is None
    client.post(
        f"/dossiers/{identifiant}/notices/{notice.notice_id}",
        data={"action": "rattacher", "personne": "1"},
    )
    assert dossier.notice(notice.notice_id).personne_id == 1  # type: ignore[union-attr]
    _envoyer(client, "m1", "note", note="à vérifier", dossier=identifiant)
    client.post(f"/dossiers/{identifiant}/trouvailles/m1", data={"personne": "1"})
    assert dossier.lire("m1").personne_id == 1  # type: ignore[union-attr]

    page = _texte(client.get(f"/dossiers/{identifiant}").text)
    assert (
        "LE GOFF Marie, baptême le 02/03/1755 à Plougastel-Daoulas (29). AD 29, 3 E 158/2, vue 12."
        in page
    )
    assert "repérée sur Filae" in page
    tableau = client.get(f"/dossiers/{identifiant}.csv")
    assert tableau.headers["content-disposition"] == 'attachment; filename="famille-le-goff.csv"'
    assert "notice saisie" in tableau.text and "à vérifier" in tableau.text

    assert (
        client.post(f"/dossiers/{identifiant}/notices", data={"type": "deces"}).status_code == 422
    )
    assert (
        client.post(
            f"/dossiers/{identifiant}/notices/{notice.notice_id}", data={"action": "pirater"}
        ).status_code
        == 400
    )
    client.post(f"/dossiers/{identifiant}/notices/{notice.notice_id}", data={"action": "supprimer"})
    assert dossier.notices() == []


def test_clore_rouvrir_et_renommer(client: TestClient, racine: Path) -> None:
    identifiant = _creer_dossier(client)
    client.post(f"/dossiers/{identifiant}/infos", data={"action": "clore"})
    dossier = Registre(racine / "perso").ouvrir(identifiant)
    assert dossier.infos().clos_le
    assert "clos le" in client.get("/dossiers").text
    client.post(f"/dossiers/{identifiant}/infos", data={"action": "rouvrir"})
    assert not dossier.infos().clos_le
    client.post(
        f"/dossiers/{identifiant}/infos", data={"nom": "Le Goff (Bretagne)", "client": "Mme Martin"}
    )
    assert dossier.infos().nom == "Le Goff (Bretagne)"
    assert dossier.identifiant == identifiant  # le fichier garde son nom
    assert client.post(f"/dossiers/{identifiant}/infos", data={"nom": " "}).status_code == 422


def test_suppression_d_un_dossier(client: TestClient, racine: Path) -> None:
    identifiant = _creer_dossier(client)
    reponse = client.post(f"/dossiers/{identifiant}/supprimer", data={"confirmation": "oui"})
    assert reponse.status_code == 422 and "pour confirmer" in reponse.text
    assert Registre(racine / "perso").existe(identifiant)
    reponse = client.post(
        f"/dossiers/{identifiant}/supprimer",
        data={"confirmation": identifiant},
        follow_redirects=False,
    )
    assert reponse.headers["location"] == "/dossiers"
    assert not Registre(racine / "perso").existe(identifiant)
    assert "Dossier : Personnel" in client.get("/").text


@pytest.mark.parametrize("adresse", ["/dossiers/inconnu", "/dossiers/..%2Fperso", "/dossiers/A-B"])
def test_dossier_inconnu(client: TestClient, adresse: str) -> None:
    assert client.get(adresse).status_code == 404
    assert client.post(f"{adresse}/activer").status_code == 404
    assert client.get(f"{adresse}.csv").status_code == 404
    assert _envoyer(client, "m1", "favori", dossier=adresse.rsplit("/", 1)[-1]) == 404
