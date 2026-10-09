#!/usr/bin/env bash
# Hook Stop : en fin de run, bloque l'arrêt une fois si du code a changé depuis la dernière
# mise à jour de CLAUDE.md, pour que Claude mette à jour l'état du projet avant de rendre la main.
#
# « Changé » = fichiers de src/, tests/, notebooks/, pyproject.toml ou main.py modifiés (commités
# ou non) ou ajoutés depuis le dernier commit qui touche CLAUDE.md. Si CLAUDE.md est lui-même
# modifié dans l'arbre de travail, on considère la mise à jour faite.

set -u

entree=$(cat)

# Deuxième passage après un blocage : on laisse s'arrêter pour éviter toute boucle.
if printf '%s' "$entree" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

reference=$(git log -1 --format=%H -- CLAUDE.md 2>/dev/null)
if [ -z "$reference" ]; then
    # CLAUDE.md n'a jamais été commité : on compare à l'arbre vide.
    reference=$(git hash-object -t tree /dev/null)
fi

modifies=$(
    {
        git diff --name-only "$reference" 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u
)

if printf '%s\n' "$modifies" | grep -qx 'CLAUDE.md'; then
    exit 0
fi

code=$(printf '%s\n' "$modifies" | grep -E '^(src/|tests/|notebooks/|pyproject\.toml$|main\.py$)' | head -n 10)
[ -z "$code" ] && exit 0

liste=$(printf '%s' "$code" | tr '\n' ' ')
cat <<EOF
{"decision": "block", "reason": "Du code a changé depuis la dernière mise à jour de CLAUDE.md (${liste}). Avant de terminer : mets à jour la section « État du projet » et le journal de CLAUDE.md, coche les tâches faites dans PLAN.md, puis commite ces fichiers avec le reste du travail. Si rien ne mérite d'être noté, ajoute au moins une ligne au journal."}
EOF
exit 0
