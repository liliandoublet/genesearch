"""Mise en forme des notices, pour la ligne de commande et l'interface web."""

from collections.abc import Callable
from datetime import date
from typing import Any

from doudoumil_search.search.evaluation import pourcent
from doudoumil_search.search.moteur import Resultat

EVENEMENTS = {
    "deces": "décès",
    "naissance": "naissance",
    "mariage": "mariage",
    "bapteme": "baptême",
    "recensement": "recensement",
    "autre": "acte",
}
SOURCES = {
    "insee_deces": "Fichier des personnes décédées (INSEE)",
    "socface": "Recensement de la population, transcription Socface (INED, FranceArchives)",
    "releve": "Relevé",
}
# Ce que désigne le champ « vue » selon la source : une ligne de fichier ou une vue d'archive.
UNITES_VUE = {"insee_deces": "ligne"}
ROLES = {
    "sujet": "",
    "pere": "père",
    "mere": "mère",
    "epoux": "époux",
    "epouse": "épouse",
    "enfant": "enfant",
    "temoin": "témoin",
    "chef_menage": "chef de ménage",
    "autre": "",
}


def _date(valeur: date | None) -> str | None:
    return valeur.strftime("%d/%m/%Y") if valeur else None


def naissance(fiche: dict[str, Any], nommer: Callable[[str], str | None] | None = None) -> str:
    """« né le 02/03/1931 à QUIMPER », « née vers 1865-1866 »…

    Si la source ne donne que le code du lieu, ``nommer`` (le référentiel des communes) le
    remplace par le nom de la commune.
    """
    accord = "e" if fiche.get("sexe") == "F" else ""
    if fiche.get("date_naissance"):
        texte = f"né{accord} le {_date(fiche['date_naissance'])}"
    elif fiche.get("annee_naissance_min") is not None:
        mini, maxi = fiche["annee_naissance_min"], fiche["annee_naissance_max"]
        texte = f"né{accord} en {mini}" if mini == maxi else f"né{accord} vers {mini}-{maxi}"
    else:
        texte = ""
    lieu = fiche.get("lieu_naissance_brut")
    code = fiche.get("lieu_naissance_code_insee")
    if not lieu and code:
        lieu = (nommer(code) if nommer else None) or code
    if lieu:
        texte = f"{texte} à {lieu}" if texte else f"né{accord} à {lieu}"
    return texte


def evenement(fiche: dict[str, Any]) -> str:
    """« décès le 15/01/2020 à Rennes (35) », « recensement 1906 à Quimper (29) »."""
    nature = EVENEMENTS.get(fiche.get("type") or "", "acte")
    quand = f"le {_date(fiche['date_acte'])}" if fiche.get("date_acte") else str(fiche["annee"])
    lieu = fiche.get("commune_label") or fiche.get("commune_code_insee")
    departement = f" ({fiche['departement']})" if fiche.get("departement") else ""
    return f"{nature} {quand}" + (f" à {lieu}{departement}" if lieu else "")


def identite(fiche: dict[str, Any]) -> str:
    return f"{fiche.get('nom_brut') or '?'} {fiche.get('prenoms_bruts') or ''}".strip()


def provenance(fiche: dict[str, Any]) -> str:
    morceaux = [fiche.get("depot"), fiche.get("cote")]
    if fiche.get("vue"):
        morceaux.append(f"{UNITES_VUE.get(fiche.get('source') or '', 'vue')} {fiche['vue']}")
    if fiche.get("url_image"):
        morceaux.append(fiche["url_image"])
    return " · ".join(m for m in morceaux if m)


def nom_source(fiche: dict[str, Any]) -> str:
    """Intitulé propre à la notice (titre d'un relevé), sinon nom de la source."""
    if fiche.get("titre_source"):
        return str(fiche["titre_source"])
    return SOURCES.get(fiche.get("source") or "", fiche.get("source") or "source inconnue")


def citation(fiche: dict[str, Any], consulte_le: date) -> str:
    """Citation de source prête à copier dans un arbre ou une note."""
    source = nom_source(fiche)
    morceaux = [source]
    if fiche.get("depot") and fiche["depot"] not in source:
        morceaux.append(fiche["depot"])
    if fiche.get("cote"):
        morceaux.append(fiche["cote"])
    if fiche.get("vue"):
        morceaux.append(f"{UNITES_VUE.get(fiche.get('source') or '', 'vue')} {fiche['vue']}")
    if fiche.get("url_image"):
        morceaux.append(fiche["url_image"])
    phrase = f"{identite(fiche)}, {evenement(fiche)}. {', '.join(morceaux)}."
    return f"{phrase} Consulté le {_date(consulte_le)}."


def formater(rang: int, resultat: Resultat, details: bool = False) -> str:
    """Deux lignes par résultat (trois avec les détails du score)."""
    fiche = resultat.fiche
    sexe = f" ({fiche['sexe']})" if fiche.get("sexe") else ""
    role = ROLES.get(resultat.role, "")
    confiance = (
        f"{resultat.libelle} {pourcent(resultat.probabilite, 0)}"
        if resultat.probabilite is not None
        else f"{resultat.libelle} (score {resultat.score:.2f})".replace(".", ",")
    )
    morceaux = [identite(fiche) + sexe, naissance(fiche), evenement(fiche)]
    if role:
        morceaux.append(role)
    lignes = [
        f"{rang:>3}. {confiance} — " + ", ".join(m for m in morceaux if m),
        f"     {provenance(fiche)}   [{', '.join(resultat.canaux)}]"
        + ("   nom d'épouse probable" if resultat.nom_epouse_probable else ""),
    ]
    if details:
        c = resultat.composantes
        valeurs = {"nom": c.nom, "prénoms": c.prenoms, "naissance": c.naissance, "lieu": c.lieu}
        lignes.append(
            "     "
            + ", ".join(
                f"{k} {'—' if v is None else f'{v:.2f}'.replace('.', ',')}"
                for k, v in valeurs.items()
            )
        )
    return "\n".join(lignes)
