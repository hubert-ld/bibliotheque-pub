# Bibliothèque : documentation complète

[English](DOCUMENTATION.md) · **Français**

Ce document décrit tout le logiciel en détail. Pour démarrer vite, le [README](README.fr.md) suffit.

**Sommaire**

1. [Vue d'ensemble](#1-vue-densemble)
2. [Installation](#2-installation)
3. [Premiers pas](#3-premiers-pas)
4. [Scanner](#4-scanner)
5. [Scanner avec le téléphone](#5-scanner-avec-le-téléphone)
6. [Livres sans code-barre](#6-livres-sans-code-barre)
7. [Le catalogue](#7-le-catalogue)
8. [La fiche d'un livre](#8-la-fiche-dun-livre)
9. [Lieux, rangement et inventaire](#9-lieux-rangement-et-inventaire)
10. [Prêts](#10-prêts)
11. [Propriétaires et dons](#11-propriétaires-et-dons)
12. [Partage, fusion et synchronisation](#12-partage-fusion-et-synchronisation)
13. [Scanner la bibliothèque d'un ami](#13-scanner-la-bibliothèque-dun-ami)
14. [D'où viennent les descriptions](#14-doù-viennent-les-descriptions)
15. [Les systèmes de classement](#15-les-systèmes-de-classement)
16. [À traiter, statistiques, exports](#16-à-traiter-statistiques-exports)
17. [Réglages, thème et langue](#17-réglages-thème-et-langue)
18. [Référence de la ligne de commande](#18-référence-de-la-ligne-de-commande)
19. [Données et sauvegardes](#19-données-et-sauvegardes)
20. [Dépannage](#20-dépannage)
21. [Pour le développement](#21-pour-le-développement)

---

## 1. Vue d'ensemble

Le logiciel gère une bibliothèque personnelle : on scanne les livres, ils sont décrits automatiquement à partir de catalogues publics, rangés dans des lieux, et cotés dans sept systèmes de classement. Il tourne sur votre ordinateur : rien n'est envoyé à un service en ligne, à part les recherches d'ISBN dans les catalogues.

Deux façons de l'utiliser :

- **l'appli web locale**, pour scanner et consulter, en français ou en anglais ;
- **la ligne de commande (CLI)**, en anglais, qui fait tout cela et donne accès aux opérations avancées.

**Vocabulaire**

| Terme | Sens |
|---|---|
| **Notice** (fiche) | La description d'une édition : titre, auteurs, cotes… Une par ISBN. |
| **Exemplaire** | Un livre physique. Deux exemplaires du même livre partagent la même notice. |
| **Lieu** | Une bibliothèque, une pièce, un carton (« Salon »). |
| **Étagère** | Une subdivision facultative d'un lieu (« Étagère 2 »). |
| **Cote** | L'étiquette de rangement, par exemple `843 CAM`. |
| **Propriétaire** | La personne à qui appartient un exemplaire : vous ou un ami. |

Dans ce document, `biblio …` désigne le lanceur de votre système : `./biblio.sh …` sous macOS et Linux, `biblio.cmd …` sous Windows.

---

## 2. Installation

Le logiciel a besoin de **uv**, le gestionnaire Python d'Astral. uv installe lui-même Python (3.12 ou plus) et les dépendances au premier lancement.

> Le logiciel est développé et testé sur macOS. Il est écrit pour fonctionner aussi sous Linux et Windows, mais il n'y a pas encore été essayé.

### macOS et Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Rouvrez le terminal, placez-vous dans le dossier du projet, puis :

```bash
./biblio.sh serve
```

Le shell SQLite (`biblio sql` sans argument) demande le programme `sqlite3`. Il est déjà présent sur macOS. Sous Linux : `sudo apt install sqlite3` ou `sudo dnf install sqlite`.

### Windows

Dans PowerShell :

```powershell
winget install --id=astral-sh.uv -e
```

Rouvrez le terminal, placez-vous dans le dossier du projet, puis :

```powershell
.\biblio.cmd serve
```

Pour le shell SQLite (facultatif) : `winget install SQLite.SQLite`.

### Où vont l'environnement Python et les données

- **Avec le lanceur**, l'environnement Python est rangé hors du projet, dans `~/.virtualenvs/uv/bibliotheque`. C'est utile si le dossier est synchronisé (OneDrive, Dropbox…). La variable `UV_PROJECT_ENVIRONMENT` permet de choisir un autre emplacement.
- **Sans lanceur**, `uv run biblio serve` marche aussi : uv crée alors un dossier `.venv` dans le projet.
- **La base et les couvertures** sont dans `data/`, dans le projet.
- **Les certificats du mode téléphone** restent hors du projet, propres à chaque ordinateur :

| Système | Dossier |
|---|---|
| macOS | `~/Library/Application Support/biblio/certs` |
| Windows | `%LOCALAPPDATA%\biblio\certs` |
| Linux | `~/.local/share/biblio/certs` (ou `$XDG_DATA_HOME/biblio/certs`) |

### Mettre à jour le programme

Remplacez le code, puis redémarrez le serveur. Si le serveur tournait pendant la mise à jour, un bandeau rouge vous le rappelle. Le logiciel étant en développement, aucune ancienne version de la base n'est maintenue : il refuse d'ouvrir une base d'une autre version, sans la modifier.

---

## 3. Premiers pas

1. Lancez `biblio serve` : le navigateur s'ouvre sur http://localhost:8000.
2. **Réglages** : indiquez votre nom (« Votre nom (propriétaire de vos livres) »).
3. **Lieux** : créez vos bibliothèques et leurs étagères. Ce n'est pas obligatoire : on peut scanner sans lieu et ranger plus tard.
4. **Scanner** : choisissez le lieu et l'étagère, puis scannez à la chaîne.
5. **À traiter** : complétez les rares livres introuvables.
6. **Catalogue** : consultez, cherchez, rangez par lots.

La barre du haut donne accès à toutes les pages. Elle indique aussi combien de livres sont en cours de recherche, le système de classement affiché, le thème et la langue.

---

## 4. Scanner

### La douchette

Une douchette se comporte comme un clavier : elle tape le code puis Entrée. Il n'y a rien à installer.

- Le champ de scan garde le focus : vous pouvez enchaîner sans toucher à la souris.
- **Le scan n'attend jamais le réseau.** Le livre est enregistré tout de suite, et sa description arrive quelques secondes plus tard.
- **Sons** : un bip aigu pour un livre ajouté, un double bip pour un livre déjà possédé ou mal rangé, un bip grave pour une erreur. La case « Bips sonores » les coupe.
- **Douchette en QWERTY sur un clavier AZERTY** : les chiffres arrivent en `çè&é…`. C'est corrigé automatiquement, sur Mac comme sur PC.
- **Code prix** : les 5 chiffres parfois collés à l'EAN sont ignorés.
- **Double lecture accidentelle** : deux lectures du même code en moins de 4 secondes, au même emplacement, comptent pour un seul livre. Pour un vrai second exemplaire au même endroit, attendez 4 secondes.
- **Sans douchette** : tapez l'ISBN (10 ou 13 chiffres, avec ou sans tirets) dans le champ et validez.

### Les quatre modes

| Mode | Effet d'un scan |
|---|---|
| **Ajouter** | Un exemplaire de plus à l'emplacement choisi. Si vous l'avez déjà, il est ajouté quand même, avec une alerte qui dit où sont les autres. Si un ami l'a, le message le signale. |
| **Déplacer** | Le livre rejoint l'emplacement choisi. Un livre absent de votre collection est signalé et n'est pas ajouté. |
| **Où est-il ?** | Affiche l'emplacement de chaque exemplaire, y compris « prêté à… » et « chez Victor ». |
| **Inventaire** | Vérifie une étagère ou un lieu (voir [Inventaire](#inventaire-récolement)). |

La colonne « Derniers scans » affiche chaque livre avec sa cote. Un bouton permet d'annuler un ajout.

### Douchette à mémoire

Si votre douchette a un mode mémoire, on peut scanner loin de l'ordinateur, puis importer le fichier :

```bash
biblio import codes.txt --place "Salon/É1"
```

Le fichier contient un code par ligne. Seul le premier champ d'une ligne séparée par `;` ou `,` est lu, et les lignes commençant par `#` sont ignorées. Le lieu et l'étagère sont créés s'ils n'existent pas. Les livres sont ensuite décrits, sauf avec `--no-resolve`.

Chaque ligne compte pour un exemplaire : deux lignes identiques font deux exemplaires. La commande signale ces doublons et indique comment retirer celui qui viendrait d'une double lecture.

### Coupure réseau

Si un scan n'atteint pas le serveur (Wi-Fi coupé, serveur arrêté), il n'est pas perdu : il est gardé sur l'appareil, et apparaît « En attente » dans la liste. Un bandeau indique combien attendent, et un bouton « Annuler » retire un scan gardé. Dès que le serveur répond, les scans partent dans l'ordre, chacun avec le mode et l'emplacement choisis au moment du scan, et leur résultat remplace la ligne.

- Deux lectures du même code en moins de 4 secondes ne comptent qu'une fois, comme d'habitude.
- Les scans gardés survivent à la fermeture de la page : ils partent à sa prochaine ouverture, sur le même appareil et le même navigateur.
- La page doit être déjà ouverte : sans connexion, un navigateur ne peut pas l'ouvrir.
- Un livre gardé n'a pas encore de titre ni de cote : ils arrivent après l'envoi.

### Choisir une douchette sans fil

Une douchette sans fil marche sans rien changer au logiciel. À regarder à l'achat :

- le **mode clavier (HID)** ;
- un **dongle USB 2,4 GHz** plutôt que Bluetooth seul : pas d'appairage, connexion plus stable ;
- un **mode mémoire**, pour scanner loin de l'ordinateur ;
- une disposition clavier réglable et le suffixe « Entrée » ;
- un lecteur 1D suffit pour les EAN des livres ; un lecteur 2D lit aussi les QR codes.

### Scanner dans le terminal

```bash
biblio scan --place "Salon/É1"
```

Pendant le scan : `:place Chambre/É2` change d'emplacement, `:mode add|move|where` change de mode, `:undo` annule le dernier ajout, `:q` quitte.

---

## 5. Scanner avec le téléphone

La caméra du téléphone remplace la douchette. Le téléphone et l'ordinateur doivent être sur le même Wi-Fi.

```bash
biblio serve --phone
```

Sur l'ordinateur, ouvrez la page **Téléphone** (ou lancez `biblio phone` pour afficher les QR codes dans le terminal).

1. **Première fois, QR code 1** : il installe sur le téléphone le certificat de la bibliothèque, en suivant les instructions affichées (iPhone ou Android). C'est nécessaire parce qu'un navigateur n'ouvre la caméra que sur une connexion chiffrée. À faire une seule fois par téléphone.
2. **Pour scanner, QR code 2** : il ouvre le poste de scan avec la caméra en plein écran. Touchez l'écran pour commencer : cela active les bips et garde l'écran allumé.
3. **Vrai plein écran sur iPhone** : depuis la page de scan dans Safari ou Firefox, Partager › « Sur l'écran d'accueil ». L'icône « Bibliothèque » ouvre alors le scan sans barre de navigateur.

**Pendant le scan** : visez le code-barres. Un bip, un flash vert, orange ou rouge et une vibration (Android) confirment la lecture, et le dernier livre s'affiche en bas avec sa cote.

- L'en-tête indique le mode et l'emplacement : touchez-le pour les changer. Les quatre modes y sont disponibles.
- Les icônes commandent la lampe, le changement de caméra, la sortie du plein écran et la fermeture.
- Une flèche sous le dernier ajout l'annule.
- Les bips sonnent même en mode silencieux, et une musique en cours peut se mettre en pause.

**Pare-feu** : au premier lancement, autorisez Python à accepter les connexions entrantes.

| Système | Que faire |
|---|---|
| macOS | Acceptez la demande affichée. |
| Windows | Dans l'invite de Windows Defender, cochez **Réseaux privés**. |
| Linux | Si un pare-feu est actif : `sudo ufw allow 8443,8080/tcp` |

**Ports** : 8000 pour l'ordinateur, 8443 pour le téléphone (HTTPS), 8080 pour l'installation du certificat. Ils se changent : `--port`, `--phone-port`, `--install-port` (ou les variables `BIBLIO_PORT_HTTPS` et
`BIBLIO_PORT_INSTALLATION`), par exemple sur un Raspberry Pi où un autre service occupe déjà 8080 et 8443
([deploy/README.fr.md](deploy/README.fr.md)).

**Sécurité**

- L'ordinateur lui-même accède librement à l'appli. Tout autre appareil doit présenter la clé secrète contenue dans le QR code 2, qui est ensuite gardée dans un cookie. Cette clé donne accès à toute l'appli, sauf aux QR codes.
- Les autres sites ouverts dans votre navigateur ne peuvent ni lire la bibliothèque ni y écrire : l'appli refuse une écriture venue d'une autre page, et une adresse qui n'est pas la sienne.
- Le certificat installé sur le téléphone ne vaut que pour le réseau local (`localhost`, noms en `.local`, adresses privées). Même si sa clé privée fuitait, il ne permettrait pas d'imiter un autre site. Un certificat installé avant cette protection continue de fonctionner, sans cette limite ; pour en profiter, supprimez `certs/` dans les données de l'ordinateur, puis réinstallez le certificat sur le téléphone.
- Page Téléphone › « Changer la clé » (ou `biblio phone --new-key`) coupe l'accès de tous les téléphones déjà connectés. Ils devront rescanner le QR code.
- Le serveur d'installation (port 8080) ne sert que le certificat, aucune donnée de la bibliothèque.
- Le certificat du serveur se renouvelle seul, y compris quand l'adresse IP change, sans rien réinstaller sur le téléphone.
- Le décodage des codes-barres se fait dans le téléphone : natif sur Android (Chrome), sinon `zxing-wasm`, embarqué dans le projet. Aucun service externe n'est utilisé.

---

## 6. Livres sans code-barre

**Cherchez d'abord un ISBN.** Beaucoup de livres des années 1970 à 2000 n'ont pas de code-barre, mais portent un ISBN imprimé, souvent au verso de la page de titre. Tapez-le dans le champ du poste de scan : la fiche se remplit seule.

**Sinon**, ouvrez la page d'ajout manuel : lien « Pas de code-barre ? » sous le champ de scan (il reprend l'emplacement courant), ou Catalogue › « + Livre sans code-barre ». En haut de la page, choisissez l'emplacement et le propriétaire. Ils valent pour les deux parcours :

**1. Chercher à la BnF** (facultatif) par titre, auteur et année.

- La page liste les notices trouvées, et signale les livres correspondants déjà dans votre base.
- « Ajouter celui-ci » : si la notice a un ISBN, le livre suit le circuit normal d'un scan. Sinon, il reçoit une référence (`L12`), à taper au poste de scan comme un ISBN, et une fiche complète et cotée, sans autre requête.

**2. Saisir à la main**, avec tous les champs : titre (seul champ obligatoire), sous-titre, auteurs séparés par `;`, éditeur, collection, année, pages, forme, public, langue, langue d'origine, ISBN, URL de couverture, sujets, résumé et note.

- Ce formulaire **ne dépend jamais de la BnF**. Si elle ne trouve rien ou ne répond pas, un message le signale, le titre et l'auteur tapés sont recopiés, et « Ajouter » enregistre le livre (statut « saisi à la main »).
- « Ajouter et en saisir un autre » revient au formulaire en gardant l'emplacement et le propriétaire.
- En cas d'erreur de saisie, le formulaire revient tel quel : rien n'est perdu.
- Avec un ISBN, les champs saisis sont protégés et les catalogues complètent les champs vides.
- La forme et la langue d'origine servent à calculer la cote : sans elles, le livre risque de rester « à classer ».

**En ligne de commande**

```bash
biblio manual --title "Mémoires" --authors "Camille Dupont" --place Salon --form essai --year 1932
```

La commande interroge d'abord la BnF et propose une liste numérotée (0 = aucun, enregistrer ce qui a été saisi). `--no-search` passe directement à la saisie. Sans `--title`, le titre et les auteurs sont demandés.

---

## 7. Le catalogue

**Par défaut, le catalogue ne montre que vos livres.** La section **Propriétaire** de la colonne de gauche indique « Mes livres » et, une fois des catalogues d'amis fusionnés, chaque ami et « Tout le monde ».

### Rechercher et filtrer

- **Recherche** : mots du titre, de l'auteur, de l'éditeur, de la collection, des sujets, du résumé ou des notes. Les accents sont ignorés, et un début de mot suffit (`cam` trouve Camus). Un ISBN complet est reconnu directement.
- **Lieu et étagère** : y compris « Non localisés ».
- **Date d'ajout** : « Ajoutés du … au … », avec un raccourci « aujourd'hui ».
- **Classes** : les classes du système affiché, avec leur nombre de livres, plus « À classer ».
- **Tri** : ordre de rangement, auteur, titre, année, derniers ajouts.
- **Affichage** : liste ou couvertures.
- **Classement** : le choix du système dans la colonne de gauche change les cotes affichées.
- **Sur téléphone** : lieu, dates, classes, affichage et classement sont regroupés derrière le bouton **Filtres**, qui indique le nombre de filtres actifs. Toucher un livre ouvre sa fiche ; la colonne de gauche sert à le cocher.

### Opérations groupées

Elles se font en affichage **Liste**. Cochez des livres : une barre d'opérations apparaît.

- **Sélection** : clic sur une ligne, Maj+clic pour une plage, case d'en-tête pour la page, « Sélectionner les N résultats » pour tous les résultats de la recherche, sur toutes les pages.
- **Ranger** : déplace les livres vers le lieu ou l'étagère choisis. Refusé si la sélection contient le livre de quelqu'un d'autre.
- **Donner…** : change le propriétaire, après confirmation (voir [Dons](#les-dons)).
- **Retirer…** : retire les exemplaires de la base. Quand c'était le dernier exemplaire d'un livre, sa fiche, ses cotes et sa note disparaissent aussi.

Exemple typique : filtre « Non localisés », « Sélectionner les N résultats », puis « Ranger ».

---

## 8. La fiche d'un livre

### Exemplaires

Pour chaque exemplaire : son emplacement, son numéro, sa date d'ajout et son propriétaire. Pour vos exemplaires, on peut aussi :

- le **déplacer** (liste déroulante) ;
- le **prêter** ou le marquer comme rendu ;
- le **donner** ;
- le **retirer de la collection**.

« + Ajouter un exemplaire » enregistre un exemplaire de plus. Les exemplaires des amis sont affichés « chez Victor », sans déplacement ni prêt possible.

**Doublons.** `biblio duplicates` liste, sans rien modifier et pour vos livres seulement :

- les livres que vous avez en plusieurs exemplaires, tous lieux confondus ;
- les fiches de même titre et même auteur : une autre édition, ou un autre tome ;
- les exemplaires de trop au même emplacement (même lieu et même étagère).

`biblio duplicates --remove` retire ces derniers, après une copie de la base dans `data/sauvegardes/`. Un exemplaire renseigné (état, achat, dédicace, note…) ou déjà prêté n'est jamais retiré. Pour garder un vrai second exemplaire, donnez-lui une note : `biblio copy N° --note "second exemplaire"`. Un livre sur une autre étagère ou non localisé reste aussi : il figure seulement dans la liste, à vous de voir.

**Détails de l'exemplaire…** : état, prix et date d'achat, provenance (librairie, héritage, cadeau…), dédicace, valeur estimée, note propre à cet objet. Tout est vide par défaut et facultatif, se règle aussi par `biblio copy N°`, et n'entre jamais dans un fichier de partage. Le prix et la valeur alimentent la carte « Valeur de la collection » des Statistiques, et les exports Excel et CSV.

### Lecture

La carte **Lecture** suit ce que vous en faites : avancement (à lire, en cours, lu, abandonné), dates de début et de fin, note de 1 à 5 étoiles. Tout est vide par défaut. La colonne Lecture du catalogue filtre par état : « À lire » donne votre pile à lire. Les Statistiques comptent les livres lus par an, les pages lues et la note moyenne.

En ligne de commande :

```bash
biblio read 978… --status read --rating 4 --finished 2026-10-30
```

```bash
biblio search --reading to-read
```

États : `to-read`, `reading`, `read`, `abandoned`. Une chaîne vide (`--status ""`) efface, et `--rating 0` retire la note. Ces données ne sont jamais partagées avec un ami, mais la synchronisation entre vos ordinateurs les reprend.

### Note

Chaque livre a une **note personnelle en Markdown**, affichée mise en forme. « Ajouter une note » ou « Modifier » ouvre la zone de saisie sur place.

```markdown
## Exemplaire de grand-père

- reliure **cuir**
- dédicace en page de garde

> Une citation

[Article à lire](https://exemple.org)
```

- Titres, gras, italique, listes, citations, liens, tableaux, code et texte barré sont reconnus.
- Le HTML brut n'est pas interprété : une note ne peut pas exécuter de script.
- Les liens s'ouvrent dans un nouvel onglet.
- Les notes sont cherchables depuis le catalogue.
- Elles ne sont jamais incluses dans un fichier de partage.

En ligne de commande :

```bash
biblio note 9782070360024
```

```bash
biblio note 9782070360024 --edit
```

`--edit` ouvre votre éditeur de texte (`$EDITOR`). `--set "texte"` remplace la note, et `--set ""` l'efface.

### Cotes

Le tableau **Cotes** montre la cote du livre dans chaque système, et son origine : fourni par le catalogue, déduit automatiquement, ou fixé à la main. « modifier » permet d'imposer une cote : elle est alors prioritaire. Laisser le champ vide revient au calcul automatique.

### Corriger la fiche

« Corriger la fiche » permet de modifier tous les champs. **Un champ corrigé est protégé** : une nouvelle recherche dans les catalogues ne l'écrasera pas. La liste « Champs protégés » permet de rendre un champ aux catalogues.

### Sources

Cette carte indique ce que chaque catalogue a répondu, avec un lien vers sa notice. « Réinterroger les catalogues » relance la recherche pour ce livre (pas pour un livre sans ISBN). Si un catalogue ne répond pas ou ne connaît plus le livre, sa réponse précédente est conservée : la fiche et sa couverture ne se vident pas.

---

## 9. Lieux, rangement et inventaire

### Lieux et étagères

La page **Lieux** permet de créer, renommer et supprimer les lieux et les étagères. Plusieurs étagères peuvent être créées d'un coup, séparées par des virgules.

- Supprimer un **lieu** : ses livres deviennent « non localisés ».
- Supprimer une **étagère** : ses livres restent dans le lieu.
- « Voir les livres » ouvre le catalogue filtré.

En ligne de commande : `biblio place add|shelf|rename|remove|list`. La forme `Lieu/Étagère` désigne une étagère, sans tenir compte des majuscules ni des accents.

### Ordre de rangement

« Ordre de rangement » sur la page Lieux liste les livres d'un lieu ou d'une étagère dans l'ordre des cotes, pour le système choisi. La page s'imprime : pratique pour ranger une étagère ou coller des étiquettes.

### Inventaire (récolement)

L'inventaire compare ce qui est réellement sur une étagère à ce que dit la base.

1. Poste de scan, mode **Inventaire** : choisissez le lieu (et l'étagère), puis « Commencer l'inventaire ».
2. Scannez tout ce qui s'y trouve. Les compteurs avancent en direct.
3. « Terminer et voir le rapport » affiche :
   - les livres **présents** ;
   - les livres **non scannés** : rangés ici d'après la base, mais pas vus (ailleurs, prêtés ou perdus) ;
   - les livres **trouvés ici, enregistrés ailleurs** ;
   - les livres **inconnus** de la collection.
4. « Clôturer » peut, si vous cochez les cases, enregistrer à cet emplacement les livres « d'ailleurs » et ajouter les inconnus.

L'inventaire compte les exemplaires : deux exemplaires du même titre sur l'étagère demandent deux scans, à plus de 4 secondes d'écart. Sinon, le second est signalé non scanné. Un livre sans ISBN n'a pas de code-barre : tapez sa référence (`L12`, indiquée sur sa fiche) dans le champ de scan.

En ligne de commande : `biblio inventory "Salon/É1"`, puis `:done` pour le rapport.

---

## 10. Prêts

Sur la fiche, « Prêter… » enregistre l'emprunteur. Le livre apparaît alors « prêté à Marie » dans le catalogue et dans « Où est-il ? », et la pastille de la page **Prêts** se met à jour.

La page **Prêts** liste les prêts en cours, avec un bouton « Rendu », et l'historique des prêts terminés.

```bash
biblio lend 9782070360024 Marie
```

```bash
biblio return 9782070360024
```

```bash
biblio loans
```

Seuls **vos** exemplaires se prêtent. Un livre emprunté à un ami n'a pas de suivi dédié : notez-le dans la note de sa fiche.

---

## 11. Propriétaires et dons

Chaque exemplaire a un **propriétaire**. Vos livres portent votre nom, réglable dans Réglages ou avec `biblio config proprietaire JD`. Changer ce nom renomme tous vos exemplaires. Il est refusé si ce nom possède déjà des livres dans la base.

Le propriétaire est porté par l'**exemplaire**, pas par la notice : si Victor et vous avez le même livre, vous partagez la même fiche, et chacun a son exemplaire.

### Les dons

Un don consiste à **changer le propriétaire**. Pour un prêt, utilisez « Prêter… » : les deux mécanismes sont indépendants.

- **Depuis le catalogue** : cochez des livres, remplissez « Donner à… » et cliquez sur « Donner… ».
- **Depuis la fiche** : « Donner… » sur l'exemplaire.
- **En ligne de commande** : `biblio give 9782070360024 Victor`. Vous pouvez donner un numéro d'exemplaire (voir `biblio show`) au lieu de l'ISBN.

Une confirmation est toujours demandée (`--yes` la saute en CLI). Conséquences d'un don :

- un prêt en cours de cet exemplaire est clos ;
- le livre quitte son emplacement ;
- il disparaît de « Mes livres » et de vos statistiques.

**Recevoir un livre** se fait de la même façon. Si le livre est déjà dans la base au nom d'un ami : « Changer de propriétaire… » puis votre nom. Il arrive non localisé, prêt à être rangé. Sinon, scannez-le simplement.

### Ce qui ne concerne que vos livres

| Fonction | Livres des amis |
|---|---|
| Catalogue | Masqués par défaut, visibles avec le filtre Propriétaire |
| Statistiques, « À traiter » | Non comptés |
| Rangement, prêt, inventaire, mode Déplacer | Non concernés |
| « Où est-il ? » | Listés (« chez Victor ») |
| Export Excel et CSV | Inclus, avec une colonne « Propriétaire » |

---

## 12. Partage, fusion et synchronisation

### Principe

Trois opérations, pour trois besoins :

| Commande | Pour quoi | Ce qui se passe |
|---|---|---|
| `biblio share` | Donner mon catalogue à un ami | Crée un fichier avec mes livres, sans mes données personnelles. |
| `biblio merge` | Recevoir le catalogue d'un ami | Ses livres restent les siens, et rien de ce qui est à moi ne change. |
| `biblio sync` | Réunir mes bases de deux ordinateurs | Ajouts, modifications et retraits se propagent. La modification la plus récente l'emporte. |

**Une personne, un livre ou un exemplaire a une identité** qui le suit d'une base à l'autre. Les noms peuvent changer, et les livres sans ISBN ne se confondent pas.

### Créer un fichier de partage

```bash
biblio share -o pour-victor.db --hide-places
```

- `--hide-places` : l'ami saura que vous avez le livre, pas où il est rangé.
- `--place Salon` (répétable) : seulement certains lieux.
- `--with-loans` : ajoute vos prêts, voir [Partager ses prêts](#partager-ses-prêts).
- `--force` : remplace sans le demander un ancien fichier de partage de même nom.

Seul un ancien fichier de partage peut être remplacé : la commande refuse d'écraser votre base ou tout autre fichier.

Dans l'appli : Réglages › « Partager avec un ami » (choix des lieux, cases « masquer les lieux » et « inclure mes prêts »).

| Dans le fichier | Jamais dans le fichier |
|---|---|
| Fiches, cotes, réponses des catalogues (l'ami n'a rien à retélécharger) | Vos notes, vos lectures, les détails de vos exemplaires (état, prix, provenance…) |
| Vos exemplaires, à votre nom | Votre clé Google et la clé du téléphone |
| Lieux, sous forme de texte, si non masqués | Vos réglages, l'historique, les couvertures |
| Vos prêts, seulement avec `--with-loans` | |

Les couvertures se téléchargent toutes seules chez l'ami, au premier affichage.

### Importer le catalogue d'un ami

Regardez d'abord ce qui changerait :

```bash
biblio merge pour-alex.db --as Victor --dry-run
```

Puis importez-le (un aperçu et une confirmation sont affichés) :

```bash
biblio merge pour-alex.db --as Victor
```

- `--as Victor` : le nom de cet ami chez vous. Il n'est nécessaire qu'une fois : ensuite, il est reconnu à son identité, même s'il change de nom. Sans cette option, c'est le nom enregistré dans le fichier qui compte. Si ce nom est le vôtre, par exemple « Moi » des deux côtés, la commande refuse et vous demande `--as`.
- `--replace` : retire aussi les livres et les prêts de cet ami qui ne sont plus dans le fichier (livres donnés, vendus…). Utilisez-le seulement si le fichier contient **tout** son catalogue, pas une partie.
- `--yes` : ne demande pas de confirmation.

Pour une mise à jour, l'ami vous envoie un nouveau fichier, et vous relancez la même commande.

### Les règles de l'import

- **Pas de doublon** : chaque exemplaire a une identité stable. Importer deux fois le même fichier ne change rien.
- **Le plus récent l'emporte** : entre deux versions d'un même exemplaire de l'ami, c'est la dernière modifiée qui est gardée.
- **Vos corrections sont protégées** : un champ que vous avez corrigé n'est jamais écrasé. Une correction de l'ami est reprise là où vous n'en avez pas fait, et suivie s'il la change ensuite. Il en va de même pour les cotes fixées à la main.
- **Vos exemplaires ne sont jamais supprimés** : `--replace` ne retire que ceux de l'ami.
- **Le fichier d'un ami ne modifie pas vos livres**, même un livre qu'il vous a donné depuis et que sa base lui attribue encore.
- **Seuls ses propres livres sont repris** : pas les vôtres, ni ceux de tiers présents dans sa base.
- **Ses notes, ses lectures et les détails de ses exemplaires ne sont jamais importés, et ses prêts seulement s'il a choisi de les partager**, même si vous importez sa base complète.
- **Les livres sans ISBN** sont reconnus par leur identité, sinon par le titre et l'auteur.
- **Les lieux d'un ami restent du texte** (« chez Victor — Salon › É2 ») : ils n'apparaissent pas dans vos lieux.
- **Tout ou rien** : une erreur en cours de route ne laisse rien à moitié fait.
- **Une copie de sécurité** de votre base est faite avant : `data/biblio-avant-fusion.db`, remplacée à chaque fois.

### Partager ses prêts

Par défaut, un fichier de partage ne contient aucun prêt, car les prêts portent le nom de tierces personnes. Pour les inclure :

```bash
biblio share -o pour-victor.db --with-loans
```

Prévenez vos emprunteurs si besoin : leur nom et ce qu'ils ont emprunté seront visibles par la personne qui reçoit le fichier. Seuls les prêts des exemplaires présents dans le fichier sont repris : un livre donné depuis, ou d'un lieu non sélectionné, n'y figure pas.

Chez celui qui reçoit le fichier :

- le **réseau des prêts** relie les amis entre eux et à leurs emprunteurs ;
- le catalogue et la fiche indiquent qu'un livre de l'ami est « prêté à… », ce qui dit s'il est disponible ;
- ces prêts restent à part : la page Prêts, la pastille et les chiffres des Statistiques ne comptent que les vôtres, et seul l'ami peut les clore, dans sa propre base.

**Une personne n'est reconnue que par son nom**, sans tenir compte des majuscules ni des accents. Si Victor a prêté un livre à « Alex » alors que votre nom de propriétaire est « JD », le réseau affichera deux personnes : mettez-vous d'accord sur l'orthographe.

**Pour retirer ses prêts** : envoyez un nouveau fichier sans l'option. Celui qui le reçoit les efface en fusionnant avec `--replace` ; sans cette option, ils restent chez lui.

### Lieux masqués après coup

Un fichier aux lieux masqués n'efface pas des lieux **déjà fusionnés** : les exemplaires n'ayant pas changé, la fusion répond « Already up to date ». Décidez donc avant la première fusion. Sinon, effacez-les à la main :

```bash
biblio sql "UPDATE exemplaires SET lieu_texte = NULL WHERE proprietaire_id = (SELECT id FROM personnes WHERE nom = 'Victor')"
```

### Synchroniser deux ordinateurs

Avec une base séparée sur chaque machine, copiez la base de l'autre machine (ou accédez-y par le réseau), puis lancez :

```bash
biblio sync /chemin/vers/l-autre/biblio.db --dry-run
```

```bash
biblio sync /chemin/vers/l-autre/biblio.db
```

**Lancez la commande des deux côtés** : chacune ne modifie que la base de la machine où elle s'exécute.

La première fois, la commande demande de confirmer que cette base est bien à vous, car c'est ce qui fait de ses livres les vôtres. Ensuite, elle est reconnue. Une base copiée d'une machine à l'autre l'est d'emblée.

Ce qui se propage :

| Donnée | Règle |
|---|---|
| Exemplaires : ajouts, déplacements, détails | La modification la plus récente de chaque exemplaire l'emporte. |
| Retraits d'exemplaires | Un livre retiré ne revient pas, sauf s'il a été modifié de l'autre côté après le retrait. |
| Notes, lectures, corrections de fiche, cotes manuelles | Champ par champ, la plus récente l'emporte : deux modifications de champs différents sont toutes deux gardées. |
| Lieux et étagères | Reconnus par leur identité : un renommage se propage, une suppression aussi (les livres deviennent non localisés). Le même nom créé des deux côtés donne un seul lieu. |
| Prêts, historique des déplacements | Repris, le retour d'un prêt compris. |
| Votre nom, le nom de vos amis, leurs catalogues | Repris. |

Ce qui reste propre à chaque machine : les réglages (langue, système affiché, clés), les inventaires, les couvertures.

Limites :

- la « dernière modification » repose sur l'horloge de chaque ordinateur ;
- un même livre physique scanné séparément sur les deux machines donne deux exemplaires, car rien ne dit que c'est le même objet.

Une erreur en cours de route ne laisse rien à moitié fait, et une copie est faite avant : `data/biblio-avant-synchro.db`.

Si le même dossier est synchronisé par OneDrive, il n'y a qu'une seule base : pas besoin de `sync`, mais n'ouvrez pas l'appli sur deux ordinateurs en même temps.

---

## 13. Scanner la bibliothèque d'un ami

Le plus simple est de **créer une base séparée pour l'ami, d'y scanner ses livres, puis de l'importer dans la vôtre** avec `biblio merge`.

- Ses lieux restent les siens : ils n'encombrent ni vos lieux ni le poste de scan.
- Ses livres ne se mélangent pas aux vôtres pendant le scan : pas de faux doublons, pas de faux rangements.
- Vous pouvez lui donner cette base, qui devient sa propre bibliothèque.

Une variable d'environnement, `BIBLIO_DB`, indique au logiciel quelle base utiliser. Toutes les commandes s'exécutent **depuis le dossier du projet**.

### Étape 1 : préparer sa base

Arrêtez votre serveur habituel (Ctrl+C), puis :

```bash
BIBLIO_DB=data/victor.db ./biblio.sh config proprietaire Victor
```

La base est créée à cette occasion.

Sous Windows, définissez d'abord la variable, valable pour ce terminal. Toutes les commandes suivantes y utiliseront alors la base de Victor :

```powershell
$env:BIBLIO_DB = "data\victor.db"
.\biblio.cmd config proprietaire Victor
```

### Étape 2 : lancer l'appli sur sa base

```bash
BIBLIO_DB=data/victor.db ./biblio.sh serve --phone
```

Sans téléphone, retirez `--phone`. **Avant de scanner, vérifiez la base utilisée** : Réglages › Données affiche son chemin, qui doit se terminer par `victor.db`.

### Étape 3 : scanner chez lui

Créez ses lieux et ses étagères, puis scannez comme d'habitude. Trois façons de faire :

| Matériel | Ce qu'il faut | Remarques |
|---|---|---|
| **Ordinateur + douchette** | L'ordinateur sur place | Internet n'est pas nécessaire pour scanner : les descriptions attendront. |
| **Ordinateur + téléphone** | Les deux sur le même Wi-Fi | Sur le téléphone, rescannez le QR code « Scanner » : la clé d'accès est propre à chaque base. Le certificat reste valable. Un Wi-Fi invité peut empêcher les appareils de se voir. |
| **Douchette à mémoire seule** | Rien d'autre sur place | Le plus léger, mais on ne voit rien pendant le scan. Notez quels codes vont dans quel lieu : faites un fichier par lieu. |

Avec une douchette à mémoire, importez ensuite chaque fichier :

```bash
BIBLIO_DB=data/victor.db ./biblio.sh import salon.txt --place "Salon"
```

Si certains livres restent « en recherche » ou « en erreur » faute de réseau, finissez une fois connecté :

```bash
BIBLIO_DB=data/victor.db ./biblio.sh resolve --retry
```

Ses livres sans code-barre se traitent comme d'habitude, avec le lien « Pas de code-barre ? ». Un même livre sur deux lieux déclenche l'alerte de doublon : c'est normal.

### Étape 4 : l'importer dans votre base

Arrêtez le serveur (Ctrl+C), puis, **sans** `BIBLIO_DB` :

```bash
./biblio.sh merge data/victor.db --dry-run
```

```bash
./biblio.sh merge data/victor.db
```

Relancez votre appli : le filtre **Propriétaire** du catalogue propose maintenant Victor. Ses livres apparaissent avec « chez Victor — Salon › É2 ».

### S'il préfère garder ses lieux pour lui

Ne fusionnez pas `victor.db` directement : passez par un fichier de partage. Faites ce choix **avant** la première fusion (voir [Lieux masqués après coup](#lieux-masqués-après-coup)).

```bash
BIBLIO_DB=data/victor.db ./biblio.sh share -o victor-partage.db --hide-places
```

```bash
./biblio.sh merge victor-partage.db
```

### Plus tard : mettre à jour

Continuez à scanner dans `data/victor.db`, puis relancez la fusion. Les nouveaux livres et les déplacements sont repris. Si vous y avez retiré des livres qu'il n'a plus, ajoutez `--replace` pour qu'ils disparaissent aussi de chez vous :

```bash
./biblio.sh merge data/victor.db --replace
```

### Lui donner sa bibliothèque

Si Victor installe aussi le logiciel, `victor.db` peut devenir sa base, déjà à son nom. Serveur arrêté, copiez `data/victor.db` dans son projet sous le nom `data/biblio.db`. Si un fichier `data/victor.db-wal` non vide subsiste, faites plutôt une copie propre :

```bash
sqlite3 data/victor.db ".backup victor-copie.db"
```

Il pourra ensuite vous envoyer ses mises à jour lui-même avec `biblio share`. Comme les identifiants d'exemplaires sont conservés, vos fusions suivantes ne créeront pas de doublons.

### En cas d'erreur

**J'ai oublié `BIBLIO_DB` et scanné ses livres dans ma base.** Dans le catalogue, filtrez avec le raccourci « aujourd'hui », cochez les livres concernés et faites « Donner… » à Victor. Ils sont alors à son nom, mais sans leurs lieux.

**J'ai mal écrit le chemin de `BIBLIO_DB`.** Une nouvelle base vide est créée sans avertissement. Vérifiez le chemin affiché dans Réglages.

**Le téléphone affiche « Accès refusé ».** Il garde la clé de l'autre base : rescannez le QR code « Scanner ». C'est aussi le cas d'une icône d'écran d'accueil créée sur l'autre base.

---

## 14. D'où viennent les descriptions

Une tâche de fond décrit les livres, sans quota journalier, au rythme poli d'environ une requête par seconde et par catalogue. Comptez 4 à 7 secondes par livre, soit 2 à 4 heures pour 2 000 livres.

| Source | Rôle |
|---|---|
| **BnF** (catalogue général, UNIMARC) | Source principale pour les livres français. Fournit le Dewey des documentaires et le « cadre de classement » pour la fiction. |
| **Open Library** | Couvertures, livres anglophones, Dewey et LCC complémentaires. |
| **Library of Congress** | LCC et Dewey des livres non français. |
| **Google Books** | Facultatif, seulement avec une clé API gratuite (Réglages, voir [Obtenir une clé Google Books](#obtenir-une-clé-google-books)). Sans clé, Google Books n'est pas interrogé. Avec une clé, il n'est interrogé que pour les livres sans titre ou sans résumé. |

Quand plusieurs catalogues répondent, l'ordre de confiance pour les champs descriptifs est : BnF, Open Library, Google Books, Library of Congress.

**Les réponses brutes sont conservées** (table `raw_responses`). Un ISBN n'est donc pas réinterrogé inutilement, et tout peut être recalculé sans réseau.

**Les couvertures** sont téléchargées une fois dans `data/covers/`. Si un catalogue n'a pas d'image, le suivant est essayé : Open Library, puis Google Books. Un petit fichier `.absente` retient qu'aucun n'en a. `biblio covers` télécharge celles qui manquent, `--missing` réessaie les livres notés sans image, et `--force` réessaie tout.

**Commandes utiles**

- `biblio resolve` : décrit les livres en attente, même sans serveur lancé.
- `biblio resolve --retry` : réessaie les livres introuvables, les erreurs réseau et les catalogues qui n'ont pas répondu. Les réponses valides sont gardées.
- Page **À traiter** › « Relancer la recherche des introuvables et erreurs » : la même chose dans l'appli.

---

## 15. Les systèmes de classement

Toutes les cotes sont calculées et stockées pour chaque livre : changer de système (menu « Classement ») est instantané.

| Système | Code CLI | Usage | Origine de la cote |
|---|---|---|---|
| **Dewey** (défaut) | `dewey` | Bibliothèques publiques | BnF ou Open Library pour les documentaires. Pour les romans, BD et livres jeunesse, que la BnF n'indexe pas en Dewey : déduite de la langue d'origine et du genre (roman français = 843, traduit de l'anglais = 823, BD = 741.5, jeunesse = « J 843 »). |
| **Cadre BnF** | `cadre_bnf` | Bibliographie nationale française | Fourni par la BnF ; proche des rayons d'une librairie. |
| **CDU** | `cdu` | Belgique, Suisse, CDI | Déduite du Dewey (821.133.1-31 = roman français). |
| **LCC** | `lcc` | Bibliothèques universitaires anglo-saxonnes | Cote complète pour les livres anglophones ; sinon sous-classe déduite. |
| **Clil** | `clil` | Libraires français | **Déduit** : le code officiel est diffusé par des services payants (Electre, Dilicom). |
| **Thema** | `thema` | Commerce international du livre | **Déduit**, grandes catégories. |
| **Rayons perso** | `rayon` | Votre propre système | Vos règles, dans `rules/rayons.toml`. |

Les intitulés officiels de la Dewey appartiennent à OCLC et ne sont pas fournis : les livres sont regroupés par tranche de centaines (`800-899`). Pour afficher vos propres intitulés, ajoutez une table `[libelles]` dans `rules/dewey.toml`, puis lancez `biblio reclassify`.

La cote suit l'usage des bibliothèques : un indice et les 3 premières lettres de l'auteur (`843 CAM`). Sans auteur, ce sont celles du premier mot significatif du titre.

**Limites connues**

- Pour les romans français, la BnF ne donne pas le sous-genre (policier, SF…). Il est deviné d'après la collection (Série noire, Folio SF…) et les sujets : c'est imparfait.
- Les fiches BnF anciennes portent parfois un indice Dewey ancien, repris tel quel.

Dans les deux cas, corrigez la cote à la main ou enrichissez les règles.

### Imposer une cote

Sur la fiche, ou :

```bash
biblio classify 9782070360024 dewey 843.914
```

Sans valeur, la commande revient au calcul automatique.

### Adapter les règles

Tout est dans `rules/` :

| Fichier | Contenu |
|---|---|
| `dewey.toml`, `cdu.toml`, `lcc.toml`, `cadre_bnf.toml` | Tables de ces systèmes |
| `clil.toml`, `thema.toml`, `rayons.toml` | Règles, lues dans l'ordre |
| `mots.toml` | Listes de mots-clés partagées, appelées avec `@nom` |

Pour les règles, **la première qui correspond gagne**. Exemple dans `rules/rayons.toml` :

```toml
[[regle]]
abbr = "MAN"
libelle = "Mangas"
bd = true
mots = ["@manga"]
```

Toutes les conditions d'une règle doivent être vraies ; dans une liste, une seule valeur suffit.

| Condition | Sens |
|---|---|
| `bd = true` | Bande dessinée |
| `fiction = true` | Roman, nouvelles, récit |
| `public = ["jeunesse", "ado", "adulte"]` | Public |
| `forme = ["poesie", "theatre", …]` | Forme |
| `dewey = ["84", "741.5"]` | Début de l'indice Dewey |
| `cadre = ["803"]` | Début du code du cadre BnF |
| `langue = ["fre"]`, `langue_non = ["fre"]` | Langue d'origine |
| `mots = ["policier", "@policier"]` | Texte, ou liste de `mots.toml` |

Après une modification :

- `biblio reclassify` recalcule toutes les cotes ;
- `biblio reclassify --reread` relit aussi les réponses stockées et reconstruit les fiches (bouton Réglages › « Recalculer toutes les cotes »).

Aucune requête réseau n'est faite, et les champs et cotes fixés à la main sont conservés.

---

## 16. À traiter, statistiques, exports

### À traiter

La page **À traiter** (`biblio todo`) regroupe ce qui demande votre attention, pour vos livres :

| Section | Que faire |
|---|---|
| En cours de recherche | Attendre : quelques secondes par livre. |
| Erreurs réseau | Relancer quand la connexion est revenue. |
| Introuvables | Compléter la fiche à la main. |
| Réponses incomplètes | La fiche est décrite, mais un catalogue n'a pas répondu : relancer. |
| Sans cote dans le système affiché | Indiquer la forme ou imposer une cote. |
| Non localisés | Ranger depuis le catalogue, la fiche ou le poste de scan. |

### Statistiques

La page **Statistiques** (résumé : `biblio stats`) ne compte que vos livres :

- **Chiffres clés** : livres, titres différents, auteurs, pages, pages par livre en moyenne, titres en plusieurs exemplaires.
- **Activité** : livres ajoutés ces 12 derniers mois.
- **Lecture** : livres lus, en cours et à lire, pages lues, note moyenne, livres lus par an, notes données.
- **Prêts** :
  - réseau des prêts : un graphe où chaque personne est un nœud et chaque lien réunit deux personnes. Le rayon d'un nœud suit le logarithme du nombre de livres de sa bibliothèque, l'épaisseur d'un lien celui du nombre de prêts. Un cercle vide signale une personne dont la bibliothèque est inconnue, un lien en pointillés des prêts tous rendus. Survoler une personne met ses liens en avant, et cliquer dessus ouvre ses livres. Les liens partent de vous, et relient aussi vos amis s'ils ont [partagé leurs prêts](#partager-ses-prêts) ;
  - prêts en cours, avec une barre par livre indiquant depuis combien de jours il est sorti, les plus anciens d'abord ;
  - prêts en cours par emprunteur, et prêts lancés chaque mois sur 12 mois ;
  - emprunteurs les plus fréquents et livres les plus prêtés ;
  - prêts en cours, total des prêts, nombre d'emprunteurs et nombre moyen de jours avant le retour. Un don clôt le prêt en cours : il compte alors comme un retour dans cette moyenne.
- **La collection** : répartition par classe, lieu, auteur, éditeur, décennie d'édition, langue d'origine, genre, public, longueur et collection (sans son numéro : « Folio ; 4082 » compte pour Folio), ainsi que les records (livres le plus ancien, le plus récent, le plus long, le plus court).
- **Rangement et fiches** :
  - étagères les plus remplies ;
  - titres en plusieurs exemplaires, utile pour repérer ce qu'on peut donner ;
  - complétude des fiches, en pourcentage ;
  - état des fiches ;
  - état des exemplaires et valeur de la collection, d'après ce que vous avez renseigné.
- **Chez les amis**, si vous avez importé un catalogue : pour chaque ami, ses exemplaires, ses titres, ceux que vous avez aussi et ceux que vous n'avez pas.

Plusieurs cartes se basculent entre liste, camembert et histogramme, et le choix est mémorisé sur l'appareil. Les noms de livres, d'auteurs, d'éditeurs, de collections et d'étagères sont des liens vers la fiche ou le catalogue. Au survol ou au toucher d'une barre, une infobulle donne le détail.

### Exports

- **Excel** : une feuille générale, plus une feuille par lieu. Bouton dans le catalogue et les Réglages, ou `biblio export`.
- **CSV** : une seule table, séparateur `;`, lisible par Excel avec les accents. `biblio export --format csv`.

Une ligne par exemplaire, tous propriétaires confondus, avec toutes les cotes en colonnes. En CLI, le fichier va dans `data/exports/`, sauf avec `--output`.

---

## 17. Réglages, thème et langue

**Thème** : trois icônes en haut à droite. Automatique (suit le réglage clair ou sombre de l'appareil), clair, sombre. Le choix est propre à chaque appareil et à chaque navigateur.

**Langue** : **FR · EN** en haut à droite, ou Réglages. Elle s'applique à toute l'appli et à tous les appareils. La CLI est toujours en anglais.

**Page Réglages** :

- langue de l'interface ;
- système de classement affiché par défaut ;
- votre nom de propriétaire ;
- clé API Google Books (facultative, gratuite, 1 000 requêtes par jour, API « Books » de la console Google Cloud) ;
- chemin de la base et nombre de réponses conservées ;
- exports ;
- recalcul des cotes ;
- partage avec un ami.

**En ligne de commande** :

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

`biblio config` sans argument affiche tous les réglages et le chemin de la base. `biblio system rayon` choisit le système par défaut.

### Obtenir une clé Google Books

La clé est facultative. Elle ajoute résumés et couvertures quand la BnF et Open Library n'en ont pas. Il faut un compte Google.

**1. Créer la clé dans la console Google Cloud**

1. Ouvrez [console.cloud.google.com](https://console.cloud.google.com) et créez un projet (par exemple « bibliotheque »), ou choisissez-en un.
2. Dans [la bibliothèque d'API](https://console.cloud.google.com/apis/library/books.googleapis.com), ouvrez **Books API** et cliquez sur **Activer**.
3. Dans [Identifiants](https://console.cloud.google.com/apis/credentials), cliquez sur **Créer des identifiants** › **Clé API**.
4. Limitez la clé : dans **Restrictions d'API**, choisissez **Restreindre la clé**, puis **Books API**. Inutile d'ajouter une restriction d'application : le logiciel n'est ni un site web ni une appli mobile, et l'adresse IP d'un domicile peut changer.
5. Copiez la clé entière. Elle commence en général par `AIza`.

Si la console demande d'activer la facturation, vérifiez ce qui vous sera facturé avant d'accepter. Le quota journalier (annoncé à 1 000 requêtes) se lit dans la rubrique des quotas de la Books API.

**2. Vérifier la clé**

Remplacez `VOTRE_CLE` :

```bash
curl "https://www.googleapis.com/books/v1/volumes?q=isbn:9782070360024&key=VOTRE_CLE"
```

Une réponse contenant `totalItems` signifie que la clé fonctionne, même si ce nombre vaut 0. Une réponse contenant `error` donne la raison du refus.

**3. L'enregistrer dans le logiciel**

Collez-la dans la page **Réglages**, champ « Clé API Google Books ». C'est la méthode à préférer, car la clé ne reste pas dans l'historique du terminal. En ligne de commande :

```bash
biblio config google_api_key VOTRE_CLE
```

La clé est rangée dans la base et n'est jamais incluse dans un fichier de partage. La variable d'environnement `BIBLIO_GOOGLE_KEY`, si elle existe, passe avant ce réglage. Traitez la clé comme un mot de passe. Si elle a fuité, supprimez-la dans la console et créez-en une autre.

**4. Compléter les livres déjà décrits**

La clé s'applique d'elle-même aux prochains livres scannés, mais pas aux livres déjà décrits : `biblio resolve --retry` ne reprend que les introuvables et les erreurs. Pour interroger Google sur les livres déjà trouvés qui n'ont pas de résumé, remettez-les en attente :

```bash
biblio sql "UPDATE notices SET statut = 'en_attente' WHERE statut = 'trouve' AND isbn13 IS NOT NULL AND (resume IS NULL OR resume = '')"
```

```bash
biblio resolve
```

Cela coûte une requête Google par livre. Les réponses des autres catalogues sont conservées : ils ne sont réinterrogés que s'ils avaient échoué ou n'avaient pas encore été consultés. Les champs que vous avez corrigés restent protégés. Google n'est interrogé qu'une fois par livre : s'il ne connaît pas un livre, la commande ne le redemandera pas.

Si la clé est refusée ou le quota dépassé, les livres restent décrits comme avant et l'erreur est notée dans leur carte Sources. Corrigez la cause, ou attendez le lendemain pour le quota, puis lancez `biblio resolve --retry`.

---

## 18. Référence de la ligne de commande

`biblio --help` liste les commandes, et `biblio <commande> --help` détaille leurs options. Là où un livre est attendu, `978…` désigne son ISBN, ou sa référence s'il n'en a pas (`L12`).

### Lieux

| Commande | Rôle |
|---|---|
| `place list` | Lieux, étagères et nombre de livres |
| `place add NOM [-d DESCRIPTION]` | Créer un lieu |
| `place shelf LIEU NOM [NOM…]` | Ajouter des étagères |
| `place rename ANCIEN NOUVEAU` | Renommer (`Lieu/Étagère` pour une étagère) |
| `place remove SPEC [--yes]` | Supprimer ; les livres deviennent non localisés (ou restent dans le lieu pour une étagère) |

### Scan et description

| Commande | Rôle |
|---|---|
| `scan [-p LIEU] [-m add\|move\|where]` | Scanner dans le terminal |
| `import FICHIER [-p LIEU] [--no-resolve]` | Importer une liste de codes |
| `resolve [--retry]` | Décrire les livres en attente ; `--retry` réessaie les échecs |
| `covers [--missing] [--force]` | Télécharger les couvertures manquantes |
| `manual [--title …] [--authors …] [-p LIEU] [--isbn …] [--owner NOM] [--no-search] …` | Livre sans code-barre (voir `--help` pour tous les champs) |

### Consultation

| Commande | Rôle |
|---|---|
| `show 978…` | Tout sur un livre : fiche, lecture, cotes, exemplaires |
| `where CODE` | Où est ce livre ? (ISBN ou mots, chez tout le monde) |
| `search [MOTS] [-p LIEU] [-s SYSTÈME] [--sort …] [--since …] [--until …] [-o NOM\|all] [--reading …] [-n N]` | Rechercher ; vos livres par défaut |
| `list [-p LIEU] [-s SYSTÈME] [--sort …] [-n N]` | Lister dans l'ordre de rangement |
| `todo` | Ce qui reste à traiter |
| `stats` | Quelques chiffres |
| `owners` | Propriétaires présents |

Tris : `shelf`, `title`, `author`, `year`, `added`.

### Corrections et rangement

| Commande | Rôle |
|---|---|
| `edit 978… [--title …] [--form …] [--release CHAMP] …` | Corriger une fiche ; `--release` rend un champ aux catalogues (nom français : `titre`, `forme`…) |
| `note 978… [--edit] [--set TEXTE]` | Afficher ou modifier la note |
| `read 978… [--status …] [--rating N] [--started DATE] [--finished DATE]` | Afficher ou noter sa lecture |
| `copy N° [--condition …] [--price …] [--bought DATE] [--from …] [--inscription …] [--value …] [--note …]` | Afficher ou renseigner les détails d'un exemplaire |
| `classify 978… SYSTÈME [VALEUR] [--label …]` | Imposer une cote ; sans valeur, retour au calcul automatique |
| `move 978… LIEU[/ÉTAGÈRE]` | Déplacer (le lieu est créé si besoin) |
| `remove N° [--yes]` | Retirer un exemplaire |
| `give 978…\|N° NOM [--yes]` | Donner |
| `inventory LIEU[/ÉTAGÈRE]` | Inventaire |

### Prêts

| Commande | Rôle |
|---|---|
| `lend 978… NOM` | Prêter |
| `return 978…` | Rendu |
| `loans` | Prêts en cours |

### Partage, import et synchronisation

| Commande | Rôle |
|---|---|
| `share -o FICHIER [-p LIEU…] [--hide-places] [--with-loans] [--force]` | Créer un fichier de partage |
| `merge FICHIER [--as NOM] [--replace] [--dry-run] [--yes]` | Importer le catalogue d'un ami |
| `sync FICHIER [--dry-run] [--yes]` | Réunir mes bases de deux ordinateurs |

### Réglages et données

| Commande | Rôle |
|---|---|
| `system [SYSTÈME]` | Voir ou choisir le système par défaut |
| `config [CLÉ] [VALEUR] [--clear]` | `google_api_key`, `systeme`, `langue`, `proprietaire` |
| `reclassify [--reread]` | Recalculer les cotes, sans réseau |
| `export [-f xlsx\|csv] [-o FICHIER] [-s SYSTÈME]` | Exporter |
| `backup [--dir DOSSIER] [--keep N]` | Copier la base, même serveur en marche ; 14 copies gardées par défaut |
| `sql ["REQUÊTE"]` | Requête SQL directe, ou shell SQLite sans argument |
| `serve [--port N] [--host H] [--phone] [--no-open]` | Lancer l'appli web |
| `phone [--new-key]` | QR codes du mode téléphone ; changer la clé |

`biblio sql` peut tout modifier : faites une copie de la base avant une requête d'écriture.

---

## 19. Données et sauvegardes

### Les fichiers

| Emplacement | Contenu |
|---|---|
| `data/biblio.db` | La base SQLite (avec `-wal` et `-shm` pendant l'utilisation) |
| `data/covers/` | Les couvertures, communes à toutes les bases du projet |
| `data/exports/` | Les exports de la CLI |
| `data/biblio-avant-fusion.db`, `data/biblio-avant-synchro.db` | Copies faites avant le dernier import ou la dernière synchronisation |
| `data/sauvegardes/` | Les copies de sécurité de la base |
| `rules/` | Les règles de classement |

### Les tables

| Table | Contenu |
|---|---|
| `personnes` | Propriétaires, prêteurs, emprunteurs : `uid` stable, `nom`, `cle` (nom sans casse ni accents) |
| `notices` | Le livre : `uid` stable, `isbn13` s'il en a un, description, `corrections` (champs corrigés et leur date), note et lecture |
| `exemplaires` | L'objet : `uid` stable, `notice_id`, `proprietaire_id`, lieu, `lieu_texte` chez un ami, détails (état, prix…), date `maj_le` |
| `classifications` | Une cote par système et par notice |
| `raw_responses` | Les réponses brutes des catalogues |
| `lieux`, `etageres` | Vos lieux, avec leur identité stable |
| `mouvements` | L'historique des déplacements |
| `inventaires`, `inventaire_scans` | Les inventaires |
| `prets` | Les prêts : `preteur_id`, `emprunteur_id` |
| `suppressions` | Ce qui a été retiré, pour que la synchronisation ne le fasse pas revenir |
| `meta` | Les réglages |
| `notices_fts` | L'index de recherche |
| `exemplaires_v`, `prets_v` | Vues pratiques pour `biblio sql` : avec les noms des personnes |

### Sauvegarder

`biblio serve` copie la base dans `data/sauvegardes/` à son lancement, si la dernière copie a plus d'un jour. Pour en faire une à tout moment, même serveur en marche :

```bash
biblio backup
```

Chaque copie tient en un seul fichier, daté, par exemple `biblio-2026-11-01-143000.db`. Les 14 dernières de chaque base sont gardées (`--keep` pour changer ce nombre, `--dir` pour un autre dossier, par exemple un disque externe). Les couvertures n'y sont pas : elles se téléchargent de nouveau. Pour les garder aussi, copiez `data/covers/`.

### Restaurer

Arrêtez le serveur, supprimez `data/biblio.db-wal` et `data/biblio.db-shm` s'ils existent, puis remplacez `data/biblio.db` par la copie choisie.

### Dans un dossier synchronisé

OneDrive ou un service équivalent n'est pas une sauvegarde de la base : pendant l'utilisation, elle vit dans trois fichiers (`.db`, `-wal`, `-shm`) que la synchronisation copie séparément, et une base SQLite supporte mal d'être modifiée à deux endroits. N'ouvrez pas l'appli sur deux ordinateurs en même temps, et attendez la fin de la synchronisation avant de changer de machine. Les copies de `data/sauvegardes/`, elles, sont cohérentes : la synchronisation les met à l'abri.

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `BIBLIO_DB` | Chemin de la base à utiliser |
| `BIBLIO_RULES` | Dossier des règles de classement |
| `BIBLIO_CERTS` | Dossier des certificats |
| `BIBLIO_COVERS` | Dossier des couvertures |
| `BIBLIO_GOOGLE_KEY` | Clé Google Books, prioritaire sur le réglage |
| `UV_PROJECT_ENVIRONMENT` | Emplacement de l'environnement Python |

Pour essayer quelque chose sans risque, travaillez sur une copie :

```bash
BIBLIO_DB=/tmp/essai.db ./biblio.sh serve
```

Sous Windows, dans PowerShell : `$env:BIBLIO_DB = "C:\chemin\essai.db"`, puis la commande. Dans l'invite de commandes : `set BIBLIO_DB=C:\chemin\essai.db`.

---

## 20. Dépannage

| Symptôme | Cause et solution |
|---|---|
| `port 8000 is already in use` | La bibliothèque tourne déjà dans un autre terminal : arrêtez-la (Ctrl+C), ou choisissez `--port`. |
| `uv` introuvable après l'installation | Rouvrez le terminal. |
| Bandeau rouge « Le programme a été mis à jour » | Redémarrez le serveur. |
| Mise en page étrange après une mise à jour | Forcez le rechargement (Cmd+Maj+R, ou Ctrl+Maj+R). |
| Le téléphone n'atteint pas la page | Même Wi-Fi ? Un Wi-Fi invité peut isoler les appareils. Le serveur tourne-t-il avec `--phone` ? Vérifiez le pare-feu (voir [section 5](#5-scanner-avec-le-téléphone)). |
| « Accès refusé » sur le téléphone | La clé a changé, ou vous avez changé de base : rescannez le QR code « Scanner ». Pour une icône d'écran d'accueil : supprimez-la, puis recréez-la depuis le QR code dans Safari. |
| La caméra ne s'ouvre pas | Le certificat n'est probablement pas installé : QR code 1. Sur iPhone, seul Safari l'installe, et la confiance doit être activée dans Réglages › Général › Informations › Réglages des certificats. |
| Un livre reste « en recherche » | Le serveur doit tourner pour que les recherches avancent, sinon lancez `biblio resolve`. |
| Livre « introuvable » | Aucun catalogue ne le connaît : complétez la fiche, ou essayez `biblio resolve --retry` plus tard. |
| Livre « à classer » | Indiquez sa forme (roman, essai…) sur la fiche, ou imposez une cote. |
| Sous-genre ou cote approximatifs | Corrigez sur la fiche, ou enrichissez `rules/mots.toml`. |
| La clé Google ne change rien | Les livres déjà décrits ne sont pas réinterrogés d'eux-mêmes : voir [Obtenir une clé Google Books](#obtenir-une-clé-google-books), étape 4. Pour voir les erreurs : `biblio sql "SELECT payload, count(*) FROM raw_responses WHERE source = 'google' AND statut = 'erreur' GROUP BY payload"`. `HTTP 400` indique une clé invalide. |
| Des chiffres bizarres lus par la douchette | Normalement corrigé. Sinon, réglez sa disposition clavier et son suffixe « Entrée ». |
| `sqlite3 not found` | Installez-le, ou passez la requête en argument : `biblio sql "select …"`. |
| `was made by another version of this program` | La base vient d'une autre version du logiciel : elle n'a pas été modifiée, mais ne peut pas être ouverte. |
| `base d'une autre version du programme` à l'import | Les deux logiciels n'ont pas la même version : mettez-les à jour. |
| `this file is not a library database` | Le fichier n'est pas une base de ce logiciel, ou il est endommagé. |
| `this file carries your own name` | Le fichier d'un ami porte votre nom, par exemple « Moi » des deux côtés : relancez avec `--as NOM`. |
| `this file comes from your own database` | C'est une de vos bases : utilisez `biblio sync`. |
| `this is a share file` | Le fichier d'un ami : utilisez `biblio merge`. |
| Un import ou une synchronisation ne convient pas | Restaurez `data/biblio-avant-fusion.db` ou `data/biblio-avant-synchro.db` (voir [Restaurer](#restaurer)). |
| « Requête refusée : elle ne vient pas de la bibliothèque » | L'appli a été appelée depuis une autre page ou sous une autre adresse : ouvrez-la avec http://localhost:8000. |
| Les ordres de rangement ont changé après une mise à jour | Normal : `843` passe désormais avant `843.914`, et les cotes LCC se comparent comme des nombres. Tout est recalculé une fois, sans réseau, au lancement. |
| Les livres de Victor ne s'affichent pas | Par défaut, le catalogue montre vos livres : choisissez Victor ou « Tout le monde » dans la section Propriétaire. |
| Mes livres ont disparu du catalogue | Regardez d'abord le filtre Propriétaire, puis le chemin de la base dans Réglages : `BIBLIO_DB` pointe peut-être ailleurs. |

---

## 21. Pour le développement

```bash
uv run pytest
```

Les tests n'utilisent pas le réseau : les lecteurs de catalogues sont testés sur de vraies réponses enregistrées dans `tests/fixtures/`. Ils ne touchent jamais la vraie base, les couvertures ni les certificats.

| Élément | Emplacement |
|---|---|
| Logique métier commune | `biblio/services.py` |
| Base et schéma | `biblio/db.py` |
| Partage, import d'un ami, synchronisation | `biblio/partage.py` |
| Copies de sécurité | `biblio/sauvegarde.py` |
| Catalogues | `biblio/sources/`, assemblés par `biblio/resolver.py` |
| Calcul des cotes | `biblio/classify/`, avec `rules/` |
| Appli web | `biblio/web/` |
| CLI | `biblio/cli.py` |
| Traductions | `biblio/traductions.py` |

Toute phrase affichée par l'interface doit avoir sa traduction anglaise dans `biblio/traductions.py` : un test le vérifie. La clé est le texte français exact.
