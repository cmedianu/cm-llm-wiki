# Claude Conversation History Mode

*(Merged from the former `wiki-claude-history` skill.)* When the source is the user's Claude Code
history rather than documents, follow this flow instead of Steps 1 to 5 of the ingest skill. You are
extracting knowledge from past conversations (rich but messy) and compiling the signal, not
transcribing chats. Everything else (vault resolution, Page-Writing Protocol, manifest/journal in
Step 7) is unchanged.

## Data layout: scan both locations

**Source 1, `~/.claude/` (CLI sessions):**

```
~/.claude/
├── projects/-Users-name-project/       # path-derived dir name (slashes to dashes)
│   ├── <session-uuid>.jsonl            # conversation transcript (JSONL)
│   └── memory/{MEMORY.md,user_*.md,feedback_*.md,project_*.md}
├── sessions/<pid>.json                  # {pid, sessionId, cwd, startedAt, kind}
├── history.jsonl, tasks/, plans/, settings.json
```

**Source 2, `~/Library/Application Support/Claude/local-agent-mode-sessions/` (desktop app, macOS only).**
**Skip the whole source if the directory is absent:** gate every command on
`[ -d "$HOME/Library/Application Support/Claude/local-agent-mode-sessions" ]` and silently drop the
branch on non-macOS or no-desktop-app; never error. Structure is deeply nested:
`<outer-uuid>/<inner-uuid>/local_<session-uuid>.json` (session metadata) alongside
`local_<session-uuid>/audit.jsonl` (tool-call audit log) and
`local_<session-uuid>/.claude/projects/<name>/<uuid>.jsonl` (transcript, same JSONL format as CLI).
Find them with `find … -name "local_*.json" -maxdepth 4`, `-name "audit.jsonl"`, and
`-name "*.jsonl" -path "*/.claude/projects/*"`.

**Sources ranked by value:** (1) memory files, pre-distilled, already wiki-friendly, gold;
(2) conversation JSONL, rich but noisy; (3) audit logs, a tool-call record of what was actually done;
(4) session metadata, which project, when, and what CWD.

## Step H1: Survey and compute delta

Glob both locations (`~/.claude/projects/*/`, `~/.claude/projects/*/memory/*.md`,
`~/.claude/projects/*/*.jsonl`, plus the desktop `find`s above) and classify each file against
`.manifest.json` as **new** / **modified** (`size_bytes` or `mtime` differ) / **unchanged** (skip in
append mode). Report: "Found X CLI projects, Y desktop sessions. Memory: A. Conversations: B. Audit
logs: C. Delta: D new, E modified."

## Step H2: Ingest memory files first

Memory files carry `type: user|feedback|project|reference` frontmatter. `user` feeds an entity page
about the user or concept pages about their domain; `feedback` feeds skills/workflow pages; `project`
feeds an entity page for the project; `reference` feeds a reference page. Read each project's
`MEMORY.md` index first to decide which individual memory files are worth reading in full.

## Step H3: Prefilter conversation JSONL (required)

Raw `.jsonl` files are large and noisy (thinking blocks, tool_use/tool_result, progress,
file-history-snapshot). **Never read a raw `.jsonl` whole.** Run a `jq` pass first and read only its
distilled output:

```bash
jq -rc 'select(.type=="user" or .type=="assistant")
  | .message.content
  | if type=="array" then (map(select(.type=="text").text) | join("\n")) else . end' session.jsonl
```

Which project a conversation belongs to comes from its file location (the `-Users-name-project` dir
name decodes to the path); pull exact `cwd` with a separate one-line `jq` if needed. Skip subagent
conversations (under `subagents/`) unless the user asks.

## Step H3b: Parse audit logs (desktop sessions only)

Each `audit.jsonl` line is one agent action (`{type, toolName, input, output, timestamp, sessionId}`).
**Extract:** recurring file Read/Edit targets (the project's high-value files, so project references);
recurring Bash commands (build/test/deploy workflow, so a skills-style page); repeated tool-call
sequences (workflow patterns); failed calls (pain points, known rough edges); MCP calls (external
integrations). **Skip:** one-off config reads, noise output (summarize the error *class*, not the full
stack trace), and anything resembling secrets/tokens/credentials. Read the paired `local_<uuid>.json`
first for `cwd`/`startedAt`/`title`. The audit log says *what happened*; the transcript says *why*, so
use them together when both exist for a session.

## Step H4: Cluster by topic, then distill

Don't create one page per conversation. Group extracted knowledge **by topic** across conversations
(one session about "auth + CI" becomes two topics; three sessions about "React perf" become one merged
topic). Each Claude project maps to a project dir in the vault: decode `-Users-…-my-Project` to
`myproject` and route project-specific knowledge under `projects/<name>/<discovered-subcategory>/`,
global knowledge to the best-fitting existing top-level folder (categories discovered from disk, per
Step 3). Create/update the project overview at `projects/<name>/<name>.md`, **named after the project,
never `_project.md`** (Obsidian uses the filename as the graph node label).

Write each page per the Page-Writing Protocol (`wiki/references/page-protocol.md`). Two
history-specific points:

- **Distill the _knowledge_, not the conversation.** Not "On March 15 the user asked about X"; write
  the knowledge itself, with the conversation as source attribution.
- **Provenance depends on the source:** memory-file claims are mostly *extracted* (the user hand-wrote
  them); conversation distillation is mostly `^[inferred]` (you synthesize across many turns); use
  `^[ambiguous]` when the user changed their mind across sessions or user and assistant contradicted
  each other unresolved.

Then run Step 7 (manifest regen + journal) once at the end. Use a `CLAUDE_HISTORY_INGEST` log op-code,
e.g. `--log 'CLAUDE_HISTORY_INGEST projects=N conversations=M desktop_sessions=D audit_logs=A pages_updated=X pages_created=Y mode=append'`.

**Privacy:** on top of the `private_paths` + `visibility/` guards, conversation history has its own
hazards. Distill/synthesize rather than copy raw text; skip secrets/keys/tokens; ask the user before
including personal/sensitive content; be thoughtful about other people the conversations reference.

See `claude-data-format.md` for the full data-structure details.
