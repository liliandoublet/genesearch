"""Interface web locale : pages de recherche, fiches, trouvailles, exports et API JSON.

L'application ne sert que sur la machine de l'utilisateur (``127.0.0.1``). Deux protections
contre les pages web malveillantes qui viseraient ce serveur local :

- seuls les noms d'hôte ``localhost`` et ``127.0.0.1`` sont acceptés (rebond DNS) ;
- un envoi de formulaire venu d'une autre origine est refusé (falsification de requête).

Les pages sont rendues côté serveur avec Jinja2, sans framework JavaScript ; quelques lignes
de JavaScript ne servent qu'à l'autocomplétion des lieux.
"""

import csv
import io
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.trustedhost import TrustedHostMiddleware

from doudoumil_search.api.formulaire import (
    PAR_PAGE,
    SOURCES,
    Formulaire,
    FormulaireInvalide,
    facettes,
    filtrer,
)
from doudoumil_search.api.trouvailles import Carnet
from doudoumil_search.config import dossier_gold, dossier_perso, dossier_referentiels
from doudoumil_search.normalize.lieux import Referentiel
from doudoumil_search.search import affichage
from doudoumil_search.search.evaluation import pourcent
from doudoumil_search.search.gold import chemin_base
from doudoumil_search.search.moteur import Moteur, Resultat
from doudoumil_search.search.requete import Requete

DOSSIER: Final = Path(__file__).parent
HOTES: Final = ["127.0.0.1", "localhost", "testserver"]
EXPORT_MAXIMUM: Final = 500
ACTIONS: Final = ("favori", "note", "oui", "non", "effacer", "supprimer")
CLASSES_CONFIANCE: Final = {
    "très probable": "tres-probable",
    "probable": "probable",
    "à vérifier": "a-verifier",
    "non calibré": "non-calibre",
}


class Etat:
    """Ressources partagées : moteur (rouvert si la base change), référentiel, carnet."""

    def __init__(self, racine: Path) -> None:
        self.racine = racine
        self.chemin_gold = chemin_base(dossier_gold(racine))
        communes = dossier_referentiels(racine) / "communes"
        self.referentiel = (
            Referentiel.depuis_dossier(communes) if (communes / "communes.json").exists() else None
        )
        self.carnet = Carnet(dossier_perso(racine) / "trouvailles.sqlite")
        self._moteur: Moteur | None = None
        self._date_base = 0.0
        self.verrou = threading.Lock()  # une connexion DuckDB ne se partage pas entre fils

    def fermer(self) -> None:
        with self.verrou:
            if self._moteur is not None:
                self._moteur.fermer()
                self._moteur = None

    def moteur(self) -> Moteur | None:
        """Moteur prêt, rouvert si la base a été reconstruite ; ``None`` sans base."""
        if not self.chemin_gold.exists():
            return None
        date_base = self.chemin_gold.stat().st_mtime
        if self._moteur is None or date_base != self._date_base:
            if self._moteur is not None:
                self._moteur.fermer()
            self._moteur = Moteur(self.chemin_gold)
            self._date_base = date_base
        return self._moteur


