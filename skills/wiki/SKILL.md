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

`sources:` is a YAML list of strings. Each entry is either a vault-relative path or a full URL (leading `http://` / `https://` is the discriminator). Mix freely:

```yaml
sources:
  - _sources/web/martinfowler-microservices-2014.md   # local snapshot
  - https://martinfowler.com/articles/microservices.html   # original URL
  - _sources/papers/attention-is-all-you-need.pdf   # file source
  - https://example.com/see-also   # URL-only, no snapshot
```

**Recommended:** snapshot + URL (two entries) for any URL that is **evidence** for a non-trivial claim. Snapshot first (what `wiki-lint` verifies), URL second (what a reader clicks).

**URL-only** (one entry) is acceptable only for ephemera — "see also" pointers whose removal would not weaken any claim on the page.

Snapshot conventions:

- Path: `_sources/web/<slug>.md`
- Slug: kebab-case, derived from `<domain>-<title-or-slug>-<year>`, e.g. `martinfowler-microservices-2014.md`, `instructables-carbon-quantum-dots-2019.md`
- Format: Markdown preferred (clean grep target). HTML alongside (`<slug>.html`) only when conversion loses important structure. PDFs unchanged.
- Manifest entry keyed by the snapshot path, with `source_type: "url"`, `source_url:`, `fetched_at:`, `content_hash:`.

`wiki-lint` flags URL-only `sources:` entries that 404 and downgrades dependent claims to `^[ambiguous]` until a snapshot is added.

### Folder naming convention

Top-level folders (categories) and subfolders both use **kebab-case-lowercase**, matching the filename convention. Examples: `ai/`, `git/`, `mcp/`, `science-fair/`, `team-meta/`.

Why: consistent with kebab-case filenames, URL-safe, no shift-key ambiguity, plays nicely with Obsidian wikilink resolution (case-insensitive on Windows but case-sensitive on Linux/WSL — lowercase removes the footgun).

Exceptions that may keep TitleCase: none enforced, but if you prefer prettier sidebar display in Obsidian and only ever access the vault on Windows/macOS (case-insensitive), TitleCase top-level folders work too. Pick one style per vault — mixing is what breaks.

**To rename a category:**

1. Run `.claude/wiki-scripts/kebab-rename.py` (or a folder-only variant) — it renames the folder, rewrites every wikilink that referenced the old path, and re-keys the manifest in lockstep. Use `DRY_RUN=1` first.
2. Update the section heading in `index.md`.
3. Append a `RECATEGORIZE` entry to `log.md`.

To **add** a category: `mkdir <name>` at the vault root. No config edit needed — skills discover it on next read. To **remove** a category: move its pages elsewhere first, then `rmdir`. To **hide a top-level directory from category discovery** (e.g. a scratch area you don't want ingest to write into), rename it with a `_` prefix.

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

The vault is self-describing — **no config file or per-vault settings are needed**. The vault is the directory containing `.manifest.json`; every other path derives from that location.

### Vault discovery

1. **Walk up from CWD** — look for `.manifest.json`, stopping at the first match (up to `$HOME` or `/`).
2. **Global config** — if no vault found and `~/.obsidian-wiki/config` exists, read `VAULT` from it.
3. **Prompt setup** — if neither, tell the user: "No vault found. Run `wiki-setup` to initialize."

```bash
find_vault() {
  dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    [[ -f "$dir/.manifest.json" ]] && { echo "$dir"; return; }
    [[ "$dir" == "$HOME" ]] && break
    dir="$(dirname "$dir")"
  done
  [[ -f "$HOME/.obsidian-wiki/config" ]] && grep -m1 '^VAULT=' "$HOME/.obsidian-wiki/config" | cut -d= -f2-
}
```

### Paths derived from the vault location

Everything derives from the vault root — there is no config file:

| Setting | Value |
|---|---|
| Vault root | directory containing `.manifest.json` |
| Sources dir | `$OBSIDIAN_VAULT_PATH/_sources` |
| Archives dir | `$OBSIDIAN_VAULT_PATH/_archives` |
| Link format | wikilinks (vault-relative) |
| Claude history | `$HOME/.claude/projects` if it exists |

Skills MUST infer every path from the vault location. A vault with no config of any kind is the only supported case — that's what keeps it relocatable (`cp -r <vault> /elsewhere && cd /elsewhere` must work with zero edits).

### Vault-scoped state

Skills writing runtime state outside the vault must scope it by vault location, not a global path:

```bash
VAULT_ID=$(echo "$VAULT" | md5sum 2>/dev/null | cut -c1-8)
STATE_DIR="$HOME/.obsidian-wiki/state/$VAULT_ID"
```

The vault path is the input to the hash — copying the vault elsewhere produces a new scope, which is the desired behavior (the new vault is a different instance).

### Standard "Before You Start" block

Every skill's setup section should read:

> **Resolve vault** — walk up from CWD for `.manifest.json` (per the Config Resolution Protocol in `wiki/SKILL.md`). All paths derive from the vault root.

## Relocatability Invariant

The vault is the unit of relocation. A vault must satisfy this invariant:

> **Copy-paste works.** `cp -r <vault> <new-location> && cd <new-location>` must produce a fully functional wiki without editing any file.

This rules out:

- Absolute paths inside the vault pointing back to itself
- Manifest entries keyed by absolute paths (relative paths only)
- Symlinks pointing to absolute paths inside the vault

The skills follow this. If you find a script that violates it, that's a bug.

## Configuration

There is none, by design. A vault works with **zero configuration** — no config file, no per-vault settings. The vault is the directory containing `.manifest.json`, and every path derives from it (see the Config Resolution Protocol above). Skills refer to the resolved vault root as `$OBSIDIAN_VAULT_PATH` in their examples; that's just the variable they set from `find_vault`, not a value read from the environment.

Categories are not declared anywhere; they are discovered from disk (any top-level dir not prefixed with `_` or `.`).

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
- **wiki-link** — Discover and insert missing wikilinks
- **wiki-claude-history** — Mine `~/.claude` session data into the wiki

Maintenance scripts (`../../scripts/`):

- `regen-manifest.py` — rebuild `.manifest.json` from filesystem
- `kebab-rename.py` — mass kebab-case rename + wikilink rewrite
- `validate-frontmatter.py` — verify every page's YAML frontmatter parses
