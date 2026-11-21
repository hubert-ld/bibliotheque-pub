#!/bin/bash
# Ouvre sur cet ordinateur l'interface « ordinateur » de la bibliothèque du serveur, par un tunnel SSH.
# Tout y est disponible, y compris la page Téléphone et ses QR codes. Ctrl+C ferme le tunnel.
#   ./deploy/ouvrir.sh
set -euo pipefail
. "$(dirname "$0")/commun.sh"

url="http://localhost:$PORT_TUNNEL"
echo "Bibliothèque du serveur : $url   (Ctrl+C pour fermer)"
ouvrir=$(command -v open || command -v xdg-open || true)
[ -n "$ouvrir" ] && (sleep 2 && "$ouvrir" "$url") &
exec ssh -N -o ExitOnForwardFailure=yes -L "$PORT_TUNNEL:127.0.0.1:$PORT_WEB" "$SERVEUR_SSH"
