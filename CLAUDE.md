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
