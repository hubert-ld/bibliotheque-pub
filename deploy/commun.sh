# Lu par les scripts de ce dossier, côté ordinateur : réglages et lancement de la CLI locale.
cd "$(dirname "$0")/.."
[ -f deploy/serveur.conf ] || {
  echo "Pas de deploy/serveur.conf : cp deploy/serveur.conf.example deploy/serveur.conf, puis réglez-le." >&2; exit 1; }
. deploy/serveur.conf
: "${SERVEUR_SSH:?à régler dans deploy/serveur.conf}"
if [ -x ./biblio.sh ]; then BIBLIO_LOCAL=./biblio.sh; else BIBLIO_LOCAL=biblio; fi
