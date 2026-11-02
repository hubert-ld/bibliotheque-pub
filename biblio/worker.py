"""Résolution en arrière-plan : le scan n'attend jamais le réseau.

Chaque scan crée une notice « en_attente » ; ce fil la complète dès que possible,
au rythme poli d'environ une requête par seconde et par catalogue (quelques secondes par livre).
"""

import logging
import threading
import traceback

from . import db, resolver
from .sources import make_client

log = logging.getLogger("biblio.worker")
PAUSE_APRES_ERREUR = 5


def prochaine(conn) -> int | None:
    row = conn.execute(
        "SELECT id FROM notices WHERE statut = 'en_attente' ORDER BY cree_le, id LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


class Worker(threading.Thread):
    def __init__(self, db_path=None, on_done=None):
        super().__init__(name="biblio-worker", daemon=True)
        self.db_path = db_path
        self.on_done = on_done
        self._wake = threading.Event()
        self._arret = threading.Event()
        self.en_cours: str | None = None

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._arret.set()
        self._wake.set()

    def run(self) -> None:
        conn = db.connect(self.db_path)
        client = make_client()
        try:
            while not self._arret.is_set():
                try:
                    self._tour(conn, client)
                except Exception:      # base occupée, disque plein… : la file ne doit jamais s'arrêter
                    log.exception("fil de fond : nouvel essai dans %s s", PAUSE_APRES_ERREUR)
                    self._arret.wait(PAUSE_APRES_ERREUR)
        finally:
            client.close()
            conn.close()

    def _tour(self, conn, client) -> None:
        notice_id = prochaine(conn)
        if not notice_id:
            self._wake.wait(timeout=10)
            self._wake.clear()
            return
        self.en_cours = notice_id
        try:
            notice = resolver.resolve(conn, client, notice_id)
        except Exception:
            log.error("échec de résolution de la notice %s\n%s", notice_id, traceback.format_exc())
            conn.rollback()
            conn.execute("UPDATE notices SET statut = 'erreur', maj_le = ? WHERE id = ?",
                         (db.now(), notice_id))
            conn.commit()
            notice = None
        finally:
            self.en_cours = None
        if notice and notice.get("couverture_url"):
            resolver.telecharger_couverture(conn, client, notice_id)
        if self.on_done:
            self.on_done(notice_id, notice)
