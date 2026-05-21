---
name: llm-wiki
description: >
  The foundational knowledge distillation pattern for building and maintaining an AI-powered Obsidian wiki.
  Based on Andrej Karpathy's LLM Wiki architecture. Use this skill whenever the user wants to understand the
  wiki pattern, set up a new knowledge base, or needs guidance on the three-layer architecture (raw sources →
  wiki → schema). Also use when discussing knowledge management strategy, wiki structure decisions, or how
  to organize distilled knowledge. This is the "theory" skill — other skills handle specific operations
  (ingesting, querying, linting).
---

# LLM Wiki — Knowledge Distillation Pattern

The wiki is a **compiled artifact**: knowledge distilled once and kept current, not re-derived on every query.

Based on Andrej Karpathy's LLM Wiki pattern — <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

## Three-Layer Architecture

### Layer 1: Raw Sources (immutable)

The user's original documents — articles, papers, notes, PDFs, conversation logs, bookmarks, **and images** (screenshots, whiteboard photos, diagrams). Never modified by the system. Located via `OBSIDIAN_SOURCES_DIR` in `.env`. Images are first-class sources for vision-capable models; non-vision models skip them and report which were skipped.

Think of raw sources as the "source code" — authoritative but hard to query directly.

### Layer 2: The Wiki (LLM-maintained)

A collection of interconnected Obsidian-compatible markdown files. This is the compiled knowledge — synthesized, cross-referenced, navigable. Each page has YAML frontmatter, Obsidian `[[wikilinks]]`, and clear provenance for its claims. Lives at `OBSIDIAN_VAULT_PATH`.

### Layer 3: The Schema (this skill + config)

The rules governing how the wiki is structured — categories, conventions, page templates, operational workflows. The schema tells the LLM *how* to maintain the wiki.

## Wiki Organization

Organize pages into folders that match your domain. Declare them in `OBSIDIAN_CATEGORIES` (comma-separated). Two patterns work well:

- **Domain folders** — folder names mirror the subjects of the notes (`AI/`, `Health/`, `Recipes/`, etc.). Natural for hand-authored personal wikis.
- **Karpathy taxonomy** — `concepts/`, `entities/`, `skills/`, `references/`, `synthesis/`, `journal/`. Natural for external-source distillation; less so for hand-authored notes.

Pick one and be consistent within a vault. Different vaults can use different schemas.

## Special Files

Every wiki has these at its root:

### `index.md`

A content-oriented catalog organized by folder. Each entry has a one-line summary and tags. Rebuild after every ingest.

```markdown
# Wiki Index

## AI
- [[ai/transformer-architecture]] — The dominant architecture for sequence modeling ( #ml #architecture)
- [[ai/attention-mechanism]] — Core building block of transformers ( #ml #fundamentals)
```

**Format rule:** add a space after the opening `(` before the tags.

- ❌ `description (#tag)` — breaks tag parsing
- ✅ `description ( #tag)` — proper spacing

### `log.md`

Append-only operations record. One line per operation:

```markdown
- [2024-03-15T10:30:00Z] INGEST source="papers/attention.pdf" pages_updated=12 pages_created=3
- [2024-03-15T11:00:00Z] QUERY query="How do transformers handle long sequences?" result_pages=4
- [2024-03-16T09:00:00Z] LINT issues_found=2 orphans=1 contradictions=1
```

The op-code list is open — invent new ones as needed.

### `.manifest.json`

Tracks every source file that has been ingested — path, timestamps, what wiki pages it produced. Backbone of the delta system. See `wiki-status` for the schema.

The manifest enables:

- **Delta computation** — what's new or modified since last ingest
- **Append mode** — only process the delta, not everything
- **Audit** — which source produced which wiki page
- **Staleness detection** — source changed but wiki page hasn't been updated

## Page Template

