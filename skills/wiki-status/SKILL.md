---
name: wiki-status
description: >
  Show the current state of the wiki — what's been ingested, what's pending, and the delta between sources
  and wiki content. Use this skill when the user asks "what's the status", "how much is ingested",
  "what's left to process", "show me the delta", "what changed since last ingest", "wiki dashboard",
  or wants an overview of their knowledge base health and completeness. Also use before deciding whether
  to append or rebuild. Includes an insights mode triggered by "wiki insights", "what's central",
  "show me the hubs", "central pages", "what's connected", "wiki structure" — analyzes the shape of
  the wiki itself to surface top hubs, cross-domain bridges, and orphan-adjacent pages.
---

# Wiki Status — Audit & Delta

You are computing the current state of the wiki: what's been ingested, what's new since last ingest, and what the delta looks like. This helps the user decide whether to append (ingest the delta) or rebuild (archive and reprocess everything).

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.
2. Read `.manifest.json` at the vault root — this is the ingest tracking ledger

## The Manifest

The manifest lives at `$OBSIDIAN_VAULT_PATH/.manifest.json`. It tracks every source file that has been ingested.

**If the manifest is missing but the vault has content** (e.g. a pre-existing Obsidian vault being adopted into the wiki pattern, or one where a bulk filesystem operation happened outside the skills), run `../wiki-scripts/regen-manifest.py` from the vault root. It scans the filesystem and rebuilds the manifest from scratch, registering existing pages as self-authored sources. Use `DRY_RUN=1` first to preview. If the manifest is missing AND the vault is empty, this is a fresh vault with nothing ingested — recommend `wiki-setup` instead.

```json
{
  "version": 1,
  "last_updated": "2026-04-06T10:30:00Z",
  "sources": {
    "/absolute/path/to/file.md": {
      "ingested_at": "2026-04-06T10:30:00Z",
      "size_bytes": 4523,
      "modified_at": "2026-04-05T08:00:00Z",
      "source_type": "document",
      "project": null,
      "pages_created": ["concepts/transformers.md"],
      "pages_updated": ["entities/vaswani.md"]
    },
    "~/.claude/projects/-Users-name-my-app/abc123.jsonl": {
      "ingested_at": "2026-04-06T11:00:00Z",
      "size_bytes": 128000,
      "modified_at": "2026-04-06T09:00:00Z",
      "source_type": "claude_conversation",
      "project": "my-app",
      "pages_created": ["entities/my-app.md"],
      "pages_updated": ["skills/react-debugging.md"]
    }
  },
  "projects": {
    "my-app": {
      "source_path": "~/.claude/projects/-Users-name-my-app",
      "vault_path": "projects/my-app",
      "last_ingested": "2026-04-06T11:00:00Z",
      "conversations_ingested": 5,
      "conversations_total": 8,
      "memory_files_ingested": 3
    }
  },
  "stats": {
    "total_sources_ingested": 42,
    "total_pages": 87,
    "total_projects": 6,
    "last_full_rebuild": null
  }
}
```

## Step 1: Scan Current Sources

Build an inventory of everything available to ingest right now:

### Documents (from `$OBSIDIAN_VAULT_PATH/_sources`)
```
Glob the sources dir for all text files
Record: path, size, modification time
```

### Claude History (from `$HOME/.claude/projects`)
```
Glob: ~/.claude/projects/*/          → project directories
Glob: ~/.claude/projects/*/*.jsonl   → conversation files
Glob: ~/.claude/projects/*/memory/*.md → memory files
Record: path, size, modification time, parent project
```

### Codex History (from `CODEX_HISTORY_PATH`)
```
Glob: ~/.codex/session_index.jsonl            → session inventory index
Glob: ~/.codex/sessions/**/rollout-*.jsonl    → session rollout transcripts
Glob: ~/.codex/history.jsonl                  → optional local history log
Glob: ~/.codex/archived_sessions/**/rollout-*.jsonl → archived rollouts (if user wants archive coverage)
Record: path, size, modification time, inferred project from cwd when available
```

