"""Tests du téléchargement, contre un petit serveur HTTP local qui imite data.gouv.fr."""

import hashlib
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from doudoumil_search.ingest.telechargement import (
    Ressource,
    SommeIncorrecte,
    extraire_si_archive,
    lister_ressources_insee,
    telecharger,
)

CONTENU_2019 = b"ligne 2019\n" * 1000
CONTENU_2020 = b"ligne 2020\n" * 1000


class Serveur:
    """Sert un catalogue JSON et des fichiers, en gérant les requêtes ``Range``."""

    def __init__(self) -> None:
        self.fichiers: dict[str, bytes] = {}
        self.requetes: list[tuple[str, str | None]] = []
        serveur = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                plage = self.headers.get("Range")
                serveur.requetes.append((self.path, plage))
                if self.path == "/api":
                    corps = json.dumps(serveur.catalogue()).encode()
                    self._repondre(200, corps)
                    return
                contenu = serveur.fichiers.get(self.path.lstrip("/"))
                if contenu is None:
                    self._repondre(404, b"")
                    return
                if plage:
                    debut = int(plage.removeprefix("bytes=").rstrip("-"))
                    self._repondre(206, contenu[debut:])
                else:
                    self._repondre(200, contenu)

            def _repondre(self, statut: int, corps: bytes) -> None:
                self.send_response(statut)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    def catalogue(self) -> dict[str, object]:
        ressources: list[dict[str, object]] = [
            {
                "title": nom,
                "url": f"{self.base}/{nom}",
                "filesize": len(contenu),
                "checksum": {"type": "sha1", "value": hashlib.sha1(contenu).hexdigest()},
            }
            for nom, contenu in self.fichiers.items()
        ]
        ressources.append({"title": "Documentation", "url": f"{self.base}/doc.pdf"})
        return {"resources": ressources}


@pytest.fixture
def serveur() -> Iterator[Serveur]:
    s = Serveur()
    s.fichiers = {"deces-2019.txt": CONTENU_2019, "deces-2020.txt": CONTENU_2020}
    fil = threading.Thread(target=s.http.serve_forever, args=(0.05,), daemon=True)
    fil.start()
    yield s
    s.http.shutdown()


def test_catalogue_filtre_les_fichiers_de_deces(serveur: Serveur) -> None:
    ressources = lister_ressources_insee(f"{serveur.base}/api")
    assert [r.nom for r in ressources] == ["deces-2019.txt", "deces-2020.txt"]
    assert ressources[0].somme_type == "sha1"
    assert ressources[0].taille == len(CONTENU_2019)


def test_catalogue_filtre_par_annee(serveur: Serveur) -> None:
    ressources = lister_ressources_insee(f"{serveur.base}/api", annees=[2020])
    assert [r.nom for r in ressources] == ["deces-2020.txt"]


@pytest.mark.parametrize(
    ("nom", "annee"),
    [("deces-2020.txt", 2020), ("deces-2024-m03.txt", 2024), ("Deces-1975.zip", 1975)],
)
def test_annee_d_une_ressource(nom: str, annee: int) -> None:
    assert Ressource(nom=nom, url="").annee == annee


def test_telechargement_complet(serveur: Serveur, tmp_path: Path) -> None:
    ressource = lister_ressources_insee(f"{serveur.base}/api", annees=[2019])[0]
    chemin = telecharger(ressource, tmp_path)
    assert chemin.read_bytes() == CONTENU_2019
    assert not list(tmp_path.glob("*.part"))


def test_fichier_conforme_non_retelecharge(serveur: Serveur, tmp_path: Path) -> None:
    ressource = lister_ressources_insee(f"{serveur.base}/api", annees=[2019])[0]
    telecharger(ressource, tmp_path)
    nb = len(serveur.requetes)
    telecharger(ressource, tmp_path)
    assert len(serveur.requetes) == nb


def test_reprise_d_un_telechargement_interrompu(serveur: Serveur, tmp_path: Path) -> None:
    ressource = lister_ressources_insee(f"{serveur.base}/api", annees=[2020])[0]
    (tmp_path / "deces-2020.txt.part").write_bytes(CONTENU_2020[:4000])
    chemin = telecharger(ressource, tmp_path)
    assert chemin.read_bytes() == CONTENU_2020
    assert serveur.requetes[-1] == ("/deces-2020.txt", "bytes=4000-")


def test_somme_incorrecte(serveur: Serveur, tmp_path: Path) -> None:
    ressource = Ressource(
        nom="deces-2019.txt",
        url=f"{serveur.base}/deces-2019.txt",
        somme_type="sha1",
        somme_valeur="0" * 40,
    )
    with pytest.raises(SommeIncorrecte):
        telecharger(ressource, tmp_path)
    assert not list(tmp_path.iterdir())


def test_extraction_d_une_archive(tmp_path: Path) -> None:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr("dossier/deces-1975.txt", CONTENU_2019)
        archive.writestr("lisez-moi.pdf", b"%PDF")
    chemin = tmp_path / "deces-1975.zip"
    chemin.write_bytes(tampon.getvalue())
    extraits = extraire_si_archive(chemin)
    assert extraits == [tmp_path / "deces-1975.txt"]
    assert extraits[0].read_bytes() == CONTENU_2019


def test_un_fichier_texte_n_est_pas_extrait(tmp_path: Path) -> None:
    chemin = tmp_path / "deces-2020.txt"
    assert extraire_si_archive(chemin) == [chemin]
