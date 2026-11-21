# The library on a Linux server

**English** · [Français](README.fr.md)

A small always-on server (mini-PC, NAS, single-board computer, old laptop…) runs the library as a service,
day and night: you scan with your phone without switching your computer on, and the computer connects to it
whenever it wants. The scripts in this folder are run **from your computer**, in the project folder, and act on
the server over SSH. (Script and option names are in French, like the rest of the code.)

Server requirements: Linux with systemd (Debian, Ubuntu and derivatives: the installer uses `apt` for missing
packages), SSH access and `sudo`. uv and Python are installed by the installer.

## What goes where

| What | Where | Why |
|---|---|---|
| Code | `/opt/biblio/app` (root, read-only for the service) | Replaced on each deployment, never changed by the service |
| Python + dependencies | `/opt/biblio/venv`, `/opt/biblio/python` (uv) | Same Python as on the computer (`.python-version`) |
| Database, covers, certificates | `DATA_DIR`, by default `/var/lib/biblio` (user `biblio`, mode 700) | A few MB, protected by Unix permissions |
| Copies | `DATA_DIR/sauvegardes`: the last 3; `BACKUP_DIR`: the archive (see below) | Preferably on another disk, outside any network share |
| Settings | `deploy/serveur.conf` (here) → `/etc/biblio/biblio.env` | A single file to edit |

**Not in a network share**: the database contains your notes, the borrowers' names and the phone key
(reading the file is enough to get in). And SQLite gets corrupted if it is opened through a network share while
the server writes. The installer therefore refuses a `DATA_DIR` in a Samba share, on a network disk or on an
exFAT/NTFS disk.

## Ports

| Port | Listens on | Role |
|---|---|---|
| `PORT_WEB` (8000) | `127.0.0.1` only | Interface without a key, through an SSH tunnel (`./deploy/ouvrir.sh`): emergency access |
| `PORT_HTTPS` (8443) | local network | Computers (account or admin key) and phones (account or QR code key), over HTTPS |
| `PORT_INSTALLATION` (8080) | local network | Certificate installation page (nothing else) |

If another service already uses one of these ports, change it in `deploy/serveur.conf`: `./deploy/diagnostic.sh`
lists the ports in use, and the installer refuses a port that is taken. `PORT_WEB` is never open to the network:
over HTTP, without a key, any device on the Wi-Fi could read everything.

## Accounts and keys

The simplest for a household: **one account per person** (Administration › Accounts), with a code typed once per
device. To create your first account, get in with the admin key below, or over SSH:
`biblio user add your-name --role admin`. Both keys remain valid alongside the accounts:

| Key | For | Gives access to |
|---|---|---|
| **Phone** (“Scan” QR code, Librarian role) | the phones | scanning, catalogue, records, places, loans, statistics… Can be turned off in Administration › Network access |
| **Admin** (`biblio phone --admin`) | your computer, only | everything, plus **Settings**, **Phone** (QR codes, change the key), the share file, the app's classification and language |

With the phone key, the Settings and Phone menus and the Classification / FR·EN selectors disappear,
and the server refuses these pages even if the address is typed. The admin key is never shown as a QR code.
“Change the key” (Phone page) cuts off all phones, not the computer; `biblio phone --admin --new-key`
changes the admin key.

## Connecting from the computer, without a tunnel

Once and for all (example with `NOM_RESEAU=mon-serveur` and the default ports):

1. **Trust the certificate**. On macOS (Safari, Chrome; Firefox has its own setting):
   ```bash
   curl -o /tmp/biblio-ca.crt "http://mon-serveur:8080/bibliotheque-ca.crt?fichier=1"
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /tmp/biblio-ca.crt
   ```
   On Linux or Windows, import the same file into the system's or the browser's trusted authorities.
   A recent authority is only valid for `NOM_RESEAU`, `localhost` and private addresses (`192.168…`), even if
   its key leaked.
2. **Give the admin key to the browser**: over SSH on the server, `biblio phone --admin` shows
   `https://mon-serveur:8443/catalogue?cle=…`. Open it on the computer: the key goes into a cookie
   (one year) and disappears from the address.

Then: **https://mon-serveur:8443/catalogue** (bookmark it; the cookie belongs to this
address, not to the IP address).

## Setting up (from the computer, in the project folder)

