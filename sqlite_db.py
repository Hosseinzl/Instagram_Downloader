import sqlite3
import threading
from datetime import datetime
from typing import Optional
import asyncio
from pathlib import Path

_db_path = Path(__file__).parent / "requests.db"
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def init_db(db_path: Optional[str] = None):
    """Initialize the sqlite database and create table if needed."""
    global _conn, _db_path
    if db_path:
        _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            url TEXT NOT NULL,
            tor_index INTEGER,
            status_code INTEGER
        )
        """
    )
    _conn.commit()


def _get_conn():
    global _conn
    if _conn is None:
        init_db()
    return _conn


def log_request_sync(url: str, tor_index: Optional[int], status_code: Optional[int]):
    """Synchronous write to the sqlite DB."""
    conn = _get_conn()
    ts = datetime.utcnow().isoformat()
    with _lock:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO requests (timestamp, url, tor_index, status_code) VALUES (?, ?, ?, ?)",
            (ts, url, tor_index, status_code),
        )
        conn.commit()


async def async_log_request(url: str, tor_index: Optional[int], status_code: Optional[int]):
    """Async wrapper to run the blocking sqlite write in a thread.

    Use this from async code to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, log_request_sync, url, tor_index, status_code)


# small helper to query last N rows (useful for debugging)
def recent(n: int = 20):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, timestamp, url, tor_index, status_code FROM requests ORDER BY id DESC LIMIT ?", (n,))
    return cur.fetchall()
