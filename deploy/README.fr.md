# La bibliothèque sur un serveur Linux

[English](README.md) · **Français**

Un petit serveur toujours allumé (mini-PC, NAS, nano-ordinateur, vieux portable…) fait tourner la bibliothèque
en service, jour et nuit : on scanne au téléphone sans allumer son ordinateur, et l'ordinateur s'y connecte
quand il veut. Les scripts de ce dossier s'utilisent **depuis votre ordinateur**, dans le dossier du projet, et
agissent sur le serveur par SSH.

Prérequis côté serveur : Linux avec systemd (Debian, Ubuntu et dérivés : l'installeur utilise `apt` pour les
paquets manquants), un accès SSH et `sudo`. uv et Python sont installés par l'installeur.

## Où va quoi

| Quoi | Où | Pourquoi |
|---|---|---|
| Code | `/opt/biblio/app` (root, lecture seule pour le service) | Remplacé à chaque déploiement, jamais modifié par le service |
| Python + dépendances | `/opt/biblio/venv`, `/opt/biblio/python` (uv) | Même Python que sur l'ordinateur (`.python-version`) |
| Base, couvertures, certificats | `DATA_DIR`, par défaut `/var/lib/biblio` (utilisateur `biblio`, droits 700) | Quelques Mo, protégés par les droits Unix |
| Copies | `DATA_DIR/sauvegardes` : les 3 dernières ; `BACKUP_DIR` : l'archive (voir plus bas) | De préférence sur un autre disque, hors de tout partage réseau |
| Réglages | `deploy/serveur.conf` (ici) → `/etc/biblio/biblio.env` | Un seul fichier à modifier |

**Pas dans un partage réseau** : la base contient vos notes, les noms des emprunteurs et la clé du téléphone
(lire le fichier suffit pour entrer). Et SQLite se corrompt si on l'ouvre par un partage réseau pendant que le
serveur écrit. L'installeur refuse donc un `DATA_DIR` dans un partage Samba, sur un disque réseau ou sur un disque
exFAT/NTFS.

## Ports

| Port | Écoute | Rôle |
|---|---|---|
| `PORT_WEB` (8000) | `127.0.0.1` seulement | Interface sans clé, par tunnel SSH (`./deploy/ouvrir.sh`) : secours |
| `PORT_HTTPS` (8443) | réseau local | Les ordinateurs (compte ou clé admin) et les téléphones (compte ou clé du QR code), en HTTPS |
| `PORT_INSTALLATION` (8080) | réseau local | Page d'installation du certificat (rien d'autre) |

Si un autre service occupe déjà l'un de ces ports, changez-le dans `deploy/serveur.conf` : `./deploy/diagnostic.sh`
liste les ports pris, et l'installeur refuse un port déjà utilisé. `PORT_WEB` n'est jamais ouvert au réseau :
en HTTP, sans clé, n'importe quel appareil du Wi-Fi lirait tout.

## Comptes et clés

Le plus simple pour la maison : un **compte par personne** (Administration › Comptes), code à taper une fois par
appareil. Pour créer votre premier compte, entrez avec la clé admin ci-dessous, ou en SSH :
`biblio user add votre-nom --role admin`. Les deux clés restent valables à côté des comptes :

| Clé | Pour | Donne accès à |
|---|---|---|
| **Téléphone** (QR code « Scanner », rôle Bibliothécaire) | les téléphones | scanner, catalogue, fiches, lieux, prêts, statistiques… Se coupe dans Administration › Accès réseau |
| **Admin** (`biblio phone --admin`) | votre ordinateur, uniquement | tout, plus **Réglages**, **Téléphone** (QR codes, changer la clé), le fichier de partage, le classement et la langue de l'appli |

Avec la clé téléphone, les menus Réglages et Téléphone et les sélecteurs Classement / FR·EN disparaissent,
et le serveur refuse ces pages même si on tape l'adresse. La clé admin n'est jamais affichée en QR code.
« Changer la clé » (page Téléphone) coupe tous les téléphones, pas l'ordinateur ; `biblio phone --admin --new-key`
change la clé admin.

## Se connecter depuis l'ordinateur, sans tunnel

Une fois pour toutes (exemple avec `NOM_RESEAU=mon-serveur` et les ports par défaut) :

1. **Faire confiance au certificat**. Sur macOS (Safari, Chrome ; Firefox a son propre réglage) :
   ```bash
   curl -o /tmp/biblio-ca.crt "http://mon-serveur:8080/bibliotheque-ca.crt?fichier=1"
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /tmp/biblio-ca.crt
   ```
   Sous Linux ou Windows, importez ce même fichier dans les autorités de confiance du système ou du navigateur.
   Une autorité récente ne vaut que pour `NOM_RESEAU`, `localhost` et les adresses privées (`192.168…`), même si
   sa clé fuitait.
2. **Donner la clé admin au navigateur** : en SSH sur le serveur, `biblio phone --admin` affiche
   `https://mon-serveur:8443/catalogue?cle=…`. Ouvrez-la sur l'ordinateur : la clé passe dans un cookie
   (un an) et disparaît de l'adresse.

Ensuite : **https://mon-serveur:8443/catalogue** (à mettre en favori ; le cookie est propre à cette
adresse, pas à l'adresse IP).

## Mise en place (depuis l'ordinateur, dans le dossier du projet)

