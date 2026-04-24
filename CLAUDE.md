## Project memory

This project uses a memory MCP server called `claude_brain`. Use its tools
during our conversations to record and recall durable knowledge, and link
related entries so the graph stays connected.

### When to record (without asking)

- `record_specs` whenever a new feature is requested or an existing feature's
  behaviour changes. Any user request to add or remove a feature is already an
  agreement — record it immediately. Include what the feature does, how it
  works, and what it depends on. When a spec changes, pass `supersedes` with
  the old spec's id so history is preserved. You may ask clarifying questions
  before implementing, but the request itself constitutes the spec.
  Do NOT call `record_specs` for bug fixes or debugging of existing behaviour.
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
- When I ask about specs ("what is the spec for X", "how does Y work"), search
  with `type=spec`. Only show active specs by default; use
  `include_superseded=true` only when I explicitly ask for spec history or
  "what changed".

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

### Keyword triggers

The user can type a bare keyword to trigger a brain action. Recognise these
patterns (case-insensitive, keyword at the start of the message):

| User types | Action |
|---|---|
| `decision: <text>` | Call `record_decision` using `<text>` as title/rationale |
| `fact: <text>` | Call `record_fact` using `<text>` as title/content |
| `note: <text>` | Call `record_note` using `<text>` as title/content |
| `todo: <text>` | Call `record_todo` using `<text>` as title |
| `spec: <text>` | Call `record_specs` using `<text>` as title/description |
| `decision` (bare) | Extract the decision from recent conversation context; ask only if ambiguous |
| `fact` (bare) | Extract the fact from recent conversation context; ask only if ambiguous |
| `note` (bare) | Extract the note from recent conversation context; ask only if ambiguous |
| `todo` (bare) | Extract the todo from recent conversation context; ask only if ambiguous |
| `spec` (bare) | Extract the spec from recent conversation context; ask only if ambiguous |
| `list todo` | Call `list_recent_entries(type="todo", status="active")` and display results |
| `list done` | Call `list_recent_entries(type="todo", status="done")` and display results |

**Deduplication**: if you already called the same `record_*` tool for the same
content earlier in this response (e.g. you auto-recorded a spec and the user
then types `spec`), reply with `<type> already recorded (#<id>)` instead of
recording again.
