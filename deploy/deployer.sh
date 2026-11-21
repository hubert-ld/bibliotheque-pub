#!/bin/bash
# Envoie le code sur le serveur puis installe ou met à jour le service. À lancer depuis votre ordinateur :
#   ./deploy/deployer.sh
# Les données du serveur (base, couvertures, certificats) ne sont jamais touchées.
set -euo pipefail
. "$(dirname "$0")/commun.sh"

echo "== Envoi du code vers $SERVEUR_SSH:~/biblio-src"
rsync -rlt --delete --exclude-from=deploy/rsync-exclude ./ "$SERVEUR_SSH:biblio-src/"
echo "== Installation (mot de passe sudo du serveur si demandé)"
ssh -t "$SERVEUR_SSH" 'sudo bash "$HOME/biblio-src/deploy/installer-serveur.sh"'