1. **Régler** : `cp deploy/serveur.conf.example deploy/serveur.conf`, puis au moins `SERVEUR_SSH`
   (votre `utilisateur@mon-serveur` ou alias SSH) et `NOM_RESEAU`. Ce fichier reste hors du dépôt.
2. **Vérifier**, sans rien modifier : `./deploy/diagnostic.sh` (ports pris, disques, partages Samba).
3. **Installer** : `./deploy/deployer.sh` (code, uv, utilisateur `biblio`, services, copie quotidienne).
4. **Reprendre la base de l'ordinateur**, une fois : `./deploy/migrer-base.sh --avec-certificats`
   (`--avec-certificats` reprend l'autorité déjà installée sur vos téléphones : rien à réinstaller ;
   sans l'option, le serveur crée la sienne et il faut rescanner le QR code 1 sur chaque téléphone).
   Pour partir d'une base vide : `sudo systemctl start biblio` sur le serveur.
5. **Ouvrir** : voir « Se connecter depuis l'ordinateur » ci-dessus. Page **Téléphone** : rescannez le QR code
   « Scanner » (nouvelle adresse), et refaites l'icône d'écran d'accueil sur iPhone.

Mise à jour du code ensuite : `./deploy/deployer.sh`, c'est tout (les données ne sont jamais touchées).

**Après la migration, la base du serveur fait foi.** N'ajoutez plus de livres dans la base de l'ordinateur,
ou réunissez les deux avec `./deploy/synchroniser.sh` (voir plus bas).

> Réservez l'adresse IP du serveur dans votre box (bail DHCP statique) : les QR codes et le certificat utilisent
> l'IP prise au démarrage du service. Si elle change : `sudo systemctl restart biblio`, puis rescanner.

## Synchroniser l'ordinateur et le serveur

Depuis l'ordinateur, dans le dossier du projet. Sans option, la synchronisation se fait dans les deux sens :

```bash
./deploy/synchroniser.sh                  # les deux sens, avec une confirmation de chaque côté
./deploy/synchroniser.sh --vers-local     # du serveur vers l'ordinateur : seule la base locale change
./deploy/synchroniser.sh --vers-serveur   # de l'ordinateur vers le serveur : seule la base du serveur change
```

`--dry-run` montre seulement ce qui changerait, et `--yes` applique sans rien demander. Les ajouts, modifications et
retraits se propagent, selon les règles de `biblio sync` (voir la documentation). Le côté modifié garde d'abord une
copie de sa base, `biblio-avant-synchro.db`, et les fichiers de travail sont retirés à la fin. Le service peut rester
en marche. La base locale est celle de `BIBLIO_DB` (par défaut `data/biblio.db`). Il faut `sudo` sans mot de passe
sur le serveur, pour lire et retirer ces fichiers.

## Les copies de sécurité

Chaque nuit vers 4 h 20 (`biblio-backup.timer`, rattrapée au démarrage si le serveur était éteint) :

1. `biblio backup --keep 3` : copie cohérente de la base, même serveur en marche, dans `DATA_DIR/sauvegardes`,
   qui garde les **3 dernières**.
2. `deploy/retention.py` : la copie part dans l'archive `BACKUP_DIR`, qui garde **toutes celles de la semaine,
   puis 1 par semaine sur un mois, 1 par mois sur un an, et 1 par an sans limite** (environ 25 fichiers
   au bout de deux ans). Les couvertures y sont aussi recopiées.

Les durées se comptent depuis la copie la plus récente : si les copies s'arrêtent, rien n'est supprimé de
plus. Si `BACKUP_DIR` est sous `/mnt` ou `/media` et que le disque est débranché, rien n'y est écrit (la copie du
jour se fait quand même) : l'archive reprend à son retour.
Voir ce que ferait le tri : `sudo /opt/biblio/venv/bin/python -I /opt/biblio/app/deploy/retention.py
--copies /var/lib/biblio/sauvegardes --archive /var/backups/biblio --simulation`.

## Au quotidien, sur le serveur (en SSH)

```bash
biblio stats                      # la CLI, avec la base du service (biblio --help)
biblio backup                     # une copie maintenant
sudo systemctl restart biblio     # relancer
journalctl -u biblio -f           # journal
systemctl list-timers biblio-backup.timer   # prochaine copie (chaque nuit vers 4 h 20)
```

Restaurer une copie : `sudo systemctl stop biblio`, copier la sauvegarde sur `/var/lib/biblio/biblio.db`
(`sudo install -o biblio -g biblio -m 600 …`), supprimer `biblio.db-wal` et `biblio.db-shm`, relancer.

## Les scripts

| Script | Où il tourne | Rôle |
|---|---|---|
| `diagnostic.sh` | ordinateur → serveur | État du serveur, sans rien modifier |
| `deployer.sh` | ordinateur → serveur | Envoie le code et lance `installer-serveur.sh` |
| `installer-serveur.sh` | serveur (root) | Installe ou met à jour : paquets, uv, utilisateur, services systemd ; idempotent |
| `migrer-base.sh` | ordinateur → serveur | Envoie la base et les couvertures, puis lance `importer-base.sh` |
| `importer-base.sh` | serveur (root) | Met la base reçue en place, en gardant l'ancienne |
| `synchroniser.sh` | ordinateur ↔ serveur | `biblio sync` dans un sens ou dans les deux |
| `ouvrir.sh` | ordinateur | Tunnel SSH vers l'interface locale du serveur |
| `retention.py` | serveur (chaque nuit) | Archive et tri des copies |
