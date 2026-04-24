import asyncio
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from claude_brain.db import (connect, insert_entry, update_entry, upsert_embedding,
                      supersede, create_edge, delete_edge, query_edges,
                      traverse, get_entry, list_recent, hybrid_search)
from claude_brain.embeddings import embed

DB_PATH = Path(os.path.expanduser(os.environ.get("CLAUDE_BRAIN_DB", "./claude_brain.db")))

mcp = FastMCP("claude_brain")

# Ensure the DB and schema exist at import time so the file is created even
# before the first tool call (avoids confusion when the server starts cold).
_startup_con = connect(DB_PATH)
_startup_con.close()


def _get_con():
    return connect(DB_PATH)


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if "body" in d:
        d["snippet"] = (d["body"] or "")[:200]
    return d


# ---------- tools ----------

@mcp.tool()
async def record_decision(
    title: str,
    rationale: str,
    alternatives: str = "",
    tags: str = "",
    keywords: str = "",
    supersedes: int = 0,
) -> dict:
    """Record an architectural or technical decision with its rationale."""
    try:
        con = _get_con()
        embedding = await embed(f"{title} {rationale} {keywords}")
        entry_id = insert_entry(
            con, type="decision", title=title, body=rationale,
            alternatives=alternatives or None,
            tags=tags or None, keywords=keywords or None,
        )
        upsert_embedding(con, entry_id, embedding)
        if supersedes:
            target = get_entry(con, supersedes)
            if target is None:
                con.close()
                return {"ok": False, "error": f"Entry {supersedes} not found"}
            supersede(con, supersedes, entry_id)
            create_edge(con, entry_id, supersedes, "replaces")
        con.commit()
        con.close()
        suffix = f" (supersedes #{supersedes})" if supersedes else ""
        return {"id": entry_id, "ok": True, "recorded": f"decision #{entry_id}: {title}{suffix}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def record_fact(
    title: str,
    content: str,
    tags: str = "",
    keywords: str = "",
) -> dict:
    """Record a load-bearing fact about the system."""
    try:
        con = _get_con()
        embedding = await embed(f"{title} {content} {keywords}")
        entry_id = insert_entry(
            con, type="fact", title=title, body=content,
            tags=tags or None, keywords=keywords or None,
        )
        upsert_embedding(con, entry_id, embedding)
        con.commit()
        con.close()
        return {"id": entry_id, "ok": True, "recorded": f"fact #{entry_id}: {title}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def record_todo(
    title: str,
    detail: str = "",
    tags: str = "",
) -> dict:
    """Record a follow-up task."""
    try:
        con = _get_con()
        body = detail or title
        embedding = await embed(f"{title} {body}")
        entry_id = insert_entry(
            con, type="todo", title=title, body=body,
            tags=tags or None,
        )
        upsert_embedding(con, entry_id, embedding)
        con.commit()
        con.close()
        return {"id": entry_id, "ok": True, "recorded": f"todo #{entry_id}: {title}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def record_note(
    title: str,
    content: str,
    tags: str = "",
    keywords: str = "",
) -> dict:
    """Record a free-form note from a conversation — context, explanations, or summaries
    that don't fit as a decision, fact, or todo."""
    try:
        con = _get_con()
        embedding = await embed(f"{title} {content} {keywords}")
        entry_id = insert_entry(
            con, type="note", title=title, body=content,
            tags=tags or None, keywords=keywords or None,
        )
        upsert_embedding(con, entry_id, embedding)
        con.commit()
        con.close()
        return {"id": entry_id, "ok": True, "recorded": f"note #{entry_id}: {title}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def record_specs(
    title: str,
    description: str,
    dependencies: str = "",
    tags: str = "",
    keywords: str = "",
    supersedes: int = 0,
) -> dict:
    """Record a feature-level specification: what it does, how it works, and what it depends on.

    Call this whenever a new feature is agreed upon or an existing feature's behaviour changes.
    Superseded specs are kept for history but hidden from normal searches.
    Use `supersedes` to link to the old spec when a feature changes.
    Store dependencies (other features/components this relies on) in the `dependencies` field.
    """
    try:
        con = _get_con()
        embedding = await embed(f"{title} {description} {keywords}")
        entry_id = insert_entry(
            con, type="spec", title=title, body=description,
            alternatives=dependencies or None,
            tags=tags or None, keywords=keywords or None,
        )
        upsert_embedding(con, entry_id, embedding)
        if supersedes:
            target = get_entry(con, supersedes)
            if target is None:
                con.close()
                return {"ok": False, "error": f"Entry {supersedes} not found"}
            supersede(con, supersedes, entry_id)
            create_edge(con, entry_id, supersedes, "replaces")
        con.commit()
        con.close()
        suffix = f" (supersedes #{supersedes})" if supersedes else ""
        return {"id": entry_id, "ok": True, "recorded": f"spec #{entry_id}: {title}{suffix}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def update_todo(
    entry_id: int,
    status: str,
) -> dict:
    """Update a todo's status: active, done, or cancelled."""
    try:
        if status not in ("active", "done", "cancelled"):
            return {"ok": False, "error": "status must be active, done, or cancelled"}
        con = _get_con()
        entry = get_entry(con, entry_id)
        if entry is None:
            con.close()
            return {"ok": False, "error": f"Entry {entry_id} not found"}
        if entry["type"] != "todo":
            con.close()
            return {"ok": False, "error": f"Entry {entry_id} is not a todo"}
        update_entry(con, entry_id, status=status)
        con.commit()
        con.close()
        return {"id": entry_id, "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def link_entries(
    from_id: int,
    to_id: int,
    kind: str,
    note: str = "",
) -> dict:
    """Create a typed edge between two entries."""
    valid_kinds = {"depends_on", "blocks", "relates_to", "uses",
                   "replaces", "implements", "contradicts"}
    if kind not in valid_kinds:
        return {"ok": False, "error": f"kind must be one of {sorted(valid_kinds)}"}
    try:
        con = _get_con()
        if get_entry(con, from_id) is None:
            con.close()
            return {"ok": False, "error": f"Entry {from_id} not found"}
        if get_entry(con, to_id) is None:
            con.close()
            return {"ok": False, "error": f"Entry {to_id} not found"}
        edge_id = create_edge(con, from_id, to_id, kind, note or None)
        con.commit()
        con.close()
        return {"edge_id": edge_id, "ok": True}
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return {"ok": False, "error": "Edge already exists"}
        return {"ok": False, "error": str(e)}


