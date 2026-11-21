#!/bin/bash
# Copie la base locale (et les couvertures) sur le serveur, une fois : ensuite, c'est la base du serveur qui fait foi.
#   ./deploy/migrer-base.sh                      # nouvelle autorité sur le serveur : réinstaller le certificat
#   ./deploy/migrer-base.sh --avec-certificats   # reprend l'autorité de cet ordinateur : téléphones déjà prêts
# Une base déjà présente sur le serveur n'est pas effacée : elle est renommée biblio-remplacee-<date>.db.
set -euo pipefail
. "$(dirname "$0")/commun.sh"

certs=0
[ "${1:-}" = --avec-certificats ] && certs=1

ssh "$SERVEUR_SSH" 'test -x /opt/biblio/venv/bin/biblio' || {
  echo "Le service n'est pas encore installé sur le serveur : lancez d'abord ./deploy/deployer.sh" >&2; exit 1; }

echo "Les changements faits ici après cette copie ne seront pas sur le serveur."
read -r -p "Arrêtez la bibliothèque locale si elle tourne, puis Entrée pour continuer (Ctrl+C pour annuler) "

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
$BIBLIO_LOCAL backup --dir "$tmp" --keep 1 >/dev/null      # copie cohérente, en un seul fichier
copie=$(ls "$tmp"/*.db)
couvertures=${BIBLIO_COVERS:-data/covers}
echo "== Envoi de la base ($(du -h "$copie" | cut -f1)) et des couvertures"
ssh "$SERVEUR_SSH" 'rm -rf "$HOME/biblio-migration" && mkdir -m 700 "$HOME/biblio-migration"'
rsync -t "$copie" "$SERVEUR_SSH:biblio-migration/biblio.db"
[ -d "$couvertures" ] && rsync -rt "$couvertures/" "$SERVEUR_SSH:biblio-migration/covers/"
if [ $certs = 1 ]; then
  # Le dossier des certificats de cet ordinateur (BIBLIO_CERTS, sinon le dossier de données du système)
  dossier=${BIBLIO_CERTS:-}
  if [ -z "$dossier" ]; then
    case "$(uname -s)" in
      Darwin) dossier="$HOME/Library/Application Support/biblio/certs" ;;
      *) dossier="${XDG_DATA_HOME:-$HOME/.local/share}/biblio/certs" ;;
    esac
  fi
  [ -d "$dossier" ] || { echo "Pas de certificats dans $dossier" >&2; exit 1; }
  rsync -rt "$dossier/" "$SERVEUR_SSH:biblio-migration/certs/"
fi
ssh -t "$SERVEUR_SSH" 'sudo bash "$HOME/biblio-src/deploy/importer-base.sh" "$HOME/biblio-migration"'
