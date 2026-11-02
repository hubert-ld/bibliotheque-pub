# Bibliothèque: full documentation

**English** · [Français](DOCUMENTATION.fr.md)

This document describes the whole software in detail. To get started quickly, the [README](README.md) is enough.

**Contents**

1. [Overview](#1-overview)
2. [Installation](#2-installation)
3. [First steps](#3-first-steps)
4. [Scanning](#4-scanning)
5. [Scanning with your phone](#5-scanning-with-your-phone)
6. [Books without a barcode](#6-books-without-a-barcode)
7. [The catalogue](#7-the-catalogue)
8. [A book's record](#8-a-books-record)
9. [Places, shelving and inventory](#9-places-shelving-and-inventory)
10. [Loans](#10-loans)
11. [Owners and gifts](#11-owners-and-gifts)
12. [Sharing, merging and syncing](#12-sharing-merging-and-syncing)
13. [Scanning a friend's library](#13-scanning-a-friends-library)
14. [Where the descriptions come from](#14-where-the-descriptions-come-from)
15. [Classification systems](#15-classification-systems)
16. [To do, statistics, exports](#16-to-do-statistics-exports)
17. [Settings, theme and language](#17-settings-theme-and-language)
18. [Command line reference](#18-command-line-reference)
19. [Data and backups](#19-data-and-backups)
20. [Troubleshooting](#20-troubleshooting)
21. [For development](#21-for-development)

---

## 1. Overview

The software manages a personal library: you scan books, they are described automatically from public catalogues, shelved in places, and given call numbers in seven classification systems. It runs on your computer: nothing is sent to an online service, apart from ISBN lookups in the catalogues.

Two ways to use it:

- **the local web app**, for scanning and browsing, in French or English;
- **the command line (CLI)**, in English, which does all of that and gives access to advanced operations.

**Vocabulary**

| Term | Meaning |
|---|---|
| **Record** | The description of an edition: title, authors, call numbers… One per ISBN. |
| **Copy** | A physical book. Two copies of the same book share the same record. |
| **Place** | A bookcase, a room, a box (“Lounge”). |
| **Shelf** | An optional subdivision of a place (“Shelf 2”). |
| **Call number** | The shelving label, for example `843 CAM`. |
| **Owner** | The person a copy belongs to: you or a friend. |

In this document, `biblio …` stands for your system's launcher: `./biblio.sh …` on macOS and Linux, `biblio.cmd …` on Windows.

---

## 2. Installation

The software needs **uv**, Astral's Python manager. uv installs Python (3.12 or later) and the dependencies by itself on first launch.

> The software is developed and tested on macOS. It is written to work on Linux and Windows too, but has not been tried there yet.

### macOS and Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reopen the terminal, go to the project folder, then:

```bash
./biblio.sh serve
```

The SQLite shell (`biblio sql` without an argument) needs the `sqlite3` program. It is already there on macOS. On Linux: `sudo apt install sqlite3` or `sudo dnf install sqlite`.

### Windows

In PowerShell:

```powershell
winget install --id=astral-sh.uv -e
```

Reopen the terminal, go to the project folder, then:

```powershell
.\biblio.cmd serve
```

For the SQLite shell (optional): `winget install SQLite.SQLite`.

### Where the Python environment and the data go

- **With the launcher**, the Python environment is kept outside the project, in `~/.virtualenvs/uv/bibliotheque`. This is useful if the folder is synced (OneDrive, Dropbox…). The `UV_PROJECT_ENVIRONMENT` variable lets you choose another location.
- **Without the launcher**, `uv run biblio serve` works too: uv then creates a `.venv` folder in the project.
- **The database and the covers** are in `data/`, in the project.
- **The phone mode certificates** stay outside the project, specific to each computer:

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/biblio/certs` |
| Windows | `%LOCALAPPDATA%\biblio\certs` |
| Linux | `~/.local/share/biblio/certs` (or `$XDG_DATA_HOME/biblio/certs`) |

### Updating the program

Replace the code, then restart the server. If the server was running during the update, a red banner reminds you. Since the software is in development, no older database version is maintained: it refuses to open a database from another version, without changing it.

---

## 3. First steps

1. Run `biblio serve`: the browser opens at http://localhost:8000.
2. **Settings**: enter your name (“Your name (owner of your books)”).
3. **Places**: create your bookcases and their shelves. This is not mandatory: you can scan without a place and shelve later.
4. **Scan**: choose the place and the shelf, then scan one book after another.
5. **To do**: complete the few books that could not be found.
6. **Catalogue**: browse, search, shelve in batches.

The top bar gives access to all the pages. It also shows how many books are being looked up, the classification system displayed, the theme and the language.

---

## 4. Scanning

### The barcode scanner

A barcode scanner behaves like a keyboard: it types the code, then Enter. There is nothing to install.

- The scan field keeps the focus: you can keep going without touching the mouse.
- **Scanning never waits for the network.** The book is saved at once, and its description arrives a few seconds later.
- **Sounds**: a high beep for a book added, a double beep for a book already owned or in the wrong place, a low beep for an error. The “Beeps” box turns them off.
- **QWERTY scanner on an AZERTY keyboard**: digits arrive as `çè&é…`. This is corrected automatically, on Mac as on PC.
- **Price code**: the 5 digits sometimes attached to the EAN are ignored.
- **Accidental double read**: two reads of the same code less than 4 seconds apart, at the same location, count as one book. For a genuine second copy in the same place, wait 4 seconds.
- **Without a scanner**: type the ISBN (10 or 13 digits, with or without hyphens) into the field and confirm.

### The four modes

| Mode | What a scan does |
|---|---|
| **Add** | One more copy at the chosen location. If you already have it, it is added anyway, with an alert saying where the others are. If a friend has it, the message says so. |
| **Move** | The book joins the chosen location. A book missing from your collection is flagged and not added. |
| **Where is it?** | Shows the location of each copy, including “lent to…” and “at Victor's”. |
| **Inventory** | Checks a shelf or a place (see [Inventory](#inventory-stocktaking)). |

The “Latest scans” column shows each book with its call number. A button lets you undo an addition.

### Memory scanner

If your scanner has a memory mode, you can scan far from the computer, then import the file:

```bash
biblio import codes.txt --place "Lounge/S1"
```

The file contains one code per line. Only the first field of a line separated by `;` or `,` is read, and lines starting with `#` are ignored. The place and the shelf are created if they do not exist. The books are then described, unless you use `--no-resolve`.

Each line counts as one copy: two identical lines make two copies. The command flags these duplicates and explains how to remove one that came from a double read.

### Network outage

If a scan does not reach the server (Wi-Fi down, server stopped), it is not lost: it is kept on the device, and appears as “Waiting” in the list. A banner shows how many are waiting, and an “Undo” button removes a kept scan. As soon as the server answers, the scans are sent in order, each with the mode and location chosen at the time of the scan, and their result replaces the line.

- Two reads of the same code less than 4 seconds apart count once, as usual.
- Kept scans survive closing the page: they are sent the next time it opens, on the same device and in the same browser.
- The page must already be open: without a connection, a browser cannot open it.
- A kept book has no title or call number yet: they arrive after sending.

### Choosing a wireless scanner

A wireless scanner works without changing anything in the software. What to look for when buying:

- **keyboard mode (HID)**;
- a **2.4 GHz USB dongle** rather than Bluetooth alone: no pairing, a more stable connection;
- a **memory mode**, to scan far from the computer;
- an adjustable keyboard layout and an “Enter” suffix;
- a 1D reader is enough for book EANs; a 2D reader also reads QR codes.

### Scanning in the terminal

```bash
biblio scan --place "Lounge/S1"
```

While scanning: `:place Bedroom/S2` changes location, `:mode add|move|where` changes mode, `:undo` undoes the latest addition, `:q` quits.

---

## 5. Scanning with your phone

The phone's camera replaces the barcode scanner. The phone and the computer must be on the same Wi-Fi.

```bash
biblio serve --phone
```

On the computer, open the **Phone** page (or run `biblio phone` to display the QR codes in the terminal).

1. **The first time, QR code 1**: installs the library's certificate on the phone, following the instructions displayed (iPhone or Android). This is needed because a browser only opens the camera over an encrypted connection. Do this once per phone.
2. **To scan, QR code 2**: opens the scanning station with the camera in full screen. Tap the screen to start: this turns on the beeps and keeps the screen awake.
3. **True full screen on iPhone**: from the scan page in Safari or Firefox, Share › “Add to Home Screen”. The “Bibliothèque” icon then opens the scanner with no browser bar.

**While scanning**: aim at the barcode. A beep, a green, orange or red flash and a vibration (Android) confirm the read, and the latest book appears at the bottom with its call number.

- The header shows the mode and the location: tap it to change them. All four modes are available there.
- The icons control the torch, switching camera, leaving full screen and closing.
- An arrow under the latest addition undoes it.
- The beeps sound even in silent mode, and music that is playing may pause.

**Firewall**: on first launch, allow Python to accept incoming connections.

| System | What to do |
|---|---|
| macOS | Accept the request displayed. |
| Windows | In the Windows Defender prompt, tick **Private networks**. |
| Linux | If a firewall is active: `sudo ufw allow 8443,8080/tcp` |

**Ports**: 8000 for the computer, 8443 for the phone (HTTPS), 8080 for installing the certificate. They can be changed: `--port`, `--phone-port`, `--install-port` (or the `BIBLIO_PORT_HTTPS` and
`BIBLIO_PORT_INSTALLATION` variables), for example on a Raspberry Pi where another service already uses 8080 and 8443
([deploy/README.md](deploy/README.md)).

**Security**

- The computer itself accesses the app freely. Any other device must present the secret key contained in QR code 2, which is then kept in a cookie. This key gives access to the whole app, except the QR codes.
- Other sites open in your browser can neither read the library nor write to it: the app refuses a write coming from another page, and an address that is not its own.
- The certificate installed on the phone is only valid for the local network (`localhost`, `.local` names, private addresses). Even if its private key leaked, it could not be used to impersonate another site. A certificate installed before this protection keeps working, without this limit; to benefit from it, delete `certs/` in the computer's data, then reinstall the certificate on the phone.
- Phone page › “Change the key” (or `biblio phone --new-key`) cuts off all phones already connected. They will have to scan the QR code again.
- The installation server (port 8080) only serves the certificate, and no library data.
- The server certificate renews itself, including when the IP address changes, with nothing to reinstall on the phone.
- Barcodes are decoded on the phone: natively on Android (Chrome), otherwise with `zxing-wasm`, bundled in the project. No external service is used.

---

## 6. Books without a barcode

**Look for an ISBN first.** Many books from the 1970s to 2000s have no barcode, but do carry a printed ISBN, often on the back of the title page. Type it into the scanning station's field: the record fills itself in.

**Otherwise**, open the manual addition page: the “No barcode?” link under the scan field (it uses the current location), or Catalogue › “+ Book without a barcode”. At the top of the page, choose the location and the owner. They apply to both routes:

**1. Look it up at the BnF** (optional) by title, author and year. The BnF is the French national library.

- The page lists the records found, and flags matching books already in your database.
- “Add this one”: if the record has an ISBN, the book follows the normal path of a scan. Otherwise, it receives a reference (`L12`), to type at the scanning station like an ISBN, and a complete record with call numbers, with no further request.

**2. Describe it by hand**, with all fields: title (the only mandatory field), subtitle, authors separated by `;`, publisher, collection, year, pages, form, audience, language, original language, ISBN, cover URL, subjects, summary and note.

- This form **never depends on the BnF**. If it finds nothing or does not answer, a message says so, the title and author you typed are carried over, and “Add” saves the book (status “entered by hand”).
- “Add and describe another one” returns to the form, keeping the location and the owner.
- If there is an input error, the form comes back as it was: nothing is lost.
- With an ISBN, the fields you entered are protected and the catalogues complete the empty ones.
- The form and the original language are used to compute the call number: without them, the book may stay “unclassified”.

**From the command line**

```bash
biblio manual --title "Mémoires" --authors "Camille Dupont" --place Lounge --form essai --year 1932
```

The command first queries the BnF and offers a numbered list (0 = none, save what was entered). `--no-search` goes straight to entering the book. Without `--title`, the title and authors are asked for.

---

## 7. The catalogue

**By default, the catalogue only shows your books.** The **Owner** section of the left column shows “My books” and, once friends' catalogues have been merged, each friend and “Everyone”.

### Searching and filtering

- **Search**: words from the title, author, publisher, collection, subjects, summary or notes. Accents are ignored, and the start of a word is enough (`cam` finds Camus). A complete ISBN is recognised directly.
- **Place and shelf**: including “Unshelved”.
- **Date added**: “Added” from … to …, with a “today” shortcut.
- **Classes**: the classes of the displayed system, with their number of books, plus “Unclassified”.
- **Sort**: shelving order, author, title, year, latest additions.
- **Display**: list or covers.
- **Classification**: choosing the system in the left column changes the call numbers displayed.
- **On a phone**: place, dates, classes, display and classification are grouped behind the **Filters** button, which shows the number of active filters. Tapping a book opens its record; the left column is used to tick it.

### Batch operations

These are done in **List** display. Tick books: an action bar appears.

- **Selection**: click a line, Shift+click for a range, the header box for the page, “Select all N results” for all the results of the search, across all pages.
- **Shelve**: moves the books to the chosen place or shelf. Refused if the selection contains someone else's book.
- **Give…**: changes the owner, after confirmation (see [Gifts](#gifts)).
- **Remove…**: removes the copies from the database. When it was a book's last copy, its record, call numbers and note disappear too.

A typical example: the “Unshelved” filter, “Select all N results”, then “Shelve”.

---

## 8. A book's record

### Copies

For each copy: its location, number, date added and owner. For your copies, you can also:

- **move** it (drop-down list);
- **lend** it or mark it as returned;
- **give** it away;
- **remove it from the collection**.

“+ Add a copy” saves one more copy. Friends' copies are shown as “at Victor's”, with no moving or lending possible.

**Duplicates.** `biblio duplicates` lists, without changing anything and for your own books only:

- the books you own in several copies, across all places;
- the records with the same title and author: another edition, or another volume;
- the extra copies at the same location (same place and same shelf).

`biblio duplicates --remove` removes the latter, after backing up the database to `data/sauvegardes/`. A copy with details (condition, purchase, inscription, note…) or that has already been lent is never removed. To keep a real second copy, give it a note: `biblio copy N --note "second copy"`. A book on another shelf or with no location stays too: it only appears in the list, for you to decide.

**Copy details…**: condition, purchase price and date, provenance (bookshop, inheritance, gift…), inscription, estimated value, a note specific to this object. Everything is empty by default and optional, can also be set with `biblio copy N`, and never goes into a share file. The price and the value feed the “Value of the collection” card in Statistics, and the Excel and CSV exports.

### Reading

The **Reading** card tracks what you do with the book: progress (to read, in progress, read, abandoned), start and end dates, a rating from 1 to 5 stars. Everything is empty by default. The catalogue's Reading column filters by status: “To read” gives your to-read pile. Statistics count books read per year, pages read and the average rating.

From the command line:

```bash
biblio read 978… --status read --rating 4 --finished 2026-10-30
```

```bash
biblio search --reading to-read
```

Statuses: `to-read`, `reading`, `read`, `abandoned`. An empty string (`--status ""`) clears it, and `--rating 0` removes the rating. This data is never shared with a friend, but syncing between your computers carries it over.

### Note

Each book has a **personal note in Markdown**, displayed formatted. “Add a note” or “Edit” opens the input area in place.

```markdown
## Grandfather's copy

- **leather** binding
- inscription on the flyleaf

> A quote

[Article to read](https://example.org)
```

- Headings, bold, italics, lists, quotes, links, tables, code and strikethrough are recognised.
- Raw HTML is not interpreted: a note cannot run a script.
- Links open in a new tab.
- Notes can be searched from the catalogue.
- They are never included in a share file.

From the command line:

```bash
biblio note 9782070360024
```

```bash
biblio note 9782070360024 --edit
```

`--edit` opens your text editor (`$EDITOR`). `--set "text"` replaces the note, and `--set ""` clears it.

### Call numbers

The **Call numbers** table shows the book's call number in each system, and its origin: from the catalogue, inferred automatically, or set by hand. “edit” lets you force a call number, which then takes priority. Leaving the field empty returns to the automatic calculation.

### Correcting the record

“Correct the record” lets you change every field. **A corrected field is protected**: a new catalogue lookup will not overwrite it. The “Protected fields” list lets you hand a field back to the catalogues.

### Sources

This card shows what each catalogue answered, with a link to its record. “Query the catalogues again” reruns the lookup for this book (not for a book without an ISBN). If a catalogue does not answer or no longer knows the book, its previous answer is kept: the record and its cover do not empty out.

---

## 9. Places, shelving and inventory

### Places and shelves

The **Places** page lets you create, rename and delete places and shelves. Several shelves can be created at once, separated by commas.

- Deleting a **place**: its books become “unshelved”.
- Deleting a **shelf**: its books stay in the place.
- “See the books” opens the filtered catalogue.

From the command line: `biblio place add|shelf|rename|remove|list`. The form `Place/Shelf` designates a shelf, regardless of capitals and accents.

### Shelving order

“Shelving order” on the Places page lists the books of a place or shelf in call number order, for the chosen system. The page can be printed: handy for tidying a shelf or sticking on labels.

### Inventory (stocktaking)

The inventory compares what is really on a shelf with what the database says.

1. Scanning station, **Inventory** mode: choose the place (and the shelf), then “Start the inventory”.
2. Scan everything that is there. The counters update live.
3. “Finish and see the report” shows:
   - the books **present**;
   - the books **not scanned**: shelved here according to the database, but not seen (elsewhere, lent or lost);
   - the books **found here, recorded elsewhere**;
   - the books **unknown** to the collection.
4. “Close” can, if you tick the boxes, record the books “from elsewhere” at this location and add the unknown ones.

The inventory counts copies: two copies of the same title on the shelf need two scans, more than 4 seconds apart. Otherwise, the second is flagged as not scanned. A book without an ISBN has no barcode: type its reference (`L12`, shown on its record) into the scan field.

From the command line: `biblio inventory "Lounge/S1"`, then `:done` for the report.

---

## 10. Loans

On the record, “Lend…” saves the borrower. The book then appears as “lent to Marie” in the catalogue and in “Where is it?”, and the badge on the **Loans** page updates.

The **Loans** page lists current loans, with a “Returned” button, and the history of finished loans.

```bash
biblio lend 9782070360024 Marie
```

```bash
biblio return 9782070360024
```

```bash
biblio loans
```

Only **your** copies can be lent. A book borrowed from a friend has no dedicated tracking: mention it in its record's note.

---

## 11. Owners and gifts

Each copy has an **owner**. Your books carry your name, set in Settings or with `biblio config proprietaire JD`. Changing this name renames all your copies. It is refused if that name already owns books in the database.

The owner belongs to the **copy**, not the record: if Victor and you have the same book, you share the same record, and each of you has your own copy.

### Gifts

A gift consists of **changing the owner**. For a loan, use “Lend…”: the two mechanisms are independent.

- **From the catalogue**: tick books, fill in “Give to…” and click “Give…”.
- **From the record**: “Give…” on the copy.
- **From the command line**: `biblio give 9782070360024 Victor`. You can give a copy number (see `biblio show`) instead of the ISBN.

Confirmation is always requested (`--yes` skips it in the CLI). Consequences of a gift:

- a current loan of this copy is closed;
- the book leaves its location;
- it disappears from “My books” and from your statistics.

**Receiving a book** works the same way. If the book is already in the database under a friend's name: “Change owner…” then your name. It arrives unshelved, ready to be put away. Otherwise, just scan it.

### What only concerns your books

| Feature | Friends' books |
|---|---|
| Catalogue | Hidden by default, visible with the Owner filter |
| Statistics, “To do” | Not counted |
| Shelving, loans, inventory, Move mode | Not concerned |
| “Where is it?” | Listed (“at Victor's”) |
| Excel and CSV export | Included, with an “Owner” column |

---

## 12. Sharing, merging and syncing

### Principle

Three operations, for three needs:

| Command | What for | What happens |
|---|---|---|
| `biblio share` | Give my catalogue to a friend | Creates a file with my books, without my personal data. |
| `biblio merge` | Receive a friend's catalogue | Their books stay theirs, and nothing of mine changes. |
| `biblio sync` | Bring together my databases from two computers | Additions, changes and removals propagate. The most recent change wins. |

**A person, a book or a copy has an identity** that follows it from one database to another. Names can change, and books without an ISBN do not get mixed up.

### Creating a share file

```bash
biblio share -o for-victor.db --hide-places
```

- `--hide-places`: your friend will know you have the book, not where it is shelved.
- `--place Lounge` (repeatable): only certain places.
- `--with-loans`: adds your loans, see [Sharing your loans](#sharing-your-loans).
- `--force`: replaces an old share file of the same name without asking.

Only an old share file can be replaced: the command refuses to overwrite your database or any other file.

In the app: Settings › “Share with a friend” (choice of places, boxes to hide places and to include your loans).

| In the file | Never in the file |
|---|---|
| Records, call numbers, catalogue answers (your friend has nothing to download again) | Your notes, your reading, your copy details (condition, price, provenance…) |
| Your copies, in your name | Your Google key and the phone key |
| Places, as text, unless hidden | Your settings, the history, the covers |
| Your loans, only with `--with-loans` | |

The covers download by themselves at your friend's, the first time they are displayed.

### Importing a friend's catalogue

First see what would change:

```bash
biblio merge for-alex.db --as Victor --dry-run
```

Then import it (a preview and a confirmation are displayed):

```bash
biblio merge for-alex.db --as Victor
```

- `--as Victor`: this friend's name at your place. It is only needed once: after that, they are recognised by their identity, even if they change their name. Without this option, the name stored in the file counts. If that name is yours, for example “Moi” on both sides, the command refuses and asks you for `--as`.
- `--replace`: also removes this friend's books and loans that are no longer in the file (books given away, sold…). Use it only if the file contains **their whole** catalogue, not part of it.
- `--yes`: does not ask for confirmation.

For an update, your friend sends you a new file, and you run the same command again.

### The import rules

- **No duplicates**: each copy has a stable identity. Importing the same file twice changes nothing.
- **The most recent wins**: between two versions of the same copy of your friend's, the last one changed is kept.
- **Your corrections are protected**: a field you corrected is never overwritten. A correction by your friend is taken where you made none, and followed if they change it later. The same goes for call numbers set by hand.
- **Your copies are never deleted**: `--replace` only removes your friend's.
- **A friend's file does not change your books**, not even a book they have since given you and that their database still attributes to them.
- **Only their own books are taken**: not yours, nor those of third parties present in their database.
- **Their notes, reading and copy details are never imported, and their loans only if they chose to share them**, even if you import their complete database.
- **Books without an ISBN** are recognised by their identity, otherwise by title and author.
- **A friend's places stay as text** (“at Victor's — Lounge › S2”): they do not appear in your places.
- **All or nothing**: an error along the way leaves nothing half done.
- **A backup copy** of your database is made first: `data/biblio-avant-fusion.db`, replaced each time.

### Sharing your loans

By default, a share file contains no loans, since loans carry the names of third parties. To include them:

```bash
biblio share -o for-victor.db --with-loans
```

Let your borrowers know if needed: their names and what they borrowed will be visible to the person receiving the file. Only loans of copies present in the file are taken: a book given away since, or from a place not selected, is not included.

For the person receiving the file:

- the **loan network** links friends to each other and to their borrowers;
- the catalogue and the record show that a friend's book is “lent to…”, which tells you whether it is available;
- these loans stay separate: the Loans page, the badge and the Statistics figures only count yours, and only your friend can close them, in their own database.

**A person is only recognised by their name**, regardless of capitals and accents. If Victor lent a book to “Alex” while your owner name is “JD”, the network will show two people: agree on the spelling.

**To withdraw your loans**: send a new file without the option. The person receiving it clears them by merging with `--replace`; without this option, they stay on their side.

### Hiding places afterwards

A file with hidden places does not clear places **already merged**: since the copies have not changed, the merge answers “Already up to date”. So decide before the first merge. Otherwise, clear them by hand:

```bash
biblio sql "UPDATE exemplaires SET lieu_texte = NULL WHERE proprietaire_id = (SELECT id FROM personnes WHERE nom = 'Victor')"
```

### Syncing two computers

With a separate database on each machine, copy the other machine's database (or access it over the network), then run:

```bash
biblio sync /path/to/the-other/biblio.db --dry-run
```

```bash
biblio sync /path/to/the-other/biblio.db
```

**Run the command on both sides**: each one only changes the database of the machine it runs on.

The first time, the command asks you to confirm that this database really is yours, since that is what makes its books yours. After that, it is recognised. A database copied from one machine to the other is recognised straight away.

What propagates:

| Data | Rule |
|---|---|
| Copies: additions, moves, details | The most recent change to each copy wins. |
| Copy removals | A removed book does not come back, unless it was changed on the other side after the removal. |
| Notes, reading, record corrections, manual call numbers | Field by field, the most recent wins: two changes to different fields are both kept. |
| Places and shelves | Recognised by their identity: a rename propagates, and so does a deletion (the books become unshelved). The same name created on both sides gives a single place. |
| Loans, move history | Carried over, including a loan's return. |
| Your name, your friends' names, their catalogues | Carried over. |

What stays specific to each machine: settings (language, displayed system, keys), inventories, covers.

Limits:

- the “last change” relies on each computer's clock;
- the same physical book scanned separately on both machines gives two copies, since nothing says it is the same object.

An error along the way leaves nothing half done, and a copy is made first: `data/biblio-avant-synchro.db`.

If the same folder is synced by OneDrive, there is only one database: no need for `sync`, but do not open the app on two computers at once.

---

## 13. Scanning a friend's library

The simplest way is to **create a separate database for your friend, scan their books into it, then import it into yours** with `biblio merge`.

- Their places stay theirs: they clutter neither your places nor the scanning station.
- Their books do not mix with yours during scanning: no false duplicates, no false shelving.
- You can give them this database, which becomes their own library.

An environment variable, `BIBLIO_DB`, tells the software which database to use. All commands run **from the project folder**.

### Step 1: prepare their database

Stop your usual server (Ctrl+C), then:

```bash
BIBLIO_DB=data/victor.db ./biblio.sh config proprietaire Victor
```

The database is created at this point.

On Windows, first set the variable, valid for this terminal. All the following commands there will then use Victor's database:

```powershell
$env:BIBLIO_DB = "data\victor.db"
.\biblio.cmd config proprietaire Victor
```

### Step 2: run the app on their database

```bash
BIBLIO_DB=data/victor.db ./biblio.sh serve --phone
```

Without a phone, remove `--phone`. **Before scanning, check which database is in use**: Settings › Data shows its path, which must end with `victor.db`.

### Step 3: scan at their place

Create their places and shelves, then scan as usual. Three ways to do it:

| Equipment | What you need | Remarks |
|---|---|---|
| **Computer + barcode scanner** | The computer on site | Internet is not needed to scan: the descriptions will wait. |
| **Computer + phone** | Both on the same Wi-Fi | On the phone, scan the “Scan” QR code again: the access key belongs to each database. The certificate stays valid. A guest Wi-Fi can stop devices from seeing each other. |
| **Memory scanner alone** | Nothing else on site | The lightest option, but you see nothing while scanning. Keep track of which codes go in which place: make one file per place. |

With a memory scanner, then import each file:

```bash
BIBLIO_DB=data/victor.db ./biblio.sh import lounge.txt --place "Lounge"
```

If some books stay “being looked up” or in “error” for lack of a network, finish once connected:

```bash
BIBLIO_DB=data/victor.db ./biblio.sh resolve --retry
```

Their books without a barcode are handled as usual, with the “No barcode?” link. The same book in two places triggers the duplicate alert: this is normal.

### Step 4: import it into your database

Stop the server (Ctrl+C), then, **without** `BIBLIO_DB`:

```bash
./biblio.sh merge data/victor.db --dry-run
```

```bash
./biblio.sh merge data/victor.db
```

Restart your app: the catalogue's **Owner** filter now offers Victor. Their books appear with “at Victor's — Lounge › S2”.

### If they prefer to keep their places to themselves

Do not merge `victor.db` directly: go through a share file. Make this choice **before** the first merge (see [Hiding places afterwards](#hiding-places-afterwards)).

```bash
BIBLIO_DB=data/victor.db ./biblio.sh share -o victor-share.db --hide-places
```

```bash
./biblio.sh merge victor-share.db
```

### Later: updating

Keep scanning into `data/victor.db`, then run the merge again. New books and moves are carried over. If you removed books they no longer have, add `--replace` so that they disappear on your side too:

```bash
./biblio.sh merge data/victor.db --replace
```

### Giving them their library

If Victor installs the software too, `victor.db` can become their database, already in their name. With the server stopped, copy `data/victor.db` into their project as `data/biblio.db`. If a non-empty `data/victor.db-wal` file remains, make a clean copy instead:

```bash
sqlite3 data/victor.db ".backup victor-copy.db"
```

They can then send you their updates themselves with `biblio share`. Since copy identifiers are preserved, your later merges will not create duplicates.

### If something goes wrong

**I forgot `BIBLIO_DB` and scanned their books into my database.** In the catalogue, filter with the “today” shortcut, tick the books concerned and use “Give…” to Victor. They are then in their name, but without their places.

**I mistyped the `BIBLIO_DB` path.** A new empty database is created without warning. Check the path shown in Settings.

**The phone shows “Access denied”.** It still has the other database's key: scan the “Scan” QR code again. The same goes for a home screen icon created on the other database.

---

## 14. Where the descriptions come from

A background task describes the books, with no daily quota, at a polite pace of about one request per second per catalogue. Allow 4 to 7 seconds per book, or 2 to 4 hours for 2,000 books.

| Source | Role |
|---|---|
| **BnF** (general catalogue, UNIMARC) | Main source for French books. Provides the Dewey number for non-fiction and the “cadre de classement” (classification framework) for fiction. |
| **Open Library** | Covers, English-language books, additional Dewey and LCC numbers. |
| **Library of Congress** | LCC and Dewey numbers for non-French books. |
| **Google Books** | Optional, only with a free API key (Settings, see [Getting a Google Books key](#getting-a-google-books-key)). Without a key, Google Books is not queried. With a key, it is only queried for books without a title or a summary. |

When several catalogues answer, the order of trust for descriptive fields is: BnF, Open Library, Google Books, Library of Congress.

**Raw answers are kept** (table `raw_responses`). An ISBN is therefore not queried again needlessly, and everything can be recomputed without a network.

**Covers** are downloaded once into `data/covers/`. If a catalogue has no image, the next one is tried: Open Library, then Google Books. A small `.absente` file records that none has one. `biblio covers` downloads the missing ones, `--missing` retries books noted as having no image, and `--force` retries everything.

**Useful commands**

- `biblio resolve`: describes pending books, even with no server running.
- `biblio resolve --retry`: retries books not found, network errors and catalogues that did not answer. Valid answers are kept.
- **To do** page › “Look up again books not found and errors”: the same thing in the app.

---

## 15. Classification systems

All call numbers are computed and stored for each book: switching systems (the “Classification” menu) is instant.

| System | CLI code | Used by | Where the call number comes from |
|---|---|---|---|
| **Dewey** (default) | `dewey` | Public libraries | BnF or Open Library for non-fiction. For novels, comics and children's books, which the BnF does not index in Dewey: inferred from the original language and the genre (French novel = 843, translated from English = 823, comics = 741.5, children's = “J 843”). |
| **BnF framework** | `cadre_bnf` | French national bibliography | Provided by the BnF; close to the sections of a bookshop. |
| **UDC** | `cdu` | Belgium, Switzerland, school libraries | Inferred from Dewey (821.133.1-31 = French novel). |
| **LCC** | `lcc` | English-speaking university libraries | Full call number for English-language books; otherwise an inferred subclass. |
| **Clil** | `clil` | French booksellers | **Inferred**: the official code is distributed by paid services (Electre, Dilicom). |
| **Thema** | `thema` | International book trade | **Inferred**, main categories. |
| **Custom sections** | `rayon` | Your own system | Your rules, in `rules/rayons.toml`. |

The official Dewey captions belong to OCLC and are not provided: books are grouped by range of hundreds (`800-899`). To display your own captions, add a `[libelles]` table to `rules/dewey.toml`, then run `biblio reclassify`.

The call number follows library practice: a class number and the first 3 letters of the author (`843 CAM`). Without an author, they are those of the first significant word of the title.

**Known limitations**

- For French novels, the BnF does not give the subgenre (crime, science fiction…). It is guessed from the collection (Série noire, Folio SF…) and the subjects: this is imperfect.
- Old BnF records sometimes carry an old Dewey number, taken as is.

In both cases, correct the call number by hand or enrich the rules.

### Forcing a call number

On the record, or:

```bash
biblio classify 9782070360024 dewey 843.914
```

Without a value, the command returns to the automatic calculation.

### Adapting the rules

Everything is in `rules/`:

| File | Content |
|---|---|
| `dewey.toml`, `cdu.toml`, `lcc.toml`, `cadre_bnf.toml` | Tables for these systems |
| `clil.toml`, `thema.toml`, `rayons.toml` | Rules, read in order |
| `mots.toml` | Shared keyword lists, called with `@name` |

For rules, **the first one that matches wins**. An example from `rules/rayons.toml`:

```toml
[[regle]]
abbr = "MAN"
libelle = "Mangas"
bd = true
mots = ["@manga"]
```

All the conditions of a rule must be true; in a list, a single value is enough.

| Condition | Meaning |
|---|---|
| `bd = true` | Comics |
| `fiction = true` | Novel, short stories, narrative |
| `public = ["jeunesse", "ado", "adulte"]` | Audience (children, teen, adult) |
| `forme = ["poesie", "theatre", …]` | Form |
| `dewey = ["84", "741.5"]` | Start of the Dewey number |
| `cadre = ["803"]` | Start of the BnF framework code |
| `langue = ["fre"]`, `langue_non = ["fre"]` | Original language |
| `mots = ["policier", "@policier"]` | Text, or a list from `mots.toml` |

After a change:

- `biblio reclassify` recomputes all call numbers;
- `biblio reclassify --reread` also rereads the stored answers and rebuilds the records (button Settings › “Recompute all call numbers”).

No network request is made, and fields and call numbers set by hand are kept.

---

## 16. To do, statistics, exports

### To do

The **To do** page (`biblio todo`) gathers what needs your attention, for your books:

| Section | What to do |
|---|---|
| Being looked up | Wait: a few seconds per book. |
| Network errors | Rerun once the connection is back. |
| Not found | Complete the record by hand. |
| Incomplete answers | The record is described, but a catalogue did not answer: rerun. |
| No call number in the displayed system | Enter the form or force a call number. |
| Unshelved | Shelve from the catalogue, the record or the scanning station. |

### Statistics

The **Statistics** page (summary: `biblio stats`) only counts your books:

- **Key figures**: books, distinct titles, authors, pages, pages per book on average, titles with several copies.
- **Activity**: books added over the last 12 months.
- **Reading**: books read, in progress and to read, pages read, average rating, books read per year, ratings given.
- **Loans**:
  - loan network: a graph where each person is a node and each link joins two people. A node's radius follows the logarithm of the number of books in their library, a link's thickness that of the number of loans. An empty circle marks a person whose library is unknown, a dotted link loans that were all returned. Hovering over a person highlights their links, and clicking opens their books. Links start from you, and also join your friends if they have [shared their loans](#sharing-your-loans);
  - current loans, with a bar per book showing how many days it has been out, oldest first;
  - current loans per borrower, and loans started each month over 12 months;
  - most frequent borrowers and most lent books;
  - current loans, total loans, number of borrowers and average number of days before return. A gift closes the current loan: it then counts as a return in this average.
- **The collection**: breakdown by class, place, author, publisher, decade of publication, original language, genre, audience, length and collection (without its number: “Folio ; 4082” counts as Folio), as well as the records (oldest, newest, longest and shortest books).
- **Shelving and records**:
  - fullest shelves;
  - titles with several copies, useful for spotting what you can give away;
  - record completeness, as a percentage;
  - state of the records;
  - condition of copies and value of the collection, based on what you entered.
- **At friends' places**, if you have imported a catalogue: for each friend, their copies, their titles, those you have too and those you do not.

Several cards switch between list, pie chart and bar chart, and the choice is remembered on the device. Names of books, authors, publishers, collections and shelves are links to the record or the catalogue. Hovering over or tapping a bar shows a tooltip with the details.

### Exports

- **Excel**: a general sheet, plus one sheet per place. Button in the catalogue and in Settings, or `biblio export`.
- **CSV**: a single table, `;` separator, readable by Excel with accents. `biblio export --format csv`.

One line per copy, all owners together, with all call numbers as columns. In the CLI, the file goes to `data/exports/`, unless you use `--output`.

---

## 17. Settings, theme and language

**Theme**: three icons at the top right. Automatic (follows the device's light or dark setting), light, dark. The choice belongs to each device and each browser.

**Language**: **FR · EN** at the top right, or Settings. It applies to the whole app and all devices. The CLI is always in English.

**Settings page**:

- interface language;
- classification system displayed by default;
- your owner name;
- Google Books API key (optional, free, 1,000 requests per day, “Books” API in the Google Cloud console);
- database path and number of answers kept;
- exports;
- recomputing call numbers;
- sharing with a friend.

**From the command line**:

```bash
biblio config
```

```bash
biblio config proprietaire JD
```

```bash
biblio config langue en
```

```bash
biblio config google_api_key --clear
```

`biblio config` without an argument shows all settings and the database path. `biblio system rayon` chooses the default system.

### Getting a Google Books key

The key is optional. It adds summaries and covers when the BnF and Open Library have none. You need a Google account.

**1. Create the key in the Google Cloud console**

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create a project (for example “bibliotheque”), or choose one.
2. In [the API library](https://console.cloud.google.com/apis/library/books.googleapis.com), open **Books API** and click **Enable**.
3. In [Credentials](https://console.cloud.google.com/apis/credentials), click **Create credentials** › **API key**.
4. Restrict the key: under **API restrictions**, choose **Restrict key**, then **Books API**. There is no need to add an application restriction: the software is neither a website nor a mobile app, and a home IP address can change.
5. Copy the whole key. It usually starts with `AIza`.

If the console asks you to enable billing, check what you would be charged before accepting. The daily quota (advertised at 1,000 requests) can be read in the quotas section of the Books API.

**2. Check the key**

Replace `YOUR_KEY`:

```bash
curl "https://www.googleapis.com/books/v1/volumes?q=isbn:9782070360024&key=YOUR_KEY"
```

An answer containing `totalItems` means the key works, even if that number is 0. An answer containing `error` gives the reason for the refusal.

**3. Save it in the software**

Paste it into the **Settings** page, field “Google Books API key”. This is the preferred method, since the key does not stay in the terminal history. From the command line:

```bash
biblio config google_api_key YOUR_KEY
```

The key is stored in the database and is never included in a share file. The `BIBLIO_GOOGLE_KEY` environment variable, if it exists, takes priority over this setting. Treat the key like a password. If it has leaked, delete it in the console and create another one.

**4. Complete books already described**

The key applies by itself to the next books scanned, but not to books already described: `biblio resolve --retry` only picks up books not found and errors. To query Google for books already found that have no summary, put them back as pending:

```bash
biblio sql "UPDATE notices SET statut = 'en_attente' WHERE statut = 'trouve' AND isbn13 IS NOT NULL AND (resume IS NULL OR resume = '')"
```

```bash
biblio resolve
```

This costs one Google request per book. The other catalogues' answers are kept: they are only queried again if they had failed or had not yet been consulted. Fields you corrected stay protected. Google is only queried once per book: if it does not know a book, the command will not ask again.

If the key is refused or the quota exceeded, the books stay described as before and the error is noted in their Sources card. Fix the cause, or wait until the next day for the quota, then run `biblio resolve --retry`.

---

## 18. Command line reference

`biblio --help` lists the commands, and `biblio <command> --help` details their options. Where a book is expected, `978…` stands for its ISBN, or its reference if it has none (`L12`).

### Places

| Command | Role |
|---|---|
| `place list` | Places, shelves and number of books |
| `place add NAME [-d DESCRIPTION]` | Create a place |
| `place shelf PLACE NAME [NAME…]` | Add shelves |
| `place rename OLD NEW` | Rename (`Place/Shelf` for a shelf) |
| `place remove SPEC [--yes]` | Delete; the books become unshelved (or stay in the place for a shelf) |

### Scanning and description

| Command | Role |
|---|---|
| `scan [-p PLACE] [-m add\|move\|where]` | Scan in the terminal |
| `import FILE [-p PLACE] [--no-resolve]` | Import a list of codes |
| `resolve [--retry]` | Describe pending books; `--retry` retries failures |
| `covers [--missing] [--force]` | Download missing covers |
| `manual [--title …] [--authors …] [-p PLACE] [--isbn …] [--owner NAME] [--no-search] …` | Book without a barcode (see `--help` for all fields) |

### Browsing

| Command | Role |
|---|---|
| `show 978…` | Everything about a book: record, reading, call numbers, copies |
| `where CODE` | Where is this book? (ISBN or words, across everyone) |
| `search [WORDS] [-p PLACE] [-s SYSTEM] [--sort …] [--since …] [--until …] [-o NAME\|all] [--reading …] [-n N]` | Search; your books by default |
| `list [-p PLACE] [-s SYSTEM] [--sort …] [-n N]` | List in shelving order |
| `todo` | What remains to be done |
| `stats` | A few figures |
| `owners` | Owners present |

Sorts: `shelf`, `title`, `author`, `year`, `added`.

### Corrections and shelving

| Command | Role |
|---|---|
| `edit 978… [--title …] [--form …] [--release FIELD] …` | Correct a record; `--release` hands a field back to the catalogues (French field name: `titre`, `forme`…) |
| `note 978… [--edit] [--set TEXT]` | Show or change the note |
| `read 978… [--status …] [--rating N] [--started DATE] [--finished DATE]` | Show or log your reading |
| `copy N [--condition …] [--price …] [--bought DATE] [--from …] [--inscription …] [--value …] [--note …]` | Show or fill in a copy's details |
| `classify 978… SYSTEM [VALUE] [--label …]` | Force a call number; without a value, back to automatic |
| `move 978… PLACE[/SHELF]` | Move (the place is created if needed) |
| `remove N [--yes]` | Remove a copy |
| `give 978…\|N NAME [--yes]` | Give |
| `inventory PLACE[/SHELF]` | Inventory |

### Loans

| Command | Role |
|---|---|
| `lend 978… NAME` | Lend |
| `return 978…` | Returned |
| `loans` | Current loans |

### Sharing, importing and syncing

| Command | Role |
|---|---|
| `share -o FILE [-p PLACE…] [--hide-places] [--with-loans] [--force]` | Create a share file |
| `merge FILE [--as NAME] [--replace] [--dry-run] [--yes]` | Import a friend's catalogue |
| `sync FILE [--dry-run] [--yes]` | Bring together my databases from two computers |

### Settings and data

| Command | Role |
|---|---|
| `system [SYSTEM]` | See or choose the default system |
| `config [KEY] [VALUE] [--clear]` | `google_api_key`, `systeme`, `langue`, `proprietaire` |
| `reclassify [--reread]` | Recompute call numbers, without a network |
| `export [-f xlsx\|csv] [-o FILE] [-s SYSTEM]` | Export |
| `backup [--dir FOLDER] [--keep N]` | Copy the database, even with the server running; 14 copies kept by default |
| `sql ["QUERY"]` | Direct SQL query, or SQLite shell without an argument |
| `serve [--port N] [--host H] [--phone] [--no-open]` | Run the web app |
| `phone [--new-key]` | Phone mode QR codes; change the key |

`biblio sql` can change anything: make a copy of the database before a write query.

---

## 19. Data and backups

### The files

| Location | Content |
|---|---|
| `data/biblio.db` | The SQLite database (with `-wal` and `-shm` during use) |
| `data/covers/` | The covers, shared by all the project's databases |
| `data/exports/` | CLI exports |
| `data/biblio-avant-fusion.db`, `data/biblio-avant-synchro.db` | Copies made before the last import or the last sync |
| `data/sauvegardes/` | Backup copies of the database |
| `rules/` | The classification rules |

### The tables

Table and column names are in French.

| Table | Content |
|---|---|
| `personnes` | Owners, lenders, borrowers: stable `uid`, `nom`, `cle` (name without case or accents) |
| `notices` | The book: stable `uid`, `isbn13` if it has one, description, `corrections` (corrected fields and their date), note and reading |
| `exemplaires` | The object: stable `uid`, `notice_id`, `proprietaire_id`, place, `lieu_texte` at a friend's, details (condition, price…), date `maj_le` |
| `classifications` | One call number per system and per record |
| `raw_responses` | The catalogues' raw answers |
| `lieux`, `etageres` | Your places, with their stable identity |
| `mouvements` | The history of moves |
| `inventaires`, `inventaire_scans` | Inventories |
| `prets` | Loans: `preteur_id`, `emprunteur_id` |
| `suppressions` | What has been removed, so that syncing does not bring it back |
| `meta` | Settings |
| `notices_fts` | The search index |
| `exemplaires_v`, `prets_v` | Handy views for `biblio sql`: with people's names |

### Backing up

`biblio serve` copies the database to `data/sauvegardes/` when it starts, if the last copy is more than a day old. To make one at any time, even with the server running:

```bash
biblio backup
```

Each copy fits in a single dated file, for example `biblio-2026-11-01-143000.db`. The last 14 of each database are kept (`--keep` to change this number, `--dir` for another folder, for example an external drive). Covers are not included: they download again. To keep them too, copy `data/covers/`.

### Restoring

Stop the server, delete `data/biblio.db-wal` and `data/biblio.db-shm` if they exist, then replace `data/biblio.db` with the chosen copy.

### In a synced folder

OneDrive or an equivalent service is not a backup of the database: while in use, it lives in three files (`.db`, `-wal`, `-shm`) that syncing copies separately, and a SQLite database copes badly with being changed in two places. Do not open the app on two computers at once, and wait for syncing to finish before switching machines. The copies in `data/sauvegardes/`, on the other hand, are consistent: syncing keeps them safe.

### Environment variables

| Variable | Role |
|---|---|
| `BIBLIO_DB` | Path of the database to use |
| `BIBLIO_RULES` | Folder of the classification rules |
| `BIBLIO_CERTS` | Folder of the certificates |
| `BIBLIO_COVERS` | Folder of the covers |
| `BIBLIO_GOOGLE_KEY` | Google Books key, takes priority over the setting |
| `UV_PROJECT_ENVIRONMENT` | Location of the Python environment |

To try something without risk, work on a copy:

```bash
BIBLIO_DB=/tmp/trial.db ./biblio.sh serve
```

On Windows, in PowerShell: `$env:BIBLIO_DB = "C:\path\trial.db"`, then the command. In the command prompt: `set BIBLIO_DB=C:\path\trial.db`.

---

## 20. Troubleshooting

| Symptom | Cause and solution |
|---|---|
| `port 8000 is already in use` | The library is already running in another terminal: stop it (Ctrl+C), or choose `--port`. |
| `uv` not found after installing | Reopen the terminal. |
| Red banner saying the program was updated | Restart the server. |
| Strange layout after an update | Force a reload (Cmd+Shift+R, or Ctrl+Shift+R). |
| The phone cannot reach the page | Same Wi-Fi? A guest Wi-Fi can isolate devices. Is the server running with `--phone`? Check the firewall (see [section 5](#5-scanning-with-your-phone)). |
| “Access denied” on the phone | The key changed, or you switched database: scan the “Scan” QR code again. For a home screen icon: delete it, then recreate it from the QR code in Safari. |
| The camera does not open | The certificate is probably not installed: QR code 1. On iPhone, only Safari installs it, and trust must be enabled in Settings › General › About › Certificate Trust Settings. |
| A book stays “being looked up” | The server must be running for lookups to progress; otherwise run `biblio resolve`. |
| A book is “not found” | No catalogue knows it: complete the record, or try `biblio resolve --retry` later. |
| A book is “unclassified” | Enter its form (novel, essay…) on the record, or force a call number. |
| Approximate subgenre or call number | Correct it on the record, or enrich `rules/mots.toml`. |
| The Google key changes nothing | Books already described are not queried again by themselves: see [Getting a Google Books key](#getting-a-google-books-key), step 4. To see the errors: `biblio sql "SELECT payload, count(*) FROM raw_responses WHERE source = 'google' AND statut = 'erreur' GROUP BY payload"`. `HTTP 400` means an invalid key. |
| Odd digits read by the scanner | Normally corrected. Otherwise, set its keyboard layout and its “Enter” suffix. |
| `sqlite3 not found` | Install it, or pass the query as an argument: `biblio sql "select …"`. |
| `was made by another version of this program` | The database comes from another version of the software: it has not been changed, but cannot be opened. |
| Error about a database from another version when importing | The two copies of the software do not have the same version: update them. |
| `this file is not a library database` | The file is not a database for this software, or it is damaged. |
| `this file carries your own name` | A friend's file carries your name, for example “Moi” on both sides: run again with `--as NAME`. |
| `this file comes from your own database` | It is one of your databases: use `biblio sync`. |
| `this is a share file` | A friend's file: use `biblio merge`. |
| An import or a sync is not what you wanted | Restore `data/biblio-avant-fusion.db` or `data/biblio-avant-synchro.db` (see [Restoring](#restoring)). |
| “Request refused: it does not come from the library.” | The app was called from another page or under another address: open it at http://localhost:8000. |
| Shelving orders changed after an update | Normal: `843` now comes before `843.914`, and LCC call numbers are compared as numbers. Everything is recomputed once, without a network, at launch. |
| Victor's books do not appear | By default, the catalogue shows your books: choose Victor or “Everyone” in the Owner section. |
| My books have disappeared from the catalogue | First look at the Owner filter, then the database path in Settings: `BIBLIO_DB` may point elsewhere. |

---

## 21. For development

```bash
uv run pytest
```

The tests do not use the network: the catalogue readers are tested on real answers recorded in `tests/fixtures/`. They never touch the real database, the covers or the certificates.

| Element | Location |
|---|---|
| Shared business logic | `biblio/services.py` |
| Database and schema | `biblio/db.py` |
| Sharing, importing from a friend, syncing | `biblio/partage.py` |
| Backup copies | `biblio/sauvegarde.py` |
| Catalogues | `biblio/sources/`, assembled by `biblio/resolver.py` |
| Call number computation | `biblio/classify/`, with `rules/` |
| Web app | `biblio/web/` |
| CLI | `biblio/cli.py` |
| Translations | `biblio/traductions.py` |

Every sentence displayed by the interface must have its English translation in `biblio/traductions.py`: a test checks this. The key is the exact French text.
