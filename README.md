# project-brain

A local MCP server that gives Claude Code persistent memory for a project.
Stores decisions, facts, and todos in SQLite (FTS5 + vector search via sqlite-vec),
with typed graph edges between entries.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with `nomic-embed-text` pulled

## Install

```bash
git clone <repo> ~/brain
cd ~/brain
python3 -m venv .venv
.venv/bin/pip install -e .
```

Verify Ollama and the model:

```bash
ollama list          # should show nomic-embed-text
ollama serve &       # if not already running
```

Confirm everything works:

```bash
.venv/bin/python3 -c "import mcp, httpx, sqlite_vec, click; print('ok')"
```

## Register in a project

**Option A — copy the example config:**

```bash
cp ~/brain/.mcp.json.example /your/project/.mcp.json
# edit .mcp.json: update the command path and BRAIN_DB path
```

**Option B — use `claude mcp add`:**

```bash
cd /your/project
claude mcp add project-brain \
  /root/brain/.venv/bin/python -- -m brain.server
```

Then set `BRAIN_DB` in the server env or export it in your shell.

## Verify it works

```bash
cd /your/project
BRAIN_DB=./brain.db brain list       # empty at first
# start Claude Code — it will call record_* tools automatically
brain stats
brain list
brain show 1
```

## CLI reference

```
brain list [--type decision|fact|todo] [--limit N]
brain show ID
brain search QUERY [--type X] [--limit N]
brain link FROM_ID TO_ID KIND [--note TEXT]
brain unlink EDGE_ID
brain graph ID [--depth N] [--kinds KIND1,KIND2]
brain stats
brain export [--format markdown|json|dot]
```

## Edge kinds

| Kind | When to use |
|------|-------------|
| `depends_on` | This entry relies on the other being true/chosen |
| `blocks` | This todo prevents that decision/todo from proceeding |
| `relates_to` | Thematic connection, no strict dependency |
| `uses` | This component/decision uses that library/service/pattern |
| `replaces` | This supersedes that (also set automatically via `supersedes`) |
| `implements` | This fact/todo realizes that decision |
| `contradicts` | These two entries are in tension |

## CLAUDE.md block

Paste this into any project's `CLAUDE.md` to enable automatic memory use:

```markdown
## Project memory

This project uses a memory MCP server called `project-brain`. Use its tools
during our conversations to record and recall durable knowledge, and link
related entries so the graph stays connected.

### When to record (without asking)

- `record_decision` whenever we finalize an architectural or technical choice
  we'd want to find again later. Always include the rationale and what was
  rejected (`alternatives`). Populate `keywords` with 3–5 synonyms or
  alternative phrasings someone might search for months later.
- `record_fact` for load-bearing facts about this system: API endpoints,
  invariants, conventions, where things live, non-obvious configuration.
- `record_todo` when we identify follow-up work but don't do it now.

### When to link (without asking)

After recording an entry, consider whether it connects to an existing one.
If it does, call `link_entries` with the appropriate kind:

- `depends_on` — this entry relies on that one being true/chosen
- `blocks` — this todo prevents that decision/todo from proceeding
- `relates_to` — thematic connection, no strict dependency
- `uses` — this component/decision uses that library/service/pattern
- `replaces` — this supersedes that (also set automatically via `supersedes`)
- `implements` — this fact/todo realizes that decision
- `contradicts` — these two entries are in tension; surface that explicitly

Don't over-link. Aim for the one or two strongest connections, not every
plausible one. A dense graph is as unhelpful as no graph.

Before creating an edge, run a quick `search_memory` to find the likely
target entry rather than guessing its id.

### When to search

- Before designing a new component, call `search_memory` with
  `include_related=true` for the topic, so past decisions and their
  connected context come back together.
- When I ask "what did we decide", "why did we", "how does X work", or
  "what's affected by Y" — search before answering. For impact/blast-radius
  questions, follow up with `explore` on the most relevant hit.

### Style

- Titles: declarative and specific ("Use Redis for sessions",
  not "Caching decision").
- Keep `body` / `rationale` to ~3–5 sentences. This is a decision log,
  not documentation.
- Use consistent tags within a project. Check `list_recent` occasionally
  to see what tags are in use.

### When a decision changes

Don't edit the old entry. Call `record_decision` for the new one and set
`supersedes` to the old entry's id — this marks the old one and creates
a `replaces` edge automatically. This preserves history and traversability.
```
