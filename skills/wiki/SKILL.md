---
name: wiki
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

The user's original documents — articles, papers, notes, PDFs, conversation logs, bookmarks, **and images** (screenshots, whiteboard photos, diagrams). Never modified by the system. Live at `<vault>/_sources/` by default. Images are first-class sources for vision-capable models; non-vision models skip them and report which were skipped.

Think of raw sources as the "source code" — authoritative but hard to query directly.

### Layer 2: The Wiki (LLM-maintained)

A collection of interconnected Obsidian-compatible markdown files. This is the compiled knowledge — synthesized, cross-referenced, navigable. Each page has YAML frontmatter, Obsidian `[[wikilinks]]`, and clear provenance for its claims. The vault is the directory containing `.manifest.json` — that file is the canonical marker.

### Layer 3: The Schema (this skill + config)

The rules governing how the wiki is structured — categories, conventions, page templates, operational workflows. The schema tells the LLM *how* to maintain the wiki.

## Wiki Organization

Organize pages into folders that match your domain. **Categories are discovered from disk**, not declared in config: any top-level directory not prefixed with `_` or `.` is a category. `_foo/` is system state (`_sources/`, `_archives/`), `.foo/` is tool config (`.obsidian/`, `.claude/`). Everything else is content.

Two patterns work well:

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

### URL sources

`sources:` entries are vault-relative paths or full URLs (`http(s)://` is the discriminator), mixed freely. For any URL that is **evidence** for a non-trivial claim, store a local snapshot under `_sources/web/<slug>.md` *and* the URL. See **`references/vault-mechanics.md` → URL Sources** for the snapshot conventions and manifest keys.

### Folder naming convention

Top-level folders (categories) and subfolders both use **kebab-case-lowercase**, matching the filename convention. Examples: `ai/`, `git/`, `mcp/`, `science-fair/`, `projects/`.

Why: consistent with kebab-case filenames, URL-safe, no shift-key ambiguity, plays nicely with Obsidian wikilink resolution (case-insensitive on Windows but case-sensitive on Linux/WSL — lowercase removes the footgun).

Exceptions that may keep TitleCase: none enforced, but if you prefer prettier sidebar display in Obsidian and only ever access the vault on Windows/macOS (case-insensitive), TitleCase top-level folders work too. Pick one style per vault — mixing is what breaks.

**To add** a category: `mkdir <name>` at the vault root — skills discover it on next read, no config edit needed. **To rename, remove, or hide** one (including the `kebab-rename.py` lockstep rename + wikilink-rewrite + manifest re-key), see **`references/vault-mechanics.md` → Renaming a Category**.

Optional frontmatter fields (ingest skills may populate; hand-authored pages can omit):

- `aliases:` — alternate names this page should also resolve as.
- `lifecycle:` — `draft` / `reviewed` / `verified` / `disputed` / `archived`. Default `reviewed` for human-authored; only ingest skills set `draft`. A qualitative, human-curated state — transitions are manual.

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

This is how the framework scales to large vaults without a database. Skills consuming this table: `wiki-query`, `wiki-link`, `wiki-lint`, `wiki-status`.

## Core Principles

1. **Compile, don't retrieve.** The wiki is pre-compiled knowledge. When you ingest a source, update every relevant page — don't just create a summary of the source.
2. **Compound over time.** Each ingest should make the wiki smarter, not just bigger. Merge new information into existing pages, resolve contradictions, strengthen cross-references.
3. **Provenance matters.** Every claim should trace to a source. When updating a page, note which source prompted the update.
4. **Mark inferences.** Default = extracted. Mark synthesized claims `^[inferred]`, contested claims `^[ambiguous]`. A wiki that hides its guessing rots silently.
5. **Human curates, LLM maintains.** Human decides what sources to add and what questions to ask. LLM handles the bookkeeping.
6. **Obsidian is the IDE.** The user browses in Obsidian. Everything must be valid Obsidian markdown with working wikilinks.

## Link Format

The wiki uses Obsidian **wikilinks** with full vault-relative paths:

| Syntax | Example |
|---|---|
| `[[path/to/page]]` or `[[path/to/page\|display]]` | `[[concepts/foo]]` |

Always use vault-relative paths, not bare basenames — some basenames aren't globally unique. Run `wiki-link` or `wiki-lint` to find and fix broken or missing links.

## Config Resolution Protocol

The vault is self-describing — **zero configuration**, no config file or per-vault settings. The vault is the directory containing `.manifest.json`; every other path derives from it (`_sources/`, `_archives/`, …). Categories are discovered from disk (any top-level dir not prefixed `_` or `.`). No API keys — the agent already has LLM access.

**Resolve the vault** by walking up from CWD for `.manifest.json` (stop at `$HOME` or `/`); fall back to `VAULT` in `~/.obsidian-wiki/config`; if neither, tell the user to run `wiki-setup`. The maintenance scripts do this walk-up themselves. Standard skill setup line:

> **Resolve vault** — walk up from CWD for `.manifest.json` (per the Config Resolution Protocol in `wiki/SKILL.md`). All paths derive from the vault root.

**Relocatability invariant:** `cp -r <vault> <new-location> && cd <new-location>` must produce a fully functional wiki with zero edits — so no absolute paths inside the vault, relative manifest keys only. Runtime state written *outside* the vault is scoped by a hash of the vault path.

The `find_vault` shell function, the derived-paths table, vault-scoped-state hashing, and the full relocatability rules live in **`references/vault-mechanics.md`**.

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
- **wiki-link** — Discover and insert missing wikilinks
- **wiki-claude-history** — Mine `~/.claude` session data into the wiki

Maintenance scripts (`../../scripts/`, symlinked into vaults as `.claude/wiki-scripts/`):

- `wiki-lint.py` — deterministic health checks (orphans, broken links, frontmatter, index, stale, lifecycle, provenance ratios). Used by `wiki-lint`.
- `wiki-graph.py` — wikilink-graph analysis (hubs, tag cohesion, orphans, bridges, cross-category edges, delta). Used by `wiki-status` insights.
- `regen-manifest.py` — rebuild `.manifest.json` from filesystem
- `kebab-rename.py` — mass kebab-case rename + wikilink rewrite
- `validate-frontmatter.py` — verify every page's YAML frontmatter parses

Reference (`references/`):

- `karpathy-pattern.md` — the original LLM Wiki pattern explained
- `vault-mechanics.md` — config resolution, relocatability, URL snapshots, category renames (read on demand, not every op)