@mcp.tool()
async def search_memory(
    query: str,
    type: str = "",
    limit: int = 10,
    include_superseded: bool = False,
    include_related: bool = False,
) -> list:
    """Hybrid FTS + vector search over recorded entries."""
    try:
        con = _get_con()
        embedding = await embed(query)
        rows = hybrid_search(
            con, query, embedding,
            type_filter=type or None,
            limit=limit,
            include_superseded=include_superseded,
        )
        results = []
        for row in rows:
            entry = _row_to_dict(row)
            if include_related:
                edges = query_edges(con, row["id"], direction="both")
                related = []
                for edge in edges:
                    is_out = edge["from_id"] == row["id"]
                    neighbour_id = edge["to_id"] if is_out else edge["from_id"]
                    neighbour = get_entry(con, neighbour_id)
                    if neighbour:
                        related.append({
                            "id": neighbour_id,
                            "title": neighbour["title"],
                            "kind": edge["kind"],
                            "direction": "out" if is_out else "in",
                        })
                entry["related"] = related
            results.append(entry)
        con.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def list_recent_entries(
    type: str = "",
    status: str = "",
    limit: int = 10,
) -> list:
    """List the most recently created entries, newest first.

    Use type='todo' with status='active' for open todos, status='done' for completed ones.
    """
    try:
        con = _get_con()
        rows = list_recent(con, type_filter=type or None, status_filter=status or None, limit=limit)
        result = [_row_to_dict(r) for r in rows]
        con.close()
        return result
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def explore(
    entry_id: int,
    kinds: str = "",
    max_depth: int = 2,
) -> dict:
    """Graph traversal from an entry — returns everything reachable up to max_depth hops."""
    max_depth = min(max_depth, 4)
    try:
        con = _get_con()
        root = get_entry(con, entry_id)
        if root is None:
            con.close()
            return {"error": f"Entry {entry_id} not found"}
        kind_filter = [k.strip() for k in kinds.split(",") if k.strip()] or None
        distances = traverse(con, entry_id, kinds=kind_filter, max_depth=max_depth)

        by_depth: dict[int, list] = {}
        for eid, dist in distances.items():
            if eid == entry_id:
                continue
            by_depth.setdefault(dist, [])
            entry = get_entry(con, eid)
            if entry is None:
                continue
            edges_to_entry = [
                e for e in query_edges(con, eid, direction="both")
                if e["from_id"] in distances or e["to_id"] in distances
            ]
            edge_kinds = list({e["kind"] for e in edges_to_entry})
            by_depth[dist].append({
                "id": eid,
                "type": entry["type"],
                "title": entry["title"],
                "status": entry["status"],
                "via_kinds": edge_kinds,
            })

        con.close()
        return {
            "root": _row_to_dict(root),
            "depths": {str(d): entries for d, entries in sorted(by_depth.items())},
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
