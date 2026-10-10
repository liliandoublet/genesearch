"""Intervalle d'années de naissance (règle R3 de PLAN.md).

Toute naissance est ramenée à un intervalle ``[min, max]`` d'années :

- date complète → l'année ;
- date brute incomplète dont l'année est lisible (``19310300``, ``../03/1855``, ``vers 1850``)
  → l'année, soit la première suite de quatre chiffres ;
- âge révolu ``A`` dans un acte de l'année ``Y`` → ``[Y − A − 1, Y − A]`` ;
- sujet d'un acte de naissance ou de baptême de l'année ``Y`` → ``[Y, Y]``, ou ``[Y − 1, Y]``
  si l'acte est de janvier ou sans date complète (enfant né fin décembre) ;
- sinon, pas d'intervalle.

La règle du sujet de l'acte n'existe qu'en expression Polars (``expressions_naissance_de_l_acte``),
car elle porte sur une notice et non sur une personne isolée. Le reste de la règle existe
sous deux formes : une fonction pour une valeur isolée (requête,
individu d'un arbre) et une expression Polars pour une table entière ; un test vérifie
qu'elles concordent.
"""

import re
from datetime import date
from typing import Final

import polars as pl

ANNEE_MIN: Final = 1300
ANNEE_MAX: Final = 2100
ANNEE_EN_TETE: Final = re.compile(r"(\d{4})")


def intervalle_naissance(
    date_naissance: date | None = None,
    date_brute: str | None = None,
    age: int | None = None,
    annee_acte: int | None = None,
) -> tuple[int, int] | None:
    """Intervalle d'années de naissance, ou ``None`` faute d'information exploitable."""
    if date_naissance is not None:
        bornes = (date_naissance.year, date_naissance.year)
    elif date_brute and (lue := ANNEE_EN_TETE.search(date_brute)) and lue.group(1) != "0000":
        annee = int(lue.group(1))
        bornes = (annee, annee)
    elif age is not None and annee_acte is not None:
        bornes = (annee_acte - age - 1, annee_acte - age)
    else:
        return None
    if bornes[0] < ANNEE_MIN or bornes[1] > ANNEE_MAX:
        return None
    return bornes


def expressions_intervalle_naissance(
    annee_acte: pl.Expr,
) -> tuple[pl.Expr, pl.Expr]:
    """Expressions ``annee_naissance_min`` et ``annee_naissance_max`` pour une table pivot.

    ``annee_acte`` désigne l'année de l'acte, nécessaire pour déduire la naissance d'un âge.
    """
    annee_date = pl.col("date_naissance").dt.year().cast(pl.Int32)
    texte_annee = pl.col("date_naissance_brute").str.extract(ANNEE_EN_TETE.pattern, 1)
    annee_brute = pl.when(texte_annee != "0000").then(texte_annee.cast(pl.Int32, strict=False))
    age = pl.col("age").cast(pl.Int32)
    annee = annee_acte.cast(pl.Int32)
    mini = pl.coalesce(annee_date, annee_brute, annee - age - 1)
    maxi = pl.coalesce(annee_date, annee_brute, annee - age)
    valide = (mini >= ANNEE_MIN) & (maxi <= ANNEE_MAX)
    return (
        pl.when(valide).then(mini).otherwise(None).cast(pl.Int16).alias("annee_naissance_min"),
        pl.when(valide).then(maxi).otherwise(None).cast(pl.Int16).alias("annee_naissance_max"),
    )


TYPES_ACTE_DE_NAISSANCE: Final = ("naissance", "bapteme")


def expressions_naissance_de_l_acte(
    type_acte: pl.Expr, role: pl.Expr, annee_acte: pl.Expr, date_acte: pl.Expr
) -> tuple[pl.Expr, pl.Expr]:
    """Intervalle de naissance du sujet d'un acte de naissance ou de baptême, sinon nul."""
    sujet = role.eq("sujet") & type_acte.is_in(TYPES_ACTE_DE_NAISSANCE)
    annee = annee_acte.cast(pl.Int32)
    debut_d_annee = date_acte.is_null() | date_acte.dt.month().eq(1)
    mini = pl.when(sujet).then(pl.when(debut_d_annee).then(annee - 1).otherwise(annee))
    maxi = pl.when(sujet).then(annee)
    return mini.cast(pl.Int16), maxi.cast(pl.Int16)
