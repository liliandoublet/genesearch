"""Tests du connecteur de relevés (CSV ou Excel + fichier de correspondance)."""

import html
import re
import shutil
import tomllib
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter
from fastapi.testclient import TestClient

from doudoumil_search.api.application import creer_application
from doudoumil_search.cli import main
from doudoumil_search.ingest.releves import (
    CorrespondanceInvalide,
    ingerer_releve,
    lire_annee,
    lire_correspondance,
    lire_date,
    lire_enumeration,
    modele_correspondance,
)
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.normalize.silver import construire_silver
from doudoumil_search.pivot import Acte, Mention, Sexe, TypeActe
from doudoumil_search.search.affichage import citation
from doudoumil_search.search.evaluation import tirer_notices
from doudoumil_search.search.gold import chemin_base, construire_gold
from doudoumil_search.search.moteur import Moteur
from doudoumil_search.search.requete import Requete
from jeu_recherche import construire_racine

FIXTURES = Path(__file__).parent / "fixtures"
RELEVE = FIXTURES / "releves" / "landerneau-bms.toml"
INGESTION = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

CORRESPONDANCE_MINIMALE = """
[releve]
titre = "Essai"
fichier = "essai.csv"

[acte]
type = "bapteme"
date = { colonne = "Date" }

[[personne]]
role = "sujet"
nom = { colonne = "Nom" }
prenoms = { colonne = "Prénoms" }
"""


def ecrire(dossier: Path, csv: str, toml: str = CORRESPONDANCE_MINIMALE) -> Path:
    (dossier / "essai.csv").write_text(csv, encoding="utf-8")
    chemin = dossier / "essai.toml"
    chemin.write_text(toml, encoding="utf-8")
    return chemin


