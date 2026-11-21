#!/bin/bash
# Installe sur le serveur la base envoyée par migrer-base.sh (lancé par lui, en root).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "À lancer avec sudo" >&2; exit 1; }
. "$(cd "$(dirname "$0")" && pwd)/serveur.conf"
recu=${1:?dossier reçu}
[ -s "$recu/biblio.db" ] || { echo "Pas de base dans $recu" >&2; exit 1; }

systemctl stop biblio.service 2>/dev/null || true
if [ -e "$DATA_DIR/biblio.db" ]; then
  ancienne="$DATA_DIR/biblio-remplacee-$(date +%Y-%m-%d-%H%M%S).db"
  runuser -u biblio -- sqlite3 "$DATA_DIR/biblio.db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
  mv "$DATA_DIR/biblio.db" "$ancienne"
  echo "Base existante gardée sous $ancienne"
fi
rm -f "$DATA_DIR/biblio.db-wal" "$DATA_DIR/biblio.db-shm"
install -o biblio -g biblio -m 600 "$recu/biblio.db" "$DATA_DIR/biblio.db"
for d in covers certs; do
  if [ -d "$recu/$d" ]; then
    rsync -rt "$recu/$d/" "$DATA_DIR/$d/"
    chown -R biblio:biblio "$DATA_DIR/$d"
    chmod -R u=rwX,go= "$DATA_DIR/$d"
    echo "$d : $(ls "$DATA_DIR/$d" | wc -l) fichiers"
  fi
done
rm -rf "$recu"
systemctl start biblio.service
sleep 3
if systemctl is-active -q biblio.service; then
  printf '\033[32m✓ Base installée, la bibliothèque tourne.\033[0m\n'
  echo "  $(runuser -u biblio -- sqlite3 "$DATA_DIR/biblio.db" 'SELECT count(*) FROM exemplaires') exemplaires"
else
  journalctl -u biblio -n 30 --no-pager; exit 1
fi
