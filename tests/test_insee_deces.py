"""Tests du connecteur INSEE décès : découpage, conversion, anomalies, partition bronze."""

from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from doudoumil_search.ingest.insee_deces import (
    LigneRejetee,
    convertir,
    decouper_ligne,
    departement_de,
    ingerer_fichier,
    lire_annee,
    lire_date,
    separer_nom_prenoms,
)
from doudoumil_search.pivot import Acte, Mention, NatureNom, Role, Sexe, TypeActe
from doudoumil_search.schemas import SCHEMA_ACTES, SCHEMA_MENTIONS
from fabrique_insee import ligne_insee

FIXTURE = Path(__file__).parent / "fixtures" / "deces-extrait.txt"
INGESTION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _convertir(ligne: str) -> tuple[Acte, Mention, Counter[str]]:
    anomalies: Counter[str] = Counter()
    acte, mention = convertir(decouper_ligne(ligne), "deces-2020.txt", 7, INGESTION, anomalies)
    return acte, mention, anomalies


def test_decoupage_des_champs() -> None:
    champs = decouper_ligne(ligne_insee())
    assert champs == {
        "nom_prenoms": "LE GOFF*MARIE JOSEPHE/",
        "sexe": "2",
        "date_naissance": "19310302",
        "code_lieu_naissance": "29232",
        "commune_naissance": "QUIMPER",
        "pays_naissance": "",
        "date_deces": "20200115",
        "code_lieu_deces": "35238",
        "numero_acte": "42",
    }


def test_ligne_sans_espaces_de_fin_completee() -> None:
    assert decouper_ligne(ligne_insee().rstrip())["numero_acte"] == "42"


def test_ligne_trop_longue_rejetee() -> None:
    with pytest.raises(LigneRejetee, match="trop longue"):
        decouper_ligne(ligne_insee() + "X")


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("LE GOFF*MARIE JOSEPHE/", ("LE GOFF", "MARIE JOSEPHE")),
        ("DUPONT*ANNE/", ("DUPONT", "ANNE")),
        ("DUPONT/", ("DUPONT", None)),
        ("DUPONT*/", ("DUPONT", None)),
        ("*ANNE/", (None, "ANNE")),
        ("D'ARTOIS*JEAN-MARIE/", ("D'ARTOIS", "JEAN-MARIE")),
    ],
)
def test_separer_nom_prenoms(brut: str, attendu: tuple[str | None, str | None]) -> None:
    assert separer_nom_prenoms(brut) == attendu


@pytest.mark.parametrize(
    ("brute", "attendue"),
    [
        ("19310302", date(1931, 3, 2)),
        ("19310300", None),
        ("19310002", None),
        ("19310230", None),
        ("00000000", None),
        ("1931", None),
        ("", None),
    ],
)
def test_lire_date(brute: str, attendue: date | None) -> None:
    assert lire_date(brute) == attendue


@pytest.mark.parametrize(
    ("brute", "annee"),
    [("19310302", 1931), ("19310000", 1931), ("00000000", None), ("2020XX01", None), ("", None)],
)
def test_lire_annee(brute: str, annee: int | None) -> None:
    assert lire_annee(brute) == annee


@pytest.mark.parametrize(
    ("code", "departement"),
    [("35238", "35"), ("2A004", "2A"), ("97411", "974"), ("98818", "988"), ("99139", "99")],
)
def test_departement_de(code: str, departement: str) -> None:
    assert departement_de(code) == departement


def test_conversion_complete() -> None:
    acte, mention, anomalies = _convertir(ligne_insee())
    assert acte.type is TypeActe.DECES
    assert acte.annee == 2020
    assert acte.date_acte == date(2020, 1, 15)
    assert acte.commune_code_insee == "35238"
    assert acte.departement == "35"
    assert (acte.depot, acte.cote, acte.vue) == ("INSEE", "deces-2020.txt", "7")
    assert mention.acte_id == acte.acte_id
    assert mention.role is Role.SUJET
    assert (mention.nom_brut, mention.prenoms_bruts) == ("LE GOFF", "MARIE JOSEPHE")
    assert mention.nature_nom is NatureNom.NAISSANCE
    assert mention.sexe is Sexe.F
    assert mention.date_naissance_brute == "19310302"
    assert mention.date_naissance == date(1931, 3, 2)
    assert mention.lieu_naissance_brut == "QUIMPER"
    assert mention.lieu_naissance_code_insee == "29232"
    assert mention.confiance_source == 1.0
    # bronze : rien n'est normalisé
    assert mention.nom_norm is None
    assert mention.annee_naissance_min is None
    assert not anomalies


def test_date_naissance_partielle_conservee_brute() -> None:
    _, mention, anomalies = _convertir(ligne_insee(date_naissance="19190500"))
    assert mention.date_naissance_brute == "19190500"
    assert mention.date_naissance is None
    assert anomalies["date de naissance incomplète"] == 1


def test_date_naissance_absente() -> None:
    _, mention, anomalies = _convertir(ligne_insee(date_naissance=""))
    assert mention.date_naissance_brute is None
    assert not anomalies


def test_date_deces_partielle_garde_l_annee() -> None:
    acte, _, anomalies = _convertir(ligne_insee(date_deces="20200100"))
    assert acte.annee == 2020
    assert acte.date_acte is None
    assert anomalies["date de décès incomplète"] == 1


@pytest.mark.parametrize("date_deces", ["2020XX01", "00000000", ""])
def test_date_deces_illisible_rejetee(date_deces: str) -> None:
    with pytest.raises(LigneRejetee, match="date de décès"):
        _convertir(ligne_insee(date_deces=date_deces))


