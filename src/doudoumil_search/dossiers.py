"""Dossiers de recherche : un classeur par client ou par famille (jalon 11).

Chaque dossier est un fichier SQLite à part, ``data/perso/dossiers/<identifiant>.sqlite`` :
supprimer, exporter ou sauvegarder un client ne touche jamais les autres. Il contient :

- ``infos`` : nom affiché, client ou famille, description, dates d'ouverture et de clôture ;
- ``personnes`` : les personnes recherchées et ce que l'on sait d'elles ;
- ``trouvailles`` : les notices de l'atelier retenues (favori, note, verdict, requête),
  rattachables à une personne recherchée (voir ``api/trouvailles.py``) ;
- ``notices`` : les actes trouvés ailleurs (Filae, Geneanet, archives…) et saisis à la main.

Une même notice peut figurer dans plusieurs dossiers : elle y est copiée, si bien que supprimer
un dossier n'en affecte aucun autre.

Le dossier actif, celui où l'interface range les trouvailles, est noté dans
``data/perso/dossier-actif``. Le carnet d'avant les dossiers (``data/perso/trouvailles.sqlite``)
devient le dossier « Personnel » à la première ouverture du registre.
"""

import csv
import re
import shutil
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from doudoumil_search.api.trouvailles import Carnet, Trouvaille
from doudoumil_search.normalize.texte import majuscules_ascii
from doudoumil_search.pivot import TypeActe
from doudoumil_search.search import affichage
from doudoumil_search.search.moteur import Moteur

