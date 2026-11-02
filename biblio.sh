#!/bin/sh
# Lance la CLI avec l'environnement uv rangé hors du projet.
# Usage : ./biblio.sh <commande> [options]   (ex. ./biblio.sh serve)
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.virtualenvs/uv/bibliotheque}"
exec uv run --project "$(dirname "$0")" biblio "$@"
