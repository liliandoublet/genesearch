"""Sauvegarde et restauration de tes données personnelles : trouvailles et relevés.

Tout le reste se reconstruit (``doudoumil pipeline``), mais pas ces deux dossiers :

- ``data/perso/`` : « Mes trouvailles » (``trouvailles.sqlite``) ;
- ``data/releves/`` : tes tableurs de relevés et leurs fichiers de correspondance.

Une sauvegarde est une archive zip datée qui contient ces dossiers et un fichier
``sauvegarde.json`` qui la décrit. La base des trouvailles y est copiée par l'API de
sauvegarde de SQLite : la copie est cohérente même si l'interface web écrit au même moment.

La restauration remplace les dossiers présents dans l'archive, après avoir sauvegardé l'état
actuel : une restauration malencontreuse se défait en restaurant cette sauvegarde-là.
"""

import io
import json
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

DOSSIERS: Final = ("perso", "releves")
MANIFESTE: Final = "sauvegarde.json"
APPLICATION: Final = "doudoumil-search"
# fichiers temporaires de SQLite : la copie par l'API de sauvegarde les rend inutiles
SUFFIXES_SQLITE_IGNORES: Final = ("-journal", "-wal", "-shm")


class SauvegardeInvalide(ValueError):
    """Archive qui n'est pas une sauvegarde doudoumil, ou dont un chemin sortirait de data/."""


@dataclass(frozen=True)
class Contenu:
    """Ce que contient une sauvegarde."""

    dossiers: tuple[str, ...]
    fichiers: tuple[str, ...]
    trouvailles: int


def _copie_sqlite(chemin: Path) -> tuple[bytes, int]:
    """Copie cohérente d'une base SQLite, et le nombre de trouvailles qu'elle contient."""
    source = sqlite3.connect(chemin)
    copie = sqlite3.connect(":memory:")
    try:
        source.backup(copie)
        try:
            (nombre,) = copie.execute("SELECT count(*) FROM trouvailles").fetchone()
        except sqlite3.OperationalError:  # autre base que celle des trouvailles
            nombre = 0
        return copie.serialize(), int(nombre)
    finally:
        copie.close()
        source.close()


def ecrire_sauvegarde(racine: Path, sortie: Path | IO[bytes]) -> Contenu:
    """Écrit l'archive de sauvegarde des dossiers personnels de ``racine`` dans ``sortie``."""
    dossiers = tuple(d for d in DOSSIERS if (racine / d).is_dir())
    fichiers: list[str] = []
    trouvailles = 0
    with zipfile.ZipFile(sortie, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for dossier in dossiers:
            for fichier in sorted((racine / dossier).rglob("*")):
                if not fichier.is_file() or fichier.name.endswith(SUFFIXES_SQLITE_IGNORES):
                    continue
                nom = fichier.relative_to(racine).as_posix()
                if fichier.suffix == ".sqlite":
                    octets, nombre = _copie_sqlite(fichier)
                    archive.writestr(nom, octets)
                    trouvailles += nombre
                else:
                    archive.write(fichier, nom)
                fichiers.append(nom)
        contenu = Contenu(dossiers, tuple(fichiers), trouvailles)
        manifeste = {
            "application": APPLICATION,
            "version": version(APPLICATION),
            "creee_le": datetime.now(UTC).isoformat(timespec="seconds"),
            "dossiers": list(contenu.dossiers),
            "fichiers": list(contenu.fichiers),
            "trouvailles": contenu.trouvailles,
        }
        archive.writestr(MANIFESTE, json.dumps(manifeste, ensure_ascii=False, indent=2))
    return contenu


def sauvegarder(racine: Path, destination: Path | None = None) -> tuple[Path, Contenu]:
    """Crée ``doudoumil-AAAAMMJJ-HHMMSS.zip`` dans ``destination`` (``data/sauvegardes/``)."""
    destination = destination or racine / "sauvegardes"
    destination.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    chemin = destination / f"doudoumil-{horodatage}.zip"
    rang = 1
    while chemin.exists():  # deux sauvegardes dans la même seconde
        rang += 1
        chemin = destination / f"doudoumil-{horodatage}-{rang}.zip"
    temporaire = chemin.with_name(chemin.name + ".en-cours")
    try:
        contenu = ecrire_sauvegarde(racine, temporaire)
        temporaire.replace(chemin)
    finally:
        temporaire.unlink(missing_ok=True)
    return chemin, contenu


def lire_manifeste(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Description de la sauvegarde ; refuse une archive qui n'en est pas une."""
    try:
        manifeste = json.loads(archive.read(MANIFESTE))
    except (KeyError, ValueError):
        raise SauvegardeInvalide("ce n'est pas une sauvegarde doudoumil") from None
    if not isinstance(manifeste, dict) or manifeste.get("application") != APPLICATION:
        raise SauvegardeInvalide("ce n'est pas une sauvegarde doudoumil")
    return manifeste


def _verifier_chemins(archive: zipfile.ZipFile) -> None:
    """Chaque fichier doit rester dans perso/ ou releves/ (pas de ``..`` ni de chemin absolu)."""
    for nom in archive.namelist():
        if nom == MANIFESTE:
            continue
        chemin = PurePosixPath(nom)
        if (
            chemin.is_absolute()
            or "\\" in nom
            or ".." in chemin.parts
            or chemin.parts[0] not in DOSSIERS
        ):
            raise SauvegardeInvalide(f"chemin refusé dans l'archive : {nom}")


def restaurer(racine: Path, archive_zip: Path) -> tuple[Contenu, Path | None]:
    """Remplace les dossiers personnels par ceux de la sauvegarde.

    Renvoie le contenu restauré et la sauvegarde de l'état précédent (``None`` s'il n'y avait
    rien à sauvegarder). Les dossiers absents de l'archive ne sont pas touchés.
    """
    with zipfile.ZipFile(archive_zip) as archive:
        manifeste = lire_manifeste(archive)
        _verifier_chemins(archive)
        dossiers = tuple(d for d in manifeste.get("dossiers", []) if d in DOSSIERS)

        precedente = None
        if any((racine / d).is_dir() and any((racine / d).iterdir()) for d in DOSSIERS):
            precedente, _ = sauvegarder(racine)

        travail = racine / ".restauration-en-cours"
        if travail.exists():
            shutil.rmtree(travail)
        travail.mkdir(parents=True)
        try:
            for nom in archive.namelist():
                if nom != MANIFESTE and not nom.endswith("/"):
                    cible = travail / nom
                    cible.parent.mkdir(parents=True, exist_ok=True)
                    cible.write_bytes(archive.read(nom))
            for dossier in dossiers:
                (travail / dossier).mkdir(exist_ok=True)  # dossier vide à la sauvegarde
                if (racine / dossier).exists():
                    shutil.rmtree(racine / dossier)
                (travail / dossier).rename(racine / dossier)
        finally:
            shutil.rmtree(travail, ignore_errors=True)
    fichiers = tuple(
        nom for nom in manifeste.get("fichiers", []) if PurePosixPath(nom).parts[0] in dossiers
    )
    return Contenu(dossiers, fichiers, int(manifeste.get("trouvailles", 0))), precedente


def octets_de_sauvegarde(racine: Path) -> bytes:
    """Archive de sauvegarde en mémoire, pour la télécharger depuis l'interface web."""
    tampon = io.BytesIO()
    ecrire_sauvegarde(racine, tampon)
    return tampon.getvalue()