### Any other sources the user has pointed at previously
Check the manifest for source paths outside the standard directories.

## Step 2: Compute the Delta

Compare current sources against the manifest. Classify each source file:

| Status | Meaning | Action needed |
|---|---|---|
| **New** | File exists on disk, not in manifest | Needs ingesting |
| **Modified** | File in manifest, hash differs from `content_hash` | Needs re-ingesting |
| **Touched** | File in manifest, mtime newer but hash unchanged | Skip — content identical, no re-ingest needed |
| **Unchanged** | File in manifest, mtime and hash both match | Nothing to do |
| **Deleted** | In manifest, but file no longer exists on disk | Note it — wiki pages may be stale |

When a manifest entry has no `content_hash` (older entry), fall back to mtime comparison only.

For Claude history specifically, also compute:
- New projects (directories in `~/.claude/projects/` not in manifest)
- New conversations within existing projects
- Updated memory files

For Codex history specifically, also compute:
- New rollout files under `sessions/**`
- Updated `session_index.jsonl` entries (session title/freshness changes)
- Archived rollout delta only when archive coverage is requested

## Step 3: Report the Status

**Visibility tally (before rendering the report):** Grep frontmatter across all vault `.md` pages for `visibility/internal` and `visibility/pii` tag values. Count:
- `public` = pages with `visibility/public` tag **or** no `visibility/` tag at all
- `internal` = pages with `visibility/internal` tag
- `pii` = pages with `visibility/pii` tag

Include this in the Overview section as `Page visibility: N public · M internal · K pii`. Skip the line if all pages are untagged (fully public vault).

Present a clear summary:

```markdown
# Wiki Status

## Overview
- **Total wiki pages:** 87 across 6 categories
- **Page visibility:** 72 public · 11 internal · 4 pii
- **Total sources ingested:** 42
- **Projects tracked:** 6
- **Last ingest:** 2026-04-06T11:00:00Z

## Delta (what's changed since last ingest)

### New sources (never ingested): 12
| Source | Type | Size |
|---|---|---|
| ~/Documents/research/new-paper.pdf | document | 2.1 MB |
| ~/.claude/projects/-Users-.../session-xyz.jsonl | claude_conversation | 340 KB |
| ~/.codex/sessions/2026/04/12/rollout-...jsonl | codex_rollout | 220 KB |
| ... | | |

### Modified sources (need re-ingesting): 3
| Source | Last ingested | Last modified | Delta |
|---|---|---|---|
| ~/notes/architecture.md | 2026-04-01 | 2026-04-05 | 4 days newer |
| ... | | | |

### New projects (not yet in wiki): 2
- **tractorex** (3 conversations, 2 memory files)
- **papertech** (1 conversation, 0 memory files)

### Deleted sources (ingested but gone): 0

## Summary
- **Ready to ingest:** 12 new + 3 modified = 15 sources
- **Up to date:** 27 sources unchanged
- **Recommendation:** Append (delta is small relative to total)
```

## Step 4: Recommend Action

Based on the delta, recommend one of:

| Situation | Recommendation |
|---|---|
| Delta is small (<20% of total) | **Append** — just ingest the new/modified sources |
| Delta is large (>50% of total) | **Rebuild** — archive and reprocess everything |
| Many deleted sources | **Lint first** — check for stale pages, then decide |
| First time / empty vault | **Full ingest** — process everything |
| User just wants to see status | **No action** — just report |

Tell the user:
- "You have X new sources and Y modified sources. I'd recommend [append/rebuild]."
- "Want me to [ingest the delta / rebuild from scratch / just look at a specific project]?"

## Insights Mode

Triggered when the user asks something like "wiki insights", "what's central in my wiki", "show me the hubs", "cross-domain bridges", "what pages are most important", or "wiki structure". This mode is *additive* — it doesn't replace the delta report, it analyzes the *shape* of the wiki itself.

Where the delta report tells the user what's pending, insights mode tells them what they've already built and where the interesting structure lives. Complements `wiki-lint` (which finds *problems*) by surfacing *interesting structure*.