def _environnement(referentiel: Referentiel | None) -> Environment:
    environnement = Environment(
        loader=FileSystemLoader(DOSSIER / "gabarits"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environnement.globals.update(
        identite=affichage.identite,
        naissance=lambda fiche: affichage.naissance(fiche, nommer=_nommer(referentiel)),
        evenement=affichage.evenement,
        provenance=affichage.provenance,
        pourcent=pourcent,
        roles=affichage.ROLES,
        noms_sources=SOURCES,
    )
    environnement.filters["score"] = lambda v: "—" if v is None else f"{v:.2f}".replace(".", ",")
    environnement.filters["lien_sur"] = lien_sur
    environnement.filters["initiale"] = lambda texte: texte[:1].upper() + texte[1:]
    environnement.filters["classe_confiance"] = lambda libelle: CLASSES_CONFIANCE.get(libelle, "")
    return environnement


def lien_sur(adresse: str | None) -> str | None:
    """Adresse d'image affichable : http(s) seulement, jamais « javascript: » ni autre."""
    if adresse and urlparse(adresse).scheme in ("http", "https"):
        return adresse
    return None


def _requete_transmise(texte: str) -> Requete | None:
    """Requête d'origine renvoyée par un formulaire ; ignorée si elle est mal formée."""
    if not texte:
        return None
    try:
        donnees = json.loads(texte)
        return Requete.depuis_dict(donnees) if isinstance(donnees, dict) else None
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None


def _nommer(referentiel: Referentiel | None) -> Callable[[str], str | None] | None:
    """« Quimper (29) » pour un code de commune, avec le référentiel s'il est présent."""
    if referentiel is None:
        return None

    def nommer(code: str) -> str | None:
        nom, commune = referentiel.nom(code), referentiel.commune(code)
        return f"{nom} ({commune.departement})" if nom and commune else nom

    return nommer


def _resultat_json(resultat: Resultat) -> dict[str, Any]:
    donnees: dict[str, Any] = jsonable_encoder(asdict(resultat))
    return donnees


def _retour_sur(retour: str | None) -> str:
    """Adresse de retour après un envoi : un chemin local seulement."""
    if retour and retour.startswith("/") and not retour.startswith("//"):
        return retour
    return "/trouvailles"


def creer_application(racine: Path) -> FastAPI:
    """Application web pour les données rangées sous ``racine``."""
    etat = Etat(racine)
    gabarits = _environnement(etat.referentiel)

    @asynccontextmanager
    async def cycle_de_vie(_: FastAPI) -> AsyncIterator[None]:
        yield
        etat.fermer()  # libère la base : d'autres commandes peuvent alors y écrire

    application = FastAPI(
        lifespan=cycle_de_vie,
        title="doudoumil-search",
        description="Moteur de recherche généalogique personnel",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=HOTES)
    application.mount("/statique", StaticFiles(directory=DOSSIER / "statique"), name="statique")
    application.state.etat = etat

    @application.middleware("http")
    async def meme_origine(requete_http: Request, suite: Any) -> Response:
        if requete_http.method == "POST":
            origine = requete_http.headers.get("origin")
            if origine and urlparse(origine).netloc != requete_http.headers.get("host"):
                return Response("envoi refusé : autre origine", status_code=403)
        reponse: Response = await suite(requete_http)
        return reponse

    def page(nom: str, statut: int = 200, **contexte: Any) -> HTMLResponse:
        departements = etat.referentiel.departements if etat.referentiel else {}
        contexte.setdefault(
            "noms_departements", {code: f"{code} {nom}" for code, nom in departements.items()}
        )
        contexte.setdefault("base_presente", etat.chemin_gold.exists())
        contexte.setdefault("referentiel_present", etat.referentiel is not None)
        return HTMLResponse(gabarits.get_template(nom).render(**contexte), status_code=statut)

    def classer(formulaire: Formulaire) -> tuple[Requete, list[Resultat], Moteur]:
        moteur = etat.moteur()
        if moteur is None:
            raise HTTPException(503, "base de recherche absente : lancez « doudoumil index »")
        requete = formulaire.requete(etat.referentiel)
        return requete, moteur.classer(requete), moteur

    # --- pages -------------------------------------------------------------------------

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def accueil() -> HTMLResponse:
        return page("accueil.html", formulaire=Formulaire())

    @application.get("/recherche", response_class=HTMLResponse, include_in_schema=False)
    def recherche(requete_http: Request) -> HTMLResponse:
        formulaire = Formulaire.depuis(requete_http.query_params)
        if formulaire.vide:
            return page("accueil.html", formulaire=formulaire)
        try:
            with etat.verrou:
                requete, classes, moteur = classer(formulaire)
                retenus = filtrer(classes, formulaire)
                debut = (formulaire.page - 1) * PAR_PAGE
                affiches = retenus[debut : debut + PAR_PAGE]
                fiches = moteur.fiches([r.mention_id for r in affiches])
        except FormulaireInvalide as erreur:
            return page("accueil.html", statut=422, formulaire=formulaire, erreurs=erreur.erreurs)
        except HTTPException as erreur:
            return page(
                "accueil.html",
                statut=erreur.status_code,
                formulaire=formulaire,
                erreurs={"base": erreur.detail},
            )
        pages = max(1, -(-len(retenus) // PAR_PAGE))
        return page(
            "resultats.html",
            formulaire=formulaire,
            requete_json=json.dumps(requete.vers_dict(), ensure_ascii=False),
            resultats=[
                (debut + i + 1, r, fiches.get(r.mention_id, {})) for i, r in enumerate(affiches)
            ],
            total=len(retenus),
            total_avant_filtres=len(classes),
            facettes=facettes(classes),
            pages=pages,
            trouvailles=etat.carnet.parmi([r.mention_id for r in affiches]),
            retour=str(requete_http.url.path)
            + ("?" + requete_http.url.query if requete_http.url.query else ""),
        )

    @application.get("/actes/{acte_id}", response_class=HTMLResponse, include_in_schema=False)
    def fiche(acte_id: str, requete_http: Request) -> HTMLResponse:
        with etat.verrou:
            moteur = etat.moteur()
            trouve = moteur.acte(acte_id) if moteur else None
        if trouve is None:
            return page("erreur.html", statut=404, message="Acte introuvable.")
        acte, mentions = trouve
        consulte = date.today()
        personnes = [
            ({**acte, **mention}, affichage.citation({**acte, **mention}, consulte))
            for mention in mentions
        ]
        retour = requete_http.query_params.get("retour")
        return page(
            "fiche.html",
            acte=acte,
            personnes=personnes,
            mise_en_avant=requete_http.query_params.get("mention"),
            trouvailles=etat.carnet.parmi([m["mention_id"] for m in mentions]),
            retour=_retour_sur(retour) if retour else None,
            requete_json=requete_http.query_params.get("requete", ""),
            ici=str(requete_http.url.path)
            + ("?" + requete_http.url.query if requete_http.url.query else ""),
        )

    @application.get("/trouvailles", response_class=HTMLResponse, include_in_schema=False)
    def trouvailles() -> HTMLResponse:
        return page("trouvailles.html", trouvailles=etat.carnet.toutes())

    @application.post("/trouvailles/{mention_id}", include_in_schema=False)
    def noter(
        mention_id: str,
        action: str = Form(...),
        acte_id: str = Form(...),
        libelle: str = Form(...),
        source: str = Form(""),
        note: str = Form(""),
        requete: str = Form(""),
        retour: str = Form("/trouvailles"),
    ) -> RedirectResponse:
        if action not in ACTIONS:
            raise HTTPException(400, f"action inconnue : {action}")
        if action == "supprimer":
            etat.carnet.supprimer(mention_id)
        else:
            requete_origine = _requete_transmise(requete)
            actuelle = etat.carnet.lire(mention_id)
            etat.carnet.enregistrer(
                mention_id,
                acte_id,
                libelle,
                source=source or None,
                requete=requete_origine,
                favori=(not actuelle.favori if actuelle else True) if action == "favori" else None,
                note=note if action == "note" else None,
                verdict=action if action in ("oui", "non") else None,
                effacer_verdict=action == "effacer",
            )
        return RedirectResponse(_retour_sur(retour), status_code=303)

    # --- exports CSV ---------------------------------------------------------------------

    def csv_reponse(lignes: list[list[Any]], entete: list[str], nom: str) -> Response:
        tampon = io.StringIO()
        ecrivain = csv.writer(tampon, delimiter=";")
        ecrivain.writerow(entete)
        ecrivain.writerows(lignes)
        # BOM : le tableur ouvre alors le fichier en UTF-8 sans question
        return Response(
            "﻿" + tampon.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nom}"'},
        )

    @application.get("/recherche.csv", include_in_schema=False)
    def recherche_csv(requete_http: Request) -> Response:
        formulaire = Formulaire.depuis(requete_http.query_params)
        try:
            with etat.verrou:
                _, classes, moteur = classer(formulaire)
                retenus = filtrer(classes, formulaire)[:EXPORT_MAXIMUM]
                fiches = moteur.fiches([r.mention_id for r in retenus])
        except FormulaireInvalide as erreur:
            raise HTTPException(422, erreur.erreurs) from erreur
        lignes = []
        for rang, r in enumerate(retenus, start=1):
            f = fiches.get(r.mention_id, {})
            lignes.append(
                [
                    rang,
                    r.libelle,
                    pourcent(r.probabilite, 0) if r.probabilite is not None else "",
                    f"{r.score:.3f}".replace(".", ","),
                    affichage.identite(f),
                    f.get("sexe") or "",
                    affichage.naissance(f),
                    affichage.evenement(f),
                    affichage.ROLES.get(r.role, ""),
                    f.get("titre_source") or SOURCES.get(r.source, r.source),
                    affichage.provenance(f),
                    f.get("url_image") or "",
                    ", ".join(r.canaux),
                    r.mention_id,
                    r.acte_id,
                ]
            )
        entete = [
            "rang",
            "confiance",
            "probabilité",
            "score",
            "personne",
            "sexe",
            "naissance",
            "événement",
            "rôle",
            "source",
            "provenance",
            "image",
            "canaux",
            "mention_id",
            "acte_id",
        ]
        return csv_reponse(lignes, entete, "recherche.csv")

    @application.get("/trouvailles.csv", include_in_schema=False)
    def trouvailles_csv() -> Response:
        lignes = [
            [
                t.libelle,
                "oui" if t.favori else "",
                t.verdict or "",
                t.note,
                SOURCES.get(t.source or "", t.source or ""),
                t.modifie_le,
                t.mention_id,
                t.acte_id,
            ]
            for t in etat.carnet.toutes()
        ]
        entete = [
            "notice",
            "favori",
            "verdict",
            "note",
            "source",
            "modifiée le",
            "mention_id",
            "acte_id",
        ]
        return csv_reponse(lignes, entete, "trouvailles.csv")

    # --- API JSON ------------------------------------------------------------------------

    @application.get("/api/recherche", tags=["recherche"])
    def api_recherche(requete_http: Request) -> JSONResponse:
        """Résultats classés ; mêmes paramètres que la page de recherche."""
        formulaire = Formulaire.depuis(requete_http.query_params)
        try:
            with etat.verrou:
                _, classes, moteur = classer(formulaire)
                retenus = filtrer(classes, formulaire)
                debut = (formulaire.page - 1) * PAR_PAGE
                affiches = retenus[debut : debut + PAR_PAGE]
                fiches = moteur.fiches([r.mention_id for r in affiches])
        except FormulaireInvalide as erreur:
            return JSONResponse({"erreurs": erreur.erreurs}, status_code=422)
        resultats = []
        for r in affiches:
            donnees = _resultat_json(r)
            donnees["fiche"] = jsonable_encoder(fiches.get(r.mention_id, {}))
            resultats.append(donnees)
        return JSONResponse(
            {
                "total": len(retenus),
                "page": formulaire.page,
                "par_page": PAR_PAGE,
                "facettes": jsonable_encoder(facettes(classes)),
                "resultats": resultats,
            }
        )

    @application.get("/api/actes/{acte_id}", tags=["recherche"])
    def api_acte(acte_id: str) -> JSONResponse:
        """Un acte et toutes les personnes qui y figurent."""
        with etat.verrou:
            moteur = etat.moteur()
            trouve = moteur.acte(acte_id) if moteur else None
        if trouve is None:
            return JSONResponse({"erreur": "acte introuvable"}, status_code=404)
        acte, mentions = trouve
        return JSONResponse(jsonable_encoder({"acte": acte, "mentions": mentions}))

    @application.get("/api/lieux", tags=["référentiel"])
    def api_lieux(q: str = "") -> JSONResponse:
        """Suggestions de communes et de départements pour l'autocomplétion."""
        if etat.referentiel is None:
            return JSONResponse([])
        return JSONResponse(
            [{"libelle": s.libelle, "valeur": s.valeur} for s in etat.referentiel.suggerer(q)]
        )

    return application