```markdown
---
title: Page Title
category: ai
tags: [ml, architecture]
summary: One or two sentences, ≤200 chars — what is this page about?
sources: [papers/attention.pdf]
created: 2024-03-15T10:30:00Z
updated: 2024-03-15T10:30:00Z
---

# Page Title

One-paragraph summary.

## Key Ideas

- A central claim, paraphrased from a source.
- A connection the source implies but doesn't state outright. ^[inferred]
- A figure two sources disagree on. ^[ambiguous]

Use [[wikilinks]] to connect to related pages.

## Sources

- [[references/attention-is-all-you-need]] — Original paper
```

Optional frontmatter fields (ingest skills may populate; hand-authored pages can omit):

- `aliases:` — alternate names this page should also resolve as.
- `lifecycle:` — `draft` / `reviewed` / `archived`. Default `reviewed` for human-authored. Only ingest skills set `draft`. Transitions are manual.
- `base_confidence:` — `[0.0, 1.0]` quality estimate. Default `0.85` for human-authored. Ingest skills compute their own.

## Provenance Markers

Every claim on a wiki page has one of three provenance states. Mark them inline so a reader (or another skill) can tell signal from synthesis.

| State | Marker | Meaning |
|---|---|---|
| **Extracted** | *(no marker — default)* | Paraphrase of what a source says. |
| **Inferred** | `^[inferred]` suffix | LLM-synthesized claim — a connection or generalization. |
| **Ambiguous** | `^[ambiguous]` suffix | Sources disagree, or the source is unclear. |

```markdown
- Transformers parallelize across positions, unlike RNNs.
- This is why they scale better on modern hardware. ^[inferred]
- GPT-4 was trained on roughly 13T tokens. ^[ambiguous]
```

Why this syntax: `^[...]` is footnote-adjacent in Obsidian — renders cleanly, never collides with `[[wikilinks]]`. Default = extracted means existing pages without markers stay valid.

## Retrieval Primitives

Reading the vault is the dominant cost of every read-side skill. Use the cheapest primitive that answers the question — escalate only when insufficient.

| Need | Primitive | Cost |
|---|---|---|
| Does a page exist? title/category/tags? | Read `index.md`; `Grep` frontmatter blocks | **Cheapest** |
| 1–2 sentence preview of a page | Read its `summary:` frontmatter field | **Cheap** |
| A specific claim or section inside a page | `Grep -A <n> -B <n> "<term>" <file>` | **Medium** |
| Whole-page content | `Read <file>` | **Expensive** — last resort |
| Relationships across pages | `Grep "\[\[.*?\]\]"` across vault, or walk wikilinks | Case-by-case |

The rule: if `summary:` fields answer it, don't read page bodies. If a grepped section with `-A 10 -B 2` gives the claim, don't read the whole page. A 500-line page opened to read 15 lines is 485 lines of wasted tokens.

This is how the framework scales to large vaults without a database. Skills consuming this table: `wiki-query`, `cross-linker`, `wiki-lint`, `wiki-status`.

## Core Principles

1. **Compile, don't retrieve.** The wiki is pre-compiled knowledge. When you ingest a source, update every relevant page — don't just create a summary of the source.
2. **Compound over time.** Each ingest should make the wiki smarter, not just bigger. Merge new information into existing pages, resolve contradictions, strengthen cross-references.
3. **Provenance matters.** Every claim should trace to a source. When updating a page, note which source prompted the update.
4. **Mark inferences.** Default = extracted. Mark synthesized claims `^[inferred]`, contested claims `^[ambiguous]`. A wiki that hides its guessing rots silently.
5. **Human curates, LLM maintains.** Human decides what sources to add and what questions to ask. LLM handles the bookkeeping.
6. **Obsidian is the IDE.** The user browses in Obsidian. Everything must be valid Obsidian markdown with working wikilinks.

## Link Format

Controlled by `OBSIDIAN_LINK_FORMAT` from the resolved config (default: `wikilink`).

| Setting | Syntax | Example |
|---|---|---|
| `wikilink` *(default)* | `[[path/to/page]]` or `[[path/to/page\|display]]` | `[[concepts/foo]]` |
| `markdown` | `[display](relative/path.md)` | `[foo](../concepts/foo.md)` |

For markdown mode: compute the path from the current file's directory to the target `.md` file using `..` to climb up; always include the `.md` extension. The `[[path|display]]` wikilink form maps to `[display](relative/path.md)` in markdown mode.

