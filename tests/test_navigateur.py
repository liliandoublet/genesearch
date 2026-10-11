"""Parcours dans un vrai navigateur (Chromium piloté par Playwright).

Le serveur tourne dans un fil d'exécution, sur un port libre. Chromium est cherché dans
``$DOUDOUMIL_CHROMIUM``, puis à l'emplacement préinstallé de l'environnement de développement,
puis là où ``playwright install chromium`` le range ; sans navigateur, ces tests sont sautés.
"""

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from doudoumil_search.api.application import creer_application
from jeu_recherche import construire_racine

playwright_sync = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.navigateur


def _chromium() -> str | None:
    for candidat in (os.environ.get("DOUDOUMIL_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if candidat and Path(candidat).exists():
            return candidat
    return None  # emplacement par défaut de Playwright


@pytest.fixture(scope="module")
def adresse(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    racine = tmp_path_factory.mktemp("navigateur")
    construire_racine(racine)
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        port = prise.getsockname()[1]
    serveur = uvicorn.Server(
        uvicorn.Config(creer_application(racine), host="127.0.0.1", port=port, log_level="error")
    )
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    limite = time.monotonic() + 10
    while not serveur.started:
        if time.monotonic() > limite:
            raise RuntimeError("le serveur de test n'a pas démarré")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=10)


@pytest.fixture(scope="module")
def navigateur() -> Iterator[object]:
    with playwright_sync.sync_playwright() as p:
        try:
            instance = p.chromium.launch(executable_path=_chromium())
        except playwright_sync.Error as erreur:
            pytest.skip(f"Chromium indisponible : {erreur}")
        yield instance
        instance.close()


@pytest.fixture
def page(navigateur: object, adresse: str) -> Iterator[object]:
    contexte = navigateur.new_context(  # type: ignore[attr-defined]
        base_url=adresse, permissions=["clipboard-read", "clipboard-write"]
    )
    une_page = contexte.new_page()
    erreurs: list[str] = []
    une_page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
    une_page.on("pageerror", lambda e: erreurs.append(str(e)))
    yield une_page
    contexte.close()
    assert not erreurs, f"erreurs JavaScript : {erreurs}"


def test_parcours_complet(page: object) -> None:
    p = page  # type: ignore[assignment]
    p.goto("/")  # type: ignore[attr-defined]
    p.fill("#q", "LE GOFF Marie")  # type: ignore[attr-defined]
    p.click("summary")  # type: ignore[attr-defined]
    p.fill("input[name=naissance]", "1931")  # type: ignore[attr-defined]

    # autocomplétion du lieu
    p.fill("input[name=lieu]", "quimp")  # type: ignore[attr-defined]
    p.wait_for_function(  # type: ignore[attr-defined]
        "document.querySelectorAll('#suggestions-lieux option').length > 0"
    )
    assert p.get_attribute("#suggestions-lieux option", "value") == "Quimper (29)"  # type: ignore[attr-defined]
    p.fill("input[name=lieu]", "Quimper (29)")  # type: ignore[attr-defined]
    p.click("button[type=submit]")  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: "/recherche?" in url)  # type: ignore[attr-defined]
    # les champs vides ne sont pas envoyés
    assert "nom=" not in p.url and "naissance=1931" in p.url  # type: ignore[attr-defined]
    premier = p.locator("ol.liste > li").first  # type: ignore[attr-defined]
    assert "LE GOFF MARIE JOSEPHE" in premier.inner_text()

    # favori et verdict, sans quitter la page de résultats
    premier.locator("button[value=favori]").click()
    p.wait_for_load_state()  # type: ignore[attr-defined]
    premier = p.locator("ol.liste > li").first  # type: ignore[attr-defined]
    assert premier.locator("button[value=favori]").get_attribute("aria-pressed") == "true"
    premier.locator("button[value=oui]").click()
    p.wait_for_load_state()  # type: ignore[attr-defined]

    # fiche : citation copiée, note enregistrée
    p.locator("ol.liste > li").first.locator("a.nom").click()  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: "/actes/" in url)  # type: ignore[attr-defined]
    assert "Décès le 15/01/2020 à Rennes (35)" in p.inner_text("h1")  # type: ignore[attr-defined]
    p.click("button.copier")  # type: ignore[attr-defined]
    p.wait_for_function(  # type: ignore[attr-defined]
        "document.querySelector('button.copier').textContent.startsWith('Copiée')"
    )
    copie = p.evaluate("navigator.clipboard.readText()")  # type: ignore[attr-defined]
    assert copie.startswith("LE GOFF MARIE JOSEPHE, décès le 15/01/2020 à Rennes (35).")
    p.fill("textarea[name=note]", "chercher l'acte de naissance à Quimper")  # type: ignore[attr-defined]
    p.click("button[value=note]")  # type: ignore[attr-defined]
    p.wait_for_load_state()  # type: ignore[attr-defined]
    assert "Quimper" in p.input_value("textarea[name=note]")  # type: ignore[attr-defined]

    # le dossier actif (« Personnel ») a gardé la notice
    p.click("text=Dossier : Personnel")  # type: ignore[attr-defined]
    texte = p.inner_text("main")  # type: ignore[attr-defined]
    assert "LE GOFF MARIE JOSEPHE" in texte
    assert "chercher l'acte de naissance à Quimper" in texte
    assert "c'est bien lui / elle" in texte
    assert "favori" in texte


