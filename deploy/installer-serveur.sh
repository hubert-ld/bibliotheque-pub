#!/bin/bash
# Installe ou met à jour la bibliothèque sur un serveur Linux (systemd). Lancé par deployer.sh, en root.
# Idempotent : on peut le relancer à chaque mise à jour du code.
#
#   /opt/biblio/app      le code (root, lecture seule pour le service)
#   /opt/biblio/venv     l'environnement Python (uv), /opt/biblio/python : le Python géré par uv
#   $DATA_DIR            base, couvertures, certificats, copies du jour (utilisateur biblio, 700)
#   $BACKUP_DIR          archive des copies quotidiennes (de préférence sur un autre disque)
#   /etc/biblio/biblio.env, biblio.service, biblio-backup.{service,timer}, /usr/local/bin/biblio
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "À lancer avec sudo" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")/.." && pwd)
. "$SRC/deploy/serveur.conf"

APP=/opt/biblio/app
VENV=/opt/biblio/venv
ENV_FILE=/etc/biblio/biblio.env
etape() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
echec() { printf '\033[31mERREUR : %s\033[0m\n' "$*" >&2; exit 1; }
attention() { printf '\033[33mATTENTION : %s\033[0m\n' "$*" >&2; }
existant() { local p=$1; while [ ! -e "$p" ]; do p=$(dirname "$p"); done; echo "$p"; }
monte() {   # un chemin sous /mnt ou /media doit être sur un disque monté, pas sur le disque système
  case "$1" in /mnt/*|/media/*) [ "$(findmnt -no TARGET -T "$(existant "$1")")" != / ] ;; *) true ;; esac
}

etape "Vérifications"
case "$DATA_DIR" in /*) ;; *) echec "DATA_DIR doit être un chemin absolu" ;; esac
monte "$DATA_DIR" || echec "$DATA_DIR : le disque n'est pas monté"
fs=$(findmnt -no FSTYPE -T "$(existant "$DATA_DIR")")
case "$fs" in
  vfat|exfat|ntfs|ntfs3|fuseblk|cifs|smb3|nfs|nfs4)
    echec "$DATA_DIR est sur un système de fichiers $fs : pas de droits Unix (ou réseau), la base n'y serait ni protégée ni sûre. Prenez par exemple DATA_DIR=/var/lib/biblio." ;;
esac
if command -v testparm >/dev/null; then
  partages=$(testparm -s 2>/dev/null | sed -n 's/^[[:space:]]*path = //p')
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    case "$DATA_DIR/" in "${p%/}/"*) echec "$DATA_DIR est dans le partage Samba $p : la base (notes, prêts, clé du téléphone) serait lisible depuis le réseau, et SQLite se corrompt si on l'ouvre par le partage." ;; esac
    case "$BACKUP_DIR/" in "${p%/}/"*) attention "$BACKUP_DIR est dans le partage Samba $p : les copies y sont lisibles depuis le réseau." ;; esac
  done <<< "$partages"
fi
[ "$(printf '%s\n' "$PORT_WEB" "$PORT_HTTPS" "$PORT_INSTALLATION" | sort -u | wc -l)" = 3 ] \
  || echec "PORT_WEB, PORT_HTTPS et PORT_INSTALLATION doivent être différents"
arrete=0
if systemctl is-active -q biblio.service; then
  echo "Service arrêté le temps de la mise à jour"
  systemctl stop biblio.service
  arrete=1
fi
# En cas d'échec, l'ancienne version repart
trap 'rc=$?; if [ $rc -ne 0 ] && [ $arrete = 1 ]; then systemctl start biblio.service || true; fi; exit $rc' EXIT
for p in $PORT_WEB $PORT_HTTPS $PORT_INSTALLATION; do
  pris=$(ss -Hltnp "sport = :$p")
  [ -z "$pris" ] || echec "le port $p est déjà pris : $pris — choisissez-en un autre dans deploy/serveur.conf"
done
echo "Ports libres : $PORT_WEB (local), $PORT_HTTPS, $PORT_INSTALLATION — données : $DATA_DIR ($fs)"

etape "Paquets"
manquants=""
for c in rsync sqlite3 curl; do command -v "$c" >/dev/null || manquants="$manquants $c"; done
if [ -n "$manquants" ]; then apt-get update -q && apt-get install -y -q $manquants; fi
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
echo "uv $(uv --version | cut -d' ' -f2)"

etape "Utilisateur système biblio"
if ! id biblio >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home --shell /usr/sbin/nologin biblio
  echo "créé"
else
  echo "existe déjà"
fi
# covers/ et sauvegardes/ dès l'installation : la copie de la nuit les envoie dans l'archive,
# même avant le premier téléchargement de couverture.
install -d -o biblio -g biblio -m 700 "$DATA_DIR" "$DATA_DIR/covers" "$DATA_DIR/sauvegardes"

etape "Code et environnement Python"
install -d -m 755 /opt/biblio
rsync -rlt --delete --chmod=D755,F644 --exclude-from="$SRC/deploy/rsync-exclude" "$SRC/" "$APP/"
chown -R root:root "$APP"
# Installation « éditable » (défaut de uv) : le paquet garde son dossier, donc rules/ reste trouvé.
UV_PROJECT_ENVIRONMENT=$VENV UV_PYTHON_INSTALL_DIR=/opt/biblio/python UV_CACHE_DIR=/var/cache/biblio-uv \
  UV_PYTHON_PREFERENCE=only-managed uv sync --project "$APP" --frozen --no-dev --compile-bytecode -q
"$VENV/bin/python" -m compileall -q "$APP/biblio"
chmod -R a+rX /opt/biblio
echo "$("$VENV/bin/python" --version), biblio $("$VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("biblio"))')"

etape "Configuration"
install -d -m 755 /etc/biblio
cat > "$ENV_FILE" <<CONF
# Généré par deploy/installer-serveur.sh : modifier deploy/serveur.conf sur votre ordinateur, puis redéployer.
BIBLIO_DB=$DATA_DIR/biblio.db
BIBLIO_COVERS=$DATA_DIR/covers
BIBLIO_CERTS=$DATA_DIR/certs
BIBLIO_NOM=${NOM_RESEAU:-$(hostname)}
BIBLIO_PORT_WEB=$PORT_WEB
BIBLIO_PORT_HTTPS=$PORT_HTTPS
BIBLIO_PORT_INSTALLATION=$PORT_INSTALLATION
CONF
chown root:biblio "$ENV_FILE"
chmod 640 "$ENV_FILE"

cat > /usr/local/bin/biblio <<'CLI'
#!/bin/sh
# La CLI de la bibliothèque sur le serveur, avec le même utilisateur et la même base que le service.
#   biblio stats · biblio search camus · biblio todo · biblio backup · biblio phone --new-key
case "${1:-}" in
  serve) echo "Le serveur tourne en service : sudo systemctl restart biblio (journal : journalctl -u biblio)" >&2; exit 1 ;;
esac
exec sudo -H -u biblio /bin/sh -c 'set -a; . /etc/biblio/biblio.env; set +a; cd "$HOME"; exec /opt/biblio/venv/bin/biblio "$@"' biblio "$@"
CLI
chmod 755 /usr/local/bin/biblio

# Durcissement commun : le service ne peut écrire que dans ses données.
DURCI="NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
UMask=0077
ReadWritePaths=$DATA_DIR"

cat > /etc/systemd/system/biblio.service <<UNIT
[Unit]
Description=Bibliothèque personnelle (scan, catalogue, téléphone)
Wants=network-online.target
After=network-online.target
RequiresMountsFor=$DATA_DIR

[Service]
User=biblio
Group=biblio
EnvironmentFile=$ENV_FILE
WorkingDirectory=$DATA_DIR
# Interface « ordinateur » sur 127.0.0.1 seulement (tunnel SSH) ; téléphones sur le réseau, avec la clé.
ExecStart=$VENV/bin/biblio serve --phone --no-open --host 127.0.0.1 --port \${BIBLIO_PORT_WEB}
Restart=on-failure
RestartSec=5
# Priorité basse : les autres services du serveur passent avant.
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
$DURCI

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/biblio-backup.service <<UNIT
[Unit]
Description=Bibliothèque : copie de sécurité quotidienne, puis archive
RequiresMountsFor=$DATA_DIR
# Attend le disque de l'archive s'il est là, mais la copie du jour se fait même sans lui
WantsMountsFor=$BACKUP_DIR

[Service]
Type=oneshot
User=biblio
Group=biblio
EnvironmentFile=$ENV_FILE
# Copie cohérente en un fichier (même serveur en marche), dans $DATA_DIR/sauvegardes : les 3 dernières
ExecStart=$VENV/bin/biblio backup --keep 3
# Puis l'archive, en root (« + ») : toute la semaine, puis 1 par semaine sur un mois, 1 par mois sur un an,
# 1 par an sans limite (deploy/retention.py). Rien n'est écrit si le disque n'est pas monté.
ExecStartPost=+$VENV/bin/python -I $APP/deploy/retention.py --copies $DATA_DIR/sauvegardes --archive $BACKUP_DIR --couvertures $DATA_DIR/covers
Nice=19
IOSchedulingClass=idle
$DURCI
UNIT

cat > /etc/systemd/system/biblio-backup.timer <<UNIT
[Unit]
Description=Copie de sécurité quotidienne de la bibliothèque

[Timer]
OnCalendar=*-*-* 04:20
RandomizedDelaySec=20min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

if monte "$BACKUP_DIR"; then
  mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR" 2>/dev/null || true
else
  attention "$BACKUP_DIR : disque non monté, l'archive ne sera pas mise à jour tant qu'il manque"
fi

etape "Démarrage"
systemctl daemon-reload
systemctl enable -q biblio.service biblio-backup.timer
systemctl start biblio-backup.timer
ip=$(hostname -I | awk '{print $1}')
if [ ! -e "$DATA_DIR/biblio.db" ]; then
  echo "Pas encore de base sur le serveur : service installé mais pas lancé."
  echo "  - reprendre la base de votre ordinateur : ./deploy/migrer-base.sh (sur l'ordinateur)"
  echo "  - ou partir d'une base vide : sudo systemctl start biblio"
  exit 0
fi
systemctl start biblio.service
for _ in $(seq 20); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT_WEB/static/style.css" 2>/dev/null && break
  sleep 1
done
if curl -fsS -o /dev/null "http://127.0.0.1:$PORT_WEB/static/style.css" 2>/dev/null; then
  printf '\033[32m✓ La bibliothèque tourne.\033[0m\n'
  echo "  Ordinateur : adresse avec la clé admin : biblio phone --admin   (secours : ./deploy/ouvrir.sh)"
  echo "  Téléphone  : https://$ip:$PORT_HTTPS/scan  (certificat : http://$ip:$PORT_INSTALLATION/)"
  echo "  Journal    : journalctl -u biblio -f      CLI : biblio --help"
else
  journalctl -u biblio -n 30 --no-pager
  echec "le service ne répond pas (journal ci-dessus)"
fi
