import sqlite3
import time
from pathlib import Path
from collections import deque

import sqlite_vec

SCHEMA_SQL = Path(__file__).parent / "schema.sql"


def connect(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    _init_schema(con)
    return con


def _init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_SQL.read_text())
    con.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries_vec
        USING vec0(id INTEGER PRIMARY KEY, embedding FLOAT[768])
    """)
    con.commit()


# ---------- writes ----------

def insert_entry(con: sqlite3.Connection, *, type: str, title: str, body: str,
                 alternatives: str | None = None, tags: str | None = None,
                 keywords: str | None = None, status: str = "active") -> int:
    now = int(time.time())
    cur = con.execute(
        """INSERT INTO entries(type, title, body, alternatives, tags, keywords,
                               status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (type, title, body, alternatives, tags, keywords, status, now, now),
    )
    return cur.lastrowid


def update_entry(con: sqlite3.Connection, entry_id: int, **fields) -> None:
    fields["updated_at"] = int(time.time())
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"UPDATE entries SET {set_clause} WHERE id = ?",
                (*fields.values(), entry_id))


def upsert_embedding(con: sqlite3.Connection, entry_id: int,
                     embedding: list[float]) -> None:
    import struct
    blob = struct.pack(f"{len(embedding)}f", *embedding)
    con.execute(
        "INSERT OR REPLACE INTO entries_vec(id, embedding) VALUES (?, ?)",
        (entry_id, blob),
    )


def supersede(con: sqlite3.Connection, old_id: int, new_id: int) -> None:
    now = int(time.time())
    con.execute(
        "UPDATE entries SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
        (new_id, now, old_id),
    )


def create_edge(con: sqlite3.Connection, from_id: int, to_id: int,
                kind: str, note: str | None = None) -> int:
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO edges(from_id, to_id, kind, note, created_at) VALUES (?,?,?,?,?)",
        (from_id, to_id, kind, note, now),
    )
    return cur.lastrowid


def delete_edge(con: sqlite3.Connection, edge_id: int) -> None:
    con.execute("DELETE FROM edges WHERE id = ?", (edge_id,))


# ---------- reads ----------

def get_entry(con: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM entries WHERE id = ?",
                       (entry_id,)).fetchone()


def list_recent(con: sqlite3.Connection, type_filter: str | None = None,
                limit: int = 20) -> list[sqlite3.Row]:
    if type_filter:
        return con.execute(
            "SELECT * FROM entries WHERE type=? ORDER BY created_at DESC LIMIT ?",
            (type_filter, limit),
        ).fetchall()
    return con.execute(
        "SELECT * FROM entries ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def query_edges(con: sqlite3.Connection, entry_id: int,
                direction: str = "both", kind: str | None = None
                ) -> list[sqlite3.Row]:
    filters, params = [], []
    if direction in ("out", "both"):
        q = "SELECT * FROM edges WHERE from_id = ?"
        p = [entry_id]
        if kind:
            q += " AND kind = ?"; p.append(kind)
        filters.append((q, p))
    if direction in ("in", "both"):
        q = "SELECT * FROM edges WHERE to_id = ?"
        p = [entry_id]
        if kind:
            q += " AND kind = ?"; p.append(kind)
        filters.append((q, p))
    rows = []
    for q, p in filters:
        rows.extend(con.execute(q, p).fetchall())
    return rows


def traverse(con: sqlite3.Connection, entry_id: int,
             kinds: list[str] | None = None, max_depth: int = 2
             ) -> dict[int, int]:
    """BFS from entry_id. Returns {id: shortest_distance}."""
    visited = {entry_id: 0}
    queue = deque([(entry_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        edges = query_edges(con, current, direction="both")
        for edge in edges:
            if kinds and edge["kind"] not in kinds:
                continue
            neighbour = edge["to_id"] if edge["from_id"] == current else edge["from_id"]
            if neighbour not in visited:
                visited[neighbour] = depth + 1
                queue.append((neighbour, depth + 1))
    return visited


# ---------- search ----------

def search_fts(con: sqlite3.Connection, query: str,
               type_filter: str | None = None, limit: int = 10
               ) -> list[tuple[int, float]]:
    sql = """
        SELECT e.id, rank
        FROM entries_fts
        JOIN entries e ON entries_fts.rowid = e.id
        WHERE entries_fts MATCH ?
    """
    params: list = [query]
    if type_filter:
        sql += " AND e.type = ?"
        params.append(type_filter)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    # FTS rank is negative (more negative = better); normalise to positive score
    return [(r["id"], -r["rank"]) for r in rows]


def search_vec(con: sqlite3.Connection, query_embedding: list[float],
               limit: int = 10) -> list[tuple[int, float]]:
    import struct
    blob = struct.pack(f"{len(query_embedding)}f", *query_embedding)
    rows = con.execute(
        "SELECT id, distance FROM entries_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (blob, limit),
    ).fetchall()
    # distance is L2; convert to a score (lower distance = higher score)
    return [(r["id"], r["distance"]) for r in rows]


def hybrid_search(con: sqlite3.Connection, query: str,
                  query_embedding: list[float],
                  type_filter: str | None = None,
                  limit: int = 10,
                  include_superseded: bool = False) -> list[sqlite3.Row]:
    K = 60  # RRF constant
    fts_hits = search_fts(con, query, type_filter=type_filter, limit=limit * 2)
    vec_hits = search_vec(con, query_embedding, limit=limit * 2)

    scores: dict[int, float] = {}
    for rank, (entry_id, _) in enumerate(fts_hits):
        scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (K + rank + 1)
    for rank, (entry_id, _) in enumerate(vec_hits):
        scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (K + rank + 1)

    ranked = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)[:limit]
    results = []
    for entry_id in ranked:
        row = get_entry(con, entry_id)
        if row is None:
            continue
        if not include_superseded and row["status"] == "superseded":
            continue
        results.append(row)
    return results
