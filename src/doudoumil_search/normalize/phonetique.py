"""Clé phonétique adaptée aux noms et prénoms français.

Deux écritures qui se prononcent de la même façon doivent donner la même clé (``LE GOFF``,
``LEGOF``, ``LE GOFFE``) ; c'est le canal A de la présélection (règle R1 de PLAN.md).

L'algorithme s'inspire de Soundex2 (F. Brouard), une adaptation de Soundex au français,
avec trois écarts assumés :

- la clé n'est pas tronquée à quatre caractères : sur plusieurs dizaines de millions de
  personnes, une clé courte rassemblerait trop de noms différents ;
- ``PH`` devient ``F`` partout, pas seulement en début de nom (``JOSEPH``, ``STEPHANE``) ;
- ``Y`` est traité comme une voyelle (``MEYER``, ``MAIER`` et ``MAYER`` se rejoignent), et
  le ``H`` est supprimé avant le traitement des voyelles, pour qu'un ``H`` initial muet ne
  change pas la première lettre (``HENRI`` et ``ENRI``).

Étapes, sur les lettres A à Z seules :

1. ``PH`` → ``F`` ; groupes durs : ``GUI`` → ``KI``, ``GUE`` → ``KE``, ``GA`` → ``KA``,
   ``GO`` → ``KO``, ``GU`` → ``K``, ``CA`` → ``KA``, ``CO`` → ``KO``, ``CU`` → ``KU``,
   ``Q`` → ``K``, ``CC`` → ``K``, ``CK`` → ``K`` ;
2. préfixes : ``MAC`` → ``MCC``, ``SCH`` → ``SSS``, ``ASA`` → ``AZA``, ``KN`` → ``NN``,
   ``PF`` → ``FF`` ;
3. suppression des ``H`` qui ne suivent pas un ``C`` ou un ``S`` ;
4. toute voyelle (Y compris) autre que la première lettre devient ``A`` ;
5. suppression des ``A``, ``D``, ``T`` et ``S`` finaux, tant qu'il en reste ;
6. suppression des ``A`` autres que la première lettre ;
7. suppression des lettres répétées.
"""

import re
from typing import Final

from doudoumil_search.normalize.texte import majuscules_ascii

GROUPES: Final = (
    ("PH", "F"),
    ("GUI", "KI"),
    ("GUE", "KE"),
    ("GA", "KA"),
    ("GO", "KO"),
    ("GU", "K"),
    ("CA", "KA"),
    ("CO", "KO"),
    ("CU", "KU"),
    ("Q", "K"),
    ("CC", "K"),
    ("CK", "K"),
)
PREFIXES: Final = (("MAC", "MCC"), ("SCH", "SSS"), ("ASA", "AZA"), ("KN", "NN"), ("PF", "FF"))

NON_LETTRES: Final = re.compile(r"[^A-Z]+")
H_MUET: Final = re.compile(r"(?<![CS])H")
VOYELLES_INTERNES: Final = re.compile(r"(?<=.)[AEIOUY]")
FINALES: Final = re.compile(r"(?<=.)[ADTS]+$")
A_INTERNES: Final = re.compile(r"(?<=.)A")
REPETITIONS: Final = re.compile(r"(.)\1+")


def cle_phonetique(texte: str | None) -> str | None:
    """Clé phonétique d'un nom ou d'un prénom ; ``None`` s'il ne contient aucune lettre."""
    if texte is None:
        return None
    cle = NON_LETTRES.sub("", majuscules_ascii(texte))
    if not cle:
        return None
    for groupe, remplacement in GROUPES:
        cle = cle.replace(groupe, remplacement)
    for prefixe, remplacement in PREFIXES:
        if cle.startswith(prefixe):
            cle = remplacement + cle[len(prefixe) :]
            break
    cle = H_MUET.sub("", cle) or cle[:1]
    cle = VOYELLES_INTERNES.sub("A", cle)
    cle = FINALES.sub("", cle)
    cle = A_INTERNES.sub("", cle)
    return REPETITIONS.sub(r"\1", cle)
