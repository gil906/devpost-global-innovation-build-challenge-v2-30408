"""Anonymous, bounded, seven-day scenario snapshots. No personal data is required."""

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

MAX_PER_SESSION = 25
MAX_TOTAL = 1000
RETENTION_SECONDS = 7 * 24 * 60 * 60


class StoreFull(Exception):
    pass


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "commontable.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    scenario TEXT NOT NULL, created_at INTEGER NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS scenarios_owner ON scenarios(owner)")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, owner, scenario):
        identifier, now = secrets.token_hex(16), int(time.time())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM scenarios WHERE created_at < ?", (now - RETENTION_SECONDS,))
            count = connection.execute("SELECT COUNT(*) FROM scenarios WHERE owner = ?", (owner,)).fetchone()[0]
            total = connection.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
            if count >= MAX_PER_SESSION or total >= MAX_TOTAL:
                raise StoreFull("Snapshot storage is full. Delete an older snapshot or export your scenario as JSON.")
            connection.execute("INSERT INTO scenarios VALUES (?, ?, ?, ?, ?)",
                               (identifier, owner, scenario["name"], json.dumps(scenario), now))
        return {"id": identifier, "name": scenario["name"], "created_at": now}

    def list(self, owner):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at FROM scenarios WHERE owner = ? AND created_at >= ? "
                "ORDER BY created_at DESC, rowid DESC",
                (owner, int(time.time()) - RETENTION_SECONDS),
            ).fetchall()
        return [dict(zip(("id", "name", "created_at"), row)) for row in rows]

    def get(self, owner, identifier):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT scenario FROM scenarios WHERE owner = ? AND id = ? AND created_at >= ?",
                (owner, identifier, int(time.time()) - RETENTION_SECONDS),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, owner, identifier):
        with self.connect() as connection:
            deleted = connection.execute("DELETE FROM scenarios WHERE owner = ? AND id = ?", (owner, identifier))
            return bool(deleted.rowcount)
