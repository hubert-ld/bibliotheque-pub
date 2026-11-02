"""Command-line interface: `biblio --help`. Always in English."""

import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape as esc
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from . import covers as covers_store, db, i18n, resolver, sauvegarde, services
from .classify import SYSTEMES, reclasser_tout, systeme_courant
from .i18n import tr
from .services import Erreur
from .sources import make_client
from .worker import Worker, prochaine

i18n.utiliser("en")          # messages from the shared code (errors, statuses) in English

app = typer.Typer(help="Personal library: barcode scanning, places, classification systems.",
                  no_args_is_help=True, rich_markup_mode="rich")
place_app = typer.Typer(help="Manage places (bookcases, rooms) and their shelves.", no_args_is_help=True)
app.add_typer(place_app, name="place")
console = Console()

COLOURS = {"ajoute": "green", "doublon": "yellow", "rebond": "dim", "deplace": "cyan",
           "deja_la": "dim", "inconnu": "red", "present": "green", "ailleurs": "yellow",
           "trouve": "green"}
MODES = {"add": "ajout", "move": "deplacement", "where": "ou"}
SORTS = {"shelf": "cote", "title": "titre", "author": "auteur", "year": "annee", "added": "ajout"}
READING = {"to-read": "a_lire", "reading": "en_cours", "read": "lu", "abandoned": "abandonne"}
CONDITIONS = {"new": "neuf", "very-good": "tres_bon", "good": "bon", "fair": "moyen", "damaged": "abime"}
SYSTEM_HELP = ", ".join(SYSTEMES)


def _conn():
    try:
        return db.connect()
    except db.AutreVersion as e:
        _fail(f"{e} was made by another version of this program: it cannot be opened")


def _fail(msg: str):
    console.print(f"[red]✗ {esc(msg)}[/red]")
    raise typer.Exit(1)


def _check_system(name: str | None) -> None:
    if name and name not in SYSTEMES:
        _fail(f"unknown system: {name} (choices: {SYSTEM_HELP})")


def _authors(n) -> str:
    a = n.get("auteurs") or []
    return ", ".join(a[:2]) + (" …" if len(a) > 2 else "")


def _book_line(n: dict | None) -> str:
    if not n:
        return ""
    if n.get("statut") == "en_attente":
        return "[dim](looking it up…)[/dim]"
    title = esc(n["titre"]) if n.get("titre") else "[red]unknown title[/red]"
    call_number = f"[bold magenta]{esc(n['cote'])}[/bold magenta]  " if n.get("cote") else ""
    return f"{call_number}{title} — {esc(_authors(n))}"


def _place(conn, spec: str | None, create: bool = False):
    if not spec:
        return None, None
    try:
        return services.emplacement(conn, spec, creer=create)
    except Erreur as e:
        _fail(str(e))


# --- Places -----------------------------------------------------------------------

@place_app.command("list")
def place_list():
    """List places, their shelves and how many books each holds."""
    conn = _conn()
    places = services.lieux(conn)
    if not places:
        console.print("No places yet. Create one: [bold]biblio place add \"Living room\"[/bold]")
        return
    table = Table("Place", "Shelves", "Books")
    for p in places:
        shelves = ", ".join(f"{esc(e['nom'])} ({e['nb']})" for e in p["etageres"]) or "—"
        table.add_row(esc(p["nom"]), shelves, str(p["nb"]))
    console.print(table)


@place_app.command("add")
def place_add(name: str, description: str = typer.Option(None, "--description", "-d")):
    """Create a place (e.g. Living room, Bedroom, Study)."""
    try:
        services.creer_lieu(_conn(), name, description)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓[/green] place “{esc(name)}” created")


@place_app.command("shelf")
def place_shelf(place: str, names: list[str]):
    """Add one or more shelves to a place: biblio place shelf "Living room" S1 S2."""
    conn = _conn()
    place_id, _ = _place(conn, place)
    try:
        for name in names:
            services.creer_etagere(conn, place_id, name)
            console.print(f"[green]✓[/green] shelf “{esc(name)}” added to {esc(place)}")
    except Erreur as e:
        _fail(str(e))


@place_app.command("rename")
def place_rename(old: str, new: str):
    """Rename a place, or a shelf using the Place/Shelf form."""
    conn = _conn()
    place_id, shelf_id = _place(conn, old)
    try:
        if shelf_id:
            services.renommer_etagere(conn, shelf_id, new)
        else:
            services.renommer_lieu(conn, place_id, new)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓[/green] “{esc(old)}” → “{esc(new)}”")


