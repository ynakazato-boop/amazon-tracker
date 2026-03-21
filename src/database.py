import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "rankings.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rankings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                asin       TEXT NOT NULL,
                keyword    TEXT NOT NULL,
                rank       INTEGER,
                page       INTEGER,
                checked_at TEXT NOT NULL,
                note       TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rankings_asin_kw
            ON rankings (asin, keyword, checked_at)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                total      INTEGER DEFAULT 0,
                success    INTEGER DEFAULT 0,
                failed     INTEGER DEFAULT 0,
                status     TEXT DEFAULT 'running'
            )
        """)
        conn.commit()


def insert_ranking(asin: str, keyword: str, rank: int | None, page: int | None, note: str = ""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO rankings (asin, keyword, rank, page, checked_at, note) VALUES (?, ?, ?, ?, ?, ?)",
            (asin, keyword, rank, page, datetime.now().isoformat(timespec="seconds"), note),
        )
        conn.commit()


def get_latest_rankings() -> list[dict]:
    """各 ASIN×KW の最新順位を返す"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT r.asin, r.keyword, r.rank, r.page, r.checked_at, r.note
            FROM rankings r
            INNER JOIN (
                SELECT asin, keyword, MAX(checked_at) AS latest
                FROM rankings
                GROUP BY asin, keyword
            ) sub ON r.asin = sub.asin AND r.keyword = sub.keyword AND r.checked_at = sub.latest
            ORDER BY r.asin, r.keyword
        """).fetchall()
    return [dict(r) for r in rows]


def get_ranking_history(asin: str, keyword: str, days: int = 30) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT rank, page, checked_at
            FROM rankings
            WHERE asin = ? AND keyword = ?
              AND checked_at >= datetime('now', ? || ' days')
            ORDER BY checked_at
        """, (asin, keyword, f"-{days}")).fetchall()
    return [dict(r) for r in rows]


def get_all_asin_kw_pairs() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT asin, keyword FROM rankings ORDER BY asin, keyword
        """).fetchall()
    return [dict(r) for r in rows]


def start_run_log() -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO run_logs (started_at) VALUES (?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return cur.lastrowid


def finish_run_log(log_id: int, total: int, success: int, failed: int):
    status = "success" if failed == 0 else "partial" if success > 0 else "failed"
    with get_connection() as conn:
        conn.execute(
            """UPDATE run_logs
               SET finished_at=?, total=?, success=?, failed=?, status=?
               WHERE id=?""",
            (datetime.now().isoformat(timespec="seconds"), total, success, failed, status, log_id),
        )
        conn.commit()


def get_recent_run_logs(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM run_logs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
