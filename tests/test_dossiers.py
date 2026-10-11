"""Tests des dossiers de recherche : un fichier SQLite par dossier."""

from datetime import date
from pathlib import Path

import pytest

from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.dossiers import (
    ENTETE_EXPORT,
    DossierExistant,
    DossierInconnu,
    Registre,
    identifiant_de,
    lignes_export,
    personne_visee,
)
from doudoumil_search.search.affichage import citation_saisie
from doudoumil_search.search.requete import Requete

CONSULTE = date(2026, 10, 11)


@pytest.fixture
def registre(tmp_path: Path) -> Registre:
    return Registre(tmp_path / "perso")


@pytest.mark.parametrize(
    ("nom", "identifiant"),
    [
        ("Famille Le Goff", "famille-le-goff"),
        ("  Dupont & Fils — 2026 ", "dupont-fils-2026"),
        ("Hélène Bézier", "helene-bezier"),
    ],
)
def test_identifiant(nom: str, identifiant: str) -> None:
    assert identifiant_de(nom) == identifiant


def test_identifiant_vide() -> None:
    with pytest.raises(ValueError, match="au moins une lettre"):
        identifiant_de(" — ")


def test_creation_et_dossier_actif(registre: Registre) -> None:
    assert registre.identifiants() == []
    # sans aucun dossier, le dossier actif « Personnel » est créé
    assert registre.actif().identifiant == "personnel"
    client = registre.creer("Famille Le Goff", client="M. Martin", description="branche bretonne")
    infos = client.infos()
    assert (infos.identifiant, infos.nom, infos.client) == (
        "famille-le-goff",
        "Famille Le Goff",
        "M. Martin",
    )
    assert infos.ouvert_le and not infos.clos_le
    assert (registre.dossier / "famille-le-goff.sqlite").exists()
    assert registre.actif().identifiant == "personnel"  # créer n'active pas
    registre.activer("famille-le-goff")
    assert registre.actif().identifiant == "famille-le-goff"
    with pytest.raises(DossierExistant):
        registre.creer("famille le goff")
    with pytest.raises(DossierInconnu):
        registre.activer("inconnu")


@pytest.mark.parametrize("identifiant", ["../evasion", "a/b", "MAJ", ""])
def test_identifiant_refuse(registre: Registre, identifiant: str) -> None:
    with pytest.raises(DossierInconnu):
        registre.ouvrir(identifiant)


def test_modifier_infos(registre: Registre) -> None:
    dossier = registre.creer("Client A")
    dossier.modifier_infos(description="mission close", clos_le="2026-12-01")
    assert dossier.infos().clos_le == "2026-12-01"
    with pytest.raises(ValueError, match="information inconnue"):
        dossier.modifier_infos(couleur="bleu")


def test_reprise_de_l_ancien_carnet(tmp_path: Path) -> None:
    perso = tmp_path / "perso"
    Carnet(perso / "trouvailles.sqlite").enregistrer("m1", "a1", "LE GOFF Marie", note="gardée")
    registre = Registre(perso)
    assert not (perso / "trouvailles.sqlite").exists()
    personnel = registre.actif()
    assert personnel.identifiant == "personnel"
    assert personnel.infos().nom == "Personnel"
    assert personnel.lire("m1").note == "gardée"  # type: ignore[union-attr]
    # une sauvegarde ancienne restaurée plus tard : reprise à côté, sans écraser
    Carnet(perso / "trouvailles.sqlite").enregistrer("m2", "a2", "x")
    Registre(perso)
    assert registre.identifiants() == ["personnel", "personnel-2"]
    assert registre.ouvrir("personnel-2").infos().nom == "Personnel (2)"


def test_personnes_recherchees(registre: Registre) -> None:
    dossier = registre.creer("Client")
    marie = dossier.ajouter_personne(
        nom="LE GOFF", prenoms="Marie", sexe="F", naissance="1930-1932", lieu="Quimper (29)"
    )
    assert marie.libelle == "LE GOFF Marie"
    assert marie.parametres_recherche("client") == {
        "nom": "LE GOFF",
        "prenoms": "Marie",
        "sexe": "F",
        "naissance": "1930-1932",
        "lieu": "Quimper (29)",
        "personne": f"client:{marie.personne_id}",
    }
    assert personne_visee(registre, f"client:{marie.personne_id}") is not None
    for valeur in ("client:999", "inconnu:1", "client", "client:x", "../x:1"):
        assert personne_visee(registre, valeur) is None
    dossier.modifier_personne(marie.personne_id, conjoint="MARTIN", note="veuve en 1960")
    assert dossier.personne(marie.personne_id).conjoint == "MARTIN"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="au moins un nom"):
        dossier.ajouter_personne(lieu="Brest")
    with pytest.raises(ValueError, match="sexe"):
        dossier.ajouter_personne(nom="X", sexe="H")
    with pytest.raises(ValueError, match="champ inconnu"):
        dossier.ajouter_personne(nom="X", age="40")
    with pytest.raises(LookupError):
        dossier.modifier_personne(999, nom="Y")