The setting affects only newly written or updated links — existing content is never auto-migrated. Run `cross-linker` or `wiki-lint` to convert old links if needed.

## Config Resolution Protocol

**All skills must resolve config using this algorithm — don't hard-code `.env` or `~/.obsidian-wiki/config` directly.** This is how single-vault, multi-vault, and project-local setups coexist.

1. **Walk up from CWD** — look for a `.env` containing `OBSIDIAN_VAULT_PATH`, stopping at the first match (up to `$HOME`).
2. **Global config** — if no local `.env`, read `~/.obsidian-wiki/config`.
3. **Prompt setup** — if neither exists, tell the user: "No config found. Run `wiki-setup` to initialize."

```bash
find_config() {
  dir="$PWD"
  while [[ "$dir" != "$HOME" && "$dir" != "/" ]]; do
    [[ -f "$dir/.env" ]] && grep -q "OBSIDIAN_VAULT_PATH" "$dir/.env" && { echo "$dir/.env"; return; }
    dir="$(dirname "$dir")"
  done
  [[ -f "$HOME/.obsidian-wiki/config" ]] && { echo "$HOME/.obsidian-wiki/config"; return; }
  echo ""
}
```

### Vault-scoped state

Skills writing runtime state must scope it to the resolved vault, not a global path:

```bash
VAULT_ID=$(echo "$OBSIDIAN_VAULT_PATH" | md5sum 2>/dev/null | cut -c1-8)
STATE_DIR="$HOME/.obsidian-wiki/state/$VAULT_ID"
```

### Standard "Before You Start" block

Every skill's setup section should read:

> **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md`. Walk up from CWD for `.env`, fall back to `~/.obsidian-wiki/config`, else prompt setup. This gives `OBSIDIAN_VAULT_PATH` and any tool-specific path overrides.

## Environment Variables

Only `OBSIDIAN_VAULT_PATH` is required.

- `OBSIDIAN_VAULT_PATH` — Where the wiki lives **(required)**
- `OBSIDIAN_SOURCES_DIR` — Where raw source documents are
- `OBSIDIAN_CATEGORIES` — Comma-separated top-level folder/category names
- `OBSIDIAN_LINK_FORMAT` — `wikilink` (default) or `markdown`
- `CLAUDE_HISTORY_PATH` — Where Claude session data lives (for `claude-history-ingest`)

No API keys needed — the agent running these skills already has LLM access built in.

## Modes of Operation

Three ingest modes:

| Mode | When | What happens |
|---|---|---|
| **Append** | Small delta, incremental updates | Compute delta via manifest, ingest only new/modified sources |
| **Rebuild** | Major drift, fresh start needed | Archive current wiki to `_archives/`, clear, reprocess all sources |
| **Restore** | Need to go back | Bring back a previous archive |

Use `wiki-status` to see the delta and get a recommendation. Use `wiki-rebuild` for archive/rebuild/restore.

## Reference

Companion skills (`../`):

- **wiki-setup** — Initialize a new vault
- **wiki-status** — Audit what's ingested, compute delta, recommend append vs rebuild
- **wiki-rebuild** — Archive, rebuild from scratch, or restore
- **wiki-ingest** — Distill source documents into wiki pages
- **wiki-query** — Answer questions against the wiki
- **wiki-lint** — Audit and maintain wiki health
- **wiki-update** — Push knowledge from any working project into the wiki
- **wiki-capture** — Save the current conversation as a wiki page
- **wiki-research** — Multi-round web research, auto-file results
- **wiki-synthesize** — Cross-page synthesis pages
- **wiki-switch** — Manage multiple vault profiles
- **cross-linker** — Discover and insert missing wikilinks
- **claude-history-ingest** — Mine `~/.claude` session data into the wiki

Maintenance scripts (`../../scripts/`):

- `regen-manifest.py` — rebuild `.manifest.json` from filesystem
- `kebab-rename.py` — mass kebab-case rename + wikilink rewrite

What was trimmed from this skill (and how to restore): see `../../docs/trimming-log.md`.
