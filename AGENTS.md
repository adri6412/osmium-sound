# AGENTS.md — Osmium (hifi-media-player)

Shared instructions for any agent working in this repository.

## Memory (Graphiti) — read this before acting on any project fact

A shared memory lives in Graphiti (MCP server, FalkorDB backend), reachable on
the LAN at http://10.0.1.220:8000/mcp. It is the source of truth for
release/tag state, versions, machines & IPs, decisions, prohibitions (🚨), and
what is done vs. not done.

### Before acting on a project fact
1. Search Graphiti FIRST: `search_memory_facts` with the project's `group_id`
   and `max_facts` 5–8. ALWAYS pass `group_ids` — without it you get 0 results
   even though the graph is full.
2. Do NOT pass the user's question verbatim. Rewrite it with the names, files,
   tags, numbers and technical terms the memory would contain
   (e.g. "Qt/QML spike Dell 653 MB Electron 4.9 W", not "why did we move to Qt").
3. If results are thin, run a SECOND search with different terms before
   concluding the fact is missing.
4. Check `valid_at` / `invalid_at`: a fact with `invalid_at` is superseded.

### group_id map
- `hifi-media-player` → Osmium media player (also its Windows folders) ← this repo
- `linuxos`
- `rag-main`
- `vpnzen`
- `fflauncher`

Any other project → the folder name.

### When you learn something worth keeping
Save it with `add_memory` (same `group_id`, `source: "text"`). Avoid the exact
string "-r _" in that text (it breaks Graphiti extraction — rephrase). If a
stored fact is corrected or no longer true, record the correction with a new
`add_memory` that says what no longer holds.

## Working rules
- Reply to the user in Italian (explanations too). Code, commits, comments and
  all git text in English.
- 🚨 prohibitions in memory are literal — if in doubt, respect them and ask.
- 🚨 Never push commits or tags unless explicitly told. "alpha" means the alpha
  channel only; verify the tag number against the actual tags even when stated.
- 🚨 No temp dirs: put worktrees, scripts and builds under
  `/home/coder/osmium/<work>/`, never `/tmp`. Commit WIP often.
- Keep command output filtered (`tail`, `grep`, `head`, `--tail`) — never paste
  whole build/log output back.