@place_app.command("remove")
def place_remove(spec: str, yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation")):
    """Remove a place or a shelf (its books become “unshelved”)."""
    conn = _conn()
    place_id, shelf_id = _place(conn, spec)
    if not yes and not typer.confirm(f"Remove “{spec}”? Its books will become unshelved"):
        raise typer.Abort()
    if shelf_id:
        services.supprimer_etagere(conn, shelf_id)
    else:
        services.supprimer_lieu(conn, place_id)
    console.print(f"[green]✓[/green] “{esc(spec)}” removed")


# --- Scanning ---------------------------------------------------------------------

def _resolution_callback(db_path):
    def callback(notice_id, notice):
        conn = db.connect(db_path)
        n = services.resume_notice(conn, notice_id)
        conn.close()
        ref = n["reference"] if n else notice_id
        if n and n["statut"] in ("trouve", "manuel"):
            console.print(f"   [dim]↳ {ref}[/dim] {_book_line(n)}")
        else:
            status = n["statut"] if n else "?"
            console.print(f"   [red]↳ {ref}: {status}[/red] (complete it with: biblio show {ref})")
    return callback


@app.command()
def scan(
    place: str = typer.Option(None, "--place", "-p", help="Place or Place/Shelf (created if needed)"),
    mode: str = typer.Option("add", "--mode", "-m", help="add | move | where"),
):
    """Scan books one after another. While scanning: :place Bedroom/S2  :mode move  :undo  :q"""
    if mode not in MODES:
        _fail("modes: add, move, where")
    conn = _conn()
    place_id, shelf_id = _place(conn, place, create=True)
    worker = Worker(on_done=_resolution_callback(db.db_path()))
    worker.start()
    console.print(Panel.fit(
        "Scan barcodes (or type an ISBN and press Enter).\n"
        "[dim]:place Bedroom/S1[/dim] change location · [dim]:mode add|move|where[/dim] · "
        "[dim]:undo[/dim] last addition · [dim]:q[/dim] quit",
        title="Scanning station"))
    last_copy = None
    while True:
        where = services.nom_emplacement(conn, place_id, shelf_id)
        try:
            code = console.input(f"[bold]{mode}[/bold] [cyan]{esc(where)}[/cyan] › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not code:
            continue
        if code in (":q", ":quit", "q", "quit", "exit"):
            break
        if code.startswith(":place"):
            try:
                place_id, shelf_id = services.emplacement(conn, code[6:].strip(), creer=True)
            except Erreur as e:
                console.print(f"[red]✗ {esc(str(e))}[/red]")
            continue
        if code.startswith(":mode"):
            m = code[5:].strip()
            if m in MODES:
                mode = m
            else:
                console.print("[red]modes: add, move, where[/red]")
            continue
        if code == ":undo":
            if last_copy:
                services.annuler_exemplaire(conn, last_copy)
                console.print("[yellow]↺ last addition undone[/yellow]")
                last_copy = None
            continue
        try:
            if MODES[mode] == "ajout":
                res = services.ajouter(conn, code, place_id, shelf_id)
                last_copy = res.get("exemplaire_id") or last_copy
                worker.wake()
            elif MODES[mode] == "deplacement":
                res = services.deplacer(conn, code, place_id, shelf_id)
            else:
                res = services.localiser(conn, code)
        except Erreur as e:
            console.print(f"[red]✗ {esc(str(e))}[/red]\a")
            continue
        colour = COLOURS.get(res["statut"], "white")
        bell = "\a" if not res["ok"] or res["statut"] == "doublon" else ""
        console.print(f"[{colour}]● {res['code']}  {esc(res['message'])}[/{colour}]  "
                      f"{_book_line(res.get('notice'))}{bell}")
    worker.stop()
    pending = conn.execute("SELECT count(*) FROM notices WHERE statut = 'en_attente'").fetchone()[0]
    if pending:
        console.print(f"[yellow]{pending} book(s) still waiting for their description.[/yellow] "
                      "They will be completed by [bold]biblio resolve[/bold] or [bold]biblio serve[/bold].")


@app.command("import")
def import_codes(
    file: Path,
    place: str = typer.Option(None, "--place", "-p", help="Place or Place/Shelf"),
    resolve_after: bool = typer.Option(True, "--resolve/--no-resolve"),
):
    """Import a file of barcodes (one per line), e.g. the scanner's memory."""
    if not file.is_file():
        _fail(f"file not found: {file}")
    conn = _conn()
    place_id, shelf_id = _place(conn, place, create=True)
    ok = errors = duplicates = 0
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        code = line.strip().split(";")[0].split(",")[0].strip()
        if not code or code.startswith("#"):
            continue
        try:
            # Chaque ligne compte : une mémoire de douchette ne dit pas si c'est une double lecture
            res = services.ajouter(conn, code, place_id, shelf_id, filtrer_rebond=False)
            if res["statut"] == "doublon":
                duplicates += 1
                console.print(f"[yellow]? {res['code']}: one more copy (no. {res['exemplaire_id']}); "
                              f"if it was read twice by mistake: biblio remove {res['exemplaire_id']}[/yellow]")
            ok += 1
        except Erreur as e:
            errors += 1
            console.print(f"[red]✗ {esc(str(e))}[/red]")
    console.print(f"[green]✓ {ok} cop(ies) imported[/green], {duplicates} duplicate(s), {errors} error(s)")
    if resolve_after and ok:
        resolve(retry=False)


@app.command()
def resolve(retry: bool = typer.Option(False, "--retry", help="Try again books not found and network errors")):
    """Describe pending books by querying the catalogues (a few seconds per book)."""
    conn = _conn()
    if retry:
        services.relancer(conn)
    total = conn.execute("SELECT count(*) FROM notices WHERE statut = 'en_attente'").fetchone()[0]
    if not total:
        console.print("[green]Nothing pending.[/green]")
        return
    found = 0
    with make_client() as client, Progress(
        TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn(),
        TimeRemainingColumn(), console=console,
    ) as progress:
        task = progress.add_task("Looking up", total=total)
        while (notice_id := prochaine(conn)):
            ref = services.resume_notice(conn, notice_id)["reference"]
            progress.update(task, description=f"Looking up {ref}")
            try:
                n = resolver.resolve(conn, client, notice_id)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                conn.rollback()
                conn.execute("UPDATE notices SET statut = 'erreur' WHERE id = ?", (notice_id,))
                conn.commit()
                progress.console.print(f"[red]✗ {ref}: {esc(str(e))}[/red]")
                n = None
            if n and n.get("couverture_url"):
                resolver.telecharger_couverture(conn, client, notice_id)
            if n and n["statut"] == "trouve":
                found += 1
            else:
                progress.console.print(f"[yellow]? {ref}: {n['statut'] if n else 'error'}[/yellow]")
            progress.advance(task)
    console.print(f"[green]✓ {found}/{total} described.[/green] Others: [bold]biblio todo[/bold]")


@app.command()
def covers(force: bool = typer.Option(False, "--force", help="Download again covers already checked"),
           missing: bool = typer.Option(False, "--missing", help="Try again only the books noted as having no cover")):
    """Download missing covers into data/covers (~1 per second)."""
    conn = _conn()
    rows = conn.execute("SELECT id, isbn13, uid FROM notices WHERE couverture_url IS NOT NULL").fetchall()
    if missing:
        todo = [r for r in rows if covers_store.absente(db.cle_couverture(r)).exists()]
    else:
        todo = [r for r in rows if force or not covers_store.connue(db.cle_couverture(r))]
    if not todo:
        console.print(f"[green]All {len(rows)} covers already handled.[/green]")
        return
    ok = 0
    with make_client() as client, Progress(TextColumn("Covers"), BarColumn(), MofNCompleteColumn(),
                                           TimeRemainingColumn(), console=console) as progress:
        task = progress.add_task("", total=len(todo))
        for r in todo:
            ok += resolver.telecharger_couverture(conn, client, r["id"], forcer=force or missing)
            progress.advance(task)
    console.print(f"[green]✓ {ok} cover(s) downloaded[/green], {len(todo) - ok} without an image")


# --- Browsing ---------------------------------------------------------------------

def _isbn(code: str) -> str:
    """ISBN, ou référence d'un livre sans ISBN (L12)."""
    try:
        return services._code(code)
    except Erreur as e:
        _fail(str(e))


@app.command()
def show(code: str):
    """Show everything about a book."""
    conn = _conn()
    n = services.notice(conn, _isbn(code))
    if not n:
        _fail("not in the collection")
    lines = [
        f"[bold]{esc(n['titre'] or '(untitled)')}[/bold]" + (f" — {esc(n['sous_titre'])}" if n["sous_titre"] else ""),
        esc(", ".join(n["auteurs"])) or "[dim]unknown author[/dim]",
        esc(" · ".join(str(x) for x in [n["editeur"], n["collection"], n["annee"],
                                         f"{n['pages']} p." if n["pages"] else None] if x)),
        f"[dim]{'ISBN ' + n['isbn13'] if n['isbn13'] else 'Reference ' + n['reference']} · language {esc(n['langue'] or '?')}"
        + (f" (original {esc(n['langue_originale'])})" if n["langue_originale"] else "")
        + f" · form {esc(n['forme'] or '?')} · audience {esc(n['public'] or '?')} · status {n['statut']}[/dim]",
    ]
    if n["sujets"]:
        lines.append("[dim]Subjects:[/dim] " + esc(" ; ".join(n["sujets"][:8])))
    if n["resume"]:
        lines.append("")
        lines.append(esc(n["resume"][:600]) + ("…" if len(n["resume"]) > 600 else ""))
    if n["lecture"] or n["etoiles"]:
        lines.append("[dim]Reading:[/dim] " + " · ".join(str(x) for x in [
            {v: k for k, v in READING.items()}.get(n["lecture"]), "★" * n["etoiles"] if n["etoiles"] else None,
            f"started {n['lecture_debut']}" if n["lecture_debut"] else None,
            f"finished {n['lecture_fin']}" if n["lecture_fin"] else None] if x))
    console.print(Panel("\n".join(lines), title="Record", expand=False))

    origins = {"source": "from catalogue", "deduit": "inferred", "manuel": "set by hand"}
    t = Table("System", "Call number", "Class", "Origin")
    for c in n["classifications"]:
        t.add_row(tr(c["nom"]), esc(c.get("cote") or "—"), esc(c.get("libelle") or ""), origins.get(c.get("origine"), ""))
    console.print(t)
    t = Table("Copy", "Owner", "Location", "Added", "Loan")
    for e in n["exemplaires"]:
        t.add_row(str(e["id"]), esc(e["proprietaire"]), esc(e["emplacement"]), e["ajoute_le"][:10],
                  esc(e["pret"]["emprunteur"]) if e["pret"] else "")
    console.print(t)
    for e in n["exemplaires"]:
        details = _copy_details(e)
        if details:
            console.print(f"[dim]Copy {e['id']}:[/dim] {esc(details)}")
    if n["champs_manuels"]:
        console.print(f"[dim]Fields corrected by hand: {', '.join(n['champs_manuels'])}[/dim]")
    sources = ", ".join(f"{r['source']} ({r['statut']})" for r in n["raw"])
    console.print(f"[dim]Catalogues: {sources or 'none'}[/dim]")


@app.command()
def where(code: str):
    """Where is this book? (ISBN or search words)"""
    conn = _conn()
    try:
        res = services.localiser(conn, code)
        console.print(f"{_book_line(res.get('notice'))}\n[bold cyan]{esc(res['message'])}[/bold cyan]")
        return
    except Erreur:
        pass
    rows, total = services.rechercher(conn, code, limite=20, proprietaire="tous")
    if not rows:
        _fail("no book found")
    _copies_table(rows, total)


def _copy_details(e: dict) -> str:
    conditions = {v: k for k, v in CONDITIONS.items()}
    return " · ".join(x for x in [
        conditions.get(e["etat"]), f"bought for {e['prix_achat']:g}" if e["prix_achat"] is not None else None,
        f"on {e['date_achat']}" if e["date_achat"] else None, f"from {e['provenance']}" if e["provenance"] else None,
        f"worth {e['valeur']:g}" if e["valeur"] is not None else None,
        f"inscription: {e['dedicace']}" if e["dedicace"] else None, e["notes"]] if x)


def _copies_table(rows, total):
    t = Table("Call number", "Title", "Author", "Location", "Reference")
    for r in rows:
        where = esc(r["emplacement"]) + (f" [yellow](lent: {esc(r['emprunteur'])})[/yellow]" if r["emprunteur"] else "")
        if not r["a_moi"]:
            where = f"[cyan]{esc(r['proprietaire'])}[/cyan] " + where
        t.add_row(esc(r["cote"]) if r["cote"] else "[dim]unclassified[/dim]",
                  esc(r["titre"]) if r["titre"] else "[dim]?[/dim]", esc(_authors(r)), where, r["reference"])
    console.print(t)
    if total > len(rows):
        console.print(f"[dim]{len(rows)} of {total} shown (option --limit)[/dim]")


@app.command()
def search(
    query: str = typer.Argument("", help="Words from the title, author, subject… or an ISBN"),
    place: str = typer.Option(None, "--place", "-p"),
    system: str = typer.Option(None, "--system", "-s", help=SYSTEM_HELP),
    sort: str = typer.Option("shelf", "--sort", help="shelf | title | author | year | added"),
    since: str = typer.Option(None, "--since", help="Added on or after YYYY-MM-DD"),
    until: str = typer.Option(None, "--until", help="Added on or before YYYY-MM-DD"),
    owner: str = typer.Option(None, "--owner", "-o", help="Whose books: a friend's name, or “all” (default: mine)"),
    reading: str = typer.Option(None, "--reading", help=", ".join(READING)),
    limit: int = typer.Option(50, "--limit", "-n"),
):
    """Search the whole collection (accents ignored, word beginnings accepted)."""
    _check_system(system)
    if sort not in SORTS:
        _fail(f"unknown sort: {sort} (choices: {', '.join(SORTS)})")
    if reading and reading not in READING:
        _fail(f"unknown reading status: {reading} (choices: {', '.join(READING)})")
    conn = _conn()
    place_id, shelf_id = _place(conn, place)
    try:
        rows, total = services.rechercher(conn, query, lieu_id=place_id, etagere_id=shelf_id, systeme=system,
                                          ajout_du=since, ajout_au=until, tri=SORTS[sort], limite=limit,
                                          proprietaire="tous" if owner == "all" else owner,
                                          lecture=READING.get(reading))
    except Erreur as e:
        _fail(str(e))
    if not rows:
        console.print("No books.")
        return
    _copies_table(rows, total)


@app.command("list")
def list_books(
    place: str = typer.Option(None, "--place", "-p"),
    system: str = typer.Option(None, "--system", "-s", help=SYSTEM_HELP),
    sort: str = typer.Option("shelf", "--sort"),
    limit: int = typer.Option(100, "--limit", "-n"),
):
    """List the collection in shelving order."""
    search("", place=place, system=system, sort=sort, since=None, until=None, owner=None, reading=None, limit=limit)


@app.command()
def todo():
    """Books pending, not found, without call number, or without a place."""
    conn = _conn()
    data = services.a_traiter(conn)
    titles = {"en_attente": "Pending", "erreur": "Network errors", "introuvable": "Not found",
              "partiels": "Incomplete answers (retry with: biblio resolve --retry)",
              "sans_cote": f"No call number ({tr(SYSTEMES[systeme_courant(conn)])})", "non_localises": "Unshelved"}
    for key, title in titles.items():
        items = data[key]
        if not items:
            continue
        console.print(f"\n[bold]{title}[/bold] ({len(items)})")
        for n in items[:30]:
            console.print(f"  {n['reference']}  {esc(n['titre']) if n['titre'] else '[dim]?[/dim]'}")
    if not any(data.values()):
        console.print("[green]Everything is in order.[/green]")


# --- Corrections ------------------------------------------------------------------

@app.command()
def edit(
    code: str,
    title: str = typer.Option(None), subtitle: str = typer.Option(None),
    authors: str = typer.Option(None, help='Separated by ; (e.g. "Albert Camus; Camille Dupont")'),
    publisher: str = typer.Option(None), series: str = typer.Option(None),
    year: int = typer.Option(None), pages: int = typer.Option(None),
    language: str = typer.Option(None, help="ISO 639-2 code: fre, eng, ger…"),
    original_language: str = typer.Option(None),
    form: str = typer.Option(None, help=", ".join(services.FORMES)),
    audience: str = typer.Option(None, help=", ".join(services.PUBLICS)),
    subjects: str = typer.Option(None, help="Separated by ;"),
    notes: str = typer.Option(None, help="Personal note in Markdown (see also: biblio note)"),
    release: str = typer.Option(None, help="Give this field back to the catalogues (French field name)"),
):
    """Correct a record. Corrected fields are no longer overwritten automatically."""
    conn = _conn()
    isbn = _isbn(code)
    fields = {k: v for k, v in dict(
        titre=title, sous_titre=subtitle, auteurs=authors, editeur=publisher, collection=series,
        annee=year, pages=pages, langue=language, langue_originale=original_language, forme=form,
        public=audience, sujets=subjects, notes=notes).items() if v is not None}
    try:
        if fields:
            services.modifier_notice(conn, isbn, fields)
        if release:
            services.liberer_champ(conn, isbn, release)
    except Erreur as e:
        _fail(str(e))
    show(isbn)


@app.command()
def note(
    code: str,
    edit_note: bool = typer.Option(False, "--edit", "-e", help="Edit the note in your text editor ($EDITOR)"),
    text: str = typer.Option(None, "--set", help="Replace the note with this text (empty string clears it)"),
):
    """Show or edit a book's personal note, written in Markdown."""
    from rich.markdown import Markdown

    conn = _conn()
    isbn = _isbn(code)
    n = services.notice(conn, isbn)
    if not n:
        _fail("not in the collection")
    if edit_note:
        text = typer.edit(n["notes"] or "", extension=".md")
        if text is None:
            console.print("[dim]No change.[/dim]")
            return
    if text is not None:
        services.modifier_notice(conn, isbn, {"notes": text})
        n["notes"] = text.strip() or None
    title = esc(n["titre"] or n["reference"])
    if n["notes"]:
        console.print(Panel(Markdown(n["notes"]), title=title, expand=False))
    else:
        console.print(f"[dim]No note for “{title}”. Add one with: biblio note {code} --edit[/dim]")


@app.command()
def read(
    code: str,
    status: str = typer.Option(None, "--status", help=", ".join(READING) + ", or an empty string to clear"),
    rating: int = typer.Option(None, "--rating", help="1 to 5 stars, 0 to clear"),
    started: str = typer.Option(None, "--started", help="YYYY-MM-DD, or an empty string to clear"),
    finished: str = typer.Option(None, "--finished", help="YYYY-MM-DD, or an empty string to clear"),
):
    """Show or record your reading of a book: status, dates, rating. Everything is empty by default."""
    conn = _conn()
    isbn = _isbn(code)
    if status and status not in READING:
        _fail(f"unknown reading status: {status} (choices: {', '.join(READING)})")
    fields = {}
    if status is not None:
        fields["lecture"] = READING.get(status)
    if rating is not None:
        fields["etoiles"] = rating or None
    if started is not None:
        fields["lecture_debut"] = started
    if finished is not None:
        fields["lecture_fin"] = finished
    try:
        services.modifier_notice(conn, isbn, fields)
    except Erreur as e:
        _fail(str(e))
    show(isbn)


@app.command("copy")
def copy_details(
    number: int = typer.Argument(..., help="Copy number (see biblio show)"),
    condition: str = typer.Option(None, "--condition", help=", ".join(CONDITIONS) + ", or an empty string to clear"),
    price: str = typer.Option(None, "--price", help="Purchase price"),
    bought: str = typer.Option(None, "--bought", help="Purchase date, YYYY-MM-DD"),
    source: str = typer.Option(None, "--from", help="Where it comes from: bookshop, inheritance, gift…"),
    inscription: str = typer.Option(None, "--inscription"),
    value: str = typer.Option(None, "--value", help="Estimated value"),
    note: str = typer.Option(None, "--note"),
):
    """Show or record the details of one of your copies. Everything is optional, none of it is ever shared."""
    conn = _conn()
    if condition and condition not in CONDITIONS:
        _fail(f"unknown condition: {condition} (choices: {', '.join(CONDITIONS)})")
    fields = {k: v for k, v in dict(prix_achat=price, date_achat=bought, provenance=source, dedicace=inscription,
                                    valeur=value, notes=note).items() if v is not None}
    if condition is not None:
        fields["etat"] = CONDITIONS.get(condition)
    try:
        services.modifier_exemplaire(conn, number, fields)
    except Erreur as e:
        _fail(str(e))
    e = dict(conn.execute("SELECT * FROM exemplaires WHERE id = ?", (number,)).fetchone())
    console.print(f"[dim]Copy {number}:[/dim] {esc(_copy_details(e)) or '[dim]no details[/dim]'}")


@app.command()
def classify(
    code: str,
    system: str = typer.Argument(..., help=SYSTEM_HELP),
    value: str = typer.Argument(None, help="Code (e.g. 843.914, ROMF); empty = back to automatic"),
    label: str = typer.Option(None, "--label"),
):
    """Force a call number in one system (e.g. biblio classify 978… dewey 843.914)."""
    conn = _conn()
    try:
        services.fixer_classification(conn, _isbn(code), system, value, label)
    except Erreur as e:
        _fail(str(e))
    show(code)


@app.command()
def move(code: str, to: str = typer.Argument(..., help="Place or Place/Shelf")):
    """Move a book to another place or shelf."""
    conn = _conn()
    place_id, shelf_id = _place(conn, to, create=True)
    try:
        res = services.deplacer(conn, code, place_id, shelf_id)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[{COLOURS.get(res['statut'], 'white')}]{esc(res['message'])}[/]")


@app.command()
def manual(
    title: str = typer.Option(..., prompt=True),
    authors: str = typer.Option("", prompt="Author(s), separated by ;"),
    place: str = typer.Option(None, "--place", "-p"),
    isbn: str = typer.Option(None, help="ISBN if one is printed (catalogues then fill in the rest)"),
    subtitle: str = typer.Option(None), publisher: str = typer.Option(None), series: str = typer.Option(None),
    year: int = typer.Option(None), pages: int = typer.Option(None),
    language: str = typer.Option(None, help="ISO 639-2 code: fre, eng, ger…"),
    original_language: str = typer.Option(None),
    form: str = typer.Option(None, help=", ".join(services.FORMES)),
    audience: str = typer.Option(None, help=", ".join(services.PUBLICS)),
    subjects: str = typer.Option(None, help="Separated by ;"),
    owner: str = typer.Option(None, "--owner", help="Whose book it is (default: you)"),
    search: bool = typer.Option(True, "--search/--no-search", help="First look it up at the BnF by title and author"),
):
    """Add a book without a barcode (old, self-published…): BnF lookup, or described by hand."""
    from .sources import bnf

    conn = _conn()
    place_id, shelf_id = _place(conn, place, create=True)
    if search and not isbn:
        try:
            with make_client() as client:
                results = bnf.rechercher(client, title, authors, year)
        except bnf.RechercheImpossible as e:
            console.print(f"[yellow]BnF unreachable ({esc(str(e))}): saving what you typed.[/yellow]")
            results = []
        if results:
            t = Table("#", "Title", "Author", "Publisher", "Year", "ISBN")
            for i, r in enumerate(results, 1):
                t.add_row(str(i), esc(r["titre"]), esc(_authors(r)), esc(r["editeur"] or ""), str(r["annee"] or ""), r["isbn"] or "—")
            console.print(t)
            choice = typer.prompt("Number of the matching book (0 = none of them, save what I typed)",
                                  type=int, default=0)
            if 1 <= choice <= len(results):
                try:
                    res = services.ajouter_depuis_bnf(conn, results[choice - 1], place_id, shelf_id, owner)
                except Erreur as e:
                    _fail(str(e))
                console.print(f"[green]✓[/green] added as {res.get('reference') or res['code']} (BnF record)")
                if res.get("recherche"):
                    resolve(retry=False)
                return
        else:
            console.print("[dim]No match at the BnF: saving what you typed.[/dim]")
    fields = dict(sous_titre=subtitle, editeur=publisher, collection=series, annee=year, pages=pages,
                  langue=language, langue_originale=original_language, forme=form, public=audience,
                  sujets=subjects)
    try:
        res = services.creer_notice_manuelle(conn, title, authors, isbn=isbn, lieu_id=place_id,
                                             etagere_id=shelf_id, proprietaire=owner,
                                             **{k: v for k, v in fields.items() if v is not None})
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓[/green] added as {res['reference']}")
    if res["recherche"]:
        resolve(retry=False)


@app.command()
def remove(copy: int, yes: bool = typer.Option(False, "--yes")):
    """Remove a copy from the collection (its number is shown by biblio show)."""
    conn = _conn()
    if not yes and not typer.confirm(f"Remove copy {copy}?"):
        raise typer.Abort()
    try:
        services.annuler_exemplaire(conn, copy)
    except Erreur as e:
        _fail(str(e))
    console.print("[green]✓ removed[/green]")


def _duplicate_book(book: dict) -> str:
    title = book["titre"] or book["reference"]
    return esc(f"{title} — {_authors(book)}" if book["auteurs"] else title)


@app.command()
def duplicates(
    remove_extra: bool = typer.Option(False, "--remove", help="Remove the extra copies on the same shelf, after a backup"),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
):
    """List the books you own more than once; --remove clears the extra copies on the same shelf."""
    conn = _conn()
    found = services.doublons(conn)
    extra = sum(len(group["retirer"]) for group in found["de_trop"])

    def section(title: str, columns: list[str], rows: list[tuple]) -> None:
        console.print(f"[bold]{title}[/bold]")
        if rows:
            table = Table(*columns)
            for row in rows:
                table.add_row(*row)
            console.print(table)

    def places(book: dict) -> str:
        where: dict[str, list[str]] = {}
        for copy in book["exemplaires"]:
            where.setdefault(copy["emplacement"], []).append(str(copy["id"]))
        return "\n".join(f"{esc(place)}: {', '.join(ids)}" for place, ids in where.items())

    def record(book: dict) -> str:
        return esc(" · ".join(str(x) for x in (book["reference"], book["sous_titre"], book["editeur"], book["annee"]) if x))

    section(f"Same book in several copies, all places: {len(found['titres'])}", ["Book", "Copies (place: numbers)"],
            [(_duplicate_book(book), places(book)) for book in found["titres"]])
    section(f"Same title and author, another record (another edition, or another volume): {len(found['editions'])}",
            ["Book", "Records"],
            [(_duplicate_book(books[0]), "\n".join(map(record, books))) for books in found["editions"]])
    section(f"Extra copies on the same shelf: {extra}", ["Book", "Place", "Keep", "Remove"],
            [(_duplicate_book(group), esc(group["emplacement"]), ", ".join(map(str, group["garder"])),
              ", ".join(map(str, group["retirer"]))) for group in found["de_trop"]])

    if not extra:
        return
    if not remove_extra:
        console.print("[dim]Nothing was changed. To remove them: biblio duplicates --remove. "
                      "A copy with details is never removed: to keep a real second copy, "
                      "give it a note (biblio copy N --note …).[/dim]")
        return
    if not yes and not typer.confirm(f"Remove {extra} extra copies?"):
        raise typer.Abort()
    copy = sauvegarde.creer(conn)
    removed = services.retirer_doublons(conn)
    console.print(f"[green]✓ {removed} extra copies removed[/green] [dim](previous database kept in {esc(str(copy))})[/dim]")


# --- Inventory, loans ----------------------------------------------------------------

@app.command()
def inventory(zone: str = typer.Argument(..., help="Place or Place/Shelf to check")):
    """Check a shelf: scan everything on it, then :done for the report."""
    conn = _conn()
    place_id, shelf_id = _place(conn, zone)
    try:
        inv_id = services.demarrer_inventaire(conn, place_id, shelf_id)
    except Erreur as e:
        _fail(str(e))
    console.print(Panel.fit(f"Scan every book on [bold]{esc(zone)}[/bold]. Type [bold]:done[/bold] for the report.",
                            title="Inventory"))
    while True:
        try:
            code = console.input("[bold]inventory[/bold] › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if code in (":done", ":q", "q"):
            break
        if not code:
            continue
        try:
            res = services.scanner_inventaire(conn, inv_id, code)
        except Erreur as e:
            console.print(f"[red]✗ {esc(str(e))}[/red]\a")
            continue
        colour = COLOURS.get(res["statut"], "white")
        console.print(f"[{colour}]● {esc(res['message'])}[/{colour}]  {_book_line(res.get('notice'))}"
                      + ("" if res["ok"] else "\a"))
    report = services.rapport_inventaire(conn, inv_id)
    console.print(f"\n[green]Present: {len(report['presents'])}[/green]")
    if report["manquants"]:
        console.print(f"[red]Missing: {len(report['manquants'])}[/red]")
        for n in report["manquants"]:
            console.print(f"  {esc(n.get('titre') or n['reference'])}" + ("  [yellow](lent)[/yellow]" if n["prete"] else ""))
    if report["ailleurs"]:
        console.print(f"[yellow]Recorded elsewhere: {len(report['ailleurs'])}[/yellow]")
        for n in report["ailleurs"]:
            console.print(f"  {esc(str(n.get('titre')))}  (database: {esc(', '.join(n['emplacements']))})")
    if report["inconnus"]:
        console.print(f"[red]Not in the collection: {len(report['inconnus'])}[/red]  {', '.join(report['inconnus'])}")
    reshelve = bool(report["ailleurs"]) and typer.confirm("Record the books found here at this location?")
    add = bool(report["inconnus"]) and typer.confirm("Add the unknown books to the collection?")
    services.cloturer_inventaire(conn, inv_id, ranger_ailleurs=reshelve, ajouter_inconnus=add)
    if add:
        resolve(retry=False)


@app.command()
def lend(code: str, borrower: str):
    """Record a loan: biblio lend 978… "Marie"."""
    try:
        services.preter(_conn(), code, borrower)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓ lent to {esc(borrower)}[/green]")


@app.command("return")
def return_book(code: str):
    """Record that a lent book came back."""
    try:
        res = services.rendre(_conn(), code)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓ returned by {esc(res['emprunteur'])}[/green]")


@app.command()
def owners():
    """Whose books are in the database: you, and the friends whose catalogue you merged."""
    t = Table("Owner", "Copies")
    for o in services.proprietaires(_conn()):
        t.add_row(f"[bold]{esc(o['nom'])}[/bold] (you)" if o["local"] else esc(o["nom"]), str(o["nb"]))
    console.print(t)


@app.command()
def give(code: str = typer.Argument(..., help="Copy number (see biblio show) or ISBN"),
         to: str = typer.Argument(..., help="New owner"),
         yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation")):
    """Give a book away: it changes owner (this is not a loan — use lend for that)."""
    conn = _conn()
    if code.isdigit() and len(code) < 9:
        copy_id = int(code)
    else:
        mine = services.exemplaires_de(conn, _isbn(code), miens=True)
        if not mine:
            _fail("you have no copy of this book")
        copy_id = mine[0]["id"]
    if not yes and not typer.confirm(f"Give copy {copy_id} to {to}? It will leave your collection (not a loan)"):
        raise typer.Abort()
    try:
        changed = services.donner(conn, copy_id, to)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓ given to {esc(to)}[/green]" if changed else f"[dim]already owned by {esc(to)}[/dim]")


@app.command()
def loans():
    """Books currently lent."""
    rows = services.prets(_conn())
    if not rows:
        console.print("No current loans.")
        return
    t = Table("Title", "Borrower", "Since")
    for p in rows:
        t.add_row(esc(p["titre"] or p["reference"]), esc(p["emprunteur"]), p["date_pret"][:10])
    console.print(t)


# --- Classification, settings, data ------------------------------------------------------

@app.command()
def system(name: str = typer.Argument(None, help=SYSTEM_HELP)):
    """Show or choose the default classification system."""
    conn = _conn()
    if name:
        try:
            services.choisir_systeme(conn, name)
        except Erreur as e:
            _fail(str(e))
    current = systeme_courant(conn)
    for s, label in SYSTEMES.items():
        line = f"{s:10} {tr(label)}"
        console.print(f"[bold green]● {line}[/]" if s == current else f"  {line}")


@app.command()
def reclassify(reread: bool = typer.Option(False, "--reread", help="Also re-read the stored catalogue responses")):
    """Recompute every call number (after editing rules/*.toml). No network requests."""
    conn = _conn()
    if reread:
        ids = [r["id"] for r in conn.execute("SELECT id FROM notices WHERE statut != 'en_attente'")]
        for notice_id in ids:
            resolver.rebuild(conn, notice_id)
        console.print(f"[green]✓ {len(ids)} records rebuilt from stored data[/green]")
    else:
        console.print(f"[green]✓ {reclasser_tout(conn)} records reclassified[/green]")


@app.command()
def config(key: str = typer.Argument(None), value: str = typer.Argument(None),
           clear: bool = typer.Option(False, "--clear")):
    """Settings. E.g.: biblio config google_api_key <key> (enables Google Books)."""
    conn = _conn()
    known = {"google_api_key": "Google Books API key (optional)", "systeme": "default classification system",
             "langue": "web interface language (fr or en)",
             "proprietaire": "your name as the owner of your books (renames all your copies)"}
    if key and (value or clear):
        if key not in known:
            _fail(f"unknown setting (choices: {', '.join(known)})")
        if key == "systeme":
            try:
                services.choisir_systeme(conn, value)
            except Erreur as e:
                _fail(str(e))
        elif key == "langue" and value not in i18n.LANGUES:
            _fail(f"language: {', '.join(i18n.LANGUES)}")
        elif key == "proprietaire":
            try:
                services.renommer_proprietaire_local(conn, value)
            except Erreur as e:
                _fail(str(e))
        else:
            db.set_meta(conn, key, None if clear else value)
    for k, desc in known.items():
        v = services.proprietaire_local(conn) if k == "proprietaire" else db.get_meta(conn, k)
        if k == "google_api_key" and v:
            v = v[:6] + "…"
        console.print(f"{k:16} {esc(v) if v else '[dim]not set[/dim]'}  [dim]{desc}[/dim]")
    console.print(f"[dim]database: {esc(str(db.db_path()))}[/dim]")


@app.command()
def stats():
    """A few figures about the collection."""
    s = services.stats(_conn())
    console.print(f"[bold]{s['exemplaires']}[/bold] books ({s['notices']} distinct titles), "
                  f"{s['auteurs']} authors, {s['pages']:,} pages"
                  + (f", {s['prets']} lent" if s["prets"] else ""))
    if s["lecture_lus"] or s["lecture_en_cours"] or s["lecture_a_lire"]:
        console.print(f"Reading: {s['lecture_lus']} read, {s['lecture_en_cours']} in progress, "
                      f"{s['lecture_a_lire']} to read, {s['lecture_pages']:,} pages read")
    if s["valeur_renseignee"] or s["prix_renseigne"]:
        console.print(f"Value: {s['valeur_totale']:,.2f} estimated ({s['valeur_renseignee']} copies), "
                      f"{s['prix_total']:,.2f} paid ({s['prix_renseigne']} copies)")
    if s["prets_en_cours"]:
        t = Table("Current loans", "Borrower", "Days")
        for p in s["prets_en_cours"][:10]:
            t.add_row(esc(p["nom"]), esc(p["qui"]), str(p["nb"]))
        console.print(t)
    for title, key in (("By place", "par_lieu"), (f"By class ({tr(SYSTEMES[s['systeme']])})", "par_classe"),
                       ("Most frequent authors", "par_auteur"), ("Publishers", "par_editeur"),
                       ("Series", "par_collection"), ("Fullest shelves", "par_etagere")):
        if s[key]:
            t = Table(title, "Books")
            for r in s[key][:10]:
                t.add_row(esc(str(r["nom"])), str(r["nb"]))
            console.print(t)


@app.command()
def export(
    format: str = typer.Option("xlsx", "--format", "-f", help="xlsx | csv"),
    output: Path = typer.Option(None, "--output", "-o"),
    system: str = typer.Option(None, "--system", "-s"),
):
    """Export the collection (Excel: one overall sheet plus one per place)."""
    from . import export as exporter

    _check_system(system)
    conn = _conn()
    if format not in ("xlsx", "csv"):
        _fail("format: xlsx or csv")
    # next to the database (data/exports by default): the code folder may be read-only (server install)
    output = output or db.chemin_base(conn).parent / "exports" / f"library-{date.today()}.{format}"
    output.parent.mkdir(parents=True, exist_ok=True)
    data = exporter.xlsx_bytes(conn, systeme=system) if format == "xlsx" else exporter.csv_bytes(conn, systeme=system)
    output.write_bytes(data)
    console.print(f"[green]✓[/green] {esc(str(output))}")


@app.command()
def share(
    output: Path = typer.Option(..., "--output", "-o", help="File to create, e.g. for-victor.db"),
    place: list[str] = typer.Option(None, "--place", "-p", help="Only these places (repeatable)"),
    hide_places: bool = typer.Option(False, "--hide-places", help="Say that you own the books, not where they are"),
    with_loans: bool = typer.Option(False, "--with-loans", help="Also share your loans, borrowers' names included"),
    force: bool = typer.Option(False, "--force", help="Replace an older share file without asking"),
):
    """Write a file with your books for a friend (no notes, keys or settings; no loans unless asked)."""
    from . import partage

    conn = _conn()
    ids = [_place(conn, p)[0] for p in place or []]
    if output.exists() and not force and partage.est_fichier_de_partage(output):
        if output.resolve() != db.chemin_base(conn).resolve() and not typer.confirm(f"Replace the share file {output}?"):
            raise typer.Abort()
    try:
        res = partage.exporter_partage(conn, output, lieux=ids, masquer_lieux=hide_places, avec_prets=with_loans)
    except Erreur as e:
        _fail(str(e))
    console.print(f"[green]✓[/green] {esc(str(output))}: {res['exemplaires']} copies of {res['notices']} books, "
                  f"owner “{esc(res['proprietaire'])}”" + (", places hidden" if hide_places else "")
                  + (f", {res['prets']} loans with borrowers' names" if with_loans else ""))
    console.print(f"[dim]Your friend adds it to their library with: biblio merge {esc(output.name)}[/dim]")


REPORT = {"notices_ajoutees": "records added", "notices_completees": "records completed",
          "exemplaires_ajoutes": "copies added", "exemplaires_mis_a_jour": "copies updated",
          "exemplaires_retires": "copies removed", "prets_ajoutes": "loans added or closed",
          "prets_retires": "loans no longer shared, removed",
          "lieux_ajoutes": "places or shelves added", "lieux_mis_a_jour": "places or shelves updated",
          "lieux_retires": "places or shelves removed",
          "exemplaires_ignores": "copies not taken: they are not this friend's own"}


@app.command()
def merge(
    file: Path = typer.Argument(..., help="A friend's share file, or the database you scanned for them"),
    as_owner: str = typer.Option(None, "--as", help="Name to give this friend here (e.g. Victor)"),
    replace: bool = typer.Option(False, "--replace",
                                 help="Remove that friend's copies and loans that are no longer in the file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would change"),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
):
    """Add a friend's catalogue to your library. For your own other computer, use biblio sync."""
    from . import partage

    conn = _conn()
    try:
        info = partage.resume_source(file)
        preview = partage.importer_ami(conn, file, comme=as_owner, remplacer=replace, simulation=True)
    except Erreur as e:
        _fail(str(e))
    console.print(f"{esc(str(file))}: {info['exemplaires']} copies — books of [bold]{esc(preview['source'])}[/bold]"
                  + (" [dim](share file)[/dim]" if info["partage"] else "")
                  + (" [dim](with loans)[/dim]" if info["prets"] else ""))
    _merge_report(preview)
    if dry_run:
        console.print("[dim]Dry run: nothing changed.[/dim]")
        return
    if not any(v for k, v in preview.items() if k in REPORT and k != "exemplaires_ignores"):
        console.print("[green]Already up to date.[/green]")
        return
    if not yes and not typer.confirm("Apply?"):
        raise typer.Abort()
    backup = partage.sauvegarder(conn, "avant-fusion")
    report = partage.importer_ami(conn, file, comme=as_owner, remplacer=replace)
    console.print(f"[green]✓ merged[/green] [dim](previous database kept in {esc(backup.name)})[/dim]")
    _merge_report(report)


@app.command()
def sync(
    file: Path = typer.Argument(..., help="Your database on another computer"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would change"),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
):
    """Sync with another of your own databases: additions, changes and removals. Run it on both sides."""
    from . import partage

    conn = _conn()
    try:
        info = partage.resume_source(file)
        pair = not partage.est_ma_base(conn, file)
        if pair and not dry_run and not yes and not typer.confirm(
                f"{file} belongs to “{info['proprietaire']}” and has never been synced with this database. Is it yours?"):
            raise typer.Abort()
        preview = partage.synchroniser(conn, file, appairer=pair, simulation=True)
    except Erreur as e:
        _fail(str(e))
    console.print(f"{esc(str(file))}: {info['exemplaires']} copies")
    _merge_report(preview)
    if dry_run:
        console.print("[dim]Dry run: nothing changed.[/dim]")
        return
    if not pair and not any(v for k, v in preview.items() if k in REPORT):
        console.print("[green]Already up to date.[/green]")
        return
    if not yes and not typer.confirm("Apply?"):
        raise typer.Abort()
    backup = partage.sauvegarder(conn, "avant-synchro")
    report = partage.synchroniser(conn, file, appairer=pair)
    console.print(f"[green]✓ synced[/green] [dim](previous database kept in {esc(backup.name)})[/dim]")
    _merge_report(report)


def _merge_report(report: dict) -> None:
    for key, label in REPORT.items():
        if report.get(key):
            console.print(f"  {report[key]:>5}  {label}")


@app.command()
def backup(
    directory: Path = typer.Option(None, "--dir", help="Where to put the copy (default: data/sauvegardes)"),
    keep: int = typer.Option(sauvegarde.GARDER, "--keep", min=1, help="How many copies of this database to keep"),
):
    """Make a consistent copy of the database, in a single file, even while the server is running."""
    copy = sauvegarde.creer(_conn(), dossier=directory, garder=keep)
    console.print(f"[green]✓[/green] {esc(str(copy))}")


@app.command()
def sql(query: str = typer.Argument(None, help="SQL query; without argument, opens the sqlite3 shell")):
    """Direct access to the SQLite database (the core of the engine)."""
    path = db.db_path()
    if not query:
        _conn().close()
        if not shutil.which("sqlite3"):
            _fail("sqlite3 not found; pass a query as argument")
        console.print(f"[dim]{esc(str(path))} — tables: notices, exemplaires, personnes, classifications, lieux, "
                      "etageres, raw_responses, mouvements, inventaires, prets, suppressions. Quit: .quit[/dim]")
        if sys.platform == "win32":                     # pas de exec sous Windows : on attend le shell
            raise typer.Exit(subprocess.run(["sqlite3", "-box", str(path)]).returncode)
        os.execvp("sqlite3", ["sqlite3", "-box", str(path)])
    conn = _conn()
    try:
        cur = conn.execute(query)
    except Exception as e:
        _fail(str(e))
    if cur.description:
        t = Table(*[d[0] for d in cur.description])
        for row in cur.fetchmany(500):
            t.add_row(*["" if v is None else esc(str(v)[:80]) for v in row])
        console.print(t)
    else:
        conn.commit()
        console.print(f"[green]✓ {cur.rowcount} row(s) changed[/green]")


@app.command()
def serve(
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Address the app listens on for this computer"),
    phone: bool = typer.Option(False, "--phone", help="Allow scanning with a phone on the same Wi-Fi (HTTPS)"),
    phone_port: int = typer.Option(None, "--phone-port", min=1, max=65535,
                                   help="HTTPS port for phones (default 8443, or $BIBLIO_PORT_HTTPS)"),
    install_port: int = typer.Option(None, "--install-port", min=1, max=65535,
                                     help="Port of the certificate installation page (default 8080, "
                                          "or $BIBLIO_PORT_INSTALLATION)"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser"),
):
    """Start the local web app (scanning station, catalogue, places…)."""
    import uvicorn

    from . import telephone as tel

    tel.PORT_HTTPS = phone_port or tel.PORT_HTTPS
    tel.PORT_INSTALLATION = install_port or tel.PORT_INSTALLATION
    if phone and len({port, tel.PORT_HTTPS, tel.PORT_INSTALLATION}) < 3:
        _fail("--port, --phone-port and --install-port must be three different ports")
    ports = [(host, port)]
    if phone:
        ports += [("0.0.0.0", tel.PORT_HTTPS), ("0.0.0.0", tel.PORT_INSTALLATION)]
    for h, p in ports:
        if not _port_free(h, p):
            _fail(f"port {p} is already in use — the library may already be running in another "
                  f"terminal (stop it with Ctrl+C), or choose --port")
    _automatic_backup()
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    console.print(f"[green]Library:[/green] {url}   [dim](Ctrl+C to stop)[/dim]")
    if not phone:
        if open_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run("biblio.web.app:app", host=host, port=port, log_level="warning")
        return

    from . import certs
    from .web.app import app as web_app, installation

    ip, name = tel.ip_locale(), tel.nom_local()
    cert, private_key = certs.serveur(["localhost", name], ["127.0.0.1", ip])
    tel.activer(ip, name)
    conn = _conn()
    tel.cle(conn)
    conn.close()
    configs = [
        uvicorn.Config(web_app, host=host, port=port, log_level="warning"),
        uvicorn.Config(web_app, host="0.0.0.0", port=tel.PORT_HTTPS, log_level="warning", lifespan="off",
                       ssl_certfile=str(cert), ssl_keyfile=str(private_key)),
        uvicorn.Config(installation, host="0.0.0.0", port=tel.PORT_INSTALLATION, log_level="warning",
                       lifespan="off"),
    ]
    console.print(f"[green]Phone:[/green] open {url}/telephone and scan the QR codes "
                  f"[dim](https://{ip}:{tel.PORT_HTTPS})[/dim]")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url + "/telephone")).start()
    _serve_together([uvicorn.Server(c) for c in configs])


def _automatic_backup() -> None:
    """A copy a day when the server starts; a failure must not keep the library from opening."""
    conn = _conn()
    try:
        copy = sauvegarde.automatique(conn)
    except (OSError, sqlite3.Error) as e:
        console.print(f"[yellow]Automatic backup failed: {esc(str(e))}[/yellow]")
        return
    finally:
        conn.close()
    if copy:
        console.print(f"[dim]Backup: {esc(str(copy))}[/dim]")


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # as uvicorn does
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _serve_together(servers) -> None:
    """Run several uvicorn servers; stopping one (Ctrl+C) stops the others."""
    import asyncio

    async def main():
        tasks = [asyncio.create_task(s.serve()) for s in servers]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for s in servers:
            s.should_exit = True
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


@app.command()
def phone(
    new_key: bool = typer.Option(False, "--new-key", help="Change the key (phones will have to scan again)"),
    admin: bool = typer.Option(False, "--admin", help="The admin key instead, for your own computer when the library "
                                                       "runs on a server: everything, settings included"),
):
    """Addresses and QR codes to scan with a phone (server started with serve --phone)."""
    import segno

    from . import telephone as tel

    conn = _conn()
    if admin:
        if new_key:
            tel.nouvelle_cle_admin(conn)
            console.print("[yellow]New admin key: browsers that had the old one must open this address again.[/yellow]")
        console.print("\n[bold]Admin access[/bold] (your own computer only: never on a phone, never as a QR code)")
        console.print(tel.url_admin(conn), soft_wrap=True)
        console.print("[dim]Open it once in the browser: the key moves into a cookie and leaves the address. "
                      "Then bookmark the page.[/dim]")
        return
    if new_key:
        tel.nouvelle_cle(conn)
        console.print("[yellow]New key: phones already connected must scan the QR code again.[/yellow]")
    urls = tel.urls(conn)
    for title, key in (("1. First time: install the certificate", "installation"), ("2. Scan", "scan")):
        console.print(f"\n[bold]{title}[/bold]  [dim]{urls[key]}[/dim]")
        segno.make(urls[key], error="m").terminal(compact=True)
    console.print("\n[dim]The server must be running with: biblio serve --phone[/dim]")


if __name__ == "__main__":
    app()
