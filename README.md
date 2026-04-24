# claude_brain

A local MCP server that gives Claude Code persistent memory for a project.
Stores decisions, facts, and todos in SQLite (FTS5 + vector search via sqlite-vec),
with typed graph edges between entries.

## The embedding model

claude_brain uses **[nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF)**
via **[llama.cpp](https://github.com/ggml-org/llama.cpp)** to generate vector embeddings for semantic search.

- **Small** — the model is ~270 MB on disk (F16). 137M parameters — tiny compared to any chat model.
- **GPU-aware** — the install script detects your GPU and builds llama.cpp accordingly:
  NVIDIA → `-DGGML_CUDA=ON`, AMD → `-DGGML_HIPBLAS=ON`, no GPU → `-DGGML_NATIVE=ON` (CPU-optimised).
- **Not a chat model** — produces only numeric vectors. No text generation, no prompt-injection surface.
- **Runs as a local service** — llama-server listens on `localhost:8080` and claude_brain
  calls it over HTTP (`/v1/embeddings`). Nothing leaves the machine.

## Quick install

Installs all dependencies (Python, Ollama, sqlite3), pulls the embedding model,
and sets Ollama to start on boot:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cactixxx/claude_brain/master/install.sh)
```

Installs to `~/.claude_brain` by default. Override with `CLAUDE_BRAIN_INSTALL_DIR=/custom/path`.

## Manual install

Requirements: Python 3.11+, cmake 3.14+, build-essential, and a running `llama-server` with `nomic-embed-text-v1.5.f16.gguf` on port 8080.

```bash
git clone https://github.com/cactixxx/claude_brain ~/.claude_brain
cd ~/.claude_brain
python3 -m venv .venv
.venv/bin/pip install -e .
```

Confirm everything works:

```bash
.venv/bin/python3 -c "import mcp, httpx, sqlite_vec, click; print('ok')"
```

## Register in a project

The project directory where you start Claude doesn't have to contain all the
files you work on. Claude Code can read and edit files anywhere on the
filesystem — the start directory just determines which `.mcp.json` and
`CLAUDE.md` are loaded. For example, you might start Claude in
`/project/scripts` (where your config lives) but spend the session editing
files under `/build` and `/usr/src/myapp`.

**Option A — copy the example config:**

```bash
cp ~/.claude_brain/.mcp.json.example /your/project/.mcp.json
cp ~/.claude_brain/CLAUDE.md /your/project/CLAUDE.md
# edit .mcp.json: update the command path and CLAUDE_BRAIN_DB path
```

**Option B — use `claude mcp add`:**

This registers the claude_brain server as a project-scoped MCP server — one global entry for the project on this server, running in MCP mode.

```bash
cd /your/project
claude mcp add claude_brain \
  ~/.claude_brain/.venv/bin/python -- -m claude_brain.server \
  --env CLAUDE_BRAIN_DB=~/.claude_brain/claude_brain.db
```

## Verify it works

```bash
cd /your/project
source ~/.bashrc
CLAUDE_BRAIN_DB=./claude_brain.db claude_brain list       # empty at first
# start Claude Code — it will call record_* tools automatically
claude_brain stats
claude_brain list
claude_brain show 1
```

## Disabling the MCP temporarily

Sometimes you want Claude to work on something — a spike, a throwaway experiment,
a sensitive refactor — without recording anything to the brain. There are two ways:

**Per-session (recommended):** Run `/mcp` inside Claude Code to see all registered
MCP servers. Select `claude_brain` and toggle it off. It stays off for that session
only and comes back automatically next time.

**Remove from project config:** If you want it gone until you explicitly re-add it:

```bash
claude mcp remove claude_brain
```

Re-add it when you are ready to resume recording:

```bash
claude mcp add claude_brain \
  ~/.claude_brain/.venv/bin/python -- -m claude_brain.server \
  --env CLAUDE_BRAIN_DB=~/.claude_brain/claude_brain.db
```

**In-conversation:** You can also just tell Claude "don't record anything from this
conversation" and it will respect that without needing to touch the config.

## CLI reference

```
claude_brain list [--type decision|fact|todo|note] [--limit N]
claude_brain show ID
claude_brain search QUERY [--type X] [--limit N]
claude_brain link FROM_ID TO_ID KIND [--note TEXT]
claude_brain unlink EDGE_ID
claude_brain graph ID [--depth N] [--kinds KIND1,KIND2]
claude_brain stats
claude_brain export [--format markdown|json|dot]
```

## MCP tools

These are the functions Claude calls during a conversation. **You never need to invoke them yourself — Claude decides when to fire them based on what's being discussed.** You can also trigger any of them explicitly by just saying so in plain English.

| Tool | What it stores | When Claude calls it automatically | Example prompts to trigger it yourself |
|------|---------------|-----------------------------------|----------------------------------------|
| `record_decision` | An architectural or technical choice, its rationale, and what was considered and rejected | When a design or technology choice is finalised that you would want to find again later | _"Record that as a decision"_ · _"Log why we went with X"_ · **`decision: <text>`** |
| `record_fact` | A load-bearing fact: API endpoints, invariants, conventions, where things live, non-obvious config | When something true about the system is established or discovered | _"Record that as a fact"_ · _"Remember where X lives"_ · **`fact: <text>`** |
| `record_note` | Free-form context from a conversation — explanations, overviews, background that doesn't fit elsewhere | When a conversation surfaces meaningful project context not derivable from the code or git history | _"Save that"_ · _"Record this as a note"_ · **`note: <text>`** |
| `record_todo` | A follow-up task that was identified but not done right now | When work is deferred — "we should do X later" | _"Add a todo for that"_ · _"Remember to do X"_ · **`todo: <text>`** |
| `record_specs` | A feature-level specification: what it does, how it works, what it depends on — versioned via supersedes chain | When a new feature is agreed upon or an existing feature's behaviour changes | _"Record the spec for X"_ · _"Add this as a spec"_ · **`spec: <text>`** |
| `update_todo` | Changes a todo's status to `active`, `done`, or `cancelled` | When a previously recorded todo is completed or dropped | _"Mark that todo as done"_ · _"Cancel todo 3"_ |
| `link_entries` | A typed edge between two existing entries | After recording an entry, if it clearly connects to an earlier one | _"Link those two entries"_ · _"Connect that decision to the todo"_ |
| `search_memory` | _(read-only)_ Hybrid full-text + vector search across all entries | Before designing something new, or when answering "what did we decide / why / how does X work" | _"What do we know about X?"_ · _"What did we decide about Y?"_ · _"Search memory for Z"_ |
| `list_recent_entries` | _(read-only)_ The most recently created entries, with optional type and status filters | To get a quick overview of what has been recorded, or to check open/completed todos | _"What have we recorded lately?"_ · _"Show recent entries"_ · **`list todo`** · **`list done`** |
| `explore` | _(read-only)_ Graph traversal outward from one entry up to N hops | When an impact or blast-radius question requires following the chain of connections from a single entry | _"What's connected to entry 5?"_ · _"Show everything related to that decision"_ |

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

This project uses a memory MCP server called `claude_brain`. Use its tools
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
- `record_note` in two situations:
  1. **User-triggered**: the user says "note", "record this as a note",
     "save that", or similar — record immediately without asking.
  2. **Conservative auto-record**: a conversation surfaces meaningful context
     about the project (its purpose, structure, history, how something works)
     that isn't derivable from the code or git history. Summarise it; don't
     transcribe the raw exchange. Skip ephemeral or obvious content.

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