SOUS_DOSSIER: Final = "dossiers"
FICHIER_ACTIF: Final = "dossier-actif"
ANCIEN_CARNET: Final = "trouvailles.sqlite"
PERSONNEL: Final = ("personnel", "Personnel")
MOTIF_IDENTIFIANT: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LONGUEUR_IDENTIFIANT: Final = 60
SEXES: Final = ("", "M", "F")
# fichiers annexes de SQLite, à supprimer avec la base
SUFFIXES_SQLITE: Final = ("-journal", "-wal", "-shm")

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS infos (
    cle TEXT PRIMARY KEY,
    valeur TEXT
);
CREATE TABLE IF NOT EXISTS personnes (
    personne_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL DEFAULT '',
    prenoms TEXT NOT NULL DEFAULT '',
    sexe TEXT NOT NULL DEFAULT '' CHECK (sexe IN ('', 'M', 'F')),
    naissance TEXT NOT NULL DEFAULT '',
    lieu TEXT NOT NULL DEFAULT '',
    conjoint TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    personne_id INTEGER,
    type TEXT NOT NULL,
    date TEXT NOT NULL DEFAULT '',
    lieu TEXT NOT NULL DEFAULT '',
    personnes TEXT NOT NULL DEFAULT '',
    depot TEXT NOT NULL DEFAULT '',
    cote TEXT NOT NULL DEFAULT '',
    vue TEXT NOT NULL DEFAULT '',
    lien TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
"""


class DossierInconnu(LookupError):
    """Aucun dossier ne porte cet identifiant."""


class DossierExistant(ValueError):
    """Un dossier porte déjà cet identifiant."""


def maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def identifiant_de(nom: str) -> str:
    """« Famille Le Goff » → « famille-le-goff » : nom du fichier du dossier."""
    identifiant = re.sub(r"[^a-z0-9]+", "-", majuscules_ascii(nom).lower()).strip("-")
    identifiant = identifiant[:LONGUEUR_IDENTIFIANT].strip("-")
    if not identifiant:
        raise ValueError("le nom du dossier doit contenir au moins une lettre ou un chiffre")
    return identifiant


@dataclass(frozen=True)
class InfosDossier:
    identifiant: str
    nom: str
    client: str
    description: str
    ouvert_le: str
    clos_le: str


@dataclass(frozen=True)
class PersonneRecherchee:
    """Personne visée par un dossier, avec ce que l'on sait d'elle (texte libre)."""

    personne_id: int
    nom: str
    prenoms: str
    sexe: str
    naissance: str  # « 1931 » ou « 1930-1932 », comme dans le formulaire de recherche
    lieu: str
    conjoint: str
    note: str
    cree_le: str
    modifie_le: str

    @property
    def libelle(self) -> str:
        return f"{self.nom} {self.prenoms}".strip() or f"personne n° {self.personne_id}"

    def parametres_recherche(self, dossier: str) -> dict[str, str]:
        """Paramètres de l'adresse ``/recherche`` qui cherchent cette personne.

        ``personne`` vaut « dossier:numéro » : les notices retenues depuis ces résultats vont à
        cette personne de ce dossier, même si le dossier actif change entre-temps.
        """
        valeurs = {
            "nom": self.nom,
            "prenoms": self.prenoms,
            "sexe": self.sexe,
            "naissance": self.naissance,
            "lieu": self.lieu,
            "conjoint": self.conjoint,
            "personne": f"{dossier}:{self.personne_id}",
        }
        return {cle: valeur for cle, valeur in valeurs.items() if valeur}


CHAMPS_PERSONNE: Final = ("nom", "prenoms", "sexe", "naissance", "lieu", "conjoint", "note")


@dataclass(frozen=True)
class NoticeSaisie:
    """Acte trouvé hors de l'atelier (Filae, archives…), saisi à la main."""

    notice_id: str
    personne_id: int | None
    type: str
    date: str
    lieu: str
    personnes: str  # qui figure dans l'acte, tel que lu
    depot: str
    cote: str
    vue: str
    lien: str
    site: str  # où l'acte a été repéré : « Filae », « Geneanet »…
    note: str
    cree_le: str
    modifie_le: str


CHAMPS_NOTICE: Final = (
    "type",
    "date",
    "lieu",
    "personnes",
    "depot",
    "cote",
    "vue",
    "lien",
    "site",
    "note",
)


def personne_visee(
    registre: "Registre", valeur: str
) -> tuple["Dossier", PersonneRecherchee] | None:
    """« famille-le-goff:3 » → le dossier et la personne ; ``None`` si l'un d'eux n'existe pas."""
    identifiant, _, numero = valeur.partition(":")
    if not numero.isdigit() or not registre.existe(identifiant):
        return None
    dossier = registre.ouvrir(identifiant)
    personne = dossier.personne(int(numero))
    return (dossier, personne) if personne else None


class Dossier(Carnet):
    """Un dossier de recherche : ses informations, ses personnes et ses notices.

    Hérite du carnet de trouvailles, qui vit dans le même fichier.
    """

    def __init__(self, chemin: Path) -> None:
        super().__init__(chemin)
        self.identifiant = chemin.stem
        with self._connexion() as connexion:
            connexion.executescript(_SCHEMA)

    # --- informations -------------------------------------------------------------------

    def infos(self) -> InfosDossier:
        with self._connexion() as connexion:
            valeurs = dict(connexion.execute("SELECT cle, valeur FROM infos").fetchall())
        return InfosDossier(
            identifiant=self.identifiant,
            nom=valeurs.get("nom") or self.identifiant,
            client=valeurs.get("client") or "",
            description=valeurs.get("description") or "",
            ouvert_le=valeurs.get("ouvert_le") or "",
            clos_le=valeurs.get("clos_le") or "",
        )

    def modifier_infos(self, **valeurs: str) -> InfosDossier:
        """Change le nom affiché, le client, la description ou les dates."""
        permises = {f.name for f in fields(InfosDossier)} - {"identifiant"}
        if inconnues := set(valeurs) - permises:
            raise ValueError(f"information inconnue : {', '.join(sorted(inconnues))}")
        with self._connexion() as connexion:
            connexion.executemany(
                "INSERT INTO infos (cle, valeur) VALUES (?, ?) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = excluded.valeur",
                [(cle, valeur.strip()) for cle, valeur in valeurs.items()],
            )
        return self.infos()

    # --- personnes recherchées ------------------------------------------------------------

    def personnes(self) -> list[PersonneRecherchee]:
        with self._connexion() as connexion:
            lignes = connexion.execute(
                "SELECT * FROM personnes ORDER BY nom, prenoms, personne_id"
            ).fetchall()
        return [PersonneRecherchee(**dict(ligne)) for ligne in lignes]

    def personne(self, personne_id: int) -> PersonneRecherchee | None:
        with self._connexion() as connexion:
            ligne = connexion.execute(
                "SELECT * FROM personnes WHERE personne_id = ?", (personne_id,)
            ).fetchone()
        return PersonneRecherchee(**dict(ligne)) if ligne else None

    def ajouter_personne(self, **valeurs: str) -> PersonneRecherchee:
        champs = _verifier_personne(valeurs)
        if not (champs.get("nom") or champs.get("prenoms")):
            raise ValueError("indiquez au moins un nom ou un prénom")
        instant = maintenant()
        with self._connexion() as connexion:
            curseur = connexion.execute(
                f"INSERT INTO personnes ({', '.join(champs)}, cree_le, modifie_le) "
                f"VALUES ({', '.join('?' * len(champs))}, ?, ?)",
                (*champs.values(), instant, instant),
            )
            personne_id = curseur.lastrowid
        assert personne_id is not None
        personne = self.personne(personne_id)
        assert personne is not None
        return personne

    def modifier_personne(self, personne_id: int, **valeurs: str) -> PersonneRecherchee:
        champs = _verifier_personne(valeurs)
        if self.personne(personne_id) is None:
            raise LookupError(f"personne inconnue : {personne_id}")
        affectations = ", ".join(f"{champ} = ?" for champ in champs)
        with self._connexion() as connexion:
            connexion.execute(
                f"UPDATE personnes SET {affectations}, modifie_le = ? WHERE personne_id = ?",
                (*champs.values(), maintenant(), personne_id),
            )
        personne = self.personne(personne_id)
        assert personne is not None
        return personne

    def supprimer_personne(self, personne_id: int) -> None:
        """Supprime la personne ; ses notices restent dans le dossier, sans rattachement."""
        with self._connexion() as connexion:
            connexion.execute(
                "UPDATE trouvailles SET personne_id = NULL WHERE personne_id = ?", (personne_id,)
            )
            connexion.execute(
                "UPDATE notices SET personne_id = NULL WHERE personne_id = ?", (personne_id,)
            )
            connexion.execute("DELETE FROM personnes WHERE personne_id = ?", (personne_id,))

    # --- notices saisies à la main --------------------------------------------------------

    def notices(self) -> list[NoticeSaisie]:
        with self._connexion() as connexion:
            lignes = connexion.execute(
                "SELECT * FROM notices ORDER BY cree_le, notice_id"
            ).fetchall()
        return [NoticeSaisie(**dict(ligne)) for ligne in lignes]

    def notice(self, notice_id: str) -> NoticeSaisie | None:
        with self._connexion() as connexion:
            ligne = connexion.execute(
                "SELECT * FROM notices WHERE notice_id = ?", (notice_id,)
            ).fetchone()
        return NoticeSaisie(**dict(ligne)) if ligne else None

    def ajouter_notice(self, personne_id: int | None = None, **valeurs: str) -> NoticeSaisie:
        champs = _verifier_notice(valeurs)
        if not (champs.get("personnes") or champs.get("date") or champs.get("cote")):
            raise ValueError("indiquez au moins les personnes, la date ou la cote de l'acte")
        if personne_id is not None and self.personne(personne_id) is None:
            raise LookupError(f"personne inconnue : {personne_id}")
        notice_id = uuid.uuid4().hex
        instant = maintenant()
        with self._connexion() as connexion:
            connexion.execute(
                f"INSERT INTO notices (notice_id, personne_id, {', '.join(champs)}, cree_le, "
                f"modifie_le) VALUES (?, ?, {', '.join('?' * len(champs))}, ?, ?)",
                (notice_id, personne_id, *champs.values(), instant, instant),
            )
        notice = self.notice(notice_id)
        assert notice is not None
        return notice

    def rattacher_notice(self, notice_id: str, personne_id: int | None) -> None:
        with self._connexion() as connexion:
            connexion.execute(
                "UPDATE notices SET personne_id = ?, modifie_le = ? WHERE notice_id = ?",
                (personne_id, maintenant(), notice_id),
            )

    def supprimer_notice(self, notice_id: str) -> None:
        with self._connexion() as connexion:
            connexion.execute("DELETE FROM notices WHERE notice_id = ?", (notice_id,))


def _verifier_personne(valeurs: Mapping[str, str]) -> dict[str, str]:
    if inconnus := set(valeurs) - set(CHAMPS_PERSONNE):
        raise ValueError(f"champ inconnu : {', '.join(sorted(inconnus))}")
    champs = {cle: (valeur or "").strip() for cle, valeur in valeurs.items()}
    if champs.get("sexe", "") not in SEXES:
        raise ValueError("sexe attendu : M, F ou vide")
    return champs


def _verifier_notice(valeurs: Mapping[str, str]) -> dict[str, str]:
    if inconnus := set(valeurs) - set(CHAMPS_NOTICE):
        raise ValueError(f"champ inconnu : {', '.join(sorted(inconnus))}")
    champs = {cle: (valeur or "").strip() for cle, valeur in valeurs.items()}
    champs["type"] = champs.get("type") or TypeActe.AUTRE.value
    if champs["type"] not in {t.value for t in TypeActe}:
        raise ValueError(f"type d'acte inconnu : « {champs['type']} »")
    return champs


# --- registre des dossiers ---------------------------------------------------------------


class Registre:
    """Les dossiers de recherche d'un utilisateur, dans ``data/perso/``."""

    def __init__(self, perso: Path) -> None:
        self.perso = perso
        self.dossier = perso / SOUS_DOSSIER
        self.dossier.mkdir(parents=True, exist_ok=True)
        self._reprendre_ancien_carnet()

    def _chemin(self, identifiant: str) -> Path:
        if not MOTIF_IDENTIFIANT.fullmatch(identifiant):
            raise DossierInconnu(f"identifiant de dossier invalide : « {identifiant} »")
        return self.dossier / f"{identifiant}.sqlite"

    def _reprendre_ancien_carnet(self) -> None:
        """Le carnet d'avant les dossiers devient le dossier « Personnel », sans perte."""
        ancien = self.perso / ANCIEN_CARNET
        if not ancien.exists():
            return
        identifiant, nom = PERSONNEL
        rang = 1
        while self._chemin(identifiant).exists():
            rang += 1
            identifiant = f"{PERSONNEL[0]}-{rang}"
        for suffixe in ("", *SUFFIXES_SQLITE):
            source = ancien.with_name(ancien.name + suffixe)
            if source.exists():
                source.rename(self._chemin(identifiant).with_name(f"{identifiant}.sqlite{suffixe}"))
        dossier = Dossier(self._chemin(identifiant))
        dossier.modifier_infos(
            nom=nom if rang == 1 else f"{nom} ({rang})",
            description="Trouvailles enregistrées avant les dossiers de recherche",
            ouvert_le=maintenant(),
        )

    def identifiants(self) -> list[str]:
        return sorted(
            chemin.stem
            for chemin in self.dossier.glob("*.sqlite")
            if MOTIF_IDENTIFIANT.fullmatch(chemin.stem)
        )

    def dossiers(self) -> list[InfosDossier]:
        return [self.ouvrir(identifiant).infos() for identifiant in self.identifiants()]

    def existe(self, identifiant: str) -> bool:
        return MOTIF_IDENTIFIANT.fullmatch(identifiant) is not None and (
            self._chemin(identifiant).exists()
        )

    def ouvrir(self, identifiant: str) -> Dossier:
        if not self.existe(identifiant):
            raise DossierInconnu(f"dossier inconnu : « {identifiant} »")
        return Dossier(self._chemin(identifiant))

    def creer(self, nom: str, client: str = "", description: str = "") -> Dossier:
        identifiant = identifiant_de(nom)
        if self.existe(identifiant):
            raise DossierExistant(f"un dossier « {identifiant} » existe déjà")
        dossier = Dossier(self._chemin(identifiant))
        dossier.modifier_infos(
            nom=nom.strip(), client=client, description=description, ouvert_le=maintenant()
        )
        return dossier

    # --- dossier actif ------------------------------------------------------------------

    def actif(self) -> Dossier:
        """Le dossier actif ; à défaut le premier, et « Personnel » s'il n'y en a aucun."""
        fichier = self.perso / FICHIER_ACTIF
        choisi = fichier.read_text(encoding="utf-8").strip() if fichier.exists() else ""
        if choisi and self.existe(choisi):
            return self.ouvrir(choisi)
        identifiants = self.identifiants()
        if PERSONNEL[0] in identifiants:
            return self.ouvrir(PERSONNEL[0])
        if identifiants:
            return self.ouvrir(identifiants[0])
        return self.creer(PERSONNEL[1])

    def activer(self, identifiant: str) -> Dossier:
        dossier = self.ouvrir(identifiant)
        (self.perso / FICHIER_ACTIF).write_text(identifiant + "\n", encoding="utf-8")
        return dossier

    # --- suppression, export, import ----------------------------------------------------

    def supprimer(self, identifiant: str) -> None:
        """Supprime définitivement le dossier et toutes ses données (fin de mission)."""
        chemin = self.ouvrir(identifiant).chemin
        for suffixe in ("", *SUFFIXES_SQLITE):
            chemin.with_name(chemin.name + suffixe).unlink(missing_ok=True)
        fichier = self.perso / FICHIER_ACTIF
        if fichier.exists() and fichier.read_text(encoding="utf-8").strip() == identifiant:
            fichier.unlink()

    def exporter(self, identifiant: str, destination: Path) -> Path:
        """Copie complète et cohérente du dossier (``<identifiant>.sqlite``), réimportable."""
        source = self.ouvrir(identifiant).chemin
        destination.mkdir(parents=True, exist_ok=True)
        cible = destination / source.name
        if cible.exists():
            raise FileExistsError(f"{cible} existe déjà")
        with closing(sqlite3.connect(source)) as depuis, closing(sqlite3.connect(cible)) as vers:
            depuis.backup(vers)
        return cible

    def importer(self, fichier: Path) -> Dossier:
        """Ajoute un dossier exporté ; refuse d'en remplacer un existant."""
        if not fichier.is_file():
            raise FileNotFoundError(f"{fichier} introuvable")
        try:
            with closing(sqlite3.connect(f"file:{fichier}?mode=ro", uri=True)) as connexion:
                tables = {nom for (nom,) in connexion.execute("SELECT name FROM sqlite_master")}
        except sqlite3.DatabaseError as erreur:
            raise ValueError(f"{fichier.name} : ce n'est pas un dossier ({erreur})") from None
        if not {"infos", "personnes", "notices", "trouvailles"} <= tables:
            raise ValueError(f"{fichier.name} : ce n'est pas un dossier de recherche")
        identifiant = identifiant_de(fichier.stem)
        if self.existe(identifiant):
            raise DossierExistant(
                f"un dossier « {identifiant} » existe déjà : supprimez-le ou renommez le fichier"
            )
        shutil.copyfile(fichier, self._chemin(identifiant))
        return self.ouvrir(identifiant)

    # --- ensemble des dossiers -------------------------------------------------------------

    def verdicts(self) -> list[Trouvaille]:
        """Verdicts de tous les dossiers : exemples réels pour la calibration (R5)."""
        return [
            t for identifiant in self.identifiants() for t in self.ouvrir(identifiant).verdicts()
        ]


# --- export ------------------------------------------------------------------------------

ENTETE_EXPORT: Final = [
    "personne recherchée",
    "nature",
    "notice",
    "citation",
    "source",
    "favori",
    "verdict",
    "note",
    "lien",
    "identifiant",
]


def lignes_export(
    dossier: Dossier, citations: Mapping[str, str] | None = None, consulte_le: date | None = None
) -> list[list[str]]:
    """Le dossier en tableau, une ligne par notice, groupé par personne recherchée.

    ``citations`` donne la citation des notices de l'atelier (calculée depuis la base de
    recherche quand elle est présente) ; une personne sans notice a sa propre ligne.
    """
    citations = citations or {}
    consulte_le = consulte_le or date.today()
    personnes = dossier.personnes()
    rang = {p.personne_id: i for i, p in enumerate(personnes)}
    libelles = {p.personne_id: p.libelle for p in personnes}
    lignes: list[tuple[int, list[str]]] = []
    for t in dossier.toutes():
        lignes.append(
            (
                rang.get(t.personne_id or -1, len(rang)),
                [
                    libelles.get(t.personne_id or -1, ""),
                    "notice de l'atelier",
                    t.libelle,
                    citations.get(t.mention_id, ""),
                    affichage.SOURCES.get(t.source or "", t.source or ""),
                    "oui" if t.favori else "",
                    t.verdict or "",
                    t.note,
                    "",
                    t.mention_id,
                ],
            )
        )
    for n in dossier.notices():
        lignes.append(
            (
                rang.get(n.personne_id or -1, len(rang)),
                [
                    libelles.get(n.personne_id or -1, ""),
                    "notice saisie",
                    ", ".join(
                        m
                        for m in (
                            n.personnes,
                            affichage.EVENEMENTS.get(n.type, "acte"),
                            n.date,
                            n.lieu,
                        )
                        if m
                    ),
                    affichage.citation_saisie(n, consulte_le),
                    n.site,
                    "",
                    "",
                    n.note,
                    n.lien,
                    n.notice_id,
                ],
            )
        )
    avec_notice = {ligne[0] for ligne in lignes}
    for p in personnes:
        if rang[p.personne_id] not in avec_notice:
            lignes.append(
                (
                    rang[p.personne_id],
                    [p.libelle, "personne recherchée", "", "", "", "", "", p.note, "", ""],
                )
            )
    return [ligne for _, ligne in sorted(lignes, key=lambda e: e[0])]


def citations_atelier(moteur: Moteur, dossier: Dossier, consulte_le: date) -> dict[str, str]:
    """Citations des notices de l'atelier retenues dans le dossier, lues dans la base."""
    fiches = moteur.fiches([t.mention_id for t in dossier.toutes()])
    return {mention: affichage.citation(fiche, consulte_le) for mention, fiche in fiches.items()}


def ecrire_export(dossier: Dossier, chemin: Path, citations: Mapping[str, str]) -> Path:
    """Tableau du dossier en CSV (séparateur « ; », UTF-8 avec BOM pour les tableurs)."""
    with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
        ecrivain = csv.writer(fichier, delimiter=";")
        ecrivain.writerow(ENTETE_EXPORT)
        ecrivain.writerows(lignes_export(dossier, citations))
    return chemin
