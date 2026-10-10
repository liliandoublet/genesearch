"""Téléchargement des fichiers sources depuis data.gouv.fr.

Le catalogue d'un jeu de données est lu par l'API publique de data.gouv.fr, qui donne pour
chaque ressource son adresse, sa taille et, souvent, une somme de contrôle. Le téléchargement
reprend là où il s'était arrêté (requête ``Range``) et vérifie la somme de contrôle avant de
publier le fichier : un fichier présent dans le dossier est donc toujours complet.

L'identifiant du jeu de données INSEE (``fichier-des-personnes-decedees``) et la forme des noms
de fichiers sont à revérifier sur data.gouv.fr : ils n'étaient pas accessibles lors de
l'écriture.
"""

import hashlib
import json
import logging
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

journal = logging.getLogger(__name__)

API_INSEE_DECES: Final = "https://www.data.gouv.fr/api/1/datasets/fichier-des-personnes-decedees/"
AGENT: Final = "doudoumil-search (moteur de recherche généalogique personnel)"
TAILLE_BLOC: Final = 1 << 20

# deces-2020.txt, deces-2024-m03.txt, éventuellement compressés en .zip
MOTIF_FICHIER_DECES: Final = re.compile(r"deces-(\d{4})(?:-m(\d{2}))?\.(txt|zip)$", re.IGNORECASE)


class Reponse(Protocol):
    status: int

    def read(self, taille: int = -1) -> bytes: ...
    def __enter__(self) -> "Reponse": ...
    def __exit__(self, *args: object) -> None: ...


Ouvreur = Callable[[Request], Reponse]


class SommeIncorrecte(RuntimeError):
    """Le fichier téléchargé ne correspond pas à la somme de contrôle annoncée."""


@dataclass(frozen=True)
class Ressource:
    """Fichier proposé par un jeu de données data.gouv.fr."""

    nom: str
    url: str
    taille: int | None = None
    somme_type: str | None = None
    somme_valeur: str | None = None

    @property
    def annee(self) -> int | None:
        correspondance = MOTIF_FICHIER_DECES.search(self.nom)
        return int(correspondance.group(1)) if correspondance else None


def _ouvrir(requete: Request) -> Reponse:
    return urlopen(requete, timeout=60)  # type: ignore[no-any-return]


def _requete(url: str, entetes: dict[str, str] | None = None) -> Request:
    return Request(url, headers={"User-Agent": AGENT, **(entetes or {})})


def nom_de_fichier(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def lister_ressources_insee(
    url_api: str = API_INSEE_DECES,
    annees: Iterable[int] | None = None,
    ouvrir: Ouvreur = _ouvrir,
) -> list[Ressource]:
    """Ressources du fichier des décès, triées par nom, éventuellement filtrées par année."""
    with ouvrir(_requete(url_api, {"Accept": "application/json"})) as reponse:
        catalogue: dict[str, Any] = json.loads(reponse.read())
    retenues = set(annees) if annees is not None else None
    ressources = []
    for brute in catalogue.get("resources", []):
        url = brute.get("url") or ""
        nom = nom_de_fichier(url)
        if not MOTIF_FICHIER_DECES.search(nom):
            continue
        somme = brute.get("checksum") or {}
        ressource = Ressource(
            nom=nom,
            url=url,
            taille=brute.get("filesize"),
            somme_type=somme.get("type"),
            somme_valeur=somme.get("value"),
        )
        if retenues is None or ressource.annee in retenues:
            ressources.append(ressource)
    return sorted(ressources, key=lambda r: r.nom)


def telecharger(ressource: Ressource, dossier: Path, ouvrir: Ouvreur = _ouvrir) -> Path:
    """Télécharge une ressource dans ``dossier`` et renvoie le chemin du fichier complet.

    Un fichier déjà présent et conforme n'est pas retéléchargé. Un téléchargement interrompu
    (fichier ``.part``) est repris là où il s'était arrêté.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    final = dossier / ressource.nom
    if final.exists() and _conforme(final, ressource):
        journal.info("%s : déjà téléchargé", ressource.nom)
        return final

    partiel = final.with_name(final.name + ".part")
    deja = partiel.stat().st_size if partiel.exists() else 0
    entetes = {"Range": f"bytes={deja}-"} if deja else {}
    with ouvrir(_requete(ressource.url, entetes)) as reponse:
        # 206 : le serveur reprend ; 200 : il renvoie tout, on repart de zéro.
        mode = "ab" if deja and reponse.status == 206 else "wb"
        with partiel.open(mode) as sortie:
            while bloc := reponse.read(TAILLE_BLOC):
                sortie.write(bloc)

    if not _conforme(partiel, ressource):
        partiel.unlink()
        raise SommeIncorrecte(f"{ressource.nom} : somme de contrôle incorrecte, fichier supprimé")
    partiel.replace(final)
    journal.info("%s : téléchargé", ressource.nom)
    return final


def extraire_si_archive(chemin: Path) -> list[Path]:
    """Extrait les fichiers texte d'une archive zip à côté d'elle ; renvoie les fichiers texte."""
    if chemin.suffix.lower() != ".zip":
        return [chemin]
    extraits = []
    with zipfile.ZipFile(chemin) as archive:
        for membre in archive.infolist():
            nom = Path(membre.filename).name
            if membre.is_dir() or not nom.lower().endswith(".txt"):
                continue
            cible = chemin.parent / nom
            extraits.append(cible)
            if _deja_extrait(cible, membre, chemin):
                continue  # sa date reste celle de la première extraction (doudoumil pipeline)
            with archive.open(membre) as source, cible.open("wb") as sortie:
                while bloc := source.read(TAILLE_BLOC):
                    sortie.write(bloc)
    return extraits


def _deja_extrait(cible: Path, membre: zipfile.ZipInfo, archive: Path) -> bool:
    """Fichier extrait de cette archive-ci : même taille, et plus récent que l'archive."""
    if not cible.exists():
        return False
    etat = cible.stat()
    return etat.st_size == membre.file_size and etat.st_mtime >= archive.stat().st_mtime


def _conforme(chemin: Path, ressource: Ressource) -> bool:
    """Vérifie la somme de contrôle si elle est connue, sinon la taille si elle l'est."""
    if ressource.somme_type and ressource.somme_valeur:
        try:
            empreinte = hashlib.new(ressource.somme_type.lower())
        except ValueError:
            journal.warning("%s : somme %s inconnue", ressource.nom, ressource.somme_type)
        else:
            with chemin.open("rb") as fichier:
                while bloc := fichier.read(TAILLE_BLOC):
                    empreinte.update(bloc)
            return empreinte.hexdigest() == ressource.somme_valeur.lower()
    if ressource.taille is not None:
        return chemin.stat().st_size == ressource.taille
    return True
