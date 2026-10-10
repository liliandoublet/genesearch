"""``python -m doudoumil_search`` fonctionne, y compris avec le pool de processus."""

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "deces-extrait.txt"


def test_module_executable_avec_pool(tmp_path: Path) -> None:
    for annee in (2020, 2021):
        shutil.copy(FIXTURE, tmp_path / f"deces-{annee}.txt")
    fichiers = [str(tmp_path / f"deces-{annee}.txt") for annee in (2020, 2021)]
    commande = [sys.executable, "-m", "doudoumil_search", "--donnees", str(tmp_path / "d")]
    resultat = subprocess.run(
        [*commande, "ingest", "insee", *fichiers, "--processus", "2"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.count("8 ingérées, 2 rejetées") == 2
