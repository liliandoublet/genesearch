"""Mise en forme des résultats pour la ligne de commande."""

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


def naissance(fiche: dict[str, Any]) -> str:
    """« né le 02/03/1931 à QUIMPER », « née vers 1865-1866 »…"""
    accord = "e" if fiche.get("sexe") == "F" else ""
    if fiche.get("date_naissance"):
        texte = f"né{accord} le {_date(fiche['date_naissance'])}"
    elif fiche.get("annee_naissance_min") is not None:
        mini, maxi = fiche["annee_naissance_min"], fiche["annee_naissance_max"]
        texte = f"né{accord} en {mini}" if mini == maxi else f"né{accord} vers {mini}-{maxi}"
    else:
        texte = ""
    lieu = fiche.get("lieu_naissance_brut") or fiche.get("lieu_naissance_code_insee")
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


def provenance(fiche: dict[str, Any]) -> str:
    morceaux = [fiche.get("depot"), fiche.get("cote")]
    if fiche.get("vue"):
        morceaux.append(f"vue {fiche['vue']}")
    if fiche.get("url_image"):
        morceaux.append(fiche["url_image"])
    return " · ".join(m for m in morceaux if m)


def formater(rang: int, resultat: Resultat, details: bool = False) -> str:
    """Deux lignes par résultat (trois avec les détails du score)."""
    fiche = resultat.fiche
    sexe = f" ({fiche['sexe']})" if fiche.get("sexe") else ""
    identite = f"{fiche.get('nom_brut') or '?'} {fiche.get('prenoms_bruts') or ''}".strip()
    role = ROLES.get(resultat.role, "")
    confiance = (
        f"{resultat.libelle} {pourcent(resultat.probabilite, 0)}"
        if resultat.probabilite is not None
        else f"{resultat.libelle} (score {resultat.score:.2f})".replace(".", ",")
    )
    morceaux = [identite + sexe, naissance(fiche), evenement(fiche)]
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