def lire(dossier: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    return (
        pl.read_parquet(dossier / "actes-*.parquet"),
        pl.read_parquet(dossier / "mentions-*.parquet"),
    )


@pytest.fixture
def ingere(tmp_path: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    rapport = ingerer_releve(RELEVE, tmp_path / "bronze", INGESTION)
    assert rapport.dossier == tmp_path / "bronze" / "releve" / "landerneau-bms"
    return lire(rapport.dossier)


def test_rapport(tmp_path: Path) -> None:
    rapport = ingerer_releve(RELEVE, tmp_path, INGESTION)
    assert (rapport.lignes_lues, rapport.lignes_ingerees, rapport.lignes_rejetees) == (10, 7, 3)
    assert rapport.anomalies == {
        "date de l'acte incomplète": 1,
        "sexe inconnu": 1,
        "clé en double (numéro d'ordre ajouté)": 1,
        "âge illisible": 1,
    }
    rejets = pl.read_csv(rapport.dossier / "rejets.csv")
    assert rejets["numero_ligne"].to_list() == [8, 9, 10]
    assert rejets["motif"].to_list() == [
        "type d'acte inconnu (X)",
        "année de l'acte illisible",
        "personne n'est nommé",
    ]


def test_actes(ingere: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    actes, _ = ingere
    premier = actes.row(0, named=True)
    assert premier["source"] == "releve"
    assert premier["type"] == "bapteme"
    assert premier["date_acte"] == date(1755, 3, 2)
    assert premier["titre_source"].startswith("Baptêmes et sépultures de Landerneau")
    assert (premier["commune_label"], premier["departement"], premier["depot"]) == (
        "Landerneau",
        "29",
        "AD 29",
    )
    assert (premier["cote"], premier["vue"]) == ("3 E 103/2", "12")
    # « ../11/1760 » : date incomplète, mais année lisible
    incomplet = actes.filter(pl.col("cote") == "3 E 103/3").row(0, named=True)
    assert (incomplet["type"], incomplet["annee"], incomplet["date_acte"]) == ("deces", 1760, None)
    assert actes["acte_id"].n_unique() == actes.height == 7


def test_mentions(ingere: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    actes, mentions = ingere
    assert mentions.height == 16
    assert mentions["confiance_source"].to_list() == pytest.approx([0.95] * 16)
    bapteme = mentions.filter(pl.col("acte_id") == actes["acte_id"][0])
    assert bapteme.select("role", "nom_brut", "prenoms_bruts", "sexe", "nature_nom").rows() == [
        ("sujet", "LE GOFF", "Marie Josèphe", "F", None),
        ("pere", "LE GOFF", "Yves", "M", None),  # sexe déduit du rôle
        ("mere", "KERGOAT", "Anne", "F", "naissance"),
    ]
    # sépulture sans père : le nom de l'enfant ne suffit pas à créer un père
    quemener = mentions.filter(pl.col("nom_brut") == "QUEMENER")
    assert quemener.select("role", "age").rows() == [("sujet", 40)]
    assert mentions.filter(pl.col("age") == 0).height == 1  # « 6 mois »
    assert mentions.filter(pl.col("nom_brut") == "MORVAN")["age"].to_list() == [None]
    # « G » pour garçon ; « ? » laissé vide
    assert mentions.filter(pl.col("role") == "sujet")["sexe"].null_count() == 2


def test_conforme_au_modele_pivot(ingere: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    actes, mentions = ingere
    for ligne in actes.iter_rows(named=True):
        Acte(**{k: v for k, v in ligne.items() if v is not None})
    for ligne in mentions.iter_rows(named=True):
        Mention(**{k: v for k, v in ligne.items() if v is not None})


def test_reingestion_idempotente(tmp_path: Path) -> None:
    premier = lire(ingerer_releve(RELEVE, tmp_path / "a", INGESTION).dossier)
    second = lire(ingerer_releve(RELEVE, tmp_path / "b", datetime.now(UTC)).dossier)
    for avant, apres in zip(premier, second, strict=True):
        assert avant.drop("ingested_at", strict=False).equals(
            apres.drop("ingested_at", strict=False)
        )


def test_cle_independante_de_l_ordre_des_lignes(tmp_path: Path) -> None:
    toml = CORRESPONDANCE_MINIMALE.replace(
        'fichier = "essai.csv"', 'fichier = "essai.csv"\ncle = ["Date", "Nom"]'
    )
    lignes = ["02/03/1755;LE GOFF;Marie", "15/07/1756;MORVAN;Jean"]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = ecrire(tmp_path / "a", "Date;Nom;Prénoms\n" + "\n".join(lignes), toml)
    b = ecrire(tmp_path / "b", "Date;Nom;Prénoms\n" + "\n".join(reversed(lignes)), toml)
    ids_a = lire(ingerer_releve(a, tmp_path / "bronze-a", INGESTION).dossier)[1]
    ids_b = lire(ingerer_releve(b, tmp_path / "bronze-b", INGESTION).dossier)[1]
    assert set(ids_a["mention_id"]) == set(ids_b["mention_id"])


def test_sans_cle_le_numero_de_ligne_identifie(tmp_path: Path) -> None:
    chemin = ecrire(
        tmp_path, "Date;Nom;Prénoms\n02/03/1755;LE GOFF;Marie\n02/03/1755;LE GOFF;Marie\n"
    )
    rapport = ingerer_releve(chemin, tmp_path / "bronze", INGESTION)
    assert rapport.lignes_ingerees == 2
    assert not rapport.anomalies
    assert lire(rapport.dossier)[0]["acte_id"].n_unique() == 2


def test_csv_windows_et_virgules(tmp_path: Path) -> None:
    """CSV enregistré par Excel sous Windows : Windows-1252, virgules, champs entre guillemets."""
    texte = 'Date,Nom,Prénoms\n1755-03-02,"LE GOFF","Marie Josèphe"\n'
    (tmp_path / "essai.csv").write_bytes(texte.encode("cp1252"))
    (tmp_path / "essai.toml").write_text(CORRESPONDANCE_MINIMALE, encoding="utf-8")
    rapport = ingerer_releve(tmp_path / "essai.toml", tmp_path / "bronze", INGESTION)
    actes, mentions = lire(rapport.dossier)
    assert mentions["prenoms_bruts"].to_list() == ["Marie Josèphe"]
    assert actes["date_acte"].to_list() == [date(1755, 3, 2)]


def test_encodage_impose_invalide(tmp_path: Path) -> None:
    toml = CORRESPONDANCE_MINIMALE.replace(
        'fichier = "essai.csv"', 'fichier = "essai.csv"\nencodage = "utf-8"'
    )
    (tmp_path / "essai.csv").write_bytes("Date;Nom;Prénoms\n".encode("cp1252"))
    (tmp_path / "essai.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(CorrespondanceInvalide, match="lecture en utf-8 impossible"):
        ingerer_releve(tmp_path / "essai.toml", tmp_path / "bronze")


def test_excel(tmp_path: Path) -> None:
    """Classeur avec une ligne de titre avant l'en-tête, dates et nombres Excel."""
    classeur = xlsxwriter.Workbook(tmp_path / "bms.xlsx")
    classeur.add_worksheet("Notes")
    feuille = classeur.add_worksheet("Baptêmes")
    format_date = classeur.add_format({"num_format": "dd/mm/yyyy"})
    feuille.write_row(0, 0, ["Baptêmes de Landerneau, relevé du cercle"])
    feuille.write_row(1, 0, [" Date ", "NOM", "prenoms", "Vue", "Âge"])
    feuille.write_datetime(2, 0, datetime(1755, 3, 2), format_date)
    feuille.write_row(2, 1, ["LE GOFF", "Marie"])
    feuille.write_number(2, 3, 12)
    feuille.write_number(2, 4, 40)
    classeur.close()
    toml = """
        [releve]
        titre = "Baptêmes de Landerneau"
        fichier = "bms.xlsx"
        feuille = "Baptêmes"
        entete = 2

        [acte]
        type = "Baptême"
        date = { colonne = "Date", format = "%d/%m/%Y" }
        vue = { colonne = "Vue" }

        [[personne]]
        role = "sujet"
        nom = { colonne = "Nom" }
        prenoms = { colonne = "Prénoms" }
        age = { colonne = "Âge" }
    """
    (tmp_path / "bms.toml").write_text(toml, encoding="utf-8")
    rapport = ingerer_releve(tmp_path / "bms.toml", tmp_path / "bronze", INGESTION)
    actes, mentions = lire(rapport.dossier)
    assert actes.select("type", "date_acte", "vue").rows() == [("bapteme", date(1755, 3, 2), "12")]
    assert mentions.select("nom_brut", "prenoms_bruts", "age").rows() == [("LE GOFF", "Marie", 40)]


def test_feuille_absente(tmp_path: Path) -> None:
    classeur = xlsxwriter.Workbook(tmp_path / "bms.xlsx")
    classeur.add_worksheet("Feuil1")
    classeur.close()
    toml = CORRESPONDANCE_MINIMALE.replace('"essai.csv"', '"bms.xlsx"\nfeuille = "Baptêmes"')
    (tmp_path / "bms.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(CorrespondanceInvalide, match=r"feuille « Baptêmes » absente.*Feuil1"):
        ingerer_releve(tmp_path / "bms.toml", tmp_path / "bronze")


def test_colonnes_absentes(tmp_path: Path) -> None:
    chemin = ecrire(tmp_path, "Date;Nom de famille;Prénom\n02/03/1755;LE GOFF;Marie\n")
    with pytest.raises(CorrespondanceInvalide) as erreur:
        ingerer_releve(chemin, tmp_path / "bronze")
    message = str(erreur.value)
    assert "colonnes absentes de essai.csv : « Nom », « Prénoms »" in message
    assert "« Nom de famille », « Prénom »" in message
    assert not (tmp_path / "bronze" / "releve" / "essai").exists()


@pytest.mark.parametrize(
    ("remplacement", "message"),
    [
        (('role = "sujet"', 'role = "sujet"\nprenom = "Marie"'), "clé inconnue prenom"),
        (('type = "bapteme"', 'type = "baptism"'), "« baptism » inconnu"),
        (('role = "sujet"', 'role = "parrain"'), "« role » manquant ou inconnu"),
        (('date = { colonne = "Date" }', ""), "« date » ou « annee »"),
        (('titre = "Essai"', 'titre = "Essai"\nconfiance = 2'), "entre 0 et 1"),
        (('{ colonne = "Date" }', '{ col = "Date" }'), "clé inconnue col"),
        (('titre = "Essai"', "titre = "), "TOML invalide"),
    ],
)
def test_correspondance_invalide(
    tmp_path: Path, remplacement: tuple[str, str], message: str
) -> None:
    chemin = tmp_path / "essai.toml"
    chemin.write_text(CORRESPONDANCE_MINIMALE.replace(*remplacement), encoding="utf-8")
    with pytest.raises(CorrespondanceInvalide, match=message):
        lire_correspondance(chemin)


def test_tableur_introuvable(tmp_path: Path) -> None:
    chemin = tmp_path / "essai.toml"
    chemin.write_text(CORRESPONDANCE_MINIMALE, encoding="utf-8")
    with pytest.raises(CorrespondanceInvalide, match="tableur introuvable"):
        ingerer_releve(chemin, tmp_path / "bronze")


@pytest.mark.parametrize(
    ("brute", "format_", "attendue"),
    [
        ("02/03/1755", None, date(1755, 3, 2)),
        ("1755-03-02", None, date(1755, 3, 2)),
        ("1755-03-02 00:00:00", "%d/%m/%Y", date(1755, 3, 2)),  # cellule date d'Excel
        ("2 mars 1755", None, None),
        ("03/02/1755", "%m/%d/%Y", date(1755, 3, 2)),
        ("../03/1755", None, None),
        (None, None, None),
    ],
)
def test_lire_date(brute: str | None, format_: str | None, attendue: date | None) -> None:
    assert lire_date(brute, format_) == attendue


@pytest.mark.parametrize(
    ("brute", "annee"),
    [("1755", 1755), ("../03/1755", 1755), ("vers 1850", 1850), ("an XII", None), (None, None)],
)
def test_lire_annee(brute: str | None, annee: int | None) -> None:
    assert lire_annee(brute) == annee


def test_lire_enumeration() -> None:
    assert lire_enumeration(TypeActe, "Baptême") is TypeActe.BAPTEME
    assert lire_enumeration(TypeActe, "DÉCÈS") is TypeActe.DECES
    assert lire_enumeration(TypeActe, "inconnu") is None
    assert lire_enumeration(Sexe, "Fille", {"FILLE": Sexe.F}) is Sexe.F


def test_modele_du_releve_d_essai(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "releves" / "landerneau-bms.csv", tmp_path)
    tableur = tmp_path / "landerneau-bms.csv"
    texte = modele_correspondance(tableur)
    contenu = tomllib.loads(texte)
    assert contenu["acte"]["type"] == {
        "colonne": "Type",
        "valeurs": {"B": "bapteme", "M": "mariage", "S": "deces"},
    }
    assert contenu["acte"]["date"] == {"colonne": "Date"}
    roles = [(p["role"], p["nom"]["colonne"], p["prenoms"]["colonne"]) for p in contenu["personne"]]
    assert roles == [
        ("sujet", "Nom", "Prénoms"),
        ("pere", "Nom", "Père"),  # nom repris de l'enfant
        ("mere", "Nom mère", "Mère"),
    ]
    # le modèle s'ingère tel quel
    (tmp_path / "landerneau-bms.toml").write_text(texte, encoding="utf-8")
    rapport = ingerer_releve(tmp_path / "landerneau-bms.toml", tmp_path / "bronze", INGESTION)
    assert rapport.lignes_ingerees == 7


def test_modele_d_un_tableur_de_naissances(tmp_path: Path) -> None:
    entete = (
        "N°;Date de l'acte;Commune;Nom;Prénom(s);Date de naissance;Lieu de naissance;"
        "Prénom du père;Profession du père;Nom de la mère;Prénom de la mère;Parrain"
    )
    (tmp_path / "naissances.csv").write_text(entete + "\n", encoding="utf-8")
    contenu = tomllib.loads(modele_correspondance(tmp_path / "naissances.csv"))
    assert contenu["acte"] == {
        "type": "naissance",
        "date": {"colonne": "Date de l'acte"},
        "commune": {"colonne": "Commune"},
    }
    sujet, pere, mere = contenu["personne"]
    assert sujet["date_naissance"] == {"colonne": "Date de naissance"}
    assert sujet["lieu_naissance"] == {"colonne": "Lieu de naissance"}
    assert pere == {
        "role": "pere",
        "nom": {"colonne": "Nom"},
        "prenoms": {"colonne": "Prénom du père"},
        "profession": {"colonne": "Profession du père"},
    }
    assert mere["nom"] == {"colonne": "Nom de la mère"}


def test_commande_ingest_releve(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    releves = tmp_path / "releves"
    releves.mkdir()
    shutil.copy(FIXTURES / "releves" / "landerneau-bms.csv", releves)
    assert main(["--donnees", str(tmp_path), "ingest", "releve"]) == 1  # pas de correspondance

    assert (
        main(
            [
                "--donnees",
                str(tmp_path),
                "ingest",
                "releve",
                "--modele",
                str(releves / "landerneau-bms.csv"),
            ]
        )
        == 0
    )
    assert (releves / "landerneau-bms.toml").exists()
    # ne remplace jamais une correspondance existante
    assert (
        main(
            [
                "--donnees",
                str(tmp_path),
                "ingest",
                "releve",
                "--modele",
                str(releves / "landerneau-bms.csv"),
            ]
        )
        == 1
    )

    shutil.copy(RELEVE, releves / "landerneau-bms.toml")
    capsys.readouterr()
    assert main(["--donnees", str(tmp_path), "ingest", "releve"]) == 0
    sortie = capsys.readouterr().out
    assert "landerneau-bms.csv : 7 ingérées, 3 rejetées" in sortie
    assert "rejets.csv" in sortie
    assert (tmp_path / "bronze" / "releve" / "landerneau-bms" / "actes-00000.parquet").exists()


def test_commande_ingest_releve_invalide(tmp_path: Path) -> None:
    chemin = tmp_path / "essai.toml"
    chemin.write_text(CORRESPONDANCE_MINIMALE, encoding="utf-8")
    assert main(["--donnees", str(tmp_path), "ingest", "releve", str(chemin)]) == 1


@pytest.fixture
def gold_releve(tmp_path: Path) -> Path:
    """Relevé d'essai ingéré, normalisé avec le référentiel, puis indexé."""
    referentiel = Referentiel.depuis_dossier(FIXTURES / "communes")
    ingerer_releve(RELEVE, tmp_path / "bronze", INGESTION)
    construire_silver(tmp_path / "bronze", tmp_path / "silver", referentiel)
    construire_gold(tmp_path / "silver", tmp_path / "gold", referentiel)
    return tmp_path


def test_silver_deduit_la_commune(gold_releve: Path) -> None:
    actes = pl.read_parquet(gold_releve / "silver" / "releve" / "actes.parquet")
    assert set(actes["commune_code_insee"]) == {"29103"}  # Landerneau


def test_silver_naissance_deduite_du_bapteme(gold_releve: Path) -> None:
    silver = gold_releve / "silver" / "releve"
    mentions = pl.read_parquet(silver / "mentions.parquet").join(
        pl.read_parquet(silver / "actes.parquet").select("acte_id", "type", "date_acte"),
        on="acte_id",
    )
    intervalles = {
        (ligne["type"], ligne["role"], ligne["prenoms_bruts"], ligne["date_acte"]): (
            ligne["annee_naissance_min"],
            ligne["annee_naissance_max"],
        )
        for ligne in mentions.iter_rows(named=True)
    }
    assert intervalles[("bapteme", "sujet", "Marie Josèphe", date(1755, 3, 2))] == (1755, 1755)
    assert intervalles[("bapteme", "pere", "Yves", date(1755, 3, 2))] == (None, None)
    # sépulture : naissance déduite de l'âge, pas de l'année de l'acte
    assert intervalles[("deces", "sujet", "Guillaume", None)] == (1719, 1720)


def test_recherche_dans_un_releve(gold_releve: Path) -> None:
    with Moteur(chemin_base(gold_releve / "gold")) as moteur:
        resultats = moteur.rechercher(
            Requete.creer(nom="LE GOFF", prenoms="Marie", naissance=(1754, 1756))
        )
        assert resultats
        meilleur = resultats[0]
        assert meilleur.source == "releve"
        fiche = moteur.fiches([meilleur.mention_id])[meilleur.mention_id]
    texte = citation(fiche, date(2026, 10, 10))
    assert texte.startswith("LE GOFF Marie Josèphe, baptême le 02/03/1755 à Landerneau (29).")
    assert "Baptêmes et sépultures de Landerneau (1755-1762), relevé d'essai, AD 29" in texte
    assert "3 E 103/2, vue 12" in texte


def test_interface_web(gold_releve: Path) -> None:
    with TestClient(creer_application(gold_releve)) as client:
        page = client.get("/recherche", params={"q": "LE GOFF Marie", "source": "releve"})
        assert page.status_code == 200
        assert '<option value="releve" selected>Relevés</option>' in page.text
        assert "Baptêmes et sépultures de Landerneau (1755-1762)" in page.text
        lien = re.search(r'href="(/actes/[^"]+)"', page.text)
        assert lien is not None
        fiche = client.get(html.unescape(lien.group(1)))
    assert fiche.status_code == 200
    assert (
        "<dd>Baptêmes et sépultures de Landerneau (1755-1762), relevé d&#39;essai</dd>"
        in fiche.text
    )
    assert "fiabilité estimée de la transcription : 95" in fiche.text


def test_tirage_d_evaluation_par_source(tmp_path: Path) -> None:
    """Un petit relevé à côté d'une grosse source a ses propres exemples de calibration."""
    construire_racine(tmp_path)
    referentiel = Referentiel.depuis_dossier(tmp_path / "ref" / "communes")
    ingerer_releve(RELEVE, tmp_path / "bronze", INGESTION)
    construire_silver(tmp_path / "bronze", tmp_path / "silver", referentiel)
    chemin = construire_gold(tmp_path / "silver", tmp_path / "gold", referentiel).chemin
    notices = tirer_notices(chemin, 3, graine=1)
    sources = Counter(n["source"] for n in notices)
    assert sources["insee_deces"] == sources["releve"] == 3
    assert sources["socface"] >= 1