def test_annee_deces_improbable_rejetee() -> None:
    with pytest.raises(LigneRejetee, match="improbable"):
        _convertir(ligne_insee(date_deces="14990101"))


def test_code_lieu_invalide_tolere() -> None:
    acte, mention, anomalies = _convertir(
        ligne_insee(code_lieu_naissance="ABCDE", code_lieu_deces="")
    )
    assert mention.lieu_naissance_code_insee is None
    assert acte.commune_code_insee is None
    assert acte.departement is None
    assert anomalies["code du lieu de naissance invalide"] == 1
    assert anomalies["code du lieu de décès absent"] == 1


def test_sexe_inconnu_tolere() -> None:
    _, mention, anomalies = _convertir(ligne_insee(sexe="9"))
    assert mention.sexe is None
    assert anomalies["sexe absent ou inconnu"] == 1


def test_identifiant_independant_du_fichier_et_de_la_ligne() -> None:
    """Un décès présent dans deux fichiers garde le même identifiant."""
    anomalies: Counter[str] = Counter()
    champs = decouper_ligne(ligne_insee())
    acte_a, mention_a = convertir(champs, "deces-2020-m01.txt", 3, INGESTION, anomalies)
    acte_b, mention_b = convertir(champs, "deces-2020.txt", 51234, INGESTION, anomalies)
    assert acte_a.acte_id == acte_b.acte_id
    assert mention_a.mention_id == mention_b.mention_id
    assert acte_a.cote != acte_b.cote


def test_identifiant_distingue_les_actes() -> None:
    ids = {
        _convertir(ligne_insee(numero_acte="42"))[0].acte_id,
        _convertir(ligne_insee(numero_acte="43"))[0].acte_id,
        _convertir(ligne_insee(code_lieu_deces="35047"))[0].acte_id,
        _convertir(ligne_insee(date_deces="20200116"))[0].acte_id,
    }
    assert len(ids) == 4


def test_cle_de_repli_sans_numero_d_acte() -> None:
    a = _convertir(ligne_insee(numero_acte="", nom_prenoms="DUPONT*ANNE/"))[0]
    b = _convertir(ligne_insee(numero_acte="", nom_prenoms="DUPONT*ANNIE/"))[0]
    assert a.acte_id != b.acte_id


def test_ingestion_de_la_fixture(tmp_path: Path) -> None:
    rapport = ingerer_fichier(FIXTURE, tmp_path, ingested_at=INGESTION, taille_lot=3)
    assert (rapport.lignes_lues, rapport.lignes_ingerees, rapport.lignes_rejetees) == (10, 8, 2)

    dossier = tmp_path / "insee_deces" / "deces-extrait"
    assert rapport.dossier == dossier
    actes = pl.read_parquet(dossier / "actes-*.parquet")
    mentions = pl.read_parquet(dossier / "mentions-*.parquet")
    assert actes.schema == SCHEMA_ACTES
    assert mentions.schema == SCHEMA_MENTIONS
    assert actes.height == mentions.height == 8
    # taille de lot 3 : trois fichiers par table
    assert len(list(dossier.glob("actes-*.parquet"))) == 3
    # la ligne 10 répète la ligne 1 : même identifiant, dédoublonnage laissé à silver
    assert actes["acte_id"].n_unique() == 7

    rejets = pl.read_csv(dossier / "rejets.csv")
    assert rejets["numero_ligne"].to_list() == [8, 9]
    assert set(rejets["motif"]) == {"date de décès illisible"}

    accentuee = mentions.filter(pl.col("nom_brut") == "PAYET")
    assert accentuee["prenoms_bruts"].item() == "LOUISE ANDRÉE"


def test_reingestion_identique_et_sans_doublon(tmp_path: Path) -> None:
    premier = ingerer_fichier(FIXTURE, tmp_path, ingested_at=INGESTION)
    ids_1 = pl.read_parquet(premier.dossier / "mentions-*.parquet")["mention_id"].sort()
    second = ingerer_fichier(FIXTURE, tmp_path, ingested_at=INGESTION)
    ids_2 = pl.read_parquet(second.dossier / "mentions-*.parquet")["mention_id"].sort()
    assert ids_1.to_list() == ids_2.to_list()
    assert sorted(p.name for p in tmp_path.joinpath("insee_deces").iterdir()) == ["deces-extrait"]


def test_ligne_latin1_decodee(tmp_path: Path) -> None:
    fichier = tmp_path / "deces-1975.txt"
    fichier.write_bytes(ligne_insee(commune_naissance="BÉZIERS").encode("latin-1") + b"\n")
    rapport = ingerer_fichier(fichier, tmp_path / "bronze", ingested_at=INGESTION)
    mentions = pl.read_parquet(rapport.dossier / "mentions-*.parquet")
    assert mentions["lieu_naissance_brut"].item() == "BÉZIERS"


def test_erreur_en_cours_preserve_l_ancienne_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rapport = ingerer_fichier(FIXTURE, tmp_path, ingested_at=INGESTION)
    avant = sorted(p.name for p in rapport.dossier.iterdir())

    def panne(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr("doudoumil_search.ingest.insee_deces.convertir", panne)
    with pytest.raises(OSError, match="disque plein"):
        ingerer_fichier(FIXTURE, tmp_path, ingested_at=INGESTION)
    assert sorted(p.name for p in rapport.dossier.iterdir()) == avant
    assert not list(tmp_path.joinpath("insee_deces").glob("*.en-cours"))
