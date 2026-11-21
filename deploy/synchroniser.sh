#!/bin/bash
# Réunit la base de cet ordinateur et celle du serveur : ajouts, modifications et retraits (biblio sync).
#   ./deploy/synchroniser.sh                  # dans les deux sens, avec une confirmation de chaque côté
#   ./deploy/synchroniser.sh --vers-local     # seulement du serveur vers l'ordinateur : seule la base locale change
#   ./deploy/synchroniser.sh --vers-serveur   # seulement de l'ordinateur vers le serveur : seule sa base change
#   Avec l'une ou l'autre : --dry-run montre seulement ce qui changerait, --yes applique sans rien demander.
# Avant d'écrire, le côté modifié garde une copie de sa base : biblio-avant-synchro.db, à côté d'elle.
# La base locale est celle de BIBLIO_DB (par défaut data/biblio.db).
set -euo pipefail
. "$(dirname "$0")/commun.sh"

options=""
vers_local=1
vers_serveur=1
usage() { echo "Usage : $0 [--vers-local | --vers-serveur] [--dry-run] [--yes]" >&2; exit 2; }
for option in "$@"; do
  case "$option" in
    --dry-run|--yes) options="$options $option" ;;
    --vers-local) [ $vers_local = 1 ] || usage; vers_serveur=0 ;;
    --vers-serveur) [ $vers_serveur = 1 ] || usage; vers_local=0 ;;
    *) usage ;;
  esac
done

SYNCHRO="${DATA_DIR:?}/synchro"            # côté serveur : dossier privé de l'utilisateur biblio
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"; ssh "$SERVEUR_SSH" "sudo rm -rf $SYNCHRO" || true' EXIT

if [ $vers_local = 1 ]; then
  echo "== Du serveur vers cet ordinateur"
  ssh "$SERVEUR_SSH" "biblio backup --dir $SYNCHRO --keep 1" >/dev/null
  ssh "$SERVEUR_SSH" "sudo sh -c 'cat $SYNCHRO/*.db'" > "$tmp/serveur.db"   # sans -t : un terminal abîmerait le fichier
  $BIBLIO_LOCAL sync "$tmp/serveur.db" $options
fi

if [ $vers_serveur = 1 ]; then
  echo "== De cet ordinateur vers le serveur"
  $BIBLIO_LOCAL backup --dir "$tmp/local" --keep 1 >/dev/null              # copie cohérente, en un seul fichier
  ssh "$SERVEUR_SSH" "sudo -u biblio sh -c 'mkdir -p $SYNCHRO && cat > $SYNCHRO/local.db'" < "$(ls "$tmp"/local/*.db)"
  terminal=""
  [ -t 0 ] && terminal="-t"               # pour répondre à la confirmation, côté serveur
  ssh $terminal "$SERVEUR_SSH" "biblio sync $SYNCHRO/local.db $options"
fi
