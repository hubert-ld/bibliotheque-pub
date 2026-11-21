#!/bin/bash
# État du serveur avant installation, sans rien modifier : ports pris, disques, partages Samba.
#   ./deploy/diagnostic.sh
set -euo pipefail
. "$(dirname "$0")/commun.sh"

ssh "$SERVEUR_SSH" "PORTS='$PORT_WEB $PORT_HTTPS $PORT_INSTALLATION' DATA_DIR='$DATA_DIR' BACKUP_DIR='$BACKUP_DIR' bash -s" <<'DIAG'
echo "== Ports TCP en écoute"
ss -Hltn | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\n' ' '; echo
for p in $PORTS; do
  if ss -Hltn "sport = :$p" | grep -q .; then echo "   ✗ $p est PRIS"; else echo "   ✓ $p est libre"; fi
done
echo "== Disques"
df -h -x tmpfs -x devtmpfs 2>/dev/null | sed 's/^/   /'
if command -v testparm >/dev/null; then
  echo "== Partages Samba (chemins)"
  testparm -s 2>/dev/null | sed -n 's/^\[\(.*\)\]$/   [\1]/p; s/^[[:space:]]*path = /      /p'
fi
echo "== Dossiers prévus"
for d in "$DATA_DIR" "$BACKUP_DIR"; do
  p=$d; while [ ! -e "$p" ]; do p=$(dirname "$p"); done
  echo "   $d → système de fichiers $(findmnt -no FSTYPE -T "$p") ($(findmnt -no TARGET -T "$p"))"
done
echo "== Système"
echo "   $(hostname) — $(hostname -I)"
echo "   $(. /etc/os-release; echo "$PRETTY_NAME") — $(uname -m) — $(python3 --version 2>&1)"
echo "   uv : $(command -v uv || echo absent, sera installé)"
DIAG
