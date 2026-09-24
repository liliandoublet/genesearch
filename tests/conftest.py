"""Fixtures partagées : un acte et une mention valides servant de base aux tests."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from doudoumil_search.pivot import Role, Sexe, Source, TypeActe, fabriquer_id

ACTE_ID = fabriquer_id(Source.INSEE_DECES, "deces-2020-m01.txt", "42")


@pytest.fixture
def acte_valide() -> dict[str, Any]:
    """Champs d'un acte de décès INSEE complet."""
    return {
        "acte_id": ACTE_ID,
        "source": Source.INSEE_DECES,
        "type": TypeActe.DECES,
        "annee": 2020,
        "date_acte": date(2020, 1, 15),
        "commune_code_insee": "35238",
        "commune_label": "Rennes",
        "departement": "35",
        "depot": "INSEE",
        "cote": "deces-2020-m01.txt",
        "vue": "42",
        "url_image": None,
        "ingested_at": datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
    }


@pytest.fixture
def mention_valide() -> dict[str, Any]:
    """Champs de la mention du défunt rattachée à ``acte_valide``."""
    return {
        "mention_id": fabriquer_id(Source.INSEE_DECES, "deces-2020-m01.txt", "42", "sujet"),
        "acte_id": ACTE_ID,
        "role": Role.SUJET,
        "nom_brut": "LE GOFF",
        "prenoms_bruts": "Marie Josèphe",
        "nom_norm": None,
        "nom_phonetique": None,
        "prenoms_norm": None,
        "sexe": Sexe.F,
        "date_naissance": date(1931, 3, 2),
        "age": 88,
        "profession": None,
        "lieu_naissance_brut": "Quimper",
        "lieu_naissance_code_insee": "29232",
        "confiance_source": 1.0,
    }
