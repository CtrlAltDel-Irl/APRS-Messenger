"""SQLite persistence: credentials, address book (max 500), chat history."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def default_data_dir() -> Path:
    env = os.environ.get("APRS_MESSENGER_DATA")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".local" / "share" / "aprs-messenger"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Contact:
    id: int
    callsign: str
    name: str
    notes: str = ""
    created_at: float = 0.0


@dataclass
class ChatMessage:
    id: int
    peer: str
    direction: str  # "out" | "in"
    body: str
    msg_id: str
    status: str  # pending | sent | delivered | failed | received
    ts: float


class Storage:
    MAX_CONTACTS = 500

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (default_data_dir() / "messenger.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # UI + network callbacks may touch the DB; serialize all access.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            c = self._conn.cursor()
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    callsign TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    peer TEXT NOT NULL COLLATE NOCASE,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    msg_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_peer_ts ON messages(peer, ts);
                CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(msg_id);
                """
            )
            self._conn.commit()

    # ── settings ──────────────────────────────────────────
    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def get_credentials(self) -> tuple[str, str]:
        with self._lock:
            return self.get_setting("callsign"), self.get_setting("passcode")

    def get_grid(self) -> str:
        return self.get_setting("grid", "")

    def set_credentials(self, callsign: str, passcode: str, grid: str = "") -> None:
        with self._lock:
            self.set_setting("callsign", callsign)
            self.set_setting("passcode", passcode)
            self.set_setting("grid", (grid or "").strip().upper())
            self.set_setting("configured", "1")

    def is_configured(self) -> bool:
        with self._lock:
            return self.get_setting("configured") == "1" and bool(
                self.get_setting("callsign")
            )

    def clear_credentials(self) -> None:
        with self._lock:
            for k in ("callsign", "passcode", "grid", "configured"):
                self._conn.execute("DELETE FROM settings WHERE key = ?", (k,))
            self._conn.commit()

    # ── contacts ──────────────────────────────────────────
    def contact_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()
            return int(row["n"])

    def list_contacts(self) -> list[Contact]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM contacts ORDER BY callsign COLLATE NOCASE"
            ).fetchall()
            return [self._row_contact(r) for r in rows]

    def get_contact_by_callsign(self, callsign: str) -> Optional[Contact]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM contacts WHERE callsign = ? COLLATE NOCASE",
                (callsign,),
            ).fetchone()
            return self._row_contact(row) if row else None

    def add_contact(self, callsign: str, name: str, notes: str = "") -> Contact:
        with self._lock:
            if self.contact_count() >= self.MAX_CONTACTS:
                raise ValueError(
                    f"Address book full (maximum {self.MAX_CONTACTS} contacts)."
                )
            callsign = callsign.strip().upper()
            name = (name or callsign).strip()
            notes = notes.strip()
            ts = time.time()
            try:
                cur = self._conn.execute(
                    "INSERT INTO contacts(callsign, name, notes, created_at) "
                    "VALUES(?,?,?,?)",
                    (callsign, name, notes, ts),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Contact {callsign} already exists.") from e
            return Contact(
                id=cur.lastrowid,
                callsign=callsign,
                name=name,
                notes=notes,
                created_at=ts,
            )

    def delete_contact(self, contact_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
            self._conn.commit()

    def update_contact(
        self, contact_id: int, callsign: str, name: str, notes: str = ""
    ) -> None:
        callsign = callsign.strip().upper()
        name = name.strip() or callsign
        notes = notes.strip()
        with self._lock:
            # Prevent colliding with another contact's callsign
            row = self._conn.execute(
                "SELECT id FROM contacts WHERE callsign = ? COLLATE NOCASE AND id != ?",
                (callsign, contact_id),
            ).fetchone()
            if row:
                raise ValueError(f"Contact {callsign} already exists.")
            self._conn.execute(
                "UPDATE contacts SET callsign = ?, name = ?, notes = ? WHERE id = ?",
                (callsign, name, notes, contact_id),
            )
            self._conn.commit()

    @staticmethod
    def _row_contact(r: sqlite3.Row) -> Contact:
        return Contact(
            id=r["id"],
            callsign=r["callsign"],
            name=r["name"],
            notes=r["notes"] or "",
            created_at=r["created_at"],
        )

    # ── messages ──────────────────────────────────────────
    def add_message(
        self,
        peer: str,
        direction: str,
        body: str,
        msg_id: str = "",
        status: str = "sent",
        ts: Optional[float] = None,
    ) -> ChatMessage:
        ts = ts if ts is not None else time.time()
        peer = peer.strip().upper()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(peer, direction, body, msg_id, status, ts) "
                "VALUES(?,?,?,?,?,?)",
                (peer, direction, body, msg_id, status, ts),
            )
            self._conn.commit()
            return ChatMessage(
                id=cur.lastrowid,
                peer=peer,
                direction=direction,
                body=body,
                msg_id=msg_id,
                status=status,
                ts=ts,
            )

    def update_message_status(
        self,
        msg_id: str,
        status: str,
        peer: Optional[str] = None,
    ) -> int:
        """
        Update status for outbound message(s) with this APRS msg id.

        When peer is set (recommended for ACK/REJ), only that conversation is
        updated so recycled 2-digit msg ids cannot mark other chats delivered.
        Only rows still awaiting confirmation (pending/sent) are changed.
        Returns rows changed.
        """
        msg_id = (msg_id or "").strip()
        if not msg_id:
            return 0
        sql = (
            "UPDATE messages SET status = ? "
            "WHERE msg_id = ? AND direction = 'out' "
            "AND status IN ('pending', 'sent')"
        )
        params: list = [status, msg_id]
        if peer:
            sql += " AND peer = ? COLLATE NOCASE"
            params.append(peer.strip().upper())
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount

    def get_message_by_id(self, db_id: int) -> Optional[ChatMessage]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE id = ?", (db_id,)
            ).fetchone()
            return self._row_message(row) if row else None

    def list_messages(self, peer: str, limit: int = 500) -> list[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE peer = ? COLLATE NOCASE "
                "ORDER BY ts ASC LIMIT ?",
                (peer.strip().upper(), limit),
            ).fetchall()
            return [self._row_message(r) for r in rows]

    def list_conversations(self) -> list[dict]:
        """Peers with last message preview."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.peer,
                       m.body AS last_body,
                       m.ts AS last_ts,
                       m.direction,
                       m.status,
                       (SELECT name FROM contacts c
                        WHERE c.callsign = m.peer COLLATE NOCASE) AS name
                FROM messages m
                INNER JOIN (
                    SELECT peer, MAX(ts) AS max_ts
                    FROM messages
                    GROUP BY peer COLLATE NOCASE
                ) t ON m.peer = t.peer AND m.ts = t.max_ts
                ORDER BY m.ts DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_conversation(self, peer: str) -> None:
        peer = peer.strip().upper()
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE peer = ? COLLATE NOCASE", (peer,)
            )
            self._conn.commit()

    def clear_conversation(self, peer: str) -> None:
        """Same as delete for message history (alias)."""
        self.delete_conversation(peer)

    @staticmethod
    def _row_message(r: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=r["id"],
            peer=r["peer"],
            direction=r["direction"],
            body=r["body"],
            msg_id=r["msg_id"] or "",
            status=r["status"],
            ts=r["ts"],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
