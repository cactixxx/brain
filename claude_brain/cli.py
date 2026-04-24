import json
import os
import sys
from pathlib import Path

import click

from claude_brain.db import (connect, get_entry, list_recent, query_edges, traverse,
                      create_edge, delete_edge, hybrid_search, search_fts)
from claude_brain.embeddings import embed_sync


def _resolve_db_path() -> Path:
    if "CLAUDE_BRAIN_DB" in os.environ:
        return Path(os.environ["CLAUDE_BRAIN_DB"])

    # Search cwd and parents for .mcp.json
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".mcp.json"
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text())
                db = data["mcpServers"]["claude_brain"]["env"]["CLAUDE_BRAIN_DB"]
                return Path(db)
            except (KeyError, json.JSONDecodeError):
                break

    # Fall back to prompting the user
    click.echo(
        "CLAUDE_BRAIN_DB is not set and no .mcp.json was found in the current "
        "directory or its parents.",
        err=True,
    )
    project_dir = click.prompt("Enter the path to your project directory", err=True)
    mcp_path = Path(project_dir).expanduser() / ".mcp.json"
    if not mcp_path.exists():
        click.echo(f"No .mcp.json found in {mcp_path.parent}", err=True)
        sys.exit(1)
    try:
        data = json.loads(mcp_path.read_text())
        db = data["mcpServers"]["claude_brain"]["env"]["CLAUDE_BRAIN_DB"]
        return Path(db)
    except (KeyError, json.JSONDecodeError, OSError) as exc:
        click.echo(f"Could not read CLAUDE_BRAIN_DB from {mcp_path}: {exc}", err=True)
        sys.exit(1)


def _con():
    return connect(_resolve_db_path())