def test_affichage_sur_telephone(page: object) -> None:
    p = page  # type: ignore[assignment]
    p.set_viewport_size({"width": 390, "height": 844})  # type: ignore[attr-defined]
    p.goto("/recherche?q=LE+GOFF")  # type: ignore[attr-defined]
    debordement = p.evaluate(  # type: ignore[attr-defined]
        "document.documentElement.scrollWidth > window.innerWidth"
    )
    assert not debordement


def test_parcours_dossier(page: object) -> None:
    """Créer un dossier, y chercher une personne, garder une notice, en saisir une, supprimer."""
    p = page  # type: ignore[assignment]
    p.goto("/dossiers")  # type: ignore[attr-defined]
    p.fill("input[name=nom]", "Famille Moreau")  # type: ignore[attr-defined]
    p.click("text=Créer et activer")  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: url.endswith("/dossiers/famille-moreau"))  # type: ignore[attr-defined]
    assert "Dossier : Famille Moreau" in p.inner_text("header")  # type: ignore[attr-defined]

    # personne recherchée, puis recherche lancée depuis elle
    p.fill("#ajout-personne input[name=nom]", "MOREAU")  # type: ignore[attr-defined]
    p.fill("#ajout-personne input[name=prenoms]", "Jean")  # type: ignore[attr-defined]
    p.fill("#ajout-personne input[name=naissance]", "1925")  # type: ignore[attr-defined]
    p.click("#ajout-personne button")  # type: ignore[attr-defined]
    p.wait_for_load_state()  # type: ignore[attr-defined]
    p.click("a.bouton:has-text('Chercher')")  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: "/recherche?" in url)  # type: ignore[attr-defined]
    assert "Recherche pour MOREAU Jean" in p.inner_text(".bandeau")  # type: ignore[attr-defined]
    premier = p.locator("ol.liste > li").first  # type: ignore[attr-defined]
    assert "MOREAU JEAN" in premier.inner_text()
    premier.locator("button[value=favori]").click()
    p.wait_for_load_state()  # type: ignore[attr-defined]

    # la notice est rangée sous la personne
    p.click("text=Dossier : Famille Moreau")  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: "/dossiers/famille-moreau" in url)  # type: ignore[attr-defined]
    texte = p.inner_text("main")  # type: ignore[attr-defined]
    assert "notice de l'atelier" in texte
    assert "Notices non rattachées" not in texte

    # acte trouvé sur Filae, saisi à la main et rattaché à la personne
    p.click("#ajout-notice summary")  # type: ignore[attr-defined]
    p.select_option("#ajout-notice select[name=personne]", label="MOREAU Jean")  # type: ignore[attr-defined]
    p.select_option("#ajout-notice select[name=type]", "naissance")  # type: ignore[attr-defined]
    p.fill("#ajout-notice input[name=date]", "1925")  # type: ignore[attr-defined]
    p.fill("#ajout-notice input[name=personnes]", "MOREAU Jean, fils de Louis")  # type: ignore[attr-defined]
    p.fill("#ajout-notice input[name=site]", "Filae")  # type: ignore[attr-defined]
    p.click("#ajout-notice button")  # type: ignore[attr-defined]
    p.wait_for_load_state()  # type: ignore[attr-defined]
    texte = p.inner_text("#p-1")  # type: ignore[attr-defined]
    assert "repérée sur Filae" in texte
    assert "MOREAU Jean, fils de Louis, naissance 1925. index Filae." in texte

    # fin de mission : suppression complète, confirmée par l'identifiant
    p.fill("input[name=confirmation]", "famille-moreau")  # type: ignore[attr-defined]
    p.click("text=Supprimer définitivement")  # type: ignore[attr-defined]
    p.wait_for_url(lambda url: url.endswith("/dossiers"))  # type: ignore[attr-defined]
    assert "Famille Moreau" not in p.inner_text("main")  # type: ignore[attr-defined]
    assert "Dossier : Personnel" in p.inner_text("header")  # type: ignore[attr-defined]