def test_trouvailles_rattachees_puis_personne_supprimee(registre: Registre) -> None:
    dossier = registre.creer("Client")
    marie = dossier.ajouter_personne(nom="LE GOFF", prenoms="Marie")
    dossier.enregistrer("m1", "a1", "LE GOFF Marie", favori=True, personne_id=marie.personne_id)
    dossier.enregistrer("m2", "a2", "LE GOFF Jean", favori=True)
    dossier.rattacher("m2", marie.personne_id)
    notice = dossier.ajouter_notice(
        personne_id=marie.personne_id, type="bapteme", personnes="LE GOFF Marie", date="1755"
    )
    assert {t.personne_id for t in dossier.toutes()} == {marie.personne_id}
    dossier.supprimer_personne(marie.personne_id)
    assert dossier.personnes() == []
    # les notices restent, sans rattachement
    assert {t.personne_id for t in dossier.toutes()} == {None}
    assert dossier.notice(notice.notice_id).personne_id is None  # type: ignore[union-attr]


def test_notices_saisies(registre: Registre) -> None:
    dossier = registre.creer("Client")
    notice = dossier.ajouter_notice(
        type="bapteme",
        date="02/03/1755",
        lieu="Plougastel-Daoulas (29)",
        personnes="LE GOFF Marie Josèphe, fille d'Yves et d'Anne KERGOAT",
        depot="AD 29",
        cote="3 E 158/2",
        vue="12",
        lien="https://archives.example/vue/12",
        site="Filae",
    )
    assert dossier.notices() == [notice]
    assert citation_saisie(notice, CONSULTE) == (
        "LE GOFF Marie Josèphe, fille d'Yves et d'Anne KERGOAT, baptême le 02/03/1755 à "
        "Plougastel-Daoulas (29). AD 29, 3 E 158/2, vue 12, https://archives.example/vue/12. "
        "Consulté le 11/10/2026."
    )
    dossier.supprimer_notice(notice.notice_id)
    assert dossier.notices() == []
    with pytest.raises(ValueError, match="type d'acte inconnu"):
        dossier.ajouter_notice(type="divorce", personnes="X")
    with pytest.raises(ValueError, match="au moins les personnes"):
        dossier.ajouter_notice(type="deces", lieu="Brest")
    with pytest.raises(LookupError):
        dossier.ajouter_notice(personne_id=42, personnes="X")


def test_citation_sans_cote_cite_le_site(registre: Registre) -> None:
    notice = registre.creer("Client").ajouter_notice(
        type="mariage", date="1880", personnes="MARTIN Jean et LE GOFF Anne", site="Geneanet"
    )
    assert citation_saisie(notice, CONSULTE) == (
        "MARTIN Jean et LE GOFF Anne, mariage 1880. index Geneanet. Consulté le 11/10/2026."
    )


def test_copie_d_une_notice_dans_deux_dossiers(registre: Registre) -> None:
    a, b = registre.creer("Famille A"), registre.creer("Famille B")
    a.enregistrer("m1", "a1", "LE GOFF Marie", favori=True)
    b.enregistrer("m1", "a1", "LE GOFF Marie", note="cousine de la famille B")
    registre.supprimer("famille-a")
    assert b.lire("m1").note == "cousine de la famille B"  # type: ignore[union-attr]


def test_suppression_complete(registre: Registre) -> None:
    dossier = registre.creer("Client sensible")
    dossier.ajouter_personne(nom="DUPONT", prenoms="Paul")
    registre.activer("client-sensible")
    registre.supprimer("client-sensible")
    assert not list(registre.dossier.glob("client-sensible*"))
    assert registre.actif().identifiant == "personnel"  # plus de dossier actif désigné
    with pytest.raises(DossierInconnu):
        registre.supprimer("client-sensible")


def test_export_et_import(registre: Registre, tmp_path: Path) -> None:
    dossier = registre.creer("Famille Le Goff")
    dossier.ajouter_personne(nom="LE GOFF", prenoms="Marie")
    copie = registre.exporter("famille-le-goff", tmp_path / "cle-usb")
    assert copie.name == "famille-le-goff.sqlite"
    with pytest.raises(FileExistsError):
        registre.exporter("famille-le-goff", tmp_path / "cle-usb")
    with pytest.raises(DossierExistant):
        registre.importer(copie)
    autre = Registre(tmp_path / "autre-ordinateur")
    importe = autre.importer(copie)
    assert importe.infos().nom == "Famille Le Goff"
    assert [p.libelle for p in importe.personnes()] == ["LE GOFF Marie"]