1. **Configure**: `cp deploy/serveur.conf.example deploy/serveur.conf`, then at least `SERVEUR_SSH`
   (your `user@my-server` or SSH alias) and `NOM_RESEAU`. This file stays out of the repository.
2. **Check**, without changing anything: `./deploy/diagnostic.sh` (ports in use, disks, Samba shares).
3. **Install**: `./deploy/deployer.sh` (code, uv, `biblio` user, services, daily copy).
4. **Take over the computer's database**, once: `./deploy/migrer-base.sh --avec-certificats`
   (`--avec-certificats` takes over the authority already installed on your phones: nothing to reinstall;
   without the option, the server creates its own and QR code 1 must be scanned again on each phone).
   To start from an empty database: `sudo systemctl start biblio` on the server.
5. **Open**: see “Connecting from the computer” above. **Phone** page: scan the “Scan” QR code again
   (new address), and recreate the home screen icon on iPhone.

Updating the code afterwards: `./deploy/deployer.sh`, that's all (the data is never touched).

**After the migration, the server's database is the reference.** Stop adding books to the computer's database,
or bring the two together with `./deploy/synchroniser.sh` (see below).

> Reserve the server's IP address in your router (static DHCP lease): the QR codes and the certificate use
> the IP taken when the service starts. If it changes: `sudo systemctl restart biblio`, then scan again.

## Syncing the computer and the server

From the computer, in the project folder. Without an option, synchronisation goes both ways:

```bash
./deploy/synchroniser.sh                  # both ways, with a confirmation on each side
./deploy/synchroniser.sh --vers-local     # from the server to the computer: only the local database changes
./deploy/synchroniser.sh --vers-serveur   # from the computer to the server: only the server's database changes
```

`--dry-run` only shows what would change, and `--yes` applies without asking. Additions, changes and
removals are propagated, following the rules of `biblio sync` (see the documentation). The changed side first keeps a
copy of its database, `biblio-avant-synchro.db`, and the working files are removed at the end. The service can keep
running. The local database is the one in `BIBLIO_DB` (by default `data/biblio.db`). Passwordless `sudo` is needed
on the server, to read and remove these files.

## Backups

Every night around 4:20 (`biblio-backup.timer`, caught up at boot if the server was off):

1. `biblio backup --keep 3`: a consistent copy of the database, even with the server running, in
   `DATA_DIR/sauvegardes`, which keeps the **last 3**.
2. `deploy/retention.py`: the copy goes to the `BACKUP_DIR` archive, which keeps **all those of the week,
   then 1 per week over a month, 1 per month over a year, and 1 per year without limit** (about 25 files
   after two years). The covers are copied there too.

Durations are counted from the most recent copy: if copies stop, nothing more is deleted.
If `BACKUP_DIR` is under `/mnt` or `/media` and the disk is unplugged, nothing is written there (the day's copy
is still made): the archive resumes when it comes back.
See what the sorting would do: `sudo /opt/biblio/venv/bin/python -I /opt/biblio/app/deploy/retention.py
--copies /var/lib/biblio/sauvegardes --archive /var/backups/biblio --simulation`.

## Day to day, on the server (over SSH)

```bash
biblio stats                      # the CLI, with the service's database (biblio --help)
biblio backup                     # a copy now
sudo systemctl restart biblio     # restart
journalctl -u biblio -f           # log
systemctl list-timers biblio-backup.timer   # next copy (every night around 4:20)
```

Restoring a copy: `sudo systemctl stop biblio`, copy the backup over `/var/lib/biblio/biblio.db`
(`sudo install -o biblio -g biblio -m 600 …`), delete `biblio.db-wal` and `biblio.db-shm`, restart.

## The scripts

| Script | Runs on | Role |
|---|---|---|
| `diagnostic.sh` | computer → server | State of the server, without changing anything |
| `deployer.sh` | computer → server | Sends the code and runs `installer-serveur.sh` |
| `installer-serveur.sh` | server (root) | Installs or updates: packages, uv, user, systemd services; idempotent |
| `migrer-base.sh` | computer → server | Sends the database and the covers, then runs `importer-base.sh` |
| `importer-base.sh` | server (root) | Puts the received database in place, keeping the old one |
| `synchroniser.sh` | computer ↔ server | `biblio sync` one way or both |
| `ouvrir.sh` | computer | SSH tunnel to the server's local interface |
| `retention.py` | server (every night) | Archiving and sorting of the copies |