def _fmt_ts(ts: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _status_style(status: str) -> str:
    colors = {"active": "green", "done": "cyan", "superseded": "yellow", "cancelled": "red"}
    return click.style(status, fg=colors.get(status, "white"))


@click.group()
def cli():
    """claude_brain — local project memory."""


# ---------- list ----------

@cli.command("list")
@click.option("--type", "type_filter", type=click.Choice(["decision", "fact", "todo"]))
@click.option("--limit", default=10, show_default=True)
def list_cmd(type_filter, limit):
    """List recent entries."""
    con = _con()
    rows = list_recent(con, type_filter=type_filter, limit=limit)
    con.close()
    if not rows:
        click.echo("No entries found.")
        return
    click.echo(f"{'ID':>4}  {'TYPE':10}  {'STATUS':12}  {'DATE':10}  TITLE")
    click.echo("-" * 72)
    for r in rows:
        click.echo(f"{r['id']:>4}  {r['type']:10}  {_status_style(r['status']):12}  "
                   f"{_fmt_ts(r['created_at'])}  {r['title']}")


# ---------- show ----------

@cli.command()
@click.argument("entry_id", type=int)
def show(entry_id):
    """Show full detail for an entry including edges."""
    con = _con()
    row = get_entry(con, entry_id)
    if row is None:
        click.echo(f"Entry {entry_id} not found.", err=True)
        sys.exit(1)

    click.echo(f"\n[{row['id']}] {row['title']}")
    click.echo(f"  Type    : {row['type']}")
    click.echo(f"  Status  : {_status_style(row['status'])}")
    click.echo(f"  Created : {_fmt_ts(row['created_at'])}")
    if row["tags"]:
        click.echo(f"  Tags    : {row['tags']}")
    if row["keywords"]:
        click.echo(f"  Keywords: {row['keywords']}")
    if row["alternatives"]:
        click.echo(f"\nAlternatives considered:\n  {row['alternatives']}")
    click.echo(f"\nBody:\n  {row['body']}")

    edges = query_edges(con, entry_id, direction="both")
    if edges:
        click.echo("\nEdges:")
        for e in edges:
            is_out = e["from_id"] == entry_id
            neighbour_id = e["to_id"] if is_out else e["from_id"]
            neighbour = get_entry(con, neighbour_id)
            neighbour_title = neighbour["title"] if neighbour else f"#{neighbour_id}"
            arrow = "→" if is_out else "←"
            note = f"  ({e['note']})" if e["note"] else ""
            click.echo(f"  [{e['id']}] {arrow} {e['kind']:14} #{neighbour_id} {neighbour_title}{note}")
    con.close()


# ---------- search ----------

@cli.command()
@click.argument("query")
@click.option("--type", "type_filter", type=click.Choice(["decision", "fact", "todo"]))
@click.option("--limit", default=10, show_default=True)
def search(query, type_filter, limit):
    """Hybrid search (FTS + vector)."""
    try:
        embedding = embed_sync(query)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    con = _con()
    rows = hybrid_search(con, query, embedding, type_filter=type_filter, limit=limit)
    con.close()
    if not rows:
        click.echo("No results.")
        return
    for r in rows:
        snippet = (r["body"] or "")[:120].replace("\n", " ")
        click.echo(f"\n[{r['id']}] ({r['type']}) {r['title']}")
        click.echo(f"  {snippet}")


# ---------- link / unlink ----------

@cli.command()
@click.argument("from_id", type=int)
@click.argument("to_id", type=int)
@click.argument("kind", type=click.Choice([
    "depends_on", "blocks", "relates_to", "uses",
    "replaces", "implements", "contradicts"]))
@click.option("--note", default="")
def link(from_id, to_id, kind, note):
    """Create an edge between two entries."""
    con = _con()
    try:
        edge_id = create_edge(con, from_id, to_id, kind, note or None)
        con.commit()
        click.echo(f"Edge {edge_id} created: #{from_id} → {kind} → #{to_id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        con.close()


@cli.command()
@click.argument("edge_id", type=int)
def unlink(edge_id):
    """Delete an edge by its id."""
    con = _con()
    delete_edge(con, edge_id)
    con.commit()
    con.close()
    click.echo(f"Edge {edge_id} deleted.")


# ---------- graph ----------

@cli.command()
@click.argument("entry_id", type=int)
@click.option("--depth", default=2, show_default=True)
@click.option("--kinds", default="")
def graph(entry_id, depth, kinds):
    """Print a text tree of entries reachable from entry_id."""
    con = _con()
    root = get_entry(con, entry_id)
    if root is None:
        click.echo(f"Entry {entry_id} not found.", err=True)
        sys.exit(1)
    kind_filter = [k.strip() for k in kinds.split(",") if k.strip()] or None
    distances = traverse(con, entry_id, kinds=kind_filter, max_depth=depth)

    click.echo(f"[{root['id']}] {root['title']} ({root['type']})")
    by_depth: dict[int, list] = {}
    for eid, dist in distances.items():
        if eid == entry_id:
            continue
        by_depth.setdefault(dist, []).append(eid)

    for d in sorted(by_depth):
        indent = "  " * d
        for eid in by_depth[d]:
            e = get_entry(con, eid)
            if e is None:
                continue
            edges = [eg for eg in query_edges(con, eid, direction="both")
                     if eg["from_id"] in distances and eg["to_id"] in distances]
            kinds_used = ", ".join({eg["kind"] for eg in edges})
            click.echo(f"{indent}└─ [{eid}] {e['title']} ({e['type']}) via {kinds_used}")
    con.close()


# ---------- stats ----------

@cli.command()
def stats():
    """Show database statistics."""
    con = _con()
    type_counts = {r[0]: r[1] for r in con.execute(
        "SELECT type, COUNT(*) FROM entries GROUP BY type").fetchall()}
    status_counts = {r[0]: r[1] for r in con.execute(
        "SELECT status, COUNT(*) FROM entries GROUP BY status").fetchall()}
    total_entries = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    total_edges = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    edge_kinds = {r[0]: r[1] for r in con.execute(
        "SELECT kind, COUNT(*) FROM edges GROUP BY kind").fetchall()}
    total_vecs = con.execute("SELECT COUNT(*) FROM entries_vec").fetchone()[0]
    con.close()

    db_path = _resolve_db_path()
    db_size = db_path.stat().st_size if db_path.exists() else 0

    click.echo(f"DB path  : {db_path}  ({db_size // 1024} KB)")
    click.echo(f"Entries  : {total_entries}  (embeddings: {total_vecs})")
    click.echo(f"  by type  : {type_counts}")
    click.echo(f"  by status: {status_counts}")
    click.echo(f"Edges    : {total_edges}")
    if edge_kinds:
        click.echo(f"  by kind  : {edge_kinds}")


# ---------- export ----------

@cli.command()
@click.option("--format", "fmt", type=click.Choice(["markdown", "json", "dot"]),
              default="markdown", show_default=True)
def export(fmt):
    """Export all entries."""
    con = _con()
    all_entries = list_recent(con, limit=10_000)
    all_edges = con.execute("SELECT * FROM edges").fetchall()

    if fmt == "json":
        entries_list = [dict(e) for e in all_entries]
        edges_list = [dict(e) for e in all_edges]
        click.echo(json.dumps({"entries": entries_list, "edges": edges_list}, indent=2))

    elif fmt == "dot":
        lines = ["digraph claude_brain {", '  node [shape=box fontname="Helvetica"]']
        for e in all_entries:
            label = e["title"].replace('"', '\\"')
            color = {"decision": "lightblue", "fact": "lightyellow", "todo": "lightgreen"}.get(e["type"], "white")
            lines.append(f'  {e["id"]} [label="{label}" style=filled fillcolor={color}]')
        for edge in all_edges:
            note = f' [label="{edge["kind"]}"]'
            lines.append(f'  {edge["from_id"]} -> {edge["to_id"]}{note}')
        lines.append("}")
        click.echo("\n".join(lines))

    else:  # markdown ADR-style
        decisions = [e for e in all_entries if e["type"] == "decision"]
        for d in decisions:
            click.echo(f"# {d['id']}. {d['title']}\n")
            click.echo(f"**Date:** {_fmt_ts(d['created_at'])}  ")
            click.echo(f"**Status:** {d['status']}\n")
            click.echo(f"## Context\n\n{d['body']}\n")
            if d["alternatives"]:
                click.echo(f"## Alternatives Considered\n\n{d['alternatives']}\n")
            edges = query_edges(con, d["id"], direction="both")
            if edges:
                click.echo("## Related\n")
                for edge in edges:
                    is_out = edge["from_id"] == d["id"]
                    neighbour_id = edge["to_id"] if is_out else edge["from_id"]
                    nb = get_entry(con, neighbour_id)
                    nb_title = nb["title"] if nb else f"#{neighbour_id}"
                    arrow = "→" if is_out else "←"
                    click.echo(f"- {arrow} `{edge['kind']}` #{neighbour_id} {nb_title}")
                click.echo()
            click.echo("---\n")
    con.close()


if __name__ == "__main__":
    cli()