def test_import_d_un_fichier_quelconque(registre: Registre, tmp_path: Path) -> None:
    faux = tmp_path / "photo.sqlite"
    faux.write_bytes(b"pas une base")
    with pytest.raises(ValueError, match="pas un dossier"):
        registre.importer(faux)
    carnet_seul = tmp_path / "carnet.sqlite"
    Carnet(carnet_seul)
    with pytest.raises(ValueError, match="pas un dossier de recherche"):
        registre.importer(carnet_seul)


def test_verdicts_de_tous_les_dossiers(registre: Registre) -> None:
    requete = Requete.creer(nom="LE GOFF", prenoms="Marie")
    registre.creer("A").enregistrer("m1", "a1", "x", requete=requete, verdict="oui")
    registre.creer("B").enregistrer("m2", "a2", "y", requete=requete, verdict="non")
    assert sorted(t.mention_id for t in registre.verdicts()) == ["m1", "m2"]


def test_lignes_export(registre: Registre) -> None:
    dossier = registre.creer("Client")
    marie = dossier.ajouter_personne(nom="LE GOFF", prenoms="Marie")
    jean = dossier.ajouter_personne(nom="LE GOFF", prenoms="Jean")
    dossier.enregistrer(
        "m1", "a1", "LE GOFF Marie, décès", source="insee_deces", favori=True, verdict="oui"
    )
    dossier.rattacher("m1", marie.personne_id)
    dossier.ajouter_notice(type="bapteme", personnes="LE GOFF Marie", date="1931", site="Filae")
    dossier.enregistrer("m9", "a9", "inconnu non rattaché", note="à revoir")
    lignes = lignes_export(dossier, citations={"m1": "citation m1"}, consulte_le=CONSULTE)
    assert all(len(ligne) == len(ENTETE_EXPORT) for ligne in lignes)
    resume = [(ligne[0], ligne[1], ligne[3]) for ligne in lignes]
    assert resume == [
        ("LE GOFF Jean", "personne recherchée", ""),  # tri par nom : Jean avant Marie
        ("LE GOFF Marie", "notice de l'atelier", "citation m1"),
        ("", "notice de l'atelier", ""),
        ("", "notice saisie", "LE GOFF Marie, baptême 1931. index Filae. Consulté le 11/10/2026."),
    ]
    assert lignes[1][4] == "Fichier des personnes décédées (INSEE)"
    assert jean.libelle == "LE GOFF Jean"


# --- ligne de commande ---------------------------------------------------------------------


def test_commandes_dossier(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from doudoumil_search.cli import main

    donnees = ["--donnees", str(tmp_path)]
    assert main([*donnees, "dossier", "cree", "Famille Le Goff", "--client", "M. Martin"]) == 0
    assert "créé et activé (famille-le-goff)" in capsys.readouterr().out
    assert main([*donnees, "dossier", "cree", "famille le goff"]) == 1  # existe déjà
    Registre(tmp_path / "perso").ouvrir("famille-le-goff").ajouter_personne(nom="LE GOFF")
    assert main([*donnees, "dossier", "liste"]) == 0
    sortie = capsys.readouterr().out
    assert "* famille-le-goff — Famille Le Goff (M. Martin) : 1 personne, 0 notice" in sortie
    assert main([*donnees, "dossier", "active", "Personnel"]) == 1  # pas encore créé
    assert main([*donnees, "dossier", "cree", "Personnel"]) == 0
    assert main([*donnees, "dossier", "active", "famille-le-goff"]) == 0

    assert (
        main([*donnees, "dossier", "exporte", "famille-le-goff", "--vers", str(tmp_path / "x")])
        == 0
    )
    (export,) = (tmp_path / "x").iterdir()
    assert sorted(f.name for f in export.iterdir()) == [
        "famille-le-goff.csv",
        "famille-le-goff.sqlite",
    ]
    tableau = (export / "famille-le-goff.csv").read_text(encoding="utf-8-sig")
    assert tableau.splitlines()[1].startswith("LE GOFF;personne recherchée")

    # suppression : confirmation exigée
    monkeypatch.setattr("builtins.input", lambda _: "non")
    assert main([*donnees, "dossier", "supprime", "famille-le-goff"]) == 1
    monkeypatch.setattr("builtins.input", lambda _: "famille-le-goff")
    assert main([*donnees, "dossier", "supprime", "famille-le-goff"]) == 0
    assert main([*donnees, "dossier", "importe", str(export / "famille-le-goff.sqlite")]) == 0
    assert main([*donnees, "dossier", "supprime", "famille-le-goff", "--oui"]) == 0
    assert Registre(tmp_path / "perso").identifiants() == ["personnel"]
