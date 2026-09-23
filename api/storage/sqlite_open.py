"""One way to open a SQLite file, so concurrent writers stop colliding.

Two processes touch these files at once: the API service (answering the
dashboard, and writing the journal, the paper book and the login record) and
the 19:30 job (writing the forward log, the archives and the research). With
SQLite's defaults that means "database is locked" — a 500 on the dashboard,
or a nightly step that fails for no reason anyone would ever diagnose.

Two settings fix it:

  WAL          readers no longer block the writer, and the writer no longer
               blocks readers. Set once per file; it sticks.
  busy_timeout a writer waits its turn instead of failing instantly. 30s is
               far longer than any write here takes, and a wait beats a crash.

Every store opens through this. An unwritable or corrupt file falls back to a
plain connection rather than taking the process down — a dashboard that loads
without the journal is better than one that does not load.
"""

import sqlite3
from pathlib import Path

TIMEOUT_SECONDS = 30
BUSY_TIMEOUT_MS = 30_000


def open_db(path: Path | str, timeout: float = TIMEOUT_SECONDS) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        # A read-only directory or a file another tool holds exclusively:
        # keep the connection, lose the tuning, carry on.
        pass
    return conn
