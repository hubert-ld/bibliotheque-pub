@echo off
rem Lance la CLI avec uv, sous Windows. Usage : biblio.cmd <commande> [options]  (ex. biblio.cmd serve)
rem L'environnement Python est range hors du dossier du projet (utile si le projet est dans OneDrive).
setlocal
if not defined UV_PROJECT_ENVIRONMENT set "UV_PROJECT_ENVIRONMENT=%USERPROFILE%\.virtualenvs\uv\bibliotheque"
uv run --project "%~dp0." biblio %*