### Step 1: Run the graph tool

```bash
uv run .claude/wiki-scripts/wiki-graph.py --format json
```

It builds the wikilink graph once and computes — deterministically, no LLM arithmetic — everything this mode reports:

- **Hubs** — top pages by incoming links; connector hubs (high in *and* out) vs sink hubs (high in, zero out → wiki-link candidates)
- **Tag cohesion** — for each tag on ≥ 5 pages, how tightly its pages interlink; `fragmented` (cohesion < 0.15) clusters are wiki-link targets
- **Orphans / orphan-adjacent** — isolated pages, and dead-ends linked from a hub
- **Bridges** — real articulation points (cut vertices): removing one partitions the graph. Structurally load-bearing, often more so than raw hub count suggests.
- **Cross-category edges** — links that cross category boundaries — the non-obvious, cross-domain connections
- **Graph delta** — new/removed pages and links since the last run, and pages that gained or lost all incoming links

The delta snapshot lives at `~/.obsidian-wiki/state/<vault-id>/graph-snapshot.json` — the script writes and reads it, so nothing is stored inside the vault (a copied vault simply starts a fresh snapshot). (No `uv`? Run it as `python3 .claude/wiki-scripts/wiki-graph.py` after `pip install pyyaml`.)

### Step 2: Render `_insights.md`

Turn the JSON into a readable report at the vault root. Overwrite freely — it's regenerable. The script gives you the structure; you add a plain-language *reason* to each highlighted item and draft the questions.

```markdown
# Wiki Insights — <TIMESTAMP>

## Anchor Pages (top hubs)
| Page | Incoming | Outgoing | Note |
|---|---|---|---|
| [[concepts/transformer-architecture]] | 23 | 8 | connector hub |
| [[entities/andrej-karpathy]] | 17 | 0 | sink hub — wiki-link candidate |

## Bridges (structural cut-points)
- [[concepts/exponential-growth]] — removing it isolates the #economics cluster from #ml

## Tag Cluster Cohesion
### Most cohesive (well-linked)
- **#ml** — 12 pages, cohesion 0.41
### Most fragmented (wiki-link targets)
- **#systems** — 7 pages, cohesion 0.06 ⚠️ run wiki-link on this tag

## Cross-Category Connections
- [[concepts/scaling-laws]] → [[entities/gordon-moore]] — links a concept to the person behind it

## Orphan-Adjacent (dead-ends near hubs)
- [[concepts/foo]] — linked from 3 hubs, 0 outbound links

## Graph Delta Since Last Run
- +3 new pages, +11 new wikilinks
- Newly connected: [[concepts/bar]], [[entities/baz]]
- Lost incoming links: [[references/old-paper]] (target may have been renamed)

## Questions Worth Asking
1. Resolve: What is the exact relationship between `scaling-laws` and `moore's-law`? (^[ambiguous] claim)
2. Explore: Why does `exponential-growth` bridge #ml and #economics?
3. Link: `references/foo.md` has no incoming links — what should reference it?
4. Audit: Should tag `#systems` be split? (cohesion 0.06, 7 pages)
```

For "Questions Worth Asking", grep the flagged pages for `^[ambiguous]` claims and combine them with the graph's bridges and orphans — prioritize ambiguous claims first, then bridges, then isolates.

After writing the file, append to `log.md`:
```
- [TIMESTAMP] STATUS_INSIGHTS hubs=H bridges=N fragmented=F delta="+N pages +M links"
```

### When to skip

- Vaults with fewer than 20 pages — not enough graph structure. Tell the user and skip.
- After a fresh `wiki-rebuild` — wait until at least one ingest has happened.

## Notes

- If the manifest doesn't exist, report everything as "new" and recommend a full ingest
- This skill only reads and reports — it doesn't modify anything (except writing `_insights.md` in insights mode, which is regenerable)
- The actual ingest work is done by the ingest skills (`wiki-ingest`, `wiki-claude-history`, `codex-history-ingest`, `data-ingest`)
- Those skills are responsible for updating the manifest after they finish
